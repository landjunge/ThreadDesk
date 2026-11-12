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
