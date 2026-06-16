"""
Deployment entry point for uvicorn (`uvicorn main:app`).

Re-exports the FastAPI app and symbols used by test_main.py for backward compatibility.
"""

from app.main import app
from app.schemas.metrics import CompressorDataInput
from app.services.diagnostics import diagnose_compressor
from app.services.ph_diagram import build_saturation_dome, compute_cycle_points
from app.services.utils import safe_round

__all__ = [
    "app",
    "safe_round",
    "diagnose_compressor",
    "compute_cycle_points",
    "build_saturation_dome",
    "CompressorDataInput",
]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
