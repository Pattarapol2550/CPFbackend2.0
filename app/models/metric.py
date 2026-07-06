"""
ORM mapping for the `compressor_data` table.

Stores sensor readings as individual columns and diagnosis as JSON.
"""

from sqlalchemy import Column, DateTime, Float, Index, Integer, JSON, String

from app.database import Base


class MetricModel(Base):
    __tablename__ = "compressor_data"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(String(100), nullable=False)
    timestamp     = Column(DateTime(timezone=True))

    # ── Core sensor inputs ────────────────────────────────────────────────────
    sp_kg                  = Column(Float)
    dp_kg                  = Column(Float)
    st_c                   = Column(Float)
    dt_c                   = Column(Float)
    liquid_temp_c          = Column(Float)
    current_amp            = Column(Float)
    evaporator_room_temp_c = Column(Float)
    condenser_temp_c       = Column(Float)
    compressor_type        = Column(String(20))

    # ── Extra sensor fields ───────────────────────────────────────────────────
    glycol_temp     = Column(Float)
    glycol_level    = Column(Float)
    oil_pressure    = Column(Float)
    oil_temp        = Column(Float)
    oil_filter      = Column(Float)
    oil_level       = Column(Float)
    slide_valve_pct = Column(Float)
    nh3_level       = Column(Float)
    nh3_pump        = Column(Float)
    room_temp_1b    = Column(Float)
    room_temp_1c    = Column(Float)
    room_temp_2b    = Column(Float)
    room_temp_2c    = Column(Float)
    room_temp_3b    = Column(Float)
    run_hour        = Column(Float)

    # ── Computed thermodynamic diagnosis (JSON) ───────────────────────────────
    diagnosis = Column(JSON)

    __table_args__ = (
        Index("ix_comp_ts", "compressor_id", "timestamp"),
    )
