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

Step 1 keeps ``understand``, ``profile``, ``research`` and ``watch`` as
deterministic stubs fed from the context; ``hypotheses`` (ranking),
``trials`` (runner injection), ``judges``, ``verdicts``, ``approval_gate``
(``interrupt()``), ``combine``, ``deliver`` and ``learn`` are final.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from langgraph.types import interrupt
from pydantic import ValidationError

from autonomous_ai_agents.common.config import settings
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
from autonomous_ai_agents.optimization.ranking import rank_hypotheses
from autonomous_ai_agents.orchestrator.events import emit, make_event
from autonomous_ai_agents.orchestrator.state import EngineState
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


class EngineError(Exception):
    """A run cannot continue: the state or the measurements are not trustworthy."""


class DeliveryError(EngineError):
    """The delivery would be unsafe (for example onto the default branch)."""


@dataclass(frozen=True)
class NodeContext:
    """Everything the nodes need that must not live in the checkpointed state.

    ``candidates``, ``hotspots`` and ``techniques`` stand in for the research
    and profiler output until Steps 2 and 3 produce them; the rigour knobs
    default to the settings.
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
    noise_multiplier: float = settings.NOISE_MULTIPLIER
    branch_prefix: str = settings.TRIAL_BRANCH_PREFIX
    max_hypotheses_per_round: int = 3


# ---------------------------------------------------------------------------
# Helpers shared by the nodes
# ---------------------------------------------------------------------------


_STATUS_AFTER_VERDICT: dict[VerdictOutcome, HypothesisStatus] = {
    VerdictOutcome.keep: HypothesisStatus.kept,
    VerdictOutcome.reject: HypothesisStatus.rejected,
    VerdictOutcome.inconclusive: HypothesisStatus.inconclusive,
    VerdictOutcome.needs_approval: HypothesisStatus.trialled,
}


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


def _objective_metrics(objectives: Iterable[Objective]) -> frozenset[str]:
    return frozenset(objective.metric for objective in objectives)


def _run_count_violations(
    measurements: Iterable[Measurement],
    objective_metrics: frozenset[str],
    min_runs: int,
) -> tuple[Violation, ...]:
    """Run-count violations on objective metrics only.

    ``tests_passed`` is a single flag by design and guardrail metrics are
    bounded, not proven, so neither needs ``min_runs`` runs.
    """
    found = (
        check_run_count(measurement.stats, min_runs)
        for measurement in measurements
        if measurement.metric in objective_metrics
    )
    return tuple(violation for violation in found if violation is not None)


@dataclass(frozen=True)
class _PrimarySummary:
    """The primary metric's baseline figures for events and the report."""

    metric: str | None
    n: int
    mean: float | None
    unit: str
    workloads: int

    def line(self) -> str:
        if self.mean is None:
            return f"Baseline: no measurement of {self.metric}"
        return (
            f"Baseline: {self.metric} mean {self.mean:.3f} {self.unit} "
            f"over {self.n} run(s) on {self.workloads} workload(s)"
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


def _apply_approval(
    verdicts: Iterable[Verdict], approval: ApprovalDecision | None
) -> list[Verdict]:
    """Rewrite ``needs_approval`` verdicts with the human's decision.

    Approved ones become ``keep`` (with the approver), rejected ones become
    ``reject``; undecided ones stay as they are. Other outcomes are never
    touched: the gate only ever offered ``needs_approval`` verdicts.
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
                    }
                )
            )
        elif verdict.id in rejected:
            decided.append(
                verdict.model_copy(
                    update={
                        "outcome": VerdictOutcome.reject,
                        "approval_note": approval.note,
                    }
                )
            )
        else:
            decided.append(verdict)
    return decided


def assert_safe_branch(branch: str, project: Project, prefix: str) -> None:
    """Refuse a delivery branch that is the default branch or outside ``prefix``."""
    if branch == project.default_branch:
        raise DeliveryError(
            f"refusing to deliver onto the default branch {branch!r} of {project.name}"
        )
    if not branch.startswith(prefix):
        raise DeliveryError(
            f"delivery branch {branch!r} is outside the engine prefix {prefix!r}"
        )


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _report(state: EngineState) -> str:
    """A small markdown report: title, baseline, one row per verdict, kept list."""
    project = state["project"]
    hypotheses = _by_id(state["hypotheses"])
    verdicts_by_id = {verdict.id: verdict for verdict in state["verdicts"]}
    baseline = state["baseline"]
    baseline_line = (
        "Baseline: not measured"
        if baseline is None
        else _summarize_primary(baseline.measurements, baseline.objectives).line()
    )
    lines = [
        f"# Engine run {state['run_id'][:8]}: {project.name}",
        "",
        baseline_line,
        "",
        "| Hypothesis | Outcome | Gain | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for verdict in state["verdicts"]:
        gain = "n/a" if verdict.gain is None else f"{verdict.gain:+.1%}"
        lines.append(
            f"| {_cell(_title_for(hypotheses, verdict))} | {verdict.outcome.value} "
            f"| {gain} | {_cell(verdict.summary)} |"
        )
    kept = [
        _title_for(hypotheses, verdicts_by_id[verdict_id])
        for verdict_id in state["kept_verdict_ids"]
        if verdict_id in verdicts_by_id
    ]
    lines += ["", "Kept: " + (", ".join(kept) if kept else "nothing"), ""]
    return "\n".join(lines)


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
                description="minimize wall time",
            )
        ]
        metrics = ", ".join(objective.metric for objective in objectives)
        kinds = ", ".join(guardrail.kind.value for guardrail in state["guardrails"])
        event = _announce(
            state,
            RunPhase.define,
            f"objectives: {metrics}; guardrails: {kinds or 'none'}",
            data={
                "objectives": metrics,
                "guardrails": kinds,
                "min_runs": ctx.min_runs,
                "noise_multiplier": ctx.noise_multiplier,
            },
        )
        return {"phase": RunPhase.define, "objectives": objectives, "events": [event]}

    def baseline(state: EngineState) -> NodeDelta:
        measurements = ctx.baseline_runner.measure(state["workloads"])
        objectives = tuple(state["objectives"])
        violations = _run_count_violations(
            measurements, _objective_metrics(objectives), ctx.min_runs
        )
        if violations:
            raise EngineError(
                "baseline is not trustworthy: "
                + "; ".join(violation.message for violation in violations)
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
        trialled = {trial.hypothesis_id for trial in state["trials"]}
        candidates = [h for h in ctx.candidates if h.id not in trialled]
        lessons = ctx.repository.list_lessons(state["project"].id)
        ranked = rank_hypotheses(candidates, lessons)[: ctx.max_hypotheses_per_round]
        # Earlier rounds' hypotheses stay (with their statuses) so the report
        # and the lessons see every idea the run tried; only this round's
        # ranked ones are ``proposed``.
        carried = [
            h for h in state["hypotheses"] if h.status is not HypothesisStatus.proposed
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
            "hypotheses": [*carried, *ranked],
            "events": [event],
        }

    def trials(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        run_id = state["run_id"]
        new_trials: list[Trial] = []
        for hypothesis in state["hypotheses"]:
            if hypothesis.status is not HypothesisStatus.proposed:
                continue
            branch = f"{ctx.branch_prefix}{run_id[:8]}/{hypothesis.id[:8]}"
            trial = ctx.runner.run(
                hypothesis,
                state["workloads"],
                measured,
                round=state["round"],
                branch=branch,
            )
            ctx.repository.save_trial(run_id, trial)
            new_trials.append(trial)
        ran = {trial.hypothesis_id for trial in new_trials}
        cost_usd = state["cost_usd"] + sum(trial.cost_usd for trial in new_trials)
        tokens_used = state["tokens_used"] + sum(t.tokens_used for t in new_trials)
        failed = sum(1 for t in new_trials if t.status is TrialStatus.failed)
        event = _announce(
            state,
            RunPhase.trials,
            f"round {state['round']}: ran {len(new_trials)} trial(s), {failed} failed",
            data={
                "round": state["round"],
                "trials": len(new_trials),
                "failed": failed,
                "cost_usd": cost_usd,
                "tokens_used": tokens_used,
            },
        )
        return {
            "phase": RunPhase.trials,
            "trials": new_trials,
            "hypotheses": [
                h.model_copy(update={"status": HypothesisStatus.trialled})
                if h.id in ran
                else h
                for h in state["hypotheses"]
            ],
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
        current = [t for t in state["trials"] if t.round == state["round"]]
        # The trials channel is append-only, so the judged copy lives in the
        # repository (and later on the verdict), not in the state.
        for trial in current:
            results = tuple(judge.evaluate(measured, trial) for judge in active)
            ctx.repository.save_trial(
                state["run_id"], trial.model_copy(update={"judge_results": results})
            )
        event = _announce(
            state,
            RunPhase.judges,
            f"round {state['round']}: judged {len(current)} trial(s) "
            f"with {len(active)} judge(s)",
            data={
                "round": state["round"],
                "trials": len(current),
                "judges": ", ".join(judge.name for judge in active),
            },
        )
        return {"phase": RunPhase.judges, "events": [event]}

    def verdicts(state: EngineState) -> NodeDelta:
        measured = _require_baseline(state)
        run_id = state["run_id"]
        known = _by_id(state["hypotheses"])
        objective_metrics = _objective_metrics(measured.objectives)
        primary = primary_metric(measured.objectives)
        new_verdicts: list[Verdict] = []
        for trial in ctx.repository.list_trials(run_id):
            if trial.round != state["round"]:
                continue
            hypothesis = known.get(trial.hypothesis_id)
            if hypothesis is None:
                raise EngineError(
                    f"trial {trial.id} refers to unknown hypothesis {trial.hypothesis_id}"
                )
            violations = (
                *check_diff_all(trial.touched_paths, ctx.protected_patterns),
                *_run_count_violations(
                    trial.measurements, objective_metrics, ctx.min_runs
                ),
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
            "hypotheses": [
                h.model_copy(update={"status": status_for[h.id]})
                if h.id in status_for
                else h
                for h in state["hypotheses"]
            ],
            "pending_approval_ids": [
                v.id for v in new_verdicts if v.outcome is VerdictOutcome.needs_approval
            ],
            "events": [event],
        }

    def approval_gate(state: EngineState) -> NodeDelta:
        # Everything before interrupt() runs again on resume, so the request
        # is built from state only and nothing is written until the decision
        # is in hand.
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
        raw = interrupt(request.model_dump(mode="json"))
        try:
            decision = ApprovalDecision.model_validate(raw)
        except ValidationError as exc:
            raise EngineError(f"invalid approval decision: {exc}") from exc
        pending_ids = {verdict.id for verdict in pending}
        approved = set(decision.approved_verdict_ids) & pending_ids
        rejected = set(decision.rejected_verdict_ids) & pending_ids
        for verdict in pending:
            if verdict.id in approved:
                ctx.repository.save_verdict(
                    run_id,
                    verdict.model_copy(
                        update={
                            "approved_by": decision.approver,
                            "approval_note": decision.note,
                        }
                    ),
                )
        event = _announce(
            state,
            RunPhase.approval,
            f"approval by {decision.approver}: {len(approved)} approved, "
            f"{len(rejected)} rejected",
            data={
                "approver": decision.approver,
                "approved": len(approved),
                "rejected": len(rejected),
            },
        )
        return {
            "phase": RunPhase.approval,
            "approval": decision,
            "pending_approval_ids": [],
            "events": [event],
        }

    def combine(state: EngineState) -> NodeDelta:
        verdicts_by_id = {v.id: v for v in state["verdicts"]}
        kept = [v.id for v in state["verdicts"] if v.outcome is VerdictOutcome.keep]
        approval = state["approval"]
        approved_ids = () if approval is None else approval.approved_verdict_ids
        for verdict_id in approved_ids:
            verdict = verdicts_by_id.get(verdict_id)
            if (
                verdict is not None
                and verdict.outcome is VerdictOutcome.needs_approval
                and verdict_id not in kept
            ):
                kept.append(verdict_id)
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
            branch = f"{ctx.branch_prefix}{state['run_id'][:8]}"
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
        decided = _apply_approval(state["verdicts"], state["approval"])
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
