"""Label retained source snapshots and distinguish their proven record lineage."""
import json
from pathlib import Path


def _source_receipts(library_root):
    from threaddesk.services.library_files.state import check_path, fail
    path = Path(library_root).parent / "library-batch-sources.json"
    check_path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > 16 * 1024 * 1024:
        fail("file_state_limit", "Source receipts exceed the size limit")
    try:
        sources = json.loads(path.read_text())["sources"]
        if not isinstance(sources, dict):
            raise ValueError("source shape")
        return sources
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("source_receipts_unreadable") from exc


def version_state(library_root):
    """Only current/history identities affect the indexed version projection.

    Receipt checkpoints, activity evidence and observation times are technical
    provenance; rewriting those does not change any version label.
    """
    sources = _source_receipts(library_root)
    try:
        current = {row.get("record_id") for row in sources.values() if isinstance(row, dict)}
        historical = set()
        for row in sources.values():
            if not isinstance(row, dict):
                continue
            history = row.get('history', [])
            if not isinstance(history, list) or any(not isinstance(value, str) for value in history):
                raise ValueError('source history shape')
            historical.update(history)
        current.discard(None)
        if any(not isinstance(value, str) for value in current):
            raise ValueError('source identity shape')
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError("source_receipts_unreadable") from exc
    return sorted(current), sorted(historical)


def annotate_versions(records, library_root):
    current, historical = version_state(library_root)
    current, historical = set(current), set(historical)
    return [{**row, "current_version": bool(row.get("copied_from"))
             or row["id"] in current or row["id"] not in historical} for row in records]


def confirmed_predecessors(record, library_root):
    """IDs from the same durable current/history receipt, never name heuristics.

    Copies are independent namespace entries. Only a source's current record
    can share its logical path with that source's retained historical records.
    Histories from unrelated receipts are never joined transitively.
    """
    if record.get("copied_from"):
        return frozenset()
    sources = _source_receipts(library_root)
    previous = set()
    for receipt in sources.values():
        if not isinstance(receipt, dict) or receipt.get("record_id") != record["id"]:
            continue
        history = receipt.get("history", [])
        if not isinstance(history, list) or any(not isinstance(value, str) for value in history):
            raise ValueError("source_receipts_unreadable")
        previous.update(history)
    previous.discard(record["id"])
    return frozenset(previous)
