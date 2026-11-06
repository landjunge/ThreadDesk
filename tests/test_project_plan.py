"""Auditable revisions, live knowledge binding and preserved project ownership."""

import copy
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from test_project_start import create
from test_project_start import svc as project_fixture

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.services import project_plan
from threaddesk.services.commands import CommandApplication
from threaddesk.services.knowledge_memory import manage, reentry
from threaddesk.services.mcp import McpBridge
from threaddesk.services.mcp_commands import tool_name
from threaddesk.services.project_memory import read
from threaddesk.services.thread_management import manage as organize
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

svc = project_fixture
ROOT = Path(__file__).resolve().parents[1]
INITIAL = {
    "goals": ["Use primary sources"],
    "next_steps": ["First", "Second"],
    "open_questions": ["Which archive?"],
}


def seed(svc, operation="initial"):
    return create(svc, operation=operation, plan=INITIAL)["result"]


def get(svc, started, **extra):
    return project_plan.get(
        svc,
        {
            "project_id": started["project_id"],
            "thread_id": started["thread_id"],
            **extra,
        },
    )


def request_for(svc, started, operation="revise-2", basis=None, plan=None):
    basis = basis or get(svc, started)
    return {
        "version": 1,
        "workspace_id": CommandApplication(svc).workspace_id,
        "command": "project.plan.revise",
        "operation_id": operation,
        "expected_revision": basis["thread_revision"],
        "arguments": {
            "project_id": started["project_id"],
            "thread_id": started["thread_id"],
            "expected_plan_revision": basis["plan_revision"],
            "expected_basis": basis["basis_digest"],
            "reason": "A new primary source changes the next step.",
            "source_ref": "synthetic:conversation:revision",
            "source_revision": "message-43",
            "plan": plan
            or {
                group: [item["title"] for item in basis["live_plan"][group]]
                for group in project_plan.GROUPS
            },
        },
    }


def accepted(svc, identity):
    for state in (
        "ready",
        "assigned",
        "in_progress",
        "delivered",
        "review",
        "accepted",
    ):
        node = svc.get_node(identity)
        svc.transition_node(identity, state, expected_revision=node.revision)


def test_revision_keeps_old_bytes_provenance_and_current_reentry(svc):
    active = svc.create("Other ongoing work")
    started = seed(svc)
    first = get(svc, started)
    old = copy.deepcopy(first["snapshot"])
    events = []
    svc.bus.on("*", lambda name, _: events.append(name))
    new = {**INITIAL, "next_steps": ["Second", "Third"]}
    req = request_for(svc, started, plan=new)
    response = CommandApplication(svc).call(req)
    assert (
        response["result"]["plan_revision"] == 2
        and not response["result"]["execution_started"]
    )
    current = get(svc, started)
    assert get(svc, started, revision=1)["snapshot"] == old
    assert current["snapshot"]["previous_digest"] == project_plan.digest(old)
    assert current["snapshot"]["source_revision"] == "message-43"
    assert current["current_reentry"]["next_step"] == "Second"
    assert svc.get_node(old["plan"]["next_steps"][0]["node_id"]).status == "superseded"
    assert (
        current["live_plan"]["next_steps"][0]["node_id"]
        == old["plan"]["next_steps"][1]["node_id"]
    )
    assert svc.current().id == active.id and "thread.switched" not in events
    assert not svc.store.list_issued_handoffs()
    accepted(svc, current["live_plan"]["next_steps"][0]["node_id"])
    latest = reentry(svc, {"id": started["thread_id"]})
    assert (
        latest["saved"]["next_step"] == "Second"
    )  # recorded checkpoint remains truthful
    assert latest["current_plan"]["next_step"] == "Third"
    row = read(svc, {"project_id": started["project_id"]})["threads"][0]
    assert row["current_plan"]["next_step"] == "Third"
    assert get(svc, started, revision=1)["snapshot"] == old


def test_confirmed_answered_accepted_items_are_reused_without_reopening(svc):
    started = seed(svc)
    basis = get(svc, started)
    goal = basis["live_plan"]["goals"][0]["node_id"]
    svc.transition_node(
        goal, "confirmed", expected_revision=svc.get_node(goal).revision
    )
    for item in basis["live_plan"]["next_steps"]:
        accepted(svc, item["node_id"])
    question = svc.get_node(basis["live_plan"]["open_questions"][0]["node_id"])
    manage(
        svc,
        {
            "operation_id": "answer",
            "id": started["thread_id"],
            "expected_revision": svc.get(started["thread_id"]).revision,
            "action": "resolve_question",
            "data": {
                "node_id": question.id,
                "expected_node_revision": question.revision,
                "text": "The primary archive.",
                "source_ref": "synthetic:answer",
                "source_revision": "answer-1",
            },
        },
    )
    count = len(svc.list_nodes())
    before = get(svc, started)
    CommandApplication(svc).call(request_for(svc, started, basis=before))
    after = get(svc, started)
    assert len(svc.list_nodes()) == count
    assert after["live_plan"] == before["live_plan"]
    assert (
        not after["current_reentry"]["next_node_id"]
        and after["current_reentry"]["next_step"] == ""
    )
    assert (
        svc.get_node(question.id).status == "done"
        and svc.get_node(goal).status == "confirmed"
    )


@pytest.mark.parametrize("mutation", ["transition", "additional_knowledge"])
def test_entire_knowledge_basis_changes_even_without_thread_revision(svc, mutation):
    started = seed(svc)
    basis = get(svc, started)
    if mutation == "transition":
        item = basis["live_plan"]["next_steps"][0]
        svc.transition_node(
            item["node_id"], "ready", expected_revision=item["node_revision"]
        )
    else:
        svc.create_node(
            "decision",
            "A separate decision",
            status="confirmed",
            metadata={"thread_id": started["thread_id"]},
        )
    assert svc.get(started["thread_id"]).revision == basis["thread_revision"]
    with pytest.raises(ManagementError) as stale:
        CommandApplication(svc).call(request_for(svc, started, basis=basis))
    assert stale.value.code == "plan_basis_conflict"
    assert get(svc, started)["plan_revision"] == 1


def test_thread_cas_operation_collision_and_restart_replay(svc):
    started = seed(svc)
    req = request_for(svc, started)
    response = CommandApplication(svc).call(req)
    reopened = ThreadService(type(svc.store)(svc.store.root))
    try:
        replay = CommandApplication(reopened).call(req)
        assert replay["duplicate"] and replay["result"] == response["result"]
        with pytest.raises(ManagementError) as collision:
            CommandApplication(reopened).call(
                {**req, "arguments": {**req["arguments"], "reason": "Different"}}
            )
        assert collision.value.code == "operation_conflict"
        with pytest.raises(ManagementError) as stale:
            CommandApplication(reopened).call(
                {**req, "operation_id": "another-operation"}
            )
        assert stale.value.code == "revision_conflict"
    finally:
        if hasattr(reopened.store, "connection"):
            reopened.store.connection.close()


def test_competing_separate_stores_commit_one_plan_revision(svc):
    started = seed(svc)
    basis = get(svc, started)
    root, backend = svc.store.root, type(svc.store)

    def worker(number):
        other = ThreadService(backend(root))
        try:
            try:
                return CommandApplication(other).call(
                    request_for(
                        other, started, operation=f"concurrent-{number}", basis=basis
                    )
                )
            except ManagementError as exc:
                return {"code": exc.code}
        finally:
            if hasattr(other.store, "connection"):
                other.store.connection.close()

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(worker, range(3)))
    assert sum("result" in r for r in results) == 1
    assert sum(r.get("code") == "revision_conflict" for r in results) == 2
    assert get(svc, started)["plan_revision"] == 2
    assert (
        project_plan._load(svc, started["project_id"], started["thread_id"], 3) is None
    )


def test_exact_project_binding_and_no_foreign_context_leak(svc):
    one, two = seed(svc, "one"), seed(svc, "two")
    with pytest.raises(ManagementError) as wrong:
        get(svc, {**one, "project_id": two["project_id"]})
    assert wrong.value.code == "scope_conflict"
    organize(
        svc,
        {
            "operation_id": "move-project",
            "action": "organize",
            "id": one["thread_id"],
            "expected_revision": svc.get(one["thread_id"]).revision,
            "data": {"project_id": two["project_id"]},
        },
    )
    for requested in (one, {**one, "project_id": two["project_id"]}):
        with pytest.raises(ManagementError) as denied:
            get(svc, requested)
        assert denied.value.code == "scope_conflict"
        assert "Use primary sources" not in str(denied.value)


def test_m2_observed_adoption_is_read_only_until_first_revision(svc, monkeypatch):
    with monkeypatch.context() as ctx:
        ctx.setattr(project_plan, "initialize", lambda *a: None)
        started = seed(svc)
    before_thread = svc.get(started["thread_id"]).to_dict()
    before_records = svc.store.list_management_operations()
    initial = get(svc, started)
    assert (
        initial["snapshot"]["origin"] == "observed_m2"
        and initial["snapshot"]["recorded_at"] is None
    )
    assert svc.get(started["thread_id"]).to_dict() == before_thread
    assert svc.store.list_management_operations() == before_records
    CommandApplication(svc).call(request_for(svc, started, basis=initial))
    old = get(svc, started, revision=1)["snapshot"]
    assert old["origin"] == "observed_m2" and old["recorded_at"]
    assert get(svc, started)["snapshot"]["previous_digest"] == project_plan.digest(old)


@pytest.mark.parametrize("head", [None, {"format": "future-plan-v9"}])
def test_unsupported_head_does_not_silently_reinitialize(svc, head):
    started = seed(svc)
    thread = svc.get(started["thread_id"])
    thread.context.extra["project_plan"] = head
    svc.store.save_thread(thread)
    with pytest.raises(ManagementError) as bad:
        get(svc, started)
    assert bad.value.code == "plan_state_conflict"


def test_snapshot_restore_retains_audit_and_rejects_rewound_head(svc):
    started = seed(svc)
    snapshot = svc.snapshot("Before plan change", started["thread_id"])
    CommandApplication(svc).call(request_for(svc, started))
    second = copy.deepcopy(
        project_plan._load(svc, started["project_id"], started["thread_id"], 2)
    )
    svc.restore(snapshot.id)
    with pytest.raises(ManagementError) as stale:
        get(svc, started)
    assert stale.value.code == "plan_state_conflict"
    assert (
        project_plan._load(svc, started["project_id"], started["thread_id"], 2)
        == second
    )
    assert (
        reentry(svc, {"id": started["thread_id"]})["current_plan"]["available"] is False
    )


def test_revision_failure_rolls_back_head_reentry_nodes_and_evidence(svc, monkeypatch):
    started = seed(svc)
    req = request_for(svc, started, plan={**INITIAL, "next_steps": ["New step"]})
    before = (
        svc.get(started["thread_id"]).to_dict(),
        [n.to_dict() for n in svc.list_nodes()],
        svc.store.list_management_operations(),
        [e.to_dict() for e in svc.list_graph_events()],
    )
    put = project_plan._put

    def interrupted(*args):
        put(*args)
        raise OSError("synthetic failure after staged revision evidence")

    monkeypatch.setattr(project_plan, "_put", interrupted)
    with pytest.raises(ManagementError) as error:
        CommandApplication(svc).call(req)
    assert error.value.code == "command_unconfirmed"
    assert (
        svc.get(started["thread_id"]).to_dict(),
        [n.to_dict() for n in svc.list_nodes()],
        svc.store.list_management_operations(),
        [e.to_dict() for e in svc.list_graph_events()],
    ) == before


def test_json_partial_commit_recovers_same_revision_and_receipt(tmp_path, monkeypatch):
    svc = ThreadService(JsonStore(tmp_path))
    started = seed(svc)
    req = request_for(
        svc, started, plan={**INITIAL, "next_steps": ["New pending step"]}
    )
    write = svc.store._atomic_json
    count = 0

    def crash(path, value):
        nonlocal count
        count += 1
        write(path, value)
        if count == 2:
            raise OSError("synthetic loss after journal and first payload")

    monkeypatch.setattr(svc.store, "_atomic_json", crash)
    with pytest.raises(ManagementError) as unknown:
        CommandApplication(svc).call(req)
    assert unknown.value.code == "invalid_state"
    recovered = ThreadService(JsonStore(tmp_path))
    receipt = CommandApplication(recovered).operation(req["operation_id"])
    assert receipt["state"] == "complete" and receipt["result"]["plan_revision"] == 2
    assert CommandApplication(recovered).call(req)["duplicate"]
    assert get(recovered, started)["current_reentry"]["next_step"] == "New pending step"
    assert get(recovered, started)["plan_revision"] == 2


def test_real_cli_revision_and_mcp_replay_use_same_receipt(svc):
    started = seed(svc)
    req = request_for(svc, started)
    env = {
        **os.environ,
        "THREADDESK_HOME": str(svc.store.root),
        "THREADDESK_STORAGE": "sqlite"
        if isinstance(svc.store, SQLiteStore)
        else "json",
        "PYTHONPATH": str(ROOT / "src"),
    }
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
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    expected = json.loads(cli.stdout)["result"]
    rpc = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name("project.plan.revise"),
            "arguments": {
                k: v for k, v in req.items() if k not in {"version", "command"}
            },
        },
    }
    proc = subprocess.run(
        [sys.executable, "-m", "threaddesk.ui.mcp_stdio"],
        env=env,
        input=json.dumps(rpc) + "\n",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    reply = json.loads(proc.stdout)["result"]["structuredContent"]
    assert reply["duplicate"] and reply["result"] == expected
    bridge = McpBridge(svc, allowed_scopes={"workspace.read"})
    names = {t["name"] for t in bridge.list_tools()}
    assert (
        tool_name("project.plan.get") in names
        and tool_name("project.plan.revise") not in names
    )


def test_rejected_task_is_pending_rework_not_a_closed_next_step(svc):
    started = seed(svc)
    item = get(svc, started)["live_plan"]["next_steps"][0]
    for state in (
        "ready",
        "assigned",
        "in_progress",
        "delivered",
        "review",
        "rejected",
    ):
        svc.transition_node(
            item["node_id"],
            state,
            expected_revision=svc.get_node(item["node_id"]).revision,
        )
    assert get(svc, started)["current_reentry"]["next_node_id"] == item["node_id"]
    assert (
        reentry(svc, {"id": started["thread_id"]})["current_plan"]["next_step"]
        == "First"
    )


def test_json_to_sqlite_migration_keeps_internal_evidence_keys(tmp_path):
    from threaddesk.storage.json_migration import migrate_json_store

    source = ThreadService(JsonStore(tmp_path / "source"))
    started = seed(source)
    CommandApplication(source).call(request_for(source, started))
    before = get(source, started)
    target = SQLiteStore(tmp_path / "target")
    try:
        migrate_json_store(source.store, target)
        assert get(ThreadService(target), started) == before
        assert target.get_management_operation(
            project_plan.key(started["thread_id"], 2)
        )["storage_operation_id"]
    finally:
        target.connection.close()


def test_plan_payload_copies_are_visible_to_existing_permanent_purge_guard(svc):
    from threaddesk.services.trash_receipts import receipt_plan

    started = seed(svc)
    public = receipt_plan(svc.store, "thread", started["thread_id"]).public
    assert any(
        item["storage_operation_id"] == project_plan.key(started["thread_id"], 1)
        for item in public["blockers"]
    )
    assert "Use primary sources" not in json.dumps(public)


def test_corrupt_history_record_is_rejected_without_replacement(svc, monkeypatch):
    started = seed(svc)
    read_record = svc.store.get_management_operation
    identity = project_plan.key(started["thread_id"], 1)
    original = copy.deepcopy(read_record(identity))

    def corrupted(key):
        result = copy.deepcopy(read_record(key))
        if key == identity:
            result["result"]["format"] = "future-version"
        return result

    monkeypatch.setattr(svc.store, "get_management_operation", corrupted)
    with pytest.raises(ManagementError) as bad:
        get(svc, started)
    assert bad.value.code == "plan_state_conflict"
    assert read_record(identity) == original


@pytest.mark.parametrize("payload", [[], "unsupported-record", 17, False])
def test_nonobject_stored_record_is_a_structured_conflict_after_restart(svc, payload):
    started = seed(svc)
    identity = project_plan.key(started["thread_id"], 1)
    before = svc.get(started["thread_id"]).to_dict()
    # Fault injection in this test's own temporary store, then a real reopen.
    with svc.store.transaction():
        if isinstance(svc.store, SQLiteStore):
            svc.store.connection.execute(
                "UPDATE management_operations SET payload=? WHERE id=?",
                (json.dumps(payload), identity),
            )
        else:
            svc.store.save_management_operation(identity, payload)
    reopened = ThreadService(type(svc.store)(svc.store.root))
    try:
        assert type(reopened.store.get_management_operation(identity)) is type(payload)
        with pytest.raises(ManagementError) as direct:
            get(reopened, started)
        assert direct.value.code == "plan_state_conflict"
        app = CommandApplication(reopened)
        with pytest.raises(ManagementError) as command:
            app.call(
                {
                    "version": 1,
                    "workspace_id": app.workspace_id,
                    "command": "project.plan.get",
                    "arguments": {
                        "project_id": started["project_id"],
                        "thread_id": started["thread_id"],
                    },
                },
                read_only=True,
            )
        assert command.value.code == "plan_state_conflict"
        unavailable = {"available": False, "code": "plan_state_conflict"}
        assert (
            reentry(reopened, {"id": started["thread_id"]})["current_plan"]
            == unavailable
        )
        assert (
            read(reopened, {"project_id": started["project_id"]})["threads"][0][
                "current_plan"
            ]
            == unavailable
        )
        assert reopened.store.get_management_operation(identity) == payload
        assert reopened.get(started["thread_id"]).to_dict() == before
    finally:
        if hasattr(reopened.store, "connection"):
            reopened.store.connection.close()


def test_large_plan_readback_pages_keep_one_snapshot_without_writes(svc):
    started = create(
        svc,
        operation="large",
        source_ref="source:" + "🌊" * 1000,
        plan={group: ["🌊" * 300] * 8 for group in project_plan.GROUPS},
    )["result"]
    app = CommandApplication(svc)
    before = svc.store.list_management_operations()
    req = {
        "version": 1,
        "workspace_id": app.workspace_id,
        "command": "project.plan.get",
        "arguments": {
            "project_id": started["project_id"],
            "thread_id": started["thread_id"],
        },
    }
    response = app.call(req, read_only=True)
    assert "result_page" in response
    digest, pieces = response["result_digest"], []
    while True:
        pieces.append(response["result_page"])
        if response["next_offset"] is None:
            break
        response = app.call(
            {**req, "result_offset": response["next_offset"], "result_digest": digest},
            read_only=True,
        )
    decoded = json.loads("".join(pieces))
    assert (
        decoded["plan_revision"] == 1
        and len(decoded["snapshot"]["plan"]["next_steps"]) == 8
    )
    assert svc.store.list_management_operations() == before


def test_malformed_m2_reentry_is_a_structured_conflict(svc, monkeypatch):
    with monkeypatch.context() as ctx:
        ctx.setattr(project_plan, "initialize", lambda *a: None)
        started = seed(svc)
    thread = svc.get(started["thread_id"])
    thread.context.extra["reentry"] = False
    svc.store.save_thread(thread)
    with pytest.raises(ManagementError) as error:
        get(svc, started)
    assert error.value.code == "plan_state_conflict"
    assert (
        reentry(svc, {"id": thread.id})["current_plan"]["code"] == "plan_state_conflict"
    )


def test_history_pages_require_a_stable_revision_head(svc):
    started = seed(svc)
    app = CommandApplication(svc)
    for number in range(2, 5):
        app.call(request_for(svc, started, operation=f"page-revision-{number}"))
    first = get(svc, started, limit=2)
    second = get(
        svc, started, limit=2, offset=2, expected_plan_revision=first["plan_revision"]
    )
    assert [i["revision"] for i in first["history"] + second["history"]] == [4, 3, 2, 1]
    app.call(request_for(svc, started, operation="later-revision"))
    with pytest.raises(ManagementError) as changed:
        get(svc, started, offset=2, expected_plan_revision=first["plan_revision"])
    assert changed.value.code == "plan_basis_conflict"
