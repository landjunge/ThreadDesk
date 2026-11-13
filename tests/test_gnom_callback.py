from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import InvalidState
from threaddesk.storage.json_store import JsonStore


def setup(tmp_path: Path):
    svc = ThreadService(store=JsonStore(tmp_path)); svc.create("Callback")
    packet = svc.gnom(); svc.bind_gnom_job("job-1", packet)
    return svc


def callback(status="started", event_id="e1", **extra):
    return {"format": "threaddesk.gnom-callback.v1", "event_id": event_id,
            "job_id": "job-1", "handoff_revision": 1, "status": status,
            "occurred_at": "2026-09-15T19:00:00+00:00", **extra}


def test_status_callback_updates_only_bound_job(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    result = svc.receive_gnom_callback(callback(details="Working"))
    assert result["job"]["status"] == "started"
    assert result["return"] is None
    assert svc.returns() == []


def test_delivered_callback_enters_unverified_inbox_idempotently(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    value = callback("delivered", result="Done", artifacts=["out.txt"],
                     test_results=["8 passed"], open_issues=[])
    first = svc.receive_gnom_callback(value)
    again = svc.receive_gnom_callback(value)
    assert first["return"]["return"]["review_status"] == "unverified"
    assert again["return"]["duplicate"] is True
    assert len(svc.returns()) == 1


def test_callback_rejects_unknown_fields_and_missing_delivery_result(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    with pytest.raises(InvalidState, match="fields"):
        svc.receive_gnom_callback(callback(admin=True))
    with pytest.raises(InvalidState, match="result"):
        svc.receive_gnom_callback(callback("delivered"))


def test_stale_revision_late_event_and_delivery_after_cancel_are_rejected(tmp_path: Path) -> None:
    svc = setup(tmp_path)
    with pytest.raises(InvalidState, match="stale_revision"):
        svc.receive_gnom_callback(callback(handoff_revision=2))
    svc.receive_gnom_callback(callback("started", event_id="e1", occurred_at="2026-09-15T19:02:00+00:00"))
    with pytest.raises(InvalidState, match="event_stale"):
        svc.receive_gnom_callback(callback("blocked", event_id="late", occurred_at="2026-09-15T19:01:00+00:00"))
    svc.receive_gnom_callback(callback("cancelled", event_id="cancel", occurred_at="2026-09-15T19:03:00+00:00"))
    with pytest.raises(InvalidState, match="job_terminal"):
        svc.receive_gnom_callback(callback("delivered", event_id="delivery", occurred_at="2026-09-15T19:04:00+00:00", result="Too late"))
    assert svc.returns() == []


@pytest.mark.parametrize("revision", [True, False, 0, -1, 1.0, "1", None])
def test_callback_rejects_non_integer_revision_without_effects(tmp_path: Path, revision) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Callback")
    svc.bind_gnom_job("job-1", svc.gnom())
    before = svc.whiteboard(thread.id)
    with pytest.raises(InvalidState, match="gnom_callback_revision"):
        svc.receive_gnom_callback(callback(handoff_revision=revision))
    job = svc.gnom_jobs()[0]
    assert job["events"] == [] and job["status"] is None
    assert svc.returns() == []
    assert svc.whiteboard(thread.id) == before


def test_true_delivered_revision_has_no_return_or_board_effect(tmp_path: Path) -> None:
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Callback")
    svc.bind_gnom_job("job-1", svc.gnom())
    before = svc.whiteboard(thread.id)
    with pytest.raises(InvalidState, match="gnom_callback_revision"):
        svc.receive_gnom_callback(callback("delivered", result="Done", handoff_revision=True))
    assert svc.gnom_jobs()[0]["events"] == []
    assert svc.returns() == []
    assert svc.whiteboard(thread.id) == before
