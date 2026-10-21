"""Project-relative path rules shared by models and the anti-cheating checks.

A path the engine stores or touches must be relative to the project root
and must never escape it: no absolute paths, drive letters, ``~`` or ``..``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


class PathTraversalError(ValueError):
    """Raised for absolute paths, home-relative paths or any ``..`` segment."""


def normalize_path(path: str) -> str:
    """Return ``path`` as a clean POSIX path relative to the project root.

    Backslashes become slashes, ``./`` prefixes and doubled slashes are
    collapsed. Absolute, drive-letter, ``~`` and ``..`` paths are refused.
    """
    candidate = path.replace("\\", "/")
    if candidate.startswith(("/", "~")) or _WINDOWS_DRIVE.match(candidate):
        raise PathTraversalError(f"path must be relative to the project root: {path!r}")
    posix = PurePosixPath(candidate)
    if ".." in posix.parts:
        raise PathTraversalError(f"path must not contain '..': {path!r}")
    return posix.as_posix()
