"""
app/main.py — FastAPI application factory and startup.
"""

import logging
from contextlib import asynccontextmanager

import CoolProp.CoolProp as CP
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import CORS_ORIGINS
from app.core.limiter import limiter          # ← import จากไฟล์กลาง
from app.database import Base, engine
from app.routers import auth, calculator, metrics, ph_diagram

logger = logging.getLogger(__name__)

CP.set_reference_state("Ammonia", "IIR")


@asynccontextmanager
async def lifespan(application: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("PostgreSQL tables ready")
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Ammonia Diagnostics API v2", lifespan=lifespan)

    application.state.limiter = limiter
    application.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    )

    application.include_router(auth.router)
    application.include_router(metrics.router)
    application.include_router(ph_diagram.router)
    application.include_router(calculator.router)

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)