"""
Calculator endpoints for single- and two-stage refrigeration cycles.

Stateless POST handlers; no auth required (same as original main.py).
"""

from fastapi import APIRouter

from app.schemas.calculator import CalcInput, TwoStageInput
from app.services.calculator import calculate_single_stage, calculate_two_stage

router = APIRouter()


# =========================================================
# POST /api/calculate
# =========================================================
@router.post("/api/calculate", tags=["calculator"])
def api_calculate(data: CalcInput):
    return calculate_single_stage(data)


# =========================================================
# POST /api/calculate_two
# =========================================================
@router.post("/api/calculate_two", tags=["calculator"])
def api_calculate_two(data: TwoStageInput):
    return calculate_two_stage(data)
