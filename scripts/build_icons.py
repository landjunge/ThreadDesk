"""Derive native icons from the approved mark; do not redesign the brand."""
from __future__ import annotations

import hashlib
import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tauri", action="store_true", help="Also update the actual Tauri bundle icons")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source_path = "assets/design/icons/dark/ThreadDesk-dark-1024.png"
    source = root / source_path
    output = root / "build/icons"
    output.mkdir(parents=True, exist_ok=True)
    image = Image.open(source).convert("RGBA")
    assert image.size == (1024, 1024)
    # Tauri's embedded icon decoder requires RGBA, even for an opaque original.
    image.save(output / "icon.png")
    image.save(output / "icon.ico", format="ICO", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    image.save(output / "icon.icns", format="ICNS")
    evidence = {"source": source_path, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    for name in ("icon.png", "icon.ico", "icon.icns"):
        assert (output / name).stat().st_size > 0
        evidence[name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / "icons.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    if args.tauri:
        destination = root / "packaging/tauri/src-tauri/icons"
        for name in ("icon.png", "icon.icns"):
            shutil.copyfile(output / name, destination / name)
    print("Native icons generated from the original ThreadDesk family asset")


if __name__ == "__main__":
    main()
