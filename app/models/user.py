"""
ORM mapping for the `users` table.

Used by auth router and security token creation.
"""

from sqlalchemy import Column, DateTime, Integer, String

from app.database import Base


class UserModel(Base):
    """Registered application user with bcrypt password hash."""

    __tablename__ = "users"

    # =========================================================
    # Columns
    # =========================================================
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(32), unique=True, nullable=False)
    username_lower = Column(String(32), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    phone = Column(String(20))
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user")
    created_at = Column(DateTime(timezone=True))
    is_active = Column(String(5), default="true")
