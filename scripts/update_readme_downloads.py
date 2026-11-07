#!/usr/bin/env python3
"""Refresh README download badges from actual GitHub Release assets (including prereleases)."""
import json, os, re, urllib.request
from pathlib import Path
from html import escape

repo = os.environ["GITHUB_REPOSITORY"]
token = os.environ["GITHUB_TOKEN"]
readme = Path("README.md")
start, end = "<!-- AUTO-DOWNLOADS:START -->", "<!-- AUTO-DOWNLOADS:END -->"
headers = {"Accept":"application/vnd.github+json", "Authorization":f"Bearer {token}", "X-GitHub-Api-Version":"2022-11-28"}
req = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases?per_page=100",headers=headers)
with urllib.request.urlopen(req, timeout=25) as response:
    releases = json.load(response)
# Latest means newest published package per platform, not latest source commit.
releases = sorted((r for r in releases if not r.get("draft") and r.get("published_at")),
                  key=lambda r:r["published_at"], reverse=True)
platforms = [
    ("macOS Intel", r"(?:mac|darwin|osx|intel)", r"(?:windows|win32|win64|linux|arm64|aarch64|apple.silicon|universal|\\.exe$|\\.msi$)"),
    ("macOS Apple Silicon", r"(?:mac|darwin|osx)", r"(?:windows|win32|win64|linux|intel|x86_64|amd64|\\.exe$|\\.msi$)"),
    ("Windows", r"(?:windows|win32|win64|win11|\.exe$|\.msi$)", r"(?:macos|darwin|osx|linux|\.dmg$|\.pkg$|\.appimage$)"),
    ("Linux", r"(?:linux|ubuntu|debian|\.appimage$|\.deb$|\.rpm$)", r"(?:windows|win32|win64|darwin|macos|\.dmg$|\.exe$|\.msi$)"),
]
# Only packages, never checksums, source archives, or documentation.
ext = re.compile(r"(?:\.zip|\.dmg|\.pkg|\.exe|\.msi|\.appimage|\.deb|\.rpm|\.tar\.gz)$", re.I)
bad = re.compile(r"(?:checksum|sha256|source|symbols|debug|sbom|manifest|\.sig\.|\.asc$)", re.I)
chosen = {}
for label, include, exclude in platforms:
    for release in releases:
        for asset in release.get("assets",[]):
            name = asset.get("name","")
            if (asset.get("state") == "uploaded" and ext.search(name) and not bad.search(name)
                and re.search(include,name,re.I) and not re.search(exclude,name,re.I)
                and (label != "macOS Apple Silicon" or re.search(r"(?:arm64|aarch64|apple.silicon|universal)",name,re.I))
                and (label != "macOS Intel" or re.search(r"(?:mac|darwin|osx|intel)",name,re.I))):
                chosen[label] = (release["tag_name"], asset["browser_download_url"])
                break
        if label in chosen: break

# Non-platform-labelled archives cannot be safely claimed as a specific OS.
colors = {"KiraBridge":"#6060c0", "threaddesk":"#b99cff", "4AllPass":"#5b6fa8"}
color = colors[repo.split("/")[-1]]
button_dir = Path("assets/readme")
button_dir.mkdir(parents=True, exist_ok=True)
links=[]
for label,(version,url) in chosen.items():
    slug = re.sub(r"[^a-z0-9]+","-",label.lower()).strip("-")
    path=button_dir / f"download-auto-{slug}.svg"
    v=escape(version[:28]); name=escape(label)
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" width="174" height="48" viewBox="0 0 174 48" role="img" aria-label="{name} {v}">'
         f'<rect x="1" y="1" width="172" height="46" rx="8" fill="{color}" fill-opacity=".14" stroke="{color}" stroke-width="1.2"/>'
         f'<text x="87" y="20" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" font-weight="bold" fill="{color}">{name}</text>'
         f'<text x="87" y="36" text-anchor="middle" font-family="Arial,sans-serif" font-size="10" fill="{color}">{v}</text></svg>\n')
    path.write_text(svg,encoding="utf-8")
    links.append(f'<a href="{escape(url,quote=True)}"><img src="{path.as_posix()}" alt="{name} {v}" width="174"></a>')

if not links:
    print("No verified platform-specific release assets; keeping existing links unchanged.")
    raise SystemExit(0)
block='<p align="center">\n  '+'\n  &nbsp;\n  '.join(links)+'\n</p>'
src=readme.read_text(encoding="utf-8")
if start not in src or end not in src:
    raise SystemExit("Missing README AUTO-DOWNLOADS markers")
src = src[:src.index(start)+len(start)]+'\n'+block+'\n'+src[src.index(end):]
readme.write_text(src, encoding="utf-8")
print(f"Updated {len(links)} verified platform buttons for {repo}")
