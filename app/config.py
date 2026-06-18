"""
app/config.py

เอา ADMIN_EMAIL_DOMAINS ออก — ไม่มี auto-admin จาก domain อีกต่อไป
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")

# ── JWT ───────────────────────────────────────────────────────────────────────
JWT_SECRET  = os.getenv("JWT_SECRET", "change-me-in-production-use-strong-secret")
JWT_ALGO    = "HS256"
TOKEN_TTL_H = 8

# =========================================================
# CORS
# =========================================================
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS"
    ).split(",")
    if origin.strip()
]

# =========================================================
# Auth cookie
# =========================================================
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "access_token")
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "none")
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "true").lower() == "true"
AUTH_COOKIE_HTTPONLY = os.getenv("AUTH_COOKIE_HTTPONLY", "true").lower() == "true"
AUTH_COOKIE_PATH = os.getenv("AUTH_COOKIE_PATH", "/")
AUTH_COOKIE_MAX_AGE = int(os.getenv("AUTH_COOKIE_MAX_AGE", str(TOKEN_TTL_H * 3600)))
if JWT_SECRET == "change-me-in-production-use-strong-secret":
    logger.warning("⚠️  JWT_SECRET ยังเป็นค่า default — ควรเปลี่ยนก่อน deploy production")

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_raw    = os.getenv("CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in _cors_raw.split(",") if o.strip()]

# ── Auth cookie ───────────────────────────────────────────────────────────────
AUTH_COOKIE_NAME     = os.getenv("AUTH_COOKIE_NAME",     "access_token")
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "lax")
AUTH_COOKIE_SECURE   = os.getenv("AUTH_COOKIE_SECURE",   "false").lower() == "true"
AUTH_COOKIE_HTTPONLY = os.getenv("AUTH_COOKIE_HTTPONLY",  "true").lower() == "true"
AUTH_COOKIE_PATH     = os.getenv("AUTH_COOKIE_PATH",      "/")
AUTH_COOKIE_MAX_AGE  = int(os.getenv("AUTH_COOKIE_MAX_AGE", str(TOKEN_TTL_H * 3600)))

# ── Google OAuth ──────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID",     "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

if not GOOGLE_CLIENT_ID:
    logger.warning("⚠️  GOOGLE_CLIENT_ID ไม่ได้ตั้งค่า — Google Login จะไม่ทำงาน")
if not GOOGLE_CLIENT_SECRET:
    logger.warning("⚠️  GOOGLE_CLIENT_SECRET ไม่ได้ตั้งค่า — Google Login จะไม่ทำงาน")
    logger.warning("⚠️  GOOGLE_CLIENT_SECRET ไม่ได้ตั้งค่า — Google Login จะไม่ทำงาน")
