"""Small, ordered migration runner for future non-destructive schema changes."""

from __future__ import annotations

import logging
from collections.abc import Callable

from database.models import SchemaVersion, db

logger = logging.getLogger(__name__)

# Migrations are append-only. A migration may add tables, columns or indexes,
# but must never drop user data. Version 1 represents the initial create_all
# schema; future versions are added as (version, callable) entries.
MIGRATIONS: tuple[tuple[int, Callable[[], None]], ...] = ()
CURRENT_VERSION = 1


def run_migrations() -> None:
    applied = {
        value
        for value in db.session.scalars(db.select(SchemaVersion.version)).all()
    }
    if 1 not in applied:
        db.session.add(SchemaVersion(version=1))
        db.session.commit()
        applied.add(1)
    for version, migrate in MIGRATIONS:
        if version in applied:
            continue
        logger.info("Datenbankmigration %d wird angewendet.", version)
        try:
            migrate()
            db.session.add(SchemaVersion(version=version))
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("Datenbankmigration %d fehlgeschlagen.", version)
            raise
