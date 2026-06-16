from sqlalchemy import Column, String, DateTime, JSON, Integer
from database import Base

class UserModel(Base):
    __tablename__ = "users"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    username       = Column(String(32),  unique=True, nullable=False)
    username_lower = Column(String(32),  unique=True, nullable=False)
    email          = Column(String(255), unique=True, nullable=False)
    phone          = Column(String(20))
    password_hash  = Column(String(255), nullable=False)
    role           = Column(String(20),  default="user")
    created_at     = Column(DateTime(timezone=True))
    is_active      = Column(String(5),   default="false")


class MetricModel(Base):
    __tablename__ = "compressor_data"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id   = Column(String(100), nullable=False, index=True)
    timestamp       = Column(DateTime(timezone=True), index=True)
    inputs_snapshot = Column(JSON)
    diagnosis       = Column(JSON)


class OTPModel(Base):
    __tablename__ = "otp_codes"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    email      = Column(String(255), nullable=False, index=True)
    code       = Column(String(6),   nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used       = Column(String(5),   default="false")
