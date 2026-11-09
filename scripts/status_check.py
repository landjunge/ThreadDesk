#!/usr/bin/env python3
"""Vergleicht ein STATUS.json (status-v1) mit GitHub (`gh`) und lokalen Pfaden.

Nur lesend, nur Standardbibliothek. Meldet Abweichungen, ändert nichts.

    python scripts/status_check.py --status STATUS.json
    python scripts/status_check.py --status ../KiraBridge/STATUS.json --ops-inventory ../KiraBridge/ops/netcup.json
    python scripts/status_check.py --offline          # nur Schema und lokale Pfade

Exit-Code: 0 = keine Abweichung (WARN/INFO erlaubt, mit --strict nicht), 1 = Abweichung, 2 = Datei/Aufruf unbrauchbar.
Vertrag: docs/contracts/status-v1.md.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, List, Tuple

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "status-v1.schema.json"
ERROR, WARN, INFO = "ERROR", "WARN", "INFO"
Finding = Tuple[str, str, str]  # (level, area, message)
Gh = Callable[[List[str]], str]


# ---------------------------------------------------------------- Schema

def _type_ok(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }[expected]


def validate(value: Any, schema: dict, root: dict | None = None, path: str = "$") -> list[str]:
    """Minimaler JSON-Schema-Prüfer (die hier genutzten Schlüsselwörter)."""
    root = root or schema
    if "$ref" in schema:
        node: Any = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate(value, node, root, path)
    errors: list[str] = []
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        return [f"{path}: erwartet {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} nicht in {schema['enum']}"]
    if "oneOf" in schema:
        results = [validate(value, s, root, path) for s in schema["oneOf"]]
        if sum(1 for r in results if not r) == 1:
            return []
        if not any(not r for r in results):
            detail = [r for sub, r in zip(schema["oneOf"], results) if "const" not in sub]
            if len(detail) == 1:  # einzige Nicht-"unknown"-Form: deren Fehler zeigen
                return detail[0]
        return [f"{path}: passt auf keine erlaubte Form"]
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{path}: erwartet {schema['type']}"]
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: zu kurz")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} passt nicht auf {schema['pattern']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: Pflichtfeld {key!r} fehlt")
        props = schema.get("properties", {})
        for key, sub in value.items():
            if key in props:
                errors += validate(sub, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unbekanntes Feld {key!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            errors += validate(item, schema["items"], root, f"{path}[{i}]")
    return errors


# ---------------------------------------------------------------- Hilfen

def parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def run_gh(args: list[str]) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60, check=False)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "gh fehlgeschlagen")
    return done.stdout


def _gh_json(gh: Gh, args: list[str]) -> Any:
    return json.loads(gh(args))


# ---------------------------------------------------------------- GitHub

def check_github(status: dict, gh: Gh, max_behind: int = 10) -> list[Finding]:
    out: list[Finding] = []
    repo = status["repo"]["name"]
    try:
        info = _gh_json(gh, ["repo", "view", repo, "--json", "visibility,defaultBranchRef"])
    except Exception as exc:  # noqa: BLE001 - Meldung an den Nutzer
        return [(ERROR, "github", f"{repo} nicht lesbar: {exc}")]
    if info["visibility"].lower() != status["repo"]["visibility"]:
        out.append((ERROR, "repo", f"Sichtbarkeit: Register {status['repo']['visibility']}, GitHub {info['visibility'].lower()}"))
    branch = info["defaultBranchRef"]["name"]
    if branch != status["repo"]["default_branch"]:
        out.append((ERROR, "repo", f"Standardbranch: Register {status['repo']['default_branch']}, GitHub {branch}"))

    pin = status["main_pin"]["commit"]
    try:
        cmp = _gh_json(gh, ["api", f"repos/{repo}/compare/{pin}...{branch}", "--jq", "{status: .status, ahead_by: .ahead_by}"])
    except Exception as exc:  # noqa: BLE001
        out.append((ERROR, "main_pin", f"Pin {pin[:12]} bei GitHub nicht prüfbar: {exc}"))
    else:
        if cmp["status"] in ("identical",):
            pass
        elif cmp["status"] == "ahead":
            level = WARN if cmp["ahead_by"] > max_behind else INFO
            out.append((level, "main_pin", f"{branch} liegt {cmp['ahead_by']} Commit(s) vor dem Pin {pin[:12]}"))
        else:
            out.append((ERROR, "main_pin", f"Pin {pin[:12]} ist kein Vorfahr von {branch} (Status {cmp['status']})"))
        try:
            when = _gh_json(gh, ["api", f"repos/{repo}/commits/{pin}", "--jq", "{d: .commit.committer.date}"])["d"]
            if parse_ts(when) != parse_ts(status["main_pin"]["committed_at"]):
                out.append((ERROR, "main_pin", f"committed_at: Register {status['main_pin']['committed_at']}, GitHub {when}"))
        except Exception:  # noqa: BLE001 - bereits oben gemeldet
            pass

    out += _check_releases(status, repo, gh)
    return out


def _check_releases(status: dict, repo: str, gh: Gh) -> list[Finding]:
    if status["releases"] == "unknown":
        return [(INFO, "releases", "Register führt Releases als unknown")]
    out: list[Finding] = []
    try:
        remote = _gh_json(gh, ["release", "list", "-R", repo, "--limit", "200", "--json", "tagName,isDraft,isPrerelease,publishedAt"])
    except Exception as exc:  # noqa: BLE001
        return [(ERROR, "releases", f"gh release list fehlgeschlagen: {exc}")]
    by_tag = {r["tagName"]: r for r in remote}
    recorded_times = []
    for rel in status["releases"]:
        tag = rel["tag"]
        got = by_tag.get(tag)
        if got is None:
            out.append((ERROR, "releases", f"{tag}: im Register, aber nicht auf GitHub"))
            continue
        if got["isDraft"] != rel["draft"]:
            out.append((ERROR, "releases", f"{tag}: draft Register {rel['draft']}, GitHub {got['isDraft']}"))
        if got["isPrerelease"] != rel["prerelease"]:
            out.append((ERROR, "releases", f"{tag}: prerelease Register {rel['prerelease']}, GitHub {got['isPrerelease']}"))
        if not got["isDraft"]:
            if rel["published_at"] is None or parse_ts(got["publishedAt"]) != parse_ts(rel["published_at"]):
                out.append((ERROR, "releases", f"{tag}: published_at Register {rel['published_at']}, GitHub {got['publishedAt']}"))
            recorded_times.append(parse_ts(got["publishedAt"]))
        try:
            names = sorted(a["name"] for a in _gh_json(gh, ["release", "view", tag, "-R", repo, "--json", "assets"])["assets"])
        except Exception as exc:  # noqa: BLE001
            out.append((ERROR, "releases", f"{tag}: Assets nicht lesbar: {exc}"))
            continue
        if names != sorted(rel["assets"]):
            missing = sorted(set(rel["assets"]) - set(names))
            extra = sorted(set(names) - set(rel["assets"]))
            out.append((ERROR, "releases", f"{tag}: Assets weichen ab (nur im Register: {missing[:3]}, nur auf GitHub: {extra[:3]})"))
    newest = max(recorded_times) if recorded_times else None
    for tag, got in by_tag.items():
        if got["isDraft"] or tag in {r["tag"] for r in status["releases"]}:
            continue
        if newest is None or parse_ts(got["publishedAt"]) > newest:
            out.append((ERROR, "releases", f"{tag} ({got['publishedAt']}) ist neuer als alles im Register und fehlt dort"))
    return out


# ---------------------------------------------------------------- lokal

def check_local(status: dict) -> list[Finding]:
    mac = status["installed"]["mac"]
    if mac == "unknown":
        return [(INFO, "installed", "Mac-Stand im Register unknown")]
    out: list[Finding] = []
    if mac["state"] == "not-installed":
        for raw in mac.get("checked_paths", []):
            if Path(raw).expanduser().exists():
                out.append((ERROR, "installed", f"{raw} existiert, Register sagt not-installed"))
        return out
    for entry in mac.get("entries", []):
        path = Path(entry["path"]).expanduser()
        if not path.exists():
            out.append((ERROR, "installed", f"{entry['path']} fehlt"))
            continue
        if entry["kind"] == "app":
            plist = path / "Contents" / "Info.plist"
            try:
                info = plistlib.loads(plist.read_bytes())
            except Exception as exc:  # noqa: BLE001
                out.append((ERROR, "installed", f"{entry['path']}: Info.plist nicht lesbar ({exc})"))
                continue
            got_v = str(info.get(entry.get("version_key", "CFBundleShortVersionString"), "unknown"))
            if entry["version"] != "unknown" and got_v != entry["version"]:
                out.append((ERROR, "installed", f"{entry['path']}: Version Register {entry['version']}, installiert {got_v}"))
            if entry["source_commit"] != "unknown" and entry.get("commit_key"):
                got_c = str(info.get(entry["commit_key"], "unknown"))
                if not got_c.startswith(entry["source_commit"][: len(got_c)]) and not entry["source_commit"].startswith(got_c):
                    out.append((ERROR, "installed", f"{entry['path']}: Quellcommit Register {entry['source_commit'][:12]}, installiert {got_c[:12]}"))
        else:  # launcher
            marker = entry.get("runtime_marker")
            if not marker:
                out.append((WARN, "installed", f"{entry['path']}: kein runtime_marker, Launcher nicht prüfbar"))
            elif marker not in path.read_text(errors="replace"):
                out.append((ERROR, "installed", f"{entry['path']}: Launcher verweist nicht mehr auf {marker}"))
    return out


# ---------------------------------------------------------------- Server (Inventar)

def check_ops(status: dict, inventory: dict) -> list[Finding]:
    server = status["server"]
    if server == "unknown":
        return [(INFO, "server", "Serverstand im Register unknown")]
    out: list[Finding] = []
    if parse_ts(inventory["observed_at"]) > parse_ts(server["observed_at"]):
        out.append((WARN, "server", f"Inventar ({inventory['observed_at']}) ist neuer als der Serverstand im Register ({server['observed_at']})"))
    units = {u["unit"]: u for u in inventory.get("systemd_system", []) + inventory.get("systemd_user", [])}
    for comp in server["components"]:
        unit = comp.get("unit")
        if not unit:
            continue
        hit = units.get(unit)
        if hit is None:
            out.append((ERROR, "server", f"{comp['name']}: Unit {unit} nicht im Inventar"))
        elif hit["active_state"] != comp["state"]:
            out.append((ERROR, "server", f"{comp['name']}: Register {comp['state']}, Inventar {hit['active_state']}"))
    return out


# ---------------------------------------------------------------- Ablauf

def check_all(status: dict, gh: Gh | None, inventory: dict | None, schema: dict, *, now: datetime | None = None,
              max_age_days: int = 14, max_behind: int = 10) -> list[Finding]:
    errors = validate(status, schema)
    if errors:
        return [(ERROR, "schema", e) for e in errors]
    out: list[Finding] = []
    now = now or datetime.now(timezone.utc)
    if now - parse_ts(status["observed_at"]) > timedelta(days=max_age_days):
        out.append((WARN, "alter", f"Register ist älter als {max_age_days} Tage ({status['observed_at']})"))
    if gh is not None:
        out += check_github(status, gh, max_behind)
    out += check_local(status)
    if inventory is not None:
        out += check_ops(status, inventory)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", default="STATUS.json", type=Path)
    ap.add_argument("--schema", default=SCHEMA_PATH, type=Path)
    ap.add_argument("--ops-inventory", type=Path, help="ops/netcup.json aus KiraBridge (optional)")
    ap.add_argument("--offline", action="store_true", help="GitHub nicht fragen")
    ap.add_argument("--max-behind", type=int, default=10)
    ap.add_argument("--max-age-days", type=int, default=14)
    ap.add_argument("--strict", action="store_true", help="WARN zählt als Abweichung")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        status = json.loads(args.status.read_text())
        schema = json.loads(args.schema.read_text())
        inventory = json.loads(args.ops_inventory.read_text()) if args.ops_inventory else None
    except (OSError, ValueError) as exc:
        print(f"status_check: {exc}", file=sys.stderr)
        return 2
    findings = check_all(status, None if args.offline else run_gh, inventory, schema,
                         max_age_days=args.max_age_days, max_behind=args.max_behind)
    if args.json:
        print(json.dumps([{"level": l, "area": a, "message": m} for l, a, m in findings], ensure_ascii=False, indent=2))
    else:
        for level, area, msg in findings:
            print(f"{level:5} {area}: {msg}")
        product = status.get("product", "?") if isinstance(status, dict) else "?"
        bad = sum(1 for f in findings if f[0] == ERROR)
        print(f"{product}: {bad} Abweichung(en), {sum(1 for f in findings if f[0] == WARN)} Warnung(en)")
    failing = {ERROR, WARN} if args.strict else {ERROR}
    return 1 if any(f[0] in failing for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
