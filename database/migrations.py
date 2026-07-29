"""Small, non-destructive schema migration runner.

The first schema uses SQLAlchemy's idempotent ``create_all``. Future changes can
append numbered migration functions without replacing existing user data.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, Table, insert, select

from database.manager import engine
from database.models import Base

metadata = MetaData()
schema_version = Table(
    "schema_version",
    metadata,
    Column("version", Integer, nullable=False),
)
CURRENT_VERSION = 1


def run_migrations() -> None:
    Base.metadata.create_all(engine)
    metadata.create_all(engine)
    with engine.begin() as connection:
        version = connection.scalar(select(schema_version.c.version).limit(1))
        if version is None:
            connection.execute(insert(schema_version).values(version=CURRENT_VERSION))
        elif version > CURRENT_VERSION:
            raise RuntimeError(
                "Die Datenbank wurde mit einer neueren zyrahd.net-Version erstellt."
            )
