"""G5b round seeds, the node's side: the hypotheses node passes the generator
this run's verdicts, each with its hypothesis, the mechanism key the idea
pipeline recorded for it (read back from the run's events), its deciding
primary result's gain and floor, and the run's noise floor; round 1 passes
None."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    Baseline,
    ChangeClass,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    Project,
    RunStats,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.optimization import idea_dedupe as dd
from autonomous_ai_agents.optimization.evolve import (
    CompoundPair,
    NearMiss,
    compound_hypothesis,
)
from autonomous_ai_agents.optimization.idea_types import Mechanism, MorphCell
from autonomous_ai_agents.optimization.sources import GenerateResult, RunVerdicts
from autonomous_ai_agents.orchestrator.nodes import NodeContext, make_nodes
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]
KEY = dd.IdeaKey(key=dd.MechanismKey(
    target=dd.Target(path="pkg/m.py", first=3, last=4),
    mechanism=Mechanism.algorithm, cell=MorphCell.work_reuse,
), function="f")  # fmt: skip
STDEV = 0.05  # the baseline's spread on a mean of 1.0


class _Generator:
    """Records every call's keyword arguments; returns its scripted results
    in turn, then nothing."""

    def __init__(self, *results: GenerateResult) -> None:
        self.calls: list[dict[str, Any]] = []
        self.results = list(results)

    def generate(self, **kwargs: Any) -> GenerateResult:  # noqa: ANN401
        self.calls.append(kwargs)
        budget = kwargs["budget"]
        assert isinstance(budget, Budget)
        budget.check(0.0)
        return self.results.pop(0) if self.results else GenerateResult()


def _hypothesis(project: Project, title: str) -> Hypothesis:
    return Hypothesis(project_id=project.id, source=HypothesisSource.novel,
                      title=title, rationale="r", change_class=ChangeClass.efficiency,
                      expected_gain=0.1, provability=0.5, risk=0.1)  # fmt: skip


def _verdict(
    trial: str,
    hypothesis: str,
    outcome: VerdictOutcome,
    results: Sequence[JudgeResult] = (),
) -> Verdict:
    return Verdict(trial_id=trial, hypothesis_id=hypothesis, outcome=outcome,
                   change_class=ChangeClass.efficiency, summary="s",
                   judge_results=tuple(results))  # fmt: skip


def _primary(metric: str, gain: float, floor: float) -> JudgeResult:
    return JudgeResult(judge=f"gain:{metric}", outcome=JudgeOutcome.inconclusive,
                       metric=metric, gain=gain, noise_floor=floor,
                       reason="scripted")  # fmt: skip


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    found = initial_state(sample_project, [sample_workload], [sample_objective],
                          sample_guardrails, run_id="run-g5b", max_rounds=3,
                          max_cost_usd=10.0)  # fmt: skip
    stats = RunStats(n=5, mean=1.0, stdev=STDEV, min=0.9, max=1.1, unit="s")
    found["baseline"] = Baseline(
        commit="0" * 40, objectives=(sample_objective,),
        measurements=(Measurement(workload_id=sample_workload.id,
                                  metric=sample_objective.metric, stats=stats,
                                  samples=(1.0,) * 5),),
    )  # fmt: skip
    return found


def _round_one(
    ctx: NodeContext, state: EngineState, keyed: Hypothesis, unkeyed: Hypothesis
) -> None:
    """Runs round 1's hypotheses node and folds its delta into ``state`` as
    the graph's reducers would (``events`` appended)."""
    delta = make_nodes(ctx)["hypotheses"](state)
    hypotheses, events = delta["hypotheses"], delta.get("events", [])
    assert isinstance(hypotheses, list) and isinstance(events, list)
    state["hypotheses"] = hypotheses
    state["events"] = [*state["events"], *events]
    assert {h.id for h in state["hypotheses"]} >= {keyed.id, unkeyed.id}


def test_round_one_passes_no_verdicts(
    make_context: ContextFactory, state: EngineState
) -> None:
    generator = _Generator()
    make_nodes(make_context(generator=generator))["hypotheses"](state)
    assert generator.calls[0]["verdicts"] is None


def test_the_keys_round_one_recorded_reach_round_two_with_each_trials_ratio(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    sample_objective: Objective,
) -> None:
    """The real path: round 1's pipeline events (one key) pass through the
    node into the run's events; round 2's call gets that key back, each
    verdict's own primary gain and floor, and the run floor exactly."""
    keyed, unkeyed = (_hypothesis(sample_project, t) for t in ("a", "b"))
    event = dd.key_event(keyed.id, keyed.title, KEY)
    generator = _Generator(GenerateResult(hypotheses=(keyed, unkeyed),
                                          events=(event,)))  # fmt: skip
    ctx = make_context(generator=generator, generator_max_calls=2)
    _round_one(ctx, state, keyed, unkeyed)
    metric = sample_objective.metric
    state["verdicts"] = [
        _verdict(
            "t1",
            keyed.id,
            VerdictOutcome.inconclusive,
            [_primary(metric, 0.0278, 0.0707)],
        ),  # fmt: skip
        _verdict("t2", unkeyed.id, VerdictOutcome.reject),
        _verdict("t3", "gone", VerdictOutcome.reject),  # no hypothesis: dropped
    ]
    state["hypotheses"] = [keyed, unkeyed]  # the pool is empty again
    state["round"], state["generator_calls"] = 1, 1

    make_nodes(ctx)["hypotheses"](state)

    passed = generator.calls[1]["verdicts"]
    assert isinstance(passed, RunVerdicts)
    found = [(t.hypothesis.id, t.verdict.trial_id, t.key, t.gain, t.floor)
             for t in passed.trialled]  # fmt: skip
    assert found == [(keyed.id, "t1", KEY, 0.0278, 0.0707),
                     (unkeyed.id, "t2", None, None, None)]  # fmt: skip
    expected = max(
        settings.NOISE_MULTIPLIER * STDEV, sample_objective.min_relative_gain
    )
    assert passed.noise_floor == pytest.approx(expected)


def test_a_compound_verdict_reaches_the_generator_unkeyed(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """A near-miss compound (G5b) has no recorded key, so the generator gets
    it as unkeyed and the pipeline never seeds it."""
    parents = []
    for i, title in enumerate(("x", "y")):
        hypothesis = _hypothesis(sample_project, title)
        trial = Trial(id=f"p{i}", hypothesis_id=hypothesis.id, round=1,
                      branch=f"engine/trial-run-g5b-{hypothesis.id}")  # fmt: skip
        parents.append(NearMiss(trial=trial, hypothesis=hypothesis, gain=0.03,
                                ratio=0.75))  # fmt: skip
    compound = compound_hypothesis(CompoundPair(first=parents[0], second=parents[1]))
    state["hypotheses"] = [compound]
    state["verdicts"] = [_verdict("tc", compound.id, VerdictOutcome.reject)]
    state["round"], state["generator_calls"] = 1, 1
    generator = _Generator()
    make_nodes(make_context(generator=generator, generator_max_calls=2))["hypotheses"](
        state
    )
    passed = generator.calls[0]["verdicts"]
    assert isinstance(passed, RunVerdicts)
    (trialled,) = passed.trialled
    assert (trialled.hypothesis.id, trialled.key) == (compound.id, None)


def test_without_a_baseline_the_floor_is_unknown(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    keyed = _hypothesis(sample_project, "a")
    state["hypotheses"] = [keyed]
    state["verdicts"] = [_verdict("t1", keyed.id, VerdictOutcome.reject)]
    state["round"], state["generator_calls"] = 1, 1
    state["baseline"] = None
    generator = _Generator()
    ctx = make_context(generator=generator, generator_max_calls=2)
    make_nodes(ctx)["hypotheses"](state)
    passed = generator.calls[0]["verdicts"]
    assert isinstance(passed, RunVerdicts) and passed.noise_floor is None
    assert passed.trialled[0].floor is None
