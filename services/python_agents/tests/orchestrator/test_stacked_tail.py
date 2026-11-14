"""The stacked tail and the graph wiring (X2-DT U5b; dt-design section 1,
"Graph" and "``stacked_combine``", the U5b row of section 2 and the
section 6 note on compounds).

With ``stack_rounds`` on, ``create_graph`` routes every further round
through ``restack`` (U5a) and replaces the ``combine`` node with
``stacked_combine``: the last round's combine on the round base, then the
last held tip squashed onto the original base and re-tested there once
through the FIXED ``combine_kept``, with no fallback to an earlier tip.
Off, the graph and ``run_config`` are today's.

Swap points (the seams): ``_Runner`` stands for ``GitTrialRunner`` (the
conftest's ``StubTrialRunner`` outcomes, committed as ``t-<id>`` on the
baseline's commit; ``replay`` builds a compound the same way);
``_Baseline`` and ``_Calibrator`` for ``GitBaselineRunner`` (every call's
commit recorded, the same rows at every commit); ``FakeProfiler`` for
``CProfiler``; ``_Combiner`` for ``GitCombiner`` (it applies, or skips,
every change offered and reports a scripted tip); ``FakeStacker`` for
``GitStacker``; ``FakePreflight`` pins ``FAKE_COMMIT`` as the original
base; ``FakePublisher`` for the branch push. Runs go through the real
graph (``Orchestrator.run``); a few edge cases call ``stacked_combine``
directly on the checkpointed state just before ``combine``. Real git and
the real timings are U7's E2E and the pilot's.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Final, cast

import pytest
from langgraph.graph import END, START

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    Baseline,
    ChangeClass,
    CombineSkip,
    EngineEvent,
    FrozenFile,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCalibration,
    Objective,
    Project,
    RunStats,
    StackLedger,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.fakes import (
    FAKE_COMMIT,
    FAKE_SQUASH,
    FakePreflight,
    FakeProfiler,
    FakePublisher,
    FakeStacker,
)
from autonomous_ai_agents.execution.measure import baseline_test_count
from autonomous_ai_agents.execution.protocols import (
    CombineMeasured,
    KeptChange,
)
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.anticheat import fingerprint
from autonomous_ai_agents.optimization.judges import Judge, default_judges
from autonomous_ai_agents.orchestrator import main
from autonomous_ai_agents.orchestrator.main import (
    EngineRunResult,
    Orchestrator,
    create_graph,
    default_context,
    run_config,
)
from autonomous_ai_agents.orchestrator.nodes import NODE_NAMES, NodeContext
from autonomous_ai_agents.orchestrator.stacking import (
    STACK_NODE,
    STACKED_TIP,
    stacked_combine,
    stacked_nodes,
    stacked_router,
)
from autonomous_ai_agents.orchestrator.state import EngineState
from autonomous_ai_agents.persistence.repository import InMemoryRepository

ORIGIN: Final = FAKE_COMMIT
T1, T2, T3 = "1" * 40, "2" * 40, "3" * 40
DELIVERY_TIP: Final = "e" * 40
REVIEW_TIP: Final = "f" * 40
SQUASH: Final = FAKE_SQUASH
RUN_ID: Final = "run-dt5b"
VAL_LOSS: Final = "val_loss"
SAME: Final = fingerprint("baseline")  # the conftest's baseline output
OTHER: Final = fingerprint("something else")
FLOOR: Final = 0.05


@dataclasses.dataclass(frozen=True)
class _Idea:
    title: str
    wall: float
    path: str
    output: str = SAME
    change_class: ChangeClass = ChangeClass.efficiency
    val_loss: float = 0.500


A = _Idea("A cache", 1.05, "src/bridge/a.py")
B = _Idea("B hoist", 1.20, "src/bridge/b.py")
C = _Idea("C batch", 1.40, "src/bridge/c.py")
D = _Idea("D other output", 1.05, "src/bridge/d.py", output=OTHER)
N1 = _Idea("N1 tweak", 1.74, "src/bridge/n1.py")  # a near miss: 0.67 of the floor
N2 = _Idea("N2 pad", 1.73, "src/bridge/n2.py")  # a near miss: 0.78 of the floor
R = _Idea("R bf16", 1.50, "src/bridge/r.py", change_class=ChangeClass.behaviour,
          val_loss=0.503)  # fmt: skip
R2 = _Idea("R2 fp8", 1.50, "src/bridge/r2.py", change_class=ChangeClass.behaviour,
           val_loss=0.503)  # fmt: skip
COMPOUND: Final = _Idea("compound", 1.62, N1.path)
"""The near-miss compound's outcome: the runner's default (its title
follows the parents' random trial ids)."""


def _script(idea: _Idea) -> ScriptedOutcome:
    return ScriptedOutcome(
        touched_paths=(idea.path,),
        samples={
            METRIC_WALL_TIME_S: tuple(idea.wall + d for d in (0.0, -0.03, 0.03, 0.0, 0.0)),
            VAL_LOSS: (idea.val_loss,) * 5,
        },
        output_fingerprint=idea.output, tests_passed=True, cost_usd=0.05,
        tokens_used=1000,
    )  # fmt: skip


def _commit(trial_id: str) -> str:
    return hashlib.sha256(trial_id.encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# The seams
# ---------------------------------------------------------------------------


class _Runner:
    """The stub's trial as ``t-<hypothesis id>``, committed on the
    baseline's commit; ``replay`` (so compounds are allowed) the same."""

    def __init__(self, ideas: Sequence[_Idea]) -> None:
        scripts = {idea.title: _script(idea) for idea in ideas}
        self._inner = StubTrialRunner(scripts, default=_script(COMPOUND))
        self.calls: list[tuple[str, str, str | None]] = []

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, **kwargs: Any) -> Trial:  # fmt: skip
        self.calls.append(("run", hypothesis.title, baseline.commit))
        return self._committed(hypothesis, workloads, baseline, kwargs)

    def replay(self, hypothesis: Hypothesis, parents: Sequence[Trial],
               workloads: Sequence[Workload], baseline: Baseline,
               **kwargs: Any) -> Trial:  # fmt: skip
        self.calls.append(("replay", hypothesis.title, baseline.commit))
        return self._committed(hypothesis, workloads, baseline, kwargs)

    def _committed(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
                   baseline: Baseline, kwargs: dict[str, Any]) -> Trial:  # fmt: skip
        trial = self._inner.run(hypothesis, workloads, baseline, **kwargs)
        trial_id = f"t-{hypothesis.id}"
        return trial.model_copy(update={"id": trial_id, "commit": _commit(trial_id),
                                        "base_commit": baseline.commit})  # fmt: skip


class _Baseline:
    """The stub's rows at every commit; ``counts[commit]`` is the suite's
    passing-test count there (``tests_counted``, as ``GitBaselineRunner``
    records it), none for an unlisted commit."""

    def __init__(
        self, inner: StubBaselineRunner, counts: Mapping[str, int] | None = None
    ) -> None:
        self._inner, self._counts = inner, dict(counts or {})
        self.commits: list[str | None] = []

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        self.commits.append(commit)
        rows = self._inner.measure(workloads, run_id=run_id, commit=commit)
        count = self._counts.get(cast(str, commit))
        if count is None:
            return rows
        return tuple(
            r.model_copy(update={"hardware": {**r.hardware, "tests_counted": count}})
            if r.metric == METRIC_TESTS_PASSED
            else r
            for r in rows
        )


class _Calibrator:
    def __init__(self) -> None:
        self.commits: list[str] = []

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        self.commits.append(commit)
        gaps = {f"{w.id}:{METRIC_WALL_TIME_S}": 0.02 for w in workloads}
        return NoiseCalibration(blocks=blocks, gaps=gaps, floor=FLOOR)


@dataclasses.dataclass(frozen=True)
class _Look:
    """One scripted re-test: the tip and the B rows' wall time; ``skip``
    skips every change offered (``GitCombiner``'s "nothing left to apply")."""

    tip: str
    wall: float = 0.85
    val_loss: float = 0.500
    skip: bool = False
    conflict_last: bool = False
    """The last change offered is skipped on a merge conflict, the rest applied."""


def _rows(workload: Workload, wall: float, val_loss: float, *, suite: bool
          ) -> tuple[Measurement, ...]:  # fmt: skip
    samples = {
        METRIC_WALL_TIME_S: tuple(wall + d for d in (0.0, -0.02, 0.02, 0.0, 0.0)),
        VAL_LOSS: (val_loss,) * 5,
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
    return tuple(rows)


@dataclasses.dataclass(frozen=True)
class _Call:
    base_commit: str
    kept: tuple[tuple[str, str], ...]
    baseline_count: int | None


class _Combiner:
    """Each call takes the next ``_Look``: every change offered applied (A
    rows at 1.80 s, B rows at the look's wall) or, with ``skip``, skipped."""

    def __init__(self, looks: Sequence[_Look | Exception]) -> None:
        self._looks = list(looks)
        self.calls: list[_Call] = []
        self.last_notes: tuple[str, ...] = ()

    def combine(self, run_id: str, project: Project, base_commit: str,
                kept: Sequence[KeptChange], workloads: Sequence[Workload], *,
                baseline_count: int | None = None,
                quality_files: Sequence[FrozenFile] = ()) -> CombineMeasured:  # fmt: skip
        pairs = tuple((c.trial_id, c.commit) for c in kept)
        self.calls.append(_Call(base_commit, pairs, baseline_count))
        look = self._looks[len(self.calls) - 1]
        if isinstance(look, Exception):
            raise look
        if look.skip:
            skips = tuple(CombineSkip(trial_id=c.trial_id, reason="nothing left to apply")
                          for c in kept)  # fmt: skip
            return CombineMeasured(base_commit, (), skips, (), ())
        applied, skipped = list(kept), []
        if look.conflict_last:
            last = applied.pop()
            skipped.append(CombineSkip(trial_id=last.trial_id, reason="merge conflict",
                                       paths=("src/bridge/shared.py",)))  # fmt: skip
        return CombineMeasured(
            tip_commit=look.tip, applied=tuple(c.trial_id for c in applied),
            skipped=tuple(skipped),
            baseline=tuple(r for w in workloads for r in _rows(w, 1.80, 0.5, suite=False)),
            combined=tuple(r for w in workloads
                           for r in _rows(w, look.wall, look.val_loss, suite=True)),
        )  # fmt: skip


@dataclasses.dataclass
class _World:
    runner: _Runner
    baseline: _Baseline
    calibrator: _Calibrator
    profiler: FakeProfiler
    combiner: _Combiner
    stacker: FakeStacker
    publisher: FakePublisher
    ctx: NodeContext
    ideas: dict[str, Hypothesis]


def _hypothesis(project: Project, idea: _Idea) -> Hypothesis:
    return Hypothesis(project_id=project.id, source=HypothesisSource.playbook,
                      title=idea.title, rationale="r", change_class=idea.change_class,
                      expected_gain=0.2, provability=0.8, risk=0.1)  # fmt: skip


def _world(
    project: Project,
    workload: Workload,
    ideas: Sequence[_Idea],
    looks: Sequence[_Look | Exception],
    *,
    per_round: int = 1,
    stacker: FakeStacker | None = None,
    compounds: bool = False,
    stack: bool = True,
    counts: Mapping[str, int] | None = None,
    preflight: FakePreflight | None = None,
    judges: Sequence[Judge] = (),
) -> _World:
    hypotheses = {idea.title: _hypothesis(project, idea) for idea in ideas}
    hotspot = Hotspot(project_id=project.id, workload_id=workload.id,
                      file_path=A.path, symbol="encode", line_start=10,
                      self_time_s=0.8, total_time_s=1.2, share=0.6)  # fmt: skip
    runner = _Runner(ideas)
    baseline = _Baseline(StubBaselineRunner(_base_script()), counts)
    calibrator = _Calibrator()
    profiler = FakeProfiler((hotspot,))
    combiner = _Combiner(looks)
    paths = {(ORIGIN, tip): (A.path,) for tip in (T1, T2, T3)}
    stacker = FakeStacker(paths=paths) if stacker is None else stacker
    publisher = FakePublisher("diff --git a/x b/x\n")
    ctx = NodeContext(
        runner=runner, baseline_runner=baseline,
        judges=(*default_judges(2.0, quality=None), *judges),
        repository=InMemoryRepository(), candidates=tuple(hypotheses.values()),
        preflight=preflight or FakePreflight(), profiler=profiler, combiner=combiner,
        publisher=publisher, default_output_check=True, calibrator=calibrator,
        calibration_blocks=3, portfolio_rounds=3, max_hypotheses_per_round=per_round,
        near_miss_compounds=compounds, stack_rounds=stack,
        stacker=stacker if stack else None,
    )  # fmt: skip
    return _World(runner, baseline, calibrator, profiler, combiner, stacker,
                  publisher, ctx, hypotheses)  # fmt: skip


def _base_script() -> ScriptedOutcome:
    return ScriptedOutcome(
        samples={METRIC_WALL_TIME_S: (1.80, 1.75, 1.85, 1.80, 1.80),
                 VAL_LOSS: (0.500,) * 5},
        tests_passed=True, output_fingerprint=SAME,
    )  # fmt: skip


@dataclasses.dataclass(frozen=True)
class _Ran:
    result: EngineRunResult
    orchestrator: Orchestrator
    visits: tuple[str, ...]
    configs: tuple[dict[str, object], ...]

    @property
    def state(self) -> EngineState:
        return self.result.state

    @property
    def ledger(self) -> StackLedger:
        ledger = self.state["stack"]
        assert isinstance(ledger, StackLedger)
        return ledger

    def before_combine(self) -> EngineState:
        """The checkpointed state the ``combine`` node ran on."""
        history = self.orchestrator.graph.get_state_history(
            {"configurable": {"thread_id": RUN_ID}}
        )
        (snap,) = [s for s in history if s.next == ("combine",)]
        return cast(EngineState, dict(snap.values))


@pytest.fixture
def run_world(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Run a world through the real graph, ``run_config`` spied."""

    def go(world: _World, *, max_rounds: int = 3) -> _Ran:
        configs: list[dict[str, object]] = []
        real = main.run_config

        def spied(*args: Any, **kwargs: Any) -> Any:
            config = real(*args, **kwargs)
            configs.append({"args": args, "kwargs": kwargs, "result": config})
            return config

        monkeypatch.setattr(main, "run_config", spied)
        orchestrator = Orchestrator(context=world.ctx)
        result = orchestrator.run(
            sample_project, [sample_workload], [sample_objective], sample_guardrails,
            run_id=RUN_ID, max_rounds=max_rounds, max_cost_usd=10.0,
        )  # fmt: skip
        history = orchestrator.graph.get_state_history(
            {"configurable": {"thread_id": RUN_ID}}
        )
        visits = tuple(n for snap in reversed(list(history)) for n in snap.next)
        return _Ran(result, orchestrator, visits, tuple(configs))

    return go


def _verdict(state: EngineState, world: _World, idea: _Idea) -> Verdict:
    hypothesis_id = world.ideas[idea.title].id
    (found,) = [v for v in state["verdicts"] if v.hypothesis_id == hypothesis_id]
    return found


def _trial(state: EngineState, world: _World, idea: _Idea) -> Trial:
    trial_id = f"t-{world.ideas[idea.title].id}"
    (found,) = [t for t in state["trials"] if t.id == trial_id]
    return found


def _coded(state: EngineState, code: str) -> list[EngineEvent]:
    return [e for e in state["events"] if e.data.get("code") == code]


def _stack_calls(world: _World) -> list[tuple[str, str, str]]:
    return [(c.method, c.base, c.tip) for c in world.stacker.calls]


THREE_ROUNDS: Final = (_Look(T1), _Look(T2), _Look(T3), _Look(DELIVERY_TIP))


# ---------------------------------------------------------------------------
# A three-round stacked run end to end
# ---------------------------------------------------------------------------


def test_three_stacked_rounds_deliver_the_last_tip_squashed_onto_the_origin(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN three rounds, one keep each (A, B, C), every combine holding
    WHEN the stacked run goes through the real graph
    THEN round 2's trial starts at T1 and round 3's at T2 (both adopted by
         restack, measured, calibrated and profiled there); the tail combines
         round 3's keep on T2, checks the T3 diff, squashes T3 onto the
         origin and re-tests that one change there against the origin's
         rules; the run delivers all three keeps from the origin with
         ``all_rounds_held``, and the graph and its config are the stacked ones
    """
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS)
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]

    assert [(c.base_commit, [t for t, _ in c.kept]) for c in world.combiner.calls] == [
        (ORIGIN, [_trial(state, world, A).id]),
        (T1, [_trial(state, world, B).id]),
        (T2, [_trial(state, world, C).id]),
        (ORIGIN, [STACKED_TIP]),
    ]
    assert world.combiner.calls[3].kept == ((STACKED_TIP, SQUASH),)
    assert [_trial(state, world, i).base_commit for i in (A, B, C)] == [ORIGIN, T1, T2]
    assert world.baseline.commits == [ORIGIN, T1, T2]
    assert world.calibrator.commits == [ORIGIN, T1, T2]
    assert [c.commit for c in world.profiler.calls] == [ORIGIN, T1, T2]
    assert _stack_calls(world) == [
        ("diff", ORIGIN, T1), ("diff", T1, T2),
        ("changed_paths", ORIGIN, T3), ("squash", ORIGIN, T3),
    ]  # fmt: skip
    assert world.stacker.calls[-1].label == RUN_ID
    assert [(p.branch, p.tip, p.base) for p in world.publisher.calls] == [
        (f"engine/run-{RUN_ID}", DELIVERY_TIP, ORIGIN)
    ]

    assert state["base_commit"] == ORIGIN
    origin = ran.ledger.origin_baseline
    assert state["baseline"] == origin and origin.commit == ORIGIN
    kept = [_verdict(state, world, i).id for i in (A, B, C)]
    assert state["kept_verdict_ids"] == kept
    combination = state["combination"]
    assert combination is not None and combination.holds
    assert combination.base_commit == ORIGIN and combination.tip_commit == DELIVERY_TIP
    assert combination.applied_trial_ids == tuple(
        _trial(state, world, i).id for i in (A, B, C)
    )
    assert combination.fallback_trial_id is None
    delivery = ran.ledger.delivery
    assert delivery is not None and combination.judge_results == delivery.judge_results

    ledger = ran.ledger
    assert [(r.round, r.base_commit, r.adopted, r.tip_commit, r.reason)
            for r in ledger.rounds] == [
        (1, ORIGIN, True, T1, "held"), (2, T1, True, T2, "held"),
        (3, T2, False, None, "held"),
    ]  # fmt: skip
    last = ledger.rounds[-1].combination
    assert last is not None and last.tip_commit == T3
    assert ledger.delivery is not None and ledger.delivery.holds
    assert ledger.delivery.applied_trial_ids == (STACKED_TIP,)
    assert ledger.delivery_seconds is not None and ledger.delivery_seconds >= 0
    assert ledger.all_rounds_held is True
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["holds"] is True and delivered.data["squash"] == SQUASH
    assert [e.data["round"] for e in _coded(state, "stack_round")] == [1, 2, 3]
    assert _coded(state, "stack_compound_skipped") == []  # compounds are off

    assert ran.visits.count("hypotheses") == 3
    assert ran.visits.count(STACK_NODE) == 2
    assert ran.visits[-4:] == ("combine", "deliver", "learn", "watch")
    index = ran.visits.index(STACK_NODE)
    assert ran.visits[index - 1 : index + 2] == ("verdicts", STACK_NODE, "hypotheses")
    assert [(c["args"], c["kwargs"]) for c in ran.configs] == [
        ((RUN_ID, 3), {"stacked": True})
    ]


def test_the_delivery_retest_does_not_hold_and_nothing_falls_back(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN three held rounds whose squashed tip shows no gain on the origin
    THEN the one re-test is the only delivery look (no fallback, no earlier
         tip), nothing is kept, the run delivers the report only, and the
         ledger records that the re-test failed although every round held
    """
    looks = (*THREE_ROUNDS[:3], _Look(DELIVERY_TIP, wall=1.80))
    world = _world(sample_project, sample_workload, (A, B, C), looks)
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert len(world.combiner.calls) == 4
    assert state["kept_verdict_ids"] == []
    assert world.publisher.calls == []
    combination = state["combination"]
    assert combination is not None and not combination.holds
    assert len(combination.applied_trial_ids) == 3  # the tip held them, judged as one
    assert ran.ledger.delivery is not None and not ran.ledger.delivery.holds
    assert ran.ledger.all_rounds_held is True
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["holds"] is False
    assert state["base_commit"] == ORIGIN


@pytest.mark.parametrize(
    ("stacker", "said"),
    [
        (FakeStacker(squash=EngineError("tip does not descend from the base"),
                     paths={(ORIGIN, T3): (A.path,)}),
         "tip does not descend from the base"),
        (FakeStacker(paths={(ORIGIN, T3): (A.path, "tests/test_cache.py")}),
         "protected"),
        (FakeStacker(paths={(ORIGIN, T3): EngineError("diff truncated")}),
         "diff truncated"),
    ],
    ids=["squash-refused", "protected-path", "truncated-diff"],
)  # fmt: skip
def test_a_stacked_delivery_that_cannot_be_checked_fails_the_run(
    sample_project: Project,
    sample_workload: Workload,
    run_world: Any,
    stacker: FakeStacker,
    said: str,
) -> None:
    """
    GIVEN three held rounds
    WHEN the squash is refused, the origin..tip diff touches a protected
         path, or that diff cannot be read
    THEN the run fails closed before any delivery re-test or publish
    """
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS,
                   stacker=stacker)  # fmt: skip
    ran = run_world(world)
    assert ran.result.status == "failed"
    assert said in str(ran.state["error"])
    assert len(world.combiner.calls) == 3
    assert world.publisher.calls == []
    squashes = [c for c in stacker.calls if c.method == "squash"]
    assert len(squashes) == (1 if said.startswith("tip") else 0)


def test_a_tip_with_no_net_change_is_not_squashed_or_retested(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN held rounds whose last tip's tree equals the origin's (no changed
          paths: its squash would be an empty commit)
    THEN no squash and no delivery re-test run, nothing is kept, and the
         ``stack_delivery`` event says why
    """
    stacker = FakeStacker(paths={(ORIGIN, T3): ()})
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS,
                   stacker=stacker)  # fmt: skip
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert [c.method for c in stacker.calls][-1] == "changed_paths"
    assert len(world.combiner.calls) == 3
    assert state["kept_verdict_ids"] == [] and state["combination"] is None
    assert ran.ledger.delivery is None and ran.ledger.all_rounds_held is True
    (delivered,) = _coded(state, "stack_delivery")
    assert "changes nothing" in delivered.message
    assert delivered.data["retest"] is False


def test_a_combiner_that_applies_nothing_of_the_squash_delivers_nothing(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN the squash is skipped by the combiner ("nothing left to apply",
          U2's empty-commit case), in the re-test and its fallback alike
    THEN the combination applies nothing and claims none of the rounds'
         trials, no fallback names the synthetic change, and nothing is kept
    """
    looks = (*THREE_ROUNDS[:3], _Look(ORIGIN, skip=True), _Look(ORIGIN, skip=True))
    world = _world(sample_project, sample_workload, (A, B, C), looks)
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    combination = state["combination"]
    assert combination is not None and not combination.holds
    assert combination.applied_trial_ids == () and combination.skipped == ()
    assert combination.fallback_trial_id is None
    assert state["kept_verdict_ids"] == []
    delivery = ran.ledger.delivery
    assert delivery is not None and delivery.fallback_trial_id == STACKED_TIP


# ---------------------------------------------------------------------------
# Equivalence against both bases; the last round with nothing on its base
# ---------------------------------------------------------------------------


def test_a_tip_round_trial_is_checked_against_both_bases(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1 keeps A (adopted at T1) and round 2's D changes the output
    THEN D, measured at T1, is rejected by the frozen judge against T1's
         twin and carries the ``original base:`` violation too; the last
         round has nothing kept on T1, so the tail squashes the current base
         T1 and re-tests it against the origin, delivering A alone
    """
    looks = (_Look(T1), _Look(DELIVERY_TIP))
    world = _world(sample_project, sample_workload, (A, D), looks)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    rejected = _verdict(state, world, D)
    assert rejected.outcome is VerdictOutcome.reject
    messages = [v.message for v in rejected.violations]
    assert "original base: workload " in messages[0]  # against the origin
    (twin,) = [r for r in rejected.judge_results if r.judge == "equivalence"]
    assert twin.outcome is JudgeOutcome.failed  # the frozen judge, against T1
    assert ran.ledger.rounds[0].adopted  # T1's own outputs were the origin's
    assert _trial(state, world, D).base_commit == T1
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN, ORIGIN]
    assert world.combiner.calls[1].kept == ((STACKED_TIP, SQUASH),)
    assert _stack_calls(world)[-2:] == [("changed_paths", ORIGIN, T1),
                                        ("squash", ORIGIN, T1)]  # fmt: skip
    origin = ran.ledger.origin_baseline
    assert world.combiner.calls[1].baseline_count == baseline_test_count(
        origin.measurements
    )
    last = ran.ledger.rounds[-1]
    assert (last.round, last.base_commit, last.reason) == (2, T1, "nothing kept")
    assert state["kept_verdict_ids"] == [_verdict(state, world, A).id]
    combination = state["combination"]
    assert combination is not None
    assert combination.applied_trial_ids == (_trial(state, world, A).id,)
    assert ran.ledger.all_rounds_held is True


# ---------------------------------------------------------------------------
# One round on the origin: today's combine, no second re-test
# ---------------------------------------------------------------------------


def test_a_held_combine_on_the_origin_is_the_delivery_retest(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN one round whose combine holds on the origin
    THEN no restack, no squash and no second re-test: the round combine is
         the delivery, and its tip is published from the origin
    """
    world = _world(sample_project, sample_workload, (A,), (_Look(DELIVERY_TIP),))
    ran = run_world(world, max_rounds=1)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert STACK_NODE not in ran.visits
    assert world.stacker.calls == []
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN]
    assert state["kept_verdict_ids"] == [_verdict(state, world, A).id]
    assert [(p.tip, p.base) for p in world.publisher.calls] == [(DELIVERY_TIP, ORIGIN)]
    ledger = ran.ledger
    assert ledger.delivery is None and ledger.delivery_seconds is None
    assert ledger.all_rounds_held is True
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["retest"] is False and delivered.data["holds"] is True
    assert [(c["args"], c["kwargs"]) for c in ran.configs] == [
        ((RUN_ID, 1), {"stacked": True})
    ]


def test_nothing_kept_anywhere_delivers_the_report_only(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN two rounds with no keep
    THEN no combiner, no stacker, no publish; ``all_rounds_held`` is None
    """
    world = _world(sample_project, sample_workload, (N1, N2), ())
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert world.combiner.calls == [] and world.stacker.calls == []
    assert state["kept_verdict_ids"] == [] and state["combination"] is None
    assert [r.reason for r in ran.ledger.rounds] == ["nothing kept", "nothing kept"]
    assert ran.ledger.all_rounds_held is None
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.level.value == "info" and delivered.data["tip"] is None


def test_a_round_that_did_not_hold_on_the_origin_leaves_nothing_to_deliver(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN one round whose combine (and its fallback) does not hold on the origin
    THEN nothing is delivered and ``all_rounds_held`` is False
    """
    looks = (_Look(DELIVERY_TIP, wall=1.80), _Look(DELIVERY_TIP, wall=1.80))
    world = _world(sample_project, sample_workload, (A, B), looks, per_round=2)
    ran = run_world(world, max_rounds=1)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert world.stacker.calls == [] and world.publisher.calls == []
    assert state["kept_verdict_ids"] == []
    combination = state["combination"]
    assert combination is not None and not combination.holds
    assert ran.ledger.all_rounds_held is False
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.level.value == "warning"


# ---------------------------------------------------------------------------
# The review set: combined from the origin only
# ---------------------------------------------------------------------------


def test_only_origin_review_changes_are_combined_from_the_origin(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1 (origin) keeps A and has R to review; round 2 (at T1)
          keeps B and has R2 to review
    THEN the review set is R alone, combined from the origin on its own
         branch; R2 gets a ``stack_review_skipped`` note
    """
    looks = (_Look(T1), _Look(T2), _Look(DELIVERY_TIP),
             _Look(REVIEW_TIP, wall=1.50, val_loss=0.503))  # fmt: skip
    world = _world(sample_project, sample_workload, (A, R, B, R2), looks, per_round=2)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert _verdict(state, world, R).outcome is VerdictOutcome.review
    assert _verdict(state, world, R2).outcome is VerdictOutcome.review
    review_call = world.combiner.calls[3]
    assert review_call.base_commit == ORIGIN
    assert [t for t, _ in review_call.kept] == [_trial(state, world, R).id]
    review = state["review_combination"]
    assert review is not None and review.holds
    assert review.applied_trial_ids == (_trial(state, world, R).id,)
    (skipped,) = _coded(state, "stack_review_skipped")
    assert skipped.data["trial"] == _trial(state, world, R2).id
    assert skipped.data["base"] == T1
    assert [p.branch for p in world.publisher.calls] == [
        f"engine/run-{RUN_ID}",
        f"engine/review-{RUN_ID}",
    ]


def test_the_combiner_notes_of_each_stacked_set_are_recorded(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN a combiner that leaves notes on every call (``GitCombiner.last_notes``)
    THEN restack's round combine, the delivery re-test and the review set
         each record them, as the combine node does for its sets
    """
    looks = (_Look(T1), _Look(T2), _Look(DELIVERY_TIP),
             _Look(REVIEW_TIP, wall=1.50, val_loss=0.503))  # fmt: skip
    world = _world(sample_project, sample_workload, (A, R, B, R2), looks, per_round=2)
    world.combiner.last_notes = ("ran under taskset",)
    ran = run_world(world, max_rounds=2)
    assert ran.result.status == "done", ran.state["error"]
    noted = _coded(ran.state, "combiner_notes")
    assert [e.data["set"] for e in noted] == ["stack", "stack", "run", "review"]
    assert {e.data["notes"] for e in noted} == {"ran under taskset"}


def test_a_review_set_entirely_off_the_origin_is_not_combined(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1 keeps A (adopted at T1); round 2 has only R2 to review
    THEN no review combine runs; R2 is noted as skipped
    """
    looks = (_Look(T1), _Look(DELIVERY_TIP))
    world = _world(sample_project, sample_workload, (A, R2), looks)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert len(world.combiner.calls) == 2
    assert state["review_combination"] is None
    assert len(_coded(state, "stack_review_skipped")) == 1


# ---------------------------------------------------------------------------
# Routing: a near-miss pair alone never leads into an empty round
# ---------------------------------------------------------------------------


def test_a_compound_alone_routes_to_combine_when_the_base_can_move(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1 keeps A and leaves two near misses, nothing else to try
    WHEN the router would continue only for their compound
    THEN it goes to combine: the round combine on the origin could move the
         base and drop the pair's parents, so no round starts for it
    """
    world = _world(sample_project, sample_workload, (A, N1, N2),
                   (_Look(DELIVERY_TIP),), per_round=3, compounds=True)  # fmt: skip
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert [_verdict(state, world, n).outcome for n in (N1, N2)] == [
        VerdictOutcome.inconclusive,
        VerdictOutcome.inconclusive,
    ]
    assert STACK_NODE not in ran.visits
    assert ran.visits.count("hypotheses") == 1
    assert [kind for kind, _, _ in world.runner.calls] == ["run", "run", "run"]
    assert state["kept_verdict_ids"] == [_verdict(state, world, A).id]
    (dropped,) = _coded(state, "stack_compound_skipped")  # what the rule cost
    parents = {_trial(state, world, n).id for n in (N1, N2)}
    assert set(str(dropped.data["parents"]).split(",")) == parents
    assert dropped.level.value == "info" and dropped.data["base"] == ORIGIN
    assert N1.title in dropped.message and N2.title in dropped.message


def test_a_compound_alone_still_runs_while_the_base_cannot_move(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1 leaves two near misses and no keep (nothing to combine, so
          the base stays)
    THEN the router continues, restack records nothing kept, and round 2
         replays their compound on the origin, which is then delivered
    """
    world = _world(sample_project, sample_workload, (N1, N2),
                   (_Look(DELIVERY_TIP),), per_round=2, compounds=True)  # fmt: skip
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert ran.visits.count(STACK_NODE) == 1
    kind, title, at = world.runner.calls[-1]
    assert (kind, at) == ("replay", ORIGIN) and title.startswith("compound: ")
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN]
    assert len(state["kept_verdict_ids"]) == 1
    assert [r.reason for r in ran.ledger.rounds] == ["nothing kept", "held"]


def test_the_stacked_router_keeps_every_other_route(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """The wrapper changes only a compound-only ``hypotheses``: a run with
    candidates left still restacks (the three-round run), and a finished
    round goes to combine as today."""
    world = _world(sample_project, sample_workload, (A, B), (_Look(T1), _Look(T2),
                   _Look(DELIVERY_TIP)))  # fmt: skip
    ran = run_world(world, max_rounds=2)
    route = stacked_router(world.ctx)
    assert route(ran.before_combine()) == "combine"
    assert ran.visits.count(STACK_NODE) == 1


# ---------------------------------------------------------------------------
# stacked_combine on a crafted state: the ledger chain and its guards
# ---------------------------------------------------------------------------


@pytest.fixture
def three(sample_project: Project, sample_workload: Workload, run_world: Any) -> Any:
    """A finished three-round run and a fresh world to call the tail with."""
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS)
    ran = run_world(world)
    assert ran.result.status == "done", ran.state["error"]
    fresh = _world(sample_project, sample_workload, (A, B, C),
                   (_Look(T3), _Look(DELIVERY_TIP)))  # fmt: skip
    return ran, fresh


def test_the_tail_refuses_a_base_off_the_ledger_chain(three: Any) -> None:
    ran, fresh = three
    state = ran.before_combine()
    state["base_commit"] = T1  # the ledger's current base is T2
    with pytest.raises(EngineError, match="not the stack ledger's current base"):
        stacked_combine(fresh.ctx, state)
    assert fresh.combiner.calls == []


def test_the_tail_refuses_a_closed_ledger(three: Any) -> None:
    ran, fresh = three
    state = ran.before_combine()
    ledger = state["stack"]
    assert ledger is not None
    state["stack"] = ledger.closed(None, None)
    with pytest.raises(EngineError, match="already closed"):
        stacked_combine(fresh.ctx, state)


def test_the_tail_refuses_an_applied_trial_without_a_kept_verdict(three: Any) -> None:
    """An adopted round's applied trial must still be a run-set keep: the
    delivered ids are never guessed."""
    ran, fresh = three
    state = ran.before_combine()
    ledger = state["stack"]
    assert ledger is not None and ledger.rounds[0].combination is not None
    (a_trial,) = ledger.rounds[0].combination.applied_trial_ids  # round 1's keep
    state["verdicts"] = [v for v in state["verdicts"] if v.trial_id != a_trial]
    with pytest.raises(EngineError, match="no kept verdict"):
        stacked_combine(fresh.ctx, state)


def test_the_tail_needs_a_stacking_context(three: Any) -> None:
    ran, fresh = three
    off = dataclasses.replace(fresh.ctx, stack_rounds=False)
    with pytest.raises(EngineError, match="stacked rounds"):
        stacked_combine(off, ran.before_combine())


def test_the_tail_times_the_delivery_retest_with_the_injected_clock(
    three: Any,
) -> None:
    ran, fresh = three
    ticks = iter(float(n) for n in range(100))
    delta = stacked_combine(fresh.ctx, ran.before_combine(), clock=lambda: next(ticks))
    ledger = delta["stack"]
    assert isinstance(ledger, StackLedger)
    assert ledger.delivery_seconds == 1.0
    assert ledger.rounds[-1].seconds == {"combine": 1.0}


# ---------------------------------------------------------------------------
# The graph: stacked wiring, today's topology and config when off
# ---------------------------------------------------------------------------


def _edges(context: NodeContext) -> set[tuple[str, str, bool]]:
    drawn = create_graph(context=context).get_graph()
    return {(e.source, e.target, e.conditional) for e in drawn.edges}


def test_the_default_topology_is_node_names() -> None:
    graph = create_graph(context=default_context())
    assert tuple(n for n in graph.nodes if n != START) == NODE_NAMES
    edges = _edges(default_context())
    assert ("verdicts", "hypotheses", True) in edges
    assert not any(STACK_NODE in edge for edge in edges)


def test_the_stacked_topology_adds_restack_before_each_further_round(
    sample_project: Project, sample_workload: Workload
) -> None:
    world = _world(sample_project, sample_workload, (A,), ())
    graph = create_graph(context=world.ctx)
    assert tuple(n for n in graph.nodes if n != START) == (*NODE_NAMES, STACK_NODE)
    edges = _edges(world.ctx)
    off = _edges(dataclasses.replace(world.ctx, stack_rounds=False, stacker=None))
    assert edges - off == {
        ("verdicts", STACK_NODE, True),
        (STACK_NODE, "hypotheses", False),
    }
    assert off - edges == {("verdicts", "hypotheses", True)}
    assert ("watch", END, False) in edges


def test_stacked_nodes_replace_combine_and_add_restack(
    sample_project: Project, sample_workload: Workload
) -> None:
    world = _world(sample_project, sample_workload, (A,), ())
    nodes = {name: object() for name in NODE_NAMES}
    stacked = stacked_nodes(world.ctx, nodes)  # type: ignore[arg-type]
    assert tuple(stacked) == (*NODE_NAMES, STACK_NODE)
    assert stacked["combine"] is not nodes["combine"]
    assert all(stacked[n] is nodes[n] for n in NODE_NAMES if n != "combine")
    off = dataclasses.replace(world.ctx, stack_rounds=False, stacker=None)
    with pytest.raises(ValueError, match="stack_rounds"):
        stacked_nodes(off, nodes)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_rounds", [1, 3, 60])
def test_run_config_adds_a_restack_visit_per_further_round(max_rounds: int) -> None:
    off = run_config("run-7", max_rounds)
    assert off == {"configurable": {"thread_id": "run-7"},
                   "recursion_limit": 11 + 4 * max_rounds + 5}  # fmt: skip
    assert run_config("run-7", max_rounds, stacked=False) == off
    stacked = run_config("run-7", max_rounds, stacked=True)
    assert stacked == {"configurable": {"thread_id": "run-7"},
                       "recursion_limit": 11 + 5 * max_rounds - 1 + 5}  # fmt: skip


def test_the_orchestrator_passes_no_stacked_keyword_when_off(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    world = _world(sample_project, sample_workload, (A,), (_Look(DELIVERY_TIP),),
                   stack=False)  # fmt: skip
    ran = run_world(world, max_rounds=1)
    assert ran.result.status == "done", ran.state["error"]
    assert [(c["args"], c["kwargs"]) for c in ran.configs] == [((RUN_ID, 1), {})]
    assert ran.state["stack"] is None


NOVEL = _Idea("N novel", 1.05, "src/bridge/novel.py", change_class=ChangeClass.novel)


def test_a_resume_without_stacking_refuses_an_open_stack_ledger(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN a stacked run paused at the approval gate after round 1's tip was
          adopted (its ledger open, the base at T1)
    WHEN it is resumed by an orchestrator whose context does not stack
    THEN the resume is refused before any node runs: that context would
         deliver from the tip with no squash and no re-test from the origin;
         the stacking orchestrator then resumes it and delivers from the origin
    """
    looks = (_Look(T1), _Look(T2), _Look(DELIVERY_TIP))
    world = _world(sample_project, sample_workload, (A, NOVEL), looks)
    ran = run_world(world, max_rounds=2)
    assert ran.result.status == "needs_approval", ran.state["error"]
    paused = ran.state["stack"]
    assert paused is not None and paused.current_base == T1
    off = dataclasses.replace(world.ctx, stack_rounds=False, stacker=None)
    other = Orchestrator(context=off, checkpointer=ran.orchestrator.checkpointer)
    decision = ApprovalDecision(
        approved_verdict_ids=tuple(ran.state["pending_approval_ids"]), approver="pk"
    )
    with pytest.raises(EngineError, match="open stack ledger"):
        other.resume(RUN_ID, decision)
    assert len(world.combiner.calls) == 1 and world.publisher.calls == []

    done = ran.orchestrator.resume(RUN_ID, decision)
    assert done.status == "done", done.state["error"]
    assert done.state["base_commit"] == ORIGIN
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN, T1, ORIGIN]
    assert len(done.state["kept_verdict_ids"]) == 2


# ---------------------------------------------------------------------------
# U5b review: delivered rounds only, the origin's rules, extra protection,
# the review accept, skips, and the three missing scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wall", "holds"),
    [(0.85, True), (1.80, False)],
    ids=["delivery-holds", "delivery-fails"],
)
def test_a_last_round_that_does_not_hold_on_a_moved_base_is_not_delivered(
    sample_project: Project,
    sample_workload: Workload,
    run_world: Any,
    wall: float,
    holds: bool,
) -> None:
    """
    GIVEN round 1 adopted at T1, then round 2's keep B does not hold on T1
    THEN the tail squashes T1 (the current base), not round 2's tip; the
         combination names A alone, B is never claimed or kept, and
         ``all_rounds_held`` is False whether the delivery holds or not
    """
    looks = (_Look(T1), _Look(T2, wall=1.80), _Look(DELIVERY_TIP, wall=wall))
    world = _world(sample_project, sample_workload, (A, B), looks)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN, T1, ORIGIN]
    assert _stack_calls(world)[-2:] == [("changed_paths", ORIGIN, T1),
                                        ("squash", ORIGIN, T1)]  # fmt: skip
    combination = state["combination"]
    assert combination is not None and combination.holds is holds
    assert combination.applied_trial_ids == (_trial(state, world, A).id,)
    kept = [_verdict(state, world, A).id] if holds else []
    assert state["kept_verdict_ids"] == kept
    assert _verdict(state, world, B).id not in state["kept_verdict_ids"]
    assert [r.reason for r in ran.ledger.rounds] == ["held", "did not hold"]
    assert ran.ledger.all_rounds_held is False
    assert len(world.publisher.calls) == (1 if holds else 0)


def test_a_held_but_refused_round_is_not_delivered_after_a_later_adoption(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1's combine holds at T1 but the tip is refused (its diff
          cannot be read), round 2 re-offers A with B on the origin and is
          adopted at T2, round 3 keeps C on T2
    THEN the delivery names A, B and C once each: round 1's held combine
         (refused, never adopted) is not one of the delivered rounds
    """
    stacker = FakeStacker(diffs={(ORIGIN, T1): EngineError("no diff")},
                          paths={(ORIGIN, T3): (A.path,)})  # fmt: skip
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS,
                   stacker=stacker)  # fmt: skip
    ran = run_world(world)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    rounds = ran.ledger.rounds
    assert [(r.base_commit, r.adopted) for r in rounds] == [
        (ORIGIN, False), (ORIGIN, True), (T2, False)
    ]  # fmt: skip
    assert rounds[0].reason.startswith("the tip's diff could not be read")
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN, ORIGIN, T2, ORIGIN]
    trials = [_trial(state, world, i).id for i in (A, B, C)]
    assert {t for t, _ in world.combiner.calls[1].kept} == set(trials[:2])
    combination = state["combination"]
    assert combination is not None and combination.holds
    assert sorted(combination.applied_trial_ids) == sorted(trials)
    kept = state["kept_verdict_ids"]
    assert sorted(kept) == sorted(_verdict(state, world, i).id for i in (A, B, C))


def test_a_refused_tip_then_a_failing_last_round_on_the_origin(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN round 1's held tip is refused, so the last round combines A and B
          on the origin again, and that combine and its fallback fail
    THEN the last round is the delivery (no squash, no second re-test),
         nothing is kept or published, and ``all_rounds_held`` is False
    """
    stacker = FakeStacker(diffs={(ORIGIN, T1): EngineError("no diff")})
    looks = (_Look(T1), _Look(T2, wall=1.80), _Look(T2, wall=1.80))
    world = _world(sample_project, sample_workload, (A, B), looks, stacker=stacker)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    assert [c.base_commit for c in world.combiner.calls] == [ORIGIN] * 3
    assert [c.method for c in stacker.calls] == ["diff"]
    assert world.publisher.calls == [] and state["kept_verdict_ids"] == []
    combination = state["combination"]
    assert combination is not None and not combination.holds
    ledger = ran.ledger
    assert [
        (r.base_commit, r.adopted, r.reason.split(":")[0]) for r in ledger.rounds
    ] == [
        (ORIGIN, False, "the tip's diff could not be read"),
        (ORIGIN, False, "did not hold"),
    ]
    assert ledger.delivery is None and ledger.all_rounds_held is False
    (delivered,) = _coded(state, "stack_delivery")
    assert delivered.data["retest"] is False and delivered.level.value == "warning"


def test_the_delivery_and_review_are_judged_by_the_origin_baselines_rules(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN the suite counts 40 passing tests at the origin and 41 at T1
    THEN the round combine on T1 is held to T1's count, while the delivery
         re-test and the review set (both from the origin) are held to the
         origin's 40, never the tip's
    """
    looks = (_Look(T1), _Look(T2), _Look(DELIVERY_TIP),
             _Look(REVIEW_TIP, wall=1.50, val_loss=0.503))  # fmt: skip
    world = _world(sample_project, sample_workload, (A, R, B, R2), looks, per_round=2,
                   counts={ORIGIN: 40, T1: 41})  # fmt: skip
    ran = run_world(world, max_rounds=2)
    assert ran.result.status == "done", ran.state["error"]
    calls = world.combiner.calls
    assert [(c.base_commit, c.baseline_count) for c in calls] == [
        (ORIGIN, 40), (T1, 41), (ORIGIN, 40), (ORIGIN, 40)
    ]  # fmt: skip
    assert calls[2].kept == ((STACKED_TIP, SQUASH),)
    assert ran.state["baseline"] == ran.ledger.origin_baseline


def test_extra_protected_paths_guard_the_stacked_diff(
    sample_project: Project,
    sample_workload: Workload,
    sample_guardrails: tuple[Guardrail, ...],
    run_world: Any,
) -> None:
    """
    GIVEN preflight protects one more path, which only the origin..T3 diff
          touches (no single trial did)
    THEN the run fails closed before the squash
    """
    extra = "src/bridge/frozen_table.py"
    echo = FakePreflight().check(sample_project, [sample_workload], sample_guardrails)
    preflight = FakePreflight(dataclasses.replace(echo, extra_protected=(extra,)))
    stacker = FakeStacker(paths={(ORIGIN, T3): (A.path, extra)})
    world = _world(sample_project, sample_workload, (A, B, C), THREE_ROUNDS,
                   stacker=stacker, preflight=preflight)  # fmt: skip
    ran = run_world(world)
    assert ran.result.status == "failed"
    assert "protected" in str(ran.state["error"]) and extra in str(ran.state["error"])
    assert [c.method for c in stacker.calls][-1] == "changed_paths"
    assert len(world.combiner.calls) == 3


class _ReviewMarker:
    """A judge that marks the review set's re-test (its transient trial is
    on the review branch) as an output change, so the combined verdict is
    ``review``; every other trial it passes without a mark."""

    @property
    def name(self) -> str:
        return "review-marker"

    def applies_to(self, objective: Objective) -> bool:
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        marked = trial.branch == f"engine/review-{RUN_ID}"
        return JudgeResult(judge=self.name, outcome=JudgeOutcome.passed,
                           reason="marks the review re-test",
                           output_changed=True if marked else None)  # fmt: skip


def test_the_review_set_holds_on_a_review_verdict(
    sample_project: Project, sample_workload: Workload, run_world: Any
) -> None:
    """
    GIVEN the review set's combined re-test ends in a ``review`` verdict
    THEN it holds (``accept`` is ``CONFIRMABLE`` for the review set, as
         today) and the review branch is published
    """
    looks = (_Look(T1), _Look(T2), _Look(DELIVERY_TIP),
             _Look(REVIEW_TIP, wall=1.50, val_loss=0.503))  # fmt: skip
    world = _world(sample_project, sample_workload, (A, R, B, R2), looks, per_round=2,
                   judges=(_ReviewMarker(),))  # fmt: skip
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    review = state["review_combination"]
    assert review is not None and review.holds
    (mark,) = [r for r in review.judge_results if r.judge == "review-marker"]
    assert mark.output_changed is True
    combination = state["combination"]
    assert combination is not None and combination.holds  # the run set: keep
    assert [p.branch for p in world.publisher.calls][-1] == f"engine/review-{RUN_ID}"


@pytest.mark.parametrize(
    "took", [True, False], ids=["squash-applied", "squash-skipped"]
)
def test_the_delivered_rounds_skips_are_kept_only_with_the_squash(
    sample_project: Project, sample_workload: Workload, run_world: Any, took: bool
) -> None:
    """
    GIVEN round 1 combines A and B on the origin, one skipped on a conflict,
          and is adopted at T1; round 2 keeps C on T1
    THEN with the squash applied the combination carries round 1's skip and
         the two applied trials; with the squash skipped it carries neither
    """
    delivery = (_Look(DELIVERY_TIP),) if took else (_Look(ORIGIN, skip=True),) * 2
    looks = (_Look(T1, conflict_last=True), _Look(T2), *delivery)
    world = _world(sample_project, sample_workload, (A, B, C), looks, per_round=2)
    ran = run_world(world, max_rounds=2)
    state = ran.state
    assert ran.result.status == "done", state["error"]
    first = ran.ledger.rounds[0].combination
    assert first is not None and len(first.skipped) == 1
    assert first is not None and len(first.applied_trial_ids) == 1
    combination = state["combination"]
    assert combination is not None
    if took:
        assert combination.skipped == first.skipped
        assert combination.applied_trial_ids == (
            *first.applied_trial_ids,
            _trial(state, world, C).id,
        )
        assert len(state["kept_verdict_ids"]) == 2
    else:
        assert combination.skipped == () and combination.applied_trial_ids == ()
        assert state["kept_verdict_ids"] == []
