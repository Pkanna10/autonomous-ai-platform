"""Shared rules for reading repository text at a commit (Step 3 Wave 2, D44).

Moved from ``orchestrator/understand.py`` so the understander and the idea
pipeline's code context (``optimization/idea_context.py``) read with one
policy, and no module under ``optimization/`` imports ``orchestrator/``:

- ``RepoReader``: git objects at a commit (``GitWorkspace`` is the real one),
  never the working tree.
- ``read_text``: one blob's head as text. A path matching
  ``READ_DENY_PATTERNS`` is never asked of git; git hands over at most one
  byte past the cap and never less than ``BINARY_SNIFF_BYTES``, so a huge
  tracked file is never held whole and a short cap cannot hide a NUL from
  git's binary rule; the head is decoded incrementally, so a character split
  by the cut is left out while invalid UTF-8 is refused. The result is the
  text and whether it was cut, or the reason it is not text. The reader's
  own errors (``GitError`` for git) propagate for the caller to classify.
- ``unprintable``: controls, separators and bidi overrides (forged lines or
  markers), or text that is not UTF-8.
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass
from typing import Final, Protocol

from autonomous_ai_agents.common.paths import READ_DENY_PATTERNS, matches_pattern

BINARY_SNIFF_BYTES: Final = 8000  # git's rule: a NUL in the first 8000 bytes
DENIED: Final = "a secret-like file never read"
BINARY: Final = "binary"
NOT_UTF8: Final = "not UTF-8"

# C0, DEL, C1 (NEL), the line and paragraph separators and the bidi controls.
UNPRINTABLE: Final = re.compile(
    r"[\x00-\x1f\x7f-\x9f\u200e\u200f\u2028-\u202e\u2066-\u2069]"
)


class RepoReader(Protocol):
    """Git objects at a commit; ``GitWorkspace`` is the real one."""

    def ls_tree(self, commit: str) -> tuple[str, ...]: ...

    def read_blob(
        self, commit: str, path: str, *, limit: int | None = None
    ) -> bytes: ...


@dataclass(frozen=True)
class ReadText:
    """A blob's head decoded as UTF-8; ``cut`` when the blob is longer."""

    text: str
    cut: bool


def read_denied(path: str) -> bool:
    """Whether ``path`` matches a ``READ_DENY_PATTERNS`` entry (never read)."""
    return any(matches_pattern(path, pattern) for pattern in READ_DENY_PATTERNS)


def read_text(
    reader: RepoReader, commit: str, path: str, *, cap: int
) -> ReadText | str:
    """At most ``cap`` bytes of ``path`` at ``commit`` as text, or the reason
    it is not text (``DENIED``, ``BINARY`` or ``NOT_UTF8``)."""
    if cap < 1:
        raise ValueError(f"cap must be at least 1 byte, got {cap}")
    if read_denied(path):
        return DENIED
    # One byte past the cap shows a cut; never less than the sniff.
    data = reader.read_blob(commit, path, limit=max(cap + 1, BINARY_SNIFF_BYTES))
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return BINARY
    cut = len(data) > cap
    try:  # only the head is decoded; a character split by the cut is left out
        text = codecs.getincrementaldecoder("utf-8")().decode(data[:cap], final=not cut)
    except UnicodeDecodeError:
        return NOT_UTF8
    return ReadText(text, cut)


def unprintable(text: str) -> bool:
    """Controls, separators, bidi overrides (forged lines or markers), no UTF-8."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return UNPRINTABLE.search(text) is not None
