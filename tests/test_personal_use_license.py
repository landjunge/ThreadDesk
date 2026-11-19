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


def test_a_valid_license_file_cannot_mask_a_conflicting_tauri_identifier(tmp_path):
    import json

    tool = _tool()
    conf = tmp_path / "src-tauri" / "tauri.conf.json"
    conf.parent.mkdir()
    conf.write_text(json.dumps({"bundle": {"license": "MIT", "licenseFile": "../LICENSE"}}))
    assert any("bundle.license" in p for p in tool.check_tauri(tmp_path))
    conf.write_text(json.dumps({"bundle": {"licenseFile": "../LICENSE"}}))
    assert not [p for p in tool.check_tauri(tmp_path) if "bundle" in p]
