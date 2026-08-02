from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base
from app.utils.config import get_settings


@lru_cache
def _engine():
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )
    # Enable WAL mode for SQLite so concurrent readers and the background-task
    # writer don't block each other.  No-op on PostgreSQL.
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_wal(dbapi_connection, _record):
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            dbapi_connection.execute("PRAGMA busy_timeout=5000")
    return engine


@lru_cache
def _sessionmaker():
    return sessionmaker(bind=_engine(), autocommit=False, autoflush=False)


def init_db() -> None:
    """Create all tables if they don't exist. Called at app startup."""
    Base.metadata.create_all(bind=_engine())


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy session and handles cleanup."""
    session = _sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session.
    Use with Depends(get_db) in route parameters.
    """
    session = _sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
