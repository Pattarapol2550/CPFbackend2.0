"""
main.py — entry point
ไฟล์นี้มีหน้าที่เดียว: สร้าง app, ลง middleware, register routers
ห้ามใส่ business logic ที่นี่
"""
import logging
from contextlib import asynccontextmanager

import CoolProp.CoolProp as CP
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import ALLOWED_ORIGINS, FLUID
from database import engine
from models import Base  # noqa: F401 — ensures all models are registered

from routers import auth, metrics, ph_diagram, calculator

logger = logging.getLogger(__name__)


# ── Lifespan (แทน on_event deprecated) ────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    CP.set_reference_state(FLUID, "IIR")
    logger.info("PostgreSQL tables ready")
    yield
    # cleanup ถ้าจำเป็นในอนาคต


# ── App ────────────────────────────────────────────────────

app = FastAPI(title="Ammonia Diagnostics API v2", lifespan=lifespan)

# Rate limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Security headers
@app.middleware("http")
async def set_secure_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"]  = "nosniff"
    response.headers["X-Frame-Options"]          = "DENY"
    response.headers["Referrer-Policy"]          = "no-referrer"
    response.headers["Cache-Control"]            = "no-store"
    response.headers["Strict-Transport-Security"]= "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"]  = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    )
    return response

# Routers
app.include_router(auth.router)
app.include_router(metrics.router)
app.include_router(ph_diagram.router)
app.include_router(calculator.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
