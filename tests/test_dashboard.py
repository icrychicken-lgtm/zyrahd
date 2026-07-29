from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from bot.services import BotService
from config import Settings
from dashboard.app import create_app
from database.models import Ticket, TicketType, db


@pytest.fixture()
def app(tmp_path, monkeypatch):
    test_settings = Settings(
        discord_bot_token="test-token",
        guild_id=123456789,
        initial_admin_ids=frozenset({42}),
        discord_client_id="client",
        discord_client_secret="secret",
        discord_redirect_uri="http://localhost/callback",
        flask_secret_key="test-secret",
        flask_host="127.0.0.1",
        flask_port=5042,
        internal_api_host="127.0.0.1",
        internal_api_port=5050,
        internal_api_secret="internal-secret",
        timezone="Europe/Berlin",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    monkeypatch.setattr("dashboard.api.GUILD_ID", str(test_settings.guild_id))
    monkeypatch.setattr("dashboard.permissions.settings", test_settings)

    def fake_bot_request(method, path, payload=None):
        if path == "/status":
            return {
                "online": True,
                "guild_name": "Testserver",
                "members": 120,
                "online_members": 35,
                "guild_icon": None,
                "latency_ms": 20,
            }
        if path == "/resources":
            return {
                "roles": [
                    {
                        "id": "654",
                        "name": "Mitglied",
                        "usable": True,
                        "managed": False,
                    }
                ],
                "channels": [{"id": "987", "name": "willkommen", "type": "text"}],
                "members": [],
            }
        return {}

    monkeypatch.setattr("dashboard.api.bot_request", fake_bot_request)
    application = create_app(test_settings)
    application.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client):
    with client.session_transaction() as session:
        session["discord_user"] = {
            "id": "42",
            "username": "Admin",
            "global_name": "Test Admin",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png",
        }
        session["discord_roles"] = []
        session["roles_checked_at"] = time.time()


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"service": "zyrahd.net", "status": "ok"}


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_all_dashboard_sections_render_for_admin(client):
    login(client)
    sections = (
        "overview",
        "tickets",
        "welcome",
        "verify",
        "security",
        "moderation",
        "designer",
        "announcements",
        "permissions",
        "audit",
    )
    for section in sections:
        response = client.get(f"/dashboard/{section}")
        assert response.status_code == 200, section
        assert b"zyrahd.net" in response.data


def test_default_ticket_types_are_seeded(client):
    login(client)
    response = client.get("/api/ticket-types")
    assert response.status_code == 200
    names = {item["name"] for item in response.json["items"]}
    assert names == {
        "Support",
        "Bewerbung",
        "Partnerschaft",
        "Beschwerde",
        "Entbannungsantrag",
        "Allgemeine Anfrage",
    }


def test_settings_are_saved_and_unknown_keys_rejected(client):
    login(client)
    response = client.put(
        "/api/settings/welcome",
        json={
            "enabled": True,
            "channel_id": "987",
            "message": "Hallo {mention}",
            "embed": True,
            "title": "Willkommen",
            "color": "#8b5cf6",
            "role_ids": ["654"],
            "dm_enabled": False,
        },
    )
    assert response.status_code == 200
    assert response.json["settings"]["enabled"] is True

    invalid = client.put(
        "/api/settings/welcome",
        json={"enabled": True, "arbitrary_id": "not-allowed"},
    )
    assert invalid.status_code == 400


def test_ticket_creation_persists_after_discord_channel_is_created(app, monkeypatch):
    class FakeMember:
        id = 77
        display_name = "Test User"
        mention = "<@77>"

    class FakeChannel:
        id = 999

        async def send(self, **_kwargs):
            return SimpleNamespace(id=1000)

        async def delete(self, **_kwargs):
            raise AssertionError("Successful ticket channel must not be deleted")

    class FakeGuild:
        default_role = object()
        me = object()

        def __init__(self):
            self.channel = FakeChannel()

        def get_member(self, user_id):
            return FakeMember() if user_id == 77 else None

        def get_channel(self, _channel_id):
            return None

        def get_role(self, _role_id):
            return None

        async def create_text_channel(self, *_args, **_kwargs):
            return self.channel

    guild = FakeGuild()
    fake_bot = SimpleNamespace(get_guild=lambda _guild_id: guild)
    monkeypatch.setattr("bot.services.settings", SimpleNamespace(guild_id=123456789))
    service = BotService(fake_bot, app)

    with app.app_context():
        ticket_type = db.session.scalar(
            db.select(TicketType).where(TicketType.name == "Support")
        )
        ticket_type_id = ticket_type.id

    import asyncio

    ticket = asyncio.run(
        service.create_ticket(
            ticket_type_id,
            77,
            "Test User",
            {"field-0": "Ich brauche Hilfe."},
        )
    )

    with app.app_context():
        stored = db.session.get(Ticket, ticket.id)
        assert stored is not None
        assert stored.status == "open"
        assert stored.channel_id == "999"


def test_removed_guild_member_loses_dashboard_session(client, monkeypatch):
    login(client)
    with client.session_transaction() as session:
        session["roles_checked_at"] = 0
    monkeypatch.setattr(
        "dashboard.auth.requests.get",
        lambda *_args, **_kwargs: SimpleNamespace(status_code=404, ok=False),
    )

    response = client.get("/dashboard")

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "discord_user" not in session
