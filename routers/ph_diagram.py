"""
routers/ph_diagram.py
P-H Diagram endpoint
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import MetricModel
from services.auth_service import get_current_user
from services.thermo_service import build_saturation_dome, compute_cycle_points

router = APIRouter(prefix="/api/ph-diagram", tags=["ph-diagram"])
logger = logging.getLogger(__name__)

TZ_TH = timezone(timedelta(hours=7))


@router.get("/{compressor_id}")
async def get_ph_diagram(
    compressor_id: str,
    record_id:     Optional[str]      = None,
    timestamp:     Optional[datetime]  = None,
    _user:         dict               = Depends(get_current_user),
    db:            AsyncSession       = Depends(get_db),
):
    if record_id:
        try:
            result = await db.execute(
                select(MetricModel).where(
                    MetricModel.id            == int(record_id),
                    MetricModel.compressor_id == compressor_id,
                )
            )
            doc = result.scalar_one_or_none()
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="record_id ไม่ถูกต้อง")

    elif timestamp:
        ts     = timestamp.astimezone(TZ_TH)
        result = await db.execute(
            select(MetricModel).where(
                MetricModel.compressor_id == compressor_id,
                MetricModel.timestamp     >= ts - timedelta(seconds=1),
                MetricModel.timestamp     <= ts + timedelta(seconds=1),
            ).order_by(MetricModel.timestamp.desc()).limit(1)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบข้อมูลของ {compressor_id} ในช่วงเวลาที่เลือก",
            )
    else:
        result = await db.execute(
            select(MetricModel)
            .where(MetricModel.compressor_id == compressor_id)
            .order_by(MetricModel.timestamp.desc())
            .limit(1)
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"ไม่พบข้อมูลของ {compressor_id}")

    return {
        "compressor_id":   compressor_id,
        "timestamp":       doc.timestamp.astimezone(TZ_TH).isoformat() if doc.timestamp else None,
        "record_id":       str(doc.id),
        "saturation_dome": build_saturation_dome(),
        "cycle":           compute_cycle_points(doc.inputs_snapshot or {}),
    }
