from __future__ import annotations

import pytest

from config import Settings
from dashboard.app import create_app


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
    monkeypatch.setattr(
        "dashboard.api.bot_request",
        lambda method, path, payload=None: (
            {
                "online": True,
                "guild_name": "Testserver",
                "members": 120,
                "online_members": 35,
                "guild_icon": None,
                "latency_ms": 20,
            }
            if path == "/status"
            else {"roles": [], "channels": [], "members": []}
        ),
    )
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


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"service": "zyrahd.net", "status": "ok"}


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


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
