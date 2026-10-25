"""The hypotheses node and the router with a generator (Step 3, U8; spec 4.2-4.3).

Swap point: ``_Generator`` stands for ``ClaudeHypothesisGenerator`` (U7). It
spends through the real narrowed ``Budget`` it is handed (``check`` before
"sending", ``record`` after), so the D7 refusals are the budget's own; the
repository is the conftest's ``InMemoryRepository``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    EngineError,
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
    UnusableReplyError,
)
from autonomous_ai_agents.common.models import (
    ChangeClass,
    EngineEvent,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    Lesson,
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    make_nodes,
    make_router,
    progress_of,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]


class _Generator:
    """Checks ``estimate`` against the budget, records ``spend``, then raises
    ``error`` or returns ``hypotheses``; every call's keywords are kept."""

    def __init__(
        self,
        hypotheses: Sequence[Hypothesis] = (),
        *,
        spend: float = 0.0,
        estimate: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.hypotheses, self.spend, self.estimate = tuple(hypotheses), spend, estimate
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls.append(kwargs)
        budget = cast(Budget, kwargs["budget"])
        budget.check(self.estimate)
        budget.record(self.spend, 100 if self.spend else 0)
        if self.error is not None:
            raise self.error
        return GenerateResult(hypotheses=self.hypotheses, notes=("one dropped",))


def _idea(
    project: Project, title: str, cls: ChangeClass = ChangeClass.efficiency, **kw: Any
) -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.novel,
        title=title,
        rationale="generated",
        change_class=cls,
        expected_gain=0.1,
        provability=0.5,
        risk=0.1,
        **kw,
    )


def _apply(state: EngineState, delta: NodeDelta) -> EngineState:
    merged: dict[str, Any] = dict(state)
    for key, value in delta.items():
        merged[key] = (
            [*merged[key], *cast(list[Any], value)] if key == "events" else value
        )
    return cast(EngineState, merged)


def _list(delta: NodeDelta, key: str) -> list[Hypothesis]:
    return cast(list[Hypothesis], delta[key])


def _codes(delta: NodeDelta) -> list[object]:
    return [
        event.data.get("code") for event in cast(list[EngineEvent], delta["events"])
    ]


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A fresh 10 USD run of three rounds."""
    return initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-u8",
        max_rounds=3,
        max_cost_usd=10.0,
    )


def _context_inputs(state: EngineState, project: Project, workload: Workload) -> None:
    state["understanding"] = ProjectUnderstanding(
        language="python", summary="a bridge", served_by_model="m"
    )
    state["hotspots"] = [
        Hotspot(
            project_id=project.id,
            workload_id=workload.id,
            file_path="src/encode.py",
            symbol="encode",
            self_time_s=0.5,
            total_time_s=0.6,
            share=0.4,
        )
    ]
    state["techniques"] = [
        Technique(
            slug="memoize",
            name="Memoize",
            summary="cache pure calls",
            change_class=ChangeClass.efficiency,
            expected_gain=0.2,
            provability=0.8,
            risk=0.1,
        )
    ]


def _teach(
    ctx: NodeContext, project: Project, *lessons: tuple[Hypothesis, VerdictOutcome]
) -> None:
    """A keep lesson, or a weight-5 reject (enough to beat one position)."""
    for hypothesis, outcome in lessons:
        weight = 5.0 if outcome is VerdictOutcome.reject else 1.0
        ctx.repository.save_lesson(
            Lesson(
                project_id=project.id,
                hypothesis_id=hypothesis.id,
                outcome=outcome,
                weight=weight,
                text="taught",
            )
        )


def test_one_generation_parks_slices_three_and_pools_two(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    sample_workload: Workload,
) -> None:
    """
    GIVEN no caller candidates and a generator returning four efficiency
          ideas, a behaviour one second and a novel one
    WHEN hypotheses runs twice, with lessons learnt between the rounds
    THEN one paid call with the run's context: the novel idea is parked, the
         behaviour idea enters a round (D9), three are sliced in model order
         and two pooled; round 2 re-ranks the pool by the lessons (D8)
    """
    ideas = [_idea(sample_project, f"idea {i}") for i in range(5)]
    ideas[1] = _idea(sample_project, "change it", ChangeClass.behaviour)
    novel = _idea(sample_project, "rewrite it", ChangeClass.novel)
    generator = _Generator([ideas[0], novel, *ideas[1:]], spend=0.02)
    earlier = _idea(sample_project, "earlier", status=HypothesisStatus.rejected)
    state["hypotheses"] = [earlier]
    state["cost_usd"], state["tokens_used"] = 1.0, 50
    _context_inputs(state, sample_project, sample_workload)
    ctx = make_context(generator=generator, generator_n=6)
    node = make_nodes(ctx)["hypotheses"]

    delta = node(state)

    (call,) = generator.calls
    assert call["n"] == 6 and call["objective"] == state["objectives"][0]
    assert call["avoid_titles"] == ["earlier"] and call["project"] == sample_project
    assert call["understanding"] == state["understanding"]
    assert call["hotspots"] == state["hotspots"]
    assert call["techniques"] == state["techniques"]
    assert list(call["lessons"]) == []
    sliced = _list(delta, "hypotheses")
    assert [h.id for h in sliced] == [earlier.id, *(h.id for h in ideas[:3])]
    assert all(h.status is HypothesisStatus.proposed for h in sliced[1:])
    assert [h.id for h in _list(delta, "candidate_pool")] == [h.id for h in ideas[3:]]
    (parked,) = _list(delta, "parked")
    assert parked.id == novel.id and parked.parked_reason == "needs approval"
    assert delta["generator_calls"] == 1 and delta["tokens_used"] == 150
    assert delta["cost_usd"] == pytest.approx(1.02)
    assert delta["discovery_cost_usd"] == pytest.approx(0.02)
    assert _codes(delta)[0] == "generated" and "generate_note" in _codes(delta)

    _teach(ctx, sample_project, (ideas[3], VerdictOutcome.reject))
    _teach(ctx, sample_project, (ideas[4], VerdictOutcome.keep))
    again = node(_apply(state, delta))

    assert len(generator.calls) == 1
    assert [h.id for h in _list(again, "hypotheses")[4:]] == [ideas[4].id, ideas[3].id]
    assert again["candidate_pool"] == []
    assert set(again) == {"phase", "round", "hypotheses", "candidate_pool", "events"}


def test_drops_repeated_titles_and_unusable_ids_and_lessons_reorder(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN generated ideas repeating a known title (spacing and case aside),
          an id that cannot name a branch, an id already used, and two good
          ones, the first strongly rejected before and the second kept
    WHEN hypotheses runs
    THEN only the two good ones are proposed, the lessons reorder them
         (rank_generated), each drop noted
    """
    known = _idea(sample_project, "Cache  It")
    good = [_idea(sample_project, "first"), _idea(sample_project, "second")]
    generated = [
        _idea(sample_project, "cache it"),
        _idea(sample_project, "bad id", id="../x"),
        _idea(sample_project, "taken", id=known.id),
        *good,
        _idea(sample_project, "SECOND"),
    ]
    state["parked"] = [known]
    generator = _Generator(generated)
    ctx = make_context(generator=generator)
    _teach(
        ctx,
        sample_project,
        (good[0], VerdictOutcome.reject),
        (good[1], VerdictOutcome.keep),
    )

    delta = make_nodes(ctx)["hypotheses"](state)

    assert generator.calls[0]["avoid_titles"] == ["Cache  It"]
    lessons = ctx.repository.list_lessons(sample_project.id)
    assert generator.calls[0]["lessons"] == lessons and len(lessons) == 2
    assert [h.id for h in _list(delta, "hypotheses")] == [good[1].id, good[0].id]
    assert _codes(delta).count("generate_note") == 5
    assert "candidate_pool" not in delta and delta["parked"] == [known]


def test_narrowed_generated_classes_park_a_behaviour_idea(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN GENERATED_CLASSES narrowed to efficiency (D9's knob)
    WHEN the generator returns a behaviour idea and an efficiency one
    THEN the behaviour idea is parked as "needs approval", the other sliced
    """
    behaviour = _idea(sample_project, "change it", ChangeClass.behaviour)
    efficient = _idea(sample_project, "speed it")
    ctx = make_context(
        generator=_Generator([behaviour, efficient]),
        generated_classes=(ChangeClass.efficiency,),
    )

    delta = make_nodes(ctx)["hypotheses"](state)

    assert [h.id for h in _list(delta, "hypotheses")] == [efficient.id]
    (parked,) = _list(delta, "parked")
    assert parked.id == behaviour.id and parked.parked_reason == "needs approval"


@pytest.mark.parametrize(
    ("cost", "spent_share", "expected_cap"),
    [
        pytest.param(7.5, 0.0, 8.0, id="the trial reserve"),
        pytest.param(1.0, 2.0, 1.5, id="the discovery share"),
    ],
)
def test_the_narrowed_budget_refuses_before_send(
    make_context: ContextFactory,
    state: EngineState,
    cost: float,
    spent_share: float,
    expected_cap: float,
) -> None:
    """
    GIVEN a 10 USD run, a 2 USD trial reserve and a 25 % discovery share
    WHEN the generator's worst case (0.6 USD) cuts into the reserve or share
    THEN BudgetExceeded is soft: discovery is exhausted, nothing charged or counted
    """
    generator = _Generator(estimate=0.6)
    state["cost_usd"], state["discovery_cost_usd"] = cost, spent_share
    ctx = make_context(generator=generator, min_trial_budget_usd=2.0)

    delta = make_nodes(ctx)["hypotheses"](state)

    assert cast(Budget, generator.calls[0]["budget"]).cap_usd == expected_cap
    assert delta["discovery_exhausted"] is True and delta["generator_calls"] == 0
    assert delta["cost_usd"] == cost and delta["discovery_cost_usd"] == spent_share
    assert _codes(delta)[0] == "discovery_unaffordable"
    assert make_router(ctx)(_apply(state, delta)) == "combine"


@pytest.mark.parametrize(
    ("max_cost", "cost"),
    [pytest.param(10.0, 9.5, id="d below cost"), pytest.param(0.5, 0.0, id="d < 0")],
)
def test_no_request_when_discovery_cannot_be_afforded(
    make_context: ContextFactory, state: EngineState, max_cost: float, cost: float
) -> None:
    """
    GIVEN d <= cost_usd (D7), including a negative d
    WHEN hypotheses runs
    THEN no request, no ValueError, discovery_exhausted set
    """
    generator = _Generator()
    state["max_cost_usd"], state["cost_usd"] = max_cost, cost
    ctx = make_context(generator=generator, min_trial_budget_usd=1.0)

    delta = make_nodes(ctx)["hypotheses"](state)

    assert generator.calls == [] and delta["discovery_exhausted"] is True
    assert _codes(delta)[0] == "discovery_unaffordable" and "cost_usd" not in delta


@pytest.mark.parametrize(
    ("error", "code"),
    [
        pytest.param(LLMUnavailable("529"), "generate_failed", id="unavailable"),
        pytest.param(LLMRequestError("400"), "generate_failed", id="refused"),
        pytest.param(UnusableReplyError("refusal", "no"), "generate_failed", id="bad"),
        pytest.param(BudgetExceeded("over"), "discovery_unaffordable", id="paid, over"),
    ],
)
def test_a_soft_failure_is_charged_and_counted(
    make_context: ContextFactory, state: EngineState, error: Exception, code: str
) -> None:
    """
    GIVEN a generator that is billed 0.03 USD and then fails softly
    WHEN hypotheses runs
    THEN the round is empty, the spend charged to the run and to discovery,
         the paid call counted
    """
    ctx = make_context(generator=_Generator(spend=0.03, error=error))

    delta = make_nodes(ctx)["hypotheses"](state)

    assert _list(delta, "hypotheses") == [] and delta["generator_calls"] == 1
    assert delta["cost_usd"] == delta["discovery_cost_usd"] == pytest.approx(0.03)
    assert _codes(delta)[0] == code
    assert delta.get("discovery_exhausted", False) is (code != "generate_failed")


@pytest.mark.parametrize(
    "error", [LLMConfigError("401"), RuntimeError("bug")], ids=["config", "bug"]
)
def test_any_other_failure_ends_the_run_with_its_spend(
    make_context: ContextFactory, state: EngineState, error: Exception
) -> None:
    """
    GIVEN a generator billed 0.01 USD that then raises LLMConfigError or a bug
    WHEN hypotheses runs
    THEN the error propagates carrying the spend and the counted call (D18)
    """
    ctx = make_context(generator=_Generator(spend=0.01, error=error))

    with pytest.raises(type(error)) as caught:
        make_nodes(ctx)["hypotheses"](state)

    progress = progress_of(caught.value)
    assert progress["cost_usd"] == progress["discovery_cost_usd"] == 0.01
    assert progress["generator_calls"] == 1


def test_generation_needs_an_objective(
    make_context: ContextFactory, state: EngineState
) -> None:
    """
    GIVEN a generator and a state whose define never ran (no objective)
    WHEN hypotheses runs
    THEN an EngineError names define, before any request
    """
    generator = _Generator()
    state["objectives"] = []

    with pytest.raises(EngineError, match="define"):
        make_nodes(make_context(generator=generator))["hypotheses"](state)
    assert generator.calls == []


@pytest.mark.parametrize(
    "setup",
    ["caller", "pool", "calls spent", "budget exhausted", "discovery exhausted"],
)
def test_no_generation_while_ideas_remain_or_it_is_ruled_out(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    h1_cache: Hypothesis,
    setup: str,
) -> None:
    """
    GIVEN an untried caller or pooled idea, or the calls, run budget or
          discovery budget spent
    WHEN hypotheses runs
    THEN the generator is not called
    """
    generator = _Generator()
    callers = [h1_cache] if setup == "caller" else []
    state["candidate_pool"] = [_idea(sample_project, "p")] if setup == "pool" else []
    state["generator_calls"] = 2 if setup == "calls spent" else 0
    state["budget_exhausted"] = setup == "budget exhausted"
    state["discovery_exhausted"] = setup == "discovery exhausted"

    make_nodes(make_context(callers, generator=generator))["hypotheses"](state)

    assert generator.calls == []


_ROUTES: dict[str, tuple[str, int, VerdictOutcome, str]] = {
    "a pool, after a review": ("gen pool", 0, VerdictOutcome.review, "hypotheses"),
    "a call left (D6)": ("gen", 1, VerdictOutcome.reject, "hypotheses"),
    "calls spent": ("gen", 2, VerdictOutcome.reject, "combine"),
    "share spent (D7 d <= cost)": ("gen broke", 0, VerdictOutcome.reject, "combine"),
    "discovery exhausted": ("gen discovery", 0, VerdictOutcome.review, "combine"),
    "budget exhausted": ("gen pool budget", 0, VerdictOutcome.reject, "combine"),
    "a keep": ("gen pool", 0, VerdictOutcome.keep, "combine"),
    "last round": ("gen pool rounds", 0, VerdictOutcome.reject, "combine"),
    "Step 2, nothing left": ("", 0, VerdictOutcome.reject, "combine"),
}


@pytest.mark.parametrize("case", _ROUTES)
def test_router_with_a_generator(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    case: str,
) -> None:
    """
    GIVEN no caller candidates, a pool or generator calls left, and a verdict
    WHEN after_verdicts routes
    THEN a pool or a possible call continues; spent calls, an exhausted
         budget, a keep or the last round end; a review never routes
    """
    setup, calls, outcome, expected = _ROUTES[case]
    flags = setup.split()
    tried = _idea(sample_project, "tried")
    state["trials"] = [Trial(hypothesis_id=tried.id, round=1)]
    state["verdicts"] = [
        Verdict(
            trial_id="t",
            hypothesis_id=tried.id,
            outcome=outcome,
            change_class=tried.change_class,
            summary="s",
        )
    ]
    state["round"] = state["max_rounds"] if "rounds" in flags else 1
    state["candidate_pool"] = [_idea(sample_project, "next")] if "pool" in flags else []
    state["generator_calls"] = calls
    state["discovery_exhausted"] = "discovery" in flags
    state["budget_exhausted"] = "budget" in flags
    state["discovery_cost_usd"] = 2.5 if "broke" in flags else 0.0
    ctx = make_context(generator=_Generator() if "gen" in flags else None)

    assert make_router(ctx)(state) == expected


def test_without_a_generator_the_node_keeps_step2_keys(
    make_context: ContextFactory, state: EngineState
) -> None:
    """
    GIVEN no generator and no candidates (Step 2)
    WHEN hypotheses runs
    THEN the delta holds Step 2's keys only and ranks nothing
    """
    delta = make_nodes(make_context())["hypotheses"](state)

    assert set(delta) == {"phase", "round", "hypotheses", "events"}
    assert delta["hypotheses"] == []
