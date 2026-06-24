"""
P-H diagram data: saturation dome and refrigeration cycle points.

Used by ph-diagram router. Assumes eta_is=0.70 when discharge temp is missing.
"""

import logging

import CoolProp.CoolProp as CP
import numpy as np

from app.core.constants import DEFAULT_ISENTROPIC_EFF, FLUID
from app.services.utils import pressure_kgcm2_to_pa

logger = logging.getLogger(__name__)


def build_saturation_dome(fluid: str = FLUID, n_points: int = 60) -> dict:
    """Build liquid/vapour saturation curves and critical point for P-H chart."""
    T_min_K = 223.15
    T_crit_K = CP.PropsSI("Tcrit", fluid)
    T_max_K = T_crit_K - 0.5
    temps = np.linspace(T_min_K, T_max_K, n_points)
    liq_points = []
    vap_points = []
    for T in temps:
        try:
            h_liq = CP.PropsSI("H", "T", T, "Q", 0, fluid) / 1000
            h_vap = CP.PropsSI("H", "T", T, "Q", 1, fluid) / 1000
            p_mpa = CP.PropsSI("P", "T", T, "Q", 0, fluid) / 1e6
            liq_points.append({"h": round(h_liq, 2), "p": round(p_mpa, 4)})
            vap_points.append({"h": round(h_vap, 2), "p": round(p_mpa, 4)})
        except (ValueError, RuntimeError):
            continue
    h_crit = CP.PropsSI("H", "T", T_crit_K, "Q", 0, fluid) / 1000
    p_crit = CP.PropsSI("P", "T", T_crit_K, "Q", 0, fluid) / 1e6
    crit_point = {"h": round(h_crit, 2), "p": round(p_crit, 4)}
    liq_points.append(crit_point)
    vap_points.append(crit_point)
    return {
        "liquid": liq_points,
        "vapour": vap_points,
        "critical": crit_point,
    }


def compute_cycle_points(inputs: dict, fluid: str = FLUID) -> dict:
    """Compute cycle state points 1→2→3→4 from stored inputs_snapshot dict."""
    sp_kg = inputs.get("sp_kg")
    st_c = inputs.get("st_c")
    dp_kg = inputs.get("dp_kg")
    dt_c = inputs.get("dt_c")
    liq_c = inputs.get("liquid_temp_c")
    points = {
        "point1": None,
        "point2": None,
        "point2s": None,
        "point3": None,
        "point4": None,
        "p_suc_mpa": None,
        "p_dis_mpa": None,
        "t_sat_suc_c": None,
        "t_sat_dis_c": None,
        "isentropic_efficiency": None,
    }
    try:
        p_suc_pa = pressure_kgcm2_to_pa(float(sp_kg)) if sp_kg is not None else None
        p_dis_pa = pressure_kgcm2_to_pa(float(dp_kg)) if dp_kg is not None else None
        if p_suc_pa:
            points["p_suc_mpa"] = round(p_suc_pa / 1e6, 4)
        if p_dis_pa:
            points["p_dis_mpa"] = round(p_dis_pa / 1e6, 4)
        if p_suc_pa:
            points["t_sat_suc_c"] = round(
                CP.PropsSI("T", "P", p_suc_pa, "Q", 1, fluid) - 273.15, 2
            )
        if p_dis_pa:
            points["t_sat_dis_c"] = round(
                CP.PropsSI("T", "P", p_dis_pa, "Q", 1, fluid) - 273.15, 2
            )
        if p_suc_pa and st_c is not None:
            t1_k = float(st_c) + 273.15
            h1 = CP.PropsSI("H", "P", p_suc_pa, "T", t1_k, fluid) / 1000
            s1 = CP.PropsSI("S", "P", p_suc_pa, "T", t1_k, fluid)
            points["point1"] = {
                "h": round(h1, 2),
                "p": round(p_suc_pa / 1e6, 4),
                "label": "1 — Comp. inlet",
                "t_c": round(float(st_c), 2),
            }
            if p_dis_pa:
                h2s = CP.PropsSI("H", "P", p_dis_pa, "S", s1, fluid) / 1000
                points["point2s"] = {
                    "h": round(h2s, 2),
                    "p": round(p_dis_pa / 1e6, 4),
                    "label": "2s — Isentropic",
                }
        if p_dis_pa and points["point1"] and points["point2s"]:
            h1_val = points["point1"]["h"]
            h2s_val = points["point2s"]["h"]
            if dt_c is not None:
                t2_k = float(dt_c) + 273.15
                h2 = CP.PropsSI("H", "P", p_dis_pa, "T", t2_k, fluid) / 1000
                dt_used = round(float(dt_c), 2)
                if (h2 - h1_val) != 0:
                    points["isentropic_efficiency"] = round((h2s_val - h1_val) / (h2 - h1_val), 4)
            else:
                h2 = h1_val + (h2s_val - h1_val) / DEFAULT_ISENTROPIC_EFF
                dt_used = round(
                    CP.PropsSI("T", "P", p_dis_pa, "H", h2 * 1000, fluid) - 273.15, 2
                )
                points["isentropic_efficiency"] = DEFAULT_ISENTROPIC_EFF
            points["point2"] = {
                "h": round(h2, 2),
                "p": round(p_dis_pa / 1e6, 4),
                "label": "2 — Comp. outlet",
                "t_c": dt_used,
            }
        if p_dis_pa:
            if liq_c is not None:
                t3_k = float(liq_c) + 273.15
                h3 = CP.PropsSI("H", "P", p_dis_pa, "T", t3_k, fluid) / 1000
                t3_c = round(float(liq_c), 2)
            else:
                h3 = CP.PropsSI("H", "P", p_dis_pa, "Q", 0, fluid) / 1000
                t3_c = round(CP.PropsSI("T", "P", p_dis_pa, "Q", 0, fluid) - 273.15, 2)
            points["point3"] = {
                "h": round(h3, 2),
                "p": round(p_dis_pa / 1e6, 4),
                "label": "3 — Cond. outlet",
                "t_c": t3_c,
            }
            if p_suc_pa:
                points["point4"] = {
                    "h": round(h3, 2),
                    "p": round(p_suc_pa / 1e6, 4),
                    "label": "4 — Evap. inlet",
                }
    except Exception:
        logger.exception("compute_cycle_points failed")
    return points
