"""
app/models/compressor.py — ORM mapping for the compressors registry table.
"""

import re

from sqlalchemy import Column, DateTime, String

from app.database import Base

_TRAILING_NUM_RE = re.compile(r"^(.*?)(\d+)$")


def normalize_compressor_id(raw: str) -> str:
    """Canonicalize a compressor id so 'comp-1', 'COMP-1' and 'COMP-01' all
    collapse to the same id (e.g. 'COMP-01'), preventing duplicate entries
    that differ only by case or numeric zero-padding."""
    value = (raw or "").strip().upper()
    m = _TRAILING_NUM_RE.match(value)
    if not m:
        return value
    prefix, digits = m.groups()
    return f"{prefix}{int(digits):02d}"


class CompressorModel(Base):
    __tablename__ = "compressors"

    # เดียวกับ compressor_id ที่ใช้อ้างอิงใน compressor_data (ex. "COMP-01")
    id         = Column(String(20), primary_key=True)
    type       = Column(String(20), nullable=False)  # booster | high_stage | single
    created_at = Column(DateTime(timezone=True))
