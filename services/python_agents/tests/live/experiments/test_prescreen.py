"""Offline tests of E8b (``prescreen.py``, ``test_prescreen_live.py``).

The variant scripts really run here (a tiny workload, this interpreter in
isolated mode); the live test runs dry against ``FakeApi`` on the wire of a
``LiveRun``, the fake container printing what the script would.
"""

from __future__ import annotations

import ast
import json
import math
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx2
import pytest

from ..conftest import LiveRun, StartLive, restore_host_key
from . import prescreen, web
from . import test_harness as th
from . import test_prescreen_live as live_e8b
from .bounds import ExperimentRefusedError, Json, ToolAllowance, server_allowance
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_web import WebApi, reply

TINY = prescreen.Workload(n=300, unique=30, repeats=3)


# --- the scripts and the local runner ---------------------------------------


@pytest.mark.parametrize("variant", prescreen.VARIANTS)
def test_each_script_is_deterministic_self_contained_and_stdlib_only(
    variant: str,
) -> None:
    text = prescreen.script(variant)
    assert text == prescreen.script(variant) and text.endswith("main()\n")
    tree = ast.parse(text)
    imports = {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    }
    assert imports == {"hashlib", "json", "time"}
    assert not any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree))
    assert f'"variant": "{variant}"' in text and "N, UNIQUE, REPEATS" in text
    warm = text.index("    dedup(data)  # untimed warm-up")
    assert warm < text.index("for _ in range(REPEATS)")
    others = [prescreen.script(v) for v in prescreen.VARIANTS if v != variant]
    assert all(o != text for o in others)


def test_a_workload_is_bounded() -> None:
    for bad in (
        {"repeats": 1},
        {"repeats": 51},
        {"unique": 0},
        {"n": 10, "unique": 11},
    ):
        with pytest.raises(ValueError, match="bad workload"):
            prescreen.Workload(**bad)


def test_the_scripts_run_locally_and_print_one_checked_result(tmp_path: Path) -> None:
    paths = prescreen.write_scripts(tmp_path, TINY)
    assert sorted(paths) == sorted(prescreen.VARIANTS)
    for variant, path in paths.items():
        out = prescreen.run_local(path, timeout_s=60)
        timing = prescreen.parse_timing(out, variant, TINY.repeats)
        assert timing is not None and timing.ok, out
        assert timing.sha256 == prescreen.digest(prescreen.script(variant, TINY))
        assert len(timing.times) == TINY.repeats


def test_the_local_runner_uses_argv_isolated_mode_and_a_timeout(tmp_path: Path) -> None:
    (path,) = [
        p for v, p in prescreen.write_scripts(tmp_path).items() if v == "seen_set"
    ]
    calls: list[tuple[object, dict[str, object]]] = []

    def runner(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "out", "")  # type: ignore[arg-type]

    assert prescreen.run_local(path, timeout_s=7.5, runner=runner) == "out"
    ((argv, kwargs),) = calls
    assert argv == [sys.executable, "-I", str(path)]
    assert kwargs == {
        "cwd": path.parent,
        "env": {},
        "capture_output": True,
        "text": True,
        "timeout": 7.5,
        "check": False,
    }
    assert prescreen.LOCAL_TIMEOUT_S == 300.0


def test_a_hung_local_script_times_out(tmp_path: Path) -> None:
    path = tmp_path / "seen_set.py"
    path.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    with pytest.raises(subprocess.TimeoutExpired):
        prescreen.run_local(path, timeout_s=0.5)


def test_the_local_runner_and_writer_validate_paths(tmp_path: Path) -> None:
    other = tmp_path / "other.py"
    other.write_text("print(1)\n", encoding="utf-8")
    link = tmp_path / "seen_set.py"
    link.symlink_to(other)
    for bad in (other, link, Path("seen_set.py"), tmp_path / "dict_fromkeys.py"):
        with pytest.raises(ValueError, match="variant script|regular file"):
            prescreen.run_local(bad)
    for bad_dir in (Path("relative"), tmp_path / "missing", other):
        with pytest.raises(ValueError, match="absolute real directory"):
            prescreen.write_scripts(bad_dir)
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path)
    with pytest.raises(ValueError, match="absolute real directory"):
        prescreen.write_scripts(linked)
    with pytest.raises(FileExistsError):  # never overwrites
        prescreen.write_scripts(tmp_path)


# --- parsing, ranking and variation -------------------------------------------

SHA = "a" * 64


def _line(
    variant: str = "seen_set", times: object = (0.1, 0.2, 0.3), **extra: object
) -> str:
    line: Json = {
        "variant": variant,
        "times": list(times) if isinstance(times, tuple) else times,
    }
    line.update({"ok": True, "sha256": SHA}, **extra)
    return json.dumps(line)


def test_parse_timing_takes_the_last_well_formed_line_for_the_variant() -> None:
    good = _line(times=(0.3, 0.2, 0.1))
    out = "\n".join(
        [_line(times=(1.0, 1.0, 1.0)), "noise {", good, _line("dict_fromkeys")]
    )
    timing = prescreen.parse_timing(out, "seen_set", 3)
    assert timing == prescreen.Timing("seen_set", (0.3, 0.2, 0.1), True, SHA)


@pytest.mark.parametrize(
    "line",
    [
        _line(times=(0.1, 0.2)),
        _line(times="0.1"),
        _line(times=(0.1, True, 0.2)),
        _line(times=(0.1, -0.2, 0.2)),
        _line(times=(0.1, 0.0, 0.2)),
        '{"variant": "seen_set", "times": [0.1, Infinity, 0.2], "ok": true, "sha256": "'
        + SHA
        + '"}',
        _line(ok="yes"),
        _line(sha256="XYZ"),
        _line(sha256=None),
        json.dumps(["seen_set"]),
        _line("list_membership"),
    ],
)
def test_parse_timing_refuses_malformed_results(line: str) -> None:
    assert prescreen.parse_timing(line, "seen_set", 3) is None


def test_parse_timing_reads_only_the_tail_of_a_flood() -> None:
    flood = _line() + "\n" + "x" * prescreen.STDOUT_LIMIT
    assert prescreen.parse_timing(flood, "seen_set", 3) is None
    assert prescreen.parse_timing(
        "x" * 10 * prescreen.STDOUT_LIMIT + "\n" + _line(), "seen_set", 3
    )


def test_ranking_cv_and_the_recorded_verdicts() -> None:
    container = {
        "list_membership": [1.0, 1.02, 0.98],
        "seen_set": [0.010, 0.011, 0.009],
        "dict_fromkeys": [0.004, 0.004, 0.004],
    }
    local = {k: [t * 3 for t in v] for k, v in container.items()}
    assert prescreen.ranking(container) == (
        "dict_fromkeys",
        "seen_set",
        "list_membership",
    )
    assert prescreen.ranking({"b": [1.0], "a": [1.0]}) == ("a", "b")
    assert prescreen.cv([1.0, 1.0]) == 0.0
    assert math.isclose(prescreen.cv([0.9, 1.1]), 0.1414, rel_tol=1e-3)
    verdict = prescreen.compare(container, local)
    assert (
        verdict["same_ranking"] is True and verdict["cv_pass"] is False
    )  # seen_set 10 %
    assert verdict["container_ranking"] == "dict_fromkeys < seen_set < list_membership"
    steady = {**container, "seen_set": [0.010, 0.0101, 0.0099]}
    assert prescreen.compare(steady, local)["cv_pass"] is True
    swapped = {**local, "seen_set": [0.001, 0.001, 0.001]}
    assert prescreen.compare(container, swapped)["same_ranking"] is False
    partial = prescreen.compare({"seen_set": [0.1, 0.1]}, local)
    assert (partial["same_ranking"], partial["cv_pass"]) == (None, None)
    empty = prescreen.compare({}, {})
    assert (empty["container_max_cv"], empty["local_max_cv"], empty["cv_pass"]) == (
        None,
        None,
        None,
    )


# --- the container request and its answer -------------------------------------


def test_the_container_request_has_only_the_code_execution_tool() -> None:
    text = prescreen.script("seen_set")
    body = prescreen.container_body("seen_set", text)
    assert body["tools"] == [
        {"type": "code_execution_20260521", "name": "code_execution"}
    ]
    assert (
        body["model"] == prescreen.MODEL
        and "container" not in body
        and "betas" not in body
    )
    assert f"<<<SCRIPT\n{text}SCRIPT>>>" in _prompt(body)
    assert (
        prescreen.container_body("seen_set", text, "container_01A-b")["container"]
        == "container_01A-b"
    )
    for bad in ("", "a b", "x" * 129, "../c"):
        with pytest.raises(ValueError, match="container id"):
            prescreen.container_body("seen_set", text, bad)


def test_code_execution_needs_the_explicit_allowance() -> None:
    with pytest.raises(ExperimentRefusedError, match="ToolAllowance"):
        server_allowance([prescreen.TOOL], batch=False)
    allowed = server_allowance(
        [prescreen.TOOL], batch=False, explicit=prescreen.ALLOWANCE
    )
    assert allowed == prescreen.ALLOWANCE == ToolAllowance(10, 20_000, 0.05)


def test_stdout_container_id_and_reported_hours_are_read_strictly() -> None:
    blocks: list[Json] = [
        {
            "type": "bash_code_execution_tool_result",
            "content": {"type": "bash_code_execution_result", "stdout": "a"},
        },
        {"type": "code_execution_tool_result", "content": {"stdout": "b"}},
        {"type": "bash_code_execution_tool_result", "content": {"stdout": 3}},
        {"type": "bash_code_execution_tool_result", "content": "c"},
        {"type": "text", "content": {"stdout": "d"}},
    ]
    assert prescreen.stdouts(blocks) == ["a", "b"]
    assert prescreen.container_id({"id": "container_01"}) == "container_01"
    assert (
        prescreen.container_id({"id": "bad id"}) is None
        and prescreen.container_id(None) is None
    )
    hours = prescreen.reported_hours
    assert hours({"server_tool_use": {"code_execution_requests": 2}}) is None
    assert hours({"server_tool_use": {"container_seconds": 900}}) == 0.25
    assert hours({"x": {"container_hours": 0.5}}) == 0.5
    assert hours({"execution_time_hours": True, "container_hours": -1}) is None


def test_each_mode_cap_covers_its_three_worst_cases() -> None:
    for mode in prescreen.MODES:
        reuse = "c" * 128 if mode == "reused" else None
        least = sum(
            web.run_cap(
                prescreen.container_body(v, prescreen.script(v), reuse),
                prescreen.ALLOWANCE,
            )
            for v in prescreen.VARIANTS
        )
        assert live_e8b.mode_cap(mode) >= least > 0
    assert live_e8b.E8B_NEED_USD < 3.0


# --- the live test, dry ---------------------------------------------------------------


def _prompt(body: Json) -> str:
    messages = body["messages"]
    assert isinstance(messages, list) and isinstance(messages[0], dict)
    return str(messages[0]["content"])


def _respond(body: Json) -> Json:
    """The container's answer: the script's own line, as if it ran."""
    prompt = _prompt(body)
    (variant,) = [v for v in prescreen.VARIANTS if f"/tmp/e8b/{v}.py" in prompt]
    scale = {"list_membership": 1.0, "seen_set": 0.01, "dict_fromkeys": 0.004}[variant]
    match = re.search(r"<<<SCRIPT\n(.*)SCRIPT>>>", prompt, re.DOTALL)
    assert match is not None
    text = match.group(1)
    line = {
        "variant": variant,
        "times": [scale, scale * 1.01, scale * 0.99],
        "ok": True,
        "sha256": prescreen.digest(text),
    }
    container = body.get("container") or f"container_{variant}"
    out = {
        "type": "bash_code_execution_result",
        "stdout": json.dumps(line) + "\n",
        "stderr": "",
        "return_code": 0,
        "content": [],
    }
    message = reply(
        prescreen.MODEL,
        [
            {
                "type": "bash_code_execution_tool_result",
                "tool_use_id": "srvtoolu_1",
                "content": out,
            }
        ],
    )
    message["container"] = {"id": container, "expires_at": "2026-10-23T01:00:00Z"}
    usage = message["usage"]
    assert isinstance(usage, dict)
    usage["server_tool_use"] = {
        "web_search_requests": 0,
        "web_fetch_requests": 0,
        "container_seconds": 300,
    }
    return message


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> WebApi:
    restore_host_key(monkeypatch, th.KEY)
    monkeypatch.setattr(prescreen, "DEFAULT_WORKLOAD", TINY)
    return WebApi(_respond)


@pytest.fixture
def start(api: WebApi) -> Iterator[StartLive]:
    runs: list[LiveRun] = []

    def begin(cap: float) -> LiveRun:
        runs.append(LiveRun("dry", cap, wire=httpx2.MockTransport(api)))
        return runs[-1]

    yield begin
    assert all(r.spent_usd <= r.cap_usd for r in runs)


@pytest.mark.parametrize("mode", prescreen.MODES)
def test_a_dry_prescreen_records_each_variant_and_the_verdicts(
    mode: str, api: WebApi, start: StartLive, tmp_path: Path
) -> None:
    recorder = ExperimentRecorder("E8b", {})
    live_e8b.test_e8b_prescreen(mode, start, tmp_path, recorder)
    rows = {r.item: r.metrics for r in recorder.rows}
    assert set(rows) == {*prescreen.VARIANTS, "summary"}
    for variant in prescreen.VARIANTS:
        m = rows[variant]
        assert (m["parsed"], m["output_ok"], m["script_intact"]) == (True, True, True)
        assert m["reported_container_hours"] == pytest.approx(300 / 3600)
    containers = [b.get("container") for b in api.bodies]
    summary = rows["summary"]
    if mode == "reused":
        assert containers == [
            None,
            "container_list_membership",
            "container_list_membership",
        ]
        assert (summary["containers"], summary["reused_one_container"]) == (1, True)
    else:
        assert containers == [None, None, None] and summary["containers"] == 3
        assert summary["reused_one_container"] is None
    assert summary["container_ranking"] == "dict_fromkeys < seen_set < list_membership"
    assert summary["cv_pass"] is True and isinstance(summary["same_ranking"], bool)
    count = summary["containers"]
    assert isinstance(count, int)
    assert summary["container_hours_floor"] == pytest.approx(count * 5 / 60)
    assert summary["reported_container_hours"] == pytest.approx(3 * 300 / 3600)


e8b_recorder = live_e8b.e8b_recorder  # the live module's fixture, run here


def test_the_live_recorder_fixture_yields_an_empty_recorder(
    e8b_recorder: ExperimentRecorder,
) -> None:
    assert e8b_recorder.title == "E8b sandbox pre-screen" and e8b_recorder.rows == []


def test_a_refused_container_request_is_recorded_and_the_run_goes_on(
    api: WebApi, start: StartLive, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prescreen, "run_local", lambda path: "no result line")
    api.status = 400
    recorder = ExperimentRecorder("E8b", {})
    live_e8b.test_e8b_prescreen("reused", start, tmp_path, recorder)
    rows = {r.item: r.metrics for r in recorder.rows}
    assert rows["seen_set"]["parsed"] is False and rows["summary"]["containers"] == 0
    assert rows["summary"]["same_ranking"] is None and len(api.bodies) == 0
    assert rows["summary"]["local_ranking"] == ""  # no local line parsed either


def test_each_container_request_fits_its_cap_at_a_count_of_its_bytes(
    api: WebApi,
) -> None:
    for mode in prescreen.MODES:
        run = LiveRun("dry", live_e8b.mode_cap(mode), wire=httpx2.MockTransport(api))
        client = ExperimentClient(run)
        reuse = "container_" + "x" * 118 if mode == "reused" else None
        total = 0.0
        for variant in prescreen.VARIANTS:
            body = prescreen.container_body(variant, prescreen.script(variant), reuse)
            api.count = len(json.dumps(body).encode())
            total += client.estimate(body, allowance=prescreen.ALLOWANCE)
        assert total <= run.cap_usd, mode
