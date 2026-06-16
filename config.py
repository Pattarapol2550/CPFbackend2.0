import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ── Database ───────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ── JWT ────────────────────────────────────────────────────
JWT_SECRET: str = os.getenv("JWT_SECRET", "")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET ไม่ได้ตั้งค่าใน .env — ห้ามรัน production โดยไม่มี secret")

JWT_ALGO    = "HS256"
TOKEN_TTL_H = 8

# ── CORS ───────────────────────────────────────────────────
ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# ── Email / OTP ────────────────────────────────────────────
RESEND_API_KEY      = os.getenv("RESEND_API_KEY", "")
OTP_EXPIRE_MINUTES  = int(os.getenv("OTP_EXPIRE_MINUTES", "10"))

# ── Thermodynamics ─────────────────────────────────────────
FLUID           = "Ammonia"
DEFAULT_VOLTAGE = 385.0
DEFAULT_PF      = 0.86  # power factor

# ── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
