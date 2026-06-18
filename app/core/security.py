"""
app/core/security.py — Password hashing, JWT, and FastAPI auth dependencies.

FIX: create_token รับ explicit params แทน dict{"_id": ...}
     ป้องกัน KeyError ถ้าใครเรียกโดยไม่รู้ว่าต้องส่ง "_id"
"""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status

from app.config import (
    AUTH_COOKIE_HTTPONLY,
    AUTH_COOKIE_MAX_AGE,
    AUTH_COOKIE_NAME,
    AUTH_COOKIE_PATH,
    AUTH_COOKIE_SAMESITE,
    AUTH_COOKIE_SECURE,
    JWT_ALGO,
    JWT_SECRET,
    TOKEN_TTL_H,
)

# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (12 rounds)."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Token ─────────────────────────────────────────────────────────────────────

# FIX: เปลี่ยนจาก create_token(user_doc: dict) ที่ต้องการ key "_id" (MongoDB legacy)
#      เป็น explicit params ที่ชัดเจน ป้องกัน KeyError ในอนาคต
def create_token(user_id: int, username: str, role: str) -> str:
    """Build a signed JWT from explicit user fields."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":      str(user_id),
        "username": username,
        "role":     role,
        "iat":      now,
        "exp":      now + timedelta(hours=TOKEN_TTL_H),
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


# ── Cookie helpers ────────────────────────────────────────────────────────────

def set_auth_cookie(response: Response, token: str) -> None:
    """Set the HttpOnly auth cookie on the response."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=AUTH_COOKIE_HTTPONLY,
        secure=AUTH_COOKIE_SECURE,
        samesite=AUTH_COOKIE_SAMESITE,
        path=AUTH_COOKIE_PATH,
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the auth cookie from the client."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        path=AUTH_COOKIE_PATH,
        httponly=AUTH_COOKIE_HTTPONLY,
        secure=AUTH_COOKIE_SECURE,
        samesite=AUTH_COOKIE_SAMESITE,
    )


# ── Dependencies ──────────────────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    """Extract and decode JWT from the auth cookie."""
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="กรุณา login ก่อน")
    return decode_token(token)


async def require_user(current: dict = Depends(get_current_user)) -> dict:
    """Require any authenticated user."""
    return current


async def require_admin(current: dict = Depends(get_current_user)) -> dict:
    """Require authenticated user with admin role."""
    if current.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="ต้องการสิทธิ์ admin")
    return current