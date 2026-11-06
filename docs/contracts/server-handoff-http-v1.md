# Optionaler Handoff-Transport für BP-REMOTE-02

05.11.2026, `BIGPLAN-REMOTE-SLICE-20261105-V1`. Quellimplementierung für einen
isolierten lokalen Vertikalschnitt; keine produktive Aktivierung/Remoteabnahme.

`server_sync.app.create_app(..., handoff_rpc=True)` registriert genau
`GET/POST /api/projects/{pid}/handoff`. Standardwert `False`: bestehende
Serverinstallationen und die vorhandene Server-CLI aktivieren diesen Weg nicht.
Kein zweiter Server, Dispatcher, Agentenprozess oder neue Rechteengine.

GET meldet `format=threaddesk.handoff-http.v1`, Projekt, aus authentifiziertem
Benutzer/Projekt abgeleitete `subject_ref`, erlaubte Tools und ausdrücklich
unsupported interaktive Tools. POST verlangt exakt `{tool, arguments}` und
liefert dieselbe Identitätsbindung sowie das vorhandene `McpBridge.call`-Ergebnis.

Zulässig sind vorhandene Methoden `issue_handoff`, `get_issued_handoff`,
`bind_handoff_run`, `record_handoff_question`, `import_return`, `get_return`.
`import_return` verlangt `strict_binding=true`. Schema-, Quellrevision-,
Knowledge-, Run- und Return-Prüfungen verbleiben in denselben Core-Methoden.
Vor storeweiten Lookups werden Benutzer- und Projektgrenzen geprüft, auch
bei wiederholten Operations-/Return-IDs. Fremde IDs ergeben 404.

Die einzige ergänzende Metadatenoperation `reserve_handoff_delivery` schreibt
einen unveränderlichen Zustellmarker in das bereits existierende issued-
Handoffregister. Exakte Felder: `handoff_id`, `core_task_id`, `device_ref`,
`operator_scope`, `principal_ref`, `request_sha256`, `envelope_sha256`.
Gleiche Bindung liefert `duplicate=true`, andere Bindung Konflikt.
Bestehende native Laufbindungen müssen Core-ID/Principal/Operator-Scope
einhalten. Keine Thread-/Knowledge-Revision wird dafür erhöht; keine Queue,
automatische Ausführung oder neue Freigabe entsteht.

`review_return` und `answer_handoff_question` werden in diesem HTTP-Adapter
vollständig verweigert, einschließlich Cookie/CSRF. Der vorhandene Owner-Bearer
kann sich selbst einen Browser-Cookie beschaffen. Cookie/CSRF beweisen somit
keine separate Operatorrolle. Bestehende lokale Operatorfunktionen bleiben
erhalten, die sichere unabhängige Remoteentscheidung gehört nicht zu diesem
Paket. Der Worker darf sich keine Abnahme selbst ausstellen.

Der Adapter nutzt ausschließlich vorhandene Auth-, TLS-/Origin-/CSRF- und
Body-Grenzen, Tenant-Lock und Core-Transaktionen. Keine verschachtelte
Store-Transaktion um Serviceaufrufe. Geheimnisse oder unstrukturierter
Whiteboardtext sind keine auszuführenden Kommandos.

`tests/test_server_handoff_transport.py` prüft reale Core-Receipts in temporären
Stores mit TestClient, Projekt-/Benutzerisolation, default-off, strikten Import,
Zustellmarker, Konflikt sowie Bearer→Cookie-Selbstabnahme. Der zugehörige
KB-Test `test_remote_relay.py` prüft zusätzlich tatsächliches lokales TLS und
MCP/Core bis Return/Whiteboard, mit synthetischem kostenfreiem CLI-Agenten.
Keiner dieser Nachweise ist eine Handy-, Debian- oder echte CLI-Abnahme.
