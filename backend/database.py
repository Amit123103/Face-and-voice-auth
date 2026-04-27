"""
FaceVoiceAuth — Async Database Engine & Session Management
SQLAlchemy Async with connection pooling and WAL mode for SQLite performance.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool, AsyncAdaptedQueuePool
from sqlalchemy import event, text

from backend.config import get_settings

settings = get_settings()


def _get_engine_kwargs() -> dict:
    """Build engine keyword arguments based on environment."""
    kwargs = {"echo": settings.DEBUG}
    if settings.is_sqlite:
        # NullPool is required for SQLite async
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["poolclass"] = AsyncAdaptedQueuePool
        kwargs["pool_size"] = settings.DB_POOL_SIZE
        kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 3600
    return kwargs


engine = create_async_engine(settings.DATABASE_URL, **_get_engine_kwargs())

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """Dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables from ORM metadata and optimize SQLite settings."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # SQLite performance optimizations
        if settings.is_sqlite:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=-64000"))  # 64MB cache
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            await conn.execute(text("PRAGMA mmap_size=268435456"))  # 256MB mmap
            await conn.execute(text("PRAGMA optimize"))


async def sync_database_schema() -> None:
    """
    Self-healing schema synchronization.
    Detects missing columns and adds them to ensure the database matches the ORM models.
    """
    from sqlalchemy import inspect

    # Definitions of columns that might be missing due to schema evolution
    patches = {
        "users": [
            ("balance", "FLOAT", "1000.0"),
            ("security_score", "FLOAT", "0.0"),
            ("voice_passphrase", "VARCHAR(255)", "NULL"),
            ("voice_passphrase_enabled", "BOOLEAN", "FALSE"),
            ("encryption_salt", "VARCHAR(44)", "NULL"),
        ],
        "secret_vault": [
            ("category", "VARCHAR(50)", "'Personal'"),
            ("secret_type", "VARCHAR(50)", "'Note'"),
        ],
        "transactions": [
            ("sender_face_verified", "BOOLEAN", "FALSE"),
            ("receiver_face_verified", "BOOLEAN", "FALSE"),
            ("admin_approved", "BOOLEAN", "FALSE"),
        ]
    }

    async with engine.connect() as conn:
        def get_columns(target_conn, table_name):
            inst = inspect(target_conn)
            return [c["name"] for c in inst.get_columns(table_name)]

        for table, columns in patches.items():
            try:
                # Check if table exists first
                table_exists = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(table))
                if not table_exists:
                    continue

                existing_cols = await conn.run_sync(get_columns, table)
                
                for col_name, col_type, col_default in columns:
                    if col_name not in existing_cols:
                        # Construct ALTER TABLE statement
                        # PostgreSQL / SQLite compatible basic ALTER TABLE
                        stmt = f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"
                        if col_default != "NULL":
                            stmt += f" DEFAULT {col_default}"
                        
                        await conn.execute(text(stmt))
                        await conn.commit()
                        print(f"DEBUG: Patched database -> Added {table}.{col_name}")
                        
            except Exception as e:
                print(f"WARNING: Schema sync failed for table {table}: {e}")

    print("INFO: Database schema synchronization complete.")


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    await engine.dispose()
