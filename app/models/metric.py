"""
ORM mapping for the `compressor_data` table.

Stores sensor snapshots and diagnosis JSON per compressor reading.
"""

from sqlalchemy import Column, DateTime, Index, Integer, JSON, String

from app.database import Base


class MetricModel(Base):
    """One compressor sensor reading with computed diagnosis."""

    __tablename__ = "compressor_data"

    # =========================================================
    # Columns
    # =========================================================
    id = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True))
    inputs_snapshot = Column(JSON)
    diagnosis = Column(JSON)

    # Composite index covers the main query pattern:
    # WHERE compressor_id = ? AND timestamp BETWEEN ? AND ? ORDER BY timestamp DESC
    __table_args__ = (
        Index("ix_comp_ts", "compressor_id", "timestamp"),
    )
