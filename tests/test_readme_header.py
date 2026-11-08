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
