# zyrahd.net

Professioneller Discord-Bot mit lila Dark-Mode-Dashboard. Bot, Dashboard und
interne API werden gemeinsam gestartet und verwenden dieselbe SQLite-Datenbank.

## Enthaltene Grundversion

- Discord OAuth2-Login mit Mitgliedschafts- und Rollenprüfung
- serverseitige Dashboard-Berechtigungen pro Discord-Rolle
- Ticket-Arten mit individuellen Discord-Modals (maximal fünf Felder)
- private Ticket-Kanäle, Übernahme, Schließen, Transcript und Web-Antworten
- Willkommensnachrichten, DMs und automatische Rollen
- persistentes Verify-Panel mit Konto-Mindestalter und Rollenwechsel
- Anti-Spam, Link-/Invite-/Caps-/Mention-Schutz und individuelle Wortfilter
- Moderationen im Dashboard sowie Slash-Commands mit fortlaufender Fallnummer
- Embed-Designer mit Live-Vorschau und direktem Versand
- Team-Ankündigungen mit Zielrollen und optionaler Lesebestätigung
- vollständiges Dashboard-Audit-Log
- responsive, animierte Oberfläche für Desktop, Tablet und Mobilgeräte

Alle im Dashboard angebotenen Aktionen sind an echte API- und Discord-Aktionen
angebunden. Discord-Rollen, Kanäle, Kategorien und Mitglieder werden in
durchsuchbaren Auswahlfeldern geladen; dafür müssen keine IDs kopiert werden.

## Voraussetzungen

- Python 3.11 oder neuer
- ein Discord-Bot und eine OAuth2-Anwendung im
  [Discord Developer Portal](https://discord.com/developers/applications)
- Schreibzugriff auf den Projektordner

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Unter Windows wird die Umgebung mit `.venv\Scripts\activate` aktiviert.

## Discord Developer Portal

1. Unter **Bot** einen Bot anlegen und den Token in `DISCORD_BOT_TOKEN`
   eintragen.
2. Diese **Privileged Gateway Intents** aktivieren:
   - Server Members Intent
   - Presence Intent
   - Message Content Intent
3. Unter **OAuth2 → General** dieselbe Redirect-URL eintragen, die in
   `DISCORD_REDIRECT_URI` steht, beispielsweise
   `https://bot.example.de/callback`.
4. Den Bot mit den Scopes `bot` und `applications.commands` einladen.

Empfohlene Bot-Rechte:

- Kanäle ansehen und verwalten
- Nachrichten senden, einbetten, verwalten und Verlauf lesen
- Dateien anhängen
- Rollen verwalten
- Mitglieder moderieren, kicken und bannen

Die Bot-Rolle muss oberhalb aller Rollen stehen, die der Bot vergeben oder
moderieren soll. Administrator-Rechte sind nicht zwingend erforderlich.

## `.env` konfigurieren

Die vorhandene Struktur bleibt bewusst klein. Rollen und Kanäle werden nur im
Dashboard konfiguriert.

```env
DISCORD_BOT_TOKEN=
GUILD_ID=
INITIAL_ADMIN_DISCORD_IDS=

DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=https://bot.example.de/callback

FLASK_SECRET_KEY=
FLASK_HOST=0.0.0.0
FLASK_PORT=5042

INTERNAL_API_HOST=127.0.0.1
INTERNAL_API_PORT=5050
INTERNAL_API_SECRET=

TIMEZONE=Europe/Berlin
```

Sichere Schlüssel lassen sich so erzeugen:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

`INITIAL_ADMIN_DISCORD_IDS` enthält eine oder mehrere, durch Komma getrennte
Discord-Benutzer-IDs. Diese Personen richten anschließend im Dashboard unter
**Berechtigungen** den rollenbasierten Zugriff ein.

Optional kann `DATABASE_URL` gesetzt werden. Ohne diese Variable wird
automatisch `data/bot.db` verwendet.

## Start

```bash
python start.py
```

Beim Start werden `data/`, Datenbank und fehlende Tabellen automatisch
erstellt. Im Log erscheinen:

- erfolgreiche Discord-Anmeldung und geladener Server
- jedes geladene Cog-Modul
- Anzahl synchronisierter Slash-Commands
- Adressen von Dashboard und interner API

Die Server-spezifische Synchronisierung über `GUILD_ID` macht neue
Slash-Commands sofort verfügbar und wird nur einmal im `setup_hook`
ausgeführt.

## Erste Einrichtung

1. Dashboard im Browser öffnen und mit einem initialen Admin anmelden.
2. Unter **Berechtigungen** Discord-Rollen und deren Zugriffe festlegen.
3. Ticket-Arten konfigurieren und das Ticket-Panel veröffentlichen.
4. Willkommen, Verify und Sicherheitsregeln konfigurieren.
5. Verify-Panel veröffentlichen und die Rollenposition des Bots prüfen.

## Hosting und Reverse Proxy

Das öffentliche Dashboard läuft standardmäßig auf Port `5042`. Die interne API
läuft ausschließlich auf `127.0.0.1:5050` und muss extern gesperrt bleiben.
Für eine öffentliche Installation sollte vor Port 5042 ein HTTPS-Reverse-Proxy
wie nginx, Caddy oder die Proxy-Funktion des Hosting-Panels verwendet werden.
`DISCORD_REDIRECT_URI` muss dabei die öffentliche HTTPS-Adresse enthalten.

Persistente Hosting-Verzeichnisse müssen mindestens `.env` und `data/`
umfassen. Der Prozess-Startbefehl ist:

```text
python start.py
```

## Datenbank und Backup

Bei der Standardkonfiguration genügt für ein Backup:

```bash
cp data/bot.db "data/bot-$(date +%Y%m%d-%H%M).db.backup"
```

Für ein konsistentes Offline-Backup sollte der Prozess kurz gestoppt werden.
Bestehende Tabellen oder Daten werden beim Start nicht gelöscht.

## Update

```bash
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
python start.py
```

Vor Updates sollte `data/bot.db` gesichert werden. Abhängigkeiten sind für
reproduzierbare Installationen in `requirements.txt` festgeschrieben.

## Tests

```bash
python -m pytest
```

Die Tests verwenden eine temporäre SQLite-Datenbank und verbinden sich nicht
mit Discord.

## Fehlerbehebung

**Slash-Commands fehlen:** `GUILD_ID` prüfen, den Bot mit
`applications.commands` neu einladen und das Synchronisierungs-Log lesen.

**Login kehrt mit Fehler zurück:** Die Redirect-URL muss in `.env` und im
Developer Portal bytegenau übereinstimmen. Der Nutzer muss Mitglied des Servers
sein.

**Rollen werden nicht vergeben:** Die Bot-Rolle steht vermutlich unterhalb der
Zielrolle oder besitzt nicht die Berechtigung „Rollen verwalten“.

**Dashboard meldet „Bot nicht erreichbar“:** Prüfen, ob Port 5050 lokal frei
ist und `INTERNAL_API_SECRET` gesetzt wurde. Diesen Port niemals öffentlich
freigeben.

**Ticket-Kanal kann nicht erstellt werden:** Der Bot benötigt „Kanäle
verwalten“ und Zugriff auf die konfigurierte Kategorie.

## Sicherheitskonzept

- OAuth2-State-Prüfung und sichere, HttpOnly Sessions
- CSRF-Schutz für Formulare und JSON-API
- serverseitige Rechteprüfung auf jeder geschützten Route
- Loopback-API mit konstantzeitlich geprüftem Secret
- Rate-Limits, Größenlimits und restriktive Browser-Sicherheitsheader
- SQLAlchemy statt zusammengesetzter SQL-Abfragen
- keine Tokens im Browser, in URLs oder Anwendungslogs
- Discord-Mentions beim frei gestalteten Embed-Versand deaktiviert
