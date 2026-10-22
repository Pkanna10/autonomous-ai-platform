"""cProfile profiler: where the base commit spends its time, as untrusted hints.

``CProfiler.profile`` has the phase shape of decision 38: F0
(``repo_fingerprint``), ``<WORKTREE_ROOT>/<run>/profile`` at the commit with
``_scratch/profile`` and ``_probe/profile`` (``measure.make_phase``: the
sandbox, environment and reset of measurement), one untimed run per Python
workload, F1 (``RepoTamperedError`` when it differs), and in ``finally`` the
removal of all three, ``prune`` and an ``rmdir`` of ``<run>`` when empty.

Each run is ``python [options] _profile_shim.py OUT module|script TARGET``
(``profiled_argv``) from the working dir, right after a reset, with the
workload's timeout times ``PROFILE_TIMEOUT_FACTOR`` (cProfile's overhead; the
run is not timed); ``PYTHONPATH`` starts with the worktree (and its
``src``). A non-Python command, ``-c``, ``-``, ``-x``, a non-zero exit, a
``RunFailure`` or unusable output is a note (the node's ``profile_skipped``)
that ends with ``GUARD_SKIPPED``, as is every ``RunSample`` and
``RunFailure`` note.

The workload runs in the shim's interpreter, so its output is untrusted: the
engine never unmarshals pstats data; it reads the shim's JSON (size-capped,
never through a final link) and parses it strictly (``parse_profile``).
After a reset (only committed links remain) a frame is a hotspot only when
its file, links resolved first, is a tracked file inside the worktree
(``project_file``);
symbols are cleaned and capped. Hotspots rank by self time; share is self
time over the larger of the reported total and the summed self times (a
forged total cannot inflate it); at most ``HOTSPOTS_PER_WORKLOAD`` per
workload and ``MAX_HOTSPOTS`` in all, largest share first.

Editable installs: a frame that is, or links to, a tracked file of the
user's checkout (``checkout_file``: a ``.pth`` or ``sys.path`` entry, an
alias directory, a symlinked install such as ``flit install --symlink``)
means the workload imported the checkout, not the commit, so measurements
would time the wrong code: ``EngineError`` naming the frame's path, after F1
(tampering wins) and the cleanup. Untracked files there (an in-tree
``.venv``) do not count. This guards against misconfiguration; a hostile
workload can forge its profile, and a workload that is not profiled is not
checked (its note says so).

Cleanup never follows a link the workload planted in place of an engine dir
or of its parent; a dir it cannot remove safely is an ``EngineError`` after
every other step ran, unless an error is already on its way.

Known limits: time in C builtins and the stdlib stays with them; child
processes are not profiled; ``-I`` and ``-E`` ignore ``PYTHONPATH``; the
shim imports a few stdlib modules (``json``, ``runpy``, ``cProfile``...) with
``PYTHONPATH`` on ``sys.path``, so a repository module of the same name at
the top of the worktree breaks the profile run only (a note); a checkout on a
case-insensitive file system reached through a differently cased path is not
recognised (``realpath`` keeps the case it was given).
"""

from __future__ import annotations

import contextlib
import functools
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.models import Hotspot, Project, Workload
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.common.refnames import refname_problem
from autonomous_ai_agents.execution import _profile_shim
from autonomous_ai_agents.execution.git import (
    GitWorkspace,
    _contained,
    _rmtree,
    repo_fingerprint,
)
from autonomous_ai_agents.execution.measure import (
    _PYTHON,
    Phase,
    RunOnce,
    _launch,
    _read_regular,
    _UnusableError,
    make_phase,
)
from autonomous_ai_agents.execution.procrun import RunFailure, run_once
from autonomous_ai_agents.execution.protocols import ProfileResult, WorktreeHandle

PHASE = "profile"
PROFILE_NAME = "profile.json"
"""The shim's output, in the phase's scratch root (wiped before every run)."""
SHIM_PATH = Path(_profile_shim.__file__).resolve()
HOTSPOTS_PER_WORKLOAD = 10
MAX_HOTSPOTS = 30
MAX_SYMBOL_CHARS = 200
MAX_LINE = 2**31 - 1
MAX_COUNT = 2**53
MAX_SECONDS = 1e7
_QUOTE_CHARS = 300
PROFILE_TIMEOUT_FACTOR = 3.0
"""The profile run's timeout is the workload's times this: cProfile's
overhead is commonly 2-3x on call-heavy code, and the run is not timed."""
GUARD_SKIPPED = (
    "; the editable-install check did not run for it, so make sure the"
    " project is not installed with -e"
)
"""Ends every ``is not profiled`` note: only a profile can run the check."""


class ProfileFormatError(Exception):
    """The shim's output is not a document the engine accepts; says why."""


class NotProfiledError(Exception):
    """A workload command the shim cannot run; the message says why."""


@dataclass(frozen=True)
class ProfileEntry:
    """One frame of the shim's summary; only its shape and bounds are checked."""

    file: str
    line: int
    function: str
    primitive_calls: int
    total_calls: int
    self_s: float
    cumulative_s: float


@dataclass(frozen=True)
class ProfileDoc:
    total_s: float
    entries: tuple[ProfileEntry, ...]


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise ProfileFormatError("has an object with a repeated key")
    return found


def _constant(name: str) -> object:
    raise ProfileFormatError(f"holds {name}, which is not a number")


def _integer(value: object, what: str, top: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= top:
        raise ProfileFormatError(f"{what} must be an integer from 0 to {top}")
    return value


def _seconds(value: object, what: str) -> float:
    if not isinstance(value, float) or not 0 <= value <= MAX_SECONDS:
        raise ProfileFormatError(f"{what} must be a float from 0 to {MAX_SECONDS:g}")
    return value


def _text(value: object, what: str, top: int) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= top:
        raise ProfileFormatError(f"{what} must be text of 1 to {top} characters")
    return value


def _entry(item: object, index: int) -> ProfileEntry:
    where, keys = f"entry {index}", _profile_shim.ENTRY_KEYS
    if not isinstance(item, dict) or set(item) != set(keys):
        raise ProfileFormatError(f"{where} must hold exactly {', '.join(keys)}")
    primitive = _integer(
        item["primitive_calls"], f"{where}: primitive_calls", MAX_COUNT
    )
    total = _integer(item["total_calls"], f"{where}: total_calls", MAX_COUNT)
    if primitive > total:
        raise ProfileFormatError(f"{where}: primitive_calls exceeds total_calls")
    return ProfileEntry(
        file=_text(item["file"], f"{where}: file", _profile_shim.MAX_FILE_CHARS),
        line=_integer(item["line"], f"{where}: line", MAX_LINE),
        function=_text(
            item["function"], f"{where}: function", _profile_shim.MAX_FUNCTION_CHARS
        ),
        primitive_calls=primitive,
        total_calls=total,
        self_s=_seconds(item["self_s"], f"{where}: self_s"),
        cumulative_s=_seconds(item["cumulative_s"], f"{where}: cumulative_s"),
    )


def parse_profile(data: bytes) -> ProfileDoc:
    """The shim's document, or ``ProfileFormatError``: exact keys and types,
    finite non-negative bounded numbers, bounded strings and counts, no
    repeated key or entry, no NaN or Infinity, ASCII, at most the shim's cap."""
    if len(data) > _profile_shim.MAX_DOC_BYTES:
        raise ProfileFormatError(f"is larger than {_profile_shim.MAX_DOC_BYTES} bytes")
    if not data.isascii():
        raise ProfileFormatError("is not ASCII JSON")
    try:
        doc: object = json.loads(
            data.decode("ascii"), object_pairs_hook=_unique, parse_constant=_constant
        )
    except (ValueError, RecursionError):  # JSONDecodeError, int digit limit
        raise ProfileFormatError("is not valid JSON") from None
    if not isinstance(doc, dict) or set(doc) != set(_profile_shim.DOC_KEYS):
        raise ProfileFormatError(
            "its top level must hold exactly version, total_s, entries"
        )
    version = doc["version"]
    if type(version) is not int or version != _profile_shim.FORMAT_VERSION:
        raise ProfileFormatError(
            f"version must be the integer {_profile_shim.FORMAT_VERSION}"
        )
    total = _seconds(doc["total_s"], "total_s")
    items = doc["entries"]
    if not isinstance(items, list):
        raise ProfileFormatError("entries must be a list")
    if len(items) > _profile_shim.MAX_ENTRIES:
        raise ProfileFormatError(
            f"entries holds more than {_profile_shim.MAX_ENTRIES} entries"
        )
    entries = tuple(_entry(item, index) for index, item in enumerate(items))
    if len({(e.file, e.line, e.function) for e in entries}) != len(entries):
        raise ProfileFormatError("repeats an entry (file, line, function)")
    return ProfileDoc(total, entries)


_Target = tuple[list[str], str, str, list[str]]
"""Interpreter options, ``module`` or ``script``, the target, its arguments."""


def _split(command: Sequence[str]) -> _Target:
    """Parse a Python argv as CPython does; ``NotProfiledError`` otherwise."""
    if _PYTHON.fullmatch(PurePath(command[0]).name) is None:
        raise NotProfiledError(f"{command[0]!r} is not a Python interpreter")
    options: list[str] = []
    index = 1
    while index < len(command) and command[index].startswith("-"):
        arg = command[index]
        index += 1
        if arg == "-":
            raise NotProfiledError("it reads its program from stdin")
        if arg == "--":
            break
        takes_value = arg == "--check-hash-based-pycs"
        for at, flag in enumerate(arg[1:] if arg[1] != "-" else "", start=2):
            if flag == "c":
                raise NotProfiledError("inline code (-c) has no file to profile")
            if flag == "x":
                raise NotProfiledError("-x (skip the first line) is not supported")
            if flag == "m":
                head, attached = arg[1 : at - 1], arg[at:]
                if head:
                    options.append(f"-{head}")
                if attached:
                    return options, "module", attached, list(command[index:])
                if index == len(command):
                    raise NotProfiledError("-m names no module")
                return options, "module", command[index], list(command[index + 1 :])
            if flag in "WX":
                takes_value = not arg[at:]
                break
        options.append(arg)
        if takes_value and index < len(command):
            options.append(command[index])
            index += 1
    if index == len(command):
        raise NotProfiledError("it names no script or module")
    return options, "script", command[index], list(command[index + 1 :])


def _assemble(python: str, target: _Target, out: Path) -> list[str]:
    options, kind, name, args = target
    return [python, *options, str(SHIM_PATH), str(out), kind, name, *args]


def profiled_argv(command: Sequence[str], out: Path) -> list[str]:
    """``command`` run under the shim, which writes ``out``; ``NotProfiledError``."""
    return _assemble(command[0], _split(command), out)


def _printable(text: str, replace: str) -> str:
    return "".join(ch if ch.isprintable() else replace for ch in text)


def clean_symbol(text: str) -> str:
    """A function name without control or format characters, capped."""
    return _printable(text, "")[:MAX_SYMBOL_CHARS].strip()


def _quote(text: str) -> str:
    return _printable(text[:_QUOTE_CHARS], "?")


def _joined(file: str, cwd: Path) -> str | None:
    """``file`` joined to ``cwd`` (not normalised), or ``None``: NUL, not UTF-8."""
    try:
        file.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate (undecodable file name bytes)
        return None
    if "\0" in file:
        return None
    return os.path.join(cwd, file)


def project_file(
    file: str, *, cwd: Path, worktree: Path, tracked: frozenset[str]
) -> str | None:
    """The tracked project-relative file that ``file`` resolves to inside
    ``worktree`` (reset first: only committed links are followed), or ``None``.
    Links resolve before ``..``, as the kernel does: ``link/../x`` is not
    ``x`` when ``link`` points elsewhere."""
    joined = _joined(file, cwd)
    if joined is None:
        return None
    real, root = Path(os.path.realpath(joined)), Path(os.path.realpath(worktree))
    if not real.is_relative_to(root):
        return None
    rel = real.relative_to(root).as_posix()
    try:
        clean = normalize_path(rel)
    except ValueError:  # a tracked '~x' or 'c:x' name
        return None
    return rel if clean == rel and rel in tracked else None


def checkout_file(
    file: str, *, cwd: Path, roots: Sequence[Path], tracked: frozenset[str]
) -> str | None:
    """``file`` normalised when it, or what its links resolve to, is a tracked
    file of the user's checkout (any of ``roots``), else ``None``. Either
    form counts, wherever the frame's own path is (a symlinked install)."""
    joined = _joined(file, cwd)
    if joined is None:
        return None
    path = Path(os.path.normpath(joined))
    hit = any(
        candidate.relative_to(root).as_posix() in tracked
        for candidate in (path, Path(os.path.realpath(joined)))
        for root in roots
        if candidate.is_relative_to(root)
    )
    return str(path) if hit else None


def _remove(path: Path) -> None:
    """Remove an engine dir the workload could write. A link planted in its
    place or in its parent's (``<run>/_scratch``) is unlinked, never
    followed; ``ValueError`` when ``<run>`` itself no longer resolves inside
    ``WORKTREE_ROOT``."""
    parent = _contained(path.parent)
    if os.path.islink(parent):
        os.unlink(parent)
        return
    target = _contained(path)
    if os.path.isdir(target) and not os.path.islink(target):
        _rmtree(target)
    elif os.path.lexists(target):
        os.unlink(target)


class ProfileGit(Protocol):
    """The ``GitWorkspace`` calls the profiler makes (a double in tests)."""

    def add_worktree(self, path: Path, commit: str) -> WorktreeHandle: ...
    def remove_worktree(self, target: WorktreeHandle | Path) -> None: ...
    def prune(self) -> None: ...
    def reset(self, handle: WorktreeHandle) -> None: ...
    def ls_tree(self, commit: str) -> tuple[str, ...]: ...


class CProfiler:
    """The real ``Profiler``. ``git`` defaults to the project's ``GitWorkspace``
    and ``fingerprint`` to its ``repo_fingerprint`` (a git double brings its
    own); the modes default to the settings (``make_phase``)."""

    def __init__(
        self,
        project: Project,
        *,
        git: ProfileGit | None = None,
        fingerprint: Callable[[], str] | None = None,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        base_env: Mapping[str, str] | None = None,
        run: RunOnce = run_once,
    ) -> None:
        workspace = GitWorkspace(Path(project.root_path)) if git is None else git
        if fingerprint is None:
            if not isinstance(workspace, GitWorkspace):
                raise ValueError("a git double needs its own fingerprint callable")
            fingerprint = functools.partial(repo_fingerprint, workspace)
        self._project, self._git, self._fingerprint = project, workspace, fingerprint
        self._phase = functools.partial(
            make_phase, network=network, fs=fs, platform=platform, base_env=base_env
        )
        self._run = run
        root = project.root_path
        self._roots = (Path(os.path.normpath(root)), Path(os.path.realpath(root)))

    def profile(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str
    ) -> ProfileResult:
        """Hotspots of every Python workload at ``commit`` and the notes."""
        problem = "it contains '/'" if "/" in run_id else refname_problem(run_id)
        if problem is not None:
            raise ValueError(
                f"run_id {run_id!r} is not a safe directory name: {problem}"
            )
        notes: list[str] = []
        planned: list[tuple[Workload, _Target]] = []
        for workload in workloads:
            try:
                planned.append((workload, _split(workload.command)))
            except NotProfiledError as reason:
                label = f"workload {workload.name!r}"
                notes.append(f"{label} is not profiled: {reason}{GUARD_SKIPPED}")
        if not planned:
            return ProfileResult((), tuple(notes))
        run_dir = settings.WORKTREE_ROOT / run_id
        worktree = run_dir / PHASE
        scratch, probe = run_dir / "_scratch" / PHASE, run_dir / "_probe" / PHASE
        hotspots: list[Hotspot] = []
        checkout: tuple[Workload, str] | None = None
        left: list[str] = []
        before = self._fingerprint()
        try:
            handle = self._git.add_worktree(worktree, commit)
            phase = self._phase(
                self._git, handle, scratch=scratch, probe=probe, run=self._run
            )
            tracked = frozenset(self._git.ls_tree(commit))
            for workload, target in planned:
                found, named = self._one(phase, workload, target, tracked, notes)
                hotspots.extend(found)
                if named is not None:
                    checkout = (workload, named)
                    break
            if self._fingerprint() != before:
                raise RepoTamperedError(
                    "the repository changed while the profiler ran: its refs,"
                    " config or hooks differ from before the run"
                )
        finally:
            left = self._cleanup(run_dir, worktree, scratch, probe)
        if left:  # only when nothing else was raised: that error wins
            raise EngineError(
                "the profiler could not clean up "
                + ", ".join(_quote(path) for path in left)
                + ": it no longer resolves inside WORKTREE_ROOT (a link was"
                " planted in place of the run directory); remove it by hand"
            )
        if checkout is not None:
            raise self._editable(*checkout)
        hotspots.sort(key=lambda hotspot: -hotspot.share)
        return ProfileResult(tuple(hotspots[:MAX_HOTSPOTS]), tuple(notes))

    def _one(
        self,
        phase: Phase,
        workload: Workload,
        target: _Target,
        tracked: frozenset[str],
        notes: list[str],
    ) -> tuple[list[Hotspot], str | None]:
        """One reset run; its hotspots and the first checkout file, if any."""
        label = f"workload {workload.name!r}"
        out = phase.scratch / PROFILE_NAME
        argv = _assemble(workload.command[0], target, out)
        run_notes: list[str] = []
        failed: str | None = None
        try:
            where = "the profile run"
            timeout_s = workload.timeout_s * PROFILE_TIMEOUT_FACTOR
            _launch(phase, argv, workload.working_dir, timeout_s, where, run_notes)
        except RunFailure as failure:
            failed = failure.reason
        notes.extend(f"{label}: {note}" for note in run_notes)
        if failed is not None:
            notes.append(f"{label} is not profiled: {failed}{GUARD_SKIPPED}")
            return [], None
        phase.reset()
        data = bytearray()
        try:
            _read_regular(out, _profile_shim.MAX_DOC_BYTES, data.extend)
            doc = parse_profile(bytes(data))
        except (_UnusableError, ProfileFormatError) as problem:
            notes.append(
                f"{label} is not profiled: the profile output {problem}{GUARD_SKIPPED}"
            )
            return [], None
        cwd = phase.worktree / workload.working_dir
        return self._hotspots(doc, workload, cwd, phase.worktree, tracked)

    def _hotspots(
        self,
        doc: ProfileDoc,
        workload: Workload,
        cwd: Path,
        worktree: Path,
        tracked: frozenset[str],
    ) -> tuple[list[Hotspot], str | None]:
        total = max(doc.total_s, math.fsum(item.self_s for item in doc.entries))
        ranked = sorted(
            doc.entries, key=lambda e: (-e.self_s, e.file, e.line, e.function)
        )
        found: list[Hotspot] = []
        for item in ranked:
            if item.file == str(SHIM_PATH):
                continue  # the shim's own frames, even in the engine's own checkout
            rel = project_file(item.file, cwd=cwd, worktree=worktree, tracked=tracked)
            if rel is None:
                named = checkout_file(
                    item.file, cwd=cwd, roots=self._roots, tracked=tracked
                )
                if named is not None:
                    return found, named
                continue
            symbol = clean_symbol(item.function)
            if item.self_s > 0 and symbol and len(found) < HOTSPOTS_PER_WORKLOAD:
                found.append(
                    Hotspot(
                        project_id=self._project.id,
                        workload_id=workload.id,
                        file_path=rel,
                        symbol=symbol,
                        line_start=item.line or None,
                        self_time_s=item.self_s,
                        total_time_s=item.cumulative_s,
                        share=item.self_s / total,
                        calls=item.total_calls,
                    )
                )
        return found, None

    def _editable(self, workload: Workload, path: str) -> EngineError:
        return EngineError(
            f"workload {workload.name!r} ran {_quote(path)} from the project"
            f" checkout {_quote(self._project.root_path)} instead of the profile"
            " worktree: an editable install, a symlinked install or a sys.path"
            " entry points at the checkout, so every measurement would time the"
            " checkout, not the commit; install the project without -e or"
            " --symlink, or remove that entry"
        )

    def _cleanup(self, run_dir: Path, worktree: Path, *dirs: Path) -> list[str]:
        """Remove the worktree, then each dir, then prune; every step runs.
        Returns the dirs it could not remove safely (``_remove``)."""
        left: list[str] = []
        try:
            self._git.remove_worktree(worktree)
        finally:
            try:
                for path in dirs:
                    try:
                        _remove(path)
                    except ValueError:
                        left.append(str(path))
            finally:
                self._git.prune()
                for path in (run_dir / "_scratch", run_dir / "_probe", run_dir):
                    # not empty (another owner), or <run> is a planted link
                    with contextlib.suppress(OSError, ValueError):
                        os.rmdir(_contained(path))
        return left
