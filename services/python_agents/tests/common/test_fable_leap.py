"""Claude Fable 5.2 in the engine's tables and the Fable leap's settings.

The price, effort and retention rows for ``claude-fable-5-2`` (pricing and
effort pages, read 2026-11-11), and what a Fable ``IDEAS_LEAP_MODEL``
(Fable 5, 5.1 or 5.2) changes: the leap's chain gains the explicit
``claude-opus-4-8`` fallback, its request shape is fixed (``leap_shape``:
effort ``high``, 32,000 output tokens, X1-1's 951 s timeout) and the leap's
settings copy carries both, so the transport built from it sends them. An
Opus or Sonnet leap (the default) keeps every value it had.
"""

from __future__ import annotations

import pytest
from live.ideas_probe import X1_1_TIMEOUT_S
from pydantic import ValidationError

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import (
    EFFORT_LEVELS,
    FABLE_LEAP_EFFORT,
    FABLE_LEAP_FALLBACKS,
    FABLE_LEAP_MAX_TOKENS,
    FABLE_LEAP_MODELS,
    FABLE_LEAP_TIMEOUT_S,
    RETENTION_REQUIRED_MODELS,
    LeapShape,
    Settings,
    leap_shape,
    role_chain,
    role_settings,
)
from autonomous_ai_agents.common.models import ModelPrice

FABLE_5_2 = "claude-fable-5-2"
OPUS_4_8 = "claude-opus-4-8"
FABLES = ("claude-fable-5", "claude-fable-5-1", FABLE_5_2)


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _fable_leap(model: str = FABLE_5_2, /, **values: object) -> Settings:
    return _settings(
        IDEA_PIPELINE=True, ALLOW_RETENTION_MODELS=True, IDEAS_LEAP_MODEL=model,
        **values,
    )  # fmt: skip


# ---------------------------------------------------------------------------
# The tables
# ---------------------------------------------------------------------------


def test_fable_5_2_is_priced_as_the_pricing_page_lists_it() -> None:
    """
    GIVEN the pricing page (read 2026-11-11): Fable 5.2 $8 input, $10
          5-minute writes, $0.20 cache hits (0.025x), $40 output, no
          long-context tier
    WHEN the default price table is read
    THEN its row matches, a 5-minute write is 1.25x input
    """
    price = _settings().MODEL_PRICING[FABLE_5_2]
    assert price == ModelPrice(
        input=8.0, output=40.0, cache_write=10.0, cache_read=0.20
    )
    assert price.cache_write == pytest.approx(1.25 * price.input)
    assert price.cache_read == pytest.approx(0.025 * price.input)
    assert price.long_context is None


def test_fable_5_2_takes_all_five_effort_levels() -> None:
    assert EFFORT_LEVELS[FABLE_5_2] == frozenset(
        {"low", "medium", "high", "xhigh", "max"}
    )


def test_the_5_2_models_require_30_day_retention() -> None:
    assert {FABLE_5_2, "claude-mythos-5-2"} <= RETENTION_REQUIRED_MODELS


def test_the_fable_leap_constants() -> None:
    """X1-1's timeout (``tests/live/ideas_probe.py``) is the leap's, verbatim."""
    assert frozenset(FABLES) == FABLE_LEAP_MODELS
    assert FABLE_LEAP_FALLBACKS == (OPUS_4_8,)
    assert (FABLE_LEAP_EFFORT, FABLE_LEAP_MAX_TOKENS) == ("high", 32_000)
    assert FABLE_LEAP_TIMEOUT_S == float(X1_1_TIMEOUT_S) == 951.0
    # The fallback is priced, takes the leap's effort and needs no retention.
    assert OPUS_4_8 in _settings().MODEL_PRICING
    assert FABLE_LEAP_EFFORT in EFFORT_LEVELS[OPUS_4_8]
    assert OPUS_4_8 not in RETENTION_REQUIRED_MODELS


# ---------------------------------------------------------------------------
# The Fable leap's chain, shape and settings copy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", FABLES)
def test_a_fable_leap_falls_back_to_opus_4_8_alone(model: str) -> None:
    cfg = _fable_leap(model)
    assert role_chain(cfg, "leap") == (model, OPUS_4_8)
    copy = role_settings(cfg, "leap")
    assert chain(copy) == role_chain(cfg, "leap")
    assert (copy.ENGINE_MODEL, copy.ENGINE_FALLBACKS) == (model, True)
    assert copy.ENGINE_FALLBACK_MODELS == (OPUS_4_8,)
    assert copy.LLM_TIMEOUT_S == FABLE_LEAP_TIMEOUT_S
    assert (copy.EDITOR_MODEL, copy.UNDERSTAND_EFFORT) == (None, None)


@pytest.mark.parametrize("model", FABLES)
def test_a_fable_leap_has_a_fixed_shape_whatever_the_leap_settings(
    model: str,
) -> None:
    fixed = LeapShape(effort="high", max_tokens=32_000, timeout_s=951.0)
    assert leap_shape(_fable_leap(model)) == fixed
    moved = _fable_leap(model, IDEAS_LEAP_EFFORT="low", IDEAS_LEAP_MAX_TOKENS=20_000)
    assert leap_shape(moved) == fixed


def test_the_fable_timeout_is_the_leap_copys_only() -> None:
    """The run's timeout and every other role's copy keep their 300 s."""
    cfg = _fable_leap()
    assert cfg.LLM_TIMEOUT_S == 300.0
    for role in ("engine", "editor", "generator", "matcher", "lane", "reviewer"):
        assert role_settings(cfg, role).LLM_TIMEOUT_S == 300.0, role
    assert role_settings(cfg, "leap", LLM_TIMEOUT_S=42.0).LLM_TIMEOUT_S == 42.0


def test_the_fable_timeout_never_lowers_a_longer_run_timeout() -> None:
    cfg = _fable_leap(LLM_TIMEOUT_S=1200.0)
    assert leap_shape(cfg).timeout_s == 1200.0
    assert role_settings(cfg, "leap").LLM_TIMEOUT_S == 1200.0
    assert leap_shape(_fable_leap(LLM_TIMEOUT_S=951.5)).timeout_s == 951.5


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5"])
def test_an_opus_or_sonnet_leap_is_unchanged(model: str) -> None:
    cfg = _settings(IDEA_PIPELINE=True, IDEAS_LEAP_MODEL=model,
                    IDEAS_LEAP_EFFORT="medium", IDEAS_LEAP_MAX_TOKENS=9000)  # fmt: skip
    assert role_chain(cfg, "leap") == (model,)
    assert leap_shape(cfg) == LeapShape(
        effort="medium", max_tokens=9000, timeout_s=None
    )
    copy = role_settings(cfg, "leap")
    assert chain(copy) == (model,)
    assert (copy.ENGINE_FALLBACKS, copy.LLM_TIMEOUT_S) == (False, 300.0)
    assert copy.ENGINE_FALLBACK_MODELS == cfg.ENGINE_FALLBACK_MODELS


def test_the_default_leap_copy_is_what_it_was() -> None:
    cfg = _settings(IDEA_PIPELINE=True)
    copy = role_settings(cfg, "leap")
    assert leap_shape(cfg) == LeapShape(
        effort="high", max_tokens=12_000, timeout_s=None
    )
    assert copy.model_dump() == cfg.model_copy(update={
        "ENGINE_MODEL": "claude-opus-5-5", "ENGINE_FALLBACKS": False,
        "EDITOR_MODEL": None, "UNDERSTAND_EFFORT": None, "EDITOR_EFFORT": None,
    }).model_dump()  # fmt: skip


# ---------------------------------------------------------------------------
# The guards that already hold for fallback models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pipeline", [True, False])
def test_a_fable_5_2_leap_is_refused_without_the_retention_flag(
    pipeline: bool,
) -> None:
    """D63, as for Fable 5.1: refused with the pipeline on or off."""
    with pytest.raises(
        ValidationError, match=f"leap.*{FABLE_5_2}.*ALLOW_RETENTION_MODELS"
    ):
        _settings(IDEA_PIPELINE=pipeline, IDEAS_LEAP_MODEL=FABLE_5_2)
    cfg = _settings(
        IDEA_PIPELINE=pipeline, IDEAS_LEAP_MODEL=FABLE_5_2, ALLOW_RETENTION_MODELS=True
    )
    assert role_chain(cfg, "leap")[0] == FABLE_5_2
    with pytest.raises(ValidationError, match="ALLOW_RETENTION_MODELS"):
        role_settings(cfg, "leap", ALLOW_RETENTION_MODELS=False)


def test_the_leap_fallback_must_be_priced() -> None:
    """The price check bills the leap's whole chain, fallback included."""
    prices = {
        name: price
        for name, price in _settings().MODEL_PRICING.items()
        if name != OPUS_4_8
    }
    values: dict[str, object] = {
        "ENGINE_FALLBACK_MODELS": ("claude-opus-5",),
        "MODEL_PRICING": prices,
    }
    _settings(IDEA_PIPELINE=True, **values)  # an Opus leap needs no Opus 4.8
    with pytest.raises(ValidationError, match=f"no price for {OPUS_4_8}"):
        _fable_leap(**values)
