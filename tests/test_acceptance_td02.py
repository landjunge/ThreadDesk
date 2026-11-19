"""CLI, local UI and MCP stay usable together. A foreign web request changes nothing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from threaddesk.api.service import ThreadService
from threaddesk.services.mcp import McpBridge
from threaddesk.ui.cli import main
from threaddesk.ui.mcp_stdio import handle
from threaddesk.ui.server import create_app


def _snapshot(home: Path):
    os.environ["THREADDESK_HOME"] = str(home)
    os.environ["THREADDESK_STORAGE"] = "json"
    service = ThreadService()
    return [
        (thread.id, thread.title, thread.context.notes, thread.revision)
        for thread in service.list(True)
    ]


def test_cli_survives_foreign_origin_and_mcp_still_answers(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("THREADDESK_HOME", str(home))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")

    assert main(["new", "Abnahme"]) == 0
    assert main(["note", "Notiz bleibt"]) == 0
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "Abnahme" in listed

    before = _snapshot(home)
    assert len(before) == 1
    assert before[0][2] == "Notiz bleibt"
    client = TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000))
    assert client.get("/").status_code == 200
    before = _snapshot(home)
    denied = client.post("/threads", data={"title": "fremd"}, headers={"Origin": "http://evil.invalid"})
    assert denied.status_code == 403
    assert denied.json()["error"] == "foreign_origin"
    assert _snapshot(home) == before

    assert main(["list"]) == 0
    again = capsys.readouterr().out
    assert "Abnahme" in again
    assert "fremd" not in again
    assert main(["note", "Weiter nutzbar", "--append"]) == 0
    assert _snapshot(home)[0][2] == "Notiz bleibt\nWeiter nutzbar"

    bridge = McpBridge(ThreadService())
    initialized = handle(bridge, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert initialized["result"]["serverInfo"]["name"] == "threaddesk"
    listed_tools = bridge.call("list_threads", {})
    assert listed_tools["ok"] is True
    assert [row["title"] for row in listed_tools["result"]] == ["Abnahme"]

    guard = tmp_path / "selftest-guard"
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    env["THREADDESK_HOME"] = str(guard)
    env["THREADDESK_STORAGE"] = "json"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(root / "packaging/tauri/backend/server.py"), "--self-test"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "self-test: OK" in completed.stdout
    assert not guard.exists()
    assert _snapshot(home)[0][2] == "Notiz bleibt\nWeiter nutzbar"
