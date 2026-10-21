"""Tests for the per-run cost budget (Step 2, unit U1).

``Budget`` is rebuilt from state by every node that spends money
(``Budget(state["max_cost_usd"], state["cost_usd"])``). ``check`` runs before
every request with a worst-case estimate; ``record`` runs after every
attempt with what was actually billed. Both refuse to let the run go past
its cap.
"""

from __future__ import annotations

import math

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.errors import BudgetExceeded, EngineError

NON_FINITE = (math.inf, -math.inf, math.nan)


def test_defaults_start_empty() -> None:
    """
    GIVEN only a cap
    WHEN a Budget is built
    THEN nothing is spent, no tokens are counted and the whole cap remains
    """
    budget = Budget(2.0)

    assert budget.cap_usd == 2.0
    assert budget.spent_usd == 0.0
    assert budget.tokens == 0
    assert budget.remaining == 2.0


def test_remaining_is_cap_minus_spent() -> None:
    """
    GIVEN a budget rebuilt from state with some money already spent
    WHEN remaining is read
    THEN it is the cap minus the spend
    """
    budget = Budget(cap_usd=5.0, spent_usd=1.25, tokens=900)

    assert budget.remaining == pytest.approx(3.75)
    assert budget.tokens == 900


def test_remaining_never_goes_negative() -> None:
    """
    GIVEN a state whose recorded spend already exceeds the cap
    WHEN a Budget is rebuilt from it
    THEN construction succeeds and remaining is 0, not negative
    """
    budget = Budget(cap_usd=1.0, spent_usd=1.5)

    assert budget.remaining == 0.0


def test_check_passes_up_to_and_including_the_cap() -> None:
    """
    GIVEN a budget with money left
    WHEN check is called with an estimate that lands exactly on the cap
    THEN it passes and changes nothing
    """
    budget = Budget(cap_usd=1.0, spent_usd=0.25)

    budget.check(0.75)
    budget.check(0.0)

    assert budget.spent_usd == 0.25
    assert budget.tokens == 0


def test_check_refuses_an_estimate_past_the_cap() -> None:
    """
    GIVEN a budget with 0.25 USD left
    WHEN check is called with a larger estimate
    THEN BudgetExceeded (an EngineError) names the numbers and nothing changes
    """
    budget = Budget(cap_usd=1.0, spent_usd=0.75)

    with pytest.raises(BudgetExceeded, match=r"0\.75.*0\.3.*1\.0") as caught:
        budget.check(0.3)

    assert isinstance(caught.value, EngineError)
    assert budget.spent_usd == 0.75


def test_check_refuses_any_estimate_once_spend_exceeds_cap() -> None:
    """
    GIVEN a budget whose spend already exceeds the cap
    WHEN check is called, even with a zero estimate
    THEN BudgetExceeded is raised
    """
    budget = Budget(cap_usd=1.0, spent_usd=1.5)

    with pytest.raises(BudgetExceeded):
        budget.check(0.0)


def test_record_adds_spend_and_tokens() -> None:
    """
    GIVEN a budget
    WHEN two attempts are recorded
    THEN spend and tokens accumulate and remaining shrinks
    """
    budget = Budget(cap_usd=1.0)

    budget.record(0.2, 1000)
    budget.record(0.3, 500)

    assert budget.spent_usd == pytest.approx(0.5)
    assert budget.tokens == 1500
    assert budget.remaining == pytest.approx(0.5)


def test_record_up_to_the_cap_is_allowed() -> None:
    """
    GIVEN a budget
    WHEN the recorded total lands exactly on the cap
    THEN no error is raised
    """
    budget = Budget(cap_usd=1.0, spent_usd=0.5)

    budget.record(0.5, 10)

    assert budget.spent_usd == 1.0
    assert budget.remaining == 0.0


def test_record_past_the_cap_keeps_the_spend_and_raises() -> None:
    """
    GIVEN a budget with 0.1 USD left
    WHEN an attempt billed 0.4 USD is recorded
    THEN the spend and tokens are kept (the money is gone) and BudgetExceeded
         is raised
    """
    budget = Budget(cap_usd=1.0, spent_usd=0.9)

    with pytest.raises(BudgetExceeded, match="cap"):
        budget.record(0.4, 2000)

    assert budget.spent_usd == pytest.approx(1.3)
    assert budget.tokens == 2000
    assert budget.remaining == 0.0


def test_the_cap_is_a_strict_float_bound() -> None:
    """
    GIVEN a 0.3 USD cap and amounts whose decimal sum is exactly 0.3
    WHEN they are checked and recorded in float arithmetic
    THEN a sum that rounds one ulp past the cap is refused: there is no
         tolerance, so the cap is a hard bound (documented on Budget)
    """
    assert 0.1 + 0.2 > 0.3  # the float fact this test pins

    with pytest.raises(BudgetExceeded):
        Budget(cap_usd=0.3, spent_usd=0.1).check(0.2)
    budget = Budget(cap_usd=0.3)
    budget.record(0.1, 0)
    with pytest.raises(BudgetExceeded):
        budget.record(0.2, 0)


def test_zero_cap_allows_only_free_work() -> None:
    """
    GIVEN a zero cap
    WHEN a zero estimate and a zero spend are checked and recorded
    THEN both pass, while any positive estimate is refused
    """
    budget = Budget(cap_usd=0.0)

    budget.check(0.0)
    budget.record(0.0, 0)
    with pytest.raises(BudgetExceeded):
        budget.check(0.000001)


@pytest.mark.parametrize("value", [-0.01, *NON_FINITE])
def test_construction_rejects_a_bad_cap(value: float) -> None:
    """
    GIVEN a negative or non-finite cap
    WHEN a Budget is built
    THEN ValueError names the cap
    """
    with pytest.raises(ValueError, match="cap_usd"):
        Budget(cap_usd=value)


@pytest.mark.parametrize("value", [-0.01, *NON_FINITE])
def test_construction_rejects_a_bad_spend(value: float) -> None:
    """
    GIVEN a negative or non-finite starting spend
    WHEN a Budget is built
    THEN ValueError names the spend
    """
    with pytest.raises(ValueError, match="spent_usd"):
        Budget(cap_usd=1.0, spent_usd=value)


def test_construction_rejects_negative_tokens() -> None:
    """
    GIVEN a negative starting token count
    WHEN a Budget is built
    THEN ValueError names the tokens
    """
    with pytest.raises(ValueError, match="tokens"):
        Budget(cap_usd=1.0, tokens=-1)


@pytest.mark.parametrize("value", [-0.01, *NON_FINITE])
def test_check_rejects_a_bad_estimate(value: float) -> None:
    """
    GIVEN a negative or non-finite estimate (a broken estimator)
    WHEN check is called
    THEN ValueError is raised rather than a pass or a budget error
    """
    budget = Budget(cap_usd=1.0)

    with pytest.raises(ValueError, match="estimate_usd"):
        budget.check(value)


@pytest.mark.parametrize("value", [-0.01, *NON_FINITE])
def test_record_rejects_a_bad_amount(value: float) -> None:
    """
    GIVEN a negative or non-finite billed amount
    WHEN record is called
    THEN ValueError is raised and nothing is added
    """
    budget = Budget(cap_usd=1.0, spent_usd=0.1, tokens=5)

    with pytest.raises(ValueError, match="usd"):
        budget.record(value, 1)

    assert budget.spent_usd == 0.1
    assert budget.tokens == 5


def test_record_rejects_negative_tokens() -> None:
    """
    GIVEN a negative token count
    WHEN record is called
    THEN ValueError is raised and nothing is added
    """
    budget = Budget(cap_usd=1.0)

    with pytest.raises(ValueError, match="tokens"):
        budget.record(0.1, -5)

    assert budget.spent_usd == 0.0
    assert budget.tokens == 0
