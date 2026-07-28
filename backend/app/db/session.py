from contextlib import contextmanager
from functools import lru_cache
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.db.models import Base
from app.utils.config import get_settings


@lru_cache
def _engine():
    settings = get_settings()
    return create_engine(settings.database_url, connect_args={"check_same_thread": False})


def init_db() -> None:
    """Create all tables if they don't exist. Called at app startup."""
    Base.metadata.create_all(bind=_engine())


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager that yields a SQLAlchemy session and handles cleanup."""
    SessionLocal = sessionmaker(bind=_engine(), autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
