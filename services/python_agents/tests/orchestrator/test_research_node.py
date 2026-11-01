"""The research node: blind and matched retrieval (Step 3, U9; spec 4.1, D7, D18).

Swap point: ``_Matcher`` stands for ``ClaudeTechniqueMatcher`` (U7). It spends
through the real narrowed ``Budget`` it is handed (``check`` before "sending",
``record`` after), so the D7 refusal is the budget's own; the repository is
the conftest's ``InMemoryRepository``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.errors import (
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
    Objective,
    Project,
    ProjectUnderstanding,
    Technique,
    TechniqueMatchRecord,
    Workload,
)
from autonomous_ai_agents.optimization.sources import MatchResult
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeDelta,
    make_nodes,
    progress_of,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]

STEP2_KEYS = frozenset({"phase", "techniques", "papers", "events"})
SPEND_KEYS = frozenset({"cost_usd", "tokens_used", "discovery_cost_usd"})


def _technique(slug: str) -> Technique:
    return Technique(
        slug=slug,
        name=slug.title(),
        summary=f"apply {slug}",
        change_class=ChangeClass.efficiency,
        expected_gain=0.2,
        provability=0.8,
        risk=0.1,
    )


CALLER = _technique("caller-card")
PLAYBOOK = (_technique("memoize"), _technique("vectorize"), _technique("batch-io"))


def _record(slug: str, fit: float = 0.9) -> TechniqueMatchRecord:
    return TechniqueMatchRecord(slug=slug, fit=fit, justification_summary="fits")


class _Matcher:
    """Checks ``estimate`` against the budget, records ``spend``, then raises
    ``error`` or returns ``matches``; every call's keywords are kept."""

    def __init__(
        self,
        matches: Sequence[TechniqueMatchRecord] = (),
        *,
        spend: float = 0.0,
        estimate: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self.matches, self.spend, self.estimate = tuple(matches), spend, estimate
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def match(self, **kwargs: Any) -> MatchResult:
        self.calls.append(kwargs)
        budget = cast(Budget, kwargs["budget"])
        budget.check(self.estimate)
        budget.record(self.spend, 100 if self.spend else 0)
        if self.error is not None:
            raise self.error
        return MatchResult(matches=self.matches, notes=("one dropped",))


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A 10 USD run that has spent 1 USD, 0.5 of it on discovery: D7's cap is
    ``min(10 - 0.5, 1 + 0.25 * 10 - 0.5) = 3.0`` with a 0.5 USD trial reserve."""
    state = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-u9",
        max_cost_usd=10.0,
    )
    state["cost_usd"], state["tokens_used"] = 1.0, 500
    state["discovery_cost_usd"] = 0.5
    state["understanding"] = ProjectUnderstanding(
        language="python", summary="a bridge", served_by_model="m"
    )
    state["hotspots"] = [
        Hotspot(
            project_id=sample_project.id,
            workload_id=sample_workload.id,
            file_path="src/encode.py",
            symbol="encode",
            self_time_s=0.5,
            total_time_s=0.6,
            share=0.4,
        )
    ]
    return state


@pytest.fixture
def research(make_context: ContextFactory) -> Callable[..., NodeDelta]:
    """Run the research node over a matched context unless told otherwise."""

    def run(
        state: EngineState, matcher: _Matcher | None, **overrides: Any
    ) -> NodeDelta:
        fields: dict[str, Any] = {
            "retrieval": "matched",
            "matcher": matcher,
            "playbook": PLAYBOOK,
            "techniques": (CALLER,),
            "min_trial_budget_usd": 0.5,
            **overrides,
        }
        return make_nodes(make_context(**fields))["research"](state)

    return run


def _codes(delta: NodeDelta) -> list[object]:
    return [e.data.get("code") for e in cast(list[EngineEvent], delta["events"])]


def _notes(delta: NodeDelta) -> list[str]:
    """The ``research_note`` messages, the fake's own ``one dropped`` aside."""
    prefix, events = "research_note: ", cast(list[EngineEvent], delta["events"])
    notes = [e.message.removeprefix(prefix) for e in events]
    return [
        n
        for n, e in zip(notes, events, strict=True)
        if e.data.get("code") == "research_note" and n != "one dropped"
    ]


def _blind_and_charged(delta: NodeDelta, spend: float) -> None:
    assert set(delta) == STEP2_KEYS | SPEND_KEYS
    assert delta["techniques"] == [CALLER]
    assert delta["cost_usd"] == pytest.approx(1.0 + spend)
    assert delta["discovery_cost_usd"] == pytest.approx(0.5 + spend)
    assert _codes(delta)[0] == "research_unavailable"


def test_blind_sends_no_match_request(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN blind retrieval with a matcher and a playbook in the context
    WHEN research runs
    THEN no request is made, the caller's techniques are copied and the delta
         keeps Step 2's keys (no matches, no spend)
    """
    matcher = _Matcher([_record("memoize")], spend=0.02)

    delta = research(state, matcher, retrieval="blind")

    assert matcher.calls == []
    assert set(delta) == STEP2_KEYS
    assert delta["techniques"] == [CALLER] and delta["papers"] == []


def test_matched_writes_matches_and_charges_once(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN matched retrieval and a matcher that spends 0.02 USD
    WHEN research runs
    THEN one request goes out on D7's narrowed budget with the playbook, k, the
         understanding and the hotspots; the matched cards replace the caller's
         in fit order with their records; the spend is charged exactly once to
         the run and to discovery, and no generator call is counted
    """
    matcher = _Matcher([_record("vectorize"), _record("memoize", 0.5)], spend=0.02)

    delta = research(state, matcher, matcher_k=2)

    (call,) = matcher.calls
    budget = cast(Budget, call["budget"])
    assert budget.cap_usd == pytest.approx(3.0)
    assert call["techniques"] == PLAYBOOK and call["k"] == 2
    assert call["understanding"] is state["understanding"]
    assert call["hotspots"] == state["hotspots"]
    assert set(delta) == STEP2_KEYS | SPEND_KEYS | {"technique_matches"}
    assert delta["techniques"] == [PLAYBOOK[1], PLAYBOOK[0]]
    assert delta["technique_matches"] == [_record("vectorize"), _record("memoize", 0.5)]
    assert delta["cost_usd"] == pytest.approx(1.02)
    assert delta["tokens_used"] == 600
    assert delta["discovery_cost_usd"] == pytest.approx(0.52)
    assert _codes(delta) == ["research_note", None]


def test_matched_drops_unknown_and_repeated_slugs(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN a matcher answering a slug outside the playbook and one slug twice
    WHEN research runs
    THEN both are dropped with a note and only the known card is kept
    """
    matches = [_record("rewrite-in-c"), _record("batch-io"), _record("batch-io")]

    delta = research(state, _Matcher(matches))

    assert delta["techniques"] == [PLAYBOOK[2]]
    assert delta["technique_matches"] == [_record("batch-io")]
    assert _notes(delta) == [
        "dropped match 'rewrite-in-c': not a playbook technique",
        "dropped repeated match 'batch-io'",
    ]


def test_matched_keeps_at_most_k_matches(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN matcher_k=1 and a matcher answering two usable records
    WHEN research runs
    THEN only the first is kept, as card and record, and the excess is noted
    """
    matches = [_record("vectorize"), _record("memoize", 0.5)]

    delta = research(state, _Matcher(matches), matcher_k=1)

    assert delta["techniques"] == [PLAYBOOK[1]]
    assert delta["technique_matches"] == [_record("vectorize")]
    assert _notes(delta) == ["dropped 1 match(es) beyond k=1"]


def test_matched_with_no_usable_match_says_so(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN a matcher whose reply holds no playbook technique
    WHEN research runs
    THEN no cards and no records, charged, with a note that none matched
    """
    delta = research(state, _Matcher([_record("rewrite-in-c")], spend=0.01))

    assert delta["techniques"] == [] and delta["technique_matches"] == []
    assert delta["cost_usd"] == pytest.approx(1.01)
    assert _notes(delta) == [
        "dropped match 'rewrite-in-c': not a playbook technique",
        "no playbook technique matched; generating without cards",
    ]


def test_matched_card_for_a_repeated_playbook_slug_is_the_first(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN a caller-built playbook that repeats a slug (the prompt shows the first)
    WHEN the matcher picks that slug
    THEN the first card with it is the one kept
    """
    later = _technique("memoize").model_copy(update={"name": "Later memoize"})
    playbook = (PLAYBOOK[0], later)

    delta = research(state, _Matcher([_record("memoize")]), playbook=playbook)

    assert delta["techniques"] == [PLAYBOOK[0]]


@pytest.mark.parametrize(
    ("matcher", "spend"),
    [
        pytest.param(_Matcher(estimate=3.5), 0.0, id="budget-before-send"),
        pytest.param(_Matcher(spend=0.01, error=LLMConfigError("403")), 0.01, id="cfg"),
        pytest.param(_Matcher(spend=0.01, error=LLMUnavailable("529")), 0.01, id="503"),
        pytest.param(
            _Matcher(spend=0.01, error=LLMRequestError("413")), 0.01, id="4xx"
        ),
        pytest.param(
            _Matcher(spend=0.03, error=UnusableReplyError("schema", "bad")),
            0.03,
            id="unusable",
        ),
    ],
)
def test_matcher_failure_falls_back_to_blind_charged(
    research: Callable[..., NodeDelta],
    state: EngineState,
    matcher: _Matcher,
    spend: float,
) -> None:
    """
    GIVEN matched retrieval and a matcher refused before send or failing after
    WHEN research runs
    THEN a research_unavailable note, the caller's techniques, no matches, and
         whatever was billed is charged; discovery stays open for the generator
    """
    delta = research(state, matcher)

    _blind_and_charged(delta, spend)
    assert "discovery_exhausted" not in delta


@pytest.mark.parametrize("field", ["matcher", "playbook"])
def test_matched_with_no_matcher_or_playbook_is_soft(
    research: Callable[..., NodeDelta], state: EngineState, field: str
) -> None:
    """
    GIVEN matched retrieval with the matcher off, or with nothing to match
    WHEN research runs
    THEN a research_unavailable note, the caller's techniques and Step 2's keys
    """
    matcher = _Matcher([_record("memoize")])
    off: dict[str, Any] = {"playbook": ()} if field == "playbook" else {}

    delta = research(state, None if field == "matcher" else matcher, **off)

    assert matcher.calls == []
    assert set(delta) == STEP2_KEYS
    assert delta["techniques"] == [CALLER]
    assert _codes(delta)[0] == "research_unavailable"


def test_matched_unaffordable_sends_nothing_and_exhausts_discovery(
    research: Callable[..., NodeDelta], state: EngineState
) -> None:
    """
    GIVEN discovery's 25 % share is spent (d <= cost_usd, D7)
    WHEN research runs
    THEN no request and no Budget (a negative cap would be a ValueError), the
         caller's techniques, and discovery_exhausted set for the hypotheses node
    """
    state["discovery_cost_usd"] = 2.6
    matcher = _Matcher([_record("memoize")])

    delta = research(state, matcher)

    assert matcher.calls == []
    assert set(delta) == STEP2_KEYS | {"discovery_exhausted"}
    assert delta["discovery_exhausted"] is True
    assert delta["techniques"] == [CALLER]
    assert _codes(delta)[0] == "research_unavailable"


@pytest.mark.parametrize(
    "error", [EngineError("bad state"), RuntimeError("bug")], ids=["engine", "bug"]
)
def test_other_failures_end_the_run_with_the_spend_kept(
    research: Callable[..., NodeDelta], state: EngineState, error: Exception
) -> None:
    """
    GIVEN a matcher that bills 0.02 USD and then raises an unexpected error
    WHEN research runs
    THEN the error propagates (D18) carrying the run and discovery totals
    """
    with pytest.raises(type(error)) as raised:
        research(state, _Matcher(spend=0.02, error=error))

    progress = progress_of(raised.value)
    assert set(progress) == SPEND_KEYS
    assert progress["cost_usd"] == pytest.approx(1.02)
    assert progress["discovery_cost_usd"] == pytest.approx(0.52)
