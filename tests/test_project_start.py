"""Project intake uses atomic receipts, with no agent or active-session effects."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.knowledge_memory import reentry
from threaddesk.services.mcp import McpBridge
from threaddesk.services.mcp_commands import tool_name
from threaddesk.services.project_memory import read
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[1]
IDEA = {
    "idea": "Ein Buch über Berlin recherchieren und Quellen belegen.",
    "source_ref": "synthetic:conversation:idea",
    "source_revision": "message-42",
}


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(tmp_path, request):
    value = ThreadService(request.param(tmp_path / "workspace"))
    yield value
    if hasattr(value.store, "connection"):
        value.store.connection.close()


def request_for(svc, operation="new-project", **args):
    return {
        "version": 1,
        "workspace_id": CommandApplication(svc).workspace_id,
        "command": "project.start",
        "operation_id": operation,
        "expected_revision": 0,
        "arguments": {**IDEA, **args},
    }


def create(svc, operation="new-project", **args):
    return CommandApplication(svc).call(request_for(svc, operation, **args))


def test_preview_is_transient_and_supplied_fields_remain_editable(svc):
    active = svc.create("Existing active work")
    events = []
    svc.bus.on("*", lambda name, _: events.append(name))
    app = CommandApplication(svc, allowed_scopes={"workspace.read"})
    req = {
        "version": 1,
        "workspace_id": app.workspace_id,
        "command": "project.preview",
        "arguments": {
            **IDEA,
            "language": "en",
            "plan": {"goals": ["Verify citations"]},
        },
    }
    first = app.call(req, read_only=True)["result"]
    assert first["plan"]["goals"] == ["Verify citations"]
    assert first["plan"]["next_steps"] == ["Review requirements and existing sources"]
    assert first["plan_origin"] == "mixed"
    assert first["plan_status"] == "draft" and not first["execution_started"]
    assert app.call(req)["result"] == first
    assert svc.current().id == active.id and len(svc.list()) == 1
    assert (
        not svc.list_nodes()
        and not svc.store.list_management_operations()
        and not events
    )


@pytest.mark.parametrize("has_active", [True, False])
def test_save_preserves_selection_and_stores_ordered_unapproved_plan(svc, has_active):
    active = svc.create("Foreign work stays selected") if has_active else None
    events = []
    svc.bus.on("*", lambda name, _: events.append(name))
    plan = {
        "goals": ["Check facts", "Keep references"],
        "next_steps": ["First inspect sources", "Then draft a chapter"],
        "open_questions": ["Which period?"],
    }
    first = create(svc, title="Berlin book", plan=plan)
    result = first["result"]
    assert not first["duplicate"] and not result["execution_started"]
    assert svc.store.get_current_id() == (active.id if active else None)
    assert "thread.switched" not in events
    assert events.count("project.draft_created") == 1
    thread = svc.get(result["thread_id"])
    assert thread.context.extra["organization"]["project_id"] == result["project_id"]
    for group, ids in result["node_ids"].items():
        assert [svc.get_node(i).title for i in ids] == plan[group]
        assert thread.context.extra["project_start"]["initial_node_ids"][group] == ids
    states = {
        svc.get_node(i).status for ids in result["node_ids"].values() for i in ids
    }
    assert states == {"proposed", "idea", "waiting"}
    saved = reentry(svc, {"id": thread.id})["saved"]
    assert saved["next_step"] == plan["next_steps"][0]
    assert saved["source_ref"] == IDEA["source_ref"]
    assert saved["source_verification"] == "referenced_unverified"
    memory = read(svc, {"project_id": result["project_id"]})
    assert memory["total_threads"] == 1 and memory["threads"][0]["id"] == thread.id
    assert len(json.dumps(first).encode()) < 5000
    assert not svc.store.list_issued_handoffs()
    reopened = ThreadService(type(svc.store)(svc.store.root))
    try:
        replay = create(reopened, title="Berlin book", plan=plan)
        assert replay["duplicate"] and replay["result"] == result
        assert len(reopened.list_nodes()) == 6
        with pytest.raises(ManagementError) as changed:
            create(reopened, title="Changed content", plan=plan)
        assert changed.value.code == "operation_conflict"
    finally:
        if hasattr(reopened.store, "connection"):
            reopened.store.connection.close()


def test_invalid_fields_secrets_and_missing_scope_never_create_partial_project(svc):
    app = CommandApplication(svc)
    invalid = [
        {"idea": " "},
        {"plan": {"next_steps": ["x"] * 9}},
        {"plan": {"goals": [" "]}},
        {"execute": True},
        {"language": "xx"},
        {"title": ""},
        {"plan": {"approved": True}},
    ]
    for patch in invalid:
        with pytest.raises(ManagementError) as bad:
            app.call(request_for(svc, **patch))
        assert bad.value.code == "validation_error"
    with pytest.raises(ManagementError) as secret:
        app.call(request_for(svc, idea="ghp_" + "x" * 40))
    assert secret.value.code == "secret_rejected"
    for req, scopes, read_only, code in (
        (request_for(svc), {"workspace.read"}, False, "permission_required"),
        (request_for(svc), {"workspace.write"}, True, "read_only_required"),
        (
            {**request_for(svc), "expected_revision": 1},
            None,
            False,
            "revision_conflict",
        ),
    ):
        with pytest.raises(ManagementError) as denied:
            CommandApplication(svc, allowed_scopes=scopes).call(
                req, read_only=read_only
            )
        assert denied.value.code == code
    assert (
        not svc.list()
        and not svc.list_nodes()
        and not svc.store.list_management_operations()
    )


def test_failure_mid_batch_rolls_back_receipt_context_and_events(svc, monkeypatch):
    original = svc.create("Existing")
    before = original.to_dict()
    events = []
    svc.bus.on("*", lambda name, _: events.append(name))
    create_node = svc.create_node
    count = 0

    def interrupted(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 3:
            raise OSError("synthetic failure inside project transaction")
        return create_node(*args, **kwargs)

    monkeypatch.setattr(svc, "create_node", interrupted)
    with pytest.raises(ManagementError) as error:
        create(svc)
    assert error.value.code == "command_unconfirmed"
    assert svc.get(original.id).to_dict() == before and svc.current().id == original.id
    assert len(svc.list()) == 1 and not svc.list_nodes()
    assert not events and not svc.store.list_management_operations()
    assert not svc.list_graph_events()
    assert not CommandApplication(svc).operation("new-project")["found"]


@pytest.mark.parametrize("same_content", [True, False])
def test_concurrent_requests_own_separate_stores_and_admit_once(svc, same_content):
    root, backend = svc.store.root, type(svc.store)

    def worker(number):
        other = ThreadService(backend(root))
        try:
            try:
                return create(
                    other, title="Same" if same_content else f"Different-{number}"
                )
            except ManagementError as exc:
                return {"code": exc.code}
        finally:
            if hasattr(other.store, "connection"):
                other.store.connection.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(worker, range(3)))
    assert sum(r.get("duplicate") is False for r in results) == 1
    if same_content:
        assert sum(r.get("duplicate") is True for r in results) == 2
        assert len({r["result"]["project_id"] for r in results}) == 1
    else:
        assert sum(r.get("code") == "operation_conflict" for r in results) == 2
    assert len(svc.list()) == 1 and len(svc.list_nodes()) == 4
    assert svc.current() is None


def test_json_partial_commit_recovers_project_and_same_receipt_once(
    tmp_path, monkeypatch
):
    svc = ThreadService(JsonStore(tmp_path))
    events = []
    svc.bus.on("*", lambda name, _: events.append(name))
    write = svc.store._atomic_json
    count = 0

    def crash(path, value):
        nonlocal count
        count += 1
        write(path, value)
        if count == 2:
            raise OSError("synthetic power loss after journal and first committed blob")

    monkeypatch.setattr(svc.store, "_atomic_json", crash)
    with pytest.raises(ManagementError) as unknown:
        create(svc)
    assert unknown.value.code == "invalid_state"  # Existing JSON journal guard.
    assert (tmp_path / ".management-commit.json").exists()
    recovered = ThreadService(JsonStore(tmp_path))
    receipt = CommandApplication(recovered).operation("new-project")
    assert receipt["state"] == "complete"
    repeated = create(recovered)
    assert repeated["duplicate"] and repeated["result"] == receipt["result"]
    assert len(recovered.list()) == 1 and len(recovered.list_nodes()) == 4
    assert not (tmp_path / ".management-commit.json").exists()
    assert not events  # EventBus is not a durable event replay/outbox.


def test_real_cli_then_mcp_process_share_the_same_start_receipt(svc):
    env = {
        **os.environ,
        "THREADDESK_HOME": str(svc.store.root),
        "THREADDESK_STORAGE": "sqlite"
        if isinstance(svc.store, SQLiteStore)
        else "json",
        "PYTHONPATH": str(ROOT / "src"),
    }
    req = request_for(svc)
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "threaddesk.ui.cli",
            "command",
            "--request",
            json.dumps(req),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    first = json.loads(cli.stdout)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name("project.start"),
            "arguments": {
                key: value
                for key, value in req.items()
                if key not in {"version", "command"}
            },
        },
    }
    mcp = subprocess.run(
        [sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
        env=env,
        input=json.dumps(payload) + "\n",
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert mcp.returncode == 0, mcp.stderr
    replay = json.loads(mcp.stdout)["result"]["structuredContent"]
    assert replay["duplicate"] and replay["result"] == first["result"]
    restricted = McpBridge(svc, allowed_scopes={"workspace.read"})
    names = {t["name"] for t in restricted.list_tools()}
    assert (
        tool_name("project.preview") in names
        and tool_name("project.start") not in names
    )


def test_launcher_uses_real_git_and_passes_its_own_source_to_python(tmp_path):
    stub = tmp_path / "python-stub"
    stub.write_text(
        "#!"
        + sys.executable
        + "\nimport json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'source':os.environ.get('PYTHONPATH')}))\n"
    )
    stub.chmod(0o700)
    run = subprocess.run(
        ["sh", str(ROOT / "Start Projektgedaechtnis Demo.command")],
        cwd=tmp_path,
        env={**os.environ, "THREADDESK_PYTHON": str(stub)},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["source"] == str(ROOT / "src")
    assert data["args"] == [
        str(ROOT / "scripts/demo_project_memory.py"),
        "--serve",
        "--open",
    ]


def test_large_preview_readback_pages_are_stable_without_writes(svc):
    app = CommandApplication(svc)
    req = {
        "version": 1,
        "workspace_id": app.workspace_id,
        "command": "project.preview",
        "arguments": {**IDEA, "idea": "🌊" * 10000},
    }
    response = app.call(req, read_only=True)
    assert "result_page" in response and response["next_offset"] is not None
    digest = response["result_digest"]
    chunks = [response["result_page"]]
    while response["next_offset"] is not None:
        response = app.call(
            {**req, "result_offset": response["next_offset"], "result_digest": digest},
            read_only=True,
        )
        chunks.append(response["result_page"])
    assert json.loads("".join(chunks))["idea"] == req["arguments"]["idea"]
    assert (
        not svc.list()
        and not svc.list_nodes()
        and not svc.store.list_management_operations()
    )
