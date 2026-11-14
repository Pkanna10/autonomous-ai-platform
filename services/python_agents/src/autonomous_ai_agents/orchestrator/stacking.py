"""The stacked tail and graph pieces (X2-DT U5b, O63; dt-design section 1,
"Graph" and "``stacked_combine``").

With ``STACKED_ROUNDS`` on, ``main.create_graph`` builds its nodes through
``stacked_nodes`` (``restack`` added before every further round, ``combine``
replaced by ``stacked_combine``) and routes through ``stacked_router``.
Nothing here runs with stacking off.

``stacked_combine`` (the tail) runs where today's combine runs:

1. the last round's combine on the round base (``stack_round.combine_round``,
   the same as ``restack``'s), appended to the ledger with ``with_round``
   after the ledger's chain is checked (the round base is its current base,
   the ledger not closed yet). The last round's held tip is not adopted, so
   its record names no ``tip_commit`` (it carries no "refused"): the tip is
   in its ``combination``;
2. the last tip: this round's held tip, else the current base when a round
   moved it, else none;
3. when the round base is the origin, that round combine already is today's
   re-test from the origin: it is the delivery, and no squash runs (``squash``
   refuses ``base == tip``);
4. otherwise the cumulative ``origin..tip`` diff's paths go through the
   protected-path rules (``check_diff_all``; ``changed_paths`` fails closed
   on a diff it cannot read), a violation failing the run. A tip whose tree
   is the origin's (no changed path; U2: its squash would be an empty
   commit, which the FIXED combiner skips as "nothing left to apply") is not
   squashed or re-tested: nothing is delivered. Else the tip is squashed onto
   the origin and that one change (``STACKED_TIP``) is re-tested from the
   origin through the FIXED ``combine_kept`` against the origin baseline's
   rules: today's ABAB, the suite against the origin's count, the frozen
   judges against the origin's A rows. Its result is the ledger's
   ``delivery``; ``state["combination"]`` is that result with the applied
   and skipped trials of the delivered rounds (every adopted round and a
   held last round) when the re-test applied the squash, none when it did
   not, and no fallback (one change has none worth naming: a fallback can
   only have re-tried the squash itself). ``holds``, the tip and the judge
   results stay the re-test's. ``kept_verdict_ids`` are the run-set
   verdicts of those trials when it held, else none: there is no fallback
   to an earlier tip (a second chance);
5. ``ledger.closed`` records the delivery and its wall seconds and sets
   ``all_rounds_held``;
6. the review set: only review verdicts whose trial started at the origin
   are combined, from the origin, on the review branch (``accept`` widened
   to ``CONFIRMABLE``, as today); every other one gets a
   ``stack_review_skipped`` note (its diff is against a tip);
7. the delta restores ``base_commit`` and ``baseline`` to the origin's, so
   ``deliver`` and ``learn`` run unchanged.

Every delivery ends in one ``stack_delivery`` event (``retest`` says whether
a squash was re-tested). A near-miss pair still waiting on the round base
when the tail runs (``_next_compound``) is recorded as one
``stack_compound_skipped`` event, so the compounds stacking gives up are
counted.

``stacked_router`` wraps ``after_verdicts`` (dt-design section 6, U4
review): the router checks near-miss compounds on the base before
``restack``, but the hypotheses node checks them after it, where a moved
base drops parents on the old one. So when a compound is the only reason to
go on and the round base has keeps to offer (``restack`` would combine them
and, if that holds, move the base), it routes to ``combine``. Decision:
route on "the base can move" rather than "the base will move". Why: whether
it moves is the round combine's result, known only by running it, and the
tail runs that same combine; a round that adopts a tip and then runs no
trial costs a baseline, a calibration and a profile for nothing. The price
is a compound that a combine which would not have held could have tried.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Final, Literal

from autonomous_ai_agents.clients.structured import shown
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    Baseline,
    Combination,
    EngineEvent,
    EventLevel,
    RoundBase,
    RunPhase,
    ScalarDict,
    StackLedger,
    Verdict,
)
from autonomous_ai_agents.execution.protocols import Combiner, KeptChange, Stacker
from autonomous_ai_agents.optimization.anticheat import check_diff_all
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineTarget,
    combine_kept,
    kept_changes,
)
from autonomous_ai_agents.orchestrator.confirm import CONFIRMABLE
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    NodeFn,
    Route,
    RouterFn,
    _announce,
    _by_id,
    _capped,
    _combine_rules,
    _combiner_notes,
    _deliverable,
    _delivery_sets,
    _live_generator,
    _next_compound,
    _note,
    _require_baseline,
    _require_commit,
    _untried,
    make_router,
)
from autonomous_ai_agents.orchestrator.stack_round import (
    Clock,
    RoundCombine,
    StepTimer,
    _notes_events,
    _require_stacking,
    combine_round,
    offered_keeps,
    restack,
)
from autonomous_ai_agents.orchestrator.state import EngineState

STACK_NODE: Final = "restack"
"""The node between stacked rounds (a node name may not be a state key)."""

STACKED_TIP: Final = "stacked-tip"
"""The trial, hypothesis and verdict id of the squashed tip's ``KeptChange``."""


def stacked_nodes(ctx: NodeContext, nodes: Mapping[str, NodeFn]) -> dict[str, NodeFn]:
    """``nodes`` (``make_nodes(ctx)``) with ``combine`` replaced by
    ``stacked_combine`` and ``restack`` added last; ``ValueError`` for a
    context that does not stack."""
    if not ctx.stack_rounds:
        raise ValueError("stacked_nodes needs a context with stack_rounds on")

    def restack_node(state: EngineState) -> NodeDelta:
        return restack(ctx, state)

    def combine(state: EngineState) -> NodeDelta:
        return stacked_combine(ctx, state)

    return {**nodes, "combine": combine, STACK_NODE: restack_node}


def stacked_router(ctx: NodeContext) -> RouterFn:
    """``after_verdicts`` for stacked rounds (module docstring)."""
    route = make_router(ctx)

    def after_verdicts(state: EngineState) -> Route:
        target = route(state)
        if (
            target == "hypotheses"
            and _only_a_compound(ctx, state)
            and offered_keeps(state)
        ):
            return "combine"
        return target

    return after_verdicts


def _only_a_compound(ctx: NodeContext, state: EngineState) -> bool:
    """With the router going on: no candidate, pooled idea or generator
    call is left, so a near-miss pair is its only reason."""
    candidates, pool = _untried(ctx, state)
    return not (
        candidates or pool or _live_generator(ctx, state, priced=True) is not None
    )


def _open_ledger(state: EngineState, base: str) -> StackLedger:
    """The run's ledger (a fresh one at ``base`` when no round restacked),
    on ``base`` and not closed, else ``EngineError``."""
    ledger = state.get("stack")
    if ledger is None:
        return StackLedger(origin_commit=base, origin_baseline=_require_baseline(state))
    if ledger.delivery is not None or ledger.all_rounds_held is not None:
        raise EngineError("the stack ledger is already closed: its delivery ran")
    if ledger.current_base != base:
        raise EngineError(
            f"the round base {base} is not the stack ledger's current base "
            f"{ledger.current_base}"
        )
    return ledger


def _last_round(state: EngineState, combined: RoundCombine) -> RoundBase:
    return RoundBase.model_validate(
        {
            "round": max(1, state["round"]),
            "base_commit": combined.base_commit,
            "offered_trial_ids": combined.offered_trial_ids,
            "combination": combined.combination,
            "reason": combined.reason,
            "seconds": dict(combined.seconds),
        }
    )


def _round_event(state: EngineState, record: RoundBase) -> EngineEvent:
    """``stack_round`` for the last round, in ``restack``'s shape."""
    combination = record.combination
    data: ScalarDict = {
        "round": record.round,
        "base": record.base_commit,
        "offered": len(record.offered_trial_ids),
        "applied": 0 if combination is None else len(combination.applied_trial_ids),
        "holds": None if combination is None else combination.holds,
        "adopted": False,
        "tip": None if combination is None else combination.tip_commit,
        "reason": record.reason,
        "last": True,
    }
    calm = combination is None or combination.holds
    return _note(
        state,
        RunPhase.combine,
        "stack_round",
        f"round {record.round} on {record.base_commit[:12]} (the last): "
        f"{record.reason}",
        level=EventLevel.info if calm else EventLevel.warning,
        data=data,
    )


def _compound_skipped(ctx: NodeContext, state: EngineState) -> list[EngineEvent]:
    """``stack_compound_skipped``: the near-miss pair on the round base that
    the run ends without compounding (``stacked_router``'s price, or a run
    out of rounds), so the plan's count of lost compounds is recorded; none
    without one (or with compounds off)."""
    pair = _next_compound(ctx, state)
    if pair is None:
        return []
    a, b = pair.first, pair.second
    return [
        _note(
            state,
            RunPhase.combine,
            "stack_compound_skipped",
            f"a near-miss pair was not compounded: {shown(a.hypothesis.title)} "
            f"and {shown(b.hypothesis.title)} (gain/floor {a.ratio:.2f} + "
            f"{b.ratio:.2f})",
            data={
                "parents": f"{a.trial.id},{b.trial.id}",
                "ratio": pair.ratio,
                "base": state["base_commit"],
            },
        )
    ]


def _delivered_ids(state: EngineState, applied: Sequence[str]) -> list[str]:
    """The run-set verdict of each applied trial, in order; ``EngineError``
    for one with none (the delivered ids are never guessed)."""
    by_trial: dict[str, Verdict] = {
        v.trial_id: v for v in _delivery_sets(_deliverable(state))[0]
    }
    missing = [trial_id for trial_id in applied if trial_id not in by_trial]
    if missing:
        raise EngineError(
            "the stacked delivery applied trial(s) with no kept verdict: "
            + ", ".join(missing)
        )
    return [by_trial[trial_id].id for trial_id in applied]


def _stated(raw: Combination, delivered: Sequence[Combination]) -> Combination:
    """``state["combination"]``: the delivery re-test with the delivered
    rounds' trials (module docstring, item 4)."""
    took = STACKED_TIP in raw.applied_trial_ids
    applied = tuple(t for c in delivered for t in c.applied_trial_ids) if took else ()
    return Combination(
        base_commit=raw.base_commit,
        tip_commit=raw.tip_commit,
        applied_trial_ids=applied,
        skipped=tuple(s for c in delivered for s in c.skipped) if took else (),
        judge_results=raw.judge_results,
        holds=raw.holds,
        summary=f"stacked tip of {len(delivered)} round(s), squashed onto the original "
        f"base and re-tested: {raw.summary}",
    )


def _delivery_event(
    state: EngineState,
    message: str,
    *,
    level: EventLevel = EventLevel.info,
    **data: str | int | float | bool | None,
) -> EngineEvent:
    return _note(state, RunPhase.combine, "stack_delivery", message, level=level,
                 data=dict(data))  # fmt: skip


def stacked_combine(
    ctx: NodeContext, state: EngineState, *, clock: Clock = time.perf_counter
) -> NodeDelta:
    """The stacked tail (module docstring)."""
    combiner, stacker = _require_stacking(ctx)
    base = _require_commit(state, "combine")
    ledger = _open_ledger(state, base)
    combined = combine_round(ctx, state, clock=clock)
    record = _last_round(state, combined)
    ledger = ledger.with_round(record)
    events = [*_notes_events(state, combined.notes), _round_event(state, record)]
    events.extend(_compound_skipped(ctx, state))
    origin, origin_baseline = ledger.origin_commit, ledger.origin_baseline
    combination = combined.combination
    held = combination is not None and combination.holds
    delta: NodeDelta = {"phase": RunPhase.combine, "kept_verdict_ids": []}
    if base == origin:  # the round combine is today's re-test from the origin
        if combined.outcome is not None:
            delta["kept_verdict_ids"] = list(combined.outcome.kept_verdict_ids)
        delta["combination"] = combination
        tip = None if combination is None else combination.tip_commit
        events.append(
            _delivery_event(
                state,
                "the last round ran on the original base: its combine is the "
                f"delivery ({combined.reason})",
                level=EventLevel.info
                if held or combination is None
                else EventLevel.warning,
                origin=origin,
                tip=tip,
                retest=False,
                holds=held,
            )
        )
        ledger = ledger.closed(None, None)
    else:
        held_tip = combination.tip_commit if held and combination is not None else None
        last_tip = base if held_tip is None else held_tip
        delivered = [
            r.combination
            for r in ledger.rounds
            if r.combination is not None
            and (r.adopted or (r is ledger.rounds[-1] and held))
        ]
        ledger = _deliver(
            ctx,
            state,
            combiner,
            stacker,
            ledger,
            last_tip,
            delivered,
            delta,
            events,
            clock,
        )
    _review(ctx, state, combiner, origin, origin_baseline, delta, events)
    return {
        **delta,
        "base_commit": origin,
        "baseline": origin_baseline,
        "stack": ledger,
        "events": events,
    }


def _deliver(
    ctx: NodeContext,
    state: EngineState,
    combiner: Combiner,
    stacker: Stacker,
    ledger: StackLedger,
    tip: str,
    delivered: Sequence[Combination],
    delta: NodeDelta,
    events: list[EngineEvent],
    clock: Clock,
) -> StackLedger:
    """Items 4-5: the tip checked, squashed and re-tested from the origin."""
    project, origin = state["project"], ledger.origin_commit
    paths = stacker.changed_paths(project, origin, tip)
    protected = (*ctx.protected_patterns, *state["extra_protected"])
    found = check_diff_all(paths, protected)
    if found:
        raise EngineError(
            f"refusing to deliver the stacked tip {tip}: its diff from the "
            "original base touches protected paths: "
            + _capped("; ".join(v.message for v in found))
        )
    if not paths:
        events.append(
            _delivery_event(
                state,
                f"the stacked tip {tip[:12]} changes nothing against the original "
                "base: nothing to deliver",
                level=EventLevel.warning,
                origin=origin,
                tip=tip,
                retest=False,
                holds=False,
            )
        )
        return ledger.closed(None, None)
    squash = stacker.squash(project, origin, tip, state["run_id"])
    change = KeptChange(trial_id=STACKED_TIP, hypothesis_id=STACKED_TIP,
                        verdict_id=STACKED_TIP, commit=squash, score=0.0, gain=None)  # fmt: skip
    target = CombineTarget(
        run_id=state["run_id"],
        project=project,
        base_commit=origin,
        workloads=tuple(state["workloads"]),
        branch=f"{ctx.branch_prefix}run-{state['run_id']}",
        round=max(1, state["round"]),
        quality_files=ledger.origin_baseline.quality_files,
    )
    rules = _combine_rules(ctx, ledger.origin_baseline)
    timer = StepTimer(clock)
    outcome = timer.timed(
        "delivery", lambda: combine_kept(combiner, [change], rules, target)
    )
    raw = outcome.combination
    stated = _stated(raw, delivered)
    kept = _delivered_ids(state, stated.applied_trial_ids) if raw.holds else []
    delta["combination"], delta["kept_verdict_ids"] = stated, kept
    said = "held" if raw.holds else "did not hold"
    events.extend(_set_notes(state, ctx, "run"))
    events.append(
        _delivery_event(
            state,
            f"stacked tip {tip[:12]} squashed onto the original base as "
            f"{squash[:12]} and re-tested there: {said}; delivering "
            f"{len(kept)} change(s)",
            level=EventLevel.info if raw.holds else EventLevel.warning,
            origin=origin,
            tip=tip,
            squash=squash,
            retest=True,
            holds=raw.holds,
            rounds=len(delivered),
            applied=len(stated.applied_trial_ids),
            delivered=len(kept),
            seconds=timer.seconds["delivery"],
        )
    )
    return ledger.closed(raw, timer.seconds["delivery"])


def _set_notes(
    state: EngineState, ctx: NodeContext, kind: Literal["run", "review"]
) -> list[EngineEvent]:
    """The combiner's notes of its latest call, as the combine node writes
    them for ``kind``'s set; none without notes."""
    notes = _combiner_notes(ctx)
    if not notes:
        return []
    said = _capped("; ".join(notes))
    return [_note(state, RunPhase.combine, "combiner_notes", f"{kind} set: {said}",
                  data={"set": kind, "notes": said})]  # fmt: skip


def _review(
    ctx: NodeContext,
    state: EngineState,
    combiner: Combiner,
    origin: str,
    origin_baseline: Baseline,
    delta: NodeDelta,
    events: list[EngineEvent],
) -> None:
    """Item 6: the review set from the origin, the rest noted as skipped."""
    trials = {trial.id: trial for trial in state["trials"]}
    at_origin: list[Verdict] = []
    for verdict in _delivery_sets(_deliverable(state))[1]:
        trial = trials.get(verdict.trial_id)
        started = None if trial is None else trial.base_commit
        if started == origin:
            at_origin.append(verdict)
            continue
        events.append(
            _note(
                state,
                RunPhase.combine,
                "stack_review_skipped",
                f"review change {verdict.id[:8]} started from "
                f"{(started or 'no base')[:12]}, not the original base: not "
                "combined for review",
                level=EventLevel.warning,
                data={
                    "verdict": verdict.id,
                    "trial": verdict.trial_id,
                    "base": started,
                },
            )
        )
    if not at_origin:
        return
    branch = f"{ctx.branch_prefix}review-{state['run_id']}"
    target = CombineTarget(
        run_id=state["run_id"],
        project=state["project"],
        base_commit=origin,
        workloads=tuple(state["workloads"]),
        branch=branch,
        round=max(1, state["round"]),
        quality_files=origin_baseline.quality_files,
    )
    changes = kept_changes(at_origin, trials, _by_id(state["hypotheses"]))
    rules = replace(_combine_rules(ctx, origin_baseline), accept=CONFIRMABLE)
    outcome = combine_kept(combiner, changes, rules, target)
    combination = outcome.combination
    held = "held" if combination.holds else "did not hold"
    events.append(
        _announce(
            state,
            RunPhase.combine,
            f"review combination {held}: delivering "
            f"{len(outcome.kept_verdict_ids)} of {len(changes)} review "
            f"change(s) on {branch}",
            level=EventLevel.info if combination.holds else EventLevel.warning,
            data={
                "set": "review",
                "kept": len(changes),
                "applied": len(combination.applied_trial_ids),
                "skipped": len(combination.skipped),
                "holds": combination.holds,
                "fallback": combination.fallback_trial_id is not None,
                "delivered": len(outcome.kept_verdict_ids),
            },
        )
    )
    events.extend(_set_notes(state, ctx, "review"))
    delta["review_combination"] = combination
