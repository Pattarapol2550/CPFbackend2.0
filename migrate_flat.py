"""
migrate_flat.py
---------------
One-time migration: drop compressor_data table and recreate with flat columns.
Run once locally, then push to GitHub so Render does the same on next deploy.

    python migrate_flat.py
    python migrate_flat.py --url postgresql+asyncpg://user:pass@host/db
"""

import asyncio
import argparse

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

from app.database import Base
from app.models import metric   # noqa: F401 — registers MetricModel with Base.metadata
from app.config import DATABASE_URL


async def run(url: str):
    engine = create_async_engine(url, echo=True)
    async with engine.begin() as conn:
        print(">>> Dropping compressor_data …")
        await conn.execute(text("DROP TABLE IF EXISTS compressor_data CASCADE"))
        print(">>> Recreating compressor_data with flat columns …")
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print(">>> Done. compressor_data is now using flat columns.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DATABASE_URL,
                        help="Async database URL (default: from app.config)")
    args = parser.parse_args()
    asyncio.run(run(args.url))
