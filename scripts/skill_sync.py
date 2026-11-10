#!/usr/bin/env python3
"""Central, versioned skill source for Claude, Codex and Grok.

ThreadDesk's library is the source: every file is a content-addressed blob with
a record version, and MANIFEST.json (its record version is the release number)
lists all files with SHA-256 and date. `export` copies a release to
ROOT/releases/rN and points ROOT/current at it; CLI entries point at `current`,
so the last export keeps working without ThreadDesk (local fallback) and
`rollback` only switches the link. Every replaced CLI entry is moved to
ROOT/backups/STAMP first; `restore STAMP` puts it back.

Entries per CLI come from targets.json in the source: mode "link" is a
directory symlink (Codex, Grok load it), mode "entry" a generated small
SKILL.md with the canonical frontmatter (Claude).

    PYTHONPATH=src python scripts/skill_sync.py publish DIR   # import + export
    python scripts/skill_sync.py export [--release N]
    python scripts/skill_sync.py rollback [--to N]
    python scripts/skill_sync.py restore STAMP
    python scripts/skill_sync.py status
Only `publish` and `export` need ThreadDesk; the rest is stdlib only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys

THREAD = "Big Plan · Skill-Quelle"
MANIFEST = "MANIFEST.json"
SCHEMA = "threaddesk.skill-source.v1"
HOME = Path.home()
DEFAULT_ROOT = HOME / ".local/share/threaddesk-skills"
DEFAULT_WORKSPACE = HOME / ".local/share/threaddesk/kirabridge-operator"


class SyncError(Exception):
    pass


def frontmatter(text: str) -> tuple[str, dict]:
    if not text.startswith("---\n") or (end := text.find("\n---\n", 3)) < 0:
        raise SyncError("frontmatter missing")
    block, fields, key = text[4:end], {}, None
    for line in block.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] = (fields[key] + " " + line.strip()).strip()
            continue
        name, sep, value = line.partition(":")
        if sep:
            key, value = name.strip(), value.strip()
            fields[key] = "" if value in (">", "|", ">-", "|-") else value.strip("\"'")
    return block, fields


def check_skill(folder: Path) -> None:
    _, fields = frontmatter((folder / "SKILL.md").read_text(encoding="utf-8"))
    if fields.get("name") != folder.name or not fields.get("description"):
        raise SyncError(f"{folder.name}: name/description invalid")


def _safe(rel: str) -> str:
    pure = PurePosixPath(rel)
    if pure.is_absolute() or not pure.parts or any(p in ("", ".", "..") for p in pure.parts):
        raise SyncError(f"unsafe path: {rel}")
    return pure.as_posix()


# --- ThreadDesk library (publish/export only) ---------------------------------

def _library(workspace: Path):
    if not (workspace / "threads").is_dir():
        raise SyncError(f"ThreadDesk workspace missing: {workspace}")
    from threaddesk.services.library_import import LibraryImporter
    from threaddesk.storage.json_store import JsonStore
    return LibraryImporter(JsonStore(workspace))


def _thread(store):
    from threaddesk.core.models import new_thread
    wanted = " ".join(THREAD.casefold().split())
    for thread in store.list_threads(include_archived=True):
        if " ".join(thread.title.casefold().split()) == wanted:
            return thread
    thread = new_thread(THREAD, "Zentrale, versionierte Skill-Quelle für Claude, Codex und Grok "
                                "(scripts/skill_sync.py).")
    store.save_thread(thread)  # deliberately no switch of the current thread
    return thread


def _import(lib, staging: Path, thread_id: str) -> dict:
    summary = lib.import_tree(staging)
    rows = {row["relative_path"]: row for row in summary["results"]}
    bad = [f"{k}: {v['error'] or v['thread_title']}" for k, v in rows.items()
           if v["status"] not in ("stored", "duplicate") or v["thread_id"] != thread_id]
    if bad:
        raise SyncError("library import failed: " + "; ".join(bad))
    return rows


def _manifest(lib, release: int | None = None) -> tuple[int, dict]:
    origin = f"{THREAD}/{MANIFEST}"
    found = {int(r["version"]): r["id"] for r in lib.catalog()["records"]
             if r.get("origin_path") == origin}
    if not found or (release is not None and release not in found):
        raise SyncError(f"no release {release or ''} in ThreadDesk".replace("  ", " "))
    version = release if release is not None else max(found)
    blob, _ = lib.open_record(found[version])
    return version, json.loads(blob.read_text(encoding="utf-8"))


def publish(src: Path, workspace: Path, root: Path, home: Path) -> dict:
    from threaddesk.services.library_import import _FORMATS
    src = src.resolve()
    files = sorted(p for p in src.rglob("*") if p.is_file()
                   and not any(part.startswith(".") for part in p.relative_to(src).parts))
    targets = json.loads((src / "targets.json").read_text(encoding="utf-8"))
    for skill in {s for spec in targets.values() for s in spec["skills"]}:
        check_skill(src / skill)
    lib = _library(workspace)
    thread = _thread(lib.store)
    staging = root / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    stored = {}
    for path in files:
        rel = path.relative_to(src).as_posix()
        stored[rel] = rel if path.suffix.casefold() in _FORMATS else rel + ".txt"
        out = staging / THREAD / stored[rel]
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, out)
    rows = _import(lib, staging, thread.id)
    entries = {rel: {"record": rows[f"{THREAD}/{name}"]["record_id"],
                     "sha256": rows[f"{THREAD}/{name}"]["sha256"],
                     "mode": "755" if os.access(src / rel, os.X_OK) else "644"}
               for rel, name in stored.items()}
    try:
        latest, previous = _manifest(lib)
        same = {k: (v["sha256"], v["mode"]) for k, v in previous["files"].items()}
        if same == {k: (v["sha256"], v["mode"]) for k, v in entries.items()}:
            shutil.rmtree(staging, ignore_errors=True)
            return {"release": latest, "unchanged": True, **export(workspace, root, home, latest)}
    except SyncError:
        pass
    manifest = {"schema": SCHEMA, "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "thread_id": thread.id, "files": entries}
    shutil.rmtree(staging)
    (staging / THREAD).mkdir(parents=True)
    (staging / THREAD / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
    row = _import(lib, staging, thread.id)[f"{THREAD}/{MANIFEST}"]
    shutil.rmtree(staging, ignore_errors=True)
    release, _ = _manifest(lib)
    return {"release": release, "unchanged": False, "manifest_sha256": row["sha256"],
            **export(workspace, root, home, release)}


def export(workspace: Path, root: Path, home: Path, release: int | None = None) -> dict:
    lib = _library(workspace)
    version, manifest = _manifest(lib, release)
    target = root / "releases" / f"r{version}"
    if not target.is_dir():
        tmp = root / "releases" / f".r{version}.tmp"
        shutil.rmtree(tmp, ignore_errors=True)
        for rel, item in manifest["files"].items():
            blob, _ = lib.open_record(item["record"])
            data = blob.read_bytes()
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise SyncError(f"integrity: {rel}")
            out = tmp / _safe(rel)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            out.chmod(int(item["mode"], 8))
        info = {"release": version, "date": manifest["date"], "source": f"ThreadDesk {workspace}",
                "thread_id": manifest["thread_id"],
                "files": {k: v["sha256"] for k, v in manifest["files"].items()}}
        (tmp / "release.json").write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        os.rename(tmp, target)
    _switch(root, version)
    return {"current": version, "changed": install(root, home)}


# --- local only: switch, entries, rollback, restore, status --------------------

def _current(root: Path) -> int:
    link = root / "current"
    if not link.is_symlink():
        raise SyncError("no exported release")
    return int(Path(os.readlink(link)).name[1:])


def _switch(root: Path, version: int) -> None:
    if not (root / "releases" / f"r{version}").is_dir():
        raise SyncError(f"release r{version} not exported locally")
    tmp = root / ".current.tmp"
    if tmp.is_symlink():
        tmp.unlink()
    os.symlink(f"releases/r{version}", tmp)
    os.replace(tmp, root / "current")


def entry_text(root: Path, skill: str) -> str:
    block, _ = frontmatter((root / "current" / skill / "SKILL.md").read_text(encoding="utf-8"))
    return (f"---\n{block}\n---\n# {skill} — Einstieg\n\n"
            f"Zentrale Fassung: `{root}/current/{skill}/SKILL.md`. Vor der Arbeit vollständig lesen, "
            "Nebendateien im selben Ordner nach Bedarf. Quelle ist die ThreadDesk-Skill-Quelle; "
            "diese Datei erzeugt `scripts/skill_sync.py`. Änderungen nur dort veröffentlichen.\n")


def _wanted(root: Path, mode: str, skill: str) -> str:
    return str(root / "current" / skill) if mode == "link" else entry_text(root, skill)


def _matches(path: Path, mode: str, want: str) -> bool:
    if mode == "link":
        return path.is_symlink() and os.readlink(path) == want
    return (path.is_dir() and not path.is_symlink() and os.listdir(path) == ["SKILL.md"]
            and (path / "SKILL.md").read_text(encoding="utf-8") == want)


def _stash(path: Path, backup: Path, key: str) -> None:
    if not (path.is_symlink() or path.exists()):
        return
    dest = backup / key
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.rename(path, dest)
    index = backup / "index.json"
    data = json.loads(index.read_text(encoding="utf-8")) if index.exists() else {}
    data[key] = str(path)
    index.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


def _place(path: Path, mode: str, want: str) -> None:
    if mode == "link":
        os.symlink(want, path)
    else:
        path.mkdir()
        (path / "SKILL.md").write_text(want, encoding="utf-8")


def _backup_dir(root: Path) -> Path:
    return root / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def install(root: Path, home: Path) -> list[str]:
    targets = json.loads((root / "current" / "targets.json").read_text(encoding="utf-8"))
    backup, changed = _backup_dir(root), []
    for cli, spec in targets.items():
        base = home / spec["dir"]
        base.mkdir(parents=True, exist_ok=True)
        for skill in spec["skills"]:
            path, want = base / skill, _wanted(root, spec["mode"], skill)
            if _matches(path, spec["mode"], want):
                continue
            _stash(path, backup, f"{cli}/{skill}")
            _place(path, spec["mode"], want)
            changed.append(f"{cli}/{skill}")
    return changed


def rollback(root: Path, home: Path, to: int | None = None) -> dict:
    current = _current(root)
    have = sorted(int(p.name[1:]) for p in (root / "releases").glob("r*") if p.is_dir())
    older = [v for v in have if v < current]
    target = to if to is not None else (older[-1] if older else None)
    if target is None:
        raise SyncError(f"no release older than r{current}")
    _switch(root, target)
    return {"from": current, "current": target, "changed": install(root, home)}


def restore(root: Path, stamp: str) -> list[str]:
    backup = root / "backups" / stamp
    index = json.loads((backup / "index.json").read_text(encoding="utf-8"))
    safety, restored = _backup_dir(root), []
    for key, original in index.items():
        path = Path(original)
        _stash(path, safety, key)
        os.rename(backup / key, path)
        restored.append(key)
    return restored


def status(root: Path, home: Path) -> dict:
    problems, current = [], None
    try:
        current = _current(root)
        targets = json.loads((root / "current" / "targets.json").read_text(encoding="utf-8"))
    except (SyncError, OSError, ValueError) as exc:
        return {"current": current, "problems": [str(exc)]}
    for cli, spec in targets.items():
        for skill in spec["skills"]:
            path = home / spec["dir"] / skill
            try:
                check_skill(root / "current" / skill)
                if not _matches(path, spec["mode"], _wanted(root, spec["mode"], skill)):
                    problems.append(f"{cli}/{skill}: entry differs from current")
                elif not (path / "SKILL.md").is_file():
                    problems.append(f"{cli}/{skill}: SKILL.md unreadable")
            except (SyncError, OSError) as exc:
                problems.append(f"{cli}/{skill}: {exc}")
    return {"current": current, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--home", type=Path, default=HOME)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("publish").add_argument("source", type=Path)
    sub.add_parser("export").add_argument("--release", type=int)
    sub.add_parser("rollback").add_argument("--to", type=int)
    sub.add_parser("restore").add_argument("stamp")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    root = args.root.expanduser().absolute()
    try:
        if args.action == "publish":
            result = publish(args.source, args.workspace, root, args.home)
        elif args.action == "export":
            result = export(args.workspace, root, args.home, args.release)
        elif args.action == "rollback":
            result = rollback(root, args.home, args.to)
        elif args.action == "restore":
            result = {"restored": restore(root, args.stamp)}
        else:
            result = status(root, args.home)
    except Exception as exc:  # one JSON error line; the local release stays untouched
        try:
            kept = f"local release r{_current(root)} stays active"
        except SyncError:
            kept = "no local release"
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}", "fallback": kept},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 1 if result.get("problems") else 0


if __name__ == "__main__":
    sys.exit(main())
