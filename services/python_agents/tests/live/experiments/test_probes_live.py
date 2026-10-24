"""E1: compatibility probes for the Window 0 experiments (live, CI only).

Each probe sends one tiny request shape the later experiments depend on and
records what the API said (accepted or rejected, with a capped, redacted
error excerpt) in ``$LIVE_RESULTS_PATH``, the job summary and the cost
table's notes. A probe asserts only that the API answered: an HTTP status
that is not an authentication or billing refusal. The documented behaviour
it checks is named in each docstring; the record, not the assertion, is the
result. All probes together are capped at ``E1_CAP_USD`` (0.50 USD).
"""

from __future__ import annotations

import base64
import math
import os
from collections.abc import Callable, Iterator, Mapping

import pytest

from autonomous_ai_agents.clients.transport import CONFIG_STATUSES, FALLBACK_BETA

from ..conftest import LiveRun, StartLive
from .bounds import ExperimentRefusedError, minimal_pdf
from .harness import Answer, BatchItem, ExperimentAPIError, ExperimentClient
from .recorder import ExperimentRecorder, Metric, excerpt

pytestmark = pytest.mark.live

E1_CAP_USD = 0.50
OPUS, SONNET, HAIKU, FABLE = (
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "claude-haiku-5-5",
    "claude-fable-5-1",
)
OPUS_48 = "claude-opus-4-8"
BATCH_ID = "e1-fallbacks"
BATCH_WAIT_S = 20 * 60
BATCH_POLL_S = 20.0
CAPS: Mapping[str, float] = {
    "models": 0.0,  # GET /v1/models is free
    "citations_format": 0.03,
    "citations_strict_tool": 0.03,
    "pdf_in_tool_result": 0.05,
    "batch_fallbacks": 0.05,
    "web_search_format": 0.25,  # ten server-loop passes (bounds)
    "effort": 0.05,
}
DOCUMENT = "The sky over the harbour is grey. The boats are red."
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
Probe = Callable[[StartLive, ExperimentRecorder], None]


def answered(answer: Answer) -> bool:
    """An HTTP status came back, and it was not a key or billing refusal."""
    return answer.status is not None and answer.status not in CONFIG_STATUSES


def _note(
    run: LiveRun,
    recorder: ExperimentRecorder,
    arm: str,
    model: str,
    answer: Answer,
    **extra: Metric,
) -> None:
    usage = answer.message.usage if answer.message is not None else None
    metrics: dict[str, Metric] = {
        "status": answer.status,
        "accepted": answer.accepted,
        "outcome": answer.outcome,
        "error": answer.error,
        "input_tokens": usage.input_tokens if usage is not None else None,
        "output_tokens": usage.output_tokens if usage is not None else None,
        "cost_usd": answer.cost_usd,
        "estimate_usd": answer.estimate_usd,
        **extra,
    }
    recorder.record("E1", arm, model, metrics)
    verdict = "accepted" if answer.accepted else f"rejected ({answer.error})"
    run.note(f"E1 {arm} on {model}: {verdict}")
    assert answered(answer), (
        f"{arm}: the API never answered: {answer.status} {answer.error}"
    )


def _cited_document() -> dict[str, object]:
    return {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": DOCUMENT},
        "title": "Harbour",
        "citations": {"enabled": True},
    }


def _user(*blocks: object) -> dict[str, object]:
    return {"role": "user", "content": list(blocks)}


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def probe_models(start: StartLive, recorder: ExperimentRecorder) -> None:
    """GET /v1/models/{id} (models API): capabilities, limits and the
    fallbacks each model accepts, for the four models the plan names."""
    run = start(CAPS["models"])
    with ExperimentClient(run, recorder=recorder) as client:
        for model in (OPUS, SONNET, HAIKU, FABLE):
            try:
                info = client.models_get(model)
            except ExperimentAPIError as exc:
                recorder.record(
                    "E1", "models", model, {"status": exc.status, "error": str(exc)}
                )
                run.note(f"E1 models {model}: HTTP {exc.status}")
                assert exc.status is not None and exc.status not in CONFIG_STATUSES, (
                    str(exc)
                )
                continue
            metrics: dict[str, Metric] = {
                "status": 200,
                "max_input_tokens": _number(info.get("max_input_tokens")),
                "max_tokens": _number(info.get("max_tokens")),
                "allowed_fallback_models": ", ".join(
                    str(m) for m in _list(info.get("allowed_fallback_models"))
                ),
            }
            metrics.update(_capabilities(info.get("capabilities")))
            recorder.record("E1", "models", model, metrics)
            run.note(f"E1 models {model}: {len(metrics) - 4} capabilities recorded")


def _number(value: object) -> Metric:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _capabilities(node: object, prefix: str = "cap") -> Iterator[tuple[str, Metric]]:
    """``cap.<name>[.<sub>]`` = supported, two levels deep."""
    if not isinstance(node, Mapping):
        return
    for name, value in sorted(node.items()):
        if not isinstance(value, Mapping):
            continue
        supported = value.get("supported")
        if isinstance(supported, bool):
            yield f"{prefix}.{name}", supported
        elif prefix.count(".") < 1:
            yield from _capabilities(value, f"{prefix}.{name}")


def probe_citations_format(start: StartLive, recorder: ExperimentRecorder) -> None:
    """Citations with ``output_config.format`` (the citations page documents
    a 400 for the pair)."""
    run = start(CAPS["citations_format"])
    with ExperimentClient(run, recorder=recorder) as client:
        answer = client.messages(
            {
                "model": HAIKU,
                "max_tokens": 200,
                "messages": [
                    _user(_cited_document(), _text("What colour are the boats?"))
                ],
                "output_config": {
                    "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}
                },
            }
        )
        _note(run, recorder, "citations_format", HAIKU, answer)


def probe_citations_strict_tool(start: StartLive, recorder: ExperimentRecorder) -> None:
    """Citations beside a ``strict: true`` tool (not documented either way)."""
    run = start(CAPS["citations_strict_tool"])
    tool = {
        "name": "record_answer",
        "description": "Record the answer to the question.",
        "strict": True,
        "input_schema": ANSWER_SCHEMA,
    }
    with ExperimentClient(run, recorder=recorder) as client:
        answer = client.messages(
            {
                "model": HAIKU,
                "max_tokens": 200,
                "tools": [tool],
                "messages": [
                    _user(
                        _cited_document(),
                        _text("Use record_answer to say what colour the sky is."),
                    )
                ],
            }
        )
        kinds = (
            sorted({b.type for b in answer.message.content}) if answer.message else []
        )
        _note(
            run,
            recorder,
            "citations_strict_tool",
            HAIKU,
            answer,
            blocks=", ".join(kinds),
        )


def probe_pdf_in_tool_result(start: StartLive, recorder: ExperimentRecorder) -> None:
    """A base64 PDF ``document`` block inside a ``tool_result`` (tiny PDF
    built in code; whether tool results take documents is the question)."""
    run = start(CAPS["pdf_in_tool_result"])
    data = base64.b64encode(minimal_pdf("The answer is seven.")).decode()
    tool_id = "toolu_01E1ProbePdfToolResult0001"
    tool = {
        "name": "fetch_document",
        "description": "Return the document the user asked about.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }
    pdf = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": data},
    }
    messages = [
        _user(_text("Fetch the document and tell me the number in it.")),
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "fetch_document",
                    "input": {},
                }
            ],
        },
        _user({"type": "tool_result", "tool_use_id": tool_id, "content": [pdf]}),
    ]
    with ExperimentClient(run, recorder=recorder) as client:
        try:
            answer = client.messages(
                {
                    "model": HAIKU,
                    "max_tokens": 200,
                    "tools": [tool],
                    "messages": messages,
                }
            )
        except ExperimentRefusedError as exc:
            # A PDF is sent only once count_tokens sized it; its refusal of
            # the shape is the observation.
            errors = run.api_errors()
            reason = errors[-1] if errors else str(exc)
            metrics: dict[str, Metric] = {"status": None, "accepted": False}
            metrics.update(outcome="count_refused", error=excerpt(reason))
            recorder.record("E1", "pdf_in_tool_result", HAIKU, metrics)
            run.note(f"E1 pdf_in_tool_result on {HAIKU}: count refused ({reason})")
            assert errors, f"pdf_in_tool_result: no count answer: {exc}"
            return
        _note(run, recorder, "pdf_in_tool_result", HAIKU, answer)


def probe_batch_fallbacks(start: StartLive, recorder: ExperimentRecorder) -> None:
    """``fallbacks`` inside a one-request batch (batch-processing documents
    a per-request validation error). The probe needs the batch to be
    created; a batch still running after ``BATCH_WAIT_S`` stays pending with
    its id in the results and is charged its worst case."""
    run = start(CAPS["batch_fallbacks"])
    params: dict[str, object] = {
        "model": OPUS,
        "max_tokens": 64,
        "output_config": {"effort": "low"},
        "fallbacks": [{"model": OPUS_48}],
        "messages": [_user(_text("Say ok."))],
    }
    with ExperimentClient(run, recorder=recorder) as client:
        try:
            batch = client.submit([BatchItem(BATCH_ID, params)], betas=[FALLBACK_BETA])
        except ExperimentAPIError as exc:
            recorder.record(
                "E1", "batch_fallbacks", OPUS, {"status": exc.status, "error": str(exc)}
            )
            run.note(f"E1 batch_fallbacks: batch refused, HTTP {exc.status}")
            assert exc.status is not None and exc.status not in CONFIG_STATUSES, str(
                exc
            )
            return
        status = client.wait(batch, timeout_s=BATCH_WAIT_S, poll_s=BATCH_POLL_S)
        if status != "ended":
            run.note(f"E1 batch_fallbacks: batch {batch.batch_id} still {status}")
            return
        answer = client.results(batch)[BATCH_ID]
        recorder.record(
            "E1",
            "batch_fallbacks",
            OPUS,
            {
                "batch_id": batch.batch_id,
                "outcome": answer.outcome,
                "accepted": answer.accepted,
                "error": answer.error,
                "cost_usd": answer.cost_usd,
            },
        )
        verdict = "accepted" if answer.accepted else f"rejected ({answer.error})"
        run.note(f"E1 batch_fallbacks on {OPUS}: {verdict}")


def probe_web_search_format(start: StartLive, recorder: ExperimentRecorder) -> None:
    """Web search with ``output_config.format`` on Haiku 5.5, in the shape
    the experiments send: ``web_search_20260318`` called directly
    (``allowed_callers: ["direct"]``, no code execution), ``max_uses: 1``."""
    run = start(CAPS["web_search_format"])
    tool = {
        "type": "web_search_20260318",
        "name": "web_search",
        "max_uses": 1,
        "allowed_callers": ["direct"],
    }
    with ExperimentClient(run, recorder=recorder) as client:
        answer = client.messages(
            {
                "model": HAIKU,
                "max_tokens": 200,
                "tools": [tool],
                "messages": [
                    _user(
                        _text("Search the web once: what is the latest Python release?")
                    )
                ],
                "output_config": {
                    "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}
                },
            }
        )
        tool_use = answer.message.usage.server_tool_use if answer.message else None
        searches = tool_use.web_search_requests if tool_use is not None else None
        _note(run, recorder, "web_search_format", HAIKU, answer, searches=searches)


def probe_effort(start: StartLive, recorder: ExperimentRecorder) -> None:
    """``output_config.effort`` ``xhigh`` and ``max`` on Opus 4.8 and
    Haiku 5.5 (the skill lists both levels for both models)."""
    run = start(CAPS["effort"])
    with ExperimentClient(run, recorder=recorder) as client:
        for model in (OPUS_48, HAIKU):
            for effort in ("xhigh", "max"):
                answer = client.messages(
                    {
                        "model": model,
                        "max_tokens": 128,
                        "output_config": {"effort": effort},
                        "messages": [_user(_text("Say ok."))],
                    }
                )
                _note(run, recorder, f"effort_{effort}", model, answer)


PROBES: Mapping[str, Probe] = {
    "models": probe_models,
    "citations_format": probe_citations_format,
    "citations_strict_tool": probe_citations_strict_tool,
    "pdf_in_tool_result": probe_pdf_in_tool_result,
    "batch_fallbacks": probe_batch_fallbacks,
    "web_search_format": probe_web_search_format,
    "effort": probe_effort,
}
assert set(PROBES) == set(CAPS) and math.fsum(CAPS.values()) <= E1_CAP_USD


def finish(recorder: ExperimentRecorder, config: pytest.Config) -> None:
    """The probes' table into the job summary, else the terminal."""
    if recorder.rows:
        reporter = config.pluginmanager.get_plugin("terminalreporter")
        echo: Callable[[str], None] = (
            reporter.write_line if reporter is not None else print
        )
        recorder.finish(echo)


@pytest.fixture(scope="module")
def e1_recorder(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    recorder = ExperimentRecorder("E1 compatibility probes", os.environ)
    yield recorder
    finish(recorder, pytestconfig)


@pytest.mark.parametrize("name", sorted(PROBES))
def test_e1_probe(name: str, live: StartLive, e1_recorder: ExperimentRecorder) -> None:
    PROBES[name](live, e1_recorder)
