"""Live contract checks: the request shapes the engine sends, against the real API.

Spec risk 8 and decision 31 leave these unverified until a live run: the text
editor tool type the editor sends, the explicit server-side ``fallbacks``
body with its beta header, the operator-notice shape inside the editor loop
(a text block after the tool results), ``count_tokens`` against the byte
bound, the understand node's structured-output schema, and prompt caching.
Each check goes through the engine's own code (``ClaudeEditor``,
``ClaudeUnderstander``, ``call()``) on the real ``AnthropicTransport``; the
httpx capture shows exactly what went over the wire and what came back. A
refused request is a failure, never a skip. The ``role: system`` notice is
probed and recorded, not asserted: the engine does not use it (decision 31).

Every test has its own hard ``Budget`` (about 1.4 USD in all) and is admitted
by the suite ledger; usage and cost go into the job summary.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import pytest
from anthropic.types.beta import BetaMessage, BetaMessageParam
from e2e.conftest import DEDUPE_REPO

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.clients.transport import (
    COUNT_MARGIN_DIVISOR,
    COUNT_MARGIN_MIN_TOKENS,
    FALLBACK_BETA,
    LLMRequest,
    LLMTransport,
    ScriptedTransport,
    call,
)
from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.errors import LLMRequestError
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    ModelPrice,
    Project,
    Workload,
)
from autonomous_ai_agents.execution.editor import (
    EDITOR_TOOL,
    EDITOR_TOOL_NAME,
    STOP_ERROR,
    SYSTEM_PROMPT,
    ClaudeEditor,
)
from autonomous_ai_agents.execution.protocols import EditTask, TrialBrief
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.orchestrator.understand import (
    RESPONSE_SCHEMA,
    ClaudeUnderstander,
)

from .conftest import LiveRun, StartLive

pytestmark = pytest.mark.live

TOOL_CAP_USD = 0.25
FALLBACK_CAP_USD = 0.10
NOTICE_CAP_USD = 0.30
SYSTEM_ROLE_CAP_USD = 0.15
COUNT_CAP_USD = 0.0  # count_tokens is free
SCHEMA_CAP_USD = 0.35
# One request's worst case at the byte bound (count_tokens failing) is about
# 0.29 USD; the cap must afford it or the contract proves nothing.
CACHE_CAP_USD = 0.40
VIEW_ID = "toolu_01LiveContractView00000001"
FILES = ("dedupe/__init__.py", "dedupe/core.py", "dedupe/main.py")


def _cfg(**overrides: object) -> Settings:
    """The engine's settings (the key from the environment) plus overrides."""
    return Settings.model_validate(overrides)


def _hypothesis() -> Hypothesis:
    return Hypothesis(
        project_id="live-contract",
        source=HypothesisSource.playbook,
        title="seen-set",
        rationale=(
            "unique_in_order checks membership in the result list for every "
            "item. Start by viewing /repo/dedupe/core.py, then keep a set of "
            "the values already seen so each check is O(1)."
        ),
        change_class=ChangeClass.efficiency,
        expected_gain=0.8,
        provability=0.9,
        risk=0.1,
    )


def _task() -> EditTask:
    brief = TrialBrief(None, (), DEFAULT_PROTECTED_PATTERNS)
    return EditTask(_hypothesis(), brief, secrets.token_hex(8))


def _worktree(base: Path) -> Path:
    tree = base / "wt"
    shutil.copytree(DEDUPE_REPO, tree, ignore=shutil.ignore_patterns("__pycache__"))
    return tree


def _settled(run: LiveRun) -> None:
    """The recorder priced exactly what ``call()`` charged, within the cap."""
    assert run.spent_usd == pytest.approx(run.budget.spent_usd, rel=1e-9, abs=1e-12)
    assert run.budget.spent_usd <= run.cap_usd
    for exchange in run.capture.exchanges:
        assert os.environ["ANTHROPIC_API_KEY"] not in repr(exchange)


def _user(text: str) -> BetaMessageParam:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


class _ScriptedFirst:
    """Replays scripted answers first (free), then sends to the real API."""

    def __init__(self, first: ScriptedTransport, then: LLMTransport) -> None:
        self._first, self._then = first, then

    @property
    def chain(self) -> tuple[str, ...]:
        return self._then.chain

    @property
    def prices(self) -> Mapping[str, ModelPrice]:
        return self._then.prices

    def _current(self) -> LLMTransport:
        return self._first if self._first.remaining else self._then

    def count_input_tokens(self, request: LLMRequest) -> int:
        return self._current().count_input_tokens(request)

    def send(self, request: LLMRequest) -> BetaMessage:
        return self._current().send(request)


def _view_reply(model: str) -> dict[str, object]:
    return {
        "id": "msg_01LiveContractScripted",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [
            {
                "type": "tool_use",
                "id": VIEW_ID,
                "name": EDITOR_TOOL_NAME,
                "input": {"command": "view", "path": "/repo/dedupe/core.py"},
            }
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        # Free: call() prices this scripted turn into the budget while the
        # recorder never sees it, so it must cost 0 for the two to agree.
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _block_types(message: object) -> list[object]:
    assert isinstance(message, Mapping)
    content = message["content"]
    assert isinstance(content, list)
    return [block["type"] for block in content if isinstance(block, Mapping)]


def test_text_editor_tool_type_is_accepted(live: StartLive, tmp_path: Path) -> None:
    """The editor's first request, with its one server-defined tool, gets a
    tool call or an answer back, never a 400 about the tool."""
    run = live(TOOL_CAP_USD)
    cfg = _cfg(EDITOR_MAX_TOKENS=2048, EDITOR_MAX_TURNS=1)
    editor = ClaudeEditor(run.transport(cfg), config=cfg)

    result = editor.edit(_worktree(tmp_path), _task(), run.budget)

    assert result.stop != STOP_ERROR, result.error
    (sent,) = run.capture.messages()
    assert sent.status == 200
    assert sent.json()["tools"] == [EDITOR_TOOL]
    (record,) = run.records
    assert record.outcome in {"tool_use", "end_turn"}
    run.note(f"tool {EDITOR_TOOL['type']} accepted; answer: {record.outcome}")
    _settled(run)


def test_explicit_fallbacks_body_and_beta_header_are_accepted(
    live: StartLive,
) -> None:
    run = live(FALLBACK_CAP_USD)
    cfg = _cfg(ENGINE_FALLBACKS=True)
    assert cfg.ENGINE_FALLBACK_MODELS, "the fallback chain is empty"
    request = LLMRequest(
        system="Answer with one word.",
        messages=(_user("Say ok."),),
        max_tokens=512,
        cache=False,
    )

    result = call(run.transport(cfg), request, run.budget, sleep=time.sleep)

    (sent,) = run.capture.messages()
    assert sent.status == 200
    body = sent.json()
    assert body["model"] == cfg.ENGINE_MODEL
    assert body["fallbacks"] == [{"model": m} for m in cfg.ENGINE_FALLBACK_MODELS]
    betas = [beta.strip() for beta in sent.headers["anthropic-beta"].split(",")]
    assert FALLBACK_BETA in betas
    assert result.served_model in chain(cfg)
    run.note(f"fallbacks {body['fallbacks']} with {FALLBACK_BETA} accepted")
    _settled(run)


def test_operator_notice_after_tool_results_is_accepted(
    live: StartLive, tmp_path: Path
) -> None:
    """Turn 1 is scripted (a view call); the editor then sends its real turn
    2: the tool result followed by its last-turn ``engine_notice`` text."""
    run = live(NOTICE_CAP_USD)
    cfg = _cfg(EDITOR_MAX_TOKENS=2048, EDITOR_MAX_TURNS=2)
    first = ScriptedTransport([_view_reply(cfg.ENGINE_MODEL)], cfg=cfg)
    editor = ClaudeEditor(_ScriptedFirst(first, run.transport(cfg)), config=cfg)

    result = editor.edit(_worktree(tmp_path), _task(), run.budget)

    assert result.stop != STOP_ERROR, result.error
    (sent,) = run.capture.messages()
    assert sent.status == 200
    messages = sent.json()["messages"]
    assert isinstance(messages, list) and len(messages) == 3
    assert _block_types(messages[1]) == ["tool_use"]
    last = messages[-1]
    assert _block_types(last) == ["tool_result", "text"]
    blocks = last["content"]
    assert blocks[0]["tool_use_id"] == VIEW_ID and "is_error" not in blocks[0]
    assert blocks[1]["text"].startswith("<engine_notice nonce=")
    run.note("text-block engine_notice after a tool_result accepted")
    _settled(run)


def test_role_system_notice_is_probed_and_recorded(live: StartLive) -> None:
    """Decision 31: ``role: system`` mid-loop is used only once confirmed.
    The shape is sent for the record; a refusal is noted, not failed."""
    run = live(SYSTEM_ROLE_CAP_USD)
    cfg = _cfg()
    use = _view_reply(cfg.ENGINE_MODEL)["content"]
    messages: Sequence[BetaMessageParam] = (
        _user("Implement a faster unique_in_order in /repo/dedupe/core.py."),
        cast(BetaMessageParam, {"role": "assistant", "content": use}),
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": VIEW_ID,
                    "content": (DEDUPE_REPO / "dedupe" / "core.py").read_text(),
                }
            ],
        },
        cast(
            BetaMessageParam,
            {"role": "system", "content": "Your next answer is the last turn."},
        ),
    )
    request = LLMRequest(
        system=SYSTEM_PROMPT,
        messages=tuple(messages),
        max_tokens=1024,
        tools=(EDITOR_TOOL,),
    )

    try:
        call(run.transport(cfg), request, run.budget, sleep=time.sleep)
        outcome = "accepted"
    except LLMRequestError as exc:
        outcome = f"refused ({exc})"

    (sent,) = run.capture.messages()
    sent_messages = sent.json()["messages"]
    assert isinstance(sent_messages, list) and sent_messages[-1]["role"] == "system"
    run.note(f"role: system after a tool_result: {outcome}, HTTP {sent.status}")
    _settled(run)


def test_count_tokens_works_and_stays_within_the_byte_bound(
    live: StartLive,
) -> None:
    run = live(COUNT_CAP_USD)
    cfg = _cfg()
    request = LLMRequest(
        system=SYSTEM_PROMPT,
        messages=(_user("Make unique_in_order in /repo/dedupe/core.py faster."),),
        max_tokens=cfg.EDITOR_MAX_TOKENS,
        tools=(EDITOR_TOOL,),
    )

    counted = run.transport(cfg).count_input_tokens(request)
    bound = ScriptedTransport([], cfg=cfg).count_input_tokens(request)

    counts = run.capture.counts()
    models = list(dict.fromkeys(chain(cfg)))
    assert [e.json()["model"] for e in counts] == models
    assert [e.status for e in counts] == [200] * len(models)
    # Every reply is a whole count and ``counted`` is the transport's formula
    # over them, so the byte-bound fallback cannot pass for a working count.
    replies = [_whole_count(e.response_body) for e in counts]
    top = max(replies)
    margin = max(COUNT_MARGIN_MIN_TOKENS, -(-top // COUNT_MARGIN_DIVISOR))
    assert counted == top + margin + request.prompt_allowance_tokens
    assert 0 < counted <= bound
    run.note(f"count_tokens {counted} (margin included) vs byte bound {bound}")
    _settled(run)


def _whole_count(body: bytes) -> int:
    reply = json.loads(body)
    assert isinstance(reply, dict), reply
    value = reply.get("input_tokens")
    assert isinstance(value, int) and not isinstance(value, bool), reply
    assert value >= 0, reply
    return value


class _Files:
    """``RepoReader`` over three dedupe files at a made-up commit."""

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        return FILES

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = (DEDUPE_REPO / path).read_bytes()
        return data if limit is None else data[:limit]


def test_understand_schema_is_accepted_and_the_reply_validates(
    live: StartLive, tmp_path: Path
) -> None:
    run = live(SCHEMA_CAP_USD)
    cfg = _cfg(UNDERSTAND_MAX_TOKENS=4000)
    project = Project(name="dedupe", root_path=os.path.realpath(tmp_path))
    workload = Workload(
        project_id=project.id, name="dedupe", command=("python", "-m", "dedupe.main")
    )
    files = _Files()
    understander = ClaudeUnderstander(
        run.transport(cfg), config=cfg, reader=lambda _: files
    )

    result = understander.understand(
        project, [workload], commit="0" * 40, budget=run.budget
    )

    assert result.understanding is not None, result.notes
    (sent,) = run.capture.messages()
    assert sent.status == 200
    output_config = sent.json()["output_config"]
    assert output_config == {
        "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
    }
    understanding = result.understanding
    assert understanding.language == "python"
    assert {m.path for m in understanding.candidate_modules} <= set(FILES)
    assert set(understanding.workload_notes) == {workload.id}
    assert result.cost_usd == pytest.approx(run.spent_usd, rel=1e-9)
    run.note(f"structured output valid; notes: {list(result.notes) or 'none'}")
    _settled(run)


def cache_request() -> LLMRequest:
    """A prompt long enough to cache (the minimum cacheable prompt), cached."""
    reference = (DEDUPE_REPO / "dedupe" / "main.py").read_text(encoding="utf-8")
    text = (
        "Reference material, repeated:\n"
        + "\n".join([reference] * 8)
        + "\nReply with the single word ok."
    )
    return LLMRequest(
        system=SYSTEM_PROMPT, messages=(_user(text),), max_tokens=256, cache=True
    )


def test_prompt_caching_reads_the_cache_on_a_repeat(live: StartLive) -> None:
    run = live(CACHE_CAP_USD)
    cfg = _cfg()
    request = cache_request()
    transport = run.transport(cfg)

    call(transport, request, run.budget, sleep=time.sleep)
    reads: list[int] = []
    for _ in range(2):  # the second repeat only if the first read nothing
        call(transport, request, run.budget, sleep=time.sleep)
        reads.append(run.records[-1].cache_read_tokens)
        if reads[-1] > 0:
            break

    first = run.records[0]
    assert first.cache_write_tokens + first.cache_read_tokens > 0, first
    assert reads[-1] > 0, run.records
    run.note(
        f"cache write {first.cache_write_tokens}, then read {reads} tokens "
        f"({len(run.records)} requests)"
    )
    _settled(run)
