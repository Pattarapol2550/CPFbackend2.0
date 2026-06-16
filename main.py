import math
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Optional
import numpy as np
from dotenv import load_dotenv
import CoolProp.CoolProp as CP
from fastapi import FastAPI, HTTPException, status, Depends,Response,Request,Cookie
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, String, DateTime, JSON, Integer
from sqlalchemy.future import select
import bcrypt
from pydantic import BaseModel, EmailStr, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import secure
import logging
import jwt

# =========================================================
# LOAD ENV
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET ไม่ได้ตั้งค่าใน .env — ห้ามรัน production โดยไม่มี secret")
JWT_ALGO     = "HS256"
TOKEN_TTL_H  = 8

# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(title="Ammonia Diagnostics API v2")
CP.set_reference_state("Ammonia", "IIR")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

secure_headers = secure.Secure(
    csp=secure.ContentSecurityPolicy()
        .default_src("'self'")
        .script_src("'self'")
        .style_src("'self'", "'unsafe-inline'"),
    hsts=secure.StrictTransportSecurity().max_age(31536000).include_subdomains(),
    referrer=secure.ReferrerPolicy().no_referrer(),
    cache=secure.CacheControl().no_store(),
    xfo=secure.XFrameOptions().deny(),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

@app.middleware("http")
async def set_secure_headers(request: Request, call_next):
    response = await call_next(request)
    secure_headers.framework.fastapi(response)
    return response

# =========================================================
# DATABASE SETUP
# =========================================================

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class UserModel(Base):
    __tablename__ = "users"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    username       = Column(String(32), unique=True, nullable=False)
    username_lower = Column(String(32), unique=True, nullable=False)
    email          = Column(String(255), unique=True, nullable=False)
    phone          = Column(String(20))
    password_hash  = Column(String(255), nullable=False)
    role           = Column(String(20), default="user")
    created_at     = Column(DateTime(timezone=True))
    is_active      = Column(String(5), default="true")

class MetricModel(Base):
    __tablename__ = "compressor_data"
    id              = Column(Integer, primary_key=True, autoincrement=True)
    compressor_id   = Column(String(100), nullable=False, index=True)
    timestamp       = Column(DateTime(timezone=True), index=True)
    inputs_snapshot = Column(JSON)
    diagnosis       = Column(JSON)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

# =========================================================
# PASSWORD + JWT HELPERS
# =========================================================

bearer = HTTPBearer(auto_error=False)

RE_USERNAME = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")
RE_PHONE_TH = re.compile(r"^0\d{8,9}$")

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_token(user_doc: dict) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub":      str(user_doc["_id"]),
        "username": user_doc["username"],
        "role":     user_doc.get("role", "user"),
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

async def get_current_user(
    access_token: str | None = Cookie(default=None)
) -> dict:
    if access_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="กรุณา login ก่อน")
    return decode_token(access_token)

async def require_admin(current: dict = Depends(get_current_user)) -> dict:
    if current.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="ต้องการสิทธิ์ admin")
    return current

async def require_user(current: dict = Depends(get_current_user)) -> dict:
    return current

# =========================================================
# AUTH SCHEMAS
# =========================================================

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
    password: str

class AdminCreateUserIn(RegisterIn):
    role: str = "user"

    @field_validator("role")
    @classmethod
    def check_role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("role ต้องเป็น 'user' หรือ 'admin'")
        return v

# =========================================================
# AUTH ENDPOINTS
# =========================================================

@app.post("/api/auth/register", status_code=201, tags=["auth"])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    uname_lower = body.username.lower()
    email_lower = body.email.lower()

    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) |
            (UserModel.email == email_lower)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว")

    now = datetime.now(timezone.utc)
    user = UserModel(
        username=body.username,
        username_lower=uname_lower,
        email=email_lower,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role="user",
        created_at=now,
        is_active="true",
    )
    db.add(user)
    await db.commit()
    return {"ok": True, "message": "สมัครสมาชิกสำเร็จ"}


audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)

handler = logging.FileHandler("audit.log")
handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
audit_logger.addHandler(handler)

@app.post("/api/auth/login", tags=["auth"])
@limiter.limit("5/minute")
async def login(body: LoginIn, response: Response, db: AsyncSession = Depends(get_db)):
    identifier = body.identifier.strip().lower()
    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == identifier) |
            (UserModel.email == identifier)
        )
    )
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        # ✅ log failed attempt
        audit_logger.warning(f"LOGIN_FAIL ip={client_ip} identifier={identifier}")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    if user.is_active != "true":
        audit_logger.warning(f"LOGIN_BLOCKED ip={client_ip} user={user.username}")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="บัญชีนี้ถูกระงับการใช้งาน")

    # if not verify_password(body.password, user.password_hash):
    #     raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    
    audit_logger.info(f"LOGIN_OK ip={client_ip} user={user.username} role={user.role}")


    token = create_token({"_id": user.id, "username": user.username, "role": user.role})
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=TOKEN_TTL_H * 3600,
        path="/",
    )
    return {
        "ok": True,
        "user": {"username": user.username, "role": user.role}
    }

@app.get("/api/auth/me", tags=["auth"])
async def get_me(current: dict = Depends(require_user)):
    return {"username": current["username"], "role": current.get("role", "user")}

@app.post("/api/auth/admin/create-user", status_code=201, tags=["auth"])
async def admin_create_user(
    body: AdminCreateUserIn,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    uname_lower = body.username.lower()
    email_lower = body.email.lower()

    result = await db.execute(
        select(UserModel).where(
            (UserModel.username_lower == uname_lower) |
            (UserModel.email == email_lower)
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้หรืออีเมลนี้ถูกใช้งานแล้ว")

    now = datetime.now(timezone.utc)
    user = UserModel(
        username=body.username,
        username_lower=uname_lower,
        email=email_lower,
        phone=body.phone,
        password_hash=hash_password(body.password),
        role=body.role,
        created_at=now,
        is_active="true",
    )
    db.add(user)
    await db.commit()
    return {"ok": True, "message": f"สร้าง user '{body.username}' (role: {body.role}) สำเร็จ"}

    

@app.get("/api/auth/admin/users", tags=["auth"])
async def admin_list_users(
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(UserModel).order_by(UserModel.created_at.desc()).limit(500))
    users = result.scalars().all()
    return [
        {
            "id": u.id, "username": u.username, "email": u.email,
            "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]

@app.post("/api/auth/logout", tags=["auth"])
async def logout(response: Response):
    response.delete_cookie(key="access_token", path="/")
    return {"ok": True}
# =========================================================
# DATA MODEL
# =========================================================

class CompressorDataInput(BaseModel):
    compressor_id: str
    timestamp: Optional[datetime] = None
    sp_kg: float
    dp_kg: float
    st_c:  Optional[float] = None
    dt_c:  Optional[float] = None
    liquid_temp_c: Optional[float] = None
    current_amp: Optional[float] = None
    evaporator_room_temp_c: Optional[float] = None
    condenser_temp_c: Optional[float] = None

def safe_round(value, digit=2):
    if value is None:
        return "--"
    try:
        return round(value, digit)
    except:
        return "--"

# =========================================================
# DIAGNOSTIC (ไม่เปลี่ยน)
# =========================================================

def diagnose_compressor(data: CompressorDataInput):
    fluid = "Ammonia"
    voltage = 385.0
    power_factor = 0.86
    alarms = []
    result = {
        "q_e_kw": "--", "power_kw": "--", "cop": "--",
        "superheat_suc": "--", "subcooling": "--", "pressure_ratio": "--",
        "systems": {
            "sensor": {"status": "Unknown", "text": "--"},
            "condenser": {"status": "Unknown", "text": "--"}
        }
    }
    try:
        p_suc_pa = (data.sp_kg * 98066.5 + 101325) if data.sp_kg is not None else None
        p_dis_pa = (data.dp_kg * 98066.5 + 101325) if data.dp_kg is not None else None
        t_suc_k = (data.st_c + 273.15) if data.st_c is not None else None
        t_dis_k = (data.dt_c + 273.15) if data.dt_c is not None else None
        h1 = None; h2 = None; h2s = None; h3 = None
        sh_mode = "assumed"; dt_mode = "assumed"
        if p_suc_pa:
            if t_suc_k:
                h1 = CP.PropsSI('H','P',p_suc_pa,'T',t_suc_k,fluid)
                sh_mode = "measured"
            else:
                t_sat_suc_k = CP.PropsSI('T','P',p_suc_pa,'Q',1,fluid)
                t1_assume = t_sat_suc_k + 5.0
                h1 = CP.PropsSI('H','P',p_suc_pa,'T',t1_assume,fluid)
                t_suc_k = t1_assume
                sh_mode = "assumed_5K"
        if h1 is not None and p_dis_pa and t_suc_k and p_suc_pa:
            s1 = CP.PropsSI('S','P',p_suc_pa,'T',t_suc_k,fluid)
            h2s = CP.PropsSI('H','P',p_dis_pa,'S',s1,fluid)
        if p_dis_pa:
            if t_dis_k:
                h2 = CP.PropsSI('H','P',p_dis_pa,'T',t_dis_k,fluid)
                dt_mode = "measured"
            elif h2s is not None and h1 is not None:
                h2 = h1 + (h2s - h1) / 0.70
                dt_mode = "assumed_eta07"
        if p_dis_pa and data.liquid_temp_c is not None:
            h3 = CP.PropsSI('H','P',p_dis_pa,'T',data.liquid_temp_c+273.15,fluid)
        elif p_dis_pa:
            try:
                h3 = CP.PropsSI('H','P',p_dis_pa,'Q',0,fluid)
            except:
                h3 = None
        power_kw = None
        if data.current_amp is not None:
            power_kw = (math.sqrt(3) * voltage * data.current_amp * power_factor) / 1000
        cop = None; q_e_kw = None; m_dot = None
        if h1 is not None and h2 is not None and h3 is not None and (h2 - h1) != 0:
            cop = (h1 - h3) / (h2 - h1)
        if cop is not None and power_kw is not None and power_kw > 0:
            q_e_kw = power_kw * cop
            m_dot  = (q_e_kw * 1000) / (h1 - h3)
        if cop is not None and cop < 1.5:
            alarms.append({"severity": "Warning", "title": "Low COP", "message": "ประสิทธิภาพระบบต่ำ",
                           "possible_causes": ["โหลดสูงเกิน","Compressor efficiency ต่ำ","Condenser ทำงานไม่ดี"],
                           "recommendation": ["ตรวจ compressor","ตรวจ condenser","ตรวจโหลดระบบ"]})
        superheat = None
        if p_suc_pa and data.st_c is not None:
            t_sat_suc = CP.PropsSI('T','P',p_suc_pa,'Q',1,fluid) - 273.15
            superheat = data.st_c - t_sat_suc
        if superheat is not None:
            if superheat > 15:
                alarms.append({"severity": "Warning", "title": "High Superheat", "message": "Superheat สูงเกินปกติ",
                               "possible_causes": ["น้ำยาเข้า evaporator ไม่พอ","Expansion valve เปิดน้อย","โหลด evaporator ต่ำ"],
                               "recommendation": ["ตรวจ TXV","ตรวจระดับน้ำยา","ตรวจโหลดห้องเย็น"]})
            elif superheat < 2:
                alarms.append({"severity": "Warning", "title": "Low Superheat", "message": "เสี่ยง liquid floodback",
                               "possible_causes": ["TXV เปิดมากเกิน","น้ำยาเข้า compressor เป็น liquid"],
                               "recommendation": ["ตรวจ TXV","ตรวจ suction line","เช็ค compressor safety"]})
        subcooling = None
        if p_dis_pa and data.liquid_temp_c is not None:
            t_sat_dis = CP.PropsSI('T','P',p_dis_pa,'Q',0,fluid) - 273.15
            subcooling = t_sat_dis - data.liquid_temp_c
            if data.condenser_temp_c is not None and p_dis_pa:
                t_sat_dis2 = CP.PropsSI('T','P',p_dis_pa,'Q',1,fluid) - 273.15
                approach = t_sat_dis2 - data.condenser_temp_c
                if approach > 15:
                    alarms.append({"severity": "Critical", "title": "High Condensing Temperature",
                                   "message": "Condenser ระบายความร้อนได้ไม่ดี",
                                   "possible_causes": ["Condenser สกปรก","พัดลม condenser เสีย","น้ำหล่อเย็นร้อนเกิน"],
                                   "recommendation": ["ล้าง condenser","ตรวจพัดลม","ตรวจ cooling water"]})
        pressure_ratio = (p_dis_pa / p_suc_pa) if (p_suc_pa and p_dis_pa and p_suc_pa > 0) else None
        sensor_status = "Unknown"
        if superheat is not None:
            sensor_status = "Normal" if 2 <= superheat <= 15 else "Warning"
        h1_kj  = round(h1/1000, 2)  if h1  else None
        h2_kj  = round(h2/1000, 2)  if h2  else None
        h2s_kj = round(h2s/1000, 2) if h2s else None
        h3_kj  = round(h3/1000, 2)  if h3  else None
        t_evap_c   = round(CP.PropsSI('T','P',p_suc_pa,'Q',1,fluid)-273.15,2) if p_suc_pa else None
        t_cond_c   = round(CP.PropsSI('T','P',p_dis_pa,'Q',0,fluid)-273.15,2) if p_dis_pa else None
        eta_is_pct = round((h2s-h1)/(h2-h1)*100,1) if (h2s and h1 and h2 and (h2-h1)!=0) else None
        q_l_kgkg   = round((h1-h3)/1000,2) if (h1 and h3) else None
        w_comp_kgkg= round((h2-h1)/1000,2) if (h1 and h2) else None
        m_dot_kgh  = round(m_dot*3600,1)   if m_dot else None
        result.update({
            "power_kw": safe_round(power_kw), "cop": safe_round(cop, 4),
            "q_e_kw": safe_round(q_e_kw), "superheat_suc": safe_round(superheat),
            "subcooling": safe_round(subcooling), "pressure_ratio": safe_round(pressure_ratio),
            "m_dot_kgh": safe_round(m_dot_kgh), "alarms": alarms,
            "modes": {"sh_mode": sh_mode, "dt_mode": dt_mode},
            "enthalpy": {
                "t_evap_c": t_evap_c, "t_cond_c": t_cond_c,
                "h1": h1_kj, "h2": h2_kj, "h2s": h2s_kj, "h3": h3_kj,
                "eta_is_pct": eta_is_pct, "q_l_kgkg": q_l_kgkg, "w_comp_kgkg": w_comp_kgkg,
            },
            "systems": {
                "sensor":    {"status": sensor_status, "text": f"Superheat = {safe_round(superheat)}"},
                "condenser": {"status": "Unknown", "text": "--"}
            }
        })
        return result
    except Exception as e:
        logger.error("Diagnostic error: %s", e, exc_info=True)
        return result

# =========================================================
# METRICS ENDPOINTS
# =========================================================

@app.post("/api/metrics", tags=["metrics"])
async def save_data(
    payload: CompressorDataInput,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    diag = diagnose_compressor(payload)
    tz_th = timezone(timedelta(hours=7))
    record_time = (
        payload.timestamp.astimezone(tz_th)
        if payload.timestamp
        else datetime.now(tz_th)
    )
    record = MetricModel(
        compressor_id=payload.compressor_id,
        timestamp=record_time,
        inputs_snapshot=payload.model_dump(),
        diagnosis=diag,
    )
    db.add(record)
    await db.commit()
    return {"status": "Success", "analysis": diag}

@app.get("/api/metrics/{compressor_id}", tags=["metrics"])
async def get_dashboard_data(
    compressor_id: str,
    limit: int = 2000,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    tz_th = timezone(timedelta(hours=7))
    query = select(MetricModel).where(MetricModel.compressor_id == compressor_id)
    if start:
        query = query.where(MetricModel.timestamp >= start.astimezone(tz_th))
    if end:
        query = query.where(MetricModel.timestamp <= end.astimezone(tz_th))
    query = query.order_by(MetricModel.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    return [
        {
            "_id": str(row.id),
            "compressor_id": row.compressor_id,
            "timestamp": row.timestamp.astimezone(tz_th).isoformat() if row.timestamp else None,
            "inputs_snapshot": row.inputs_snapshot,
            "diagnosis": row.diagnosis,
        }
        for row in rows
    ]

# =========================================================
# P-H DIAGRAM
# =========================================================

def build_saturation_dome(fluid: str = "Ammonia", n_points: int = 60) -> dict:
    T_min_K  = 223.15
    T_crit_K = CP.PropsSI("Tcrit", fluid)
    T_max_K  = T_crit_K - 0.5
    temps = np.linspace(T_min_K, T_max_K, n_points)
    liq_points = []; vap_points = []
    for T in temps:
        try:
            h_liq = CP.PropsSI("H","T",T,"Q",0,fluid)/1000
            h_vap = CP.PropsSI("H","T",T,"Q",1,fluid)/1000
            p_mpa = CP.PropsSI("P","T",T,"Q",0,fluid)/1e6
            liq_points.append({"h": round(h_liq,2), "p": round(p_mpa,4)})
            vap_points.append({"h": round(h_vap,2), "p": round(p_mpa,4)})
        except:
            continue
    h_crit = CP.PropsSI("H","T",T_crit_K,"Q",0,fluid)/1000
    p_crit = CP.PropsSI("P","T",T_crit_K,"Q",0,fluid)/1e6
    return {"liquid": liq_points, "vapour": vap_points,
            "critical": {"h": round(h_crit,2), "p": round(p_crit,4)}}

def compute_cycle_points(inputs: dict, fluid: str = "Ammonia") -> dict:
    sp_kg = inputs.get("sp_kg"); st_c = inputs.get("st_c")
    dp_kg = inputs.get("dp_kg"); dt_c = inputs.get("dt_c")
    liq_c = inputs.get("liquid_temp_c")
    points = {
        "point1": None, "point2": None, "point2s": None,
        "point3": None, "point4": None,
        "p_suc_mpa": None, "p_dis_mpa": None,
        "t_sat_suc_c": None, "t_sat_dis_c": None,
        "isentropic_efficiency": None,
    }
    try:
        p_suc_pa = float(sp_kg)*98066.5+101325 if sp_kg is not None else None
        p_dis_pa = float(dp_kg)*98066.5+101325 if dp_kg is not None else None
        if p_suc_pa: points["p_suc_mpa"] = round(p_suc_pa/1e6, 4)
        if p_dis_pa: points["p_dis_mpa"] = round(p_dis_pa/1e6, 4)
        if p_suc_pa: points["t_sat_suc_c"] = round(CP.PropsSI("T","P",p_suc_pa,"Q",1,fluid)-273.15, 2)
        if p_dis_pa: points["t_sat_dis_c"] = round(CP.PropsSI("T","P",p_dis_pa,"Q",1,fluid)-273.15, 2)
        if p_suc_pa and st_c is not None:
            t1_k = float(st_c)+273.15
            h1   = CP.PropsSI("H","P",p_suc_pa,"T",t1_k,fluid)/1000
            s1   = CP.PropsSI("S","P",p_suc_pa,"T",t1_k,fluid)
            points["point1"] = {"h": round(h1,2), "p": round(p_suc_pa/1e6,4),
                                 "label": "1 — Comp. inlet", "t_c": round(float(st_c),2)}
            if p_dis_pa:
                h2s = CP.PropsSI("H","P",p_dis_pa,"S",s1,fluid)/1000
                points["point2s"] = {"h": round(h2s,2), "p": round(p_dis_pa/1e6,4), "label": "2s — Isentropic"}
        if p_dis_pa and points["point1"] and points["point2s"]:
            h1_val  = points["point1"]["h"]
            h2s_val = points["point2s"]["h"]
            if dt_c is not None:
                t2_k = float(dt_c)+273.15
                h2   = CP.PropsSI("H","P",p_dis_pa,"T",t2_k,fluid)/1000
                dt_used = round(float(dt_c),2)
                if (h2-h1_val) != 0:
                    points["isentropic_efficiency"] = round((h2s_val-h1_val)/(h2-h1_val),4)
            else:
                h2 = h1_val + (h2s_val-h1_val)/0.70
                dt_used = round(CP.PropsSI("T","P",p_dis_pa,"H",h2*1000,fluid)-273.15, 2)
                points["isentropic_efficiency"] = 0.70
            points["point2"] = {"h": round(h2,2), "p": round(p_dis_pa/1e6,4),
                                  "label": "2 — Comp. outlet", "t_c": dt_used}
        if p_dis_pa:
            if liq_c is not None:
                t3_k = float(liq_c)+273.15
                h3   = CP.PropsSI("H","P",p_dis_pa,"T",t3_k,fluid)/1000
                t3_c = round(float(liq_c),2)
            else:
                h3   = CP.PropsSI("H","P",p_dis_pa,"Q",0,fluid)/1000
                t3_c = round(CP.PropsSI("T","P",p_dis_pa,"Q",0,fluid)-273.15,2)
            points["point3"] = {"h": round(h3,2), "p": round(p_dis_pa/1e6,4),
                                  "label": "3 — Cond. outlet", "t_c": t3_c}
            if p_suc_pa:
                points["point4"] = {"h": round(h3,2), "p": round(p_suc_pa/1e6,4), "label": "4 — Evap. inlet"}
    except Exception as e:
        logger.error("P-H compute error: %s", e, exc_info=True)
    return points

@app.get("/api/ph-diagram/{compressor_id}", tags=["ph-diagram"])
async def get_ph_diagram(
    compressor_id: str,
    record_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if record_id:
        try:
            result = await db.execute(
                select(MetricModel).where(
                    MetricModel.id == int(record_id),
                    MetricModel.compressor_id == compressor_id
                )
            )
            doc = result.scalar_one_or_none()
        except:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="record_id ไม่ถูกต้อง")
    elif timestamp:
        tz_th = timezone(timedelta(hours=7))
        ts = timestamp.astimezone(tz_th)
        result = await db.execute(
            select(MetricModel).where(
                MetricModel.compressor_id == compressor_id,
                MetricModel.timestamp >= ts - timedelta(seconds=1),
                MetricModel.timestamp <= ts + timedelta(seconds=1),
            ).order_by(MetricModel.timestamp.desc()).limit(1)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"ไม่พบข้อมูลของ {compressor_id} ในช่วงเวลาที่เลือก")
    else:
        result = await db.execute(
            select(MetricModel).where(MetricModel.compressor_id == compressor_id)
            .order_by(MetricModel.timestamp.desc()).limit(1)
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"ไม่พบข้อมูลของ {compressor_id}")

    inputs = doc.inputs_snapshot or {}
    cycle  = compute_cycle_points(inputs)
    dome   = build_saturation_dome()
    tz_th  = timezone(timedelta(hours=7))
    ts_str = doc.timestamp.astimezone(tz_th).isoformat() if doc.timestamp else None

    return {
        "compressor_id": compressor_id,
        "timestamp":     ts_str,
        "record_id":     str(doc.id),
        "saturation_dome": dome,
        "cycle": cycle,
    }

# =========================================================
# CALCULATOR ENDPOINTS (ไม่เปลี่ยน)
# =========================================================

class CalcInput(BaseModel):
    current: float
    sp: float
    dp: float
    st: Optional[float] = None
    dt: Optional[float] = None
    liquid_temp: Optional[float] = None
    sh_default: float = 5.0
    eta_is: float = 0.70
    voltage: float = 385.0
    power_factor: float = 0.86

class TwoStageInput(BaseModel):
    i_booster: float
    sp: float
    st: Optional[float] = None
    dt_booster: Optional[float] = None
    t_int: float = -7.0
    i_high: float
    dp: float
    dt_high: Optional[float] = None
    liquid_temp: Optional[float] = None
    sh_default: float = 5.0
    eta_booster: float = 0.70
    eta_high: float = 0.70
    voltage: float = 385.0
    power_factor: float = 0.86

def _kpa(p: float) -> float:
    return (p * 98066.5) + 101325

@app.post("/api/calculate", tags=["calculator"])
def api_calculate(data: CalcInput):
    fluid = "Ammonia"
    P_comp_kW = (1.732 * data.voltage * data.current * data.power_factor) / 1000
    P_low  = _kpa(data.sp)
    P_high = _kpa(data.dp)
    T_evap = CP.PropsSI("T","P",P_low, "Q",1,fluid) - 273.15
    T_cond = CP.PropsSI("T","P",P_high,"Q",0,fluid) - 273.15
    if data.st is not None:
        SH = data.st - T_evap
        h1 = CP.PropsSI("H","P",P_low,"T",data.st+273.15,fluid)/1000
        st_used = data.st; sh_mode = "measured"
    else:
        SH = data.sh_default
        h1 = CP.PropsSI("H","P",P_low,"T",T_evap+SH+273.15,fluid)/1000
        st_used = T_evap+SH; sh_mode = "assumed"
    T1_K = st_used + 273.15
    s1   = CP.PropsSI("S","P",P_low,"T",T1_K,fluid)
    h2s  = CP.PropsSI("H","P",P_high,"S",s1,fluid)/1000
    T2s_C= CP.PropsSI("T","P",P_high,"S",s1,fluid) - 273.15
    if data.dt is not None:
        h2 = CP.PropsSI("H","P",P_high,"T",data.dt+273.15,fluid)/1000
        eta_is_actual = (h2s-h1)/(h2-h1) if (h2-h1)!=0 else None
        dt_used = data.dt; dt_mode = "measured"
    else:
        h2 = h1 + (h2s-h1)/data.eta_is
        eta_is_actual = data.eta_is
        dt_used = CP.PropsSI("T","P",P_high,"H",h2*1000,fluid) - 273.15
        dt_mode = "assumed"
    hf_cond = CP.PropsSI("H","P",P_high,"Q",0,fluid)/1000
    if data.liquid_temp is not None:
        SC = T_cond - data.liquid_temp
        h3 = CP.PropsSI("H","P",P_high,"T",data.liquid_temp+273.15,fluid)/1000
        liq_mode = "measured"
    else:
        SC = 0.0; h3 = hf_cond; liq_mode = "assumed"
    h4 = h3
    q_L = h1-h4; w_comp = h2-h1; q_H = h2-h3
    COP = q_L/w_comp
    Q_e = P_comp_kW*COP; Q_H_kW = P_comp_kW+Q_e
    m_dot = Q_e/q_L; TR = Q_e/3.517
    warnings = []
    if SH < 0:  warnings.append({"level":"danger",  "msg":f"Superheat = {SH:.1f} K — มีของเหลวเข้า compressor!"})
    if SH > 15: warnings.append({"level":"warning", "msg":f"Superheat สูง ({SH:.1f} K)"})
    if SC < 0:  warnings.append({"level":"danger",  "msg":f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP < 1.5: warnings.append({"level":"warning","msg":f"COP = {COP:.2f} — ต่ำกว่าปกติ"})
    if eta_is_actual and eta_is_actual < 0.55:
        warnings.append({"level":"warning","msg":f"eta_is = {eta_is_actual*100:.1f}% — ต่ำมาก"})
    return {
        "modes":      {"sh_mode":sh_mode,"dt_mode":dt_mode,"liq_mode":liq_mode,
                       "st_used":round(st_used,2),"dt_used":round(dt_used,2)},
        "inputs":     {"P_low_kPa":round(P_low/1000,2),"P_high_kPa":round(P_high/1000,2)},
        "saturation": {"T_evap":round(T_evap,2),"T_cond":round(T_cond,2),
                       "superheat":round(SH,2),"subcool":round(SC,2)},
        "enthalpy":   {"h1":round(h1,2),"h2":round(h2,2),"h3":round(h3,2),"h4":round(h4,2),
                       "h2s":round(h2s,2),"T2s_degC":round(T2s_C,2)},
        "performance":{"P_comp_kW":round(P_comp_kW,3),"q_L":round(q_L,2),"w_comp":round(w_comp,2),
                       "q_H":round(q_H,2),"COP":round(COP,4),"Q_e_kW":round(Q_e,3),
                       "Q_H_kW":round(Q_H_kW,3),"TR":round(TR,2),
                       "m_dot_kgs":round(m_dot,5),"m_dot_kgh":round(m_dot*3600,2),
                       "eta_isentropic":round(eta_is_actual*100,1) if eta_is_actual else None},
        "warnings": warnings,
    }

@app.post("/api/calculate_two", tags=["calculator"])
def api_calculate_two(data: TwoStageInput):
    fluid = "Ammonia"
    P_low  = _kpa(data.sp)
    P_int  = CP.PropsSI("P","T",data.t_int+273.15,"Q",1,fluid)
    P_high = _kpa(data.dp)
    T_evap = CP.PropsSI("T","P",P_low, "Q",1,fluid) - 273.15
    T_cond = CP.PropsSI("T","P",P_high,"Q",0,fluid) - 273.15
    if data.st is not None:
        SH=data.st-T_evap; h1=CP.PropsSI("H","P",P_low,"T",data.st+273.15,fluid)/1000
        st_used=data.st; sh_mode="measured"
    else:
        SH=data.sh_default; h1=CP.PropsSI("H","P",P_low,"T",T_evap+SH+273.15,fluid)/1000
        st_used=T_evap+SH; sh_mode="assumed"
    s1    = CP.PropsSI("S","P",P_low,"T",st_used+273.15,fluid)
    h2s_b = CP.PropsSI("H","P",P_int,"S",s1,fluid)/1000
    if data.dt_booster is not None:
        h2=CP.PropsSI("H","P",P_int,"T",data.dt_booster+273.15,fluid)/1000
        eta_b=(h2s_b-h1)/(h2-h1) if (h2-h1)!=0 else None
        dt_b_used=data.dt_booster; dt_b_mode="measured"
    else:
        h2=h1+(h2s_b-h1)/data.eta_booster; eta_b=data.eta_booster
        dt_b_used=CP.PropsSI("T","P",P_int,"H",h2*1000,fluid)-273.15; dt_b_mode="assumed"
    h3  = CP.PropsSI("H","P",P_int,"Q",1,fluid)/1000
    s3  = CP.PropsSI("S","P",P_int,"Q",1,fluid)
    h4s = CP.PropsSI("H","P",P_high,"S",s3,fluid)/1000
    if data.dt_high is not None:
        h4=CP.PropsSI("H","P",P_high,"T",data.dt_high+273.15,fluid)/1000
        eta_h=(h4s-h3)/(h4-h3) if (h4-h3)!=0 else None
        dt_h_used=data.dt_high; dt_h_mode="measured"
    else:
        h4=h3+(h4s-h3)/data.eta_high; eta_h=data.eta_high
        dt_h_used=CP.PropsSI("T","P",P_high,"H",h4*1000,fluid)-273.15; dt_h_mode="assumed"
    hf_cond=CP.PropsSI("H","P",P_high,"Q",0,fluid)/1000
    if data.liquid_temp is not None:
        SC=T_cond-data.liquid_temp
        h5=CP.PropsSI("H","P",P_high,"T",data.liquid_temp+273.15,fluid)/1000; liq_mode="measured"
    else:
        SC=0.0; h5=hf_cond; liq_mode="assumed"
    h6=h5
    hf_int=CP.PropsSI("H","P",P_int,"Q",0,fluid)/1000; h7=hf_int
    ratio=(h2-h6)/(h3-h6)
    W_booster=(1.732*data.voltage*data.i_booster*data.power_factor)/1000
    W_high   =(1.732*data.voltage*data.i_high   *data.power_factor)/1000
    W_total  =W_booster+W_high
    m_low=W_booster/(h2-h1); m_high=m_low*ratio
    Q_e=m_low*(h1-h7); Q_cond=m_high*(h4-h5)
    COP_system=Q_e/W_total; TR=Q_e/3.517
    warnings=[]
    if SH<0:    warnings.append({"level":"danger",  "msg":f"Superheat = {SH:.1f} K — liquid เข้า booster!"})
    if SH>15:   warnings.append({"level":"warning", "msg":f"Superheat สูง ({SH:.1f} K)"})
    if SC<0:    warnings.append({"level":"danger",  "msg":f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP_system<1.2: warnings.append({"level":"warning","msg":f"COP = {COP_system:.2f} — ต่ำกว่าปกติ"})
    if ratio>1.5: warnings.append({"level":"warning","msg":f"m_high/m_low = {ratio:.2f} — สูงมาก ตรวจ intercooler"})
    return {
        "modes":      {"sh_mode":sh_mode,"dt_b_mode":dt_b_mode,"dt_h_mode":dt_h_mode,
                       "liq_mode":liq_mode,"st_used":round(st_used,2),
                       "dt_b_used":round(dt_b_used,2),"dt_h_used":round(dt_h_used,2)},
        "pressures":  {"P_low_kPa":round(P_low/1000,2),"P_int_kPa":round(P_int/1000,2),
                       "P_int_kgcm2g":round(P_int/98066.5-1.0332,3),"P_high_kPa":round(P_high/1000,2)},
        "saturation": {"T_evap":round(T_evap,2),"T_int":round(data.t_int,2),"T_cond":round(T_cond,2),
                       "superheat":round(SH,2),"subcool":round(SC,2)},
        "enthalpy":   {"h1":round(h1,2),"h2":round(h2,2),"h2s_b":round(h2s_b,2),
                       "h3":round(h3,2),"h4":round(h4,2),"h4s":round(h4s,2),
                       "h5":round(h5,2),"h6":round(h6,2),"hf_int":round(hf_int,2),"h7":round(h7,2)},
        "performance":{"W_booster_kW":round(W_booster,3),"W_high_kW":round(W_high,3),"W_total_kW":round(W_total,3),
                       "m_low_kgs":round(m_low,5),"m_low_kgh":round(m_low*3600,2),
                       "m_high_kgs":round(m_high,5),"m_high_kgh":round(m_high*3600,2),
                       "ratio_mh_ml":round(ratio,3),"Q_e_kW":round(Q_e,3),"Q_e_TR":round(TR,2),
                       "Q_cond_kW":round(Q_cond,3),"COP_system":round(COP_system,4),
                       "eta_booster":round(eta_b*100,1) if eta_b else None,
                       "eta_high":round(eta_h*100,1) if eta_h else None},
        "warnings": warnings,
    }

# =========================================================
# QUERY ENDPOINT — แสดงข้อมูลแบบ flat 
# =========================================================

@app.get("/api/metrics/{compressor_id}/detail", tags=["metrics"])
async def get_detail_data(
    compressor_id: str,
    limit: int = 100,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    _user: dict = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    tz_th = timezone(timedelta(hours=7))
    query = select(MetricModel).where(MetricModel.compressor_id == compressor_id)
    if start:
        query = query.where(MetricModel.timestamp >= start.astimezone(tz_th))
    if end:
        query = query.where(MetricModel.timestamp <= end.astimezone(tz_th))
    query = query.order_by(MetricModel.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    rows = result.scalars().all()

    data_list = []
    for row in rows:
        inp = row.inputs_snapshot or {}
        diag = row.diagnosis or {}
        enth = diag.get("enthalpy", {})
        systems = diag.get("systems", {})
        alarms = diag.get("alarms", [])

        data_list.append({
            # ── Meta ──────────────────────────────
            "id":             row.id,
            "compressor_id":  row.compressor_id,
            "timestamp":      row.timestamp.astimezone(tz_th).isoformat() if row.timestamp else None,

            # ── Input (ค่าจาก sensor) ─────────────
            "input": {
                "sp_kg":                  inp.get("sp_kg"),
                "dp_kg":                  inp.get("dp_kg"),
                "st_c":                   inp.get("st_c"),
                "dt_c":                   inp.get("dt_c"),
                "liquid_temp_c":          inp.get("liquid_temp_c"),
                "current_amp":            inp.get("current_amp"),
                "evaporator_room_temp_c": inp.get("evaporator_room_temp_c"),
                "condenser_temp_c":       inp.get("condenser_temp_c"),
            },

            # ── Performance (ค่าหลังคำนวณ) ────────
            "performance": {
                "power_kw":       diag.get("power_kw"),
                "cop":            diag.get("cop"),
                "q_e_kw":         diag.get("q_e_kw"),
                "m_dot_kgh":      diag.get("m_dot_kgh"),
                "superheat_suc":  diag.get("superheat_suc"),
                "subcooling":     diag.get("subcooling"),
                "pressure_ratio": diag.get("pressure_ratio"),
            },

            # ── Enthalpy ──────────────────────────
            "enthalpy": {
                "t_evap_c":    enth.get("t_evap_c"),
                "t_cond_c":    enth.get("t_cond_c"),
                "h1":          enth.get("h1"),
                "h2":          enth.get("h2"),
                "h2s":         enth.get("h2s"),
                "h3":          enth.get("h3"),
                "eta_is_pct":  enth.get("eta_is_pct"),
                "q_l_kgkg":    enth.get("q_l_kgkg"),
                "w_comp_kgkg": enth.get("w_comp_kgkg"),
            },

            # ── Status ────────────────────────────
            "status": {
                "sensor":    systems.get("sensor", {}).get("status"),
                "sensor_text": systems.get("sensor", {}).get("text"),
                "condenser": systems.get("condenser", {}).get("status"),
            },

            # ── Alarms ────────────────────────────
            "alarms": [
                {
                    "severity": a.get("severity"),
                    "title":    a.get("title"),
                    "message":  a.get("message"),
                }
                for a in alarms
            ],
            "alarm_count": len(alarms),
        })

    return {
        "compressor_id": compressor_id,
        "count":         len(data_list),
        "data":          data_list,
    }

# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables ready")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)