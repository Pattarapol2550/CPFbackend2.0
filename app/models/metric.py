"""
ORM mapping for the `compressor_data` table.

Stores sensor snapshots and diagnosis JSON per compressor reading.
"""

from sqlalchemy import Column, DateTime, Integer, JSON, String

from app.database import Base


class MetricModel(Base):
    """One compressor sensor reading with computed diagnosis."""

    __tablename__ = "compressor_data"

    # =========================================================
    # Columns
    # =========================================================
    id = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    inputs_snapshot = Column(JSON)
    diagnosis = Column(JSON)
