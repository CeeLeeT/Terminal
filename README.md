# GeeKStation Terminal

Lokales Backend für nachvollziehbare Terminal-Aufträge und die spätere Anbindung von GeeKStation-, Office- und Habibis-Agenten. Aufträge sollen eine ID, einen gespeicherten Verlauf und ein überprüfbares Ergebnis erhalten.

## Projektstand und Geltungsbereich

Stand: 11. Oktober 2026. Das Repository enthält die lokale Auftrags-API, den CLI-Adapter, die zugehörigen Tests und diese Projektdokumentation. Backend und Dokumentation aus [PR #1](https://github.com/CeeLeeT/Terminal/pull/1) und [PR #2](https://github.com/CeeLeeT/Terminal/pull/2) sind gemeinsam in `main` integriert.

Die API und Sicherheitskorrekturen wurden durch 15 automatisierte Tests unter Linux/Python 3.12 geprüft. Die tatsächliche GeeKStation-Agenteninstallation und Zielgeräte-Konfiguration sind noch nicht bestätigt.

| Bereich | Stand |
|---|---|
| HTTP-API, Prozessausführung, SQLite-Verlauf, SSE | Implementiert |
| Nicht interaktiver CLI-Adapter | Implementiert; tatsächliche Agenteninstallation noch zu prüfen |
| Weboberfläche | Geplant; `frontend/` enthält nur eine Beschreibung |
| GeeKStation / Office / Habibis / R2D2 | Noch nicht angeschlossen |
| PTY, Tastatureingabe, Jobabbruch, Mehrbenutzerbetrieb | Noch nicht implementiert |
| HTTPS-Fernzugriff, Supervisor, Backups, Aufbewahrung | Vor dauerhaftem Betrieb zu ergänzen |

GitHub Pages kann Dokumentation ausliefern, aber dieses Python-Backend nicht ausführen. `_config.yml` ist keine Backend-Konfiguration.

## Architektur

Eine Python-Serverinstanz nimmt authentifizierte HTTP-Aufträge an. `backend/jobs.py` speichert Auftrag und Ereignisse in SQLite und startet pro Auftrag einen Prozess. `backend/server.py` liefert Status und gespeicherte oder neue Ausgabe über HTTP beziehungsweise Server-Sent Events (SSE).

Der Prozess erhält einzelne Argumente ohne Shell-Interpolation. Registrierte Prozessgruppen werden beim geordneten Serverende (SIGTERM/Strg+C) beendet und die Job-Threads abgeschlossen. Standardausgabe und Fehlerausgabe werden zusammengeführt und als UTF-8 mit Ersatz für ungültige Zeichen gespeichert. Es gibt weder PTY noch offene Standardeingabe; interaktive Rückfragen eines CLI-Agenten werden damit nicht unterstützt.

Aufträge wechseln von `queued` zu `running`, danach zu `completed`, `failed` oder `timed_out`. Beim Initialisieren der Jobverwaltung werden zuvor aktive Aufträge als `interrupted` markiert. Sie werden nicht automatisch erneut ausgeführt. Die Daten sind persistent; die Ausführung selbst ist keine dauerhafte Warteschlange mit Wiederanlaufgarantie.

Es gibt maximal zwei aktive Aufträge. Ein weiterer Auftrag wird abgewiesen, nicht zur späteren Ausführung eingereiht. Nur eine Serverinstanz darf dieselbe Datenbank verwalten.

### Dateistruktur

Diese Pfade sind im Repository vorhanden:

| Pfad | Aufgabe |
|---|---|
| `backend/__init__.py` | Python-Paket |
| `backend/server.py` | HTTP, Authentifizierung, SSE, Serverstart |
| `backend/jobs.py` | Prozessadapter, Status und SQLite-Speicher |
| `docs/architecture.md` | Ergänzende Architektur und Betriebsgrenzen |
| `frontend/README.md` | Geplanter Oberflächenschritt |
| `tests/test_jobs.py` | Bestehende Backend-Tests |
| `.env.example` | Namen der Umgebungsvariablen; wird nicht automatisch geladen |
| `.gitignore` | Unter anderem lokale Daten, virtuelle Umgebung und `.env` |
| `_config.yml` | Bestehende GitHub-Pages-/Jekyll-Konfiguration |

## Lokale Einrichtung

Für den sicheren Prototyp sind Linux/macOS (POSIX) und Python 3.11 oder neuer vorgesehen; verwendet wird ausschließlich die Standardbibliothek. Windows wird bis zur Umsetzung sicherer ACLs und Prozessbaum-Verwaltung abgewiesen. Die Tests bestanden unter Linux/Python 3.12; die tatsächlichen Zielgeräte müssen noch geprüft werden.

1. Repository klonen und `main` auschecken:

   ```bash
   git clone https://github.com/CeeLeeT/Terminal.git
   cd Terminal
   git switch main
   ```

2. In einer lokalen Bash-Sitzung einen zufälligen Token setzen und starten:

   ```bash
   export TERMINAL_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
   python3 -m backend.server
   ```

Der Server bindet fest an `http://127.0.0.1:8765`. Beide Werte sind derzeit nicht über Umgebungsvariablen einstellbar. Der Token muss mindestens 24 ASCII-Zeichen enthalten; das ersetzt nicht die Anforderung an einen zufälligen Token. Token nicht veröffentlichen oder ins Repository schreiben.

| Variable | Bedeutung / Standard |
|---|---|
| `TERMINAL_API_TOKEN` | Pflicht; gemeinsamer Bearer-Token für alle Endpunkte |
| `TERMINAL_DATA_DIR` | Datenordner, standardmäßig `data`; Datenbank `terminal.sqlite3` |
| `TERMINAL_WORKDIR` | Arbeitsverzeichnis der Kindprozesse, standardmäßig `.` |
| `TERMINAL_AGENT_ARGV` | Optionales JSON-Array des CLI-Aufrufs; ohne Konfiguration nur `diagnostics` |

Datenordner werden mit 0700 und Datenbanken mit 0600 geschützt; vorhandene Rechte werden korrigiert. Fremde Eigentümer und Symlinks sowie Datenbank-Hardlinks werden abgewiesen. SQLite-Journale übernehmen die Datenbankrechte.

Relative Datenpfade beziehen sich auf das Startverzeichnis. Für dauerhaften Betrieb einen festen Datenpfad und ein vorhandenes, bewusst gewähltes Arbeitsverzeichnis verwenden. `.env.example` dient als Vorlage; Kopieren nach `.env` allein setzt keine Variablen.

### Lokale Prüfung

```bash
python3 -m unittest discover -s tests -v
curl -H "Authorization: Bearer $TERMINAL_API_TOKEN" http://127.0.0.1:8765/templates
curl -H "Authorization: Bearer $TERMINAL_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"template":"diagnostics","prompt":""}' \
  http://127.0.0.1:8765/jobs
```

`diagnostics` startet einen echten Prozess und gibt Python-Version und Betriebssystem aus. Es prüft keine Agentenverbindung. Die Tests ersetzen keinen Funktionstest der tatsächlichen CLI auf dem Zielgerät.

## HTTP-API

Alle Endpunkte verlangen `Authorization: Bearer <Token>`. JSON-Antworten und SSE werden mit `Cache-Control: no-store` ausgeliefert.

| Methode / Pfad | Verhalten |
|---|---|
| `GET /templates` | JSON-Array: `diagnostics`, zusätzlich `agent` bei konfiguriertem Adapter |
| `POST /jobs` | JSON-Objekt mit `template` und optionalem `prompt` (Standard: leere Zeichenfolge); bestätigt Speicherung mit HTTP 202 |
| `GET /jobs` | Letzte 100 Aufträge, neueste zuerst; keine Pagination |
| `GET /jobs/{id}` | Auftrag mit `id`, `template`, `prompt`, `status`, `exit_code`, `created` |
| `GET /jobs/{id}/events` | Gespeicherte Ereignisse, danach Live-Ausgabe bis der Auftrag beendet ist |

Die Empfangsbestätigung enthält `id`, `status: queued` und `message: Auftrag erhalten.`. Sie bestätigt keine erfolgreiche Ausführung; der aktuelle Status muss separat abgefragt werden. `exit_code` kann bei noch laufenden oder nicht gestarteten Prozessen `null` sein. `created` ist ein SQLite-Zeitstempel in UTC ohne explizites Zeitzonensuffix.

### Ereignisse und Wiederaufnahme

SSE-Ereignisse besitzen `id`, `event` und JSON-`data` mit dem Feld `text`. Ereignistypen sind `ack`, `status`, `output` und `error`. Ausgabe wird in Blöcken geliefert, nicht zwingend zeilenweise. Kommentar-Heartbeats sind keine gespeicherten Ereignisse.

Ein nicht negativer `Last-Event-ID`-Header liefert nur Ereignisse mit größerer ID. IDs sind datenbankweit fortlaufend; Clients müssen die zuletzt empfangene ID je Auftrag speichern. Nach Verbindungsabbruch kann derselbe Auftrag weitergelesen werden, ohne ihn erneut einzureichen.

Browser-Clients brauchen Streaming-Fetch oder einen anderen Client mit Unterstützung für den Authorization-Header. Der native `EventSource`-Konstruktor bietet dafür keine Option. CORS und die Auslieferung einer Oberfläche sind derzeit nicht implementiert; die spätere Oberfläche benötigt ein ausdrücklich festgelegtes Origin-/Proxy-Konzept.

### Validierung und Grenzen

| Grenze / Antwort | Bedeutung |
|---|---|
| HTTP 400 | Ungültiger JSON-Auftrag, Vorlage, Prompt, Body-Größe oder `Last-Event-ID` |
| HTTP 401 | Fehlender oder falscher Token |
| HTTP 404 | Unbekannter Pfad oder Auftrag |
| HTTP 429 | Bereits zwei aktive Aufträge |
| Request-Body | Maximal 65.536 Byte; gültiger `Content-Length` erforderlich |
| Prompt | Maximal 16.000 Zeichen; für `agent` nicht leer oder nur Leerraum |
| Laufzeit | Standardmäßig 120 Sekunden je Auftrag |
| HTTP-Verbindungen | Maximal 16 aktive Verbindungen; weitere werden vor Threadstart geschlossen, Backlog 16 |
| Header / Body | Absolute Frist von zehn Sekunden |
| SSE | Absolute Frist von 150 Sekunden; danach mit `Last-Event-ID` wieder verbinden |
| Ausgabe | Maximal 1 MiB gelesene Prozessausgabe je Auftrag; Überschreitung beendet den Prozess und führt zu `failed` |

Laufzeit, Parallelität und Ausgabelimit sind derzeit keine Umgebungsvariablen. Es gibt noch keine Idempotenzschlüssel, Abbruch-API oder strukturierte Agentenergebnisse. Ein erneut gesendetes `POST /jobs` erzeugt einen neuen Auftrag.

## Sicherheitsgrenzen

Der Prototyp ist für lokale Erprobung vorgesehen. Loopback-Bindung und Bearer-Token begrenzen den API-Zugang, sind aber keine Sandbox für die gestarteten Prozesse.

- Agenten laufen mit den Rechten des Serverkontos und erben dessen Umgebung mit Ausnahme von `TERMINAL_API_TOKEN`. Werkzeuge, Dateien, Netzwerkzugriffe und Geheimnisse müssen separat begrenzt werden. Nicht als root betreiben.
- Die wörtliche Prompt-Übergabe verhindert Shell-Interpolation im Adapter. Sie verhindert nicht, dass ein Agent selbst Befehle ausführt oder Dateien verändert.
- Ein gemeinsamer Token erlaubt Zugriff auf sämtliche Aufträge und Prompts. Benutzertrennung, Rollen, Token-Rotation im laufenden Server und Audit-Protokoll fehlen.
- SQLite enthält Prompts und Ausgaben unverschlüsselt. Automatische Löschung, Gesamtgrößenlimit und Backup-/Restore-Verfahren fehlen. Keine Zugangsdaten in Prompts schreiben.
- Timeout und geordnetes Serverende bereinigen registrierte Prozessgruppen. SIGKILL, Stromausfall und absichtlich aus der Prozessgruppe ausbrechende Prozesse brauchen zusätzliche Prozessverwaltung. Ein Neustart allein erkennt keine verwaisten Prozesse.
- HTTP-Verbindungen und Fristen sind begrenzt; HTTPS, Browser-Sicherheitskonzept und umfassende Schutzmaßnahmen für Fernzugriff bleiben offen. Den Port nicht unmittelbar im Internet veröffentlichen.

Vor Dienst- oder Fernbetrieb sind ein eingeschränktes Dienstkonto, kontrollierter Zugang, Supervisor für harte Abbrüche und ausbrechende Prozesse, Backup und Aufbewahrungsregeln umzusetzen und zu prüfen.

## Geplante GeeKStation-Agenten-Anbindung

GeeKStation, Office und Habibis sollen denselben Auftragsvertrag nutzen: Auftrag einreichen, ID speichern, Status und Ereignisse anzeigen und später den Verlauf wieder öffnen. Anzeigen müssen aus tatsächlichen Backend-Ereignissen entstehen. `completed` bedeutet zunächst nur Prozessende mit Exit-Code 0; eine fachlich korrekte Agentenleistung ist damit nicht bewiesen.

Der vorhandene Integrationspunkt ist `TERMINAL_AGENT_ARGV`: ein nicht leeres JSON-Array aus nicht leeren Zeichenfolgen. Genau ein vollständiges Argument muss `{prompt}` sein. Dieses Argument wird wörtlich ersetzt; andere Platzhalter oder zusammengesetzte Prompt-Argumente werden nicht unterstützt.

Die konkrete CLI, ihr absoluter Pfad, nicht interaktive Optionen, Provider-/Modellkonfiguration und Werkzeugberechtigungen sind noch nicht für dieses Backend bestätigt. Deshalb enthält diese README keinen vermeintlich fertigen Agentenaufruf. Zunächst ist ein ungefährlicher Probeauftrag auf dem Zielgerät vollständig zu prüfen: Annahme, Ausgabe, Exit-Code, Timeout und Wiederaufnahme des Verlaufs.

R2D2-Zugriff, Agentenauswahl, Sprachsteuerung und interaktive Terminals sind weitere Vorhaben, keine bereits vorhandenen Funktionen. Der derzeitige Adapter konfiguriert einen CLI-Aufruf pro Serverinstanz, keinen Agentenkatalog.

## Vor der Umsetzung zu verifizieren

| Offener Punkt | Erforderlicher Nachweis / Entscheidung |
|---|---|
| Backend-Basis | Zusammengeführten main-Stand verwenden; bei künftigen Änderungen Dokumentation und Tests abgleichen |
| Zielsystem | Host, Betriebssystem, Architektur, Python-Version und Verfügbarkeit von Port 8765 |
| CLI-Agent | Installierter Pfad und Version, gültige nicht interaktive Argumente, wörtliche Prompt-Übergabe und Exit-Code-Verhalten |
| Modell / Provider | Tatsächlich verfügbare Konfiguration, Zugang und Verhalten innerhalb des 120-Sekunden-Limits |
| Berechtigungen | Dienstkonto, erlaubte Werkzeuge, Dateipfade, Netzwerke und benötigte Umgebungsvariablen |
| Speicher | Dauerhafter Datenpfad, Dateirechte, Speicherbedarf, Aufbewahrung und erfolgreich getestetes Restore |
| Frontend-Vertrag | Vorhandene GeeKStation-/Office-/Habibis-Dateien, Origin, Authentifizierung und Zuordnung der Job-IDs |
| Stream-Verhalten | Ausgabe ohne störende Pufferung, Wiederaufnahme und Darstellung von Fehlern/Unterbrechungen |
| Prozessverwaltung | Automatisierte Tests für Timeout, SIGTERM und Kindprozess-Bereinigung bestanden; Verhalten auf dem tatsächlichen Zielsystem und bei harten Abbrüchen prüfen |
| Fernzugriff | Ob benötigt; erst danach HTTPS-/Proxy-Konzept und Zugangsregeln festlegen |
| R2D2 | Ob benötigt; konkrete Freigaben, Protokoll und eingeschränkter Zugang prüfen |
| Pages / Dokumentation | Zweck der verbliebenen Jekyll-Konfiguration und Dokumentationsveröffentlichung klären |

## Nächster konkreter Ausbauschritt

Zuerst Backend-Basis und tatsächlichen CLI-Vertrag bestätigen und die Architektur-Dokumentation damit abgleichen. Danach einen vollständigen, harmlosen Agentenauftrag über die vorhandene API ausführen. Auf dieser geprüften Schnittstelle kann eine minimale Weboberfläche für Auftragseingabe, Status, Live-Ausgabe und Verlauf entstehen.

Diese README ersetzt die allgemeine GitHub-Pages-Vorlage und führt Backend, Sicherheitskorrekturen und geplante Integration in einer Projektdokumentation zusammen.

## Sicherheitskorrekturen

Die vier Befunde der ersten Prüfung wurden korrigiert: Dateirechte, geordnetes Beenden von Prozessgruppen, HTTP-Ressourcengrenzen und Ignore-Regeln für lokale Umgebungsdateien/Datenbanken. Zusätzlich erhalten Kindprozesse den API-Token nicht mehr. Alle 15 Funktionstests und Sicherheits-/Regressionstests bestanden. Der [Prüfbericht](docs/security-review-2026-10-11.md) beschreibt den ursprünglichen Stand und den aktuellen Korrekturstatus.
