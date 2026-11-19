# ThreadDesk 0.2.0 – Release-Notizen

> Big-Plan-Paket `BP-TD-REL-01`, Nutzerfreigabe vom 09.11.2026. Veröffentlicht als
> GitHub-Release `v0.2.0` mit einem Paket für **macOS Intel (x86_64, Tauri)**.
> Prüfsummen und den Quell-Commit des Pakets nennt der Release-Text auf GitHub.
> Ältere Ausgaben bleiben unverändert: [0.1.1rc1](https://github.com/landjunge/ThreadDesk/releases/tag/v0.1.1rc1)
> (Pre-release) und der nie veröffentlichte Entwurf 0.1.1rc2.

## Deutsch

ThreadDesk 0.2 fasst die seit 0.1.1rc1 auf `main` übernommenen Funktionen zu
einer Desktop-Ausgabe zusammen. Oberfläche, CLI und MCP verwenden dieselben
Fachhandler mit Revisions-, Konflikt- und Wiederholungsschutz.

### Neu seit 0.1.1rc1

- **Papierkorb** – Threads und Graphbeziehungen kommen mit stabilen IDs zurück.
  Endgültiges Löschen (`trash.purge`) braucht eine Vorschau und eine
  ausdrückliche Bestätigung; der alte direkte Löschweg ist gesperrt (PR #95).
- **Aktivitätsgraph** – gespeicherte Graphansichten mit Zentrum, Knotenliste und
  Filtern. Echte Dateiänderungen und bewusst geöffnete Dateien werden getrennt
  erfasst (PR #93, #94, #95).
- **Bibliothek** – vollständige Dateien aus Ordner, Auswahl oder ZIP mit
  Prüfsummen übernehmen, lokal indexieren, suchen und im Graphen verwalten
  (PR #86, #87, #88, #92).
- **Backup v3** – portable Sicherung als Streaming-ZIP64 mit
  Integritätsmanifest, Bibliotheksdateien und ausstehenden Übertragungen.
  Backups v1 und v2 bleiben lesbar (PR #90, #95).
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

### Paket und Installation

- **Nur macOS Intel (x86_64).** Tauri-2-Fenster mit eingebettetem lokalem
  ThreadDesk-Server (PyInstaller); eine eigene Python-Installation ist nicht
  nötig. Mindestversion macOS 11.
- Download: `ThreadDesk-0.2.0-macOS-Intel.dmg` (oder dieselbe App als `.zip`).
  DMG öffnen und `ThreadDesk.app` nach Programme ziehen.
- **Unsigniert im Sinne von Apple:** ad-hoc signiert, nicht mit Developer-ID
  signiert und nicht notarisiert. Gatekeeper kann beim ersten Start eine
  Bestätigung verlangen (Finder: Kontextmenü → Öffnen).
- Für Apple Silicon und Windows gibt es in 0.2.0 kein Paket. Windows ist
  pausiert; für diese Plattformen bleibt 0.1.1rc1 der letzte Download.

### Grenzen

- Der erste Start auf deinem Mac und die Qualität deines lokalen LLM lassen
  sich durch den Build nicht beweisen. Geprüft wurde der eingebettete Server mit
  `--self-test` auf dem Build-Mac; das Fenster wurde beim Build nicht geöffnet.
- Backups enthalten private Inhalte. Verlinkte Dateien außerhalb des
  Arbeitsbereichs sind nicht enthalten.
- Daten bleiben in `~/.threaddesk` (oder `THREADDESK_HOME`). Die Installation
  verschiebt, migriert oder löscht diesen Ordner nicht. Vor dem Ersetzen einer
  vorhandenen App den Arbeitsbereich sichern.
- Keine automatischen Updates.

## English

ThreadDesk 0.2 bundles the features merged into `main` since 0.1.1rc1 into one
desktop edition. UI, CLI and MCP share the same handlers with revision, conflict
and replay protection.

### New since 0.1.1rc1

- **Trash** restores threads and graph relationships with stable IDs; permanent
  purge (`trash.purge`) needs a preview and explicit confirmation, the old direct
  delete path is blocked (PR #95).
- **Activity graph** with saved views, centres, node lists and filters; real file
  changes and deliberate opens are recorded separately (PR #93, #94, #95).
- **Library** import of complete files with checksums, local index, search and
  graph file management (PR #86, #87, #88, #92).
- **Backup v3**: portable streaming ZIP64 backup with integrity manifest, library
  files and pending transfers; v1 and v2 remain readable (PR #90, #95).
- **Dynamic MCP catalog** derived from the command registry, with schema, scopes
  and operation receipts, plus the whiteboard lifecycle (PR #97).
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

### Package and installation

- **macOS Intel (x86_64) only.** Tauri 2 window with an embedded local ThreadDesk
  server (PyInstaller); no separate Python installation needed. Requires macOS 11.
- Download `ThreadDesk-0.2.0-macOS-Intel.dmg` (or the same app as `.zip`), open
  it and drag `ThreadDesk.app` to Applications.
- **Not Apple-signed:** ad-hoc signed only, no Developer ID, not notarized.
  Gatekeeper may ask for confirmation on first launch (Finder: context menu → Open).
- There is no Apple Silicon or Windows package for 0.2.0. Windows is paused;
  0.1.1rc1 remains the latest download for those platforms.

### Limits

First launch on your Mac and local LLM quality cannot be proven by the build. The
embedded server passed `--self-test` on the build Mac; the window was not opened
during the build. Backups contain private content; linked files outside the
workspace are not included. Data stays in `~/.threaddesk` (or `THREADDESK_HOME`)
and is neither moved, migrated nor deleted; back it up before replacing an
existing app. No auto-update.

## Build und Prüfung / Build and verification

1. Versionsquellen sind gleich: `pyproject.toml`, `src/threaddesk/__init__.py`,
   `packaging/tauri/package.json`, `packaging/tauri/src-tauri/Cargo.toml`,
   `packaging/tauri/src-tauri/tauri.conf.json` – überall `0.2.0`.
2. Build auf einem Intel-Mac aus einem sauberen Checkout des Release-Commits
   nach `packaging/tauri/README.md`: PyInstaller-Server
   (`packaging/tauri/backend/ThreadDeskServer.spec`), `--self-test`,
   `npm ci`, `npm run build` (`tauri build --bundles app`), ad-hoc-Signatur und
   `codesign --verify`.
3. DMG mit `hdiutil create` (UDZO), ZIP mit `ditto`; SHA-256 beider Dateien in
   `SHA256SUMS.txt` und im Release-Text.
4. Nach dem Hochladen wird jedes Asset frisch heruntergeladen und sein Hash mit
   dem lokalen Wert verglichen.
5. Der Workflow `Desktop installers` (PyInstaller/pywebview, alle Plattformen)
   veröffentlicht weiterhin nicht (`if: false`); dieses Release ist der manuelle
   Tauri-Weg wie zuvor bei 0.1.1rc2.
