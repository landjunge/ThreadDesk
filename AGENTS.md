# Arbeitsregeln

## Rahmen: Fünf-Produkte-Big-Plan (ab 08.11.2026)

- ThreadDesk-Arbeit erfolgt im Rahmen des gemeinsamen Big Plans für die fünf Produkte KiraBridge, ThreadDesk, 4AllPass, TollGate und Agent Authority. Pakete für ThreadDesk tragen dort IDs wie `BP-TD-*`, `BP-PLAN-01` oder `TD-P*`.
- Kanonische Planung ausschließlich in den bestehenden ThreadDesk-Haupt- und Produktboards lesen. GitHub enthält technische Umsetzung und Prüfnachweise; keine Big-Plan-Kopien oder Spiegel anlegen.
- `PLAN.md` und `docs/TEAMPLAN.md` sind historisch. Pläne unter `docs/plans/` sind Teilpläne. Bei Widerspruch gilt der Big Plan.
- Die Regeln unten bleiben gültig. Insbesondere werden KiraBridge-Pakete nicht in diesem Repo umgesetzt, sondern im KiraBridge-Repo geführt; KiraBridge ist für ThreadDesk die Gegenstelle und der Übergabeweg.


## Kira: Pflichtreferenz vor Planerstellung
Nach jedem Brainstorming und VOR jedem Plan für andere KIs die lebende Referenz /Users/landjunge/.threaddesk/Workflow/Workflow-Planerstellung-fuer-andere-KIs.md lesen und anwenden. Noch nicht abgeschlossen: neue Erfahrungen ergänzen, nicht jedes Mal neu erfinden. Fehlt Zugriff, offen melden; nicht behaupten gelesen zu haben.

## Agentenmeldungen (Nutzerauftrag 13.11.2026)

Meldungen ereignisbezogen auf fachliche Meilensteine, Blockaden, Entscheidungen und Ergebnisse begrenzen. Keine eigenen Berichtsboards je Sitzung und keine minütlichen Whiteboard-Pings oder wiederholten Rückmeldefrist-Nachfragen. Technische Frische getrennt vom fachlichen Fortschritt im aktuellen Zustand halten; fehlende Meldungen bedeuten unbekannt, keinen belegten Stillstand.

Arbeitsstand kompakt im bestehenden Produktboard, abgenommenes Ergebnis mit Quellen-/Testbeleg, Details referenzieren statt dieselben Texte mehrfach anzuhängen. Stabile Operationskennung und beobachtete Revision verwenden, unabhängig zurücklesen; unklaren Ausgang zuerst anhand derselben Kennung abgleichen. Bestehende Inhalte, historische Berichte und fremde Aufräumarbeiten bewahren. Die Workflow-Referenz gilt mit diesem neueren Nutzerbeschluss; deren alte 60-Sekunden-Pingpflicht ist ersetzt.


## Lokale Projektkopien und Arbeitsstände (2026-10-14)

- Vorhandene geeignete Arbeitsstände wiederverwenden. Vor neuen Kopien zuerst `git worktree list` und den jeweiligen Arbeitsstatus prüfen.
- Neue Worktrees nur bei begründetem Bedarf unter `/Users/landjunge/threaddesk-worktrees/<aufgabe>` anlegen; keine neuen Projekt-Geschwisterordner unter `/Users/landjunge` und keinen Sammelordner `Projekte`.
- Getrennte Entwicklungsstände nicht ungeprüft zusammenführen. Lokale Commits, gestagte/ungestagte Änderungen sowie einzigartige ignorierte und unversionierte Dateien vor einer Bereinigung sichern.
- Nach Abschluss entbehrliche temporäre Arbeitsstände sicher bereinigen: tatsächliche Nutzung und Pfadabhängigkeiten prüfen, normale Dateien zunächst in den macOS-Papierkorb verschieben, Git-Verknüpfungen mit der verfügbaren Git-Version fachgerecht behandeln und die Wiederherstellung dokumentieren. Keine erzwungenen Resets oder pauschalen Löschbefehle.
- Laufende Anwendungen, aktive KI-Aufträge und konfigurierte Runner-Pfade erhalten; nur konkret blockierte Einzelfälle zurückstellen. Bei notwendigen Verschiebungen Startpfade und lokale Installationsverweise reparieren und prüfen.
- Diese Regeln sind Projektanweisungen. Es wurde keine globale automatische Durchsetzung eingerichtet.


## Verbindliche Arbeitsweise ab 26. Oktober 2026

- Nutzerauftrag: Planung und Implementierung ausschließlich für ThreadDesk. KiraBridge ist vorhandene Gegenstelle; keine KiraBridge-Baupakete und keine Änderungen an dessen Codebasis. Externe Vertragsgrenzen konkret nachweisen und als Abhängigkeit ausweisen.
- Bei ThreadDesk-Arbeiten immer im Team arbeiten: echte getrennte Teilaufträge mit bestätigter Übernahme, Dateieigentum, Rückmeldungen und unabhängiger Prüfung. Keine nur behauptete Teamarbeit.
- Abgeschlossene Änderungen committen, pushen und nach bestandenem Review sowie den geltenden Pflichtprüfungen regulär nach main mergen. Keine Drafts als fertigen integrierten Stand ausgeben; keine Gates umgehen. Die Mergeautorisierung gilt für den angeforderten ThreadDesk-Umfang dauerhaft.
- Desktop und Git aktuell halten. Laufzeitänderungen aus dem final integrierten Quellpin bauen, prüfen und in der installierten Desktop-App belegen; Quell-/Paket-/Runtimeidentität und Datenerhalt dokumentieren. Eine Dokumentationsänderung erfordert keinen unveränderten Binärneubau: stattdessen nachweisen, dass der paketierte Laufzeitcode dem aktuellen Gitstand entspricht; den tatsächlichen älteren Buildpin offen nennen. Kein neues Paket aus Dokumentation behaupten.
- Vorläufiger Auftrag ist zunächst ein konkreter konsolidierter Plan aus den vorhandenen Brainstormings; geplante Funktionen nicht vorzeitig implementieren oder als fertig ausgeben. Für spätere Umsetzung immer die letzte ausdrückliche Aufgabenfreigabe beachten.
- Vollständige Bedienbarkeit durch ChatGPT über KiraBridge ist ein Abnahmeziel für alle ThreadDesk-Fachaktionen. Ein nur lesender Katalog genügt nicht. Tatsächliche verfügbare Transportwege und pro Funktion Erfolg, Konflikt, Wiederholung und Readback nachweisen.
- Verbesserte Graphansicht: echte Dateiänderungen und bewusst ausgelöste Dateizugriffe getrennt erfassen; Graphöffnung, technischer Cache/Index/Sync und bloße Statusänderungen sind keine Dateiaktivität. Quellen und offene Brainstormingentscheidungen erhalten.
- Papierkorb muss Threads und Graphbeziehungen mit stabilen IDs wiederherstellen; endgültige Löschung benötigt einen konkreten ausdrücklichen Löschauftrag. Originaldateien und geteilte Inhalte nicht pauschal kaskadieren.

## Bibliotheksauftrag mit sofortiger Integration

Der anschließende Nutzerauftrag autorisiert die schrittweise Umsetzung von Bibliotheksimport, verbindlicher lokaler Indexsuche, Dateimanager im vorhandenen Graphen, Formatadaptern und zugehöriger Dateiwiederherstellung. Der bisherige Plan wird erweitert, kein konkurrierender Plan angelegt. Jedes fertige Paket braucht sofort einen tatsächlichen KiraBridge-Aufruf mit Readback; keine spätere Sammelintegration und keine Erfolgsaussage allein aus Mock-/Unit-Tests. KiraBridge selbst bleibt unverändert. Fehlende Originalbytes, native Vertragsgrenzen und nicht geprüfte Principal-Kontexte ausdrücklich benennen. Indexsuche ist nun hohe Priorität und verbindlicher Umfang.

## README-Design der Produktfamilie (verbindlich ab 08.11.2026)

Jedes README eines Familien-Tools (KiraBridge, ThreadDesk, 4AllPass, TollGate, Agent Authority, BlockDesign und jedes neue Tool) bekommt den freigegebenen Kopf aus [docs/contracts/readme-header-v1.md](docs/contracts/readme-header-v1.md): großes zentrales Logo, Icon-Leiste zu allen anderen Tools, zweifarbige Wortmarke in Markenfarbe, Download-Buttons als Direktlinks auf die Installationsdatei. Neues Tool oder neue Icons: Katalog `docs/contracts/readme-header-v1.json` ergänzen und `scripts/readme_header.py` (`icons` → `apply` in allen Repos → `check`) verwenden, nicht neu gestalten.
