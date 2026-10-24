"""The engine factory: the real ``NodeContext`` for one project (spec section 3).

``build_context(project, ...)`` wires every Step 2 seam to its real
implementation, all on one ``GitWorkspace`` of ``project.root_path`` and
one pair of isolation modes:

- ``GitPreflight(protected=<the context's protected patterns>)``;
- ``ClaudeUnderstander`` and ``ClaudeEditor`` (over ``WorktreeEditor``,
  built per run scope by ``GitTrialRunner``) on one transport;
- ``CProfiler``, ``GitBaselineRunner``, ``GitTrialRunner``, ``GitCombiner``
  and ``GitBranchPublisher``; the trial runner and the publisher take the
  context's branch prefix, so neither can move a ref outside it. The two
  runners read ``project.test_command`` from their constructor while connect
  resolves it, so ``ConnectedPreflight`` rebuilds them from the resolved
  project after each check (``ConnectedRunners``), and the context holds
  delegates (``ConnectedBaselineRunner``, ``ConnectedTrialRunner``);
- ``min_trial_budget_usd``: one worst-case editor request
  (``min_trial_budget``), unless given.

Everything that launches repository code (preflight's probe, the profiler,
both runners, the combiner) is passed the context's isolation modes and one
launcher (``run``, ``procrun.run_once`` unless a test injects a recorder)
explicitly. The runners' notes (``RunSample``, ``RunFailure``, ``Measured``,
e.g. the nondeterministic-output warning) are ``runner_note`` warning
events of the run and phase the delegate serves (``RunNotes``); a context
serves one run at a time, since connect rebinds its runners.

The transport is the injected one, else ``transport_factory(settings)``
(``AnthropicTransport``) only when ``ANTHROPIC_API_KEY`` is set, else none:
understand then keeps its Step 1 stub, and the trials need an injected
editor (``LLMConfigError`` otherwise, before anything runs). The factory
never reads the key: ``AnthropicTransport`` is the only code that unwraps
the ``SecretStr``, and it sends to ``ENGINE_API_BASE_URL``, never the SDK's
``ANTHROPIC_BASE_URL``. The ``anthropic`` logger is raised to INFO (its
DEBUG log prints request options). A ``WORKTREE_ROOT`` that overlaps the
checkout is refused with ``PreflightError``: trial worktrees and their
cleanup must never live in, or contain, the user's repository.

Everything else (``WORKTREE_ROOT``, ``MIN_RUNS``, the output caps) is read
from ``settings`` by the modules themselves, so tests change ``settings``.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import structlog

from autonomous_ai_agents.clients.cost import chain, preflight_estimate
from autonomous_ai_agents.clients.transport import AnthropicTransport, LLMTransport
from autonomous_ai_agents.common.config import IsolationMode, Settings, settings
from autonomous_ai_agents.common.errors import (
    EngineError,
    LLMConfigError,
    PreflightError,
)
from autonomous_ai_agents.common.models import (
    Baseline,
    EventLevel,
    Guardrail,
    Hypothesis,
    Measurement,
    Project,
    RunPhase,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.combine import GitBranchPublisher, GitCombiner
from autonomous_ai_agents.execution.editor import ClaudeEditor
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.procrun import run_once
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import (
    Preflight,
    PreflightReport,
    TrialBrief,
)
from autonomous_ai_agents.execution.runner import BaselineRunner, TrialRunner
from autonomous_ai_agents.execution.trial_runner import (
    EditorFactory,
    GitBaselineRunner,
    GitTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.judges import Judge, default_judges
from autonomous_ai_agents.orchestrator.events import emit, make_event
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.understand import ClaudeUnderstander
from autonomous_ai_agents.persistence.repository import (
    InMemoryRepository,
    Repository,
)

TransportFactory = Callable[[Settings], LLMTransport]
"""Builds the engine's transport from the settings (``AnthropicTransport``)."""

_Runners = tuple[BaselineRunner, TrialRunner]

SDK_LOGGER = "anthropic"
_LOG = structlog.get_logger("autonomous_ai_agents.engine")


def min_trial_budget() -> float:
    """One worst-case editor request: no prompt, ``EDITOR_MAX_TOKENS`` out,
    priced over the chain the transport sends (spec decision 10)."""
    return preflight_estimate(
        0, settings.EDITOR_MAX_TOKENS, chain(settings), settings.MODEL_PRICING
    )


def engine_transport(
    transport: LLMTransport | None, transport_factory: TransportFactory
) -> LLMTransport | None:
    """The injected transport, else a built one when a key is set, else None."""
    if transport is not None:
        return transport
    if settings.ANTHROPIC_API_KEY is None:
        return None
    return transport_factory(settings)


def claude_editor_factory(
    transport: LLMTransport, *, sleep: Callable[[float], None] = time.sleep
) -> EditorFactory:
    """``GitTrialRunner``'s editor: a ``ClaudeEditor`` per run scope."""
    return functools.partial(ClaudeEditor, transport, config=settings, sleep=sleep)


class RunNotes:
    """Where the runners' notes go (``on_note``): a ``runner_note`` warning
    event of the run and phase a connected delegate is serving, which
    ``emit`` sends to the graph's live stream; outside a delegate's call (no
    run to stamp) one structured log line. Text is printable and capped."""

    CAP = 500

    def __init__(self) -> None:
        self._scope: tuple[str, RunPhase] | None = None

    @contextlib.contextmanager
    def scope(self, run_id: str | None, phase: RunPhase) -> Iterator[None]:
        """Stamp notes with ``run_id`` and ``phase`` while the block runs."""
        before = self._scope
        self._scope = None if run_id is None else (run_id, phase)
        try:
            yield
        finally:
            self._scope = before

    def __call__(self, note: str) -> None:
        text = "".join(ch if ch.isprintable() else "?" for ch in note[: self.CAP])
        if self._scope is None:
            _LOG.info("runner_note", note=text)
            return
        run_id, phase = self._scope
        emit(
            make_event(
                run_id,
                phase,
                f"runner_note: {text}",
                level=EventLevel.warning,
                data={"code": "runner_note", "note": text},
            )
        )


def _pin_sdk_logger() -> None:
    logger = logging.getLogger(SDK_LOGGER)
    logger.setLevel(max(logger.level, logging.INFO))


def _refuse_overlap(project: Project) -> None:
    root = Path(os.path.realpath(settings.WORKTREE_ROOT))
    repo = Path(os.path.realpath(project.root_path))
    if root == repo or root.is_relative_to(repo) or repo.is_relative_to(root):
        raise PreflightError(
            f"WORKTREE_ROOT {root} overlaps the project checkout {repo}: set"
            " WORKTREE_ROOT to a directory outside the repository"
        )


class ConnectedRunners:
    """The baseline and trial runners for the project as connect resolved it.

    Both runners read ``project.test_command`` from their constructor, and
    connect resolves it (a bare ``python`` becomes an absolute path), so
    ``bind`` rebuilds them from the resolved project after every preflight
    check. Before any check they hold the project as given. ``notes`` is the
    runners' ``on_note`` and ``prefix`` their branch prefix: the delegates
    scope the notes to the run a call serves.
    """

    def __init__(
        self,
        project: Project,
        build: Callable[[Project], _Runners],
        *,
        prefix: str | None = None,
        notes: RunNotes | None = None,
    ) -> None:
        self._project, self._build = project, build
        self.prefix = settings.TRIAL_BRANCH_PREFIX if prefix is None else prefix
        self.notes = RunNotes() if notes is None else notes
        self.baseline, self.trial = build(project)

    def run_of(self, branch: str, hypothesis_id: str) -> str | None:
        """The run id ``<prefix>trial-<run>-<hypothesis_id>`` names, else None."""
        head, tail = f"{self.prefix}trial-", f"-{hypothesis_id}"
        if not branch.startswith(head) or not branch.endswith(tail):
            return None
        return branch[len(head) : len(branch) - len(tail)] or None

    def bind(self, project: Project, report: PreflightReport) -> None:
        """Rebuild the runners for ``project`` with the resolved test command."""
        if (project.id, project.root_path) != (
            self._project.id,
            self._project.root_path,
        ):
            raise EngineError(
                f"this engine context was built for project {self._project.id} at"
                f" {self._project.root_path}, not {project.id} at {project.root_path}"
            )
        resolved = project.model_copy(update={"test_command": report.test_command})
        self.baseline, self.trial = self._build(resolved)


class ConnectedPreflight:
    """``Preflight`` that binds the runners to the report it returns."""

    def __init__(self, inner: Preflight, runners: ConnectedRunners) -> None:
        self.inner, self._runners = inner, runners

    def check(
        self,
        project: Project,
        workloads: Sequence[Workload],
        guardrails: Sequence[Guardrail],
    ) -> PreflightReport:
        report = self.inner.check(project, workloads, guardrails)
        self._runners.bind(project, report)
        return report


class ConnectedBaselineRunner:
    """``BaselineRunner`` that delegates to the currently bound runner."""

    def __init__(self, runners: ConnectedRunners) -> None:
        self.runners = runners

    @property
    def current(self) -> BaselineRunner:
        return self.runners.baseline

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        with self.runners.notes.scope(run_id, RunPhase.baseline):
            return self.current.measure(workloads, run_id=run_id, commit=commit)


class ConnectedTrialRunner:
    """``TrialRunner`` that delegates to the currently bound runner."""

    def __init__(self, runners: ConnectedRunners) -> None:
        self.runners = runners

    @property
    def current(self) -> TrialRunner:
        return self.runners.trial

    def run(
        self,
        hypothesis: Hypothesis,
        workloads: Sequence[Workload],
        baseline: Baseline,
        *,
        round: int,
        branch: str,
        budget_usd: float,
        brief: TrialBrief,
    ) -> Trial:
        run_id = self.runners.run_of(branch, hypothesis.id)
        with self.runners.notes.scope(run_id, RunPhase.trials):
            return self.current.run(
                hypothesis,
                workloads,
                baseline,
                round=round,
                branch=branch,
                budget_usd=budget_usd,
                brief=brief,
            )


def build_context(
    project: Project,
    *,
    candidates: Sequence[Hypothesis] = (),
    repository: Repository | None = None,
    judges: Sequence[Judge] | None = None,
    protected_patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS,
    branch_prefix: str | None = None,
    max_hypotheses_per_round: int = 3,
    transport: LLMTransport | None = None,
    transport_factory: TransportFactory = AnthropicTransport,
    editor: EditorFactory | None = None,
    min_trial_budget_usd: float | None = None,
    network: IsolationMode | None = None,
    fs: IsolationMode | None = None,
    run: RunOnce = run_once,
    sleep: Callable[[float], None] = time.sleep,
) -> NodeContext:
    """The real context for ``project``; keyword overrides are for tests."""
    _refuse_overlap(project)
    _pin_sdk_logger()
    llm = engine_transport(transport, transport_factory)
    if editor is None:
        if llm is None:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY is not set (.env or environment): the trial"
                " editor needs Claude"
            )
        editor = claude_editor_factory(llm, sleep=sleep)
    trial_editor = editor
    prefix = settings.TRIAL_BRANCH_PREFIX if branch_prefix is None else branch_prefix
    network = settings.NETWORK_ISOLATION if network is None else network
    fs = settings.FS_ISOLATION if fs is None else fs
    protected = tuple(protected_patterns)
    git = GitWorkspace(
        Path(project.root_path),
        executable=settings.GIT_EXECUTABLE,
        timeout_s=settings.GIT_TIMEOUT_S,
    )

    notes = RunNotes()

    def runners_for(bound: Project) -> _Runners:
        return (
            GitBaselineRunner(
                bound, git=git, on_note=notes, network=network, fs=fs, run=run
            ),
            GitTrialRunner(
                bound,
                editor=trial_editor,
                git=git,
                on_note=notes,
                prefix=prefix,
                network=network,
                fs=fs,
                run=run,
            ),
        )

    runners = ConnectedRunners(project, runners_for, prefix=prefix, notes=notes)
    preflight = GitPreflight(
        executable=settings.GIT_EXECUTABLE,
        protected=protected,
        network=network,
        fs=fs,
        run=run,
    )
    return NodeContext(
        runner=ConnectedTrialRunner(runners),
        baseline_runner=ConnectedBaselineRunner(runners),
        judges=(
            default_judges(settings.NOISE_MULTIPLIER)
            if judges is None
            else tuple(judges)
        ),
        repository=InMemoryRepository() if repository is None else repository,
        candidates=tuple(candidates),
        protected_patterns=protected,
        branch_prefix=prefix,
        max_hypotheses_per_round=max_hypotheses_per_round,
        preflight=ConnectedPreflight(preflight, runners),
        understander=(
            None
            if llm is None
            else ClaudeUnderstander(llm, config=settings, sleep=sleep)
        ),
        profiler=CProfiler(project, git=git, network=network, fs=fs, run=run),
        combiner=GitCombiner(git=git, network=network, fs=fs, run=run),
        publisher=GitBranchPublisher(git=git, prefix=prefix),
        min_trial_budget_usd=(
            min_trial_budget() if min_trial_budget_usd is None else min_trial_budget_usd
        ),
    )
