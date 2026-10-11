# Sicherheitskorrekturen – 11. Oktober 2026

Die vier Befunde aus der Repository-Prüfung wurden im Backend-Branch korrigiert.

| Befund | Änderung | Nachweis |
|---|---|---|
| S1: lokal lesbare Verläufe | Datenordner 0700, Datenbank 0600; vorhandene Rechte korrigieren, fremde Eigentümer und Symlinks sowie Datenbank-Hardlinks abweisen | Tests für neue und bestehende Daten, SQLite-Journal und Links |
| S2: weiterlaufende Prozesse nach Serverende | Prozessgruppen registrieren; SIGTERM/Strg+C beenden sie, warten auf Job-Threads und speichern interrupted | Tests für direkten Prozess und Kindprozess sowie echten Serverstart mit SIGTERM |
| S3: unbegrenzte HTTP-Ressourcen | Maximal 16 aktive Verbindungen, Backlog 16; Header/Body absolut zehn Sekunden, SSE 150 Sekunden; überzählige Verbindungen vor Threadstart schließen | Tests für Limit vor Anmeldung, Freigabe des Slots, langsame Header und Stream-Wiederaufnahme |
| S4: versehentlich eingecheckte Daten | .env.* ignorieren, .env.example erhalten; SQLite-/DB-Dateien einschließlich Journal/WAL/SHM unabhängig vom Ordner ignorieren | Test mit git check-ignore für eigene Datenordner und lokale Umgebungsdateien |

Zusätzlich wird TERMINAL_API_TOKEN nicht mehr an Kindprozesse vererbt. Verbindungstrennung und Fristüberschreitung schreiben keine Request-Details als Traceback ins Log.

## Unterstützte Plattform und verbleibende Grenzen

Der sichere Backend-Betrieb setzt aktuell POSIX (Linux/macOS) voraus. Unter Windows wird der Start abgewiesen, bis sichere ACLs und Prozessbaum-Verwaltung implementiert sind. Die automatischen Tests wurden unter Linux mit Python 3.12 ausgeführt; ein Test auf dem tatsächlichen Mac/Raspberry Pi steht noch aus.

SIGKILL, Stromausfall und absichtlich aus der Prozessgruppe ausbrechende Prozesse werden dadurch nicht beherrscht. Ein Supervisor mit Prozessgruppen-/Cgroup-Verwaltung bleibt für Dienstbetrieb erforderlich. Die Prozessverwaltung ist keine Sandbox.

Andere Umgebungsvariablen werden weiterhin vererbt. HTTPS, Benutzertrennung, Backups, Datenverschlüsselung und automatische Aufbewahrung sind separate, weiterhin offene Betriebsfunktionen. Gitignore schützt nicht bereits eingecheckte Dateien oder absichtliches git add -f.

## Validierung

15 automatisierte Tests bestanden: sechs vorhandene Funktionstests und neun zusätzliche Sicherheits-/Regressionstests. git diff --check bestanden. Keine Produktiv-Schlüssel oder Passwörter zur Implementierung benötigt oder gespeichert.
