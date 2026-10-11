# GeekStation Terminal

Wiederverwendbares Backend für Terminal-Aufträge und CLI-Agenten in Office und Habibis.

## Aktueller Stand

Der erste Backend-Prototyp bietet eine lokale HTTP-API, echte Prozessausführung,
SQLite-Verläufe und Live-Ausgabe über Server-Sent Events (SSE).
Eine Weboberfläche und die vorhandene Agenteninstallation sind noch nicht angeschlossen.

Vorhanden:
- Empfangsbestätigung mit Auftrags-ID und echtem Status.
- Diagnosevorlage und konfigurierbarer CLI-Adapter ohne Shell-Interpolation.
- Gespeicherte Ausgabe, Exit-Code, Timeout und Neustarterkennung.
- Token-Schutz für alle Endpunkte, Bindung ausschließlich an localhost.

Geplant:
- Schließbare Terminal-/Chat-Reiter, Agentenstatus und Jobvorlagen.
- Integration vorhandener Office-/Habibis-Agenten und Zugriff auf R2D2.
- Agentenaustausch, Sprachsteuerung, Stummschaltung und WAV-Aufzeichnung.
- Interaktives PTY-Terminal, Abbruch laufender Jobs und Mehrbenutzerbetrieb.

## Start

Linux/macOS (POSIX), Python 3.11 oder neuer, keine zusätzlichen Pakete nötig.
Windows wird bis zur Umsetzung sicherer ACLs und Prozessbaum-Bereinigung abgewiesen:

```bash
export TERMINAL_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m backend.server
```

Der Server läuft unter `http://127.0.0.1:8765`. Der Token gehört nicht ins Repository.
Daten: `data/terminal.sqlite3`; mit `TERMINAL_DATA_DIR` anderen dauerhaften Ordner wählen.
Datenordner erhalten 0700, Datenbanken 0600; vorhandene Rechte werden korrigiert.
Symlinks, Datenbank-Hardlinks und fremde Eigentümer werden abgewiesen.
`.env.example` dokumentiert Variablen; die Datei wird nicht automatisch geladen.

```bash
curl -H "Authorization: Bearer $TERMINAL_API_TOKEN" http://127.0.0.1:8765/templates
curl -H "Authorization: Bearer $TERMINAL_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"template":"diagnostics","prompt":""}' http://127.0.0.1:8765/jobs
```

`GET /jobs`: Verlauf; `GET /jobs/ID`: Status und Ergebnis-Metadaten;
`GET /jobs/ID/events`: Live-Ausgabe und gespeicherte Ereignisse.
`Last-Event-ID` setzt einen unterbrochenen Stream fort.
Clients benötigen Header-Unterstützung, beispielsweise Streaming-Fetch.

## CLI-Agent anschließen

`TERMINAL_AGENT_ARGV` ist ein JSON-Array des tatsächlichen CLI-Aufrufs.
Genau ein Argument muss `{prompt}` lauten und wird durch den Auftrag ersetzt.
Strukturbeispiel: `["/pfad/zur/cli", "nicht-interaktiver-modus", "{prompt}"]`.
Die realen Argumente müssen an der vorhandenen Installation geprüft werden.
Ohne Konfiguration steht nur die Diagnosevorlage bereit.
`TERMINAL_WORKDIR` bestimmt das Arbeitsverzeichnis des Prozesses.

Der Adapter vergibt keine zusätzlichen Rechte; Prozesse laufen mit den Rechten
seines Serverkontos. Der API-Token wird aus der Kindprozess-Umgebung entfernt;
andere Umgebungsvariablen werden weiterhin vererbt. SIGTERM und Strg+C stoppen
registrierte Prozessgruppen und warten auf die Job-Threads. SIGKILL und Stromausfall
können nicht abgefangen werden; hierfür ist ein Supervisor erforderlich.

Maximal 16 HTTP-Verbindungen, Backlog 16, zehn Sekunden absolute Frist für Header
und Body; SSE-Verbindungen haben 150 Sekunden Frist und können über Last-Event-ID
fortgesetzt werden. Überzählige Verbindungen werden vor dem Threadstart geschlossen.

Für Dienst- und Fernbetrieb fehlen noch kontrollierter
HTTPS-Zugang, ein geeignetes Dienstkonto, Backup und Aufbewahrungsregeln.
GitHub Pages allein kann dieses Backend nicht ausführen.

## Struktur

| Pfad | Inhalt |
|---|---|
| `backend/` | HTTP-API, Prozessadapter, SQLite-Speicher |
| `frontend/` | Nächster UI-Meilenstein, noch keine Oberfläche |
| `docs/architecture.md` | Schnittstellen und Grenzen |
| `tests/` | Prozesse, Speicherung, Fehlerfälle und HTTP-/SSE-Ablauf |

```bash
python -m unittest discover -s tests -v
```

Nächster Meilenstein: vorhandene Agenten-CLI anschließen und den vollständigen
Auftragsablauf über eine Weboberfläche bedienen. Vorhandene Office-/Habibis-Dateien
waren bei dieser Umsetzung nicht verfügbar; ihre Integration bleibt offen.

Sicherheitsänderungen und Prüfung: [docs/security-fixes.md](docs/security-fixes.md).
