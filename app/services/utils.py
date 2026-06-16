"""
Shared formatting and unit-conversion helpers.

Used by diagnostics, P-H diagram, and calculator services.
"""

# =========================================================
# Formatting
# =========================================================
def safe_round(value, digit=2):
    """Round numeric value for API display; return '--' for None or invalid input."""
    if value is None:
        return "--"
    try:
        return round(value, digit)
    except (TypeError, ValueError):
        return "--"


# =========================================================
# Pressure conversion
# =========================================================
def pressure_kgcm2_to_pa(p_kg: float) -> float:
    """Convert gauge pressure (kg/cm²g) to absolute Pa."""
    return (p_kg * 98066.5) + 101325
