"""Derived full-text index beside a JSON workspace, never inside it.

The JSON files stay canonical. ``<workspace>.search.sqlite`` can be deleted and
built again. Reads go straight to the files. ``get_thread`` is not used, and
neither ``.append.lock`` nor ``.management.lock`` is taken. The FTS table is
contentless: trigram search needs the folded tokens, and the snippet is cut
from the JSON file when a hit is returned.

Reuses ``SearchError`` and ``identifier`` from the local-search modules, and the
same idea as ``SQLiteSearchAdapter`` of reporting a missing FTS module instead
of inventing matches. The canonical SQLite FTS stays the thread-field index of
a SQLite workspace. This file is the whiteboard index for a JSON workspace.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from threaddesk.core.search import SearchError
from threaddesk.storage.search_source import identifier


def _regular(path):
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode)

ENTRY_FTS_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS search_body USING fts5("
    "body, content='', contentless_delete=1, tokenize='trigram')"
)
_META = (
    "CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
)
_MANIFEST = """CREATE TABLE IF NOT EXISTS thread_manifest(
 thread_id TEXT PRIMARY KEY, entry_count INTEGER NOT NULL, byte_count INTEGER NOT NULL,
 manifest_hash TEXT NOT NULL, status TEXT NOT NULL, problem_count INTEGER NOT NULL)"""
_DOCS = """CREATE TABLE IF NOT EXISTS entry_doc(
 row_key TEXT PRIMARY KEY, thread_id TEXT NOT NULL, entry_id TEXT NOT NULL,
 ordinal INTEGER, field TEXT NOT NULL, actor TEXT NOT NULL, entry_type TEXT NOT NULL,
 created_at TEXT NOT NULL, source_hash TEXT NOT NULL, source_rel TEXT NOT NULL,
 status TEXT NOT NULL, fts_rowid INTEGER NOT NULL)"""
_DOC_THREAD = "CREATE INDEX IF NOT EXISTS entry_doc_thread ON entry_doc(thread_id)"


@dataclass(frozen=True)
class EntryHit:
    thread_id: str
    entry_id: str
    ordinal: int | None
    field: str
    actor: str
    entry_type: str
    created_at: str
    title: str
    snippet: str
    start: int
    end: int
    source_hash: str


@dataclass
class EntryPage:
    hits: list
    mode: str = "fts5"
    complete: bool = False
    reasons: list | None = None
    next_cursor: str | None = None
    generation: str = ""

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


class EntryIndex:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_dir() or self.root.is_symlink():
            raise SearchError("source_unreadable_or_over_limit")
        self.path = Path(str(self.root) + ".search.sqlite")
        if self.root in self.path.parents or self.path == self.root:
            raise SearchError("source_unreadable_or_over_limit")
        self._db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        for statement in (_META, _MANIFEST, _DOCS, _DOC_THREAD):
            self._db.execute(statement)
        self._fts = self._prepare_fts()

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None

    def remove(self):
        self.close()
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self.path) + suffix)
            if path.is_file() and not path.is_symlink():
                path.unlink()

    def scan(self, *, abort_thread=None, deadline=None):
        if not self._fts:
            return self.status()
        self._meta("complete", "0")
        self._meta("generation", "")
        on_disk = set(self._thread_ids())
        stored = {row[0] for row in self._db.execute("SELECT thread_id FROM thread_manifest")}
        for thread_id in sorted(on_disk | stored):
            if deadline is not None and monotonic() >= deadline:
                return {**self.status(), "rebuilding": True}
            if thread_id not in on_disk:
                self._transaction(lambda gone=thread_id: self._delete_thread(gone))
                continue
            manifest = self._manifest(thread_id)
            if self._current(thread_id) == manifest[:3]:
                continue
            self._transaction(
                lambda current=thread_id, found=manifest: self._write_thread(current, found),
                abort=abort_thread == thread_id,
            )
        self._meta("generation", self._fingerprint())
        self._meta("complete", "1" if self._fts and not self.check() else "0")
        return self.status()

    def query(self, text, *, limit=20, cursor=None, thread_id=None, actor=None,
              entry_type=None, since=None, until=None, include_archived=False, sort="rank"):
        self._arguments(text, limit, thread_id, actor, entry_type, since, until, include_archived, sort)
        if not self._fts:
            return EntryPage(hits=[], mode="fts_unavailable", complete=False,
                             reasons=["fts_unavailable"], generation=self._generation())
        terms = text.split()
        if any(len(term.casefold()) < 3 for term in terms):
            return EntryPage(hits=[], mode="fts5", complete=False, reasons=["query_too_short"],
                             generation=self._generation())
        match = " AND ".join('"' + term.casefold().replace('"', '""') + '"' for term in terms)
        generation = self._generation()
        keyset = self._keyset(cursor, generation, sort)
        sql = (
            "SELECT entry_doc.row_key, entry_doc.thread_id, entry_doc.entry_id, entry_doc.ordinal,"
            " entry_doc.field, entry_doc.actor, entry_doc.entry_type, entry_doc.created_at,"
            " entry_doc.source_hash, entry_doc.source_rel, bm25(search_body) "
            "FROM entry_doc JOIN search_body ON search_body.rowid = entry_doc.fts_rowid "
            "WHERE search_body MATCH ?"
        )
        params = [match]
        if thread_id is not None:
            sql += " AND entry_doc.thread_id=?"
            params.append(thread_id)
        if actor is not None:
            sql += " AND entry_doc.actor=?"
            params.append(actor)
        if entry_type is not None:
            sql += " AND entry_doc.entry_type=?"
            params.append(entry_type)
        if since is not None:
            sql += " AND entry_doc.created_at>=?"
            params.append(since)
        if until is not None:
            sql += " AND entry_doc.created_at<=?"
            params.append(until)
        if not include_archived:
            sql += " AND entry_doc.status!='archived'"
        if keyset is not None:
            sql += " AND " + keyset[0]
            params.extend(keyset[1])
        if sort == "newest":
            sql += " ORDER BY entry_doc.created_at DESC, entry_doc.row_key DESC"
        else:
            sql += " ORDER BY bm25(search_body), entry_doc.row_key"
        sql += " LIMIT ?"
        params.append(limit + 1)
        try:
            rows = self._db.execute(sql, params).fetchall()
        except sqlite3.OperationalError as exc:
            raise SearchError("fts_unavailable") from exc
        extra = len(rows) > limit
        chosen = rows[:limit]
        hits = []
        titles = {}
        for row in chosen:
            snippet, start, end = self._snippet(row[1], row[9], row[4], terms)
            if row[1] not in titles:
                titles[row[1]] = self._title(row[1])
            hits.append(EntryHit(
                row[1], row[2], row[3], row[4], row[5], row[6], row[7], titles[row[1]],
                snippet, start, end, row[8],
            ))
        nxt = None
        if extra and chosen:
            last = chosen[-1]
            sort_value = last[7] if sort == "newest" else last[10]
            nxt = json.dumps(
                [generation, sort, sort_value, last[0]], separators=(",", ":"), ensure_ascii=False
            )
        # ``complete`` is the last finished scan. ``check`` reports later drift.
        complete = self._fts and self._meta_get("complete") == "1"
        return EntryPage(hits=hits, mode="fts5", complete=complete, next_cursor=nxt, generation=generation)

    def check(self):
        stored = {
            row[0]: row[1:]
            for row in self._db.execute(
                "SELECT thread_id, entry_count, byte_count, manifest_hash, problem_count FROM thread_manifest"
            )
        }
        problems = []
        seen = set()
        for thread_id in self._thread_ids():
            seen.add(thread_id)
            current = self._manifest(thread_id)
            row = stored.get(thread_id)
            if row is None:
                problems.append({"thread_id": thread_id, "problem": "missing"})
            elif row[:3] != current[:3]:
                problems.append({"thread_id": thread_id, "problem": "mismatch"})
            elif row[3]:
                problems.append({"thread_id": thread_id, "problem": "unreadable"})
        for thread_id in stored:
            if thread_id not in seen:
                problems.append({"thread_id": thread_id, "problem": "stale"})
        problems.sort(key=lambda item: (item["thread_id"], item["problem"]))
        return problems

    def status(self):
        mode = "fts5" if self._fts else "fts_unavailable"
        manifests = {
            row[0]: row[1]
            for row in self._db.execute("SELECT thread_id, manifest_hash FROM thread_manifest")
        }
        complete = bool(self._fts and self._meta_get("complete") == "1")
        reasons = [] if self._fts else ["fts_unavailable"]
        return {
            "mode": mode,
            "complete": complete,
            "generation": self._generation(),
            "manifests": manifests,
            "reasons": reasons,
            "path": str(self.path),
        }

    def _prepare_fts(self):
        try:
            self._db.execute(ENTRY_FTS_SQL)
        except sqlite3.OperationalError:
            self._meta("fts", "unavailable")
            self._meta("complete", "0")
            return False
        self._meta("fts", "ok")
        return True

    def _meta(self, key, value):
        self._db.execute("INSERT OR REPLACE INTO index_meta(key, value) VALUES(?, ?)", (key, value))

    def _meta_get(self, key):
        row = self._db.execute("SELECT value FROM index_meta WHERE key=?", (key,)).fetchone()
        return "" if row is None else row[0]

    def _generation(self):
        return self._meta_get("generation")

    def _fingerprint(self):
        digest = hashlib.sha256()
        rows = self._db.execute(
            "SELECT thread_id, manifest_hash FROM thread_manifest ORDER BY thread_id"
        )
        for thread_id, manifest_hash in rows:
            digest.update(f"{thread_id}\0{manifest_hash}\n".encode())
        return digest.hexdigest()

    def _trashed(self):
        """Thread ids that currently sit in the trash. Their files stay under threads/."""
        folder = self.root / "trash"
        if not folder.is_dir() or folder.is_symlink():
            return set()
        gone = set()
        for entry in os.scandir(folder):
            if not entry.name.startswith("thread-") or not entry.name.endswith(".json"):
                continue
            if not _regular(entry.path):
                continue
            try:
                data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if (
                isinstance(data, dict)
                and data.get("kind") == "thread"
                and data.get("state") == "trashed"
                and isinstance(data.get("object_id"), str)
            ):
                gone.add(data["object_id"])
        return gone

    def _thread_ids(self):
        folder = self.root / "threads"
        if not folder.is_dir() or folder.is_symlink():
            return []
        trashed = self._trashed()
        found = []
        for entry in os.scandir(folder):
            if not entry.name.endswith(".json") or not _regular(entry.path):
                continue
            thread_id = entry.name[:-5]
            try:
                identifier(thread_id)
            except SearchError:
                continue
            if thread_id in trashed:
                continue
            found.append(thread_id)
        return sorted(found)

    def _manifest(self, thread_id):
        parts = []
        thread_path = self.root / "threads" / f"{thread_id}.json"
        info = self._file_info(thread_path)
        if info is None:
            raise SearchError("source_unreadable_or_over_limit")
        parts.append(info)
        board = self.root / "whiteboard" / thread_id
        if board.is_dir() and not board.is_symlink():
            for entry in os.scandir(board):
                if not entry.name.endswith(".json") or entry.name.startswith("."):
                    continue
                if not _regular(entry.path):
                    continue
                info = self._file_info(Path(entry.path))
                if info is not None:
                    parts.append(info)
        parts.sort()
        digest = hashlib.sha256()
        digest.update(b"entry-manifest-v1\n")
        total = 0
        entries = 0
        for rel, size, mtime in parts:
            digest.update(f"{rel}\0{size}\0{mtime}\n".encode())
            total += size
            if rel.startswith("whiteboard/"):
                entries += 1
        return (entries, total, digest.hexdigest(), self._status_of(thread_path))

    def _current(self, thread_id):
        row = self._db.execute(
            "SELECT entry_count, byte_count, manifest_hash FROM thread_manifest WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        return None if row is None else tuple(row)

    def _transaction(self, write, *, abort=False):
        self._db.execute("BEGIN IMMEDIATE")
        try:
            write()
            if abort:
                raise RuntimeError("index_abort")
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise

    def _delete_thread(self, thread_id):
        for (rowid,) in self._db.execute("SELECT fts_rowid FROM entry_doc WHERE thread_id=?", (thread_id,)):
            self._db.execute("DELETE FROM search_body WHERE rowid=?", (rowid,))
        self._db.execute("DELETE FROM entry_doc WHERE thread_id=?", (thread_id,))
        self._db.execute("DELETE FROM thread_manifest WHERE thread_id=?", (thread_id,))

    def _write_thread(self, thread_id, manifest):
        self._delete_thread(thread_id)
        problems = self._problem_count(thread_id)
        records = self._records(thread_id) if problems == 0 else []
        next_row = self._db.execute("SELECT COALESCE(MAX(fts_rowid), 0) FROM entry_doc").fetchone()[0]
        for record in records:
            next_row += 1
            folded = record["text"].casefold()
            if not folded:
                continue
            self._db.execute("INSERT INTO search_body(rowid, body) VALUES(?, ?)", (next_row, folded))
            self._db.execute(
                "INSERT INTO entry_doc(row_key, thread_id, entry_id, ordinal, field, actor, entry_type,"
                " created_at, source_hash, source_rel, status, fts_rowid) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["row_key"], thread_id, record["entry_id"], record["ordinal"], record["field"],
                    record["actor"], record["entry_type"], record["created_at"], record["source_hash"],
                    record["source_rel"], manifest[3], next_row,
                ),
            )
        self._db.execute(
            "INSERT INTO thread_manifest("
            "thread_id, entry_count, byte_count, manifest_hash, status, problem_count) "
            "VALUES(?,?,?,?,?,?)",
            (thread_id, manifest[0], manifest[1], manifest[2], manifest[3], problems),
        )

    def _problem_count(self, thread_id):
        problems = 0
        thread = self._json(self.root / "threads" / f"{thread_id}.json")
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            return 1
        board = self.root / "whiteboard" / thread_id
        if not board.is_dir() or board.is_symlink():
            return 0
        for entry in os.scandir(board):
            if not entry.name.endswith(".json") or not _regular(entry.path):
                continue
            data = self._json(Path(entry.path))
            if not isinstance(data, dict):
                problems += 1
                continue
            same_id = data.get("id") == entry.name[:-5]
            same_thread = data.get("thread_id") == thread_id
            if not same_id or not same_thread:
                problems += 1
        return problems

    def _records(self, thread_id):
        path = self.root / "threads" / f"{thread_id}.json"
        data = self._json(path)
        if not isinstance(data, dict) or data.get("id") != thread_id:
            return []
        context = data.get("context") if isinstance(data.get("context"), dict) else {}
        notes = context.get("notes") if isinstance(context.get("notes"), str) else ""
        created = data.get("created_at") if isinstance(data.get("created_at"), str) else ""
        rel = f"threads/{thread_id}.json"
        rows = [
            self._record(thread_id, "", None, "title", "", "", created, data.get("title") or "", rel),
            self._record(thread_id, "", None, "description", "", "", created, data.get("description") or "", rel),
            self._record(thread_id, "", None, "notes", "", "", created, notes, rel),
        ]
        board = self.root / "whiteboard" / thread_id
        if board.is_dir() and not board.is_symlink():
            for entry in sorted(os.scandir(board), key=lambda item: item.name):
                if not entry.name.endswith(".json") or not _regular(entry.path):
                    continue
                payload = self._json(Path(entry.path))
                if not isinstance(payload, dict) or payload.get("thread_id") != thread_id:
                    continue
                entry_id = payload.get("id")
                if entry_id != Path(entry.name).stem:
                    continue
                ordinal = payload.get("ordinal") if type(payload.get("ordinal")) is int else None
                actor = payload.get("actor") if isinstance(payload.get("actor"), str) else ""
                kind = payload.get("entry_type") if isinstance(payload.get("entry_type"), str) else ""
                when = payload.get("created_at") if isinstance(payload.get("created_at"), str) else ""
                content = payload.get("content") if isinstance(payload.get("content"), str) else ""
                rows.append(self._record(
                    thread_id, entry_id, ordinal, "content", actor, kind, when, content,
                    f"whiteboard/{thread_id}/{entry.name}",
                ))
        return [row for row in rows if row is not None]

    def _record(self, thread_id, entry_id, ordinal, field, actor, entry_type, created_at, text, source_rel):
        if not isinstance(text, str) or not text.strip():
            return None
        return {
            "row_key": f"{thread_id}\t{field}\t{entry_id or '-'}",
            "entry_id": entry_id,
            "ordinal": ordinal,
            "field": field,
            "actor": actor,
            "entry_type": entry_type,
            "created_at": created_at,
            "text": text,
            "source_hash": hashlib.sha256(text.encode()).hexdigest(),
            "source_rel": source_rel,
        }

    def _snippet(self, thread_id, source_rel, field, terms):
        path = self._inside(source_rel)
        data = self._json(path) if path is not None else None
        text = ""
        if isinstance(data, dict):
            if field == "title":
                text = data.get("title") or ""
            elif field == "description":
                text = data.get("description") or ""
            elif field == "notes":
                context = data.get("context") if isinstance(data.get("context"), dict) else {}
                text = context.get("notes") or ""
            elif field == "content":
                text = data.get("content") or ""
        if not isinstance(text, str):
            text = ""
        folded = text.casefold()
        at = 0
        for term in terms:
            found = folded.find(term.casefold())
            if found >= 0:
                at = found
                break
        if len(folded) != len(text):
            at = 0
        start = max(0, at - 60)
        snippet = text[start:start + 240]
        return snippet, start, start + len(snippet)

    def _title(self, thread_id):
        data = self._json(self.root / "threads" / f"{thread_id}.json")
        if isinstance(data, dict) and isinstance(data.get("title"), str):
            return data["title"][:240]
        return ""

    def _status_of(self, path):
        data = self._json(path)
        if isinstance(data, dict) and isinstance(data.get("status"), str):
            return data["status"]
        return ""

    def _json(self, path):
        if path is None or not path.is_file() or path.is_symlink():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None

    def _inside(self, source_rel):
        if not isinstance(source_rel, str) or source_rel.startswith("/") or ".." in Path(source_rel).parts:
            return None
        path = (self.root / source_rel).absolute()
        try:
            path.relative_to(self.root.absolute())
        except ValueError:
            return None
        return path

    def _file_info(self, path):
        try:
            info = path.lstat()
        except OSError:
            return None
        if not stat.S_ISREG(info.st_mode):
            return None
        rel = path.relative_to(self.root).as_posix()
        return (rel, info.st_size, info.st_mtime_ns)

    def _arguments(self, text, limit, thread_id, actor, entry_type, since, until, include_archived, sort):
        too_long = len(text.encode()) > 512 or len(text.split()) > 16
        if not isinstance(text, str) or not text.strip() or too_long:
            raise SearchError("invalid_search_query")
        if any(ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in text):
            raise SearchError("invalid_search_query")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise SearchError("invalid_search_query")
        if type(include_archived) is not bool or sort not in {"rank", "newest"}:
            raise SearchError("invalid_search_query")
        if thread_id is not None:
            identifier(thread_id)
        for value in (actor, entry_type, since, until):
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > 80 or any(ord(ch) < 32 for ch in value):
                raise SearchError("invalid_search_query")

    def _keyset(self, cursor, generation, sort):
        if cursor is None:
            return None
        if not isinstance(cursor, str) or len(cursor) > 2000:
            raise SearchError("cursor_expired")
        try:
            stored_generation, stored_sort, sort_value, row_key = json.loads(cursor)
        except (json.JSONDecodeError, ValueError, TypeError):
            raise SearchError("cursor_expired") from None
        if stored_sort != sort or not isinstance(row_key, str):
            raise SearchError("cursor_expired")
        if stored_generation != generation:
            raise SearchError("generation_changed")
        if sort == "newest":
            if not isinstance(sort_value, str):
                raise SearchError("cursor_expired")
            return (
                "(entry_doc.created_at<? OR (entry_doc.created_at=? AND entry_doc.row_key<?))",
                (sort_value, sort_value, row_key),
            )
        if isinstance(sort_value, bool) or not isinstance(sort_value, (int, float)):
            raise SearchError("cursor_expired")
        return (
            "(bm25(search_body)>? OR (bm25(search_body)=? AND entry_doc.row_key>?))",
            (float(sort_value), float(sort_value), row_key),
        )
