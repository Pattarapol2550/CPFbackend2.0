"""
app/models/user.py
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String


from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base


class UserModel(Base):
    __tablename__ = "users"

    id             = Column(Integer,              primary_key=True, autoincrement=True)
    username       = Column(String(32),           unique=True,  nullable=False)
    username_lower = Column(String(32),           unique=True,  nullable=False)
    email          = Column(String(255),          unique=True,  nullable=False)
    phone          = Column(String(20),           nullable=True)
    password_hash  = Column(String(255),          nullable=False, default="")
    role           = Column(String(20),           nullable=False, default="user")
    created_at     = Column(DateTime(timezone=True))
    is_active      = Column(Boolean,              nullable=False, default=True)

    # Google OAuth
    google_id      = Column(String(128),          unique=True, nullable=True)
    # ── Google OAuth ──────────────────────────────────────────────────────────
    # google_id: "sub" จาก Google ID token — unique ต่อ Google account
    google_id      = Column(String(128),          unique=True,  nullable=True)
    # auth_provider: "local" = email+password, "google" = Google OAuth
    auth_provider  = Column(String(16),           nullable=False, default="local")