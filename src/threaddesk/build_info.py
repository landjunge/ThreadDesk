"""Read the identity embedded during packaging; never run Git in the app."""

import hashlib
import json
import re
import sys
from pathlib import Path

from threaddesk import __version__


def _packaged_identity():
    try:
        data = json.loads(Path(__file__).with_name("_build_info.json").read_text(encoding="utf-8"))
        if (data["version"] != __version__
                or not re.fullmatch(r"[0-9a-f]{40}", data["source_commit"])
                or not isinstance(data["dirty"], bool)
                or not isinstance(data["build_id"], str)):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError):
        return None


_identity = _packaged_identity()
SOURCE_COMMIT = _identity["source_commit"] if _identity else ""
BUILD_ID = _identity["build_id"] if _identity else "source"
BUILD_LABEL = f"v{__version__} · " + (
    SOURCE_COMMIT[:7] + ("+lokal" if _identity["dirty"] else "")
    if _identity else "Quellstand"
)
BUILD_DESCRIPTION = (
    f"ThreadDesk {__version__} · Commit {SOURCE_COMMIT} · Build {BUILD_ID}"
    if _identity else f"ThreadDesk {__version__} · nicht paketierter Quellstand"
)

_CHECKSUM_BLOCK = 65536
_prefix_cache: dict[tuple[bool, str], str] = {}


def frozen_program_prefix() -> str:
    """First eight hex digits of a frozen program, remembered after one read.

    A source checkout and a program that cannot be read contribute nothing.
    The caller keeps the existing label, and no exception leaves this function.
    """
    frozen = bool(getattr(sys, "frozen", False))
    executable = getattr(sys, "executable", "") if frozen else ""
    key = (frozen, executable if isinstance(executable, str) else "")
    cached = _prefix_cache.get(key)
    if cached is not None:
        return cached
    prefix = ""
    if frozen and isinstance(executable, str) and executable:
        try:
            digest = hashlib.sha256()
            with open(executable, "rb") as handle:
                while True:
                    block = handle.read(_CHECKSUM_BLOCK)
                    if not block:
                        break
                    digest.update(block)
            prefix = digest.hexdigest()[:8]
        except Exception:
            prefix = ""
    _prefix_cache[key] = prefix
    return prefix


def visible_build_label() -> str:
    """Version and source label, plus the frozen program prefix when it exists."""
    prefix = frozen_program_prefix()
    if not prefix:
        return BUILD_LABEL
    return f"{BUILD_LABEL} · {prefix}"


class VisibleBuildLabel:
    """Header value rendered when the page is shown, not when the module loads."""

    def __str__(self) -> str:
        return visible_build_label()

    def __html__(self) -> str:
        return str(self)
