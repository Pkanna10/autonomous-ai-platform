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
  (``min_trial_budget``, the editor's chain), unless given.

Step 3 (U10). Each role's transport bills its own chain (spec section 5):
injected through ``role_transports``; else, when the engine's transport is
injected, the caller wires every transport (a captured run never gains an
uncaptured one), so only the editor may reuse it, while it bills the
editor's chain, as in Step 2; else, with a key,
``transport_factory(role_settings(settings, role))``, never the base
settings. A transport on another chain is refused. The generator is built
when it has a transport; the matcher and the playbook only for ``matched``
retrieval (blind keeps ``techniques`` and ``playbook`` empty, D1). The trial
runner gets ``EDITOR_FIX_RETRIES``, the floor ``min_trial_budget()`` and
``PAIRED_TRIALS``; the context the run's fix retries, the output check,
confirmation and the calibrator (the connected baseline runner, when any
block is set) with its blocks, all from the settings (D4); with
``PAIRED_TRIALS``, ``CONFIRM_WINNERS`` and the blocks off they are Step 2's. With a confirmed ``quality`` check one
``FrozenScorer`` (launching through a ``NoteTap`` of ``run``) is in both
runners, the combiner and the profiler, which mask its frozen files, and the
judges print its drops in its unit (D37, D38); without one nothing changes.

Step 3 Wave 2 (N4b; D43, D54, C11). With ``IDEA_PIPELINE`` on the
generator is ``IdeaPipelineGenerator`` on the ``lane``, ``leap`` and
``reviewer`` transports, resolved as every role's is; all three must
resolve or the build is refused naming the missing role (never today's
generator, never no generator, in silence). Today's generator, when it has a
transport, is the pipeline's fallback for a call with no code context; the
pipeline reads code through ``repo_reader`` (a ``GitWorkspace`` on the
project's checkout, at the base commit it is given). The discovery share is
``IDEAS_DISCOVERY_MAX_SHARE`` with the pipeline on, else
``DISCOVERY_MAX_SHARE``; ``portfolio_rounds`` is ``PORTFOLIO_ROUNDS`` either
way. With the pipeline off no pipeline transport is resolved or built.

Everything that launches repository code (preflight's probe, the profiler,
both runners, the combiner, the quality scorer) is passed the context's
isolation modes and one launcher (``run``, ``procrun.run_once`` unless a
test injects a recorder) explicitly. The runners' notes (``RunSample``, ``RunFailure``, ``Measured``,
e.g. the nondeterministic-output warning) are ``runner_note`` warning
events of the run and phase the delegate serves (``RunNotes``); a context
serves one run at a time, since connect rebinds its runners.

The engine's transport is the injected one, else
``transport_factory(settings)`` (``AnthropicTransport``) only when
``ANTHROPIC_API_KEY`` is set, else none: understand then keeps its Step 1
stub, and the trials need an editor transport or an injected editor
(``LLMConfigError`` otherwise, before anything runs). The factory never
reads the key: ``AnthropicTransport`` is the only code that unwraps
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
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

import structlog

from autonomous_ai_agents.clients.cost import preflight_estimate
from autonomous_ai_agents.clients.transport import AnthropicTransport, LLMTransport
from autonomous_ai_agents.common.config import (
    IsolationMode,
    Role,
    Settings,
    role_chain,
    role_settings,
    settings,
)
from autonomous_ai_agents.common.errors import (
    EngineError,
    LLMConfigError,
    PreflightError,
)
from autonomous_ai_agents.common.models import (
    Baseline,
    EventLevel,
    FrozenFile,
    Guardrail,
    Hypothesis,
    Measurement,
    NoiseCalibration,
    Project,
    QualityCheck,
    RunPhase,
    Trial,
    Workload,
)
from autonomous_ai_agents.common.repo_read import RepoReader
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
from autonomous_ai_agents.execution.quality import FrozenScorer
from autonomous_ai_agents.execution.runner import BaselineRunner, TrialRunner
from autonomous_ai_agents.execution.trial_runner import (
    EditorFactory,
    GitBaselineRunner,
    GitTrialRunner,
    NoteTap,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.hypothesis_source import (
    ClaudeHypothesisGenerator,
    ClaudeTechniqueMatcher,
)
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.judges import Judge, default_judges
from autonomous_ai_agents.optimization.sources import HypothesisGenerator
from autonomous_ai_agents.orchestrator.events import emit, make_event
from autonomous_ai_agents.orchestrator.nodes import NodeContext, NoiseCalibrator
from autonomous_ai_agents.orchestrator.understand import ClaudeUnderstander
from autonomous_ai_agents.persistence.repository import (
    InMemoryRepository,
    Repository,
)
from autonomous_ai_agents.research.playbook import load_playbook

TransportFactory = Callable[[Settings], LLMTransport]
"""Builds the engine's transport from the settings (``AnthropicTransport``)."""

_Runners = tuple[BaselineRunner, TrialRunner]

SDK_LOGGER = "anthropic"
PIPELINE_ROLES: Final[tuple[Role, ...]] = ("lane", "leap", "reviewer")
_ROLE_TRANSPORTS: Final[tuple[Role, ...]] = (
    "editor",
    "generator",
    "matcher",
    *PIPELINE_ROLES,
)
_LOG = structlog.get_logger("autonomous_ai_agents.engine")


def min_trial_budget() -> float:
    """One worst-case editor request: no prompt, ``EDITOR_MAX_TOKENS`` out,
    priced over the chain the editor's transport sends (spec decision 10;
    the engine's while ``EDITOR_MODEL`` is unset). Also the retry floor (D12)."""
    return preflight_estimate(
        0,
        settings.EDITOR_MAX_TOKENS,
        role_chain(settings, "editor"),
        settings.MODEL_PRICING,
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


def role_transport(
    role: Role,
    given: Mapping[Role, LLMTransport],
    injected: LLMTransport | None,
    transport_factory: TransportFactory,
) -> LLMTransport | None:
    """``role``'s transport (module docstring), checked to bill ``role``'s chain."""
    expected = role_chain(settings, role)
    found = given.get(role)
    if found is None and injected is not None:  # the caller wires (captures) them
        shared = role == "editor" and tuple(injected.chain) == expected
        found = injected if shared else None
    elif found is None and settings.ANTHROPIC_API_KEY is not None:
        found = transport_factory(role_settings(settings, role))
    if found is not None and tuple(found.chain) != expected:
        raise ValueError(
            f"the {role} transport bills {list(found.chain)}, "
            f"not the {role} chain {list(expected)}"
        )
    return found


def repo_reader(project: Project) -> RepoReader:
    """The idea pipeline's reader: the project's git objects, never its
    working tree (D44), as the understander reads them."""
    return GitWorkspace(
        Path(project.root_path),
        executable=settings.GIT_EXECUTABLE,
        timeout_s=settings.GIT_TIMEOUT_S,
    )


def idea_pipeline(
    role: Callable[[Role], LLMTransport | None],
    fallback: HypothesisGenerator | None,
    *,
    sleep: Callable[[float], None],
) -> IdeaPipelineGenerator:
    """The pipeline on every one of its roles' transports, or ``ValueError``
    naming the first role with none (C11): a captured run never gains an
    uncaptured transport, and a missing role never quietly means today's
    generator or none."""
    transports: dict[Role, LLMTransport] = {}
    for name in PIPELINE_ROLES:
        found = role(name)
        if found is None:
            raise ValueError(
                f"IDEA_PIPELINE is on and the idea pipeline needs a {name} transport:"
                f" give role_transports[{name!r}] or set ANTHROPIC_API_KEY"
            )
        transports[name] = found
    return IdeaPipelineGenerator(
        transports, reader=repo_reader, config=settings, sleep=sleep, fallback=fallback
    )


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


@runtime_checkable
class _Freezing(Protocol):
    """What a quality-aware baseline runner reports (``GitBaselineRunner``)."""

    @property
    def quality_files(self) -> tuple[FrozenFile, ...]: ...

    @property
    def label_leaks(self) -> tuple[str, ...]: ...


class ConnectedBaselineRunner:
    """``BaselineRunner`` and ``NoiseCalibrator`` that delegate to the currently
    bound runner, with its ``quality_files`` and ``label_leaks`` (none for a
    runner that freezes nothing)."""

    def __init__(self, runners: ConnectedRunners) -> None:
        self.runners = runners

    @property
    def current(self) -> BaselineRunner:
        return self.runners.baseline

    @property
    def quality_files(self) -> tuple[FrozenFile, ...]:
        current = self.current
        return current.quality_files if isinstance(current, _Freezing) else ()

    @property
    def label_leaks(self) -> tuple[str, ...]:
        current = self.current
        return current.label_leaks if isinstance(current, _Freezing) else ()

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        current = self.current
        if not isinstance(current, NoiseCalibrator):
            raise EngineError("the bound baseline runner cannot calibrate the noise")
        with self.runners.notes.scope(run_id, RunPhase.baseline):
            return current.calibrate(
                workloads, run_id=run_id, commit=commit, blocks=blocks
            )

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
    role_transports: Mapping[Role, LLMTransport] | None = None,
    transport_factory: TransportFactory = AnthropicTransport,
    editor: EditorFactory | None = None,
    min_trial_budget_usd: float | None = None,
    network: IsolationMode | None = None,
    fs: IsolationMode | None = None,
    run: RunOnce = run_once,
    sleep: Callable[[float], None] = time.sleep,
    quality: QualityCheck | None = None,
) -> NodeContext:
    """The real context for ``project``; ``quality`` is the caller's confirmed
    check (D40); the other keyword overrides are for tests.

    ``role_transports`` without ``transport=`` and with a key set builds the
    engine's transport and every role missing from it from the key; with
    ``transport=`` it builds none (module docstring). Unknown roles, ``None``
    and ``editor=`` beside an editor transport are refused with ``ValueError``.
    """
    _refuse_overlap(project)
    _pin_sdk_logger()
    given = dict(role_transports or {})
    if "engine" in given:
        raise ValueError("pass the engine's transport as transport=")
    for name, found in given.items():  # a typo or None would be built from the key
        if name not in _ROLE_TRANSPORTS or found is None:
            raise ValueError(
                f"unknown role transport {name!r}: give a transport for any of"
                f" {', '.join(_ROLE_TRANSPORTS)}"
            )
    if editor is not None and "editor" in given:
        raise ValueError("pass editor= or an editor transport, not both")
    llm = engine_transport(transport, transport_factory)

    def role(name: Role) -> LLMTransport | None:
        return role_transport(name, given, transport, transport_factory)

    if editor is None:
        editing = role("editor")
        if editing is None:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY is not set (.env or environment), or no"
                " transport bills the editor's chain: the trial editor needs Claude"
            )
        editor = claude_editor_factory(editing, sleep=sleep)
    trial_editor = editor
    generating = role("generator")
    generator: HypothesisGenerator | None = (
        None
        if generating is None
        else ClaudeHypothesisGenerator(generating, config=settings, sleep=sleep)
    )
    pipeline = settings.IDEA_PIPELINE
    if pipeline:
        generator = idea_pipeline(role, generator, sleep=sleep)
    matched = settings.RESEARCH_RETRIEVAL == "matched"
    matching = role("matcher") if matched else None
    matcher = (
        None
        if matching is None
        else ClaudeTechniqueMatcher(matching, config=settings, sleep=sleep)
    )
    floor = min_trial_budget()
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
    tap: NoteTap | None = None
    scorer: FrozenScorer | None = None
    if quality is not None:
        tap = NoteTap(run)
        scorer = FrozenScorer(quality, run=tap, network=network, fs=fs)

    def runners_for(bound: Project) -> _Runners:
        return (
            GitBaselineRunner(
                bound,
                git=git,
                on_note=notes,
                network=network,
                fs=fs,
                run=run,
                scorer=scorer,
                scorer_notes=tap,
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
                fix_retries=settings.EDITOR_FIX_RETRIES,
                retry_floor_usd=floor,
                paired=settings.PAIRED_TRIALS,
                scorer=scorer,
            ),
        )

    runners = ConnectedRunners(project, runners_for, prefix=prefix, notes=notes)
    baseline_runner = ConnectedBaselineRunner(runners)
    preflight = GitPreflight(
        executable=settings.GIT_EXECUTABLE,
        protected=protected,
        network=network,
        fs=fs,
        run=run,
    )
    return NodeContext(
        runner=ConnectedTrialRunner(runners),
        baseline_runner=baseline_runner,
        judges=(
            default_judges(settings.NOISE_MULTIPLIER, quality=quality)
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
        profiler=CProfiler(
            project, git=git, network=network, fs=fs, run=run, scorer=scorer
        ),
        combiner=GitCombiner(git=git, network=network, fs=fs, run=run, scorer=scorer),
        publisher=GitBranchPublisher(git=git, prefix=prefix),
        min_trial_budget_usd=(
            floor if min_trial_budget_usd is None else min_trial_budget_usd
        ),
        generator=generator,
        matcher=matcher,
        retrieval=settings.RESEARCH_RETRIEVAL,
        generated_classes=settings.GENERATED_CLASSES,
        generator_n=settings.GENERATOR_N,
        generator_max_calls=settings.GENERATOR_MAX_CALLS,
        matcher_k=settings.MATCHER_K,
        discovery_max_share=(
            settings.IDEAS_DISCOVERY_MAX_SHARE
            if pipeline
            else settings.DISCOVERY_MAX_SHARE
        ),
        fix_retries_per_run=settings.EDITOR_FIX_RETRIES_PER_RUN,
        playbook=load_playbook() if matched else (),
        quality=quality,
        default_output_check=settings.DEFAULT_OUTPUT_CHECK,
        calibrator=baseline_runner if settings.NOISE_CALIBRATION_BLOCKS else None,
        calibration_blocks=settings.NOISE_CALIBRATION_BLOCKS,
        confirm_winners=settings.CONFIRM_WINNERS,
        portfolio_rounds=settings.PORTFOLIO_ROUNDS,
    )
