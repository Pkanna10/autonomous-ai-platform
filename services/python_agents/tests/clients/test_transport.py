"""Tests for the Claude transport and its retry loop (Step 2, unit U12).

``AnthropicTransport`` is the only module that holds an SDK client. Its tests
run a real ``anthropic.Anthropic`` against ``httpx2.MockTransport``, so the
request body, the headers and the SDK's own exception classes are the real
ones, with no network. ``call()`` holds the retry and budget policy (spec
decision 9) and is tested through ``ScriptedTransport``, plus a few runs
through the real client to tie the two together.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import logging
import traceback
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import NoReturn

import anthropic
import httpx2
import pytest
from anthropic import DefaultHttpxClient
from anthropic.types.beta import (
    BetaMessage,
    BetaMessageParam,
    BetaOutputConfigParam,
    BetaToolUnionParam,
)

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import (
    chain,
    preflight_estimate,
    prompt_token_bound,
    response_cost,
)
from autonomous_ai_agents.clients.transport import (
    CONFIG_STATUSES,
    CONNECT_TIMEOUT_S,
    COUNT_MARGIN_DIVISOR,
    COUNT_MARGIN_MIN_TOKENS,
    COUNT_TIMEOUT_S,
    FALLBACK_BETA,
    MAX_BACKOFF_S,
    MAX_RETRY_AFTER_S,
    RETRYABLE_STATUSES,
    AnthropicTransport,
    LLMHTTPUnavailableError,
    LLMNoResponseError,
    LLMRequest,
    LLMResult,
    LLMTransport,
    LLMUnreadableResponseError,
    ScriptedTransport,
    call,
)
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import (
    BudgetExceeded,
    EngineError,
    LLMConfigError,
    LLMRequestError,
    LLMUnavailable,
)

KEY = "sk-ant-api03-LEAKCHECK-7f3a9c0d"
ENGINE = "claude-opus-5-5"
FALLBACK = "claude-opus-4-8"
URL = "https://api.anthropic.com/v1/messages"
REQ = httpx2.Request("POST", URL)
FORBIDDEN_KEYS = ("thinking", "temperature", "tool_choice", "top_p", "top_k")

SYSTEM = "You implement one optimisation hypothesis in /repo."
TOOL: BetaToolUnionParam = {
    "type": "text_editor_20250728",
    "name": "str_replace_based_edit_tool",
    "max_characters": 20_000,
}
USER: BetaMessageParam = {"role": "user", "content": "Make unique_in_order faster."}
EFFORT: BetaOutputConfigParam = {"effort": "medium"}
BASE = LLMRequest(system=SYSTEM, messages=(USER,), max_tokens=8000)


def _settings(**overrides: object) -> Settings:
    """Settings from explicit values only, so the host environment cannot leak in."""
    base: dict[str, object] = {
        "ANTHROPIC_API_KEY": KEY,
        "ENGINE_MODEL": ENGINE,
        "ENGINE_FALLBACKS": True,
        "ENGINE_FALLBACK_MODELS": (FALLBACK,),
        "LLM_TIMEOUT_S": 300.0,
    }
    base.update(overrides)
    return Settings.model_validate(base)


def _message_json(
    *,
    model: str = ENGINE,
    stop_reason: str = "end_turn",
    usage: Mapping[str, object] | None = None,
    content: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": list(content) if content else [{"type": "text", "text": "done"}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": dict(usage) if usage else {"input_tokens": 100, "output_tokens": 50},
    }


def _message(
    *,
    model: str = ENGINE,
    stop_reason: str = "end_turn",
    usage: Mapping[str, object] | None = None,
) -> BetaMessage:
    return BetaMessage.model_validate(
        _message_json(model=model, stop_reason=stop_reason, usage=usage)
    )


Reply = httpx2.Response | Callable[[httpx2.Request], httpx2.Response]


class Wire:
    """A MockTransport handler: records every request, answers per endpoint."""

    def __init__(
        self, messages: Sequence[Reply] = (), counts: Sequence[Reply] = ()
    ) -> None:
        self._messages: deque[Reply] = deque(messages)
        self._counts: deque[Reply] = deque(counts)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        counting = request.url.path.endswith("/count_tokens")
        reply = (self._counts if counting else self._messages).popleft()
        return reply if isinstance(reply, httpx2.Response) else reply(request)

    @property
    def sent(self) -> list[httpx2.Request]:
        return [r for r in self.requests if not r.url.path.endswith("/count_tokens")]

    @property
    def counted(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path.endswith("/count_tokens")]


def _ok(
    *,
    usage: Mapping[str, object] | None = None,
    stop_reason: str = "end_turn",
    content: Sequence[Mapping[str, object]] | None = None,
) -> httpx2.Response:
    body = _message_json(usage=usage, stop_reason=stop_reason, content=content)
    return httpx2.Response(200, json=body)


def _error(
    status: int, kind: str = "api_error", headers: Mapping[str, str] | None = None
) -> httpx2.Response:
    body = {"type": "error", "error": {"type": kind, "message": "SECRET-DETAIL"}}
    return httpx2.Response(
        status, json=body, headers={"request-id": "req_abc123", **(headers or {})}
    )


def _count(tokens: object) -> httpx2.Response:
    return httpx2.Response(200, json={"input_tokens": tokens})


def _timeout(request: httpx2.Request) -> NoReturn:
    raise httpx2.ReadTimeout("read timed out", request=request)


def _disconnect(request: httpx2.Request) -> NoReturn:
    raise httpx2.ConnectError("connection refused", request=request)


def _transport(wire: Wire, cfg: Settings | None = None) -> AnthropicTransport:
    return AnthropicTransport(
        cfg or _settings(), http_transport=httpx2.MockTransport(wire)
    )


def _padded(counted: int) -> int:
    """The exact count plus the documented margin (2 %, at least 16 tokens)."""
    return counted + max(COUNT_MARGIN_MIN_TOKENS, -(-counted // COUNT_MARGIN_DIVISOR))


def _exception_chain(exc: BaseException) -> list[BaseException]:
    """``exc`` and every exception reachable through its cause and context."""
    found: list[BaseException] = []
    pending: list[BaseException | None] = [exc]
    while pending:
        current = pending.pop()
        if current is not None and current not in found:
            found.append(current)
            pending += [current.__cause__, current.__context__]
    return found


def _body(request: httpx2.Request) -> dict[str, object]:
    loaded = json.loads(request.content)
    assert isinstance(loaded, dict)
    return loaded


def _sdk_status(status: int, retry_after: str | None = None) -> anthropic.APIError:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    response = httpx2.Response(status, request=REQ, headers=headers)
    return anthropic.APIStatusError("boom", response=response, body=None)


def _no_sleep(seconds: float) -> None:
    raise AssertionError(f"slept {seconds} s where no retry was expected")


# ---------------------------------------------------------------------------
# LLMRequest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("max_tokens", [0, -1, True])
def test_a_request_refuses_a_bad_max_tokens(max_tokens: int) -> None:
    """
    GIVEN max_tokens that is not a whole number of at least 1
    WHEN a request is built
    THEN it is refused before anything can be priced or sent
    """
    with pytest.raises(ValueError, match="max_tokens"):
        dataclasses.replace(BASE, max_tokens=max_tokens)


@pytest.mark.parametrize("allowance", [-1, True])
def test_a_request_refuses_a_bad_prompt_allowance(allowance: int) -> None:
    """
    GIVEN a negative (or boolean) prompt allowance
    WHEN a request is built
    THEN it is refused: the allowance only ever adds to the bound
    """
    with pytest.raises(ValueError, match="prompt_allowance_tokens"):
        dataclasses.replace(BASE, prompt_allowance_tokens=allowance)


def test_a_request_needs_a_message() -> None:
    """
    GIVEN no messages
    WHEN a request is built
    THEN it is refused
    """
    with pytest.raises(ValueError, match="message"):
        dataclasses.replace(BASE, messages=())


def test_a_request_refuses_a_one_hour_cache_breakpoint() -> None:
    """
    GIVEN a block or a tool asking for a 1-hour cache write
    WHEN a request is built
    THEN it is refused: the cost estimate is a bound only for 5-minute writes
    """
    deep: BetaMessageParam = {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "t1",
                "content": [
                    {
                        "type": "text",
                        "text": "x",
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    }
                ],
            }
        ],
    }
    tool: BetaToolUnionParam = {
        "type": "text_editor_20250728",
        "name": "str_replace_based_edit_tool",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }

    with pytest.raises(ValueError, match="5-minute"):
        dataclasses.replace(BASE, messages=(deep,))
    with pytest.raises(ValueError, match="5-minute"):
        dataclasses.replace(BASE, tools=(tool,))


def test_a_request_accepts_five_minute_and_default_breakpoints() -> None:
    """
    GIVEN cache breakpoints with ttl "5m" or no ttl, and an echoed SDK block
    WHEN a request is built
    THEN it is accepted
    """
    message: BetaMessageParam = {
        "role": "user",
        "content": [
            {"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}},
            {
                "type": "text",
                "text": "b",
                "cache_control": {"type": "ephemeral", "ttl": "5m"},
            },
        ],
    }
    echoed: BetaMessageParam = {"role": "assistant", "content": _message().content}

    request = dataclasses.replace(BASE, messages=(message, echoed, USER))

    assert request.messages[0] == message


# ---------------------------------------------------------------------------
# AnthropicTransport: construction and the key
# ---------------------------------------------------------------------------


def test_no_api_key_is_a_config_error_naming_the_variable() -> None:
    """
    GIVEN settings without ANTHROPIC_API_KEY
    WHEN the transport is built
    THEN LLMConfigError (an EngineError) names the variable
    """
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY") as caught:
        AnthropicTransport(_settings(ANTHROPIC_API_KEY=None))

    assert isinstance(caught.value, EngineError)


def test_the_env_example_placeholder_key_is_refused_without_echoing_it() -> None:
    """
    GIVEN the placeholder value copied from .env.example
    WHEN the transport is built
    THEN LLMConfigError names the variable, never the value
    """
    placeholder = "sk-ant-api03-your-api-key-here"

    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY") as caught:
        AnthropicTransport(_settings(ANTHROPIC_API_KEY=placeholder))

    assert placeholder not in str(caught.value)


def test_the_transport_reports_its_chain_and_prices() -> None:
    """
    GIVEN the default chain settings
    WHEN the transport is built
    THEN its chain is cost.chain(settings) and its prices the settings table
    """
    cfg = _settings()

    transport = _transport(Wire(), cfg)

    assert transport.chain == (ENGINE, FALLBACK)
    assert dict(transport.prices) == cfg.MODEL_PRICING
    assert repr(transport) == f"AnthropicTransport(chain={(ENGINE, FALLBACK)!r})"


def test_the_client_has_the_settings_timeout_and_no_sdk_retries() -> None:
    """
    GIVEN LLM_TIMEOUT_S=123 and a server that answers 429
    WHEN one request is sent
    THEN exactly one HTTP request goes out (max_retries=0), with a 123 s
         timeout for reading, writing and the pool, and a 10 s connect timeout
    """
    wire = Wire(messages=[_error(429, "rate_limit_error")])
    transport = _transport(wire, _settings(LLM_TIMEOUT_S=123.0))

    with pytest.raises(LLMHTTPUnavailableError):
        transport.send(BASE)

    assert len(wire.requests) == 1
    assert CONNECT_TIMEOUT_S == 10.0
    assert wire.requests[0].extensions["timeout"] == {
        "connect": CONNECT_TIMEOUT_S,
        "read": 123.0,
        "write": 123.0,
        "pool": 123.0,
    }


# ---------------------------------------------------------------------------
# AnthropicTransport: the request on the wire
# ---------------------------------------------------------------------------


def test_the_body_carries_the_request_and_the_explicit_fallback_chain() -> None:
    """
    GIVEN a full request and the default chain
    WHEN it is sent
    THEN the body has the engine model, the cached system block, the tools,
         messages, output_config, top-level caching and fallbacks equal to
         ENGINE_FALLBACK_MODELS, the beta header is the array-form one, and
         thinking, temperature and tool_choice are absent
    """
    cfg = _settings()
    wire = Wire(messages=[_ok()])
    request = dataclasses.replace(BASE, tools=(TOOL,), output_config=EFFORT)

    message = _transport(wire, cfg).send(request)

    (sent,) = wire.sent
    body = _body(sent)
    assert sent.url.path == "/v1/messages"
    assert sent.headers["anthropic-beta"] == FALLBACK_BETA
    assert FALLBACK_BETA == "server-side-fallback-2026-06-01"
    assert sent.headers["x-api-key"] == KEY
    assert set(body) == {
        "model",
        "max_tokens",
        "system",
        "messages",
        "tools",
        "output_config",
        "cache_control",
        "fallbacks",
    }
    assert body["model"] == ENGINE
    assert body["max_tokens"] == 8000
    assert body["system"] == [
        {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
    ]
    assert body["messages"] == [USER]
    assert body["tools"] == [TOOL]
    assert body["output_config"] == EFFORT
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["fallbacks"] == [{"model": m} for m in cfg.ENGINE_FALLBACK_MODELS]
    assert not set(FORBIDDEN_KEYS) & set(body)
    assert isinstance(message, BetaMessage)
    assert message.model == ENGINE


def test_several_fallbacks_are_sent_verbatim_and_in_order() -> None:
    """
    GIVEN two fallback models, one of them repeated
    WHEN a request is sent
    THEN the fallbacks list is the configured list, verbatim
    """
    models = ("claude-opus-5", "claude-opus-4-8", "claude-opus-5")
    wire = Wire(messages=[_ok()])

    _transport(wire, _settings(ENGINE_FALLBACK_MODELS=models)).send(BASE)

    assert _body(wire.sent[0])["fallbacks"] == [{"model": m} for m in models]


@pytest.mark.parametrize(
    "overrides",
    [{"ENGINE_FALLBACKS": False}, {"ENGINE_FALLBACK_MODELS": ()}],
    ids=["fallbacks-off", "empty-fallback-list"],
)
def test_no_fallbacks_field_and_no_beta_header_without_a_fallback(
    overrides: dict[str, object],
) -> None:
    """
    GIVEN ENGINE_FALLBACKS=False, or True with no fallback models
    WHEN a request is sent
    THEN neither the fallbacks field nor the fallback beta header is sent
    """
    wire = Wire(messages=[_ok()])

    _transport(wire, _settings(**overrides)).send(BASE)

    (sent,) = wire.sent
    assert "fallbacks" not in _body(sent)
    assert "server-side-fallback" not in sent.headers.get("anthropic-beta", "")


def test_an_uncached_request_without_system_or_tools_sends_only_the_core() -> None:
    """
    GIVEN cache=False, an empty system prompt, no tools and no output_config
    WHEN it is sent
    THEN the body holds no cache_control, system, tools or output_config
    """
    wire = Wire(messages=[_ok()])
    request = dataclasses.replace(BASE, system="", cache=False)

    _transport(wire, _settings(ENGINE_FALLBACKS=False)).send(request)

    assert set(_body(wire.sent[0])) == {"model", "max_tokens", "messages"}


def test_an_uncached_system_prompt_has_no_breakpoint() -> None:
    """
    GIVEN cache=False with a system prompt
    WHEN it is sent
    THEN the system block carries no cache_control
    """
    wire = Wire(messages=[_ok()])

    _transport(wire).send(dataclasses.replace(BASE, cache=False))

    body = _body(wire.sent[0])
    assert body["system"] == [{"type": "text", "text": SYSTEM}]
    assert "cache_control" not in body


def test_echoed_sdk_blocks_are_counted_bounded_and_sent_as_their_json() -> None:
    """
    GIVEN a first answer that asks for a tool, whose SDK content blocks the
          editor appends verbatim to the next request with a tool result
    WHEN the follow-up is counted (one count fails, so the byte bound is
         used) and sent through the real client
    THEN the count and message bodies carry the blocks as their JSON, and
         the byte bound prices them
    """
    tool_use = {
        "type": "tool_use",
        "id": "toolu_1",
        "name": "str_replace_based_edit_tool",
        "input": {"command": "view", "path": "/repo/a.py"},
    }
    wire = Wire(
        messages=[_ok(stop_reason="tool_use", content=[tool_use]), _ok()],
        counts=[_count(10), _count(10), _count(20), _error(500)],
    )
    transport = _transport(wire)
    request = dataclasses.replace(BASE, tools=(TOOL,))
    first = call(transport, request, Budget(5.0), sleep=_no_sleep)
    echoed: BetaMessageParam = {"role": "assistant", "content": first.message.content}
    answer: BetaMessageParam = {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "1"}],
    }
    follow_up = dataclasses.replace(request, messages=(USER, echoed, answer))

    second = call(transport, follow_up, Budget(5.0), sleep=_no_sleep)

    for body in (_body(wire.counted[2]), _body(wire.sent[1])):
        assert body["messages"] == [
            USER,
            {"role": "assistant", "content": [tool_use]},
            answer,
        ]
    assert second.estimate_usd == preflight_estimate(
        _byte_bound(follow_up), BASE.max_tokens, transport.chain, transport.prices
    )
    assert _byte_bound(follow_up) > _byte_bound(request)


# ---------------------------------------------------------------------------
# AnthropicTransport: error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "kind", "expected"),
    [
        (400, "invalid_request_error", LLMRequestError),
        (401, "authentication_error", LLMConfigError),
        (403, "permission_error", LLMConfigError),
        (404, "not_found_error", LLMRequestError),
        (413, "request_too_large", LLMRequestError),
        (429, "rate_limit_error", LLMHTTPUnavailableError),
        (500, "api_error", LLMHTTPUnavailableError),
        (502, "api_error", LLMHTTPUnavailableError),
        (503, "api_error", LLMHTTPUnavailableError),
        (504, "timeout_error", LLMHTTPUnavailableError),
        (529, "overloaded_error", LLMHTTPUnavailableError),
        (402, "billing_error", LLMConfigError),
        (409, "api_error", LLMRequestError),
        (422, "api_error", LLMRequestError),
        (501, "api_error", LLMRequestError),
    ],
)
def test_http_errors_map_to_engine_errors(
    status: int, kind: str, expected: type[Exception]
) -> None:
    """
    GIVEN the API answers with an HTTP error
    WHEN the transport sends
    THEN 401/402/403 are config errors (the account, not the request, is at
         fault, so the run stops), the transient statuses are LLMUnavailable
         (with the status), and every other status is a request error
    """
    wire = Wire(messages=[_error(status, kind)])

    with pytest.raises(expected) as caught:
        _transport(wire).send(BASE)

    assert type(caught.value) is expected
    text = str(caught.value)
    assert str(status) in text
    assert kind in text
    assert "req_abc123" in text
    assert "SECRET-DETAIL" not in text
    if isinstance(caught.value, LLMHTTPUnavailableError):
        assert caught.value.status_code == status
        assert isinstance(caught.value, LLMUnavailable)


def test_the_status_sets_match_the_retry_policy() -> None:
    """
    GIVEN the published status sets
    THEN they are decision 9's lists, plus 402 billing as a config error
    """
    assert RETRYABLE_STATUSES == frozenset({429, 500, 502, 503, 504, 529})
    assert CONFIG_STATUSES == frozenset({401, 402, 403})


def test_529_is_not_an_internal_server_error_in_the_sdk_but_is_retryable() -> None:
    """
    GIVEN a 529 answer
    WHEN the bare SDK client and the transport each send
    THEN the SDK raises OverloadedError, which is not an InternalServerError,
         and the transport still maps it to a retryable LLMUnavailable
    """
    wire = Wire(messages=[_error(529, "overloaded_error")] * 2)
    client = anthropic.Anthropic(
        api_key=KEY,
        max_retries=0,
        http_client=DefaultHttpxClient(transport=httpx2.MockTransport(wire)),
    )

    with pytest.raises(anthropic.OverloadedError) as raw:
        client.beta.messages.create(model=ENGINE, max_tokens=10, messages=[USER])
    with pytest.raises(LLMHTTPUnavailableError) as mapped:
        _transport(wire).send(BASE)

    assert not isinstance(raw.value, anthropic.InternalServerError)
    assert mapped.value.status_code == 529


def test_an_unusual_error_type_or_request_id_is_not_echoed() -> None:
    """
    GIVEN an error body whose type and request id are not plain tokens
    WHEN it is mapped
    THEN neither is copied into the message
    """
    body = {"type": "error", "error": {"type": "<b>x y</b>", "message": "m"}}
    response = httpx2.Response(400, json=body, headers={"request-id": "id with space"})

    with pytest.raises(LLMRequestError) as caught:
        _transport(Wire(messages=[response])).send(BASE)

    assert "<b>" not in str(caught.value)
    assert "id with space" not in str(caught.value)
    assert "HTTP 400" in str(caught.value)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("5", 5.0),
        (" 0.5 ", 0.5),
        ("120", 120.0),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        ("-3", None),
        ("nan", None),
        ("inf", None),
        (None, None),
    ],
)
def test_a_numeric_retry_after_header_is_read(
    header: str | None, expected: float | None
) -> None:
    """
    GIVEN a 429 with a retry-after header (or none)
    WHEN it is mapped
    THEN only a finite, non-negative number of seconds is kept
    """
    headers = {"retry-after": header} if header is not None else {}
    wire = Wire(messages=[_error(429, "rate_limit_error", headers)])

    with pytest.raises(LLMHTTPUnavailableError) as caught:
        _transport(wire).send(BASE)

    assert caught.value.retry_after == expected


def test_a_timeout_is_a_lost_attempt_and_is_caught_before_connection_errors() -> None:
    """
    GIVEN a read timeout, then a refused connection
    WHEN each is sent
    THEN both are LLMNoResponseError; only the first says it timed out
         (APITimeoutError subclasses APIConnectionError, so order matters),
         and neither carries the SDK exception
    """
    wire = Wire(messages=[_timeout, _disconnect])
    transport = _transport(wire)

    with pytest.raises(LLMNoResponseError) as timed_out:
        transport.send(BASE)
    with pytest.raises(LLMNoResponseError) as refused:
        transport.send(BASE)

    assert timed_out.value.timed_out is True
    assert "in time" in str(timed_out.value)
    assert refused.value.timed_out is False
    assert "connection lost" in str(refused.value)
    assert isinstance(refused.value, LLMUnavailable)
    for caught in (timed_out.value, refused.value):
        assert _exception_chain(caught) == [caught]


def test_a_redirect_is_refused_and_never_followed() -> None:
    """
    GIVEN the messages endpoint answers 307 to another host
    WHEN the transport sends
    THEN LLMRequestError is raised after exactly one request, and no request
         (with the key or the prompt) leaves api.anthropic.com
    """
    moved = httpx2.Response(
        307, headers={"location": "https://evil.example/v1/messages"}
    )
    wire = Wire(messages=[moved, _ok()])

    with pytest.raises(LLMRequestError, match="HTTP 307") as caught:
        _transport(wire).send(BASE)

    assert type(caught.value) is LLMRequestError
    assert [r.url.host for r in wire.requests] == ["api.anthropic.com"]


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(
            200, content=b"not json", headers={"content-type": "application/json"}
        ),
        httpx2.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        httpx2.Response(200, json={"id": "m", "type": "message"}),
    ],
    ids=["bad-json", "html", "missing-fields"],
)
def test_a_2xx_body_that_is_not_a_message_is_unreadable(
    response: httpx2.Response,
) -> None:
    """
    GIVEN a 2xx answer whose body is not a message
    WHEN it is sent
    THEN LLMUnreadableResponseError (a request error) is raised
    """
    with pytest.raises(LLMUnreadableResponseError) as caught:
        _transport(Wire(messages=[response])).send(BASE)

    assert isinstance(caught.value, LLMRequestError)


# ---------------------------------------------------------------------------
# AnthropicTransport: exact input tokens
# ---------------------------------------------------------------------------


def test_count_asks_once_per_distinct_model_and_returns_the_largest() -> None:
    """
    GIVEN a chain that repeats a model, and two different counts
    WHEN the input tokens are counted
    THEN each distinct model is counted once, with the request's prompt and
         no max_tokens, fallbacks or fallback beta, and the larger count wins,
         plus the margin
    """
    wire = Wire(counts=[_count(40), _count(55)])
    cfg = _settings(ENGINE_FALLBACK_MODELS=(FALLBACK, FALLBACK))
    request = dataclasses.replace(BASE, tools=(TOOL,), output_config=EFFORT)

    tokens = _transport(wire, cfg).count_input_tokens(request)

    assert tokens == _padded(55) == 55 + COUNT_MARGIN_MIN_TOKENS
    assert [_body(r)["model"] for r in wire.counted] == [ENGINE, FALLBACK]
    assert not wire.sent
    for counted in wire.counted:
        body = _body(counted)
        assert set(body) == {
            "model",
            "system",
            "messages",
            "tools",
            "output_config",
            "cache_control",
        }
        assert "server-side-fallback" not in counted.headers.get("anthropic-beta", "")
        assert counted.extensions["timeout"]["read"] == COUNT_TIMEOUT_S
        assert counted.extensions["timeout"]["connect"] == CONNECT_TIMEOUT_S


def test_count_without_optional_parts_sends_only_model_and_messages() -> None:
    """
    GIVEN an uncached request with no system, tools or output_config
    WHEN it is counted
    THEN the count body holds only the model and messages
    """
    wire = Wire(counts=[_count(7)])
    request = dataclasses.replace(BASE, system="", cache=False)

    tokens = _transport(wire, _settings(ENGINE_FALLBACKS=False)).count_input_tokens(
        request
    )

    assert tokens == _padded(7)
    assert set(_body(wire.counted[0])) == {"model", "messages"}


def test_count_timeout_never_exceeds_the_request_timeout() -> None:
    """
    GIVEN LLM_TIMEOUT_S below COUNT_TIMEOUT_S
    WHEN a request is counted
    THEN the count uses the smaller timeout
    """
    wire = Wire(counts=[_count(7)])

    _transport(
        wire, _settings(LLM_TIMEOUT_S=5.0, ENGINE_FALLBACKS=False)
    ).count_input_tokens(BASE)

    assert wire.counted[0].extensions["timeout"]["read"] == 5.0
    assert wire.counted[0].extensions["timeout"]["connect"] == 5.0


def test_count_adds_the_request_allowance() -> None:
    """
    GIVEN a request with a prompt allowance for input the count may not show
    WHEN it is counted
    THEN the allowance is added to the largest count and its margin
    """
    wire = Wire(counts=[_count(40), _count(30)])
    request = dataclasses.replace(BASE, prompt_allowance_tokens=2000)

    assert _transport(wire).count_input_tokens(request) == _padded(40) + 2000


@pytest.mark.parametrize(
    ("counted", "expected"),
    [(0, 16), (799, 815), (800, 816), (801, 818), (100_000, 102_000)],
)
def test_the_exact_count_carries_a_margin(counted: int, expected: int) -> None:
    """
    GIVEN a count_tokens answer, which the docs call an estimate
    WHEN the request is counted
    THEN the count grows by 2 % (rounded up), and by at least 16 tokens
    """
    wire = Wire(counts=[_count(counted)])

    tokens = _transport(wire, _settings(ENGINE_FALLBACKS=False)).count_input_tokens(
        BASE
    )

    assert tokens == expected == _padded(counted)


def _byte_bound(request: LLMRequest) -> int:
    """The documented fallback: the cost module's byte bound of what is sent."""
    system: list[Mapping[str, object]] = []
    if request.system:
        block: dict[str, object] = {"type": "text", "text": request.system}
        if request.cache:
            block["cache_control"] = {"type": "ephemeral"}
        system.append(block)
    bound = prompt_token_bound(system, request.tools, request.messages)
    if request.output_config is not None:
        bound += prompt_token_bound(None, (), (request.output_config,))
    return bound + request.prompt_allowance_tokens


@pytest.mark.parametrize(
    "second",
    [
        _error(500),
        _error(429, "rate_limit_error"),
        _disconnect,
        _timeout,
        _count(-1),
        _count("many"),
        _count(True),
        _count(None),
        httpx2.Response(
            200, content=b"{", headers={"content-type": "application/json"}
        ),
    ],
    ids=[
        "500",
        "429",
        "connection",
        "timeout",
        "negative",
        "text",
        "bool",
        "null",
        "bad-json",
    ],
)
def test_any_count_failure_falls_back_to_the_byte_bound_without_retrying(
    second: Reply,
) -> None:
    """
    GIVEN the first model's count succeeds and the second fails in any way
    WHEN the request is counted
    THEN the byte bound (with the allowance) is returned, and the failed
         count is not retried
    """
    wire = Wire(counts=[_count(40), second])
    request = dataclasses.replace(
        BASE, tools=(TOOL,), output_config=EFFORT, prompt_allowance_tokens=100
    )

    tokens = _transport(wire).count_input_tokens(request)

    assert tokens == _byte_bound(request)
    assert len(wire.counted) == 2


# ---------------------------------------------------------------------------
# ScriptedTransport
# ---------------------------------------------------------------------------


def test_scripted_transport_replays_in_order_and_records_requests() -> None:
    """
    GIVEN two scripted replies, one an SDK message and one a fixture mapping
    WHEN three requests are sent
    THEN the replies come back in order, every request is recorded, and the
         third request fails as a request error (the script ran out)
    """
    first = _message(model=ENGINE)
    transport = ScriptedTransport([first, _message_json(model=FALLBACK)])
    second_request = dataclasses.replace(BASE, max_tokens=10)

    assert transport.send(BASE) is first
    assert transport.send(second_request).model == FALLBACK
    assert transport.remaining == 0
    with pytest.raises(LLMRequestError, match="no reply left"):
        transport.send(BASE)

    assert transport.requests == [BASE, second_request, BASE]


def test_scripted_transport_raises_engine_errors_and_maps_sdk_errors() -> None:
    """
    GIVEN scripted engine errors and real SDK exceptions
    WHEN requests are sent
    THEN engine errors are raised as they are and SDK errors are mapped the
         way AnthropicTransport maps them
    """
    unavailable = LLMUnavailable("scripted outage")
    transport = ScriptedTransport(
        [
            unavailable,
            _sdk_status(529, retry_after="5"),
            anthropic.APITimeoutError(request=REQ),
            anthropic.APIConnectionError(request=REQ),
            _sdk_status(401),
            anthropic.APIResponseValidationError(
                response=httpx2.Response(200, request=REQ), body=None
            ),
        ]
    )

    with pytest.raises(LLMUnavailable) as first:
        transport.send(BASE)
    with pytest.raises(LLMHTTPUnavailableError) as overloaded:
        transport.send(BASE)
    with pytest.raises(LLMNoResponseError) as timed_out:
        transport.send(BASE)
    with pytest.raises(LLMNoResponseError) as refused:
        transport.send(BASE)
    with pytest.raises(LLMConfigError):
        transport.send(BASE)
    with pytest.raises(LLMUnreadableResponseError, match="APIResponseValidationError"):
        transport.send(BASE)

    assert first.value is unavailable
    assert (overloaded.value.status_code, overloaded.value.retry_after) == (529, 5.0)
    assert timed_out.value.timed_out is True
    assert refused.value.timed_out is False


def test_scripted_transport_counts_the_byte_bound_and_uses_the_settings_chain() -> None:
    """
    GIVEN a scripted transport built from settings
    WHEN it is asked for the chain, the prices and a count
    THEN they come from cost.chain, the settings table and the byte bound
    """
    cfg = _settings(ENGINE_FALLBACK_MODELS=("claude-opus-5",))
    transport: LLMTransport = ScriptedTransport([], cfg=cfg)
    request = dataclasses.replace(BASE, tools=(TOOL,), output_config=EFFORT)

    assert transport.chain == (ENGINE, "claude-opus-5")
    assert dict(transport.prices) == cfg.MODEL_PRICING
    assert transport.count_input_tokens(request) == _byte_bound(request)
    assert ScriptedTransport([]).chain == chain(settings)


def test_scripted_transport_refuses_an_invalid_fixture_at_once() -> None:
    """
    GIVEN a fixture mapping that is not a message
    WHEN the scripted transport is built
    THEN it fails then, not when the reply is due
    """
    with pytest.raises(ValueError, match="validation error"):
        ScriptedTransport([{"type": "message"}])


# ---------------------------------------------------------------------------
# call(): success
# ---------------------------------------------------------------------------


def _estimate(transport: LLMTransport, request: LLMRequest = BASE) -> float:
    return preflight_estimate(
        transport.count_input_tokens(request),
        request.max_tokens,
        transport.chain,
        transport.prices,
    )


USAGE = {
    "input_tokens": 1200,
    "output_tokens": 300,
    "cache_creation_input_tokens": 2000,
    "cache_read_input_tokens": 0,
}


def test_a_successful_call_is_priced_recorded_and_described() -> None:
    """
    GIVEN one scripted success
    WHEN call() runs
    THEN the result carries the message, its priced cost and tokens (also
         recorded in the budget), the estimate, the serving model, one
         attempt, no fallback and no unpriced model
    """
    message = _message(usage=USAGE)
    transport = ScriptedTransport([message], cfg=_settings())
    budget = Budget(5.0, spent_usd=0.25, tokens=10)
    usd, tokens = response_cost(message.usage, transport.prices, model=ENGINE)

    result = call(transport, BASE, budget, sleep=_no_sleep)

    assert isinstance(result, LLMResult)
    assert result.message is message
    assert result.cost_usd == usd
    assert result.tokens == tokens
    assert result.estimate_usd == _estimate(transport)
    assert result.served_model == ENGINE
    assert result.fell_back is False
    assert result.unpriced_models == ()
    assert result.attempts == 1
    assert budget.spent_usd == pytest.approx(0.25 + usd)
    assert budget.tokens == 10 + tokens
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.attempts = 2  # type: ignore[misc]


def test_a_fallback_served_answer_is_reported() -> None:
    """
    GIVEN a response whose iterations end in a fallback_message entry
    WHEN call() runs
    THEN fell_back is true, served_model is the fallback, and both
         iterations are priced at their own model
    """
    iterations = [
        {
            "type": "message",
            "model": ENGINE,
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        {
            "type": "fallback_message",
            "model": FALLBACK,
            "input_tokens": 100,
            "output_tokens": 80,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    ]
    usage = {"input_tokens": 100, "output_tokens": 80, "iterations": iterations}
    message = _message(model=FALLBACK, usage=usage)
    transport = ScriptedTransport([message], cfg=_settings())

    result = call(transport, BASE, Budget(5.0), sleep=_no_sleep)

    assert result.fell_back is True
    assert result.served_model == FALLBACK
    assert result.cost_usd == pytest.approx(
        (100 * 4 + 20 * 20 + 100 * 5 + 80 * 25) / 1e6
    )
    assert result.unpriced_models == ()


def test_an_unpriced_model_is_named_and_priced_at_the_worst_rate() -> None:
    """
    GIVEN an iteration billed by a model missing from MODEL_PRICING, and an
          iteration that names no model
    WHEN call() runs
    THEN that model is listed once in unpriced_models; the unnamed one is
         priced at the response model, which is priced
    """
    iterations = [
        {
            "type": "message",
            "model": "claude-mystery-9",
            "input_tokens": 10,
            "output_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        {
            "type": "message",
            "input_tokens": 10,
            "output_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
        {
            "type": "message",
            "model": "claude-mystery-9",
            "input_tokens": 10,
            "output_tokens": 10,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        },
    ]
    usage = {"input_tokens": 10, "output_tokens": 10, "iterations": iterations}
    transport = ScriptedTransport([_message(usage=usage)], cfg=_settings())

    result = call(transport, BASE, Budget(5.0), sleep=_no_sleep)

    assert result.unpriced_models == ("claude-mystery-9",)


def test_an_unpriced_serving_model_without_iterations_is_named() -> None:
    """
    GIVEN a response from an unpriced model with no iterations
    WHEN call() runs
    THEN that model is listed
    """
    transport = ScriptedTransport([_message(model="claude-mystery-9")], cfg=_settings())

    result = call(transport, BASE, Budget(5.0), sleep=_no_sleep)

    assert result.unpriced_models == ("claude-mystery-9",)
    assert result.served_model == "claude-mystery-9"


def test_a_refusal_is_returned_not_raised() -> None:
    """
    GIVEN a response with stop_reason refusal
    WHEN call() runs
    THEN it is returned for the editor or understand node to decide
    """
    transport = ScriptedTransport([_message(stop_reason="refusal")], cfg=_settings())

    result = call(transport, BASE, Budget(5.0), sleep=_no_sleep)

    assert result.message.stop_reason == "refusal"


def test_the_estimate_uses_the_transport_count() -> None:
    """
    GIVEN the real client, whose count endpoint reports 42 tokens per model
    WHEN call() runs
    THEN the estimate is preflight_estimate(42 + margin, ...); the count is free
    """
    wire = Wire(messages=[_ok(usage=USAGE)], counts=[_count(42), _count(42)])
    transport = _transport(wire)
    budget = Budget(5.0)

    result = call(transport, BASE, budget, sleep=_no_sleep)

    assert result.estimate_usd == preflight_estimate(
        _padded(42), BASE.max_tokens, transport.chain, transport.prices
    )
    assert budget.spent_usd == result.cost_usd
    assert len(wire.counted) == 2
    assert len(wire.sent) == 1


# ---------------------------------------------------------------------------
# call(): retries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        _sdk_status(429),
        _sdk_status(529),
        _sdk_status(500),
        _sdk_status(502),
        _sdk_status(503),
        _sdk_status(504),
        anthropic.APITimeoutError(request=REQ),
        anthropic.APIConnectionError(request=REQ),
    ],
    ids=["429", "529", "500", "502", "503", "504", "timeout", "connection"],
)
def test_transient_failures_are_retried_then_raise_unavailable(
    failure: anthropic.APIError,
) -> None:
    """
    GIVEN a transient failure on every attempt
    WHEN call() runs with max_retries=2
    THEN three attempts are made, the sleeps are 1 s and 2 s, and
         LLMUnavailable is raised naming the attempts
    """
    transport = ScriptedTransport([failure] * 4, cfg=_settings())
    sleeps: list[float] = []

    with pytest.raises(LLMUnavailable, match="3 attempts") as caught:
        call(transport, BASE, Budget(5.0), sleep=sleeps.append, max_retries=2)

    assert len(transport.requests) == 3
    assert sleeps == [1.0, 2.0]
    assert isinstance(caught.value.__cause__, LLMUnavailable)


def test_a_transient_failure_then_success_returns_the_answer() -> None:
    """
    GIVEN a 529 then a success
    WHEN call() runs
    THEN the answer is returned after one sleep, with attempts=2
    """
    transport = ScriptedTransport([_sdk_status(529), _message()], cfg=_settings())
    sleeps: list[float] = []

    result = call(transport, BASE, Budget(5.0), sleep=sleeps.append)

    assert result.attempts == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize("status", [400, 404, 413])
def test_request_errors_are_not_retried(status: int) -> None:
    """
    GIVEN a 400, 404 or 413
    WHEN call() runs
    THEN LLMRequestError is raised after one attempt, and nothing is charged
    """
    transport = ScriptedTransport([_sdk_status(status), _message()], cfg=_settings())
    budget = Budget(5.0)

    with pytest.raises(LLMRequestError):
        call(transport, BASE, budget, sleep=_no_sleep)

    assert len(transport.requests) == 1
    assert budget.spent_usd == 0.0


@pytest.mark.parametrize("status", [401, 402, 403])
def test_auth_errors_are_config_errors_and_not_retried(status: int) -> None:
    """
    GIVEN a 401, a 402 (billing) or a 403
    WHEN call() runs
    THEN LLMConfigError (an EngineError) is raised after one attempt
    """
    transport = ScriptedTransport([_sdk_status(status), _message()], cfg=_settings())

    with pytest.raises(LLMConfigError):
        call(transport, BASE, Budget(5.0), sleep=_no_sleep)

    assert len(transport.requests) == 1


def test_retry_after_is_a_floor_on_the_backoff() -> None:
    """
    GIVEN a 429 with retry-after 5, a 429 with retry-after 0.5, then success
    WHEN call() runs
    THEN the sleeps are 5 s (the floor) and 2 s (the backoff wins)
    """
    transport = ScriptedTransport(
        [_sdk_status(429, "5"), _sdk_status(429, "0.5"), _message()], cfg=_settings()
    )
    sleeps: list[float] = []

    call(transport, BASE, Budget(5.0), sleep=sleeps.append)

    assert sleeps == [5.0, 2.0]


def test_a_retry_after_above_sixty_seconds_gives_up_at_once() -> None:
    """
    GIVEN a 429 asking to retry after 120 s, with retries left
    WHEN call() runs
    THEN LLMUnavailable is raised without sleeping or sending again
    """
    transport = ScriptedTransport(
        [_sdk_status(429, "120"), _message()], cfg=_settings()
    )

    with pytest.raises(LLMUnavailable, match="120"):
        call(transport, BASE, Budget(5.0), sleep=_no_sleep, max_retries=2)

    assert len(transport.requests) == 1
    assert MAX_RETRY_AFTER_S == 60.0


def test_a_retry_after_of_exactly_sixty_seconds_is_honoured() -> None:
    """
    GIVEN a 529 asking to retry after exactly 60 s
    WHEN call() runs
    THEN it sleeps 60 s and retries
    """
    transport = ScriptedTransport([_sdk_status(529, "60"), _message()], cfg=_settings())
    sleeps: list[float] = []

    call(transport, BASE, Budget(5.0), sleep=sleeps.append)

    assert sleeps == [60.0]


def test_the_backoff_doubles_up_to_thirty_seconds() -> None:
    """
    GIVEN seven 429s and max_retries=7
    WHEN call() runs
    THEN the sleeps double from 1 s and stop growing at 30 s
    """
    transport = ScriptedTransport([_sdk_status(429)] * 8, cfg=_settings())
    sleeps: list[float] = []

    with pytest.raises(LLMUnavailable):
        call(transport, BASE, Budget(50.0), sleep=sleeps.append, max_retries=7)

    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
    assert MAX_BACKOFF_S == 30.0


def test_a_long_retry_budget_never_overflows_the_backoff() -> None:
    """
    GIVEN 1,100 429s and max_retries=1,100
    WHEN call() runs
    THEN every sleep after the fifth is 30 s (no float overflow)
    """
    transport = ScriptedTransport([_sdk_status(429)] * 1101, cfg=_settings())
    sleeps: list[float] = []

    with pytest.raises(LLMUnavailable):
        call(transport, BASE, Budget(50.0), sleep=sleeps.append, max_retries=1100)

    assert len(sleeps) == 1100
    assert set(sleeps[5:]) == {30.0}


def test_max_retries_zero_makes_one_attempt() -> None:
    """
    GIVEN max_retries=0 and a 503
    WHEN call() runs
    THEN one attempt is made and LLMUnavailable is raised without sleeping
    """
    transport = ScriptedTransport([_sdk_status(503), _message()], cfg=_settings())

    with pytest.raises(LLMUnavailable, match="1 attempt"):
        call(transport, BASE, Budget(5.0), sleep=_no_sleep, max_retries=0)

    assert len(transport.requests) == 1


@pytest.mark.parametrize("max_retries", [-1, True])
def test_a_bad_max_retries_is_refused(max_retries: int) -> None:
    """
    GIVEN a negative or boolean max_retries
    WHEN call() runs
    THEN ValueError is raised before anything is sent
    """
    transport = ScriptedTransport([_message()], cfg=_settings())

    with pytest.raises(ValueError, match="max_retries"):
        call(transport, BASE, Budget(5.0), sleep=_no_sleep, max_retries=max_retries)

    assert transport.requests == []


def test_the_default_retry_count_is_the_setting() -> None:
    """
    GIVEN call()'s signature
    THEN max_retries defaults to settings.LLM_MAX_RETRIES
    """
    default = inspect.signature(call).parameters["max_retries"].default

    assert default == settings.LLM_MAX_RETRIES


# ---------------------------------------------------------------------------
# call(): charging and the budget
# ---------------------------------------------------------------------------


def test_lost_attempts_are_charged_the_estimate_and_http_errors_nothing() -> None:
    """
    GIVEN a timeout, a 429, a connection error, then a success
    WHEN call() runs
    THEN the two lost attempts are each charged the full estimate, the 429
         nothing, and the result's cost is everything this call charged
    """
    message = _message(usage=USAGE)
    transport = ScriptedTransport(
        [
            anthropic.APITimeoutError(request=REQ),
            _sdk_status(429),
            anthropic.APIConnectionError(request=REQ),
            message,
        ],
        cfg=_settings(),
    )
    budget = Budget(10.0)
    estimate = _estimate(transport)
    usd, tokens = response_cost(message.usage, transport.prices, model=ENGINE)

    result = call(transport, BASE, budget, sleep=lambda _: None, max_retries=3)

    assert budget.spent_usd == pytest.approx(2 * estimate + usd)
    assert result.cost_usd == pytest.approx(2 * estimate + usd)
    assert result.tokens == tokens
    assert budget.tokens == tokens
    assert result.attempts == 4


def test_an_unclassified_unavailable_error_is_charged_the_estimate() -> None:
    """
    GIVEN a plain LLMUnavailable (no status, so it may have been billed)
    WHEN call() runs with no retries
    THEN the attempt is charged the full estimate
    """
    transport = ScriptedTransport([LLMUnavailable("down")], cfg=_settings())
    budget = Budget(5.0)

    with pytest.raises(LLMUnavailable):
        call(transport, BASE, budget, sleep=_no_sleep, max_retries=0)

    assert budget.spent_usd == _estimate(transport)


def test_an_unreadable_2xx_answer_is_charged_the_estimate_and_not_retried() -> None:
    """
    GIVEN a 2xx answer the client could not read
    WHEN call() runs through the real client
    THEN LLMUnreadableResponseError is raised after one attempt, charged the
         full estimate (the server may have billed it)
    """
    bad = httpx2.Response(
        200, content=b"{", headers={"content-type": "application/json"}
    )
    wire = Wire(messages=[bad], counts=[_count(42), _count(42)])
    transport = _transport(wire)
    budget = Budget(5.0)

    with pytest.raises(LLMUnreadableResponseError):
        call(transport, BASE, budget, sleep=_no_sleep)

    assert len(wire.sent) == 1
    assert budget.spent_usd == preflight_estimate(
        _padded(42), BASE.max_tokens, transport.chain, transport.prices
    )


def test_a_usage_that_cannot_be_priced_is_charged_the_estimate() -> None:
    """
    GIVEN a message whose usage has a negative token count
    WHEN call() runs
    THEN LLMUnreadableResponseError is raised and the estimate is charged
    """
    message = _message()
    broken = message.model_copy(
        update={"usage": message.usage.model_copy(update={"output_tokens": -5})}
    )
    transport = ScriptedTransport([broken], cfg=_settings())
    budget = Budget(5.0)

    with pytest.raises(LLMUnreadableResponseError, match="priced"):
        call(transport, BASE, budget, sleep=_no_sleep)

    assert budget.spent_usd == _estimate(transport)


@pytest.mark.parametrize(
    ("cap_tokens", "sent"), [(1005, False), (1020, True), (1030, True)]
)
def test_a_bill_slightly_above_the_count_never_passes_the_cap(
    cap_tokens: int, sent: bool
) -> None:
    """
    GIVEN a chain of one, a count of 1,000 tokens, and a bill of 1,010 prompt
          tokens (all cache writes, the dearest input rate) plus max_tokens
          of output, under a cap that affords 1,005 to 1,030 such tokens
    WHEN call() runs
    THEN the spend never passes the cap: the margin makes the check refuse
         before anything is sent, or the bill fits under the cap
    """
    usage = {
        "input_tokens": 0,
        "output_tokens": BASE.max_tokens,
        "cache_creation_input_tokens": 1010,
        "cache_read_input_tokens": 0,
    }
    wire = Wire(messages=[_ok(usage=usage)], counts=[_count(1000)])
    transport = _transport(wire, _settings(ENGINE_FALLBACKS=False))
    cap = preflight_estimate(
        cap_tokens, BASE.max_tokens, transport.chain, transport.prices
    )
    budget = Budget(cap)

    if sent:
        result = call(transport, BASE, budget, sleep=_no_sleep)
        assert result.cost_usd <= cap
    else:
        with pytest.raises(BudgetExceeded, match="estimate"):
            call(transport, BASE, budget, sleep=_no_sleep)

    assert len(wire.sent) == int(sent)
    assert budget.spent_usd <= cap


def test_the_budget_is_checked_before_the_first_attempt() -> None:
    """
    GIVEN a budget smaller than one estimate
    WHEN call() runs
    THEN BudgetExceeded is raised and nothing is sent
    """
    transport = ScriptedTransport([_message()], cfg=_settings())

    with pytest.raises(BudgetExceeded):
        call(transport, BASE, Budget(_estimate(transport) / 2), sleep=_no_sleep)

    assert transport.requests == []


def test_the_cap_halts_the_retry_loop_before_sleeping() -> None:
    """
    GIVEN a budget that affords one estimate, and a first attempt that times out
    WHEN call() runs with retries left
    THEN the lost attempt is charged, the next check raises BudgetExceeded,
         nothing more is sent and no sleep happens
    """
    transport = ScriptedTransport(
        [anthropic.APITimeoutError(request=REQ), _message()], cfg=_settings()
    )
    estimate = _estimate(transport)
    budget = Budget(estimate * 1.5)

    with pytest.raises(BudgetExceeded):
        call(transport, BASE, budget, sleep=_no_sleep, max_retries=2)

    assert len(transport.requests) == 1
    assert budget.spent_usd == estimate


def test_the_budget_is_checked_before_every_retry() -> None:
    """
    GIVEN a budget whose check is counted, and two 429s then a success
    WHEN call() runs
    THEN the budget is checked once per attempt, each time with the estimate
    """
    checks: list[float] = []

    class CountingBudget(Budget):
        def check(self, estimate_usd: float) -> None:
            checks.append(estimate_usd)
            super().check(estimate_usd)

    transport = ScriptedTransport(
        [_sdk_status(429), _sdk_status(429), _message()], cfg=_settings()
    )

    call(transport, BASE, CountingBudget(5.0), sleep=lambda _: None)

    assert checks == [_estimate(transport)] * 3


def test_a_response_dearer_than_the_cap_is_recorded_then_raises() -> None:
    """
    GIVEN a response that costs more than the money left
    WHEN call() runs
    THEN its cost is recorded and BudgetExceeded is raised
    """
    huge = {"input_tokens": 0, "output_tokens": 10_000_000}
    transport = ScriptedTransport([_message(usage=huge)], cfg=_settings())
    budget = Budget(_estimate(transport) * 1.01)

    with pytest.raises(BudgetExceeded):
        call(transport, BASE, budget, sleep=_no_sleep)

    assert budget.spent_usd == pytest.approx(10_000_000 * 20 / 1e6)


# ---------------------------------------------------------------------------
# The key never leaks
# ---------------------------------------------------------------------------


def test_the_api_key_never_appears_in_errors_logs_reprs_or_bodies(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN a real key, debug logging on every logger and a run through a
          success, a 401, a 429 and a timeout
    WHEN every message, repr, traceback, log line and request body is read
    THEN the key appears only in the x-api-key header the SDK sends, and no
         raised error carries the SDK exception, the API's error message or
         the prompt, in its chain or its formatted traceback
    """
    caplog.set_level(logging.DEBUG)
    for name in ("anthropic", "httpx2", "httpcore"):
        caplog.set_level(logging.DEBUG, logger=name)
    wire = Wire(
        messages=[_ok(), _error(401, "authentication_error"), _error(429), _timeout],
        counts=[_count(1)] * 8,
    )
    transport = _transport(wire)
    seen: list[str] = [repr(transport), str(transport), repr(BASE)]

    result = call(transport, BASE, Budget(5.0), sleep=_no_sleep)
    seen += [repr(result)]
    errors: list[str] = []
    for _ in range(3):
        with pytest.raises(Exception) as caught:  # noqa: B017 - any of the mapped ones
            call(transport, BASE, Budget(5.0), sleep=_no_sleep, max_retries=0)
        errors += [
            str(caught.value),
            repr(caught.value),
            "".join(traceback.format_exception(caught.value)),
        ]
        assert not any(
            isinstance(e, anthropic.APIError | httpx2.HTTPError)
            for e in _exception_chain(caught.value)
        )
    assert all(
        text not in error
        for text in ("SECRET-DETAIL", SYSTEM, "unique_in_order")
        for error in errors
    )
    seen += errors
    seen += [r.content.decode() for r in wire.requests]
    out, err = capsys.readouterr()
    seen += [caplog.text, out, err]

    assert caplog.records, "debug logging must have been captured"
    assert all(KEY not in text for text in seen)
    assert all(r.headers["x-api-key"] == KEY for r in wire.requests)
