"""
Application configuration loaded from environment variables.

Imported by database, security, and app startup. Calls load_dotenv() once at import.
"""

import os

from dotenv import load_dotenv

# =========================================================
# LOAD ENV
# =========================================================
load_dotenv()

# =========================================================
# Database
# =========================================================
DATABASE_URL = os.getenv("DATABASE_URL")

# =========================================================
# JWT
# =========================================================
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production-use-strong-secret")
JWT_ALGO = "HS256"
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

# ── Google OAuth ──────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID",     "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

if not GOOGLE_CLIENT_ID:
    logger.warning("⚠️  GOOGLE_CLIENT_ID ไม่ได้ตั้งค่า — Google Login จะไม่ทำงาน")
if not GOOGLE_CLIENT_SECRET:
    logger.warning("⚠️  GOOGLE_CLIENT_SECRET ไม่ได้ตั้งค่า — Google Login จะไม่ทำงาน")
