"""SQLAlchemy engine, session, and declarative Base."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from api.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_is_sqlite = "sqlite" in _settings.database.url

if _is_sqlite:
    engine = create_engine(
        _settings.database.url,
        connect_args={"check_same_thread": False},
        echo=_settings.debug,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()
else:
    # PostgreSQL: connection pooling
    engine = create_engine(
        _settings.database.url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=_settings.debug,
    )


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Session:
    """FastAPI dependency: yield a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
