"""
Metrics input schema for compressor sensor payloads.

Used by metrics router and diagnose_compressor service.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CompressorDataInput(BaseModel):
    """Sensor readings for one compressor snapshot."""

    compressor_id: str
    timestamp: Optional[datetime] = None
    sp_kg: float
    dp_kg: float
    st_c: Optional[float] = None
    dt_c: Optional[float] = None
    liquid_temp_c: Optional[float] = None
    current_amp: Optional[float] = None
    evaporator_room_temp_c: Optional[float] = None
    condenser_temp_c: Optional[float] = None
    # "booster" = LP→intermediate, "high_stage" = intermediate→HP, "single" = single-stage
    compressor_type: str = "single"
