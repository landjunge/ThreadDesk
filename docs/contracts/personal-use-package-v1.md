# Installationspakete · personal-use-package-v1

**Status: verbindlich für die fünf Produkt-Repositories.** Die Lizenzdatei
im Git-Stamm ist [Netzwerkpunkt Personal Use License 1.0](personal-use-license-1.0.txt).
Jedes veröffentlichte Installationspaket nimmt **dieselbe Datei** mit, bytegleich.

## Repositories

4AllPass, TollGate, ThreadDesk, KiraBridge, Agent Authority
(`agent-authority-lab`). GitHub Actions läuft
`scripts/check_personal_use_license.py` (identische Kopie, `TOOL_VERSION`)
bei Pull Requests und auf dem Default-Branch.

Die Prüfung verlangt:

1. `LICENSE` beginnt mit dem Lizenznamen, enthält DE/EN, nennt in der Historie
   kein fremdes Produkt.
2. `README.md` und vorhandenes `README.de.md` nennen den Lizenznamen und
   verlinken `LICENSE`.
3. `pyproject.toml` zeigt auf `LICENSE` oder
   `LicenseRef-Netzwerkpunkt-Personal-Use-1.0`, nicht MIT/Proprietary.
4. Produkt-`package.json` nutzt `SEE LICENSE IN …` auf dieselbe Datei.
5. Vorhandene Tauri-/Cargo-Konfiguration bindet `LICENSE` ein.
6. Vorhandene Packrezepte (Desktop-Workflow, `build_release.py`, native
   macOS-Builder, Docker) erwähnen `LICENSE` und kopieren sie ins Artefakt.

Gebaute Installer (DMG, AppImage, NSIS, tar.gz, Wheel, `.app`) müssen die
Stamm-`LICENSE` enthalten. Produkt-spezifische Nachweise (z. B. 4AllPass
`scripts/check-release-license.py`, KiraBridge `scripts/release_smoke.py`)
bleiben zusätzlich gültig.

## GitHub

Workflow: `.github/workflows/personal-use-license.yml`. Kein neues öffentliches
Repository. Vorlage und Familienkopf bleiben in ThreadDesk.
