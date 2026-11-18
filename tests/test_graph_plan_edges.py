"""Derived plan edges are calculated while reading the graph and never stored."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.core.errors import ManagementError
from threaddesk.core.models import KnowledgeNode, Thread, ThreadContext, WhiteboardEntry
from threaddesk.services.trash import TrashService
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore

STORES = [JsonStore, SQLiteStore]
PLAN = "7fb455b083f7"
KIRA = "ba619be9cbf4"
DESK = "8b7f304ee839"
NOTE = "450d3dc1c6d2"
ARCHIVED = "30f80f0e050e"
TRASHED = "111111111111"
PAUSED = "222222222222"
CYCLE_A = "aaaaaaaaaaaa"
CYCLE_B = "bbbbbbbbbbbb"


def _service(store) -> ThreadService:
    return ThreadService(store=store)


def _board(
    store, thread_id, *, status="idea", description="", notes="", organization=None
):
    extra = {"whiteboard": {"version": 1, "state": "open"}}
    if organization is not None:
        extra["organization"] = organization
    store.save_thread(
        Thread(
            id=thread_id,
            title=thread_id,
            description=description,
            status=status,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            context=ThreadContext(notes=notes, extra=extra),
        )
    )


def _derived(graph):
    return [
        row
        for row in graph["relations"]
        if row.get("metadata", {}).get("derived") is True
    ]


def _pairs(graph, kind):
    return {
        (row["source_id"], row["target_id"])
        for row in _derived(graph)
        if row["kind"] == kind
    }


def _files(root: Path) -> dict[str, bytes]:
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            found[str(path.relative_to(root))] = path.read_bytes()
    return found


def _family(store):
    _board(
        store,
        PLAN,
        notes=f"siehe {NOTE} und nicht sich selbst {PLAN}",
        organization={
            "related_thread_ids": [KIRA, DESK, KIRA, PLAN, "not-a-thread", 12],
        },
    )
    _board(store, KIRA, organization={"parent_thread_id": PLAN})
    _board(store, DESK, organization={"parent_thread_id": PLAN})
    _board(store, NOTE)
    _board(store, PAUSED, status="paused", organization={"parent_thread_id": PLAN})
    _board(
        store,
        ARCHIVED,
        status="archived",
        description=f"nennt {KIRA}",
        organization={
            "parent_thread_id": PLAN,
            "related_thread_ids": [DESK],
        },
    )
    store.append_whiteboard_entry(
        WhiteboardEntry(
            id="entry-mentions-desk",
            thread_id=PLAN,
            actor="synthetic",
            actor_type="human",
            created_at="2026-01-01T00:00:01Z",
            entry_type="note",
            content=f"nur im Eintrag {DESK}",
            ordinal=1,
            metadata={},
        )
    )
    # A longer hex string contains a live id. That is not a thread reference.
    thread = store.get_thread(KIRA)
    thread.description = "aa" + DESK + "bb"
    store.save_thread(thread)


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_parent_and_related_ids_become_one_contains_edge(store_class, tmp_path):
    store = store_class(tmp_path)
    _family(store)
    pairs = _pairs(_service(store).graph(), "contains")
    assert pairs == {
        ("wb-" + PLAN, "wb-" + KIRA),
        ("wb-" + PLAN, "wb-" + DESK),
        ("wb-" + PLAN, "wb-" + PAUSED),
    }
    edge = next(
        row
        for row in _derived(_service(store).graph())
        if row["kind"] == "contains" and row["target_id"] == "wb-" + KIRA
    )
    assert edge["metadata"]["derived"] is True
    assert edge["source"] == "threaddesk.organization"
    assert edge["id"].startswith("wb-org-contains-")


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_text_mentions_link_only_living_threads(store_class, tmp_path):
    store = store_class(tmp_path)
    _family(store)
    _board(
        store,
        TRASHED,
        description=f"nennt {KIRA}",
        organization={"parent_thread_id": PLAN},
    )
    TrashService(store).move(
        kind="thread",
        object_id=TRASHED,
        expected_revision=store.get_thread(TRASHED).revision,
        operation_id="trash-plan-edge",
    )
    graph = _service(store).graph()
    assert _pairs(graph, "references") == {("wb-" + PLAN, "wb-" + NOTE)}
    ends = {row["source_id"] for row in _derived(graph)} | {
        row["target_id"] for row in _derived(graph)
    }
    assert "wb-" + TRASHED not in ends
    assert "wb-" + ARCHIVED not in ends


@pytest.mark.parametrize("store_class", STORES, ids=["json", "sqlite"])
def test_cycles_and_broken_organization_do_not_break_the_map(store_class, tmp_path):
    store = store_class(tmp_path)
    _board(
        store,
        CYCLE_A,
        organization={"parent_thread_id": CYCLE_B, "related_thread_ids": "nope"},
    )
    _board(
        store,
        CYCLE_B,
        description=f"zurück {CYCLE_A}",
        organization={
            "parent_thread_id": CYCLE_A,
            "related_thread_ids": [None, CYCLE_B],
        },
    )
    _board(store, PLAN, organization="broken", description=f"trotzdem {CYCLE_A}")
    graph = _service(store).graph()
    assert _pairs(graph, "contains") == {
        ("wb-" + CYCLE_B, "wb-" + CYCLE_A),
        ("wb-" + CYCLE_A, "wb-" + CYCLE_B),
    }
    assert _pairs(graph, "references") == {
        ("wb-" + CYCLE_B, "wb-" + CYCLE_A),
        ("wb-" + PLAN, "wb-" + CYCLE_A),
    }


def test_reading_the_graph_does_not_change_a_byte(tmp_path):
    store = JsonStore(tmp_path)
    _family(store)
    before = _files(tmp_path)
    digest = hashlib.sha256(b"".join(before.values())).hexdigest()
    _service(store).graph()
    _service(store).graph()
    assert _files(tmp_path) == before
    assert hashlib.sha256(b"".join(_files(tmp_path).values())).hexdigest() == digest


def test_projection_conflict_still_aborts_before_derived_edges(tmp_path):
    store = JsonStore(tmp_path)
    _board(store, PLAN, organization={"related_thread_ids": [KIRA]})
    _board(store, KIRA, organization={"parent_thread_id": PLAN})
    store.save_node(
        KnowledgeNode(
            id="wb-" + PLAN,
            kind="task",
            title="Kollision",
            status="idea",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
    )
    before = _files(tmp_path)
    with pytest.raises(ManagementError) as conflict:
        _service(store).graph()
    assert conflict.value.code == "graph_projection_conflict"
    assert _files(tmp_path) == before


def test_derived_edges_do_not_read_whiteboard_entries(tmp_path, monkeypatch):
    store = JsonStore(tmp_path)
    _board(store, PLAN, organization={"related_thread_ids": [KIRA]})
    _board(store, KIRA, organization={"parent_thread_id": PLAN})

    def fail(*args, **kwargs):
        raise AssertionError("derived edges must not read whiteboard entries")

    monkeypatch.setattr(store, "list_whiteboard", fail)
    assert ("wb-" + PLAN, "wb-" + KIRA) in _pairs(_service(store).graph(), "contains")
