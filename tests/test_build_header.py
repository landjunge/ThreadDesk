"""Every full UI page identifies the installed build without losing navigation."""

import hashlib
import sys
from html.parser import HTMLParser

import pytest

from threaddesk import __version__
from threaddesk.build_info import BUILD_ID, BUILD_LABEL, SOURCE_COMMIT


class Header(HTMLParser):
    def __init__(self):
        super().__init__()
        self.labels = []
        self.links = []
        self.current_label = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "p" and attrs.get("data-testid") == "build-label":
            self.current_label = {"attrs": attrs, "text": ""}
            self.labels.append(self.current_label)
        if tag == "a":
            self.links.append(attrs.get("href"))

    def handle_data(self, data):
        if self.current_label is not None:
            self.current_label["text"] += data

    def handle_endtag(self, tag):
        if tag == "p":
            self.current_label = None


@pytest.mark.parametrize("path", [
    "/", "/knowledge", "/data", "/map", "/migration",
    "/threads/{thread_id}/server-sync",
])
def test_full_pages_identify_build_and_keep_navigation(tmp_path, monkeypatch, path):
    from http_ui_client import UIClient
    from threaddesk.api.service import ThreadService
    from threaddesk.storage.json_store import JsonStore
    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    thread = ThreadService(store=JsonStore(tmp_path)).create("Headerprüfung")
    response = UIClient(create_app()).get(path.format(thread_id=thread.id))
    assert response.status_code == 200
    header = Header()
    header.feed(response.text)
    assert len(header.labels) == 1
    label = header.labels[0]
    assert label["text"] == BUILD_LABEL
    assert label["text"].startswith(f"v{__version__} · ")
    assert label["attrs"]["data-build-id"] == BUILD_ID
    if SOURCE_COMMIT:
        assert SOURCE_COMMIT[:7] in label["text"]
        assert SOURCE_COMMIT in label["attrs"]["title"]
    else:
        assert "Quellstand" in label["text"]
    assert all(path in header.links for path in ("/", "/knowledge", "/data", "/map"))


def _page_label(tmp_path, monkeypatch):
    from http_ui_client import UIClient
    from threaddesk.api.service import ThreadService
    from threaddesk.storage.json_store import JsonStore
    from threaddesk.ui.server import create_app

    monkeypatch.setenv("THREADDESK_HOME", str(tmp_path))
    monkeypatch.setenv("THREADDESK_STORAGE", "json")
    ThreadService(store=JsonStore(tmp_path)).create("Headerprüfung")
    response = UIClient(create_app()).get("/")
    assert response.status_code == 200
    header = Header()
    header.feed(response.text)
    assert len(header.labels) == 1
    return header.labels[0]["text"]


def test_frozen_build_shows_executable_checksum(tmp_path, monkeypatch):
    program = tmp_path / "ThreadDesk"
    payload = b"frozen-build-bytes"
    program.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()[:8]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(program))

    text = _page_label(tmp_path / "home", monkeypatch)

    assert text == f"{BUILD_LABEL} · {expected}"
    assert text.startswith(f"v{__version__} · ")
    assert ("Quellstand" in text) or (SOURCE_COMMIT[:7] in text)
    program.unlink()
    from threaddesk.build_info import visible_build_label
    assert visible_build_label() == text


def test_source_checkout_shows_no_invented_checksum(tmp_path, monkeypatch):
    decoy = tmp_path / "not-the-program"
    payload = b"do-not-invent-a-checksum"
    decoy.write_bytes(payload)
    invented = hashlib.sha256(payload).hexdigest()[:8]
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(sys, "executable", str(decoy))

    text = _page_label(tmp_path / "home", monkeypatch)

    assert text == BUILD_LABEL
    assert invented not in text


def test_frozen_unreadable_program_leaves_header_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "missing-program"))

    text = _page_label(tmp_path / "home", monkeypatch)

    assert text == BUILD_LABEL
