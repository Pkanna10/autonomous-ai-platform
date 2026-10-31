"""Offline guards of A0 (pilot P0, ``test_agent_probes_live.py``): no API call.

Every probe runs here on ``ProbeApi``, a mock wire behind the real
``ExperimentClient`` (the SDK client, the host pin, the capture, the run's
budget and records), so only the wire is a fake. They pin the design: the
caps (each the sum of its requests' worst cases, counted and uncounted, with
the largest reply the probe resends), the shapes each probe sends (Opus 5.5
alone, no tools on a paid request, no fallbacks, the per-message effort
message and its beta, the fenced retry feedback, the one edited message, an
environment created with no ``networking``), the verdict rules (match,
differs, inconclusive) and the account hygiene (every environment deleted
and the deletion verified, or the test fails), and the CI row the Lead adds.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx2
import pytest

from ..conftest import TESTS_DIR, LiveRun
from . import agent_probes as ap
from . import test_agent_probes_live as live_a0
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_harness import KEY, host_key

__all__ = ["host_key"]  # the fixture, imported for its side effect

Json = dict[str, Any]
CI_WORKFLOW = TESTS_DIR.parents[2] / ".github" / "workflows" / "ci.yml"
LIVE_MODULE = Path(live_a0.__file__)
SUITE = "agent-probes"


# ---------------------------------------------------------------------------
# The fake API
# ---------------------------------------------------------------------------


def message(
    *blocks: Json,
    cache_read: int = 0,
    cache_write: int = 0,
    out: int = 40,
    stop: str = "end_turn",
) -> Json:
    return {
        "id": "msg_01A0Probe",
        "type": "message",
        "role": "assistant",
        "model": ap.OPUS,
        "content": list(blocks) or [text("red")],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {
            "input_tokens": 30,
            "output_tokens": out,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
    }


def text(value: str) -> Json:
    return {"type": "text", "text": value}


def thinking(signature: str = "c2lnbmF0dXJl") -> Json:
    return {"type": "thinking", "thinking": "", "signature": signature}


def error(status: int, reason: str = "dry run refusal") -> httpx2.Response:
    body = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": reason},
    }
    return httpx2.Response(status, json=body)


def environment(
    env_id: str, networking: Json, name: str = "x", metadata: Json | None = None
) -> Json:
    packages: dict[str, list[str]] = {
        manager: [] for manager in ("apt", "cargo", "gem", "go", "npm", "pip")
    }
    return {
        "id": env_id,
        "type": "environment",
        "name": name,
        "config": {"type": "cloud", "networking": networking, "packages": packages},
        "metadata": metadata or {},
        "created_at": "2026-10-26T00:00:00Z",
        "updated_at": "2026-10-26T00:00:00Z",
        "archived_at": None,
    }


Scripted = Json | int | tuple[int, str]


class ProbeApi:
    """``count_tokens`` (the documented 400 for server tools), scripted
    ``/v1/messages`` replies in order, and the environment endpoints."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.replies: list[Scripted] = []
        self.count: int | None = 2_000  # None: one token per byte sent
        self.count_status = 200
        self.create_status = 200
        self.networking: Json = {"type": "unrestricted"}
        self.delete_statuses: list[int] = []  # then 200
        self.delete_no_content = False  # True: 204, as the API reference says
        self.after_delete = 404
        self.environments: dict[str, Json] = {}
        self.list_status = 200
        self.create_times_out = False  # stored, then the read times out

    def bodies(self, path: str = "/v1/messages") -> list[Json]:
        return [
            json.loads(r.read())
            for r in self.requests
            if r.url.path == path and r.method == "POST"
        ]

    def sent(self) -> list[httpx2.Request]:
        return [r for r in self.requests if r.url.path == "/v1/messages"]

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if path.endswith("/count_tokens"):
            body = json.loads(request.read())
            tools = body.get("tools", [])
            if any(t.get("type", "custom") != "custom" for t in tools):
                return error(400, "count_tokens does not support server tools")
            if self.count_status != 200:
                return error(self.count_status)
            tokens = len(request.read()) if self.count is None else self.count
            return httpx2.Response(200, json={"input_tokens": tokens})
        if path == "/v1/messages":
            if not self.replies:
                raise AssertionError("an unscripted request was sent")
            reply = self.replies.pop(0)
            if isinstance(reply, int):
                return error(reply)
            if isinstance(reply, tuple):
                return error(*reply)
            return httpx2.Response(200, json=reply)
        if path == "/v1/environments" and method == "GET":
            return self._list(request)
        if path == "/v1/environments" and method == "POST":
            if self.create_status != 200:
                return error(self.create_status)
            body = json.loads(request.read())
            env = environment(
                "env_01A0", self.networking, body["name"], body.get("metadata")
            )
            self.environments[env["id"]] = env
            if self.create_times_out:
                raise httpx2.ReadTimeout("the reply never came", request=request)
            return httpx2.Response(200, json=env)
        if path.startswith("/v1/environments/"):
            env_id = path.rsplit("/", 1)[1]
            if method == "DELETE":
                status = self.delete_statuses.pop(0) if self.delete_statuses else 200
                if status != 200:
                    return error(status)
                self.environments.pop(env_id, None)
                if self.delete_no_content:
                    return httpx2.Response(204)
                return httpx2.Response(
                    200, json={"id": env_id, "type": "environment_deleted"}
                )
            if env_id in self.environments:
                return httpx2.Response(200, json=self.environments[env_id])
            return error(self.after_delete, "environment not found")
        raise AssertionError(f"unexpected request {method} {path}")

    def _list(self, request: httpx2.Request) -> httpx2.Response:
        """A cursor page: ``page`` is an offset, ``next_page`` the next one."""
        if self.list_status != 200:
            return error(self.list_status)
        limit = int(request.url.params["limit"])
        start = int(request.url.params.get("page") or 0)
        items = list(self.environments.values())
        end = start + limit
        next_page = str(end) if end < len(items) else None
        return httpx2.Response(
            200, json={"data": items[start:end], "next_page": next_page}
        )


@pytest.fixture
def api() -> ProbeApi:
    return ProbeApi()


@pytest.fixture
def dry(api: ProbeApi, host_key: str) -> Iterator[Callable[[float], LiveRun]]:
    """A ``live`` start on the fake API; every run stays within its cap."""
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry-{len(runs)}", cap_usd, wire=httpx2.MockTransport(api))
        runs.append(run)
        return run

    yield start
    for run in runs:
        assert run.spent_usd <= run.cap_usd
        assert KEY not in json.dumps(run.notes)


def _client(start: Callable[[float], LiveRun], probe: str) -> ExperimentClient:
    return ExperimentClient(start(live_a0.CAPS[probe]))


def _checks(result: ap.ProbeResult) -> dict[str, ap.Verdict]:
    return {check.name: check.verdict for check in result.checks}


CACHED = 2_000


def _effort_replies() -> list[Scripted]:
    return [
        message(thinking(), text("red"), cache_write=CACHED),
        message(text("amber"), cache_read=CACHED),
        message(text("amber"), cache_write=CACHED),
    ]


# ---------------------------------------------------------------------------
# Caps and the decision (D24): each cap the sum of its worst cases
# ---------------------------------------------------------------------------


def test_the_pilot_cap_holds_every_probe_cap() -> None:
    assert live_a0.A0_CAP_USD == 1.0
    assert list(live_a0.CAPS) == list(ap.PROBES)
    assert math.fsum(live_a0.CAPS.values()) <= live_a0.A0_CAP_USD
    assert live_a0.a0_need() == math.fsum(live_a0.CAPS.values())
    for free in ("count_web_tools", "environment_networking"):
        assert live_a0.CAPS[free] == 0.0, free
    assert "3c" in ap.DECISION and "O18" in ap.DECISION and "feeds" in ap.DECISION


def _worst(client: ExperimentClient, bodies: list[Json]) -> float:
    return math.fsum(client.estimate(body) for body in bodies)


@pytest.mark.parametrize("count_status", [200, 400], ids=["counted", "uncounted"])
def test_each_paid_cap_is_the_sum_of_its_worst_cases(
    count_status: int, api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """With the largest reply a probe resends (``ECHO_MAX_BYTES``), counted
    at the most a body can count (a token per byte sent, plus the harness's
    margin) or not counted at all (the structural bound), every request of
    each paid probe fits its cap, with less than 5 cents to spare."""
    api.count, api.count_status = None, count_status
    client = ExperimentClient(dry(1.0))
    echo = ap.largest_echo()
    assert len(json.dumps(echo["content"])) == ap.ECHO_MAX_BYTES
    fence = ap.Fence.new()
    plans = {
        "effort_mid_conversation": [ap.warm_body(), *ap.effort_bodies(echo)],
        "system_feedback": [ap.warm_body(), ap.feedback_body(echo, fence)],
        "append_only": [ap.think_body(ap.THINK_QUESTION, None), *ap.edit_bodies(echo)],
    }
    for probe, bodies in plans.items():
        worst = _worst(client, bodies)
        cap = live_a0.CAPS[probe]
        assert worst <= cap, (probe, worst, cap)
        assert cap - worst < 0.05, (probe, worst, cap)


def test_a_reply_larger_than_the_echo_bound_is_never_resent(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    big = "x" * ap.ECHO_MAX_BYTES
    api.replies = [message(thinking(big), cache_write=CACHED)]
    result = ap.PROBES["effort_mid_conversation"](
        _client(dry, "effort_mid_conversation")
    )
    assert len(api.sent()) == 1
    assert set(_checks(result).values()) == {"inconclusive"}
    assert "ECHO_MAX_BYTES" in result.checks[0].observed


def test_a_refused_budget_sends_nothing_and_is_inconclusive(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    client = ExperimentClient(dry(0.0001))
    result = ap.PROBES["append_only"](client)
    assert api.sent() == [] and set(_checks(result).values()) == {"inconclusive"}
    assert "unaffordable" in result.checks[0].observed
    assert client.run.records == []


# ---------------------------------------------------------------------------
# Probe 1: per-message effort mid-conversation (cache kept?)
# ---------------------------------------------------------------------------


def test_the_effort_probe_matches_when_the_cache_is_kept_and_the_control_restarts(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.replies = _effort_replies()
    result = ap.PROBES["effort_mid_conversation"](
        _client(dry, "effort_mid_conversation")
    )
    assert _checks(result) == {
        "per_message_effort": "match",
        "top_level_effort_control": "match",
    }
    assert result.verdict == "match" and result.answered and not result.failures
    for check in result.checks:
        assert check.doc.startswith("https://platform.claude.com/docs/en/")
        assert check.expected and check.observed


def test_the_effort_probe_sends_the_documented_shapes(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """Turn 1 at top-level ``low``; turn 2 appends the reply verbatim, a user
    turn and then the per-message effort message (beta header on it alone);
    the control moves effort to the top level, with no system message."""
    api.replies = _effort_replies()
    ap.PROBES["effort_mid_conversation"](_client(dry, "effort_mid_conversation"))
    warm, per, control = api.bodies()
    betas = [r.headers.get("anthropic-beta") for r in api.sent()]
    assert betas == [None, ap.EFFORT_BETA, None]
    assert warm["output_config"] == per["output_config"] == {"effort": "low"}
    assert control["output_config"] == {"effort": "high"}
    assert per["messages"][-1] == {
        "role": "system",
        "content": [],
        "output_config": {"effort": "high"},
    }
    assert per["messages"][-2]["role"] == "user"
    assert per["messages"][1] == {
        "role": "assistant",
        "content": [thinking(), text("red")],
    }
    assert control["messages"] == per["messages"][:-1]
    assert per["messages"][0] == warm["messages"][0] == control["messages"][0]
    first = warm["messages"][0]["content"]
    assert first[0]["cache_control"] == {"type": "ephemeral"}
    assert json.dumps(per).count("cache_control") == 1  # one breakpoint, turn 1


@pytest.mark.parametrize(
    ("replies", "expected"),
    [
        (
            [message(cache_write=CACHED), (400, "unknown field"), message()],
            {"per_message_effort": "differs", "top_level_effort_control": "match"},
        ),
        (
            [
                message(cache_write=CACHED),
                (400, "messages.3.content: Extra inputs are not permitted"),
                message(),
            ],
            {
                "per_message_effort": "inconclusive",
                "top_level_effort_control": "match",
            },
        ),
        (
            [message(cache_write=CACHED), message(), message(cache_read=CACHED)],
            {"per_message_effort": "differs", "top_level_effort_control": "differs"},
        ),
        (
            [message(cache_write=CACHED), 529, 529],
            {
                "per_message_effort": "inconclusive",
                "top_level_effort_control": "inconclusive",
            },
        ),
        (
            [message()],
            {
                "per_message_effort": "inconclusive",
                "top_level_effort_control": "inconclusive",
            },
        ),
        (
            [500],
            {
                "per_message_effort": "inconclusive",
                "top_level_effort_control": "inconclusive",
            },
        ),
    ],
    ids=[
        "refused",
        "shape-error",
        "not-kept",
        "overloaded",
        "nothing-cached",
        "turn-1-failed",
    ],
)
def test_the_effort_verdicts(
    replies: list[Scripted],
    expected: dict[str, str],
    api: ProbeApi,
    dry: Callable[[float], LiveRun],
) -> None:
    api.replies = replies
    result = ap.PROBES["effort_mid_conversation"](
        _client(dry, "effort_mid_conversation")
    )
    assert _checks(result) == expected
    assert api.replies == []  # nothing more was sent than the script holds
    want = "differs" if "differs" in expected.values() else "inconclusive"
    assert result.verdict == want


def test_a_turn_one_cache_read_counts_as_cached(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """An earlier probe may have written the same prefix: a read on turn 1
    proves the prefix is cached too."""
    api.replies = [
        message(cache_read=CACHED),
        message(cache_read=CACHED),
        message(cache_write=CACHED),
    ]
    result = ap.PROBES["effort_mid_conversation"](
        _client(dry, "effort_mid_conversation")
    )
    assert result.verdict == "match"


# ---------------------------------------------------------------------------
# Probe 2: a mid-conversation system message carrying retry feedback
# ---------------------------------------------------------------------------


def test_the_feedback_probe_fences_the_untrusted_error_and_keeps_the_cache(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.replies = [
        message(text("red"), cache_write=CACHED),
        message(text(ap.item_colour(ap.RETRY_ITEM)), cache_read=CACHED),
    ]
    result = ap.PROBES["system_feedback"](_client(dry, "system_feedback"))
    assert _checks(result) == {"system_message_cache": "match"}
    assert result.extra["followed"] is True
    warm, retry = api.bodies()
    assert [r.headers.get("anthropic-beta") for r in api.sent()] == [None, None]
    assert retry["messages"][0] == warm["messages"][0]
    assert retry["output_config"] == warm["output_config"]
    assert [m["role"] for m in retry["messages"]] == [
        "user",
        "assistant",
        "user",
        "system",
    ]
    feedback = retry["messages"][-1]["content"]
    assert isinstance(feedback, str) and "output_config" not in retry["messages"][-1]
    token = re.search(r"boundary token is ([0-9a-f]{16})", feedback)
    assert token is not None
    inside = feedback.split(f"boundary={token.group(1)}>")
    assert len(inside) == 3  # opening and closing tags only
    assert json.dumps(ap.FEEDBACK_ERROR)[1:-1] in inside[1]
    assert ap.FEEDBACK_ERROR not in inside[0] + inside[2]


@pytest.mark.parametrize(
    ("second", "verdict", "followed"),
    [
        (message(text("blue")), "differs", False),
        ((400, "system role not allowed"), "differs", None),
        (529, "inconclusive", None),
    ],
    ids=["not-kept", "refused", "overloaded"],
)
def test_the_feedback_verdicts(
    second: Scripted,
    verdict: str,
    followed: bool | None,
    api: ProbeApi,
    dry: Callable[[float], LiveRun],
) -> None:
    api.replies = [message(cache_write=CACHED), second]
    result = ap.PROBES["system_feedback"](_client(dry, "system_feedback"))
    assert _checks(result) == {"system_message_cache": verdict}
    assert result.extra["followed"] is followed


def test_the_retry_item_answer_differs_from_the_first() -> None:
    colours = {ap.item_colour(i) for i in (ap.FIRST_ITEM, ap.RETRY_ITEM)}
    assert len(colours) == 2 and all(c in ap.filler() for c in colours)


# ---------------------------------------------------------------------------
# Probe 3: count_tokens with web tools (documented to error)
# ---------------------------------------------------------------------------


def test_the_count_probe_matches_the_documented_400_and_spends_nothing(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    client = _client(dry, "count_web_tools")
    result = ap.PROBES["count_web_tools"](client)
    assert _checks(result) == {
        "web_search_refused": "match",
        "web_fetch_refused": "match",
        "client_only_counted": "match",
        "harness_strips_server_tools": "match",
    }
    assert api.sent() == [] and client.run.records == []
    counted = api.bodies("/v1/messages/count_tokens")
    kinds = [[t["type"] for t in body.get("tools", [])] for body in counted]
    assert kinds == [[ap.SEARCH_TOOL["type"]], [ap.FETCH_TOOL["type"]], [], []]
    for tool in (ap.SEARCH_TOOL, ap.FETCH_TOOL):
        assert tool["max_uses"] == 1 and tool["allowed_callers"] == ["direct"]
    assert all(body["model"] == ap.OPUS for body in counted)


def test_the_count_verdicts_when_the_api_counts_server_tools_or_refuses_all(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.count_status = 400
    result = ap.PROBES["count_web_tools"](_client(dry, "count_web_tools"))
    assert _checks(result)["client_only_counted"] == "differs"
    assert _checks(result)["harness_strips_server_tools"] == "inconclusive"
    assert result.answered and result.verdict == "differs"

    def counts_all(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"input_tokens": 50})

    run = LiveRun("dry-all", 0.0, wire=httpx2.MockTransport(counts_all))
    result = ap.PROBES["count_web_tools"](ExperimentClient(run))
    assert _checks(result)["web_search_refused"] == "differs"
    assert _checks(result)["web_fetch_refused"] == "differs"


def test_a_count_with_no_answer_is_not_answered(
    dry: Callable[[float], LiveRun],
) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    run = LiveRun("dry-down", 0.0, wire=httpx2.MockTransport(down))
    result = ap.PROBES["count_web_tools"](ExperimentClient(run))
    assert not result.answered
    assert set(_checks(result).values()) == {"inconclusive"}


# ---------------------------------------------------------------------------
# Probe 4: the append-only rule (preserved thinking)
# ---------------------------------------------------------------------------


def test_the_append_only_probe_edits_exactly_one_earlier_message(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.replies = [
        message(thinking(), text("75")),
        message(thinking("c2Vjb25k"), text("150")),
        (400, "thinking block signature does not match the conversation prefix"),
    ]
    result = ap.PROBES["append_only"](_client(dry, "append_only"))
    assert _checks(result) == {
        "append_only_continuation": "match",
        "edited_earlier_message": "match",
    }
    first, control, edited = api.bodies()
    assert first["messages"] == control["messages"][:1]
    assert control["messages"][1:] == edited["messages"][1:]
    assert control["messages"][1]["content"][0] == thinking()
    assert control["messages"][0] != edited["messages"][0]
    assert edited["messages"][0] == ap.user(ap.THINK_EDITED)
    for body in (first, control, edited):
        assert body["output_config"] == {"effort": "high"}
        assert body["max_tokens"] == ap.THINK_MAX_TOKENS
        assert "system" not in body and "thinking" not in body


@pytest.mark.parametrize(
    ("replies", "expected"),
    [
        (
            [message(text("75"))],
            {
                "append_only_continuation": "inconclusive",
                "edited_earlier_message": "inconclusive",
            },
        ),
        (
            [message(thinking(), text("75")), message(), message()],
            {
                "append_only_continuation": "match",
                "edited_earlier_message": "inconclusive",
            },
        ),
        (
            [message(thinking()), (400, "bad"), (400, "max_tokens too large")],
            {
                "append_only_continuation": "differs",
                "edited_earlier_message": "inconclusive",
            },
        ),
        (  # the same unrelated 400 on both: never a match for the edit
            [
                message(thinking(), text("75")),
                (400, "thinking block signature is malformed"),
                (400, "thinking block signature is malformed"),
            ],
            {
                "append_only_continuation": "differs",
                "edited_earlier_message": "inconclusive",
            },
        ),
        (  # truncated inside thinking: a thinking-only turn is never resent
            [message(thinking(), stop="max_tokens")],
            {
                "append_only_continuation": "inconclusive",
                "edited_earlier_message": "inconclusive",
            },
        ),
    ],
    ids=["no-thinking", "not-enforced", "other-400", "control-refused", "truncated"],
)
def test_the_append_only_verdicts(
    replies: list[Scripted],
    expected: dict[str, str],
    api: ProbeApi,
    dry: Callable[[float], LiveRun],
) -> None:
    api.replies = replies
    result = ap.PROBES["append_only"](_client(dry, "append_only"))
    assert _checks(result) == expected and api.replies == []


def test_a_turn_one_cut_short_says_why_and_sends_nothing_more(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.replies = [message(thinking(), text("7"), stop="max_tokens")]
    result = ap.PROBES["append_only"](_client(dry, "append_only"))
    assert len(api.sent()) == 1 and result.answered
    for check in result.checks:
        assert check.observed == "turn 1 stopped with max_tokens; not resent"


def test_redacted_thinking_counts_as_thinking() -> None:
    reply = message({"type": "redacted_thinking", "data": "eA=="}, text("75"))
    assert ap.has_thinking(reply["content"])
    assert not ap.has_thinking([text("75")])


# ---------------------------------------------------------------------------
# Probe 5: a Managed Agents environment with no networking setting
# ---------------------------------------------------------------------------


def test_the_environment_probe_creates_with_no_networking_and_verifies_deletion(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert _checks(result) == {"default_networking": "match", "deleted": "match"}
    assert not result.failures and result.answered
    (created,) = api.bodies("/v1/environments")
    assert created["config"] == {"type": "cloud"}
    assert "networking" not in json.dumps(created)
    assert re.fullmatch(re.escape(ap.ENV_NAME_PREFIX) + "[0-9a-f]{8}", created["name"])
    calls = [(r.method, r.url.path) for r in api.requests]
    assert calls == [
        ("GET", "/v1/environments"),  # the leftover sweep: nothing to delete
        ("POST", "/v1/environments"),
        ("DELETE", "/v1/environments/env_01A0"),
        ("GET", "/v1/environments/env_01A0"),
    ]
    assert result.extra["swept"] == "none"
    beta = {r.headers.get("anthropic-beta") for r in api.requests}
    assert beta == {ap.MANAGED_AGENTS_BETA}
    assert result.extra["environment_id"] == "env_01A0"
    assert result.extra["delete"] == "environment_deleted"
    assert api.environments == {}


def test_a_failed_delete_is_retried_once(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.delete_statuses = [500, 200]
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert _checks(result)["deleted"] == "match" and not result.failures
    deletes = [r for r in api.requests if r.method == "DELETE"]
    assert len(deletes) == ap.DELETE_ATTEMPTS == 2


def test_a_delete_answered_204_is_acknowledged_and_verified(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """The API reference says ``DELETE`` answers 204 (the SDK then returns
    the empty text, not a model): acknowledged, and the 404 still checked."""
    api.delete_no_content = True
    api.environments["env_dead"] = _ours("env_dead")
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert _checks(result) == {"default_networking": "match", "deleted": "match"}
    assert not result.failures and api.environments == {}
    assert result.extra["swept"] == "env_dead"
    assert result.extra["delete"] == "2xx" and result.extra["retrieve_after"] == "404"


def test_a_reading_failure_with_a_204_delete_keeps_the_original_error(
    api: ProbeApi, dry: Callable[[float], LiveRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(env: object) -> str:
        raise RuntimeError("unreadable")

    monkeypatch.setattr(ap, "networking_of", broken)
    api.delete_no_content = True
    client = _client(dry, "environment_networking")
    with pytest.raises(RuntimeError, match="unreadable"):
        ap.PROBES["environment_networking"](client)
    assert api.environments == {}
    assert not [n for n in client.run.notes if "env_01A0" in n]


@pytest.mark.parametrize(
    ("deletes", "after"), [([500, 500], 404), ([200], 200)], ids=["refused", "still"]
)
def test_an_environment_not_verified_deleted_fails_the_probe(
    deletes: list[int],
    after: int,
    api: ProbeApi,
    dry: Callable[[float], LiveRun],
) -> None:
    api.delete_statuses, api.after_delete = deletes, after
    if after == 200:  # the delete answers but the environment is still there

        def keep(env_id: str) -> None:
            api.environments[env_id] = environment(env_id, api.networking)

        original = api.__call__

        def wire(request: httpx2.Request) -> httpx2.Response:
            response = original(request)
            if request.method == "DELETE":
                keep("env_01A0")
            return response

        run = LiveRun("dry-keep", 0.0, wire=httpx2.MockTransport(wire))
        client = ExperimentClient(run)
    else:
        client = _client(dry, "environment_networking")
    result = ap.PROBES["environment_networking"](client)
    assert _checks(result)["deleted"] == "differs"
    (failure,) = result.failures
    assert "env_01A0" in failure and "by hand" in failure


def test_a_limited_default_differs_and_a_refused_create_leaves_nothing(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.networking = {
        "type": "limited",
        "allowed_hosts": [],
        "allow_package_managers": False,
        "allow_mcp_servers": False,
    }
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert _checks(result) == {"default_networking": "differs", "deleted": "match"}

    refused = ProbeApi()
    refused.create_status = 400
    run = LiveRun("dry-refused", 0.0, wire=httpx2.MockTransport(refused))
    result = ap.PROBES["environment_networking"](ExperimentClient(run))
    assert set(_checks(result).values()) == {"inconclusive"}
    assert result.answered and not result.failures
    assert [r.method for r in refused.requests] == ["GET", "POST"]  # no sweep


def test_a_key_refusal_is_not_an_answer(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.create_status = 401
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert not result.answered
    api.replies = [401]
    result = ap.PROBES["append_only"](_client(dry, "append_only"))
    assert not result.answered


def test_the_environment_is_deleted_even_when_reading_it_fails(
    api: ProbeApi, dry: Callable[[float], LiveRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(env: object) -> str:
        raise RuntimeError("unreadable")

    monkeypatch.setattr(ap, "networking_of", broken)
    with pytest.raises(RuntimeError):
        ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert api.environments == {}
    assert [r.method for r in api.requests][-2:] == ["DELETE", "GET"]


def test_a_reading_failure_with_a_failed_delete_notes_the_leftover(
    api: ProbeApi, dry: Callable[[float], LiveRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exception propagates, so ``failures`` never reaches the test:
    the run's notes carry the environment id instead."""

    def broken(env: object) -> str:
        raise RuntimeError("unreadable")

    monkeypatch.setattr(ap, "networking_of", broken)
    api.delete_statuses = [500, 500]
    client = _client(dry, "environment_networking")
    with pytest.raises(RuntimeError):
        ap.PROBES["environment_networking"](client)
    (note,) = [n for n in client.run.notes if "env_01A0" in n]
    assert "by hand" in note and "500, 500" in note


def _ours(env_id: str, name: str = ap.ENV_NAME_PREFIX + "dead") -> Json:
    return environment(env_id, {"type": "unrestricted"}, name, dict(ap.ENV_METADATA))


def test_a_create_that_timed_out_is_swept_and_its_deletion_verified(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """The server stored the environment but the reply never came: the
    sweep finds it by name and metadata, deletes it and checks the 404."""
    api.create_times_out = True
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert api.environments == {}
    calls = [(r.method, r.url.path) for r in api.requests]
    assert calls == [
        ("GET", "/v1/environments"),
        ("POST", "/v1/environments"),
        ("GET", "/v1/environments"),
        ("DELETE", "/v1/environments/env_01A0"),
        ("GET", "/v1/environments/env_01A0"),
    ]
    assert set(_checks(result).values()) == {"inconclusive"}
    assert "APITimeoutError" in result.checks[0].observed
    assert result.extra["swept_after_create"] == "env_01A0"
    assert not result.failures


def test_a_create_answered_5xx_is_swept_too(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.create_status = 500
    api.environments["env_01A0"] = _ours("env_01A0", ap.ENV_NAME_PREFIX + "0badc0de")
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    assert result.answered and not result.failures
    # the start sweep removed the seeded one, the second sweep found nothing
    assert result.extra["swept"] == "env_01A0"
    assert result.extra["swept_after_create"] == "none"
    assert [r.method for r in api.requests] == ["GET", "DELETE", "GET", "POST", "GET"]


def test_a_leftover_from_a_killed_job_is_deleted_before_the_create(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    """Only an environment with both marks (the name prefix and
    ``pilot=A0``) is ours; anything else on the account is never touched."""
    api.environments["env_dead"] = _ours("env_dead")
    api.environments["env_user"] = environment("env_user", {"type": "limited"})
    api.environments["env_named"] = environment(
        "env_named", {"type": "unrestricted"}, ap.ENV_NAME_PREFIX + "user"
    )
    api.environments["env_tagged"] = environment(
        "env_tagged", {"type": "unrestricted"}, "user", {"pilot": ap.PILOT}
    )
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    calls = [(r.method, r.url.path) for r in api.requests]
    assert calls[:4] == [
        ("GET", "/v1/environments"),
        ("DELETE", "/v1/environments/env_dead"),
        ("GET", "/v1/environments/env_dead"),
        ("POST", "/v1/environments"),
    ]
    assert set(api.environments) == {"env_user", "env_named", "env_tagged"}
    assert result.extra["swept"] == "env_dead"
    assert _checks(result) == {"default_networking": "match", "deleted": "match"}
    assert not result.failures


def test_a_leftover_not_verified_deleted_fails_the_probe_by_id(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.environments["env_dead"] = _ours("env_dead")
    api.delete_statuses = [500, 500]
    result = ap.PROBES["environment_networking"](_client(dry, "environment_networking"))
    (failure,) = result.failures
    assert "env_dead" in failure and "by hand" in failure
    assert _checks(result) == {"default_networking": "match", "deleted": "match"}


def test_the_sweep_follows_every_page_up_to_its_bound(
    api: ProbeApi, dry: Callable[[float], LiveRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ap, "SWEEP_PAGE_LIMIT", 1)
    for i in range(3):
        api.environments[f"env_{i}"] = _ours(f"env_{i}")
    swept = ap.sweep(_client(dry, "environment_networking"))
    assert swept == ap.Swept(removed=("env_0", "env_1", "env_2"))
    lists = [r for r in api.requests if r.url.path == "/v1/environments"]
    assert [r.url.params.get("page") for r in lists] == [None, "1", "2"]

    monkeypatch.setattr(ap, "SWEEP_MAX_PAGES", 2)
    for i in range(3):
        api.environments[f"env_{i}"] = _ours(f"env_{i}")
    swept = ap.sweep(_client(dry, "environment_networking"))
    assert swept.removed == ("env_0", "env_1")  # what was listed is still deleted
    assert swept.unlisted == "more than 2 pages"


@pytest.mark.parametrize(
    ("failure", "unlisted"),
    [("status", "list HTTP 503"), ("timeout", "list not answered: APITimeoutError")],
)
def test_a_sweep_that_cannot_list_says_why(
    failure: str,
    unlisted: str,
    api: ProbeApi,
    dry: Callable[[float], LiveRun],
) -> None:
    """Before the create, a failed list is a note (nothing of this run
    exists yet); after a create that may have committed, it fails the probe."""
    if failure == "status":
        api.list_status = 503
        wire: httpx2.MockTransport = httpx2.MockTransport(api)
    else:

        def wire_fn(request: httpx2.Request) -> httpx2.Response:
            if request.method == "GET" and request.url.path == "/v1/environments":
                raise httpx2.ReadTimeout("no list", request=request)
            return api(request)

        wire = httpx2.MockTransport(wire_fn)
    api.create_times_out = True
    run = LiveRun("dry-unlisted", 0.0, wire=wire)
    result = ap.PROBES["environment_networking"](ExperimentClient(run))
    assert ap.sweep(ExperimentClient(run)).unlisted == unlisted
    assert result.extra["sweep_unlisted"] == unlisted
    assert any(unlisted in note and "before the create" in note for note in run.notes)
    (failure_text,) = result.failures
    assert unlisted in failure_text and ap.ENV_NAME_PREFIX in failure_text
    assert "by hand" in failure_text


# ---------------------------------------------------------------------------
# What every probe may send: Opus 5.5 alone, no tools, engine-owned text
# ---------------------------------------------------------------------------


def test_no_paid_request_offers_a_tool_or_a_fallback(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    api.replies = [
        *_effort_replies(),
        message(cache_write=CACHED),
        message(cache_read=CACHED),
        message(thinking(), text("75")),
        message(),
        (400, "thinking signature"),
    ]
    for name in ("effort_mid_conversation", "system_feedback", "append_only"):
        ap.PROBES[name](_client(dry, name))
    bodies = api.bodies()
    assert len(bodies) == 8 and api.replies == []
    for body in bodies:
        assert body["model"] == ap.OPUS
        assert not {"tools", "tool_choice", "fallbacks", "mcp_servers"} & set(body)
        assert "system" not in body  # instructions travel as messages only


def test_the_probes_read_no_file_and_build_their_text_from_constants() -> None:
    """No pilot sends repository source code (7c): the module opens nothing."""
    source = inspect.getsource(ap)
    for banned in ("open(", "read_text", "read_bytes", "Path(", "os.environ"):
        assert banned not in source, banned
    assert len(ap.filler()) >= ap.FILLER_MIN_BYTES


def test_every_check_names_a_docs_url_and_a_verdict() -> None:
    assert set(ap.VERDICTS) == {"match", "differs", "inconclusive"}
    for url in ap.DOCS.values():
        assert url.startswith("https://platform.claude.com/docs/en/")


# ---------------------------------------------------------------------------
# The live module: records, notes and the gate summary
# ---------------------------------------------------------------------------


def test_the_live_probe_records_every_check_and_the_gate(
    api: ProbeApi, dry: Callable[[float], LiveRun], pytestconfig: pytest.Config
) -> None:
    log = live_a0.A0Log(ExperimentRecorder("A0", {}))
    started: list[LiveRun] = []

    def start(cap: float) -> LiveRun:
        run = dry(cap)
        started.append(run)
        return run

    for name in ("count_web_tools", "environment_networking"):
        live_a0.test_a0_probe(name, start, log)
    assert [run.cap_usd for run in started] == [0.0, 0.0]
    rows = [(r.arm, r.item, r.metrics.get("verdict")) for r in log.recorder.rows]
    assert ("count_web_tools", "web_search_refused", "match") in rows
    assert ("environment_networking", "probe", "match") in rows
    check = next(r for r in log.recorder.rows if r.item == "default_networking")
    assert set(check.metrics) >= {"expected", "observed", "doc", "verdict"}
    notes = started[-1].notes
    assert any(n.startswith("A0 environment_networking/deleted: match") for n in notes)
    assert any(n.startswith("A0 gate: 2/2 probes match") for n in notes)
    live_a0.close_log(log, pytestconfig)
    summary = log.recorder.rows[-1]
    assert (summary.arm, summary.item) == ("summary", "gate")
    assert summary.metrics["match"] == 2 and summary.metrics["probes"] == 2


def test_the_live_probe_fails_on_a_missing_answer_or_a_leftover(
    api: ProbeApi, dry: Callable[[float], LiveRun]
) -> None:
    log = live_a0.A0Log(ExperimentRecorder("A0", {}))
    api.delete_statuses = [500, 500]
    with pytest.raises(AssertionError, match="by hand"):
        live_a0.test_a0_probe("environment_networking", dry, log)
    api.create_status = 403
    with pytest.raises(AssertionError, match="never answered"):
        live_a0.test_a0_probe("environment_networking", dry, log)


def test_the_gate_names_what_differs() -> None:
    def result(name: str, verdict: ap.Verdict) -> ap.ProbeResult:
        check = ap.Check(name, "c", ap.DOCS["effort"], "e", "o", verdict)
        return ap.ProbeResult(name, [check])

    metrics, note = ap.gate([result("a", "match"), result("b", "differs")])
    assert metrics == {"probes": 2, "match": 1, "differs": 1, "inconclusive": 0}
    assert note.startswith("A0 gate: 1/2 probes match; differs: b")
    assert "3c kernel design changes first" in note
    _, note = ap.gate([result("a", "inconclusive")])
    assert "inconclusive: a" in note


def test_the_live_module_admits_each_run_before_any_client() -> None:
    source = LIVE_MODULE.read_text(encoding="utf-8")
    assert re.search(r"^pytestmark = pytest\.mark\.live$", source, re.M)
    tests = re.findall(r"^def (test_\w+)\(([^)]*)\)", source, re.M)
    assert [name for name, _ in tests] == ["test_a0_probe"]
    body = source.split("def run_probe", 1)[1]
    assert body.index("start(CAPS[name])") < body.index("ExperimentClient(")


# ---------------------------------------------------------------------------
# CI: its own suite (the Lead applies the patch; this fails until then)
# ---------------------------------------------------------------------------


def _ci_run_step() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Run live tests")
    return text[start : text.index("      - name: Upload live corpus", start)]


def test_ci_runs_a0_as_its_own_suite_with_room_for_its_cap() -> None:
    """Stage A never collects A0 (the experiments directory is ignored); the
    agent-probes suite runs it alone, its need covering the caps (D24),
    under Step 2's noise rule (A0 starts no engine run)."""
    step = _ci_run_step()
    path = LIVE_MODULE.relative_to(TESTS_DIR.parent).as_posix()
    stage_a = re.search(r"^ *corpus=\((.*)\)$", step, re.MULTILINE)
    assert stage_a is not None
    assert "--ignore=tests/live/experiments" in stage_a.group(1).split()
    suite = re.search(
        rf"^ *{SUITE}\) paths=\({re.escape(path)}\); need=(\d+) ;;$", step, re.M
    )
    assert suite is not None, "apply the A0 ci.yml patch (A0-lead/ci.yml.patch)"
    need = live_a0.a0_need()
    assert need <= int(suite.group(1)) < need + 1
    rule = re.search(rf"^ *(.*\b{SUITE}\b.*)\) noise_rule=(\w+) ;;$", step, re.M)
    assert rule is not None and rule.group(2) == "step2"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    inputs = text[text.index("      suite:") : text.index("      mode:")]
    assert re.search(rf"^ +{SUITE},$", inputs, re.M)
    cap = text[text.index("      suite_cap_usd:") : text.index("      oss_repo:")]
    assert f"{SUITE} {suite.group(1)}" in cap
