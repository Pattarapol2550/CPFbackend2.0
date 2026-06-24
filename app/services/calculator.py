"""
Single- and two-stage refrigeration cycle calculators.

Pure calculation logic (no HTTP). Used by calculator router endpoints.
"""

import math

import CoolProp.CoolProp as CP

from app.core.constants import FLUID
from app.schemas.calculator import CalcInput, TwoStageInput
from app.services.utils import pressure_kgcm2_to_pa


def calculate_single_stage(data: CalcInput) -> dict:
    """Run single-stage cycle calculation from CalcInput."""
    fluid = FLUID
    P_comp_kW = (math.sqrt(3) * data.voltage * data.current * data.power_factor) / 1000
    P_low = pressure_kgcm2_to_pa(data.sp)
    P_high = pressure_kgcm2_to_pa(data.dp)
    T_evap = CP.PropsSI("T", "P", P_low, "Q", 1, fluid) - 273.15
    T_cond = CP.PropsSI("T", "P", P_high, "Q", 0, fluid) - 273.15
    if data.st is not None:
        SH = data.st - T_evap
        h1 = CP.PropsSI("H", "P", P_low, "T", data.st + 273.15, fluid) / 1000
        st_used = data.st
        sh_mode = "measured"
    else:
        SH = data.sh_default
        h1 = CP.PropsSI("H", "P", P_low, "T", T_evap + SH + 273.15, fluid) / 1000
        st_used = T_evap + SH
        sh_mode = "assumed"

    T1_K = st_used + 273.15
    s1 = CP.PropsSI("S", "P", P_low, "T", T1_K, fluid)
    h2s = CP.PropsSI("H", "P", P_high, "S", s1, fluid) / 1000
    T2s_C = CP.PropsSI("T", "P", P_high, "S", s1, fluid) - 273.15

    if data.dt is not None:
        h2 = CP.PropsSI("H", "P", P_high, "T", data.dt + 273.15, fluid) / 1000
        eta_is_actual = (h2s - h1) / (h2 - h1) if (h2 - h1) != 0 else None
        dt_used = data.dt
        dt_mode = "measured"
    else:
        h2 = h1 + (h2s - h1) / data.eta_is
        eta_is_actual = data.eta_is
        dt_used = CP.PropsSI("T", "P", P_high, "H", h2 * 1000, fluid) - 273.15
        dt_mode = "assumed"

    hf_cond = CP.PropsSI("H", "P", P_high, "Q", 0, fluid) / 1000
    if data.liquid_temp is not None:
        SC = T_cond - data.liquid_temp
        h3 = CP.PropsSI("H", "P", P_high, "T", data.liquid_temp + 273.15, fluid) / 1000
        liq_mode = "measured"
    else:
        SC = 0.0
        h3 = hf_cond
        liq_mode = "assumed"

    h4 = h3
    q_L = h1 - h4
    w_comp = h2 - h1
    q_H = h2 - h3
    COP = q_L / w_comp
    Q_e = P_comp_kW * COP
    Q_H_kW = P_comp_kW + Q_e
    m_dot = Q_e / q_L
    TR = Q_e / 3.517
    warnings = []

    if SH < 0:
        warnings.append({"level": "danger", "msg": f"Superheat = {SH:.1f} K — มีของเหลวเข้า compressor!"})
    if SH > 15:
        warnings.append({"level": "warning", "msg": f"Superheat สูง ({SH:.1f} K)"})
    if SC < 0:
        warnings.append({"level": "danger", "msg": f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP < 1.5:
        warnings.append({"level": "warning", "msg": f"COP = {COP:.2f} — ต่ำกว่าปกติ"})
    if eta_is_actual and eta_is_actual < 0.55:
        warnings.append({"level": "warning", "msg": f"eta_is = {eta_is_actual * 100:.1f}% — ต่ำมาก"})

    return {
        "modes": {
            "sh_mode": sh_mode,
            "dt_mode": dt_mode,
            "liq_mode": liq_mode,
            "st_used": round(st_used, 2),
            "dt_used": round(dt_used, 2),
        },
        "inputs": {"P_low_kPa": round(P_low / 1000, 2), "P_high_kPa": round(P_high / 1000, 2)},
        "saturation": {
            "T_evap": round(T_evap, 2),
            "T_cond": round(T_cond, 2),
            "superheat": round(SH, 2),
            "subcool": round(SC, 2),
        },
        "enthalpy": {
            "h1": round(h1, 2),
            "h2": round(h2, 2),
            "h3": round(h3, 2),
            "h4": round(h4, 2),
            "h2s": round(h2s, 2),
            "T2s_degC": round(T2s_C, 2),
        },
        "performance": {
            "P_comp_kW": round(P_comp_kW, 3),
            "q_L": round(q_L, 2),
            "w_comp": round(w_comp, 2),
            "q_H": round(q_H, 2),
            "COP": round(COP, 4),
            "Q_e_kW": round(Q_e, 3),
            "Q_H_kW": round(Q_H_kW, 3),
            "TR": round(TR, 2),
            "m_dot_kgs": round(m_dot, 5),
            "m_dot_kgh": round(m_dot * 3600, 2),
            "eta_isentropic": round(eta_is_actual * 100, 1) if eta_is_actual else None,
        },
        "warnings": warnings,
    }


def calculate_two_stage(data: TwoStageInput) -> dict:
    """Run two-stage (booster + high) cycle calculation from TwoStageInput."""
    fluid = FLUID
    P_low = pressure_kgcm2_to_pa(data.sp)
    P_int = CP.PropsSI("P", "T", data.t_int + 273.15, "Q", 1, fluid)
    P_high = pressure_kgcm2_to_pa(data.dp)
    T_evap = CP.PropsSI("T", "P", P_low, "Q", 1, fluid) - 273.15
    T_cond = CP.PropsSI("T", "P", P_high, "Q", 0, fluid) - 273.15

    if data.st is not None:
        SH = data.st - T_evap
        h1 = CP.PropsSI("H", "P", P_low, "T", data.st + 273.15, fluid) / 1000
        st_used = data.st
        sh_mode = "measured"
    else:
        SH = data.sh_default
        h1 = CP.PropsSI("H", "P", P_low, "T", T_evap + SH + 273.15, fluid) / 1000
        st_used = T_evap + SH
        sh_mode = "assumed"

    s1 = CP.PropsSI("S", "P", P_low, "T", st_used + 273.15, fluid)
    h2s_b = CP.PropsSI("H", "P", P_int, "S", s1, fluid) / 1000
    if data.dt_booster is not None:
        h2 = CP.PropsSI("H", "P", P_int, "T", data.dt_booster + 273.15, fluid) / 1000
        eta_b = (h2s_b - h1) / (h2 - h1) if (h2 - h1) != 0 else None
        dt_b_used = data.dt_booster
        dt_b_mode = "measured"
    else:
        h2 = h1 + (h2s_b - h1) / data.eta_booster
        eta_b = data.eta_booster
        dt_b_used = CP.PropsSI("T", "P", P_int, "H", h2 * 1000, fluid) - 273.15
        dt_b_mode = "assumed"

    h3 = CP.PropsSI("H", "P", P_int, "Q", 1, fluid) / 1000
    s3 = CP.PropsSI("S", "P", P_int, "Q", 1, fluid)
    h4s = CP.PropsSI("H", "P", P_high, "S", s3, fluid) / 1000
    if data.dt_high is not None:
        h4 = CP.PropsSI("H", "P", P_high, "T", data.dt_high + 273.15, fluid) / 1000
        eta_h = (h4s - h3) / (h4 - h3) if (h4 - h3) != 0 else None
        dt_h_used = data.dt_high
        dt_h_mode = "measured"
    else:
        h4 = h3 + (h4s - h3) / data.eta_high
        eta_h = data.eta_high
        dt_h_used = CP.PropsSI("T", "P", P_high, "H", h4 * 1000, fluid) - 273.15
        dt_h_mode = "assumed"

    hf_cond = CP.PropsSI("H", "P", P_high, "Q", 0, fluid) / 1000
    if data.liquid_temp is not None:
        SC = T_cond - data.liquid_temp
        h5 = CP.PropsSI("H", "P", P_high, "T", data.liquid_temp + 273.15, fluid) / 1000
        liq_mode = "measured"
    else:
        SC = 0.0
        h5 = hf_cond
        liq_mode = "assumed"

    h6 = h5
    hf_int = CP.PropsSI("H", "P", P_int, "Q", 0, fluid) / 1000
    h7 = hf_int
    # Flash intercooler mass balance: ṁ_H/ṁ_L = (h2 - hf_int) / (hg_int - hf_int)
    ratio = (h2 - h7) / (h3 - h7)
    W_booster = (math.sqrt(3) * data.voltage * data.i_booster * data.power_factor) / 1000
    W_high = (math.sqrt(3) * data.voltage * data.i_high * data.power_factor) / 1000
    W_total = W_booster + W_high
    m_low = W_booster / (h2 - h1)
    m_high = m_low * ratio
    Q_e = m_low * (h1 - h7)
    Q_cond = m_high * (h4 - h5)
    COP_system = Q_e / W_total
    TR = Q_e / 3.517
    warnings = []

    if SH < 0:
        warnings.append({"level": "danger", "msg": f"Superheat = {SH:.1f} K — liquid เข้า booster!"})
    if SH > 15:
        warnings.append({"level": "warning", "msg": f"Superheat สูง ({SH:.1f} K)"})
    if SC < 0:
        warnings.append({"level": "danger", "msg": f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP_system < 1.2:
        warnings.append({"level": "warning", "msg": f"COP = {COP_system:.2f} — ต่ำกว่าปกติ"})
    if ratio > 1.5:
        warnings.append({"level": "warning", "msg": f"m_high/m_low = {ratio:.2f} — สูงมาก ตรวจ intercooler"})
        
    return {
        "modes": {
            "sh_mode": sh_mode,
            "dt_b_mode": dt_b_mode,
            "dt_h_mode": dt_h_mode,
            "liq_mode": liq_mode,
            "st_used": round(st_used, 2),
            "dt_b_used": round(dt_b_used, 2),
            "dt_h_used": round(dt_h_used, 2),
        },
        "pressures": {
            "P_low_kPa": round(P_low / 1000, 2),
            "P_int_kPa": round(P_int / 1000, 2),
            "P_int_kgcm2g": round(P_int / 98066.5 - 1.0332, 3),
            "P_high_kPa": round(P_high / 1000, 2),
        },
        "saturation": {
            "T_evap": round(T_evap, 2),
            "T_int": round(data.t_int, 2),
            "T_cond": round(T_cond, 2),
            "superheat": round(SH, 2),
            "subcool": round(SC, 2),
        },
        "enthalpy": {
            "h1": round(h1, 2),
            "h2": round(h2, 2),
            "h2s_b": round(h2s_b, 2),
            "h3": round(h3, 2),
            "h4": round(h4, 2),
            "h4s": round(h4s, 2),
            "h5": round(h5, 2),
            "h6": round(h6, 2),
            "hf_int": round(hf_int, 2),
            "h7": round(h7, 2),
        },
        "performance": {
            "W_booster_kW": round(W_booster, 3),
            "W_high_kW": round(W_high, 3),
            "W_total_kW": round(W_total, 3),
            "m_low_kgs": round(m_low, 5),
            "m_low_kgh": round(m_low * 3600, 2),
            "m_high_kgs": round(m_high, 5),
            "m_high_kgh": round(m_high * 3600, 2),
            "ratio_mh_ml": round(ratio, 3),
            "Q_e_kW": round(Q_e, 3),
            "Q_e_TR": round(TR, 2),
            "Q_cond_kW": round(Q_cond, 3),
            "COP_system": round(COP_system, 4),
            "eta_booster": round(eta_b * 100, 1) if eta_b else None,
            "eta_high": round(eta_h * 100, 1) if eta_h else None,
        },
        "warnings": warnings,
    }
