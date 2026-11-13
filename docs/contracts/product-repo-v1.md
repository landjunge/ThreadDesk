# Produkt-Repository · product-repo-v1

**Status: verbindlich für neue Repos der Produktfamilie.** Gemeinsame Quelle
ist ThreadDesk, wie beim [README-Kopf](readme-header-v1.md). Ein neues Tool
erfindet Layout und Lizenz nicht neu.

## Was jedes neue Produkt-Repo bekommt

1. **README-Kopf** nach `readme-header-v1` (Katalog ergänzen, Icons, `apply`).
2. **LICENSE** nach [Netzwerkpunkt Personal Use License 1.0](personal-use-license-1.0.txt).
3. **Lizenzabschnitt** im README (Deutsch und Englisch, wenn es beide Dateien gibt)
   nach [personal-use-readme-block-v1.md](personal-use-readme-block-v1.md).

## Anlegen

Neues GitHub-Repo zuerst **privat** (`gh repo create NAME --private`). Öffentlich
nur mit ausdrücklichem Nutzerauftrag und Eintrag in `~/.grok/github-allowlist.txt`.

```bash
# im ThreadDesk-Klon mit aktuellem Vertrag
python3 scripts/readme_header.py init --product KEY --repo /pfad/zum/neuen-repo
python3 scripts/readme_header.py check --product KEY --repo /pfad/zum/neuen-repo
```

`KEY` steht im Katalog `readme-header-v1.json`. Neues Tool: zuerst Katalog und
Icons ergänzen, danach `init` in **allen** bestehenden Repos `apply` ausführen.

Optionale historische Rechte (MIT, PolyForm, ältere Veröffentlichungen):

```bash
python3 scripts/readme_header.py init --product KEY --repo PFAD \
  --history-de "Frühere MIT-Rechte an historischen NAMEN-Fassungen bleiben bestehen." \
  --history-en "Previously granted MIT rights for historical NAME versions remain intact."
```

Ohne diese Angaben setzt `init` einen produktneutralen Satz: bereits eingeräumte
Rechte an historischen Fassungen dieses Produkts bleiben unberührt. Die LICENSE
darf keine fremden Produktnamen in der Historie führen.

## Prüfung

`check` verlangt denselben Lizenznamen in `LICENSE` und README sowie einen Link
auf `LICENSE`. Der Kopf bleibt unverändert `readme-header-v1`.
