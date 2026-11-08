# ThreadDesk 0.2.0 – Release-Notizen (Entwurf)

> **Status: vorbereitet, nicht veröffentlicht.** Diese Datei ist ein Entwurf für
> eine spätere Veröffentlichung (Big-Plan-Paket `BP-TD-REL-01`). Es gibt dazu noch
> kein GitHub-Release und keinen Tag `v0.2.0`. Die zuletzt veröffentlichte Ausgabe
> bleibt [0.1.1rc1](https://github.com/landjunge/threaddesk/releases/tag/v0.1.1rc1).
> Der Release-Entwurf 0.1.1rc2 ist nicht veröffentlicht.

## Deutsch

ThreadDesk 0.2 fasst die seit 0.1.1rc1 auf `main` übernommenen Funktionen zu
einer Desktop-Ausgabe zusammen. Oberfläche, CLI und MCP verwenden dieselben
Fachhandler mit Revisions-, Konflikt- und Wiederholungsschutz.

### Neu seit 0.1.1rc1

- **Papierkorb** – Threads und Graphbeziehungen kommen mit stabilen IDs zurück.
  Endgültiges Löschen braucht eine Vorschau und eine ausdrückliche Freigabe
  (PR #95).
- **Aktivitätsgraph** – gespeicherte Graphansichten mit Zentrum, Knotenliste und
  Filtern. Echte Dateiänderungen und bewusst geöffnete Dateien werden getrennt
  erfasst (PR #93, #94, #95).
- **Bibliothek** – vollständige Dateien aus Ordner, Auswahl oder ZIP mit
  Prüfsummen übernehmen, lokal indexieren, suchen und im Graphen verwalten
  (PR #86, #87, #88, #92).
- **Backup v3** – Streaming/ZIP64, Integritätsmanifest, Bibliotheksdateien und
  ausstehende Übertragungen. Backups v1 und v2 bleiben lesbar (PR #90, #95).
- **Dynamischer MCP-Katalog** – MCP-Werkzeuge entstehen direkt aus der
  Befehlsliste, mit Schema, Scopes und Operationsbeleg. Whiteboards haben einen
  vollständigen Lebenszyklus (PR #97).
- **Verwaltung, Handoffs und Wissen** – revisionsgebundene Thread-Verwaltung,
  ausgestellte Handoffs mit Laufbindung, Rückfragen, Wissen und Wiedereinstieg
  (PR #75, #76, #77).
- **Projektgedächtnis** – Projektpläne mit Revisionsverlauf und ein optionaler
  HTTP-Adapter für Projekt-Handoffs (PR #99).
- **Server & Sync** – Verbindung zu `threaddesk-server` mit Offline-Kopien und
  sichtbaren Konflikten (PR #89). Der Server ist ein eigenes Projekt und nicht
  Teil des Desktop-Pakets.

### Übergabeweg

Handoffs werden in ThreadDesk ausgestellt. KiraBridge liest sie über MCP und
prüft vor jedem Aufruf die eigene Freigabe. ThreadDesk sendet nichts selbst und
startet keine Agenten. Der ältere lokale Gnom-Hub-V1-Weg bleibt verfügbar.

### Grenzen

- Nur macOS (Intel und Apple Silicon). Windows ist pausiert.
- macOS-Pakete sind ad-hoc signiert, nicht mit Developer-ID signiert und nicht
  notarisiert.
- Der erste Start auf deinem Mac und die Qualität deines lokalen LLM lassen
  sich durch CI nicht beweisen.
- Backups enthalten private Inhalte. Verlinkte Dateien außerhalb des
  Arbeitsbereichs sind nicht enthalten.
- Daten bleiben in `~/.threaddesk` (oder `THREADDESK_HOME`). Die Installation
  verschiebt oder löscht diesen Ordner nicht.

## English

ThreadDesk 0.2 bundles the features merged into `main` since 0.1.1rc1 into one
desktop edition. UI, CLI and MCP share the same handlers with revision, conflict
and replay protection.

### New since 0.1.1rc1

- **Trash** restores threads and graph relationships with stable IDs; permanent
  purge needs a preview and explicit approval (PR #95).
- **Activity graph** with saved views, centres, node lists and filters; real file
  changes and deliberate opens are recorded separately (PR #93, #94, #95).
- **Library** import of complete files with checksums, local index, search and
  graph file management (PR #86, #87, #88, #92).
- **Backup v3** with streaming/ZIP64, integrity manifest, library files and
  pending transfers; v1 and v2 remain readable (PR #90, #95).
- **Dynamic MCP catalog** derived from the command registry, plus the whiteboard
  lifecycle (PR #97).
- **Administration, handoffs and knowledge**: revision-bound administration,
  issued handoffs with run binding, questions, knowledge and re-entry
  (PR #75, #76, #77).
- **Project memory**: project plans with revision history and an opt-in HTTP
  adapter for project handoffs (PR #99).
- **Server & sync** with `threaddesk-server`, offline copies and visible
  conflicts (PR #89). The server is a separate project.

### Handoff route

Handoffs are issued in ThreadDesk. KiraBridge reads them over MCP and applies its
own authorization before each call. ThreadDesk does not send anything or start
agents. The older local Gnom-Hub-V1 route remains available.

### Limits

macOS only (Intel and Apple Silicon); Windows is paused. Packages are ad-hoc
signed, not Developer-ID signed or notarized. First launch on your Mac and local
LLM quality cannot be proven by CI. Backups contain private content. Data stays in
`~/.threaddesk` (or `THREADDESK_HOME`) and is neither moved nor deleted.

## Vor der Veröffentlichung / Before publishing

1. Versionsquellen gleich halten: `pyproject.toml`, `src/threaddesk/__init__.py`,
   `packaging/tauri/package.json`, `packaging/tauri/src-tauri/Cargo.toml`,
   `packaging/tauri/src-tauri/tauri.conf.json` (heute überall `0.2.0`).
2. Entscheiden, welcher Pakettyp veröffentlicht wird: Der Workflow
   `Desktop installers` baut PyInstaller-Pakete. Die lokal installierte 0.2.0
   ist eine Tauri-App, für die es keinen CI-Workflow gibt.
3. Der Veröffentlichungsjob im Workflow ist abgeschaltet (`if: false`), weil
   `scripts/verify_release.py` alle drei nativen Pakete einschließlich Windows
   verlangt. Für ein reines macOS-Release müssen Prüfung und Job angepasst werden.
4. Doppelte vollständige Testsuite, beide macOS-Builds mit Selbsttest,
   Prüfsummen und Herkunftsbelege am selben Quell-Commit.
5. Erst danach Tag `v0.2.0` und Release anlegen. Die README-Download-Knöpfe
   folgen automatisch dem veröffentlichten Release.
