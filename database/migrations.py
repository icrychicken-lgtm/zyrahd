"""Tiny migration registry for future non-destructive schema upgrades.

SQLAlchemy's ``create_all`` creates every missing table on first start. Future
releases can append versioned, additive migration functions here without
recreating or deleting a user's existing SQLite database.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

CURRENT_VERSION = 1


def migrate(connection: Connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_version "
            "(id INTEGER PRIMARY KEY CHECK (id = 1), version INTEGER NOT NULL)"
        )
    )
    version = connection.execute(
        text("SELECT version FROM schema_version WHERE id = 1")
    ).scalar_one_or_none()
    if version is None:
        connection.execute(
            text("INSERT INTO schema_version (id, version) VALUES (1, :version)"),
            {"version": CURRENT_VERSION},
        )
    # Future additive migrations:
    # if version < 2:
    #     connection.execute(text("ALTER TABLE ... ADD COLUMN ..."))
    #     version = 2
    if version is not None and version < CURRENT_VERSION:
        connection.execute(
            text("UPDATE schema_version SET version = :version WHERE id = 1"),
            {"version": CURRENT_VERSION},
        )
