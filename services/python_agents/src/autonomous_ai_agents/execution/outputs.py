"""Output comparison under a workload's tolerance (D39) and the frozen-path mask (D37).

``canonical`` rewrites an output so two outputs a workload's
``OutputTolerance`` calls equal get the same bytes: strict UTF-8; a whole
token (split on ASCII whitespace and ``,;:=()[]{}"'``, delimiters kept byte
for byte) that is a decimal with a ``.`` or an exponent becomes
``format(float(t), ".{d}g")``; integers, ``nan``, ``inf``, zeros, overflow and
subnormals stay verbatim (rounding them could make unequal values equal);
then lines are sorted when unordered. It is sound one way: equal after
rounding means a relative difference under ``10**(1 - d)``; values within
that may still round apart, a false "changed", never a false "equal".

``mask`` deletes the frozen evaluation files from a worktree before a
workload runs, walking directory fds with ``O_NOFOLLOW`` so no link, at any
depth, is followed out of the worktree.
"""

from __future__ import annotations

import errno
import hashlib
import math
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from autonomous_ai_agents.common.models import OutputTolerance
from autonomous_ai_agents.common.paths import literal_project_file
from autonomous_ai_agents.execution.procrun import RunFailure

TOLERANT_TAG = b"aip-output-tolerant/1"
"""Domain tag: a canonical fingerprint never equals an exact one."""
_DELIMITERS = r"\s,;:=()\[\]{}\"'"
_NUMBER = re.compile(
    rf"(?<![^{_DELIMITERS}])[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)"
    rf"(?:[eE][+-]?[0-9]+)?(?![^{_DELIMITERS}])",
    re.ASCII,
)
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _rounded(digits: int, match: re.Match[str]) -> str:
    token = match[0]
    if not any(mark in token for mark in ".eE"):
        return token  # an integer: exact
    value = float(token)
    if not math.isfinite(value) or abs(value) < sys.float_info.min:
        return token  # overflow, zero, underflow or a subnormal: verbatim
    return format(value, f".{digits}g")


def canonical(data: bytes, tolerance: OutputTolerance) -> bytes:
    """The bytes ``tolerance`` compares; ``UnicodeDecodeError`` if not UTF-8."""
    text = data.decode("utf-8")
    digits = tolerance.float_digits
    if digits is not None:
        text = _NUMBER.sub(lambda match: _rounded(digits, match), text)
    if tolerance.unordered_lines:
        *lines, tail = text.split("\n")  # the unterminated tail stays last
        text = "".join(f"{line}\n" for line in sorted(lines)) + tail
    return text.encode("utf-8")


def tolerant_fingerprint(
    stdout: bytes, file: bytes | None, tolerance: OutputTolerance
) -> str:
    """sha256 over the options, then fixed-width (len, sha256) of each part."""
    digits, unordered = tolerance.float_digits or 0, int(tolerance.unordered_lines)
    parts = [TOLERANT_TAG, f"digits={digits};unordered={unordered}".encode(), b"\0"]
    for label, data in ((b"stdout", stdout), (b"file", file)):
        if data is not None:
            shown = canonical(data, tolerance)
            size = len(shown).to_bytes(8, "big")
            parts += [label, size, hashlib.sha256(shown).digest()]
    return hashlib.sha256(b"".join(parts)).hexdigest()


@dataclass
class Retained:
    """A sink keeping at most ``cap`` bytes; ``data`` is ``None`` past it."""

    cap: int
    _kept: bytearray | None = field(default_factory=bytearray, init=False, repr=False)

    def __call__(self, chunk: bytes) -> None:
        if self._kept is not None:
            self._kept += chunk
            if len(self._kept) > self.cap:
                self._kept = None

    @property
    def data(self) -> bytes | None:
        return None if self._kept is None else bytes(self._kept)


@dataclass(frozen=True)
class RunOutput:
    """One run's fingerprints (``canonical`` is ``raw`` without a tolerance),
    the scoring input (``data``) and why a tolerance was not applied."""

    raw: str
    canonical: str
    data: bytes | None = field(default=None, repr=False)
    note: str | None = None


def resolve(
    raw: str,
    stdout: bytes | None,
    file: Retained | None,
    tolerance: OutputTolerance | None,
    head_bytes: int,
) -> RunOutput:
    """``stdout`` is ``None`` when incomplete; ``file`` when none is declared.

    A tolerance applies to complete outputs only, else the exact fingerprint
    stands with a note (D39)."""
    kept = None if file is None else file.data
    data = stdout if file is None else kept
    if tolerance is None:
        return RunOutput(raw, raw, data)
    if stdout is None:
        why = f"stdout is longer than the {head_bytes} bytes kept"
    elif file is not None and kept is None:
        why = f"the output file is larger than {file.cap} bytes"
    else:
        try:
            return RunOutput(raw, tolerant_fingerprint(stdout, kept, tolerance), data)
        except UnicodeDecodeError:
            why = "the output is not UTF-8"
    note = f"compared exactly, not within its tolerance: {why}"
    return RunOutput(raw, raw, data, note)


def check_mask(paths: Sequence[str]) -> None:
    """Each mask entry is already a literal project file (never a glob): the
    quality check's rule (``literal_project_file``), and its own fixed point."""
    for path in paths:
        refused = f"a mask path must be a clean project file, got {path!r}"
        try:
            clean = literal_project_file("a mask path", path) == path
        except ValueError as error:
            raise ValueError(f"{refused}: {error}") from None
        if not clean:
            raise ValueError(refused)


def mask(root: Path, paths: Sequence[str]) -> None:
    """Delete each path under ``root`` without following any link.

    A missing file or parent is already masked; a link is removed, never its
    target. ``RunFailure`` when a parent is not a plain directory, the path is
    a directory or the delete fails, since the workload could then still
    reach the file.
    """
    if not paths:
        return
    try:
        top = os.open(root, _DIR_FLAGS)
    except (OSError, ValueError) as error:
        why = error.strerror if isinstance(error, OSError) else str(error)
        raise RunFailure(f"cannot open the worktree to mask it: {why}") from None
    try:
        for path in paths:
            _unlink(top, path)
    finally:
        os.close(top)


def _unlink(top: int, path: str) -> None:
    *parents, name = path.split("/")
    fds: list[int] = []
    try:
        for part in parents:
            fds.append(os.open(part, _DIR_FLAGS, dir_fd=fds[-1] if fds else top))
        where = fds[-1] if fds else top
        if stat.S_ISDIR(os.stat(name, dir_fd=where, follow_symlinks=False).st_mode):
            raise RunFailure(f"cannot mask {path!r}: is a directory")
        os.unlink(name, dir_fd=where)
    except FileNotFoundError:
        pass
    except OSError as error:
        linked = error.errno in (errno.ELOOP, errno.ENOTDIR)
        why = "a parent is not a directory" if linked else error.strerror
        raise RunFailure(f"cannot mask {path!r}: {why}") from None
    except ValueError as error:  # a NUL byte
        raise RunFailure(f"cannot mask {path!r}: {error}") from None
    finally:
        for fd in fds:
            os.close(fd)
