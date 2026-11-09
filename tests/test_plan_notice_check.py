"""Plan-Governance 09.11.2026: scripts/plan_notice_check.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("plan_notice_check", REPO / "scripts" / "plan_notice_check.py")
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)

NOTICE = (
    "> Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `188ce4729a62` (Nutzerbeschluss 09.11.2026). "
    "Diese Datei ist Archiv bzw. technischer Spiegel.\n\n"
)


def make_repo(tmp_path: Path, files: dict) -> Path:
    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def test_is_plan_file():
    for path in ("PLAN.md", "docs/plans/BIGPLAN-BAUPLAN-20261108.md", "docs/TEAMPLAN.md", "x/GESAMTPLAN.txt", "docs/BAUPLAN-2"):
        assert pn.is_plan_file(path), path
    for path in ("README.md", "src/plan_fast_path.py", "docs/evidence/final-plan.md", "docs/planning.txt"):
        assert not pn.is_plan_file(path), path


def test_notice_must_be_near_top():
    assert pn.has_notice(NOTICE + "# Plan")
    assert not pn.has_notice("# Plan\n" + "x\n" * 60 + NOTICE)
    assert not pn.has_notice("Maßgeblich ist der Big Plan")


def test_reports_missing_notice_and_accepts_marked(tmp_path):
    repo = make_repo(tmp_path, {"docs/A-PLAN.md": "# A\n", "docs/B-PLAN.md": NOTICE + "# B\n", "README.md": "x\n"})
    assert pn.check_repo(repo) == ["docs/A-PLAN.md"]


def test_baseline_exempts_only_listed_paths(tmp_path):
    repo = make_repo(tmp_path, {"docs/OLD-PLAN.md": "# alt\n", "docs/NEW-PLAN.md": "# neu\n"})
    assert pn.check_repo(repo, baseline={"demo": ["docs/OLD-PLAN.md"]}) == ["docs/NEW-PLAN.md"]


def test_ref_mode_reads_committed_content(tmp_path):
    repo = make_repo(tmp_path, {"docs/A-PLAN.md": "# A\n"})
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], cwd=repo, check=True
    )
    (repo / "docs/A-PLAN.md").write_text(NOTICE + "# A\n", encoding="utf-8")  # nur im Arbeitsbaum
    assert pn.check_repo(repo, ref="HEAD") == ["docs/A-PLAN.md"]
    assert pn.check_repo(repo) == []


def test_main_exit_codes(tmp_path, capsys):
    repo = make_repo(tmp_path, {"docs/A-PLAN.md": "# A\n"})
    base = tmp_path / "base.json"
    base.write_text("{}")
    assert pn.main(["--repo", str(repo), "--baseline", str(base)]) == 1
    assert "FEHLT demo/docs/A-PLAN.md" in capsys.readouterr().out
    base.write_text(json.dumps({"demo": ["docs/A-PLAN.md"]}))
    assert pn.main(["--repo", str(repo), "--baseline", str(base)]) == 0


def test_this_repo_plan_files_carry_notice():
    """Die Plan-Dateien dieses Repos tragen den Hinweis oder stehen in der Baseline."""
    baseline = {REPO.name: pn.load_baseline().get("threaddesk", [])}  # Worktree-Ordner heißt anders als das Repo
    assert pn.check_repo(REPO, baseline=baseline) == []
