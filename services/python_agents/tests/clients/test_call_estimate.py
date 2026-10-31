"""``call(estimate=)`` (Step 3 Wave 2, N4a; spec amendment 3.4, D48, C1).

The idea pipeline counts each lane's prompt once, reserves the sum on the
run's budget and runs each lane on a child budget capped at that lane's
estimate. ``call()`` must then use the number the pipeline reserved: a
recount (or a count failure's byte bound, about 3x larger) could overrun the
child cap, and a charged timeout must cost exactly what was reserved.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pytest
from anthropic.types.beta import BetaMessage

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate, response_cost
from autonomous_ai_agents.clients.transport import (
    LLMNoResponseError,
    LLMRequest,
    ScriptedReply,
    ScriptedTransport,
    call,
)
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.errors import BudgetExceeded, LLMUnavailable

CFG = Settings.model_validate({"ENGINE_FALLBACKS": False, "LLM_MAX_RETRIES": 0})
MODEL = CFG.ENGINE_MODEL
REQUEST = LLMRequest(
    system="You write ideas.",
    messages=({"role": "user", "content": "Propose ideas."},),
    max_tokens=1000,
)
USAGE: Mapping[str, int] = {"input_tokens": 120, "output_tokens": 80}


def _ok() -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": MODEL,
            "content": [{"type": "text", "text": "{}"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": dict(USAGE),
        }
    )


class _NoCount(ScriptedTransport):
    """A transport whose count must never be asked for."""

    def __init__(self, *replies: ScriptedReply) -> None:
        super().__init__(replies, cfg=CFG)
        self.counts = 0

    def count_input_tokens(self, request: LLMRequest) -> int:
        self.counts += 1
        raise AssertionError("call() recounted a prompt it was given an estimate for")


class _Counted(ScriptedTransport):
    def __init__(self, *replies: ScriptedReply) -> None:
        super().__init__(replies, cfg=CFG)
        self.counts = 0

    def count_input_tokens(self, request: LLMRequest) -> int:
        self.counts += 1
        return 500


def _no_sleep(_s: float) -> None:
    return None


def test_a_given_estimate_skips_the_count_and_is_reported() -> None:
    transport = _NoCount(_ok())
    budget = Budget(1.0)
    result = call(transport, REQUEST, budget, sleep=_no_sleep, estimate=0.25)
    assert transport.counts == 0
    assert result.estimate_usd == 0.25
    billed, tokens = response_cost(USAGE, CFG.MODEL_PRICING, model=MODEL)
    assert budget.spent_usd == pytest.approx(billed)
    assert budget.tokens == tokens


def test_the_given_estimate_is_what_the_budget_checks() -> None:
    transport = _NoCount(_ok())
    budget = Budget(0.10)
    with pytest.raises(BudgetExceeded, match="estimate 0.200000"):
        call(transport, REQUEST, budget, sleep=_no_sleep, estimate=0.20)
    assert transport.requests == []
    assert budget.spent_usd == 0.0


def test_a_small_given_estimate_lets_through_what_a_recount_would_refuse() -> None:
    # The byte bound of this request is far above 1e-6 USD; the reserved
    # number decides, as the pipeline's child cap requires.
    bound = preflight_estimate(
        ScriptedTransport([], cfg=CFG).count_input_tokens(REQUEST),
        REQUEST.max_tokens,
        (MODEL,),
        CFG.MODEL_PRICING,
    )
    budget = Budget(bound / 2)
    result = call(_NoCount(_ok()), REQUEST, budget, sleep=_no_sleep, estimate=bound / 4)
    assert result.estimate_usd == bound / 4


def test_a_charged_timeout_costs_the_given_estimate_and_a_child_cap_ends_it() -> None:
    timeout = LLMNoResponseError("Claude API: no answer in time", timed_out=True)
    transport = _NoCount(timeout, _ok())
    child = Budget(0.05)
    with pytest.raises(BudgetExceeded):
        call(transport, REQUEST, child, sleep=_no_sleep, max_retries=2, estimate=0.05)
    assert child.spent_usd == 0.05  # charged once, the retry refused by the cap
    assert len(transport.requests) == 1
    assert transport.remaining == 1


def test_a_timeout_then_an_answer_charges_the_estimate_plus_the_bill() -> None:
    timeout = LLMNoResponseError("Claude API: connection lost", timed_out=False)
    transport = _NoCount(timeout, _ok())
    budget = Budget(1.0)
    result = call(
        transport, REQUEST, budget, sleep=_no_sleep, max_retries=1, estimate=0.05
    )
    billed, _ = response_cost(USAGE, CFG.MODEL_PRICING, model=MODEL)
    assert result.cost_usd == pytest.approx(0.05 + billed)
    assert budget.spent_usd == pytest.approx(0.05 + billed)
    assert result.attempts == 2


def test_out_of_retries_still_charges_only_the_given_estimate() -> None:
    timeout = LLMNoResponseError("Claude API: no answer in time", timed_out=True)
    budget = Budget(1.0)
    with pytest.raises(LLMUnavailable, match="gave up after 1 attempt"):
        call(
            _NoCount(timeout),
            REQUEST,
            budget,
            sleep=_no_sleep,
            max_retries=0,
            estimate=0.03,
        )
    assert budget.spent_usd == 0.03


def test_without_an_estimate_the_count_is_still_taken() -> None:
    transport = _Counted(_ok())
    result = call(transport, REQUEST, Budget(1.0), sleep=_no_sleep)
    assert transport.counts == 1
    assert result.estimate_usd == preflight_estimate(
        500, REQUEST.max_tokens, (MODEL,), CFG.MODEL_PRICING
    )


@pytest.mark.parametrize("bad", [-0.01, math.nan, math.inf, True])
def test_an_unusable_estimate_is_refused_before_anything_is_sent(bad: float) -> None:
    transport = _NoCount(_ok())
    budget = Budget(1.0)
    with pytest.raises(ValueError, match="estimate"):
        call(transport, REQUEST, budget, sleep=_no_sleep, estimate=bad)
    assert transport.requests == []
    assert budget.spent_usd == 0.0
