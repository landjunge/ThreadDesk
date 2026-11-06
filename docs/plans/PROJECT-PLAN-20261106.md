# Planrevision und aktueller Wiedereinstieg

Stand: 6. November 2026. **BP-PROJECT-PLAN-20261106-M3**.
Freigegebene Karte `188ce4729a62/1efb9741ba1f`, Koordination
`482f593429ad/c154c9769e17`; tatsächliche Übernahme `188ce4729a62/c9b04af821c8`.
Eigener vorhandener Worktree `threaddesk-worktrees/project-memory-20261106`,
Branch `feat/project-plan-20261106`, Basis M2 `54624d8`. Ein schreibender Parent;
getrennter lesender Codex-Prüfer gemäß Repo-Regel, Sol/max beibehalten.
KB-Sitzung01a1a7d1 samt Code/Terminals/Grokreview/Diensten/VM/Profilen ausgeschlossen.

## Nutzbarer Abschnitt

In einem gespeicherten Projekt **Plan und Verlauf öffnen**, aktuellen Plan und
Wiedereinstieg lesen, Planpunkte/Zusammenfassung anpassen, Grund der Änderung
angeben und eine neue Fassung speichern. Frühere Fassungen zeigen ihren damals
festgehaltenen Inhalt, Zustand, Grund und Quellenverweis. Eine gewählte Altversion
ist lesend; die aktuellen Livezustände werden getrennt angezeigt. Die Demo erstellt
ihre Hauptprojektthreads jetzt über den gemeinsamen Projektstartvertrag und bietet
unmittelbar lesbare/revidierbare Beispielpläne. Alle Beispieldaten bleiben synthetisch.

Der aktuelle nächste Schritt ist der erste aktuelle Plan-Task, der nicht
accepted/done/archived/superseded ist. Rejected bedeutet im vorhandenen Taskautomaten
Nacharbeit und bleibt offen. `get_reentry.current_plan` und die Projektübersicht
verwenden diese Ableitung. `get_reentry.saved` bleibt der tatsächliche gespeicherte
Checkpoint und behauptet keine spätere Neuspeicherung. Leere nächste Schritte
werden als kein offener Schritt dieser Planfassung angezeigt, nicht als neue Arbeit.

## Gemeinsame Befehle

```json
{
  "version": 1,
  "workspace_id": "AUS_DEM_TATSAECHLICHEN_KATALOG",
  "command": "project.plan.get",
  "arguments": {"project_id": "EXAKTES_PROJEKT", "thread_id": "EXAKTER_THREAD"}
}
```

Der Read liefert `thread_revision`, `plan_revision`, `basis_digest`, eingefrorenen
`snapshot`, separate `live_plan`/`current_reentry` und begrenzte Historymetadaten.
Mit `revision` wird eine konkrete alte Fassung gelesen. Historyseiten sind auf
höchstens20Einträge begrenzt; `offset>0` benötigt `expected_plan_revision`, damit
eine neue Fassung die Folgeseite nicht still verschiebt. Große JSONresultate nutzen
bestehende Command-Readbackseiten und `result_digest`; keine neue Export-/Taskqueue.

```json
{
  "version": 1,
  "workspace_id": "AUS_DEM_TATSAECHLICHEN_KATALOG",
  "command": "project.plan.revise",
  "operation_id": "EINDEUTIGE_NEUE_OPERATION",
  "expected_revision": 7,
  "arguments": {
    "project_id": "EXAKTES_PROJEKT",
    "thread_id": "EXAKTER_THREAD",
    "expected_plan_revision": 1,
    "expected_basis": "64_HEXZEICHEN_AUS_DEM_LETZTEN_READ",
    "plan": {
      "goals": ["Ein belegtes Ergebnis erstellen"],
      "next_steps": ["Neue Quelle prüfen", "Ergebnis dokumentieren"],
      "open_questions": ["Welche Aussage muss noch geklärt werden?"]
    },
    "reason": "Eine neue Quelle verändert die Reihenfolge.",
    "source_ref": "conversation:EXAKTE_QUELLE",
    "source_revision": "EXAKTER_QUELLSTAND"
  }
}
```

Die Threadrevision oben ist nur ein Beispiel; beide Revisionen und der Hash müssen
vom eigenen Read stammen. Scope `workspace.read` für Get, `workspace.write` für
Revise. Bestehende UI/HTTP/CLI/MCP-Dispatcher verwenden denselben Handler.
Der lokale HTML-Read nutzt ein ausdrückliches2MiB-Budget für die schema-begrenzten
Snapshot-/History-/Livewerte; normale CLI/MCP-Resultate bleiben paginiert.

## Persistenz und Konflikte

Revisionsbelege liegen im vorhandenen ManagementOperationStore, nicht in einer
neuen Datenbank oder Ausführungsqueue. `kind=project_plan_revision`, abgeleiteter
Schlüssel pro Thread/Fassung und `storage_operation_id` erhalten die bestehende
JSON→SQLite-Migrationsfähigkeit. Der gesamte Plansnapshot steht im `result` mit
expliziter Thread-/Projektbindung; es gibt keine unbeachteten Plantextkopien in
freien Rootfeldern. Kein bestehender Schlüssel wird überschrieben. Die vorhandene
Purgeinventur erkennt die Besitzerbindung und blockiert derzeit eine permanente
Löschung dieser noch nicht reduzierbaren neuen Belegform ausdrücklich. Kein
stilles Zurücklassen von Kopien und kein Umbau des Purgeprotokolls in M3.

Der Thread hält einen strikt versionierten Head. Neue M3-Projekte erhalten ihre
exakte erste Fassung beim Projektstart. Alte M2-Pläne werden anhand ihrer geordneten
Referenzen nur lesend beobachtet; erst bei der ersten Änderung wird eine ausdrücklich
`observed_m2` genannte Baseline gespeichert. Das ist kein nachträglich erfundener
Original-Erstellungsnachweis. Unbekannte Formate/kaputte Heads werden abgewiesen.

Der Write läuft mit der vorhandenen Commandreceipt in einer Storetransaktion:
Thread-CAS, exakte Projektzuordnung und komplette aktuelle Wissensbasis werden
geprüft, neue Fassung und Wiedereinstieg gemeinsam gespeichert. Der Basisdigest
bindet Projekt, Thread, Head und ALLE threadgebundenen Wissensknoten, weil direkte
Graphänderungen nicht zwingend die Threadrevision erhöhen. Der Hash ist lokale
Konsistenzbindung, keine externe Beglaubigung. Quellen bleiben unverified.

Unveränderte aktuelle Planpunkte werden gruppenweise mit derselben Kennung und
allen fachlichen Zuständen weiterverwendet, auch confirmed/accepted/answered.
Nur neu hinzugefügte Texte erhalten neue Draftknoten. Entfallene reine Planentwürfe
(proposed/idea/waiting) werden eng begrenzt mit Revisionsherkunft superseded;
bereits etablierte/abgeschlossene Einträge bleiben unangetastet. Die globale
Transitionstabelle wird dafür nicht gelockert. Historische Snapshotbytes bleiben
von späteren Liveänderungen getrennt. Keine neue automatische Zuordnung semantisch
ähnlicher Aufgaben und kein vollständiges Teammanagement.

Threadsnapshot-Restore kann seinen Head zurücksetzen, aber nicht die externen
Revisionsbelege entfernen. Fehlender/zurückgesetzter Head, bereits vorhandene
Folgefassung oder inkonsistente Hashbeziehung ergeben `plan_state_conflict`;
keine automatische Reparatur, Umdefinition von Restore oder neue zweite Linie.
Gleiche Operation mit gleichem Inhalt liest auch nach Restart ihre ursprüngliche
Completequittung; anderer Inhalt unter derselben Kennung ist ein Konflikt.
Bei UNKNOWN bleiben Formular, Kennung und Basis erhalten; der Statuslink liest
nur die bestehende Quittung und startet keine neue Revision. JSON-Journal-Recovery
stellt Head, Beleg, Knoten, Reentry und Commandreceipt zusammen wieder her.
EventBus bleibt eine Benachrichtigungsgrenze, keine dauerhafte Outbox.

## Abnahme und Grenze

Gezielte Nachweise in `test_project_plan.py`/`test_project_plan_ui.py`: beide Stores,
Erstplan→Revision→alte Fassung/Herkunft→aktueller Wiedereinstieg, vollständige
Wissensbindung, Projektgrenzen, Thread-CAS, gleiche/abweichende ID, konkurrierende
Operationen, Erhalt abgeschlossener Punkte, M2-Adoption, unbekannte Schemata,
Restorekonflikte, Rollback, JSON-Teilcommit, Migration, Purgebeleginventur,
echte CLI-/MCP-Prozesse, große Readbackseiten und UI-UNKNOWN/CSRF/Escaping.
Echte Browserfälle prüfen Speichern, Historie und aktuellen Wiedereinstieg nach
einem abgeschlossenen Schritt auf DE/1280px und EN/390px; Bilder unter
`test-results/project-memory/plan-*.png`. Finale Zählungen/Quellpin stehen im Board.

Alle Schreib-/Browserprüfungen verwenden eigene temporäre Daten und Prozesse.
Keine Worker-/Modellstarts aus dem Plan, neue Queue oder neuer Dispatcher.
Kein Mainmerge/PR/produktives Paket/Livepeerwechsel in dieser Karte; bestehende
CI-/Kosten-/Produktivgates sowie nativeWindows-/Mehrbenutzergrenzen bleiben getrennt.
