"""
Shared thermodynamic and validation constants.

Used by diagnostics, P-H diagram, and calculator services. No side effects on import.
"""

import re
from datetime import timezone, timedelta

# =========================================================
# Refrigerant & electrical defaults
# =========================================================
FLUID = "Ammonia"
VOLTAGE = 385.0
POWER_FACTOR = 0.86
DEFAULT_SUPERHEAT_K = 5.0
DEFAULT_ISENTROPIC_EFF = 0.70

# =========================================================
# Timezone
# =========================================================
TZ_TH = timezone(timedelta(hours=7))

# =========================================================
# Validation patterns
# =========================================================
RE_USERNAME = re.compile(r"^[a-zA-Z0-9_.]{3,32}$")
RE_PHONE_TH = re.compile(r"^0\d{8,9}$")
