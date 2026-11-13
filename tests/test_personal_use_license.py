"""Family license checker for GitHub CI and installation packages."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "check_personal_use_license", ROOT / "scripts/check_personal_use_license.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_self_test_and_this_repo():
    tool = _tool()
    assert tool.main(["--self-test"]) == 0
    assert tool.main(["--product", "threaddesk", "--repo", str(ROOT)]) == 0
