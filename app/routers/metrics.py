"""
app/routers/metrics.py — Metrics CRUD endpoints.
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.constants import TZ_TH
from app.core.security import require_user
from app.database import get_db
from app.models.compressor import CompressorModel
from app.models.metric import MetricModel
from app.models.user import UserModel
from app.schemas.metrics import CompressorDataInput
from app.services.diagnostics import diagnose_compressor
from app.services.email import send_alarm_email

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Sensor field names (same order as schema) ─────────────────────────────────
SENSOR_FIELDS = [
    "sp_kg", "dp_kg", "st_c", "dt_c", "liquid_temp_c", "current_amp",
    "evaporator_room_temp_c", "condenser_temp_c", "compressor_type",
    "glycol_temp", "glycol_level", "oil_pressure", "oil_temp",
    "oil_filter", "oil_level", "slide_valve_pct",
    "nh3_level", "nh3_pump",
    "room_temp_1b", "room_temp_1c", "room_temp_2b", "room_temp_2c", "room_temp_3b",
    "run_hour",
]


def _payload_to_model_kwargs(payload: CompressorDataInput) -> dict:
    """Extract sensor fields from schema into MetricModel column kwargs."""
    return {f: getattr(payload, f, None) for f in SENSOR_FIELDS}


def _row_to_flat(row: MetricModel, tz_th) -> dict:
    """Serialize one MetricModel row to a flat dict for API response."""
    ts = row.timestamp.astimezone(tz_th).isoformat() if row.timestamp else None
    d = {
        "_id":          str(row.id),
        "compressor_id": row.compressor_id,
        "timestamp":    ts,
        "diagnosis":    row.diagnosis,
    }
    for f in SENSOR_FIELDS:
        d[f] = getattr(row, f, None)
    return d


def _serialize_detail_row(row: MetricModel, tz_th) -> dict:
    diag    = row.diagnosis or {}
    enth    = diag.get("enthalpy", {})
    systems = diag.get("systems", {})
    alarms  = diag.get("alarms", [])
    return {
        "id":            row.id,
        "compressor_id": row.compressor_id,
        "timestamp":     row.timestamp.astimezone(tz_th).isoformat() if row.timestamp else None,
        "input": {
            "sp_kg":                  row.sp_kg,
            "dp_kg":                  row.dp_kg,
            "st_c":                   row.st_c,
            "dt_c":                   row.dt_c,
            "liquid_temp_c":          row.liquid_temp_c,
            "current_amp":            row.current_amp,
            "evaporator_room_temp_c": row.evaporator_room_temp_c,
            "condenser_temp_c":       row.condenser_temp_c,
        },
        "performance": {
            "power_kw":       diag.get("power_kw"),
            "cop":            diag.get("cop"),
            "q_e_kw":         diag.get("q_e_kw"),
            "m_dot_kgh":      diag.get("m_dot_kgh"),
            "superheat_suc":  diag.get("superheat_suc"),
            "subcooling":     diag.get("subcooling"),
            "pressure_ratio": diag.get("pressure_ratio"),
        },
        "enthalpy": {
            "t_evap_c":    enth.get("t_evap_c"),
            "t_cond_c":    enth.get("t_cond_c"),
            "h1":          enth.get("h1"),
            "h2":          enth.get("h2"),
            "h2s":         enth.get("h2s"),
            "h3":          enth.get("h3"),
            "eta_is_pct":  enth.get("eta_is_pct"),
            "q_l_kjkg":    enth.get("q_l_kjkg"),
            "w_comp_kjkg": enth.get("w_comp_kjkg"),
        },
        "status": {
            "sensor":      systems.get("sensor",    {}).get("status"),
            "sensor_text": systems.get("sensor",    {}).get("text"),
            "condenser":   systems.get("condenser", {}).get("status"),
        },
        "alarms": [
            {
                "severity":       a.get("severity"),
                "title":          a.get("title"),
                "message":        a.get("message"),
                "recommendation": a.get("recommendation", []),
            }
            for a in alarms
        ],
        "alarm_count": len(alarms),
    }


# ── POST /api/metrics ─────────────────────────────────────────────────────────

@router.post("/api/metrics", tags=["metrics"])
async def save_data(
    payload: CompressorDataInput,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    diag = diagnose_compressor(payload)
    record_time = (
        payload.timestamp.astimezone(TZ_TH) if payload.timestamp else datetime.now(TZ_TH)
    )

    # สร้าง compressor ถ้ายังไม่มี (manual input อาจเพิ่ม compressor ใหม่)
    existing = await db.execute(
        select(CompressorModel).where(CompressorModel.id == payload.compressor_id)
    )
    if not existing.scalars().first():
        new_comp = CompressorModel(
            id=payload.compressor_id,
            type=payload.compressor_type or "single"
        )
        db.add(new_comp)
        await db.flush()  # flush to ensure ID is available before commit

    record = MetricModel(
        compressor_id=payload.compressor_id,
        timestamp=record_time,
        diagnosis=diag,
        **_payload_to_model_kwargs(payload),
    )
    db.add(record)
    await db.commit()

    try:
        alarms = diag.get("alarms", []) if isinstance(diag, dict) else []
        if any(a.get("severity") == "Critical" for a in alarms):
            admin_result = await db.execute(
                select(UserModel.email).where(
                    UserModel.role == "admin",
                    UserModel.is_active == True,
                )
            )
            admin_emails = [row[0] for row in admin_result.all() if row[0]]
            ts = record_time.strftime("%d %b %Y %H:%M:%S")
            loop = asyncio.get_event_loop()
            loop.create_task(
                send_alarm_email(payload.compressor_id, alarms, admin_emails, ts)
            )
    except Exception:
        logger.exception("alarm email task failed — ignoring")

    return {"status": "Success", "analysis": diag}


# ── POST /api/metrics/bulk ────────────────────────────────────────────────────

@router.post("/api/metrics/bulk", tags=["metrics"])
async def bulk_import(
    payload: List[CompressorDataInput],
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload:
        return {"status": "Success", "imported": 0, "failed": 0}

    # สร้าง compressor ใหม่สำหรับ ID ที่ยังไม่มีอยู่
    comp_ids = set(item.compressor_id for item in payload)
    existing_result = await db.execute(
        select(CompressorModel.id).where(CompressorModel.id.in_(list(comp_ids)))
    )
    existing_ids = {row[0] for row in existing_result.all()}
    missing_ids = comp_ids - existing_ids

    for comp_id in missing_ids:
        # หาประเภทคอมเพรสเซอร์จาก payload
        comp_type = next((item.compressor_type for item in payload if item.compressor_id == comp_id), "single")
        new_comp = CompressorModel(id=comp_id, type=comp_type or "single")
        db.add(new_comp)
    if missing_ids:
        await db.flush()

    records, failed = [], 0
    critical_by_comp = {}
    for item in payload:
        try:
            diag = diagnose_compressor(item)
            record_time = item.timestamp.astimezone(TZ_TH) if item.timestamp else datetime.now(TZ_TH)
            records.append(MetricModel(
                compressor_id=item.compressor_id,
                timestamp=record_time,
                diagnosis=diag,
                **_payload_to_model_kwargs(item),
            ))
            alarms = diag.get("alarms", []) if isinstance(diag, dict) else []
            if any(a.get("severity") == "Critical" for a in alarms):
                # เก็บ record ล่าสุดต่อ compressor ไว้ยิงอีเมลทีเดียวหลัง commit
                if (item.compressor_id not in critical_by_comp
                        or record_time > critical_by_comp[item.compressor_id][1]):
                    critical_by_comp[item.compressor_id] = (alarms, record_time)
        except Exception:
            logger.warning("bulk_import: skipped one record due to error", exc_info=True)
            failed += 1

    if records:
        db.add_all(records)
        await db.commit()

    if critical_by_comp:
        try:
            admin_result = await db.execute(
                select(UserModel.email).where(
                    UserModel.role == "admin",
                    UserModel.is_active == True,
                )
            )
            admin_emails = [row[0] for row in admin_result.all() if row[0]]
            loop = asyncio.get_event_loop()
            for comp_id, (alarms, record_time) in critical_by_comp.items():
                ts = record_time.strftime("%d %b %Y %H:%M:%S")
                loop.create_task(
                    send_alarm_email(comp_id, alarms, admin_emails, ts)
                )
        except Exception:
            logger.exception("bulk_import: alarm email task failed — ignoring")

    return {"status": "Success", "imported": len(records), "failed": failed}


# ── GET /api/metrics/{compressor_id} ─────────────────────────────────────────

@router.get("/api/metrics/{compressor_id}", tags=["metrics"])
async def get_dashboard_data(
    compressor_id: str,
    limit: int = Query(default=2000, ge=1, le=10_000),
    start: Optional[datetime] = None,
    end:   Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(MetricModel).where(MetricModel.compressor_id == compressor_id)
    if start:
        query = query.where(MetricModel.timestamp >= start.astimezone(TZ_TH))
    if end:
        query = query.where(MetricModel.timestamp <= end.astimezone(TZ_TH))
    query = query.order_by(MetricModel.timestamp.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [_row_to_flat(row, TZ_TH) for row in rows]


# ── GET /api/metrics/{compressor_id}/detail ───────────────────────────────────

@router.get("/api/metrics/{compressor_id}/detail", tags=["metrics"])
async def get_detail_data(
    compressor_id: str,
    limit: int = Query(default=100, ge=1, le=5_000),
    start: Optional[datetime] = None,
    end:   Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(MetricModel).where(MetricModel.compressor_id == compressor_id)
    if start:
        query = query.where(MetricModel.timestamp >= start.astimezone(TZ_TH))
    if end:
        query = query.where(MetricModel.timestamp <= end.astimezone(TZ_TH))
    query = query.order_by(MetricModel.timestamp.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return {
        "compressor_id": compressor_id,
        "count":         len(rows),
        "data":          [_serialize_detail_row(r, TZ_TH) for r in rows],
    }
