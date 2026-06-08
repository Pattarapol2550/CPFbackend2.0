import math
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
import numpy as np
from dotenv import load_dotenv
import CoolProp.CoolProp as CP
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
 
# =========================================================
# FASTAPI
# =========================================================
 
app = FastAPI(
    title="Ammonia Diagnostics API v2"
)
 
# =========================================================
# CORS
# =========================================================
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
# =========================================================
# MONGODB
# =========================================================
 
# MONGO_DETAILS = "mongodb://localhost:27017"
 
# client = AsyncIOMotorClient(MONGO_DETAILS)
 
# database = client.thermoCPF
 
# metrics_collection = database.get_collection(
#     "compressor_data_v2"
# )
 
load_dotenv()
MONGO_DETAILS = os.getenv("MONGO_DETAILS")
client = AsyncIOMotorClient(MONGO_DETAILS)
database = client.thermoCPF
metrics_collection = database.get_collection("compressor_data_v2")
 
# =========================================================
# DATA MODEL
# =========================================================
 
class CompressorDataInput(BaseModel):
 
    compressor_id: str
 
    timestamp: Optional[datetime] = None
 
    # =====================================================
    # OPTIONAL INPUTS
    # =====================================================
 
    sp_kg: float
    dp_kg: float
    st_c:  Optional[float] = None  # ถ้าไม่กรอก assume SH=5K
    dt_c:  Optional[float] = None  # ถ้าไม่กรอก assume η_is=0.70
 
    liquid_temp_c: Optional[float] = None

    current_amp: Optional[float] = None

    evaporator_room_temp_c: Optional[float] = None

    condenser_temp_c: Optional[float] = None
 
# =========================================================
# SAFE ROUND
# =========================================================
 
def safe_round(value, digit=2):
 
    if value is None:
        return "--"
 
    try:
        return round(value, digit)
 
    except:
        return "--"
 
# =========================================================
# MAIN DIAGNOSTIC
# =========================================================
 
def diagnose_compressor(data: CompressorDataInput):
 
    fluid = "Ammonia"
 
    voltage = 385.0
 
    power_factor = 0.86
 
    # =====================================================
    # DEFAULT RESULT
    # =====================================================
    alarms = []
 
    result = {
 
        "q_e_kw": "--",
 
        "power_kw": "--",
 
        "cop": "--",
 
        
 
        
 
        "superheat_suc": "--",
 
        "subcooling": "--",
 
        "pressure_ratio": "--",
 
        "systems": {
 
            "sensor": {
                "status": "Unknown",
                "text": "--"
            },
 
            "condenser": {
                "status": "Unknown",
                "text": "--"
            }
        }
    }
 
    try:
 
        # =================================================
        # PRESSURE
        # =================================================
 
        p_suc_pa = None
        p_dis_pa = None
 
        if data.sp_kg is not None:
            p_suc_pa = (
                data.sp_kg * 98066.5 + 101325
            )
 
        if data.dp_kg is not None:
            p_dis_pa = (
                data.dp_kg * 98066.5 + 101325
            ) 
 
        # =================================================
        # TEMPERATURE
        # =================================================
 
        t_suc_k = None
        t_dis_k = None
 
        if data.st_c is not None:
            t_suc_k = data.st_c + 273.15
 
        if data.dt_c is not None:
            t_dis_k = data.dt_c + 273.15
 
        # =================================================
        # ENTHALPY
        # =================================================
 

        h1 = None
        h2 = None
        h2s = None
        h3 = None
        sh_mode = "assumed"
        dt_mode = "assumed"

        # h1: ถ้ามี ST ใช้จริง ถ้าไม่มี assume SH=5K
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

        # h2s: isentropic (ต้องการ h1 ก่อน)
        if h1 is not None and p_dis_pa and t_suc_k and p_suc_pa:
            s1 = CP.PropsSI('S','P',p_suc_pa,'T',t_suc_k,fluid)
            h2s = CP.PropsSI('H','P',p_dis_pa,'S',s1,fluid)

        # h2: ถ้ามี DT ใช้จริง ถ้าไม่มี assume eta_is=0.70
        if p_dis_pa:
            if t_dis_k:
                h2 = CP.PropsSI('H','P',p_dis_pa,'T',t_dis_k,fluid)
                dt_mode = "measured"
            elif h2s is not None and h1 is not None:
                eta_is = 0.70
                h2 = h1 + (h2s - h1) / eta_is
                dt_mode = "assumed_eta07"

 
        # =================================================
        # LIQUID ENTHALPY
        # =================================================
 
        if (
            p_dis_pa and
            data.liquid_temp_c is not None
        ):
 
            h3 = CP.PropsSI(
                'H',
                'P',
                p_dis_pa,
                'T',
                data.liquid_temp_c + 273.15,
                fluid
            )
 
        elif p_dis_pa:
 
            try:
                h3 = CP.PropsSI(
                    'H',
                    'P',
                    p_dis_pa,
                    'Q',
                    0,
                    fluid
                )
                print(f"DEBUG h3 fallback OK: {h3:.2f} J/kg at p_dis={p_dis_pa:.1f} Pa")
            except Exception as ex:
                print(f"DEBUG h3 fallback ERROR: {ex}")
                h3 = None
 
        # =================================================
        # POWER
        # =================================================
 
        power_kw = None
 
        if data.current_amp is not None:
 
            power_kw = (
                math.sqrt(3) *
                voltage *
                data.current_amp *
                power_factor
            ) / 1000
 
        # =================================================
        # COP, Q_e, m_dot (logic เดียวกับเว็บคำนวณ)
        # =================================================

        cop    = None
        q_e_kw = None
        m_dot  = None

        if h1 is not None and h2 is not None and h3 is not None and (h2 - h1) != 0:
            cop = (h1 - h3) / (h2 - h1)

        if cop is not None and power_kw is not None and power_kw > 0:
            q_e_kw = power_kw * cop
            m_dot  = (q_e_kw * 1000) / (h1 - h3)  # kg/s

        # COP alarm
        if cop is not None and cop < 1.5:
            alarms.append({
                "severity": "Warning",
                "title": "Low COP",
                "message": "ประสิทธิภาพระบบต่ำ",
                "possible_causes": [
                    "โหลดสูงเกิน",
                    "Compressor efficiency ต่ำ",
                    "Condenser ทำงานไม่ดี"
                ],
                "recommendation": [
                    "ตรวจ compressor",
                    "ตรวจ condenser",
                    "ตรวจโหลดระบบ"
                ]
            })
 
        # =================================================
        # SUPERHEAT
        # =================================================
 
        superheat = None
 
        if (
            p_suc_pa and
            data.st_c is not None
        ):
 
            t_sat_suc = CP.PropsSI(
                'T',
                'P',
                p_suc_pa,
                'Q',
                1,
                fluid
            ) - 273.15
 
            superheat = (
                data.st_c - t_sat_suc
            )
        
 
        if superheat is not None:
 
            if superheat > 15:
 
                alarms.append({
                    "severity": "Warning",
                    "title": "High Superheat",
                    "message": "Superheat สูงเกินปกติ",
                    "possible_causes": [
                        "น้ำยาเข้า evaporator ไม่พอ",
                        "Expansion valve เปิดน้อย",
                        "โหลด evaporator ต่ำ"
                    ],
                    "recommendation": [
                        "ตรวจ TXV",
                        "ตรวจระดับน้ำยา",
                        "ตรวจโหลดห้องเย็น"
                    ]
                })
 
            elif superheat < 2:
 
                alarms.append({
                    "severity": "Warning",
                    "title": "Low Superheat",
                    "message": "เสี่ยง liquid floodback",
                    "possible_causes": [
                        "TXV เปิดมากเกิน",
                        "น้ำยาเข้า compressor เป็น liquid"
                    ],
                    "recommendation": [
                        "ตรวจ TXV",
                        "ตรวจ suction line",
                        "เช็ค compressor safety"
                    ]
                })
            
 
        # =================================================
        # SUBCOOLING
        # =================================================
 
        subcooling = None
 
        if (
            p_dis_pa and
            data.liquid_temp_c is not None
        ):
 
            t_sat_dis = CP.PropsSI(
                'T',
                'P',
                p_dis_pa,
                'Q',
                0,
                fluid
            ) - 273.15
 
            subcooling = (
                t_sat_dis -
                data.liquid_temp_c
            )
 
            if (
                data.condenser_temp_c is not None and
                p_dis_pa
            ):
 
                t_sat_dis = CP.PropsSI(
                    'T',
                    'P',
                    p_dis_pa,
                    'Q',
                    1,
                    fluid
                ) - 273.15
 
                approach = t_sat_dis - data.condenser_temp_c
 
                if approach > 15:
 
                    alarms.append({
                        "severity": "Critical",
                        "title": "High Condensing Temperature",
                        "message": "Condenser ระบายความร้อนได้ไม่ดี",
                        "possible_causes": [
                            "Condenser สกปรก",
                            "พัดลม condenser เสีย",
                            "น้ำหล่อเย็นร้อนเกิน"
                        ],
                        "recommendation": [
                            "ล้าง condenser",
                            "ตรวจพัดลม",
                            "ตรวจ cooling water"
                        ]
                    })
 
                
 
        # =================================================
        # PRESSURE RATIO
        # =================================================
 
        pressure_ratio = None
 
        if (
            p_suc_pa and
            p_dis_pa and
            p_suc_pa > 0
        ):
 
            pressure_ratio = (
                p_dis_pa / p_suc_pa
            )
 
        # =================================================
        # STATUS
        # =================================================
 
        sensor_status = "Unknown"
 
        if superheat is not None:
 
            if 2 <= superheat <= 15:
                sensor_status = "Normal"
 
            else:
                sensor_status = "Warning"
 
        condenser_status = "Unknown"
 
        # =================================================
        # UPDATE RESULT
        # =================================================
 
        # =================================================

        # Enthalpy detail (kJ/kg)
        h1_kj       = round(h1/1000, 2)  if h1  else None
        h2_kj       = round(h2/1000, 2)  if h2  else None
        h2s_kj      = round(h2s/1000, 2) if h2s else None
        h3_kj       = round(h3/1000, 2)  if h3  else None
        t_evap_c    = round(CP.PropsSI('T','P',p_suc_pa,'Q',1,fluid)-273.15,2) if p_suc_pa else None
        t_cond_c    = round(CP.PropsSI('T','P',p_dis_pa,'Q',0,fluid)-273.15,2) if p_dis_pa else None
        eta_is_pct  = round((h2s-h1)/(h2-h1)*100,1) if (h2s and h1 and h2 and (h2-h1)!=0) else None
        q_l_kgkg    = round((h1-h3)/1000,2) if (h1 and h3) else None
        w_comp_kgkg = round((h2-h1)/1000,2) if (h1 and h2) else None
        m_dot_kgh   = round(m_dot*3600,1)   if m_dot else None

        result.update({

            "power_kw":       safe_round(power_kw),
            "cop":            safe_round(cop, 4),
            "q_e_kw":         safe_round(q_e_kw),
            "superheat_suc":  safe_round(superheat),
            "subcooling":     safe_round(subcooling),
            "pressure_ratio": safe_round(pressure_ratio),
            "m_dot_kgh":      safe_round(m_dot_kgh),

            "alarms": alarms,

            "modes": {
                "sh_mode": sh_mode,
                "dt_mode": dt_mode,
            },

            "enthalpy": {
                "t_evap_c":    t_evap_c,
                "t_cond_c":    t_cond_c,
                "h1":          h1_kj,
                "h2":          h2_kj,
                "h2s":         h2s_kj,
                "h3":          h3_kj,
                "eta_is_pct":  eta_is_pct,
                "q_l_kgkg":    q_l_kgkg,
                "w_comp_kgkg": w_comp_kgkg,
            },

            "systems": {
                "sensor": {
                    "status": sensor_status,
                    "text":   f"Superheat = {safe_round(superheat)}"
                },
                "condenser": {
                    "status": condenser_status,
                    "text":   "--"
                }
            }
        })

 
        return result
 
    except Exception as e:
 
        print("ERROR =", e)
 
        return result
 
# =========================================================
# SAVE DATA
# =========================================================
 
@app.post("/api/metrics")
 
async def save_data(payload: CompressorDataInput):
 
    diag = diagnose_compressor(payload)
 
    tz_th = timezone(
        timedelta(hours=7)
    )
 
    record_time = (
    payload.timestamp.astimezone(tz_th)
    if payload.timestamp
    else datetime.now(tz_th)
    )
 
    document = {
 
        "compressor_id":
            payload.compressor_id,
 
        "timestamp":
            record_time,
 
        "inputs_snapshot":
            payload.model_dump(),
 
        "diagnosis":
            diag
    }
 
    await metrics_collection.insert_one(
        document
    )
 
    return {
 
        "status": "Success",
 
        "analysis": diag
    }
 
# =========================================================
# GET DATA
# =========================================================
 
@app.get("/api/metrics/{compressor_id}")
 
async def get_dashboard_data(
    compressor_id: str,
    limit: int = 2000,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None
):
 
    query: dict = {"compressor_id": compressor_id}
 
    tz_th = timezone(timedelta(hours=7))
 
    if start or end:
        ts_filter = {}
        if start:
            ts_filter["$gte"] = start.astimezone(tz_th)
        if end:
            ts_filter["$lte"] = end.astimezone(tz_th)
        query["timestamp"] = ts_filter
 
    cursor = metrics_collection.find(query).sort(
 
        "timestamp",
        -1
 
    ).limit(limit)
 
    data_list = []
 
    async for doc in cursor:
 
        doc["_id"] = str(doc["_id"])
 
        if "timestamp" in doc and doc["timestamp"]:
 
            doc["timestamp"] = (
            doc["timestamp"]
            .astimezone(timezone(timedelta(hours=7)))
            .isoformat()
        )
 
        data_list.append(doc)
 
    return data_list
 
# =========================================================
# P-H DIAGRAM ENDPOINT
# =========================================================
 
# ----------------------------------------------------------
# Helper: build ammonia saturation dome via CoolProp
# Returns list of {h, p} points for liquid side + vapour side
# ----------------------------------------------------------
 
def build_saturation_dome(
    fluid: str = "Ammonia",
    n_points: int = 60
) -> dict:
 
 
    # Temperature range: -50 °C to critical point (~132.25 °C)
    T_min_K = 223.15   # -50 °C
    T_crit_K = CP.PropsSI("Tcrit", fluid)
    T_max_K  = T_crit_K - 0.5   # stop just below critical
 
    temps = np.linspace(T_min_K, T_max_K, n_points)
 
    liq_points = []   # saturated liquid (Q=0)
    vap_points = []   # saturated vapour (Q=1)
 
    for T in temps:
        try:
            h_liq = CP.PropsSI("H", "T", T, "Q", 0, fluid) / 1000  # kJ/kg
            h_vap = CP.PropsSI("H", "T", T, "Q", 1, fluid) / 1000
            p_mpa = CP.PropsSI("P", "T", T, "Q", 0, fluid) / 1e6   # MPa
 
            liq_points.append({"h": round(h_liq, 2), "p": round(p_mpa, 4)})
            vap_points.append({"h": round(h_vap, 2), "p": round(p_mpa, 4)})
        except Exception:
            continue
 
    # Critical point
    h_crit = CP.PropsSI("H", "T", T_crit_K, "Q", 0, fluid) / 1000
    p_crit = CP.PropsSI("P", "T", T_crit_K, "Q", 0, fluid) / 1e6
 
    return {
        "liquid": liq_points,
        "vapour": vap_points,
        "critical": {"h": round(h_crit, 2), "p": round(p_crit, 4)},
    }
 
 
# ----------------------------------------------------------
# Helper: compute cycle points from raw sensor inputs
# Returns None for each point that cannot be computed
#
# Refrigeration cycle (simple single-stage):
#   1 → compressor inlet  (suction, actual superheat)
#   2 → compressor outlet (discharge, actual)
#   2s→ isentropic discharge (ideal, for isentropic eff.)
#   3 → condenser outlet  (liquid at discharge pressure)
#   4 → evaporator inlet  (after expansion valve, throttling → h4 = h3)
# ----------------------------------------------------------
 
def compute_cycle_points(inputs: dict, fluid: str = "Ammonia") -> dict:
 
    sp_kg  = inputs.get("sp_kg")
    st_c   = inputs.get("st_c")
    dp_kg  = inputs.get("dp_kg")
    dt_c   = inputs.get("dt_c")
    liq_c  = inputs.get("liquid_temp_c")
 
    points = {
        "point1":  None,   # suction (comp inlet)
        "point2":  None,   # discharge actual (comp outlet)
        "point2s": None,   # discharge isentropic (ideal)
        "point3":  None,   # condenser outlet (liquid)
        "point4":  None,   # evaporator inlet (after expansion)
        "p_suc_mpa": None,
        "p_dis_mpa": None,
        "t_sat_suc_c": None,
        "t_sat_dis_c": None,
        "isentropic_efficiency": None,
    }
 
    try:
        # ── Pressures ──────────────────────────────────────
        p_suc_pa = float(sp_kg) * 98066.5 + 101325 if sp_kg is not None else None
        p_dis_pa = float(dp_kg) * 98066.5 + 101325 if dp_kg is not None else None
 
        if p_suc_pa:
            points["p_suc_mpa"] = round(p_suc_pa / 1e6, 4)
        if p_dis_pa:
            points["p_dis_mpa"] = round(p_dis_pa / 1e6, 4)
 
        # ── Saturation temperatures ─────────────────────────
        if p_suc_pa:
            t_sat_suc = CP.PropsSI("T", "P", p_suc_pa, "Q", 1, fluid) - 273.15
            points["t_sat_suc_c"] = round(t_sat_suc, 2)
        if p_dis_pa:
            t_sat_dis = CP.PropsSI("T", "P", p_dis_pa, "Q", 1, fluid) - 273.15
            points["t_sat_dis_c"] = round(t_sat_dis, 2)
 
        # ── Point 1: compressor inlet (suction) ────────────
        if p_suc_pa and st_c is not None:
            t1_k = float(st_c) + 273.15
            h1   = CP.PropsSI("H", "P", p_suc_pa, "T", t1_k, fluid) / 1000
            s1   = CP.PropsSI("S", "P", p_suc_pa, "T", t1_k, fluid)
            points["point1"] = {
                "h": round(h1, 2),
                "p": round(p_suc_pa / 1e6, 4),
                "label": "1 — Comp. inlet",
                "t_c": round(float(st_c), 2),
            }
 
            # ── Point 2s: isentropic discharge ─────────────
            if p_dis_pa:
                h2s = CP.PropsSI("H", "P", p_dis_pa, "S", s1, fluid) / 1000
                points["point2s"] = {
                    "h": round(h2s, 2),
                    "p": round(p_dis_pa / 1e6, 4),
                    "label": "2s — Isentropic",
                }
 
        # ── Point 2: compressor outlet (discharge actual) ───
        if p_dis_pa and dt_c is not None:
            t2_k = float(dt_c) + 273.15
            h2   = CP.PropsSI("H", "P", p_dis_pa, "T", t2_k, fluid) / 1000
            points["point2"] = {
                "h": round(h2, 2),
                "p": round(p_dis_pa / 1e6, 4),
                "label": "2 — Comp. outlet",
                "t_c": round(float(dt_c), 2),
            }
 
            # ── Isentropic efficiency ───────────────────────
            if points["point2s"] and points["point1"]:
                h1_val  = points["point1"]["h"]
                h2s_val = points["point2s"]["h"]
                if (h2 - h1_val) != 0:
                    eta_is = (h2s_val - h1_val) / (h2 - h1_val)
                    points["isentropic_efficiency"] = round(eta_is, 4)
 
        # ── Point 3: condenser outlet (liquid) ──────────────
        if p_dis_pa:
            if liq_c is not None:
                t3_k = float(liq_c) + 273.15
                h3   = CP.PropsSI("H", "P", p_dis_pa, "T", t3_k, fluid) / 1000
                t3_c = round(float(liq_c), 2)
            else:
                # fall back: saturated liquid at discharge pressure
                h3   = CP.PropsSI("H", "P", p_dis_pa, "Q", 0, fluid) / 1000
                t3_c = round(CP.PropsSI("T", "P", p_dis_pa, "Q", 0, fluid) - 273.15, 2)
 
            points["point3"] = {
                "h": round(h3, 2),
                "p": round(p_dis_pa / 1e6, 4),
                "label": "3 — Cond. outlet",
                "t_c": t3_c,
            }
 
            # ── Point 4: evaporator inlet (throttling h4 = h3) ──
            if p_suc_pa:
                points["point4"] = {
                    "h": round(h3, 2),   # isenthalpic expansion
                    "p": round(p_suc_pa / 1e6, 4),
                    "label": "4 — Evap. inlet",
                }
 
    except Exception as e:
        print("P-H compute error:", e)
 
    return points
 
 
# ----------------------------------------------------------
# GET /api/ph-diagram/{compressor_id}
#
# Query params:
#   record_id (str, optional) — fetch a specific document _id
#   If omitted → use the latest record for that compressor
#
# Response:
#   {
#     "saturation_dome": { "liquid": [...], "vapour": [...], "critical": {...} },
#     "cycle": { "point1": {...}, "point2": {...}, ... },
#     "compressor_id": "COMP-01",
#     "timestamp": "...",
#   }
# ----------------------------------------------------------
 
@app.get("/api/ph-diagram/{compressor_id}")
 
async def get_ph_diagram(
    compressor_id: str,
    record_id: Optional[str] = None,
):
 
    # ── Fetch the right document from MongoDB ────────────
    if record_id:
 
        from bson import ObjectId
 
        try:
            doc = await metrics_collection.find_one(
                {"_id": ObjectId(record_id), "compressor_id": compressor_id}
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="record_id ไม่ถูกต้อง"
            )
 
    else:
        # latest record for this compressor
        doc = await metrics_collection.find_one(
            {"compressor_id": compressor_id},
            sort=[("timestamp", -1)]
        )
 
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"ไม่พบข้อมูลของ {compressor_id}"
        )
 
    # ── Pull raw sensor inputs from the stored snapshot ──
    inputs = doc.get("inputs_snapshot", {})
 
    # ── Compute cycle points ─────────────────────────────
    cycle = compute_cycle_points(inputs)
 
    # ── Build saturation dome (cached-friendly; same for all) ──
    dome = build_saturation_dome()
 
    # ── Format timestamp ─────────────────────────────────
    tz_th = timezone(timedelta(hours=7))
    ts = doc.get("timestamp")
    if ts and hasattr(ts, "astimezone"):
        ts_str = ts.astimezone(tz_th).isoformat()
    else:
        ts_str = str(ts) if ts else None
 
    return {
        "compressor_id": compressor_id,
        "timestamp": ts_str,
        "record_id": str(doc["_id"]),
        "saturation_dome": dome,
        "cycle": cycle,
    }
 
 
# =========================================================
# RUN SERVER
# =========================================================
 
if __name__ == "__main__":
 
    import uvicorn
 
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )