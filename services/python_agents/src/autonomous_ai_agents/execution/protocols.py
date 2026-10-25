"""The Step 2 seams: value types and the protocols behind every external effect.

Each external effect of the engine loop (preflight, profiling, Claude edits
and understanding, combining kept changes, publishing a branch) sits behind a
runtime-checkable Protocol here, so the nodes are tested with the
deterministic doubles in ``execution/fakes.py`` and the real implementations
(git, processes, Claude) arrive behind the same signatures.

The carriers are frozen dataclasses, not pydantic models: they cross one
call and never enter the checkpointed state. The few that feed an
anti-cheat rule or the budget check their values on construction and raise
``ValueError``, so a misparse fails loudly instead of slipping past capture.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypedDict, runtime_checkable

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import IsolationMode
from autonomous_ai_agents.common.models import (
    CombineSkip,
    Guardrail,
    Hotspot,
    Hypothesis,
    Measurement,
    Project,
    ProjectUnderstanding,
    Workload,
)
from autonomous_ai_agents.common.paths import normalize_path

CHANGE_STATUSES: frozenset[str] = frozenset({"A", "M", "D", "T"})
"""``git diff --raw --no-renames`` letters: added, modified, deleted, type change."""

_GIT_MODE = re.compile(r"[0-7]{6}")


def _require_money(usd: float, tokens: int) -> None:
    if not math.isfinite(usd) or usd < 0:
        raise ValueError(f"cost_usd must be finite and at least 0, got {usd}")
    if tokens < 0:
        raise ValueError(f"tokens_used must be at least 0, got {tokens}")


def _require_clean_path(what: str, path: str) -> None:
    """A repo-relative file path exactly as ``normalize_path`` returns it."""
    try:
        clean = normalize_path(path)
    except ValueError as exc:
        raise ValueError(f"{what} {path!r} is not repo-relative: {exc}") from exc
    if clean != path or clean == ".":
        raise ValueError(f"{what} {path!r} must be a normalised file path")


def _require_git_path(path: str) -> None:
    """A path as ``git diff --raw -z`` prints it, kept verbatim.

    Git never prints an absolute path, an empty, ``.`` or ``..`` component
    or a NUL (the ``-z`` separator), so those mean a misparse. A backslash,
    a leading ``~`` or ``c:`` are legal POSIX name characters that
    ``normalize_path`` would rewrite or refuse, so it is not applied here:
    such a path fails ``unrecorded_write`` instead of crashing capture.
    """
    if "\0" in path or any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"path {path!r} is not a repo-relative git path")


@dataclass(frozen=True)
class TrialBrief:
    """What a trial's editor is told: the understanding, its hotspots, the rules.

    ``fix_retries_left`` is the run's fix retries still unspent (D12): the
    trials node computes it, the runner retries only below it, and the editor
    prompt never shows it. A field, not a ``run()`` keyword, so every
    ``TrialRunner`` keeps its signature; the default 0 fails closed.
    """

    understanding: ProjectUnderstanding | None
    hotspots: tuple[Hotspot, ...]
    protected: tuple[str, ...]
    fix_retries_left: int = 0

    def __post_init__(self) -> None:
        if self.fix_retries_left < 0:
            raise ValueError(
                f"fix_retries_left must be at least 0, got {self.fix_retries_left}"
            )


@dataclass(frozen=True)
class Change:
    """One captured diff entry: a name-status letter, git octal modes, a path.

    ``path`` is git's, verbatim (see ``_require_git_path``): it may hold
    characters ``normalize_path`` rewrites, so compare it as text only.
    """

    status: str
    old_mode: str
    new_mode: str
    path: str

    def __post_init__(self) -> None:
        if self.status not in CHANGE_STATUSES:
            raise ValueError(f"status {self.status!r} is not one of A, M, D, T")
        for mode in (self.old_mode, self.new_mode):
            if _GIT_MODE.fullmatch(mode) is None:
                raise ValueError(f"mode {mode!r} is not six octal digits")
        _require_git_path(self.path)


@dataclass(frozen=True)
class WorktreeHandle:
    """A worktree, the admin dir its ``.git`` file named, and that file's bytes."""

    path: Path
    gitdir: Path
    link_bytes: bytes


@dataclass(frozen=True)
class PreflightReport:
    """What connect learned: the pinned commit, the resolved inputs, isolation.

    ``notes`` are printable lines for connect events (accepted risks such as
    a ``merge=union`` attribute, skipped parses, isolation not applied);
    ``python_version`` is the engine's interpreter, ``None`` when unknown.
    """

    head_commit: str
    dirty_entries: tuple[str, ...]
    git_version: tuple[int, int, int]
    network: IsolationMode
    fs: IsolationMode
    workloads: tuple[Workload, ...]
    test_command: tuple[str, ...] | None
    extra_protected: tuple[str, ...]
    notes: tuple[str, ...] = ()
    python_version: tuple[int, int, int] | None = None


@dataclass(frozen=True)
class EditTask:
    """One hypothesis to implement, with its brief and the per-trial boundary.

    ``feedback`` is set on a fix retry only: ``TrialFeedback.render()`` of the
    first attempt's crash and nothing else (D13), a string so no withheld
    reason or raw run output can reach the editor through it.
    """

    hypothesis: Hypothesis
    brief: TrialBrief
    boundary: str
    feedback: str | None = None

    def __post_init__(self) -> None:
        if not self.boundary:
            raise ValueError("boundary must be a non-empty token")
        if self.feedback is not None and not self.feedback:
            raise ValueError("feedback must be non-empty when given")


@dataclass(frozen=True)
class EditResult:
    """What an editor did: bytes written per repo-relative path (0 = deleted).

    ``written`` is copied into a read-only mapping. Its keys must be
    normalised paths because ``unrecorded_write`` compares them with git's.
    ``stop`` is the reason the edit ended (``end_turn`` on success). The
    explicit ``__hash__`` hashes ``written`` as sorted items, because a
    mapping proxy is not hashable; equal results hash alike.
    """

    written: Mapping[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    tokens_used: int = 0
    stop: str = "end_turn"
    error: str | None = None

    def __post_init__(self) -> None:
        for path, size in self.written.items():
            _require_clean_path("written path", path)
            if size < 0:
                raise ValueError(f"written[{path!r}] must be at least 0, got {size}")
        _require_money(self.cost_usd, self.tokens_used)
        object.__setattr__(self, "written", MappingProxyType(dict(self.written)))

    def __hash__(self) -> int:
        items = tuple(sorted(self.written.items()))
        return hash((items, self.cost_usd, self.tokens_used, self.stop, self.error))


@dataclass(frozen=True)
class ProfileResult:
    """The profiler's hotspots and its notes (skipped workloads and why)."""

    hotspots: tuple[Hotspot, ...]
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnderstandResult:
    """The understanding (``None`` when it failed softly), notes and its cost."""

    understanding: ProjectUnderstanding | None
    notes: tuple[str, ...] = ()
    cost_usd: float = 0.0
    tokens_used: int = 0

    def __post_init__(self) -> None:
        _require_money(self.cost_usd, self.tokens_used)


@dataclass(frozen=True)
class KeptChange:
    """A kept (or approved) trial commit the combiner merges onto the base."""

    trial_id: str
    hypothesis_id: str
    verdict_id: str
    commit: str
    score: float
    gain: float | None


@dataclass(frozen=True)
class CombineMeasured:
    """The combined tip and its interleaved re-test.

    ``applied`` and ``skipped`` hold trial ids; ``baseline`` are the A runs,
    ``combined`` the B runs plus one ``tests_passed`` row per workload.
    """

    tip_commit: str
    applied: tuple[str, ...]
    skipped: tuple[CombineSkip, ...]
    baseline: tuple[Measurement, ...]
    combined: tuple[Measurement, ...]


class LaunchReport(TypedDict):
    """The launcher's JSON report for one run (``maxrss`` in platform units)."""

    wall_ns: int
    utime: float
    stime: float
    maxrss: int
    exit: int
    fs_isolated: bool
    net_isolated: bool
    error: str | None


@runtime_checkable
class Preflight(Protocol):
    """Checks the repo and host at connect; raises ``PreflightError``."""

    def check(
        self,
        project: Project,
        workloads: Sequence[Workload],
        guardrails: Sequence[Guardrail],
    ) -> PreflightReport: ...


@runtime_checkable
class Profiler(Protocol):
    """Profiles the workloads at ``commit`` in the run's own worktree."""

    def profile(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str
    ) -> ProfileResult: ...


@runtime_checkable
class CodeEditor(Protocol):
    """Implements one hypothesis inside ``worktree``, spending from ``budget``."""

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult: ...


@runtime_checkable
class ProjectUnderstander(Protocol):
    """Reads the project at ``commit`` and summarises it for the editor."""

    def understand(
        self,
        project: Project,
        workloads: Sequence[Workload],
        *,
        commit: str,
        budget: Budget,
    ) -> UnderstandResult: ...


@runtime_checkable
class Combiner(Protocol):
    """Merges the kept changes onto ``base_commit`` and re-tests the tip."""

    def combine(
        self,
        run_id: str,
        project: Project,
        base_commit: str,
        kept: Sequence[KeptChange],
        workloads: Sequence[Workload],
        *,
        baseline_count: int | None = None,
    ) -> CombineMeasured: ...


@runtime_checkable
class BranchPublisher(Protocol):
    """Creates ``branch`` at ``tip`` and returns the capped ``base..tip`` diff."""

    def publish(self, project: Project, branch: str, tip: str, base: str) -> str: ...
