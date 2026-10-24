"""One owner per phase directory (decision 38), and the one cleanup they share.

Every owner (the baseline runner, the profiler, each trial, the combiner)
works in ``<WORKTREE_ROOT>/<run>/<phase>`` (its worktree) with
``<run>/_scratch/<phase>`` and ``<run>/_probe/<phase>`` (``phase_dirs``),
and wraps that work in ``owned_phases``, which in ``finally`` runs
``cleanup_phases``:

1. ``remove_worktree`` of each worktree (``worktree remove --force``, a
   contained ``rmtree``, and a prune when git failed); a link planted in
   place of the worktree is unlinked instead, never handed to git (git
   would resolve it and remove the worktree it points at);
2. each scratch and probe dir: a link planted in place of ``<run>/_scratch``
   or ``<run>/_probe`` is unlinked, never followed; then the dir itself goes
   (``git.remove_contained``: a link there is unlinked, never followed);
3. ``prune``;
4. ``rmdir`` of ``<run>/_scratch``, ``<run>/_probe`` and ``<run>``, each
   only when empty (another owner may still be using ``<run>``).

Every step runs whatever the steps before it did (each in its own
``finally``). A step's ``ValueError`` (its path no longer resolves inside
``WORKTREE_ROOT``), ``GitError`` (a timeout) or ``OSError`` (a file a
workload made unremovable) is recorded, not raised; anything else
propagates once every later step ran. A ``<run>`` that is itself a link
(planted) is never followed, even to another run inside ``WORKTREE_ROOT``:
nothing under it is removed, git is never asked to remove a worktree
through it, and the worktree, scratch and probe dirs are recorded as left. What is left becomes one ``EngineError``
naming it (``raise_left``), and only when no error is already on its way:
that error wins.

**Crash recovery.** While an owner works, it holds a shared ``flock`` on
``<run>/.aip-run.lock`` (``RUN_LOCK``); the lock file marks ``<run>`` as the
engine's. The kernel drops the lock when the process dies, even on
``kill -9``, and ``cleanup_phases`` never runs then, so the worktree, its
registration in the user's ``.git/worktrees``, the scratch and probe dirs
stay. ``sweep_stale_runs`` (connect calls it before its ``prune``) finds
every marked ``<run>`` whose lock it can take exclusively, which no live owner
holds, and runs ``cleanup_phases`` on each phase found in it. It never
touches a directory without the marker (a user's own worktree inside
``WORKTREE_ROOT``, the preflight probe's dir) or one a live owner holds. A
worktree of another repository under the same root is removed from disk; its
own repository's next prune drops the registration, which then points at a
missing path. A live owner drops the marker when it ends (what its cleanup
could not remove is its ``EngineError``); a sweep that cannot remove
everything keeps it, so the next sweep tries again.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.refnames import refname_problem
from autonomous_ai_agents.execution.git import GitError, contained, remove_contained
from autonomous_ai_agents.execution.protocols import WorktreeHandle

SCRATCH, PROBE = "_scratch", "_probe"
RUN_LOCK = ".aip-run.lock"
"""The marker and lock in ``<run>``: no phase name can begin with a dot."""
_LOCK_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
PLANTED = (
    "it no longer resolves inside WORKTREE_ROOT (a link was planted in place of"
    " the run directory)"
)
UNLINKED = (
    "a link was planted in place of the worktree: it was unlinked, never"
    " followed, and the worktree it replaced is not known"
)
_SHOWN = 300


class _UnlinkedError(Exception):
    """A link planted in place of a worktree was unlinked (recorded as left)."""


@runtime_checkable
class PhaseGit(Protocol):
    """The two ``GitWorkspace`` calls the cleanup makes (a double in tests)."""

    def remove_worktree(self, target: WorktreeHandle | Path) -> None: ...
    def prune(self) -> None: ...


@dataclass(frozen=True)
class PhaseDirs:
    """One phase's paths: ``<run>``, its worktree, scratch and probe dirs."""

    run: Path
    worktree: Path
    scratch: Path
    probe: Path


def require_dir_name(what: str, value: str) -> None:
    """``value`` must be one safe path component (a git refname segment)."""
    problem = "it contains '/'" if "/" in value else refname_problem(value)
    if problem is not None:
        raise ValueError(
            f"{what} {value[:_SHOWN]!r} is not a safe directory name: {problem}"
        )


def phase_dirs(run_id: str, phase: str) -> PhaseDirs:
    """The decision 38 layout of ``phase`` in run ``run_id``."""
    require_dir_name("run_id", run_id)
    require_dir_name("phase", phase)
    run = settings.WORKTREE_ROOT / run_id
    return PhaseDirs(run, run / phase, run / SCRATCH / phase, run / PROBE / phase)


def _shown(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_SHOWN])


def _not_through_a_link(run: Path) -> None:
    if os.path.islink(run):
        raise ValueError(f"{run} is a link")


def _remove_dir(run: Path, path: Path) -> None:
    """Remove a scratch or probe dir; a link in place of its parent is
    unlinked; nothing is reached through a planted ``<run>`` link."""
    _not_through_a_link(run)
    parent = contained(path.parent)
    if os.path.islink(parent):
        os.unlink(parent)
        return
    remove_contained(path)


def _remove_worktree(git: PhaseGit, run: Path, worktree: Path) -> None:
    """Step 1 for one worktree, never through a planted ``<run>`` link nor a
    link at the worktree path (an engine worktree is never a link)."""
    _not_through_a_link(run)
    if os.path.islink(worktree):
        remove_contained(worktree)
        raise _UnlinkedError(UNLINKED)
    git.remove_worktree(worktree)


def _rmdir_empty(run: Path) -> None:
    for path in (run / SCRATCH, run / PROBE, run):
        # not empty (another owner), or <run> is a planted link
        with contextlib.suppress(OSError, ValueError):
            if path != run:
                _not_through_a_link(run)
            os.rmdir(contained(path))


def _step(
    left: list[str], what: Path | str, action: Callable[..., None], *args: object
) -> None:
    """One step; a containment, git or OS error is appended to ``left``."""
    try:
        action(*args)
    except _UnlinkedError as unlinked:
        left.append(f"{str(what)!r}: {unlinked}")
    except ValueError:
        left.append(f"{str(what)!r}: {PLANTED}")
    except (GitError, OSError) as error:
        left.append(f"{str(what)!r}: {_shown(str(error))}")


def _one_run(phases: Sequence[PhaseDirs]) -> Path:
    if not phases:
        raise ValueError("the cleanup needs at least one phase")
    run = phases[0].run
    if any(dirs.run != run for dirs in phases):
        raise ValueError("every phase cleaned up together must belong to one run")
    return run


def cleanup_phases(git: PhaseGit, *phases: PhaseDirs) -> list[str]:
    """Steps 1 to 4 (module docstring) for ``phases`` of one run; returns
    what could not be removed, and why."""
    run = _one_run(phases)
    left: list[str] = []
    with contextlib.ExitStack() as stack:  # last in, first out; each one runs
        stack.callback(_rmdir_empty, run)
        stack.callback(_step, left, "the worktree registrations", git.prune)
        for dirs in reversed(phases):
            for path in (dirs.probe, dirs.scratch):
                stack.callback(_step, left, path, _remove_dir, run, path)
        for dirs in reversed(phases):
            stack.callback(
                _step, left, dirs.worktree, _remove_worktree, git, run, dirs.worktree
            )
    return left


def raise_left(owner: str, left: Sequence[str]) -> None:
    """One ``EngineError`` naming everything ``left``; nothing when empty."""
    if left:
        raise EngineError(
            f"{owner} could not clean up {'; '.join(left)}; remove what is left by hand"
        )


def _same_file(fd: int, path: Path) -> bool:
    """Whether ``fd`` is still the file at ``path`` (no one replaced it)."""
    try:
        here = os.lstat(path)
    except OSError:
        return False
    there = os.fstat(fd)
    return (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)


def _hold(run: Path) -> int | None:
    """A shared lock on ``<run>/RUN_LOCK`` (created, with ``<run>``, when
    missing), or ``None`` when ``<run>`` is a link or the file cannot be
    made: a run without the marker is never swept, so that only costs the
    crash recovery, never safety."""
    try:
        contained(run).mkdir(mode=0o700, parents=True, exist_ok=True)
        _not_through_a_link(run)
        fd = os.open(run / RUN_LOCK, _LOCK_FLAGS | os.O_CREAT, 0o600)
    except (OSError, ValueError):
        return None
    fcntl.flock(fd, fcntl.LOCK_SH)  # waits while a sweep cleans this run
    return fd


def _release(run: Path, fd: int) -> None:
    """Drop the marker when no other owner holds the lock, then ``<run>`` when
    it is empty; always close ``fd``. What the cleanup could not remove was
    reported (``raise_left``), so the marker never outlives its owner."""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.unlink(run / RUN_LOCK)
        os.rmdir(run)
    except OSError:  # another owner holds it (it drops the marker), or not empty
        pass
    finally:
        os.close(fd)


@contextlib.contextmanager
def owned_phases(git: PhaseGit, owner: str, *phases: PhaseDirs) -> Iterator[None]:
    """Run the body, then always ``cleanup_phases``; what is left is an
    ``EngineError`` only when the body raised nothing (its error wins).

    The run's lock is held for the whole body and its cleanup (module
    docstring), so a sweep never removes what a live owner uses."""
    run = _one_run(phases)
    fd = _hold(run)
    try:
        yield
    finally:
        try:
            left = cleanup_phases(git, *phases)
        finally:
            if fd is not None:
                _release(run, fd)
    raise_left(owner, left)


def _phase_names(run: Path) -> tuple[list[str], list[str]]:
    """The phases found in a marked ``<run>``: its own dirs and the names in
    its scratch and probe dirs; names no phase can have are the second list
    (left alone)."""
    found = [n for n in os.listdir(run) if n not in (SCRATCH, PROBE, RUN_LOCK)]
    for sub in (SCRATCH, PROBE):
        with contextlib.suppress(OSError):  # missing (a link is safe: step 2)
            found += os.listdir(run / sub)
    names: list[str] = []
    odd: list[str] = []
    for name in dict.fromkeys(found):
        try:
            require_dir_name("phase", name)
        except ValueError:
            odd.append(name)
        else:
            names.append(name)
    return names, odd


def _sweep_one(git: PhaseGit, name: str) -> str:
    """Clean the stale ``<run>`` called ``name`` (its lock held); a note."""
    run = settings.WORKTREE_ROOT / name
    phases, odd = _phase_names(run)
    left = cleanup_phases(git, *(phase_dirs(name, p) for p in phases)) if phases else []
    left += [f"{_shown(str(run / entry))!r}: not an engine phase" for entry in odd]
    if left:  # the marker stays, so the next sweep tries again
        return (
            f"an engine run that ended without its cleanup left {'; '.join(left)};"
            " remove what is left by hand"
        )
    with contextlib.suppress(OSError):
        os.unlink(run / RUN_LOCK)
        os.rmdir(run)
    shown = ", ".join(_shown(p) for p in phases) or "no phase dirs"
    return (
        "removed what an engine run that ended without its cleanup (killed?)"
        f" left in WORKTREE_ROOT: run {_shown(name)} ({shown})"
    )


def sweep_stale_runs(git: PhaseGit) -> list[str]:
    """Clean every marked ``<run>`` no live owner holds (module docstring);
    one note per run swept. A directory without the marker, a link, or a run
    some process still holds is never touched."""
    root = Path(os.path.realpath(settings.WORKTREE_ROOT))
    try:
        names = sorted(os.listdir(root))
    except OSError:  # no root yet: nothing ever ran here
        return []
    notes: list[str] = []
    for name in names:
        lock = root / name / RUN_LOCK
        try:
            require_dir_name("run id", name)
            _not_through_a_link(root / name)
            fd = os.open(lock, _LOCK_FLAGS)
        except (OSError, ValueError):  # unmarked, a link, or no run name
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if _same_file(fd, lock):  # else an owner replaced it: it is live
                notes.append(_sweep_one(git, name))
        except BlockingIOError:  # a live owner holds it
            pass
        finally:
            os.close(fd)
    return notes
