# ThreadDesk 0.2.0 (Tauri, Intel macOS)

This desktop build bundles the existing local-first ThreadDesk Python HTTP server with an independent Tauri WebKit window. It does **not** require a Python installation on target machines.

The window opens the existing workspace at `~/.threaddesk` or the explicitly selected profile. There is no auto-update endpoint. The local application works offline; optional room/server sync remains explicitly configured. Local builds are ad-hoc signed.

To build on an x86_64 macOS host:

1. Use the existing ThreadDesk build environment including PyInstaller and Pillow. Run `python scripts/build_icons.py --tauri` from the repository root; this generates the native icons from the existing approved family PNG and updates the actual Tauri icon paths.
2. From repository root, run `python -m PyInstaller --clean --noconfirm --distpath packaging/tauri/backend/dist --workpath packaging/tauri/backend/build packaging/tauri/backend/ThreadDeskServer.spec`.
3. Run `packaging/tauri/backend/dist/ThreadDeskServer --self-test`.
4. From `packaging/tauri`, run `npm ci` and `npm run build`.
5. Check `src-tauri/target/release/bundle/macos/ThreadDesk.app`, sign locally with `codesign --force --deep --sign -` if needed and package a DMG (`hdiutil create -format UDZO`) and a zip (`ditto -c -k --keepParent`) for GitHub release uploads; record SHA-256 for both.

No Apple Developer ID signing or notarization is provided. Gatekeeper may require manual user approval. Verify the bundle, bundled backend, and local GUI with a clean test workspace before distributing. The 0.2.0 GitHub release is published this way: ad-hoc signed, not notarized. See `docs/RELEASE-NOTES-0.2.0.md`.

## Startup diagnostics and readiness

The Tauri host starts the bundled `bin/ThreadDeskServer`, keeps its **stderr**,
and accepts only the first `THREADDESK_URL` line from **its own child**. The URL
must be `http://127.0.0.1:<port>`; the existing port, workspace-lock and
data-ownership checks remain in the Python backend.

- Backend stderr is written to the app's own log directory
  (`app_log_dir()/startup.log`): directory `0700`, file `0600` (also fixed if an
  older permissive file exists), symlinks refused, **capped at 256 KiB**. The
  drain continues past the cap, so a full log can never block the backend
  through a full pipe. Only a **structured allowlist** is stored: fixed startup
  codes (workspace locked, saved address corrupt/invalid, port in use,
  traceback, stopped-before-ready, startup timeout) plus counts of unclassified
  lines. Raw stderr text, request bodies and profile content are **never**
  written. If the private log cannot be opened safely, startup fails with a
  clear alert instead of writing to an unprotected path.
- Cleanup happens **before** the alert: on timeout, early exit, protocol error
  or a window/capability failure the host stops and reaps only its own spawned
  process group first, then writes the reason and shows the modal message.
- Readiness is bounded to **30 s**. On timeout, or when the backend exits before
  announcing its URL, the host stops **only its own spawned process group**
  (one-file bundles fork a child), reaps it, writes the reason plus the log path
  to the log, and shows a native alert with that log path. There is no automatic
  retry.
- Startup failures therefore stay diagnosable instead of silently ending the
  app. The first unknown startup failure of the 2026-11-13 candidate is still
  unexplained; this change removes the blind spot, it does not claim a root
  cause.

Deutsch: Der Tauri-Host startet `bin/ThreadDeskServer`, behält dessen **stderr**
und akzeptiert die erste `THREADDESK_URL`-Zeile nur vom **eigenen Kind**. Die URL
muss `http://127.0.0.1:<port>` sein; Port-, Workspace-Lock- und
Datenbesitzprüfung bleiben im Python-Backend. Backend-stderr landet im eigenen
App-Logverzeichnis (`app_log_dir()/startup.log`): Verzeichnis `0700`, Datei
`0600` (auch eine ältere permissivere Datei wird korrigiert), Symlinks werden
abgelehnt, **maximal 256 KiB**. Auch nach der Kappung wird weitergelesen, damit
ein voller Log das Backend nie über eine volle Pipe blockiert. Gespeichert wird
nur eine **strukturierte Allowlist**: feste Startup-Codes (Workspace gesperrt,
gespeicherte Adresse beschädigt/ungültig, Port belegt, Traceback,
vorzeitig beendet, Startup-Timeout) plus Zähler nicht klassifizierter Zeilen.
Roher stderr-Text, Request-Bodies und Profilinhalte werden **nie** geschrieben.
Lässt sich der private Log nicht sicher öffnen, bricht der Start mit klarem
Hinweis ab, statt in einen ungeschützten Pfad zu schreiben. Das Aufräumen
passiert **vor** dem Hinweis: Bei Timeout, frühem Exit, Protokollfehler oder
Fenster-/Capability-Fehler beendet und reapet der Host zuerst nur seine eigene
Prozessgruppe, dann werden Grund geschrieben und der modale Hinweis gezeigt. Die
Bereitschaft ist auf **30 s** begrenzt: Bei Timeout oder vorzeitigem Backend-Exit
beendet der Host **nur seine eigene Prozessgruppe** (Ein-Datei-Bundles forken ein
Kind), reapet sie, schreibt Grund und Logpfad ins Log und zeigt einen nativen
Hinweis mit Logpfad. Kein automatischer Retry. Der unbekannte erste
Startabbruch des Kandidaten vom 13.11.2026 bleibt unerklärt; diese Änderung
beseitigt den blinden Fleck, nicht die Ursache.

## Visible version and source identity

The shared header displays the package version and the first seven characters of the source commit. Both PyInstaller specifications run `scripts/write_build_info.py` before collecting resources. It records the current commit, whether the checkout contains local changes, and the UTC build identifier in an ignored package resource. The running app reads that resource without executing Git or accessing a user workspace.

Commit the intended source before building a distributable package. A clean checkout produces a label such as `v0.1.2 · abcdef0`; an uncommitted checkout adds `+lokal`. A source launch without valid packaged metadata says `Quellstand` rather than claiming a commit. Keep the Python package version, Tauri configuration, npm package and Cargo package aligned when changing versions.

Before replacing an installation, preserve the previous app and workspace, run the packaged self-test, and check the app with a separate HOME containing a workspace copy. Verify the actual header and the thread/graph/whiteboard counts, then compare source hashes and embedded build metadata. Install only the tested bundle. Publishing that exact source commit afterwards keeps the installed label traceable to GitHub.

## Workspace response ordering

Independent editor forms may finish in a different order from their requests. The UI suppresses superseded workspace responses so that an older note-save response cannot replace a later snapshot restore or thread selection. Requests still finish normally and write failures remain visible. The browser regression delays a real note-save reply until after the restore swap and verifies the restored note again after a server restart.


## Family window adapter / Familienfensteradapter

The native `family_switch` command accepts only one of the five catalog IDs. It is
allowed only in the owned `main` webview at the exact backend origin established
by the native ready handshake. Navigation to other origins is rejected. No shell
plugin, generic process command or broad loopback capability is exposed.

The native host invokes `~/.local/bin/kirabridge --principal local family switch
TARGET --source-pid PID` directly; PID is the Tauri host's own PID. The existing
broker binds the registered installation, process/start identity and UID again at
the effect boundary. Exit zero alone is insufficient: top-level JSON must contain
`success:true`, matching `active_product`, finite `actual_outer_bounds` with
positive width/height, and `visible_family_windows:1`. Invalid replies or unknown
execution outcomes never trigger an automatic retry. Only the broker transfers
outer bounds and hides/shows registered family windows. The host does not issue
Close/Quit or reload the webview when switching. 4AllPass lock policy is unchanged.

The shared 1.2.2 native host waits 31 seconds in the UI, covering the Rust bridge's
30-second receipt deadline plus one second of dispatch/delivery overhead. A valid
receipt from that same attempt after two seconds still resolves the pending UI.
Only a later explicit click starts another switch. UNKNOWN and expiry keep the
target blocked; there is no automatic retry or time-based recovery.

Closing `main` hides it; macOS Reopen shows/focuses the same window. Explicit Quit
still destroys the app and ends its own backend. Browser-only use remains separate
and reports unavailable native targets. Two installed ThreadDesk copies are not
interchangeable: the broker's default target is `~/Applications/ThreadDesk.app`;
`/Applications/ThreadDesk.app` must not be silently substituted or terminated.

Deutsch: Der Browser übergibt ausschließlich eine feste Produkt-ID. Pfad, argv und
PID entstehen im nativen Host; der Broker prüft den tatsächlichen Aufrufer und die
Fensterwirkung. Fehler bleiben Fehler, UNKNOWN wird nicht blind wiederholt.
Schließen blendet das eigene Fenster aus, Reopen erhält UI/Backend. Installation,
Fünfer-Laufzeitabnahme und Freigabe der Pakete erfolgen separat beim Koordinator.

For a local test bundle, commit the intended source, perform steps 1–3, then use
`tauri build --debug --bundles app` from `packaging/tauri` with the existing pinned
CLI 2.11.4. Record Git pin, embedded `_build_info.json`, executable/icon SHA-256
and architecture. This produces an isolated build artifact; do not copy it over
an installed app or launch against the production workspace. A debug bundle is
not a release artifact. The static documentation has no separate compiler: check
`python scripts/readme_header.py check --product threaddesk --repo .` and the
changed relative links; no website deployment is needed for this change.
