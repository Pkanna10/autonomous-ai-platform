"""Step 3 contracts (U2): state keys, serde, the discovery seams, NodeContext.

Spec sections 3.2 and 3.4, D4: every new key is set by ``initial_state`` and
round-trips through ``dump_state``/``load_state``; the ``NodeContext``
defaults reproduce Step 2 (no generator, no matcher, blind retrieval, no fix
retry left for the run until U16 computes it).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Combination,
    Delivery,
    DeliveryKind,
    Guardrail,
    Hotspot,
    Hypothesis,
    Lesson,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
    TechniqueMatchRecord,
    Workload,
)
from autonomous_ai_agents.optimization.sources import (
    GenerateResult,
    HypothesisGenerator,
    MatchResult,
    TechniqueMatcher,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]

STEP3_KEYS = {
    "candidate_pool": [],
    "parked": [],
    "technique_matches": [],
    "generator_calls": 0,
    "discovery_cost_usd": 0.0,
    "discovery_exhausted": False,
    "review_combination": None,
    "review_delivery": None,
}


class _Generator:
    def __init__(self, hypotheses: Sequence[Hypothesis]) -> None:
        self.hypotheses = tuple(hypotheses)

    def generate(
        self,
        *,
        project: Project,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        objective: Objective,
        techniques: Sequence[Technique],
        lessons: Sequence[Lesson],
        avoid_titles: Sequence[str],
        n: int,
        budget: Budget,
    ) -> GenerateResult:
        return GenerateResult(hypotheses=self.hypotheses[:n], notes=("one",))


class _Matcher:
    def match(
        self,
        *,
        understanding: ProjectUnderstanding | None,
        hotspots: Sequence[Hotspot],
        techniques: Sequence[Technique],
        k: int,
        budget: Budget,
    ) -> MatchResult:
        return MatchResult()


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    return initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )


def test_initial_state_sets_every_step3_key(state: EngineState) -> None:
    """
    GIVEN a fresh state
    WHEN the Step 3 keys are read
    THEN each is present with its Step 2-neutral value
    """
    assert {key: state[key] for key in STEP3_KEYS} == STEP3_KEYS  # type: ignore[literal-required]
    assert isinstance(state["discovery_cost_usd"], float)


def test_the_step3_keys_round_trip_through_json(
    state: EngineState, h1_cache: Hypothesis, h4_behaviour: Hypothesis
) -> None:
    """
    GIVEN a state with every Step 3 key set to a non-default value
    WHEN it is dumped, JSON-encoded, decoded and loaded
    THEN every key comes back equal and typed
    """
    parked = h4_behaviour.model_copy(update={"parked_reason": "needs approval"})
    match = TechniqueMatchRecord(
        slug="memoize", fit=0.7, justification_summary="pure", unmet_preconditions=()
    )
    combination = Combination(base_commit="a" * 40, holds=True, summary="review set")
    delivery = Delivery(
        project_id=state["project"].id,
        kind=DeliveryKind.branch,
        branch="engine/review-r1",
        report_markdown="# review",
    )
    state["candidate_pool"] = [h1_cache]
    state["parked"] = [parked]
    state["technique_matches"] = [match]
    state["generator_calls"] = 2
    state["discovery_cost_usd"] = 0.125
    state["discovery_exhausted"] = True
    state["review_combination"] = combination
    state["review_delivery"] = delivery

    loaded = load_state(json.loads(json.dumps(dump_state(state), allow_nan=False)))

    assert loaded == state
    assert type(loaded["technique_matches"][0]) is TechniqueMatchRecord
    assert loaded["parked"][0].parked_reason == "needs approval"
    assert isinstance(loaded["review_delivery"], Delivery)


def test_node_context_defaults_reproduce_step2(make_context: ContextFactory) -> None:
    """
    GIVEN a context built as in Step 2
    WHEN the discovery and retry fields are read
    THEN no generator or matcher, blind retrieval, no playbook and no fix
         retry left for the run (fail closed until U16)
    """
    ctx = make_context()

    assert (ctx.generator, ctx.matcher, ctx.retrieval) == (None, None, "blind")
    assert ctx.generated_classes == (ChangeClass.efficiency, ChangeClass.behaviour)
    assert (ctx.generator_n, ctx.generator_max_calls, ctx.matcher_k) == (5, 2, 3)
    assert ctx.discovery_max_share == 0.25
    assert ctx.fix_retries_per_run == 0
    assert ctx.playbook == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"generator_n": 0},
        {"generator_n": 21},
        {"matcher_k": 0},
        {"matcher_k": 21},
        {"generator_max_calls": -1},
        {"generator_max_calls": 6},
        {"discovery_max_share": 0.0},
        {"discovery_max_share": 1.0},
        {"discovery_max_share": float("inf")},
        {"discovery_max_share": float("nan")},
        {"generated_classes": (ChangeClass.novel,)},
        {"generated_classes": ()},
        {"fix_retries_per_run": -1},
        {"fix_retries_per_run": 2},
    ],
)
def test_node_context_refuses_out_of_range_discovery_knobs(
    make_context: ContextFactory, overrides: dict[str, object]
) -> None:
    """
    GIVEN a discovery or retry knob outside the range its setting allows
    WHEN the context is built
    THEN construction raises ValueError
    """
    with pytest.raises(ValueError):
        make_context(**overrides)


def test_the_seams_accept_structural_implementations(
    make_context: ContextFactory, h1_cache: Hypothesis, sample_objective: Objective
) -> None:
    """
    GIVEN a generator and a matcher written against the protocols only
    WHEN they are checked and placed in a context at the edges of its ranges
    THEN both satisfy the runtime-checkable protocols and the context keeps them
    """
    generator, matcher = _Generator([h1_cache]), _Matcher()
    ctx = make_context(
        generator=generator,
        matcher=matcher,
        retrieval="matched",
        generator_n=20,
        matcher_k=1,
        generator_max_calls=0,
        fix_retries_per_run=1,
    )

    assert isinstance(generator, HypothesisGenerator)
    assert isinstance(matcher, TechniqueMatcher)
    assert not isinstance(object(), HypothesisGenerator)
    assert ctx.generator is generator and ctx.matcher is matcher
    assert MatchResult() == MatchResult(matches=(), notes=())
    assert generator.generate(
        project=Project(id=h1_cache.project_id, name="p", root_path="/tmp/p"),
        understanding=None,
        hotspots=(),
        objective=sample_objective,
        techniques=(),
        lessons=(),
        avoid_titles=(),
        n=1,
        budget=Budget(1.0),
    ) == GenerateResult(hypotheses=(h1_cache,), notes=("one",))


def test_every_verdict_outcome_has_a_status_and_review_is_trialled() -> None:
    """
    GIVEN the verdict outcomes, ``review`` (D35) among them
    WHEN the verdicts node maps an outcome to the hypothesis status
    THEN every outcome has a status (a missing one would raise KeyError in the
        node) and ``review`` leaves the hypothesis trialled, as
        ``needs_approval`` does
    """
    from autonomous_ai_agents.common.models import HypothesisStatus, VerdictOutcome
    from autonomous_ai_agents.orchestrator import nodes

    assert set(nodes._STATUS_AFTER_VERDICT) == set(VerdictOutcome)
    assert nodes._STATUS_AFTER_VERDICT[VerdictOutcome.review] is (
        HypothesisStatus.trialled
    )
