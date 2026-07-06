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

    # ── Extra sensor fields (stored in inputs_snapshot, not used in thermo calc) ──
    glycol_temp: Optional[float] = None      # น้ำหล่อเย็น — ถ้าไม่มี condenser_temp_c จะใช้แทน
    glycol_level: Optional[float] = None     # ระดับ glycol
    oil_pressure: Optional[float] = None     # op — แรงดันน้ำมัน (kg/cm²)
    oil_temp: Optional[float] = None         # ot — อุณหภูมิน้ำมัน (°C)
    oil_filter: Optional[float] = None       # pressure drop กรองน้ำมัน
    oil_level: Optional[float] = None        # ระดับน้ำมัน
    slide_valve_pct: Optional[float] = None  # slide valve position (%)
    nh3_level: Optional[float] = None        # ระดับ NH₃
    nh3_pump: Optional[float] = None         # สถานะปั๊ม NH₃
    room_temp_1b: Optional[float] = None
    room_temp_1c: Optional[float] = None
    room_temp_2b: Optional[float] = None
    room_temp_2c: Optional[float] = None
    room_temp_3b: Optional[float] = None
    run_hour: Optional[float] = None         # ชั่วโมงเดินเครื่อง
