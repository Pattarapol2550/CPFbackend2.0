"""
app/routers/metrics.py — Metrics CRUD endpoints.

FIX: เพิ่ม Query(ge=1, le=10_000) บน limit parameter
     เดิม: limit: int = 2000  ← ใส่ ?limit=9999999 ได้ → server อาจช้าหรือ OOM
     แก้:  Query(default=2000, ge=1, le=10_000) ← จำกัดสูงสุด 10,000 records
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.constants import TZ_TH
from app.core.security import require_user
from app.database import get_db
from app.models.metric import MetricModel
from app.schemas.metrics import CompressorDataInput
from app.services.diagnostics import diagnose_compressor

router = APIRouter()


def _serialize_detail_row(row: MetricModel, tz_th) -> dict:
    """Build flat detail dict for one MetricModel row."""
    inp     = row.inputs_snapshot or {}
    diag    = row.diagnosis       or {}
    enth    = diag.get("enthalpy", {})
    systems = diag.get("systems",  {})
    alarms  = diag.get("alarms",   [])
    return {
        "id":            row.id,
        "compressor_id": row.compressor_id,
        "timestamp":     row.timestamp.astimezone(tz_th).isoformat() if row.timestamp else None,
        "input": {
            "sp_kg":                inp.get("sp_kg"),
            "dp_kg":                inp.get("dp_kg"),
            "st_c":                 inp.get("st_c"),
            "dt_c":                 inp.get("dt_c"),
            "liquid_temp_c":        inp.get("liquid_temp_c"),
            "current_amp":          inp.get("current_amp"),
            "evaporator_room_temp_c": inp.get("evaporator_room_temp_c"),
            "condenser_temp_c":     inp.get("condenser_temp_c"),
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
            "q_l_kgkg":    enth.get("q_l_kgkg"),
            "w_comp_kgkg": enth.get("w_comp_kgkg"),
        },
        "status": {
            "sensor":      systems.get("sensor",    {}).get("status"),
            "sensor_text": systems.get("sensor",    {}).get("text"),
            "condenser":   systems.get("condenser", {}).get("status"),
        },
        "alarms": [
            {"severity": a.get("severity"), "title": a.get("title"), "message": a.get("message")}
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
    record = MetricModel(
        compressor_id=payload.compressor_id,
        timestamp=record_time,
       inputs_snapshot=payload.model_dump(
        mode="json",
        exclude={"timestamp", "compressor_id"}
    ),
        diagnosis=diag,
    )
    db.add(record)
    await db.commit()
    return {"status": "Success", "analysis": diag}


# ── GET /api/metrics/{compressor_id} ─────────────────────────────────────────

@router.get("/api/metrics/{compressor_id}", tags=["metrics"])
async def get_dashboard_data(
    compressor_id: str,
    # FIX: เพิ่ม upper bound ป้องกัน ?limit=9999999
    limit: int = Query(default=2000, ge=1, le=10_000,
                       description="จำนวน records สูงสุด 10,000"),
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
    return [
        {
            "_id":             str(row.id),
            "compressor_id":   row.compressor_id,
            "timestamp":       row.timestamp.astimezone(TZ_TH).isoformat() if row.timestamp else None,
            "inputs_snapshot": row.inputs_snapshot,
            "diagnosis":       row.diagnosis,
        }
        for row in rows
    ]


# ── GET /api/metrics/{compressor_id}/detail ───────────────────────────────────

@router.get("/api/metrics/{compressor_id}/detail", tags=["metrics"])
async def get_detail_data(
    compressor_id: str,
    # FIX: เพิ่ม upper bound เช่นกัน
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