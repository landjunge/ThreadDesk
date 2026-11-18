"""Opening view when the remembered thread is empty. Synthetic homes only."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore

FIXED = datetime(2026, 11, 18, 12, 0, 0, tzinfo=timezone.utc)
WINDOW = 15 * 60


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    return tmp_path


def _client():
    pytest.importorskip("fastapi")
    from http_ui_client import UIClient as TestClient
    from threaddesk.ui.server import create_app
    return TestClient(create_app())


def _remember(home: Path, thread_id: str | None) -> bytes:
    payload = {"current_id": thread_id}
    path = home / "state.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path.read_bytes()


def _freeze(monkeypatch: pytest.MonkeyPatch) -> None:
    import threaddesk.ui.server as server

    monkeypatch.setattr(server, "_opening_now", lambda: FIXED)


def _stamp(seconds_ago: int) -> str:
    return (FIXED - timedelta(seconds=seconds_ago)).isoformat()


def _board(home: Path, thread_id: str, updated_at: str | None, content: str | None, **changes) -> None:
    notes = changes.get("notes", "")
    body = {
        "id": thread_id,
        "title": changes.get("title", thread_id),
        "description": changes.get("description", ""),
        "status": changes.get("status", "idea"),
        "revision": 1,
        "context": {"notes": notes, "files": [], "prompts": [], "agent_state": {}, "extra": {}},
    }
    created_at = changes.get("created_at", "2026-11-01T00:00:00+00:00")
    if created_at is not None:
        body["created_at"] = created_at
    if updated_at is not None:
        body["updated_at"] = updated_at
    (home / "threads").mkdir(parents=True, exist_ok=True)
    (home / "threads" / f"{thread_id}.json").write_text(json.dumps(body), encoding="utf-8")
    if content is not None:
        folder = home / "whiteboard" / thread_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "entry00000001.json").write_text(json.dumps({
            "id": "entry00000001",
            "thread_id": thread_id,
            "ordinal": 1,
            "actor": "Codex",
            "actor_type": "codex",
            "entry_type": "note",
            "content": content,
            "created_at": updated_at,
        }), encoding="utf-8")


def test_explicit_thread_wins(home: Path) -> None:
    _board(home, "emptythread01", "2026-11-18T00:00:00+00:00", None,
           title="Leerer Start", description="nur beschreibung")
    _board(home, "fullthread001", "2026-11-18T01:00:00+00:00", "sichtbarer eintrag",
           title="Volles Board")
    state = _remember(home, "emptythread01")
    page = _client().get("/?thread=emptythread01")
    assert page.status_code == 200
    assert "nur beschreibung" in page.text
    assert "sichtbarer eintrag" not in page.text
    assert "Stattdessen" not in page.text
    assert (home / "state.json").read_bytes() == state


def test_nonempty_current_stays(home: Path) -> None:
    _board(home, "notedthread01", "2026-11-17T00:00:00+00:00", None,
           title="Mit Notiz", notes="behaltene notiz")
    _board(home, "fullthread001", "2026-11-18T01:00:00+00:00", "sichtbarer eintrag",
           title="Volles Board")
    state = _remember(home, "notedthread01")
    page = _client().get("/")
    assert page.status_code == 200
    assert "behaltene notiz" in page.text
    assert "sichtbarer eintrag" not in page.text
    assert (home / "state.json").read_bytes() == state


def test_empty_current_falls_back_to_newest_board(home: Path) -> None:
    _board(home, "emptythread01", "2026-11-18T03:00:00+00:00", None,
           title="Leerer Start", description="nur beschreibung")
    _board(home, "olderboard001", "2026-11-18T01:00:00+00:00", "alter eintrag",
           title="Aelteres Board")
    _board(home, "newerboard001", "2026-11-18T02:00:00+00:00", "sichtbarer eintrag",
           title="Juengstes Board")
    state = _remember(home, "emptythread01")
    page = _client().get("/")
    assert page.status_code == 200
    assert "sichtbarer eintrag" in page.text
    assert "alter eintrag" not in page.text
    assert "Stattdessen" in page.text
    assert "/?thread=emptythread01" in page.text
    assert (home / "state.json").read_bytes() == state


def test_archived_and_empty_threads_are_skipped(home: Path) -> None:
    _board(home, "archivedboard1", "2026-11-18T04:00:00+00:00", "archivierter eintrag",
           title="Archiv", status="archived")
    _board(home, "emptynewer001", "2026-11-18T03:00:00+00:00", None, title="Leer neu")
    _board(home, "keptboard0001", "2026-11-18T01:00:00+00:00", "sichtbarer eintrag",
           title="Behalten")
    state = _remember(home, "archivedboard1")
    page = _client().get("/")
    assert "sichtbarer eintrag" in page.text
    assert "archivierter eintrag" not in page.text
    assert (home / "state.json").read_bytes() == state


def test_missing_current_and_broken_state_stay_as_before(home: Path) -> None:
    _board(home, "fullthread001", "2026-11-18T01:00:00+00:00", "sichtbarer eintrag",
           title="Volles Board")
    JsonStore(home)
    missing = _remember(home, None)
    page = _client().get("/")
    assert page.status_code == 200
    assert "sichtbarer eintrag" not in page.text
    assert (home / "state.json").read_bytes() == missing
    (home / "state.json").write_text("{", encoding="utf-8")
    broken = (home / "state.json").read_bytes()
    with pytest.raises(json.JSONDecodeError):
        _client().get("/")
    assert (home / "state.json").read_bytes() == broken


def _opening(home: Path, *boards: tuple, remember: str) -> tuple[object, bytes]:
    for thread_id, updated_at, content, changes in boards:
        _board(home, thread_id, updated_at, content, **changes)
    state = _remember(home, remember)
    return _client().get("/"), state


@pytest.mark.parametrize(
    ("age_seconds", "stays"),
    [
        (0, True),
        (WINDOW - 1, True),
        (WINDOW, True),
        (WINDOW + 1, False),
        (2 * 60 * 60, False),
    ],
    ids=["fresh", "just-under-15m", "exactly-15m", "just-over-15m", "old"],
)
def test_empty_thread_age_window(home: Path, monkeypatch: pytest.MonkeyPatch, age_seconds: int, stays: bool) -> None:
    _freeze(monkeypatch)
    stamp = _stamp(age_seconds)
    page, state = _opening(
        home,
        ("emptythread01", stamp, None, {
            "title": "Leerer Start", "description": "nur beschreibung", "created_at": stamp,
        }),
        ("fullthread001", _stamp(3 * 60 * 60), "sichtbarer eintrag", {
            "title": "Volles Board", "created_at": _stamp(3 * 60 * 60),
        }),
        remember="emptythread01",
    )
    assert page.status_code == 200
    if stays:
        assert "nur beschreibung" in page.text
        assert "sichtbarer eintrag" not in page.text
        assert "Stattdessen" not in page.text
    else:
        assert "sichtbarer eintrag" in page.text
        assert "nur beschreibung" not in page.text
        assert "Stattdessen" in page.text
        assert "/?thread=emptythread01" in page.text
    assert (home / "state.json").read_bytes() == state


def test_old_empty_thread_the_user_just_switched_to_stays(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch)
    page, state = _opening(
        home,
        ("emptythread01", _stamp(60), None, {
            "title": "Leerer Start", "description": "nur beschreibung",
            "created_at": _stamp(WINDOW + 60),
        }),
        ("fullthread001", _stamp(3 * 60 * 60), "sichtbarer eintrag", {
            "title": "Volles Board", "created_at": _stamp(3 * 60 * 60),
        }),
        remember="emptythread01",
    )
    assert page.status_code == 200
    assert "nur beschreibung" in page.text
    assert "sichtbarer eintrag" not in page.text
    assert (home / "state.json").read_bytes() == state


def test_missing_or_unreadable_timestamps_count_as_old(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch)
    page, state = _opening(
        home,
        ("emptythread01", None, None, {
            "title": "Leerer Start", "description": "nur beschreibung", "created_at": None,
        }),
        ("fullthread001", _stamp(3 * 60 * 60), "sichtbarer eintrag", {
            "title": "Volles Board", "created_at": _stamp(3 * 60 * 60),
        }),
        remember="emptythread01",
    )
    assert page.status_code == 200
    assert "sichtbarer eintrag" in page.text
    assert (home / "state.json").read_bytes() == state
    raw = json.loads((home / "threads" / "emptythread01.json").read_text(encoding="utf-8"))
    raw["created_at"] = "not-a-time"
    raw["updated_at"] = "also-not"
    (home / "threads" / "emptythread01.json").write_text(json.dumps(raw), encoding="utf-8")
    broken = _client().get("/")
    assert broken.status_code == 200
    assert "sichtbarer eintrag" in broken.text
    assert (home / "state.json").read_bytes() == state


def test_just_created_empty_thread_keeps_its_heading(home: Path) -> None:
    _board(home, "fullthread001", "2026-11-01T00:00:00+00:00", "sichtbarer eintrag", title="Volles Board")
    client = _client()
    created = client.post_thread_form("/threads", data={"title": "Browser Leseraumthread", "description": ""})
    assert created.status_code == 200
    assert "<h1>Browser Leseraumthread</h1>" in created.text
    assert "<h1>Volles Board</h1>" not in created.text
    state = (home / "state.json").read_bytes()
    again = client.get("/")
    assert "<h1>Browser Leseraumthread</h1>" in again.text
    assert "sichtbarer eintrag" not in again.text
    assert (home / "state.json").read_bytes() == state
