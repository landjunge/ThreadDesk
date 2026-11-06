#!/usr/bin/env python3
"""Open the candidate with synthetic projects in a new, separate workspace."""

from __future__ import annotations

import argparse
import json
import os
import socket
import tempfile
import webbrowser
from pathlib import Path

from threaddesk.api.service import ThreadService
from threaddesk.services.commands import CommandApplication
from threaddesk.services.knowledge_memory import manage as remember
from threaddesk.services.thread_management import manage
from threaddesk.storage.json_store import JsonStore


def seed(root):
    svc = ThreadService(JsonStore(root))
    projects = []
    for number, (title, summary, next_step) in enumerate(
        (
            (
                "Berlin-Buch · Demo",
                "Recherche und Kapitelplanung beginnen.",
                "Zwei Primärquellen prüfen.",
            ),
            (
                "Buschradio · Demo",
                "Eine Interviewidee ist festgehalten.",
                "Interviewfragen entwerfen.",
            ),
            (
                "Ocean · Demo",
                "Externe Plattform; noch keine offizielle Anbindung verifiziert.",
                "Offizielle Integrationsmöglichkeiten klären.",
            ),
        )
    ):
        project = svc.create_node(
            "project",
            title,
            details="Synthetische Beispieldaten, keine laufende Projektarbeit.",
        )
        projects.append({"id": project.id, "title": title})
        for step in range(4 if number == 0 else 1):
            thread = manage(
                svc,
                {
                    "operation_id": f"demo-thread-{number}-{step}",
                    "action": "create",
                    "expected_revision": 0,
                    "data": {
                        "title": f"{title} · Arbeitsschritt {step + 1}",
                        "project_id": project.id,
                    },
                },
            )["thread_id"]
            for item, (action, fields) in enumerate(
                (
                    ("save_reentry", {"summary": summary, "next_step": next_step}),
                    ("record", {"kind": "task", "title": next_step}),
                    (
                        "record",
                        {
                            "kind": "question",
                            "title": "Welche Quellen und Anforderungen gelten?",
                        },
                    ),
                )
            ):
                remember(
                    svc,
                    {
                        "operation_id": f"demo-memory-{number}-{step}-{item}",
                        "id": thread,
                        "expected_revision": svc.get(thread).revision,
                        "action": action,
                        "data": {
                            "source_ref": "synthetic:project-memory-demo",
                            "source_revision": "demo-v1",
                            **fields,
                        },
                    },
                )
            svc.append_whiteboard(
                thread,
                actor="Demo",
                actor_type="human",
                entry_type="note",
                content="Gespeicherter Beispielstand; keine Agenten gestartet.",
            )
    app = CommandApplication(svc, allowed_scopes={"workspace.read"})
    result = app.call(
        {
            "version": 1,
            "workspace_id": app.workspace_id,
            "command": "project.memory",
            "arguments": {"project_id": projects[0]["id"]},
        },
        read_only=True,
    )
    return {
        "workspace": str(root),
        "projects": projects,
        "workspace_id": app.workspace_id,
        "sample_snapshot": result["result"]["snapshot"],
        "synthetic": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace", type=Path, help="New directory; existing directories are refused"
    )
    parser.add_argument(
        "--serve", action="store_true", help="Run the isolated candidate on loopback"
    )
    parser.add_argument(
        "--open", action="store_true", help="Open this candidate in a new browser tab"
    )
    args = parser.parse_args()
    if args.workspace:
        root = args.workspace.expanduser().resolve()
        try:
            root.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error("Workspace already exists; choose a new directory.")
    else:
        root = Path(tempfile.mkdtemp(prefix="threaddesk-project-memory-"))
    report = seed(root)
    if not args.serve:
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 0
    os.environ["THREADDESK_HOME"] = str(root)
    os.environ["THREADDESK_STORAGE"] = "json"
    import uvicorn

    from threaddesk.ui.server import create_app

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{listener.getsockname()[1]}/projects"
        print(json.dumps({**report, "url": url}, ensure_ascii=False), flush=True)
        if args.open:
            # Opening a tab does not switch or modify another application's session.
            import threading

            threading.Timer(1, webbrowser.open_new_tab, args=(url,)).start()
        uvicorn.Server(uvicorn.Config(create_app(), log_level="warning")).run(
            sockets=[listener]
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
