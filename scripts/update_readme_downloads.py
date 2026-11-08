#!/usr/bin/env python3
"""Refresh README download buttons from published GitHub Release assets.

Every button links straight to the installation file (``browser_download_url``),
never to a release page, so one click starts the download. Drafts are ignored;
prereleases count because the products currently ship previews only.

Shared by KiraBridge, ThreadDesk and 4AllPass; the three copies are identical
(see TOOL_VERSION). Only the block between the AUTO-DOWNLOADS markers in
README.md / README.de.md and the generated ``assets/readme/download-<platform>.svg``
buttons are touched. Other ``download-*.svg`` files are never removed.

Before anything is written, every chosen asset is confirmed through the
Releases API and, for public repositories, the download URL itself must answer.
If a check fails, nothing is changed and the script exits non-zero.

Usage:
  update_readme_downloads.py             refresh files in the current checkout
  update_readme_downloads.py --dry-run   print the chosen downloads, write nothing
  update_readme_downloads.py --self-test check the platform rules, no network
Environment: GITHUB_REPOSITORY (owner/name) and GITHUB_TOKEN or GH_TOKEN.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path

TOOL_VERSION = "2.0.0"
START, END = "<!-- AUTO-DOWNLOADS:START -->", "<!-- AUTO-DOWNLOADS:END -->"
BUTTON_DIR = Path("assets/readme")
API = "https://api.github.com"

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

PACKAGE = re.compile(r"\.(?:dmg|pkg|exe|msi|appimage|deb|rpm|zip|tar\.gz)$", re.IGNORECASE)
NOT_PACKAGE = re.compile(
    r"(?:checksum|sha256|sha512|sbom|manifest|symbols|debug|notices|evidence|"
    r"source|\.sig$|\.asc$|\.whl$|-review|build-only|historical-)",
    re.IGNORECASE,
)
WINDOWS = re.compile(r"(?:windows|win32|win64|win11|\.exe$|\.msi$)", re.IGNORECASE)
LINUX = re.compile(r"(?:linux|ubuntu|debian|\.appimage$|\.deb$|\.rpm$)", re.IGNORECASE)
MAC = re.compile(r"(?:mac|darwin|osx|apple|intel|\.dmg$|\.pkg$)", re.IGNORECASE)
ARM = re.compile(r"(?:arm64|aarch64|apple.?silicon)", re.IGNORECASE)
UNIVERSAL = re.compile(r"universal", re.IGNORECASE)


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


MANAGED = {f"download-{slug(label)}.svg" for label in ORDER}


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
    return re.sub(r"^(?:[a-z]+-)?v?", "", tag, flags=re.IGNORECASE) or tag


def button_svg(label, version, color):
    label, version = escape(label), escape(version[:28])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="190" height="52" '
        f'viewBox="0 0 190 52" role="img" aria-label="Download {label} {version}">'
        f"<title>Download {label} {version}</title>"
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


# --- network -----------------------------------------------------------------


def _token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN or GH_TOKEN is required")
    return token


def api(path):
    """GET a GitHub API path with three attempts for transient failures."""
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {_token()}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "readme-downloads",
    }
    for attempt in range(3):
        try:
            request = urllib.request.Request(API + path, headers=headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            error = exc
        time.sleep(5 * (attempt + 1))
    raise SystemExit(f"GitHub API {path} failed after 3 attempts: {error}")


def all_releases(repo):
    releases, page = [], 1
    while True:
        batch = api(f"/repos/{repo}/releases?per_page=100&page={page}")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def public_download_ok(url):
    """A public download URL must answer (GitHub redirects to its file CDN)."""
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "readme-downloads"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.status == 200
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return False
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5 * (attempt + 1))
    return False


def verify(repo, private, chosen):
    """Return a list of problems; empty means every link may be published."""
    problems = []
    for label, (_tag, asset) in chosen.items():
        current = api(f"/repos/{repo}/releases/assets/{asset['id']}")
        if current.get("state") != "uploaded" or not current.get("size"):
            problems.append(f"{label}: asset {asset['name']} is not a complete upload")
            continue
        if current.get("browser_download_url") != asset["browser_download_url"]:
            problems.append(f"{label}: asset {asset['name']} changed while checking")
            continue
        if not private and not public_download_ok(asset["browser_download_url"]):
            problems.append(f"{label}: {asset['browser_download_url']} does not answer")
    return problems


# --- output ------------------------------------------------------------------


def render(repo, chosen):
    """Return ({button file: svg}, readme block) for the chosen downloads."""
    color = BRAND[repo.split("/")[-1].lower()]
    buttons, links = {}, []
    for label in ORDER:
        if label not in chosen:
            continue
        tag, asset = chosen[label]
        version = version_of(tag)
        path = BUTTON_DIR / f"download-{slug(label)}.svg"
        buttons[path] = button_svg(label, version, color)
        url = escape(asset["browser_download_url"], quote=True)
        title = escape(f"{asset['name']} herunterladen / download", quote=True)
        alt = escape(f"Download {label} {version}", quote=True)
        links.append(
            f'<a href="{url}" title="{title}"><img src="{path.as_posix()}" '
            f'alt="{alt}" width="190" height="52"></a>'
        )
    block = '<p align="center">\n  ' + "\n  &nbsp;\n  ".join(links) + "\n</p>"
    return buttons, block


def replace_block(text, block, page):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise SystemExit(f"{page} needs exactly one AUTO-DOWNLOADS START/END marker pair")
    head, rest = text.split(START, 1)
    tail = rest.split(END, 1)[1]
    return head + START + "\n" + block + "\n" + END + tail


def write(buttons, block):
    pages = [p for p in (Path("README.md"), Path("README.de.md")) if p.exists()]
    if not pages:
        raise SystemExit("No README.md in the current directory")
    # Validate every page before touching any file.
    updated = {page: replace_block(page.read_text(encoding="utf-8"), block, page) for page in pages}
    BUTTON_DIR.mkdir(parents=True, exist_ok=True)
    for path, svg in buttons.items():
        if not path.exists() or path.read_text(encoding="utf-8") != svg:
            path.write_text(svg, encoding="utf-8")
    for name in MANAGED - {p.name for p in buttons}:
        (BUTTON_DIR / name).unlink(missing_ok=True)
    for page, text in updated.items():
        if page.read_text(encoding="utf-8") != text:
            page.write_text(text, encoding="utf-8")


def summary(lines):
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def self_test():
    cases = {
        "4AllPass_0.1.2-rc.2_aarch64.dmg": ["macOS Apple Silicon"],
        "4AllPass_0.1.2-rc.2_x64.dmg": ["macOS Intel"],
        "4AllPass_0.1.2-rc.2_x64-setup.exe": ["Windows"],
        "4AllPass_0.1.2-rc.2_amd64.AppImage": ["Linux"],
        "ThreadDesk-macOS-AppleSilicon.dmg": ["macOS Apple Silicon"],
        "ThreadDesk-macOS.dmg": ["macOS Intel"],
        "ThreadDesk-Windows.exe": ["Windows"],
        "KiraBridge-0.8.0rc36-Intel-Installer.zip": ["macOS Intel"],
        "KiraBridge-0.8.0rc37.dev1-Windows-Dev-Kit.zip": ["Windows"],
        "KiraBridge-0.8.0rc41-Linux-x86_64.tar.gz": ["Linux"],
        "App-universal.dmg": ["macOS Apple Silicon", "macOS Intel"],
        "SHA256SUMS": [],
        "third-party-notices-macOS.zip": [],
        "KiraBridge-0.8.0rc41-source.tar.gz": [],
        "historical-1-KiraBridge-macos.tar.gz": [],
        "kirabridge-0.8.0rc41-py3-none-any.whl": [],
        "4AllPass_0.1.2-rc.2_x64.dmg.sha256": [],
    }
    failed = [f"{n}: {platforms(n)} != {want}" for n, want in cases.items() if platforms(n) != want]
    releases = [
        {
            "tag_name": "v0.8.0rc2",
            "draft": False,
            "published_at": "2026-02-01",
            "assets": [{"name": "X-0.8.0rc2-Linux.tar.gz", "state": "uploaded"}],
        },
        {
            "tag_name": "v0.8.0rc1",
            "draft": False,
            "published_at": "2026-01-01",
            "assets": [
                {"name": "X-0.8.0rc1-Windows.zip", "state": "uploaded"},
                {"name": "X-0.8.0rc1-Linux.tar.gz", "state": "uploaded"},
            ],
        },
        {
            "tag_name": "v0.7.9",
            "draft": False,
            "published_at": "2025-12-01",
            "assets": [{"name": "X-0.7.9.dmg", "state": "uploaded"}],
        },
        {
            "tag_name": "v0.8.0rc3",
            "draft": True,
            "published_at": "2026-03-01",
            "assets": [{"name": "X-0.8.0rc3.dmg", "state": "uploaded"}],
        },
    ]
    picked = {label: tag for label, (tag, _) in choose(releases).items()}
    if picked != {"Linux": "v0.8.0rc2", "Windows": "v0.8.0rc1"}:
        failed.append(f"choose: {picked}")
    if failed:
        raise SystemExit("Self-test failed:\n  " + "\n  ".join(failed))
    print(f"Self-test passed ({len(cases)} names, version-line selection), tool {TOOL_VERSION}")


def main(argv):
    if "--self-test" in argv:
        self_test()
        return
    dry_run = "--dry-run" in argv
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise SystemExit("GITHUB_REPOSITORY (owner/name) is required")
    private = bool(api(f"/repos/{repo}").get("private"))
    chosen = choose(all_releases(repo))
    if not chosen:
        print("No platform-specific release assets; keeping existing buttons unchanged.")
        summary(["### README downloads", "", "No platform release assets; nothing changed."])
        return
    rows = [
        f"| {label} | {chosen[label][0]} | `{chosen[label][1]['name']}` |"
        for label in ORDER
        if label in chosen
    ]
    table = ["| Platform | Release | File |", "| --- | --- | --- |", *rows]
    print("\n".join(table))
    problems = verify(repo, private, chosen)
    if problems:
        summary(["### README downloads: not updated", "", *[f"- {p}" for p in problems]])
        raise SystemExit("Not updating README; failed checks:\n  " + "\n  ".join(problems))
    if dry_run:
        print("Dry run: all links verified, no files written.")
        return
    buttons, block = render(repo, chosen)
    write(buttons, block)
    summary(["### README downloads", "", *table])
    print(f"Verified {len(chosen)} direct download buttons for {repo} (tool {TOOL_VERSION})")


if __name__ == "__main__":
    main(sys.argv[1:])
