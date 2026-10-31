"""The last Python traceback in a stderr tail, as CPython 3.8-3.14 print it.

``parse_traceback`` reads the tail backwards from its last non-blank line,
which must be ``Type`` or ``Type: message``. Above it, ``  File "...", line
N[, in NAME]`` lines are frames; their source lines, PEP 657 caret lines (3.11+)
and ``[Previous line repeated ...]`` are skipped; anything else (the
``Traceback`` header, the chaining text, other output, a line cut by the tail's
start) ends the block, so a chained traceback gives its last exception. A
``SyntaxError`` location (``File`` with no ``in``) is the innermost frame,
with no function. Nothing here is trusted: a workload can print any text, so
``retry.classify`` checks every field before anything reaches a prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FRAME = re.compile(
    r'  File "(?P<path>.+)", line (?P<line>\d{1,12})(?:, in (?P<fn>.+))?'
)
_EXCEPTION = re.compile(r"(?P<type>[A-Za-z_][A-Za-z0-9_.]*)(?:: (?P<message>.*))?")
_REPEATED = re.compile(r"  \[Previous line repeated \d+ more times?\]")


@dataclass(frozen=True)
class CrashFrame:
    """One frame as printed; ``function`` is ``None`` for a syntax location."""

    path: str
    line: int
    function: str | None


@dataclass(frozen=True)
class CrashReport:
    """The final exception: its printed type, message and frames, outermost first."""

    exc_type: str
    message: str | None
    frames: tuple[CrashFrame, ...]


def parse_traceback(tail: bytes) -> CrashReport | None:
    """The last traceback of ``tail``, or ``None`` when it ends in none."""
    lines = tail.decode("utf-8", errors="replace").splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines or (last := _EXCEPTION.fullmatch(lines[-1])) is None:
        return None
    frames: list[CrashFrame] = []
    for text in reversed(lines[:-1]):
        if (frame := _FRAME.fullmatch(text)) is not None:
            frames.append(CrashFrame(frame["path"], int(frame["line"]), frame["fn"]))
        elif not (text.startswith("    ") or _REPEATED.fullmatch(text)):
            break
    if not frames:
        return None
    return CrashReport(last["type"], last["message"], tuple(reversed(frames)))
