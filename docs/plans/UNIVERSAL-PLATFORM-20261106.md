# Universelle KI-Projektplattform – erstes nutzbares Paket

Stand: 6. November 2026. **BP-PROJECT-MEMORY-20261106-M1**.
Quelle: direkter Masterauftrag vom 6. November 2026. ThreadDesk-Zuordnung
`188ce4729a62`, Übernahme `9d3c05270b24`, eigener Bericht `d5e9f661c6e2`,
unabhängiger Codex-Prüfer `0c2bfd2e81c0`. Basis `main@067a525` im eigenen Worktree
`threaddesk-worktrees/project-memory-20261106`, Branch `feat/project-memory-20261106`.

Folgepaket: [M2 – Idee, bearbeitbarer Erstplan und atomarer Projektstart](PROJECT-START-20261106.md)
auf eigenem Folgebranch; die folgenden M1-Nachweise bleiben historisch erhalten.

## Nutzbarer Einstieg

**Projekte → Projektgedächtnis** (`/projects`) bündelt pro ausdrücklich zugeordnetem
Thread gespeicherten Wiedereinstieg, nächsten Schritt, Entscheidungen, Aufgaben,
Fragen und letzte Whiteboardbeiträge. Quellen und Berichte bleiben ungeprüfte
Angaben; gespeicherte Zustände beweisen weder Ausführung noch Abnahme.

UI, CLI, HTTP und MCP verwenden denselben lesenden Befehl `project.memory` und die
vorhandenen Speicher-/Wissensverträge. Es entsteht keine zweite Aufgabenqueue
oder Agentensteuerung. Die Wissensprojektion ist wiederverwendet; neue Handoffs
behalten ihre bisherigen Standardlimits. Bestehende ausgestellte Handoffs bleiben erhalten.

Zum Ausprobieren **Start Projektgedaechtnis Demo.command** im ausgecheckten
Repository öffnen. Der Launcher nutzt die vorhandene Hauptrepo-Pythonumgebung,
alternativ `THREADDESK_PYTHON` bzw. `python3` mit den bisherigen UI-Abhängigkeiten.
Ein neuer temporärer Workspace und ein zufälliger freier Loopbackport halten die
Demo getrennt von laufenden Anwendungen. Beispiele: Berlin-Buch, Buschradio und
Ocean, jeweils **synthetische Daten**, keine laufende Projektarbeit. Terminal-Ctrl-C
beendet nur diesen Kandidaten; der ausgegebene Beispielpfad bleibt erhalten.

```sh
PYTHONPATH=src python scripts/demo_project_memory.py --serve --open
```

Ohne `--serve` erstellt das Skript den Beispielstand und liest einen echten
Projektsnapshot. Ein mit `--workspace` angegebenes bestehendes Verzeichnis wird
abgelehnt. Natürlichsprachlicher Projektstart und dynamische Teamausführung sind
noch folgende Pakete. Bestehende Schreibverträge können schon Projektknoten und
Threads anlegen/zuordnen sowie Wissen und Wiedereinstieg speichern.

## Gemeinsamer Aufruf und Grenzen

```json
{
  "version": 1,
  "workspace_id": "EXAKTE_KENNUNG_AUS_COMMAND_CATALOG",
  "command": "project.memory",
  "arguments": {"project_id": "EXAKTE_PROJEKTKNOTEN_ID", "limit": 3}
}
```

CLI: `td command --request-file request.json`; HTTP: autorisiertes
`POST /api/commands`; MCP: `td_project__memory` mit `workspace_id`/`arguments`,
alternativ `command_query`. Die Workspacekennung stammt vom Katalog des wirklich
ausgewählten lokalen Datenbestands. Unterstützte Backends: JSON und SQLite.

Format `threaddesk.project-memory.v1`: bis 18.000 kanonische UTF-8-Bytes je Seite,
angefordert bis 10 Threads (Standard 3), pro Thread bis 8 Wissenseinträge/
5.000 Projektionsbytes und 3 Whiteboardbeiträge; Textauszüge bis 300 Zeichen.
`total_threads`, `next_offset`, `truncated` und Wissenszählungen unterscheiden
Bestand und Auszug. Extreme Zustandszählungen ergeben gegebenenfalls
`page_too_large`, keine still als vollständig ausgegebene Leerseite.

Eine gemeinsame Speichertransaktion liest Projekt, Mitgliedsthreads, Wissen und
Boards. Eine eigene bereits aktive Transaktion wird wiederverwendet. JSON-Locks/
Recovery und SQLite-Transaktionen sind vorhandene technische Nebenwirkungen;
der Befehl ändert keine fachlichen Daten, Receipts, Agenten oder den aktiven Thread.
Der vollständige lokale Snapshot bindet auch ausgelassene Inhalte/Seiten.
Folgeseiten brauchen `expected_snapshot`; Änderungen führen zu `snapshot_conflict`.
Der Hash ist Konsistenzbindung, keine Signatur oder externe Quellenprüfung.

Mitgliedschaft gilt nur über `organization.project_id`. Eltern, Relationen und
gleichnamige Projekte erweitern sie nicht. Wissen gehört über `metadata.thread_id`
zu den Mitgliedsthreads; für andere direkte Projektknoten bleibt `graph.query`
zuständig. Zugriff bleibt `workspace.read`, noch keine Benutzer-/Mandanten-ACL.

## Bestandsprüfung

| Baustein | Beobachtet / vorhandener Quellstand | Grenze |
|---|---|---|
| ThreadDesk | `main@067a525`: gemeinsame Befehlsregistry, Projekte, Wissen, Reentry, lokale Administration/Whiteboards. Lokales Berichtssystem aus `6eeb465` tatsächlich benutzt. | Neues Projektgedächtnis ist dieser Quellkandidat und die separate Demo, kein installiertes Desktoprelease. |
| KiraBridge | Frischer Livehealth: `0.8.0rc39@8d331314b608`, Intel-Mac, PID `40336`; bestehende ThreadDesk-Tools benutzt. | Health ist keine pauschale Abnahme jeder Computeraktion oder aktueller Rechte. Neuer Command im Livepeer noch nicht vorhanden. |
| Aufgabenkoordinator | Eigener Dienst PID `4499`, `complete / no_authorized_ready_card`; Laufzeitpin `4bdf851`. | In dieser Runde nur Status gelesen, keine alten Karten oder historischen UNKNOWN-Versuche gestartet. Frühere Abnahme separat dokumentiert. |
| CLI-Routing | Matrix `c9a396be4081` Revision 5; Planhook frisch: Codex/Sol/high, bestehender ChatGPT-Zugang. | Native Teamprüfung erbt die Sitzung; CLI-Plantest ist kein ausgeführter Modellwechsel. |
| 4AllPass | Pin `e97885ca948170bdd6ce1695897fab03e5f8a615`: Backend, PWA/Client, lokaler Broker und Accesspaket vorhanden. | Laut `docs/security-boundary.md` liefert v1-Allow Rohwertkopien; TTL widerruft keine Kopien. Mediated Proxy/kryptografische Agentenidentität nicht als produktiv integrierte Funktion ausweisen. Keine Secrets gelesen. |
| TollGate | Pin `aead5d00a75acd32641b766bb6f215a1fe3c8dc1`: Budget-/Protect-/Loop-/Scopes-/Freeze-Code und MCP-Adapter. | Kein neuer Produktionstest oder belegter durchgängiger Plattformbudgetschutz. |
| Agent Authority | Beobachterworktree `8891ee3546da81a4417c9d7bba19c44e1015dd55`: Bindung von Bridge-/Originaltask-IDs, read-only. Vorheriger Prüfbericht: 83 Tests und statische Checks. | Bericht gelesen, Tests des anderen Pakets nicht wiederholt; keine produktive Aktivierung. |
| Ocean | Eigenständige externe Plattform. Vorhandene statische APK-Forschung: `Desktop/Forschungskoordination-Dirk-2026-11-04/projekte/06-Ocean.md`, SHA256 `db5fd8bbc8e5c1460ee17192bc52bae7ed1529a830936ad93c388be8cacf2641`. | Erkannte REST/WSS-/WebDAV-Clientwege sind kein nachgewiesener offizieller Bot-/MCP-/Serviceaccount-Vertrag. Keine Anmeldung/Live-API-Abfrage. |

Frische lokale `--version`-Abfragen, alle Exit 0: Codex `0.166.0`, Grok `1.0.77`
Build `50ca579fa996` (jetzt Kanal stable), Claude Code `2.1.236`, OpenCode `1.4.4`,
Gemini CLI `0.37.2`, Copilot CLI `1.0.67`, Cursor Agent `2026.08.11-e8db854`.
Aider nicht auf PATH gefunden. Eine Versionsausgabe belegt für die fünf weiteren
installierten Anbieter keinen Modellzugang oder erfolgreichen Agentenauftrag.
Kein Update und keine Änderung fremder Sitzungen.

## Nachweise und nächster Schritt

Prüfungen: `tests/test_project_memory.py` (beide Backends, zwei Projekte, Neustart,
Archiv/Trash, Snapshotkonflikte, Größenbudget, Metadaten, Scope, echte CLI/MCP-stdio,
HTTP, UI-Fehler-/Leerzustände); bestehende Wissens-/Handoff-/Katalogprüfungen;
`tests/test_project_memory_browser.py` (Chromium, Projektauswahl, Tastatur und
Seitennavigation, Deutsch/1280 und Englisch/390 mit hell/dunkel Browserpräferenz;
das vorhandene Produktthema bleibt dunkel). Browseraufnahmen unter
`test-results/project-memory/`, finale Ergebnisse im zugeordneten ThreadDesk-Board.
Dies ist keine native Paket-/Windowsabnahme. Python-3.9-Syntax wird geprüft,
Frameworklaufzeit hier auf Python 3.12.13; Optional-Handler erhalten 3.9-kompatible Typen.

Nächste sinnvolle Pakete:

1. Quellpin regulär integrieren. Nach gelesenen Workflows startet Featurepush keine
   CI; PR/Main-Push würde unter anderem Cloud-/macOS-ARM-Builds starten. Die dafür
   nötige Kosten-/Kapazitätsfreigabe bleibt offen. Keine Workflowänderung/Umgehung.
2. Nach geplanter Integration neue Commandroute über den tatsächlichen KiraBridge-
   Peer end-to-end lesen. Vorhandene Gegenstelle erweitern, keinen Dispatcher duplizieren.
3. Natürlichen Projektstart auf bestehenden Schreibverträgen aufsetzen: Idee,
   veränderbarer Plan, Aufgaben und Fragen; anschließend passende vorhandene
   Workerprofile/Claims anbinden. Plan, Freigabe, Ausführung und Abnahme unterscheiden.
4. Bestehende Server-/Remotezweige integrieren und Handy → Server → Rechner →
   Agent → ThreadDesk einschließlich Offline-/Konfliktfällen tatsächlich prüfen.
5. Gemeinsame Projekte, Benutzerrollen und kontrollierte Wiederverwendung ergänzen.
   Ocean braucht einen belegten offiziellen Integrationsweg. Windows für Dirk bleibt
   beim bestehenden parallelen Auftrag; fremde Sitzung/VM werden nicht übernommen.

Öffentliche Webseite/Downloads erst nach Integration und echter Auslieferung
aktualisieren. Aktuell keine neue Desktopinstallation, Veröffentlichung oder
Mehrbenutzerverfügbarkeit behaupten.
