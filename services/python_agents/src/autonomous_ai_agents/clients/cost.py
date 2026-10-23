"""What a paid Claude request may cost before it is sent, and what it cost.

The run budget (``clients/budget.py``) is a hard cap only if two numbers are
right:

- ``preflight_estimate``, passed to ``Budget.check`` **before** every attempt:
  the most that attempt can be billed.
- ``response_cost``, passed to ``Budget.record`` **after** it: what the
  response reports was billed.

Why the estimate is a bound. With server-side fallbacks, one request is
served by at most one attempt per entry of ``chain()``, and the response's
``usage.iterations`` lists every attempt with the model that ran it. Each
attempt reads the same prompt, at most ``prompt_token_bound`` tokens (the
input the API adds for tools included) billed as some mix of plain input,
cache write and cache read, and writes at most ``max_tokens``. So
``len(chain) x (prompt x dearest input-side rate + max_tokens x dearest
output rate)``, taken over the chain, is at least the cost of any response
within those limits. Both functions add up in exact rational arithmetic and
round to a float once, and rounding is monotone, so rounding can never lift
a cost above its estimate. The property is checked over many random usage
shapes in ``tests/clients/test_cost.py``.

Long-context tiers (``ModelPrice.long_context``, Claude Haiku 5.5). Pricing
page, "Long context pricing" (platform.claude.com, read 2026-10-23): "a
request whose prompt is over 100,000 tokens pays higher prices. A request's
prompt length counts all of its input tokens, including cache reads and
cache writes. Each request is priced on its own." So ``response_cost``
prices an attempt whose input, cache-write and cache-read tokens add up to
more than ``threshold_tokens`` at the long rates for every component, output
included. ``preflight_estimate`` takes, per model and component, the dearer
of the base and long rates whenever the prompt bound, plus one count margin,
is over the threshold (some billed prompt could be): the bound still holds.

The bound has three preconditions, all on the callers:

- **Only 5-minute cache writes.** ``response_cost`` prices a 1-hour write at
  its true rate, twice the base input rate. The estimate does not charge
  that rate (for every real model it is above ``cache_write``, 2x against
  1.25x input), so a request that asked for ``ttl: "1h"`` may cost more than
  its estimate. The engine only uses the 5-minute TTL; if that ever breaks,
  the honest cost lets ``Budget.record`` see the overrun instead of hiding
  it.
- **Every billing model is priced, or nothing dearer than the chain is
  listed.** A model missing from the price table is priced at the dearest
  listed rate for each component, across the whole table, while the estimate
  takes the chain's rates. A dearer unchained model then lifts an unknown
  model's cost above the estimate: an over-count, so the safe direction. The
  settings validator already requires a price for every model in the chain.
- **A count off by at most one more margin, near a long-context tier.**
  ``prompt_tokens`` is ``count_tokens`` plus ``count_margin`` in production,
  and the count is only an estimate. Without a tier, a billed prompt a few
  tokens past the bound costs only those tokens more; past a tier's threshold it
  would re-price the whole request (Haiku 5.5: 5x input). So the estimate
  treats a bound within ``count_margin(bound)`` of a threshold as crossing
  it: a billed prompt up to ``bound + count_margin(bound)`` never pays a tier
  the estimate left out, and overruns the estimate only by its extra tokens.
  The margin constants are ``COUNT_MARGIN_MIN_TOKENS`` and
  ``COUNT_MARGIN_DIVISOR``, the same ones ``transport`` pads its count with.

Rates are USD per million tokens (``ModelPrice``). ``prompt_token_bound``
also counts the input the API adds when tools are sent: its tool-use system
prompt and the definitions of server-defined tools, at the largest figures
the docs give (``TOOL_USE_SYSTEM_PROMPT_TOKENS``,
``BUILTIN_TOOL_INPUT_TOKENS``). A server tool without a documented figure is
refused.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from fractions import Fraction
from types import MappingProxyType
from typing import Final

from pydantic import BaseModel

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import LongContextPrice, ModelPrice

_Rates = ModelPrice | LongContextPrice
"""Four per-MTok rates; only ``input``, ``output`` and the cache rates are read."""

_PER_MTOK: Final = Fraction(1_000_000)
# Pricing page, prompt caching: a 1-hour cache write bills 2x base input.
_ONE_HOUR_WRITE_PER_INPUT: Final = Fraction(2)

# Input the API adds whenever ``tools`` is non-empty, in tokens. From the live
# docs, 2026-10-21: the largest tool-use system prompt on the pricing page
# (804, Opus 4.7 with tool_choice any/tool; Opus 5.5 and Opus 5 are 286, Opus
# 4.8 is 290), and the text editor page's "additional input tokens" (974 for
# text_editor_20250728 on Claude 4.7 and later, 745 on 4.6 and earlier).
TOOL_USE_SYSTEM_PROMPT_TOKENS: Final = 804
BUILTIN_TOOL_INPUT_TOKENS: Final[Mapping[str, int]] = MappingProxyType(
    {"text_editor_20250728": 974}
)


COUNT_MARGIN_MIN_TOKENS: Final = 16
COUNT_MARGIN_DIVISOR: Final = 50
"""``count_tokens`` is an estimate: a count gains 1/50 (2 %), at least 16 tokens."""


def count_margin(tokens: int) -> int:
    """The margin added to a token count: ``ceil(tokens / 50)``, at least 16."""
    return max(COUNT_MARGIN_MIN_TOKENS, -(-tokens // COUNT_MARGIN_DIVISOR))


def chain(cfg: Settings = settings) -> tuple[str, ...]:
    """Every model one engine request may bill, in the order the API tries them.

    The same list ``AnthropicTransport`` sends: the engine model, then
    ``ENGINE_FALLBACK_MODELS`` verbatim (repeats included) when
    ``ENGINE_FALLBACKS`` is on. The estimate is a bound only for this chain.
    """
    if cfg.ENGINE_FALLBACKS:
        return (cfg.ENGINE_MODEL, *cfg.ENGINE_FALLBACK_MODELS)
    return (cfg.ENGINE_MODEL,)


def response_cost(
    usage: object, prices: Mapping[str, ModelPrice], *, model: str
) -> tuple[float, int]:
    """Return ``(USD, tokens)`` billed for one response.

    ``usage`` is the SDK's ``Usage`` or ``BetaUsage``, or a mapping with the
    same keys: ``input_tokens`` and ``output_tokens`` (required),
    ``cache_creation_input_tokens`` and ``cache_read_input_tokens`` (absent or
    None counts as 0), and optional ``cache_creation`` and ``iterations``.
    ``model`` is the response's model, the one that produced the message.

    When ``iterations`` lists attempts, they are the billing truth and the
    top level (which covers only the serving attempt) is ignored. Each
    attempt is priced at its own ``model``, or at ``model`` when it names
    none. ``cache_creation`` splits the cache writes by TTL: 5-minute ones
    bill at ``cache_write``, 1-hour ones at twice ``input``; without the
    split every write is a 5-minute one. An attempt whose prompt (input,
    cache-write and cache-read tokens) is over its model's
    ``long_context.threshold_tokens`` bills every component at the long
    rates. ``tokens`` counts every input, cache and output token.

    Raises ``ValueError`` on a negative, fractional, boolean or missing
    count, a TTL split that does not add up to its total, a malformed
    ``iterations``, an empty price table, or a cost too large for a float.
    """
    if not prices:
        raise ValueError("the price table is empty, so nothing can be priced")
    micro_usd = Fraction(0)
    tokens = 0
    for attempt in _attempts(usage):
        price = prices.get(_attempt_model(attempt, model))
        read = _counts(attempt)
        prompt = read[0] + read[2] + read[3] + read[4]
        rates = (
            _worst(_rates_at(listed, prompt) for listed in prices.values())
            if price is None
            else _rates_at(price, prompt)
        )
        micro_usd += (
            read[0] * Fraction(rates.input)
            + read[1] * Fraction(rates.output)
            + read[2] * Fraction(rates.cache_write)
            + read[3] * _ONE_HOUR_WRITE_PER_INPUT * Fraction(rates.input)
            + read[4] * Fraction(rates.cache_read)
        )
        tokens += sum(read)
    return _usd(micro_usd), tokens


def preflight_estimate(
    prompt_tokens: int,
    max_tokens: int,
    models: Sequence[str],
    prices: Mapping[str, ModelPrice],
) -> float:
    """The most one request can cost: ``len(models)`` worst-case attempts, in USD.

    ``models`` is the request's ``chain()``. Every prompt token is charged
    at the dearest of input, cache-write and cache-read rates, and every
    ``max_tokens`` token at the dearest output rate, each taken over the
    chain separately. When ``prompt_tokens`` plus its ``count_margin`` is
    over a model's long-context threshold, that model's long rates count too
    (the dearer of base and long per component). ``cache_write`` is the 5-minute rate: the bound
    assumes no 1-hour cache writes (module docstring). Raises ``ValueError`` on a
    bad count, an empty chain, a bare string as the chain, or a chain model
    with no price.
    """
    prompt = _count("prompt_tokens", prompt_tokens)
    output = _count("max_tokens", max_tokens)
    if isinstance(models, str) or not models:
        raise ValueError("the model chain must be a non-empty sequence of model ids")
    missing = sorted({name for name in models if name not in prices})
    if missing:
        raise ValueError(f"the model chain has no price for {', '.join(missing)}")
    worst = _worst(_rates_upto(prices[name], prompt) for name in models)
    input_side = max(worst.input, worst.cache_write, worst.cache_read)
    attempt = prompt * Fraction(input_side) + output * Fraction(worst.output)
    return _usd(len(models) * attempt)


def prompt_token_bound(
    system: str | Sequence[Mapping[str, object]] | None,
    tools: Sequence[Mapping[str, object]],
    messages: Sequence[Mapping[str, object]],
) -> int:
    """An upper bound on a request's prompt tokens.

    It is the UTF-8 byte count of the three parts, dumped as one compact,
    key-sorted JSON array (so key order does not matter), plus the input the
    API adds for tools. No text token covers less than one byte, and escaping
    only adds bytes. SDK content blocks and tools (pydantic models) count as
    their full dump, at least what the SDK sends for them. When ``tools`` is
    non-empty, ``TOOL_USE_SYSTEM_PROMPT_TOKENS`` is added once, and each
    server-defined tool (a ``type`` other than ``"custom"``) adds its entry
    in ``BUILTIN_TOOL_INPUT_TOKENS``: the request carries only its name, the
    API bills its whole definition.

    Raises ``ValueError`` on NaN or infinity, on text with no UTF-8 form (a
    lone surrogate), and on a tool whose type is not text or has no
    documented input figure; ``TypeError`` on a value JSON cannot hold.
    """
    body = json.dumps(
        [system, tools, messages],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_jsonable,
    )
    return len(body.encode("utf-8")) + _tool_input_tokens(tools)


def _tool_input_tokens(tools: Sequence[object]) -> int:
    """The input the API adds for ``tools`` beyond the bytes the client sends."""
    if not tools:
        return 0
    added = TOOL_USE_SYSTEM_PROMPT_TOKENS
    for tool in tools:
        kind = _field(tool, "type")
        if kind is None or kind == "custom":
            continue
        if not isinstance(kind, str):
            raise ValueError(f"a tool's type must be text, got {kind!r}")
        if kind not in BUILTIN_TOOL_INPUT_TOKENS:
            raise ValueError(
                f"no documented input size for server tool {kind!r}; "
                "add it to BUILTIN_TOOL_INPUT_TOKENS before sending it"
            )
        added += BUILTIN_TOOL_INPUT_TOKENS[kind]
    return added


def _jsonable(value: object) -> object:
    """Turn SDK models and non-dict mappings into what ``json`` can dump."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{type(value).__name__} cannot be part of a request body")


def _rates_at(price: ModelPrice, prompt: int) -> _Rates:
    """The rates a request with ``prompt`` prompt tokens pays on this model."""
    long = price.long_context
    if long is not None and prompt > long.threshold_tokens:
        return long
    return price


def _rates_upto(price: ModelPrice, prompt_bound: int) -> _Rates:
    """The dearest rates of any prompt the API may bill under ``prompt_bound``.

    A bound within ``count_margin(prompt_bound)`` of the threshold counts as
    crossing it (third precondition in the module docstring).
    """
    long = price.long_context
    reach = prompt_bound + count_margin(prompt_bound)
    if long is not None and reach > long.threshold_tokens:
        return _worst((price, long))
    return price


def _worst(rates: Iterable[_Rates]) -> ModelPrice:
    """The dearest rate for each component over a non-empty ``rates``."""
    listed = tuple(rates)
    return ModelPrice(
        input=max(rate.input for rate in listed),
        output=max(rate.output for rate in listed),
        cache_write=max(rate.cache_write for rate in listed),
        cache_read=max(rate.cache_read for rate in listed),
    )


def _field(source: object, name: str) -> object:
    """Read ``name`` from a mapping or an SDK object; None when absent."""
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _attempts(usage: object) -> tuple[object, ...]:
    """The billed attempts: the iterations, or the usage itself without them."""
    iterations = _field(usage, "iterations")
    if iterations is None:
        return (usage,)
    if isinstance(iterations, str | bytes) or not isinstance(iterations, Sequence):
        raise ValueError(
            "usage iterations must be a list of attempts, "
            f"got {type(iterations).__name__}"
        )
    return tuple(iterations) or (usage,)


def _attempt_model(attempt: object, response_model: str) -> str:
    """The model that billed an attempt; the response's model if it names none."""
    named = _field(attempt, "model")
    if named is None:
        return response_model
    if not isinstance(named, str):
        raise ValueError(f"an attempt's model must be a model id, got {named!r}")
    return named


def _counts(attempt: object) -> tuple[int, int, int, int, int]:
    """``(input, output, 5-minute write, 1-hour write, cache_read)`` tokens."""
    plain = _count("input_tokens", _field(attempt, "input_tokens"))
    output = _count("output_tokens", _field(attempt, "output_tokens"))
    five_minute, one_hour = _cache_writes(attempt)
    read = _count(
        "cache_read_input_tokens",
        _field(attempt, "cache_read_input_tokens"),
        required=False,
    )
    return plain, output, five_minute, one_hour, read


def _cache_writes(attempt: object) -> tuple[int, int]:
    """``(5-minute, 1-hour)`` cache-write tokens of one attempt.

    ``cache_creation`` breaks ``cache_creation_input_tokens`` down by TTL, so
    the two must agree; a missing total is the split's sum. Without a split,
    every write is a 5-minute one.
    """
    stated = _field(attempt, "cache_creation_input_tokens")
    total = _count("cache_creation_input_tokens", stated, required=False)
    split = _field(attempt, "cache_creation")
    if split is None:
        return total, 0
    five_minute = _count(
        "ephemeral_5m_input_tokens", _field(split, "ephemeral_5m_input_tokens")
    )
    one_hour = _count(
        "ephemeral_1h_input_tokens", _field(split, "ephemeral_1h_input_tokens")
    )
    if stated is not None and five_minute + one_hour != total:
        raise ValueError(
            f"cache_creation splits {five_minute + one_hour} cache-write tokens "
            f"by TTL, but cache_creation_input_tokens is {total}"
        )
    return five_minute, one_hour


def _count(name: str, value: object, *, required: bool = True) -> int:
    """A whole token count of at least 0; an optional one may be None (0)."""
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a whole number >= 0, got {value!r}")
    return value


def _usd(micro_usd: Fraction) -> float:
    """Convert exact micro-dollars to USD, rounding once."""
    try:
        return float(micro_usd / _PER_MTOK)
    except OverflowError:
        raise ValueError("the cost is too large for a float") from None
