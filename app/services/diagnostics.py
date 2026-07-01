"""
Compressor diagnosis from live sensor inputs (CoolProp + alarms).

Logic preserved from original main.py. Assumes SH=5K and eta_is=0.70 when
suction/discharge temps are missing. Called by metrics POST endpoint.
"""

import logging
import math

import CoolProp.CoolProp as CP

from app.core.constants import (
    DEFAULT_ISENTROPIC_EFF,
    DEFAULT_SUPERHEAT_K,
    FLUID,
    POWER_FACTOR,
    VOLTAGE,
)
from app.schemas.metrics import CompressorDataInput
from app.services.utils import pressure_kgcm2_to_pa, safe_round

logger = logging.getLogger(__name__)


def diagnose_compressor(data: CompressorDataInput):
    """Run full thermodynamic diagnosis and return result dict with alarms."""
    fluid = FLUID
    voltage = VOLTAGE
    power_factor = POWER_FACTOR
    alarms = []
    result = {
        "q_e_kw": "--",
        "power_kw": "--",
        "cop": "--",
        "superheat_suc": "--",
        "subcooling": "--",
        "pressure_ratio": "--",
        "systems": {
            "sensor": {"status": "Unknown", "text": "--"},
            "condenser": {"status": "Unknown", "text": "--"},
        },
    }
    try:
        # =========================================================
        # Pressure conversion
        # =========================================================
        p_suc_pa = pressure_kgcm2_to_pa(data.sp_kg) if data.sp_kg is not None else None
        p_dis_pa = pressure_kgcm2_to_pa(data.dp_kg) if data.dp_kg is not None else None
        t_suc_k = (data.st_c + 273.15) if data.st_c is not None else None
        t_dis_k = (data.dt_c + 273.15) if data.dt_c is not None else None
        h1 = None
        h2 = None
        h2s = None
        h3 = None
        sh_mode = "assumed"
        dt_mode = "assumed"

        # =========================================================
        # Enthalpy — suction (point 1)
        # =========================================================
        if p_suc_pa:
            if t_suc_k:
                h1 = CP.PropsSI("H", "P", p_suc_pa, "T", t_suc_k, fluid)
                sh_mode = "measured"
            else:
                t_sat_suc_k = CP.PropsSI("T", "P", p_suc_pa, "Q", 1, fluid)
                t1_assume = t_sat_suc_k + DEFAULT_SUPERHEAT_K
                h1 = CP.PropsSI("H", "P", p_suc_pa, "T", t1_assume, fluid)
                t_suc_k = t1_assume
                sh_mode = "assumed_5K"
        if h1 is not None and p_dis_pa and t_suc_k and p_suc_pa:
            s1 = CP.PropsSI("S", "P", p_suc_pa, "T", t_suc_k, fluid)
            h2s = CP.PropsSI("H", "P", p_dis_pa, "S", s1, fluid)

        # =========================================================
        # Enthalpy — discharge (point 2)
        # =========================================================
        if p_dis_pa:
            if t_dis_k:
                h2 = CP.PropsSI("H", "P", p_dis_pa, "T", t_dis_k, fluid)
                dt_mode = "measured"
            elif h2s is not None and h1 is not None:
                h2 = h1 + (h2s - h1) / DEFAULT_ISENTROPIC_EFF
                dt_mode = "assumed_eta07"
        if p_dis_pa and data.liquid_temp_c is not None:
            h3 = CP.PropsSI("H", "P", p_dis_pa, "T", data.liquid_temp_c + 273.15, fluid)
        elif p_dis_pa:
            try:
                h3 = CP.PropsSI("H", "P", p_dis_pa, "Q", 0, fluid)
            except (ValueError, RuntimeError):
                h3 = None

        # =========================================================
        # Performance
        # =========================================================
        power_kw = None
        if data.current_amp is not None:
            power_kw = (math.sqrt(3) * voltage * data.current_amp * power_factor) / 1000
        cop = None
        q_e_kw = None
        m_dot = None
        if h1 is not None and h2 is not None and h3 is not None and (h2 - h1) != 0:
            cop = (h1 - h3) / (h2 - h1)
        if cop is not None and power_kw is not None and power_kw > 0:
            q_e_kw = power_kw * cop
            m_dot = (q_e_kw * 1000) / (h1 - h3)

        # =========================================================
        # Alarms
        # =========================================================
        # High stage COP is inherently higher (3-5) than booster/single (1.5-2.5)
        cop_threshold = 2.5 if data.compressor_type == "high_stage" else 1.5
        if cop is not None and cop < cop_threshold:
            alarms.append(
                {
                    "severity": "Warning",
                    "title": "Low COP",
                    "message": "ประสิทธิภาพระบบต่ำ",
                    "possible_causes": [
                        "โหลดสูงเกิน",
                        "Compressor efficiency ต่ำ",
                        "Condenser ทำงานไม่ดี",
                    ],
                    "recommendation": ["ตรวจ compressor", "ตรวจ condenser", "ตรวจโหลดระบบ"],
                }
            )

        superheat = None
        if p_suc_pa and data.st_c is not None:
            t_sat_suc = CP.PropsSI("T", "P", p_suc_pa, "Q", 1, fluid) - 273.15
            superheat = data.st_c - t_sat_suc

        if superheat is not None:
            if superheat > 15:
                alarms.append(
                    {
                        "severity": "Warning",
                        "title": "High Superheat",
                        "message": "Superheat สูงเกินปกติ",
                        "possible_causes": [
                            "น้ำยาเข้า evaporator ไม่พอ",
                            "Expansion valve เปิดน้อย",
                            "โหลด evaporator ต่ำ",
                        ],
                        "recommendation": ["ตรวจ TXV", "ตรวจระดับน้ำยา", "ตรวจโหลดห้องเย็น"],
                    }
                )
            elif superheat < 0:
                alarms.append(
                    {
                        "severity": "Critical",
                        "title": "Liquid Floodback",
                        "message": f"น้ำยาเหลวเข้า compressor (Superheat = {safe_round(superheat)} K) — หยุดเครื่องทันที",
                        "possible_causes": [
                            "TXV เปิดมากเกินไป",
                            "โหลด evaporator ลดลงกะทันหัน",
                            "น้ำยาล้น evaporator",
                        ],
                        "recommendation": ["หยุดเครื่องทันที", "ตรวจ TXV", "ตรวจระดับน้ำยา"],
                    }
                )
            elif superheat < 2:
                alarms.append(
                    {
                        "severity": "Warning",
                        "title": "Low Superheat",
                        "message": "เสี่ยง liquid floodback",
                        "possible_causes": [
                            "TXV เปิดมากเกิน",
                            "น้ำยาเข้า compressor เป็น liquid",
                        ],
                        "recommendation": ["ตรวจ TXV", "ตรวจ suction line", "เช็ค compressor safety"],
                    }
                )

        subcooling = None
        approach = None
        if p_dis_pa and data.liquid_temp_c is not None:
            t_sat_dis = CP.PropsSI("T", "P", p_dis_pa, "Q", 0, fluid) - 273.15
            subcooling = t_sat_dis - data.liquid_temp_c

        if p_dis_pa and data.condenser_temp_c is not None:
            t_sat_dis2 = CP.PropsSI("T", "P", p_dis_pa, "Q", 1, fluid) - 273.15
            approach = t_sat_dis2 - data.condenser_temp_c
            if approach > 15:
                alarms.append(
                    {
                        "severity": "Critical",
                        "title": "High Condensing Temperature",
                        "message": "Condenser ระบายความร้อนได้ไม่ดี",
                        "possible_causes": [
                            "Condenser สกปรก",
                            "พัดลม condenser เสีย",
                            "น้ำหล่อเย็นร้อนเกิน",
                        ],
                        "recommendation": ["ล้าง condenser", "ตรวจพัดลม", "ตรวจ cooling water"],
                    }
                )
        pressure_ratio = (
            (p_dis_pa / p_suc_pa) if (p_suc_pa and p_dis_pa and p_suc_pa > 0) else None
        )
        if pressure_ratio is not None and pressure_ratio > 12:
            alarms.append(
                {
                    "severity": "Critical",
                    "title": "High Pressure Ratio",
                    "message": f"Pressure ratio สูงเกินอันตราย ({safe_round(pressure_ratio)}) — เสี่ยง compressor overload",
                    "possible_causes": [
                        "Suction pressure ต่ำผิดปกติ",
                        "Discharge pressure สูงผิดปกติ",
                        "Condenser ระบายความร้อนไม่ได้",
                    ],
                    "recommendation": ["ตรวจแรงดัน suction/discharge", "ตรวจ condenser", "พิจารณาหยุดเครื่อง"],
                }
            )

        sensor_status = "Unknown"
        if superheat is not None:
            sensor_status = "Normal" if 2 <= superheat <= 15 else "Warning"
        h1_kj = round(h1 / 1000, 2) if h1 is not None else None
        h2_kj = round(h2 / 1000, 2) if h2 is not None else None
        h2s_kj = round(h2s / 1000, 2) if h2s is not None else None
        h3_kj = round(h3 / 1000, 2) if h3 is not None else None

        t_evap_c = (
            round(CP.PropsSI("T", "P", p_suc_pa, "Q", 1, fluid) - 273.15, 2) if p_suc_pa else None
        )

        t_cond_c = (
            round(CP.PropsSI("T", "P", p_dis_pa, "Q", 0, fluid) - 273.15, 2) if p_dis_pa else None
        )

        eta_is_pct = (
            round((h2s - h1) / (h2 - h1) * 100, 1)
            if (h2s is not None and h1 is not None and h2 is not None and (h2 - h1) != 0)
            else None
        )

        q_l_kjkg = round((h1 - h3) / 1000, 2) if (h1 is not None and h3 is not None) else None
        w_comp_kjkg = round((h2 - h1) / 1000, 2) if (h1 is not None and h2 is not None) else None
        m_dot_kgh = round(m_dot * 3600, 1) if m_dot else None

        result.update(
            {
                "power_kw": safe_round(power_kw),
                "cop": safe_round(cop, 4),
                "q_e_kw": safe_round(q_e_kw),
                "superheat_suc": safe_round(superheat),
                "subcooling": safe_round(subcooling),
                "pressure_ratio": safe_round(pressure_ratio),
                "m_dot_kgh": safe_round(m_dot_kgh),
                "alarms": alarms,
                "compressor_type": data.compressor_type,
                "cop_threshold": cop_threshold,
                "modes": {"sh_mode": sh_mode, "dt_mode": dt_mode},
                "enthalpy": {
                    "t_evap_c": t_evap_c,
                    "t_cond_c": t_cond_c,
                    "h1": h1_kj,
                    "h2": h2_kj,
                    "h2s": h2s_kj,
                    "h3": h3_kj,
                    "eta_is_pct": eta_is_pct,
                    "q_l_kjkg": q_l_kjkg,
                    "w_comp_kjkg": w_comp_kjkg,
                },
                "systems": {
                    "sensor": {
                        "status": sensor_status,
                        "text": f"Superheat = {safe_round(superheat)}",
                    },
                    "condenser": {
                        "status": (
                            "Critical" if approach is not None and approach > 15
                            else "Warning" if approach is not None and approach > 8
                            else "Normal" if approach is not None
                            else "Unknown"
                        ),
                        "text": f"Approach = {safe_round(approach)} K" if approach is not None else "--",
                    },
                },
            }
        )
        
        return result
    except Exception:
        logger.exception("diagnose_compressor failed")
        return result
