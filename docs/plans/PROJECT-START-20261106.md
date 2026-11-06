# Projektstart aus einer Idee

Folgepaket: [M3 – nachvollziehbare Planrevision und aktueller Wiedereinstieg](PROJECT-PLAN-20261106.md).

Stand: 6. November 2026. **BP-PROJECT-START-20261106-M2**.
Auftrag: Fortsetzung des universellen Plattformauftrags, ausdrücklich ohne die
andere Sitzung zu stören. ThreadDesk-Arbeitszuordnung `188ce4729a62/d9a2db6c4bc0`.
Eigener Branch `feat/project-start-20261106`, Basis M1 `e65016f`; vorhandener eigener
Worktree `threaddesk-worktrees/project-memory-20261106`. Parent ist einziger Schreiber;
nativer getrennter Codex-Prüfer arbeitet lesend mit eigener Berichtskennung.

## Praktischer Ablauf

**Projekte → Neues Projekt → Idee beschreiben → ersten Plan vorbereiten → anpassen
→ Projekt und Entwurf speichern.** Der Name ist optional; ohne Namen wird ein
kurzer Auszug der Idee verwendet. Ziele, nächste Schritte und Fragen lassen sich
vor dem Speichern bearbeiten. Danach erscheinen sie im bestehenden Projektgedächtnis.
Weitere Wissenseinträge, Zustandsänderungen und Wiedereinstieg verwenden weiter
bestehende Thread-/Wissensaktionen; kein neuer Planeditor ersetzt diese Verträge.

Der Ausgangsentwurf ist eine lokale Hilfsstruktur, keine behauptete KI-Analyse.
Kira oder ein beauftragter Agent kann über dieselbe Schnittstelle bereits einen
fachlich passenden strukturierten Plan liefern. Fehlende Planlisten erhalten
lokale Standardvorschläge, ausdrücklich gelieferte leere Listen bleiben leer.
`plan_origin` unterscheidet `local_outline`, `supplied_fields` und `mixed`.
Die neue Funktion startet keine Modelle, Worker, Handoffs oder AutoNext-Aufgaben.

Der vorhandene Demo-Launcher öffnet einen eigenen Workspace auf einem freien
Loopbackport. In dieser Runde wurde auch ein echter Kompatibilitätsfehler im
M1-Launcher behoben: Das vorhandene Git2.15 unterstützt `--path-format` nicht.
Der Startweg verwendet jetzt `rev-parse --git-common-dir` und löst relative Pfade
explizit auf. Der Test führt das echte Git aus und ersetzt ausschließlich den
Pythonstart, damit kein Browser oder laufender Dienst berührt werden muss.

## Ein gemeinsamer Vertrag

`project.preview` ist lesend und transient. `project.start` verwendet die vorhandene
CommandApplication, `workspace.write`, `expected_revision: 0` und eine stabile
Operationskennung. UI, HTTP, CLI und generiertes MCP verwenden denselben Handler.

```json
{
  "version": 1,
  "workspace_id": "EXAKTE_KENNUNG_AUS_COMMAND_CATALOG",
  "operation_id": "EINDEUTIGE_NEUE_AUFTRAGSKENNUNG",
  "expected_revision": 0,
  "command": "project.start",
  "arguments": {
    "title": "Berlin-Buch",
    "idea": "Ein Buch über Berlin recherchieren und Quellen nachvollziehbar belegen.",
    "source_ref": "conversation:EXAKTE_QUELLE",
    "source_revision": "EXAKTER_QUELLSTAND",
    "language": "de",
    "plan": {
      "goals": ["Einen belegten Kapitelentwurf erstellen"],
      "next_steps": ["Vorhandene Quellen prüfen", "Kapitelstruktur entwerfen"],
      "open_questions": ["Welcher Zeitraum steht im Mittelpunkt?"]
    }
  }
}
```

CLI: `td command --request-file request.json`; HTTP: bestehendes autorisiertes
`POST /api/commands`; MCP: `td_project__start` bzw. `td_project__preview`.
Previewargumente sind dieselben; Preview benötigt keine Operationskennung/CAS.
Grenzen: Idee10000, optionaler Titel240, Quellenreferenz2000, Quellrevision256Zeichen;
pro Planliste bis8Einträge à300Zeichen. Große CLI-/MCP-Previewresultate werden über
vorhandene JSON-Readbackseiten und Digest gelesen. Der lokale HTML-Adapter nutzt
ein explizites128KB-Budget für den begrenzten gültigen Entwurf. Startresultate
enthalten nur IDs, Revisionen und Entwurfsstatus und bleiben klein.

## Atomarität und Arbeitskontinuität

Die vorhandene Commandtransaktion speichert Projektknoten, Thread mit expliziter
Projektzuordnung, Wissensknoten, Wiedereinstieg und Commandreceipt gemeinsam.
Es gibt kein zweites Ledger und keine verschachtelten `manage()`-Aufrufe.
Bestehende Wissens-/Organisationsprimitiven werden wiederverwendet.
`ThreadService.create(activate=False)` erhält die aktive Auswahl einschließlich
`None`, ohne vorübergehenden Wechsel oder `thread.switched`-Ereignis. Bisherige
Aufrufer behalten mit dem Standard `activate=True` ihr bisheriges Verhalten.

Ziele sind vorgeschlagene Entscheidungen (`proposed`), Schritte Ideen (`idea`),
Fragen offen (`waiting`). Eine gespeicherte Idee ist kein freigegebener Auftrag.
Geordnete Knotenkennungen im Threadkontext erhalten die ursprüngliche Planreihenfolge;
Wiedereinstieg enthält den ersten vorgeschlagenen Schritt. Allgemeine Wissensansichten
bleiben nach ihren bestehenden Prioritäten sortiert und zeigen gegebenenfalls Auszüge.
Quellen bleiben `referenced_unverified`; die vorhandene heuristische Secretprüfung
wird wiederverwendet und ist kein vollständiger Geheimniserkenner.

Gleiche Operation und gleicher Inhalt ergeben dieselbe Quittung, auch nach Neustart
und bei konkurrierenden getrennten Storeinstanzen. Anderer Inhalt unter gleicher
Kennung führt zu `operation_conflict`. Bei einem Abbruch vor Commit werden auch
Wissens-/Evidenzobjekte und gepufferte Ereignisse zurückgerollt. Nach einem
JSON-Journalteilcommit stellt der vorhandene Store Zustand und Receipt wieder her;
der Handler wird nicht erneut ausgeführt. EventBus ist keine dauerhafte Outbox,
verlorene Benachrichtigungen werden nicht als wieder zugestellt ausgegeben.

Ein unbekannter UI-Ausgang erhält Idee, bearbeitete Felder und dieselbe Operations-ID.
Der lesende Statuslink zeigt einen tatsächlich gespeicherten Start wieder an und
führt keinen Start aus. Bestehende JSON-Journalfehler können `invalid_state` statt
`command_unconfirmed` melden; beide gelten im Save-Formular als klärungsbedürftig.
Keine automatische neue Kennung und kein automatischer Wiederholungsversuch.

## Prüfung und Liefergrenze

`tests/test_project_start.py`: beide Stores, transienter Entwurf, Zustände/Reihenfolge,
vorhandene oder leere Auswahl, Neustart/Idempotenz, abweichende Inhalte, Berechtigungen,
Midbatch-Rollback, Konkurrenz mit getrennten Verbindungen, JSON-Journalwiederherstellung,
echte CLI-/MCP-Prozesse sowie Launcher mit echtem Git. `tests/test_project_start_ui.py`:
Formularablauf/gleicheID, Antwortverlust nach Commit, Statuslesen, Validierung,
CSRF, Unicode-/Escaping-/Secretfälle. Browserfälle ergänzen echte Vorschau,
Bearbeitung, Validierungsfehler, Korrektur und Speicherung bei1280/390px auf DE/EN.
Aufnahmen liegen unter `test-results/project-memory/start-*.png`.
Finale Ergebnisse und Quellpin stehen im ThreadDesk-Abschlussbericht.

Alle Schreib-/Browserprüfungen verwenden eigene temporäre Workspaces und eigene
Prozesse. Fremde Terminal-/TLS-Arbeit, VMs und gemeinsame Laufzeitkonfigurationen
werden nicht gesteuert oder verändert. Keine Produktinstallation oder Main-/PR-CI.
M1/M2 bleiben getrennt nachvollziehbare Kandidaten, bis reguläre Integration samt
bestehender Cloud-/ARM-CI-Grenze und tatsächlicher Livepeer-/Desktopabnahme erfolgt.
Eine autonome domänenspezifische Planung, dynamische Teamausführung, Mehrbenutzerrechte
und Remote-End-to-End-Abnahme sind weitere Pakete, nicht Teil dieses Nachweises.
