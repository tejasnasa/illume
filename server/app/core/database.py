"""
Database configuration and session management.

Provides both asynchronous and synchronous SQLAlchemy engines and session makers
to support FastAPI routes (async) and Celery background tasks (sync).
"""
from app.core.config import settings
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    """Base class for SQLAlchemy declarative models."""
    pass


# Async engine for FastAPI routes
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    echo=False,
)

# Session factory for async database operations
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_db():
    """
    Dependency injection for async database sessions.
    
    Yields:
        AsyncSession: An active async SQLAlchemy session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except:
            await session.rollback()
            raise
        finally:
            await session.close()


# Sync engine for Celery tasks and background jobs
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    echo=False,
)

# Session factory for sync database operations
SyncSessionLocal = sessionmaker(
    sync_engine,
    expire_on_commit=False,
)


def get_sync_db():
    """
    Dependency injection for sync database sessions.
    
    Yields:
        Session: An active sync SQLAlchemy session.
    """
    session = SyncSessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
