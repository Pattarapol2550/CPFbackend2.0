"""
P-H diagram endpoint: saturation dome + cycle points for a stored reading.

Requires authenticated user. Looks up MetricModel by record_id, timestamp, or latest.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.constants import TZ_TH
from app.core.security import require_user
from app.database import get_db
from app.models.metric import MetricModel
from app.services.ph_diagram import build_saturation_dome, compute_cycle_points

router = APIRouter()


# =========================================================
# GET /api/ph-diagram/{compressor_id}
# =========================================================
@router.get("/api/ph-diagram/{compressor_id}", tags=["ph-diagram"])
async def get_ph_diagram(
    compressor_id: str,
    record_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if record_id:
        try:
            result = await db.execute(
                select(MetricModel).where(
                    MetricModel.id == int(record_id),
                    MetricModel.compressor_id == compressor_id,
                )
            )
            doc = result.scalar_one_or_none()
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="record_id ไม่ถูกต้อง")
    elif timestamp:
        ts = timestamp.astimezone(TZ_TH)
        result = await db.execute(
            select(MetricModel)
            .where(
                MetricModel.compressor_id == compressor_id,
                MetricModel.timestamp >= ts - timedelta(seconds=1),
                MetricModel.timestamp <= ts + timedelta(seconds=1),
            )
            .order_by(MetricModel.timestamp.desc())
            .limit(1)
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
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"ไม่พบข้อมูลของ {compressor_id}"
        )

    inputs = doc.inputs_snapshot or {}
    cycle = compute_cycle_points(inputs)
    dome = build_saturation_dome()
    ts_str = doc.timestamp.astimezone(TZ_TH).isoformat() if doc.timestamp else None

    return {
        "compressor_id": compressor_id,
        "timestamp": ts_str,
        "record_id": str(doc.id),
        "saturation_dome": dome,
        "cycle": cycle,
    }
