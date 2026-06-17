"""
app/schemas/auth.py — Auth request schemas

เพิ่ม GoogleCallbackIn สำหรับ authorization code flow
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
            len(v) < 8
            or len(v) > 128
            or not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError(
                "รหัสผ่านต้องยาวอย่างน้อย 8 ตัว มีตัวพิมพ์ใหญ่ พิมพ์เล็ก และตัวเลขอย่างละ 1 ตัว"
            )
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


# ── Google OAuth (Authorization Code Flow) ────────────────────────────────────

class GoogleCallbackIn(BaseModel):
    """รับ authorization code จาก Google redirect และ redirect_uri ที่ใช้"""
    code:         str   # ?code=xxx จาก Google
    redirect_uri: str   # ต้องตรงกับที่ส่งไป Google ตอนแรก