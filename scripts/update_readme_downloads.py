#!/usr/bin/env python3
"""Refresh README download buttons from published GitHub Release assets.

Every button links straight to the installation file (``browser_download_url``),
never to a release page, so one click starts the download. Drafts are ignored;
prereleases count because the products currently ship previews only.

Shared by KiraBridge, ThreadDesk and 4AllPass. Only the block between the
AUTO-DOWNLOADS markers in README.md / README.de.md and the generated
``assets/readme/download-*.svg`` buttons are touched.
"""

import json
import os
import re
import urllib.request
from html import escape
from pathlib import Path

START, END = "<!-- AUTO-DOWNLOADS:START -->", "<!-- AUTO-DOWNLOADS:END -->"
BUTTON_DIR = Path("assets/readme")

# Brand colours as taken from the approved product icons / brand READMEs
# (same values as the shared product header catalog).
BRAND = {
    "kirabridge": "#fc63ad",
    "threaddesk": "#b99cff",
    "4allpass": "#6be4f2",
    "tollgate": "#e77745",
    "agent-authority-lab": "#3b78fc",
    "blockdesign": "#ebc33f",
}

# Display order of the buttons.
ORDER = ["macOS Apple Silicon", "macOS Intel", "Windows", "Linux"]

PACKAGE = re.compile(r"\.(?:dmg|pkg|exe|msi|appimage|deb|rpm|zip|tar\.gz)$", re.I)
NOT_PACKAGE = re.compile(
    r"(?:checksum|sha256|sha512|sbom|manifest|symbols|debug|notices|evidence|"
    r"source|\.sig$|\.asc$|\.whl$|-review|build-only|historical-)",
    re.I,
)
WINDOWS = re.compile(r"(?:windows|win32|win64|win11|\.exe$|\.msi$)", re.I)
LINUX = re.compile(r"(?:linux|ubuntu|debian|\.appimage$|\.deb$|\.rpm$)", re.I)
MAC = re.compile(r"(?:mac|darwin|osx|apple|intel|\.dmg$|\.pkg$)", re.I)
ARM = re.compile(r"(?:arm64|aarch64|apple.?silicon)", re.I)
UNIVERSAL = re.compile(r"universal", re.I)


def platforms(name):
    """Platforms an asset can be offered for (empty when unclear)."""
    if not PACKAGE.search(name) or NOT_PACKAGE.search(name):
        return []
    if WINDOWS.search(name):
        return ["Windows"]
    if LINUX.search(name):
        return ["Linux"]
    if MAC.search(name):
        if UNIVERSAL.search(name):
            return ["macOS Apple Silicon", "macOS Intel"]
        if ARM.search(name):
            return ["macOS Apple Silicon"]
        # x64 / x86_64 / intel builds, and the historical un-suffixed mac build.
        return ["macOS Intel"]
    return []


def preference(name):
    """Higher is better inside one release: real installers before archives."""
    lowered = name.lower()
    score = 0
    if re.search(r"(?:installer|setup)", lowered):
        score += 4
    if re.search(r"\.(?:dmg|pkg|exe|msi|appimage|deb|rpm)$", lowered):
        score += 3
    if lowered.endswith(".zip"):
        score += 1
    return score


def version_of(tag):
    return re.sub(r"^(?:[a-z]+-)?v?", "", tag, flags=re.I) or tag


def button_svg(label, version, color):
    label, version = escape(label), escape(version[:28])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="190" height="52" '
        f'viewBox="0 0 190 52" role="img" aria-label="Download {label} {version}">'
        f'<title>Download {label} {version}</title>'
        f'<rect x="1" y="1" width="188" height="50" rx="10" fill="{color}"/>'
        '<path d="M24 14v14m-6-6 6 6 6-6M17 34h14" fill="none" stroke="#14161b" '
        'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>'
        '<text x="110" y="23" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
        f'font-size="14" font-weight="700" fill="#14161b">{label}</text>'
        '<text x="110" y="39" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" '
        f'font-size="11" fill="#14161b">{version}</text></svg>\n'
    )


def base_version(tag):
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", tag)
    return match.groups() if match else None


def choose(releases):
    releases = sorted(
        (r for r in releases if not r.get("draft") and r.get("published_at")),
        key=lambda r: r["published_at"],
        reverse=True,
    )
    # Offer only the current version line: an older line (e.g. 0.7 next to 0.8)
    # must not reappear as a platform download just because it is the last one
    # that happened to ship that platform.
    current = next(
        (
            base_version(r["tag_name"])
            for r in releases
            if base_version(r["tag_name"])
            and any(platforms(a.get("name", "")) for a in r.get("assets", []))
        ),
        None,
    )
    chosen = {}
    for release in releases:
        if base_version(release["tag_name"]) != current:
            continue
        best = {}
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if asset.get("state") != "uploaded":
                continue
            for label in platforms(name):
                if label in chosen:
                    continue
                if label not in best or preference(name) > preference(best[label]["name"]):
                    best[label] = asset
        for label, asset in best.items():
            chosen[label] = (release["tag_name"], asset)
    return chosen


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases?per_page=100", headers=headers
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        chosen = choose(json.load(response))
    if not chosen:
        print("No platform-specific release assets; keeping existing buttons unchanged.")
        return

    color = BRAND[repo.split("/")[-1].lower()]
    BUTTON_DIR.mkdir(parents=True, exist_ok=True)
    keep, links = set(), []
    for label in ORDER:
        if label not in chosen:
            continue
        tag, asset = chosen[label]
        version = version_of(tag)
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        path = BUTTON_DIR / f"download-{slug}.svg"
        path.write_text(button_svg(label, version, color), encoding="utf-8")
        keep.add(path.name)
        url = escape(asset["browser_download_url"], quote=True)
        title = escape(f"{asset['name']} herunterladen / download", quote=True)
        alt = escape(f"Download {label} {version}", quote=True)
        links.append(
            f'<a href="{url}" title="{title}"><img src="{path.as_posix()}" '
            f'alt="{alt}" width="190" height="52"></a>'
        )
    for stale in BUTTON_DIR.glob("download-*.svg"):
        if stale.name not in keep:
            stale.unlink()

    block = '<p align="center">\n  ' + "\n  &nbsp;\n  ".join(links) + "\n</p>"
    for page in (Path("README.md"), Path("README.de.md")):
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        if START not in text or END not in text:
            raise SystemExit(f"Missing AUTO-DOWNLOADS markers in {page}")
        head, rest = text.split(START, 1)
        page.write_text(head + START + "\n" + block + "\n" + END + rest.split(END, 1)[1], encoding="utf-8")
    print(f"Updated {len(links)} direct download buttons for {repo}")


if __name__ == "__main__":
    main()
