"""
routers/metrics.py
Endpoints สำหรับบันทึกและดึงข้อมูล compressor
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import MetricModel
from services.auth_service import get_current_user
from services.thermo_service import diagnose_compressor

router = APIRouter(prefix="/api/metrics", tags=["metrics"])
logger = logging.getLogger(__name__)

TZ_TH = timezone(timedelta(hours=7))


# ── Schema ─────────────────────────────────────────────────

class CompressorDataInput(BaseModel):
    compressor_id:          str
    timestamp:              Optional[datetime] = None
    sp_kg:                  float
    dp_kg:                  float
    st_c:                   Optional[float] = None
    dt_c:                   Optional[float] = None
    liquid_temp_c:          Optional[float] = None
    current_amp:            Optional[float] = None
    evaporator_room_temp_c: Optional[float] = None
    condenser_temp_c:       Optional[float] = None


# ── Endpoints ──────────────────────────────────────────────

@router.post("")
async def save_data(
    payload: CompressorDataInput,
    _user:   dict         = Depends(get_current_user),
    db:      AsyncSession = Depends(get_db),
):
    diag        = diagnose_compressor(payload)
    record_time = (
        payload.timestamp.astimezone(TZ_TH)
        if payload.timestamp
        else datetime.now(TZ_TH)
    )
    db.add(MetricModel(
        compressor_id=payload.compressor_id,
        timestamp=record_time,
        inputs_snapshot=payload.model_dump(),
        diagnosis=diag,
    ))
    await db.commit()
    return {"status": "Success", "analysis": diag}


@router.get("/{compressor_id}")
async def get_dashboard_data(
    compressor_id: str,
    limit:         int               = 2000,
    start:         Optional[datetime] = None,
    end:           Optional[datetime] = None,
    _user:         dict              = Depends(get_current_user),
    db:            AsyncSession      = Depends(get_db),
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
            "_id":            str(row.id),
            "compressor_id":  row.compressor_id,
            "timestamp":      row.timestamp.astimezone(TZ_TH).isoformat() if row.timestamp else None,
            "inputs_snapshot": row.inputs_snapshot,
            "diagnosis":      row.diagnosis,
        }
        for row in rows
    ]


@router.get("/{compressor_id}/detail")
async def get_detail_data(
    compressor_id: str,
    limit:         int               = 100,
    start:         Optional[datetime] = None,
    end:           Optional[datetime] = None,
    _user:         dict              = Depends(get_current_user),
    db:            AsyncSession      = Depends(get_db),
):
    query = select(MetricModel).where(MetricModel.compressor_id == compressor_id)
    if start:
        query = query.where(MetricModel.timestamp >= start.astimezone(TZ_TH))
    if end:
        query = query.where(MetricModel.timestamp <= end.astimezone(TZ_TH))
    query = query.order_by(MetricModel.timestamp.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()

    def _flatten(row: MetricModel) -> dict:
        inp    = row.inputs_snapshot or {}
        diag   = row.diagnosis or {}
        enth   = diag.get("enthalpy", {})
        sys    = diag.get("systems",  {})
        alarms = diag.get("alarms",   [])
        return {
            "id":            row.id,
            "compressor_id": row.compressor_id,
            "timestamp":     row.timestamp.astimezone(TZ_TH).isoformat() if row.timestamp else None,
            "input": {
                "sp_kg":                  inp.get("sp_kg"),
                "dp_kg":                  inp.get("dp_kg"),
                "st_c":                   inp.get("st_c"),
                "dt_c":                   inp.get("dt_c"),
                "liquid_temp_c":          inp.get("liquid_temp_c"),
                "current_amp":            inp.get("current_amp"),
                "evaporator_room_temp_c": inp.get("evaporator_room_temp_c"),
                "condenser_temp_c":       inp.get("condenser_temp_c"),
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
                "sensor":       sys.get("sensor",    {}).get("status"),
                "sensor_text":  sys.get("sensor",    {}).get("text"),
                "condenser":    sys.get("condenser", {}).get("status"),
            },
            "alarms": [
                {"severity": a.get("severity"), "title": a.get("title"), "message": a.get("message")}
                for a in alarms
            ],
            "alarm_count": len(alarms),
        }

    return {"compressor_id": compressor_id, "count": len(rows), "data": [_flatten(r) for r in rows]}
