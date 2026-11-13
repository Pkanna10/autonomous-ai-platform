"""The step between stacked rounds: ``restack`` (X2-DT U5a, O63; dt-design
section 1, "restack").

With ``STACKED_ROUNDS`` on, the graph runs ``restack`` before every round
after the first (U5b wires it; it is unreachable with stacking off). It:

1. offers the round combine every run-set keep whose trial started from the
   round base (``state["base_commit"]``), so keeps of an earlier round whose
   combine did not hold are offered again while the base is unchanged; a
   keep whose trial has no base cannot be placed: ``EngineError``;
2. combines them on the round base through the FIXED ``combine_kept``,
   judged against the round base's baseline (``nodes._combine_rules``);
   with nothing offered the round is "nothing kept" and no combiner runs;
3. if that combine held, tries to adopt its tip, the cheapest check first:

   - the old-base..tip diff (``Stacker.diff``), which the seeds' re-key
     needs. Decision: a diff that cannot be read refuses the adoption,
     rather than adopting with a drop for every key. Why: refusing leaves
     the run exactly where X2-D would be (base and keys unchanged, every
     record consistent), while adopting without the diff would throw away
     every seed anchor and need a hand-built drop record outside U3's
     ``rekey_events``, a second writer of that shape. Reading it first also
     means a failure costs no measurement. A ``GitError`` (git could not
     produce it) or a plain ``EngineError`` (the stacker refused an id)
     refuses; any other error, ``RepoTamperedError`` above all, propagates;
   - the unchanged baseline node on the state at the tip: it measures,
     checks trust and calibrates there. A plain ``EngineError`` refuses the
     adoption; a subclass (``RepoTamperedError``, ``GitError``,
     ``BudgetExceeded`` ...) stops the run, as it would anywhere;
   - the tip's outputs against the original base's
     (``anticheat.compare_fingerprints``, a pure call): any difference
     refuses;
   - the unchanged profile node at the tip;
   - exactly one re-key batch: ``rekey_events(current_keys(events), diff,
     old base, tip)``, never ``recorded_keys`` (it never sees a re-key);

4. returns a delta: ``stack``, the ledger with this round appended through
   ``StackLedger.with_round`` (started at the round base on the first
   round), and the events (``combiner_notes`` when the round combine's
   latest call left notes, set ``stack``, as the combine node writes them;
   ``stack_refused`` when a held tip was refused; on adoption the tip's
   baseline and profile events and the re-key batch; then ``stack_round``,
   one per round); on adoption also ``base_commit``, ``baseline`` and
   ``hotspots`` at the tip. A refused tip's baseline events stay out of the
   delta, so the state never shows a base that did not move, but the
   unchanged baseline node has already sent them to the live log
   (``_announce``): the live stream carries them, the state does not.

Timing proxies wrap the combiner, the baseline runner, the calibrator and
the profiler the nodes see, and fill ``RoundBase.seconds`` from an injected
clock (``time.perf_counter`` by default): the combiner's first call is
``combine``, a second (the fallback) ``fallback``. The baseline proxy
forwards ``quality_files`` and ``label_leaks``, so the baseline node reads
exactly what the runner reports, and the combiner proxy passes
``quality_files`` only when given, as ``combine_kept`` does. A proxy changes
no argument and no result: the requests are the unwrapped ones.

``offered_keeps`` and ``combine_round`` are the round combine alone, for the
tail's last round (U5b). Stacking also needs the run's stored baseline to
carry the exact output check (an ``output_equivalence`` guardrail): a run
defined with it off and resumed with a stacking context is refused before
any combine (U4 review), since its tip rounds would be judged on outputs the
frozen judge treats as not applicable.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final, TypeVar, cast

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    Baseline,
    Combination,
    EngineEvent,
    EventLevel,
    FrozenFile,
    GuardrailKind,
    Hotspot,
    Measurement,
    NoiseCalibration,
    Project,
    RoundBase,
    RunPhase,
    ScalarDict,
    StackLedger,
    Verdict,
    Workload,
)
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    Combiner,
    KeptChange,
    Profiler,
    ProfileResult,
    Stacker,
)
from autonomous_ai_agents.execution.runner import BaselineRunner
from autonomous_ai_agents.optimization.anticheat import compare_fingerprints
from autonomous_ai_agents.optimization.rekey import (
    DROP_EVENT,
    current_keys,
    rekey_events,
)
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineOutcome,
    CombineTarget,
    combine_kept,
    kept_changes,
)
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    NoiseCalibrator,
    _by_id,
    _capped,
    _combine_rules,
    _combiner_notes,
    _deliverable,
    _delivery_sets,
    _Freezing,
    _note,
    _require_baseline,
    _require_commit,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import EngineState

Clock = Callable[[], float]
"""A monotonic wall clock in seconds (``time.perf_counter``)."""

_T = TypeVar("_T")

HELD: Final = "held"
NOTHING_KEPT: Final = "nothing kept"
DID_NOT_HOLD: Final = "did not hold"
OUTPUTS_DIFFER: Final = "tip outputs differ from the original base"
BASELINE_FAILED: Final = "the tip's baseline failed"
NO_DIFF: Final = "the tip's diff could not be read"
"""A round's fates (``RoundBase.reason``); a refusal adds ``": <why>"``."""


class StepTimer:
    """Wall seconds per step from ``clock``, summed over repeated calls; a
    call that raises is timed too, and a clock that goes back reads 0."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.seconds: dict[str, float] = {}

    def timed(self, step: str, call: Callable[[], _T]) -> _T:
        start = self._clock()
        try:
            return call()
        finally:
            spent = max(0.0, self._clock() - start)
            self.seconds[step] = self.seconds.get(step, 0.0) + spent


class _TimedCombiner:
    """The combiner, its first call timed as ``combine``, a later one (the
    fallback) as ``fallback``."""

    def __init__(self, inner: Combiner, timer: StepTimer) -> None:
        self._inner, self._timer, self._calls = inner, timer, 0

    def combine(
        self,
        run_id: str,
        project: Project,
        base_commit: str,
        kept: Sequence[KeptChange],
        workloads: Sequence[Workload],
        *,
        baseline_count: int | None = None,
        quality_files: Sequence[FrozenFile] = (),
    ) -> CombineMeasured:
        step = "fallback" if self._calls else "combine"
        self._calls += 1
        args = (run_id, project, base_commit, kept, workloads)

        def call() -> CombineMeasured:
            if quality_files:  # as combine_kept: the keyword only with files
                return self._inner.combine(
                    *args, baseline_count=baseline_count, quality_files=quality_files
                )
            return self._inner.combine(*args, baseline_count=baseline_count)

        return self._timer.timed(step, call)


class _TimedBaseline:
    """The baseline runner, timed as ``baseline``; it reports the runner's
    frozen files and label leaks (none for a runner that has none)."""

    def __init__(self, inner: BaselineRunner, timer: StepTimer) -> None:
        self._inner, self._timer = inner, timer

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        return self._timer.timed(
            "baseline",
            lambda: self._inner.measure(workloads, run_id=run_id, commit=commit),
        )

    @property
    def quality_files(self) -> tuple[FrozenFile, ...]:
        inner = self._inner
        return inner.quality_files if isinstance(inner, _Freezing) else ()

    @property
    def label_leaks(self) -> tuple[str, ...]:
        inner = self._inner
        return inner.label_leaks if isinstance(inner, _Freezing) else ()


class _TimedCalibrator:
    """The noise calibrator, timed as ``calibration``."""

    def __init__(self, inner: NoiseCalibrator, timer: StepTimer) -> None:
        self._inner, self._timer = inner, timer

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        return self._timer.timed(
            "calibration",
            lambda: self._inner.calibrate(
                workloads, run_id=run_id, commit=commit, blocks=blocks
            ),
        )


class _TimedProfiler:
    """The profiler, timed as ``profile``."""

    def __init__(self, inner: Profiler, timer: StepTimer) -> None:
        self._inner, self._timer = inner, timer

    def profile(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str
    ) -> ProfileResult:
        return self._timer.timed(
            "profile",
            lambda: self._inner.profile(workloads, run_id=run_id, commit=commit),
        )


@dataclass(frozen=True)
class RoundCombine:
    """One round's combine on its base: the trial ids offered, the FIXED
    combine's outcome (``None``: nothing offered, no combiner call), the
    wall seconds of its re-tests (``combine``, ``fallback``) and the
    combiner's notes of its latest call (``GitCombiner.last_notes``)."""

    base_commit: str
    offered_trial_ids: tuple[str, ...]
    outcome: CombineOutcome | None
    seconds: Mapping[str, float]
    notes: tuple[str, ...] = ()

    @property
    def combination(self) -> Combination | None:
        return None if self.outcome is None else self.outcome.combination

    @property
    def reason(self) -> str:
        """``nothing kept``, ``held`` or ``did not hold``."""
        combination = self.combination
        if combination is None:
            return NOTHING_KEPT
        return HELD if combination.holds else DID_NOT_HOLD


def _require_stacking(ctx: NodeContext) -> tuple[Combiner, Stacker]:
    """The combiner and stacker of a stacking context, else ``EngineError``."""
    combiner, stacker = ctx.combiner, ctx.stacker
    if not ctx.stack_rounds or combiner is None or stacker is None:
        raise EngineError(
            "the round combine runs only with stacked rounds (stack_rounds, "
            "a combiner and a stacker)"
        )
    return combiner, stacker


def _require_exact_check(baseline: Baseline) -> None:
    """Stacking adopts a tip only on outputs equal to the original base's,
    so the run must have been defined with the exact output check."""
    if not any(g.kind is GuardrailKind.output_equivalence for g in baseline.guardrails):
        raise EngineError(
            "stacked rounds need the run's exact output check (an "
            "output_equivalence guardrail); this run was defined without it"
        )


def offered_keeps(state: EngineState) -> list[Verdict]:
    """The run-set keeps (``nodes._delivery_sets``) whose trial started from
    the round base, in verdict order; ``EngineError`` for a keep whose trial
    is unknown or has no base (it cannot be placed on any base)."""
    base = _require_commit(state, "the round combine")
    trials = {trial.id: trial for trial in state["trials"]}
    offered: list[Verdict] = []
    for verdict in _delivery_sets(_deliverable(state))[0]:
        trial = trials.get(verdict.trial_id)
        started = None if trial is None else trial.base_commit
        if started is None:
            raise EngineError(
                f"kept verdict {verdict.id} has no trial base: it cannot be "
                "offered to a round combine"
            )
        if started == base:
            offered.append(verdict)
    return offered


def combine_round(
    ctx: NodeContext, state: EngineState, *, clock: Clock = time.perf_counter
) -> RoundCombine:
    """The round combine on the round base (module docstring, items 1-2)."""
    combiner, _ = _require_stacking(ctx)
    base = _require_commit(state, "the round combine")
    measured = _require_baseline(state)
    _require_exact_check(measured)
    offered = offered_keeps(state)
    if not offered:
        return RoundCombine(base, (), None, {})
    timer = StepTimer(clock)
    number = max(1, state["round"])
    target = CombineTarget(
        run_id=state["run_id"],
        project=state["project"],
        base_commit=base,
        workloads=tuple(state["workloads"]),
        branch=f"{ctx.branch_prefix}stack-{state['run_id']}-r{number}",
        round=number,
        quality_files=measured.quality_files,
    )
    trials = {trial.id: trial for trial in state["trials"]}
    changes = kept_changes(offered, trials, _by_id(state["hypotheses"]))
    outcome = combine_kept(
        _TimedCombiner(combiner, timer), changes, _combine_rules(ctx, measured), target
    )
    ids = tuple(verdict.trial_id for verdict in offered)
    notes = _combiner_notes(ctx)  # the real combiner's, after its last call
    return RoundCombine(base, ids, outcome, dict(timer.seconds), notes)


@dataclass(frozen=True)
class _Adopted:
    """A tip that passed adoption: its baseline and hotspots, the events its
    nodes and the re-key wrote, and the re-key's counts."""

    baseline: Baseline
    hotspots: list[Hotspot]
    events: list[EngineEvent]
    rekeyed: int
    dropped: int


def _timed_context(ctx: NodeContext, timer: StepTimer) -> NodeContext:
    """``ctx`` with its baseline runner, calibrator and profiler timed."""
    calibrator, profiler = ctx.calibrator, ctx.profiler
    return replace(
        ctx,
        baseline_runner=_TimedBaseline(ctx.baseline_runner, timer),
        calibrator=None if calibrator is None else _TimedCalibrator(calibrator, timer),
        profiler=None if profiler is None else _TimedProfiler(profiler, timer),
    )


def _adopt(
    ctx: NodeContext,
    state: EngineState,
    stacker: Stacker,
    origin: Baseline,
    tip: str,
    timer: StepTimer,
) -> _Adopted | str:
    """The tip adopted (module docstring, item 3), or why it was refused."""
    base = _require_commit(state, "restack")
    try:
        diff = stacker.diff(state["project"], base, tip)
    except EngineError as exc:
        if type(exc) is not EngineError and not isinstance(exc, GitError):
            raise
        return f"{NO_DIFF}: {_capped(str(exc))}"
    run = make_nodes(_timed_context(ctx, timer))
    at_tip = cast(EngineState, {**state, "base_commit": tip})
    try:
        measured = run["baseline"](at_tip)
    except EngineError as exc:
        if type(exc) is not EngineError:
            raise
        return f"{BASELINE_FAILED}: {_capped(str(exc))}"
    baseline = cast(Baseline, measured["baseline"])
    differ = compare_fingerprints(origin.measurements, baseline.measurements)
    if differ:
        return f"{OUTPUTS_DIFFER}: " + _capped("; ".join(v.message for v in differ))
    profiled = run["profile"](cast(EngineState, {**at_tip, "baseline": baseline}))
    keys = current_keys(event.data for event in state["events"])
    batch = rekey_events(keys, diff, base, tip)
    rekeyed = [
        _note(state, RunPhase.hypotheses, found.code, found.message,
              level=found.level, data=found.data)
        for found in batch
    ]  # fmt: skip
    dropped = sum(1 for found in batch if found.code == DROP_EVENT)
    return _Adopted(
        baseline=baseline,
        hotspots=list(cast(list[Hotspot], profiled["hotspots"])),
        events=[
            *cast(list[EngineEvent], measured["events"]),
            *cast(list[EngineEvent], profiled["events"]),
            *rekeyed,
        ],
        rekeyed=len(batch) - dropped,
        dropped=dropped,
    )


def _round_event(
    state: EngineState, record: RoundBase, adopted: _Adopted | None
) -> EngineEvent:
    """``stack_round``: the round's fate, info when adopted or nothing was
    kept, a warning when the combine did not hold or its tip was refused."""
    combination = record.combination
    if record.adopted:
        fate = f"tip {record.next_base[:12]} adopted as the next base"
    elif record.tip_commit is not None:
        fate = f"tip {record.tip_commit[:12]} refused: {record.reason}"
    else:
        fate = record.reason
    data: ScalarDict = {
        "round": record.round,
        "base": record.base_commit,
        "offered": len(record.offered_trial_ids),
        "applied": 0 if combination is None else len(combination.applied_trial_ids),
        "holds": None if combination is None else combination.holds,
        "adopted": record.adopted,
        "tip": record.tip_commit,
        "reason": record.reason,
    }
    if adopted is not None:
        data["rekeyed"], data["dropped"] = adopted.rekeyed, adopted.dropped
    calm = record.adopted or combination is None
    return _note(
        state,
        RunPhase.combine,
        "stack_round",
        f"round {record.round} on {record.base_commit[:12]}: {fate}",
        level=EventLevel.info if calm else EventLevel.warning,
        data=data,
    )


def _notes_events(state: EngineState, notes: Sequence[str]) -> list[EngineEvent]:
    """The round combine's ``combiner_notes`` event, as ``nodes._combine_set``
    writes one for a set (here set ``stack``); none without notes."""
    if not notes:
        return []
    said = _capped("; ".join(notes))
    return [
        _note(state, RunPhase.combine, "combiner_notes", f"stack set: {said}",
              data={"set": "stack", "notes": said})
    ]  # fmt: skip


def restack(
    ctx: NodeContext, state: EngineState, *, clock: Clock = time.perf_counter
) -> NodeDelta:
    """The step between stacked rounds (module docstring): the round combine
    on the round base, the held tip adopted or refused, the round recorded."""
    _, stacker = _require_stacking(ctx)
    base = _require_commit(state, "restack")
    ledger = state.get("stack")
    if ledger is None:
        ledger = StackLedger(
            origin_commit=base, origin_baseline=_require_baseline(state)
        )
    elif ledger.current_base != base:
        raise EngineError(
            f"the round base {base} is not the stack ledger's current base "
            f"{ledger.current_base}"
        )
    combined = combine_round(ctx, state, clock=clock)
    combination = combined.combination
    noted = _notes_events(state, combined.notes)
    fields: dict[str, object] = {
        "round": max(1, state["round"]),
        "base_commit": base,
        "offered_trial_ids": combined.offered_trial_ids,
        "combination": combination,
    }
    held = combination is not None and combination.holds
    tip = combination.tip_commit if combination is not None and held else None
    if tip is None:
        record = RoundBase.model_validate(
            {**fields, "reason": combined.reason, "seconds": dict(combined.seconds)}
        )
        event = _round_event(state, record, None)
        return {"stack": ledger.with_round(record), "events": [*noted, event]}
    timer = StepTimer(clock)
    adopted = _adopt(ctx, state, stacker, ledger.origin_baseline, tip, timer)
    seconds = {**combined.seconds, **timer.seconds}
    if isinstance(adopted, str):
        record = RoundBase.model_validate(
            {**fields, "tip_commit": tip, "reason": adopted, "seconds": seconds}
        )
        refused = _note(
            state,
            RunPhase.combine,
            "stack_refused",
            f"round {record.round}: tip {tip[:12]} not adopted: {adopted}",
            level=EventLevel.warning,
            data={"round": record.round, "tip": tip, "reason": adopted},
        )
        events = [*noted, refused, _round_event(state, record, None)]
        return {"stack": ledger.with_round(record), "events": events}
    calibration = adopted.baseline.calibration
    record = RoundBase.model_validate(
        {
            **fields,
            "adopted": True,
            "tip_commit": tip,
            "floor": None if calibration is None else calibration.floor,
            "reason": HELD,
            "seconds": seconds,
        }
    )
    return {
        "base_commit": tip,
        "baseline": adopted.baseline,
        "hotspots": adopted.hotspots,
        "stack": ledger.with_round(record),
        "events": [*noted, *adopted.events, _round_event(state, record, adopted)],
    }
