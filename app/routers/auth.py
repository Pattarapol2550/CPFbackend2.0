"""
app/routers/auth.py — Authentication + Profile + Admin endpoints
"""

import logging
import re
from datetime import datetime, timezone

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.core.limiter import limiter
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
from app.schemas.auth import (
    AdminCreateUserIn,
    ChangePasswordIn,
    GoogleCallbackIn,
    LoginIn,
    RegisterIn,
    UpdateProfileIn,
)

router = APIRouter()
audit  = logging.getLogger("audit")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_username(display_name: str, fallback: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.]", "_", display_name)[:32]
    if len(clean) < 3:
        clean = re.sub(r"[^a-zA-Z0-9_.]", "_", fallback.split("@")[0])[:32]
    return clean or "user___"


def _verify_google_id_token(token: str) -> dict:
    """Verify Google ID token signature and audience, then return claims."""
    try:
        return google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=GOOGLE_CLIENT_ID,
        )
    except Exception as exc:
        raise HTTPException(401, detail="Google token ไม่ถูกต้องหรือหมดอายุ") from exc


async def _get_user_by_id(db: AsyncSession, user_id: int) -> UserModel:
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="ไม่พบ user")
    return user


async def _find_or_create_google_user(
    db: AsyncSession,
    email: str,
    google_id: str,
    name: str,
    client_ip: str,
) -> UserModel:
    # 1. หาด้วย google_id
    result = await db.execute(
        select(UserModel).where(UserModel.google_id == google_id)
    )
    user = result.scalar_one_or_none()

    # 2. หาด้วย email
    if user is None:
        result = await db.execute(
            select(UserModel).where(UserModel.email == email)
        )
        user = result.scalar_one_or_none()
        if user:
            user.google_id     = google_id
            user.auth_provider = "google"
            await db.commit()
            await db.refresh(user)

    # 3. สร้างใหม่ — role=user เสมอ
    if user is None:
        username = _safe_username(name, email)
        dup = await db.execute(
            select(UserModel).where(UserModel.username_lower == username.lower())
        )
        if dup.scalar_one_or_none():
            username = (username[:28] + "_" + google_id[-3:])[:32]

        user = UserModel(
            username=username,
            username_lower=username.lower(),
            email=email,
            phone=None,
            password_hash="",
            auth_provider="google",
            google_id=google_id,
            role="user",
            created_at=datetime.now(timezone.utc),
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        audit.info("GOOGLE_REGISTER ip=%s email=%s role=user", client_ip, email)

    return user


async def _create_user(db: AsyncSession, body: RegisterIn, role: str) -> UserModel:
    uname_lower = body.username.lower()
    email_lower = body.email.lower()
    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) | (UserModel.email == email_lower)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว")
    user = UserModel(
        username=body.username,
        username_lower=uname_lower,
        email=email_lower,
        phone=getattr(body, "phone", None),
        password_hash=hash_password(body.password),
        auth_provider="local",
        role=role,
        created_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return user


# ── POST /api/auth/register ───────────────────────────────────────────────────

@router.post("/api/auth/register", status_code=201, tags=["auth"])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    await _create_user(db, body, role="user")
    return {"ok": True, "message": "สมัครสมาชิกสำเร็จ"}


# ── POST /api/auth/login ──────────────────────────────────────────────────────

@router.post("/api/auth/login", tags=["auth"])
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    identifier = body.identifier.strip().lower()
    client_ip  = request.client.host

    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == identifier) | (UserModel.email == identifier)
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        bcrypt.checkpw(b"dummy", bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=12)))
        audit.warning("LOGIN_FAIL ip=%s identifier=%s reason=not_found", client_ip, identifier)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    if not user.is_active:
        audit.warning("LOGIN_BLOCKED ip=%s user=%s", client_ip, user.username)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="บัญชีนี้ถูกระงับการใช้งาน")

    if getattr(user, "auth_provider", "local") == "google" and not user.password_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="บัญชีนี้ใช้ Google Login กรุณาคลิก 'Sign in with Google'",
        )

    if not verify_password(body.password, user.password_hash):
        audit.warning("LOGIN_FAIL ip=%s user=%s reason=wrong_password", client_ip, user.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    audit.info("LOGIN_OK ip=%s user=%s role=%s", client_ip, user.username, user.role)
    token = create_token(user.id, user.username, user.role)
    set_auth_cookie(response, token)
    return {"user": {"username": user.username, "role": user.role}}


# ── POST /api/auth/google/callback ───────────────────────────────────────────

@router.post("/api/auth/google/callback", tags=["auth"])
@limiter.limit("10/minute")
async def google_callback(
    request: Request,
    body: GoogleCallbackIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, detail="Google Login ยังไม่เปิดใช้งาน")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          body.code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  body.redirect_uri,
                "grant_type":    "authorization_code",
            },
            timeout=10,
        )

    if token_res.status_code != 200:
        audit.warning("GOOGLE_TOKEN_FAIL ip=%s status=%s",
                      request.client.host, token_res.status_code)
        raise HTTPException(401, detail="Google authentication ล้มเหลว กรุณาลองใหม่")

    id_token_str = token_res.json().get("id_token", "")
    if not id_token_str:
        raise HTTPException(401, detail="Google ไม่ส่ง token กลับมา")

    info = _verify_google_id_token(id_token_str)

    email     = info.get("email", "").lower()
    google_id = info.get("sub", "")
    name      = info.get("name", "")

    if not email or not google_id:
        raise HTTPException(401, detail="Google token ไม่มีข้อมูล email")

    user = await _find_or_create_google_user(
        db, email, google_id, name, request.client.host
    )

    if not user.is_active:
        raise HTTPException(403, detail="บัญชีนี้ถูกระงับการใช้งาน")

    audit.info("GOOGLE_LOGIN_OK ip=%s user=%s role=%s",
               request.client.host, user.username, user.role)
    token = create_token(user.id, user.username, user.role)
    set_auth_cookie(response, token)
    return {"user": {"username": user.username, "role": user.role}}


# ── POST /api/auth/logout ─────────────────────────────────────────────────────

@router.post("/api/auth/logout", tags=["auth"])
async def logout(response: Response):
    clear_auth_cookie(response)
    return {"ok": True}


# ── GET /api/auth/me ──────────────────────────────────────────────────────────

@router.get("/api/auth/me", tags=["auth"])
async def get_me(current: dict = Depends(require_user)):
    return {"username": current["username"], "role": current.get("role", "user")}


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/api/auth/profile", tags=["profile"])
async def get_profile(
    current: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, int(current["sub"]))
    return {
        "id":            user.id,
        "username":      user.username,
        "email":         user.email,
        "phone":         user.phone,
        "role":          user.role,
        "auth_provider": getattr(user, "auth_provider", "local"),
        "created_at":    user.created_at.isoformat() if user.created_at else None,
    }


@router.patch("/api/auth/profile", tags=["profile"])
async def update_profile(
    body: UpdateProfileIn,
    response: Response,
    current: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, int(current["sub"]))

    if body.username is not None and body.username != user.username:
        dup = await db.execute(
            select(UserModel).where(
                UserModel.username_lower == body.username.lower(),
                UserModel.id != user.id,
            )
        )
        if dup.scalar_one_or_none():
            raise HTTPException(409, detail="ชื่อผู้ใช้นี้ถูกใช้งานแล้ว")
        user.username       = body.username
        user.username_lower = body.username.lower()

    if body.phone is not None:
        user.phone = body.phone

    await db.commit()
    await db.refresh(user)

    # ออก token ใหม่ทันที — username ใหม่อยู่ใน token เลย
    token = create_token(user.id, user.username, user.role)
    set_auth_cookie(response, token)

    return {"ok": True, "message": "อัพเดทโปรไฟล์สำเร็จ", "username": user.username}


@router.patch("/api/auth/change-password", tags=["profile"])
async def change_password(
    body: ChangePasswordIn,
    current: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_by_id(db, int(current["sub"]))

    if getattr(user, "auth_provider", "local") == "google":
        raise HTTPException(400, detail="บัญชี Google ไม่สามารถเปลี่ยนรหัสผ่านได้")

    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, detail="รหัสผ่านปัจจุบันไม่ถูกต้อง")

    user.password_hash = hash_password(body.new_password)
    await db.commit()
    audit.info("PASSWORD_CHANGE user=%s", user.username)
    return {"ok": True, "message": "เปลี่ยนรหัสผ่านสำเร็จ"}


# ── Admin ─────────────────────────────────────────────────────────────────────

@router.post("/api/auth/admin/create-user", status_code=201, tags=["admin"])
async def admin_create_user(
    body: AdminCreateUserIn,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _create_user(db, body, role=body.role)
    return {"ok": True, "message": f"สร้าง user '{body.username}' (role: {body.role}) สำเร็จ"}


@router.get("/api/auth/admin/users", tags=["admin"])
async def admin_list_users(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserModel).order_by(UserModel.created_at.desc()).limit(500)
    )
    return [
        {
            "id":            u.id,
            "username":      u.username,
            "email":         u.email,
            "phone":         u.phone,
            "role":          u.role,
            "is_active":     u.is_active,
            "auth_provider": getattr(u, "auth_provider", "local"),
            "created_at":    u.created_at.isoformat() if u.created_at else None,
        }
        for u in result.scalars().all()
    ]


@router.patch("/api/auth/admin/users/{user_id}/active", tags=["admin"])
async def admin_toggle_active(
    user_id: int,
    current_admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if int(current_admin["sub"]) == user_id:
        raise HTTPException(400, detail="ไม่สามารถปิด account ของตัวเองได้")
    user = await _get_user_by_id(db, user_id)
    user.is_active = not user.is_active
    await db.commit()
    state = "ACTIVATED" if user.is_active else "DEACTIVATED"
    audit.info("USER_%s admin=%s target=%s", state, current_admin.get("username"), user.username)
    return {"ok": True, "username": user.username, "is_active": user.is_active}


@router.delete("/api/auth/admin/users/{user_id}", tags=["admin"])
async def admin_delete_user(
    user_id: int,
    current_admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if int(current_admin["sub"]) == user_id:
        raise HTTPException(400, detail="ไม่สามารถลบ account ของตัวเองได้")
    user = await _get_user_by_id(db, user_id)
    if getattr(user,"role",None) =="admin":
        raise HTTPException(status_code=403,detail="ไม่สามารถลบผู้ดูแลได้")
    await db.delete(user)
    await db.commit()
    audit.info("USER_DELETE admin=%s target=%s", current_admin.get("username"), user.username)
    return {"ok": True, "message": f"ลบ user '{user.username}' สำเร็จ"}