"""BP-TRUTH-01: STATUS.json (status-v1) und scripts/status_check.py."""

from __future__ import annotations

import copy
import importlib.util
import json
import plistlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("status_check", REPO / "scripts" / "status_check.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

SCHEMA = json.loads((REPO / "docs/contracts/status-v1.schema.json").read_text())
PIN = "a" * 40
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def base() -> dict:
    return {
        "schema": "status-v1",
        "product": "Demo",
        "repo": {"name": "o/demo", "visibility": "public", "default_branch": "main"},
        "observed_at": "2026-11-09T10:00:00Z",
        "main_pin": {"commit": PIN, "committed_at": "2026-11-09T09:00:00Z"},
        "source_version": "1.0.0",
        "releases": [
            {"tag": "v1", "draft": False, "prerelease": True, "published_at": "2026-11-01T10:00:00Z", "assets": ["a.zip", "b.sha256"]}
        ],
        "installed": {"mac": {"state": "not-installed", "observed_at": "2026-11-09T10:00:00Z", "checked_paths": []}},
        "server": "unknown",
        "open_packages": [{"id": "BP-DEMO-01", "title": "x", "status": "open"}],
    }


def fake_gh(*, status="identical", ahead=0, visibility="PUBLIC", releases=None, assets=None, when="2026-11-09T09:00:00Z"):
    releases = releases if releases is not None else [
        {"tagName": "v1", "isDraft": False, "isPrerelease": True, "publishedAt": "2026-11-01T10:00:00Z"}
    ]
    assets = assets if assets is not None else ["a.zip", "b.sha256"]

    def gh(args):
        if args[:2] == ["repo", "view"]:
            return json.dumps({"visibility": visibility, "defaultBranchRef": {"name": "main"}})
        if args[0] == "api" and "/compare/" in args[1]:
            return json.dumps({"status": status, "ahead_by": ahead})
        if args[0] == "api" and "/commits/" in args[1]:
            return json.dumps({"d": when})
        if args[:2] == ["release", "list"]:
            return json.dumps(releases)
        if args[:2] == ["release", "view"]:
            return json.dumps({"assets": [{"name": n} for n in assets]})
        raise AssertionError(args)

    return gh


def run(status, gh=None, inventory=None, **kw):
    return sc.check_all(status, gh, inventory, SCHEMA, now=NOW, **kw)


def levels(findings):
    return [f[0] for f in findings]


def test_committed_status_file_matches_schema():
    status = json.loads((REPO / "STATUS.json").read_text())
    assert sc.validate(status, SCHEMA) == []
    assert status["product"] == "ThreadDesk"
    # Unbekanntes darf nie leer oder geraten sein.
    assert all(e["source_commit"] for e in status["installed"]["mac"]["entries"])


def test_clean_state_has_no_findings():
    assert run(base(), fake_gh()) == []


def test_schema_rejects_missing_and_unknown_fields():
    bad = base()
    del bad["main_pin"]
    bad["extra"] = 1
    bad["releases"][0]["published_at"] = "gestern"
    msgs = " ".join(m for _, _, m in run(bad))
    assert "main_pin" in msgs and "extra" in msgs and "published_at" in msgs


def test_unknown_is_a_valid_value_but_guessing_text_is_not():
    ok = base()
    ok["releases"] = "unknown"
    ok["source_version"] = "unknown"
    assert levels(run(ok, fake_gh())) == ["INFO"]
    bad = base()
    bad["installed"]["mac"] = "vermutlich 1.0"
    assert levels(run(bad)) == ["ERROR"]


def test_pin_behind_is_info_then_warn_and_diverged_is_error():
    assert levels(run(base(), fake_gh(status="ahead", ahead=3))) == ["INFO"]
    assert levels(run(base(), fake_gh(status="ahead", ahead=30), max_behind=10)) == ["WARN"]
    assert levels(run(base(), fake_gh(status="diverged"))) == ["ERROR"]


def test_visibility_and_commit_time_mismatch():
    found = run(base(), fake_gh(visibility="PRIVATE", when="2026-11-08T00:00:00Z"))
    assert levels(found) == ["ERROR", "ERROR"]


def test_release_asset_flag_and_newer_release_deviations():
    assert any("Assets" in m for _, _, m in run(base(), fake_gh(assets=["a.zip"])))
    wrong = [{"tagName": "v1", "isDraft": False, "isPrerelease": False, "publishedAt": "2026-11-01T10:00:00Z"}]
    assert any("prerelease" in m for _, _, m in run(base(), fake_gh(releases=wrong)))
    newer = wrong[:1] + [{"tagName": "v2", "isDraft": False, "isPrerelease": True, "publishedAt": "2026-11-05T10:00:00Z"}]
    newer[0]["isPrerelease"] = True
    found = run(base(), fake_gh(releases=newer))
    assert any("v2" in m and "fehlt" in m for _, _, m in found)
    gone = run(base(), fake_gh(releases=[]))
    assert any("nicht auf GitHub" in m for _, _, m in gone)


def test_unrecorded_older_release_and_drafts_are_ignored():
    extra = [
        {"tagName": "v1", "isDraft": False, "isPrerelease": True, "publishedAt": "2026-11-01T10:00:00Z"},
        {"tagName": "v0", "isDraft": False, "isPrerelease": True, "publishedAt": "2026-10-01T10:00:00Z"},
        {"tagName": "v2-draft", "isDraft": True, "isPrerelease": True, "publishedAt": "0001-01-01T00:00:00Z"},
    ]
    assert run(base(), fake_gh(releases=extra)) == []


def test_gh_failure_is_reported_not_raised():
    def broken(args):
        raise RuntimeError("kein Zugriff")

    found = run(base(), broken)
    assert levels(found) == ["ERROR"] and "kein Zugriff" in found[0][2]


def make_app(tmp_path: Path, version: str, commit: str) -> Path:
    app = tmp_path / "Demo.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleShortVersionString": "9", "DemoVersion": version, "DemoCommit": commit})
    )
    return app


def with_app(app: Path, version: str, commit: str) -> dict:
    s = base()
    s["installed"]["mac"] = {
        "state": "installed",
        "observed_at": "2026-11-09T10:00:00Z",
        "entries": [{"kind": "app", "path": str(app), "version": version, "version_key": "DemoVersion",
                     "source_commit": commit, "commit_key": "DemoCommit"}],
    }
    return s


def test_installed_app_matches_and_detects_drift(tmp_path):
    app = make_app(tmp_path, "0.8.0rc43", "f9e6ec8e86c9704dd9c13d390a781de270dcb93a")
    assert run(with_app(app, "0.8.0rc43", "f9e6ec8e86c9704dd9c13d390a781de270dcb93a")) == []
    assert run(with_app(app, "0.8.0rc43", "f9e6ec8e86c9")) == []  # Kurz-Hash genügt
    drift = run(with_app(app, "0.8.0rc41", "f9e6ec8e86c9704dd9c13d390a781de270dcb93a"))
    assert levels(drift) == ["ERROR"] and "rc41" in drift[0][2]
    other = run(with_app(app, "0.8.0rc43", "1234567890ab"))
    assert levels(other) == ["ERROR"] and "Quellcommit" in other[0][2]


def test_installed_unknown_commit_is_not_compared_and_missing_app_fails(tmp_path):
    app = make_app(tmp_path, "1", "x")
    assert run(with_app(app, "1", "unknown")) == []
    missing = with_app(tmp_path / "Weg.app", "1", "unknown")
    assert "fehlt" in run(missing)[0][2]


def test_launcher_marker(tmp_path):
    script = tmp_path / "demo"
    script.write_text("#!/bin/sh\nexec /x/releases/0.8.0rc41-c81430b88738/bin/python\n")
    s = base()
    s["installed"]["mac"] = {"state": "installed", "observed_at": "2026-11-09T10:00:00Z", "entries": [
        {"kind": "launcher", "path": str(script), "version": "0.8.0rc41", "source_commit": "c81430b88738",
         "runtime_marker": "0.8.0rc41-c81430b88738"}]}
    assert run(s) == []
    script.write_text("#!/bin/sh\nexec /x/releases/0.8.0rc43-f9e6ec8e86c9/bin/python\n")
    assert "verweist nicht mehr" in run(s)[0][2]


def test_not_installed_claim_breaks_when_path_appears(tmp_path):
    s = base()
    s["installed"]["mac"]["checked_paths"] = [str(tmp_path / "Demo.app")]
    assert run(s) == []
    (tmp_path / "Demo.app").mkdir()
    assert "existiert" in run(s)[0][2]


def test_old_register_warns():
    s = base()
    s["observed_at"] = "2026-10-01T00:00:00Z"
    assert levels(run(s, fake_gh())) == ["WARN"]


def server_status():
    s = base()
    s["server"] = {"source": "ops/netcup.json", "observed_at": "2026-11-08T16:59:45Z", "components": [
        {"name": "svc", "unit": "svc.service", "state": "active", "version": "1", "source_commit": "unknown", "exposure": "Loopback"}]}
    return s


def test_server_state_against_inventory():
    inv = {"observed_at": "2026-11-08T16:59:45Z", "systemd_system": [{"unit": "svc.service", "active_state": "active"}], "systemd_user": []}
    assert run(server_status(), None, inv) == []
    inv["systemd_system"][0]["active_state"] = "inactive"
    assert "Inventar inactive" in run(server_status(), None, inv)[0][2]
    inv["systemd_system"] = []
    assert "nicht im Inventar" in run(server_status(), None, inv)[0][2]
    newer = {"observed_at": "2026-11-09T01:00:00Z", "systemd_system": [{"unit": "svc.service", "active_state": "active"}]}
    assert levels(run(server_status(), None, newer)) == ["WARN"]


def test_main_exit_codes(tmp_path, capsys):
    good = tmp_path / "STATUS.json"
    good.write_text(json.dumps(base()))
    assert sc.main(["--status", str(good), "--offline", "--max-age-days", "100000"]) == 0
    broken = copy.deepcopy(base())
    broken["installed"]["mac"] = {"state": "not-installed", "observed_at": "2026-11-09T10:00:00Z", "checked_paths": [str(tmp_path)]}
    good.write_text(json.dumps(broken))
    assert sc.main(["--status", str(good), "--offline", "--max-age-days", "100000"]) == 1
    assert sc.main(["--status", str(tmp_path / "fehlt.json"), "--offline"]) == 2
    capsys.readouterr()
