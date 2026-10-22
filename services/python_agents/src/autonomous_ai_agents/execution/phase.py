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
"""

from __future__ import annotations

import contextlib
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


@contextlib.contextmanager
def owned_phases(git: PhaseGit, owner: str, *phases: PhaseDirs) -> Iterator[None]:
    """Run the body, then always ``cleanup_phases``; what is left is an
    ``EngineError`` only when the body raised nothing (its error wins)."""
    _one_run(phases)
    try:
        yield
    finally:
        left = cleanup_phases(git, *phases)
    raise_left(owner, left)
