"""Search page over a synthetic home. Never a product profile."""
import json
from pathlib import Path

import pytest

from threaddesk.services.search import LocalFileOwnerPolicy, SearchService
from threaddesk.storage.json_store import JsonStore


def _thread(root: Path, thread_id: str, **changes) -> None:
    body = {
        "id": thread_id,
        "title": changes.get("title", "Title " + thread_id),
        "description": changes.get("description", ""),
        "status": changes.get("status", "idea"),
        "created_at": "2026-11-01T00:00:00+00:00",
        "updated_at": "2026-11-01T00:00:00+00:00",
        "revision": 1,
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
        "entry_type": changes.get("entry_type", "note"),
        "content": content,
        "created_at": changes.get("created_at", "2026-11-02T00:00:00+00:00"),
    }
    folder = root / "whiteboard" / thread_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{entry_id}.json").write_text(json.dumps(body), encoding="utf-8")


def _trash(root: Path, thread_id: str) -> None:
    folder = root / "trash"
    folder.mkdir(parents=True, exist_ok=True)
    body = {"kind": "thread", "object_id": thread_id, "state": "trashed", "generation": 1}
    (folder / f"thread-{thread_id}-g1.json").write_text(json.dumps(body), encoding="utf-8")


def _client(monkeypatch, home: Path):
    pytest.importorskip("fastapi")
    monkeypatch.setenv("THREADDESK_HOME", str(home))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    from http_ui_client import UIClient
    from threaddesk.ui.server import create_app
    return UIClient(create_app())


def test_search_page_answers_and_the_nav_offers_it(tmp_path, monkeypatch) -> None:
    client = _client(monkeypatch, tmp_path)
    page = client.get("/search")
    assert page.status_code == 200
    assert 'id="search-q"' in page.text
    german = client.get("/?lang=de")
    english = client.get("/?lang=en")
    assert 'href="/search"' in german.text and ">Suche<" in german.text
    assert 'href="/search"' in english.text and ">Search<" in english.text


def test_entry_text_and_a_note_both_appear(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "threadalpha01", title="Alpha board", notes="Lavendelmarke steht in der notiz")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "Lavendelmarke steht im eintrag")
    store = JsonStore(tmp_path)
    SearchService(store, LocalFileOwnerPolicy(store.workspace_path)).set_enabled(True)
    page = _client(monkeypatch, tmp_path).get("/search?q=Lavendelmarke")
    assert page.status_code == 200
    assert "Alpha board" in page.text
    assert "Lavendelmarke steht im eintrag" in page.text
    assert "Lavendelmarke steht in der notiz" in page.text
    assert "Codex" in page.text
    assert 'href="/?thread=threadalpha01"' in page.text


def test_snippet_is_escaped_text(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "threadalpha01", title="Alpha board")
    _entry(
        tmp_path, "threadalpha01", "entryalpha001",
        "<script>alert(1)</script> Lavendelmarke",
    )
    page = _client(monkeypatch, tmp_path).get("/search?q=Lavendelmarke")
    assert page.status_code == 200
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text


def test_trashed_thread_stays_out(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "livethread001", title="Live board")
    _entry(tmp_path, "livethread001", "entrylive00001", "Lavendelmarke bleibt sichtbar")
    _thread(tmp_path, "junkthread002", title="Junk board")
    _entry(tmp_path, "junkthread002", "entryjunk00001", "Lavendelmarke im papierkorb")
    _trash(tmp_path, "junkthread002")
    before = (tmp_path / "threads" / "livethread001.json").read_bytes()
    page = _client(monkeypatch, tmp_path).get("/search?q=Lavendelmarke")
    assert page.status_code == 200
    assert "Live board" in page.text
    assert "Junk board" not in page.text
    assert (tmp_path / "threads" / "livethread001.json").read_bytes() == before
    assert not (tmp_path / "livethread001.search.sqlite").exists()


def test_disabled_thread_search_still_shows_entries(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "threadalpha01", title="Alpha board", notes="NurdieNotizmarke")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "Lavendelmarke im eintrag")
    page = _client(monkeypatch, tmp_path).get("/search?q=Lavendelmarke")
    assert page.status_code == 200
    assert "Lavendelmarke im eintrag" in page.text
    assert "NurdieNotizmarke" not in page.text
    assert "Suche ist aus" not in page.text
    assert 'role="alert"' not in page.text


def test_empty_and_very_long_query_stay_open(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "threadalpha01", title="Alpha board")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "Lavendelmarke im eintrag")
    client = _client(monkeypatch, tmp_path)
    empty = client.get("/search?q=")
    assert empty.status_code == 200
    assert 'id="search-q"' in empty.text
    assert "Alpha board" not in empty.text
    assert 'role="alert"' not in empty.text
    long = client.get("/search?q=" + "Lavendelmarke " + ("wort" * 400))
    assert long.status_code == 200
    assert "Lavendelmarke im eintrag" in long.text
    assert 'role="alert"' not in long.text


def test_sort_filter_and_cursor(tmp_path, monkeypatch) -> None:
    _thread(tmp_path, "threadalpha01", title="Alpha board")
    _thread(tmp_path, "threadbravo002", title="Bravo board")
    _entry(
        tmp_path, "threadalpha01", "entryalpha001", "Lavendelmarke frueh",
        created_at="2026-11-02T00:00:00+00:00",
    )
    _entry(
        tmp_path, "threadalpha01", "entryalpha002", "Lavendelmarke spaet",
        ordinal=2, created_at="2026-11-20T00:00:00+00:00",
    )
    _entry(
        tmp_path, "threadbravo002", "entrybravo0001", "Lavendelmarke woanders",
        created_at="2026-11-21T00:00:00+00:00",
    )
    for number in range(1, 22):
        _entry(
            tmp_path, "threadalpha01", f"entrypage{number:02d}", "Blaettermarke seite",
            ordinal=number, created_at=f"2026-10-{number:02d}T00:00:00+00:00",
        )
    client = _client(monkeypatch, tmp_path)
    newest = client.get("/search?q=Lavendelmarke")
    assert newest.status_code == 200
    assert newest.text.index("Lavendelmarke woanders") < newest.text.index("Lavendelmarke frueh")
    relevance = client.get("/search?q=Lavendelmarke&sort=relevance")
    assert relevance.status_code == 200
    assert "Lavendelmarke frueh" in relevance.text
    narrowed = client.get("/search?q=Lavendelmarke&thread=threadalpha01")
    assert "Bravo board" not in narrowed.text
    assert "Alpha board" in narrowed.text
    first = client.get("/search?q=Blaettermarke&sort=newest")
    assert "2026-10-01" not in first.text
    assert "Mehr zeigen" in first.text
    link = first.text.split('href="/search?', 1)[1].split('"', 1)[0]
    assert "next_cursor=" in link
    second = client.get("/search?" + link.replace("&amp;", "&"))
    assert second.status_code == 200
    assert "2026-10-01" in second.text


def test_rebuilding_is_a_quiet_hint(tmp_path, monkeypatch) -> None:
    from threaddesk.services import entry_search
    _thread(tmp_path, "threadalpha01", title="Alpha board")
    _entry(tmp_path, "threadalpha01", "entryalpha001", "Lavendelmarke im eintrag")
    monkeypatch.setattr(entry_search, "SCAN_BUDGET_SECONDS", 0)
    page = _client(monkeypatch, tmp_path).get("/search?q=Lavendelmarke")
    assert page.status_code == 200
    assert "Index wird aufgebaut" in page.text
    assert 'role="alert"' not in page.text
    assert "Suche ist aus" not in page.text
