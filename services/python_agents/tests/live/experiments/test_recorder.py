"""Offline tests of the experiments' recorder and of the key redaction both
it and the suite's cost-table notes use (``recorder.py``, ``conftest.py``)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import cast

import httpx2
import pytest

from .. import conftest as live_conftest
from ..conftest import LiveRun, redact_keys
from .recorder import ExperimentRecorder, Metric, excerpt

KEY = "sk-ant-api03-RECORDER-0123456789abcdef"


def test_redact_keys_removes_given_secrets_the_host_key_and_key_shapes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(live_conftest, "HOST_KEY", "host-secret-value")
    text = f"a {KEY} b host-secret-value c s3cr3t d sk-ant-admin01-zzzzzzzz"
    clean = redact_keys(text, ("s3cr3t", ""))
    for secret in (KEY, "host-secret-value", "s3cr3t", "sk-ant-admin01"):
        assert secret not in clean
    assert clean.count("[redacted]") == 4
    monkeypatch.setattr(live_conftest, "HOST_KEY", None)
    assert redact_keys("plain") == "plain"


def test_an_api_error_echoing_a_key_reaches_the_cost_notes_redacted() -> None:
    """Review item 12: ``run.api_errors()`` feeds the cost-table notes."""
    long_tail = "x" * 290

    def refuse(request: httpx2.Request) -> httpx2.Response:
        message = f"{long_tail} {KEY} rejected"
        error = {"type": "invalid_request_error", "message": message}
        return httpx2.Response(400, json={"type": "error", "error": error})

    run = LiveRun("redact", 0.0, wire=httpx2.MockTransport(refuse))
    with httpx2.Client(transport=run.capture) as client:
        client.post("https://api.anthropic.com/v1/messages", json={})
    (error,) = run.api_errors()
    assert error.startswith("HTTP 400 /v1/messages: invalid_request_error: ")
    assert KEY not in error and "sk-ant-api03" not in error
    assert len(error) <= len("HTTP 400 /v1/messages: invalid_request_error: ") + 300


def test_the_recorder_refuses_a_results_path_it_cannot_write(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        ExperimentRecorder("E", {"LIVE_RESULTS_PATH": "relative.jsonl"})
    with pytest.raises(ValueError, match="directory"):
        ExperimentRecorder("E", {"LIVE_RESULTS_PATH": str(tmp_path / "no" / "r.jsonl")})


def test_the_recorder_writes_json_lines_and_a_sanitised_summary(tmp_path: Path) -> None:
    results, summary = tmp_path / "r.jsonl", tmp_path / "s.md"
    environ = {"LIVE_RESULTS_PATH": str(results), "GITHUB_STEP_SUMMARY": str(summary)}
    recorder = ExperimentRecorder("E1 probes", environ)
    hostile = "| [link](https://x.example) <b>@all</b>\n# heading " + "y" * 400
    metrics: dict[str, Metric] = {
        "error": hostile,
        "n": 3,
        "ok": True,
        "x": math.inf,
        "none": None,
        "f": 0.5,
    }
    recorder.record("E1", "arm|1", "model", metrics)
    echoed: list[str] = []
    recorder.finish(echoed.append)

    (line,) = [json.loads(text) for text in results.read_text().splitlines()]
    assert line["experiment"] == "E1" and line["metrics"]["n"] == 3
    assert line["metrics"]["x"] is None and line["metrics"]["ok"] is True
    assert len(line["metrics"]["error"]) <= 300 and "\n" not in line["metrics"]["error"]
    text = summary.read_text()
    assert text.startswith("## E1 probes")
    row = [r for r in text.splitlines() if r.startswith("| E1")][0]
    assert len(re.findall(r"(?<!\\)\|", row)) == 5  # four cells, no break-out
    for bad in ("<b>", "[link](", "\n# heading"):
        assert bad not in text
    assert echoed and "job summary" in echoed[0]


def test_the_recorder_redacts_keys_in_names_and_metrics(tmp_path: Path) -> None:
    results = tmp_path / "r.jsonl"
    recorder = ExperimentRecorder(
        "E", {"LIVE_RESULTS_PATH": str(results)}, secrets=("hush",)
    )
    recorder.secrets.add("added-later")
    recorder.record("E", f"arm {KEY}", "hush", {"error": "added-later and hush"})
    text = results.read_text() + recorder.render()
    for secret in (KEY, "hush", "added-later"):
        assert secret not in text


def test_the_recorder_echoes_without_a_summary_and_refuses_odd_metrics() -> None:
    recorder = ExperimentRecorder("E", {})
    recorder.record("E", "a", "i", {"k": "v"})
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert echoed[0] == "## E" and any("k=v" in line for line in echoed)
    with pytest.raises(TypeError):
        recorder.record("E", "a", "i", {"nested": cast(str, {"x": 1})})


def test_excerpt_redacts_flattens_and_caps() -> None:
    text = excerpt(
        f"a\nb {KEY} sk-ant-admin01-zzzzzzzzzzzz \x00c", secrets=("s3cr3t",), limit=40
    )
    assert KEY not in text and "sk-ant-admin" not in text and "\n" not in text
    assert len(text) <= 40
    assert excerpt("s3cr3t here", secrets=("s3cr3t", "")) == "[redacted] here"
    cut = excerpt("x" * 30 + KEY, limit=35)
    assert "sk-ant" not in cut  # redacted before the cap, never half a key
