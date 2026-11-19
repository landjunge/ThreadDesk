# Agentenstatus / Agent status

Stand 13.11.2026 · Quelländerung; laufende Adapter separat aktualisieren.

## Melden, wenn sich die Arbeit ändert

Fachliche Meilensteine, Blockaden, Entscheidungen und Ergebnisse kurz melden.
Keine minütliche Berichtspflicht, keine wiederholten Rückmeldefrist-Nachfragen und
keine neuen Berichtsboards je Sitzung. Das ersetzt die frühere Pflicht vom
05.11.2026. Arbeitsstand, Ergebnis und Details gehören an unterschiedliche Stellen:

- Aktueller Stand: eine zentrale Übersicht mit letzter Meldung je Instanz.
- Fachlicher Verlauf: kurze Änderungen und Ergebnisse im selben Whiteboard.
- Details: vollständige Meldung in den Metadaten des Beitrags; technische Belege
  im zugehörigen Repository referenzieren. Keine Transkripte oder Geheimnisse.

Planung bleibt in den bestehenden ThreadDesk-Produktboards. Der Berichtsdienst
ist keine Aufgabenqueue, startet keine Agenten und verändert keine Terminals.
Fehlende oder alte Meldungen bedeuten unbekannt, keinen belegten Stillstand oder
Erfolg. Ein `done`-Selbstbericht ersetzt keine unabhängige Abnahme.

## Vor dem Schreiben die Runtime unterscheiden

Der alte installierte Adapter kann weiterhin ein Board pro Instanz erzeugen.
Vor Nutzung prüfen:

```sh
~/.local/bin/bigplan-report capabilities
```

Die neue Ausgabe nennt `shared_overview: true`, `per_instance_boards: false`,
`unchanged_reports_append: false`, `refresh_appends: false` und
`runtime_compatible: true`. Fehlt der Befehl
oder ein solcher Nachweis, fachliche Meilensteine direkt im bestehenden
Produktboard mit stabiler Operationskennung, beobachteter Revision und unabhängigem
Readback speichern. Keine neuen Berichtsboards als Ausweichweg anlegen.

```sh
~/.local/bin/bigplan-report report \
  --instance codex-SITZUNGS-ID --agent Codex --report-id schritt-01 \
  --status working --done 'API geprüft' --working 'Tests' --next 'Review'
~/.local/bin/bigplan-report overview
```

Stabile Instanzkennung je Sitzung verwenden, etwa `codex-SITZUNGS-ID` oder
`grok-SITZUNGS-ID`. Eine neue fachliche Meldung erhält eine neue `report-id`.
Wiederholung derselben Kennung mit identischen Feldern liefert die ursprüngliche
Quittung, auch nach Neustart und späteren Meldungen. Anderer Inhalt unter derselben
Kennung ist ein Konflikt. Unklaren Ausgang zuerst über die Originalkennung
abgleichen, nicht mit einer neuen ID wiederholen. Status: `working`, `blocked`,
`idle`, `done`, `stopped`; optional `--blocker`. Höchstens 600 Zeichen je Feld,
80 Zeichen für den Agentennamen.

## Speicherung und Aktualität

Die vorhandene zentrale Übersicht wird wiederverwendet; wenn noch keine Übersicht
vorhanden ist, wird sie einmal angelegt. Neue Instanzen erzeugen keine Threads.
Identische Felder mit neuer Meldungskennung erneuern nur den aktuellen Zustand
und die dauerhafte Idempotenzquittung. Fachliche Änderungen erzeugen einen kurzen
Beitrag mit vollständigen Feldern in `metadata.agent_report`; `done` erscheint
als `result`, `blocked` als `problem`, andere Änderungen als `progress`.

Aktueller Zustand und Quittung werden gemeinsam in der bestehenden
Workspace-Transaktion gespeichert. Historische Instanzboards bleiben lesbar und
unverändert. Geschlossene, archivierte oder in den Papierkorb verschobene Quellen
werden nicht automatisch wieder geöffnet oder unter neuer ID nachgebaut.
Bestehende Übersichtsnotizen bleiben erhalten; nur der vom Adapter verwaltete
Abschnitt wird bei der nächsten Meldung ersetzt. Fremde Anmerkungen bleiben stehen.

`overview` berechnet Aktualität frisch. `refresh` oder `watch --interval 60`
aktualisieren nur abgeleitete Frische; sie erzeugen weder Eigenmeldungen noch
Heartbeat-Beiträge. Nach standardmäßig 180 Sekunden ist eine Meldung `stale`;
`reported_at` bleibt ohne Eigenmeldung unverändert. Diese technische Zeitgrenze
ist keine Aufforderung, alle 180 Sekunden etwas zu berichten. Bei abgestelltem
Rechner/Dienst Zeitstempel selbst vergleichen.

Die CLI lädt den Service aus ihrem eigenen Releasepfad. Änderungen im Checkout
aktualisieren deshalb weder den installierten Launcher noch einen laufenden
`watch`-Prozess. Der alte APIpin kann die heutigen Papierkorb-/Lifecycle-Grenzen nicht sicher
prüfen; die neue CLI meldet dann `runtime_compatible: false` und lehnt Schreiben
ab. Eine Aktivierung muss auch den APIpin aus geprüftem Quellstand beziehen.
Aktivierung erst aus geprüftem Quellpin, nach den erforderlichen
Integrationsprüfungen, mit gesichertem Rückfallpfad und unabhängigem Readback.
Laufende Agentensitzungen und Benutzerdaten bleiben erhalten. Ein Quellpatch ist
keine installierte Desktopversion. Das neue Capability-Schema ist
`bigplan.agent-reports.capabilities.v2`; das lesende Übersichtsformat bleibt
`bigplan.agent-overview.v1`.

## English

Report substantive milestones, blockers, decisions and results. New sessions share
one existing overview instead of creating instance boards. Unchanged reports with
fresh IDs update current status and durable receipts without appending history.
Changes produce short entries with complete report fields in metadata. Existing
instance boards and their contents remain available; no automatic cleanup or
restoration takes place. Current notes occupy a managed section, preserving other
notes. Reusing an ID with changed content fails; exact retries return the original
receipt without rolling current status back.

Check `bigplan-report capabilities` before writing: an older installed adapter may
still create instance boards. Until a verified update, record milestones directly
in the existing product board with a stable operation ID, observed revision and
independent readback. Do not fall back to creating a board. Refresh only derives
freshness, with no heartbeat entries or invented progress. Staleness is uncertainty,
not evidence that an agent stopped. The source change does not update running
services or install a desktop release.
