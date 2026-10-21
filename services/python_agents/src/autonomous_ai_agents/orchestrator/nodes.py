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

Step 1 keeps ``understand``, ``profile``, ``research`` and ``watch`` as
deterministic stubs fed from the context; ``hypotheses`` (ranking),
``trials`` (runner injection), ``judges``, ``verdicts``, ``approval_gate``
(``interrupt()``), ``combine``, ``deliver`` and ``learn`` are final.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from langgraph.types import interrupt
from pydantic import ValidationError

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import DeliveryError as DeliveryError
from autonomous_ai_agents.common.errors import EngineError as EngineError
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    ApprovalItem,
    ApprovalRequest,
    Baseline,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    EventLevel,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisStatus,
    Measurement,
    Objective,
    ObjectiveKind,
    Paper,
    Project,
    RunPhase,
    ScalarDict,
    Technique,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.common.refnames import refname_problem
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
from autonomous_ai_agents.optimization.ranking import rank_hypotheses
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

    Construction refuses duplicate or refname-unsafe candidate ids (each id
    names a trial branch) and knobs below 1, with ``ValueError``.
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


# ---------------------------------------------------------------------------
# Helpers shared by the nodes
# ---------------------------------------------------------------------------


_STATUS_AFTER_VERDICT: dict[VerdictOutcome, HypothesisStatus] = {
    VerdictOutcome.keep: HypothesisStatus.kept,
    VerdictOutcome.reject: HypothesisStatus.rejected,
    VerdictOutcome.inconclusive: HypothesisStatus.inconclusive,
    VerdictOutcome.needs_approval: HypothesisStatus.trialled,
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


def _require_baseline(state: EngineState) -> Baseline:
    baseline = state["baseline"]
    if baseline is None:
        raise EngineError("no baseline measured yet: the baseline node must run first")
    return baseline


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
    trial: Trial, hypothesis: Hypothesis, round_number: int
) -> list[str]:
    """Why a runner's Trial cannot be trusted as this hypothesis's round trial."""
    problems: list[str] = []
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


def assert_safe_branch(branch: str, project: Project, prefix: str) -> None:
    """Refuse a branch the engine must not create or deliver onto.

    ``prefix`` must be non-empty and end with ``/``; ``branch`` must not be
    the project's default branch, must start with ``prefix`` and must be a
    valid git refname: ``/``-separated segments matching
    ``[A-Za-z0-9][A-Za-z0-9._-]*``, none empty, none containing ``..`` or
    ending with ``.lock``, no ``@{`` and no trailing ``.``. Raises
    ``DeliveryError``.
    """
    if not prefix.endswith("/"):
        raise DeliveryError(
            f"engine branch prefix {prefix!r} must be non-empty and end with '/'"
        )
    if branch == project.default_branch:
        raise DeliveryError(
            f"refusing to touch the default branch {branch!r} of {project.name}"
        )
    if not branch.startswith(prefix):
        raise DeliveryError(
            f"branch {branch!r} is outside the engine prefix {prefix!r}"
        )
    problem = refname_problem(branch)
    if problem is not None:
        raise DeliveryError(f"branch {branch!r} is not a safe git refname: {problem}")


_CELL_LIMIT = 200
"""Longest report cell, in characters, ellipsis included."""

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


def _cell(text: str) -> str:
    """Make untrusted text (titles, trial errors) inert inside one table cell.

    Line breaks collapse to one space (no new rows, headings or blocks), the
    text is cut to ``_CELL_LIMIT`` characters with an ellipsis, then
    backslashes, pipes, backticks, brackets, colons and ``@`` get markdown
    escapes, ``www.`` becomes ``www\\.`` and ``&``, ``<`` and ``>`` become
    HTML entities (no cell breaks, code spans, links, GFM autolinks or raw
    HTML). The backslash is escaped first so an input ``\\|`` cannot turn the
    pipe escape into a literal backslash plus a cell break.
    """
    flat = _LINE_BREAKS.sub(" ", text)
    if len(flat) > _CELL_LIMIT:
        flat = flat[: _CELL_LIMIT - 1] + "…"
    return _WWW_AUTOLINK.sub("www\\.", flat.translate(_CELL_ESCAPES))


def _report(state: EngineState) -> str:
    """A small markdown report: title, baseline, one row per decided verdict, kept."""
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


# ---------------------------------------------------------------------------
# The nodes
# ---------------------------------------------------------------------------


def make_nodes(ctx: NodeContext) -> dict[str, NodeFn]:
    """Return the engine's node functions, keyed by name in graph order."""

    def connect(state: EngineState) -> NodeDelta:
        project = state["project"]
        event = _announce(
            state,
            RunPhase.connect,
            f"connected {project.name}",
            data={"workloads": len(state["workloads"])},
        )
        return {"phase": RunPhase.connect, "events": [event]}

    def understand(state: EngineState) -> NodeDelta:
        event = _announce(
            state,
            RunPhase.understand,
            f"understanding {state['project'].name} (stub: no LLM call in Step 1)",
        )
        return {"phase": RunPhase.understand, "events": [event]}

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
        metrics = ", ".join(objective.metric for objective in objectives)
        kinds = ", ".join(guardrail.kind.value for guardrail in state["guardrails"])
        event = _announce(
            state,
            RunPhase.define,
            f"objectives: {metrics}; guardrails: {kinds or 'none'}",
            data={"objectives": metrics, "guardrails": kinds, "min_runs": ctx.min_runs},
        )
        return {"phase": RunPhase.define, "objectives": objectives, "events": [event]}

    def baseline(state: EngineState) -> NodeDelta:
        measurements = ctx.baseline_runner.measure(state["workloads"])
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
        measured = Baseline(
            measurements=measurements,
            objectives=objectives,
            guardrails=tuple(state["guardrails"]),
        )
        summary = _summarize_primary(measurements, objectives)
        event = _announce(
            state,
            RunPhase.baseline,
            summary.line(),
            data={
                "metric": summary.metric,
                "n": summary.n,
                "mean": summary.mean,
                "workloads": summary.workloads,
            },
        )
        return {"phase": RunPhase.baseline, "baseline": measured, "events": [event]}

    def profile(state: EngineState) -> NodeDelta:
        hotspots = list(ctx.hotspots)
        event = _announce(
            state,
            RunPhase.profile,
            f"profiled {len(hotspots)} hotspot(s) (stub)",
            data={"hotspots": len(hotspots)},
        )
        return {"phase": RunPhase.profile, "hotspots": hotspots, "events": [event]}

    def research(state: EngineState) -> NodeDelta:
        techniques = list(ctx.techniques)
        papers: list[Paper] = []
        event = _announce(
            state,
            RunPhase.research,
            f"research: {len(techniques)} technique(s), {len(papers)} paper(s) (stub)",
            data={"techniques": len(techniques), "papers": len(papers)},
        )
        return {
            "phase": RunPhase.research,
            "techniques": techniques,
            "papers": papers,
            "events": [event],
        }

    def hypotheses(state: EngineState) -> NodeDelta:
        round_number = state["round"] + 1
        # A candidate is new when no trial ran it and no earlier round holds
        # it; earlier rounds' hypotheses stay (with their statuses) so the
        # report and the lessons see every idea the run tried.
        seen = {trial.hypothesis_id for trial in state["trials"]} | {
            hypothesis.id for hypothesis in state["hypotheses"]
        }
        candidates = [h for h in ctx.candidates if h.id not in seen]
        lessons = ctx.repository.list_lessons(state["project"].id)
        ranked = [
            h.model_copy(update={"status": HypothesisStatus.proposed})
            for h in rank_hypotheses(candidates, lessons)[
                : ctx.max_hypotheses_per_round
            ]
        ]
        event = _announce(
            state,
            RunPhase.hypotheses,
            f"round {round_number}: ranked {len(ranked)} of {len(candidates)} candidates",
            data={
                "round": round_number,
                "ranked": len(ranked),
                "candidates": len(candidates),
            },
        )
        return {
            "phase": RunPhase.hypotheses,
            "round": round_number,
            "hypotheses": [*state["hypotheses"], *ranked],
            "events": [event],
        }

    def trials(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        run_id = state["run_id"]
        round_number = state["round"]
        new_trials: list[Trial] = []
        for hypothesis in state["hypotheses"]:
            if hypothesis.status is not HypothesisStatus.proposed:
                continue
            branch = f"{ctx.branch_prefix}trial-{run_id}-{hypothesis.id}"
            assert_safe_branch(branch, state["project"], ctx.branch_prefix)
            trial = ctx.runner.run(
                hypothesis,
                state["workloads"],
                measured,
                round=round_number,
                branch=branch,
            )
            problems = _runner_trial_problems(trial, hypothesis, round_number)
            if problems:
                raise EngineError(
                    f"runner returned an untrustworthy trial {trial.id} for "
                    f"hypothesis {hypothesis.id}: " + "; ".join(problems)
                )
            ctx.repository.save_trial(run_id, trial)
            new_trials.append(trial)
        ran = {trial.hypothesis_id: HypothesisStatus.trialled for trial in new_trials}
        cost_usd = state["cost_usd"] + sum(trial.cost_usd for trial in new_trials)
        tokens_used = state["tokens_used"] + sum(t.tokens_used for t in new_trials)
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
        return {
            "phase": RunPhase.trials,
            "round_trials": new_trials,
            "hypotheses": _with_statuses(state["hypotheses"], ran),
            "cost_usd": cost_usd,
            "tokens_used": tokens_used,
            "events": [event],
        }

    def judges(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        active = [
            judge
            for judge in ctx.judges
            if any(judge.applies_to(o) for o in measured.objectives)
        ]
        judged = [
            trial.model_copy(
                update={
                    "judge_results": tuple(
                        judge.evaluate(measured, trial) for judge in active
                    )
                }
            )
            for trial in state["round_trials"]
        ]
        for trial in judged:
            ctx.repository.save_trial(state["run_id"], trial)
        event = _announce(
            state,
            RunPhase.judges,
            f"round {state['round']}: judged {len(judged)} trial(s) "
            f"with {len(active)} judge(s)",
            data={
                "round": state["round"],
                "trials": len(judged),
                "judges": ", ".join(judge.name for judge in active),
            },
        )
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
        new_verdicts: list[Verdict] = []
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
            violations = (
                *check_diff_all(trial.touched_paths, ctx.protected_patterns),
                *completeness,
            )
            verdict = derive_verdict(
                trial,
                hypothesis,
                trial.judge_results,
                violations,
                primary_metric=primary,
            )
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
            "events": [event],
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
            verdict.id
            for verdict in decided_verdicts(state["verdicts"], state["approval"])
            if verdict.outcome is VerdictOutcome.keep
        ]
        event = _announce(
            state,
            RunPhase.combine,
            f"combined {len(kept)} kept change(s) "
            "(re-testing the combination is Step 2)",
            data={"kept": len(kept)},
        )
        return {"phase": RunPhase.combine, "kept_verdict_ids": kept, "events": [event]}

    def deliver(state: EngineState) -> NodeDelta:
        project = state["project"]
        kept = tuple(state["kept_verdict_ids"])
        report = _report(state)
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
            trials_by_id = {trial.id: trial for trial in state["trials"]}
            verdicts_by_id = {verdict.id: verdict for verdict in state["verdicts"]}
            diffs = [
                trials_by_id[verdicts_by_id[verdict_id].trial_id].diff
                for verdict_id in kept
                if verdict_id in verdicts_by_id
                and verdicts_by_id[verdict_id].trial_id in trials_by_id
            ]
            delivery = Delivery(
                project_id=project.id,
                kind=DeliveryKind.branch,
                branch=branch,
                verdict_ids=kept,
                combined_diff="\n".join(diffs),
                report_markdown=report,
            )
            data = {
                "kind": DeliveryKind.branch.value,
                "kept": len(kept),
                "branch": branch,
            }
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
        if any(v.outcome is VerdictOutcome.keep for v in state["verdicts"]):
            return "combine"
        if state["round"] >= state["max_rounds"]:
            return "combine"
        trialled = {trial.hypothesis_id for trial in state["trials"]}
        if all(candidate.id in trialled for candidate in ctx.candidates):
            return "combine"
        return "hypotheses"

    return after_verdicts
