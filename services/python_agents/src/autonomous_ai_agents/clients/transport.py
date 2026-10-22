"""The one door to the Claude API: transports and the retry loop.

``AnthropicTransport`` holds the only SDK client: ``max_retries=0`` (SDK
retries would void the cost cap), ``timeout=LLM_TIMEOUT_S`` (connect <= 10 s),
redirects off (one would carry the key and prompt to another host). It sends
``cost.chain(settings)`` as the explicit ``fallbacks`` array with the
``server-side-fallback-2026-06-01`` beta (never the ``"default"`` scalar,
which may pick an unpriced model), and never ``thinking``, ``temperature``
or ``tool_choice``. ``call()`` is spec decision 9. Mapped errors keep only
status, type and request id, and never chain the SDK exception (it holds the
key, the prompt and the API's message), so no traceback prints them.
"""

from __future__ import annotations

import json
import math
import re
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol, TypeAlias

import anthropic
import httpx2
from anthropic import omit
from anthropic.types.beta import (
    BetaCacheControlEphemeralParam,
    BetaFallbackParam,
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaTextBlockParam,
    BetaToolUnionParam,
    BetaUsage,
)

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import (
    chain,
    preflight_estimate,
    prompt_token_bound,
    response_cost,
)
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import (
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
)
from autonomous_ai_agents.common.models import ModelPrice

FALLBACK_BETA: Final = "server-side-fallback-2026-06-01"
RETRYABLE_STATUSES: Final = frozenset({429, 500, 502, 503, 504, 529})
CONFIG_STATUSES: Final = frozenset({401, 402, 403})  # 402: billing, the account
MAX_BACKOFF_S: Final = 30.0
MAX_RETRY_AFTER_S: Final = 60.0
CONNECT_TIMEOUT_S: Final = 10.0
COUNT_TIMEOUT_S: Final = 30.0  # one free count request; both capped by LLM_TIMEOUT_S
COUNT_MARGIN_MIN_TOKENS: Final = 16
COUNT_MARGIN_DIVISOR: Final = 50
"""``count_tokens`` is an estimate: it gains 1/50 (2 %), at least 16 tokens."""

_PLACEHOLDER_KEY: Final = "your-api-key-here"  # the .env.example value
_ERROR_TYPE: Final = re.compile(r"[a-z_]{1,64}")
_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9_-]{1,128}")


class LLMHTTPUnavailableError(LLMUnavailable):
    """A retryable HTTP answer (429, 5xx, 529): no usage, so it costs 0."""

    def __init__(
        self, text: str, *, status_code: int, retry_after: float | None
    ) -> None:
        super().__init__(text)
        self.status_code = status_code
        self.retry_after = retry_after


class LLMNoResponseError(LLMUnavailable):
    """A timeout or a lost connection: the server may have billed the attempt."""

    def __init__(self, text: str, *, timed_out: bool) -> None:
        super().__init__(text)
        self.timed_out = timed_out


class LLMUnreadableResponseError(LLMRequestError):
    """A 2xx answer that is not a readable, priceable message. Not retried."""


@dataclass(frozen=True)
class LLMRequest:
    """One Messages API request; the model comes from the transport's chain.

    ``cache`` puts a 5-minute breakpoint on the system block and asks for
    top-level automatic caching; other breakpoints must be 5-minute ones.
    ``prompt_allowance_tokens`` (input the API adds that neither the bytes
    nor the count show) is added to every prompt-size figure.
    """

    system: str
    messages: tuple[BetaMessageParam, ...]
    max_tokens: int
    tools: tuple[BetaToolUnionParam, ...] = ()
    output_config: BetaOutputConfigParam | None = None
    cache: bool = True
    prompt_allowance_tokens: int = 0

    def __post_init__(self) -> None:
        _require_whole("max_tokens", self.max_tokens, minimum=1)
        _require_whole("prompt_allowance_tokens", self.prompt_allowance_tokens)
        if not self.messages:
            raise ValueError("a request needs at least one message")
        if _has_long_ttl((self.tools, self.messages)):
            raise ValueError(
                "only 5-minute cache breakpoints are allowed: the cost "
                "estimate does not cover 1-hour cache writes"
            )


@dataclass(frozen=True)
class LLMResult:
    """One ``call()``: the answer and all it recorded in the budget (lost
    attempts included). ``unpriced_models`` are billing models missing from
    the price table, which ``response_cost`` priced at the dearest rate."""

    message: BetaMessage
    cost_usd: float
    tokens: int
    estimate_usd: float
    served_model: str
    fell_back: bool
    unpriced_models: tuple[str, ...]
    attempts: int


class LLMTransport(Protocol):
    """Sends one attempt; ``call()`` owns retries, pricing and the budget."""

    @property
    def chain(self) -> tuple[str, ...]: ...

    @property
    def prices(self) -> Mapping[str, ModelPrice]: ...

    def count_input_tokens(self, request: LLMRequest) -> int: ...

    def send(self, request: LLMRequest) -> BetaMessage: ...


class _ChainPricing:
    """The chain a transport sends and the prices ``call()`` applies to it."""

    def __init__(self, cfg: Settings) -> None:
        self._chain = chain(cfg)
        self._prices = MappingProxyType(dict(cfg.MODEL_PRICING))

    @property
    def chain(self) -> tuple[str, ...]:
        return self._chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._prices


class AnthropicTransport(_ChainPricing):
    """The real Claude API, through ``client.beta.messages``.

    The HTTP client is always built here, so redirects stay off;
    ``http_transport`` only swaps the wire (tests pass a mock).
    """

    def __init__(
        self,
        cfg: Settings = settings,
        *,
        http_transport: httpx2.BaseTransport | None = None,
    ) -> None:
        super().__init__(cfg)
        secret = cfg.ANTHROPIC_API_KEY
        if secret is None:
            raise LLMConfigError("ANTHROPIC_API_KEY is not set (.env or environment)")
        if _PLACEHOLDER_KEY in secret.get_secret_value():
            raise LLMConfigError("ANTHROPIC_API_KEY holds the .env.example placeholder")
        self._client = anthropic.Anthropic(
            api_key=secret.get_secret_value(),
            max_retries=0,
            timeout=_timeout(cfg.LLM_TIMEOUT_S, cfg.LLM_TIMEOUT_S),
            http_client=anthropic.DefaultHttpxClient(
                transport=http_transport, follow_redirects=False
            ),
        )
        self._count_timeout = _timeout(COUNT_TIMEOUT_S, cfg.LLM_TIMEOUT_S)

    def __repr__(self) -> str:
        return f"AnthropicTransport(chain={self._chain!r})"

    def count_input_tokens(self, request: LLMRequest) -> int:
        """The largest count over the chain, plus its margin and the allowance.

        Tokenizers differ, so each distinct model is counted once (the
        endpoint is free). Any failure, or a count that is not a whole
        number, gives the byte bound instead; nothing is retried.
        """
        counts: list[int] = []
        for model in dict.fromkeys(self._chain):
            try:
                reply = self._client.beta.messages.count_tokens(
                    model=model,
                    messages=list(request.messages),
                    system=_system(request) or omit,
                    tools=list(request.tools) or omit,
                    output_config=request.output_config or omit,
                    cache_control=_ephemeral() if request.cache else omit,
                    timeout=self._count_timeout,
                )
            except Exception:  # any failure: the byte bound still holds
                return _byte_bound(request)
            counted = getattr(reply, "input_tokens", None)
            if isinstance(counted, bool) or not isinstance(counted, int) or counted < 0:
                return _byte_bound(request)
            counts.append(counted)
        top = max(counts)
        margin = max(COUNT_MARGIN_MIN_TOKENS, -(-top // COUNT_MARGIN_DIVISOR))
        return top + margin + request.prompt_allowance_tokens

    def send(self, request: LLMRequest) -> BetaMessage:
        """One attempt, no retries; SDK failures become engine errors."""
        fallbacks: list[BetaFallbackParam] = [{"model": m} for m in self._chain[1:]]
        failure: Exception
        try:
            reply = self._client.beta.messages.create(
                model=self._chain[0],
                max_tokens=request.max_tokens,
                messages=list(request.messages),
                system=_system(request) or omit,
                tools=list(request.tools) or omit,
                output_config=request.output_config or omit,
                cache_control=_ephemeral() if request.cache else omit,
                fallbacks=fallbacks or omit,
                betas=[FALLBACK_BETA] if fallbacks else omit,
            )
        except anthropic.APIError as exc:
            failure = _map_sdk_error(exc)
        except json.JSONDecodeError:  # its .doc holds the whole body
            failure = LLMUnreadableResponseError("the 2xx body is not JSON")
        else:
            return _checked(reply)
        raise failure  # outside the handler: no __cause__ or __context__


ScriptedReply: TypeAlias = BetaMessage | Mapping[str, object] | Exception


class ScriptedTransport(_ChainPricing):
    """Replays replies in order and records every request (tests, the E2E).

    A reply is a ``BetaMessage``, a fixture mapping (validated at once), an
    engine error (raised as is) or an SDK exception (mapped as the real
    client maps it). An empty queue fails the request with ``LLMRequestError``.
    The count is the byte bound.
    """

    def __init__(
        self, replies: Iterable[ScriptedReply], *, cfg: Settings = settings
    ) -> None:
        super().__init__(cfg)
        self._replies: deque[BetaMessage | Exception] = deque(
            r
            if isinstance(r, BetaMessage | Exception)
            else BetaMessage.model_validate(r)
            for r in replies
        )
        self.requests: list[LLMRequest] = []

    @property
    def remaining(self) -> int:
        """Replies not yet sent back."""
        return len(self._replies)

    def count_input_tokens(self, request: LLMRequest) -> int:
        return _byte_bound(request)

    def send(self, request: LLMRequest) -> BetaMessage:
        self.requests.append(request)
        if not self._replies:
            raise LLMRequestError("the scripted transport has no reply left")
        reply = self._replies.popleft()
        if isinstance(reply, anthropic.APIError):
            raise _map_sdk_error(reply)
        if isinstance(reply, Exception):
            raise reply
        return reply


def call(
    transport: LLMTransport,
    request: LLMRequest,
    budget: Budget,
    *,
    sleep: Callable[[float], None],
    max_retries: int = settings.LLM_MAX_RETRIES,
) -> LLMResult:
    """Send ``request`` under the budget and the retry policy (decision 9).

    Raises ``BudgetExceeded`` before an attempt the budget cannot afford (or
    after a response that cost more than was left), ``LLMConfigError`` on
    401/402/403, ``LLMRequestError`` on any other refusal (not retried), and
    ``LLMUnavailable`` once the retries are spent or the server asks to wait
    more than ``MAX_RETRY_AFTER_S``. A ``refusal`` stop reason is returned.
    """
    _require_whole("max_retries", max_retries)
    estimate = preflight_estimate(
        transport.count_input_tokens(request),
        request.max_tokens,
        transport.chain,
        transport.prices,
    )
    charged, attempt, delay = 0.0, 0, 0.0
    while True:
        budget.check(estimate)
        if attempt:
            sleep(delay)
        attempt += 1
        retry_after: float | None = None
        try:
            message = transport.send(request)
        except LLMHTTPUnavailableError as exc:
            failure: LLMUnavailable = exc
            retry_after = exc.retry_after
        except (LLMUnavailable, LLMUnreadableResponseError) as exc:
            budget.record(estimate, 0)
            charged += estimate
            if isinstance(exc, LLMUnreadableResponseError):
                raise
            failure = exc
        else:
            return _priced(message, transport, budget, estimate, charged, attempt)
        if attempt > max_retries:
            plural = "s" if attempt > 1 else ""
            raise LLMUnavailable(
                f"{failure} (gave up after {attempt} attempt{plural})"
            ) from failure
        if retry_after is not None and retry_after > MAX_RETRY_AFTER_S:
            raise LLMUnavailable(
                f"{failure} (asked to retry after {retry_after:g} s, "
                f"more than {MAX_RETRY_AFTER_S:g} s)"
            ) from failure
        backoff = min(MAX_BACKOFF_S, 2.0 ** min(attempt - 1, 16))
        delay = max(backoff, retry_after or 0.0)


def _priced(
    message: BetaMessage,
    transport: LLMTransport,
    budget: Budget,
    estimate: float,
    charged: float,
    attempts: int,
) -> LLMResult:
    """Price and record a successful attempt; describe the whole call."""
    prices = transport.prices
    try:
        usd, tokens = response_cost(message.usage, prices, model=message.model)
    except ValueError as exc:
        budget.record(estimate, 0)
        raise LLMUnreadableResponseError(
            "the response's usage could not be priced; charged the estimate"
        ) from exc
    budget.record(usd, tokens)
    iterations = message.usage.iterations or []
    billing = [_billing_model(i, message.model) for i in iterations]
    kinds = {i.type for i in iterations}
    return LLMResult(
        message=message,
        cost_usd=charged + usd,
        tokens=tokens,
        estimate_usd=estimate,
        served_model=message.model,
        fell_back="fallback_message" in kinds,
        unpriced_models=tuple(
            m for m in dict.fromkeys(billing or [message.model]) if m not in prices
        ),
        attempts=attempts,
    )


def _map_sdk_error(exc: anthropic.APIError) -> Exception:
    """The engine error for an SDK failure (timeouts first: they subclass
    connection errors). It copies no part of ``exc`` but status, type, id."""
    if isinstance(exc, anthropic.APITimeoutError):
        return LLMNoResponseError("Claude API: no answer in time", timed_out=True)
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMNoResponseError("Claude API: connection lost", timed_out=False)
    if not isinstance(exc, anthropic.APIStatusError):
        return LLMUnreadableResponseError(f"Claude API: {type(exc).__name__}")
    status, text = exc.status_code, _describe(exc)
    if status in CONFIG_STATUSES:
        return LLMConfigError(f"{text}: check ANTHROPIC_API_KEY and account access")
    if status in RETRYABLE_STATUSES:
        wait = _retry_after(exc.response.headers.get("retry-after"))
        return LLMHTTPUnavailableError(text, status_code=status, retry_after=wait)
    return LLMRequestError(text)


def _billing_model(iteration: object, response_model: str) -> str:
    """``cost.response_cost``'s rule: the attempt's own model, if it names one."""
    named = getattr(iteration, "model", None)  # compaction entries have none
    return named if isinstance(named, str) else response_model


def _timeout(seconds: float, cap_s: float) -> httpx2.Timeout:
    """``seconds`` (at most ``cap_s``) per phase; a connect gets at most 10 s."""
    whole = min(seconds, cap_s)
    return httpx2.Timeout(whole, connect=min(CONNECT_TIMEOUT_S, whole))


def _describe(exc: anthropic.APIStatusError) -> str:
    """Status, error type and request id only: never the body or its message."""
    kind: object = exc.type
    rid: object = exc.request_id
    if not (isinstance(kind, str) and _ERROR_TYPE.fullmatch(kind)):
        kind = "error"
    if not (isinstance(rid, str) and _REQUEST_ID.fullmatch(rid)):
        rid = "unknown"
    return f"Claude API HTTP {exc.status_code} {kind} (request id {rid})"


def _retry_after(value: str | None) -> float | None:
    """A numeric ``retry-after`` in seconds; an HTTP date or junk is ignored."""
    try:
        seconds = float(value) if value is not None else math.nan
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _checked(reply: object) -> BetaMessage:
    """The SDK does not validate a 2xx body: refuse one that is not a message."""
    if (
        isinstance(reply, BetaMessage)
        and isinstance(getattr(reply, "model", None), str)
        and isinstance(getattr(reply, "usage", None), BetaUsage)
        and isinstance(getattr(reply, "content", None), list)
    ):
        return reply
    raise LLMUnreadableResponseError("the 2xx answer is not a message")


def _ephemeral() -> BetaCacheControlEphemeralParam:
    return {"type": "ephemeral"}  # a 5-minute breakpoint


def _system(request: LLMRequest) -> list[BetaTextBlockParam]:
    """The system prompt as one text block (none when it is empty)."""
    if not request.system:
        return []
    block: BetaTextBlockParam = {"type": "text", "text": request.system}
    if request.cache:
        block["cache_control"] = _ephemeral()
    return [block]


def _byte_bound(request: LLMRequest) -> int:
    """``cost.prompt_token_bound`` of what is sent, output_config included."""
    bound = prompt_token_bound(_system(request), request.tools, request.messages)
    if request.output_config is not None:
        bound += prompt_token_bound(None, (), (request.output_config,))
    return bound + request.prompt_allowance_tokens


def _has_long_ttl(node: object) -> bool:
    """True when any ``cache_control`` below ``node`` asks for a non-5m TTL."""
    if isinstance(node, Mapping):
        control = node.get("cache_control")
        if isinstance(control, Mapping) and control.get("ttl", "5m") != "5m":
            return True
        return any(_has_long_ttl(value) for value in node.values())
    if isinstance(node, list | tuple):
        return any(_has_long_ttl(item) for item in node)
    return False


def _require_whole(name: str, value: object, *, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be a whole number >= {minimum}, got {value!r}")
