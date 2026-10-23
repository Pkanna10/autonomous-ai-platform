"""Offline tests of the raw-SDK experiment client (``harness.py``).

No network and no key: every client talks to ``FakeApi`` through the httpx
wire of a ``LiveRun`` (``LiveRun(wire=MockTransport)``), so the production
wiring (the SDK client, the host pin, the capture, the suite's records and
budget) runs and only the wire is swapped. ``FakeApi`` answers
``count_tokens`` with the documented 400 for server tools and file or URL
sources, so the dry runs take the real path. The last tests run the
experiments' live modules in a pytest subprocess, with the API pointed at a
closed local port, and each E1 probe's own body against the fake API.
"""

from __future__ import annotations

import ast
import base64
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import cast

import httpx2
import pytest

from autonomous_ai_agents.clients.cost import count_margin
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import BudgetExceeded

from ..conftest import KEY_ENV, LiveRun, StartLive, check_answered, restore_host_key
from . import harness
from . import test_probes_live as probes
from .bounds import (
    SERVER_TOOL_DEFINITION_TOKENS,
    ExperimentRefusedError,
    ToolAllowance,
    count_extras,
    is_server_tool,
    minimal_pdf,
    server_allowance,
    structural_tokens,
    worst_case_usd,
)
from .harness import (
    MAX_WAIT_S,
    Answer,
    BatchItem,
    ExperimentAPIError,
    ExperimentClient,
    HostRefusedError,
)
from .recorder import ExperimentRecorder

KEY = "sk-ant-api03-EXPERIMENTS-0123456789abcdef"
OPUS, FALLBACK, HAIKU = "claude-opus-5-5", "claude-opus-4-8", "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
HERE = Path(__file__).resolve().parent
SERVICE_DIR = HERE.parents[2]
BASE = settings.ENGINE_API_BASE_URL.rstrip("/")
PRICES = settings.MODEL_PRICING
BATCH_ID = "msgbatch_01Experiment"
SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
Json = dict[str, object]


def _user(text: str = "Say ok.") -> Json:
    return {"role": "user", "content": text}


def _body(**extra: object) -> Json:
    body: Json = {"model": HAIKU, "max_tokens": 64, "messages": [_user()]}
    body.update(extra)
    return body


def _message(model: str = HAIKU, usage: Json | None = None) -> Json:
    return {
        "id": "msg_01Experiment",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": usage or {"input_tokens": 20, "output_tokens": 5},
    }


def _batch(status: str = "in_progress", results_url: str | None = None) -> Json:
    counts = dict.fromkeys(
        ("processing", "succeeded", "errored", "canceled", "expired"), 0
    )
    return {
        "id": BATCH_ID,
        "type": "message_batch",
        "processing_status": status,
        "request_counts": counts,
        "created_at": "2026-10-23T00:00:00Z",
        "expires_at": "2026-10-24T00:00:00Z",
        "ended_at": None,
        "results_url": results_url,
        "archived_at": None,
        "cancel_initiated_at": None,
    }


def _pdf_block() -> Json:
    data = base64.b64encode(minimal_pdf("hello")).decode()
    return {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
    }


def _counts_refused(body: Json) -> bool:
    """The documented ``count_tokens`` 400s: server tools, file or URL sources."""
    tools = body.get("tools")
    if isinstance(tools, list) and any(is_server_tool(t) for t in tools):
        return True
    return '"type": "file"' in json.dumps(body) or '"type": "url"' in json.dumps(body)


class FakeApi:
    """The endpoints the harness uses, on a mock httpx wire.

    It records every request with its headers (the key included, which the
    capture must not keep) and answers by path; each knob shapes one reply.
    """

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.count: object = 100
        self.count_status = 200
        self.reply: Json = _message()
        self.status = 200
        self.error_message = "dry run refusal"
        self.timeout = False
        self.batch_status = "ended"
        self.results_url = f"{BASE}/v1/messages/batches/{BATCH_ID}/results"
        self.sdk_results_url: str | None = None  # served from retrieve swap_from on
        self.swap_from = 0
        self.results: list[Json] = []
        self.model_status = 200
        self.delete_status = 200
        self.batch_create_status = 200
        self._retrieves = 0

    def paths(self, method: str | None = None) -> list[str]:
        return [
            r.url.path for r in self.requests if method is None or r.method == method
        ]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path.endswith("/count_tokens"):
            body = json.loads(request.read())
            if _counts_refused(body):
                return self._error(400, "count_tokens does not support this request")
            if self.count_status != 200:
                return self._error(self.count_status)
            return httpx2.Response(200, json={"input_tokens": self.count})
        if path == "/v1/messages":
            if self.timeout:
                raise httpx2.ReadTimeout("no answer", request=request)
            if self.status != 200:
                return self._error(self.status)
            return httpx2.Response(200, json=self.reply)
        if path == "/v1/messages/batches" and method == "POST":
            if self.batch_create_status != 200:
                return self._error(self.batch_create_status)
            return httpx2.Response(200, json=_batch())
        if path.endswith("/results"):
            lines = "\n".join(json.dumps(line) for line in self.results)
            return httpx2.Response(200, content=lines.encode())
        if path.endswith("/cancel"):
            return httpx2.Response(200, json=_batch("canceling"))
        if path.startswith("/v1/messages/batches/"):
            return self._retrieve()
        if path == "/v1/files":
            return httpx2.Response(200, json=_file_meta())
        if path.startswith("/v1/files/") and method == "DELETE":
            if self.delete_status != 200:
                return self._error(self.delete_status)
            return httpx2.Response(200, json={"id": "file_01", "type": "file_deleted"})
        if path.startswith("/v1/models/"):
            if self.model_status != 200:
                return self._error(self.model_status)
            return httpx2.Response(200, json=_model_info(path.rsplit("/", 1)[1]))
        return httpx2.Response(404, json={"type": "error", "error": {}})

    def _retrieve(self) -> httpx2.Response:
        self._retrieves += 1
        if self.batch_status != "ended":
            return httpx2.Response(200, json=_batch(self.batch_status))
        url = self.results_url
        if self.sdk_results_url is not None and self._retrieves >= self.swap_from:
            url = self.sdk_results_url  # the SDK retrieves again inside results()
        return httpx2.Response(200, json=_batch("ended", url))

    def _error(self, status: int, message: str | None = None) -> httpx2.Response:
        error = {
            "type": "invalid_request_error",
            "message": message or self.error_message,
        }
        return httpx2.Response(status, json={"type": "error", "error": error})


def _file_meta() -> Json:
    return {
        "id": "file_01",
        "type": "file",
        "filename": "probe.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 10,
        "created_at": "2026-10-23T00:00:00Z",
        "downloadable": False,
        "expires_at": None,
    }


def _model_info(model: str) -> Json:
    capabilities = {
        "citations": {"supported": True},
        "server_tools": {"web_search": {"supported": False}},
        "odd": "not an object",
        "deep": {"a": {"b": {"supported": True}}},
    }
    return {
        "id": model,
        "type": "model",
        "display_name": model,
        "created_at": "2026-01-01T00:00:00Z",
        "lifecycle": "active",
        "max_input_tokens": 1_000_000,
        "max_tokens": 128_000,
        "allowed_fallback_models": [FALLBACK] if model == OPUS else None,
        "capabilities": capabilities if model != SONNET else None,
    }


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def host_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """What the ``live`` fixture does: the host key over the placeholder."""
    restore_host_key(monkeypatch, KEY)
    return KEY


def _run(
    api: FakeApi | Callable[[httpx2.Request], httpx2.Response], cap: float = 1.0
) -> LiveRun:
    return LiveRun("dry", cap, wire=httpx2.MockTransport(api))


class Clock:
    """A fake monotonic clock that the fake sleep advances."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _sent(api: FakeApi) -> list[httpx2.Request]:
    return [r for r in api.requests if r.url.path == "/v1/messages"]


# ---------------------------------------------------------------------------
# The key, the host pin, retries and redirects: built like AnthropicTransport
# ---------------------------------------------------------------------------


def test_the_suite_placeholder_key_is_refused_before_anything_is_sent(
    api: FakeApi,
) -> None:
    """
    GIVEN the suite's autouse reset_environment put its placeholder in the
        environment (fresh Settings read it), or there is no key at all
    WHEN a client is built from those settings
    THEN it refuses at once: a placeholder would only buy a 401
    """
    assert os.environ[KEY_ENV] == "test-key-12345"
    with pytest.raises(ExperimentRefusedError, match="placeholder"):
        ExperimentClient(_run(api), Settings())
    with pytest.raises(ExperimentRefusedError, match="not set"):
        ExperimentClient(_run(api), Settings(ANTHROPIC_API_KEY=None))
    for wrapped in ("your-api-key-here", "sk-your-api-key-here-1", "xtest-key-12345x"):
        with pytest.raises(ExperimentRefusedError, match="placeholder"):
            ExperimentClient(_run(api), Settings(ANTHROPIC_API_KEY=wrapped))
    assert api.requests == []


def test_the_host_key_restored_by_the_live_fixture_is_what_is_sent(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))

    answer = client.messages(_body())

    assert answer.accepted
    assert [r.headers["x-api-key"] for r in _sent(api)] == [host_key]
    for exchange in client.run.capture.exchanges:
        assert host_key not in repr(exchange)
    assert host_key not in repr(client)


def test_requests_go_to_the_engine_base_url_never_the_sdk_variable(
    api: FakeApi, host_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://elsewhere.example")
    ExperimentClient(_run(api)).messages(_body())
    assert {r.url.host for r in api.requests} == {httpx2.URL(BASE).host}


@pytest.mark.parametrize(
    "url",
    ["https://elsewhere.example/v1/x", "http://HOST/v1/x", "https://HOST:8443/v1/x"],
    ids=["other-host", "plain-http", "other-port"],
)
def test_the_wire_is_pinned_to_the_engine_host(
    api: FakeApi, host_key: str, url: str
) -> None:
    """Review item 7: every request the SDK makes (a followed results_url
    included) must go to ENGINE_API_BASE_URL's host over https, or nowhere."""
    client = ExperimentClient(_run(api))
    target = url.replace("HOST", httpx2.URL(BASE).host)
    with pytest.raises(HostRefusedError):
        client.wire.handle_request(httpx2.Request("GET", target))
    assert api.requests == [] and client.run.capture.exchanges == []
    assert any("refused a request" in note for note in client.run.notes)
    client.wire.handle_request(httpx2.Request("GET", f"{BASE}/v1/models/{HAIKU}"))
    assert len(api.requests) == 1
    client.wire.close()  # closes the capture beneath it


def test_no_sdk_retries_and_no_redirects(api: FakeApi, host_key: str) -> None:
    client = ExperimentClient(_run(api))
    api.status = 529

    overloaded = client.messages(_body())

    assert (overloaded.status, overloaded.cost_usd) == (529, 0.0)
    assert len(_sent(api)) == 1

    def redirect(request: httpx2.Request) -> httpx2.Response:
        api.requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 10})
        return httpx2.Response(307, headers={"location": "https://elsewhere.example/"})

    moved = ExperimentClient(_run(redirect)).messages(_body())
    assert moved.status == 307 and not moved.accepted
    assert "elsewhere.example" not in {r.url.host for r in api.requests}


# ---------------------------------------------------------------------------
# The prompt bound: count plus margin plus what it cannot see, or structure
# ---------------------------------------------------------------------------


def test_an_answer_is_priced_into_the_run_ledger_and_its_budget(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))

    answer = client.messages(_body())

    check_answered(client.run)
    (record,) = client.run.records
    assert (record.model, record.input_tokens, record.output_tokens) == (HAIKU, 20, 5)
    assert record.cost_usd == answer.cost_usd > 0
    assert record.estimate_usd == answer.estimate_usd >= answer.cost_usd
    assert client.run.budget.spent_usd == pytest.approx(client.run.spent_usd)
    assert answer.outcome == "end_turn" and answer.error is None


def _worst(body: Json, prompt: int, allowance: ToolAllowance | None = None) -> float:
    allowed = allowance or ToolAllowance()
    return worst_case_usd(body, prompt, PRICES, allowance=allowed, batch=False)


def test_a_count_is_the_largest_over_the_chain_plus_its_margin(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    body = _body(model=OPUS, fallbacks=[{"model": FALLBACK}])
    api.count = 5000
    assert client.estimate(body) == pytest.approx(
        _worst(body, 5000 + count_margin(5000))
    )
    counted = [json.loads(r.read())["model"] for r in api.requests]
    assert counted == [OPUS, FALLBACK]


def test_a_count_does_not_see_server_tools_so_they_are_stripped_and_added(
    api: FakeApi, host_key: str
) -> None:
    """Review item 5: count_tokens refuses server tools; the dry API does too."""
    client = ExperimentClient(_run(api))
    body = _body(tools=[SEARCH])
    api.count = 900
    expected = _worst(
        body,
        900 + count_margin(900) + count_extras(body),
        server_allowance([SEARCH], batch=False),
    )
    assert client.estimate(body) == pytest.approx(expected)
    (count,) = [json.loads(r.read()) for r in api.requests]
    assert "tools" not in count
    assert count_extras(body) >= SERVER_TOOL_DEFINITION_TOKENS
    assert client.run.api_errors() == []  # no spurious count 400 for the cost table


@pytest.mark.parametrize("bad", [None, -1, True, "x", 0])
def test_a_failed_count_falls_back_to_the_structure_for_text(
    api: FakeApi, host_key: str, bad: object
) -> None:
    client = ExperimentClient(_run(api))
    api.count = bad
    body = _body()
    assert client.estimate(body) == pytest.approx(
        _worst(body, structural_tokens(body, {}))
    )
    assert client.count_tokens(body) is None


def test_a_pdf_without_a_count_is_never_sent(api: FakeApi, host_key: str) -> None:
    """Review item 4: no page scanning; a PDF needs count_tokens."""
    client = ExperimentClient(_run(api))
    body = _body(messages=[{"role": "user", "content": [_pdf_block()]}])
    api.count_status = 500
    with pytest.raises(ExperimentRefusedError, match="PDF"):
        client.messages(body)
    with pytest.raises(ExperimentRefusedError, match="PDF"):
        client.estimate(body, count=False)
    assert _sent(api) == []
    api.count_status, api.count = 200, 3000
    assert client.estimate(body) == pytest.approx(
        _worst(body, 3000 + count_margin(3000))
    )


@pytest.mark.parametrize(
    "source",
    [
        {"type": "file", "file_id": "file_01"},
        {"type": "url", "url": "https://x.example/a.pdf"},
    ],
    ids=["file", "url"],
)
def test_file_and_url_sources_are_refused_before_anything_is_sent(
    api: FakeApi, host_key: str, source: Json
) -> None:
    client = ExperimentClient(_run(api))
    body = _body(
        messages=[{"role": "user", "content": [{"type": "document", "source": source}]}]
    )
    with pytest.raises(ExperimentRefusedError, match="inline"):
        client.messages(body)
    with pytest.raises(ExperimentRefusedError, match="inline"):
        client.submit([BatchItem("a", body)])
    assert api.requests == []


def test_a_stream_request_is_refused_before_sending(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    for value in (True, False):
        with pytest.raises(ExperimentRefusedError, match="stream"):
            client.messages(_body(stream=value))
    with pytest.raises(ExperimentRefusedError, match="stream"):
        client.submit([BatchItem("a", _body(stream=False))])
    assert api.requests == []


def test_an_explicit_allowance_never_undercuts_in_the_client(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    body = _body(tools=[SEARCH])
    documented = client.estimate(body)
    assert client.estimate(body, allowance=ToolAllowance()) == pytest.approx(documented)
    with pytest.raises(ExperimentRefusedError, match="batch"):
        client.estimate(body, batch=True)


def test_a_request_the_cap_cannot_afford_is_never_sent(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api, cap=1e-9))
    with pytest.raises(BudgetExceeded):
        client.messages(_body())
    assert _sent(api) == [] and client.run.records == []


def test_messages_refuses_a_body_json_cannot_hold(api: FakeApi, host_key: str) -> None:
    client = ExperimentClient(_run(api))
    with pytest.raises(ExperimentRefusedError, match="JSON"):
        client.messages(_body(metadata={"x": object()}))


def test_sdk_blocks_echoed_back_are_sent_as_the_api_wrote_them(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    first = client.messages(_body())
    assert first.message is not None
    turns = [
        _user(),
        {"role": "assistant", "content": first.message.content},
        _user("Again."),
    ]
    client.messages(_body(messages=turns))
    sent = json.loads(_sent(api)[-1].read())
    assert sent["messages"][1]["content"] == [{"type": "text", "text": "ok"}]


# ---------------------------------------------------------------------------
# After the send: every outcome is charged, then any surprise is re-raised
# ---------------------------------------------------------------------------


def test_a_lost_answer_is_charged_its_worst_case(api: FakeApi, host_key: str) -> None:
    client = ExperimentClient(_run(api))
    api.timeout = True
    answer = client.messages(_body())
    assert (
        answer.status is None and not answer.accepted and answer.outcome == "no_answer"
    )
    assert answer.cost_usd == answer.estimate_usd == client.run.spent_usd > 0


def test_an_unpriceable_answer_is_charged_its_worst_case(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    api.reply = _message(
        usage={"input_tokens": 1, "output_tokens": 1, "iterations": "x"}
    )
    answer = client.messages(_body())
    assert answer.outcome == "unpriced" and answer.cost_usd == answer.estimate_usd


def test_a_2xx_body_that_is_not_json_is_charged_its_worst_case(host_key: str) -> None:
    def garbled(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 10})
        return httpx2.Response(
            200, content=b"not json", headers={"content-type": "application/json"}
        )

    answer = ExperimentClient(_run(garbled)).messages(_body())
    assert answer.outcome == "unreadable" and answer.cost_usd == answer.estimate_usd


def test_a_surprise_after_the_request_left_is_charged_then_raised(
    api: FakeApi, host_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review item 8: an exception the client does not expect, once the
    request may have left, costs its worst case and still propagates."""
    client = ExperimentClient(_run(api))

    def boom(**_: object) -> object:
        raise RuntimeError("the SDK broke")

    monkeypatch.setattr(client.sdk.beta.messages, "create", boom)
    with pytest.raises(RuntimeError, match="the SDK broke"):
        client.messages(_body())
    (record,) = client.run.records
    assert record.outcome == "lost" and record.cost_usd == record.estimate_usd > 0


def test_a_surprise_while_pricing_is_charged_then_raised(
    api: FakeApi, host_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = ExperimentClient(_run(api))

    def broken(*_: object, **__: object) -> float:
        raise KeyError("prices")

    monkeypatch.setattr(harness, "price_message", broken)
    with pytest.raises(KeyError):
        client.messages(_body())
    (record,) = client.run.records
    assert record.outcome == "lost" and record.cost_usd == record.estimate_usd


def test_an_http_refusal_costs_nothing_and_never_carries_the_key(
    api: FakeApi, host_key: str, tmp_path: Path
) -> None:
    """
    GIVEN the API's error message echoes the key (worst case)
    WHEN the request is refused and the answer recorded
    THEN the answer, the results line, the summary and the cost notes hold no key
    """
    results, summary = tmp_path / "results.jsonl", tmp_path / "summary.md"
    environ = {"LIVE_RESULTS_PATH": str(results), "GITHUB_STEP_SUMMARY": str(summary)}
    recorder = ExperimentRecorder("E0", environ)
    client = ExperimentClient(_run(api), recorder=recorder)
    api.status, api.error_message = 400, f"bad key {host_key} in request"

    answer = client.messages(_body())
    recorder.record(
        "E0", "refusal", HAIKU, {"error": answer.error, "status": answer.status}
    )
    recorder.finish(lambda _: None)

    assert (answer.status, answer.cost_usd, answer.outcome) == (400, 0.0, "http_400")
    assert answer.error is not None and "invalid_request_error" in answer.error
    texts = (
        answer.error,
        results.read_text(),
        summary.read_text(),
        repr(answer),
        *client.run.api_errors(),
    )
    for text in texts:
        assert host_key not in text
    assert "[redacted]" in answer.error
    for exchange in client.run.capture.exchanges:
        assert (
            host_key not in repr(exchange.headers)
            and host_key.encode() not in exchange.body
        )


def test_a_code_execution_container_is_noted_in_the_run(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    api.reply = {
        **_message(),
        "container": {"id": "container_01Probe", "expires_at": "2026-10-23T01:00:00Z"},
    }
    client.messages(_body())
    assert any("container_01Probe" in note for note in client.run.notes)


# ---------------------------------------------------------------------------
# Batches: reserved, waited for, collected, or left pending with their id
# ---------------------------------------------------------------------------


def _item(custom_id: str = "a", **extra: object) -> BatchItem:
    return BatchItem(custom_id, _body(**extra))


def test_a_batch_is_reserved_at_submit_and_priced_at_half_when_collected(
    api: FakeApi, host_key: str, tmp_path: Path
) -> None:
    results = tmp_path / "results.jsonl"
    recorder = ExperimentRecorder("E0", {"LIVE_RESULTS_PATH": str(results)})
    clock = Clock()
    client = ExperimentClient(
        _run(api), recorder=recorder, clock=clock, sleep=clock.sleep
    )
    batch = client.submit(
        [_item("a"), _item("b")], betas=["server-side-fallback-2026-06-01"]
    )
    assert batch.batch_id == BATCH_ID
    (create,) = [r for r in api.requests if r.url.path == "/v1/messages/batches"]
    assert "server-side-fallback-2026-06-01" in create.headers["anthropic-beta"]
    assert sum(batch.estimates.values()) == pytest.approx(
        2 * client.estimate(_body(), batch=True)
    )
    assert client.reserved_usd == pytest.approx(sum(batch.estimates.values()))
    reason = {"type": "invalid_request_error", "message": "fallbacks not supported"}
    api.results = [
        {"custom_id": "a", "result": {"type": "succeeded", "message": _message()}},
        {
            "custom_id": "b",
            "result": {"type": "errored", "error": {"type": "error", "error": reason}},
        },
        {
            "custom_id": "stranger",
            "result": {"type": "succeeded", "message": _message()},
        },
    ]

    assert client.wait(batch, timeout_s=60, poll_s=5) == "ended"
    answers = client.results(batch)

    assert set(answers) == {"a", "b"}
    rates = PRICES[HAIKU]
    assert answers["a"].cost_usd == pytest.approx(
        (20 * rates.input + 5 * rates.output) / 2e6
    )
    assert (answers["b"].outcome, answers["b"].cost_usd) == ("errored", 0.0)
    assert (
        answers["b"].error is not None
        and "fallbacks not supported" in answers["b"].error
    )
    assert client.reserved_usd == 0
    assert [r.outcome for r in client.run.records] == ["end_turn", "errored"]
    lines = [json.loads(line) for line in results.read_text().splitlines()]
    assert lines[0]["metrics"]["status"] == "submitted" and lines[0]["item"] == BATCH_ID


def test_a_reserved_batch_blocks_spending_its_reservation_twice(
    api: FakeApi, host_key: str
) -> None:
    one = ExperimentClient(_run(api)).estimate(_body(), batch=True)
    client = ExperimentClient(_run(api, cap=one * 1.5))
    client.submit([_item()])
    with pytest.raises(BudgetExceeded):
        client.submit([_item()])


def test_a_batch_that_does_not_finish_in_time_keeps_its_id_and_its_worst_case(
    api: FakeApi, host_key: str, tmp_path: Path
) -> None:
    """
    GIVEN a batch still processing when the wait times out (a GitHub job is
        capped at 6 hours; a batch may take 24)
    WHEN the client closes (twice)
    THEN its id is in the results as pending (to collect later) and the run
        is charged its worst case exactly once, since it may still be billed
    """
    results = tmp_path / "results.jsonl"
    recorder = ExperimentRecorder("E0", {"LIVE_RESULTS_PATH": str(results)})
    clock = Clock()
    api.batch_status = "in_progress"
    with ExperimentClient(
        _run(api), recorder=recorder, clock=clock, sleep=clock.sleep
    ) as client:
        batch = client.submit([_item()])
        assert client.wait(batch, timeout_s=100, poll_s=30) == "in_progress"
        assert clock.now == pytest.approx(100) and max(clock.sleeps) <= 30
        with pytest.raises(ValueError, match="ended"):
            client.results(batch)
    client.close()  # a second close changes nothing

    (record,) = client.run.records
    assert record.outcome == "batch_pending"
    assert record.cost_usd == record.estimate_usd == batch.estimates["a"]
    assert client.reserved_usd == 0
    lines = [json.loads(line) for line in results.read_text().splitlines()]
    assert [line["metrics"]["status"] for line in lines] == [
        "submitted",
        "pending",
        "pending",
    ]
    assert all(line["item"] == BATCH_ID for line in lines)
    assert sum(BATCH_ID in note for note in client.run.notes) == 1


def test_a_budget_overrun_while_collecting_charges_each_request_once(
    api: FakeApi, host_key: str
) -> None:
    """Review item 14: results() raising BudgetExceeded mid-loop leaves the
    charged request settled and the rest to close(), each charged once."""
    client = ExperimentClient(_run(api, cap=0.05))
    batch = client.submit([_item("a"), _item("b")])
    huge = _message(usage={"input_tokens": 5_000_000, "output_tokens": 0})
    api.results = [
        {"custom_id": "a", "result": {"type": "succeeded", "message": huge}},
        {"custom_id": "b", "result": {"type": "succeeded", "message": _message()}},
    ]
    client.wait(batch, timeout_s=1, poll_s=1)
    with pytest.raises(BudgetExceeded):
        client.results(batch)
    assert batch.settled == {"a"}
    client.close()
    client.close()
    assert [r.outcome for r in client.run.records] == ["end_turn", "batch_pending"]
    overruns = [n for n in client.run.notes if "budget overrun while closing" in n]
    assert len(overruns) == 1 and "exceeds the cap" in overruns[0]
    assert KEY not in " ".join(client.run.notes)


def test_polling_survives_a_transient_error(host_key: str) -> None:
    polls = [
        httpx2.Response(200, json=_batch()),
        httpx2.Response(500, json={"type": "error", "error": {}}),
        httpx2.Response(200, json=_batch("ended", f"{BASE}/r")),
    ]

    def flaky(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 1})
        if request.method == "POST":
            return httpx2.Response(200, json=_batch())
        return polls.pop(0)

    clock = Clock()
    client = ExperimentClient(_run(flaky), clock=clock, sleep=clock.sleep)
    batch = client.submit([_item()])
    assert client.wait(batch, timeout_s=600, poll_s=10) == "ended"
    assert polls == [] and clock.sleeps == [10, 10]


def test_results_from_another_host_are_refused_so_the_key_stays_home(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    batch = client.submit([_item()])
    api.results_url = "https://elsewhere.example/results"
    client.wait(batch, timeout_s=1, poll_s=1)
    with pytest.raises(ExperimentRefusedError, match="results"):
        client.results(batch)
    assert "elsewhere.example" not in {r.url.host for r in api.requests}


def test_a_results_url_swapped_on_the_sdks_own_retrieve_never_gets_the_key(
    api: FakeApi, host_key: str
) -> None:
    """Review item 7, time of check and time of use: the client checks the
    URL, then the SDK retrieves the batch again and follows what it gets."""
    client = ExperimentClient(_run(api))
    batch = client.submit([_item()])
    client.wait(batch, timeout_s=1, poll_s=1)
    api.sdk_results_url = "https://elsewhere.example/v1/stolen"
    api.swap_from = 3  # 1: wait; 2: the client's own check; 3: the SDK's
    with pytest.raises(ExperimentAPIError):
        client.results(batch)
    assert "elsewhere.example" not in {r.url.host for r in api.requests}
    assert any("elsewhere.example" in note for note in client.run.notes)
    client.close()
    assert [r.outcome for r in client.run.records] == ["batch_pending"]


def test_missing_results_are_charged_their_worst_case(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    batch = client.submit([_item("a")])
    client.wait(batch, timeout_s=1, poll_s=1)
    answers = client.results(batch)
    assert answers["a"].outcome == "batch_missing"
    assert answers["a"].cost_usd == batch.estimates["a"]
    assert client.results(batch) == {}  # settled once


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([], "at least one"),
        ([_item("a"), _item("a")], "unique"),
        ([_item("bad id!")], "custom_id"),
        ([_item("a", betas=["x"])], "betas"),
        ([_item("a", tools=[SEARCH])], "batch"),
    ],
    ids=["empty", "duplicate", "bad-id", "betas-in-params", "server-tool-no-allowance"],
)
def test_submit_refuses_a_malformed_batch(
    api: FakeApi, host_key: str, items: list[BatchItem], message: str
) -> None:
    client = ExperimentClient(_run(api))
    with pytest.raises(ExperimentRefusedError, match=message):
        client.submit(items)
    assert "/v1/messages/batches" not in api.paths()


def test_a_batch_item_with_server_tools_takes_an_explicit_allowance(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    item = BatchItem("a", _body(tools=[SEARCH]), ToolAllowance(30))
    batch = client.submit([item])
    expected = client.estimate(item.params, allowance=ToolAllowance(30), batch=True)
    assert batch.estimates["a"] == pytest.approx(expected)


def test_a_refused_batch_reserves_nothing(api: FakeApi, host_key: str) -> None:
    api.batch_create_status = 400
    client = ExperimentClient(_run(api))
    with pytest.raises(ExperimentAPIError) as caught:
        client.submit([_item()])
    assert caught.value.status == 400 and client.reserved_usd == 0


def test_wait_refuses_a_timeout_past_the_job_limit_and_cancel_is_sent(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    batch = client.submit([_item()])
    for bad in (MAX_WAIT_S + 1, -1.0, math.inf):
        with pytest.raises(ValueError):
            client.wait(batch, timeout_s=bad, poll_s=1)
    with pytest.raises(ValueError):
        client.wait(batch, timeout_s=1, poll_s=0)
    client.cancel(batch)
    assert api.paths("POST")[-1].endswith("/cancel")


# ---------------------------------------------------------------------------
# Files, models and count_tokens
# ---------------------------------------------------------------------------


def test_an_uploaded_file_is_deleted_even_when_the_block_raises(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    pdf = minimal_pdf("hi", pages=2)
    with (
        pytest.raises(RuntimeError),
        client.uploaded("probe.pdf", pdf, "application/pdf") as file,
    ):
        assert (file.file_id, file.pages, file.size_bytes) == ("file_01", 2, len(pdf))
        raise RuntimeError("experiment failed")
    assert api.paths("DELETE") == ["/v1/files/file_01"]
    assert client.files == {}


def test_a_failed_delete_is_noted_and_close_deletes_what_is_left(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    client.upload("notes.txt", b"hello", "text/plain")
    api.delete_status = 500
    assert client.delete("file_01") is False
    assert any("file_01" in note for note in client.run.notes)
    api.delete_status = 200
    client.close()
    client.close()
    assert client.files == {}
    assert api.paths("DELETE") == ["/v1/files/file_01"] * 2


@pytest.mark.parametrize("name", ["../x.pdf", "", "a/b.txt", "x" * 200])
def test_upload_refuses_a_file_name_that_is_not_a_plain_name(
    api: FakeApi, host_key: str, name: str
) -> None:
    with pytest.raises(ExperimentRefusedError, match="file name"):
        ExperimentClient(_run(api)).upload(name, b"x", "text/plain")


def test_an_api_error_never_carries_the_key_or_chains_the_sdk_error(
    api: FakeApi, host_key: str
) -> None:
    client = ExperimentClient(_run(api))
    api.model_status, api.error_message = 404, f"model not found for {host_key}"
    with pytest.raises(ExperimentAPIError) as caught:
        client.models_get("claude-unknown")
    error = caught.value
    assert error.status == 404
    assert error.__cause__ is None and error.__context__ is None
    assert host_key not in str(error) and host_key not in repr(error.args)


def test_models_get_and_count_tokens(api: FakeApi, host_key: str) -> None:
    client = ExperimentClient(_run(api))
    info = client.models_get(HAIKU)
    assert info["id"] == HAIKU and info["max_input_tokens"] == 1_000_000
    assert client.count_tokens(_body()) == 100
    api.count_status = 500
    assert client.count_tokens(_body()) is None


def test_upload_errors_are_mapped(host_key: str) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        error = {"type": "request_too_large", "message": "big"}
        return httpx2.Response(413, json={"type": "error", "error": error})

    with pytest.raises(ExperimentAPIError) as caught:
        ExperimentClient(_run(refuse)).upload("a.txt", b"x", "text/plain")
    assert caught.value.status == 413


def test_a_lost_connection_on_a_free_call_is_an_api_error(host_key: str) -> None:
    def drop(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(ExperimentAPIError) as caught:
        ExperimentClient(_run(drop)).models_get(HAIKU)
    assert caught.value.status is None


# ---------------------------------------------------------------------------
# The experiments package in a real pytest run: never without -m live
# ---------------------------------------------------------------------------

LIVE_MODULES = tuple(sorted(p.name for p in HERE.glob("test_*_live.py")))
"""Every module here that may spend: named ``test_*_live.py`` (X5 and X6
add theirs; the subprocess checks below then cover them too)."""


def _live_marks(name: str) -> list[str]:
    tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
    return [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]


def test_a_module_is_marked_live_exactly_when_it_is_named_live() -> None:
    """A test that spends sits in a ``*_live.py`` module marked ``live``, and
    an offline test module (this one, X5's and X6's) carries no live mark."""
    assert "test_probes_live.py" in LIVE_MODULES
    for path in sorted(HERE.glob("test_*.py")):
        marks = _live_marks(path.name)
        if path.name in LIVE_MODULES:
            assert marks == ["pytest.mark.live"], path.name
        else:
            assert "pytest.mark.live" not in marks, path.name


def _pytest(
    tmp_path: Path, *args: str, key: str | None, worker: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"ANTHROPIC_API_KEY", "PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER"}
        and not name.upper().endswith("_PROXY")
    }
    env.update(
        ENGINE_API_BASE_URL="https://127.0.0.1:9",
        NO_PROXY="*",
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        LIVE_RESULTS_PATH=str(tmp_path / "results.jsonl"),
        COVERAGE_PROCESS_START="",
    )
    if key is not None:
        env["ANTHROPIC_API_KEY"] = key
    if worker is not None:
        env["PYTEST_XDIST_WORKER"] = worker
    argv = [
        sys.executable, "-m", "pytest", "-o", "addopts=", "--import-mode=importlib",
        "-p", "no:cacheprovider", "-p", "no:randomly", "-q", "-rs", *args,
        *(str(HERE / name) for name in LIVE_MODULES),
    ]  # fmt: skip
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        cwd=SERVICE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize(
    ("args", "key", "expect"),
    [
        (("-m", "live"), None, " skipped"),
        ((), KEY, " skipped"),
        (("-m", "live or not live"), KEY, " skipped"),
        (("-m", "not live"), KEY, " deselected"),
    ],
    ids=["no-key", "no-marker-expression", "live-or-not-live", "not-live"],
)
def test_the_probes_never_run_unless_selected_with_a_key(
    tmp_path: Path, args: tuple[str, ...], key: str | None, expect: str
) -> None:
    proc = _pytest(tmp_path, *args, key=key)
    output = proc.stdout + proc.stderr
    assert proc.returncode in (0, 5), output
    summary = output.strip().splitlines()[-1]
    assert expect in summary, output
    for outcome in ("passed", "failed", "error"):
        assert outcome not in summary, output
    assert not (tmp_path / "results.jsonl").exists()
    assert KEY not in output


def test_the_probes_fail_under_xdist_before_spending(tmp_path: Path) -> None:
    proc = _pytest(tmp_path, "-m", "live", key=KEY, worker="gw0")
    output = proc.stdout + proc.stderr
    summary = output.strip().splitlines()[-1]
    # pytest.fail in the live fixture: every probe errors at setup
    assert " error" in summary and "passed" not in summary, output
    assert "-n 0" in output and KEY not in output


OVERRUN_MODULE = """
import pytest

from live.conftest import RequestRecord, StartLive

pytestmark = pytest.mark.live


def test_overrun(live: StartLive) -> None:
    run = live(0.01)
    run.records.append(RequestRecord("claude-haiku-5-5", 0, 0, 0, 0, 0.5, 0.0, "end_turn"))


def test_within(live: StartLive) -> None:
    run = live(0.01)
    run.records.append(RequestRecord("claude-haiku-5-5", 0, 0, 0, 0, 0.005, 0.0, "end_turn"))
"""


def test_the_live_fixture_fails_a_run_that_spent_past_its_cap(tmp_path: Path) -> None:
    """An overrun can never be a green test: the ``live`` fixture records the
    ledger row, then fails the test at teardown."""
    module = tmp_path / "test_overrun_live.py"
    module.write_text(OVERRUN_MODULE, encoding="utf-8")
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER"}
        and not name.upper().endswith("_PROXY")
    }
    env.update(
        ANTHROPIC_API_KEY=KEY,
        ENGINE_API_BASE_URL="https://127.0.0.1:9",
        NO_PROXY="*",
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        PYTHONPATH=str(SERVICE_DIR / "tests"),
        COVERAGE_PROCESS_START="",
    )
    argv = [
        sys.executable, "-m", "pytest", "-c", str(SERVICE_DIR / "pyproject.toml"),
        "-o", "addopts=", "--import-mode=importlib", "-p", "no:cacheprovider",
        "-p", "live.conftest", "-m", "live", "-q", "-rE", str(module),
    ]  # fmt: skip
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        cwd=SERVICE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    output = proc.stdout + proc.stderr
    summary = output.strip().splitlines()[-1]
    # the overrun's call passes, its teardown errors: the run is red
    assert proc.returncode != 0 and "2 passed, 1 error" in summary, output
    errors = [line for line in output.splitlines() if line.startswith("ERROR ")]
    assert len(errors) == 1 and "test_overrun" in errors[0], output
    assert "ERROR at teardown of test_overrun" in output, output
    message = "live run over its cap: test_overrun: spent 0.5000 USD > cap 0.0100 USD"
    assert message in output, output
    table = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "| test_overrun |" in table and "| test_within |" in table
    assert KEY not in output


# ---------------------------------------------------------------------------
# Dry runs: each E1 probe's own body against the fake API
# ---------------------------------------------------------------------------


@pytest.fixture
def dry(
    api: FakeApi, host_key: str
) -> Iterator[Callable[[], tuple[StartLive, ExperimentRecorder]]]:
    """A ``live`` start on the fake API, and a recorder for the probes."""
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry-{len(runs)}", cap_usd, wire=httpx2.MockTransport(api))
        runs.append(run)
        return run

    yield lambda: (start, ExperimentRecorder("E1", {}))
    for run in runs:
        assert run.spent_usd <= run.cap_usd
        if api.count_status == 200:  # no spurious count 400 for the cost table
            count_errors = [e for e in run.api_errors() if "count_tokens" in e]
            assert count_errors == [], count_errors


def test_the_e1_caps_fit_the_half_dollar() -> None:
    assert math.fsum(probes.CAPS.values()) <= probes.E1_CAP_USD == 0.50


@pytest.mark.parametrize("name", sorted(probes.PROBES))
@pytest.mark.parametrize("status", [200, 400])
def test_each_e1_probe_passes_whether_the_api_accepts_or_refuses(
    name: str,
    status: int,
    api: FakeApi,
    dry: Callable[[], tuple[StartLive, ExperimentRecorder]],
) -> None:
    """A probe records what the API said; only a missing answer fails it."""
    api.status = api.batch_create_status = status
    api.model_status = 200 if status == 200 else 404
    api.results = [
        {
            "custom_id": probes.BATCH_ID,
            "result": {"type": "succeeded", "message": _message(OPUS)},
        }
    ]
    start, recorder = dry()

    probes.test_e1_probe(name, start, recorder)

    assert recorder.rows, name
    assert {row.experiment for row in recorder.rows} <= {"E1", "harness"}
    assert any(row.experiment == "E1" for row in recorder.rows)


def test_each_e1_probe_worst_case_fits_its_cap_with_a_large_count(
    api: FakeApi, dry: Callable[[], tuple[StartLive, ExperimentRecorder]]
) -> None:
    api.count = 2000
    start, recorder = dry()
    for name in sorted(probes.PROBES):
        probes.test_e1_probe(name, start, recorder)  # BudgetExceeded would fail it


def test_the_web_search_probe_sends_the_shape_the_experiments_will(
    api: FakeApi, dry: Callable[[], tuple[StartLive, ExperimentRecorder]]
) -> None:
    start, recorder = dry()
    probes.PROBES["web_search_format"](start, recorder)
    (sent,) = [json.loads(r.read()) for r in _sent(api)]
    assert sent["tools"] == [
        {
            "type": "web_search_20260318",
            "name": "web_search",
            "max_uses": 1,
            "allowed_callers": ["direct"],
        }
    ]


def test_the_pdf_probe_records_a_count_refusal_instead_of_sending(
    api: FakeApi, dry: Callable[[], tuple[StartLive, ExperimentRecorder]]
) -> None:
    api.count_status = 400
    start, recorder = dry()
    probes.PROBES["pdf_in_tool_result"](start, recorder)
    (row,) = recorder.rows
    assert row.metrics["outcome"] == "count_refused" and _sent(api) == []


def test_the_batch_probe_leaves_a_running_batch_pending(
    api: FakeApi,
    dry: Callable[[], tuple[StartLive, ExperimentRecorder]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probes, "BATCH_WAIT_S", 0)
    api.batch_status = "in_progress"
    start, recorder = dry()
    probes.PROBES["batch_fallbacks"](start, recorder)
    assert [row.metrics.get("status") for row in recorder.rows] == [
        "submitted",
        "pending",
        "pending",
    ]


def test_the_models_probe_records_capabilities_and_limits(
    api: FakeApi, dry: Callable[[], tuple[StartLive, ExperimentRecorder]]
) -> None:
    start, recorder = dry()
    probes.PROBES["models"](start, recorder)
    rows = {row.item: row.metrics for row in recorder.rows}
    assert set(rows) == {probes.OPUS, probes.SONNET, probes.HAIKU, probes.FABLE}
    opus = rows[probes.OPUS]
    assert (
        opus["cap.citations"] is True and opus["cap.server_tools.web_search"] is False
    )
    assert opus["allowed_fallback_models"] == FALLBACK
    assert rows[probes.HAIKU]["allowed_fallback_models"] == ""
    assert opus["max_input_tokens"] == 1_000_000 and "cap.odd" not in opus
    assert not any(key.startswith("cap.deep") for key in opus)
    assert not any(key.startswith("cap.") for key in rows[SONNET])


def test_the_probe_table_goes_to_the_terminal_or_the_summary(
    pytestconfig: pytest.Config, tmp_path: Path
) -> None:
    summary = tmp_path / "s.md"
    recorder = ExperimentRecorder("E1", {"GITHUB_STEP_SUMMARY": str(summary)})
    probes.finish(recorder, pytestconfig)
    assert not summary.exists()  # nothing recorded, nothing written
    recorder.record("E1", "arm", "item", {"status": 200})
    probes.finish(recorder, pytestconfig)
    assert "| E1 | arm | item | status=200 |" in summary.read_text()

    class NoReporter:
        class pluginmanager:  # noqa: N801 - mirrors pytest.Config
            @staticmethod
            def get_plugin(name: str) -> None:
                return None

    printed = ExperimentRecorder("E1", {})
    printed.record("E1", "arm", "item", {})
    probes.finish(printed, cast(pytest.Config, NoReporter()))


def test_a_probe_fails_when_the_key_is_refused(
    api: FakeApi, dry: Callable[[], tuple[StartLive, ExperimentRecorder]]
) -> None:
    api.status = 401
    start, recorder = dry()
    with pytest.raises(AssertionError, match="401"):
        probes.PROBES["effort"](start, recorder)


def test_the_answered_rule() -> None:
    def answer(status: int | None) -> Answer:
        return Answer(status, None, None, 0.0, 0.0, "x")

    assert probes.answered(answer(200)) and probes.answered(answer(400))
    assert not probes.answered(answer(None)) and not probes.answered(answer(403))
