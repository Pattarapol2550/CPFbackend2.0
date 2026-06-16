"""
routers/auth.py
ทุก endpoint ที่เกี่ยวกับ authentication / user management
"""
import re
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Cookie
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from database import get_db
from models import UserModel, OTPModel
from services.auth_service import (
    hash_password, verify_password,
    create_token, get_current_user, require_admin,
    generate_otp, send_otp_email, audit_logger,
)
from config import TOKEN_TTL_H, OTP_EXPIRE_MINUTES

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)

RE_USERNAME = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")
RE_PHONE_TH = re.compile(r"^0\d{8,9}$")


# ── Schemas ────────────────────────────────────────────────

class RegisterIn(BaseModel):
    username: str
    email:    EmailStr
    password: str
    phone:    str

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        if not RE_USERNAME.match(v.strip()):
            raise ValueError("ชื่อผู้ใช้ต้องยาว 3-32 ตัว ใช้ได้เฉพาะ a-z, 0-9, _ และ .")
        return v.strip()

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if (len(v) < 8 or len(v) > 128
                or not re.search(r"[A-Z]", v)
                or not re.search(r"[a-z]", v)
                or not re.search(r"\d", v)):
            raise ValueError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัว มีตัวพิมพ์ใหญ่ พิมพ์เล็ก และตัวเลขอย่างละ 1 ตัว")
        return v

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str) -> str:
        v = re.sub(r"[-\s]", "", v)
        if not RE_PHONE_TH.match(v):
            raise ValueError("เบอร์โทรศัพท์ไม่ถูกต้อง (เช่น 0812345678)")
        return v


class LoginIn(BaseModel):
    identifier: str
    password:   str


class AdminCreateUserIn(RegisterIn):
    role: str = "user"

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("role ต้องเป็น 'user' หรือ 'admin'")
        return v


class VerifyOTPIn(BaseModel):
    email: EmailStr
    code:  str


class ResendOTPIn(BaseModel):
    email: EmailStr


# ── Endpoints ──────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    uname_lower = body.username.lower()
    email_lower = body.email.lower()

    existing = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) |
            (UserModel.email == email_lower)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว")

    now  = datetime.now(timezone.utc)
    user = UserModel(
        username=body.username, username_lower=uname_lower,
        email=email_lower, phone=body.phone,
        password_hash=hash_password(body.password),
        role="user", created_at=now, is_active="false",
    )
    db.add(user)

    otp_code = generate_otp()
    db.add(OTPModel(
        email=email_lower, code=otp_code,
        expires_at=now + timedelta(minutes=OTP_EXPIRE_MINUTES),
        used="false",
    ))
    await db.commit()
    await send_otp_email(email_lower, otp_code)

    return {"ok": True, "message": "สมัครสมาชิกสำเร็จ กรุณาตรวจสอบอีเมลเพื่อยืนยัน OTP"}


@router.post("/verify-otp")
async def verify_otp(body: VerifyOTPIn, db: AsyncSession = Depends(get_db)):
    email_lower = body.email.lower()
    now = datetime.now(timezone.utc)

    otp_result = await db.execute(
        select(OTPModel).where(
            OTPModel.email      == email_lower,
            OTPModel.code       == body.code,
            OTPModel.used       == "false",
            OTPModel.expires_at > now,
        ).order_by(OTPModel.expires_at.desc()).limit(1)
    )
    otp = otp_result.scalar_one_or_none()
    if otp is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="OTP ไม่ถูกต้องหรือหมดอายุแล้ว")

    otp.used = "true"

    user_result = await db.execute(select(UserModel).where(UserModel.email == email_lower))
    user = user_result.scalar_one_or_none()
    if user:
        user.is_active = "true"

    await db.commit()
    audit_logger.info("OTP_VERIFIED email=%s", email_lower)
    return {"ok": True, "message": "ยืนยันอีเมลสำเร็จ กรุณา login"}


@router.post("/resend-otp")
async def resend_otp(request: Request, body: ResendOTPIn, db: AsyncSession = Depends(get_db)):
    email_lower = body.email.lower()

    user_result = await db.execute(select(UserModel).where(UserModel.email == email_lower))
    user = user_result.scalar_one_or_none()

    # ไม่บอกว่าเมลมีอยู่หรือไม่ — ป้องกัน user enumeration
    if user is None or user.is_active == "true":
        return {"ok": True, "message": "หากอีเมลนี้มีในระบบ จะได้รับ OTP ใหม่"}

    now      = datetime.now(timezone.utc)
    otp_code = generate_otp()
    db.add(OTPModel(
        email=email_lower, code=otp_code,
        expires_at=now + timedelta(minutes=OTP_EXPIRE_MINUTES),
        used="false",
    ))
    await db.commit()
    await send_otp_email(email_lower, otp_code)
    return {"ok": True, "message": "ส่ง OTP ใหม่แล้ว กรุณาตรวจสอบอีเมล"}


@router.post("/login")
async def login(request: Request, body: LoginIn, response: Response,
                db: AsyncSession = Depends(get_db)):
    identifier = body.identifier.strip().lower()
    client_ip  = request.client.host

    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == identifier) |
            (UserModel.email          == identifier)
        )
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        audit_logger.warning("LOGIN_FAIL ip=%s identifier=%s", client_ip, identifier)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    if user.is_active != "true":
        audit_logger.warning("LOGIN_BLOCKED ip=%s user=%s", client_ip, user.username)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="บัญชีนี้ถูกระงับการใช้งาน")

    audit_logger.info("LOGIN_OK ip=%s user=%s role=%s", client_ip, user.username, user.role)

    token = create_token({"_id": user.id, "username": user.username, "role": user.role})
    response.set_cookie(
        key="access_token", value=token,
        httponly=True, secure=True, samesite="lax",
        max_age=TOKEN_TTL_H * 3600, path="/",
    )
    return {"ok": True, "user": {"username": user.username, "role": user.role}}


@router.get("/me")
async def get_me(current: dict = Depends(get_current_user)):
    return {"username": current["username"], "role": current.get("role", "user")}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"ok": True}


@router.post("/admin/create-user", status_code=201)
async def admin_create_user(
    body: AdminCreateUserIn,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    uname_lower = body.username.lower()
    email_lower = body.email.lower()

    existing = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) |
            (UserModel.email          == email_lower)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว")

    now  = datetime.now(timezone.utc)
    user = UserModel(
        username=body.username, username_lower=uname_lower,
        email=email_lower, phone=body.phone,
        password_hash=hash_password(body.password),
        role=body.role, created_at=now, is_active="true",
    )
    db.add(user)
    await db.commit()
    return {"ok": True, "message": f"สร้าง user '{body.username}' (role: {body.role}) สำเร็จ"}


@router.get("/admin/users")
async def admin_list_users(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserModel).order_by(UserModel.created_at.desc()).limit(500)
    )
    return [
        {
            "id": u.id, "username": u.username, "email": u.email,
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in result.scalars().all()
    ]
