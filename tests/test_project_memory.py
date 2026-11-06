"""A project is explicit membership, not a graph walk or an execution grant."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services.commands import CommandApplication
from threaddesk.services.commands.validation import encode
from threaddesk.services.mcp import McpBridge
from threaddesk.services.mcp_commands import tool_name
from threaddesk.services.project_memory import MAX_PAGE_BYTES, read
from threaddesk.services.thread_management import manage
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.mcp_stdio import handle


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path):
    service = ThreadService(request.param(tmp_path / "workspace"))
    yield service
    if hasattr(service.store, "connection"):
        service.store.connection.close()


def assign(svc, project, title):
    created = manage(
        svc,
        {
            "operation_id": "new-" + title.replace(" ", "-"),
            "action": "create",
            "expected_revision": 0,
            "data": {"title": title, "project_id": project.id},
        },
    )
    return svc.store.get_thread(created["thread_id"])


def remember(svc, thread, operation, action="record", **data):
    response = McpBridge(svc).call(
        "knowledge_manage",
        {
            "id": thread.id,
            "expected_revision": svc.get(thread.id).revision,
            "operation_id": operation,
            "action": action,
            "data": {
                "source_ref": "synthetic:user:idea",
                "source_revision": "message-1",
                **data,
            },
        },
    )
    assert response["ok"], response
    return response["result"]


def invoke(svc, **arguments):
    bridge = McpBridge(svc, allowed_scopes={"workspace.read"})
    result = bridge.call(
        tool_name("project.memory"),
        {
            "workspace_id": bridge.commands.application.workspace_id,
            "arguments": arguments,
        },
    )
    assert result["ok"], result
    assert "result" in result["result"], result
    return result["result"]["result"]


def test_resume_two_projects_without_related_or_parent_leakage(svc):
    book = svc.create_node("project", "Berlin-Buch (synthetic)")
    radio = svc.create_node("project", "Buschradio (synthetic)")
    research = assign(svc, book, "book-research")
    recording = assign(svc, radio, "radio-recording")
    unassigned = svc.create("foreign-related-child")
    manage(
        svc,
        {
            "operation_id": "relate",
            "action": "organize",
            "id": research.id,
            "expected_revision": research.revision,
            "data": {"related_thread_ids": [recording.id]},
        },
    )
    manage(
        svc,
        {
            "operation_id": "parent",
            "action": "organize",
            "id": unassigned.id,
            "expected_revision": unassigned.revision,
            "data": {"parent_thread_id": research.id},
        },
    )
    remember(
        svc,
        recording,
        "foreign",
        kind="decision",
        status="confirmed",
        title="PRIVATE-RADIO",
    )
    remember(
        svc,
        research,
        "decision",
        kind="decision",
        status="confirmed",
        title="Cite local sources",
    )
    remember(svc, research, "question", kind="question", title="Which archive?")
    remember(svc, research, "task", kind="task", title="Compare two source lists")
    remember(
        svc,
        research,
        "resume",
        "save_reentry",
        summary="Sources gathered",
        next_step="Verify citations",
    )
    svc.append_whiteboard(
        research.id,
        actor="Agent",
        actor_type="codex",
        entry_type="result",
        content="Claimed result requires verification",
    )
    result = invoke(svc, project_id=book.id)
    assert result["total_threads"] == 1
    item = result["threads"][0]
    assert item["id"] == research.id
    assert item["saved_reentry"]["next_step"] == "Verify citations"
    assert {node["status"] for node in item["knowledge"]["items"]} == {
        "confirmed",
        "waiting",
        "ready",
    }
    assert all(
        node["source_verification"] == "referenced_unverified"
        for node in item["knowledge"]["items"]
    )
    assert item["whiteboard"]["items"][0]["evidence"] == "reported_unverified"
    text = encode(result)
    assert all(
        foreign not in text
        for foreign in ("PRIVATE-RADIO", recording.id, unassigned.id, radio.id)
    )
    assert "No work has been started" in result["instruction"]
    other = invoke(svc, project_id=radio.id)
    assert other["total_threads"] == 1
    assert "Cite local sources" not in encode(other)


def test_read_is_stable_after_reopen_and_has_no_domain_effects(svc, monkeypatch):
    project = svc.create_node("project", "Remembered")
    thread = assign(svc, project, "remembered-thread")
    remember(
        svc, thread, "saved", "save_reentry", summary="Checkpoint", next_step="Continue"
    )
    current = svc.current().id
    before = {
        "threads": [t.to_dict() for t in svc.list(True)],
        "nodes": [n.to_dict() for n in svc.list_nodes()],
        "receipts": svc.store.list_management_operations(),
        "handoffs": svc.store.list_issued_handoffs(),
    }
    events = []
    svc.bus.on("*", lambda name, payload: events.append(name))
    import threaddesk.services.library_refresh as refresh

    monkeypatch.setattr(
        refresh, "refresh_existing", lambda *a: pytest.fail("read refreshed index")
    )
    first = invoke(svc, project_id=project.id)
    assert events == [] and svc.current().id == current
    assert [t.to_dict() for t in svc.list(True)] == before["threads"]
    assert [n.to_dict() for n in svc.list_nodes()] == before["nodes"]
    assert svc.store.list_management_operations() == before["receipts"]
    assert svc.store.list_issued_handoffs() == before["handoffs"]
    reopened = ThreadService(type(svc.store)(svc.store.root))
    try:
        assert invoke(reopened, project_id=project.id) == first
    finally:
        if hasattr(reopened.store, "connection"):
            reopened.store.connection.close()
    with svc.store.transaction():
        assert read(svc, {"project_id": project.id}) == first


def test_explicit_archives_and_trash_do_not_reappear(svc):
    project = svc.create_node("project", "Lifecycle")
    active = assign(svc, project, "active")
    archived = assign(svc, project, "archived")
    deleted = assign(svc, project, "trashed")
    node = remember(
        svc,
        active,
        "trash-node",
        kind="decision",
        status="confirmed",
        title="REMOVED-KNOWLEDGE",
    )["node"]
    svc.archive(archived.id)
    trash = TrashService(svc.store)
    trash.move(
        kind="thread",
        object_id=deleted.id,
        expected_revision=deleted.revision,
        operation_id="trash-thread",
    )
    trash.move(
        kind="node",
        object_id=node["id"],
        expected_revision=node["revision"],
        operation_id="trash-knowledge",
    )
    ordinary = invoke(svc, project_id=project.id)
    assert {row["id"] for row in ordinary["threads"]} == {active.id}
    explicit = invoke(svc, project_id=project.id, include_archived=True)
    assert {row["id"] for row in explicit["threads"]} == {active.id, archived.id}
    assert "REMOVED-KNOWLEDGE" not in encode(explicit)
    assert explicit["snapshot"] != ordinary["snapshot"]


@pytest.mark.parametrize(
    "change", ["membership", "knowledge", "whiteboard", "note", "project"]
)
def test_pagination_rejects_changes_even_outside_selected_page(svc, change):
    project = svc.create_node("project", "Paged")
    for name in ("paged-first", "paged-second"):
        assign(svc, project, name)
    first = invoke(svc, project_id=project.id, limit=1)
    omitted = next(t for t in svc.list() if t.id != first["threads"][0]["id"])
    following = invoke(
        svc,
        project_id=project.id,
        limit=1,
        offset=1,
        expected_snapshot=first["snapshot"],
    )
    assert following["threads"][0]["id"] == omitted.id
    assert first["truncated"] and following["next_offset"] is None
    if change == "membership":
        assign(svc, project, "paged-new")
    elif change == "knowledge":
        remember(svc, omitted, "changed", kind="question", title="New question")
    elif change == "whiteboard":
        svc.append_whiteboard(
            omitted.id,
            actor="Codex",
            actor_type="codex",
            entry_type="problem",
            content="Blocked",
        )
    elif change == "note":
        svc.set_note("Changed after first page", omitted.id)
    else:
        project.details = "Project description changed"
        svc.store.save_node(project)
    with pytest.raises(ManagementError, match="Project changed") as error:
        read(
            svc,
            {
                "project_id": project.id,
                "offset": 1,
                "expected_snapshot": first["snapshot"],
            },
        )
    assert error.value.code == "snapshot_conflict"


def test_bounded_unicode_and_control_text_counts_omissions(svc):
    project = svc.create_node("project", "Budget")
    for number in range(4):
        thread = assign(svc, project, f"large-{number}")
        svc.set_note("\x01🌊" * 3000, thread.id)
        for i in range(12):
            svc.create_node(
                "task",
                "🌊" * 2000,
                status="ready",
                details="\x01" * 5000,
                source="synthetic/source",
                metadata={"thread_id": thread.id},
            )
        for i in range(5):
            svc.append_whiteboard(
                thread.id,
                actor="Codex",
                actor_type="codex",
                entry_type="result",
                content="🌊" * 1500,
            )
    first = invoke(svc, project_id=project.id, limit=10)
    assert first["total_threads"] == 4 and first["truncated"]
    assert len(encode(first).encode()) <= MAX_PAGE_BYTES
    ids = []
    page = first
    while True:
        assert len(encode(page).encode()) <= MAX_PAGE_BYTES
        for row in page["threads"]:
            ids.append(row["id"])
            assert row["knowledge"]["total"] == 12 and row["knowledge"]["truncated"]
            assert row["knowledge_counts"] == [
                {"kind": "task", "status": "ready", "total": 12}
            ]
            assert row["whiteboard"]["total"] == 5 and row["whiteboard"]["truncated"]
        if page["next_offset"] is None:
            break
        page = invoke(
            svc,
            project_id=project.id,
            limit=10,
            offset=page["next_offset"],
            expected_snapshot=first["snapshot"],
        )
    assert len(ids) == len(set(ids)) == 4


def test_missing_project_empty_project_and_strict_arguments(svc):
    project = svc.create_node("project", "Empty")
    assert invoke(svc, project_id=project.id)["threads"] == []
    for args in (
        {},
        {"project_id": "../outside"},
        {"project_id": project.id, "limit": True},
        {"project_id": project.id, "include_archived": "false"},
        {"project_id": project.id, "offset": 1},
        {"project_id": project.id, "execute": True},
    ):
        with pytest.raises(ManagementError) as error:
            read(svc, args)
        assert error.value.code == "validation_error"
    with pytest.raises(ManagementError) as error:
        read(svc, {"project_id": "missing"})
    assert error.value.code == "not_found"
    node = svc.create_node("task", "Wrong kind")
    with pytest.raises(ManagementError) as error:
        read(svc, {"project_id": node.id})
    assert error.value.code == "invalid_state"


def test_generic_graph_metadata_is_not_trusted_as_a_kind_object(svc):
    project = svc.create_node("project", "Imported metadata")
    thread = assign(svc, project, "imported-thread")
    for value in ({"nested": "untrusted"}, ["question"], None, "x" * 10000):
        svc.create_node(
            "task",
            "Imported task",
            status="ready",
            metadata={"thread_id": thread.id, "knowledge_type": value},
        )
    result = invoke(svc, project_id=project.id)["threads"][0]
    assert result["knowledge_counts"] == [
        {"kind": "task", "status": "ready", "total": 4}
    ]
    assert all(row["knowledge_type"] == "task" for row in result["knowledge"]["items"])


def test_http_and_real_cli_use_the_same_project_memory(svc, monkeypatch):
    from http_ui_client import UIClient

    from threaddesk.ui.server import create_app

    project = svc.create_node("project", "HTTP and CLI")
    assign(svc, project, "transport-thread")
    monkeypatch.setenv("THREADDESK_HOME", str(svc.store.root))
    monkeypatch.setenv(
        "THREADDESK_STORAGE", "sqlite" if isinstance(svc.store, SQLiteStore) else "json"
    )
    request = {
        "version": 1,
        "workspace_id": CommandApplication(svc).workspace_id,
        "command": "project.memory",
        "arguments": {"project_id": project.id},
    }
    expected = invoke(svc, project_id=project.id)
    with UIClient(create_app()) as client:
        response = client.post("/api/commands", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["result"] == expected
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "threaddesk.ui.cli",
            "command",
            "--request",
            json.dumps(request),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr + cli.stdout
    assert json.loads(cli.stdout)["result"] == expected
    rpc = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name("project.memory"),
                "arguments": {
                    "workspace_id": request["workspace_id"],
                    "arguments": request["arguments"],
                },
            },
        },
    ]
    stdio = subprocess.run(
        [sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
        env=env,
        input="".join(json.dumps(row) + "\n" for row in rpc),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert stdio.returncode == 0, stdio.stderr
    replies = {
        row["id"]: row
        for line in stdio.stdout.splitlines()
        if (row := json.loads(line)).get("id") is not None
    }
    assert any(
        t["name"] == tool_name("project.memory") for t in replies[2]["result"]["tools"]
    )
    assert replies[3]["result"]["structuredContent"]["result"] == expected


def test_scoped_catalog_and_actual_jsonrpc_share_one_command(svc):
    project = svc.create_node("project", "MCP")
    bridge = McpBridge(svc, allowed_scopes={"workspace.read"})
    tools = handle(bridge, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
        "result"
    ]["tools"]
    tool = next(t for t in tools if t["name"] == tool_name("project.memory"))
    assert tool["annotations"]["readOnlyHint"]
    assert tool["_meta"]["threaddesk"]["scope"] == "workspace.read"
    result = handle(
        bridge,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool["name"],
                "arguments": {
                    "workspace_id": tool["_meta"]["threaddesk"]["workspace_id"],
                    "arguments": {"project_id": project.id},
                },
            },
        },
    )["result"]
    assert not result["isError"]
    assert result["structuredContent"]["result"]["project_id"] == project.id
    unavailable = McpBridge(svc, allowed_scopes={"workspace.write"})
    assert tool["name"] not in {t["name"] for t in unavailable.list_tools()}
    assert (
        unavailable.call(
            tool["name"],
            {
                "workspace_id": tool["_meta"]["threaddesk"]["workspace_id"],
                "arguments": {"project_id": project.id},
            },
        )["code"]
        == "permission_required"
    )


def test_project_page_escapes_content_and_preserves_active_thread(svc, monkeypatch):
    from http_ui_client import UIClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(svc.store.root))
    monkeypatch.setenv(
        "THREADDESK_STORAGE", "sqlite" if isinstance(svc.store, SQLiteStore) else "json"
    )
    project = svc.create_node("project", "Project <script>bad()</script>")
    threads = [assign(svc, project, f"view-thread-{i}") for i in range(4)]
    svc.set_note("<script>alert('note')</script>", threads[0].id)
    remember(
        svc,
        threads[0],
        "view-reentry",
        "save_reentry",
        summary="Saved view",
        next_step="Read evidence",
    )
    current = svc.current().id
    with UIClient(create_app()) as client:
        page = client.get("/projects", params={"project_id": project.id, "lang": "en"})
        assert page.status_code == 200, page.text
        assert (
            "Project memory" in page.text
            and "Project &lt;script&gt;bad()&lt;/script&gt;" in page.text
        )
        assert (
            "<script>bad()" not in page.text
            and "<script>alert('note')" not in page.text
        )
        assert "data-project-next" in page.text
        snapshot = read(svc, {"project_id": project.id})["snapshot"]
        svc.set_note("Changed context", threads[1].id)
        conflict = client.get(
            "/projects",
            params={
                "project_id": project.id,
                "offset": 3,
                "expected_snapshot": snapshot,
                "lang": "en",
            },
        )
        assert conflict.status_code == 409
        assert "The project has changed" in conflict.text
    assert svc.current().id == current


def test_project_page_empty_and_failure_states(svc, monkeypatch):
    from http_ui_client import UIClient

    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(svc.store.root))
    monkeypatch.setenv(
        "THREADDESK_STORAGE", "sqlite" if isinstance(svc.store, SQLiteStore) else "json"
    )
    with UIClient(create_app()) as client:
        assert "No projects yet" in client.get("/projects?lang=en").text
        project = svc.create_node("project", "No assigned threads")
        assert (
            "No threads have been explicitly assigned"
            in client.get(f"/projects?lang=en&project_id={project.id}").text
        )
        failure = client.get("/projects?lang=en&project_id=missing")
        assert failure.status_code == 400 and "cannot be displayed" in failure.text
