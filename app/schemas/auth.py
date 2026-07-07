"""
app/schemas/auth.py — Auth request/response schemas.
"""

import re

from pydantic import BaseModel, EmailStr, field_validator

from app.core.constants import RE_PHONE_TH, RE_USERNAME


class RegisterIn(BaseModel):
    username: str
    email: EmailStr
    password: str
    phone: str

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str) -> str:
        if not RE_USERNAME.match(v.strip()):
            raise ValueError("ชื่อผู้ใช้ต้องยาว 3-32 ตัว ใช้ได้เฉพาะ a-z, 0-9, _ และ .")
        return v.strip()

    @field_validator("password")
    @classmethod
    def check_password(cls, v: str) -> str:
        if (
            len(v) < 8 or len(v) > 128
            or not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัว มีพิมพ์ใหญ่ พิมพ์เล็ก และตัวเลข")
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
    password: str


class AdminCreateUserIn(RegisterIn):
    role: str = "user"

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("role ต้องเป็น 'user' หรือ 'admin'")
        return v


# ── Google OAuth ──────────────────────────────────────────────────────────────

class GoogleCallbackIn(BaseModel):
    """รับ authorization code จาก Google redirect และ redirect_uri ที่ใช้"""
    code:         str
    redirect_uri: str


# ── Profile / Settings ────────────────────────────────────────────────────────

class UpdateProfileIn(BaseModel):
    """แก้ไขชื่อผู้ใช้ เบอร์โทร และ avatar"""
    username: str | None = None
    phone:    str | None = None
    avatar:   str | None = None  # base64 JPEG หรือ None เพื่อลบ

    @field_validator("avatar")
    @classmethod
    def check_avatar(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.startswith("data:image/"):
            raise ValueError("avatar ต้องเป็น data URL ของรูป (data:image/...)")
        if len(v) > 500_000:
            raise ValueError("ขนาดรูปใหญ่เกินไป (สูงสุด ~350 KB)")
        return v

    @field_validator("username")
    @classmethod
    def check_username(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not RE_USERNAME.match(v.strip()):
            raise ValueError("ชื่อผู้ใช้ต้องยาว 3-32 ตัว ใช้ได้เฉพาะ a-z, 0-9, _ และ .")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = re.sub(r"[-\s]", "", v)
        if not RE_PHONE_TH.match(v):
            raise ValueError("เบอร์โทรศัพท์ไม่ถูกต้อง (เช่น 0812345678)")
        return v


# ── Compressor registry (admin) ───────────────────────────────────────────────

COMPRESSOR_TYPES = ("booster", "high_stage", "single")


class CompressorIn(BaseModel):
    """สร้างคอมเพรสเซอร์ใหม่"""
    id:   str
    type: str

    @field_validator("id")
    @classmethod
    def check_id(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9_-]{2,20}$", v):
            raise ValueError("รหัสคอมเพรสเซอร์ต้องยาว 2-20 ตัว ใช้ได้เฉพาะ A-Z, 0-9, _ และ -")
        return v

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in COMPRESSOR_TYPES:
            raise ValueError(f"type ต้องเป็นหนึ่งใน {COMPRESSOR_TYPES}")
        return v


class CompressorUpdateIn(BaseModel):
    """แก้ไขรูปแบบคอมเพรสเซอร์"""
    type: str

    @field_validator("type")
    @classmethod
    def check_type(cls, v: str) -> str:
        if v not in COMPRESSOR_TYPES:
            raise ValueError(f"type ต้องเป็นหนึ่งใน {COMPRESSOR_TYPES}")
        return v


class ChangePasswordIn(BaseModel):
    """เปลี่ยนรหัสผ่าน"""
    current_password: str
    new_password:     str

    @field_validator("new_password")
    @classmethod
    def check_new_password(cls, v: str) -> str:
        if (
            len(v) < 8 or len(v) > 128
            or not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัว มีพิมพ์ใหญ่ พิมพ์เล็ก และตัวเลข")
        return v