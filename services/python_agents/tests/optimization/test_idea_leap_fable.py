"""The leap request on Claude Fable 5.2, on the wire (spec: the Fable leap).

The leap is built through the real path (``IdeaPipelineGenerator`` ->
``call`` -> ``AnthropicTransport.send``, the transport built from
``role_settings(cfg, "leap")`` as the factory builds it) and answered by a
fake wire (``httpx2.MockTransport``): no model is called. The lane and
reviewer roles run on ``ScriptedTransport``; the reviewer is off, so the
leap's request and reply are the only ones the wire sees besides its counts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

import httpx2
import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import (
    FALLBACK_BETA,
    AnthropicTransport,
    ScriptedTransport,
)
from autonomous_ai_agents.common.config import Settings, role_settings
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
)
from autonomous_ai_agents.common.repo_read import RepoReader
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane
from autonomous_ai_agents.optimization.sources import GenerateResult

KEY = "sk-ant-api03-FABLELEAP-0c1d2e3f"
FABLE_5_2, OPUS_4_8 = "claude-fable-5-2", "claude-opus-4-8"
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"
SHA = "0123456789abcdef0123456789abcdef01234567"
PATH = "pkg/text.py"
SOURCE = '''"""Text tools."""


def count_words(text):
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    return counts
'''
PROJECT = Project(id="p1", name="texttools", root_path="/srv/texttools")
OBJECTIVE = Objective(
    project_id="p1",
    kind=ObjectiveKind.runtime,
    metric="wall_time_s",
    direction=Direction.minimize,
    min_relative_gain=0.05,
    description="make the text tools faster",
)
HOTSPOT = Hotspot(
    project_id="p1", workload_id="w1", file_path=PATH, symbol="count_words",
    self_time_s=1.0, total_time_s=2.0, share=0.5,
)  # fmt: skip
FORBIDDEN = ("thinking", "tool_choice", "temperature", "top_p", "top_k")


class _Reader:
    def ls_tree(self, commit: str) -> tuple[str, ...]:
        assert commit == SHA
        return (PATH,)

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = SOURCE.encode()
        return data if limit is None else data[:limit]


def _reader(_project: Project) -> RepoReader:
    return _Reader()


def _message(
    text: str,
    *,
    model: str,
    stop: str = "end_turn",
    details: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": "msg_1", "type": "message", "role": "assistant", "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop, "stop_sequence": None, "stop_details": details,
        "usage": {"input_tokens": 3000, "output_tokens": 900},
    }  # fmt: skip


NO_IDEAS = json.dumps({"hypotheses": []})


class _Wire:
    """Counts answer 2,000 tokens; the one message request gets ``reply``."""

    def __init__(self, reply: Mapping[str, object]) -> None:
        self.reply = reply
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 2000})
        return httpx2.Response(200, json=dict(self.reply))

    @property
    def sent(self) -> list[httpx2.Request]:
        return [r for r in self.requests if not r.url.path.endswith("/count_tokens")]


def _cfg(**values: object) -> Settings:
    base: dict[str, object] = {
        "ANTHROPIC_API_KEY": KEY, "IDEA_PIPELINE": True, "IDEAS_REVIEW": False,
        "IDEAS_LANE_WORKERS": 1, "LLM_MAX_RETRIES": 0, "LLM_TIMEOUT_S": 300.0,
    }  # fmt: skip
    return Settings.model_validate({**base, **values})


def _fable() -> Settings:
    return _cfg(IDEAS_LEAP_MODEL=FABLE_5_2, ALLOW_RETENTION_MODELS=True)


def _run(cfg: Settings, wire: _Wire) -> GenerateResult:
    lanes = [_message(NO_IDEAS, model=SONNET) for _ in range(1 + len(LENS_LANES))]
    leap = AnthropicTransport(
        role_settings(cfg, "leap"), http_transport=httpx2.MockTransport(wire)
    )
    generator = IdeaPipelineGenerator(
        {
            "lane": ScriptedTransport(lanes, cfg=role_settings(cfg, "lane")),
            "leap": leap,
            "reviewer": ScriptedTransport([], cfg=role_settings(cfg, "reviewer")),
        },
        reader=_reader,
        config=cfg,
        sleep=lambda _s: None,
    )
    return generator.generate(
        project=PROJECT, understanding=None, hotspots=(HOTSPOT,),
        objective=OBJECTIVE, techniques=(), lessons=(), avoid_titles=(), n=3,
        budget=Budget(50.0), commit=SHA, run_id="run-1",
    )  # fmt: skip


def _body(request: httpx2.Request) -> dict[str, object]:
    loaded = json.loads(request.content)
    assert isinstance(loaded, dict)
    return loaded


def test_the_fable_5_2_leap_request_has_the_fable_shape() -> None:
    """
    GIVEN IDEAS_LEAP_MODEL=claude-fable-5-2 (retention flag set)
    WHEN the pipeline sends its leap through the real transport
    THEN the body names Fable 5.2 with the explicit fallback array naming
         only Opus 4.8 under the existing beta, effort high, 32,000 output
         tokens, no thinking, tool_choice or sampling parameter, and the
         request carries X1-1's 951 s timeout (connect 10 s)
    """
    wire = _Wire(_message(NO_IDEAS, model=FABLE_5_2))
    result = _run(_fable(), wire)

    assert len(wire.sent) == 1
    sent = wire.sent[0]
    body = _body(sent)
    assert body["model"] == FABLE_5_2
    for key in FORBIDDEN:
        assert key not in body, key
    assert body["fallbacks"] == [{"model": OPUS_4_8}]
    assert sent.headers["anthropic-beta"] == FALLBACK_BETA
    output_config = body["output_config"]
    assert isinstance(output_config, dict)
    assert output_config["effort"] == "high"
    assert output_config["format"]["type"] == "json_schema"
    assert body["max_tokens"] == 32_000
    assert sent.extensions["timeout"] == {
        "connect": 10.0, "read": 951.0, "write": 951.0, "pool": 951.0,
    }  # fmt: skip
    counted = [_body(r)["model"] for r in wire.requests if r not in wire.sent]
    assert counted == [FABLE_5_2, OPUS_4_8]  # each model of the chain, once
    assert result.stats is not None
    assert result.stats.stop_reasons[Lane.leap.value] == "end_turn"


def test_a_refused_leap_records_the_refusal_and_never_reads_its_text() -> None:
    """
    GIVEN the Fable 5.2 leap answered with stop_reason refusal, and text
          that is not JSON (read as content, it would fail as not_json)
    WHEN the pipeline reads the leap's reply
    THEN the refusal is recorded (stop reason, a refusal note naming its
         category) and no idea, text or JSON failure comes from it
    """
    details = {"type": "refusal", "category": "cyber", "explanation": "declined"}
    reply = _message("{not json", model=FABLE_5_2, stop="refusal", details=details)
    result = _run(_fable(), _Wire(reply))

    assert result.stats is not None
    assert result.stats.stop_reasons[Lane.leap.value] == "refusal"
    assert result.stats.ideas_per_lane[Lane.leap] == 0
    leap_notes = [n for n in result.notes if n.startswith("lane leap")]
    assert leap_notes == [
        "lane leap failed (UnusableReplyError): Claude declined to write ideas "
        "for the leap lane (category cyber)"
    ]
    assert not any("not strict JSON" in n or "schema" in n for n in result.notes)


@pytest.mark.parametrize(("model", "fallbacks"), [(OPUS, False), (OPUS, True)])
def test_the_default_opus_leap_request_is_unchanged(
    model: str, fallbacks: bool
) -> None:
    """
    GIVEN the default leap (Opus 5.5), with the engine's fallbacks on or off
    WHEN the pipeline sends it
    THEN it goes out as before: Opus 5.5 alone (no fallbacks, no beta),
         effort high, IDEAS_LEAP_MAX_TOKENS, the run's 300 s timeout
    """
    wire = _Wire(_message(NO_IDEAS, model=model))
    _run(_cfg(ENGINE_FALLBACKS=fallbacks), wire)

    (sent,) = wire.sent
    body = _body(sent)
    assert body["model"] == model
    assert "fallbacks" not in body and "anthropic-beta" not in sent.headers
    output_config = body["output_config"]
    assert isinstance(output_config, dict)
    assert (output_config["effort"], body["max_tokens"]) == ("high", 12_000)
    assert sent.extensions["timeout"]["read"] == 300.0
