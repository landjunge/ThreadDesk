"""Opening view when the remembered thread is empty. Synthetic homes only."""
import json
from pathlib import Path

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.storage.json_store import JsonStore


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


def _board(home: Path, thread_id: str, updated_at: str, content: str | None, **changes) -> None:
    notes = changes.get("notes", "")
    body = {
        "id": thread_id,
        "title": changes.get("title", thread_id),
        "description": changes.get("description", ""),
        "status": changes.get("status", "idea"),
        "created_at": "2026-11-01T00:00:00+00:00",
        "updated_at": updated_at,
        "revision": 1,
        "context": {"notes": notes, "files": [], "prompts": [], "agent_state": {}, "extra": {}},
    }
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
