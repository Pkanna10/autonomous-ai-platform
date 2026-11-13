"""The step between stacked rounds, ``restack`` (X2-DT U5a; dt-design
section 1, "restack", and the U5a row of section 2).

``restack`` offers the round combine every run-set keep still on the round
base, combines them through the FIXED ``combine_kept``, and adopts a held
tip only after the tip's diff is read, the unchanged baseline node measured
and calibrated there, its outputs matched the original base's and the
unchanged profile node ran there; then one re-key batch moves the seeds'
keys onto the tip. Every round is recorded through ``StackLedger.with_round``.

Swap points (the seams): ``_Rebased`` stands for ``GitTrialRunner`` (a
commit, and ``base_commit`` from the baseline's commit) over the conftest's
``StubTrialRunner``; ``_Measuring`` for ``GitBaselineRunner`` (per-commit
scripts, so the tip can differ from the origin); ``_Calibrator`` for its
``calibrate``; ``_Profiler`` for ``CProfiler``; ``_Merging`` for
``GitCombiner`` (it applies every change offered and reports a scripted tip
and wall time); ``FakeStacker`` for ``GitStacker``. ``_Clock`` stands for
``time.perf_counter``: every fake advances it by its own cost, so each
step's seconds are exact. Nodes run by hand, merged as LangGraph's reducers
merge them. Real git, the real timings and the graph wiring (U5b) are
proven elsewhere (U7's E2E, the pilot).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final, cast

import pytest

from autonomous_ai_agents.common.errors import EngineError, RepoTamperedError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Combination,
    EngineEvent,
    FrozenFile,
    GuardrailKind,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    Measurement,
    NoiseCalibration,
    Objective,
    Project,
    RoundBase,
    RunPhase,
    RunStats,
    StackLedger,
    Trial,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.fakes import FakeProfiler, FakeStacker
from autonomous_ai_agents.execution.git import GitError
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    KeptChange,
    ProfileResult,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization import rekey
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.idea_dedupe import (
    IdeaKey,
    MechanismKey,
    Target,
    key_event,
)
from autonomous_ai_agents.optimization.idea_types import Mechanism, MorphCell
from autonomous_ai_agents.orchestrator import stack_round
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineTarget,
    combine_kept,
    kept_changes,
)
from autonomous_ai_agents.orchestrator.events import make_event
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    _combine_rules,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.stack_round import (
    BASELINE_FAILED,
    DID_NOT_HOLD,
    HELD,
    NO_DIFF,
    NOTHING_KEPT,
    OUTPUTS_DIFFER,
    StepTimer,
    combine_round,
    offered_keeps,
    restack,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ORIGIN: Final = "a" * 40
TIP: Final = "b" * 40
TIP2: Final = "c" * 40
VAL_LOSS: Final = "val_loss"
SAME: Final = fingerprint("baseline")  # the conftest's baseline output
OTHER: Final = fingerprint("something else")
PATH: Final = "lib/parse.py"
LOOP: Final = (
    "connect", "understand", "define", "baseline", "profile", "research",
    "hypotheses", "trials", "judges", "verdicts",
)  # fmt: skip
ROUND: Final = ("hypotheses", "trials", "judges", "verdicts")
COSTS: Final = {"baseline": 2.0, "calibration": 3.0, "profile": 1.0}
"""Seconds each fake adds to the clock per call (the combiner's are scripted)."""
FLOOR: Final = 0.05


def _script(*wall: float, path: str, output: str = SAME) -> ScriptedOutcome:
    return ScriptedOutcome(
        touched_paths=(path,),
        samples={METRIC_WALL_TIME_S: wall, VAL_LOSS: (0.500,) * 5},
        output_fingerprint=output, tests_passed=True, cost_usd=0.05,
        tokens_used=1000,
    )  # fmt: skip


WIN_A: Final = _script(1.05, 1.02, 1.08, 1.05, 1.05, path=PATH)
WIN_B: Final = _script(1.10, 1.08, 1.12, 1.10, 1.10, path="lib/index.py")
WIN_C: Final = _script(1.20, 1.18, 1.22, 1.20, 1.20, path="lib/util.py")
LOSE: Final = _script(1.79, 1.76, 1.82, 1.79, 1.79, path=PATH)  # inconclusive
WIN_OTHER: Final = _script(1.05, 1.02, 1.08, 1.05, 1.05, path="lib/other.py", output=OTHER)  # fmt: skip
SCRIPTS: Final = {
    "A cache": WIN_A, "B hoist": WIN_B, "C batch": WIN_C, "L tweak": LOSE,
    "O other": WIN_OTHER,
}  # fmt: skip


def _base_script(output: str = SAME) -> ScriptedOutcome:
    return ScriptedOutcome(
        samples={METRIC_WALL_TIME_S: (1.80, 1.75, 1.85, 1.80, 1.80),
                 VAL_LOSS: (0.500,) * 5},
        tests_passed=True, output_fingerprint=output,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# The fakes, each advancing one shared clock
# ---------------------------------------------------------------------------


@dataclass
class _Clock:
    """``time.perf_counter`` stand-in: read by ``restack``, moved by the fakes."""

    now: float = 100.0
    reads: int = 0

    def __call__(self) -> float:
        self.reads += 1
        return self.now


class _Rebased(StubTrialRunner):
    """``StubTrialRunner`` whose trials carry a commit and start from the
    baseline's commit, as ``GitTrialRunner``'s do."""

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        trial = super().run(hypothesis, workloads, baseline, **kwargs)
        commit = hashlib.sha1(trial.id.encode()).hexdigest()  # noqa: S324 - a fake id
        return trial.model_copy(
            update={"commit": commit, "base_commit": baseline.commit}
        )


Raw = tuple[tuple[Any, ...], dict[str, Any]]
"""One call exactly as made: its positional and its keyword arguments."""


class _Measuring:
    """A baseline runner with one script (or error) per commit; ``raw``
    records every call's arguments exactly, ``calls`` its commit."""

    def __init__(
        self, clock: _Clock, at: Mapping[str, ScriptedOutcome | Exception]
    ) -> None:
        self._clock, self.at = clock, dict(at)
        self.calls: list[str | None] = []
        self.raw: list[Raw] = []

    def measure(self, *args: Any, **kwargs: Any) -> tuple[Measurement, ...]:
        self.raw.append((args, dict(kwargs)))
        (workloads,) = args
        run_id, commit = kwargs["run_id"], kwargs["commit"]
        self.calls.append(commit)
        self._clock.now += COSTS["baseline"]
        outcome = self.at[cast(str, commit)]
        if isinstance(outcome, Exception):
            raise outcome
        return StubBaselineRunner(outcome).measure(
            workloads, run_id=run_id, commit=commit
        )


FROZEN: Final = FrozenFile(path="eval/labels.txt", sha256="0" * 64, size=3)


class _Freezing(_Measuring):
    """A baseline runner that reports frozen files and label leaks, as
    ``GitBaselineRunner`` does after ``measure``."""

    @property
    def quality_files(self) -> tuple[FrozenFile, ...]:
        return (FROZEN,)

    @property
    def label_leaks(self) -> tuple[str, ...]:
        return ("data/train.csv",)


class _Calibrator:
    """A calibrator whose floor is ``floors[commit]`` (default ``FLOOR``)."""

    def __init__(
        self, clock: _Clock, floors: Mapping[str, float] | None = None
    ) -> None:
        self._clock, self._floors = clock, dict(floors or {})
        self.calls: list[str] = []
        self.raw: list[Raw] = []

    def calibrate(self, *args: Any, **kwargs: Any) -> NoiseCalibration:
        self.raw.append((args, dict(kwargs)))
        commit, blocks = kwargs["commit"], kwargs["blocks"]
        self.calls.append(commit)
        self._clock.now += COSTS["calibration"]
        floor = self._floors.get(commit, FLOOR)
        return NoiseCalibration(
            blocks=blocks, gaps={"w:wall_time_s": 0.01}, floor=floor
        )


class _Profiler(FakeProfiler):
    def __init__(self, clock: _Clock, hotspots: Sequence[Hotspot]) -> None:
        super().__init__(hotspots)
        self._clock = clock
        self.raw: list[Raw] = []

    def profile(self, *args: Any, **kwargs: Any) -> ProfileResult:
        self.raw.append((args, dict(kwargs)))
        self._clock.now += COSTS["profile"]
        (workloads,) = args
        return super().profile(
            workloads, run_id=kwargs["run_id"], commit=kwargs["commit"]
        )


@dataclass(frozen=True)
class _Call:
    base_commit: str
    trial_ids: tuple[str, ...]
    quality_files: tuple[FrozenFile, ...] | None


def _rows(workload: Workload, wall: float, *, suite: bool) -> list[Measurement]:
    samples = {
        METRIC_WALL_TIME_S: tuple(wall + d for d in (0.0, -0.02, 0.02, 0.0, 0.0)),
        VAL_LOSS: (0.500,) * 5,
    }
    rows = [
        Measurement(workload_id=workload.id, metric=metric,
                    stats=RunStats.from_samples(values, unit="s"), samples=values,
                    output_fingerprint=SAME)
        for metric, values in samples.items()
    ]  # fmt: skip
    if suite:
        rows.append(Measurement(workload_id=workload.id, metric=METRIC_TESTS_PASSED,
                                stats=RunStats.from_samples((1.0,), unit="bool"),
                                samples=(1.0,)))  # fmt: skip
    return rows


class _Merging:
    """A combiner applying every change offered: each call takes the next
    scripted ``(tip, wall, seconds)`` (or raises), with A rows at 1.80 s;
    ``raw`` records every call's arguments exactly, ``calls`` a summary;
    ``last_notes`` are ``GitCombiner``'s notes of the latest call."""

    def __init__(
        self,
        clock: _Clock,
        script: Sequence[tuple[str, float, float] | Exception],
        notes: Sequence[str] = (),
    ) -> None:
        self._clock, self._script = clock, list(script)
        self.calls: list[_Call] = []
        self.raw: list[Raw] = []
        self.last_notes = tuple(notes)

    def combine(self, *args: Any, **kwargs: Any) -> CombineMeasured:
        self.raw.append((args, dict(kwargs)))
        _, _, base_commit, kept, workloads = args
        quality_files = kwargs.get("quality_files")
        files = None if quality_files is None else tuple(quality_files)
        kept = cast(Sequence[KeptChange], kept)
        self.calls.append(_Call(base_commit, tuple(c.trial_id for c in kept), files))
        outcome = self._script[len(self.calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        tip, wall, seconds = outcome
        self._clock.now += seconds
        return CombineMeasured(
            tip_commit=tip,
            applied=tuple(c.trial_id for c in kept),
            skipped=(),
            baseline=tuple(r for w in workloads for r in _rows(w, 1.80, suite=False)),
            combined=tuple(r for w in workloads for r in _rows(w, wall, suite=True)),
        )


# ---------------------------------------------------------------------------
# The world: a stacking context over the fakes, rounds run by hand
# ---------------------------------------------------------------------------


def _key(first: int, last: int) -> IdeaKey:
    target = Target(path=PATH, first=first, last=last)
    key = MechanismKey(
        target=target, mechanism=Mechanism.remove_work, cell=MorphCell.work_eliminate
    )
    return IdeaKey(key=key, function="parse")


def _shift(by: int) -> str:
    """A ``PATH`` diff inserting ``by`` lines above line 1."""
    added = "".join(f"+new {n}\n" for n in range(by))
    return (
        f"diff --git a/{PATH} b/{PATH}\nindex 1111111..2222222 100644\n"
        f"--- a/{PATH}\n+++ b/{PATH}\n@@ -1,3 +1,{3 + by} @@\n{added}"
        " line 1\n line 2\n line 3\n"
    )


def _hot(line: int) -> Hotspot:
    return Hotspot(
        project_id="p", workload_id="w", file_path=PATH, symbol="parse",
        line_start=line, self_time_s=1.0, total_time_s=2.0, share=0.4,
    )  # fmt: skip


HOT: Final = _hot(5)
TIP_HOT: Final = _hot(7)


@dataclass
class _World:
    clock: _Clock
    baseline: _Measuring
    calibrator: _Calibrator | None
    profiler: _Profiler | None
    combiner: _Merging
    stacker: FakeStacker
    ctx: NodeContext
    ideas: dict[str, Hypothesis] = field(default_factory=dict)


def _idea(project: Project, title: str) -> Hypothesis:
    return Hypothesis(
        project_id=project.id, source=HypothesisSource.novel, title=title,
        rationale="r", change_class=ChangeClass.efficiency, expected_gain=0.1,
        provability=0.7, risk=0.1,
    )  # fmt: skip


def _world(
    make_context: Any,
    project: Project,
    titles: Sequence[str],
    *,
    combines: Sequence[tuple[str, float, float] | Exception] = (),
    at: Mapping[str, ScriptedOutcome | Exception] | None = None,
    diffs: Mapping[tuple[str, str], str | Exception] | None = None,
    per_round: int = 1,
    calibrate: bool = True,
    profile: bool = True,
    freezing: bool = False,
    floors: Mapping[str, float] | None = None,
    notes: Sequence[str] = (),
) -> _World:
    clock = _Clock()
    scripts = {ORIGIN: _base_script(), TIP: _base_script(), TIP2: _base_script()}
    runner_type = _Freezing if freezing else _Measuring
    baseline = runner_type(clock, {**scripts, **(at or {})})
    calibrator = _Calibrator(clock, floors) if calibrate else None
    profiler = _Profiler(clock, [TIP_HOT]) if profile else None
    combiner = _Merging(clock, combines, notes)
    default = {(ORIGIN, TIP): _shift(2), (TIP, TIP2): _shift(1)}
    stacker = FakeStacker(diffs={**default, **(diffs or {})})
    ideas = {title: _idea(project, title) for title in titles}
    ctx = make_context(
        list(ideas.values()),
        runner=_Rebased(dict(SCRIPTS)),
        baseline_runner=baseline,
        calibrator=calibrator,
        calibration_blocks=3 if calibrate else 0,
        profiler=profiler,
        hotspots=(HOT,),
        combiner=combiner,
        stacker=stacker,
        stack_rounds=True,
        default_output_check=True,
        max_hypotheses_per_round=per_round,
    )
    return _World(clock, baseline, calibrator, profiler, combiner, stacker, ctx, ideas)


@pytest.fixture
def state(
    sample_project: Project, sample_workload: Workload, sample_objective: Objective
) -> EngineState:
    state = initial_state(
        sample_project, [sample_workload], [sample_objective], [],
        run_id="run-dt5a", max_rounds=3, max_cost_usd=10.0,
    )  # fmt: skip
    state["base_commit"] = ORIGIN
    return state


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        reducer = key in ("events", "trials", "verdicts", "lessons")
        merged[key] = [*merged[key], *cast(list[Any], value)] if reducer else value
    return cast(EngineState, merged)


def _through(ctx: NodeContext, state: EngineState, names: Sequence[str]) -> EngineState:
    run = make_nodes(ctx)
    for name in names:
        state = _apply(state, run[name](state))
    return state


def _with_key(state: EngineState, idea: Hypothesis, key: IdeaKey) -> EngineState:
    """``state`` with ``idea``'s key recorded, as the idea pipeline stores it."""
    found = key_event(idea.id, idea.title, key)
    stored = make_event(state["run_id"], RunPhase.hypotheses, found.message,
                        data={"code": found.code, **found.data})  # fmt: skip
    return cast(EngineState, {**state, "events": [*state["events"], stored]})


def _codes(events: object) -> list[str]:
    return [str(e.data.get("code")) for e in cast(list[EngineEvent], events)]


def _ledger(delta: NodeDelta) -> StackLedger:
    ledger = delta["stack"]
    assert isinstance(ledger, StackLedger)
    return ledger


def _event(delta: NodeDelta, code: str) -> EngineEvent:
    (found,) = [e for e in cast(list[EngineEvent], delta["events"])
                if e.data.get("code") == code]  # fmt: skip
    return found


def _round_one(world: _World, state: EngineState, *, key: bool = True) -> EngineState:
    after = _through(world.ctx, state, LOOP)
    first = next(iter(world.ideas.values()))
    return _with_key(after, first, _key(5, 6)) if key else after


# ---------------------------------------------------------------------------
# Held: the base moves, measured, calibrated and profiled at the tip
# ---------------------------------------------------------------------------


def test_a_held_combine_moves_the_base_and_remeasures_at_the_tip(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN round one with one keep (from the origin) and its key recorded
    WHEN restack runs and the round combine holds at TIP
    THEN the delta moves ``base_commit`` to TIP with the tip's baseline (the
         unchanged baseline node: measured and calibrated at TIP, its floor
         recorded), the tip's hotspots (the unchanged profile node at TIP),
         one re-key batch moving the key two lines down, the ledger's first
         round adopted, and a ``stack_round`` event
    """
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 5.0)]
    )
    after = _round_one(world, state)
    (verdict,) = after["verdicts"]
    assert verdict.outcome is VerdictOutcome.keep
    (trial,) = after["trials"]
    assert trial.base_commit == ORIGIN
    origin = after["baseline"]
    assert origin is not None

    delta = restack(world.ctx, after, clock=world.clock)

    assert world.combiner.calls == [_Call(ORIGIN, (trial.id,), None)]
    assert world.baseline.calls == [ORIGIN, TIP]
    assert world.calibrator is not None and world.calibrator.calls == [ORIGIN, TIP]
    assert world.profiler is not None
    assert [c.commit for c in world.profiler.calls] == [ORIGIN, TIP]
    assert [(c.method, c.base, c.tip) for c in world.stacker.calls] == [
        ("diff", ORIGIN, TIP)
    ]
    assert set(delta) == {"base_commit", "baseline", "hotspots", "stack", "events"}
    assert delta["base_commit"] == TIP
    tip = delta["baseline"]
    assert isinstance(tip, Baseline) and tip.commit == TIP
    assert tip.calibration is not None and tip.calibration.floor == FLOOR
    assert tip.guardrails == origin.guardrails
    assert delta["hotspots"] == [TIP_HOT]
    ledger = _ledger(delta)
    assert (ledger.origin_commit, ledger.origin_baseline) == (ORIGIN, origin)
    assert ledger.current_base == TIP
    (record,) = ledger.rounds
    assert (record.round, record.base_commit, record.offered_trial_ids) == (
        1,
        ORIGIN,
        (trial.id,),
    )
    assert record.combination is not None and record.combination.holds
    assert (record.adopted, record.tip_commit, record.floor, record.reason) == (
        True,
        TIP,
        FLOOR,
        HELD,
    )
    codes = _codes(delta["events"])
    assert codes.count(rekey.REKEY_EVENT) == 1 and rekey.DROP_EVENT not in codes
    assert codes[-1] == "stack_round"
    assert "stack_refused" not in codes
    moved = _apply(after, delta)
    first = world.ideas["A cache"]
    assert rekey.current_keys(e.data for e in moved["events"]) == {first.id: _key(7, 8)}
    fate = _event(delta, "stack_round")
    assert fate.data["adopted"] is True and fate.data["tip"] == TIP
    assert (fate.data["rekeyed"], fate.data["dropped"]) == (1, 0)


def test_the_round_seconds_come_from_the_injected_clock(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN two keeps whose greedy combine does not hold (5 s) and whose
          fallback holds (7 s), a baseline (2 s), a calibration (3 s) and a
          profile (1 s) at the tip, each advancing the injected clock
    WHEN restack runs
    THEN the round's seconds are exactly those, keyed by step, and the tip
         the fallback's is adopted
    """
    world = _world(
        make_context, sample_project, ["A cache", "B hoist"], per_round=2,
        combines=[(TIP, 1.80, 5.0), (TIP, 0.90, 7.0)],
    )  # fmt: skip
    after = _round_one(world, state)
    assert [v.outcome for v in after["verdicts"]] == [VerdictOutcome.keep] * 2

    delta = restack(world.ctx, after, clock=world.clock)

    (record,) = _ledger(delta).rounds
    assert record.seconds == {
        "combine": 5.0, "fallback": 7.0, "baseline": 2.0, "calibration": 3.0,
        "profile": 1.0,
    }  # fmt: skip
    assert record.adopted and record.combination is not None
    assert record.combination.fallback_trial_id is not None
    assert len(world.combiner.calls[1].trial_ids) == 1
    assert delta["base_commit"] == TIP


def test_without_a_calibrator_or_profiler_the_tip_takes_the_stub_profile(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """With no calibrator the tip has no floor and no calibration step; with
    no profiler the unchanged profile node gives the context's hotspots and
    no profile step: only the steps that ran are timed."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 4.0)],
        calibrate=False, profile=False,
    )  # fmt: skip
    after = _round_one(world, state)

    delta = restack(world.ctx, after, clock=world.clock)

    (record,) = _ledger(delta).rounds
    assert record.adopted and record.floor is None
    assert record.seconds == {"combine": 4.0, "baseline": 2.0}
    assert delta["hotspots"] == [HOT]
    tip = delta["baseline"]
    assert isinstance(tip, Baseline) and tip.calibration is None


# ---------------------------------------------------------------------------
# Not held, nothing kept, offered again
# ---------------------------------------------------------------------------


def test_a_combine_that_does_not_hold_remeasures_nothing(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN one keep whose round combine does not hold (no gain at the tip;
          one change, so no fallback)
    WHEN restack runs
    THEN the base stays: no diff, no baseline, calibration or profile at the
         tip, no re-key; the round is recorded as did not hold, combine time
         only, and its event is a warning
    """
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 1.80, 6.0)]
    )
    after = _round_one(world, state)
    measured = (len(world.baseline.calls), world.clock.now)

    delta = restack(world.ctx, after, clock=world.clock)

    assert len(world.combiner.calls) == 1
    assert len(world.baseline.calls) == measured[0]
    assert world.stacker.calls == []
    assert set(delta) == {"stack", "events"}
    (record,) = _ledger(delta).rounds
    assert record.combination is not None and not record.combination.holds
    assert (record.adopted, record.tip_commit, record.reason) == (
        False,
        None,
        DID_NOT_HOLD,
    )
    assert record.seconds == {"combine": 6.0}
    assert _codes(delta["events"]) == ["stack_round"]
    assert _event(delta, "stack_round").level.value == "warning"


def test_no_keep_makes_no_combiner_call(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a round whose only trial is inconclusive
    WHEN restack runs
    THEN nothing is offered: no combiner call, no clock read, the round is
         "nothing kept" with no combination and no seconds
    """
    world = _world(make_context, sample_project, ["L tweak"])
    after = _round_one(world, state)
    assert [v.outcome for v in after["verdicts"]] == [VerdictOutcome.inconclusive]
    reads = world.clock.reads

    delta = restack(world.ctx, after, clock=world.clock)

    assert world.combiner.calls == []
    assert world.clock.reads == reads
    (record,) = _ledger(delta).rounds
    assert (record.offered_trial_ids, record.combination, record.reason) == (
        (),
        None,
        NOTHING_KEPT,
    )
    assert record.seconds == {}
    assert set(delta) == {"stack", "events"}
    fate = _event(delta, "stack_round")
    assert fate.level.value == "info" and fate.data["holds"] is None


def test_keeps_are_offered_again_while_the_base_is_unchanged_and_never_after(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN round one's keep A, whose combine does not hold; round two's keep
          B, both on the origin; round three's keep C, on the adopted tip
    WHEN restack runs after each round
    THEN round two offers A and B again (the base is unchanged) and its tip
         is adopted; round three offers C alone (A and B are on the old
         base), and its tip chains on: the ledger holds three rounds in order
         and the key, re-keyed once per adopted tip, sits at the second
         tip's lines (fed from ``current_keys``, never ``recorded_keys``)
    """
    world = _world(
        make_context, sample_project, ["A cache", "B hoist", "C batch"],
        combines=[(TIP, 1.80, 1.0), (TIP, 0.85, 1.0), (TIP2, 0.95, 1.0)],
    )  # fmt: skip
    one = _round_one(world, state)
    one = _apply(one, restack(world.ctx, one, clock=world.clock))
    assert one["base_commit"] == ORIGIN
    two = _through(world.ctx, one, ROUND)
    t_a, t_b = (t.id for t in two["trials"])

    delta = restack(world.ctx, two, clock=world.clock)
    two = _apply(two, delta)
    three = _through(world.ctx, two, ROUND)
    t_c = three["trials"][-1]
    assert t_c.base_commit == TIP
    last = restack(world.ctx, three, clock=world.clock)

    offered = [set(c.trial_ids) for c in world.combiner.calls]  # in kept_changes order
    assert offered == [{t_a}, {t_a, t_b}, {t_c.id}]
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN, ORIGIN, TIP]
    ledger = _ledger(last)
    assert [(r.round, r.base_commit, r.adopted) for r in ledger.rounds] == [
        (1, ORIGIN, False), (2, ORIGIN, True), (3, TIP, True)
    ]  # fmt: skip
    assert ledger.current_base == TIP2 and last["base_commit"] == TIP2
    done = _apply(three, last)
    codes = _codes(done["events"])
    assert codes.count(rekey.REKEY_EVENT) == 2 and rekey.DROP_EVENT not in codes
    first = world.ideas["A cache"]
    assert rekey.current_keys(e.data for e in done["events"]) == {first.id: _key(8, 9)}


# ---------------------------------------------------------------------------
# Adoption refused: the base stays, the held tip is recorded
# ---------------------------------------------------------------------------


def _refused(delta: NodeDelta, reason: str) -> None:
    assert set(delta) == {"stack", "events"}
    (record,) = _ledger(delta).rounds
    assert record.combination is not None and record.combination.holds
    assert (record.adopted, record.tip_commit, record.floor) == (False, TIP, None)
    assert record.reason.startswith(reason), record.reason
    assert _ledger(delta).current_base == ORIGIN
    codes = _codes(delta["events"])
    assert codes == ["stack_refused", "stack_round"]
    refused = _event(delta, "stack_refused")
    assert refused.level.value == "warning" and refused.data["reason"] == record.reason


def test_a_tip_whose_outputs_differ_from_the_original_base_is_refused(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a held round combine whose tip's baseline outputs differ from the
          origin's (each side consistent, so the baseline node trusts it)
    WHEN restack runs
    THEN adoption is refused, naming the workload; the tip is never profiled
    """
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        at={TIP: _base_script(OTHER)},
    )  # fmt: skip
    after = _round_one(world, state)

    delta = restack(world.ctx, after, clock=world.clock)

    _refused(delta, OUTPUTS_DIFFER)
    workload = state["workloads"][0].id
    assert f"workload {workload}: output changed" in _ledger(delta).rounds[0].reason
    assert world.baseline.calls[-1] == TIP
    assert world.profiler is not None
    assert [c.commit for c in world.profiler.calls] == [ORIGIN]
    assert _ledger(delta).rounds[0].seconds == {"combine": 1.0, "baseline": 2.0, "calibration": 3.0}  # fmt: skip


def test_a_plain_engine_error_in_the_tips_baseline_refuses_adoption(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """A plain ``EngineError`` from the baseline at the tip (its worktree,
    its suite, its trust checks) refuses adoption with its message; the
    failed measurement is still timed."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        at={TIP: EngineError("the suite failed at the tip")},
    )  # fmt: skip
    after = _round_one(world, state)

    delta = restack(world.ctx, after, clock=world.clock)

    _refused(delta, BASELINE_FAILED)
    (record,) = _ledger(delta).rounds
    assert record.reason == f"{BASELINE_FAILED}: the suite failed at the tip"
    assert record.seconds == {"combine": 1.0, "baseline": 2.0}


@pytest.mark.parametrize(
    "error",
    [RepoTamperedError("the .git link moved"), GitError("git worktree add failed")],
    ids=["tampered", "git"],
)
def test_an_engine_error_subclass_in_the_tips_baseline_propagates(
    make_context: Any, state: EngineState, sample_project: Project, error: EngineError
) -> None:
    """``RepoTamperedError`` (or any other subclass) from the baseline at
    the tip is not a refusal: it stops the run, as it would anywhere."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        at={TIP: error},
    )  # fmt: skip
    after = _round_one(world, state)

    with pytest.raises(type(error)) as raised:
        restack(world.ctx, after, clock=world.clock)
    assert raised.value is error


@pytest.mark.parametrize(
    "error",
    [GitError("bad object"), EngineError("tip is not a commit id")],
    ids=["git", "engine"],
)
def test_a_diff_that_cannot_be_read_refuses_before_any_measurement(
    make_context: Any, state: EngineState, sample_project: Project, error: EngineError
) -> None:
    """
    GIVEN a held combine whose old-base..tip diff cannot be read
    WHEN restack runs
    THEN adoption is refused (no re-key batch can be written, and a tip with
         none would leave stale lines), before the tip is measured
    """
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        diffs={(ORIGIN, TIP): error},
    )  # fmt: skip
    after = _round_one(world, state)
    measured = len(world.baseline.calls)

    delta = restack(world.ctx, after, clock=world.clock)

    _refused(delta, NO_DIFF)
    assert _ledger(delta).rounds[0].reason == f"{NO_DIFF}: {error}"
    assert len(world.baseline.calls) == measured
    assert _ledger(delta).rounds[0].seconds == {"combine": 1.0}


def test_a_tampered_repository_while_reading_the_diff_propagates(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    error = RepoTamperedError("the repository changed")
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        diffs={(ORIGIN, TIP): error},
    )  # fmt: skip
    after = _round_one(world, state)

    with pytest.raises(RepoTamperedError):
        restack(world.ctx, after, clock=world.clock)


# ---------------------------------------------------------------------------
# Refused before any combiner call
# ---------------------------------------------------------------------------


def test_a_keep_whose_trial_has_no_base_is_an_engine_error(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)]
    )
    after = _round_one(world, state)
    (trial,) = after["trials"]
    unplaced = cast(EngineState, {**after, "trials": [trial.model_copy(update={"base_commit": None})]})  # fmt: skip
    lost = cast(EngineState, {**after, "trials": []})

    for broken in (unplaced, lost):
        with pytest.raises(EngineError, match="has no trial base"):
            restack(world.ctx, broken, clock=world.clock)
    assert world.combiner.calls == []


def test_a_run_whose_baseline_has_no_exact_output_check_is_refused(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """A run defined with the output check off (its stored baseline has no
    ``output_equivalence`` guardrail), resumed with a stacking context, is
    refused before any combine: tip rounds would be judged on outputs the
    frozen judge treats as not applicable (U4 review)."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)]
    )
    after = _round_one(world, state)
    measured = after["baseline"]
    assert measured is not None
    loose = measured.model_copy(update={"guardrails": tuple(
        g for g in measured.guardrails if g.kind is not GuardrailKind.output_equivalence
    )})  # fmt: skip

    with pytest.raises(EngineError, match="output_equivalence"):
        restack(
            world.ctx,
            cast(EngineState, {**after, "baseline": loose}),
            clock=world.clock,
        )
    assert world.combiner.calls == []


def test_restack_refuses_a_context_that_does_not_stack(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    world = _world(make_context, sample_project, ["A cache"])
    after = _round_one(world, state)
    off = make_context(baseline_runner=world.baseline)

    with pytest.raises(EngineError, match="stacked rounds"):
        restack(off, after)
    with pytest.raises(EngineError, match="stacked rounds"):
        combine_round(off, after)


def test_a_state_off_the_ledgers_current_base_is_an_engine_error(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)]
    )
    after = _round_one(world, state)
    origin = after["baseline"]
    assert origin is not None
    ledger = StackLedger(origin_commit=ORIGIN, origin_baseline=origin)
    moved = cast(EngineState, {**after, "stack": ledger, "base_commit": TIP})

    with pytest.raises(EngineError, match="ledger's current base"):
        restack(world.ctx, moved, clock=world.clock)
    assert world.combiner.calls == []


def test_a_checkpoint_without_the_stack_key_starts_a_ledger(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """A state with no ``stack`` channel at all (a checkpoint from before U1)
    reads as no ledger: restack starts one at the round base, never a
    KeyError."""
    world = _world(make_context, sample_project, ["L tweak"])
    after = _round_one(world, state, key=False)
    stored = cast(EngineState, {k: v for k, v in after.items() if k != "stack"})

    delta = restack(world.ctx, stored, clock=world.clock)

    assert _ledger(delta).origin_commit == ORIGIN
    assert _ledger(delta).rounds[0].reason == NOTHING_KEPT


# ---------------------------------------------------------------------------
# The proxies and the reusable pieces
# ---------------------------------------------------------------------------


def test_the_baseline_proxy_forwards_the_frozen_files_and_leaks(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a baseline runner that reports frozen files and label leaks
    WHEN restack measures the tip through its timing proxy
    THEN the tip's baseline records the runner's frozen files (the node read
         them through the proxy), and the round combine passed the round
         base's frozen files on; a plain runner reports none through it
    """
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)],
        freezing=True,
    )  # fmt: skip
    after = _round_one(world, state)
    assert after["baseline"] is not None and after["baseline"].quality_files == (
        FROZEN,
    )

    delta = restack(world.ctx, after, clock=world.clock)

    tip = delta["baseline"]
    assert isinstance(tip, Baseline) and tip.quality_files == (FROZEN,)
    assert world.combiner.calls[0].quality_files == (FROZEN,)
    timer = StepTimer(world.clock)
    frozen = stack_round._TimedBaseline(world.baseline, timer)
    assert (frozen.quality_files, frozen.label_leaks) == (
        (FROZEN,),
        ("data/train.csv",),
    )
    plain = stack_round._TimedBaseline(StubBaselineRunner(_base_script()), timer)
    assert (plain.quality_files, plain.label_leaks) == ((), ())


def test_the_step_timer_sums_repeated_steps_and_never_goes_negative() -> None:
    reads = iter([10.0, 12.5, 20.0, 21.0, 30.0, 29.0])
    timer = StepTimer(lambda: next(reads))

    assert timer.timed("combine", lambda: "first") == "first"
    timer.timed("combine", lambda: None)
    timer.timed("profile", lambda: None)  # a clock that went back reads 0

    assert timer.seconds == {"combine": 3.5, "profile": 0.0}


def test_offered_keeps_and_combine_round_are_the_tails_round_combine(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """The same round combine U5b's tail runs for the last round:
    ``offered_keeps`` lists the run-set keeps on the round base;
    ``combine_round`` combines them on it, with no adoption and no record."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 2.0)]
    )
    after = _round_one(world, state)
    (verdict,) = after["verdicts"]

    assert offered_keeps(after) == [verdict]
    combined = combine_round(world.ctx, after, clock=world.clock)

    assert combined.base_commit == ORIGIN
    assert combined.offered_trial_ids == (verdict.trial_id,)
    assert combined.outcome is not None
    assert combined.outcome.kept_verdict_ids == (verdict.id,)
    assert combined.combination is not None and combined.combination.tip_commit == TIP
    assert (combined.reason, combined.seconds) == (HELD, {"combine": 2.0})
    assert world.baseline.calls == [ORIGIN] and world.stacker.calls == []
    at_tip = cast(EngineState, {**after, "base_commit": TIP})
    assert offered_keeps(at_tip) == []
    empty = combine_round(world.ctx, at_tip, clock=world.clock)
    assert (empty.outcome, empty.combination, empty.reason) == (
        None,
        None,
        NOTHING_KEPT,
    )


# ---------------------------------------------------------------------------
# Fix round (U5a review): every forwarded argument, the round base's rules,
# the original base's outputs, the combiner's notes
# ---------------------------------------------------------------------------


def test_the_timing_proxies_forward_every_argument_unchanged(
    sample_workload: Workload,
) -> None:
    """
    GIVEN a baseline runner, a calibrator and a profiler, each twice
    WHEN one copy is called directly and the other through its timing proxy
         with the same arguments
    THEN both record identical calls (every positional and keyword argument)
         and give equal results: a proxy only times
    """
    clock = _Clock()
    timer = StepTimer(clock)
    workloads = [sample_workload]
    plain, inner = (_Measuring(clock, {TIP: _base_script()}) for _ in range(2))
    direct = plain.measure(workloads, run_id="run-x", commit=TIP)
    timed = stack_round._TimedBaseline(inner, timer).measure(
        workloads, run_id="run-x", commit=TIP
    )
    assert (
        inner.raw == plain.raw == [((workloads,), {"run_id": "run-x", "commit": TIP})]
    )

    def content(rows: Sequence[Measurement]) -> list[tuple[Any, ...]]:
        return [
            (m.workload_id, m.metric, m.samples, m.output_fingerprint) for m in rows
        ]

    assert content(timed) == content(direct) and timed
    cal_plain, cal_inner = _Calibrator(clock), _Calibrator(clock)
    kwargs: dict[str, Any] = {"run_id": "run-x", "commit": TIP, "blocks": 3}
    assert stack_round._TimedCalibrator(cal_inner, timer).calibrate(
        workloads, **kwargs
    ) == cal_plain.calibrate(workloads, **kwargs)
    assert cal_inner.raw == cal_plain.raw == [((workloads,), kwargs)]
    prof_plain, prof_inner = _Profiler(clock, [TIP_HOT]), _Profiler(clock, [TIP_HOT])
    assert stack_round._TimedProfiler(prof_inner, timer).profile(
        workloads, run_id="run-x", commit=TIP
    ) == prof_plain.profile(workloads, run_id="run-x", commit=TIP)
    assert (
        prof_inner.raw
        == prof_plain.raw
        == [((workloads,), {"run_id": "run-x", "commit": TIP})]
    )
    assert set(timer.seconds) == {"baseline", "calibration", "profile"}


@pytest.mark.parametrize("files", [(), (FROZEN,)], ids=["no files", "files"])
def test_a_timed_combine_kept_makes_exactly_the_unwrapped_calls(
    make_context: Any,
    state: EngineState,
    sample_project: Project,
    files: tuple[FrozenFile, ...],
) -> None:
    """
    GIVEN two keeps whose greedy re-test fails and whose fallback holds
    WHEN ``combine_kept`` runs once on a plain combiner and once on the same
         script through the timing proxy, with and without frozen files
    THEN both combiners record the same two calls, every argument equal
         (``baseline_count`` always, ``quality_files`` only with files, as
         ``combine_kept`` passes them), and the outcomes are equal
    """
    world = _world(make_context, sample_project, ["A cache", "B hoist"], per_round=2)
    after = _round_one(world, state)
    measured = after["baseline"]
    assert measured is not None
    # The stub suite reports no count, so pin one: dropping it must show.
    rules = replace(_combine_rules(world.ctx, measured), baseline_count=7)
    trials = {t.id: t for t in after["trials"]}
    ideas = {h.id: h for h in after["hypotheses"]}
    changes = kept_changes(after["verdicts"], trials, ideas)
    target = CombineTarget(
        run_id="run-dt5a", project=sample_project, base_commit=ORIGIN,
        workloads=tuple(after["workloads"]), branch="aip/stack-run-dt5a-r1",
        round=1, quality_files=files,
    )  # fmt: skip
    script = [(TIP, 1.80, 5.0), (TIP, 0.90, 7.0)]
    plain, inner = _Merging(world.clock, script), _Merging(world.clock, script)
    timer = StepTimer(world.clock)

    direct = combine_kept(plain, changes, rules, target)
    timed = combine_kept(
        stack_round._TimedCombiner(inner, timer), changes, rules, target
    )

    assert len(plain.raw) == 2 and inner.raw == plain.raw
    keywords: dict[str, object] = {"baseline_count": rules.baseline_count}
    if files:
        keywords["quality_files"] = files
    assert [kw for _, kw in inner.raw] == [keywords, keywords]
    assert inner.raw[0][0][0] == "run-dt5a"
    assert inner.raw[0][0][4] == tuple(after["workloads"])
    assert timed == direct and timed.combination.holds
    assert timer.seconds == {"combine": 5.0, "fallback": 7.0}


def test_restack_measures_calibrates_and_profiles_the_tip_under_the_run_id(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """At the tip, the baseline runner, the calibrator and the profiler get
    the run's workloads and id, the tip, and the context's blocks: the
    same arguments as at the origin, the commit apart."""
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)]
    )
    after = _round_one(world, state)
    restack(world.ctx, after, clock=world.clock)

    workloads = after["workloads"]
    assert world.baseline.raw == [
        ((workloads,), {"run_id": "run-dt5a", "commit": c}) for c in (ORIGIN, TIP)
    ]
    assert world.calibrator is not None and world.calibrator.raw == [
        ((workloads,), {"run_id": "run-dt5a", "commit": c, "blocks": 3})
        for c in (ORIGIN, TIP)
    ]
    assert world.profiler is not None and world.profiler.raw == [
        ((workloads,), {"run_id": "run-dt5a", "commit": c}) for c in (ORIGIN, TIP)
    ]
    (combined,) = world.combiner.raw
    assert combined[0][0] == "run-dt5a" and combined[0][4] == tuple(workloads)


def test_the_round_combine_is_judged_against_the_round_bases_baseline(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN an origin calibrated at a 2 % floor, an adopted tip calibrated at
          8 %, and a round-two keep on the tip whose round combine gains 5 %
    WHEN restack runs after round two
    THEN the combine is judged by the tip's rules, so it does not hold; the
         same re-test under the origin's rules would hold (the control)
    """
    world = _world(
        make_context, sample_project, ["A cache", "C batch"],
        combines=[(TIP, 0.85, 1.0), (TIP2, 1.71, 1.0)],
        floors={ORIGIN: 0.02, TIP: 0.08},
    )  # fmt: skip
    one = _round_one(world, state)
    origin = one["baseline"]
    assert origin is not None and origin.calibration is not None
    assert origin.calibration.floor == 0.02
    one = _apply(one, restack(world.ctx, one, clock=world.clock))
    assert one["base_commit"] == TIP
    two = _through(world.ctx, one, ROUND)
    assert two["verdicts"][-1].outcome is VerdictOutcome.keep

    delta = restack(world.ctx, two, clock=world.clock)

    record = _ledger(delta).rounds[-1]
    assert record.base_commit == TIP and record.combination is not None
    assert (record.combination.holds, record.reason) == (False, DID_NOT_HOLD)
    assert "base_commit" not in delta
    trials = {t.id: t for t in two["trials"]}
    ideas = {h.id: h for h in two["hypotheses"]}
    changes = kept_changes([two["verdicts"][-1]], trials, ideas)
    target = CombineTarget(
        run_id="run-dt5a", project=sample_project, base_commit=TIP,
        workloads=tuple(two["workloads"]), branch="b", round=2,
    )  # fmt: skip
    control = _Merging(world.clock, [(TIP2, 1.71, 0.0)])
    held = combine_kept(control, changes, _combine_rules(world.ctx, origin), target)
    assert held.combination.holds


def test_the_tip_is_compared_with_the_original_base_not_the_round_base(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a ledger whose original base outputs SAME, a round base (an earlier
          tip) whose stored baseline outputs OTHER, and a held round combine
          whose tip also outputs OTHER
    WHEN restack runs
    THEN the tip is refused: its outputs are checked against the original
         base's, never the round base's (which they match)
    """
    at_origin = _world(make_context, sample_project, [])
    origin = _through(at_origin.ctx, state, LOOP[:4])["baseline"]
    assert origin is not None and origin.commit == ORIGIN
    world = _world(
        make_context, sample_project, ["O other"], combines=[(TIP2, 0.85, 1.0)],
        at={TIP: _base_script(OTHER), TIP2: _base_script(OTHER)},
    )  # fmt: skip
    after = _through(world.ctx, cast(EngineState, {**state, "base_commit": TIP}), LOOP)
    assert after["verdicts"][-1].outcome is VerdictOutcome.keep
    held = Combination(
        base_commit=ORIGIN, tip_commit=TIP, applied_trial_ids=("t-0",), holds=True,
        summary="held",
    )  # fmt: skip
    first = RoundBase(
        round=1, base_commit=ORIGIN, offered_trial_ids=("t-0",), combination=held,
        adopted=True, tip_commit=TIP, reason=HELD,
    )  # fmt: skip
    ledger = StackLedger(origin_commit=ORIGIN, origin_baseline=origin, rounds=(first,))
    hand = cast(EngineState, {**after, "stack": ledger, "round": 2})

    delta = restack(world.ctx, hand, clock=world.clock)

    record = _ledger(delta).rounds[-1]
    assert (record.round, record.base_commit, record.tip_commit) == (2, TIP, TIP2)
    assert not record.adopted and record.reason.startswith(OUTPUTS_DIFFER)
    assert "base_commit" not in delta


def test_the_round_combines_notes_are_a_combiner_notes_event(
    make_context: Any, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN a combiner whose latest call left notes (``GitCombiner.last_notes``)
    WHEN a round combine runs
    THEN its notes are one ``combiner_notes`` event, set ``stack``, as the
         combine node writes them; a round with nothing offered makes no
         combiner call, so it writes none
    """
    notes = ("workload train-step: run 2 timed out", "workload train-step: retried")
    world = _world(
        make_context, sample_project, ["A cache"], combines=[(TIP, 0.85, 1.0)] * 2,
        notes=notes,
    )  # fmt: skip
    after = _round_one(world, state)

    delta = restack(world.ctx, after, clock=world.clock)

    said = "; ".join(notes)
    noted = _event(delta, "combiner_notes")
    assert noted.data == {"code": "combiner_notes", "set": "stack", "notes": said}
    assert noted.message == f"combiner_notes: stack set: {said}"
    assert _codes(delta["events"])[0] == "combiner_notes"
    combined = combine_round(world.ctx, after, clock=world.clock)
    assert combined.notes == notes
    idle = _world(make_context, sample_project, ["L tweak"], notes=notes)
    quiet = restack(idle.ctx, _round_one(idle, state), clock=idle.clock)
    assert "combiner_notes" not in _codes(quiet["events"])
