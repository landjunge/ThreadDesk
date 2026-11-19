"""Refresh derived projections after writes or explicit runtime recovery only."""

from contextlib import contextmanager

from threaddesk.services.library_files.state import check_path
from threaddesk.services.library_import import LibraryImporter
from threaddesk.services.library_index import LibraryIndex

# Workspaces whose running LibraryRuntime owns the rebuild after a write.
_DEFERRED: set[str] = set()


@contextmanager
def deferred_to_runtime(workspace):
    """A serial caller marks the index stale only; its runtime rebuilds it.

    One full rebuild reads every thread and record. Doing it inside a serial
    request loop delays every following receipt by that rebuild.
    """
    key = str(workspace)
    _DEFERRED.add(key)
    try:
        yield
    finally:
        _DEFERRED.discard(key)


def refresh_existing(store, *, initialize=False):
    """Keep reads inert; runtime may initialize a pre-existing CAS library.

    ``initialize`` authorizes rebuilding derived state, not discovering original
    folders, registering watches or creating a library in an empty profile.
    """
    importer = LibraryImporter(store)
    index = LibraryIndex(importer.root)
    try:
        check_path(importer.root, directory=True)
        check_path(importer.records, directory=True)
        if importer.records.is_dir():
            for record in importer.records.glob("*.json"):
                check_path(record)
        if not index.path.exists():
            if not initialize or not importer.records.is_dir():
                return {"status": "not_initialized"}
            if not importer._read_records():
                return {"status": "not_initialized"}
        # A failed post-commit refresh must not present old results as current.
        prior = index._read()
        current = index.status()
        if (current['status'] == 'ready'
                and (prior or {}).get('workspace_projected') is True):
            return current
        if prior:
            index._replace({**prior, "status": "stale", "error": "canonical_change"})
        if not initialize and str(store.workspace_path) in _DEFERRED:
            return {"status": "stale", "error": "canonical_change"}
        # Old CAS libraries and restored profiles may predate file-node support.
        # Commit their reconstructible graph projection before its index snapshot.
        from threaddesk.services.library_links import sync_file_nodes

        sync_file_nodes(store)
        return index.rebuild(importer._read_records(), importer.blobs, store=store)
    except Exception as exc:  # noqa: BLE001 -- isolate optional background projection failures
        # A recovery/projection failure must neither undo an action nor claim
        # an unreadable index is healthy. Runtime exposes this retryable state.
        return {"status": "stale", "error": type(exc).__name__}
