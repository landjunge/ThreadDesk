"""Derived whiteboard index. Synthetic directories only, never a product profile."""
import json
import os
from pathlib import Path

import pytest

from threaddesk.core.search import SearchError
from threaddesk.storage.entry_index import EntryIndex


def _thread(root: Path, thread_id: str, **changes) -> None:
    body = {
        "id": thread_id,
        "title": changes.get("title", "Title " + thread_id),
        "description": changes.get("description", ""),
        "status": changes.get("status", "idea"),
        "created_at": changes.get("created_at", "2026-11-01T00:00:00+00:00"),
        "updated_at": changes.get("updated_at", "2026-11-01T00:00:00+00:00"),
        "revision": changes.get("revision", 1),
        "context": {
            "notes": changes.get("notes", ""),
            "files": [],
            "prompts": [],
            "agent_state": {},
            "extra": {},
        },
    }
    folder = root / "threads"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{thread_id}.json").write_text(json.dumps(body), encoding="utf-8")


def _entry(root: Path, thread_id: str, entry_id: str, content: str, **changes) -> None:
    body = {
        "id": entry_id,
        "thread_id": thread_id,
        "ordinal": changes.get("ordinal", 1),
        "actor": changes.get("actor", "Codex"),
        "actor_type": "codex",
        "entry_type": changes.get("entry_type", "note"),
        "content": content,
        "created_at": changes.get("created_at", "2026-11-02T00:00:00+00:00"),
    }
    folder = root / "whiteboard" / thread_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{entry_id}.json").write_text(json.dumps(body), encoding="utf-8")


def _snapshot(root: Path) -> dict:
    found = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            stat = path.lstat()
            found[str(path.relative_to(root))] = (stat.st_size, stat.st_mtime_ns, path.read_bytes())
    return found


def _words(index, query, **kwargs):
    hits, cursor = [], None
    for _ in range(20):
        page = index.query(query, cursor=cursor, limit=kwargs.pop("limit", 10), **kwargs)
        hits.extend(page.hits)
        cursor = page.next_cursor
        if cursor is None:
            return hits, page
    pytest.fail("cursor did not end")


def test_two_scans_share_manifest_hashes(tmp_path):
    _thread(tmp_path, "threadalpha01", notes="notes marigold")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "whiteboard lavender")
    index = EntryIndex(tmp_path)
    first = index.scan()
    second = index.scan()
    assert first["manifests"] == second["manifests"]
    assert first["manifests"]["threadalpha01"]
    assert first["complete"] is True and second["complete"] is True
    index.close()


def test_deleting_the_index_leaves_json_bytes_and_mtimes(tmp_path):
    _thread(tmp_path, "threadalpha01", title="kept title")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "kept body")
    before = _snapshot(tmp_path)
    index = EntryIndex(tmp_path)
    assert index.path.parent == tmp_path.parent
    assert not str(index.path).startswith(str(tmp_path) + os.sep)
    index.scan()
    index.remove()
    assert _snapshot(tmp_path) == before
    assert not index.path.exists()


def test_query_filters_sort_and_durable_cursor(tmp_path):
    _thread(tmp_path, "threadalpha01", title="alpha title")
    _thread(tmp_path, "threadbravo002", title="bravo title", status="archived")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "unique lavender once",
           actor="Codex", entry_type="note", created_at="2026-11-02T00:00:00+00:00")
    _entry(tmp_path, "threadalpha01", "entryalpha002",
           "lavender lavender lavender lavender",
           actor="Grok", entry_type="result", ordinal=2,
           created_at="2026-11-05T00:00:00+00:00")
    _entry(tmp_path, "threadbravo002", "entrybravo0001", "lavender archived",
           created_at="2026-11-09T00:00:00+00:00")
    index = EntryIndex(tmp_path)
    index.scan()
    ranked = index.query("lavender", sort="rank", limit=10)
    newest = index.query("lavender", sort="newest", limit=10)
    assert [hit.entry_id for hit in ranked.hits][0] == "entryalpha002"
    assert [hit.entry_id for hit in newest.hits] == ["entryalpha002", "entryalpha001"]
    assert ranked.complete is True
    filtered = index.query("lavender", thread_id="threadalpha01", actor="Grok",
                           entry_type="result", since="2026-11-03", until="2026-11-06")
    assert [hit.entry_id for hit in filtered.hits] == ["entryalpha002"]
    visible = {hit.thread_id for hit in index.query("lavender").hits}
    archived = {hit.thread_id for hit in index.query("lavender", include_archived=True).hits}
    assert "threadbravo002" not in visible
    assert "threadbravo002" in archived
    page = index.query("lavender", sort="newest", limit=1)
    assert page.next_cursor and len(page.hits) == 1
    rest = index.query("lavender", sort="newest", limit=1, cursor=page.next_cursor)
    assert rest.hits[0].entry_id != page.hits[0].entry_id
    assert rest.hits[0].snippet
    assert "lavender" in Path(tmp_path, "whiteboard", rest.hits[0].thread_id,
                              rest.hits[0].entry_id + ".json").read_text()
    index.close()
    again = EntryIndex(tmp_path)
    followed = again.query("lavender", sort="newest", limit=1, cursor=page.next_cursor)
    assert followed.hits[0].entry_id == rest.hits[0].entry_id
    again.close()


def test_foreign_file_without_revision_change_is_found_on_next_scan(tmp_path):
    _thread(tmp_path, "threadalpha01", revision=4, notes="stable notes")
    index = EntryIndex(tmp_path)
    index.scan()
    assert index.query("foreigntoken").hits == []
    _entry(tmp_path, "threadalpha01", "entryforeign01", "foreigntoken from outside")
    stored = json.loads((tmp_path / "threads" / "threadalpha01.json").read_text())
    assert stored["revision"] == 4
    index.scan()
    hits, _page = _words(index, "foreigntoken")
    assert [hit.entry_id for hit in hits] == ["entryforeign01"]
    assert json.loads((tmp_path / "threads" / "threadalpha01.json").read_text())["revision"] == 4
    index.close()


def test_changed_and_removed_entries_leave_the_index(tmp_path):
    _thread(tmp_path, "threadalpha01")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "oldtoken stays")
    index = EntryIndex(tmp_path)
    index.scan()
    _entry(tmp_path, "threadalpha01", "entryalpha001", "newtoken replaces")
    (tmp_path / "whiteboard" / "threadalpha01" / "entryalpha002.json").write_text(
        json.dumps({
            "id": "entryalpha002", "thread_id": "threadalpha01", "ordinal": 2,
            "actor": "Codex", "entry_type": "note", "content": "gonetoken vanishes",
            "created_at": "2026-11-03T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    index.scan()
    (tmp_path / "whiteboard" / "threadalpha01" / "entryalpha002.json").unlink()
    index.scan()
    assert index.query("oldtoken").hits == []
    assert [hit.entry_id for hit in index.query("newtoken").hits] == ["entryalpha001"]
    assert index.query("gonetoken").hits == []
    index.close()


def test_abort_mid_thread_keeps_prior_rows_and_check_reports_it(tmp_path):
    _thread(tmp_path, "threadalpha01")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "kepttoken original")
    index = EntryIndex(tmp_path)
    index.scan()
    _entry(tmp_path, "threadalpha01", "entryalpha001", "brokentoken replacement")
    with pytest.raises(RuntimeError, match="index_abort"):
        index.scan(abort_thread="threadalpha01")
    assert [hit.entry_id for hit in index.query("kepttoken").hits] == ["entryalpha001"]
    assert index.query("brokentoken").hits == []
    assert index.query("kepttoken").complete is False
    problems = index.check()
    assert problems == [{"thread_id": "threadalpha01", "problem": "mismatch"}]
    index.scan()
    assert [hit.entry_id for hit in index.query("brokentoken").hits] == ["entryalpha001"]
    assert index.query("kepttoken").hits == []
    assert index.check() == []
    assert index.query("brokentoken").complete is True
    _thread(tmp_path, "threadcharlie3")
    _entry(tmp_path, "threadcharlie3", "entrycharlie01", "freshcharlie token")
    with pytest.raises(RuntimeError, match="index_abort"):
        index.scan(abort_thread="threadcharlie3")
    assert index.query("freshcharlie").hits == []
    assert {"thread_id": "threadcharlie3", "problem": "missing"} in index.check()
    index.scan()
    assert index.query("freshcharlie").hits
    assert index.check() == []
    index.close()


def test_missing_fts_reports_unavailable_and_never_complete(tmp_path, monkeypatch):
    from threaddesk.storage import entry_index
    monkeypatch.setattr(entry_index, "ENTRY_FTS_SQL",
                        "CREATE VIRTUAL TABLE search_body USING td_missing_fts5(body)")
    _thread(tmp_path, "threadalpha01", notes="notes marigold")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "whiteboard lavender")
    index = EntryIndex(tmp_path)
    status = index.scan()
    page = index.query("lavender")
    assert status["mode"] == "fts_unavailable"
    assert status["complete"] is False
    assert page.mode == "fts_unavailable"
    assert page.complete is False
    assert page.hits == []
    assert "fts_unavailable" in page.reasons
    index.close()


def test_scan_does_not_open_workspace_locks(tmp_path, monkeypatch):
    _thread(tmp_path, "threadalpha01")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "locktoken body")
    real = os.open

    def guard(path, flags, *args, **kwargs):
        if os.path.basename(path) in {".append.lock", ".management.lock"}:
            raise AssertionError(path)
        return real(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", guard)
    index = EntryIndex(tmp_path)
    index.scan()
    assert index.query("locktoken").hits
    index.close()


def test_short_query_is_not_a_complete_miss(tmp_path):
    _thread(tmp_path, "threadalpha01", notes="notes marigold")
    index = EntryIndex(tmp_path)
    index.scan()
    page = index.query("ab")
    assert page.hits == []
    assert page.complete is False
    assert "query_too_short" in page.reasons
    with pytest.raises(SearchError):
        index.query("marigold", limit=0)
    index.close()
