# Big-Plan-Quellenintegration / Big Plan source integration

6. November 2026. Nutzerauftrag: GitHub mit den vorhandenen Big-Plan-Arbeitsständen
abgleichen und sinnvoll integrieren. Der eigene Branch
`integrate/current-bigplan-20261106` bewahrt die vollständigen Quelllinien:

| Quelle | Erhaltener Commit | Inhalt |
| --- | --- | --- |
| Aktuelles Main | `067a525798817629ae1d2b8e741d109230f54d08` | Ausgangsbasis |
| Projektpläne | `cd5c994b90acd6453ca1158e23c9887efdd19ec5` | Projektgedächtnis, Entwurf, Planrevisionen |
| Projekt-/Remoteintegration | `a0dd4c39478b031e0e31d335c2a15435dfbc52eb` | Enthält die Planlinie und den opt-in HTTP-Handoffadapter |
| Instanzberichte | `6eeb4654e749766a97d00f8c99707fa10415f42a` | Additive Kurzberichte und atomare zentrale Übersicht |

Die beiden Funktionslinien wurden konfliktfrei per Merge verbunden. Die
Projekt-/Remote-Vertragsgrenzen aus
[M4](PROJECT-REMOTE-INTEGRATION-20261106.md) und die
[Berichtsgrenzen](../agents/SHORT-REPORTS.md) bleiben bestehen. Es entsteht keine
weitere Aufgabenqueue. Vorhandene laufende Installationen und der ungesicherte
Diff des alten Stammworktrees werden durch diese Integration nicht verändert.

## Prüfungen und CI

Die Integration wird mit explizitem `PYTHONPATH` auf ihren eigenen `src`-Pfad
geprüft. Der lokale Prüflauf verwendet Python 3.12.13 aus der vorhandenen
ThreadDesk-Testumgebung; Importpfade werden vor dem Lauf erfasst. Der Umfang
umfasst die betroffenen Projekt-/Plan-/UI-/Browserfälle, den HTTP-Handoffadapter,
Kurzberichte und benachbarte Knowledge-, Thread-, Command- und MCP-Verträge.
Konkrete Ergebnisse und der geprüfte Commit werden im ThreadDesk-Whiteboard
`188ce4729a62` und im PR festgehalten. Frühere Teilprüfungen werden nicht addiert.

Der gezielte Lauf auf dem Produktmerge `cbe44c0` führte 300 Fälle aus: 294
bestanden, sechs Browserfälle scheiterten vor Browserstart am fehlenden
Playwright-Standardbinary `chromium_headless_shell-1243`; keine Skips. Der
unveränderte rote Lauf bleibt eigener Beleg. Nur diese sechs Fälle wurden mit
dem vorhandenen Chromium 1248 (Chrome for Testing 156.0.8078.4) über den
unterstützten `THREADDESK_CHROMIUM`-Pfad erneut geprüft: sechs bestanden in
28,64 Sekunden. Es wird kein neuer fehlerfreier 300er-Lauf daraus behauptet.
Die Releaseinputprüfung bestätigte alle 680 damaligen committed Dateien.

Der vorhandene Linux-Workflow `Tests` bleibt unverändert, einschließlich seiner
beiden vollständigen Abnahmeläufe und der Null-Skip-Prüfung. Native Desktoppakete
werden im bestehenden `Desktop installers`-Workflow ausschließlich manuell
ausgelöst. Seine Build- und Paketprüfungen bleiben erhalten. Damit startet eine
Quell-PR keinen automatischen Intel-/ARM-Mac-Build; die aktuell zurückgestellte
ARM-Abnahme wird nicht still ausgeführt. Das ist kein Nachweis eines neuen
Desktoppakets. Veröffentlichung bleibt im vorhandenen Workflow deaktiviert.

Quelle, PR-/Mainintegration, Desktopbuild, Installation und produktiver
Remotezugang benötigen jeweils ihre tatsächlichen Belege. Der bestehende
Desktopstand wird hier weder als aktualisiert noch als freigegeben behauptet.
Die KiraBridge-Integration und deren beauftragte Macinstallation werden getrennt
durch die koordinierende Sitzung bearbeitet.

## English

This merge preserves current main, all three project-plan commits, the opt-in
remote handoff adapter and the additive per-instance reporting branch. The
existing Linux acceptance workflow is unchanged. Native package builds retain
their existing checks and are explicitly dispatched; PRs no longer automatically
fan out to Intel and deferred ARM builds. Source integration does not attest a
new desktop package, installation, public download or production remote service.
