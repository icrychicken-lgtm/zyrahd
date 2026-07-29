"""Database engine, lifecycle helpers and lightweight migrations."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from config import settings
from database.migrations import migrate
from database.models import AuditLog, Base, GuildSetting, TicketFormField, TicketType

engine_options: dict[str, Any] = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(settings.database_url, **engine_options)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionFactory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
db_session = scoped_session(SessionFactory)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DEFAULT_TICKET_TYPES = (
    ("Support", "Technische Fragen und allgemeine Hilfe", "🛟"),
    ("Bewerbung", "Bewirb dich für unser Team", "📝"),
    ("Partnerschaft", "Anfragen für eine Partnerschaft", "🤝"),
    ("Beschwerde", "Melde ein Problem vertraulich", "⚖️"),
    ("Entbannungsantrag", "Beantrage die Aufhebung einer Sanktion", "🔓"),
    ("Allgemeine Anfrage", "Alles, was in keine andere Kategorie passt", "💬"),
)


def init_database() -> None:
    """Create missing tables and non-destructively seed a new guild."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        migrate(connection)
    if not settings.guild_id:
        return
    guild_id = str(settings.guild_id)
    with session_scope() as session:
        exists = session.scalar(
            select(TicketType.id).where(TicketType.guild_id == guild_id).limit(1)
        )
        if exists:
            return
        for position, (name, description, emoji) in enumerate(DEFAULT_TICKET_TYPES):
            ticket_type = TicketType(
                guild_id=guild_id,
                name=name,
                description=description,
                emoji=emoji,
                position=position,
            )
            ticket_type.fields.append(
                TicketFormField(
                    label="Wie können wir dir helfen?",
                    field_type="long",
                    placeholder="Beschreibe dein Anliegen möglichst genau …",
                    min_length=10,
                    max_length=1000,
                )
            )
            session.add(ticket_type)


def get_setting(session: Session, guild_id: str, key: str, default: Any = None) -> Any:
    row = session.scalar(
        select(GuildSetting).where(
            GuildSetting.guild_id == guild_id, GuildSetting.key == key
        )
    )
    if not row:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, json.JSONDecodeError):
        return default


def set_setting(session: Session, guild_id: str, key: str, value: Any) -> Any:
    row = session.scalar(
        select(GuildSetting).where(
            GuildSetting.guild_id == guild_id, GuildSetting.key == key
        )
    )
    previous = json.loads(row.value) if row else None
    if row:
        row.value = json.dumps(value, ensure_ascii=False)
    else:
        session.add(
            GuildSetting(
                guild_id=guild_id,
                key=key,
                value=json.dumps(value, ensure_ascii=False),
            )
        )
    return previous


def add_audit(
    session: Session,
    *,
    guild_id: str,
    user_id: str,
    user_name: str,
    action: str,
    area: str,
    old_value: Any = None,
    new_value: Any = None,
    ip_address: str | None = None,
) -> None:
    session.add(
        AuditLog(
            guild_id=guild_id,
            user_id=user_id,
            user_name=user_name,
            action=action,
            area=area,
            old_value=json.dumps(old_value, ensure_ascii=False, default=str),
            new_value=json.dumps(new_value, ensure_ascii=False, default=str),
            ip_address=ip_address,
        )
    )
