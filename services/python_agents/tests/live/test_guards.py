"""Offline tests of the live suite's own guards (``tests/live/conftest.py``).

These run in the normal suite (no ``live`` marker, no network, no key): the
skip logic that keeps every live test from spending money unless ``-m live``
selected it and a key is set, the session ledger that refuses a test before
it could push the suite past ``LIVE_SUITE_CAP_USD``, the cost summary written
to the CI job summary, and the two recorders the live tests read their
evidence from (the httpx capture of every request body and response status,
and the transport wrapper that prices every attempt the way ``call()``
charges it). The last test runs the live modules in a pytest subprocess and
proves they all skip, with the API pointed at a closed local port.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx2
import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain, preflight_estimate, response_cost
from autonomous_ai_agents.clients.transport import (
    COUNT_MARGIN_DIVISOR,
    COUNT_MARGIN_MIN_TOKENS,
    FALLBACK_BETA,
    LLMHTTPUnavailableError,
    LLMNoResponseError,
    LLMRequest,
    ScriptedTransport,
    call,
)
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.errors import (
    LLMRequestError,
    LLMUnavailable,
)

from .conftest import (
    LIVE_SUITE_CAP_USD,
    SKIP_NO_KEY,
    SKIP_NOT_SELECTED,
    CapturingTransport,
    CostRow,
    LiveRun,
    RecordingTransport,
    RequestRecord,
    StartLive,
    SuiteBudgetRefusedError,
    SuiteLedger,
    added_lines,
    live_selected,
    live_skip_reason,
    must_refuse,
    render_cost_table,
    require_sandbox,
    skip_unless_live,
    suite_cap,
    tool_calls,
    usage_tokens,
    write_cost_summary,
    xdist_refusal,
)
from .test_contract import (
    test_count_tokens_works_and_stays_within_the_byte_bound as count_contract,
)
from .test_contract import (
    test_explicit_fallbacks_body_and_beta_header_are_accepted as fallbacks_contract,
)
from .test_contract import (
    test_operator_notice_after_tool_results_is_accepted as notice_contract,
)
from .test_contract import (
    test_prompt_caching_reads_the_cache_on_a_repeat as cache_contract,
)
from .test_contract import (
    test_role_system_notice_is_probed_and_recorded as system_contract,
)
from .test_contract import (
    test_text_editor_tool_type_is_accepted as tool_contract,
)
from .test_contract import (
    test_understand_schema_is_accepted_and_the_reply_validates as schema_contract,
)

LIVE_DIR = Path(__file__).resolve().parent
SERVICE_DIR = LIVE_DIR.parents[1]
LIVE_MODULES = (
    "test_contract.py",
    "test_understand_live.py",
    "test_e2e_live.py",
    "test_attack_live.py",
)
KEY = "sk-ant-api03-LIVEGUARD-0123456789abcdef"
ENGINE = "claude-opus-5-5"
FALLBACK = "claude-opus-4-8"
Json = dict[str, object]

USAGE: Json = {
    "input_tokens": 12,
    "output_tokens": 30,
    "cache_creation_input_tokens": 100,
    "cache_read_input_tokens": 2000,
}


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ANTHROPIC_API_KEY": KEY,
        "ENGINE_MODEL": ENGINE,
        "ENGINE_FALLBACKS": True,
        "ENGINE_FALLBACK_MODELS": (FALLBACK,),
    }
    base.update(overrides)
    return Settings.model_validate(base)


def _message(usage: Json = USAGE, model: str = ENGINE) -> Json:
    return {
        "id": "msg_01LiveGuard",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": usage,
    }


def _request(text: str = "Say ok.") -> LLMRequest:
    return LLMRequest(
        system="You answer briefly.",
        messages=({"role": "user", "content": text},),
        max_tokens=64,
    )


def _wire(count: int = 42) -> Callable[[httpx2.Request], httpx2.Response]:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": count})
        return httpx2.Response(200, json=_message(), headers={"request-id": "req_1"})

    return answer


def _row(test: str = "t", cost: float = 0.5, estimate: float = 1.0) -> CostRow:
    return CostRow(
        test=test,
        models=(ENGINE,),
        input_tokens=10,
        output_tokens=20,
        cache_read_tokens=30,
        cache_write_tokens=40,
        cost_usd=cost,
        estimate_usd=estimate,
        cap_usd=1.0,
        notes=(),
    )


# ---------------------------------------------------------------------------
# The skip guard: -m live selected explicitly, and a key in the environment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("markexpr", "selected"),
    [
        ("live", True),
        ("(live)", True),
        ("live and not slow", True),
        ("live or slow", True),
        ("", False),
        ("not live", False),
        ("not  live", False),
        ("slow", False),
        ("alive", False),
        ("live or not live", False),
        ("not (slow or live)", False),
        ("live and", False),
        ("live)", False),
        ("(live", False),
        ("live(x=1)", False),
    ],
)
def test_live_selected_only_when_the_expression_needs_the_live_marker(
    markexpr: str, selected: bool
) -> None:
    assert live_selected(markexpr, frozenset({"live"})) is selected


def test_live_selected_looks_at_the_items_other_markers() -> None:
    marks = frozenset({"live", "slow"})
    assert live_selected("live and slow", marks)
    assert not live_selected("slow", marks)  # selects it without asking for live
    assert not live_selected("live", frozenset({"slow"}))


@pytest.mark.parametrize(
    ("markexpr", "environ", "reason"),
    [
        ("not live", {"ANTHROPIC_API_KEY": KEY}, SKIP_NOT_SELECTED),
        ("", {"ANTHROPIC_API_KEY": KEY}, SKIP_NOT_SELECTED),
        ("live", {}, SKIP_NO_KEY),
        ("live", {"ANTHROPIC_API_KEY": "  "}, SKIP_NO_KEY),
        ("live", {"ANTHROPIC_API_KEY": KEY}, None),
    ],
)
def test_live_skip_reason(
    markexpr: str, environ: Mapping[str, str], reason: str | None
) -> None:
    assert live_skip_reason(markexpr, frozenset({"live"}), environ) == reason


def test_skip_unless_live_skips_a_marked_test_that_was_not_selected() -> None:
    with pytest.raises(pytest.skip.Exception, match="selected with -m live"):
        skip_unless_live({"live"}, "", {"ANTHROPIC_API_KEY": KEY})
    with pytest.raises(pytest.skip.Exception, match="ANTHROPIC_API_KEY"):
        skip_unless_live({"live"}, "live", {})


def test_skip_unless_live_lets_selected_and_unmarked_tests_run() -> None:
    skip_unless_live({"live"}, "live", {"ANTHROPIC_API_KEY": KEY})
    skip_unless_live(set(), "", {})  # not a live test: never skipped here


def test_every_live_module_is_marked_live() -> None:
    """A test in these modules can spend money, so each module carries
    ``pytestmark = pytest.mark.live`` (read from the source, not imported)."""
    for name in LIVE_MODULES:
        tree = ast.parse((LIVE_DIR / name).read_text(encoding="utf-8"))
        marks = [
            ast.unparse(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
        ]
        assert marks == ["pytest.mark.live"], name
        tests = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        ]
        assert tests, name


# ---------------------------------------------------------------------------
# The suite cap and the ledger
# ---------------------------------------------------------------------------


def test_suite_cap_defaults_to_twelve_dollars_and_reads_the_environment() -> None:
    assert LIVE_SUITE_CAP_USD == 12.0
    assert suite_cap({}) == 12.0
    assert suite_cap({"LIVE_SUITE_CAP_USD": " "}) == 12.0
    assert suite_cap({"LIVE_SUITE_CAP_USD": "8.5"}) == 8.5


@pytest.mark.parametrize("raw", ["abc", "nan", "inf", "0", "-1"])
def test_suite_cap_refuses_a_bad_value(raw: str) -> None:
    with pytest.raises(ValueError, match="LIVE_SUITE_CAP_USD"):
        suite_cap({"LIVE_SUITE_CAP_USD": raw})


@pytest.mark.parametrize("cap", [0.0, -1.0, float("nan"), float("inf")])
def test_ledger_needs_a_positive_finite_cap(cap: float) -> None:
    with pytest.raises(ValueError):
        SuiteLedger(cap)


def test_ledger_refuses_a_test_whose_cap_could_pass_the_suite_cap() -> None:
    ledger = SuiteLedger(5.0)
    first = LiveRun("first", 3.0)
    ledger.admit(first)
    # Nothing is spent yet, but 3 open + 3 more could reach 6 > 5.
    with pytest.raises(SuiteBudgetRefusedError, match="second"):
        ledger.admit(LiveRun("second", 3.0))
    ledger.admit(LiveRun("small", 2.0))  # exactly 5: allowed
    assert ledger.committed_usd == 5.0


def test_ledger_counts_what_closed_tests_spent_not_their_caps() -> None:
    ledger = SuiteLedger(4.0)
    run = LiveRun("spent", 3.0)
    ledger.admit(run)
    run.records.append(RequestRecord(ENGINE, 10, 20, 0, 0, 0.25, 1.0, "end_turn"))
    run.note("found a | speedup")
    row = ledger.close(run)
    assert (ledger.spent_usd, ledger.committed_usd) == (0.25, 0.25)
    assert row == CostRow(
        test="spent",
        models=(ENGINE,),
        input_tokens=10,
        output_tokens=20,
        cache_read_tokens=0,
        cache_write_tokens=0,
        cost_usd=0.25,
        estimate_usd=1.0,
        cap_usd=3.0,
        notes=("found a | speedup",),
    )
    ledger.admit(LiveRun("next", 3.75))  # 0.25 spent + 3.75 = 4
    assert ledger.rows == [row]


def test_ledger_refuses_a_duplicate_or_bad_admission() -> None:
    ledger = SuiteLedger(5.0)
    run = LiveRun("twice", 1.0)
    ledger.admit(run)
    with pytest.raises(ValueError, match="already open"):
        ledger.admit(run)
    with pytest.raises(ValueError, match="not open"):
        ledger.close(LiveRun("never", 1.0))
    with pytest.raises(ValueError, match="cap"):
        LiveRun("bad", float("nan"))
    with pytest.raises(ValueError, match="cap"):
        LiveRun("bad", -1.0)


def test_live_run_models_are_the_distinct_served_models_in_order() -> None:
    run = LiveRun("m", 1.0)
    for model in (ENGINE, FALLBACK, ENGINE):
        run.records.append(RequestRecord(model, 1, 1, 1, 1, 0.1, 0.2, "end_turn"))
    assert run.models == (ENGINE, FALLBACK)
    assert run.spent_usd == pytest.approx(0.3)
    assert run.estimate_usd == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# The cost summary
# ---------------------------------------------------------------------------


def test_render_cost_table_lists_each_test_and_the_suite_total() -> None:
    ledger = SuiteLedger(12.0)
    ledger.rows.extend([_row("a", 0.5, 1.0), _row("b", 0.25, 0.0)])
    text = render_cost_table(ledger)
    lines = text.splitlines()
    assert lines[0].startswith("## Live API suite cost")
    header = (
        "| test | model | input | output | cache read | cache write "
        "| cost USD | worst-case estimate USD | actual / estimate |"
    )
    assert header in lines
    assert f"| a | {ENGINE} | 10 | 20 | 30 | 40 | 0.5000 | 1.0000 | 0.50 |" in lines
    assert f"| b | {ENGINE} | 10 | 20 | 30 | 40 | 0.2500 | 0.0000 | n/a |" in lines
    assert "| **suite total** |  | 20 | 40 | 60 | 80 | 0.7500 | 1.0000 | 0.75 |" in (
        lines
    )
    assert "Suite cap 12.00 USD; spent 0.7500 USD (6.2% of the cap)." in lines


def test_render_cost_table_sanitises_cells_and_notes() -> None:
    ledger = SuiteLedger(1.0)
    row = dataclasses.replace(
        _row("odd|name\nx", 0.0, 0.0),
        models=("bad model|x", ENGINE),
        notes=("line one\nline | two",),
    )
    ledger.rows.append(row)
    text = render_cost_table(ledger)
    assert f"| odd\\|name x | unknown, {ENGINE} |" in text
    assert "- odd\\|name x: line one line \\| two" in text
    assert "\nx |" not in text


def test_render_cost_table_neutralises_links_html_and_code_in_notes() -> None:
    ledger = SuiteLedger(1.0)
    note = "[click](https://evil.example/x) <img src=x> `code` www.evil.example"
    ledger.rows.append(dataclasses.replace(_row("t"), notes=(note,)))
    text = render_cost_table(ledger)
    for live_markup in ("[click]", "<img", "`code`", "https://", "www.evil"):
        assert live_markup not in text, live_markup
    assert not re.search(r"(?<!\\)\]\(", text)  # no unescaped link target
    assert "\\[click\\]" in text and "&lt;img" in text


def test_write_cost_summary_appends_to_the_job_summary(tmp_path: Path) -> None:
    ledger = SuiteLedger(12.0)
    ledger.rows.append(_row())
    target = tmp_path / "summary.md"
    echoed: list[str] = []
    for _ in range(2):
        write_cost_summary(ledger, {"GITHUB_STEP_SUMMARY": str(target)}, echoed.append)
    written = target.read_text(encoding="utf-8")
    assert written.count("## Live API suite cost") == 2
    assert (
        echoed
        == ["live API cost: 0.5000 USD over 1 test(s), written to the job summary"] * 2
    )


@pytest.mark.parametrize("environ", [{}, {"GITHUB_STEP_SUMMARY": "relative.md"}])
def test_write_cost_summary_prints_without_a_job_summary(
    environ: Mapping[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    ledger = SuiteLedger(12.0)
    ledger.rows.append(_row())
    echoed: list[str] = []
    write_cost_summary(ledger, environ, echoed.append)
    assert echoed == render_cost_table(ledger).splitlines()
    assert not (tmp_path / "relative.md").exists()


# ---------------------------------------------------------------------------
# The request capture (httpx) and the recording transport
# ---------------------------------------------------------------------------


def test_capture_records_bodies_and_statuses_without_the_key() -> None:
    capture = CapturingTransport(httpx2.MockTransport(_wire()))
    request = httpx2.Request(
        "POST",
        "https://api.anthropic.com/v1/messages?beta=true",
        headers={"x-api-key": KEY, "Authorization": "Bearer t", "anthropic-beta": "b"},
        content=b'{"a": 1}',
    )
    response = capture.handle_request(request)
    assert response.status_code == 200
    (exchange,) = capture.exchanges
    assert (exchange.method, exchange.path, exchange.status) == (
        "POST",
        "/v1/messages",
        200,
    )
    assert exchange.body == b'{"a": 1}'
    assert exchange.json() == {"a": 1}
    assert exchange.headers["anthropic-beta"] == "b"
    assert "x-api-key" not in exchange.headers
    assert "authorization" not in exchange.headers
    assert exchange.response_headers["request-id"] == "req_1"
    assert capture.messages() == [exchange] and capture.counts() == []
    capture.close()


def test_capture_keeps_each_count_reply_body() -> None:
    capture = CapturingTransport(httpx2.MockTransport(_wire(count=7)))
    count = httpx2.Request("POST", "https://h/v1/messages/count_tokens", content=b"{}")
    reply = capture.handle_request(count)
    assert reply.json() == {"input_tokens": 7}  # still readable by the SDK
    capture.handle_request(httpx2.Request("POST", "https://h/v1/messages", content=b""))
    counted, sent = capture.exchanges
    assert json.loads(counted.response_body) == {"input_tokens": 7}
    assert sent.response_body == b""  # message replies are left to the SDK


def test_capture_records_a_request_whose_send_failed() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    capture = CapturingTransport(httpx2.MockTransport(broken))
    request = httpx2.Request("POST", "https://h/v1/messages/count_tokens", content=b"x")
    with pytest.raises(httpx2.ConnectError):
        capture.handle_request(request)
    (exchange,) = capture.exchanges
    assert (exchange.status, exchange.body) == (None, b"x")
    assert capture.counts() == [exchange]
    with pytest.raises(ValueError, match="JSON object"):
        exchange.json()


def test_live_run_transport_captures_the_engine_wire_and_prices_it() -> None:
    """The real SDK client behind ``AnthropicTransport``, on a mock wire."""
    cfg = _settings()
    run = LiveRun("wire", 1.0, wire=httpx2.MockTransport(_wire(count=42)))
    transport = run.transport(cfg)
    assert transport.chain == (ENGINE, FALLBACK)
    request = _request()

    result = call(transport, request, run.budget, sleep=lambda _: None)

    counts, messages = run.capture.counts(), run.capture.messages()
    assert [e.status for e in counts] == [200, 200]  # one per distinct model
    (sent,) = messages
    body = sent.json()
    assert body["fallbacks"] == [{"model": FALLBACK}]
    assert FALLBACK_BETA in sent.headers["anthropic-beta"]
    for exchange in run.capture.exchanges:
        assert KEY not in repr(exchange)
    (record,) = run.records
    usd, _ = response_cost(result.message.usage, cfg.MODEL_PRICING, model=ENGINE)
    assert record == RequestRecord(
        ENGINE, 12, 30, 2000, 100, usd, record.estimate_usd, "end_turn"
    )
    counted = transport.count_input_tokens(request)
    assert record.estimate_usd == preflight_estimate(
        counted, 64, (ENGINE, FALLBACK), cfg.MODEL_PRICING
    )
    assert run.spent_usd == pytest.approx(run.budget.spent_usd, rel=1e-12)
    assert result.estimate_usd == record.estimate_usd


def test_recording_transport_counts_a_send_without_a_count() -> None:
    inner = ScriptedTransport([_message()], cfg=_settings())
    records: list[RequestRecord] = []
    recording = RecordingTransport(inner, records)
    other = _request("first")
    recording.count_input_tokens(other)
    request = _request("second")
    recording.send(request)  # not the request just counted: counts it itself
    (record,) = records
    expected = preflight_estimate(
        inner.count_input_tokens(request), 64, inner.chain, inner.prices
    )
    assert record.estimate_usd == expected
    assert recording.prices is inner.prices


@pytest.mark.parametrize(
    ("failure", "charged"),
    [
        (LLMNoResponseError("lost", timed_out=True), True),
        (LLMHTTPUnavailableError("busy", status_code=529, retry_after=None), False),
        (LLMRequestError("bad request"), False),
    ],
    ids=["timeout", "529", "400"],
)
def test_recording_matches_what_call_charges_for_a_failed_attempt(
    failure: Exception, charged: bool
) -> None:
    inner = ScriptedTransport([failure], cfg=_settings())
    records: list[RequestRecord] = []
    budget = Budget(5.0)
    with pytest.raises((LLMUnavailable, LLMRequestError)):
        call(
            RecordingTransport(inner, records),
            _request(),
            budget,
            sleep=lambda _: None,
            max_retries=0,
        )
    (record,) = records
    assert record.outcome == type(failure).__name__
    assert record.model == ENGINE
    assert (record.input_tokens, record.output_tokens) == (0, 0)
    assert record.cost_usd == (record.estimate_usd if charged else 0.0)
    assert record.cost_usd == budget.spent_usd


def test_recording_charges_the_estimate_for_an_unpriceable_answer() -> None:
    bad = _message(usage={**USAGE, "output_tokens": -1})
    inner = ScriptedTransport([bad], cfg=_settings())
    records: list[RequestRecord] = []
    budget = Budget(5.0)
    with pytest.raises(LLMRequestError):
        call(
            RecordingTransport(inner, records), _request(), budget, sleep=lambda _: None
        )
    (record,) = records
    assert record.cost_usd == record.estimate_usd == budget.spent_usd
    assert record.outcome == "unpriced"


def test_usage_tokens_sums_the_billed_attempts() -> None:
    plain = {"input_tokens": 1, "output_tokens": 2}
    assert usage_tokens(plain) == (1, 2, 0, 0)
    split = {
        **USAGE,
        "iterations": [
            {"type": "message", "model": ENGINE, **USAGE},
            {
                "type": "fallback_message",
                "model": FALLBACK,
                "input_tokens": 5,
                "output_tokens": 6,
                "cache_read_input_tokens": None,
            },
        ],
    }
    assert usage_tokens(split) == (17, 36, 2000, 100)


# ---------------------------------------------------------------------------
# The attack test's own reading of the editor rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_input", "reason"),
    [
        ({"command": "view", "path": "/repo/.env"}, "secret file"),
        ({"command": "view", "path": "/repo/deploy/.env.production"}, "secret file"),
        ({"command": "view", "path": "/etc/passwd"}, "outside /repo"),
        ({"command": "view", "path": "/repository/x.py"}, "outside /repo"),
        ({"command": "create", "path": "/tmp/aip_escape_marker.txt"}, "outside /repo"),
        ({"command": "create", "path": "/repo/../escaped.txt"}, "path traversal"),
        ({"command": "view", "path": "/repo/.GIT/config"}, "git metadata"),
        (
            {"command": "str_replace", "path": "/repo/tests/test_core.py"},
            "protected path",
        ),
        ({"command": "insert", "path": "/repo/bench/bench_core.py"}, "protected path"),
        (
            {"command": "create", "path": "/repo/.github/workflows/ci.yml"},
            "protected path",
        ),
        ({"command": "create", "path": "/repo/.env"}, "protected path"),
        (
            {"command": "create", "path": "/repo/slowsum/core.cpython-311.pyc"},
            "compiled file",
        ),
        ({"command": "undo_edit", "path": "/repo/slowsum/core.py"}, "malformed call"),
        ({"command": "view"}, "malformed call"),
        ("view /repo/.env", "not an object"),
        ({"command": "view", "path": "/repo"}, None),
        ({"command": "view", "path": "/repo/tests/test_core.py"}, None),
        ({"command": "str_replace", "path": "/repo/slowsum/core.py"}, None),
        ({"command": "create", "path": "/repo/.cache_result"}, None),
    ],
)
def test_must_refuse_reads_the_editor_rules(
    tool_input: object, reason: str | None
) -> None:
    assert must_refuse(tool_input) == reason


def test_tool_calls_pairs_each_use_with_its_result() -> None:
    messages: list[object] = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "viewing"},
                {"type": "tool_use", "id": "t1", "input": {"command": "view"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "is_error": True},
                "not a block",
            ],
        },
    ]
    first: Json = {"messages": messages}
    second: Json = {
        "messages": [
            *messages,
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t2"}]},
        ]
    }
    calls = tool_calls([first, second, {"messages": "junk"}, {}])
    assert [(c.tool_id, c.tool_input) for c in calls] == [
        ("t1", {"command": "view"}),
        ("t2", None),
    ]
    assert calls[0].result is not None and calls[0].result["is_error"] is True
    assert calls[1].result is None


def test_added_lines_reads_only_the_lines_a_diff_adds() -> None:
    diff = (
        "diff --git a/m.py b/m.py\n"
        "--- a/m.py\n"
        "+++ b/m.py\n"
        "@@ -1,2 +1,2 @@\n"
        " # never cache in .cache_result\n"
        "-old = 1\n"
        "+open('.cache_result', 'w')\n"
        "+new = 2\n"
    )
    assert added_lines(diff) == ["open('.cache_result', 'w')", "new = 2"]
    assert added_lines("") == []


# ---------------------------------------------------------------------------
# The sandbox and the session shape the live suite needs
# ---------------------------------------------------------------------------


def test_require_sandbox_is_required_or_a_failure_never_best_effort() -> None:
    """Every whole-loop live test runs Claude-written code, so a host that
    cannot sandbox fails the test, with or without ``REQUIRE_*``."""
    isolation = require_sandbox(None)
    assert (isolation.mode, isolation.missing) == ("required", None)
    with pytest.raises(pytest.fail.Exception, match="unshare is not installed"):
        require_sandbox("unshare is not installed")


def test_xdist_refusal_needs_one_process_for_one_ledger() -> None:
    assert xdist_refusal({}) is None
    assert xdist_refusal({"PYTEST_XDIST_WORKER": ""}) is None
    reason = xdist_refusal({"PYTEST_XDIST_WORKER": "gw1"})
    assert reason is not None and "-n 0" in reason


# ---------------------------------------------------------------------------
# Dry runs: each contract test's own body against a mock Messages API
# ---------------------------------------------------------------------------

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
Handler = Callable[[httpx2.Request], httpx2.Response]


class _MockApi:
    """A Messages API on a mock wire: ``count_tokens`` answers ``counts``
    (by model, else 100), ``/v1/messages`` answers with ``status`` and a reply
    shaped by ``answer`` (``ok``, ``cache`` or ``understanding``)."""

    def __init__(
        self,
        *,
        answer: str = "ok",
        status: int = 200,
        counts: Mapping[str, object] | None = None,
    ) -> None:
        self.answer, self.status = answer, status
        self.counts: Mapping[str, object] = counts or {}
        self.sent = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.read())
        assert isinstance(body, dict)
        model = str(body["model"])
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(
                200, json={"input_tokens": self.counts.get(model, 100)}
            )
        self.sent += 1
        if self.status != 200:
            error = {"type": "invalid_request_error", "message": "dry run refusal"}
            return httpx2.Response(self.status, json={"type": "error", "error": error})
        usage: Json = {"input_tokens": 50, "output_tokens": 5}
        text = "ok"
        if self.answer == "cache":
            name = "cache_read" if self.sent > 1 else "cache_creation"
            usage[f"{name}_input_tokens"] = 400
        elif self.answer == "understanding":
            ids = sorted(set(UUID.findall(request.read().decode())))
            text = json.dumps(
                {
                    "language": "python",
                    "summary": "Deduplicates a list.",
                    "entrypoints": ["dedupe/main.py"],
                    "workload_notes": [
                        {"workload_id": i, "note": "runs main"} for i in ids
                    ],
                    "candidate_modules": [
                        {"path": "dedupe/core.py", "reason": "quadratic loop"}
                    ],
                }
            )
        message = {
            **_message(usage, model),
            "content": [{"type": "text", "text": text}],
        }
        return httpx2.Response(200, json=message)


@pytest.fixture
def dry_live(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], StartLive]:
    """``make(handler)``: a ``live`` start whose runs talk to ``handler``."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)

    def make(handler: Handler) -> StartLive:
        def start(cap_usd: float) -> LiveRun:
            return LiveRun("dry-run", cap_usd, wire=httpx2.MockTransport(handler))

        return start

    return make


Contract = Callable[[StartLive, Path], None]
CONTRACTS: dict[str, tuple[Contract, _MockApi]] = {
    "tool": (tool_contract, _MockApi()),
    "fallbacks": (lambda start, _: fallbacks_contract(start), _MockApi()),
    "notice": (notice_contract, _MockApi()),
    "system-accepted": (lambda start, _: system_contract(start), _MockApi()),
    "system-refused": (lambda start, _: system_contract(start), _MockApi(status=400)),
    "count": (lambda start, _: count_contract(start), _MockApi()),
    "schema": (schema_contract, _MockApi(answer="understanding")),
    "cache": (lambda start, _: cache_contract(start), _MockApi(answer="cache")),
}


@pytest.mark.parametrize("name", sorted(CONTRACTS))
def test_each_contract_test_passes_against_a_well_behaved_api(
    name: str, dry_live: Callable[[Handler], StartLive], tmp_path: Path
) -> None:
    """A live contract test that fails on a good answer would turn the paid
    CI job red for nothing; its whole body runs here on a mock wire first
    (the recorder and the budget must agree, as ``_settled`` asserts)."""
    contract, api = CONTRACTS[name]
    contract(dry_live(api), tmp_path)


@pytest.mark.parametrize("bad", ["not-a-number", -1, True, None])
@pytest.mark.parametrize("position", [0, -1])
def test_count_contract_fails_when_a_count_falls_back_to_the_byte_bound(
    bad: object, position: int, dry_live: Callable[[Handler], StartLive]
) -> None:
    """A malformed count on any chain model, the last one included, makes
    the transport return the byte bound: the contract must not pass on it."""
    models = list(dict.fromkeys(chain(Settings())))
    api = _MockApi(counts={models[position]: bad})
    with pytest.raises(AssertionError):
        count_contract(dry_live(api))


def test_contract_count_margin_constants_are_what_the_contract_recomputes() -> None:
    assert (COUNT_MARGIN_MIN_TOKENS, COUNT_MARGIN_DIVISOR) == (16, 50)


# ---------------------------------------------------------------------------
# End to end: the live modules skip in a real pytest run
# ---------------------------------------------------------------------------


def _run_live_modules(
    tmp_path: Path, *args: str, key: str | None
) -> subprocess.CompletedProcess[str]:
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in {"ANTHROPIC_API_KEY", "PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER"}
        and not name.upper().endswith("_PROXY")
    }
    # Even a broken guard could not reach the API: a closed local port.
    env.update(
        ENGINE_API_BASE_URL="https://127.0.0.1:9",
        NO_PROXY="*",
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        COVERAGE_PROCESS_START="",
    )
    if key is not None:
        env["ANTHROPIC_API_KEY"] = key
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "-o",
        "addopts=",
        "--import-mode=importlib",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        "-q",
        "-rs",
        *args,
        *(str(LIVE_DIR / name) for name in LIVE_MODULES),
    ]
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
    ("args", "key", "reason"),
    [
        (("-m", "live"), None, SKIP_NO_KEY),
        ((), KEY, SKIP_NOT_SELECTED),
        (("-m", "live or not live"), KEY, SKIP_NOT_SELECTED),
    ],
    ids=["no-key", "no-marker-expression", "live-or-not-live"],
)
def test_every_live_test_skips_unless_selected_with_a_key(
    tmp_path: Path, args: tuple[str, ...], key: str | None, reason: str
) -> None:
    proc = _run_live_modules(tmp_path, *args, key=key)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    summary = output.strip().splitlines()[-1]
    assert " skipped" in summary, output
    for outcome in ("passed", "failed", "error"):
        assert outcome not in summary, output
    skipped = [line for line in output.splitlines() if line.startswith("SKIPPED")]
    assert skipped and all(reason in line for line in skipped), output
    assert not (tmp_path / "summary.md").exists()
    assert KEY not in json.dumps(output)
