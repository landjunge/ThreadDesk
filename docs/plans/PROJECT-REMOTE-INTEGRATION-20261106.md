# Gemeinsamer Projekt- und Remote-Quellstand

6. November 2026 · **BP-PROJECT-REMOTE-INTEGRATION-20261106-M4**.
Karte `188ce4729a62/84e21d69ef65`, Übernahme `188ce4729a62/112836c79cea`.

Der eigene Integrationsbranch `feat/project-remote-integration-20261106` verbindet
die vollständigen Eltern M3 `cd5c994b90acd6453ca1158e23c9887efdd19ec5` und
Remoteadapter `e90e9a6ce29c5c22b187147da35fcff40f51a790` durch einen echten Merge.
Gemeinsame Basis ist `067a525798817629ae1d2b8e741d109230f54d08`. Die Eltern hatten
keine überlappenden Dateiänderungen; es wurde keine Konfliktseite pauschal gewählt.
Bestehender eigener Worktree: `threaddesk-worktrees/project-memory-20261106`.
Der jeweilige eingefrorene gemeinsame Commit, die Tests und der unabhängige Review
stehen im ThreadDesk-Ergebnisbeleg und in der privaten Abnahmeevidenz.

## Was gemeinsam vorhanden ist

Der lokale Commandkern bietet weiterhin `project.preview`, `project.start`,
`project.memory`, `project.plan.get` und `project.plan.revise`, einschließlich
Projektgrenzen, Quellen, alter Fassungen, Thread-CAS, vollständiger Wissensbindung,
stabiler Operationen und aktuellem Wiedereinstieg. Die vorhandenen UI-, CLI- und
MCP-Verträge bleiben erhalten. [M3-Vertrag](PROJECT-PLAN-20261106.md).

Daneben bleibt der bestehende Serveradapter ausdrücklich opt-in:
`server_sync.app.create_app(..., handoff_rpc=True)`. Nur dann sind
`GET/POST /api/projects/{pid}/handoff` registriert. Standard und Server-CLI bleiben
unverändert. Authentifizierung, Tenant-/Projektprüfung, TLS-/Origin-/CSRF-Grenzen,
Issued- und Returnbelege sowie die bestehende Transaktionsführung werden verwendet.
[Remotevertrag](../contracts/server-handoff-http-v1.md).

Die Kennungen haben verschiedene Rollen: Ein lokaler Erstplan enthält eine
Graphprojektkennung und einen gesonderten zugeordneten Thread. Ein Serverprojekt
verwendet seine vorhandene, in SyncStore registrierte Threadkennung als `pid`.
`project.start` veröffentlicht keinen Serverbereich. Der HTTP-Handoffadapter
nimmt keine lokalen `project.*`-Commands entgegen. Es wird keine automatische
Umbenennung, Veröffentlichung oder Übertragung der Planhistorie eingeführt.
Die Testfixture registriert ihren eigenen Planthread ausdrücklich über den
vorhandenen `SyncStore.create_project(..., project_id=thread_id)`-Vertrag.
Das ist Testaufbau und kein neuer Bedienweg oder produktiver Import.

## Gemeinsame Nachweise

`tests/test_project_remote_integration.py` verwendet ausschließlich temporäre
Tenantdaten und den tatsächlichen Core plus HTTP-TestClient. Es prüft:

- Erhalt der unterschiedlichen Kennungen, Benutzer-/Projektgrenzen, vorhandenen
  Handofffähigkeiten und Ablehnung lokaler Plancommands im Handoffadapter.
- Ausgabe eines Handoffs, anschließende Planrevision und Abweisung der veralteten
  Laufbindung. Die ausgegebene alte Quelle und die alte Planfassung bleiben gleich.
- Neue Ausgabe mit aktuellem Planwissen, identische Zustellreservierung ohne Drift
  der Planbasis, Runbindung, strikter Returnimport und Readback. Eine Workerantwort
  akzeptiert weder einen Planpunkt noch sich selbst. Remote-Selbstabnahme bleibt
  verweigert; aktueller nächster Schritt und Threadauswahl bleiben erhalten.
- Direkte Knowledgeänderung ohne Threadrevisionsanstieg: Sowohl Remote-Return als
  auch bereits vorbereitete Planänderung werden aufgrund ihrer alten Wissensbasis
  abgewiesen. Historie und bestehende Wissenszustände bleiben erhalten.

Zusätzlich werden betroffene Projekt-, UI-/Browser-, MCP-/Command-, Knowledge-,
Issued-/Return-, Store-/CAS- und Serverregressionen gemeinsam geprüft. Ein echter
getrennter lesender Reviewer erhält den fixierten Stand; Quellen schreibt nur der
TD-Parent. Der KB-Agent erhält denselben ausdrücklich benannten gemeinsamen Pin
für seinen bestehenden synthetischen TLS/Core/TD-Harness. Diese externe Prüfung
ist erst nach seinem tatsächlichen Beleg bestätigt. HTTP-TestClient allein ist
kein echter TLS- oder KB-Lauf.

## Liefergrenzen

Es entsteht keine neue Queue, kein Dispatcher, kein Agentenstart und keine
Ausführungsfreigabe durch einen Plan oder READY-Text. Unabhängige Remoteentscheidungen
bleiben im vorhandenen Adapter unsupported. M3-Historie wird nicht als portable
Servermetadaten ausgegeben; die bestehende permanente Purgeblockade für noch nicht
reduzierbare Planbelege bleibt dokumentiert. Keine KB-Code-, Dienst-, VM-, Profil-
oder Fremdsitzungsänderung durch diesen TD-Auftrag.

Dies ist ein gemeinsamer geprüfter Quellkandidat. Featurepush setzt einen aktuellen
Workflow-/Kostenabgleich voraus. Main-/PR-, produktive Aktivierung, Desktop-/Paket-,
Livepeer-, native Windows- und Mehrbenutzerabnahme bleiben eigene Schritte unter
den bestehenden Gates. Öffentliche Downloads oder Webseiten erhalten durch diese
interne Quellintegration keine neue Verfügbarkeitsbehauptung.

English: This source merge preserves both the local project-plan contracts and the
existing opt-in HTTP handoff adapter. Graph project IDs and server thread IDs retain
their separate meanings. The integration tests use explicit synthetic setup and
prove stale-source rejection, immutable history, delivery reservation, strict return
readback and unchanged active selection. They start no agents. An external pinned
KB/TLS harness, deployment, desktop packaging and multi-user acceptance require
their own evidence; none is implied by this source candidate.
