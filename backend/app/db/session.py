from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.core.config import settings
from app.db.base import Base

# Database engine
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    # Import all models to ensure they are registered with Base.metadata
    import app.models  # noqa: F401
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Idempotent schema evolution for existing PostgreSQL/SQLite endpoint tables
        new_cols = {
            "ip_address": "VARCHAR(64)",
            "adapter_name": "VARCHAR(128)",
            "mac_address": "VARCHAR(64)",
            "last_telemetry_json": "JSONB" if settings.DATABASE_URL.startswith("postgresql") else "JSON",
        }
        if settings.DATABASE_URL.startswith("postgresql"):
            for col_name, col_type in new_cols.items():
                await conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
        elif settings.DATABASE_URL.startswith("sqlite"):
            rows = (await conn.execute(text("PRAGMA table_info(endpoints)"))).fetchall()
            existing = {r[1] for r in rows}
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    await conn.execute(text(f"ALTER TABLE endpoints ADD COLUMN {col_name} {col_type}"))
