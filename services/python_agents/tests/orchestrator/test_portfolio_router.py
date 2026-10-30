"""Router rule 3 with portfolio rounds (Step 3 Wave 2, N4b; amendment D54).

``after_verdicts`` ends exploration at a ``keep`` only once ``round`` has
reached ``ctx.portfolio_rounds``; rules 1, 2 and 4-7 keep their order, so a
pending approval, an exhausted budget and the last round still decide first,
and an empty pool with no generation left still routes to ``combine``. At
``portfolio_rounds=0`` (the default) the Step 2 table holds unchanged
(``tests/orchestrator/test_nodes.py`` routing table, D41).

Swap point: ``_Generator`` stands for any ``HypothesisGenerator``; the
router only asks whether one is live, never calls it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from autonomous_ai_agents.common.models import (
    ChangeClass,
    Guardrail,
    Hypothesis,
    HypothesisSource,
    Objective,
    Project,
    Trial,
    Verdict,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.nodes import NodeContext, make_router
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

ContextFactory = Callable[..., NodeContext]


class _Generator:
    def generate(self, **_kwargs: Any) -> GenerateResult:
        raise AssertionError("the router never calls the generator")


def _idea(project: Project, title: str) -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.novel,
        title=title,
        rationale="generated",
        change_class=ChangeClass.efficiency,
        expected_gain=0.1,
        provability=0.5,
        risk=0.1,
    )


def _verdict(hypothesis: Hypothesis, outcome: VerdictOutcome) -> Verdict:
    return Verdict(
        trial_id="t",
        hypothesis_id=hypothesis.id,
        outcome=outcome,
        change_class=hypothesis.change_class,
        summary="s",
    )


@pytest.fixture
def state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A 10 USD run of three rounds whose first trial was kept."""
    fresh = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="run-n4b",
        max_rounds=3,
        max_cost_usd=10.0,
    )
    kept = _idea(sample_project, "kept")
    fresh["trials"] = [Trial(hypothesis_id=kept.id, round=1)]
    fresh["verdicts"] = [_verdict(kept, VerdictOutcome.keep)]
    fresh["round"] = 1
    return fresh


# (portfolio_rounds, round, flags, expected); flags: pool (an untried idea),
# gen (a live generator), budget (budget_exhausted), rounds (round ==
# max_rounds), spent (no generator calls left), pending (an approval waits).
_ROUTES: dict[str, tuple[int, int, str, str]] = {
    "Step 2: keep in round 1 combines": (0, 1, "pool gen", "combine"),
    "keep in round 1 with a pool explores": (2, 1, "pool", "hypotheses"),
    "keep in round 1 with a live generator explores": (2, 1, "gen", "hypotheses"),
    "keep in round 2 combines": (2, 2, "pool gen", "combine"),
    "keep past the rounds combines": (1, 2, "pool", "combine"),
    "budget exhausted in round 1 combines": (2, 1, "pool gen budget", "combine"),
    "max_rounds still binds": (3, 3, "pool gen rounds", "combine"),
    "nothing left in round 1 combines": (2, 1, "", "combine"),
    "spent generator and no pool combines": (2, 1, "gen spent", "combine"),
    "pending approval wins": (2, 1, "pool pending", "approval_gate"),
}


@pytest.mark.parametrize("case", _ROUTES)
def test_a_keep_ends_exploration_only_after_the_portfolio_rounds(
    make_context: ContextFactory,
    state: EngineState,
    sample_project: Project,
    case: str,
) -> None:
    """
    GIVEN a keep verdict, the round, ``portfolio_rounds`` and what is left
    WHEN after_verdicts routes
    THEN a keep before the portfolio rounds complete explores the untried
         ideas; at or past them, an exhausted budget, the last round or
         nothing left combines; a pending approval still goes first
    """
    portfolio_rounds, round_, setup, expected = _ROUTES[case]
    flags = setup.split()
    state["round"] = round_
    if "rounds" in flags:
        state["max_rounds"] = round_
    state["candidate_pool"] = [_idea(sample_project, "next")] if "pool" in flags else []
    state["budget_exhausted"] = "budget" in flags
    state["generator_calls"] = 2 if "spent" in flags else 0
    if "pending" in flags:
        state["pending_approval_ids"] = [state["verdicts"][0].id]
    ctx = make_context(
        generator=_Generator() if "gen" in flags else None,
        portfolio_rounds=portfolio_rounds,
    )

    assert make_router(ctx)(state) == expected


def test_a_keep_waits_for_the_rounds_and_a_later_round_without_one_still_combines(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """
    GIVEN ``portfolio_rounds=2``, a keep in round 1 and a reject in round 2
    WHEN after_verdicts routes after each round
    THEN round 1 explores and round 2 combines: the keep is any verdict of
         the run, not only the last round's
    """
    ctx = make_context(portfolio_rounds=2)
    state["candidate_pool"] = [_idea(sample_project, "next")]
    assert make_router(ctx)(state) == "hypotheses"

    second = state["candidate_pool"][0]
    state["round"] = 2
    state["trials"] = [*state["trials"], Trial(hypothesis_id=second.id, round=2)]
    state["verdicts"] = [*state["verdicts"], _verdict(second, VerdictOutcome.reject)]
    state["candidate_pool"] = [_idea(sample_project, "third")]
    assert make_router(ctx)(state) == "combine"


def test_without_a_keep_portfolio_rounds_change_nothing(
    make_context: ContextFactory, state: EngineState, sample_project: Project
) -> None:
    """A reject routes as Step 2 does whatever ``portfolio_rounds`` is."""
    (verdict,) = state["verdicts"]
    state["verdicts"] = [verdict.model_copy(update={"outcome": VerdictOutcome.reject})]
    state["candidate_pool"] = [_idea(sample_project, "next")]
    for rounds in (0, 2, 3):
        assert make_router(make_context(portfolio_rounds=rounds))(state) == (
            "hypotheses"
        )
    state["candidate_pool"] = []
    assert make_router(make_context(portfolio_rounds=2))(state) == "combine"
