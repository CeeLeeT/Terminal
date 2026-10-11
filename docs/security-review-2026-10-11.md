# Sicherheitsprüfung: Terminal

Stand: 11. Oktober 2026. Prüfung des öffentlichen Repositorys CeeLeeT/Terminal.

## Umfang und Methode

Geprüft wurden alle Dateien von `main` (9b1c212), `feat/terminal-job-api` (5d056a5) und `docs/terminal-readme` (0c436f3), außerdem alle über diese Git-Referenzen erreichbaren früheren Dateiversionen einschließlich gelöschter Dateien. Insgesamt: 12 unterschiedliche Dateipfade, 15 unterschiedliche Datei-Blobs. Das lokal erzeugte Dokumentations-Commit enthält denselben Dateiinhalt wie der veröffentlichte Dokumentations-Branch.

Vollständige Dateiabdeckung: README.md, _config.yml, .env.example, .gitignore, backend/__init__.py, backend/jobs.py, backend/server.py, docs/architecture.md, frontend/README.md, tests/test_jobs.py sowie historisch Index und .github/workflows/blank.yml.

Manuelle Quellprüfung, ergänzende Musterprüfung aller Datei-Blobs auf private Schlüssel, bekannte Tokenformate, Zugangsdaten in URLs, Passwort-/Tokenzuweisungen, E-Mail-Adressen, persönliche Benutzerpfade und private IPv4-Adressen. Commit-Autoren wurden auf persönliche E-Mail-Adressen geprüft. Musterfunde wurden einzeln eingeordnet. Kein spezialisierter Secret-Scanner war installiert; die Referenzdateien des angebotenen Security-Scan-Workflows waren nicht abrufbar. Diese Prüfung ist daher eine eigenständige Quellprüfung, kein abgeschlossener Scan des Security-Plugins.

Nicht geprüft: unerreichbare/umgeschriebene Git-Objekte, Forks, externe Systeme, GitHub-Actions-/Repository-Secrets, Deployments und echte Agenteninstallationen. Issues, Kommentare und externe Artefakte gehören nicht zur Dateiprüfung. Für beliebige, unkenntlich kodierte Geheimnisse besteht keine vollständige Erkennungsgarantie.

## Geheimnisse und persönliche Einträge

**Keine echten Passwörter, API-Schlüssel, privaten Schlüssel oder privaten Kontaktdaten in den geprüften Dateien gefunden.**

- .env.example enthält leere Konfigurationswerte.
- README-Beispiele erzeugen einen zufälligen Token zur Laufzeit; sie enthalten keinen gespeicherten Zugangsschlüssel.
- tests/test_jobs.py enthält einen erkennbaren, ausschließlich im lokalen Testserver verwendeten Test-Token. Kein Produktiv-Geheimnis.
- backend/server.py liest den Token aus der Umgebung.
- In der veröffentlichten Commit-Historie stehen die öffentliche GitHub-Kennung und die GitHub-noreply-Adresse des Repository-Inhabers. Keine private Kontaktadresse gefunden.
- Die Dateien enthalten öffentliche Projekt-/Kontonamen und öffentliche Repository-Links. Diese sind keine vertraulichen persönlichen Einträge.

Mangels bestätigter Geheimnisse ist derzeit keine Schlüsselrotation oder Umschreibung der Git-Historie aufgrund dieser Prüfung erforderlich.

## Sicherheitsbefunde

### S1 – Mittel: Verläufe können für andere lokale Benutzer lesbar sein

Quelle: backend/jobs.py, Jobs.__init__ und connect. Das Datenverzeichnis und die SQLite-Datei erhalten keine ausdrücklich eingeschränkten Rechte.

Validierung auf Linux mit umask 022: neues Datenverzeichnis 0755, Datenbank 0644. Sofern alle übergeordneten Verzeichnisse zugänglich sind, können andere lokale Benutzer die gespeicherten Prompts und Ausgaben lesen. Der API-Token schützt nicht den direkten Dateizugriff.

Vor Dienstbetrieb: Datenverzeichnis 0700 und Datenbank 0600 unter einem eingeschränkten Dienstkonto sicherstellen; vorhandene Daten und Plattformbesonderheiten berücksichtigen. Backup-Rechte müssen dieselbe Vertraulichkeit gewährleisten.

### S2 – Mittel: Kindprozesse überleben das Serverende

Quelle: backend/jobs.py, run (start_new_session und Thread-Timer); backend/server.py, main (server_close ohne Jobbereinigung).

Validierung: Ein harmloser Schlafprozess wurde durch die Jobverwaltung gestartet. Nach SIGTERM des verwaltenden Python-Prozesses lief der Kindprozess weiter. Der Probeprozess wurde anschließend ausdrücklich beendet. Beim nächsten Start wird der Auftrag nur als interrupted markiert; der alte Prozess wird nicht gefunden oder beendet.

Folge: Ein tatsächlich angeschlossener Agent kann nach dem Serverende weiter Dateien ändern oder Netzwerkaktionen ausführen. Das Neustartverhalten bietet keine Ausführungsgarantie.

Vor Dienstbetrieb: aktive Prozesse erfassen, geordnetes Stoppen mit Prozessgruppen-Bereinigung implementieren und zusätzlich den Supervisor für vollständige Prozessbereinigung konfigurieren. Zielsystem separat testen; Windows beendet derzeit beim Timeout nur den direkten Prozess.

### S3 – Mittel, vor Fernzugriff relevant: HTTP-Verbindungen sind nicht begrenzt

Quelle: backend/server.py, ThreadingHTTPServer und Handler.setup. Pro Verbindung kann ein Thread entstehen; das Limit von zwei Jobs begrenzt nicht HTTP-Verbindungen oder SSE-Leser. Der 30-Sekunden-Socket-Timeout ist keine Gesamtgrenze für eine langsam laufende Verbindung.

Ein lokaler Prozess kann Ressourcen beanspruchen; bei späterer Proxy-Freigabe wird die Angriffsfläche größer. Dieser Befund wurde aus dem Quellcode abgeleitet; kein Last-/DoS-Test durchgeführt.

Vor Fernzugriff: Verbindungs-, Thread-, Request- und Stream-Grenzen sowie Gesamtzeitlimits im Server beziehungsweise kontrollierten Proxy festlegen und testen.

### S4 – Niedrig: alternative Datenordner sind nicht durch .gitignore geschützt

Quelle: .gitignore und TERMINAL_DATA_DIR. Ignoriert wird nur data/. Ein anders benannter Datenordner innerhalb des Repositorys kann einschließlich SQLite-Verläufen versehentlich committed werden. .env.*-Dateien außer der exakt benannten .env sind ebenfalls nicht pauschal geschützt.

Vor lokaler Nutzung: Daten vorzugsweise außerhalb des Checkouts ablegen. Ignore-Regeln für SQLite-Dateien und lokale Umgebungskonfiguration ergänzen, dabei .env.example ausdrücklich erhalten. Gitignore allein ersetzt keine Secret-Prüfung vor einem Commit.

## Weitere bestätigte Betriebsgrenzen

- Prozesse erben Serverrechte und Umgebungsvariablen, einschließlich des API-Tokens. Keine Sandbox und keine gefilterte Kindprozess-Umgebung. Bei einem späteren Agentenadapter sollten nur benötigte Variablen weitergegeben werden.
- Ein gemeinsamer API-Token erlaubt Lesen aller Aufträge; keine Benutzertrennung.
- SQLite-Verläufe sind unverschlüsselt und haben keine automatische Löschfrist oder Gesamtgrößengrenze.
- Kein HTTPS oder vollständig implementierter Browser-/Proxy-Zugang; der Server bindet derzeit ausschließlich an 127.0.0.1.
- Positiv geprüft: parametrische SQL-Abfragen für Nutzereingaben, Prozessstart ohne Shell-Interpolation, Tokenvergleich mit hmac.compare_digest, Body-/Prompt-/Ausgabelimits und Timeout. Diese Kontrollen ersetzen keine Agenten-Werkzeugrechte.
- Der gelöschte Beispielworkflow referenziert eine alte Checkout-Action. Er ist auf den aktuellen Branches nicht aktiv; bei Wiederverwendung modernisieren und Workflow-Berechtigungen begrenzen.

## Validierung und offener Arbeitsstand

Alle sechs vorhandenen Backend-Tests bestanden auf dem geprüften Quellstand. Dateirechte und überlebender Kindprozess wurden zusätzlich gezielt reproduziert. Die Prüfung verändert keine Laufzeitfunktionen.

| Aufgabe | Stand |
|---|---|
| Alle erreichbaren Datei-Blobs und historische Löschungen prüfen | Erledigt |
| Musterfunde auf echte Geheimnisse prüfen | Erledigt; keine bestätigt |
| Backend-Quellprüfung und vorhandene Tests | Erledigt; sechs Tests bestanden |
| Dateirechte und Prozessbereinigung | Probleme bestätigt; Behebung offen |
| HTTP-Ressourcengrenzen und Ignore-Regeln | Quellbefunde dokumentiert; Behebung offen |
| Echte Zielgeräte, Agenteninstallation und Deployment prüfen | Offen; in dieser Repository-Prüfung nicht enthalten |

Der Prototyp ist damit nicht als sicher für öffentlich zugänglichen Dauerbetrieb freigegeben. Nächste Priorität: S1 und S2 vor dem Anschluss eines schreibenden Agenten beheben.
