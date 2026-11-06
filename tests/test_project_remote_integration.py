"""Existing project plans and opt-in handoffs share a core without dispatching work."""

import copy

import pytest
from fastapi.testclient import TestClient
from test_project_plan import get, request_for, seed
from test_server_handoff_transport import binding, issue, returned, rpc

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import Credentials, provision
from threaddesk.server_sync.store import SyncStore
from threaddesk.services.commands import CommandApplication
from threaddesk.services.knowledge_memory import reentry
from threaddesk.storage.json_store import JsonStore


@pytest.fixture
def shared_project(tmp_path):
    data = tmp_path / "server"
    tokens = {user: provision(data, user) for user in ("alice", "bob")}
    tenant = Credentials(data).user_root("alice")
    core = ThreadService(JsonStore(tenant / "core"))
    core.gate_set(cooldown_seconds=0)
    active = core.create("Unrelated active work")
    started = seed(core)
    # Explicit test setup through the existing SyncStore contract. Project.start
    # neither publishes a server project nor supplies execution authorization.
    sync = SyncStore(tenant / "sync")
    assert sync.projects() == []
    sync.create_project("Owned plan thread", project_id=started["thread_id"])
    with TestClient(
        create_app(data, public_origin="https://testserver", handoff_rpc=True),
        base_url="https://testserver",
    ) as http:
        yield core, started, active.id, http, tokens


def marker(packet):
    return {
        "handoff_id": packet["handoff_id"],
        "core_task_id": "fixture-task",
        "device_ref": "fixture-device",
        "operator_scope": "2" * 64,
        "principal_ref": "1" * 64,
        "request_sha256": "4" * 64,
        "envelope_sha256": "5" * 64,
    }


def test_project_and_remote_identifiers_scopes_and_commands_remain_distinct(
    shared_project,
):
    core, started, active, http, tokens = shared_project
    headers = {"Authorization": "Bearer " + tokens["alice"]}
    pid = started["thread_id"]
    assert pid != started["project_id"]
    capabilities = http.get(f"/api/projects/{pid}/handoff", headers=headers).json()
    assert capabilities["executes_agents"] is False
    assert "issue_handoff" in capabilities["tools"]
    assert (
        http.get(
            f"/api/projects/{started['project_id']}/handoff", headers=headers
        ).status_code
        == 404
    )
    assert (
        http.get(
            f"/api/projects/{pid}/handoff",
            headers={"Authorization": "Bearer " + tokens["bob"]},
        ).status_code
        == 404
    )
    rpc(http, headers, pid, "project.plan.revise", {}, status=400)
    assert get(core, started)["plan_revision"] == 1
    assert reentry(core, {"id": pid})["current_plan"]["plan_revision"] == 1
    assert core.current().id == active


def test_plan_revision_invalidates_old_remote_source_and_fresh_handoff_preserves_plan(
    shared_project,
):
    core, started, active, http, tokens = shared_project
    headers = {"Authorization": "Bearer " + tokens["alice"]}
    pid = started["thread_id"]
    first_plan = copy.deepcopy(get(core, started)["snapshot"])
    old = issue(http, headers, pid, operation="before-revision")
    assert old["sent"] is old["ran"] is False
    assert old["context"]["knowledge"]["provenance"] == "source_local"
    old_receipt = copy.deepcopy(core.store.get_issued_handoff(old["handoff_id"]))
    req = request_for(
        core,
        started,
        plan={
            "goals": ["Use primary sources"],
            "next_steps": ["New source first"],
            "open_questions": ["Which archive?"],
        },
    )
    CommandApplication(core).call(req)
    stale = rpc(http, headers, pid, "bind_handoff_run", binding(old))["call"]
    assert not stale["ok"] and stale["code"] == "revision_conflict"
    assert core.store.get_issued_handoff(old["handoff_id"]) == old_receipt
    assert get(core, started, revision=1)["snapshot"] == first_plan

    fresh = issue(http, headers, pid, operation="after-revision")
    assert "New source first" in {
        item["title"] for item in fresh["context"]["knowledge"]["items"]
    }
    basis = get(core, started)
    delivery = marker(fresh)
    assert not rpc(http, headers, pid, "reserve_handoff_delivery", delivery)["call"][
        "result"
    ]["duplicate"]
    assert rpc(http, headers, pid, "reserve_handoff_delivery", delivery)["call"][
        "result"
    ]["duplicate"]
    # Reserving delivery is metadata only: no plan/thread CAS or current basis drift.
    assert get(core, started)["basis_digest"] == basis["basis_digest"]
    assert rpc(http, headers, pid, "bind_handoff_run", binding(fresh))["call"]["ok"]
    payload = returned(fresh)
    imported = rpc(
        http,
        headers,
        pid,
        "import_return",
        {"payload": payload, "strict_binding": True},
    )["call"]
    assert imported["ok"] and imported["result"]["decision"] is None
    assert (
        rpc(http, headers, pid, "get_return", {"return_id": payload["return_id"]})[
            "call"
        ]["result"]["item"]["decision"]
        is None
    )
    rpc(
        http,
        headers,
        pid,
        "review_return",
        {
            "return_id": payload["return_id"],
            "choice": "accepted",
            "note": "Not authorized",
        },
        status=403,
    )
    current = get(core, started)
    assert current["plan_revision"] == 2
    assert current["current_reentry"]["next_step"] == "New source first"
    assert current["snapshot"] == basis["snapshot"]
    assert get(core, started, revision=1)["snapshot"] == first_plan
    assert core.current().id == active


def test_remote_return_and_plan_write_both_reject_direct_knowledge_drift(
    shared_project,
):
    core, started, active, http, tokens = shared_project
    headers = {"Authorization": "Bearer " + tokens["alice"]}
    pid = started["thread_id"]
    old_request = request_for(core, started)
    before = get(core, started)
    packet = issue(http, headers, pid)
    assert rpc(http, headers, pid, "bind_handoff_run", binding(packet))["call"]["ok"]
    node = core.get_node(before["live_plan"]["next_steps"][0]["node_id"])
    core.transition_node(node.id, "ready", expected_revision=node.revision)
    assert core.get(pid).revision == before["thread_revision"]
    stale = rpc(
        http,
        headers,
        pid,
        "import_return",
        {"payload": returned(packet), "strict_binding": True},
    )["call"]
    assert not stale["ok"] and stale["code"] == "return_stale"
    with pytest.raises(ManagementError) as conflict:
        CommandApplication(core).call(old_request)
    assert conflict.value.code == "plan_basis_conflict"
    current = get(core, started)
    assert current["plan_revision"] == 1
    assert current["snapshot"] == before["snapshot"]
    assert current["live_plan"]["next_steps"][0]["status"] == "ready"
    assert core.returns() == [] and core.current().id == active
