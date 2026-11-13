"""ThreadDesks eigenes README hält den verbindlichen Familienkopf (readme-header-v1)."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location(
        "readme_header", ROOT / "scripts/readme_header.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threaddesk_readme_matches_family_header():
    assert _tool().main(["check", "--product", "threaddesk", "--repo", str(ROOT)]) == 0


def test_catalog_has_unique_keys_and_icons_for_every_product():
    tool = _tool()
    products, by_key = tool.load_catalog()
    assert len(by_key) == len(products)
    for product in products:
        for role in ("small", "large"):
            assert (tool.ICONS / f"{product['icon_prefix']}-{role}.svg").exists()


def test_license_template_has_placeholders():
    tool = _tool()
    raw = tool.LICENSE_TEMPLATE.read_text(encoding="utf-8")
    assert raw.startswith(tool.LICENSE_TITLE)
    assert "{{HISTORICAL_DE}}" in raw
    assert "{{HISTORICAL_EN}}" in raw
    filled = tool.render_license("ProbeTool")
    assert "ProbeTool-Fassungen" in filled
    assert "{{HISTORICAL_DE}}" not in filled
    assert "4AllPass" not in filled


def test_init_writes_license_and_readme_block(tmp_path):
    tool = _tool()
    dest = tmp_path / "new-tool"
    assert (
        tool.main(["init", "--product", "agent-authority", "--repo", str(dest)])
        == 0
    )
    license_text = (dest / "LICENSE").read_text(encoding="utf-8")
    assert license_text.startswith(tool.LICENSE_TITLE)
    assert "Agent Authority-Fassungen" in license_text
    readme = (dest / "README.md").read_text(encoding="utf-8")
    assert tool.LICENSE_TITLE in readme
    assert "](LICENSE)" in readme
    assert tool.MARKER in readme
    assert (
        tool.main(["check", "--product", "agent-authority", "--repo", str(dest)])
        == 0
    )
