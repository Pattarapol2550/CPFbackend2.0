"""
thermo_service.py
ฟังก์ชันคำนวณ thermodynamics ทั้งหมด — แยกออกจาก routing layer
เพื่อให้ test และ debug ได้ง่ายขึ้น
"""
import math
import logging
from typing import Optional

import numpy as np
import CoolProp.CoolProp as CP

from config import FLUID, DEFAULT_VOLTAGE, DEFAULT_PF

logger = logging.getLogger(__name__)

# ── Unit conversion helpers ────────────────────────────────

def kgcm2_to_pa(kgcm2: float) -> float:
    """kg/cm² gauge → Pascal absolute"""
    return kgcm2 * 98066.5 + 101325


def c_to_k(celsius: float) -> float:
    return celsius + 273.15


def safe_round(value, digit: int = 2):
    """คืน '--' ถ้า value เป็น None หรือคำนวณไม่ได้"""
    if value is None:
        return "--"
    try:
        return round(value, digit)
    except Exception:
        return "--"


# ── Alarm builder ──────────────────────────────────────────

def _make_alarm(severity: str, title: str, message: str,
                causes: list[str], recommendations: list[str]) -> dict:
    return {
        "severity":         severity,
        "title":            title,
        "message":          message,
        "possible_causes":  causes,
        "recommendation":   recommendations,
    }


# ── Enthalpy calculation ───────────────────────────────────

def _calc_enthalpies(p_suc_pa, p_dis_pa, t_suc_k, t_dis_k, liquid_temp_c):
    """
    คำนวณ enthalpy h1, h2, h2s, h3
    คืน tuple (h1, h2, h2s, h3, sh_mode, dt_mode, t_suc_k)
    """
    h1 = h2 = h2s = h3 = None
    sh_mode = dt_mode = "assumed"

    if p_suc_pa:
        if t_suc_k:
            h1      = CP.PropsSI("H", "P", p_suc_pa, "T", t_suc_k, FLUID)
            sh_mode = "measured"
        else:
            t_sat   = CP.PropsSI("T", "P", p_suc_pa, "Q", 1, FLUID)
            t_suc_k = t_sat + 5.0
            h1      = CP.PropsSI("H", "P", p_suc_pa, "T", t_suc_k, FLUID)
            sh_mode = "assumed_5K"

    if h1 is not None and p_dis_pa and t_suc_k and p_suc_pa:
        s1  = CP.PropsSI("S", "P", p_suc_pa, "T", t_suc_k, FLUID)
        h2s = CP.PropsSI("H", "P", p_dis_pa, "S", s1,      FLUID)

    if p_dis_pa:
        if t_dis_k:
            h2      = CP.PropsSI("H", "P", p_dis_pa, "T", t_dis_k, FLUID)
            dt_mode = "measured"
        elif h2s is not None and h1 is not None:
            h2      = h1 + (h2s - h1) / 0.70
            dt_mode = "assumed_eta07"

    if p_dis_pa:
        if liquid_temp_c is not None:
            h3 = CP.PropsSI("H", "P", p_dis_pa, "T", c_to_k(liquid_temp_c), FLUID)
        else:
            try:
                h3 = CP.PropsSI("H", "P", p_dis_pa, "Q", 0, FLUID)
            except Exception:
                h3 = None

    return h1, h2, h2s, h3, sh_mode, dt_mode, t_suc_k


# ── Main diagnostic function ───────────────────────────────

def diagnose_compressor(data) -> dict:
    """
    รับ CompressorDataInput → คืน dict ผลวิเคราะห์
    แยก try/except เป็นส่วนๆ เพื่อให้ debug ง่าย
    """
    alarms: list[dict] = []
    result = {
        "q_e_kw": "--", "power_kw": "--", "cop": "--",
        "superheat_suc": "--", "subcooling": "--", "pressure_ratio": "--",
        "systems": {
            "sensor":    {"status": "Unknown", "text": "--"},
            "condenser": {"status": "Unknown", "text": "--"},
        },
    }

    try:
        p_suc_pa = kgcm2_to_pa(data.sp_kg) if data.sp_kg is not None else None
        p_dis_pa = kgcm2_to_pa(data.dp_kg) if data.dp_kg is not None else None
        t_suc_k  = c_to_k(data.st_c)       if data.st_c  is not None else None
        t_dis_k  = c_to_k(data.dt_c)       if data.dt_c  is not None else None

        h1, h2, h2s, h3, sh_mode, dt_mode, t_suc_k = _calc_enthalpies(
            p_suc_pa, p_dis_pa, t_suc_k, t_dis_k, data.liquid_temp_c
        )

        # ── Power ──────────────────────────────────────────
        power_kw = None
        if data.current_amp is not None:
            power_kw = (math.sqrt(3) * DEFAULT_VOLTAGE * data.current_amp * DEFAULT_PF) / 1000

        # ── COP & Cooling capacity ─────────────────────────
        cop = q_e_kw = m_dot = None
        if h1 and h2 and h3 and (h2 - h1) != 0:
            cop = (h1 - h3) / (h2 - h1)
        if cop and power_kw and power_kw > 0:
            q_e_kw = power_kw * cop
            m_dot  = (q_e_kw * 1000) / (h1 - h3)

        if cop is not None and cop < 1.5:
            alarms.append(_make_alarm(
                "Warning", "Low COP", "ประสิทธิภาพระบบต่ำ",
                ["โหลดสูงเกิน", "Compressor efficiency ต่ำ", "Condenser ทำงานไม่ดี"],
                ["ตรวจ compressor", "ตรวจ condenser", "ตรวจโหลดระบบ"],
            ))

        # ── Superheat ──────────────────────────────────────
        superheat = None
        if p_suc_pa and data.st_c is not None:
            t_sat_suc = CP.PropsSI("T", "P", p_suc_pa, "Q", 1, FLUID) - 273.15
            superheat = data.st_c - t_sat_suc

        if superheat is not None:
            if superheat > 15:
                alarms.append(_make_alarm(
                    "Warning", "High Superheat", "Superheat สูงเกินปกติ",
                    ["น้ำยาเข้า evaporator ไม่พอ", "Expansion valve เปิดน้อย", "โหลด evaporator ต่ำ"],
                    ["ตรวจ TXV", "ตรวจระดับน้ำยา", "ตรวจโหลดห้องเย็น"],
                ))
            elif superheat < 2:
                alarms.append(_make_alarm(
                    "Warning", "Low Superheat", "เสี่ยง liquid floodback",
                    ["TXV เปิดมากเกิน", "น้ำยาเข้า compressor เป็น liquid"],
                    ["ตรวจ TXV", "ตรวจ suction line", "เช็ค compressor safety"],
                ))

        # ── Subcooling & Condenser approach ────────────────
        subcooling = None
        if p_dis_pa and data.liquid_temp_c is not None:
            t_sat_dis  = CP.PropsSI("T", "P", p_dis_pa, "Q", 0, FLUID) - 273.15
            subcooling = t_sat_dis - data.liquid_temp_c

            if data.condenser_temp_c is not None:
                t_sat_dis2 = CP.PropsSI("T", "P", p_dis_pa, "Q", 1, FLUID) - 273.15
                approach   = t_sat_dis2 - data.condenser_temp_c
                if approach > 15:
                    alarms.append(_make_alarm(
                        "Critical", "High Condensing Temperature", "Condenser ระบายความร้อนได้ไม่ดี",
                        ["Condenser สกปรก", "พัดลม condenser เสีย", "น้ำหล่อเย็นร้อนเกิน"],
                        ["ล้าง condenser", "ตรวจพัดลม", "ตรวจ cooling water"],
                    ))

        # ── Derived values ─────────────────────────────────
        pressure_ratio = (p_dis_pa / p_suc_pa) if (p_suc_pa and p_dis_pa and p_suc_pa > 0) else None
        sensor_status  = "Unknown"
        if superheat is not None:
            sensor_status = "Normal" if 2 <= superheat <= 15 else "Warning"

        h1_kj      = round(h1  / 1000, 2) if h1  else None
        h2_kj      = round(h2  / 1000, 2) if h2  else None
        h2s_kj     = round(h2s / 1000, 2) if h2s else None
        h3_kj      = round(h3  / 1000, 2) if h3  else None
        t_evap_c   = round(CP.PropsSI("T","P",p_suc_pa,"Q",1,FLUID) - 273.15, 2) if p_suc_pa else None
        t_cond_c   = round(CP.PropsSI("T","P",p_dis_pa,"Q",0,FLUID) - 273.15, 2) if p_dis_pa else None
        eta_is_pct = round((h2s - h1) / (h2 - h1) * 100, 1) if (h2s and h1 and h2 and (h2 - h1) != 0) else None
        q_l_kgkg   = round((h1 - h3) / 1000, 2) if (h1 and h3) else None
        w_comp_kgkg= round((h2 - h1) / 1000, 2) if (h1 and h2) else None
        m_dot_kgh  = round(m_dot * 3600, 1)      if m_dot       else None

        result.update({
            "power_kw":       safe_round(power_kw),
            "cop":            safe_round(cop, 4),
            "q_e_kw":         safe_round(q_e_kw),
            "superheat_suc":  safe_round(superheat),
            "subcooling":     safe_round(subcooling),
            "pressure_ratio": safe_round(pressure_ratio),
            "m_dot_kgh":      safe_round(m_dot_kgh),
            "alarms":         alarms,
            "modes":          {"sh_mode": sh_mode, "dt_mode": dt_mode},
            "enthalpy": {
                "t_evap_c": t_evap_c, "t_cond_c": t_cond_c,
                "h1": h1_kj, "h2": h2_kj, "h2s": h2s_kj, "h3": h3_kj,
                "eta_is_pct": eta_is_pct, "q_l_kgkg": q_l_kgkg, "w_comp_kgkg": w_comp_kgkg,
            },
            "systems": {
                "sensor":    {"status": sensor_status, "text": f"Superheat = {safe_round(superheat)}"},
                "condenser": {"status": "Unknown", "text": "--"},
            },
        })

    except Exception as e:
        logger.error("diagnose_compressor error: %s", e, exc_info=True)

    return result


# ── P-H Diagram helpers ────────────────────────────────────

def build_saturation_dome(n_points: int = 60) -> dict:
    T_min_K  = 223.15
    T_crit_K = CP.PropsSI("Tcrit", FLUID)
    T_max_K  = T_crit_K - 0.5
    liq_points, vap_points = [], []

    for T in np.linspace(T_min_K, T_max_K, n_points):
        try:
            liq_points.append({
                "h": round(CP.PropsSI("H","T",T,"Q",0,FLUID) / 1000, 2),
                "p": round(CP.PropsSI("P","T",T,"Q",0,FLUID) / 1e6,  4),
            })
            vap_points.append({
                "h": round(CP.PropsSI("H","T",T,"Q",1,FLUID) / 1000, 2),
                "p": round(CP.PropsSI("P","T",T,"Q",0,FLUID) / 1e6,  4),
            })
        except Exception:
            continue

    return {
        "liquid":   liq_points,
        "vapour":   vap_points,
        "critical": {
            "h": round(CP.PropsSI("H","T",T_crit_K,"Q",0,FLUID) / 1000, 2),
            "p": round(CP.PropsSI("P","T",T_crit_K,"Q",0,FLUID) / 1e6,  4),
        },
    }


def compute_cycle_points(inputs: dict) -> dict:
    sp_kg = inputs.get("sp_kg")
    dp_kg = inputs.get("dp_kg")
    st_c  = inputs.get("st_c")
    dt_c  = inputs.get("dt_c")
    liq_c = inputs.get("liquid_temp_c")

    points = {
        "point1": None, "point2": None, "point2s": None,
        "point3": None, "point4": None,
        "p_suc_mpa": None, "p_dis_mpa": None,
        "t_sat_suc_c": None, "t_sat_dis_c": None,
        "isentropic_efficiency": None,
    }

    try:
        p_suc_pa = kgcm2_to_pa(float(sp_kg)) if sp_kg is not None else None
        p_dis_pa = kgcm2_to_pa(float(dp_kg)) if dp_kg is not None else None

        if p_suc_pa:
            points["p_suc_mpa"]   = round(p_suc_pa / 1e6, 4)
            points["t_sat_suc_c"] = round(CP.PropsSI("T","P",p_suc_pa,"Q",1,FLUID) - 273.15, 2)
        if p_dis_pa:
            points["p_dis_mpa"]   = round(p_dis_pa / 1e6, 4)
            points["t_sat_dis_c"] = round(CP.PropsSI("T","P",p_dis_pa,"Q",1,FLUID) - 273.15, 2)

        if p_suc_pa and st_c is not None:
            t1_k = c_to_k(float(st_c))
            h1   = CP.PropsSI("H","P",p_suc_pa,"T",t1_k,FLUID) / 1000
            s1   = CP.PropsSI("S","P",p_suc_pa,"T",t1_k,FLUID)
            points["point1"] = {"h": round(h1,2), "p": round(p_suc_pa/1e6,4),
                                 "label": "1 — Comp. inlet", "t_c": round(float(st_c),2)}
            if p_dis_pa:
                h2s = CP.PropsSI("H","P",p_dis_pa,"S",s1,FLUID) / 1000
                points["point2s"] = {"h": round(h2s,2), "p": round(p_dis_pa/1e6,4),
                                     "label": "2s — Isentropic"}

        if p_dis_pa and points["point1"] and points["point2s"]:
            h1_val  = points["point1"]["h"]
            h2s_val = points["point2s"]["h"]
            if dt_c is not None:
                h2      = CP.PropsSI("H","P",p_dis_pa,"T",c_to_k(float(dt_c)),FLUID) / 1000
                dt_used = round(float(dt_c), 2)
                eta     = round((h2s_val - h1_val) / (h2 - h1_val), 4) if (h2 - h1_val) != 0 else None
            else:
                h2      = h1_val + (h2s_val - h1_val) / 0.70
                dt_used = round(CP.PropsSI("T","P",p_dis_pa,"H",h2*1000,FLUID) - 273.15, 2)
                eta     = 0.70
            points["isentropic_efficiency"] = eta
            points["point2"] = {"h": round(h2,2), "p": round(p_dis_pa/1e6,4),
                                 "label": "2 — Comp. outlet", "t_c": dt_used}

        if p_dis_pa:
            if liq_c is not None:
                h3   = CP.PropsSI("H","P",p_dis_pa,"T",c_to_k(float(liq_c)),FLUID) / 1000
                t3_c = round(float(liq_c), 2)
            else:
                h3   = CP.PropsSI("H","P",p_dis_pa,"Q",0,FLUID) / 1000
                t3_c = round(CP.PropsSI("T","P",p_dis_pa,"Q",0,FLUID) - 273.15, 2)

            points["point3"] = {"h": round(h3,2), "p": round(p_dis_pa/1e6,4),
                                 "label": "3 — Cond. outlet", "t_c": t3_c}
            if p_suc_pa:
                points["point4"] = {"h": round(h3,2), "p": round(p_suc_pa/1e6,4),
                                    "label": "4 — Evap. inlet"}

    except Exception as e:
        logger.error("compute_cycle_points error: %s", e, exc_info=True)

    return points
