# zyrahd.net — Discord Bot & Web-Dashboard

Professioneller Discord-Bot mit modernem, animiertem Dark-Mode-Dashboard (**zyrahd.net**).

## Features (Grundversion)

- Discord-OAuth2-Login mit serverseitigen Rechten
- Dashboard-Rollen & Berechtigungen
- Ticket-System (Discord + Web, Formulare, Panel, Meine Tickets)
- Willkommen / Abschied
- Verify-System (Panel aus dem Dashboard)
- Sicherheit / Automod / Wortfilter / Anti-Raid / Notfallmodus
- Moderationssystem (Slash-Commands + Dashboard)
- Embed- & Regel-Designer mit Live-Vorschau
- Team-Ankündigungen & Team-Übersicht
- Audit-Logs
- Zusätzlich: Giveaways, Vorschläge, Temp-Voice, Server-Status, Statistik-Kanäle, Reaction Roles, Logging

## Anforderungen

- Python **3.10+** (empfohlen 3.11/3.12)
- Discord-Bot mit aktivierten Privileged Intents:
  - **Server Members Intent**
  - **Message Content Intent**
  - Presence Intent empfohlen (für Online-Zähler)

## Installation

```bash
# 1) Abhängigkeiten
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2) Environment
cp .env.example .env
# .env mit deinen Werten füllen (Token, OAuth, Secrets, GUILD_ID, …)
```

### Discord Developer Portal

1. Application erstellen → Bot anlegen → Token kopieren → `DISCORD_BOT_TOKEN`
2. OAuth2 → Client ID / Secret → `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`
3. Redirect URL eintragen, z. B. `http://localhost:5042/auth/callback` → `DISCORD_REDIRECT_URI`
4. Bot einladen mit Scopes: `bot`, `applications.commands` und benötigten Permissions
5. `GUILD_ID` = deine Server-ID
6. `INITIAL_ADMIN_DISCORD_IDS` = deine Discord-User-ID (Komma-getrennt für mehrere)

### Beispiel `.env`

Die Variablennamen dürfen nicht verändert werden. Rollen-/Kanal-IDs gehören **nicht** in die `.env`, sondern ins Dashboard.

```env
DISCORD_BOT_TOKEN=
GUILD_ID=
INITIAL_ADMIN_DISCORD_IDS=

DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=http://localhost:5042/auth/callback

FLASK_SECRET_KEY=bitte-langen-zufallswert
FLASK_HOST=0.0.0.0
FLASK_PORT=5042

INTERNAL_API_HOST=127.0.0.1
INTERNAL_API_PORT=5050
INTERNAL_API_SECRET=bitte-langen-zufallswert

TIMEZONE=Europe/Berlin
```

## Start

```bash
python start.py
```

Das startet:

- Web-Dashboard auf `http://HOST:FLASK_PORT`
- Discord-Bot
- Interne API auf `INTERNAL_API_HOST:INTERNAL_API_PORT` (nur lokal, mit Secret geschützt)

Beim Start werden automatisch erstellt:

- Ordner `data/`
- SQLite-Datenbank `data/bot.db` (oder `DATABASE_URL`)
- Standard-Ticket-Arten & Config-Zeilen

## Projektstruktur

```text
start.py
config.py
requirements.txt
.env.example

bot/
├── client.py
├── internal_api.py
├── cogs/
├── views/
├── modals/
└── utils/

dashboard/
├── app.py
├── auth.py
├── routes/
├── templates/
├── static/
└── api/

database/
├── models.py
├── migrations.py
└── manager.py

data/
uploads/
```

## Hosting-Panel / VPS

1. Python 3.10+ installieren
2. Repo klonen, venv, `pip install -r requirements.txt`
3. `.env` setzen (öffentliche Redirect-URI + Port freigeben)
4. Prozess-Manager (systemd / PM2 / Panel „Custom“):

```bash
python start.py
```

Reverse-Proxy (nginx/caddy) auf Port `FLASK_PORT` legen. Die interne API (`5050`) **nicht** öffentlich exposen.

## Backup

```bash
cp data/bot.db data/bot.db.backup-$(date +%F)
```

## Update

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
python start.py
```

Schema-Migrationen laufen beim Start automatisch (ohne Datenverlust).

## Fehlerbehebung

| Problem | Lösung |
|--------|--------|
| OAuth-Fehler | Redirect-URI exakt gleich in Portal und `.env` |
| „Kein Mitglied“ | Bot/User auf dem Server? `GUILD_ID` korrekt? Scope `guilds.members.read` |
| Slash-Commands fehlen | Bot neu starten, bis zu wenigen Minuten warten, Guild-Sync prüfen |
| Rollen/Kanäle leer | Bot online? Interne API erreichbar? Secret identisch? |
| Bot sieht Nachrichten nicht | Message Content Intent aktivieren |
| Kein Dashboard-Zugriff | `INITIAL_ADMIN_DISCORD_IDS` setzen oder Rechte unter Einstellungen vergeben |

## Sicherheit

- Keine Tokens im Frontend
- CSRF-Schutz, OAuth-State-Prüfung
- Rechte serverseitig
- Interne API nur mit `INTERNAL_API_SECRET`
- Secrets nicht committen (`.env` ist in `.gitignore`)

---

© zyrahd.net
