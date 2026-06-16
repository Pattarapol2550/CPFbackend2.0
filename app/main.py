"""
FastAPI application factory and startup.

Creates the app, registers CORS, includes all routers, and runs DB migrations on startup.
Imported by root main.py shim for `uvicorn main:app`.
"""

import CoolProp.CoolProp as CP
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth, calculator, metrics, ph_diagram

# =========================================================
# CoolProp reference state (IIR for Ammonia)
# =========================================================
CP.set_reference_state("Ammonia", "IIR")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(title="Ammonia Diagnostics API v2")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(auth.router)
    application.include_router(metrics.router)
    application.include_router(ph_diagram.router)
    application.include_router(calculator.router)

    @application.on_event("startup")
    async def create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("✅ PostgreSQL tables ready")

    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
