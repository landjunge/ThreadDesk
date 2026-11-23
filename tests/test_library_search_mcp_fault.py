"""Synthetic checks for the read-only MCP library search error boundary."""

import json
from hashlib import sha256

import pytest

from threaddesk.api.service import ThreadService
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex, LibrarySearchError
from threaddesk.services.mcp import McpBridge
from threaddesk.storage.json_store import JsonStore

HISTORICAL = "a" * 12
CURRENT = "b" * 12


def seed(workspace, scratch):
    svc = ThreadService(JsonStore(workspace))
    thread = svc.create("Synthetic library versions")
    empty = svc.create("Synthetic empty library")
    importer = LibraryImporter(svc.store)
    for identifier, text in (
        (HISTORICAL, b"fixturealpha archive"),
        (CURRENT, b"fixturebeta current"),
    ):
        staging = scratch / f"{identifier}.txt"
        staging.write_bytes(text)
        importer.receive_verified(
            staging,
            filename="fixture-revision.txt",
            thread_id=thread.id,
            record_id=identifier,
            sha256=sha256(text).hexdigest(),
            size=len(text),
        )
    # The existing reader only marks a retained predecessor when its source
    # receipt establishes the relationship. A repeated filename is insufficient.
    (workspace / "library-batch-sources.json").write_text(
        json.dumps(
            {
                "sources": {
                    "fixture-revision.txt": {
                        "record_id": CURRENT,
                        "history": [HISTORICAL],
                    }
                }
            }
        )
    )
    importer.rebuild_index()
    return svc, importer, thread.id, empty.id


@pytest.fixture
def library(tmp_path):
    return seed(tmp_path / "workspace", tmp_path)


def search(bridge, thread, query="fixturealpha"):
    return bridge.call("library_search", {"thread_id": thread, "query": query})


def test_current_and_historical_hits_and_real_stale_recovery(library):
    svc, importer, thread, empty = library
    reader = McpBridge(svc, allowed_scopes={"workspace.read"})
    tool = next(
        tool for tool in reader.list_tools() if tool["name"] == "library_search"
    )
    assert tool["annotations"]["readOnlyHint"] is True

    def version(query):
        result = search(reader, thread, query)
        assert result["ok"]
        (hit,) = result["result"]["hits"]
        return hit["record_id"], hit["version"], hit["current_version"]

    assert version("fixturealpha") == (HISTORICAL, 1, False)
    assert version("fixturebeta") == (CURRENT, 2, True)
    svc.set_note("Synthetic canonical-source change", thread)
    assert LibraryIndex(importer.root).status()["status"] == "stale"
    assert search(reader, thread) == {
        "ok": False,
        "isError": True,
        "error": "The saved library index is stale. Search is temporarily unavailable.",
        "code": "index_stale",
        "details": {},
    }
    assert search(reader, empty)["result"]["hits"] == []
    assert LibraryIndex(importer.root).status()["status"] == "stale"
    importer.rebuild_index()
    assert version("fixturealpha") == (HISTORICAL, 1, False)
    assert version("fixturebeta") == (CURRENT, 2, True)


@pytest.mark.parametrize("code", ["index_stale", "private_unknown_code"])
def test_search_failure_does_not_expose_raw_error(library, monkeypatch, code):
    svc, _, thread, _ = library

    def fail(*_, **__):
        error = LibrarySearchError(code)
        error.args = ("/private-fixture-path: raw peer diagnostic",)
        raise error

    monkeypatch.setattr(LibraryIndex, "search", fail)
    result = search(McpBridge(svc, allowed_scopes={"workspace.read"}), thread)
    assert result["isError"] and "private" not in str(result)
    if code == "index_stale":
        assert result["code"] == code
        assert result["details"] == {}
    else:
        assert result == {"ok": False, "isError": True, "error": "LibrarySearchError"}


def test_search_scope_guard_still_runs_before_index(library, monkeypatch):
    svc, _, thread, _ = library
    writer = McpBridge(svc, allowed_scopes={"workspace.write"})
    assert "library_search" not in {tool["name"] for tool in writer.list_tools()}

    def unexpected(*_, **__):
        pytest.fail("read permission must be checked before calling the index")

    monkeypatch.setattr(LibraryIndex, "search", unexpected)
    result = search(writer, thread)
    assert result["isError"] and result["code"] == "permission_required"
