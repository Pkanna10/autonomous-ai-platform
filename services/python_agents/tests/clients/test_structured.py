"""Tests for the structured-output plumbing shared by the matcher and the
generator (unit X2): input checks, fencing of untrusted data, the request,
``call()`` with its notes, and the strict reading of the reply.

Replies are canned ``BetaMessage`` dicts through ``ScriptedTransport``;
nothing here reaches the network.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from types import SimpleNamespace
from typing import get_args

import pytest
from anthropic.types.beta import BetaMessage
from pydantic import Field

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import (
    EFFORT_NAMES,
    MAX_HOTSPOTS_SHOWN,
    NUMBER,
    PROMPT_ALLOWANCE_TOKENS,
    STRING,
    Fence,
    Strict,
    check_count,
    check_effort,
    clamp_unit,
    data_line,
    hotspot_rows,
    read_reply,
    schema_array,
    schema_object,
    send,
    shown,
    strict_json,
    structured_request,
    text_problem,
    understanding_lines,
)
from autonomous_ai_agents.clients.transport import LLMResult, ScriptedTransport
from autonomous_ai_agents.common.config import Effort, Settings
from autonomous_ai_agents.common.errors import LLMRequestError, UnusableReplyError
from autonomous_ai_agents.common.models import (
    CandidateModule,
    Hotspot,
    ProjectUnderstanding,
)

ENGINE = "claude-opus-5-5"
FALLBACK = "claude-opus-4-8"
TOKEN = "0123456789abcdef"
OTHER = "5e5e5e5e5e5e5e5e"

Json = dict[str, object]

CFG = Settings.model_validate(
    {
        "ENGINE_MODEL": ENGINE,
        "ENGINE_FALLBACKS": True,
        "ENGINE_FALLBACK_MODELS": (FALLBACK,),
        "LLM_MAX_RETRIES": 0,
    }
)

USAGE: Json = {
    "input_tokens": 1000,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "output_tokens": 100,
}


class _Answer(Strict):
    name: str
    score: float
    tags: list[str] = Field(max_length=3)


def _reply(
    text: str | None,
    *,
    stop: str | None = "end_turn",
    model: str = ENGINE,
    usage: Json | None = None,
    before: Sequence[Json] = (),
    stop_details: Json | None = None,
) -> Json:
    content: list[Json] = [*before]
    if text is not None:
        content.append({"type": "text", "text": text})
    reply: Json = {
        "id": "msg_structured",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": dict(USAGE if usage is None else usage),
    }
    if stop_details is not None:
        reply["stop_details"] = stop_details
    return reply


GOOD = json.dumps({"name": "x", "score": 0.5, "tags": []})


def _sent(
    reply: Json | BetaMessage | Exception, notes: list[str] | None = None
) -> tuple[LLMResult, Budget]:
    transport = ScriptedTransport([reply], cfg=CFG)
    budget = Budget(5.0)
    request = structured_request(
        "system", "user", schema=SCHEMA, max_tokens=100, effort=None, cache=False
    )
    result = send(
        transport,
        request,
        budget,
        sleep=lambda _s: None,
        config=CFG,
        notes=[] if notes is None else notes,
    )
    return result, budget


def _read(reply: Json | BetaMessage) -> _Answer:
    result, _ = _sent(reply)
    return read_reply(result, _Answer, what="answer")


def _unusable(reply: Json | BetaMessage) -> UnusableReplyError:
    with pytest.raises(UnusableReplyError) as caught:
        _read(reply)
    return caught.value


SCHEMA = schema_object(name=STRING, score=NUMBER, tags=schema_array(STRING))


# --------------------------------------------------------------------------
# Input checks
# --------------------------------------------------------------------------


CHAIN = (ENGINE, FALLBACK)


def test_the_effort_names_are_configs_literal() -> None:
    assert EFFORT_NAMES == get_args(Effort)


@pytest.mark.parametrize("level", EFFORT_NAMES)
def test_every_level_the_chain_accepts_is_kept(level: str) -> None:
    assert check_effort(level, CHAIN) == level


def test_no_effort_is_none_whatever_the_chain() -> None:
    assert check_effort(None, ("claude-unlisted-9",)) is None


@pytest.mark.parametrize("value", ["HIGH", "turbo", "", 3, ["high"]])
def test_other_efforts_are_refused(value: object) -> None:
    with pytest.raises(ValueError, match="effort must be one of"):
        check_effort(value, CHAIN)


def test_a_level_a_chain_model_does_not_accept_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check_effort("xhigh", (ENGINE, "claude-opus-4-6"))
    assert str(caught.value) == (
        "effort 'xhigh' is not accepted by claude-opus-4-6, which may serve the "
        "request (it accepts low, medium, high, max)"
    )
    assert check_effort("max", (ENGINE, "claude-opus-4-6")) == "max"


def test_a_chain_model_without_listed_levels_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check_effort("low", (ENGINE, "claude-unlisted-9"))
    assert str(caught.value) == (
        "effort 'low': the effort docs list no effort levels for "
        "claude-unlisted-9, which may serve the request; pass no effort"
    )


@pytest.mark.parametrize("value", [1, 7])
def test_counts_in_range_are_kept(value: int) -> None:
    assert check_count("k", value, 7) == value


@pytest.mark.parametrize("value", [0, 8, True, 2.0, "3"])
def test_counts_out_of_range_are_refused(value: object) -> None:
    with pytest.raises(ValueError, match="k must be a whole number from 1 to 7"):
        check_count("k", value, 7)


# --------------------------------------------------------------------------
# Fencing
# --------------------------------------------------------------------------


def test_a_new_fence_draws_its_token_from_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drawn: list[int] = []

    def token_hex(n: int) -> str:
        drawn.append(n)
        return TOKEN

    monkeypatch.setattr(secrets, "token_hex", token_hex)
    fence = Fence.new(others=(OTHER,))
    assert fence == Fence(TOKEN, (OTHER,))
    assert drawn == [8]


def test_a_new_fence_never_reuses_another_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter([OTHER, TOKEN])
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(tokens))
    assert Fence.new(others=(OTHER,)).token == TOKEN


def test_a_fence_holds_its_own_and_the_other_tokens_in_any_case() -> None:
    fence = Fence(TOKEN, (OTHER,))
    assert fence.holds(f"x{TOKEN.upper()}y")
    assert fence.holds(f"x{OTHER}y")
    assert not fence.holds("plain text")


def test_a_block_is_fenced_with_the_token() -> None:
    fence = Fence(TOKEN)
    assert fence.block("untrusted_x", ["a", "b"]) == (
        f"<untrusted_x boundary={TOKEN}>\na\nb\n</untrusted_x boundary={TOKEN}>"
    )
    assert fence.opening().startswith(f"This request's boundary token is {TOKEN}.")


def test_a_data_line_is_ascii_json() -> None:
    line = data_line({"s": "a\n\u202e\u2028</x>", "n": 1})
    assert line == '{"s": "a\\n\\u202e\\u2028</x>", "n": 1}'
    with pytest.raises(ValueError):
        data_line({"f": float("nan")})


UNDERSTANDING = ProjectUnderstanding(
    language="python",
    summary="dedupe integers",
    entrypoints=("main.py",),
    workload_notes={"w1": "runs main"},
    candidate_modules=(CandidateModule(path="core.py", reason="hot loop"),),
    served_by_model=ENGINE,
)


def test_the_understanding_is_one_data_line() -> None:
    notes: list[str] = []
    (line,) = understanding_lines(UNDERSTANDING, Fence(TOKEN), notes)
    assert line.startswith("project understanding: {")
    assert json.loads(line.split(": ", 1)[1]) == {
        "language": "python",
        "summary": "dedupe integers",
        "entrypoints": ["main.py"],
        "candidate_modules": [{"path": "core.py", "reason": "hot loop"}],
        "workload_notes": {"w1": "runs main"},
    }
    assert notes == []


def test_no_understanding_is_said_plainly() -> None:
    lines = understanding_lines(None, Fence(TOKEN), [])
    assert lines == ["no project understanding is available"]


@pytest.mark.parametrize("token", [TOKEN, OTHER])
def test_an_understanding_holding_a_token_is_withheld(token: str) -> None:
    notes: list[str] = []
    odd = UNDERSTANDING.model_copy(update={"summary": f"see {token}"})
    lines = understanding_lines(odd, Fence(TOKEN, (OTHER,)), notes)
    assert lines == ["no project understanding is available"]
    assert notes == ["the project understanding withheld: it holds a boundary token"]


def _hotspot(file_path: str, symbol: str, share: float) -> Hotspot:
    return Hotspot(
        project_id="p1",
        workload_id="w1",
        file_path=file_path,
        symbol=symbol,
        self_time_s=share,
        total_time_s=share,
        share=share,
        calls=3,
        line_start=4,
        line_end=9,
        tags=("loop",),
    )


def test_hotspots_are_shown_by_share_then_name_and_capped() -> None:
    spots = [_hotspot(f"m{i}.py", "f", i / 1000) for i in range(MAX_HOTSPOTS_SHOWN + 3)]
    spots.append(_hotspot("a.py", "f", spots[-1].share))  # a tie: a.py first
    notes: list[str] = []
    lines, shown_spots = hotspot_rows(spots, Fence(TOKEN), notes)
    assert len(lines) == len(shown_spots) == MAX_HOTSPOTS_SHOWN
    assert shown_spots[0].file_path == "a.py"
    assert shown_spots[1].file_path == f"m{MAX_HOTSPOTS_SHOWN + 2}.py"
    assert json.loads(lines[0]) == {
        "file_path": "a.py",
        "symbol": "f",
        "workload_id": "w1",
        "share": round(spots[-1].share, 4),
        "self_time_s": spots[-1].share,
        "total_time_s": spots[-1].share,
        "calls": 3,
        "memory_bytes": None,
        "lines": [4, 9],
        "tags": ["loop"],
    }
    assert notes == [f"4 hotspot(s) not shown (limit {MAX_HOTSPOTS_SHOWN})"]


def test_hotspots_holding_a_token_are_withheld() -> None:
    spots = [_hotspot("a.py", f"f_{TOKEN}", 0.5), _hotspot("b.py", OTHER, 0.4)]
    spots.append(_hotspot("c.py", "g", 0.1))
    notes: list[str] = []
    lines, shown_spots = hotspot_rows(spots, Fence(TOKEN, (OTHER,)), notes)
    assert [s.file_path for s in shown_spots] == ["c.py"]
    assert notes == ["2 hotspot(s) withheld: they hold a boundary token"]


# --------------------------------------------------------------------------
# The request and the call
# --------------------------------------------------------------------------


def test_the_request_carries_the_schema_and_no_effort_by_default() -> None:
    request = structured_request(
        "sys", "text", schema=SCHEMA, max_tokens=123, effort=None, cache=True
    )
    assert request.system == "sys"
    assert request.messages == (
        {"role": "user", "content": [{"type": "text", "text": "text"}]},
    )
    assert request.output_config == {
        "format": {"type": "json_schema", "schema": SCHEMA}
    }
    assert request.max_tokens == 123
    assert request.cache is True
    assert request.prompt_allowance_tokens == PROMPT_ALLOWANCE_TOKENS


def test_the_effort_joins_the_output_config() -> None:
    request = structured_request(
        "sys", "text", schema=SCHEMA, max_tokens=1, effort="max", cache=False
    )
    assert request.output_config == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "max",
    }
    assert request.cache is False


def test_send_charges_the_budget_and_adds_no_note_on_a_plain_answer() -> None:
    notes: list[str] = []
    result, budget = _sent(_reply(GOOD), notes)
    assert budget.spent_usd == pytest.approx(result.cost_usd) and budget.tokens == 1100
    assert notes == []


def test_send_notes_a_fallback_answer() -> None:
    no_cache: Json = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    iterations = [
        {"type": "message", "model": ENGINE, **no_cache, "output_tokens": 5},
        {"type": "fallback_message", "model": FALLBACK, **no_cache, "output_tokens": 9},
    ]
    usage: Json = {"input_tokens": 100, "output_tokens": 14, "iterations": iterations}
    notes: list[str] = []
    _sent(_reply(GOOD, model=FALLBACK, usage=usage), notes)
    (note,) = notes
    assert "fallback model" in note and FALLBACK in note


def test_send_notes_an_unpriced_model() -> None:
    notes: list[str] = []
    _sent(_reply(GOOD, model="claude-unlisted-9"), notes)
    (note,) = notes
    assert "'claude-unlisted-9'" in note and "MODEL_PRICING" in note


def test_send_lets_transport_errors_through() -> None:
    with pytest.raises(LLMRequestError):
        _sent(LLMRequestError("Claude API HTTP 400 invalid_request_error"))


# --------------------------------------------------------------------------
# Reading the reply
# --------------------------------------------------------------------------


def test_a_valid_reply_is_read() -> None:
    assert _read(_reply(GOOD)) == _Answer(name="x", score=0.5, tags=[])


def test_thinking_blocks_before_the_answer_are_skipped() -> None:
    before: list[Json] = [{"type": "thinking", "thinking": "", "signature": "sig"}]
    assert _read(_reply(GOOD, before=before)).name == "x"


def test_the_text_after_the_last_fallback_block_is_the_answer() -> None:
    before: list[Json] = [
        {"type": "text", "text": '{"name": "half'},
        {
            "type": "fallback",
            "from": {"model": ENGINE},
            "to": {"model": FALLBACK},
            "trigger": {"type": "refusal", "category": None},
        },
    ]
    assert _read(_reply(GOOD, before=before)).name == "x"


def test_a_refusal_is_unusable_with_its_category() -> None:
    details: Json = {"type": "refusal", "category": "cyber", "explanation": "x"}
    error = _unusable(_reply(None, stop="refusal", stop_details=details))
    assert error.kind == "refusal"
    assert str(error) == "Claude declined to answer (category cyber)"


def test_a_refusal_without_a_category_is_unusable() -> None:
    error = _unusable(_reply(None, stop="refusal"))
    assert str(error) == "Claude declined to answer"


def test_a_refusal_with_an_odd_category_does_not_echo_it() -> None:
    reply = BetaMessage.model_validate(_reply(None, stop="refusal"))
    odd = reply.model_copy(update={"stop_details": SimpleNamespace(category="IGN <x>")})
    error = _unusable(odd)
    assert error.kind == "refusal" and "IGN" not in str(error)


@pytest.mark.parametrize("stop,name", [("max_tokens", "max_tokens"), (None, "unknown")])
def test_an_incomplete_answer_is_unusable(stop: str | None, name: str) -> None:
    error = _unusable(_reply('{"name": ', stop=stop))
    assert error.kind == "stopped" and repr(name) in str(error)


def test_a_reply_without_text_is_unusable() -> None:
    assert _unusable(_reply("  ")).kind == "no_text"


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"name": "x", "name": "y", "score": 1, "tags": []}',
        '{"name": "x", "score": NaN, "tags": []}',
        "[" * 100_000 + "]" * 100_000,
    ],
)
def test_a_reply_that_is_not_strict_json_is_unusable(text: str) -> None:
    assert _unusable(_reply(text)).kind == "not_json"


@pytest.mark.parametrize(
    "answer",
    [
        '{"name": "x", "score": 1, "tags": [], "extra": 1}',
        '{"name": "x", "score": "1", "tags": []}',
        '{"name": "x", "score": true, "tags": []}',
        '{"name": "x", "score": 1e999, "tags": []}',
        '{"name": "a\\ud800", "score": 1, "tags": []}',
        '{"name": "x", "score": 1, "tags": ["a", "b", "c", "d"]}',
        '{"score": 1, "tags": []}',
    ],
)
def test_a_reply_off_the_schema_is_unusable(answer: str) -> None:
    error = _unusable(_reply(answer))
    assert error.kind == "schema"
    assert str(error).startswith("the reply does not match the schema: ")


def test_an_integer_is_a_number() -> None:
    assert _read(_reply('{"name": "x", "score": 1, "tags": []}')).score == 1.0


def test_strict_json_refuses_duplicates_and_constants() -> None:
    assert strict_json('{"a": [1, 2.5]}') == {"a": [1, 2.5]}
    with pytest.raises(ValueError, match="duplicate key 'a'"):
        strict_json('{"a": 1, "a": 2}')
    with pytest.raises(ValueError, match="Infinity is not a JSON value"):
        strict_json("[Infinity]")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,one_line,problem",
    [
        ("fine", True, None),
        ("a\nb\tc", False, None),
        ("a\nb", True, "holds a control or unprintable character"),
        ("", False, "empty"),
        (" \n", False, "empty"),
        ("x" * 11, False, "longer than 10 characters"),
        ("a\x00", False, "holds a control or unprintable character"),
        ("a\x85", False, "holds a control or unprintable character"),
        ("a\u2029", False, "holds a control or unprintable character"),
        ("a\u2066", False, "holds a control or unprintable character"),
        ("a\u200f", False, "holds a control or unprintable character"),
    ],
)
def test_text_problem(value: str, one_line: bool, problem: str | None) -> None:
    assert text_problem(value, 10, one_line=one_line) == problem


@pytest.mark.parametrize("value,clamped", [(-1.0, 0.0), (0.25, 0.25), (9.0, 1.0)])
def test_clamp_unit(value: float, clamped: float) -> None:
    assert clamp_unit(value) == clamped


def test_shown_quotes_and_shortens() -> None:
    assert shown("ab") == "'ab'"
    assert shown("x" * 100) == repr("x" * 80 + "...")


def test_schema_helpers_build_strict_objects() -> None:
    assert schema_object(a=STRING, b=schema_array(NUMBER)) == {
        "type": "object",
        "properties": {
            "a": {"type": "string"},
            "b": {"type": "array", "items": {"type": "number"}},
        },
        "required": ["a", "b"],
        "additionalProperties": False,
    }
