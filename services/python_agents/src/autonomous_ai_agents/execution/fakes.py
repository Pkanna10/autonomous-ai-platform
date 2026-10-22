"""Deterministic doubles for every Step 2 seam, plus the E2E's ScriptedEditor.

Each fake returns (or raises) what it was scripted with and appends every
call to ``calls`` as a named tuple, so node tests assert exactly what a node
asked for without touching git, processes or Claude. Budgets are recorded as
a ``(cap_usd, spent_usd)`` snapshot and never charged.

``ScriptedEditor`` is the one double with effects: it applies an edit set
from disk to a worktree (see its docstring), so the E2E runs the real
capture, anti-cheat and measurement on known edits. It confines every write
to the worktree but deliberately enforces no protected paths: the git-side
capture is what must catch a deleted test or an added symlink.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.models import (
    Guardrail,
    Hotspot,
    Project,
    Workload,
)
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    EditResult,
    EditTask,
    KeptChange,
    PreflightReport,
    ProfileResult,
    UnderstandResult,
)

FAKE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
"""The commit ``FakePreflight`` pins when it echoes its inputs."""


class PreflightCall(NamedTuple):
    project: Project
    workloads: tuple[Workload, ...]
    guardrails: tuple[Guardrail, ...]


class ProfileCall(NamedTuple):
    workloads: tuple[Workload, ...]
    run_id: str
    commit: str


class UnderstandCall(NamedTuple):
    project: Project
    workloads: tuple[Workload, ...]
    commit: str
    cap_usd: float
    spent_usd: float


class CombineCall(NamedTuple):
    run_id: str
    project: Project
    base_commit: str
    kept: tuple[KeptChange, ...]
    workloads: tuple[Workload, ...]
    baseline_count: int | None = None


class PublishCall(NamedTuple):
    project: Project
    branch: str
    tip: str
    base: str


class EditCall(NamedTuple):
    worktree: Path
    task: EditTask
    cap_usd: float
    spent_usd: float


class FakePreflight:
    """Returns ``report``, raises ``error``, or (neither) echoes its inputs.

    The echo report pins ``FAKE_COMMIT``, keeps the workloads and the
    project's test command, has no dirty entries, both isolation modes
    ``required``, and the scripted ``notes`` and ``python_version``.
    """

    def __init__(
        self,
        report: PreflightReport | None = None,
        *,
        error: Exception | None = None,
        notes: Sequence[str] = (),
        python_version: tuple[int, int, int] | None = None,
    ) -> None:
        if report is not None and error is not None:
            raise ValueError("script a report or an error, not both")
        if isinstance(notes, str):
            raise TypeError("notes must be a sequence of notes, not one str")
        if report is not None and (notes or python_version is not None):
            raise ValueError("script notes and python_version on the report")
        self._report, self._error = report, error
        self._notes, self._python = tuple(notes), python_version
        self.calls: list[PreflightCall] = []

    def check(
        self,
        project: Project,
        workloads: Sequence[Workload],
        guardrails: Sequence[Guardrail],
    ) -> PreflightReport:
        self.calls.append(PreflightCall(project, tuple(workloads), tuple(guardrails)))
        if self._error is not None:
            raise self._error
        if self._report is not None:
            return self._report
        return PreflightReport(
            head_commit=FAKE_COMMIT,
            dirty_entries=(),
            git_version=(2, 43, 0),
            network="required",
            fs="required",
            workloads=tuple(workloads),
            test_command=project.test_command,
            extra_protected=(),
            notes=self._notes,
            python_version=self._python,
        )


class FakeProfiler:
    """Returns the scripted hotspots and notes, or raises ``error``."""

    def __init__(
        self,
        hotspots: Sequence[Hotspot] = (),
        notes: Sequence[str] = (),
        *,
        error: Exception | None = None,
    ) -> None:
        self._result = ProfileResult(tuple(hotspots), tuple(notes))
        self._error = error
        self.calls: list[ProfileCall] = []

    def profile(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str
    ) -> ProfileResult:
        self.calls.append(ProfileCall(tuple(workloads), run_id, commit))
        if self._error is not None:
            raise self._error
        return self._result


class FakeUnderstander:
    """Returns ``result`` or raises ``error`` (exactly one must be given)."""

    def __init__(
        self, result: UnderstandResult | None = None, *, error: Exception | None = None
    ) -> None:
        outcome = result if error is None else error
        if outcome is None or (result is not None and error is not None):
            raise ValueError("script exactly one of a result or an error")
        self._outcome: UnderstandResult | Exception = outcome
        self.calls: list[UnderstandCall] = []

    def understand(
        self,
        project: Project,
        workloads: Sequence[Workload],
        *,
        commit: str,
        budget: Budget,
    ) -> UnderstandResult:
        self.calls.append(
            UnderstandCall(
                project, tuple(workloads), commit, budget.cap_usd, budget.spent_usd
            )
        )
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeCombiner:
    """Replays one scripted result (or exception) per call, in order."""

    def __init__(self, results: Sequence[CombineMeasured | Exception]) -> None:
        self._results = list(results)
        self.calls: list[CombineCall] = []

    def combine(
        self,
        run_id: str,
        project: Project,
        base_commit: str,
        kept: Sequence[KeptChange],
        workloads: Sequence[Workload],
        *,
        baseline_count: int | None = None,
    ) -> CombineMeasured:
        self.calls.append(
            CombineCall(
                run_id,
                project,
                base_commit,
                tuple(kept),
                tuple(workloads),
                baseline_count,
            )
        )
        if len(self.calls) > len(self._results):
            raise IndexError(
                f"FakeCombiner has no result scripted for call {len(self.calls)}"
            )
        outcome = self._results[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakePublisher:
    """Returns the scripted diff text, or raises ``error``."""

    def __init__(self, diff: str = "", *, error: Exception | None = None) -> None:
        self._diff, self._error = diff, error
        self.calls: list[PublishCall] = []

    def publish(self, project: Project, branch: str, tip: str, base: str) -> str:
        self.calls.append(PublishCall(project, branch, tip, base))
        if self._error is not None:
            raise self._error
        return self._diff


class FakeEditor:
    """Replays a scripted result (or exception) per hypothesis title.

    An unscripted title gets ``default``; without one a ``KeyError`` names it.
    """

    def __init__(
        self,
        results: Mapping[str, EditResult | Exception],
        default: EditResult | None = None,
    ) -> None:
        self._results = dict(results)
        self._default = default
        self.calls: list[EditCall] = []

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.calls.append(EditCall(worktree, task, budget.cap_usd, budget.spent_usd))
        title = task.hypothesis.title
        outcome = self._results.get(title, self._default)
        if outcome is None:
            raise KeyError(f"no scripted edit for hypothesis title {title!r}")
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# ---------------------------------------------------------------------------
# ScriptedEditor
# ---------------------------------------------------------------------------

_SAFE_TITLE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class _Op(NamedTuple):
    kind: str  # "write" | "delete" | "symlink"
    path: str  # normalised repo-relative target
    data: bytes  # file bytes (write) or link target (symlink)


class ScriptedEditor:
    """Applies ``edits_dir/<hypothesis title>/`` to the worktree.

    An edit set holds ``files/`` (each file copied to the same repo-relative
    path, parents created, ``__pycache__`` skipped), an optional ``_delete``
    (one path per line) and an optional ``_symlink`` (``<link>\\t<target>``
    per line; the target is written verbatim). Blank lines are ignored.

    Every path is checked with ``normalize_path`` and its parent must resolve
    to a directory inside the worktree, both before anything is written and
    again as each operation is applied. An unsafe title, a missing edit set,
    a symlink inside the edit set, a write through an existing symlink or any
    path problem (a symlink loop included) returns an ``EditResult`` with
    ``error`` set and ``stop="error"``; ``written`` then lists what was
    already applied. Nothing is ever charged to the budget.
    """

    def __init__(self, edits_dir: Path) -> None:
        self._edits_dir = edits_dir
        self.calls: list[str] = []

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        title = task.hypothesis.title
        self.calls.append(title)
        written: dict[str, int] = {}
        try:
            if _SAFE_TITLE.fullmatch(title) is None:
                raise ValueError(f"unsafe edit-set title {title!r}")
            edit_set = self._edits_dir / title
            if not edit_set.is_dir():
                raise ValueError(f"no edit set for title {title!r}")
            root = Path(os.path.realpath(worktree, strict=True))
            ops = list(_plan(edit_set))
            for op in ops:
                _check(root, op)
            for op in ops:
                written[op.path] = _apply(root, op)
        except (OSError, ValueError) as exc:
            return EditResult(written=written, stop="error", error=str(exc))
        return EditResult(written=written)


def _plan(edit_set: Path) -> Iterator[_Op]:
    files = edit_set / "files"
    if files.is_symlink():
        raise ValueError("edit set's files/ is a symlink")
    for dirpath, dirnames, filenames in os.walk(files):
        here = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in [*dirnames, *sorted(filenames)]:
            if (here / name).is_symlink():
                raise ValueError(f"edit set holds a symlink {name!r}: use _symlink")
        for name in sorted(filenames):
            source = here / name
            yield _Op(
                "write", source.relative_to(files).as_posix(), source.read_bytes()
            )
    for line in _manifest(edit_set / "_delete"):
        yield _Op("delete", line, b"")
    for line in _manifest(edit_set / "_symlink"):
        link, _, target = line.partition("\t")
        if not link or not target:
            raise ValueError(f"_symlink line {line!r} is not '<link>\\t<target>'")
        yield _Op("symlink", link, os.fsencode(target))


def _manifest(path: Path) -> Iterator[str]:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield line


def _target(root: Path, path: str) -> Path:
    """The worktree path for ``path``, refused unless it can land inside.

    The deepest existing ancestor is resolved strictly with ``os.path``,
    which raises ``OSError`` on a symlink loop on every supported Python
    (``Path.resolve`` raises ``RuntimeError`` on 3.11 and 3.12 only), and it
    must be a directory inside the worktree; nothing below it exists yet, so
    nothing below it can redirect the write.
    """
    clean = normalize_path(path)
    if clean != path or clean == ".":
        raise ValueError(f"edit path {path!r} must be a normalised file path")
    target = root / clean
    anchor = target.parent
    while not os.path.lexists(anchor):
        anchor = anchor.parent
    real = Path(os.path.realpath(anchor, strict=True))
    if not real.is_relative_to(root):
        raise ValueError(f"edit path {path!r} resolves outside the worktree")
    if not real.is_dir():
        raise ValueError(f"edit path {path!r} has a parent that is not a directory")
    return target


def _check(root: Path, op: _Op) -> Path:
    target = _target(root, op.path)
    if op.kind == "write" and target.is_symlink():
        raise ValueError(f"refusing to write through the symlink {op.path!r}")
    if op.kind == "delete" and (
        not os.path.lexists(target) or (target.is_dir() and not target.is_symlink())
    ):
        raise ValueError(f"cannot delete {op.path!r}: not an existing file")
    if op.kind == "symlink" and os.path.lexists(target):
        raise ValueError(f"cannot create symlink {op.path!r}: the path exists")
    return target


def _apply(root: Path, op: _Op) -> int:
    target = _check(root, op)
    if op.kind == "delete":
        target.unlink()
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    if op.kind == "symlink":
        os.symlink(os.fsdecode(op.data), target)
    else:
        target.write_bytes(op.data)
    return len(op.data)
