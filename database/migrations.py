"""Sichere Schema-Erweiterungen ohne Datenverlust."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("zyrahd.migrations")

# Tabelle -> zusätzliche Spalten (Name, SQL-Typ-Definition)
EXTRA_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "tickets": [
        ("internal_notes", "TEXT DEFAULT ''"),
        ("rating_comment", "TEXT DEFAULT ''"),
        ("last_activity_at", "DATETIME"),
    ],
    "security_config": [
        ("spam_messages", "INTEGER DEFAULT 5"),
        ("spam_seconds", "INTEGER DEFAULT 5"),
        ("mention_limit", "INTEGER DEFAULT 5"),
        ("caps_percent", "INTEGER DEFAULT 70"),
        ("emoji_limit", "INTEGER DEFAULT 10"),
    ],
}


def run_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in EXTRA_COLUMNS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table)}
            for col_name, col_def in columns:
                if col_name in existing_cols:
                    continue
                sql = f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}"
                logger.info("Migration: %s", sql)
                conn.execute(text(sql))

    _seed_defaults(engine)


def _seed_defaults(engine: Engine) -> None:
    """Legt Standard-Datensätze an, falls noch nicht vorhanden."""
    from database.manager import SessionLocal
    from database.models import (
        SecurityConfig,
        TeamConfig,
        TicketPanel,
        TicketType,
        VerifyConfig,
        WelcomeConfig,
        GoodbyeConfig,
        LogConfig,
        TicketFormField,
    )

    session = SessionLocal()
    try:
        if not session.query(WelcomeConfig).first():
            session.add(WelcomeConfig())
        if not session.query(GoodbyeConfig).first():
            session.add(GoodbyeConfig())
        if not session.query(VerifyConfig).first():
            session.add(VerifyConfig())
        if not session.query(SecurityConfig).first():
            session.add(SecurityConfig())
        if not session.query(TeamConfig).first():
            session.add(TeamConfig())
        if not session.query(LogConfig).first():
            session.add(LogConfig())
        if not session.query(TicketPanel).first():
            session.add(TicketPanel())

        if not session.query(TicketType).first():
            defaults = [
                ("Support", "Allgemeiner Support", "🛠️", "#9B5CFF", 0),
                ("Bewerbung", "Bewerbung fürs Team", "📝", "#7C4DFF", 1),
                ("Partnerschaft", "Partnerschaftsanfrage", "🤝", "#B388FF", 2),
                ("Beschwerde", "Beschwerde einreichen", "⚠️", "#E040FB", 3),
                ("Entbannungsantrag", "Antrag auf Entbannung", "🔓", "#CE93D8", 4),
                ("Allgemeine Anfrage", "Sonstige Anfragen", "💬", "#9575CD", 5),
            ]
            for name, desc, emoji, color, order in defaults:
                tt = TicketType(
                    name=name,
                    description=desc,
                    emoji=emoji,
                    color=color,
                    sort_order=order,
                    enabled=True,
                )
                session.add(tt)
                session.flush()
                _seed_fields(session, tt)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _seed_fields(session, ticket_type: "TicketType") -> None:  # noqa: F821
    from database.models import TicketFormField

    presets: dict[str, list[tuple[str, str, bool]]] = {
        "Support": [
            ("Wobei benötigst du Hilfe?", "long", True),
            ("Was hast du bereits versucht?", "long", False),
            ("Gibt es Bilder oder Fehlermeldungen?", "short", False),
        ],
        "Partnerschaft": [
            ("Wie heißt dein Server?", "short", True),
            ("Wie viele Mitglieder hat dein Server?", "short", True),
            ("Was ist das Thema deines Servers?", "short", True),
            ("Warum möchtest du eine Partnerschaft?", "long", True),
            ("Beschreibung oder Einladung", "long", True),
        ],
        "Bewerbung": [
            ("Wie heißt du?", "short", True),
            ("Wie alt bist du?", "short", True),
            ("Für welchen Bereich bewirbst du dich?", "short", True),
            ("Welche Erfahrungen besitzt du?", "long", True),
            ("Warum sollten wir dich annehmen?", "long", True),
            ("Wie aktiv kannst du sein?", "short", True),
        ],
        "Beschwerde": [
            ("Gegen wen/was richtet sich die Beschwerde?", "short", True),
            ("Beschreibung des Vorfalls", "long", True),
            ("Beweise (Links)", "short", False),
        ],
        "Entbannungsantrag": [
            ("Dein Discord-Name / ID", "short", True),
            ("Wann wurdest du gebannt?", "short", False),
            ("Warum solltest du entbannt werden?", "long", True),
        ],
        "Allgemeine Anfrage": [
            ("Deine Anfrage", "long", True),
        ],
    }
    fields = presets.get(ticket_type.name, [("Anliegen", "long", True)])
    for idx, (label, ftype, required) in enumerate(fields):
        session.add(
            TicketFormField(
                ticket_type_id=ticket_type.id,
                label=label,
                field_type=ftype,
                required=required,
                sort_order=idx,
                max_length=1000 if ftype == "long" else 200,
            )
        )
