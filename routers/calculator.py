"""
routers/calculator.py
One-stage และ Two-stage ammonia cycle calculator
"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
import CoolProp.CoolProp as CP

from config import FLUID

router = APIRouter(prefix="/api", tags=["calculator"])


def _kpa(p: float) -> float:
    """kg/cm² gauge → Pascal absolute"""
    return p * 98066.5 + 101325


def _warnings_single(SH, SC, COP, eta_is) -> list[dict]:
    w = []
    if SH < 0:             w.append({"level": "danger",  "msg": f"Superheat = {SH:.1f} K — มีของเหลวเข้า compressor!"})
    if SH > 15:            w.append({"level": "warning", "msg": f"Superheat สูง ({SH:.1f} K)"})
    if SC < 0:             w.append({"level": "danger",  "msg": f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP < 1.5:          w.append({"level": "warning", "msg": f"COP = {COP:.2f} — ต่ำกว่าปกติ"})
    if eta_is and eta_is < 0.55:
                           w.append({"level": "warning", "msg": f"eta_is = {eta_is*100:.1f}% — ต่ำมาก"})
    return w


# ── Schemas ────────────────────────────────────────────────

class CalcInput(BaseModel):
    current:      float
    sp:           float
    dp:           float
    st:           Optional[float] = None
    dt:           Optional[float] = None
    liquid_temp:  Optional[float] = None
    sh_default:   float = 5.0
    eta_is:       float = 0.70
    voltage:      float = 385.0
    power_factor: float = 0.86


class TwoStageInput(BaseModel):
    i_booster:    float
    sp:           float
    st:           Optional[float] = None
    dt_booster:   Optional[float] = None
    t_int:        float = -7.0
    i_high:       float
    dp:           float
    dt_high:      Optional[float] = None
    liquid_temp:  Optional[float] = None
    sh_default:   float = 5.0
    eta_booster:  float = 0.70
    eta_high:     float = 0.70
    voltage:      float = 385.0
    power_factor: float = 0.86


# ── Endpoints ──────────────────────────────────────────────

@router.post("/calculate")
def api_calculate(data: CalcInput):
    P_comp_kW = (1.732 * data.voltage * data.current * data.power_factor) / 1000
    P_low     = _kpa(data.sp)
    P_high    = _kpa(data.dp)
    T_evap    = CP.PropsSI("T","P",P_low, "Q",1,FLUID) - 273.15
    T_cond    = CP.PropsSI("T","P",P_high,"Q",0,FLUID) - 273.15

    if data.st is not None:
        SH, h1, st_used, sh_mode = (
            data.st - T_evap,
            CP.PropsSI("H","P",P_low,"T",data.st+273.15,FLUID)/1000,
            data.st, "measured",
        )
    else:
        SH      = data.sh_default
        st_used = T_evap + SH
        h1      = CP.PropsSI("H","P",P_low,"T",st_used+273.15,FLUID)/1000
        sh_mode = "assumed"

    s1   = CP.PropsSI("S","P",P_low, "T",st_used+273.15,FLUID)
    h2s  = CP.PropsSI("H","P",P_high,"S",s1,FLUID)/1000
    T2s_C= CP.PropsSI("T","P",P_high,"S",s1,FLUID) - 273.15

    if data.dt is not None:
        h2            = CP.PropsSI("H","P",P_high,"T",data.dt+273.15,FLUID)/1000
        eta_is_actual = (h2s-h1)/(h2-h1) if (h2-h1) != 0 else None
        dt_used, dt_mode = data.dt, "measured"
    else:
        h2            = h1 + (h2s-h1)/data.eta_is
        eta_is_actual = data.eta_is
        dt_used       = CP.PropsSI("T","P",P_high,"H",h2*1000,FLUID) - 273.15
        dt_mode       = "assumed"

    hf_cond = CP.PropsSI("H","P",P_high,"Q",0,FLUID)/1000
    if data.liquid_temp is not None:
        SC, h3, liq_mode = T_cond - data.liquid_temp, CP.PropsSI("H","P",P_high,"T",data.liquid_temp+273.15,FLUID)/1000, "measured"
    else:
        SC, h3, liq_mode = 0.0, hf_cond, "assumed"

    q_L, w_comp, q_H = h1-h3, h2-h1, h2-h3
    COP    = q_L / w_comp
    Q_e    = P_comp_kW * COP
    m_dot  = Q_e / q_L

    return {
        "modes":      {"sh_mode": sh_mode, "dt_mode": dt_mode, "liq_mode": liq_mode,
                       "st_used": round(st_used,2), "dt_used": round(dt_used,2)},
        "inputs":     {"P_low_kPa": round(P_low/1000,2), "P_high_kPa": round(P_high/1000,2)},
        "saturation": {"T_evap": round(T_evap,2), "T_cond": round(T_cond,2),
                       "superheat": round(SH,2), "subcool": round(SC,2)},
        "enthalpy":   {"h1": round(h1,2), "h2": round(h2,2), "h3": round(h3,2), "h4": round(h3,2),
                       "h2s": round(h2s,2), "T2s_degC": round(T2s_C,2)},
        "performance":{"P_comp_kW": round(P_comp_kW,3), "q_L": round(q_L,2),
                       "w_comp": round(w_comp,2), "q_H": round(q_H,2),
                       "COP": round(COP,4), "Q_e_kW": round(Q_e,3),
                       "Q_H_kW": round(P_comp_kW+Q_e,3), "TR": round(Q_e/3.517,2),
                       "m_dot_kgs": round(m_dot,5), "m_dot_kgh": round(m_dot*3600,2),
                       "eta_isentropic": round(eta_is_actual*100,1) if eta_is_actual else None},
        "warnings": _warnings_single(SH, SC, COP, eta_is_actual),
    }


@router.post("/calculate_two")
def api_calculate_two(data: TwoStageInput):
    P_low  = _kpa(data.sp)
    P_int  = CP.PropsSI("P","T",data.t_int+273.15,"Q",1,FLUID)
    P_high = _kpa(data.dp)
    T_evap = CP.PropsSI("T","P",P_low, "Q",1,FLUID) - 273.15
    T_cond = CP.PropsSI("T","P",P_high,"Q",0,FLUID) - 273.15

    if data.st is not None:
        SH, h1, st_used, sh_mode = data.st-T_evap, CP.PropsSI("H","P",P_low,"T",data.st+273.15,FLUID)/1000, data.st, "measured"
    else:
        SH = data.sh_default; st_used = T_evap+SH
        h1 = CP.PropsSI("H","P",P_low,"T",st_used+273.15,FLUID)/1000; sh_mode = "assumed"

    s1    = CP.PropsSI("S","P",P_low,"T",st_used+273.15,FLUID)
    h2s_b = CP.PropsSI("H","P",P_int,"S",s1,FLUID)/1000

    if data.dt_booster is not None:
        h2 = CP.PropsSI("H","P",P_int,"T",data.dt_booster+273.15,FLUID)/1000
        eta_b = (h2s_b-h1)/(h2-h1) if (h2-h1) != 0 else None
        dt_b_used, dt_b_mode = data.dt_booster, "measured"
    else:
        h2=h1+(h2s_b-h1)/data.eta_booster; eta_b=data.eta_booster
        dt_b_used=CP.PropsSI("T","P",P_int,"H",h2*1000,FLUID)-273.15; dt_b_mode="assumed"

    h3   = CP.PropsSI("H","P",P_int,"Q",1,FLUID)/1000
    h4s  = CP.PropsSI("H","P",P_high,"S",CP.PropsSI("S","P",P_int,"Q",1,FLUID),FLUID)/1000

    if data.dt_high is not None:
        h4 = CP.PropsSI("H","P",P_high,"T",data.dt_high+273.15,FLUID)/1000
        eta_h = (h4s-h3)/(h4-h3) if (h4-h3) != 0 else None
        dt_h_used, dt_h_mode = data.dt_high, "measured"
    else:
        h4=h3+(h4s-h3)/data.eta_high; eta_h=data.eta_high
        dt_h_used=CP.PropsSI("T","P",P_high,"H",h4*1000,FLUID)-273.15; dt_h_mode="assumed"

    hf_cond = CP.PropsSI("H","P",P_high,"Q",0,FLUID)/1000
    if data.liquid_temp is not None:
        SC=T_cond-data.liquid_temp; h5=CP.PropsSI("H","P",P_high,"T",data.liquid_temp+273.15,FLUID)/1000; liq_mode="measured"
    else:
        SC=0.0; h5=hf_cond; liq_mode="assumed"

    hf_int = CP.PropsSI("H","P",P_int,"Q",0,FLUID)/1000
    ratio  = (h2-h5)/(h3-h5)
    W_b    = (1.732*data.voltage*data.i_booster*data.power_factor)/1000
    W_h    = (1.732*data.voltage*data.i_high   *data.power_factor)/1000
    m_low  = W_b/(h2-h1); m_high = m_low*ratio
    Q_e    = m_low*(h1-hf_int); COP = Q_e/(W_b+W_h)

    warnings = []
    if SH < 0:          warnings.append({"level":"danger",  "msg":f"Superheat = {SH:.1f} K — liquid เข้า booster!"})
    if SH > 15:         warnings.append({"level":"warning", "msg":f"Superheat สูง ({SH:.1f} K)"})
    if SC < 0:          warnings.append({"level":"danger",  "msg":f"Subcool = {SC:.1f} K — flash ก่อน EXV"})
    if COP < 1.2:       warnings.append({"level":"warning", "msg":f"COP = {COP:.2f} — ต่ำกว่าปกติ"})
    if ratio > 1.5:     warnings.append({"level":"warning", "msg":f"m_high/m_low = {ratio:.2f} — สูงมาก ตรวจ intercooler"})

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
                       "h5":round(h5,2),"h6":round(h5,2),"hf_int":round(hf_int,2),"h7":round(hf_int,2)},
        "performance":{"W_booster_kW":round(W_b,3),"W_high_kW":round(W_h,3),"W_total_kW":round(W_b+W_h,3),
                       "m_low_kgs":round(m_low,5),"m_low_kgh":round(m_low*3600,2),
                       "m_high_kgs":round(m_high,5),"m_high_kgh":round(m_high*3600,2),
                       "ratio_mh_ml":round(ratio,3),"Q_e_kW":round(Q_e,3),"Q_e_TR":round(Q_e/3.517,2),
                       "Q_cond_kW":round(m_high*(h4-h5),3),"COP_system":round(COP,4),
                       "eta_booster":round(eta_b*100,1) if eta_b else None,
                       "eta_high":round(eta_h*100,1) if eta_h else None},
        "warnings": warnings,
    }
