"""Database engine, scoped sessions, settings, and audit helpers."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from config import settings
from database.models import AuditLog, Base, GuildSetting, JsonMixin, TicketType


engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
if settings.database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(settings.database_url, **engine_kwargs)
SessionFactory = scoped_session(
    sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
)


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
        SessionFactory.remove()


def init_database(guild_id: int | str | None = None) -> None:
    Base.metadata.create_all(engine)
    if guild_id:
        seed_ticket_types(str(guild_id))


def seed_ticket_types(guild_id: str) -> None:
    defaults = [
        (
            "Support",
            "Technische Fragen und allgemeine Hilfe",
            "🛟",
            [
                {
                    "id": "topic",
                    "label": "Wobei benötigst du Hilfe?",
                    "type": "long",
                    "required": True,
                    "max_length": 1000,
                },
                {
                    "id": "tried",
                    "label": "Was hast du bereits versucht?",
                    "type": "long",
                    "required": False,
                    "max_length": 1000,
                },
            ],
        ),
        (
            "Bewerbung",
            "Bewirb dich für unser Team",
            "💼",
            [
                {
                    "id": "about",
                    "label": "Erzähle uns von dir",
                    "type": "long",
                    "required": True,
                    "max_length": 1000,
                },
                {
                    "id": "experience",
                    "label": "Welche Erfahrungen besitzt du?",
                    "type": "long",
                    "required": True,
                    "max_length": 1000,
                },
            ],
        ),
        ("Partnerschaft", "Anfragen anderer Communities", "🤝", []),
        ("Beschwerde", "Melde ein Problem vertraulich", "⚖️", []),
        ("Entbannungsantrag", "Beantrage die Prüfung einer Sperre", "🔓", []),
        ("Allgemeine Anfrage", "Alles, was sonst nirgends passt", "💬", []),
    ]
    with session_scope() as db:
        if db.scalar(
            select(TicketType.id).where(TicketType.guild_id == guild_id).limit(1)
        ):
            return
        for name, description, emoji, fields in defaults:
            item = TicketType(
                guild_id=guild_id,
                name=name,
                description=description,
                emoji=emoji,
            )
            item.form_fields = fields
            db.add(item)


def get_setting(guild_id: str, module: str, default: Any = None) -> Any:
    with session_scope() as db:
        row = db.scalar(
            select(GuildSetting).where(
                GuildSetting.guild_id == guild_id, GuildSetting.module == module
            )
        )
        return row.value if row else (default if default is not None else {})


def set_setting(
    guild_id: str, module: str, value: dict[str, Any], user_id: str | None
) -> dict[str, Any]:
    with session_scope() as db:
        row = db.scalar(
            select(GuildSetting).where(
                GuildSetting.guild_id == guild_id, GuildSetting.module == module
            )
        )
        if row is None:
            row = GuildSetting(guild_id=guild_id, module=module)
            db.add(row)
        row.value = value
        row.updated_by = user_id
        row.updated_at = datetime.now(timezone.utc)
    return value


def write_audit(
    guild_id: str,
    user_id: str,
    user_name: str,
    action: str,
    area: str,
    *,
    target: str | None = None,
    before: Any = None,
    after: Any = None,
    ip_address: str | None = None,
) -> None:
    with session_scope() as db:
        db.add(
            AuditLog(
                guild_id=guild_id,
                user_id=user_id,
                user_name=user_name[:100],
                action=action[:100],
                area=area[:48],
                target=(target or "")[:150] or None,
                before_json=JsonMixin.encode(before) if before is not None else None,
                after_json=JsonMixin.encode(after) if after is not None else None,
                ip_address=(ip_address or "")[:64] or None,
            )
        )
