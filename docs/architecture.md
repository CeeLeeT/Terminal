# Architektur

Eine Serverinstanz besitzt den SQLite-Speicher und maximal zwei laufende Jobs.
Status: queued → running → completed / failed / timed_out.
Bei Neustart werden aktive Aufträge als interrupted markiert und nicht wiederholt.

POST /jobs bestätigt nach Speicherung mit HTTP 202 und Auftrags-ID.
GET /jobs liefert die letzten 100 Aufträge; GET /jobs/ID liefert Metadaten.
GET /jobs/ID/events streamt gespeicherte ack-, status-, output- und error-Ereignisse.
Last-Event-ID erlaubt Wiederaufnahme. Ausgabe und Exit-Code sind das Ergebnis.

Der CLI-Adapter startet einen konfigurierten Prozess mit separaten Argumenten,
ohne Shell. diagnostics ist ein echter Diagnoseprozess, ausdrücklich kein Agent.
Agenten laufen mit den Rechten des Serverkontos; ihre Werkzeuge und Zugriffsrechte
müssen in der tatsächlichen Agentenkonfiguration festgelegt werden.

Grenzen: kein PTY, kein stdin, kein Jobabbruch, keine parallelen Serverinstanzen,
keine Mehrbenutzerverwaltung. Der Server bindet ausschließlich an localhost.
120 Sekunden Timeout, maximal 1 MiB Ausgabe je Auftrag. Unter POSIX wird die
Prozessgruppe beendet, unter Windows nur der direkte Prozess.
Unverschlüsselte Verläufe ohne automatische Aufbewahrungsgrenze.
Dienstbetrieb braucht Supervisor, Backup und kontrollierten HTTPS-Zugang.

Office und Habibis sollen dieselbe API verwenden. Vor Integration ist deren
tatsächlicher CLI-Aufruf zu prüfen. Die vorhandenen Projektdateien waren hier
nicht verfügbar; es ist noch keine Verbindung zu diesen Systemen implementiert.
Jekyll-Konfiguration bleibt für vorhandene GitHub-Pages-Dokumentation erhalten.
