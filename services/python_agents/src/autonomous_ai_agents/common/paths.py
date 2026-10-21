"""Project-relative path rules shared by models, the editor and the anti-cheating checks.

A path the engine stores or touches must be relative to the project root
and must never escape it: no absolute paths, drive letters, ``~`` or ``..``.

``matches_pattern`` is the one matcher behind the protected-path check, the
editor's read and write deny lists and the capture rules, and the pattern
constants below are the one definition the editor handler and the capture
rules both enforce.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
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


GIT_METADATA_NAMES: tuple[str, ...] = (
    ".git",
    ".gitattributes",
    ".gitmodules",
    ".lfsconfig",
)
"""Path components and names a trial may never write; compared case-insensitively.

In a linked worktree ``.git`` is a file naming the user's real git dir, and
the other three change how git filters, nests or fetches content.
``.gitignore`` is deliberately absent: ``clean -ffdx`` ignores it."""

WRITE_DENY_PATTERNS: tuple[str, ...] = (
    "**/__pycache__/**",
    "*.pyc",
    "*.pyo",
    "*.so",
    "*.pyd",
    "*.dylib",
    "*.dll",
)
"""Compiled artefacts a trial may not create, change or delete.

Bytecode and native libraries are not reviewable source, and a stale
``.pyc`` or a swapped ``.so`` changes what runs without changing the diff a
human reads. ``*`` crosses ``/`` in ``fnmatch``, so ``*.so`` covers any depth."""

READ_DENY_PATTERNS: tuple[str, ...] = (
    "**/.env",
    "**/.env.*",
    "**/.envrc",
    "*.pem",
    "*.key",
    "**/id_rsa*",
    "**/id_dsa*",
    "**/id_ecdsa*",
    "**/id_ed25519*",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "*.p12",
    "*.pfx",
    "**/credentials",
    "**/credentials.*",
    "**/secrets.*",
)
"""Files the editor refuses to ``view``: whatever it returns is sent to the API.

Environment files (``.envrc`` is direnv's), TLS and SSH keys, package-index
and netrc credentials, PKCS#12 stores and generic credential or secrets
files. ``**/`` makes a name match at the root and at any depth.

``*`` crosses ``/`` in ``fnmatch``, so a name with a bare trailing ``*``
(``id_*``, ``credentials*``) would also deny every module and directory that
merely starts with it (``id_utils/``, ``credentials_loader.py``). SSH keys are
therefore named by algorithm, and ``credentials`` / ``secrets`` need an exact
name or a ``.`` right after it."""


def matches_pattern(path: str, pattern: str) -> bool:
    """fnmatch on case-folded text, with ``**/x`` also matching a root-level ``x``.

    Case is folded on both sides because the user's checkout may sit on a
    case-insensitive filesystem (macOS, Windows): there ``src/Conftest.py`` is
    the file pytest loads as ``conftest.py``, so it must be protected too.
    ``path`` is expected to be normalised already (``normalize_path``).
    """
    folded_path, folded_pattern = path.casefold(), pattern.casefold()
    if fnmatchcase(folded_path, folded_pattern):
        return True
    return folded_pattern.startswith("**/") and fnmatchcase(
        folded_path, folded_pattern[3:]
    )
