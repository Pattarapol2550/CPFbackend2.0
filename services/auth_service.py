import logging
import random
import string
from datetime import datetime, timezone, timedelta

import bcrypt
import jwt
import resend

from config import JWT_SECRET, JWT_ALGO, TOKEN_TTL_H, RESEND_API_KEY, OTP_EXPIRE_MINUTES
from fastapi import HTTPException, status, Cookie
from typing import Optional

resend.api_key = RESEND_API_KEY
logger = logging.getLogger(__name__)
def _setup_audit_logger() -> logging.Logger:
    log = logging.getLogger("audit")
    log.setLevel(logging.INFO)
    handler = logging.FileHandler("audit.log")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    return log
audit_logger = _setup_audit_logger()




# ── Password ───────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT ────────────────────────────────────────────────────

def create_token(user: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":      str(user["_id"]),
        "username": user["username"],
        "role":     user.get("role", "user"),
        "iat":      now,
        "exp":      now + timedelta(hours=TOKEN_TTL_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token หมดอายุ กรุณา login ใหม่")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token ไม่ถูกต้อง")


async def get_current_user(access_token: Optional[str] = Cookie(default=None)) -> dict:
    if access_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="กรุณา login ก่อน")
    return decode_token(access_token)


async def require_admin(current: dict = None) -> dict:
    if current is None:
        current = await get_current_user()
    if current.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="ต้องการสิทธิ์ admin")
    return current


# ── OTP ────────────────────────────────────────────────────

def generate_otp() -> str:
    return "".join(random.choices(string.digits, k=6))


async def send_otp_email(email: str, otp: str) -> None:
    try:
        resend.Emails.send({
            "from":    "SCADA System <noreply@yourdomain.com>",
            "to":      email,
            "subject": "รหัส OTP ยืนยันอีเมล",
            "html": f"""
                <h2>ยืนยันอีเมลของคุณ</h2>
                <p>รหัส OTP ของคุณคือ:</p>
                <h1 style="letter-spacing:8px;font-size:36px">{otp}</h1>
                <p>รหัสนี้จะหมดอายุใน {OTP_EXPIRE_MINUTES} นาที</p>
            """,
        })
    except Exception as e:
        logger.error("ส่งเมล OTP ไม่สำเร็จ: %s", e, exc_info=True)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="ส่งเมลไม่สำเร็จ")
