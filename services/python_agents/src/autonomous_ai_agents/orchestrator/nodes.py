"""Engine loop nodes: one closure per phase over a frozen ``NodeContext``.

``make_nodes(ctx)`` returns the node functions LangGraph runs, in loop order
(``NODE_NAMES``); ``make_router(ctx)`` returns the ``after_verdicts`` router.
Everything a node needs besides the state (the trial and baseline runners,
the frozen judges, the repository, protected-path patterns and the rigour
knobs) comes from the context, never from the state, so nothing a trial
writes can change how that trial is judged.

Every node follows the same contract:

- its only parameter is ``state`` (LangGraph's node protocol names it);
- it returns a **delta**: the keys it changes plus ``phase``, and for the
  append-only channels (``trials``, ``verdicts``, ``lessons``, ``events``)
  only the *new* items, never the full list;
- it emits one ``EngineEvent`` through :func:`emit` (the live log) and
  includes it in the ``events`` delta so it is checkpointed too.

A round's trials travel through the state, never through the repository:
``trials`` puts the runner's unjudged trials in ``round_trials``, ``judges``
replaces them with the judged copies (and appends those to ``trials``), and
``verdicts`` reads ``round_trials``. The repository is an audit log, so a
resume in another process (fresh repository) reaches the same verdicts.

The human's approval decision has one representation: ``state["approval"]``,
applied to the append-only ``verdicts`` by :func:`decided_verdicts` wherever
the decided outcome matters (the gate, ``combine``, the report, ``learn``).

Step 2 adds five optional seams to the context (``preflight``,
``understander``, ``profiler``, ``combiner``, ``publisher``). Each defaults
to ``None``, which keeps that node's Step 1 behaviour exactly: ``connect``,
``understand`` and ``profile`` stay stubs, ``combine`` keeps every kept
verdict without a re-test and ``deliver`` joins the trial diffs. ``watch``
stays a stub; ``research`` copies the context's techniques unless ``matched``
retrieval (Step 3, off by default) asks the matcher. Whatever the seams,
the trials node keeps a running cost total and stops below
``min_trial_budget_usd``, the baseline fails closed on nondeterministic
output or a failing test suite, and every report carries a "Run conditions"
section.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from langgraph.types import interrupt
from pydantic import ValidationError

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import shown
from autonomous_ai_agents.common.config import (
    FIX_RETRIES_MAX,
    GENERATOR_MAX_CALLS_MAX,
    GENERATOR_N_MAX,
    MATCHER_K_MAX,
    Retrieval,
    settings,
)
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
    TrialUnaffordable,
    UnusableReplyError,
    add_spend,
    spend_of,
)
from autonomous_ai_agents.common.errors import DeliveryError as DeliveryError
from autonomous_ai_agents.common.errors import EngineError as EngineError
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    NOISE_CALIBRATION_BLOCKS_MAX,
    NOISE_FLOOR_MIN,
    ApprovalDecision,
    ApprovalItem,
    ApprovalRequest,
    Baseline,
    ChangeClass,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    EventLevel,
    Guardrail,
    GuardrailKind,
    Hotspot,
    Hypothesis,
    HypothesisStatus,
    Lesson,
    Measurement,
    NoiseCalibration,
    Objective,
    ObjectiveKind,
    Paper,
    QualityCheck,
    RunPhase,
    ScalarDict,
    Technique,
    TechniqueMatchRecord,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.common.refnames import (
    assert_safe_branch as assert_safe_branch,
)
from autonomous_ai_agents.execution.measure import (
    UNKNOWN,
    baseline_test_count,
    classify_runner,
)
from autonomous_ai_agents.execution.protocols import (
    BranchPublisher,
    Combiner,
    Preflight,
    PreflightReport,
    Profiler,
    ProjectUnderstander,
    TrialBrief,
    UnderstandResult,
)
from autonomous_ai_agents.execution.runner import BaselineRunner, TrialRunner
from autonomous_ai_agents.learning.lessons import lessons_from_verdicts
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    check_diff_all,
    check_run_count,
)
from autonomous_ai_agents.optimization.judges import (
    Judge,
    derive_verdict,
    primary_metric,
)
from autonomous_ai_agents.optimization.ranking import rank_generated, rank_hypotheses
from autonomous_ai_agents.optimization.sources import (
    HypothesisGenerator,
    TechniqueMatcher,
)
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineRules,
    CombineTarget,
    combine_kept,
    is_commit,
    kept_changes,
)
from autonomous_ai_agents.orchestrator.confirm import CONFIRMABLE, confirm_one
from autonomous_ai_agents.orchestrator.events import emit, make_event
from autonomous_ai_agents.orchestrator.state import EngineState, validate_run_id
from autonomous_ai_agents.persistence.repository import Repository

NodeDelta = dict[str, object]
"""What a node returns: the state keys it changes, reducer channels as deltas."""

Route = Literal["approval_gate", "combine", "hypotheses"]
"""Where ``after_verdicts`` can send the run."""


class NodeFn(Protocol):
    """A graph node: takes the state, returns its delta."""

    def __call__(self, state: EngineState) -> NodeDelta: ...


class RouterFn(Protocol):
    """The conditional edge after ``verdicts``."""

    def __call__(self, state: EngineState) -> Route: ...


@runtime_checkable
class NoiseCalibrator(Protocol):
    """Measures the base against itself in ``blocks`` A/A blocks (D41 c).

    Declared here (U17) beside its only reader, the baseline node; the git
    baseline runner implements it (U20) and the factory injects it (U10).
    """

    def calibrate(
        self,
        workloads: Sequence[Workload],
        *,
        run_id: str,
        commit: str,
        blocks: int,
    ) -> NoiseCalibration: ...


LOOP_NODES: tuple[str, ...] = (
    "connect",
    "understand",
    "define",
    "baseline",
    "profile",
    "research",
    "hypotheses",
    "trials",
    "judges",
    "verdicts",
)
"""The linear chain from START to the router, in order."""

TAIL_NODES: tuple[str, ...] = ("approval_gate", "combine", "deliver", "learn", "watch")
"""The delivery tail after the router, in order; ``watch`` leads to END."""

NODE_NAMES: tuple[str, ...] = (*LOOP_NODES, *TAIL_NODES)
"""Every node ``make_nodes`` returns, in graph order."""

ROUTES: tuple[Route, ...] = ("approval_gate", "combine", "hypotheses")
"""The router's targets, each a node name."""


@dataclass(frozen=True)
class NodeContext:
    """Everything the nodes need that must not live in the checkpointed state.

    ``candidates``, ``hotspots`` and ``techniques`` stand in for the research
    and profiler output until Steps 2 and 3 produce them; the rigour knobs
    default to the settings. The noise rule lives in the judges
    (``default_judges(settings.NOISE_MULTIPLIER)``), not here.

    The Step 2 seams (``preflight``, ``understander``, ``profiler``,
    ``combiner``, ``publisher``) default to ``None``, the Step 1 behaviour of
    their node. ``min_trial_budget_usd`` is the least a trial must be able to
    spend before it starts (the factory sets one worst-case editor request).

    Step 3 discovery and retry fields (U2): ``generator`` and ``matcher``
    default to ``None`` (Step 2: no generation, no matching); ``playbook`` is
    what the matcher picks from in ``matched`` retrieval; the knobs mirror
    their settings (``GENERATOR_N`` and so on), which only the factory reads.
    ``fix_retries_per_run`` defaults to 0, so no trial retries until the
    factory passes ``EDITOR_FIX_RETRIES_PER_RUN`` (fail closed, D12).

    Step 3 quality and noise fields (U17), Step 2 by default: ``quality`` is
    the caller's confirmed check (D40; ``None``: none), and
    ``default_output_check``, ``calibrator`` with ``calibration_blocks`` and
    ``confirm_winners`` stay off until the factory passes
    ``DEFAULT_OUTPUT_CHECK``, the baseline runner with
    ``NOISE_CALIBRATION_BLOCKS``, and ``CONFIRM_WINNERS`` (D4, D41).

    Construction refuses duplicate or refname-unsafe candidate ids (each id
    names a trial branch), knobs below 1, a negative or non-finite
    ``min_trial_budget_usd`` and discovery or retry knobs outside their
    settings' ranges, or calibration blocks outside 0-5 or with no
    calibrator, with ``ValueError``.
    """

    runner: TrialRunner
    baseline_runner: BaselineRunner
    judges: tuple[Judge, ...]
    repository: Repository
    candidates: tuple[Hypothesis, ...] = ()
    hotspots: tuple[Hotspot, ...] = ()
    techniques: tuple[Technique, ...] = ()
    protected_patterns: tuple[str, ...] = DEFAULT_PROTECTED_PATTERNS
    min_runs: int = settings.MIN_RUNS
    branch_prefix: str = settings.TRIAL_BRANCH_PREFIX
    max_hypotheses_per_round: int = 3
    preflight: Preflight | None = None
    understander: ProjectUnderstander | None = None
    profiler: Profiler | None = None
    combiner: Combiner | None = None
    publisher: BranchPublisher | None = None
    min_trial_budget_usd: float = 0.0
    generator: HypothesisGenerator | None = None
    matcher: TechniqueMatcher | None = None
    retrieval: Retrieval = "blind"
    generated_classes: tuple[ChangeClass, ...] = (
        ChangeClass.efficiency,
        ChangeClass.behaviour,
    )
    generator_n: int = 5
    generator_max_calls: int = 2
    matcher_k: int = 3
    discovery_max_share: float = 0.25
    fix_retries_per_run: int = 0
    playbook: tuple[Technique, ...] = ()
    quality: QualityCheck | None = None
    default_output_check: bool = False
    calibrator: NoiseCalibrator | None = None
    calibration_blocks: int = 0
    confirm_winners: bool = False

    def __post_init__(self) -> None:
        counts = Counter(candidate.id for candidate in self.candidates)
        repeated = sorted(candidate_id for candidate_id, n in counts.items() if n > 1)
        if repeated:
            raise ValueError(f"candidate ids must be unique; repeated: {repeated}")
        for candidate_id in counts:
            try:
                validate_run_id(candidate_id)
            except ValueError as exc:
                raise ValueError(
                    f"candidate id {candidate_id!r} cannot name a trial branch: {exc}"
                ) from exc
        if self.max_hypotheses_per_round < 1:
            raise ValueError(
                "max_hypotheses_per_round must be at least 1, "
                f"got {self.max_hypotheses_per_round}"
            )
        if self.min_runs < 1:
            raise ValueError(f"min_runs must be at least 1, got {self.min_runs}")
        if not math.isfinite(self.min_trial_budget_usd) or (
            self.min_trial_budget_usd < 0
        ):
            raise ValueError(
                "min_trial_budget_usd must be finite and at least 0, "
                f"got {self.min_trial_budget_usd}"
            )
        self._check_discovery_knobs()
        self._check_noise_knobs()

    def _check_discovery_knobs(self) -> None:
        """The ranges of the matching settings (``common/config.py``)."""
        ranges = {
            "generator_n": (self.generator_n, 1, GENERATOR_N_MAX),
            "matcher_k": (self.matcher_k, 1, MATCHER_K_MAX),
            "generator_max_calls": (
                self.generator_max_calls,
                0,
                GENERATOR_MAX_CALLS_MAX,
            ),
            "fix_retries_per_run": (self.fix_retries_per_run, 0, FIX_RETRIES_MAX),
        }
        for name, (value, low, high) in ranges.items():
            if not low <= value <= high:
                raise ValueError(f"{name} must be {low}-{high}, got {value}")
        share = self.discovery_max_share
        if not (math.isfinite(share) and 0 < share < 1):
            raise ValueError(f"discovery_max_share must be in (0, 1), got {share}")
        classes = self.generated_classes
        if not classes or ChangeClass.novel in classes:
            raise ValueError(
                "generated_classes must name efficiency and/or behaviour, "
                f"never novel; got {[c.value for c in classes]}"
            )

    def _check_noise_knobs(self) -> None:
        """``NOISE_CALIBRATION_BLOCKS``'s range; blocks need a calibrator to run."""
        blocks, high = self.calibration_blocks, NOISE_CALIBRATION_BLOCKS_MAX
        if not 0 <= blocks <= high:
            raise ValueError(f"calibration_blocks must be 0-{high}, got {blocks}")
        if blocks and self.calibrator is None:
            raise ValueError(f"calibration_blocks={blocks} needs a calibrator")


# ---------------------------------------------------------------------------
# Helpers shared by the nodes
# ---------------------------------------------------------------------------


_PROGRESS = "engine_progress"


def keep_progress(exc: BaseException, delta: NodeDelta) -> None:
    """Attach to ``exc`` the delta its node had already earned (what it spent,
    the trials it ran), for ``Orchestrator`` to merge into the failed state.

    A node that raises returns no delta, and a failed run is built from the
    last checkpoint, so without this the money a node spent before it failed
    (and the trials it had saved) would be missing from the failed run.
    """
    vars(exc)[_PROGRESS] = dict(delta)


def progress_of(exc: BaseException) -> NodeDelta:
    """What ``keep_progress`` attached to ``exc``; empty when nothing was."""
    return dict(vars(exc).get(_PROGRESS, {}))


DEFAULT_RSS_MAX_GROWTH = 0.10
"""With no objectives given, the default objective (minimize wall time) comes
with a ``metric_bound`` guardrail: peak RSS may grow by at most this share of
the baseline mean, so the default "faster and leaner" never ships a change
that trades memory for speed (unless the user bounds peak RSS themselves)."""

BRIEF_FALLBACK_HOTSPOTS = 5
"""How many of the run's top hotspots (largest ``share``) a trial's brief
carries when the hypothesis names none of this run's hotspots."""


_STATUS_AFTER_VERDICT: dict[VerdictOutcome, HypothesisStatus] = {
    VerdictOutcome.keep: HypothesisStatus.kept,
    VerdictOutcome.reject: HypothesisStatus.rejected,
    VerdictOutcome.inconclusive: HypothesisStatus.inconclusive,
    VerdictOutcome.needs_approval: HypothesisStatus.trialled,
    VerdictOutcome.review: HypothesisStatus.trialled,  # D35, as needs_approval
}

_RUNNER_STATUSES: frozenset[TrialStatus] = frozenset(
    {TrialStatus.measured, TrialStatus.failed}
)
"""The only statuses a runner may report; the judges and verdicts decide the rest."""


def _announce(
    state: EngineState,
    phase: RunPhase,
    message: str,
    *,
    level: EventLevel = EventLevel.info,
    data: ScalarDict | None = None,
) -> EngineEvent:
    """Build the node's event, emit it to the live log and return it."""
    event = make_event(state["run_id"], phase, message, level=level, data=data)
    emit(event)
    return event


def _note(
    state: EngineState,
    phase: RunPhase,
    code: str,
    message: str,
    *,
    level: EventLevel = EventLevel.info,
    data: ScalarDict | None = None,
) -> EngineEvent:
    """An event a consumer can match: ``data["code"]`` and a ``code: `` prefix."""
    return _announce(
        state,
        phase,
        f"{code}: {message}",
        level=level,
        data={"code": code, **(data or {})},
    )


def _require_commit(state: EngineState, node: str) -> str:
    commit = state["base_commit"]
    if commit is None:
        raise EngineError(
            f"{node} needs the pinned base commit: connect must run with a preflight"
        )
    return commit


def _require_baseline(state: EngineState) -> Baseline:
    baseline = state["baseline"]
    if baseline is None:
        raise EngineError("no baseline measured yet: the baseline node must run first")
    return baseline


def _brief_hotspots(
    hypothesis: Hypothesis, hotspots: Sequence[Hotspot]
) -> tuple[Hotspot, ...]:
    """The hotspots a trial's editor is shown: the ones the hypothesis names,
    in profile order; when it names none of this run's (a caller-built
    candidate, or one generated in an earlier run whose ids belong to that
    run), the run's ``BRIEF_FALLBACK_HOTSPOTS`` largest-share hotspots, ties
    in profile order (``sorted`` is stable). Only the brief changes: the
    hypothesis keeps its own ids."""
    named = tuple(h for h in hotspots if h.id in hypothesis.hotspot_ids)
    if named:
        return named
    ranked = sorted(hotspots, key=lambda h: h.share, reverse=True)
    return tuple(ranked[:BRIEF_FALLBACK_HOTSPOTS])


def _by_id(hypotheses: Iterable[Hypothesis]) -> dict[str, Hypothesis]:
    return {hypothesis.id: hypothesis for hypothesis in hypotheses}


def _title_for(hypotheses: Mapping[str, Hypothesis], verdict: Verdict) -> str:
    hypothesis = hypotheses.get(verdict.hypothesis_id)
    return verdict.hypothesis_id if hypothesis is None else hypothesis.title


def _objective_metrics(objectives: Iterable[Objective]) -> tuple[str, ...]:
    """Objective metrics in objective order, each once."""
    return tuple(dict.fromkeys(objective.metric for objective in objectives))


def _guardrail_metrics(guardrails: Iterable[Guardrail]) -> tuple[str, ...]:
    """Metrics bounded by a guardrail, in guardrail order, each once."""
    return tuple(dict.fromkeys(g.metric for g in guardrails if g.metric is not None))


def _with_statuses(
    hypotheses: Iterable[Hypothesis], status_for: Mapping[str, HypothesisStatus]
) -> list[Hypothesis]:
    return [
        h.model_copy(update={"status": status_for[h.id]}) if h.id in status_for else h
        for h in hypotheses
    ]


def measurement_violations(
    measurements: Iterable[Measurement],
    workload_ids: Iterable[str],
    objective_metrics: Iterable[str],
    min_runs: int,
    guardrail_metrics: Iterable[str] = (),
) -> tuple[Violation, ...]:
    """Require exactly one measurement per (workload, metric) pair.

    For every objective or guardrail metric, in workload then metric order:
    none -> ``missing_measurement`` (a trial cannot dodge a regression or a
    bound check by not reporting the metric); more than one ->
    ``duplicate_measurement`` (the judges read one of them, so a runner could
    report a fast or healthy copy first); an objective metric built from
    fewer than ``min_runs`` runs -> ``too_few_runs``. Guardrail metrics are
    bounded, not proven, so they need no minimum run count.

    ``tests_passed`` is a single flag by design and is not a metric here;
    measurements of workloads outside ``workload_ids`` are ignored because no
    judge reads them.
    """
    objectives = tuple(dict.fromkeys(objective_metrics))
    metrics = tuple(dict.fromkeys((*objectives, *guardrail_metrics)))
    found: dict[tuple[str, str], list[Measurement]] = {}
    for measurement in measurements:
        key = (measurement.workload_id, measurement.metric)
        found.setdefault(key, []).append(measurement)
    violations: list[Violation] = []
    for workload_id in dict.fromkeys(workload_ids):
        for metric in metrics:
            rows = found.get((workload_id, metric), [])
            if not rows:
                violations.append(
                    Violation(
                        rule=ViolationRule.missing_measurement,
                        message=f"metric {metric} was not measured on workload "
                        f"{workload_id}",
                    )
                )
            elif len(rows) > 1:
                violations.append(
                    Violation(
                        rule=ViolationRule.duplicate_measurement,
                        message=f"metric {metric} was measured {len(rows)} times on "
                        f"workload {workload_id}; exactly one measurement is required",
                    )
                )
            elif metric in objectives:
                too_few = check_run_count(rows[0].stats, min_runs)
                if too_few is not None:
                    violations.append(
                        too_few.model_copy(
                            update={
                                "message": f"metric {metric} on workload "
                                f"{workload_id}: {too_few.message}"
                            }
                        )
                    )
    return tuple(violations)


def _baseline_workload_ids(baseline: Baseline, metrics: Sequence[str]) -> list[str]:
    """Workloads the baseline measured an objective metric on (what judges compare)."""
    return list(
        dict.fromkeys(
            m.workload_id for m in baseline.measurements if m.metric in metrics
        )
    )


def _runner_trial_problems(
    trial: Trial, hypothesis: Hypothesis, round_number: int, budget_usd: float
) -> list[str]:
    """Why a runner's Trial cannot be trusted as this hypothesis's round trial."""
    problems: list[str] = []
    if trial.cost_usd > budget_usd:
        problems.append(f"cost_usd {trial.cost_usd} exceeds its budget {budget_usd}")
    if trial.hypothesis_id != hypothesis.id:
        problems.append(
            f"hypothesis_id is {trial.hypothesis_id!r}, expected {hypothesis.id!r}"
        )
    if trial.round != round_number:
        problems.append(f"round is {trial.round}, expected {round_number}")
    if trial.status not in _RUNNER_STATUSES:
        problems.append(f"status is {trial.status}, expected measured or failed")
    if trial.judge_results:
        problems.append("judge_results must be empty: only the judges node judges")
    return problems


def _dedupe(violations: Iterable[Violation]) -> tuple[Violation, ...]:
    """``violations`` in order, each (rule, path, pattern) once (the first wins)."""
    seen: set[tuple[ViolationRule, str | None, str | None]] = set()
    unique: list[Violation] = []
    for violation in violations:
        key = (violation.rule, violation.path, violation.pattern)
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return tuple(unique)


def _active_judges(
    judges: Iterable[Judge], objectives: Sequence[Objective]
) -> tuple[Judge, ...]:
    """The judges that apply to at least one objective."""
    return tuple(j for j in judges if any(j.applies_to(o) for o in objectives))


# ---------------------------------------------------------------------------
# Step 2 helpers: preflight, understand, baseline trust and noise, budget
# ---------------------------------------------------------------------------


def _check_preflight(report: PreflightReport, workloads: Sequence[Workload]) -> None:
    """Refuse a report whose commit could be an option or whose workloads moved."""
    if not is_commit(report.head_commit):
        raise EngineError(
            f"preflight pinned {report.head_commit!r}, which is not a commit id"
        )
    if [w.id for w in report.workloads] != [w.id for w in workloads]:
        raise EngineError("preflight resolved workloads that are not the run's")


def _connect_events(state: EngineState, report: PreflightReport) -> list[EngineEvent]:
    """Dirty entries, isolation modes, preflight notes (warnings), the engine's
    Python and ignored inputs, as connect reports them."""
    phase, sha = RunPhase.connect, report.head_commit
    events: list[EngineEvent] = []
    if report.dirty_entries:
        dirty = len(report.dirty_entries)
        events.append(
            _note(
                state,
                phase,
                "dirty_tree_ignored",
                f"{dirty} uncommitted changes ignored; run measures {sha}",
                level=EventLevel.warning,
                data={"dirty_entries": dirty, "base_commit": sha},
            )
        )
    isolated = report.network == "required" and report.fs == "required"
    events.append(
        _note(
            state,
            phase,
            "isolation",
            f"network {report.network}, filesystem {report.fs}",
            level=EventLevel.info if isolated else EventLevel.warning,
            data={"network": report.network, "fs": report.fs},
        )
    )
    events.extend(
        _note(
            state,
            phase,
            "preflight_note",
            note,
            level=EventLevel.warning,
            data={"note": note},
        )
        for note in report.notes
    )
    if report.python_version is not None:
        version = ".".join(str(part) for part in report.python_version)
        events.append(
            _note(
                state,
                phase,
                "engine_python",
                f"the engine runs Python {version}",
                data={"python_version": version},
            )
        )
    for workload in report.workloads:
        if workload.inputs:
            events.append(
                _note(
                    state,
                    phase,
                    "workload_inputs_ignored",
                    f"workload {workload.name}: {len(workload.inputs)} input(s) "
                    "ignored; Step 2 does not pass Workload.inputs to the command",
                    level=EventLevel.warning,
                    data={"workload_id": workload.id, "inputs": len(workload.inputs)},
                )
            )
    return events


def _charged(
    state: EngineState, budget: Budget, usd: float = 0.0, tokens: int = 0
) -> tuple[float, int]:
    """New run totals after understand: what it reported or what the budget saw.

    The larger of the two counts, so an understander that both records into
    the budget and reports the same spend is charged once, and money spent
    before a failure (timeouts are charged the full estimate) is never lost.
    """
    usd = max(usd, budget.spent_usd - state["cost_usd"])
    tokens = max(tokens, budget.tokens - state["tokens_used"])
    return state["cost_usd"] + usd, state["tokens_used"] + tokens


def _understood(
    state: EngineState, budget: Budget, result: UnderstandResult
) -> NodeDelta:
    cost_usd, tokens_used = _charged(state, budget, result.cost_usd, result.tokens_used)
    phase, understanding = RunPhase.understand, result.understanding
    money: ScalarDict = {"cost_usd": cost_usd, "tokens_used": tokens_used}
    if understanding is None:
        first = _note(
            state,
            phase,
            "understand_unavailable",
            "no understanding came back; trials run without one",
            level=EventLevel.warning,
            data=money,
        )
    else:
        first = _announce(
            state,
            phase,
            f"understood {state['project'].name}: {understanding.language}, "
            f"{len(understanding.candidate_modules)} candidate module(s), "
            f"served by {understanding.served_by_model}",
            data={**money, "served_by_model": understanding.served_by_model},
        )
    notes = [_note(state, phase, "understand_note", note) for note in result.notes]
    return {
        "phase": phase,
        "understanding": understanding,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "events": [first, *notes],
    }


def _understand_failed(state: EngineState, budget: Budget, exc: Exception) -> NodeDelta:
    cost_usd, tokens_used = _charged(state, budget)
    event = _note(
        state,
        RunPhase.understand,
        "understand_failed",
        f"{type(exc).__name__}: {str(exc)[:300]}; trials run without an understanding",
        level=EventLevel.warning,
        data={"error": type(exc).__name__, "cost_usd": cost_usd},
    )
    return {
        "phase": RunPhase.understand,
        "understanding": None,
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "events": [event],
    }


_SOFT_DISCOVERY = (LLMUnavailable, LLMRequestError, UnusableReplyError)
"""Generator outcomes that leave the run going (D18): a note, charged."""


def _untried(
    ctx: NodeContext, state: EngineState
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    """Caller candidates and pooled ideas no trial ran and no round holds."""
    seen = {trial.hypothesis_id for trial in state["trials"]} | {
        hypothesis.id for hypothesis in state["hypotheses"]
    }
    return (
        [h for h in ctx.candidates if h.id not in seen],
        [h for h in state["candidate_pool"] if h.id not in seen],
    )


def _discovery_cap(ctx: NodeContext, state: EngineState) -> float:
    """D7's ``d``: discovery keeps one trial's reserve and stays in its share."""
    cap, cost = state["max_cost_usd"], state["cost_usd"]
    share_left = ctx.discovery_max_share * cap - state["discovery_cost_usd"]
    return min(cap - ctx.min_trial_budget_usd, cost + share_left)


def _live_generator(
    ctx: NodeContext, state: EngineState, *, priced: bool
) -> HypothesisGenerator | None:
    """The generator while a request is still allowed (calls, money), else None.

    ``priced`` (the router) also needs ``d > cost_usd``, so no round is
    scheduled only to find discovery unaffordable; the node leaves that check
    to ``_generate``, which then records ``discovery_exhausted``."""
    spent = state["generator_calls"] >= ctx.generator_max_calls
    if spent or state["budget_exhausted"] or state["discovery_exhausted"]:
        return None
    if priced and _discovery_cap(ctx, state) <= state["cost_usd"]:
        return None
    return ctx.generator


def _title_key(title: str) -> str:
    """A title compared as ``generate.py`` dedupes: spacing and case aside."""
    return " ".join(title.split()).casefold()


def _usable_id(hypothesis_id: str, used: set[str]) -> bool:
    try:
        validate_run_id(hypothesis_id)
    except ValueError:
        return False
    return hypothesis_id not in used


@dataclass(frozen=True)
class _Generated:
    """One generator turn: new ideas (model order), state keys, events."""

    hypotheses: list[Hypothesis]
    delta: NodeDelta
    events: list[EngineEvent]


def _discovery_spend(state: EngineState, budget: Budget, *, called: bool) -> NodeDelta:
    """The run and discovery totals after a generator turn (D7, D18)."""
    cost_usd, tokens_used = _charged(state, budget)
    spent = cost_usd - state["cost_usd"]
    return {
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
        "discovery_cost_usd": state["discovery_cost_usd"] + spent,
        "generator_calls": state["generator_calls"] + int(called),
    }


def _sift(
    ctx: NodeContext, state: EngineState, generated: Sequence[Hypothesis]
) -> tuple[list[Hypothesis], list[Hypothesis], list[str]]:
    """Kept and parked ideas, and a note per drop or park (spec 4.2, 3).

    No ``needs_package`` filter yet: ``Hypothesis`` has no ``packages`` field
    until 3b, and the generator prompt forbids new dependencies (D9)."""
    known = [*ctx.candidates, *state["hypotheses"], *state["parked"]]
    known += state["candidate_pool"]
    titles = {_title_key(h.title) for h in known}
    used = {t.hypothesis_id for t in state["trials"]} | {h.id for h in known}
    kept: list[Hypothesis] = []
    parked: list[Hypothesis] = []
    notes: list[str] = []
    for hypothesis in generated:
        named, key = shown(hypothesis.title), _title_key(hypothesis.title)
        if not _usable_id(hypothesis.id, used):
            notes.append(f"dropped hypothesis {named}: its id is unusable or taken")
        elif key in titles:
            notes.append(f"dropped repeated hypothesis {named}")
        elif hypothesis.change_class not in ctx.generated_classes:
            reason = {"parked_reason": "needs approval"}
            parked.append(hypothesis.model_copy(update=reason))
            notes.append(f"parked {hypothesis.change_class.value} hypothesis {named}")
        else:
            kept.append(hypothesis)
        used.add(hypothesis.id)
        titles.add(key)
    return kept, parked, notes


def _generate(
    ctx: NodeContext,
    state: EngineState,
    generator: HypothesisGenerator,
    lessons: Sequence[Lesson],
) -> _Generated:
    """One generator request on D7's narrowed budget, or none when unaffordable."""
    phase, cost, d = RunPhase.hypotheses, state["cost_usd"], _discovery_cap(ctx, state)
    unaffordable, warn = "discovery_unaffordable", EventLevel.warning
    if d <= cost:  # never a Budget: a negative cap is a ValueError (D7)
        message = f"no request: discovery may spend up to {d:.6f} USD"
        event = _note(state, phase, unaffordable, message, level=warn)
        return _Generated([], {"discovery_exhausted": True}, [event])
    # The baseline's objectives carry the calibrated floor (D41 c); a direct
    # call before any baseline (node tests) reads define's.
    measured = state["baseline"]
    objectives = state["objectives"] if measured is None else measured.objectives
    if not objectives:
        raise EngineError("hypotheses needs an objective: define must run first")
    budget = Budget(cap_usd=d, spent_usd=cost, tokens=state["tokens_used"])
    try:
        result = generator.generate(
            project=state["project"],
            understanding=state["understanding"],
            hotspots=state["hotspots"],
            objective=objectives[0],
            techniques=state["techniques"],
            lessons=lessons,
            avoid_titles=[h.title for h in (*state["hypotheses"], *state["parked"])],
            n=ctx.generator_n,
            budget=budget,
        )
    except BudgetExceeded as exc:  # the reserve or the share refused it (D7)
        spend = _discovery_spend(state, budget, called=budget.spent_usd > cost)
        event = _note(state, phase, unaffordable, str(exc)[:300], level=warn)
        return _Generated([], {**spend, "discovery_exhausted": True}, [event])
    except _SOFT_DISCOVERY as exc:
        message = f"{type(exc).__name__}: {str(exc)[:300]}"
        event = _note(state, phase, "generate_failed", message, level=warn)
        return _Generated([], _discovery_spend(state, budget, called=True), [event])
    except Exception as exc:  # LLMConfigError or a bug: the run ends, charged
        keep_progress(exc, _discovery_spend(state, budget, called=True))
        raise
    kept, parked, notes = _sift(ctx, state, result.hypotheses)
    delta = _discovery_spend(state, budget, called=True)
    delta["parked"] = [*state["parked"], *parked]
    counts: ScalarDict = {"kept": len(kept), "parked": len(parked)}
    summary = f"{len(kept)} hypothesis(es) kept, {len(parked)} parked"
    events = [_note(state, phase, "generated", summary, data=counts)]
    for note in (*result.notes, *notes):
        events.append(_note(state, phase, "generate_note", note))
    return _Generated(kept, delta, events)


_SOFT_MATCH = (BudgetExceeded, LLMConfigError, *_SOFT_DISCOVERY)
"""Matcher outcomes that continue blind (spec 4.1): a note, charged. Wider
than the generator's: matching is optional, so even a refused key is soft."""


@dataclass(frozen=True)
class _Matched:
    """One research turn: the techniques for the generator, state keys, events."""

    techniques: list[Technique]
    delta: NodeDelta
    events: list[EngineEvent]


def _match_spend(state: EngineState, budget: Budget) -> NodeDelta:
    """D7's totals after a matcher turn; a match is no generator call."""
    spend = _discovery_spend(state, budget, called=False)
    del spend["generator_calls"]
    return spend


def _kept_matches(
    playbook: Sequence[Technique], matches: Sequence[TechniqueMatchRecord], k: int
) -> tuple[list[TechniqueMatchRecord], list[str]]:
    """The first ``k`` matches naming a playbook card, first of each slug, and
    a note per drop (or one saying nothing matched)."""
    known = {technique.slug for technique in playbook}
    kept: dict[str, TechniqueMatchRecord] = {}
    notes: list[str] = []
    for match in matches:
        named = shown(match.slug)
        if match.slug not in known:
            notes.append(f"dropped match {named}: not a playbook technique")
        elif match.slug in kept:
            notes.append(f"dropped repeated match {named}")
        else:
            kept[match.slug] = match
    usable = list(kept.values())
    if len(usable) > k:
        notes.append(f"dropped {len(usable) - k} match(es) beyond k={k}")
    if not usable:
        notes.append("no playbook technique matched; generating without cards")
    return usable[:k], notes


def _match(ctx: NodeContext, state: EngineState) -> _Matched:
    """``matched`` retrieval: one matcher request on D7's narrowed budget; the
    caller's techniques (blind) when it is off, unaffordable or soft-fails."""
    phase, cost, warn = RunPhase.research, state["cost_usd"], EventLevel.warning
    blind, code = list(ctx.techniques), "research_unavailable"
    d = _discovery_cap(ctx, state)
    if ctx.matcher is None or not ctx.playbook:
        message = "matched retrieval has no matcher or no playbook; continuing blind"
        return _Matched(blind, {}, [_note(state, phase, code, message, level=warn)])
    if d <= cost:  # never a Budget: a negative cap is a ValueError (D7)
        message = f"no request: discovery may spend up to {d:.6f} USD; continuing blind"
        event = _note(state, phase, code, message, level=warn)
        return _Matched(blind, {"discovery_exhausted": True}, [event])
    budget = Budget(cap_usd=d, spent_usd=cost, tokens=state["tokens_used"])
    try:
        result = ctx.matcher.match(
            understanding=state["understanding"],
            hotspots=state["hotspots"],
            techniques=ctx.playbook,
            k=ctx.matcher_k,
            budget=budget,
        )
    except _SOFT_MATCH as exc:
        message = f"{type(exc).__name__}: {str(exc)[:300]}; continuing blind"
        event = _note(state, phase, code, message, level=warn)
        return _Matched(blind, _match_spend(state, budget), [event])
    except Exception as exc:  # any other EngineError or a bug: the run ends (D18)
        keep_progress(exc, _match_spend(state, budget))
        raise
    kept, dropped = _kept_matches(ctx.playbook, result.matches, ctx.matcher_k)
    by_slug: dict[str, Technique] = {}
    for technique in ctx.playbook:  # the first card of a slug, as the prompt shows
        by_slug.setdefault(technique.slug, technique)
    delta = {**_match_spend(state, budget), "technique_matches": kept}
    notes = [*result.notes, *dropped]
    events = [_note(state, phase, "research_note", note) for note in notes]
    return _Matched([by_slug[m.slug] for m in kept], delta, events)


def _named(names: Mapping[str, str], workload_ids: Iterable[str]) -> str:
    return ", ".join(dict.fromkeys(names.get(w, w) for w in workload_ids))


def _require_trustworthy_baseline(
    measurements: Sequence[Measurement],
    objectives: Sequence[Objective],
    guardrails: Sequence[Guardrail],
    names: Mapping[str, str],
) -> None:
    """Fail closed before any trial when the guardrails could never be judged.

    With ``output_equivalence`` every objective measurement needs the output
    fingerprint all its runs agreed on; with ``tests_pass`` the suite must
    already pass at the base. Raises ``EngineError``.
    """
    kinds = {guardrail.kind for guardrail in guardrails}
    metrics = set(_objective_metrics(objectives))
    if GuardrailKind.output_equivalence in kinds:
        unseeded = _named(
            names,
            (
                m.workload_id
                for m in measurements
                if m.metric in metrics and m.output_fingerprint is None
            ),
        )
        if unseeded:
            raise EngineError(
                "nondeterministic or missing output: add a seed or `output_file` "
                f"(the runs did not agree on one output on workload(s) {unseeded})"
            )
    if GuardrailKind.tests_pass in kinds:
        failing = _named(
            names,
            (
                m.workload_id
                for m in measurements
                if m.metric == METRIC_TESTS_PASSED
                and not math.isclose(m.stats.mean, 1.0)
            ),
        )
        if failing:
            raise EngineError(
                "the test suite already fails at the base commit (workload(s) "
                f"{failing}): fix it or the test command before optimising"
            )


_NOISY_FLOOR = 0.10
"""A smallest provable gain above this marks a noisy host (warning, not info)."""

_SHORT_RUN_S = 0.5
"""A mean run under this many seconds is dominated by start-up jitter."""


@dataclass(frozen=True)
class _Noise:
    """The primary metric's spread on one workload and what it lets us prove."""

    workload_id: str
    metric: str
    mean: float
    unit: str
    cv: float | None
    floor: float | None

    @property
    def short(self) -> bool:
        return self.unit == "s" and self.mean < _SHORT_RUN_S

    @property
    def noisy(self) -> bool:
        return self.floor is None or self.floor > _NOISY_FLOOR or self.short


def _noise(
    measurements: Sequence[Measurement], objectives: Sequence[Objective]
) -> list[_Noise]:
    """Per workload, the smallest provable relative gain on the primary metric.

    ``max(NOISE_MULTIPLIER x CV, min_relative_gain)`` with the primary
    objective's ``min_relative_gain`` (what its judge applies) and CV =
    stdev / |mean| of the baseline. A zero mean leaves CV and floor ``None``:
    no relative gain can be proven against it.
    """
    if not objectives:
        return []
    primary = max(objectives, key=lambda objective: objective.weight)
    found: list[_Noise] = []
    for m in measurements:
        if m.metric != primary.metric:
            continue
        cv = None if m.stats.mean == 0 else m.stats.stdev / abs(m.stats.mean)
        floor = (
            None
            if cv is None
            else max(settings.NOISE_MULTIPLIER * cv, primary.min_relative_gain)
        )
        found.append(
            _Noise(m.workload_id, m.metric, m.stats.mean, m.stats.unit, cv, floor)
        )
    return found


def _worst_floor(noise: Sequence[_Noise]) -> float | None:
    """The largest floor, or ``None`` when there is none or one is unprovable."""
    floors = [n.floor for n in noise if n.floor is not None]
    return max(floors) if floors and len(floors) == len(noise) else None


def _noisy_host(state: EngineState, noise: _Noise, name: str) -> EngineEvent:
    """One workload's noise floor: a warning when it is noisy, info otherwise."""
    if noise.cv is None or noise.floor is None:
        message = (
            f"workload {name}: the {noise.metric} mean is 0, so no relative gain "
            "can be proven"
        )
    else:
        message = (
            f"workload {name}: CV {noise.cv:.1%}, smallest provable gain "
            f"{noise.floor:.1%}"
        )
        if noise.short:
            message += f"; runs under {_SHORT_RUN_S} s are dominated by start-up noise"
    return _note(
        state,
        RunPhase.baseline,
        "noisy_host",
        message,
        level=EventLevel.warning if noise.noisy else EventLevel.info,
        data={
            "workload_id": noise.workload_id,
            "metric": noise.metric,
            "mean": noise.mean,
            "cv": noise.cv,
            "smallest_provable_gain": noise.floor,
        },
    )


def _calibrated(
    ctx: NodeContext, state: EngineState, objectives: tuple[Objective, ...]
) -> tuple[tuple[Objective, ...], NoiseCalibration | None, float | None]:
    """The objectives under the per-project noise floor, its calibration and
    the floor applied (D41 c); with no blocks asked, Step 2's objectives and
    ``None`` twice.

    The raise is keyed by metric name, and only when calibrated: a
    ``wall_time_s`` objective gets ``max(user value, NOISE_FLOOR_MIN,
    calibrated floor)``; a ``cpu_time_s`` objective, not calibrated (U20),
    gets ``max(user value, NOISE_FLOOR_MIN)``; every other metric (memory
    among them) keeps the user's value. Fewer blocks than asked, or a floor no
    gain can clear (100 % or more), stops the run with ``EngineError``.
    """
    if ctx.calibrator is None or not ctx.calibration_blocks:
        return objectives, None, None
    blocks = ctx.calibration_blocks
    calibration = ctx.calibrator.calibrate(
        state["workloads"],
        run_id=state["run_id"],
        commit=_require_commit(state, "the noise calibration"),
        blocks=blocks,
    )
    if calibration.blocks != blocks:
        raise EngineError(
            f"the noise calibration ran {calibration.blocks} block(s), "
            f"{blocks} were asked"
        )
    floor = max(NOISE_FLOOR_MIN, calibration.floor)
    if not floor < 1:
        raise EngineError(
            f"the noise floor is {floor:.0%}: no gain can be proven on this host"
        )
    least = {METRIC_WALL_TIME_S: floor, METRIC_CPU_TIME_S: NOISE_FLOOR_MIN}
    raised = tuple(
        o.model_copy(
            update={"min_relative_gain": max(o.min_relative_gain, least[o.metric])}
        )
        if o.metric in least
        else o
        for o in objectives
    )
    return raised, calibration, floor


def _judged(
    trial: Trial,
    baseline: Baseline,
    judges: Sequence[Judge],
    completeness: Callable[[Sequence[Measurement]], tuple[Violation, ...]],
) -> Trial:
    """``trial`` judged against its paired A rows when it has them (D41 a: the
    run baseline's objectives, guardrails and calibration over the twin's
    rows), else against the run baseline (Step 2).

    A measured trial's incomplete A rows become ``paired base:`` violations in
    ``trial.violations`` (each once, so judging again adds none), as combine's
    interleaved baseline does; the trial's
    own rows are checked by the verdicts node, so both sides are complete
    before a verdict. A failed trial is rejected for failing (rule 2).
    """
    reference = baseline
    found: tuple[Violation, ...] = ()
    if trial.base_measurements:
        reference = baseline.model_copy(
            update={"measurements": trial.base_measurements}
        )
        if trial.status is not TrialStatus.failed:
            labelled = (
                v.model_copy(update={"message": f"paired base: {v.message}"})
                for v in completeness(trial.base_measurements)
            )
            found = tuple(v for v in labelled if v not in trial.violations)
    results = tuple(judge.evaluate(reference, trial) for judge in judges)
    return trial.model_copy(
        update={"judge_results": results, "violations": (*trial.violations, *found)}
    )


def _trials_progress(
    state: EngineState, trials: Sequence[Trial], cost_usd: float, tokens_used: int
) -> NodeDelta:
    """What an aborted trials node had earned: the running total and the
    round's finished trials (unjudged; a failed run judges nothing more)."""
    ran = {trial.hypothesis_id: HypothesisStatus.trialled for trial in trials}
    return {
        "round_trials": list(trials),
        "trials": list(trials),
        "hypotheses": _with_statuses(state["hypotheses"], ran),
        "cost_usd": cost_usd,
        "tokens_used": tokens_used,
    }


def _budget_exhausted(
    state: EngineState,
    remaining: float,
    floor: float,
    not_started: int,
    *,
    reason: str | None = None,
) -> EngineEvent:
    """The trials stop: below the floor, or (``reason``) the next trial's
    first editor request alone would pass the cap."""
    left = max(0.0, remaining)
    needs = (
        f"a trial needs more than 0 and at least {floor:.4f} USD"
        if reason is None
        else f"the next trial's first request does not fit ({reason[:300]})"
    )
    return _note(
        state,
        RunPhase.trials,
        "budget_exhausted",
        f"{left:.4f} USD left of the {state['max_cost_usd']:.4f} USD cap; {needs}, "
        f"so {not_started} hypothesis(es) were not started",
        level=EventLevel.warning,
        data={
            "remaining_usd": left,
            "cap_usd": state["max_cost_usd"],
            "min_trial_budget_usd": floor,
            "not_started": not_started,
        },
    )


@dataclass(frozen=True)
class _PrimarySummary:
    """The primary metric's baseline figures for events and the report."""

    metric: str | None
    n: int
    mean: float | None
    unit: str
    workloads: int

    def line(self) -> str:
        """One readable line; metric and unit are sanitised (they end up in reports)."""
        if self.mean is None:
            return f"Baseline: no measurement of {_cell(str(self.metric))}"
        return (
            f"Baseline: {_cell(str(self.metric))} mean {self.mean:.3f} "
            f"{_cell(self.unit)} over {self.n} run(s) on {self.workloads} workload(s)"
        )


def _summarize_primary(
    measurements: Sequence[Measurement], objectives: Sequence[Objective]
) -> _PrimarySummary:
    metric = primary_metric(objectives)
    rows = [m for m in measurements if m.metric == metric]
    if not rows:
        return _PrimarySummary(metric, 0, None, "", 0)
    return _PrimarySummary(
        metric=metric,
        n=sum(row.stats.n for row in rows),
        mean=statistics.fmean(row.stats.mean for row in rows),
        unit=rows[0].stats.unit,
        workloads=len(rows),
    )


def _undecided(summary: str) -> str:
    """Drop the ``needs_approval: `` lead-in a decision has just overtaken."""
    return summary.removeprefix(f"{VerdictOutcome.needs_approval.value}: ")


def decided_verdicts(
    verdicts: Iterable[Verdict], approval: ApprovalDecision | None
) -> list[Verdict]:
    """Return ``verdicts`` with the human's decision applied, in order.

    Approved ``needs_approval`` verdicts become ``keep`` (with the approver
    and note), rejected ones become ``reject`` (with the note), and both get
    the decision in front of their summary; undecided ones are returned as
    they are. Other outcomes are never touched: the
    gate only ever offered ``needs_approval`` verdicts.
    """
    if approval is None:
        return list(verdicts)
    approved = set(approval.approved_verdict_ids)
    rejected = set(approval.rejected_verdict_ids)
    decided: list[Verdict] = []
    for verdict in verdicts:
        if verdict.outcome is not VerdictOutcome.needs_approval:
            decided.append(verdict)
        elif verdict.id in approved:
            decided.append(
                verdict.model_copy(
                    update={
                        "outcome": VerdictOutcome.keep,
                        "approved_by": approval.approver,
                        "approval_note": approval.note,
                        "summary": f"approved by {approval.approver}: "
                        f"{_undecided(verdict.summary)}",
                    }
                )
            )
        elif verdict.id in rejected:
            decided.append(
                verdict.model_copy(
                    update={
                        "outcome": VerdictOutcome.reject,
                        "approval_note": approval.note,
                        "summary": f"rejected by {approval.approver}: "
                        f"{_undecided(verdict.summary)}",
                    }
                )
            )
        else:
            decided.append(verdict)
    return decided


_CELL_LIMIT = 200
"""Longest report cell, in characters, ellipsis included."""

_SUMMARY_LIMIT = 1000
"""Longest combination summary in the report (it narrates several re-tests)."""

_LINE_BREAKS = re.compile(r"[\r\n\v\f\x85\u2028\u2029]+")
"""Everything ``str.splitlines`` or a terminal treats as a line break."""

_WWW_AUTOLINK = re.compile(r"(?i)\bwww\.")

_CELL_ESCAPES = str.maketrans(
    {
        "\\": "\\\\",
        "|": "\\|",
        "`": "\\`",
        "[": "\\[",
        "]": "\\]",
        ":": "\\:",
        "@": "\\@",
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
    }
)


def _cell(text: str, *, limit: int = _CELL_LIMIT) -> str:
    """Make untrusted text (titles, trial errors) inert inside one table cell.

    Line breaks collapse to one space (no new rows, headings or blocks), the
    text is cut to ``limit`` characters with an ellipsis, then
    backslashes, pipes, backticks, brackets, colons and ``@`` get markdown
    escapes, ``www.`` becomes ``www\\.`` and ``&``, ``<`` and ``>`` become
    HTML entities (no cell breaks, code spans, links, GFM autolinks or raw
    HTML). The backslash is escaped first so an input ``\\|`` cannot turn the
    pipe escape into a literal backslash plus a cell break.
    """
    flat = _LINE_BREAKS.sub(" ", text)
    if len(flat) > limit:
        flat = flat[: limit - 1] + "…"
    return _WWW_AUTOLINK.sub("www\\.", flat.translate(_CELL_ESCAPES))


_RSS_DEFINITION = (
    "the largest single process among the waited-for descendants of each run, "
    "not the sum over its process tree"
)

_REF_STEM = re.compile(r"[A-Za-z0-9._/-]+")
"""Characters a trial-ref stem may hold to appear in a copyable shell command."""


def trial_ref_cleanup(trials: Iterable[Trial], run_id: str, prefix: str) -> list[str]:
    """The lines of a copyable command deleting the committed trials' refs.

    One ``git update-ref --stdin`` transaction naming each ref and the commit
    it was left at: exactly this run's refs (a ``trial-<run>-*`` pattern also
    matches run ``<run>-2``'s), nothing at all when one moved since, and no
    command when there is nothing to delete. Empty too when a piece is not
    plain refname characters (the ref stem, a ref) or not a commit id, so
    the command never carries text a shell would interpret.
    """
    refs = {
        f"refs/heads/{trial.branch}": trial.commit
        for trial in trials
        if trial.commit is not None and trial.branch
    }
    plain = _REF_STEM.fullmatch(f"{prefix}trial-{run_id}-") is not None and all(
        _REF_STEM.fullmatch(ref) and is_commit(commit) for ref, commit in refs.items()
    )
    if not refs or not plain:
        return []
    deletes = [f"delete {ref} {commit}" for ref, commit in refs.items()]
    return ["git update-ref --stdin <<'EOF'", *deletes, "EOF"]


def trial_refs_left(state: EngineState, prefix: str) -> list[EngineEvent]:
    """A failed run's warning naming the trial refs it kept, with the command
    that deletes them (a failed run has no report); none without one."""
    refs = list(
        dict.fromkeys(
            f"refs/heads/{trial.branch}"
            for trial in state["trials"]
            if trial.commit is not None and trial.branch
        )
    )
    if not refs:
        return []
    cleanup = "\n".join(trial_ref_cleanup(state["trials"], state["run_id"], prefix))
    return [
        _note(
            state,
            RunPhase.failed,
            "trial_refs_left",
            f"{len(refs)} trial ref(s) kept for review: " + ", ".join(refs),
            level=EventLevel.warning,
            data={"refs": ", ".join(refs), "cleanup": cleanup},
        )
    ]


def _latest(events: Sequence[EngineEvent], code: str) -> EngineEvent | None:
    return next((e for e in reversed(events) if e.data.get("code") == code), None)


def _test_count_text(state: EngineState) -> str:
    """Whether the suite's passing count was read from the runner's summary
    (so fewer passing tests than the baseline fail) or only its exit code."""
    command = state["project"].test_command
    if command is None:
        return "no test command"
    runner = classify_runner(command)
    if runner == UNKNOWN:
        return (
            "not verified (the test command is neither unittest nor pytest, so the"
            " suite passed on its exit code alone; a trial that skips or deletes"
            " tests is not caught)"
        )
    return (
        f"verified from the {runner} summary (fewer passing tests than the"
        " baseline fail)"
    )


def _noise_floor_text(state: EngineState) -> str:
    baseline = state["baseline"]
    noise = (
        [] if baseline is None else _noise(baseline.measurements, baseline.objectives)
    )
    if not noise:
        return "not measured"
    names = {workload.id: workload.name for workload in state["workloads"]}
    return "smallest provable gain " + ", ".join(
        f"{_cell(names.get(n.workload_id, n.workload_id))} "
        + ("unprovable (mean 0)" if n.floor is None else f"{n.floor:.1%}")
        for n in noise
    )


def _run_conditions(state: EngineState, prefix: str) -> list[str]:
    """What the numbers above were measured under, and how to remove trial refs.

    Every value goes through ``_cell``. The cleanup command
    (``trial_ref_cleanup``) sits in a fenced block so it can be copied as is.
    """
    commit, events = state["base_commit"], state["events"]
    lines = ["**Run conditions**", ""]
    if commit is None:
        lines.append("- Measured commit: not pinned (no preflight ran)")
    else:
        dirty = _latest(events, "dirty_tree_ignored")
        count = 0 if dirty is None else dirty.data.get("dirty_entries")
        lines.append(f"- Measured commit: {_cell(commit)}")
        lines.append(f"- Uncommitted changes ignored: {_cell(str(count))}")
    isolation = _latest(events, "isolation")
    lines.append(
        "- Isolation: not checked (no preflight ran)"
        if isolation is None
        else f"- Isolation: network {_cell(str(isolation.data.get('network')))}, "
        f"filesystem {_cell(str(isolation.data.get('fs')))}"
    )
    lines.append(f"- Noise floor: {_noise_floor_text(state)}")
    lines.append(f"- Test count: {_cell(_test_count_text(state))}")
    ignored = [_cell(w.name) for w in state["workloads"] if w.inputs]
    lines.append("- Workload inputs ignored: " + (", ".join(ignored) or "none"))
    combination = state["combination"]
    lines.append(
        "- Combination: "
        + (
            "not re-tested"
            if combination is None
            else _cell(combination.summary, limit=_SUMMARY_LIMIT)
        )
    )
    lines.append(f"- Peak RSS: {_RSS_DEFINITION}")
    refs = list(
        dict.fromkeys(
            f"refs/heads/{trial.branch}"
            for trial in state["trials"]
            if trial.commit is not None and trial.branch
        )
    )
    lines.append("- Trial refs: " + (", ".join(_cell(ref) for ref in refs) or "none"))
    cleanup = trial_ref_cleanup(state["trials"], state["run_id"], prefix)
    if cleanup:
        lines += [
            "",
            "Delete the trial refs once they are reviewed (one transaction: if"
            " one moved since, none is deleted):",
            "",
            "```",
            *cleanup,
            "```",
        ]
    return lines


def _report(state: EngineState, prefix: str) -> str:
    """The markdown report: title, baseline, one row per verdict, kept, conditions."""
    project = state["project"]
    hypotheses = _by_id(state["hypotheses"])
    decided = decided_verdicts(state["verdicts"], state["approval"])
    decided_by_id = {verdict.id: verdict for verdict in decided}
    baseline = state["baseline"]
    baseline_line = (
        "Baseline: not measured"
        if baseline is None
        else _summarize_primary(baseline.measurements, baseline.objectives).line()
    )
    lines = [
        f"# Engine run {state['run_id'][:8]}: {_cell(project.name)}",
        "",
        baseline_line,
        "",
        "| Hypothesis | Outcome | Gain | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for verdict in decided:
        gain = "n/a" if verdict.gain is None else f"{verdict.gain:+.1%}"
        lines.append(
            f"| {_cell(_title_for(hypotheses, verdict))} | {verdict.outcome.value} "
            f"| {gain} | {_cell(verdict.summary)} |"
        )
    kept = [
        _cell(_title_for(hypotheses, decided_by_id[verdict_id]))
        for verdict_id in state["kept_verdict_ids"]
        if verdict_id in decided_by_id
    ]
    lines += ["", "Kept: " + (", ".join(kept) if kept else "nothing"), ""]
    lines += [*_run_conditions(state, prefix), ""]
    return "\n".join(lines)


def _await_decision(request: ApprovalRequest) -> ApprovalDecision:
    """Interrupt until the human sends a valid ``ApprovalDecision``.

    An invalid payload, or one naming verdicts the request never offered,
    never raises: the gate interrupts again with the same request carrying
    the error, so the thread is never poisoned by a bad resume (LangGraph
    replays earlier resume values to earlier ``interrupt()`` calls, and the
    next one waits for a fresh value) and a typo cannot end the run with
    nothing decided.
    """
    offered = {item.verdict_id for item in request.items}
    payload = request.model_dump(mode="json")
    while True:
        raw = interrupt(payload)
        try:
            decision = ApprovalDecision.model_validate(raw)
        except ValidationError as exc:
            error = f"invalid approval decision: {exc}"
        else:
            unknown = sorted(
                {*decision.approved_verdict_ids, *decision.rejected_verdict_ids}
                - offered
            )
            if not unknown:
                return decision
            error = "unknown verdict ids: " + ", ".join(unknown)
        payload = request.model_copy(update={"error": error}).model_dump(mode="json")


def _combine_rules(ctx: NodeContext, baseline: Baseline) -> CombineRules:
    """The verdicts node's judges, primary metric and completeness rule."""
    objective_metrics = _objective_metrics(baseline.objectives)
    workload_ids = _baseline_workload_ids(baseline, objective_metrics)
    guardrail_metrics = _guardrail_metrics(baseline.guardrails)

    def completeness(rows: Sequence[Measurement]) -> tuple[Violation, ...]:
        return measurement_violations(
            rows,
            workload_ids,
            objective_metrics,
            ctx.min_runs,
            guardrail_metrics=guardrail_metrics,
        )

    return CombineRules(
        judges=_active_judges(ctx.judges, baseline.objectives),
        objectives=baseline.objectives,
        guardrails=baseline.guardrails,
        primary=primary_metric(baseline.objectives),
        completeness=completeness,
        baseline_count=baseline_test_count(baseline.measurements),
    )


def _confirmer(
    ctx: NodeContext,
    state: EngineState,
    measured: Baseline,
    known: Mapping[str, Hypothesis],
    notes: list[str],
) -> Callable[[Trial, Verdict], Verdict] | None:
    """The verdicts node's second look (D41 b), or ``None`` with no combiner.

    Judged as combine judges, under the run baseline's objectives (the raised
    floor), never ``state["objectives"]``, scored against its quality files.
    Each look's combiner notes (``last_notes``, when it has them) go to
    ``notes``.
    """
    combiner = ctx.combiner
    if combiner is None or not ctx.confirm_winners:
        return None
    rules = _combine_rules(ctx, measured)

    def confirm(trial: Trial, verdict: Verdict) -> Verdict:
        (change,) = kept_changes([verdict], {trial.id: trial}, known)
        target = CombineTarget(
            run_id=state["run_id"],
            project=state["project"],
            base_commit=_require_commit(state, "the confirmation"),
            workloads=tuple(state["workloads"]),
            branch=f"{ctx.branch_prefix}run-{state['run_id']}",
            round=max(1, state["round"]),
            quality_files=measured.quality_files,
        )
        confirmed = confirm_one(combiner, verdict, change, rules, target)
        for note in map(str, getattr(combiner, "last_notes", ())):
            if note not in notes:
                notes.append(note)
        return confirmed

    return confirm


def _confirmation_notes(
    state: EngineState, looks: Sequence[Verdict], confirmed: bool, notes: Sequence[str]
) -> list[EngineEvent]:
    """One note on the round's winners: how many confirmed, or that none
    could; with the combiner's notes appended."""
    if not looks:
        return []
    if not confirmed:
        return [
            _note(
                state,
                RunPhase.verdicts,
                "confirmation_skipped",
                f"{len(looks)} winner(s) stand on one look: no combiner to "
                "re-test them",
                level=EventLevel.warning,
                data={"winners": len(looks)},
            )
        ]
    held = sum(1 for v in looks if v.outcome in CONFIRMABLE)
    data: ScalarDict = {"confirmed": held, "unconfirmed": len(looks) - held}
    said = ""
    if notes:
        data["notes"] = "; ".join(notes)
        said = f"; combiner notes: {data['notes']}"
    return [
        _note(
            state,
            RunPhase.verdicts,
            "confirmation",
            f"{held} of {len(looks)} winner(s) confirmed on a second look{said}",
            data=data,
        )
    ]


def _publishable(state: EngineState) -> tuple[str, str]:
    """The held combination's tip and the pinned base, or ``EngineError``."""
    combination, base = state["combination"], state["base_commit"]
    if (
        combination is None
        or not combination.holds
        or combination.tip_commit is None
        or base is None
    ):
        raise EngineError(
            "refusing to publish: the kept changes have no held, re-tested "
            "combination at a pinned base commit"
        )
    return combination.tip_commit, base


# ---------------------------------------------------------------------------
# The nodes
# ---------------------------------------------------------------------------


def make_nodes(ctx: NodeContext) -> dict[str, NodeFn]:
    """Return the engine's node functions, keyed by name in graph order."""

    def connect(state: EngineState) -> NodeDelta:
        project = state["project"]
        if ctx.preflight is None:
            event = _announce(
                state,
                RunPhase.connect,
                f"connected {project.name}",
                data={"workloads": len(state["workloads"])},
            )
            return {"phase": RunPhase.connect, "events": [event]}
        report = ctx.preflight.check(project, state["workloads"], state["guardrails"])
        _check_preflight(report, state["workloads"])
        event = _announce(
            state,
            RunPhase.connect,
            f"connected {project.name} at {report.head_commit}",
            data={
                "workloads": len(report.workloads),
                "base_commit": report.head_commit,
                "git_version": ".".join(str(part) for part in report.git_version),
            },
        )
        return {
            "phase": RunPhase.connect,
            "project": project.model_copy(update={"test_command": report.test_command}),
            "workloads": list(report.workloads),
            "base_commit": report.head_commit,
            "extra_protected": list(report.extra_protected),
            "events": [event, *_connect_events(state, report)],
        }

    def understand(state: EngineState) -> NodeDelta:
        if ctx.understander is None:
            event = _announce(
                state,
                RunPhase.understand,
                f"understanding {state['project'].name} (stub: no LLM call in Step 1)",
            )
            return {"phase": RunPhase.understand, "events": [event]}
        commit = _require_commit(state, "understand")
        budget = Budget(
            cap_usd=state["max_cost_usd"],
            spent_usd=state["cost_usd"],
            tokens=state["tokens_used"],
        )
        try:
            result = ctx.understander.understand(
                state["project"], state["workloads"], commit=commit, budget=budget
            )
        except EngineError as exc:  # BudgetExceeded, LLMConfigError: the run ends
            cost_usd, tokens_used = _charged(state, budget)  # a timeout was charged
            keep_progress(exc, {"cost_usd": cost_usd, "tokens_used": tokens_used})
            raise
        except Exception as exc:  # transport outcomes and bad replies are soft
            return _understand_failed(state, budget, exc)
        return _understood(state, budget, result)

    def define(state: EngineState) -> NodeDelta:
        project = state["project"]
        objectives = list(state["objectives"]) or [
            Objective(
                project_id=project.id,
                kind=ObjectiveKind.runtime,
                metric=METRIC_WALL_TIME_S,
                direction=Direction.minimize,
                min_relative_gain=settings.MIN_RELATIVE_GAIN,
                description="minimize wall time",
            )
        ]
        guardrails = list(state["guardrails"])
        bounded = {g.metric for g in guardrails if g.kind is GuardrailKind.metric_bound}
        leaner = not state["objectives"] and METRIC_PEAK_RSS_BYTES not in bounded
        if leaner:  # the default is faster *and* leaner: memory may not grow
            guardrails.append(
                Guardrail(
                    project_id=project.id,
                    kind=GuardrailKind.metric_bound,
                    metric=METRIC_PEAK_RSS_BYTES,
                    max_drop=DEFAULT_RSS_MAX_GROWTH,
                    direction=Direction.minimize,
                    description="peak RSS may not grow by more than "
                    f"{DEFAULT_RSS_MAX_GROWTH:.0%} (default)",
                )
            )
        metrics = ", ".join(objective.metric for objective in objectives)
        kinds = ", ".join(guardrail.kind.value for guardrail in guardrails)
        event = _announce(
            state,
            RunPhase.define,
            f"objectives: {metrics}; guardrails: {kinds or 'none'}",
            data={"objectives": metrics, "guardrails": kinds, "min_runs": ctx.min_runs},
        )
        delta: NodeDelta = {
            "phase": RunPhase.define,
            "objectives": objectives,
            "events": [event],
        }
        if leaner:
            delta["guardrails"] = guardrails
        return delta

    def baseline(state: EngineState) -> NodeDelta:
        measurements = ctx.baseline_runner.measure(
            state["workloads"], run_id=state["run_id"], commit=state["base_commit"]
        )
        objectives = tuple(state["objectives"])
        violations = measurement_violations(
            measurements,
            [workload.id for workload in state["workloads"]],
            _objective_metrics(objectives),
            ctx.min_runs,
            guardrail_metrics=_guardrail_metrics(state["guardrails"]),
        )
        if violations:
            raise EngineError(
                "baseline is not trustworthy: "
                + "; ".join(f"{v.rule}: {v.message}" for v in violations)
            )
        names = {workload.id: workload.name for workload in state["workloads"]}
        _require_trustworthy_baseline(
            measurements, objectives, state["guardrails"], names
        )
        objectives, calibration, floor = _calibrated(ctx, state, objectives)
        measured = Baseline(
            commit=state["base_commit"],
            measurements=measurements,
            objectives=objectives,
            guardrails=tuple(state["guardrails"]),
            calibration=calibration,
        )
        summary = _summarize_primary(measurements, objectives)
        noise = _noise(measurements, objectives)
        data: ScalarDict = {
            "metric": summary.metric,
            "n": summary.n,
            "mean": summary.mean,
            "workloads": summary.workloads,
            "smallest_provable_gain": _worst_floor(noise),
        }
        if calibration is not None:
            data["noise_floor"] = floor
            data["calibration_blocks"] = calibration.blocks
        event = _announce(state, RunPhase.baseline, summary.line(), data=data)
        notes = [
            _noisy_host(state, n, names.get(n.workload_id, n.workload_id))
            for n in noise
        ]
        return {
            "phase": RunPhase.baseline,
            "baseline": measured,
            "events": [event, *notes],
        }

    def profile(state: EngineState) -> NodeDelta:
        if ctx.profiler is None:
            hotspots = list(ctx.hotspots)
            event = _announce(
                state,
                RunPhase.profile,
                f"profiled {len(hotspots)} hotspot(s) (stub)",
                data={"hotspots": len(hotspots)},
            )
            return {"phase": RunPhase.profile, "hotspots": hotspots, "events": [event]}
        commit = _require_commit(state, "profile")
        result = ctx.profiler.profile(
            state["workloads"], run_id=state["run_id"], commit=commit
        )
        event = _announce(
            state,
            RunPhase.profile,
            f"profiled {len(result.hotspots)} hotspot(s) at {commit}",
            data={"hotspots": len(result.hotspots), "skipped": len(result.notes)},
        )
        skipped = [
            _note(state, RunPhase.profile, "profile_skipped", note)
            for note in result.notes
        ]
        return {
            "phase": RunPhase.profile,
            "hotspots": list(result.hotspots),
            "events": [event, *skipped],
        }

    def research(state: EngineState) -> NodeDelta:
        # Blind (the default, D1) sends nothing and keeps Step 2's delta;
        # matched adds keys only for what it changes (spec 4.1). No paper
        # intake in Step 3 (D1), so papers stay empty.
        turn = _Matched(list(ctx.techniques), {}, [])
        if ctx.retrieval == "matched":
            turn = _match(ctx, state)
        techniques, papers = turn.techniques, list[Paper]()
        event = _announce(
            state,
            RunPhase.research,
            f"research ({ctx.retrieval}): {len(techniques)} technique(s), "
            f"{len(papers)} paper(s)",
            data={"techniques": len(techniques), "papers": len(papers)},
        )
        return {
            **turn.delta,
            "phase": RunPhase.research,
            "techniques": techniques,
            "papers": papers,
            "events": [*turn.events, event],
        }

    def hypotheses(state: EngineState) -> NodeDelta:
        round_number = state["round"] + 1
        # An idea is new when no trial ran it and no earlier round holds it;
        # earlier rounds' hypotheses stay (with their statuses) so the report
        # and the lessons see every idea the run tried. Generated ideas wait
        # in the pool; the generator runs only once nothing is left (spec 4.2).
        candidates, pool = _untried(ctx, state)
        lessons = ctx.repository.list_lessons(state["project"].id)
        turn = _Generated([], {}, [])
        live = None if candidates or pool else _live_generator(ctx, state, priced=False)
        if live is not None:
            turn = _generate(ctx, state, live, lessons)
            pool = turn.hypotheses
        # The pool keeps the model's order and is re-ranked every round with
        # the current lessons, as caller candidates are (D8).
        generated = rank_generated(pool, lessons)
        ordered = [*rank_hypotheses(candidates, lessons), *generated]
        limit = ctx.max_hypotheses_per_round
        ranked = [
            h.model_copy(update={"status": HypothesisStatus.proposed})
            for h in ordered[:limit]
        ]
        sliced = {h.id for h in ranked}
        rest = [h for h in pool if h.id not in sliced]  # callers stay in ctx
        event = _announce(
            state,
            RunPhase.hypotheses,
            f"round {round_number}: ranked {len(ranked)} of {len(ordered)} candidates",
            data={
                "round": round_number,
                "ranked": len(ranked),
                "candidates": len(ordered),
            },
        )
        delta: NodeDelta = {
            **turn.delta,
            "phase": RunPhase.hypotheses,
            "round": round_number,
            "hypotheses": [*state["hypotheses"], *ranked],
            "events": [*turn.events, event],
        }
        if state["candidate_pool"] or rest:
            delta["candidate_pool"] = rest
        return delta

    def run_one(
        state: EngineState,
        hypothesis: Hypothesis,
        measured: Baseline,
        remaining: float,
    ) -> Trial:
        """One trial offered ``remaining``; ``EngineError`` when the runner's
        Trial cannot be trusted (charged at most ``remaining`` as progress)."""
        branch = f"{ctx.branch_prefix}trial-{state['run_id']}-{hypothesis.id}"
        assert_safe_branch(branch, state["project"], ctx.branch_prefix)
        trial = ctx.runner.run(
            hypothesis,
            state["workloads"],
            measured,
            round=state["round"],
            branch=branch,
            budget_usd=remaining,
            brief=TrialBrief(
                understanding=state["understanding"],
                hotspots=_brief_hotspots(hypothesis, state["hotspots"]),
                protected=(*ctx.protected_patterns, *state["extra_protected"]),
            ),
        )
        problems = _runner_trial_problems(trial, hypothesis, state["round"], remaining)
        if problems:
            error = EngineError(
                f"runner returned an untrustworthy trial {trial.id} for "
                f"hypothesis {hypothesis.id}: " + "; ".join(problems)
            )
            add_spend(error, trial.cost_usd, trial.tokens_used)
            raise error
        return trial

    def trials(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        run_id = state["run_id"]
        round_number = state["round"]
        # The running total (decision 10): each trial is offered only what the
        # trials before it, this round included, left of the cap.
        cost_usd, tokens_used = state["cost_usd"], state["tokens_used"]
        proposed = [
            h for h in state["hypotheses"] if h.status is HypothesisStatus.proposed
        ]
        new_trials: list[Trial] = []
        stopped: list[EngineEvent] = []
        for index, hypothesis in enumerate(proposed):
            remaining = state["max_cost_usd"] - cost_usd
            if remaining <= 0 or remaining < ctx.min_trial_budget_usd:
                stopped.append(
                    _budget_exhausted(
                        state,
                        remaining,
                        ctx.min_trial_budget_usd,
                        len(proposed) - index,
                    )
                )
                break
            try:
                trial = run_one(state, hypothesis, measured, remaining)
            except TrialUnaffordable as exc:  # its first request alone passes the cap
                stopped.append(
                    _budget_exhausted(
                        state,
                        remaining,
                        ctx.min_trial_budget_usd,
                        len(proposed) - index,
                        reason=str(exc),
                    )
                )
                break
            except Exception as exc:  # the round so far is the failed run's
                usd, tokens = spend_of(exc)
                keep_progress(
                    exc,
                    _trials_progress(
                        state,
                        new_trials,
                        min(state["max_cost_usd"], cost_usd + min(usd, remaining)),
                        tokens_used + tokens,
                    ),
                )
                raise
            # trial.cost_usd <= remaining, so only rounding could pass the cap
            cost_usd = min(state["max_cost_usd"], cost_usd + trial.cost_usd)
            tokens_used += trial.tokens_used
            try:
                ctx.repository.save_trial(run_id, trial)
            except Exception as exc:  # spent but not recorded: keep the money
                keep_progress(
                    exc, _trials_progress(state, new_trials, cost_usd, tokens_used)
                )
                raise
            new_trials.append(trial)
        ran = {trial.hypothesis_id: HypothesisStatus.trialled for trial in new_trials}
        failed = sum(1 for t in new_trials if t.status is TrialStatus.failed)
        event = _announce(
            state,
            RunPhase.trials,
            f"round {round_number}: ran {len(new_trials)} trial(s), {failed} failed",
            data={
                "round": round_number,
                "trials": len(new_trials),
                "failed": failed,
                "cost_usd": cost_usd,
                "tokens_used": tokens_used,
            },
        )
        delta: NodeDelta = {
            "phase": RunPhase.trials,
            "round_trials": new_trials,
            "hypotheses": _with_statuses(state["hypotheses"], ran),
            "cost_usd": cost_usd,
            "tokens_used": tokens_used,
            "events": [*stopped, event],
        }
        if stopped:
            delta["budget_exhausted"] = True
        return delta

    def judges(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        rules = _combine_rules(ctx, measured)
        judged = [
            _judged(trial, measured, rules.judges, rules.completeness)
            for trial in state["round_trials"]
        ]
        for trial in judged:
            ctx.repository.save_trial(state["run_id"], trial)
        paired = sum(1 for trial in judged if trial.base_measurements)
        message = (
            f"round {state['round']}: judged {len(judged)} trial(s) "
            f"with {len(rules.judges)} judge(s)"
        )
        data: ScalarDict = {
            "round": state["round"],
            "trials": len(judged),
            "judges": ", ".join(judge.name for judge in rules.judges),
        }
        if paired:
            message += f", {paired} against a paired base"
            data["paired"] = paired
        event = _announce(state, RunPhase.judges, message, data=data)
        return {
            "phase": RunPhase.judges,
            "trials": judged,
            "round_trials": list(judged),
            "events": [event],
        }

    def verdicts(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        run_id = state["run_id"]
        known = _by_id(state["hypotheses"])
        objective_metrics = _objective_metrics(measured.objectives)
        workload_ids = _baseline_workload_ids(measured, objective_metrics)
        primary = primary_metric(measured.objectives)
        protected = (*ctx.protected_patterns, *state["extra_protected"])
        notes: list[str] = []
        confirm = _confirmer(ctx, state, measured, known, notes)
        new_verdicts: list[Verdict] = []
        looks: list[Verdict] = []
        for trial in state["round_trials"]:
            hypothesis = known.get(trial.hypothesis_id)
            if hypothesis is None:
                raise EngineError(
                    f"trial {trial.id} refers to unknown hypothesis {trial.hypothesis_id}"
                )
            # A failed trial is rejected for failing (verdict rule 2); its
            # missing measurements are a consequence, not a violation.
            completeness = (
                ()
                if trial.status is TrialStatus.failed
                else measurement_violations(
                    trial.measurements,
                    workload_ids,
                    objective_metrics,
                    ctx.min_runs,
                    guardrail_metrics=_guardrail_metrics(measured.guardrails),
                )
            )
            # The node's own path check, the runner's capture violations, then
            # completeness; a rule found twice for one path is reported once.
            violations = _dedupe(
                (
                    *check_diff_all(trial.touched_paths, protected),
                    *trial.violations,
                    *completeness,
                )
            )
            verdict = derive_verdict(
                trial,
                hypothesis,
                trial.judge_results,
                violations,
                primary_metric=primary,
            )
            if ctx.confirm_winners and verdict.outcome in CONFIRMABLE:
                verdict = verdict if confirm is None else confirm(trial, verdict)
                looks.append(verdict)
            ctx.repository.save_verdict(run_id, verdict)
            new_verdicts.append(verdict)
        status_for = {
            v.hypothesis_id: _STATUS_AFTER_VERDICT[v.outcome] for v in new_verdicts
        }
        counts = {
            outcome.value: sum(1 for v in new_verdicts if v.outcome is outcome)
            for outcome in VerdictOutcome
        }
        event = _announce(
            state,
            RunPhase.verdicts,
            f"round {state['round']}: {len(new_verdicts)} verdict(s): "
            f"{counts['keep']} keep, {counts['reject']} reject, "
            f"{counts['inconclusive']} inconclusive, "
            f"{counts['needs_approval']} need approval",
            data={"round": state["round"], "verdicts": len(new_verdicts), **counts},
        )
        return {
            "phase": RunPhase.verdicts,
            "verdicts": new_verdicts,
            "hypotheses": _with_statuses(state["hypotheses"], status_for),
            "pending_approval_ids": [
                v.id for v in new_verdicts if v.outcome is VerdictOutcome.needs_approval
            ],
            "events": [
                *_confirmation_notes(state, looks, confirm is not None, notes),
                event,
            ],
        }

    def approval_gate(state: EngineState) -> NodeDelta:
        # Everything before interrupt() runs again on resume, so the request
        # is built from state only and nothing is written until a valid
        # decision is in hand.
        run_id = state["run_id"]
        known = _by_id(state["hypotheses"])
        verdicts_by_id = {v.id: v for v in state["verdicts"]}
        pending = [
            verdicts_by_id[verdict_id]
            for verdict_id in state["pending_approval_ids"]
            if verdict_id in verdicts_by_id
        ]
        request = ApprovalRequest(
            run_id=run_id,
            items=tuple(
                ApprovalItem(
                    verdict_id=verdict.id,
                    title=_title_for(known, verdict),
                    change_class=verdict.change_class,
                    gain=verdict.gain,
                    summary=verdict.summary,
                )
                for verdict in pending
            ),
            message=f"{len(pending)} change(s) need human approval before delivery",
        )
        decision = _await_decision(request)
        decided = [
            after
            for before, after in zip(
                pending, decided_verdicts(pending, decision), strict=True
            )
            if after.outcome is not before.outcome
        ]
        for verdict in decided:
            ctx.repository.save_verdict(run_id, verdict)
        approved = sum(1 for v in decided if v.outcome is VerdictOutcome.keep)
        rejected = sum(1 for v in decided if v.outcome is VerdictOutcome.reject)
        event = _announce(
            state,
            RunPhase.approval,
            f"approval by {decision.approver}: {approved} approved, "
            f"{rejected} rejected",
            data={
                "approver": decision.approver,
                "approved": approved,
                "rejected": rejected,
            },
        )
        status_for = {
            v.hypothesis_id: _STATUS_AFTER_VERDICT[v.outcome] for v in decided
        }
        return {
            "phase": RunPhase.approval,
            "approval": decision,
            "pending_approval_ids": [],
            "hypotheses": _with_statuses(state["hypotheses"], status_for),
            "events": [event],
        }

    def combine(state: EngineState) -> NodeDelta:
        kept = [
            verdict
            for verdict in decided_verdicts(state["verdicts"], state["approval"])
            if verdict.outcome is VerdictOutcome.keep
        ]
        if ctx.combiner is None:
            event = _announce(
                state,
                RunPhase.combine,
                f"combined {len(kept)} kept change(s) "
                "(re-testing the combination is Step 2)",
                data={"kept": len(kept)},
            )
            return {
                "phase": RunPhase.combine,
                "kept_verdict_ids": [verdict.id for verdict in kept],
                "events": [event],
            }
        if not kept:
            event = _announce(
                state,
                RunPhase.combine,
                "nothing kept: nothing to combine",
                data={"kept": 0},
            )
            return {
                "phase": RunPhase.combine,
                "kept_verdict_ids": [],
                "events": [event],
            }
        measured = _require_baseline(state)
        target = CombineTarget(
            run_id=state["run_id"],
            project=state["project"],
            base_commit=_require_commit(state, "combine"),
            workloads=tuple(state["workloads"]),
            branch=f"{ctx.branch_prefix}run-{state['run_id']}",
            round=max(1, state["round"]),
            quality_files=measured.quality_files,
        )
        changes = kept_changes(
            kept,
            {trial.id: trial for trial in state["trials"]},
            _by_id(state["hypotheses"]),
        )
        outcome = combine_kept(
            ctx.combiner, changes, _combine_rules(ctx, measured), target
        )
        combination = outcome.combination
        event = _announce(
            state,
            RunPhase.combine,
            f"combination {'held' if combination.holds else 'did not hold'}: "
            f"delivering {len(outcome.kept_verdict_ids)} of {len(changes)} kept "
            "change(s)",
            level=EventLevel.info if combination.holds else EventLevel.warning,
            data={
                "kept": len(changes),
                "applied": len(combination.applied_trial_ids),
                "skipped": len(combination.skipped),
                "holds": combination.holds,
                "fallback": combination.fallback_trial_id is not None,
                "delivered": len(outcome.kept_verdict_ids),
            },
        )
        return {
            "phase": RunPhase.combine,
            "kept_verdict_ids": list(outcome.kept_verdict_ids),
            "combination": combination,
            "events": [event],
        }

    def deliver(state: EngineState) -> NodeDelta:
        project = state["project"]
        kept = tuple(state["kept_verdict_ids"])
        report = _report(state, ctx.branch_prefix)
        data: ScalarDict = {"kind": DeliveryKind.report_only.value, "kept": len(kept)}
        if not kept:
            delivery = Delivery(
                project_id=project.id,
                kind=DeliveryKind.report_only,
                report_markdown=report,
            )
            message = "nothing kept: delivering the report only"
        else:
            branch = f"{ctx.branch_prefix}run-{state['run_id']}"
            assert_safe_branch(branch, project, ctx.branch_prefix)
            commit: str | None = None
            if ctx.publisher is None:
                trials_by_id = {trial.id: trial for trial in state["trials"]}
                verdicts_by_id = {v.id: v for v in state["verdicts"]}
                combined_diff = "\n".join(
                    trials_by_id[verdicts_by_id[verdict_id].trial_id].diff
                    for verdict_id in kept
                    if verdict_id in verdicts_by_id
                    and verdicts_by_id[verdict_id].trial_id in trials_by_id
                )
            else:
                commit, base = _publishable(state)
                combined_diff = ctx.publisher.publish(
                    project, branch, tip=commit, base=base
                )
            delivery = Delivery(
                project_id=project.id,
                kind=DeliveryKind.branch,
                branch=branch,
                commit=commit,
                verdict_ids=kept,
                combined_diff=combined_diff,
                report_markdown=report,
            )
            data = {
                "kind": DeliveryKind.branch.value,
                "kept": len(kept),
                "branch": branch,
            }
            if commit is not None:
                data["commit"] = commit
            message = f"delivering {len(kept)} change(s) on branch {branch}"
        event = _announce(state, RunPhase.deliver, message, data=data)
        return {"phase": RunPhase.deliver, "delivery": delivery, "events": [event]}

    def learn(state: EngineState) -> NodeDelta:
        known = _by_id(state["hypotheses"])
        decided = decided_verdicts(state["verdicts"], state["approval"])
        context = tuple(sorted({tag for hs in state["hotspots"] for tag in hs.tags}))
        lessons = lessons_from_verdicts(
            decided, known, project_id=state["project"].id, context=context
        )
        for lesson in lessons:
            ctx.repository.save_lesson(lesson)
        events = [
            _announce(
                state,
                RunPhase.learn,
                f"learned {len(lessons)} lesson(s)",
                data={"lessons": len(lessons)},
            )
        ]
        unknown = [v.hypothesis_id for v in decided if v.hypothesis_id not in known]
        if unknown:
            events.append(
                _announce(
                    state,
                    RunPhase.learn,
                    f"skipped {len(unknown)} verdict(s) whose hypothesis is unknown: "
                    + ", ".join(unknown),
                    level=EventLevel.warning,
                    data={"skipped": len(unknown)},
                )
            )
        return {"phase": RunPhase.learn, "lessons": list(lessons), "events": events}

    def watch(state: EngineState) -> NodeDelta:
        event = _announce(
            state, RunPhase.watch, "watching for new papers and code changes (stub)"
        )
        return {"phase": RunPhase.done, "events": [event]}

    nodes: dict[str, NodeFn] = {
        "connect": connect,
        "understand": understand,
        "define": define,
        "baseline": baseline,
        "profile": profile,
        "research": research,
        "hypotheses": hypotheses,
        "trials": trials,
        "judges": judges,
        "verdicts": verdicts,
        "approval_gate": approval_gate,
        "combine": combine,
        "deliver": deliver,
        "learn": learn,
        "watch": watch,
    }
    return nodes


def make_router(ctx: NodeContext) -> RouterFn:
    """Return ``after_verdicts``: the conditional edge out of ``verdicts``."""

    def after_verdicts(state: EngineState) -> Route:
        if state["pending_approval_ids"]:
            return "approval_gate"
        if state["budget_exhausted"]:
            return "combine"
        if any(v.outcome is VerdictOutcome.keep for v in state["verdicts"]):
            return "combine"
        if state["round"] >= state["max_rounds"]:
            return "combine"
        candidates, pool = _untried(ctx, state)  # a review verdict never routes
        if candidates or pool or _live_generator(ctx, state, priced=True) is not None:
            return "hypotheses"
        return "combine"

    return after_verdicts
