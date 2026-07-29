"""SQLAlchemy Session- und Engine-Verwaltung."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

import config

Base = declarative_base()

_connect_args = {}
if DATABASE_URL := config.DATABASE_URL:
    if DATABASE_URL.startswith("sqlite"):
        _connect_args = {"check_same_thread": False}

engine = create_engine(
    config.DATABASE_URL,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

if config.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ARG001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Erstellt Tabellen und führt sichere Schema-Migrationen aus."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Modelle registrieren
    from database import models  # noqa: F401
    from database.migrations import run_migrations

    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
