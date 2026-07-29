"""Datenbankmodelle für Bot und Dashboard."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.manager import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_loads(value: Optional[str], default: Any = None) -> Any:
    if value is None or value == "":
        return default if default is not None else []
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default if default is not None else []


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")

    @property
    def json(self) -> Any:
        return _json_loads(self.value, default={})

    @json.setter
    def json(self, data: Any) -> None:
        self.value = _json_dumps(data)


class DashboardPermission(Base, TimestampMixin):
    __tablename__ = "dashboard_permissions"
    __table_args__ = (UniqueConstraint("role_id", name="uq_dashboard_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role_name: Mapped[str] = mapped_column(String(120), default="")
    # JSON-Liste von Permission-Keys
    permissions: Mapped[str] = mapped_column(Text, default="[]")

    def get_permissions(self) -> list[str]:
        return _json_loads(self.permissions, default=[])

    def set_permissions(self, perms: list[str]) -> None:
        self.permissions = _json_dumps(sorted(set(perms)))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(255))
    area: Mapped[str] = mapped_column(String(80), default="general")
    before_value: Mapped[str] = mapped_column(Text, default="")
    after_value: Mapped[str] = mapped_column(Text, default="")
    ip_address: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TicketType(Base, TimestampMixin):
    __tablename__ = "ticket_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    emoji: Mapped[str] = mapped_column(String(40), default="🎫")
    color: Mapped[str] = mapped_column(String(20), default="#9B5CFF")
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    staff_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    transcript_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    max_open_per_user: Mapped[int] = mapped_column(Integer, default=1)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    name_format: Mapped[str] = mapped_column(String(120), default="ticket-{username}-{id}")
    greeting_message: Mapped[str] = mapped_column(Text, default="Willkommen {mention}! Ein Teammitglied hilft dir bald.")
    ping_staff: Mapped[bool] = mapped_column(Boolean, default=True)
    open_hours_json: Mapped[str] = mapped_column(Text, default="{}")
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    inactivity_close_hours: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    fields: Mapped[list["TicketFormField"]] = relationship(
        back_populates="ticket_type", cascade="all, delete-orphan"
    )
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="ticket_type")

    def get_staff_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.staff_role_ids, default=[])]

    def set_staff_roles(self, role_ids: list[int]) -> None:
        self.staff_role_ids = _json_dumps([int(x) for x in role_ids])


class TicketFormField(Base, TimestampMixin):
    __tablename__ = "ticket_form_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    field_type: Mapped[str] = mapped_column(String(40), default="short")  # short, long, select
    placeholder: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    min_length: Mapped[int] = mapped_column(Integer, default=0)
    max_length: Mapped[int] = mapped_column(Integer, default=1000)
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    ticket_type: Mapped["TicketType"] = relationship(back_populates="fields")

    def get_options(self) -> list[str]:
        return _json_loads(self.options_json, default=[])


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_number: Mapped[int] = mapped_column(Integer, index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"), index=True)
    opener_id: Mapped[int] = mapped_column(BigInteger, index=True)
    opener_name: Mapped[str] = mapped_column(String(120), default="")
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    claimed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    claimed_by_name: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    title: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    form_data: Mapped[str] = mapped_column(Text, default="{}")
    close_reason: Mapped[str] = mapped_column(Text, default="")
    closed_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating_comment: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    added_users: Mapped[str] = mapped_column(Text, default="[]")
    transcript_path: Mapped[str] = mapped_column(String(255), default="")
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket_type: Mapped["TicketType"] = relationship(back_populates="tickets")
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )

    def get_form_data(self) -> dict:
        return _json_loads(self.form_data, default={})

    def get_added_users(self) -> list[int]:
        return [int(x) for x in _json_loads(self.added_users, default=[])]


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_name: Mapped[str] = mapped_column(String(120), default="")
    author_avatar: Mapped[str] = mapped_column(String(255), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(20), default="discord")  # discord | web | system
    discord_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    ticket: Mapped["Ticket"] = relationship(back_populates="messages")

    def get_attachments(self) -> list[dict]:
        return _json_loads(self.attachments_json, default=[])


class TicketPanel(Base, TimestampMixin):
    __tablename__ = "ticket_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="Support-Center")
    description: Mapped[str] = mapped_column(
        Text,
        default=(
            "Benötigst du Hilfe oder möchtest du Kontakt mit unserem Team aufnehmen?\n"
            "Klicke auf „Ticket erstellen“ und wähle anschließend den passenden Bereich aus."
        ),
    )
    color: Mapped[str] = mapped_column(String(20), default="#9B5CFF")
    button_label: Mapped[str] = mapped_column(String(80), default="🎫 Ticket erstellen")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WelcomeConfig(Base, TimestampMixin):
    __tablename__ = "welcome_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    use_embed: Mapped[bool] = mapped_column(Boolean, default=True)
    title: Mapped[str] = mapped_column(String(200), default="Willkommen auf {server}!")
    description: Mapped[str] = mapped_column(
        Text, default="Hey {mention}, schön dass du da bist! Du bist Mitglied #{member_count}."
    )
    color: Mapped[str] = mapped_column(String(20), default="#9B5CFF")
    thumbnail_url: Mapped[str] = mapped_column(String(255), default="")
    image_url: Mapped[str] = mapped_column(String(255), default="")
    footer: Mapped[str] = mapped_column(String(200), default="{server}")
    role_ids: Mapped[str] = mapped_column(Text, default="[]")
    dm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dm_message: Mapped[str] = mapped_column(Text, default="Willkommen auf {server}, {username}!")
    plain_message: Mapped[str] = mapped_column(Text, default="Willkommen {mention}!")

    def get_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.role_ids, default=[])]

    def set_roles(self, role_ids: list[int]) -> None:
        self.role_ids = _json_dumps([int(x) for x in role_ids])


class GoodbyeConfig(Base, TimestampMixin):
    __tablename__ = "goodbye_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    use_embed: Mapped[bool] = mapped_column(Boolean, default=True)
    title: Mapped[str] = mapped_column(String(200), default="Auf Wiedersehen")
    description: Mapped[str] = mapped_column(Text, default="{username} hat den Server verlassen.")
    color: Mapped[str] = mapped_column(String(20), default="#6B4C9A")
    image_url: Mapped[str] = mapped_column(String(255), default="")
    show_kick_ban_reason: Mapped[bool] = mapped_column(Boolean, default=True)
    plain_message: Mapped[str] = mapped_column(Text, default="{username} hat den Server verlassen.")


class VerifyConfig(Base, TimestampMixin):
    __tablename__ = "verify_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    verified_role_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    remove_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    title: Mapped[str] = mapped_column(String(200), default="Verifizierung")
    description: Mapped[str] = mapped_column(
        Text, default="Klicke auf den Button, um dich zu verifizieren und Zugang zum Server zu erhalten."
    )
    color: Mapped[str] = mapped_column(String(20), default="#9B5CFF")
    button_label: Mapped[str] = mapped_column(String(80), default="✅ Verifizieren")
    button_emoji: Mapped[str] = mapped_column(String(40), default="")
    captcha_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    min_account_age_days: Mapped[int] = mapped_column(Integer, default=0)
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    dm_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    dm_message: Mapped[str] = mapped_column(Text, default="Du wurdest erfolgreich verifiziert. Willkommen!")

    def get_remove_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.remove_role_ids, default=[])]

    def set_remove_roles(self, role_ids: list[int]) -> None:
        self.remove_role_ids = _json_dumps([int(x) for x in role_ids])


class WordFilter(Base, TimestampMixin):
    __tablename__ = "word_filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern: Mapped[str] = mapped_column(String(200))
    match_type: Mapped[str] = mapped_column(String(20), default="contains")  # exact | contains
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_message: Mapped[bool] = mapped_column(Boolean, default=True)
    warn_user: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=0)
    kick: Mapped[bool] = mapped_column(Boolean, default=False)
    ban: Mapped[bool] = mapped_column(Boolean, default=False)
    strikes_needed: Mapped[int] = mapped_column(Integer, default=1)
    response_message: Mapped[str] = mapped_column(Text, default="")
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    allowed_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
    exempt_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    def get_allowed_channels(self) -> list[int]:
        return [int(x) for x in _json_loads(self.allowed_channel_ids, default=[])]

    def get_exempt_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.exempt_role_ids, default=[])]


class SecurityConfig(Base, TimestampMixin):
    __tablename__ = "security_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anti_spam: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_link: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_invite: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_mention_spam: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_caps: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_zalgo: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_duplicate: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_mass_emoji: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_raid: Mapped[bool] = mapped_column(Boolean, default=True)
    anti_bot_join: Mapped[bool] = mapped_column(Boolean, default=False)
    min_account_age_days: Mapped[int] = mapped_column(Integer, default=0)
    join_cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    raid_join_threshold: Mapped[int] = mapped_column(Integer, default=8)
    raid_join_window_seconds: Mapped[int] = mapped_column(Integer, default=10)
    raid_timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)
    raid_lock_channels: Mapped[bool] = mapped_column(Boolean, default=True)
    emergency_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    log_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    exempt_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    exempt_channel_ids: Mapped[str] = mapped_column(Text, default="[]")
    whitelist_user_ids: Mapped[str] = mapped_column(Text, default="[]")
    link_whitelist: Mapped[str] = mapped_column(Text, default="[]")
    spam_messages: Mapped[int] = mapped_column(Integer, default=5)
    spam_seconds: Mapped[int] = mapped_column(Integer, default=5)
    mention_limit: Mapped[int] = mapped_column(Integer, default=5)
    caps_percent: Mapped[int] = mapped_column(Integer, default=70)
    emoji_limit: Mapped[int] = mapped_column(Integer, default=10)

    def get_exempt_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.exempt_role_ids, default=[])]

    def get_exempt_channels(self) -> list[int]:
        return [int(x) for x in _json_loads(self.exempt_channel_ids, default=[])]

    def get_whitelist_users(self) -> list[int]:
        return [int(x) for x in _json_loads(self.whitelist_user_ids, default=[])]

    def get_link_whitelist(self) -> list[str]:
        return _json_loads(self.link_whitelist, default=[])


class ModCase(Base, TimestampMixin):
    __tablename__ = "mod_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    user_name: Mapped[str] = mapped_column(String(120), default="")
    moderator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    moderator_name: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(40), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="active")
    revoked_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class EmbedMessage(Base, TimestampMixin):
    __tablename__ = "embed_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(80), default="general")
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    embed_json: Mapped[str] = mapped_column(Text, default="{}")
    buttons_json: Mapped[str] = mapped_column(Text, default="[]")
    published: Mapped[bool] = mapped_column(Boolean, default=False)

    def get_embed(self) -> dict:
        return _json_loads(self.embed_json, default={})

    def get_buttons(self) -> list[dict]:
        return _json_loads(self.buttons_json, default=[])


class TeamAnnouncement(Base, TimestampMixin):
    __tablename__ = "team_announcements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    target_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    publish_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    require_ack: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by_name: Mapped[str] = mapped_column(String(120), default="")
    acknowledgments: Mapped[str] = mapped_column(Text, default="[]")

    def get_target_roles(self) -> list[int]:
        return [int(x) for x in _json_loads(self.target_role_ids, default=[])]

    def get_acks(self) -> list[dict]:
        return _json_loads(self.acknowledgments, default=[])


class TeamMember(Base, TimestampMixin):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("user_id", name="uq_team_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(120), default="")
    display_name: Mapped[str] = mapped_column(String(120), default="")
    avatar_url: Mapped[str] = mapped_column(String(255), default="")
    role_ids: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="active")
    absence_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    absence_reason: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    tickets_handled: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    mod_cases: Mapped[int] = mapped_column(Integer, default=0)
    kudos: Mapped[int] = mapped_column(Integer, default=0)
    warnings: Mapped[int] = mapped_column(Integer, default=0)


class TeamConfig(Base, TimestampMixin):
    __tablename__ = "team_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    support_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    mod_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    lead_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    admin_role_ids: Mapped[str] = mapped_column(Text, default="[]")

    def get_roles(self, field: str) -> list[int]:
        return [int(x) for x in _json_loads(getattr(self, field), default=[])]

    def set_roles(self, field: str, role_ids: list[int]) -> None:
        setattr(self, field, _json_dumps([int(x) for x in role_ids]))


class LogConfig(Base, TimestampMixin):
    __tablename__ = "log_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_delete: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_edit: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    member_join: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    member_leave: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    role_update: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    nickname: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    voice: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    channel: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    role_create: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    bans: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    kicks: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    timeouts: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    automod: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    tickets: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    applications: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    dashboard: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str] = mapped_column(String(120), default="")
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="")
    action_taken: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class UserStrike(Base, TimestampMixin):
    __tablename__ = "user_strikes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    filter_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    count: Mapped[int] = mapped_column(Integer, default=1)


class Suggestion(Base, TimestampMixin):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    author_id: Mapped[int] = mapped_column(BigInteger, index=True)
    author_name: Mapped[str] = mapped_column(String(120), default="")
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open")
    upvotes: Mapped[int] = mapped_column(Integer, default=0)
    downvotes: Mapped[int] = mapped_column(Integer, default=0)
    staff_comment: Mapped[str] = mapped_column(Text, default="")
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    thread_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class Giveaway(Base, TimestampMixin):
    __tablename__ = "giveaways"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prize: Mapped[str] = mapped_column(String(200))
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    required_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    forbidden_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    min_account_age_days: Mapped[int] = mapped_column(Integer, default=0)
    min_server_days: Mapped[int] = mapped_column(Integer, default=0)
    entrants: Mapped[str] = mapped_column(Text, default="[]")
    winner_ids: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(40), default="active")
    created_by: Mapped[int] = mapped_column(BigInteger, default=0)


class ReactionRolePanel(Base, TimestampMixin):
    __tablename__ = "reaction_role_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    title: Mapped[str] = mapped_column(String(200), default="Rollen wählen")
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="#9B5CFF")
    exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    roles_json: Mapped[str] = mapped_column(Text, default="[]")


class TempVoiceConfig(Base, TimestampMixin):
    __tablename__ = "temp_voice_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    create_channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    category_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name_format: Mapped[str] = mapped_column(String(120), default="{username}'s Raum")
    user_limit: Mapped[int] = mapped_column(Integer, default=0)


class TempVoiceChannel(Base, TimestampMixin):
    __tablename__ = "temp_voice_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)


class ServerStatChannel(Base, TimestampMixin):
    __tablename__ = "server_stat_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stat_type: Mapped[str] = mapped_column(String(40), unique=True)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    name_format: Mapped[str] = mapped_column(String(120), default="{name}: {value}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class ServerStatusConfig(Base, TimestampMixin):
    __tablename__ = "server_status_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    channel_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    server_name: Mapped[str] = mapped_column(String(120), default="")
    server_type: Mapped[str] = mapped_column(String(40), default="minecraft")
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    online_message: Mapped[str] = mapped_column(Text, default="🟢 Online")
    offline_message: Mapped[str] = mapped_column(Text, default="🔴 Offline")
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)
    last_online: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_players: Mapped[int] = mapped_column(Integer, default=0)
    last_max_players: Mapped[int] = mapped_column(Integer, default=0)
    last_ping: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str] = mapped_column(String(40), default="unknown")


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
