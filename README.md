# zyrahd.net

Professioneller Discord-Bot mit animiertem Web-Dashboard, Ticket-System,
Moderation, Sicherheitsfiltern, Verify- und Willkommenssystem.

## Enthaltene Funktionen

- Discord-OAuth2-Login mit State-Prüfung und Server-Mitgliedschaftsprüfung
- serverseitige Dashboard-Rechte über frei wählbare Discord-Rollen
- private Tickets über Discord und das Web-Dashboard
- konfigurierbare Ticket-Arten und Discord-Modalformulare
- bidirektionale Ticket-Nachrichten zwischen Discord und Dashboard
- persistente Ticket-Buttons für Übernahme, Schließen und Transcript
- Slash-Commands für Warnungen, Timeout, Kick, Ban, Nachrichten, Kanäle und Rollen
- Wortfilter mit Erkennung einfacher Umgehungen und konfigurierbares Anti-Spam
- Willkommens-/Abschiedsnachrichten und automatische Willkommensrollen
- Verify-Panel mit Account-Mindestalter und Rollenwechsel
- Embed-Designer mit Live-Vorschau
- Team-Ankündigungen
- unveränderliches Audit-Log für Dashboard-Aktionen
- durchsuchbare Rollen-, Kanal- und Mitgliederauswahl direkt vom Discord-Server
- responsive, animierte Dark-Mode-Oberfläche für Desktop und Mobilgeräte

## Voraussetzungen

- Python 3.11 oder neuer
- ein Discord-Bot und eine OAuth2-Anwendung
- die privilegierten Intents `Server Members Intent` und `Message Content Intent`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Trage anschließend deine Werte in `.env` ein. Die vorhandene Struktur wird
unverändert verwendet. Rollen, Kanäle und Kategorien gehören ausdrücklich
nicht in die `.env`; sie werden später im Dashboard ausgewählt.

Mindestens erforderlich:

```env
DISCORD_BOT_TOKEN=...
GUILD_ID=...
INITIAL_ADMIN_DISCORD_IDS=deine_discord_id
DISCORD_CLIENT_ID=...
DISCORD_CLIENT_SECRET=...
DISCORD_REDIRECT_URI=http://localhost:5042/oauth/callback
FLASK_SECRET_KEY=eine_lange_zufaellige_zeichenfolge
INTERNAL_API_SECRET=eine_andere_lange_zufaellige_zeichenfolge
```

Zufällige Secrets lassen sich beispielsweise so erzeugen:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Discord Developer Portal

1. Erstelle unter **Applications** eine Anwendung und anschließend einen Bot.
2. Aktiviere unter **Bot → Privileged Gateway Intents**:
   - Server Members Intent
   - Message Content Intent
3. Füge unter **OAuth2 → Redirects** exakt den Wert aus
   `DISCORD_REDIRECT_URI` hinzu.
4. Lade den Bot mit den Scopes `bot` und `applications.commands` ein.
5. Empfohlene Bot-Rechte:
   - Kanäle ansehen und verwalten
   - Rollen verwalten
   - Nachrichten senden, einbetten, verwalten und Verlauf lesen
   - Mitglieder moderieren, kicken und bannen
   - Dateien anhängen

Die Bot-Rolle muss über allen Rollen liegen, die der Bot vergeben oder
entfernen soll.

## Start

```bash
python start.py
```

Dieser Befehl startet:

- das Dashboard auf `FLASK_HOST:FLASK_PORT` (Standard: Port 5042),
- die nur intern gedachte Bot-API auf
  `INTERNAL_API_HOST:INTERNAL_API_PORT` (Standard: `127.0.0.1:5050`),
- den Discord-Bot.

Beim ersten Start werden `data/`, `data/bot.db`, alle Tabellen und die
Standard-Ticket-Arten automatisch angelegt. Bestehende Daten werden nicht
gelöscht. Slash-Commands werden einmalig mit der konfigurierten `GUILD_ID`
synchronisiert.

## Ersteinrichtung

1. Öffne das Dashboard und melde dich mit Discord an.
2. Der in `INITIAL_ADMIN_DISCORD_IDS` eingetragene Benutzer besitzt
   anfänglich Vollzugriff.
3. Öffne **Dashboard-Rollen** und ordne Discord-Rollen die gewünschten Rechte
   zu.
4. Wähle unter **Einstellungen** die Kanäle und Rollen für Willkommen und
   Verify.
5. Richte unter **Ticket-System** Kategorien, Support-Rollen und Formulare ein
   und veröffentliche das Ticket-Panel.

Alle geschützten Seiten und API-Aktionen prüfen die Berechtigungen auf dem
Server. Das Ausblenden eines Menüpunktes ist nicht die einzige Schutzschicht.

## Hosting-Panel und Reverse Proxy

Der Startbefehl bleibt `python start.py`. Setze im Panel die Umgebungsvariablen
oder lade eine `.env` hoch. Für eine öffentliche Domain sollte ein Reverse
Proxy HTTPS terminieren und auf Port 5042 weiterleiten.

Wichtig:

- `DISCORD_REDIRECT_URI` muss die öffentliche HTTPS-Adresse enthalten.
- Port 5050 darf nicht öffentlich freigegeben werden.
- Setze lange, unterschiedliche Werte für `FLASK_SECRET_KEY` und
  `INTERNAL_API_SECRET`.
- Sichere Schreibrechte für den Ordner `data/`.

## Datenbank und Backup

Standardpfad:

```text
data/bot.db
```

Für ein konsistentes Backup den Prozess kurz stoppen und anschließend
`data/bot.db` kopieren. Bei SQLite-WAL können im laufenden Betrieb zusätzlich
`bot.db-wal` und `bot.db-shm` existieren. Alternativ kann `DATABASE_URL` auf
eine andere SQLite-Datei zeigen.

## Update

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
python start.py
```

Fehlende Tabellen und additive Migrationen werden beim Start ausgeführt.
Vor einem Update wird ein Datenbank-Backup empfohlen.

## Fehlerbehebung

**Slash-Commands fehlen:** Prüfe `GUILD_ID`, den Scope
`applications.commands` und das Startprotokoll in `data/zyrahd.log`.

**Rollen können nicht vergeben werden:** Verschiebe die Bot-Rolle über die
Zielrolle und prüfe `Rollen verwalten`.

**OAuth2 schlägt fehl:** Redirect im Developer Portal und
`DISCORD_REDIRECT_URI` müssen Zeichen für Zeichen übereinstimmen.

**Dashboard meldet „Bot nicht erreichbar“:** Prüfe, ob Port 5050 lokal frei
ist und `INTERNAL_API_SECRET` gesetzt wurde.

**Normale Nutzer sehen nur Tickets:** Das ist beabsichtigt. Weitere Bereiche
werden über **Dashboard-Rollen** freigegeben.

## Projektstruktur

```text
bot/                  Discord-Client, Cogs, Events und interne API
dashboard/            Flask-App, OAuth, Seiten, API, Templates und Assets
database/             SQLAlchemy-Modelle, Manager und Migrationen
data/                 SQLite-Datenbank und rotierende Logs
config.py             zentrale .env-Konfiguration
start.py              gemeinsamer Startprozess
```
