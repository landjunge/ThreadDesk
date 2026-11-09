#!/usr/bin/env python3
"""Meldet Plan-Dateien in den Produkt-Repos ohne den Hinweis „Maßgeblich ist ThreadDesk“.

Nutzerbeschluss 09.11.2026: ThreadDesk ist die einzige maßgebliche Quelle für den Big Plan.
GitHub-Plandateien (`*PLAN*.md`, `*BAUPLAN*`, `*GESAMTPLAN*`) müssen oben diesen Hinweis tragen:

    Nicht maßgeblich. Maßgeblich ist ThreadDesk-Thread `<id>` (Nutzerbeschluss 09.11.2026).
    Diese Datei ist Archiv bzw. technischer Spiegel.

Nur lesend, nur Standardbibliothek.

    python scripts/plan_notice_check.py                      # Standard-Repos unter dem Home-Ordner
    python scripts/plan_notice_check.py --repo ../KiraBridge --repo .
    python scripts/plan_notice_check.py --repo ../4AllPass --ref origin/main

Bekannte Teilpläne ohne Big-Plan-Inhalt stehen in docs/contracts/plan-notice-baseline.json
(Schlüssel: Repo-Ordnername, Wert: Liste relativer Pfade). Neue Dateien sind nie ausgenommen.

Exit-Code: 0 = alle Plan-Dateien tragen den Hinweis oder sind in der Baseline, 1 = Verstöße, 2 = Aufruf unbrauchbar.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

NOTICE_RE = re.compile(r"Maßgeblich ist ThreadDesk-Thread\s+`?[0-9a-f]{12}`?")
HEAD_LINES = 40
DEFAULT_REPOS = ["KiraBridge", "threaddesk", "4AllPass", "tollgate", "agent-authority-lab"]
BASELINE_PATH = Path(__file__).resolve().parents[1] / "docs" / "contracts" / "plan-notice-baseline.json"
SKIP_PARTS = ("evidence/", "node_modules/", ".worktrees/", "vendor/")


def is_plan_file(path: str) -> bool:
    low = path.lower()
    if any(part in low for part in SKIP_PARTS):
        return False
    name = low.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(name, "*plan*.md"):
        return True
    return "bauplan" in name or "gesamtplan" in name


def has_notice(text: str) -> bool:
    head = "\n".join(text.splitlines()[:HEAD_LINES])
    return bool(NOTICE_RE.search(head))


def _git(repo: Path, args: List[str]) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def list_files(repo: Path, ref: Optional[str]) -> List[str]:
    if ref:
        return _git(repo, ["ls-tree", "-r", "--name-only", ref]).splitlines()
    return _git(repo, ["ls-files"]).splitlines()


def read_file(repo: Path, ref: Optional[str], path: str) -> str:
    if ref:
        return subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{path}"], check=True, capture_output=True
        ).stdout.decode("utf-8", "replace")
    return (repo / path).read_text(encoding="utf-8", errors="replace")


def check_repo(
    repo: Path,
    ref: Optional[str] = None,
    baseline: Optional[Dict[str, Iterable[str]]] = None,
    lister: Callable[[Path, Optional[str]], List[str]] = list_files,
    reader: Callable[[Path, Optional[str], str], str] = read_file,
) -> List[str]:
    """Gibt die Pfade ohne Hinweis zurück (ohne Baseline-Ausnahmen)."""
    exempt = set((baseline or {}).get(repo.name, []))
    missing = []
    for path in sorted(lister(repo, ref)):
        if not is_plan_file(path) or path in exempt:
            continue
        if not has_notice(reader(repo, ref, path)):
            missing.append(path)
    return missing


def load_baseline(path: Path = BASELINE_PATH) -> Dict[str, List[str]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", type=Path, help="Repo-Pfad (mehrfach); Standard: Produkt-Repos unter ~")
    ap.add_argument("--ref", help="Git-Ref statt Arbeitsbaum, z. B. origin/main")
    ap.add_argument("--baseline", type=Path, default=BASELINE_PATH)
    args = ap.parse_args(argv)
    repos = args.repo or [Path.home() / name for name in DEFAULT_REPOS]
    baseline = load_baseline(args.baseline)
    bad = 0
    for repo in repos:
        if not (repo / ".git").exists():
            print(f"SKIP  {repo}: kein Git-Repo")
            continue
        repo = repo.resolve()
        try:
            missing = check_repo(repo, args.ref, baseline)
        except subprocess.CalledProcessError as exc:
            print(f"FEHLER {repo}: {exc}", file=sys.stderr)
            return 2
        for path in missing:
            print(f"FEHLT {repo.name}/{path}: Hinweis „Maßgeblich ist ThreadDesk-Thread …“ fehlt")
        bad += len(missing)
    print(f"{bad} Plan-Datei(en) ohne Hinweis" if bad else "OK: alle Plan-Dateien tragen den Hinweis")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
