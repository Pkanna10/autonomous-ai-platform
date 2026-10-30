"""A0 (pilot P0, O18): kernel contract probes for Step 3c (pure parts and runners).

Five building blocks the 3c agent kernel relies on, each probed once on our
account with tiny prompts, each check recording what the docs say (with the
URL), what the API did and a verdict (``match``, ``differs``,
``inconclusive``). Nothing here reads a file: every prompt is built from the
constants below (no repository code reaches the API or a hosted agent), and
no paid request offers a tool, a fallback or a top-level ``system``.

Docs relied on (platform.claude.com/docs, as read on 2026-10-26 by the
agents investigation, ``.claude/handoff/step3/research-agents.md`` and its
notes ``api_agent_building_blocks.md`` and ``managed_agents.md``):

- effort: per-message effort is beta ``mid-conversation-output-config-
  2026-07-01`` on Opus 5.5: ``{role: "system", content: [], output_config:
  {effort}}`` (an empty list in every language example) placed directly
  after a user turn applies to that reply; changing the top-level effort
  instead "restarts the cache". A 400 naming ``content`` refuses our shape,
  not the mechanism: inconclusive, the API's message kept in ``observed``.
- prompt-caching: tools, then system, then messages; effort invalidates the
  messages level; reads at 0.05x input on Opus 5.5; 512 tokens is the least
  a 5.x model caches (the filler is also above Opus 4.5's 4,096, in case the
  5.x figure is wrong; a turn 1 that caches nothing makes it inconclusive).
- mid-conversation-system-messages: GA, no header, Opus 5.5 included;
  append a ``role: system`` message instead of editing ``system`` and "the
  cached prefix stays the same".
- token-counting: free; supports client tools and the advisor tool;
  requests with other server tools "return an error".
- preserved-thinking: the API checks every thinking block's ``signature``; a
  block is valid only while ``system``, ``tools`` and earlier messages are
  unchanged; enforced by default for "accounts created on or after August
  31, 2026" (older accounts opt in), so a 200 on the edit is inconclusive.
- managed-agents/environments: "An API create that omits ``networking``
  gets ``unrestricted``" (the Console form defaults to Limited); every
  endpoint needs ``managed-agents-2026-04-01``, which the SDK (1.17) sets.
  The probe sweeps before its create (leftovers of a killed job) and after
  a create that may have committed (no answer, or a 5xx): an environment
  is ours only with both marks, the ``ENV_NAME_PREFIX`` name and
  ``pilot=A0`` metadata, and each one found is deleted and the 404 checked.

The SDK (1.17) has every call: ``betas`` on ``beta.messages.create`` and
``beta.environments`` (create, list, delete, retrieve); no raw request is
needed.
``count_tokens`` with server tools goes through ``client.sdk`` directly,
because the harness strips them (that strip is the fourth count check).
Environments and counts are free; a paid request goes through
``ExperimentClient.messages`` (pre-call worst case against the run's cap).
A reply is resent only when it is at most ``ECHO_MAX_BYTES``, which bounds
every follow-up's worst case (the caps in ``test_agent_probes_live``).
"""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, cast, get_args

import anthropic
from anthropic.types.beta import BetaMessage
from anthropic.types.beta.beta_cloud_config import BetaCloudConfig
from anthropic.types.beta.beta_cloud_config_params import BetaCloudConfigParams
from anthropic.types.beta.beta_environment import BetaEnvironment
from anthropic.types.beta.message_count_tokens_params import MessageCountTokensParams

from autonomous_ai_agents.clients.structured import Fence, data_line
from autonomous_ai_agents.clients.transport import CONFIG_STATUSES
from autonomous_ai_agents.common.errors import BudgetExceeded

from ..conftest import usage_tokens
from .bounds import ExperimentRefusedError, Json
from .harness import ExperimentClient
from .recorder import Metric, excerpt

__all__ = ["Fence"]

PILOT: Final = "A0"
DECISION: Final = (
    "P0 (O18, spec-wave2-ideas 7c) measures whether five building blocks "
    "behave as documented on our account; it feeds the Step 3c agent kernel "
    "design: every probe matches the docs, or the kernel design changes "
    "first. Cheapest arm: Opus 5.5 (the kernel's model) with tiny prompts; "
    "count_tokens and environments are free."
)
OPUS: Final = "claude-opus-5-5"
EFFORT_BETA: Final = "mid-conversation-output-config-2026-07-01"
MANAGED_AGENTS_BETA: Final = "managed-agents-2026-04-01"
_DOCS: Final = "https://platform.claude.com/docs/en/"
DOCS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "effort": _DOCS + "build-with-claude/effort",
        "prompt_caching": _DOCS + "build-with-claude/prompt-caching",
        "system_messages": _DOCS + "build-with-claude/mid-conversation-system-messages",
        "token_counting": _DOCS + "build-with-claude/token-counting",
        "preserved_thinking": _DOCS + "build-with-claude/preserved-thinking",
        "environments": _DOCS + "managed-agents/environments",
    }
)
Verdict = Literal["match", "differs", "inconclusive"]
VERDICTS: Final[tuple[str, ...]] = get_args(Verdict)

SHORT_MAX_TOKENS: Final = 1024  # one-word answers; adaptive thinking included
THINK_MAX_TOKENS: Final = 1024  # the append-only turns, effort high
ECHO_MAX_BYTES: Final = 12_000  # the largest reply resent (signatures included)
FILLER_ITEMS: Final = 360  # about 6,000 tokens: above 512 (5.x) and 4,096 (4.5)
FILLER_MIN_BYTES: Final = 14_000
COLOURS: Final = ("red", "blue", "green", "amber", "violet", "grey", "white")
FIRST_ITEM, SECOND_ITEM, RETRY_ITEM = 17, 101, 42
FIRST_QUESTION: Final = (
    f"In the table above, what colour is item {FIRST_ITEM:03d}? "
    "Answer with one lowercase word."
)
SECOND_QUESTION: Final = f"And item {SECOND_ITEM:03d}? One lowercase word."
CHECKED: Final = "The engine checked your answer."
FEEDBACK_ERROR: Final = "AssertionError: expected one lowercase word, got 'Green.'"
THINK_QUESTION: Final = (
    "How many integers from 1 to 300 are divisible by 4 or by 6, but not by "
    "both? Reply with the number only."
)
THINK_EDITED: Final = THINK_QUESTION.replace("1 to 300", "1 to 360")
THINK_FOLLOW: Final = "Now the same count from 1 to 600. The number only."
SEARCH_TOOL: Final[Json] = {
    "type": "web_search_20260318",
    "name": "web_search",
    "max_uses": 1,
    "allowed_callers": ["direct"],
}
FETCH_TOOL: Final[Json] = {
    "type": "web_fetch_20260318",
    "name": "web_fetch",
    "max_uses": 1,
    "allowed_callers": ["direct"],
}
ENV_NAME_PREFIX: Final = "engine-a0-probe-"
ENV_CONFIG: Final[BetaCloudConfigParams] = {"type": "cloud"}  # no networking
ENV_METADATA: Final = {"pilot": PILOT, "lifetime": "deleted at once"}
DELETE_ATTEMPTS: Final = 2
SWEEP_PAGE_LIMIT: Final = 100
SWEEP_MAX_PAGES: Final = 10
_THOUGHT: Final = ("thinking", "redacted_thinking")
_SIGNATURE: Final = re.compile(r"thinking|signature", re.IGNORECASE)
_SHAPE: Final = re.compile(r"\bcontent\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One documented behaviour: the docs' claim and what the API did."""

    probe: str
    name: str
    doc: str
    expected: str
    observed: str
    verdict: Verdict

    def metrics(self) -> dict[str, Metric]:
        return {
            "verdict": self.verdict,
            "expected": self.expected,
            "observed": self.observed,
            "doc": self.doc,
        }

    def note(self) -> str:
        return excerpt(
            f"{PILOT} {self.probe}/{self.name}: {self.verdict} (expected "
            f"{self.expected}; observed {self.observed}; {self.doc})",
            limit=1000,
        )


@dataclass
class ProbeResult:
    """A probe's checks; ``answered``: the API answered at least one call
    (an HTTP status that is not a key or billing refusal); ``failures``:
    what must fail the live test (an environment left behind)."""

    probe: str
    checks: list[Check] = field(default_factory=list)
    answered: bool = False
    failures: list[str] = field(default_factory=list)
    extra: dict[str, Metric] = field(default_factory=dict)

    @property
    def verdict(self) -> Verdict:
        verdicts = {check.verdict for check in self.checks}
        if "differs" in verdicts:
            return "differs"
        return "match" if verdicts == {"match"} else "inconclusive"

    def metrics(self) -> dict[str, Metric]:
        return {
            "verdict": self.verdict,
            "checks": len(self.checks),
            "answered": self.answered,
            "failures": "; ".join(self.failures) or None,
            **self.extra,
        }


def gate(results: Sequence[ProbeResult]) -> tuple[dict[str, Metric], str]:
    """The pre-registered gate over the probes so far: counts and a note."""
    names: dict[str, list[str]] = {v: [] for v in VERDICTS}
    for result in results:
        names[result.verdict].append(result.probe)
    metrics: dict[str, Metric] = {"probes": len(results)}
    metrics.update({v: len(names[v]) for v in VERDICTS})
    note = f"{PILOT} gate: {len(names['match'])}/{len(results)} probes match"
    if not names["differs"] and not names["inconclusive"]:
        return metrics, note + " the docs"
    if names["differs"]:
        note += f"; differs: {', '.join(names['differs'])}"
    if names["inconclusive"]:
        note += f"; inconclusive: {', '.join(names['inconclusive'])}"
    if names["differs"]:
        note += "; where a probe differs, the 3c kernel design changes first"
    return metrics, note


@dataclass(frozen=True)
class Turn:
    """One call as observed: status (``None``: no answer or not sent)."""

    status: int | None
    outcome: str
    error: str | None = None
    cache_read: int = 0
    cache_write: int = 0
    output_tokens: int = 0
    input_tokens: int = 0

    @property
    def accepted(self) -> bool:
        return self.status == 200

    @property
    def answered(self) -> bool:
        return self.status is not None and self.status not in CONFIG_STATUSES

    @property
    def refused(self) -> bool:
        """A client error that is the API saying no (not the key, not a limit)."""
        status = self.status
        return (
            status is not None
            and 400 <= status < 500
            and status not in CONFIG_STATUSES
            and status != 429
        )

    def observed(self) -> str:
        if self.status is None:
            reason = f": {self.error}" if self.error else ""
            return f"not answered ({self.outcome}{reason})"
        if not self.accepted:
            return f"HTTP {self.status}: {self.error}"
        return (
            f"HTTP 200 ({self.outcome}), cache read {self.cache_read}, cache "
            f"write {self.cache_write}, input {self.input_tokens}, output "
            f"{self.output_tokens}"
        )


def send(client: ExperimentClient, params: Json) -> tuple[Turn, BetaMessage | None]:
    """One paid call through the harness (bounded before it is sent)."""
    try:
        answer = client.messages(params)
    except ExperimentRefusedError as exc:
        return Turn(None, "refused", excerpt(str(exc))), None
    except BudgetExceeded as exc:
        return Turn(None, "unaffordable", excerpt(str(exc))), None
    message = answer.message
    if message is None:
        status = None if answer.status == 200 else answer.status
        return Turn(status, answer.outcome, answer.error), None
    tokens, out, read, write = usage_tokens(message.usage)
    return Turn(200, answer.outcome, None, read, write, out, tokens), message


# ---------------------------------------------------------------------------
# Request shapes (engine-owned text only)
# ---------------------------------------------------------------------------


def item_colour(item: int) -> str:
    return COLOURS[(item * 3) % len(COLOURS)]


def filler() -> str:
    """A deterministic reference table, large enough to be cached."""
    lines = ["Reference table (engine-owned test data):"]
    for i in range(1, FILLER_ITEMS + 1):
        lines.append(
            f"item {i:03d}: colour {item_colour(i)}, weight {(i * 37) % 101} g, "
            f"shelf {chr(65 + i % 26)}{i % 9}"
        )
    return "\n".join(lines)


def user(text: str) -> Json:
    return {"role": "user", "content": text}


def cached_question() -> Json:
    """Turn 1: the table (the one cache breakpoint), then the question."""
    table: Json = {
        "type": "text",
        "text": filler(),
        "cache_control": {"type": "ephemeral"},
    }
    return {
        "role": "user",
        "content": [table, {"type": "text", "text": FIRST_QUESTION}],
    }


def effort_message(effort: str) -> Json:
    """The documented per-message effort message (beta ``EFFORT_BETA``)."""
    return {"role": "system", "content": [], "output_config": {"effort": effort}}


def body(
    messages: Sequence[Json],
    *,
    effort: str,
    max_tokens: int = SHORT_MAX_TOKENS,
    betas: Sequence[str] = (),
) -> Json:
    params: Json = {
        "model": OPUS,
        "max_tokens": max_tokens,
        "output_config": {"effort": effort},
        "messages": list(messages),
    }
    if betas:
        params["betas"] = list(betas)
    return params


def warm_body() -> Json:
    return body([cached_question()], effort="low")


def effort_bodies(echo: Json) -> list[Json]:
    """Turn 2 with per-message effort ``high`` after the user turn (top
    level unchanged), and the control: the same turn with the top-level
    effort changed to ``high`` and no system message."""
    convo = [cached_question(), echo, user(SECOND_QUESTION)]
    per = body([*convo, effort_message("high")], effort="low", betas=[EFFORT_BETA])
    return [per, body(convo, effort="high")]


def feedback_message(fence: Fence) -> Json:
    """Retry feedback as the kernel would send it: the engine's words, and
    the check's raw output fenced as one untrusted data line."""
    line = data_line({"check": "answer_format", "error": FEEDBACK_ERROR})
    if fence.holds(line):  # pragma: no cover - a random token in a constant
        raise ExperimentRefusedError("the feedback holds the fence token")
    text = "\n".join(
        (
            "Engine retry feedback: your previous answer failed a check.",
            fence.opening(),
            fence.block("check_output", [line]),
            f"Answer again: what colour is item {RETRY_ITEM:03d}? One lowercase word.",
        )
    )
    return {"role": "system", "content": text}


def feedback_body(echo: Json, fence: Fence) -> Json:
    convo = [cached_question(), echo, user(CHECKED), feedback_message(fence)]
    return body(convo, effort="low")


def think_body(first: str, echo: Json | None) -> Json:
    """The append-only probe's turns, all at effort ``high``."""
    messages = [user(first)]
    if echo is not None:
        messages += [echo, user(THINK_FOLLOW)]
    return body(messages, effort="high", max_tokens=THINK_MAX_TOKENS)


def edit_bodies(echo: Json) -> list[Json]:
    """The append-only continuation, then the same with turn 1 edited."""
    return [think_body(THINK_QUESTION, echo), think_body(THINK_EDITED, echo)]


def _block(block: object) -> Json:
    if isinstance(block, Mapping):
        return dict(block)
    dump = getattr(block, "model_dump", None)
    if dump is None:
        raise TypeError(f"{type(block).__name__} is not a content block")
    return cast(Json, dump(mode="json", by_alias=True, exclude_none=True))


def echo_of(message: BetaMessage) -> Json | None:
    """The reply resent verbatim, or ``None`` past ``ECHO_MAX_BYTES``."""
    content = [_block(block) for block in message.content]
    if len(json.dumps(content)) > ECHO_MAX_BYTES:
        return None
    return {"role": "assistant", "content": content}


def largest_echo() -> Json:
    """A reply of exactly ``ECHO_MAX_BYTES`` (for the worst-case proof)."""
    base: list[Json] = [
        {"type": "thinking", "thinking": "", "signature": ""},
        {"type": "text", "text": "x"},
    ]
    base[0]["signature"] = "A" * (ECHO_MAX_BYTES - len(json.dumps(base)))
    return {"role": "assistant", "content": base}


def has_thinking(content: Sequence[object]) -> bool:
    for block in content:
        kind = (
            block.get("type")
            if isinstance(block, Mapping)
            else getattr(block, "type", None)
        )
        if kind in _THOUGHT:
            return True
    return False


def reply_text(message: BetaMessage) -> str:
    return " ".join(b.text for b in message.content if b.type == "text")


def count_bodies() -> dict[str, Json]:
    base: Json = {"model": OPUS, "messages": [user("Say ok.")]}
    return {
        "web_search_refused": {**base, "tools": [SEARCH_TOOL]},
        "web_fetch_refused": {**base, "tools": [FETCH_TOOL]},
        "client_only_counted": base,
    }


# ---------------------------------------------------------------------------
# Verdict rules
# ---------------------------------------------------------------------------


def kept(turn: Turn) -> Verdict:
    """Accepted and read the cached prefix; a refusal of the shape differs."""
    if turn.accepted:
        return "match" if turn.cache_read > 0 else "differs"
    return "differs" if turn.refused else "inconclusive"


def effort_kept(turn: Turn) -> Verdict:
    """``kept``, except a 400 naming ``content``: the API refused our
    message's shape, which says nothing about the documented mechanism."""
    if turn.status == 400 and _SHAPE.search(turn.error or ""):
        return "inconclusive"
    return kept(turn)


def restarted(turn: Turn) -> Verdict:
    if turn.accepted:
        return "match" if turn.cache_read == 0 else "differs"
    return "inconclusive"


def accepted(turn: Turn) -> Verdict:
    if turn.accepted:
        return "match"
    return "differs" if turn.refused else "inconclusive"


def edit_refused(turn: Turn, control: Turn) -> Verdict:
    """A 400 naming the thinking signature matches, but only once the same
    conversation unedited (the control) was accepted, so an unrelated 400
    both share never reads as the rule; a 200 may be an older account
    (enforcement is opt-in before 2026-08-31): inconclusive."""
    if not control.accepted:
        return "inconclusive"
    if turn.status == 400 and _SIGNATURE.search(turn.error or ""):
        return "match"
    return "inconclusive"


def count_refused(turn: Turn) -> Verdict:
    if turn.status == 400:
        return "match"
    return "differs" if turn.accepted else "inconclusive"


def _resend(turn: Turn, message: BetaMessage | None, *, cache: bool) -> Json | str:
    """Turn 1's reply to resend, or why the probe cannot go on."""
    if message is None:
        return f"turn 1 {turn.observed()}"
    if cache and not (turn.cache_read or turn.cache_write):
        return f"turn 1 cached nothing ({turn.observed()})"
    echo = echo_of(message)
    if echo is None:
        return "turn 1's reply is over ECHO_MAX_BYTES; not resent"
    return echo


# ---------------------------------------------------------------------------
# The probes
# ---------------------------------------------------------------------------

EXPECT: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "per_message_effort": (
            DOCS["effort"],
            f"HTTP 200 with beta {EFFORT_BETA}, and the cached prefix read "
            "on that turn (cache_read_input_tokens > 0)",
        ),
        "top_level_effort_control": (
            DOCS["prompt_caching"],
            "changing the top-level effort restarts the cache: no read at "
            "the messages-level breakpoint (cache_read_input_tokens == 0)",
        ),
        "system_message_cache": (
            DOCS["system_messages"],
            "a role: system message after a user turn is accepted (GA, no "
            "beta) and the cached prefix stays (cache_read_input_tokens > 0)",
        ),
        "web_search_refused": (
            DOCS["token_counting"],
            "HTTP 400: requests with server tools other than the advisor "
            "return an error (web_search)",
        ),
        "web_fetch_refused": (
            DOCS["token_counting"],
            "HTTP 400: requests with server tools other than the advisor "
            "return an error (web_fetch)",
        ),
        "client_only_counted": (
            DOCS["token_counting"],
            "HTTP 200 with input_tokens > 0 for the same request without server tools",
        ),
        "harness_strips_server_tools": (
            DOCS["token_counting"],
            "the harness's own count (server tools stripped) answers",
        ),
        "append_only_continuation": (
            DOCS["preserved_thinking"],
            "HTTP 200: appending keeps every thinking block valid",
        ),
        "edited_earlier_message": (
            DOCS["preserved_thinking"],
            "HTTP 400 naming the thinking signature once an earlier message "
            "changed (default for accounts created on or after 2026-08-31)",
        ),
        "default_networking": (
            DOCS["environments"],
            "networking.type unrestricted: an API create that omits "
            "networking gets unrestricted",
        ),
        "deleted": (
            DOCS["environments"],
            "delete is acknowledged (environment_deleted, or a bodiless 204 "
            "in the API reference) and a retrieve then returns 404",
        ),
    }
)


def _check(probe: str, name: str, observed: str, verdict: Verdict) -> Check:
    doc, expected = EXPECT[name]
    return Check(probe, name, doc, expected, observed, verdict)


def _stopped(probe: str, names: Sequence[str], reason: str) -> list[Check]:
    return [_check(probe, name, reason, "inconclusive") for name in names]


def probe_effort(client: ExperimentClient) -> ProbeResult:
    """Per-message effort after a cached turn keeps the cache; the top-level
    change (the control) restarts it."""
    probe = "effort_mid_conversation"
    names = ("per_message_effort", "top_level_effort_control")
    warm, first = send(client, warm_body())
    result = ProbeResult(probe, answered=warm.answered)
    echo = _resend(warm, first, cache=True)
    if isinstance(echo, str):
        result.checks = _stopped(probe, names, echo)
        return result
    per_body, control_body = effort_bodies(echo)
    per, _ = send(client, per_body)
    control, _ = send(client, control_body)
    result.answered = result.answered or per.answered or control.answered
    result.checks = [
        _check(probe, names[0], per.observed(), effort_kept(per)),
        _check(probe, names[1], control.observed(), restarted(control)),
    ]
    return result


def probe_feedback(client: ExperimentClient) -> ProbeResult:
    """A system message carrying fenced retry feedback keeps the cache;
    ``followed`` says whether the reply names the retry item's colour."""
    probe, name = "system_feedback", "system_message_cache"
    warm, first = send(client, warm_body())
    result = ProbeResult(probe, answered=warm.answered, extra={"followed": None})
    echo = _resend(warm, first, cache=True)
    if isinstance(echo, str):
        result.checks = _stopped(probe, [name], echo)
        return result
    retry, message = send(client, feedback_body(echo, Fence.new()))
    result.answered = result.answered or retry.answered
    if message is not None:
        word = re.compile(rf"\b{item_colour(RETRY_ITEM)}\b", re.IGNORECASE)
        result.extra["followed"] = bool(word.search(reply_text(message)))
    result.checks = [_check(probe, name, retry.observed(), kept(retry))]
    return result


def probe_append_only(client: ExperimentClient) -> ProbeResult:
    """Append-only continuation accepted; turn 1 edited refused."""
    probe = "append_only"
    names = ("append_only_continuation", "edited_earlier_message")
    first, message = send(client, think_body(THINK_QUESTION, None))
    result = ProbeResult(probe, answered=first.answered)
    if message is not None and first.outcome != "end_turn":
        # cut short (``max_tokens`` inside thinking, say): resending it would
        # test a truncated turn, not the append-only rule
        reason = f"turn 1 stopped with {first.outcome}; not resent"
        result.checks = _stopped(probe, names, reason)
        return result
    if message is not None and not has_thinking(message.content):
        result.checks = _stopped(probe, names, "turn 1 has no thinking block")
        return result
    echo = _resend(first, message, cache=False)
    if isinstance(echo, str):
        result.checks = _stopped(probe, names, echo)
        return result
    control_body, edited_body = edit_bodies(echo)
    control, _ = send(client, control_body)
    edited, _ = send(client, edited_body)
    result.answered = result.answered or control.answered or edited.answered
    result.checks = [
        _check(probe, names[0], control.observed(), accepted(control)),
        _check(probe, names[1], edited.observed(), edit_refused(edited, control)),
    ]
    return result


def _refusal(
    client: ExperimentClient, exc: anthropic.APIStatusError, what: str
) -> Turn:
    """A free call's refusal, with the API's reason from the wire capture."""
    errors = client.run.api_errors()
    return Turn(exc.status_code, what, excerpt(errors[-1] if errors else ""))


def _count(client: ExperimentClient, params: Json) -> Turn:
    """A free ``count_tokens`` with the body as given (server tools kept)."""
    try:
        reply = client.sdk.beta.messages.count_tokens(
            **cast(MessageCountTokensParams, params)
        )
    except anthropic.APIStatusError as exc:
        return _refusal(client, exc, "count_refused")
    except anthropic.APIError as exc:
        return Turn(None, "no_answer", type(exc).__name__)
    return Turn(200, "counted", input_tokens=reply.input_tokens)


def probe_count(client: ExperimentClient) -> ProbeResult:
    """``count_tokens`` refuses web tools; the control and the harness's
    stripped count answer. Nothing paid is sent."""
    probe = "count_web_tools"
    result = ProbeResult(probe)
    turns: list[Turn] = []
    for name, params in count_bodies().items():
        turn = _count(client, params)
        turns.append(turn)
        verdict = count_refused(turn) if name.endswith("_refused") else accepted(turn)
        if verdict == "match" and name == "client_only_counted":
            verdict = "match" if turn.input_tokens > 0 else "differs"
        result.checks.append(_check(probe, name, turn.observed(), verdict))
    stripped = client.count_tokens(count_bodies()["web_search_refused"])
    harness: Verdict = "match" if stripped is not None else "inconclusive"
    if stripped is None and result.checks[-1].verdict == "match":
        harness = "differs"  # the API counts the stripped body, the harness did not
    observed = f"counted {stripped}" if stripped is not None else "no count"
    result.checks.append(
        _check(probe, "harness_strips_server_tools", observed, harness)
    )
    result.answered = any(turn.answered for turn in turns)
    return result


def networking_of(env: BetaEnvironment) -> str:
    config = env.config
    if isinstance(config, BetaCloudConfig):
        return str(config.networking.type)
    return f"{config.type} (no networking)"


def _status(call: Callable[[], object]) -> str:
    """``200`` or the HTTP status of a free call (``no answer`` without one)."""
    try:
        call()
    except anthropic.APIStatusError as exc:
        return str(exc.status_code)
    except anthropic.APIError:
        return "no answer"
    return "200"


def remove(client: ExperimentClient, env_id: str) -> tuple[bool, list[str], str]:
    """Delete (``DELETE_ATTEMPTS`` tries), then retrieve: gone means 404."""
    environments = client.sdk.beta.environments
    tries: list[str] = []
    deleted = False
    for _ in range(DELETE_ATTEMPTS):
        try:
            reply = environments.delete(env_id)
        except anthropic.APIStatusError as exc:
            tries.append(str(exc.status_code))
            continue
        except anthropic.APIError:
            tries.append("no answer")
            continue
        # a 204 has no JSON body: the SDK then returns the text, not a model,
        # so any 2xx is the acknowledgement and the retrieve's 404 the proof
        kind = getattr(reply, "type", None)
        tries.append(str(kind) if kind is not None else "2xx")
        deleted = True
        break
    after = _status(lambda: environments.retrieve(env_id))
    return deleted, tries, after


def _leftover(env_id: str, tries: Sequence[str], after: str) -> str:
    return (
        f"environment {env_id} is not verified deleted (delete "
        f"{', '.join(tries)}, retrieve {after}): delete it by hand"
    )


@dataclass(frozen=True)
class Swept:
    """One sweep: ours deleted (404 verified), ours not verified deleted
    (each a failure line), and why the listing stopped (``None``: listed)."""

    removed: tuple[str, ...] = ()
    survivors: tuple[str, ...] = ()
    unlisted: str | None = None


def is_ours(env: BetaEnvironment) -> bool:
    """Both marks this probe sets: never touch anything else on the account."""
    return env.name.startswith(ENV_NAME_PREFIX) and env.metadata.get("pilot") == PILOT


def _ours(client: ExperimentClient) -> tuple[list[str], str | None]:
    """Every environment of ours, at most ``SWEEP_MAX_PAGES`` pages."""
    found: list[str] = []
    try:
        page = client.sdk.beta.environments.list(limit=SWEEP_PAGE_LIMIT)
        for _ in range(SWEEP_MAX_PAGES):
            found += [env.id for env in page.data if is_ours(env)]
            if not page.has_next_page():
                return found, None
            page = page.get_next_page()
    except anthropic.APIStatusError as exc:
        return found, f"list HTTP {exc.status_code}"
    except anthropic.APIError as exc:
        return found, f"list not answered: {type(exc).__name__}"
    return found, f"more than {SWEEP_MAX_PAGES} pages"


def sweep(client: ExperimentClient) -> Swept:
    """List first, then delete each of ours and verify its 404 (what was
    listed is deleted even when the listing stopped early)."""
    found, unlisted = _ours(client)
    removed: list[str] = []
    survivors: list[str] = []
    for env_id in found:
        _, tries, after = remove(client, env_id)
        if after == "404":
            removed.append(env_id)
        else:
            survivors.append(_leftover(env_id, tries, after))
    return Swept(tuple(removed), tuple(survivors), unlisted)


def _swept(result: ProbeResult, key: str, swept: Swept) -> None:
    result.extra[key] = ", ".join(swept.removed) or "none"
    result.failures.extend(swept.survivors)


def _create_failed(
    client: ExperimentClient, result: ProbeResult, exc: anthropic.APIError
) -> ProbeResult:
    """A refused create (4xx) committed nothing; no answer or a 5xx may have
    committed one, so the probe sweeps, and a sweep that cannot list fails."""
    if isinstance(exc, anthropic.APIStatusError):
        turn = _refusal(client, exc, "create_refused")
        result.answered = turn.answered
        reason, committed = f"create {turn.observed()}", exc.status_code >= 500
    else:
        reason, committed = f"create not answered: {type(exc).__name__}", True
    result.checks = _stopped(result.probe, ENV_CHECKS, reason)
    if committed:
        after = sweep(client)
        _swept(result, "swept_after_create", after)
        if after.unlisted is not None:
            result.failures.append(
                f"{reason}, and the sweep could not list ({after.unlisted}): "
                f"delete any environment named {ENV_NAME_PREFIX}* with "
                f"pilot={PILOT} by hand"
            )
    return result


ENV_CHECKS: Final = ("default_networking", "deleted")


def probe_environment(client: ExperimentClient) -> ProbeResult:
    """A cloud environment created with no ``networking`` reports
    ``unrestricted``; it is deleted at once and the deletion verified. No
    agent or session is ever created, so nothing can run in it."""
    probe, names = "environment_networking", ENV_CHECKS
    result = ProbeResult(probe)
    before = sweep(client)
    _swept(result, "swept", before)
    result.extra["sweep_unlisted"] = before.unlisted
    if before.unlisted is not None:
        client.run.note(f"{PILOT} sweep before the create: {before.unlisted}")
    name = ENV_NAME_PREFIX + secrets.token_hex(4)
    try:
        env = client.sdk.beta.environments.create(
            name=name, config=ENV_CONFIG, metadata=dict(ENV_METADATA)
        )
    except anthropic.APIError as exc:
        return _create_failed(client, result, exc)
    result.answered = True
    try:
        networking = networking_of(env)
    except BaseException:
        _, tries, after = remove(client, env.id)
        if after != "404":  # the exception skips ``failures``: note the id
            client.run.note(f"{PILOT} {_leftover(env.id, tries, after)} ({name})")
        raise
    deleted, tries, after = remove(client, env.id)
    gone, attempts = after == "404", ", ".join(tries)
    result.extra.update(
        environment_id=env.id,
        networking=networking,
        delete=attempts,
        retrieve_after=after,
    )
    default: Verdict = "match" if networking == "unrestricted" else "differs"
    removed: Verdict = "match" if deleted and gone else "differs"
    result.checks = [
        _check(probe, names[0], f"networking.type {networking}", default),
        _check(probe, names[1], f"delete {attempts}; retrieve after {after}", removed),
    ]
    if not gone:
        result.failures.append(f"{_leftover(env.id, tries, after)} ({name})")
    return result


PROBES: Final[Mapping[str, Callable[[ExperimentClient], ProbeResult]]] = (
    MappingProxyType(
        {
            "count_web_tools": probe_count,
            "environment_networking": probe_environment,
            "effort_mid_conversation": probe_effort,
            "system_feedback": probe_feedback,
            "append_only": probe_append_only,
        }
    )
)
