"""Graph projection parity and no-payload-scan guarantee (AP: TD-GRAPH-FIX).

The graph projection must be identical for the file store and the SQLite store,
and must not read/parse whiteboard entry payloads. It needs only the thread
state plus the entry count.
"""
from __future__ import annotations

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode, Thread, ThreadContext, WhiteboardEntry
from threaddesk.services.whiteboard_lifecycle import WhiteboardService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

STORES = [JsonStore, SQLiteStore]


def _service(store) -> ThreadService:
    return ThreadService(store=store)


def _thread(store, thread_id: str, *, status: str = "idea", extra: dict | None = None) -> None:
    store.save_thread(
        Thread(
            id=thread_id,
            title=f"Thread {thread_id}",
            status=status,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            context=ThreadContext(extra=extra or {}),
        )
    )


def _entry(store, thread_id: str, ordinal: int) -> None:
    store.append_whiteboard_entry(
        WhiteboardEntry(
            id=f"{thread_id}-e{ordinal:04d}",
            thread_id=thread_id,
            actor="synthetic",
            actor_type="human",
            created_at=f"2026-01-01T00:00:{ordinal:02d}Z",
            entry_type="note",
            content="x",
            ordinal=ordinal,
            metadata={},
        )
    )


def _projection(store) -> list[tuple]:
    nodes = WhiteboardService(_service(store)).graph_nodes()
    return sorted(
        (
            node.id,
            node.kind,
            node.status,
            node.metadata.get("entry_count"),
            node.metadata.get("whiteboard_state"),
            node.metadata.get("whiteboard_status"),
        )
        for node in nodes
    )


def _build_scenario(store) -> None:
    _thread(store, "empty")
    _thread(store, "with-entries")
    _entry(store, "with-entries", 0)
    _entry(store, "with-entries", 1)
    _thread(store, "closed")
    _entry(store, "closed", 0)
    thread = store.get_thread("closed")
    thread.context.extra = {"whiteboard": {"version": 1, "state": "closed"}}
    store.save_thread(thread)
    _thread(store, "archived", status="archived")
    _entry(store, "archived", 0)


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_projection_cases(store_class, tmp_path):
    store = store_class(tmp_path)
    service = _service(store)

    # Empty store: no projection entries.
    assert WhiteboardService(service).graph_nodes() == []

    _build_scenario(store)
    projection = {row[0]: row for row in _projection(store)}

    assert "wb-empty" not in projection
    assert projection["wb-with-entries"][3] == 2
    assert projection["wb-with-entries"][4] == "open"
    assert projection["wb-with-entries"][5] == "open"
    assert projection["wb-closed"][2] == "paused"
    assert projection["wb-closed"][4] == "closed"
    assert projection["wb-archived"][2] == "archived"
    assert projection["wb-archived"][5] == "archived"


def test_projection_identical_across_stores(tmp_path):
    json_store = JsonStore(tmp_path / "json")
    sqlite_store = SQLiteStore(tmp_path / "sqlite")
    _build_scenario(json_store)
    _build_scenario(sqlite_store)

    assert _projection(json_store) == _projection(sqlite_store)


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_projection_conflict_is_explicit(store_class, tmp_path):
    store = store_class(tmp_path)
    _thread(store, "collision")
    _entry(store, "collision", 0)
    store.save_node(
        KnowledgeNode(
            id="wb-collision",
            kind="whiteboard",
            title="Stored projection",
            status="idea",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            source="threaddesk.whiteboard",
        )
    )
    with pytest.raises(ManagementError) as conflict:
        WhiteboardService(_service(store)).graph_nodes()
    assert conflict.value.code == "graph_projection_conflict"


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_pending_transaction_is_visible_in_projection(store_class, tmp_path):
    store = store_class(tmp_path)
    # Thread listing is disk-backed (existing semantics); only the append is
    # staged inside the transaction. The projection must still see it.
    _thread(store, "pending")
    with store.transaction():
        _entry(store, "pending", 0)
        projection = {row[0]: row for row in _projection(store)}
        assert projection["wb-pending"][3] == 1
        assert projection["wb-pending"][4] == "open"
    assert {row[0]: row for row in _projection(store)}["wb-pending"][3] == 1


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_projection_never_reads_whiteboard_payloads(store_class, tmp_path, monkeypatch):
    store = store_class(tmp_path)
    _thread(store, "with-entries")
    _entry(store, "with-entries", 0)
    _entry(store, "with-entries", 1)

    def fail(*args, **kwargs):
        raise AssertionError("graph projection must not scan whiteboard payloads")

    monkeypatch.setattr(store, "list_whiteboard", fail)
    nodes = WhiteboardService(_service(store)).graph_nodes()
    assert [(node.metadata["entry_count"]) for node in nodes] == [2]
