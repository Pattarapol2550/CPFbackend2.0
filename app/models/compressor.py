"""
app/models/compressor.py — ORM mapping for the compressors registry table.
"""

from sqlalchemy import Column, DateTime, String

from app.database import Base


class CompressorModel(Base):
    __tablename__ = "compressors"

    # เดียวกับ compressor_id ที่ใช้อ้างอิงใน compressor_data (ex. "COMP-01")
    id         = Column(String(20), primary_key=True)
    type       = Column(String(20), nullable=False)  # booster | high_stage | single
    created_at = Column(DateTime(timezone=True))
