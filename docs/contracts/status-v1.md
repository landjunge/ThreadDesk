# Ist-Stand-Register · status-v1

**Paket BP-TRUTH-01** (Big Plan, Modul X1). Jedes Produkt der Familie führt im
Repo-Root eine maschinenlesbare `STATUS.json`. Boards, READMEs und die Koordination
lesen daraus, statt Prosa abzuschreiben. Gemeinsame Quelle ist ThreadDesk, wie bei
[readme-header-v1](readme-header-v1.md).

- Schema: [`status-v1.schema.json`](status-v1.schema.json)
- Prüfskript: [`scripts/status_check.py`](../../scripts/status_check.py) (nur Standardbibliothek, nur lesend)
- Beispiel: die `STATUS.json` dieses Repos

## Regeln

1. **Unbekanntes heißt `"unknown"`.** Nie schätzen, nie „vermutlich“. Fehlt ein Beleg,
   steht `unknown` (Commit, Version, ganze Abschnitte wie `server`).
2. **Nur gelesene Werte.** Jeder Wert stammt aus `gh`, `git`, einer Info.plist, einem
   Launcher oder dem Server-Inventar (KiraBridge `ops/netcup.json`) zum Zeitpunkt
   `observed_at`. Das Register ändert keine Installation und keinen Dienst.
3. **Keine Geheimnisse und keine internen Adressen.** Öffentliche Repos (ThreadDesk,
   4AllPass, TollGate) nennen Dienste, Zustand, Quelle und Art der Erreichbarkeit,
   aber keine Hostnamen, IPs, Schlüssel oder Pfade mit Benutzernamen (`~` statt Home).
4. **Der Pin darf zurückliegen.** `main_pin` ist der beim Beobachten gelesene Stand des
   Standardbranches. Die Datei selbst erzeugt einen neuen Commit, also liegt der Branch
   danach mindestens einen Commit vor dem Pin. Verlangt wird nur, dass der Pin ein
   Vorfahr ist.
5. **Ein PR pro Aktualisierung.** Wer Release, Installation oder Serverstand ändert,
   aktualisiert die Datei im selben Zug und führt das Prüfskript aus.

## Felder

| Feld | Inhalt |
|---|---|
| `product`, `repo` | Anzeigename; GitHub-Name, Sichtbarkeit, Standardbranch (`master` bei Agent Authority). |
| `observed_at`, `plan` | Zeitpunkt der Beobachtung (UTC); Planstand, auf den sich `open_packages` beziehen. |
| `main_pin` | Commit (40 Zeichen) und Commit-Zeit des Standardbranches bei der Beobachtung. |
| `source_version` | Version im Quellstand am Pin (`pyproject.toml`, `tauri.conf.json`). |
| `releases` | Laut `gh release list` / `gh release view`: Tag, Entwurf, Vorabversion, Veröffentlichung, vollständige Assetnamen. Bei mehreren Kanälen je Kanal die letzte. Ohne Releases `[]`. |
| `installed.mac` | `installed` mit `entries` (App-Bundle oder Launcher, Version, Quellcommit) oder `not-installed` mit den geprüften Pfaden. Windows und Linux sind `unknown`, solange nicht lesend belegt. |
| `server` | Quelle und Zeitpunkt (Inventar), dazu je Komponente Zustand, Version, Quellcommit, Art der Erreichbarkeit. Ohne Beleg `unknown`. |
| `open_packages` | Plan-Pakete mit ID, Titel und Status `open`, `in-progress`, `blocked`, `done`, `unknown`. `open` heißt: laut Plan offen, kein Abschlussbeleg im Register. |
| `notes` | Kurze Hinweise auf bekannte Abweichungen (z. B. W04, W10, W18). |

## Prüfskript

```
python scripts/status_check.py --status STATUS.json
python scripts/status_check.py --status ../KiraBridge/STATUS.json --ops-inventory ../KiraBridge/ops/netcup.json
python scripts/status_check.py --offline          # nur Schema und lokale Pfade
```

Prüft gegen GitHub: Sichtbarkeit, Standardbranch, Pin (Vorfahr, Commit-Zeit,
Abstand), jedes Release (Entwurf, Vorabversion, Zeit, Assetnamen) und ob ein neueres
Release im Register fehlt. Lokal: Version und Quellcommit der App-Bundles, Launcher
(`runtime_marker`), und dass ein als `not-installed` geführtes Produkt wirklich nicht
auftaucht. Mit `--ops-inventory`: Zustand der Dienste gegen das Server-Inventar.

Ausgabe je Befund `ERROR` (Abweichung), `WARN` (Pin mehr als `--max-behind` Commits
zurück, Register älter als `--max-age-days`, Inventar neuer als Register) oder `INFO`.
Exit-Code `1` bei mindestens einem `ERROR` (mit `--strict` auch bei `WARN`), `2` bei
unlesbarer Datei.
