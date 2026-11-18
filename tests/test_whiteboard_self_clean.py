"""Boards replace and remove entries. Synthetic workspaces only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.commands.registry import CommandRegistry
from threaddesk.services.whiteboard import history_for_handoff
from threaddesk.services.whiteboard_lifecycle import WhiteboardService, effective_entries
from threaddesk.storage.entry_index import EntryIndex
from threaddesk.storage.json_store import JsonStore
from threaddesk.storage.sqlite_store import SQLiteStore
from threaddesk.ui.cli import main


@pytest.fixture(params=[JsonStore, SQLiteStore], ids=["json", "sqlite"])
def svc(request, tmp_path: Path) -> ThreadService:
    return ThreadService(store=request.param(tmp_path))


def _add(svc, thread_id, content, **extra):
    fields = {
        "actor": extra.pop("actor", "Mensch"),
        "actor_type": extra.pop("actor_type", "human"),
        "entry_type": extra.pop("entry_type", "note"),
        "content": content,
    }
    fields.update(extra)
    return svc.append_whiteboard(thread_id, **fields)


def _files(root: Path):
    return [path for path in root.rglob("*") if path.is_file()]


def _text_copies(root: Path, needle: str):
    found = []
    for path in _files(root):
        if path.suffix in {".sqlite", ".sqlite3"} or path.name.endswith(("-wal", "-shm")):
            continue
        try:
            blob = path.read_bytes()
        except OSError:
            continue
        if needle.encode() in blob:
            found.append(path)
    return found


def test_remove_is_idempotent_and_leaves_no_copy(svc, tmp_path: Path):
    thread = svc.create("Räumen")
    before = svc.get(thread.id).updated_at
    created = _add(svc, thread.id, "selfcleantoken einmalig")
    entry_id = created["entry"]["id"]
    keeper = _add(svc, thread.id, "bleibt stehen")
    first = svc.remove_whiteboard_entry(thread.id, entry_id)
    assert first["removed"] is True
    assert svc.get(thread.id).updated_at != before
    assert [entry.id for entry in svc.whiteboard(thread.id)] == [keeper["entry"]["id"]]
    again = svc.remove_whiteboard_entry(thread.id, entry_id)
    assert again["removed"] is False
    missing = svc.remove_whiteboard_entry(thread.id, "nie-da-gewesen")
    assert missing["removed"] is False
    assert _text_copies(tmp_path, "selfcleantoken einmalig") == []
    assert _text_copies(tmp_path, entry_id) == []
    if isinstance(svc.store, SQLiteStore):
        rows = svc.store.connection.execute("SELECT payload FROM whiteboard_entries").fetchall()
        assert "selfcleantoken einmalig" not in json.dumps([tuple(row) for row in rows])


def test_external_key_replaces_only_on_the_same_board(svc):
    first_board = svc.create("Eins")
    other = svc.create("Zwei")
    original = _add(svc, first_board.id, "alt", external_key="gleiche-kennung")
    same = _add(svc, first_board.id, "alt", external_key="gleiche-kennung")
    assert same["duplicate"] is True
    assert same["entry"]["id"] == original["entry"]["id"]
    _add(svc, other.id, "anderswo", external_key="gleiche-kennung")
    replaced = _add(svc, first_board.id, "neu", external_key="gleiche-kennung")
    assert replaced["duplicate"] is False
    assert replaced["entry"]["id"] != original["entry"]["id"]
    assert replaced["entry"]["ordinal"] > original["entry"]["ordinal"]
    left = svc.whiteboard(first_board.id)
    assert [entry.content for entry in left] == ["neu"]
    assert [entry.content for entry in svc.whiteboard(other.id)] == ["anderswo"]
    assert not any(entry.id == original["entry"]["id"] for entry in left)


def test_supersedes_removes_only_the_named_entries(svc):
    thread = svc.create("Ablösen")
    other = svc.create("Fremd")
    first = _add(svc, thread.id, "eins")
    second = _add(svc, thread.id, "zwei")
    foreign = _add(svc, other.id, "fremd")
    keeper = _add(svc, thread.id, "drei")
    created = _add(
        svc,
        thread.id,
        "vier",
        supersedes=[first["entry"]["id"], second["entry"]["id"], foreign["entry"]["id"], "fehlt"],
    )
    assert [entry.id for entry in svc.whiteboard(thread.id)] == [
        keeper["entry"]["id"],
        created["entry"]["id"],
    ]
    assert [entry.id for entry in svc.whiteboard(other.id)] == [foreign["entry"]["id"]]


def test_expires_at_is_removed_on_the_next_access_only(svc, tmp_path: Path):
    thread = svc.create("Ablauf")
    fresh = _add(svc, thread.id, "noch gültig", expires_at="2999-01-01T00:00:00+00:00")
    stale = _add(svc, thread.id, "selfcleanexpiredtoken", expires_at="2000-01-01T00:00:00+00:00")
    assert {entry.id for entry in svc.store.list_whiteboard(thread.id)} == {
        fresh["entry"]["id"],
        stale["entry"]["id"],
    }
    assert [entry.content for entry in svc.whiteboard(thread.id)] == ["noch gültig"]
    assert _text_copies(tmp_path, "selfcleanexpiredtoken") == []
    assert [entry.id for entry in svc.whiteboard(thread.id)] == [fresh["entry"]["id"]]


def test_search_index_drops_a_removed_entry(tmp_path: Path):
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Index")
    created = _add(svc, thread.id, "selfcleantoken im index")
    index = EntryIndex(tmp_path)
    index.scan()
    assert [hit.entry_id for hit in index.query("selfcleantoken").hits] == [created["entry"]["id"]]
    svc.remove_whiteboard_entry(thread.id, created["entry"]["id"])
    index.scan()
    assert index.query("selfcleantoken").hits == []
    index.close()


def test_graph_and_handoff_ignore_a_removed_entry(svc):
    thread = svc.create("Graph")
    kept = _add(svc, thread.id, "sichtbar")
    gone = _add(svc, thread.id, "weg")
    svc.remove_whiteboard_entry(thread.id, gone["entry"]["id"])
    nodes = WhiteboardService(svc).graph_nodes()
    assert any(node.metadata.get("thread_id") == thread.id for node in nodes)
    history = history_for_handoff(svc.whiteboard(thread.id))
    assert [item["id"] for item in history] == [kept["entry"]["id"]]
    dangling = effective_entries(svc.whiteboard(thread.id))
    assert [entry.id for entry in dangling] == [kept["entry"]["id"]]


def test_remove_command_is_registered_like_append(tmp_path: Path):
    registry = CommandRegistry(JsonStore(tmp_path))
    remove = registry.specs["whiteboard.entry.remove"]
    append = registry.specs["whiteboard.append"]
    assert remove.scope == append.scope
    assert remove.effect == "data"


def test_cli_remove_deletes_the_entry(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    svc = ThreadService(store=JsonStore(tmp_path))
    thread = svc.create("Kommando")
    created = _add(svc, thread.id, "cli-selfclean-token")
    assert main(["whiteboard", "remove", thread.id, created["entry"]["id"]]) == 0
    assert svc.whiteboard(thread.id) == []
    assert main(["whiteboard", "remove", thread.id, created["entry"]["id"]]) == 0
    assert _text_copies(tmp_path, "cli-selfclean-token") == []
    assert os.environ["THREADDESK_HOME"] == str(tmp_path)
