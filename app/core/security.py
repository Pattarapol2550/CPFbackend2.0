"""
Password hashing, JWT creation/validation, and FastAPI auth dependencies.

Imported by auth router and any route requiring require_user / require_admin.
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import JWT_ALGO, JWT_SECRET, TOKEN_TTL_H

# =========================================================
# Bearer scheme
# =========================================================
bearer = HTTPBearer(auto_error=False)

# =========================================================
# Password
# =========================================================
def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain password matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# =========================================================
# Token
# =========================================================
def create_token(user_doc: dict) -> str:
    """Build a signed JWT for the given user document (_id, username, role)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_doc["_id"]),
        "username": user_doc["username"],
        "role": user_doc.get("role", "user"),
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_TTL_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def decode_token(token: str) -> dict:
    """Decode and validate JWT; raises HTTP 401 on expiry or invalid token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token หมดอายุ กรุณา login ใหม่")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token ไม่ถูกต้อง")


# =========================================================
# Dependencies
# =========================================================
async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    """Extract and decode Bearer token from Authorization header."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="กรุณา login ก่อน")
    return decode_token(creds.credentials)

async def require_admin(current: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role."""
    if current.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="ต้องการสิทธิ์ admin")
    return current

async def require_user(current: dict = Depends(get_current_user)) -> dict:
    """Require any authenticated user."""
    return current
