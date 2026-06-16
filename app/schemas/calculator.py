"""
Calculator request schemas for single- and two-stage cycle tools.

Used by calculator router. Assumes SH=5K and eta_is=0.70 when temps omitted.
"""

from typing import Optional

from pydantic import BaseModel


class CalcInput(BaseModel):
    """Single-stage refrigeration calculator inputs."""

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
    """Two-stage (booster + high) calculator inputs."""

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
