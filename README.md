# zyrahd.net

Ein modularer Discord-Bot mit modernem Web-Dashboard für Tickets, Sicherheit,
Moderation, Willkommensnachrichten, Verifizierung, Embeds, Team-Ankündigungen
und revisionssichere Dashboard-Aktivitäten.

## Enthaltene Grundversion

- Discord OAuth2 mit Servermitgliedschafts- und Rollenprüfung
- serverseitige, rollenbasierte Dashboard-Berechtigungen
- Ticket-Erstellung in Discord und im Web, private Kanäle, Antworten,
  Statuswechsel, Formulare, Cooldowns und Limits
- durchsuchbare Rollen-/Kanalauswahl direkt aus Discord; keine manuelle
  Konfiguration von Rollen- oder Kanal-IDs
- Willkommens-/Abschiedsnachrichten und automatische Rollen
- persistentes Verify-Panel mit Account-Mindestalter
- Wortfilter mit Umgehungserkennung und Anti-Spam
- Moderationsfälle und Slash-Commands
- Embed-Designer mit Live-Vorschau
- Team-Ankündigungen mit Lesebestätigung
- Audit-Log aller Dashboard-Änderungen
- geschützte interne API

## Voraussetzungen

- Python 3.11 oder neuer
- ein Discord-Bot mit aktiviertem **Server Members Intent** und
  **Message Content Intent**
- Bot-Berechtigungen für Kanäle, Rollen, Nachrichten und die gewünschten
  Moderationsaktionen

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Trage anschließend deine vorhandenen Werte in `.env` ein. Rollen, Kanäle und
Kategorien gehören ausdrücklich nicht in diese Datei; sie werden im Dashboard
ausgewählt.

Sichere Schlüssel lassen sich beispielsweise so erzeugen:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Verwende unterschiedliche Werte für `FLASK_SECRET_KEY` und
`INTERNAL_API_SECRET`.

## Discord Developer Portal

1. Erstelle unter <https://discord.com/developers/applications> eine Anwendung.
2. Erstelle im Bereich **Bot** einen Bot und kopiere dessen Token nach
   `DISCORD_BOT_TOKEN`.
3. Aktiviere **Server Members Intent** und **Message Content Intent**.
4. Trage Application ID und Client Secret als `DISCORD_CLIENT_ID` und
   `DISCORD_CLIENT_SECRET` ein.
5. Hinterlege unter OAuth2 exakt dieselbe Redirect-URL wie in
   `DISCORD_REDIRECT_URI`, lokal zum Beispiel
   `http://localhost:5042/callback`.
6. Lade den Bot mit den Scopes `bot` und `applications.commands` ein.
   Empfohlene Rechte: View Channels, Manage Channels, Manage Roles, Send
   Messages, Manage Messages, Embed Links, Attach Files, Read Message History,
   Moderate Members, Kick Members und Ban Members.

`GUILD_ID` ist die ID des Servers. Die in `INITIAL_ADMIN_DISCORD_IDS`
aufgeführten Benutzer erhalten den initialen Vollzugriff, damit sie danach im
Dashboard weitere Discord-Rollen zuordnen können. Mehrere IDs werden durch
Kommas getrennt.

## Start

```bash
python start.py
```

Damit werden gemeinsam gestartet:

- Dashboard auf `FLASK_HOST:FLASK_PORT` (Standardport `5042`)
- interne API auf `INTERNAL_API_HOST:INTERNAL_API_PORT` (Standardport `5050`)
- Discord-Bot und serverbezogene Slash-Command-Synchronisierung

Beim ersten Start werden `data/`, die SQLite-Datenbank `data/bot.db`, die
Session-Dateien und alle Tabellen automatisch angelegt. Die sechs
Standard-Ticket-Arten werden einmalig eingefügt.

## Erste Einrichtung

1. Melde dich über Discord im Dashboard an.
2. Öffne **Berechtigungen** und ordne deinen Teamrollen die benötigten
   Dashboard-Rechte zu.
3. Konfiguriere Ticket-Arten, Support-Rollen und die Ticket-Kategorie.
4. Speichere Welcome- und Verify-Einstellungen.
5. Veröffentliche das Verify-Panel im gewählten Discord-Kanal.
6. Nutze `/ticket` als privaten Einstieg oder veröffentliche ein Ticket-Panel
   über die geschützte interne API.

Alle Auswahlfelder filtern automatisch nach Text-, Sprach-, Forum- oder
Kategoriekanälen. Verwaltete Rollen, `@everyone` und Rollen oberhalb der
höchsten Bot-Rolle sind nicht verwendbar.

## Moderationsbefehle

Die Grundversion registriert:

`/warn`, `/warnings`, `/unwarn`, `/timeout`, `/untimeout`, `/kick`, `/ban`,
`/tempban`, `/unban`, `/clear`, `/slowmode`, `/lock`, `/unlock`, `/nickname`,
`/role add`, `/role remove` und `/case`.

Jede relevante Sanktion erhält eine persistente Fallnummer. Temporäre Bans
werden auch nach einem Neustart anhand der Datenbank abgeräumt.

## Interne API

Die interne API verlangt bei jeder Anfrage:

```text
X-Internal-Secret: <INTERNAL_API_SECRET>
```

Sie sollte auf `127.0.0.1` gebunden bleiben. Verfügbare Endpunkte:

- `GET /status`
- `GET /resources`
- `POST /panels/ticket`
- `POST /panels/verify`
- `POST /embeds`
- `POST /moderation`

Beispiel:

```bash
curl -X POST http://127.0.0.1:5050/panels/ticket \
  -H "X-Internal-Secret: DEIN_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"channel_id": "123456789012345678"}'
```

## Hosting-Panel und Reverse Proxy

Lege den Startbefehl auf `python start.py` fest und verwende Python 3.11+.
Speichere `.env` als geschützte Umgebungsdatei und persistiere mindestens den
Ordner `data/`. Der öffentliche Reverse Proxy zeigt ausschließlich auf Port
`5042`; Port `5050` bleibt intern.

Für eine öffentliche Installation muss `DISCORD_REDIRECT_URI` HTTPS verwenden.
Das Dashboard setzt dann automatisch das `Secure`-Flag für Session-Cookies.
Beende TLS am Reverse Proxy und leite `X-Forwarded-Proto`, `X-Forwarded-Host`
und die Client-IP weiter.

## Backup und Update

Vor einem Update:

```bash
cp data/bot.db "data/bot-$(date +%Y%m%d-%H%M).db"
```

Danach Code aktualisieren, Abhängigkeiten installieren und `python start.py`
erneut ausführen. Migrationen legen nur fehlende Strukturen an; bestehende
Daten werden nicht gelöscht. SQLite-Backups sollten bei gestopptem Prozess
oder über das SQLite-Backup-API erstellt werden.

## Fehlerbehebung

- **Bot offline:** Token, `GUILD_ID`, aktivierte Intents und Servereinladung
  prüfen. Die Startlogs nennen Anmeldung, geladenen Server und Command-Anzahl.
- **OAuth-Fehler:** Redirect-URL in `.env` und Developer Portal müssen
  zeichengetreu identisch sein.
- **Rolle nicht auswählbar:** Die Bot-Rolle muss oberhalb der Zielrolle stehen.
- **Ticket-Kanal fehlt:** Bot-Rechte für Kategorie und Kanalverwaltung prüfen.
- **Dashboard-Zugriff verweigert:** Benutzer zunächst in
  `INITIAL_ADMIN_DISCORD_IDS` eintragen und danach Rollenrechte zuweisen.
- **SQLite gesperrt:** Nur eine Installation darf dieselbe lokale Datenbank
  verwenden; für verteilte Deployments `DATABASE_URL` auf eine gemeinsame
  SQLAlchemy-kompatible Datenbank umstellen.

Secrets und `.env` werden durch `.gitignore` ausgeschlossen. Tokens werden
weder im Browser ausgeliefert noch in Logs geschrieben.
