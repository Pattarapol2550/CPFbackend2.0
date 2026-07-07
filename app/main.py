"""
app/main.py — FastAPI application factory and startup.
"""

import logging
from contextlib import asynccontextmanager

import CoolProp.CoolProp as CP
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from datetime import datetime, timezone

from sqlalchemy import select

from app.config import CORS_ORIGINS
from app.core.limiter import limiter          # ← import จากไฟล์กลาง
from app.database import AsyncSessionLocal, Base, engine
from app.models.compressor import CompressorModel
from app.routers import auth, calculator, metrics, ph_diagram

logger = logging.getLogger(__name__)

CP.set_reference_state("Ammonia", "IIR")

# Compressor ที่มีอยู่จริงในโรงงาน — ใช้ seed ตาราง compressors ครั้งแรกที่ตารางว่าง
# (เดิม hardcode อยู่ฝั่ง frontend utils/format.js เท่านั้น)
_SEED_COMPRESSORS = {
    "COMP-01": "high_stage",
    "COMP-02": "booster",
    "COMP-03": "booster",
    "COMP-04": "booster",
    "COMP-05": "booster",
    "COMP-06": "high_stage",
    "COMP-07": "high_stage",
}


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with engine.begin() as conn:
        # ONE-TIME migration: drop old table that has inputs_snapshot JSON column.
        # Remove these two lines after first successful deploy.
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables ready")

    # ONE-TIME seed: เติม compressors ตารางใหม่ด้วยรายชื่อที่ใช้งานจริงอยู่แล้ว
    # (ถ้าเคย seed หรือ admin สร้างเองแล้ว ตารางจะไม่ว่าง จะข้ามขั้นตอนนี้)
    # ห่อ try/except กันไม่ให้ seed พังแล้วดึง startup ทั้งแอปล้มไปด้วย
    try:
        async with AsyncSessionLocal() as session:
            existing = (await session.execute(select(CompressorModel.id))).scalars().all()
            if not existing:
                session.add_all([
                    CompressorModel(id=cid, type=ctype, created_at=datetime.now(timezone.utc))
                    for cid, ctype in _SEED_COMPRESSORS.items()
                ])
                await session.commit()
                logger.info("Seeded %d compressors", len(_SEED_COMPRESSORS))
    except Exception:
        logger.exception("Compressor seed failed — continuing startup without seed data")

    yield


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["Referrer-Policy"]         = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"]      = "geolocation=(), microphone=(), camera=()"
        return response


def create_app() -> FastAPI:
    application = FastAPI(title="Ammonia Diagnostics API v2", lifespan=lifespan)

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    application.include_router(auth.router)
    application.include_router(metrics.router)
    application.include_router(ph_diagram.router)
    application.include_router(calculator.router)

    return application


app = create_app()


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)