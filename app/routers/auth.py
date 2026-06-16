"""
Authentication endpoints: register, login, me, admin user management.

Uses UserModel via SQLAlchemy and security helpers for JWT.
"""

from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import (
    clear_auth_cookie,
    create_token,
    hash_password,
    require_admin,
    require_user,
    set_auth_cookie,
    verify_password,
)
from app.database import get_db
from app.models.user import UserModel
from app.schemas.auth import AdminCreateUserIn, LoginIn, RegisterIn

router = APIRouter()


# =========================================================
# Helpers
# =========================================================
async def _create_user(db: AsyncSession, body: RegisterIn, role: str) -> UserModel:
    """Insert a new user after duplicate check; shared by register and admin create."""
    uname_lower = body.username.lower()
    email_lower = body.email.lower()

    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) | (UserModel.email == email_lower)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว"
        )

    now = datetime.now(timezone.utc)
    user = UserModel(
        username=body.username,
        username_lower=uname_lower,
        email=email_lower,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role=role,
        created_at=now,
        is_active="true",
    )
    db.add(user)
    await db.commit()
    return user


# =========================================================
# POST /api/auth/register
# =========================================================
@router.post("/api/auth/register", status_code=201, tags=["auth"])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    await _create_user(db, body, role="user")
    return {"ok": True, "message": "สมัครสมาชิกสำเร็จ"}


# =========================================================
# POST /api/auth/login
# =========================================================
@router.post("/api/auth/login", tags=["auth"])
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    identifier = body.identifier.strip().lower()
    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == identifier) | (UserModel.email == identifier)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=12)))
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
        )

    if user.is_active != "true":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="บัญชีนี้ถูกระงับการใช้งาน")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
        )

    token = create_token({"_id": user.id, "username": user.username, "role": user.role})
    set_auth_cookie(response, token)
    return {"user": {"username": user.username, "role": user.role}}


# =========================================================
# POST /api/auth/logout
# =========================================================
@router.post("/api/auth/logout", tags=["auth"])
async def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


# =========================================================
# GET /api/auth/me
# =========================================================
@router.get("/api/auth/me", tags=["auth"])
async def get_me(current: dict = Depends(require_user)):
    return {"username": current["username"], "role": current.get("role", "user")}


# =========================================================
# Admin endpoints
# =========================================================
@router.post("/api/auth/admin/create-user", status_code=201, tags=["auth"])
async def admin_create_user(
    body: AdminCreateUserIn,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _create_user(db, body, role=body.role)
    return {"ok": True, "message": f"สร้าง user '{body.username}' (role: {body.role}) สำเร็จ"}

@router.get("/api/auth/admin/users", tags=["auth"])
async def admin_list_users(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserModel).order_by(UserModel.created_at.desc()).limit(500))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]
