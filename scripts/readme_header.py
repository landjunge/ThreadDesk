#!/usr/bin/env python3
"""README-Kopf der Produktfamilie erzeugen, übernehmen und prüfen (Vertrag readme-header-v1).

Quelle der Wahrheit:
  docs/contracts/readme-header-v1.md    Gestaltungsregel (Referenz)
  docs/contracts/readme-header-v1.json  Produktkatalog (Reihenfolge, Farben, Wortmarken)
  docs/design/readme-header/icons/      normierte Icons aller Produkte (SVG mit Original-PNG)

Befehle:
  icons  --product KEY --source DIR   normierte Icons aus den freigegebenen Dark-PNGs bauen
                                      (DIR enthält <Prefix>-dark-128.png und -512.png)
  apply  --product KEY --repo PATH    Kopf, Icons, Wortmarken (und ggf. Quellcode-Button)
                                      in ein Produkt-Repository schreiben; Inhalt bleibt
  check  --product KEY --repo PATH    Kopf eines Repositories gegen den Vertrag prüfen

Nur Standardbibliothek; `icons` nutzt Pillow nur, wenn kein frame_box_256 im Katalog steht.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/contracts/readme-header-v1.json"
ICONS = ROOT / "docs/design/readme-header/icons"
START, END = "<!-- AUTO-DOWNLOADS:START -->", "<!-- AUTO-DOWNLOADS:END -->"
NEUTRAL = {"dark": "#ffffff", "light": "#17191f"}
BUTTON_TEXT = "#14161b"

# Zeilen, die zum alten Kopf gehören dürfen und beim Übernehmen ersetzt werden.
# Unsichtbarer Hinweis im README selbst: wer den Kopf anfasst, findet die Regel.
MARKER = (
    "<!-- readme-header-v1: Kopf nach ThreadDesk docs/contracts/readme-header-v1.md. "
    "Nicht von Hand umgestalten; scripts/readme_header.py apply/check verwenden. -->"
)

HEADER_LINE = re.compile(
    r"^\s*(?:$|<picture>|</picture>|<source |<img |<p align=\"center\">\s*$"
    r"|<p align=\"center\"><(?:picture|img)|</p>|<a href=|&nbsp;|<!-- AUTO-DOWNLOADS|<!-- readme-header-v1"
    r"|<h1 align=\"center\">|#\s|\*\*English\*\*|\[English\]|\[Deutsch\])"
)


def load_catalog():
    products = json.loads(CATALOG.read_text(encoding="utf-8"))["products"]
    return products, {p["key"]: p for p in products}


def measure_frame(png_256: Path, color: str):
    from PIL import Image  # nur für neue Icons ohne Katalogwert

    im = Image.open(png_256).convert("RGBA")
    target = tuple(int(color[i : i + 2], 16) for i in (1, 3, 5))
    px = im.load()
    xs, ys = [], []
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if (
                a > 200
                and abs(r - target[0]) + abs(g - target[1]) + abs(b - target[2]) < 70
            ):
                xs.append(x)
                ys.append(y)
    k = 256 / im.width
    x0, y0 = min(xs) * k, min(ys) * k
    return [
        round(x0),
        round(y0),
        round((max(xs) + 1) * k - x0),
        round((max(ys) + 1) * k - y0),
    ]


def normalized_svg(product, role: str, png: bytes, src_name: str) -> str:
    """Original-PNG unverändert eingebettet, auf den Rahmen zugeschnitten, einheitlich groß."""
    x0, y0, bw, bh = product["frame_box_256"]
    scale = 0.94 * 256 / max(bw, bh)
    tx, ty = 128 - scale * (x0 + bw / 2), 128 - scale * (y0 + bh / 2)
    meta = json.dumps(
        {
            "contract": "readme-header-v1",
            "role": role,
            "source_repo": product["repo"],
            "source_path": f"assets/design/icons/dark/{src_name}",
            "source_sha256": hashlib.sha256(png).hexdigest(),
            "frame_box_256": product["frame_box_256"],
        }
    )
    name = escape(product["name"])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="256" height="256" viewBox="0 0 256 256" role="img" aria-label="{name}">\n'
        f"  <title>{name}</title>\n"
        f"  <metadata>{escape(meta)}</metadata>\n"
        f'  <defs><clipPath id="frame"><rect x="{x0}" y="{y0}" width="{bw}" height="{bh}"/>'
        "</clipPath></defs>\n"
        f'  <g transform="translate({tx:.3f} {ty:.3f}) scale({scale:.5f})">'
        '<image width="256" height="256" clip-path="url(#frame)" '
        f'xlink:href="data:image/png;base64,{base64.b64encode(png).decode()}"/></g>\n'
        "</svg>\n"
    )


def wordmark_svg(product, theme: str) -> str:
    first, second = product["wordmark"]
    w = product["wordmark_width"]
    edge = ""
    if theme == "light":
        edge = ' stroke="#17191f" stroke-width="1.1" paint-order="stroke" stroke-linejoin="round"'
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="64" viewBox="0 0 {w} 64" '
        f'role="img" aria-label="{first}{second}"><title>{first}{second}</title>'
        f'<text x="{w // 2}" y="46" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
        'font-size="44" font-weight="700" letter-spacing="-1">'
        f'<tspan fill="{NEUTRAL[theme]}">{first}</tspan>'
        f'<tspan fill="{product["color"]}"{edge}>{second}</tspan></text></svg>\n'
    )


def button_svg(label: str, version: str, color: str) -> str:
    """Gleiche Form wie scripts/update_readme_downloads.py (Release-Buttons)."""
    label, version = escape(label), escape(version)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="190" height="52" viewBox="0 0 190 52" '
        f'role="img" aria-label="Download {label} {version}"><title>Download {label} {version}</title>'
        f'<rect x="1" y="1" width="188" height="50" rx="10" fill="{color}"/>'
        f'<path d="M24 14v14m-6-6 6 6 6-6M17 34h14" fill="none" stroke="{BUTTON_TEXT}" '
        'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
        '<text x="110" y="23" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
        f'font-size="13" font-weight="700" fill="{BUTTON_TEXT}">{label}</text>'
        '<text x="110" y="39" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
        f'font-size="11" fill="{BUTTON_TEXT}">{version}</text></svg>\n'
    )


def peer_url(peer, german: bool) -> str:
    base = f"https://github.com/landjunge/{peer['repo']}"
    if german and peer["readme_de"]:
        return f"{base}/blob/{peer['branch']}/README.de.md"
    return f"{base}#readme"


def header(products, product, german: bool, block: str) -> str:
    out = [MARKER, ""]
    if product["readme_de"]:
        out += [
            "[English](README.md) · **Deutsch**"
            if german
            else "**English** · [Deutsch](README.de.md)",
            "",
        ]
    out += [
        '<p align="center">',
        (
            f'  <img src="assets/readme/normalized/{product["icon_prefix"]}-large.svg" '
            f'alt="{product["name"]}" width="256" height="256">'
        ),
        "</p>",
        "",
    ]
    links = [
        f'<a href="{peer_url(p, german)}" title="{p["name"]}">'
        f'<img src="assets/readme/normalized/{p["icon_prefix"]}-small.svg" alt="{p["name"]}" '
        'width="48" height="48"></a>'
        for p in products
        if p is not product
    ]
    out += ['<p align="center">', "  " + "\n  &nbsp;\n  ".join(links), "</p>", ""]
    out += [
        (
            '<p align="center"><picture><source media="(prefers-color-scheme: dark)" '
            f'srcset="{product["wordmark_dark"]}"><img src="{product["wordmark_light"]}" '
            f'alt="{product["name"]}" width="{round(product["wordmark_width"] * 0.8)}"></picture></p>'
        ),
        "",
        START,
        block,
        END,
        "",
    ]
    return "\n".join(out)


def split_header(text: str):
    lines = text.split("\n")
    i = 0
    while i < len(lines) and HEADER_LINE.match(lines[i]):
        i += 1
    head, rest = lines[:i], lines[i:]
    block = ""
    joined = "\n".join(head)
    if START in joined and END in joined:
        block = joined.split(START + "\n", 1)[1].split("\n" + END, 1)[0]
    return block, "\n".join(rest).lstrip("\n")


def cmd_icons(args):
    _products, by_key = load_catalog()
    product = by_key[args.product]
    src = Path(args.source)
    prefix = product["icon_prefix"]
    if not product.get("frame_box_256"):
        product["frame_box_256"] = measure_frame(
            src / f"{prefix}-dark-256.png", product["frame_color"]
        )
        print(
            f"frame_box_256 für {args.product} im Katalog eintragen: {product['frame_box_256']}"
        )
    ICONS.mkdir(parents=True, exist_ok=True)
    for role, size in (("small", 128), ("large", 512)):
        name = f"{prefix}-dark-{size}.png"
        png = (src / name).read_bytes()
        (ICONS / f"{prefix}-{role}.svg").write_text(
            normalized_svg(product, role, png, name), encoding="utf-8"
        )
    print(f"Icons geschrieben: {ICONS}/{prefix}-small.svg, -large.svg")


def cmd_apply(args):
    products, by_key = load_catalog()
    product = by_key[args.product]
    repo = Path(args.repo)
    norm = repo / "assets/readme/normalized"
    norm.mkdir(parents=True, exist_ok=True)
    for p in products:
        role = "large" if p is product else "small"
        source = ICONS / f"{p['icon_prefix']}-{role}.svg"
        if not source.exists():
            raise SystemExit(
                f"Fehlt: {source} — zuerst `icons --product {p['key']}` ausführen"
            )
        shutil.copyfile(source, norm / source.name)
    for theme in ("dark", "light"):
        path = repo / product[f"wordmark_{theme}"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(wordmark_svg(product, theme), encoding="utf-8")

    source_block = None
    if product["downloads"] == "source":
        label, version = "Quellcode / Source", f"ZIP · {product['source_version']}"
        (repo / "assets/readme/download-source.svg").write_text(
            button_svg(label, version, product["color"]), encoding="utf-8"
        )
        url = f"https://github.com/landjunge/{product['repo']}/archive/refs/heads/{product['branch']}.zip"
        source_block = (
            '<p align="center">\n'
            f'  <a href="{url}" title="{product["repo"]}-{product["branch"]}.zip herunterladen / download">'
            f'<img src="assets/readme/download-source.svg" alt="Download {label} {version}" '
            'width="190" height="52"></a>\n</p>'
        )

    pages = [(repo / "README.md", False)]
    if product["readme_de"]:
        pages.append((repo / "README.de.md", True))
    for page, german in pages:
        text = page.read_text(encoding="utf-8") if page.exists() else ""
        block, rest = split_header(text)
        new = header(products, product, german, source_block or block) + (
            "\n" + rest if rest else ""
        )
        page.write_text(new, encoding="utf-8")
        print(f"Kopf geschrieben: {page}")
    if product["downloads"] == "releases":
        print(
            "Release-Downloads: im Repository `scripts/update_readme_downloads.py` ausführen "
            "(GITHUB_REPOSITORY, GITHUB_TOKEN)."
        )


def cmd_check(args):
    products, by_key = load_catalog()
    product = by_key[args.product]
    repo = Path(args.repo)
    problems = []
    pages = [(repo / "README.md", False)] + (
        [(repo / "README.de.md", True)] if product["readme_de"] else []
    )
    for page, german in pages:
        if not page.exists():
            problems.append(f"{page.name} fehlt")
            continue
        text = page.read_text(encoding="utf-8")
        head = text.split(END, 1)[0] if END in text else text[:4000]
        large = f"assets/readme/normalized/{product['icon_prefix']}-large.svg"
        if large not in head:
            problems.append(f"{page.name}: großes Logo fehlt")
        for p in products:
            if p is product:
                continue
            if f"normalized/{p['icon_prefix']}-small.svg" not in head:
                problems.append(f"{page.name}: Icon {p['name']} fehlt")
            if peer_url(p, german) not in head:
                problems.append(f"{page.name}: Link zu {p['name']} fehlt/falsch")
        if (
            product["wordmark_dark"] not in head
            or product["wordmark_light"] not in head
        ):
            problems.append(f"{page.name}: Wortmarke fehlt")
        if not text.startswith(MARKER):
            problems.append(
                f"{page.name}: Hinweis readme-header-v1 in der ersten Zeile fehlt"
            )
        if START not in text or END not in text:
            problems.append(f"{page.name}: AUTO-DOWNLOADS-Marker fehlen")
        else:
            block = text.split(START, 1)[1].split(END, 1)[0]
            hrefs = re.findall(r'href="([^"]+)"', block)
            if not hrefs:
                problems.append(f"{page.name}: keine Download-Buttons")
            for h in hrefs:
                if "/releases/download/" not in h and "/archive/refs/heads/" not in h:
                    problems.append(f"{page.name}: Download ist kein Direktlink: {h}")
    for ref in re.findall(
        r'(?:src|srcset)="(assets/[^"]+|brand/[^"]+)"',
        "".join(p.read_text(encoding="utf-8") for p, _ in pages if p.exists()),
    ):
        if not (repo / ref).exists():
            problems.append(f"Datei fehlt: {ref}")
    for theme in ("dark", "light"):
        wm = repo / product[f"wordmark_{theme}"]
        if wm.exists() and product["color"] not in wm.read_text(encoding="utf-8"):
            problems.append(f"Wortmarke {theme}: Markenfarbe {product['color']} fehlt")
    for line in problems:
        print("FEHLER", line)
    print("OK" if not problems else f"{len(problems)} Abweichung(en)")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("icons")
    p.add_argument("--product", required=True)
    p.add_argument("--source", required=True)
    for name in ("apply", "check"):
        p = sub.add_parser(name)
        p.add_argument("--product", required=True)
        p.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    return {"icons": cmd_icons, "apply": cmd_apply, "check": cmd_check}[args.cmd](
        args
    ) or 0


if __name__ == "__main__":
    sys.exit(main())
