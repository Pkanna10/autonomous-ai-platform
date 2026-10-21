"""Tests for the cost model of paid Claude requests (Step 2, unit U6).

``chain`` names every model one request may bill, ``preflight_estimate``
prices the worst case of that chain before a request is sent,
``response_cost`` prices what the response reports it billed, and
``prompt_token_bound`` is the prompt-size bound the estimate is fed. The
property at the bottom checks the contract the budget depends on: whatever a
response within the request's limits reports, its cost never exceeds the
estimate, under the module's two stated preconditions (no 1-hour cache
writes; every billing model priced, or nothing dearer than the chain listed).
Tests named ``test_*_outside_the_estimate`` pin what happens when one of them
does not hold.

Usage objects are built from the installed SDK's own types
(``anthropic.types.Usage``, ``anthropic.types.beta.BetaUsage``, its iteration
entries and the ``CacheCreation`` TTL split), so a renamed field breaks these
tests, not a run.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import cast

import pytest
from anthropic.types import CacheCreation, Usage
from anthropic.types.beta import (
    BetaCacheCreation,
    BetaCompactionIterationUsage,
    BetaFallbackMessageIterationUsage,
    BetaMessageIterationUsage,
    BetaTextBlock,
    BetaToolTextEditor20250728,
    BetaToolUseBlock,
    BetaUsage,
)
from anthropic.types.beta.beta_iterations_usage import BetaIterationsUsageItem

from autonomous_ai_agents.clients.cost import (
    BUILTIN_TOOL_INPUT_TOKENS,
    TOOL_USE_SYSTEM_PROMPT_TOKENS,
    chain,
    preflight_estimate,
    prompt_token_bound,
    response_cost,
)
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import ModelPrice

MTOK = 1_000_000

OPUS_5_5 = ModelPrice(input=4.0, output=20.0, cache_write=5.0, cache_read=0.20)
OPUS_5 = ModelPrice(input=5.0, output=25.0, cache_write=6.25, cache_read=0.50)
PRICES: dict[str, ModelPrice] = {"claude-opus-5-5": OPUS_5_5, "claude-opus-5": OPUS_5}

BAD_COUNTS: tuple[object, ...] = (-1, True, 1.5, math.nan, math.inf, -math.inf, "10")


def _cost(price: ModelPrice, inp: int, out: int, write: int, read: int) -> float:
    """The documented formula, written out independently of the module."""
    return (
        inp * price.input
        + out * price.output
        + write * price.cache_write
        + read * price.cache_read
    ) / MTOK


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    """Settings from explicit values only, so the host environment cannot leak in."""
    base: dict[str, object] = {
        "ENGINE_MODEL": "claude-opus-5-5",
        "ENGINE_FALLBACKS": True,
        "ENGINE_FALLBACK_MODELS": ("claude-opus-5", "claude-opus-4-8"),
    }
    base.update(overrides)
    return Settings.model_validate(base)


def test_chain_is_the_engine_model_then_the_fallbacks_in_order() -> None:
    """
    GIVEN fallbacks enabled with two fallback models
    WHEN the chain is built
    THEN it is the engine model followed by the fallbacks, verbatim and in order
    """
    cfg = _settings()

    assert chain(cfg) == ("claude-opus-5-5", "claude-opus-5", "claude-opus-4-8")


def test_chain_is_only_the_engine_model_when_fallbacks_are_off() -> None:
    """
    GIVEN ENGINE_FALLBACKS=False (the request then carries no fallbacks field)
    WHEN the chain is built
    THEN only the engine model can bill, so the chain is that one model
    """
    cfg = _settings(ENGINE_FALLBACKS=False)

    assert chain(cfg) == ("claude-opus-5-5",)


def test_chain_with_an_empty_fallback_list_is_the_engine_model() -> None:
    """
    GIVEN fallbacks enabled but no fallback models configured
    WHEN the chain is built
    THEN it holds the engine model alone
    """
    cfg = _settings(ENGINE_FALLBACK_MODELS=())

    assert chain(cfg) == ("claude-opus-5-5",)


def test_chain_keeps_a_repeated_model_because_each_entry_can_bill() -> None:
    """
    GIVEN a fallback list that repeats a model
    WHEN the chain is built
    THEN the repeat is kept: the priced chain must equal the sent chain
    """
    cfg = _settings(ENGINE_FALLBACK_MODELS=("claude-opus-5", "claude-opus-5"))

    assert chain(cfg) == ("claude-opus-5-5", "claude-opus-5", "claude-opus-5")


def test_chain_reads_the_module_settings_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN the process-wide settings object changed at run time
    WHEN chain() is called with no argument
    THEN it reflects those settings
    """
    monkeypatch.setattr(settings, "ENGINE_MODEL", "claude-opus-5")
    monkeypatch.setattr(settings, "ENGINE_FALLBACKS", True)
    monkeypatch.setattr(settings, "ENGINE_FALLBACK_MODELS", ("claude-opus-4-8",))
    assert chain() == ("claude-opus-5", "claude-opus-4-8")

    monkeypatch.setattr(settings, "ENGINE_FALLBACKS", False)
    assert chain() == ("claude-opus-5",)


# ---------------------------------------------------------------------------
# response_cost: arithmetic
# ---------------------------------------------------------------------------


def test_response_cost_prices_every_component_at_its_rate() -> None:
    """
    GIVEN an SDK Usage with input, output, cache-write and cache-read tokens
    WHEN it is priced for the model that served it
    THEN each component is billed at its own per-MTok rate and every token counts
    """
    usage = Usage(
        input_tokens=1_000,
        output_tokens=500,
        cache_creation_input_tokens=200,
        cache_read_input_tokens=3_000,
    )

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5-5")

    # 1000*4 + 500*20 + 200*5 + 3000*0.2 = 15,600 micro-dollars
    assert usd == pytest.approx(0.0156, rel=1e-12)
    assert usd == pytest.approx(_cost(OPUS_5_5, 1_000, 500, 200, 3_000), rel=1e-12)
    assert tokens == 4_700


def test_response_cost_treats_absent_cache_fields_as_zero() -> None:
    """
    GIVEN an SDK Usage whose optional cache fields are None
    WHEN it is priced
    THEN only input and output are billed
    """
    usage = Usage(input_tokens=2_000, output_tokens=100)
    assert usage.cache_creation_input_tokens is None
    assert usage.cache_read_input_tokens is None

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5")

    assert usd == pytest.approx((2_000 * 5.0 + 100 * 25.0) / MTOK, rel=1e-12)
    assert tokens == 2_100


def test_response_cost_accepts_a_mapping_like_the_sdk_object() -> None:
    """
    GIVEN the same usage as an SDK object, a dict and a read-only mapping
    WHEN each is priced
    THEN all three give the same cost and token count
    """
    fields = {
        "input_tokens": 700,
        "output_tokens": 90,
        "cache_creation_input_tokens": 40,
        "cache_read_input_tokens": 12_000,
    }
    sdk = Usage(
        input_tokens=700,
        output_tokens=90,
        cache_creation_input_tokens=40,
        cache_read_input_tokens=12_000,
    )
    from_sdk = response_cost(sdk, PRICES, model="claude-opus-5")
    from_dict = response_cost(dict(fields), PRICES, model="claude-opus-5")
    from_proxy = response_cost(MappingProxyType(fields), PRICES, model="claude-opus-5")

    assert from_sdk == from_dict == from_proxy
    assert from_dict[1] == 12_830


def test_response_cost_sums_iterations_each_at_its_own_model() -> None:
    """
    GIVEN a fallback-served response: a declined Opus 5.5 attempt and the
          Opus 5 attempt that served the message
    WHEN it is priced
    THEN both iterations are billed, each at its own model's rates
    """
    declined = BetaMessageIterationUsage(
        type="message",
        model="claude-opus-5-5",
        input_tokens=1_000,
        output_tokens=50,
        cache_creation_input_tokens=300,
        cache_read_input_tokens=0,
    )
    served = BetaFallbackMessageIterationUsage(
        type="fallback_message",
        model="claude-opus-5",
        input_tokens=1_300,
        output_tokens=800,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    iterations: list[BetaIterationsUsageItem] = [declined, served]
    usage = BetaUsage(input_tokens=1_300, output_tokens=800, iterations=iterations)

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5")

    expected = _cost(OPUS_5_5, 1_000, 50, 300, 0) + _cost(OPUS_5, 1_300, 800, 0, 0)
    assert usd == pytest.approx(expected, rel=1e-12)
    assert tokens == 1_350 + 2_100


def test_response_cost_ignores_top_level_usage_when_iterations_exist() -> None:
    """
    GIVEN iterations (the per-attempt truth) and a top-level usage that the
          docs say covers only the attempt that produced the message
    WHEN it is priced
    THEN only the iterations are billed, so nothing is counted twice
    """
    entry = BetaMessageIterationUsage(
        type="message",
        model="claude-opus-5-5",
        input_tokens=10,
        output_tokens=20,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    iterations: list[BetaIterationsUsageItem] = [entry]
    usage = BetaUsage(
        input_tokens=9_000_000,
        output_tokens=9_000_000,
        cache_read_input_tokens=9_000_000,
        iterations=iterations,
    )

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5-5")

    assert usd == pytest.approx(_cost(OPUS_5_5, 10, 20, 0, 0), rel=1e-12)
    assert tokens == 30


def test_response_cost_prices_the_top_level_when_iterations_is_empty() -> None:
    """
    GIVEN a usage whose iterations list is present but empty
    WHEN it is priced
    THEN the top-level usage is billed (an empty list reports no attempts)
    """
    usage = {"input_tokens": 100, "output_tokens": 10, "iterations": []}

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5-5")

    assert usd == pytest.approx(_cost(OPUS_5_5, 100, 10, 0, 0), rel=1e-12)
    assert tokens == 110


def test_an_iteration_without_a_model_is_priced_at_the_response_model() -> None:
    """
    GIVEN a message iteration with model None and a compaction iteration,
          which has no model field at all
    WHEN they are priced for a response served by Opus 5
    THEN both are billed at the response model's rates
    """
    message = BetaMessageIterationUsage(
        type="message",
        model=None,
        input_tokens=400,
        output_tokens=30,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=100,
    )
    compaction = BetaCompactionIterationUsage(
        type="compaction",
        input_tokens=2_000,
        output_tokens=300,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    iterations: list[BetaIterationsUsageItem] = [message, compaction]
    usage = BetaUsage(input_tokens=400, output_tokens=30, iterations=iterations)

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5")

    expected = _cost(OPUS_5, 400, 30, 0, 100) + _cost(OPUS_5, 2_000, 300, 0, 0)
    assert usd == pytest.approx(expected, rel=1e-12)
    assert tokens == 530 + 2_300


def test_mapping_iterations_are_summed_like_sdk_ones() -> None:
    """
    GIVEN iterations given as plain dicts, one naming its model and one not
    WHEN the usage is priced
    THEN each is billed like the SDK form
    """
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "iterations": [
            {"model": "claude-opus-5-5", "input_tokens": 100, "output_tokens": 10},
            {"input_tokens": 200, "output_tokens": 20, "cache_read_input_tokens": 5},
        ],
    }

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5")

    expected = _cost(OPUS_5_5, 100, 10, 0, 0) + _cost(OPUS_5, 200, 20, 0, 5)
    assert usd == pytest.approx(expected, rel=1e-12)
    assert tokens == 110 + 225


# ---------------------------------------------------------------------------
# response_cost: cache writes by TTL
# ---------------------------------------------------------------------------
# The pricing page bills a 1-hour cache write at 2x the base input rate
# (Opus 5.5: $8/MTok, Opus 5: $10/MTok) and a 5-minute one at cache_write.


def _ttl_split_forms(five: int, hour: int) -> dict[str, object]:
    """One usage with a TTL split, in every form the API or a caller gives it."""
    split = {"ephemeral_5m_input_tokens": five, "ephemeral_1h_input_tokens": hour}
    return {
        "usage": Usage(
            input_tokens=100,
            output_tokens=10,
            cache_creation_input_tokens=five + hour,
            cache_creation=CacheCreation(
                ephemeral_5m_input_tokens=five, ephemeral_1h_input_tokens=hour
            ),
        ),
        "beta": BetaUsage(
            input_tokens=100,
            output_tokens=10,
            cache_creation_input_tokens=five + hour,
            cache_creation=BetaCacheCreation(
                ephemeral_5m_input_tokens=five, ephemeral_1h_input_tokens=hour
            ),
        ),
        "mapping": {
            "input_tokens": 100,
            "output_tokens": 10,
            "cache_creation_input_tokens": five + hour,
            "cache_creation": split,
        },
        "mapping-without-total": {
            "input_tokens": 100,
            "output_tokens": 10,
            "cache_creation": MappingProxyType(split),
        },
    }


@pytest.mark.parametrize("form", ["usage", "beta", "mapping", "mapping-without-total"])
def test_a_one_hour_cache_write_is_priced_at_twice_the_input_rate(form: str) -> None:
    """
    GIVEN a usage whose cache_creation split holds 600 5-minute and 400
          1-hour write tokens, as an SDK Usage, a BetaUsage or a mapping
          (with or without the cache_creation_input_tokens total)
    WHEN it is priced
    THEN the 1-hour tokens bill at 2x input and the 5-minute ones at
         cache_write, so the record is what the API billed
    """
    usage = _ttl_split_forms(600, 400)[form]

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5-5")

    # 100*4 + 10*20 + 600*5 + 400*(2*4) = 6,800 micro-dollars
    assert usd == pytest.approx(0.0068, rel=1e-12)
    assert tokens == 1_110


def test_a_one_hour_cache_write_in_an_iteration_is_priced_at_its_own_model() -> None:
    """
    GIVEN a declined Opus 5.5 attempt and a serving Opus 5 attempt, each with
          1-hour cache writes in its own split
    WHEN the usage is priced
    THEN each attempt's 1-hour writes bill at twice its own model's input rate
    """
    declined = BetaMessageIterationUsage(
        type="message",
        model="claude-opus-5-5",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000,
        cache_read_input_tokens=0,
        cache_creation=BetaCacheCreation(
            ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=1_000
        ),
    )
    served = BetaFallbackMessageIterationUsage(
        type="fallback_message",
        model="claude-opus-5",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000,
        cache_read_input_tokens=0,
        cache_creation=BetaCacheCreation(
            ephemeral_5m_input_tokens=250, ephemeral_1h_input_tokens=750
        ),
    )
    iterations: list[BetaIterationsUsageItem] = [declined, served]
    usage = BetaUsage(input_tokens=0, output_tokens=0, iterations=iterations)

    usd, tokens = response_cost(usage, PRICES, model="claude-opus-5")

    # 1000*(2*4) + 250*6.25 + 750*(2*5) = 17,062.5 micro-dollars
    assert usd == pytest.approx(0.0170625, rel=1e-12)
    assert tokens == 2_000


def test_a_split_of_only_five_minute_writes_keeps_the_cache_write_rate() -> None:
    """
    GIVEN the same usage with and without a split that is all 5-minute writes
    WHEN both are priced
    THEN they cost the same: cache_write is the 5-minute rate
    """
    with_split = Usage(
        input_tokens=10,
        output_tokens=1,
        cache_creation_input_tokens=500,
        cache_creation=CacheCreation(
            ephemeral_5m_input_tokens=500, ephemeral_1h_input_tokens=0
        ),
    )
    without = Usage(input_tokens=10, output_tokens=1, cache_creation_input_tokens=500)

    priced = response_cost(with_split, PRICES, model="claude-opus-5-5")

    assert priced == response_cost(without, PRICES, model="claude-opus-5-5")
    assert priced[0] == pytest.approx(_cost(OPUS_5_5, 10, 1, 500, 0), rel=1e-12)


@pytest.mark.parametrize(("five", "hour"), [(300, 300), (100, 100), (0, 0)])
def test_a_ttl_split_that_disagrees_with_the_total_is_refused(
    five: int, hour: int
) -> None:
    """
    GIVEN a split whose 5-minute and 1-hour counts do not add up to the
          cache_creation_input_tokens total of 500
    WHEN the usage is priced
    THEN ValueError is raised: the split is documented as a breakdown of that
         total, and guessing which number is right could under-count
    """
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_creation_input_tokens": 500,
        "cache_creation": {
            "ephemeral_5m_input_tokens": five,
            "ephemeral_1h_input_tokens": hour,
        },
    }

    with pytest.raises(ValueError, match="cache_creation"):
        response_cost(usage, PRICES, model="claude-opus-5-5")


@pytest.mark.parametrize(
    "field", ["ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"]
)
@pytest.mark.parametrize("bad", (*BAD_COUNTS, None), ids=repr)
def test_response_cost_refuses_a_bad_count_in_the_ttl_split(
    field: str, bad: object
) -> None:
    """
    GIVEN a split with a negative, boolean, fractional, non-finite, text or
          missing count
    WHEN the usage is priced
    THEN ValueError names the field
    """
    split: dict[str, object] = {
        "ephemeral_5m_input_tokens": 0,
        "ephemeral_1h_input_tokens": 0,
        field: bad,
    }
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation": split}

    with pytest.raises(ValueError, match=field):
        response_cost(usage, PRICES, model="claude-opus-5-5")


@pytest.mark.parametrize("split", [5, "5m", [0, 0]], ids=repr)
def test_response_cost_refuses_a_ttl_split_that_is_not_a_breakdown(
    split: object,
) -> None:
    """
    GIVEN a cache_creation field that is a number, text or a list
    WHEN the usage is priced
    THEN ValueError is raised rather than pricing every write at one rate
    """
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_creation": split}

    with pytest.raises(ValueError, match="ephemeral_5m_input_tokens"):
        response_cost(usage, PRICES, model="claude-opus-5-5")


def test_a_one_hour_cache_write_is_outside_the_estimate() -> None:
    """
    GIVEN a response that wrote 1,000 prompt tokens to the 1-hour cache, a
          TTL the engine never asks for
    WHEN it is priced and the same prompt is estimated
    THEN the cost is the true 2x-input bill and exceeds the estimate, which
         charges cache writes at the 5-minute rate: the 5-minute TTL is a
         precondition of the bound, and an honest cost lets Budget.record
         catch a breach of it
    """
    prices = {"claude-opus-5-5": OPUS_5_5}
    usage = BetaUsage(
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000,
        cache_read_input_tokens=0,
        cache_creation=BetaCacheCreation(
            ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=1_000
        ),
    )

    usd, tokens = response_cost(usage, prices, model="claude-opus-5-5")
    estimate = preflight_estimate(1_000, 0, ("claude-opus-5-5",), prices)

    assert usd == pytest.approx(0.008, rel=1e-12)
    assert tokens == 1_000
    assert estimate == pytest.approx(0.005, rel=1e-12)
    assert usd > estimate


# ---------------------------------------------------------------------------
# response_cost: unknown models
# ---------------------------------------------------------------------------

# Each component's worst rate sits in a different model, so a "worst model"
# shortcut would under-price at least one component.
SPLIT_PRICES: dict[str, ModelPrice] = {
    "a": ModelPrice(input=1.0, output=30.0, cache_write=2.0, cache_read=0.1),
    "b": ModelPrice(input=5.0, output=10.0, cache_write=1.0, cache_read=3.0),
}
WORST_SPLIT = ModelPrice(input=5.0, output=30.0, cache_write=2.0, cache_read=3.0)


def test_an_unknown_iteration_model_is_priced_at_the_worst_rate_per_component() -> None:
    """
    GIVEN an iteration billed by a model missing from the price table
    WHEN it is priced
    THEN every component uses the highest rate any listed model charges for it
    """
    entry = BetaMessageIterationUsage(
        type="message",
        model="claude-unlisted-9",
        input_tokens=1_000,
        output_tokens=2_000,
        cache_creation_input_tokens=3_000,
        cache_read_input_tokens=4_000,
    )
    iterations: list[BetaIterationsUsageItem] = [entry]
    usage = BetaUsage(input_tokens=1, output_tokens=1, iterations=iterations)

    usd, tokens = response_cost(usage, SPLIT_PRICES, model="a")

    expected = _cost(WORST_SPLIT, 1_000, 2_000, 3_000, 4_000)
    assert usd == pytest.approx(expected, rel=1e-12)
    assert usd > _cost(SPLIT_PRICES["a"], 1_000, 2_000, 3_000, 4_000)
    assert usd > _cost(SPLIT_PRICES["b"], 1_000, 2_000, 3_000, 4_000)
    assert tokens == 10_000


def test_an_unknown_response_model_is_priced_at_the_worst_rates() -> None:
    """
    GIVEN a usage without iterations from a model missing from the price table
    WHEN it is priced
    THEN it is billed at the worst listed rate for every component
    """
    usage = Usage(
        input_tokens=10,
        output_tokens=20,
        cache_creation_input_tokens=30,
        cache_read_input_tokens=40,
    )

    usd, _ = response_cost(usage, SPLIT_PRICES, model="claude-unlisted-9")

    assert usd == pytest.approx(_cost(WORST_SPLIT, 10, 20, 30, 40), rel=1e-12)


def test_an_unknown_model_prices_one_hour_writes_at_twice_the_worst_input() -> None:
    """
    GIVEN 1-hour cache writes billed by a model missing from the price table
    WHEN they are priced
    THEN they bill at twice the dearest listed input rate
    """
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 1_000,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 0,
            "ephemeral_1h_input_tokens": 1_000,
        },
    }

    usd, _ = response_cost(usage, SPLIT_PRICES, model="claude-unlisted-9")

    # worst input 5.0 (model b), so 1000 * 2 * 5 = 10,000 micro-dollars
    assert usd == pytest.approx(0.01, rel=1e-12)


def test_unknown_model_beside_a_dearer_unchained_one_is_outside_the_estimate() -> None:
    """
    GIVEN a price table listing a dearer model outside the chain, and a
          response from a model id the table does not list
    WHEN it is priced and the request estimated
    THEN the cost exceeds the estimate: the unknown model is priced at the
         dearest rate in the whole table, the estimate at the chain's. This
         over-count is the safe direction (Budget.record then stops the run),
         and it is why the bound's precondition is that every billing model
         is priced, or that nothing dearer than the chain is listed
    """
    dear = ModelPrice(input=25.0, output=125.0, cache_write=31.25, cache_read=0.625)
    prices = {"claude-opus-5-5": OPUS_5_5, "claude-dear-9": dear}
    usage = Usage(input_tokens=1_000, output_tokens=100)

    estimate = preflight_estimate(1_000, 100, ("claude-opus-5-5",), prices)
    usd, tokens = response_cost(usage, prices, model="claude-opus-5-5-20260301")

    assert estimate == pytest.approx(0.007, rel=1e-12)
    assert usd == pytest.approx(0.0375, rel=1e-12)
    assert tokens == 1_100
    assert usd > estimate


# ---------------------------------------------------------------------------
# response_cost: refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    ],
)
@pytest.mark.parametrize("bad", BAD_COUNTS, ids=repr)
def test_response_cost_refuses_a_bad_token_count(field: str, bad: object) -> None:
    """
    GIVEN a usage with a negative, boolean, fractional, non-finite or text count
    WHEN it is priced
    THEN ValueError is raised instead of a cost that could slip past the cap
    """
    usage: dict[str, object] = {"input_tokens": 1, "output_tokens": 1, field: bad}

    with pytest.raises(ValueError, match=field):
        response_cost(usage, PRICES, model="claude-opus-5-5")


def test_response_cost_refuses_a_bad_count_inside_an_iteration() -> None:
    """
    GIVEN an iteration entry with a negative output count
    WHEN the usage is priced
    THEN ValueError is raised
    """
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "iterations": [{"input_tokens": 1, "output_tokens": -5}],
    }

    with pytest.raises(ValueError, match="output_tokens"):
        response_cost(usage, PRICES, model="claude-opus-5-5")


@pytest.mark.parametrize("missing", ["input_tokens", "output_tokens"])
def test_response_cost_refuses_a_usage_without_a_required_count(missing: str) -> None:
    """
    GIVEN a usage that lacks input_tokens or output_tokens
    WHEN it is priced
    THEN ValueError names the missing field
    """
    usage = {"input_tokens": 1, "output_tokens": 1}
    del usage[missing]

    with pytest.raises(ValueError, match=missing):
        response_cost(usage, PRICES, model="claude-opus-5-5")


def test_response_cost_refuses_an_object_that_is_not_a_usage() -> None:
    """
    GIVEN something with no token fields at all
    WHEN it is priced
    THEN ValueError is raised
    """
    with pytest.raises(ValueError, match="input_tokens"):
        response_cost(object(), PRICES, model="claude-opus-5-5")


@pytest.mark.parametrize(
    "iterations", ["message", b"message", {"input_tokens": 1}, 3], ids=repr
)
def test_response_cost_refuses_iterations_that_are_not_a_list(
    iterations: object,
) -> None:
    """
    GIVEN an iterations field that is text, bytes, a mapping or a number
    WHEN the usage is priced
    THEN ValueError is raised rather than guessing what was billed
    """
    usage = {"input_tokens": 1, "output_tokens": 1, "iterations": iterations}

    with pytest.raises(ValueError, match="iterations"):
        response_cost(usage, PRICES, model="claude-opus-5-5")


def test_response_cost_refuses_an_iteration_model_that_is_not_text() -> None:
    """
    GIVEN an iteration whose model field is a number
    WHEN the usage is priced
    THEN ValueError is raised
    """
    usage = {
        "input_tokens": 1,
        "output_tokens": 1,
        "iterations": [{"model": 42, "input_tokens": 1, "output_tokens": 1}],
    }

    with pytest.raises(ValueError, match="model"):
        response_cost(usage, PRICES, model="claude-opus-5-5")


def test_response_cost_refuses_an_empty_price_table() -> None:
    """
    GIVEN no prices at all
    WHEN a usage is priced
    THEN ValueError is raised: not even a worst case can be named
    """
    with pytest.raises(ValueError, match="price"):
        response_cost(Usage(input_tokens=1, output_tokens=1), {}, model="m")


def test_response_cost_refuses_a_cost_too_large_for_a_float() -> None:
    """
    GIVEN rates and counts whose product does not fit in a float
    WHEN the usage is priced
    THEN ValueError is raised instead of OverflowError or an infinite cost
    """
    huge = {"m": ModelPrice(input=1e308, output=1e308, cache_write=0, cache_read=0)}

    with pytest.raises(ValueError, match="float"):
        response_cost(Usage(input_tokens=10**10, output_tokens=1), huge, model="m")


# ---------------------------------------------------------------------------
# preflight_estimate
# ---------------------------------------------------------------------------


def test_preflight_estimate_is_chain_length_times_the_worst_attempt() -> None:
    """
    GIVEN the default three-model chain and its prices
    WHEN a 10,000-token prompt with max_tokens 16,000 is estimated
    THEN it is 3 x (prompt x worst input-side rate + max_tokens x worst output rate)
    """
    prices = {**PRICES, "claude-opus-4-8": OPUS_5}
    models = ("claude-opus-5-5", "claude-opus-5", "claude-opus-4-8")

    estimate = preflight_estimate(10_000, 16_000, models, prices)

    # worst input-side rate: Opus 5 cache write 6.25; worst output: 25
    assert estimate == pytest.approx(3 * (10_000 * 6.25 + 16_000 * 25.0) / MTOK)
    assert estimate == pytest.approx(1.3875)


def test_preflight_estimate_scales_with_the_chain_length() -> None:
    """
    GIVEN chains of one, two and three entries of the same model
    WHEN the same request is estimated against each
    THEN the estimate grows in proportion to the chain length
    """
    one = preflight_estimate(5_000, 1_000, ("claude-opus-5",), PRICES)
    two = preflight_estimate(5_000, 1_000, ("claude-opus-5",) * 2, PRICES)
    three = preflight_estimate(5_000, 1_000, ("claude-opus-5",) * 3, PRICES)

    assert one > 0
    assert two == pytest.approx(2 * one)
    assert three == pytest.approx(3 * one)


@pytest.mark.parametrize(
    ("price", "input_side_rate"),
    [
        (ModelPrice(input=4.0, output=1.0, cache_write=5.0, cache_read=0.2), 5.0),
        (ModelPrice(input=7.0, output=1.0, cache_write=5.0, cache_read=0.2), 7.0),
        (ModelPrice(input=1.0, output=1.0, cache_write=2.0, cache_read=9.0), 9.0),
    ],
    ids=["cache-write-highest", "input-highest", "cache-read-highest"],
)
def test_preflight_estimate_charges_prompt_tokens_at_the_dearest_input_rate(
    price: ModelPrice, input_side_rate: float
) -> None:
    """
    GIVEN a model whose dearest input-side rate is the cache write, the plain
          input or (in an odd table) the cache read
    WHEN a prompt is estimated
    THEN every prompt token is charged at that dearest rate, since any of
         them may be billed in any of the three ways
    """
    estimate = preflight_estimate(1_000, 0, ("m",), {"m": price})

    assert estimate == pytest.approx(1_000 * input_side_rate / MTOK)


def test_preflight_estimate_takes_the_worst_rate_per_component_across_models() -> None:
    """
    GIVEN a chain where one model has the dearest input and another the
          dearest output
    WHEN a request is estimated
    THEN each side is priced at its own worst rate, whichever model holds it
    """
    estimate = preflight_estimate(1_000, 2_000, ("a", "b"), SPLIT_PRICES)

    # input side: max(5, 2, 3) from b and a; output: 30 from a
    assert estimate == pytest.approx(2 * (1_000 * 5.0 + 2_000 * 30.0) / MTOK)


def test_preflight_estimate_ignores_models_outside_the_chain() -> None:
    """
    GIVEN a price table with a dearer model that is not in the chain
    WHEN a request is estimated
    THEN only the chain's models set the rates
    """
    prices = {
        **PRICES,
        "dear": ModelPrice(input=99, output=99, cache_write=99, cache_read=99),
    }

    estimate = preflight_estimate(1_000, 1_000, ("claude-opus-5-5",), prices)

    assert estimate == pytest.approx((1_000 * 5.0 + 1_000 * 20.0) / MTOK)


def test_preflight_estimate_of_nothing_is_zero() -> None:
    """
    GIVEN no prompt and no output allowance
    WHEN the request is estimated
    THEN it costs nothing
    """
    assert preflight_estimate(0, 0, ("claude-opus-5-5",), PRICES) == 0.0


def test_one_worst_case_editor_request_with_the_shipped_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN the shipped chain, pricing table and EDITOR_MAX_TOKENS
    WHEN the factory's min_trial_budget_usd formula is evaluated
    THEN it is 3 x 16,000 x $25/MTok = $1.20 (the floor below which no trial starts)
    """
    for name in ("MODEL_PRICING", "EDITOR_MAX_TOKENS", "TRIAGE_MODEL"):
        monkeypatch.delenv(name, raising=False)
    cfg = _settings()

    estimate = preflight_estimate(
        0, cfg.EDITOR_MAX_TOKENS, chain(cfg), cfg.MODEL_PRICING
    )

    assert cfg.EDITOR_MAX_TOKENS == 16_000
    assert estimate == pytest.approx(1.20)


@pytest.mark.parametrize("argument", ["prompt_tokens", "max_tokens"])
@pytest.mark.parametrize("bad", BAD_COUNTS, ids=repr)
def test_preflight_estimate_refuses_a_bad_token_count(
    argument: str, bad: object
) -> None:
    """
    GIVEN a negative, boolean, fractional, non-finite or text token count
    WHEN a request is estimated
    THEN ValueError names the argument
    """
    counts = {"prompt_tokens": 1, "max_tokens": 1, argument: bad}

    with pytest.raises(ValueError, match=argument):
        preflight_estimate(
            cast(int, counts["prompt_tokens"]),
            cast(int, counts["max_tokens"]),
            ("claude-opus-5-5",),
            PRICES,
        )


@pytest.mark.parametrize("models", [(), [], "claude-opus-5-5"], ids=repr)
def test_preflight_estimate_refuses_an_empty_or_textual_chain(
    models: Sequence[str],
) -> None:
    """
    GIVEN no models, or one model name passed as a bare string (which would
          otherwise count as a chain of one entry per character)
    WHEN a request is estimated
    THEN ValueError is raised
    """
    with pytest.raises(ValueError, match="chain"):
        preflight_estimate(1, 1, models, PRICES)


def test_preflight_estimate_refuses_an_unpriced_model_in_the_chain() -> None:
    """
    GIVEN a chain naming a model the price table does not list
    WHEN a request is estimated
    THEN ValueError names that model: no estimate is a bound without its price
    """
    with pytest.raises(ValueError, match="claude-unlisted-9"):
        preflight_estimate(1, 1, ("claude-opus-5-5", "claude-unlisted-9"), PRICES)


def test_preflight_estimate_refuses_a_cost_too_large_for_a_float() -> None:
    """
    GIVEN rates and counts whose product does not fit in a float
    WHEN a request is estimated
    THEN ValueError is raised
    """
    huge = {"m": ModelPrice(input=1e308, output=0, cache_write=0, cache_read=0)}

    with pytest.raises(ValueError, match="float"):
        preflight_estimate(10**10, 0, ("m",), huge)


# ---------------------------------------------------------------------------
# prompt_token_bound
# ---------------------------------------------------------------------------

EDITOR_TOOL: dict[str, object] = {
    "type": "text_editor_20250728",
    "name": "str_replace_based_edit_tool",
}
# What the API adds as input for that tool, from the live docs (2026-10-21):
# the largest tool-use system prompt on the pricing page (804 tokens, Opus 4.7
# with tool_choice any/tool; Opus 5.5 is 286) and the text editor's own
# definition (974 tokens on Claude 4.7 and later).
EDITOR_OVERHEAD = 804 + 974


def _json_bytes(
    system: object, tools: Sequence[object], messages: Sequence[object]
) -> int:
    """The documented byte rule, written out independently of the module."""
    body = json.dumps(
        [system, tools, messages],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return len(body.encode("utf-8"))


def test_prompt_token_bound_without_tools_is_the_canonical_json_byte_length() -> None:
    """
    GIVEN a system prompt and one message, and no tools
    WHEN the bound is computed
    THEN it is the byte length of the three as compact, key-sorted JSON, with
         nothing added (the API adds no tool-use system prompt then)
    """
    bound = prompt_token_bound("sys", [], [{"role": "user", "content": "hi"}])

    canonical = '["sys",[],[{"content":"hi","role":"user"}]]'
    assert bound == len(canonical.encode("utf-8"))


def test_prompt_token_bound_is_the_canonical_json_byte_length() -> None:
    """
    GIVEN a system prompt, the text editor tool and one message
    WHEN the bound is computed
    THEN it is the byte length of the three as compact, key-sorted JSON, plus
         the input the API adds for the tool: its tool-use system prompt and
         the editor's full definition, which the ~70 bytes sent do not cover
    """
    bound = prompt_token_bound(
        "sys", [EDITOR_TOOL], [{"role": "user", "content": "hi"}]
    )

    canonical = (
        '["sys",'
        '[{"name":"str_replace_based_edit_tool","type":"text_editor_20250728"}],'
        '[{"content":"hi","role":"user"}]]'
    )
    assert bound == len(canonical.encode("utf-8")) + EDITOR_OVERHEAD


def test_tool_overheads_are_the_documented_maxima() -> None:
    """
    GIVEN the pricing page's tool-use system prompt table and the text editor
          page's "additional input tokens" table (fetched 2026-10-21)
    WHEN the module's allowances are read
    THEN they are the largest documented figures, so they cover every model
         a chain may hold: 804 for the system prompt, 974 for the editor
    """
    assert TOOL_USE_SYSTEM_PROMPT_TOKENS == 804
    assert dict(BUILTIN_TOOL_INPUT_TOKENS) == {"text_editor_20250728": 974}


def test_prompt_token_bound_covers_the_input_the_api_adds_for_the_editor() -> None:
    """
    GIVEN the smallest editor request: a short system prompt, the text editor
          tool and one short message (136 bytes of JSON)
    WHEN the bound is computed
    THEN it also counts the tool-use system prompt and the editor definition
         the API bills as input, so the bound still exceeds the billed prompt
    """
    bound = prompt_token_bound(
        "You edit code.",
        [EDITOR_TOOL],
        [{"role": "user", "content": "Speed up core.py"}],
    )

    assert bound == 136 + EDITOR_OVERHEAD == 1_914


def test_prompt_token_bound_adds_the_tool_use_system_prompt_once() -> None:
    """
    GIVEN the editor tool and two client tools, one with no type and one
          typed "custom", whose whole definitions are in the body
    WHEN the bound is computed
    THEN the system prompt allowance is added once, the editor's once, and
         nothing for the client tools beyond their bytes
    """
    schema: dict[str, object] = {"type": "object", "properties": {}}
    tools: list[Mapping[str, object]] = [
        EDITOR_TOOL,
        {"name": "lookup", "description": "Find a file.", "input_schema": schema},
        {"type": "custom", "name": "note", "input_schema": schema},
    ]

    bound = prompt_token_bound(None, tools, [])

    assert bound == _json_bytes(None, tools, []) + EDITOR_OVERHEAD


def test_prompt_token_bound_reads_the_type_of_an_sdk_tool_model() -> None:
    """
    GIVEN the editor tool as the SDK's pydantic model instead of a dict
    WHEN the bound is computed
    THEN its full dump is counted and the editor allowance still applies
    """
    tool = BetaToolTextEditor20250728(
        type="text_editor_20250728", name="str_replace_based_edit_tool"
    )
    dumped = tool.model_dump(mode="json", by_alias=True)

    bound = prompt_token_bound(None, [cast(Mapping[str, object], tool)], [])

    assert bound == prompt_token_bound(None, [dumped], [])
    assert bound == _json_bytes(None, [dumped], []) + EDITOR_OVERHEAD


def test_prompt_token_bound_refuses_an_undocumented_server_tool() -> None:
    """
    GIVEN a server-defined tool this module has no input allowance for
    WHEN the bound is computed
    THEN ValueError names its type rather than under-counting its definition
    """
    with pytest.raises(ValueError, match="bash_20250124"):
        prompt_token_bound(None, [{"type": "bash_20250124", "name": "bash"}], [])


def test_prompt_token_bound_refuses_a_tool_type_that_is_not_text() -> None:
    """
    GIVEN a tool whose type is a number
    WHEN the bound is computed
    THEN ValueError is raised
    """
    with pytest.raises(ValueError, match="type"):
        prompt_token_bound(None, [{"type": 7, "name": "x"}], [])


def test_prompt_token_bound_does_not_depend_on_key_order() -> None:
    """
    GIVEN the same blocks built with different key insertion orders
    WHEN the bound is computed for each
    THEN the results are equal
    """
    first = prompt_token_bound(
        [{"type": "text", "text": "rules", "cache_control": {"type": "ephemeral"}}],
        [EDITOR_TOOL],
        [{"role": "user", "content": [{"type": "text", "text": "go"}]}],
    )
    second = prompt_token_bound(
        [{"cache_control": {"type": "ephemeral"}, "text": "rules", "type": "text"}],
        [{"name": "str_replace_based_edit_tool", "type": "text_editor_20250728"}],
        [{"content": [{"text": "go", "type": "text"}], "role": "user"}],
    )

    assert first == second


def test_prompt_token_bound_counts_utf8_bytes_not_escapes() -> None:
    """
    GIVEN text with 2-, 3- and 4-byte UTF-8 characters
    WHEN the bound is computed
    THEN each character adds its UTF-8 length, not a 6- or 12-byte \\u escape
    """
    plain = prompt_token_bound(None, [], [{"role": "user", "content": ""}])
    accented = prompt_token_bound(
        None, [], [{"role": "user", "content": "é日\U0001f600"}]
    )

    assert accented - plain == 2 + 3 + 4


def test_prompt_token_bound_is_at_least_the_text_it_carries() -> None:
    """
    GIVEN a request whose text includes characters JSON must escape
    WHEN the bound is computed
    THEN it is no smaller than the UTF-8 size of all its text
    """
    system = 'Rules:\n\t"quoted" \\ backé'
    content = "def f():\n    return '日'\n"

    bound = prompt_token_bound(
        system, [EDITOR_TOOL], [{"role": "user", "content": content}]
    )

    assert bound >= len(system.encode("utf-8")) + len(content.encode("utf-8"))


def test_prompt_token_bound_accepts_sdk_content_blocks() -> None:
    """
    GIVEN an assistant turn echoing the SDK's response content blocks verbatim
    WHEN the bound is computed
    THEN each block counts as its full JSON dump, which is at least what the
         SDK sends for it
    """
    text = BetaTextBlock(type="text", text="I will edit core.py", citations=None)
    tool = BetaToolUseBlock(
        type="tool_use",
        id="toolu_01",
        name="str_replace_based_edit_tool",
        input={"command": "view", "path": "/repo/core.py"},
    )
    as_blocks = prompt_token_bound(
        None, [EDITOR_TOOL], [{"role": "assistant", "content": [text, tool]}]
    )
    full = [b.model_dump(mode="json", by_alias=True) for b in (text, tool)]
    wire = [
        b.model_dump(mode="json", by_alias=True, exclude_unset=True)
        for b in (text, tool)
    ]

    assert as_blocks == prompt_token_bound(
        None, [EDITOR_TOOL], [{"role": "assistant", "content": full}]
    )
    assert as_blocks >= prompt_token_bound(
        None, [EDITOR_TOOL], [{"role": "assistant", "content": wire}]
    )


def test_prompt_token_bound_accepts_tuples_and_read_only_mappings() -> None:
    """
    GIVEN tuples and a read-only mapping where lists and dicts usually go
    WHEN the bound is computed
    THEN it equals the bound of the list and dict form
    """
    message: Mapping[str, object] = MappingProxyType({"role": "user", "content": "x"})

    assert prompt_token_bound("s", (EDITOR_TOOL,), (message,)) == prompt_token_bound(
        "s", [EDITOR_TOOL], [{"role": "user", "content": "x"}]
    )


def test_prompt_token_bound_refuses_a_non_finite_number() -> None:
    """
    GIVEN a request carrying NaN, which is not valid JSON
    WHEN the bound is computed
    THEN ValueError is raised
    """
    with pytest.raises(ValueError):
        prompt_token_bound(None, [], [{"role": "user", "content": "x", "n": math.nan}])


def test_prompt_token_bound_refuses_a_lone_surrogate() -> None:
    """
    GIVEN text holding a lone surrogate, which has no UTF-8 encoding
    WHEN the bound is computed
    THEN ValueError is raised (such a body could not be sent either)
    """
    with pytest.raises(ValueError):
        prompt_token_bound("\ud800", [], [])


def test_prompt_token_bound_refuses_a_value_json_cannot_hold() -> None:
    """
    GIVEN raw bytes inside a message
    WHEN the bound is computed
    THEN TypeError is raised rather than a silently wrong size
    """
    with pytest.raises(TypeError, match="bytes"):
        prompt_token_bound(None, [], [{"role": "user", "content": b"raw"}])


# ---------------------------------------------------------------------------
# Property: actual cost <= pre-send estimate
# ---------------------------------------------------------------------------

PROPERTY_CASES = 1_500
UNKNOWN_MODEL = "claude-unlisted-9"
# Real-looking rates give exact ties between components and between models.
REAL_RATES = (
    OPUS_5_5,
    OPUS_5,
    ModelPrice(input=0.10, output=0.50, cache_write=0.125, cache_read=0.10),
)


def _random_price(rng: random.Random) -> ModelPrice:
    """Real-looking rates some of the time, arbitrary floats otherwise."""
    if rng.random() < 0.4:
        return rng.choice(REAL_RATES)
    return ModelPrice(
        input=rng.uniform(0, 30),
        output=rng.uniform(0, 120),
        cache_write=rng.uniform(0, 40),
        cache_read=rng.uniform(0, 30),
    )


def _upto(rng: random.Random, limit: int) -> int:
    """A count in [0, limit] that hits both ends often."""
    roll = rng.random()
    if roll < 0.25:
        return limit
    if roll < 0.35:
        return 0
    return rng.randint(0, limit)


def _random_counts(
    rng: random.Random, prompt_bound: int, max_tokens: int
) -> dict[str, int]:
    """One attempt within the request's limits, its prompt split three ways."""
    prompt = _upto(rng, prompt_bound)
    first = rng.randint(0, prompt)
    second = rng.randint(0, prompt - first)
    parts = [first, second, prompt - first - second]
    rng.shuffle(parts)
    return {
        "input_tokens": parts[0],
        "cache_creation_input_tokens": parts[1],
        "cache_read_input_tokens": parts[2],
        "output_tokens": _upto(rng, max_tokens),
    }


def _five_minute_split(rng: random.Random, counts: Mapping[str, int]) -> int | None:
    """Half the time, the 5-minute share of a TTL split; the 1-hour share is 0.

    Every write is a 5-minute one, the bound's precondition; the split only
    makes the cost go through the TTL-split path as well.
    """
    return counts["cache_creation_input_tokens"] if rng.random() < 0.5 else None


def _as_iteration(
    rng: random.Random, counts: Mapping[str, int], model: str | None
) -> object:
    """The attempt as an SDK message, an SDK fallback or a plain-dict iteration."""
    form = rng.choice(("message", "fallback", "dict"))
    five = _five_minute_split(rng, counts)
    split = (
        None
        if five is None
        else BetaCacheCreation(
            ephemeral_5m_input_tokens=five, ephemeral_1h_input_tokens=0
        )
    )
    if form == "dict":
        entry: dict[str, object] = dict(counts)
        if model is not None:
            entry["model"] = model
        if split is not None:
            entry["cache_creation"] = split.model_dump()
        return entry
    if form == "fallback" and model is not None:
        return BetaFallbackMessageIterationUsage(
            type="fallback_message",
            model=model,
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_creation_input_tokens=counts["cache_creation_input_tokens"],
            cache_read_input_tokens=counts["cache_read_input_tokens"],
            cache_creation=split,
        )
    return BetaMessageIterationUsage(
        type="message",
        model=model,
        input_tokens=counts["input_tokens"],
        output_tokens=counts["output_tokens"],
        cache_creation_input_tokens=counts["cache_creation_input_tokens"],
        cache_read_input_tokens=counts["cache_read_input_tokens"],
        cache_creation=split,
    )


def _as_top_level(rng: random.Random, counts: Mapping[str, int]) -> object:
    """A usage without iterations as an SDK Usage, an SDK BetaUsage or a dict."""
    form = rng.choice(("usage", "beta", "dict"))
    five = _five_minute_split(rng, counts)
    if form == "usage":
        return Usage(
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_creation_input_tokens=counts["cache_creation_input_tokens"],
            cache_read_input_tokens=counts["cache_read_input_tokens"],
            cache_creation=None
            if five is None
            else CacheCreation(
                ephemeral_5m_input_tokens=five, ephemeral_1h_input_tokens=0
            ),
        )
    if form == "beta":
        return BetaUsage(
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_creation_input_tokens=counts["cache_creation_input_tokens"],
            cache_read_input_tokens=counts["cache_read_input_tokens"],
            cache_creation=None
            if five is None
            else BetaCacheCreation(
                ephemeral_5m_input_tokens=five, ephemeral_1h_input_tokens=0
            ),
        )
    usage: dict[str, object] = dict(counts)
    if five is not None:
        usage["cache_creation"] = {
            "ephemeral_5m_input_tokens": five,
            "ephemeral_1h_input_tokens": 0,
        }
    return usage


def _random_usage(
    rng: random.Random,
    attempt_models: Sequence[str],
    prompt_bound: int,
    max_tokens: int,
) -> tuple[object, int]:
    """A response usage of a random shape, and the tokens it reports.

    At most one attempt per entry of ``attempt_models``; an attempt may carry
    no model (the response's model then applies).
    """
    if rng.random() < 0.3:
        counts = _random_counts(rng, prompt_bound, max_tokens)
        return _as_top_level(rng, counts), sum(counts.values())
    entries: list[object] = []
    total = 0
    counts = {}
    for _ in range(rng.randint(1, len(attempt_models))):
        model = rng.choice((*attempt_models, None))
        counts = _random_counts(rng, prompt_bound, max_tokens)
        entries.append(_as_iteration(rng, counts, model))
        total += sum(counts.values())
    # The top level repeats the serving (last) attempt, as the API reports it.
    return {**counts, "iterations": entries}, total


def test_property_cost_never_exceeds_the_estimate_for_chain_models() -> None:
    """
    GIVEN random price tables (some with dearer models outside the chain),
          random chains with repeats, and responses of every shape with at
          most one attempt per chain entry, each attempt within the prompt
          bound and max_tokens
    WHEN the response is priced and the request estimated
    THEN the cost never exceeds the estimate, exactly, with no tolerance
    """
    rng = random.Random(20261021)
    for _ in range(PROPERTY_CASES):
        names = [f"m{i}" for i in range(rng.randint(1, 5))]
        prices = {name: _random_price(rng) for name in names}
        models = [rng.choice(names) for _ in range(rng.randint(1, 4))]
        prompt_bound = rng.randint(0, 300_000)
        max_tokens = rng.randint(0, 64_000)
        usage, expected_tokens = _random_usage(rng, models, prompt_bound, max_tokens)

        usd, tokens = response_cost(usage, prices, model=rng.choice(models))
        estimate = preflight_estimate(prompt_bound, max_tokens, models, prices)

        assert tokens == expected_tokens
        assert 0.0 <= usd <= estimate, (usage, prices, models)


def test_property_cost_never_exceeds_the_estimate_for_unknown_models() -> None:
    """
    GIVEN price tables that list exactly the chain's models, and responses
          whose attempts or serving model may be missing from the table
    WHEN the response is priced and the request estimated
    THEN worst-case pricing of the unknown model keeps the cost within the
         estimate. That holds because these tables list nothing outside the
         chain: an unknown model is priced at the dearest rate in the whole
         table, so a dearer unchained model would lift it above the estimate
         (test_unknown_model_beside_a_dearer_unchained_one_is_outside_the_estimate)
    """
    rng = random.Random(552026)
    for _ in range(PROPERTY_CASES):
        names = [f"m{i}" for i in range(rng.randint(1, 4))]
        prices = {name: _random_price(rng) for name in names}
        models = [*names, *(rng.choice(names) for _ in range(rng.randint(0, 2)))]
        attempt_models = (*models[:-1], UNKNOWN_MODEL)
        served_by = rng.choice((*models, UNKNOWN_MODEL))
        usage, expected_tokens = _random_usage(rng, attempt_models, 50_000, 8_000)

        usd, tokens = response_cost(usage, prices, model=served_by)
        estimate = preflight_estimate(50_000, 8_000, models, prices)

        assert tokens == expected_tokens
        assert 0.0 <= usd <= estimate, (usage, prices, models, served_by)


def test_property_equality_at_the_limits() -> None:
    """
    GIVEN one attempt per chain entry, each by the dearest model, each using
          the whole prompt bound at the dearest input-side rate and all of
          max_tokens
    WHEN the response is priced and the request estimated
    THEN the two are exactly equal: the estimate is tight, not padded, and
         rounding cannot push the cost above it
    """
    prices = {"cheap": OPUS_5_5, "dear": OPUS_5}
    models = ("cheap", "dear", "dear")
    attempt = {
        "model": "dear",
        "input_tokens": 0,
        "cache_creation_input_tokens": 12_345,
        "cache_read_input_tokens": 0,
        "output_tokens": 16_000,
    }
    usage = {"input_tokens": 0, "output_tokens": 0, "iterations": [attempt] * 3}

    usd, _ = response_cost(usage, prices, model="dear")

    assert usd == preflight_estimate(12_345, 16_000, models, prices)


def test_rounding_cannot_lift_a_cost_above_its_estimate() -> None:
    """
    GIVEN equal input, cache-write and cache-read rates of 0.2 and a 32-token
          prompt billed as 28 + 3 + 1 (naive float sums put this one ulp
          above 32 x 0.2)
    WHEN the response is priced and the request estimated
    THEN the cost equals the estimate and does not exceed it
    """
    flat = {"m": ModelPrice(input=0.2, output=0.2, cache_write=0.2, cache_read=0.2)}
    usage = {
        "input_tokens": 28,
        "cache_creation_input_tokens": 3,
        "cache_read_input_tokens": 1,
        "output_tokens": 0,
    }

    usd, _ = response_cost(usage, flat, model="m")
    estimate = preflight_estimate(32, 0, ("m",), flat)

    assert usd <= estimate
    assert usd == estimate
