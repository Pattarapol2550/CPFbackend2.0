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
