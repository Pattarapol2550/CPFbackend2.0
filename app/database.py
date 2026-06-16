"""
Async SQLAlchemy engine, session factory, and FastAPI DB dependency.

Side effect: creates async engine at import when DATABASE_URL is set.
Imported by routers and app startup (create_tables).
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DATABASE_URL

# =========================================================
# Engine
# =========================================================
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


# =========================================================
# Dependency
# =========================================================
async def get_db():
    """Yield an async DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session
