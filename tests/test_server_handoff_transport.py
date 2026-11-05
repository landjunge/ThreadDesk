"""Opt-in transport, real core receipts and tenant/project boundaries; no agents."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from threaddesk.server_sync.app import create_app
from threaddesk.server_sync.auth import provision
from threaddesk.server_sync.handoffs import subject_ref


@pytest.fixture
def server(tmp_path):
    data = tmp_path / "server"
    tokens = {user: provision(data, user) for user in ("alice", "bob")}
    with TestClient(
        create_app(data, public_origin="https://testserver", handoff_rpc=True),
        base_url="https://testserver",
    ) as http:
        headers = {"Authorization": "Bearer " + tokens["alice"]}
        projects = [
            http.post("/api/projects", headers=headers, json={"title": title}).json()[
                "id"
            ]
            for title in ("First", "Second")
        ]
        yield data, tokens, http, headers, projects


def rpc(http, headers, pid, tool, arguments, *, status=200):
    response = http.post(
        f"/api/projects/{pid}/handoff",
        headers=headers,
        json={"tool": tool, "arguments": arguments},
    )
    assert response.status_code == status, response.text
    return response.json()


def issue(http, headers, pid, operation="issue-first"):
    thread = http.get(f"/api/projects/{pid}/thread", headers=headers).json()
    value = rpc(
        http,
        headers,
        pid,
        "issue_handoff",
        {
            "operation_id": operation,
            "id": pid,
            "expected_revision": thread["revision"],
            "target": "codex",
        },
    )["call"]
    assert value["ok"], value
    return value["result"]


def binding(packet, task="fixture-task"):
    return {
        "handoff_id": packet["handoff_id"],
        "handoff_revision": packet["revision"],
        "task_id": packet["task_id"],
        "bridge_task_id": task,
        "run_id": "f0100000-0000-4000-8000-000000000001",
        "worker": "codex",
        "expected_thread_revision": packet["source"]["thread_revision"],
        "principal_ref": "1" * 64,
        "operator_scope": "2" * 64,
        "request_hash": "3" * 64,
    }


def returned(packet):
    return {
        "format": "threaddesk.return.v1",
        "return_id": "ret-fixture",
        "handoff_id": packet["handoff_id"],
        "handoff_revision": packet["revision"],
        "thread_id": packet["thread_id"],
        "task_id": packet["task_id"],
        "worker": "codex",
        "run_id": binding(packet)["run_id"],
        "result": "Synthetic owned result",
        "files": [],
        "pull_request": None,
        "test_results": [],
        "open_issues": [],
        "delivery_status": "delivered",
        "review_status": "unverified",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def test_capability_scope_and_default_disabled(server):
    data, tokens, http, headers, (pid, _) = server
    value = http.get(f"/api/projects/{pid}/handoff", headers=headers).json()
    assert value["subject_ref"] == subject_ref("alice", pid)
    assert value["executes_agents"] is False
    assert http.get(f"/api/projects/{pid}/handoff").status_code == 401
    assert (
        http.get(
            f"/api/projects/{pid}/handoff",
            headers={"Authorization": "Bearer " + tokens["bob"]},
        ).status_code
        == 404
    )


def test_feature_is_not_registered_in_default_server(tmp_path):
    data = tmp_path / "default"
    token = provision(data, "alice")
    with TestClient(
        create_app(data, public_origin="https://testserver"),
        base_url="https://testserver",
    ) as http:
        headers = {"Authorization": "Bearer " + token}
        pid = http.post(
            "/api/projects", headers=headers, json={"title": "Private"}
        ).json()["id"]
        assert (
            http.get(f"/api/projects/{pid}/handoff", headers=headers).status_code == 404
        )


def test_existing_issue_binding_import_readback_and_no_remote_self_review(server):
    _, tokens, http, headers, (pid, _) = server
    packet = issue(http, headers, pid)
    lookup = rpc(
        http, headers, pid, "get_issued_handoff", {"handoff_id": packet["handoff_id"]}
    )
    assert lookup["call"]["result"]["issued"]["content_hash"] == packet["content_hash"]
    run = binding(packet)
    assert (
        rpc(http, headers, pid, "bind_handoff_run", run)["call"]["result"]["binding"]
        == run
    )
    payload = returned(packet)
    result = rpc(
        http,
        headers,
        pid,
        "import_return",
        {"payload": payload, "strict_binding": True},
    )
    assert result["call"]["ok"], result
    assert result["call"]["result"]["binding_status"] == "issued_bound"
    assert result["call"]["result"]["decision"] is None
    assert rpc(
        http,
        headers,
        pid,
        "import_return",
        {"payload": payload, "strict_binding": True},
    )["call"]["result"]["duplicate"]
    rpc(
        http,
        headers,
        pid,
        "review_return",
        {
            "return_id": payload["return_id"],
            "choice": "accepted",
            "note": "not a worker decision",
        },
        status=403,
    )
    login = http.post("/auth/login", json={"token": tokens["alice"]}).json()
    csrf = {"X-ThreadDesk-CSRF": login["csrf"]}
    rpc(
        http,
        csrf,
        pid,
        "review_return",
        {
            "return_id": payload["return_id"],
            "choice": "accepted",
            "note": "Synthetic operator test",
        },
        status=403,
    )
    rpc(
        http,
        csrf,
        pid,
        "answer_handoff_question",
        {"handoff_id": packet["handoff_id"], "question_id": "owned", "text": "No"},
        status=403,
    )
    stored = rpc(http, headers, pid, "get_return", {"return_id": payload["return_id"]})
    assert stored["call"]["result"]["item"]["decision"] is None
    board = http.get(f"/api/projects/{pid}/whiteboard", headers=headers).json()[
        "entries"
    ]
    assert any("Synthetic owned result" in entry["content"] for entry in board)


def test_cross_project_and_duplicate_operation_do_not_leak_or_mutate(server):
    _, _, http, headers, (first, second) = server
    packet = issue(http, headers, first)
    rpc(
        http,
        headers,
        second,
        "get_issued_handoff",
        {"handoff_id": packet["handoff_id"]},
        status=404,
    )
    rpc(
        http,
        headers,
        second,
        "get_issued_handoff",
        {"operation_id": "issue-first"},
        status=404,
    )
    revision = http.get(f"/api/projects/{second}/thread", headers=headers).json()[
        "revision"
    ]
    rpc(
        http,
        headers,
        second,
        "issue_handoff",
        {"operation_id": "issue-first", "id": second, "expected_revision": revision},
        status=404,
    )
    rpc(http, headers, second, "bind_handoff_run", binding(packet), status=404)
    payload = returned(packet)
    payload["thread_id"] = second
    rpc(
        http,
        headers,
        second,
        "import_return",
        {"payload": payload, "strict_binding": True},
        status=404,
    )
    assert not http.get(f"/api/projects/{second}/whiteboard", headers=headers).json()[
        "entries"
    ]


@pytest.mark.parametrize(
    "tool,args",
    [
        ("agent.execute", {}),
        ({}, {}),
        ("get_issued_handoff", []),
        ("get_issued_handoff", {"handoff_id": "x", "operation_id": "y"}),
        ("import_return", {"payload": {}, "strict_binding": False}),
    ],
)
def test_unknown_calls_and_unbound_return_are_rejected(server, tool, args):
    _, _, http, headers, (pid, _) = server
    rpc(http, headers, pid, tool, args, status=400)


def test_delivery_marker_preserves_source_revision_and_cannot_rebind(server):
    _, _, http, headers, (pid, _) = server
    packet = issue(http, headers, pid)
    before = http.get(f"/api/projects/{pid}/thread", headers=headers).json()["revision"]
    marker = {
        "handoff_id": packet["handoff_id"],
        "core_task_id": "fixture-task",
        "device_ref": "fixture-device",
        "operator_scope": "2" * 64,
        "principal_ref": "1" * 64,
        "request_sha256": "4" * 64,
        "envelope_sha256": "5" * 64,
    }
    first = rpc(http, headers, pid, "reserve_handoff_delivery", marker)
    assert not first["call"]["result"]["duplicate"]
    assert rpc(http, headers, pid, "reserve_handoff_delivery", marker)["call"][
        "result"
    ]["duplicate"]
    assert (
        http.get(f"/api/projects/{pid}/thread", headers=headers).json()["revision"]
        == before
    )
    rpc(
        http,
        headers,
        pid,
        "reserve_handoff_delivery",
        {**marker, "core_task_id": "different"},
        status=409,
    )
    wrong = rpc(http, headers, pid, "bind_handoff_run", binding(packet, "different"))
    assert wrong["call"]["ok"] is False
    assert rpc(http, headers, pid, "bind_handoff_run", binding(packet))["call"]["ok"]
