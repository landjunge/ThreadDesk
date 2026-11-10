import importlib.util
import json
import os
from pathlib import Path

import pytest

from threaddesk.storage.json_store import JsonStore

spec = importlib.util.spec_from_file_location(
    "skill_sync", Path(__file__).resolve().parents[1] / "scripts/skill_sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def write_source(src: Path, body: str = "Regeln v1") -> Path:
    for name in ("alpha", "beta"):
        (src / name).mkdir(parents=True, exist_ok=True)
        (src / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: >\n  Skill {name}\n  mehrzeilig.\n---\n# {name}\n{body}\n",
            encoding="utf-8")
    tool = src / "beta/scripts/check.sh"
    tool.parent.mkdir(exist_ok=True)
    tool.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    tool.chmod(0o755)
    (src / "targets.json").write_text(json.dumps({
        "claude": {"dir": ".claude/skills", "mode": "entry", "skills": ["alpha", "beta"]},
        "codex": {"dir": ".codex/skills", "mode": "link", "skills": ["alpha", "beta"]},
    }), encoding="utf-8")
    return src


@pytest.fixture
def env(tmp_path):
    ws = tmp_path / "ws"
    JsonStore(ws)
    home, root = tmp_path / "home", tmp_path / "export"
    old = home / ".codex/skills/alpha"
    old.mkdir(parents=True)
    (old / "SKILL.md").write_text("alte Fassung\n", encoding="utf-8")
    return ws, home, root, write_source(tmp_path / "src")


def test_publish_export_entries_and_backup(env):
    ws, home, root, src = env
    result = sync.publish(src, ws, root, home)
    assert result["release"] == 1 and result["current"] == 1
    link = home / ".codex/skills/alpha"
    assert os.readlink(link) == str(root / "current/alpha")
    assert "Regeln v1" in (link / "SKILL.md").read_text(encoding="utf-8")
    entry = (home / ".claude/skills/beta/SKILL.md").read_text(encoding="utf-8")
    _, fields = sync.frontmatter(entry)
    assert fields == {"name": "beta", "description": "Skill beta mehrzeilig."}
    assert f"{root}/current/beta/SKILL.md" in entry
    tool = root / "current/beta/scripts/check.sh"
    assert tool.read_text() == "#!/bin/sh\necho ok\n" and os.access(tool, os.X_OK)
    info = json.loads((root / "current/release.json").read_text(encoding="utf-8"))
    assert info["release"] == 1 and len(info["files"]["alpha/SKILL.md"]) == 64
    backups = list((root / "backups").iterdir())
    assert len(backups) == 1
    assert (backups[0] / "codex/alpha/SKILL.md").read_text() == "alte Fassung\n"
    assert sync.status(root, home)["problems"] == []
    thread = [t for t in JsonStore(ws).list_threads(include_archived=True) if t.title == sync.THREAD]
    assert len(thread) == 1 and JsonStore(ws).get_current_id() != thread[0].id


def test_unchanged_publish_keeps_release(env):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    again = sync.publish(src, ws, root, home)
    assert again["release"] == 1 and again["unchanged"] and again["changed"] == []


def test_new_release_rollback_and_forward(env):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    write_source(src, "Regeln v2")
    assert sync.publish(src, ws, root, home)["release"] == 2
    alpha = home / ".codex/skills/alpha/SKILL.md"
    assert "Regeln v2" in alpha.read_text()
    back = sync.rollback(root, home)
    assert back == {"from": 2, "current": 1, "changed": []}
    assert "Regeln v1" in alpha.read_text()
    assert sync.export(ws, root, home, 2)["current"] == 2
    assert "Regeln v2" in alpha.read_text()


def test_fallback_without_threaddesk(env, tmp_path, capsys):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    code = sync.main(["--workspace", str(tmp_path / "missing"), "--root", str(root),
                      "--home", str(home), "export"])
    assert code == 2
    assert "r1 stays active" in capsys.readouterr().err
    assert sync.status(root, home) == {"current": 1, "problems": []}


def test_restore_returns_previous_entries(env):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    stamp = next((root / "backups").iterdir()).name
    assert sync.restore(root, stamp) == ["codex/alpha"]
    alpha = home / ".codex/skills/alpha"
    assert not alpha.is_symlink() and (alpha / "SKILL.md").read_text() == "alte Fassung\n"
    assert sync.status(root, home)["problems"] == ["codex/alpha: entry differs from current"]


def test_rejected_content_changes_nothing(env):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    (src / "alpha/SKILL.md").write_text(
        "---\nname: alpha\ndescription: x\n---\napi_key = sk-" + "a" * 20 + "\n", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="secret_content"):
        sync.publish(src, ws, root, home)
    assert sync.status(root, home) == {"current": 1, "problems": []}


def test_invalid_frontmatter_is_refused(env):
    ws, home, root, src = env
    (src / "beta/SKILL.md").write_text("---\nname: other\ndescription: x\n---\n", encoding="utf-8")
    with pytest.raises(sync.SyncError, match="beta"):
        sync.publish(src, ws, root, home)
    assert not (root / "current").exists()


def test_dropped_target_entry_is_stashed_and_rollback_restores_it(env):
    ws, home, root, src = env
    sync.publish(src, ws, root, home)
    targets = json.loads((src / "targets.json").read_text())
    targets["codex"]["skills"] = ["beta"]
    (src / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
    (home / ".codex/skills/foreign").mkdir()
    result = sync.publish(src, ws, root, home)
    assert result["release"] == 2 and result["changed"] == ["-codex/alpha"]
    assert not (home / ".codex/skills/alpha").exists()
    assert (home / ".codex/skills/foreign").is_dir()
    assert sync.status(root, home)["problems"] == []
    sync.rollback(root, home)
    assert os.readlink(home / ".codex/skills/alpha") == str(root / "current/alpha")
    assert sync.status(root, home)["problems"] == []
    assert sync.export(ws, root, home, 2)["changed"] == ["-codex/alpha"]
