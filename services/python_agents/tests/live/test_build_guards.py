"""Offline guards of the build-then-improve suite (``build_improve.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_build_live.py``, that every run's cap is the sum of the worst cases
of the requests it may send (the build and tests requests at their prompt
bounds, phase 1 and the blind generation at the OSS bounds, a loop scaled
with its trial count), that the default plan fits live-smoke's 150 USD
ceiling, what the two requests carry (the tests request holds the spec and
nothing of the build), which builds the layout check refuses, that model
code runs only in the sandbox (every launch ``required`` and isolated), and
what the notes, the results file and the summary say. ``slow`` rehearsals
run whole specs (build, tests, validation, phase 1, generation, loop) in the
sandbox with only the wire mocked.

Fakes and what they stand for: ``dg.Wire`` / ``ScriptedTransport`` for the
Messages API (the live run's captured ``AnthropicTransport``); the hand-written
builds in ``tests/fixtures/build_specs/_reference`` for Opus's build reply
and their hand-written tests for Sonnet's tests reply (the rehearsal shrinks
each benchmark's size); hand-built ``CorpusOutcome`` values for the engine's
(the rehearsal uses the real engine).
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import json
import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from e2e.conftest import Isolation, git

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import EFFORT_LEVELS, settings
from autonomous_ai_agents.execution.procrun import RunFailure, run_once
from autonomous_ai_agents.optimization.anticheat import check_path

from . import build_improve as bi
from . import corpus
from . import discovery_oss as dx
from . import test_discovery_guards as dg
from .conftest import (
    _CELL_MAX,
    TESTS_DIR,
    LiveRun,
    RequestRecord,
    restore_host_key,
)
from .discovery import OPUS, SONNET, ceil_usd, start_phase_one, worst_usd
from .discovery_ab import AB_GENERATE_MAX_TOKENS, AB_N
from .discovery_io import ResultsSink
from .experiments.heal import MAX_REASONS, Reason, RunResult, read_tree, write_tree
from .test_oss_guards import _require_sandbox

dry = dg.dry  # registered by name

LIVE_DIR = TESTS_DIR / "live"
REQUIRED = Isolation("required", None)
Json = dict[str, Any]
# What the suite needs at the default knobs (the sum of the caps run_spec
# asks the ledger for); the Lead copies it into ci.yml. Per spec: the build
# run (Opus build + Sonnet tests, 0.80), the generation run (phase 1 and the
# blind arm at the OSS bounds, 0.60) and a 3-trial loop (3 x 2.50).
BUILD_RUN_CAP = 0.8
GEN_CAP = 0.6
DEFAULT_NEED = 26.7  # 3 specs x (0.80 + 0.60 + 7.50)
ONE_SPEC_NEED = 8.9
REFERENCE_DIR = bi.BUILD_DIR / "_reference"
SMALL = {  # the rehearsal's benchmark sizes (the spec's are timed live)
    "salesreport": (("ROWS = 200_000", "ROWS = 3_000"),),
    "wordpairs": (("WORDS = 1_000_000", "WORDS = 20_000"),),
    "gridroute": (("SIZE = 600", "SIZE = 60"),),
}


def _reference(spec: bi.BuildSpec, *, small: bool = True) -> dict[str, str]:
    """The hand-written build of ``spec`` (the benchmark shrunk when
    ``small``: the rehearsal times it many times)."""
    tree = read_tree(REFERENCE_DIR / spec.name)
    if small:
        bench = tree[spec.bench_path]
        for big, little in SMALL[spec.name]:
            assert big in bench, (spec.name, big)
            bench = bench.replace(big, little)
        tree[spec.bench_path] = bench
    return tree


def _reference_tests(spec: bi.BuildSpec) -> str:
    return (REFERENCE_DIR / "tests" / f"{spec.name}.py").read_text(encoding="utf-8")


def _entries(tree: Mapping[str, str]) -> list[tuple[str, str]]:
    return sorted(tree.items())


SPEC = bi.SPECS[0]

# ---------------------------------------------------------------------------
# The specs
# ---------------------------------------------------------------------------


def test_three_specs_each_a_package_with_its_own_name() -> None:
    assert [s.name for s in bi.SPECS] == ["salesreport", "wordpairs", "gridroute"]
    for spec in bi.SPECS:
        assert spec.package == spec.name
        assert spec.text.isascii() and len(spec.text) <= bi.SPEC_MAX_CHARS
        assert f"Package name: `{spec.package}`" in spec.text
        assert "## Benchmark size" in spec.text and "seconds" in spec.text
        assert spec.bench_path == f"benchmarks/bench_{spec.name}.py"


def _manifest(**change: object) -> Json:
    entry: Json = {"name": "salesreport", "package": "salesreport"}
    entry |= {"file": "salesreport.md"}
    entry.update(change)
    return {"version": 1, "specs": [entry]}


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({"version": 2, "specs": []}, "version 1"),
        ({"specs": []}, "version, specs"),
        (_manifest(extra=1), "exactly the keys"),
        (_manifest(name="Sales"), "lowercase identifier"),
        (_manifest(package="sales-report"), "lowercase identifier"),
        (_manifest(file="../salesreport.md"), "<name>.md"),
        (_manifest(name="wordpairs", package="wordpairs"), "<name>.md"),
    ],
)
def test_the_manifest_is_read_strictly(data: Json, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        bi.parse_manifest(data, bi.BUILD_DIR)


def test_a_duplicate_or_an_unfit_spec_is_refused(tmp_path: Path) -> None:
    entry = _manifest()["specs"][0]
    with pytest.raises(ValueError, match="its own name"):
        bi.parse_manifest({"version": 1, "specs": [entry, entry]}, bi.BUILD_DIR)
    for text, match in (
        ("caf\u00e9\n", "ASCII"),
        ("x" * (bi.SPEC_MAX_CHARS + 1), "characters"),
        ("a\x00b\n", "control"),
    ):
        (tmp_path / "salesreport.md").write_text(text, encoding="utf-8")
        with pytest.raises(ValueError, match=match):
            bi.parse_manifest(_manifest(), tmp_path)


@contextlib.contextmanager
def _imported(root: Path, package: str) -> Iterator[Any]:
    sys.path.insert(0, str(root))
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # keep it clean
    try:
        yield importlib.import_module(package)
    finally:
        sys.dont_write_bytecode = saved
        sys.path.remove(str(root))
        for name in [m for m in sys.modules if m.split(".")[0] == package]:
            del sys.modules[name]


def test_each_worked_example_of_a_spec_holds_on_its_reference() -> None:
    """The examples the tests model reads are right (checked by hand-written
    builds of each spec, in process: this code is ours, not a model's)."""
    sales, words, grid = bi.SPECS
    example = (
        "date,region,product,units,unit_price\n2025-01-05,EAST,gear-02,4,10.00\n"
        "2025-01-20,EAST,bolt-01,3,8.08\n2025-02-01,WEST,gear-02,1,0.99\n"
    )
    report = (
        "region,month,orders,units,revenue,top_product\n"
        "EAST,2025-01,2,7,64.24,gear-02\nWEST,2025-02,1,1,0.99,gear-02\n"
        "TOTAL,,3,8,65.23,\n"
    )
    assert example in sales.text
    with _imported(REFERENCE_DIR / sales.name, sales.package) as module:
        assert module.build_report(example) == report
    assert report.split("\n")[1] in sales.text
    phrase = "Red fox, red fox. The red fox ran; red Fox ran!"
    rendered = "1\tred fox\t4\n2\tfox ran\t2\n3\tfox red\t1\nkept=8 distinct=4\n"
    assert phrase in words.text and rendered in words.text
    with _imported(REFERENCE_DIR / words.name, words.package) as module:
        assert module.render(phrase, 3) == rendered
    text = "3 2\n131\n112\n"
    out = (
        "size=3x2\ncorner 0,0 = 0\ncorner 2,0 = 4\ncorner 0,1 = 1\n"
        "corner 2,1 = 4\ncentre 1,1 = 2\ntotal=14\nmax=4\n"
    )
    assert out in grid.text and "[[0, 3, 4], [1, 2, 4]]" in grid.text
    with _imported(REFERENCE_DIR / grid.name, grid.package) as module:
        assert module.shortest_costs(module.parse_grid(text)) == [[0, 3, 4], [1, 2, 4]]
        assert module.render(text) == out


# ---------------------------------------------------------------------------
# The two requests
# ---------------------------------------------------------------------------


def _text(request: Any) -> str:
    return str(request.messages[0]["content"][0]["text"])


def test_the_build_request_fences_the_spec_and_asks_for_the_layout() -> None:
    fence = Fence.new()
    request = bi.build_request(SPEC, fence)
    text = _text(request)
    assert request.max_tokens == bi.BUILD_MAX_TOKENS
    assert request.output_config is not None
    assert request.output_config["effort"] == bi.BUILD_EFFORT
    form = request.output_config["format"]
    assert form is not None
    schema = form["schema"]
    assert schema["required"] == ["files"] and schema["additionalProperties"] is False
    assert request.tools == () and request.cache is False
    assert fence.token in text and "untrusted_specification" in text
    assert json.dumps({"specification": SPEC.text}) in text
    assert SPEC.bench_path in text and f"Package: {SPEC.package}" in text
    for part in ("benchmarks/generate.py", "README.md", "__main__.py", "standard"):
        assert part in str(request.system), part


def test_the_tests_request_carries_the_spec_alone() -> None:
    """Sonnet writes the tests from the English spec: the request holds no
    file of any build (the function takes the spec only)."""
    fence = Fence.new()
    request = bi.tests_request(SPEC, fence)
    text = _text(request)
    assert request.max_tokens == bi.TESTS_MAX_TOKENS
    assert request.output_config is not None
    assert request.output_config["effort"] == bi.TESTS_EFFORT
    form = request.output_config["format"]
    assert form is not None and form["schema"]["required"] == ["content"]
    assert json.dumps({"specification": SPEC.text}) in text
    reference = _reference(SPEC, small=False)
    for content in reference.values():
        for line in content.splitlines():
            if len(line) > 30 and line not in SPEC.text:
                assert json.dumps(line)[1:-1] not in text, line
    assert "never see" in str(request.system)
    signature = ast.parse((LIVE_DIR / "build_improve.py").read_text(encoding="utf-8"))
    tests_fn = next(
        n
        for n in ast.walk(signature)
        if isinstance(n, ast.FunctionDef) and n.name == "tests_request"
    )
    assert [a.arg for a in tests_fn.args.args] == ["spec", "fence"]


def test_a_spec_holding_the_boundary_token_is_refused() -> None:
    fence = Fence.new()
    bad = replace(SPEC, text=SPEC.text + fence.token)
    for build in (bi.build_request, bi.tests_request):
        with pytest.raises(ValueError, match="boundary token"):
            build(bad, fence)


def test_each_request_model_is_priced_takes_its_effort_and_has_no_fallbacks() -> None:
    for cfg, model, effort in (
        (bi.build_settings(settings), OPUS, bi.BUILD_EFFORT),
        (bi.tests_settings(settings), SONNET, bi.TESTS_EFFORT),
    ):
        assert cfg.ENGINE_MODEL == model and cfg.ENGINE_FALLBACKS is False
        assert model in cfg.MODEL_PRICING and effort in EFFORT_LEVELS[model]
        assert cfg.LLM_TIMEOUT_S == bi.REQUEST_TIMEOUT_S
    assert settings.LLM_TIMEOUT_S != bi.REQUEST_TIMEOUT_S  # the global untouched
    # A non-streaming request above about 21,333 output tokens needs an
    # explicit timeout (STATUS): the build stays below it.
    assert bi.BUILD_MAX_TOKENS < 21_333 and bi.TESTS_MAX_TOKENS < 21_333


def _bound(request: Any) -> int:
    return ScriptedTransport([]).count_input_tokens(request)


def test_the_prompt_bounds_hold_on_the_widest_spec() -> None:
    """The byte bound plus the allowance (what ``call()`` counts when the
    count endpoint fails; the API's count cannot exceed it) of each request
    built from the widest spec the manifest accepts: every character a
    quote, which JSON escapes twice."""
    widest = replace(SPEC, text='"' * bi.SPEC_MAX_CHARS)
    fence = Fence.new()
    assert _bound(bi.build_request(widest, fence)) <= bi.BUILD_PROMPT_BOUND
    assert _bound(bi.tests_request(widest, fence)) <= bi.TESTS_PROMPT_BOUND
    for spec in bi.SPECS:
        assert _bound(bi.build_request(spec, fence)) <= bi.BUILD_PROMPT_BOUND
    assert bi.BUILD_PROMPT_BOUND <= 1.2 * _bound(bi.build_request(widest, fence))


# ---------------------------------------------------------------------------
# Caps and the plan
# ---------------------------------------------------------------------------


def test_each_cap_is_the_sum_of_the_worst_cases_of_its_requests() -> None:
    build = worst_usd(bi.BUILD_PROMPT_BOUND, bi.BUILD_MAX_TOKENS, OPUS)
    tests = worst_usd(bi.TESTS_PROMPT_BOUND, bi.TESTS_MAX_TOKENS, SONNET)
    assert bi.BUILD_RUN_CAP_USD == ceil_usd(build + tests) == BUILD_RUN_CAP
    phase = dx.OSS_PHASE_ONE_WORST_USD
    blind = worst_usd(dx.OSS_BLIND_PROMPT_BOUND, AB_GENERATE_MAX_TOKENS, SONNET)
    assert bi.BUILD_GEN_CAP_USD == ceil_usd(phase + blind) == GEN_CAP
    assert bi.BUILD_PHASE_ONE_CAP_USD == dx.OSS_PHASE_ONE_CAP_USD
    plan = bi.build_plan({})
    assert plan.trial_cap == dx.OSS_TRIAL_CAP_USD
    assert [plan.loop_cap(n) for n in (1, 2, 3)] == [2.5, 5.0, 7.5]
    with pytest.raises(ValueError, match="at least one"):
        plan.loop_cap(0)


def test_the_need_is_the_sum_of_the_caps_and_fits_the_ceiling() -> None:
    plan = bi.build_plan({})
    assert plan.specs == bi.SPECS
    per_spec = bi.BUILD_RUN_CAP_USD + bi.BUILD_GEN_CAP_USD + plan.loop_cap(AB_N)
    assert bi.build_need(plan) == pytest.approx(3 * per_spec)
    assert bi.build_need(plan) == pytest.approx(DEFAULT_NEED)
    assert DEFAULT_NEED <= dx.CAP_CEILING_USD
    one = bi.build_plan({bi.SPECS_ENV: "wordpairs"})
    assert [s.name for s in one.specs] == ["wordpairs"]
    assert bi.build_need(one) == pytest.approx(ONE_SPEC_NEED)
    low = bi.build_plan({bi.TRIAL_CAP_ENV: "1"})
    assert bi.build_need(low) == pytest.approx(3 * (0.8 + 0.6 + 3.0))


@pytest.mark.parametrize(
    "environ",
    [
        {bi.SPECS_ENV: "nope"},
        {bi.SPECS_ENV: "wordpairs,wordpairs"},
        {bi.SPECS_ENV: ""},
        {bi.TRIAL_CAP_ENV: "3"},
        {bi.TRIAL_CAP_ENV: "-1"},
        {bi.TRIAL_CAP_ENV: "nan"},
    ],
)
def test_knobs_parse_strictly_before_any_spend(environ: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        bi.build_plan(environ)


def test_the_spec_knob_keeps_the_manifest_order() -> None:
    plan = bi.build_plan({bi.SPECS_ENV: "gridroute,salesreport"})
    assert [s.name for s in plan.specs] == ["salesreport", "gridroute"]


# ---------------------------------------------------------------------------
# The layout check and the tests reply
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", bi.SPECS, ids=lambda s: s.name)
def test_each_reference_build_passes_the_layout_check(spec: bi.BuildSpec) -> None:
    tree = _reference(spec, small=False)
    accepted, problems = bi.check_build(_entries(tree), spec)
    assert problems == [] and accepted == tree
    assert check_path(spec.bench_path) is not None  # the editor may not touch it
    assert check_path("benchmarks/generate.py") is not None
    assert all(check_path(p) is None for p in accepted if p.startswith(spec.package))
    assert bi.check_tests(_reference_tests(spec)) is None


def _refused(change: Callable[[dict[str, str]], None]) -> list[str]:
    tree = _reference(SPEC, small=False)
    change(tree)
    accepted, problems = bi.check_build(_entries(tree), SPEC)
    assert accepted == {} and problems
    return problems


@pytest.mark.parametrize(
    ("path", "why"),
    [
        ("tests/test_x.py", "not in the layout"),
        ("setup.py", "not in the layout"),
        ("pyproject.toml", "not in the layout"),
        ("benchmarks/other.py", "not in the layout"),
        ("salesreport/sub/deep.py", "not in the layout"),
        ("salesreport/Upper.py", "not in the layout"),
        ("salesreport/test_core.py", "protected"),
        ("salesreport/conftest.py", "protected"),
        ("salesreport/../evil.py", "not a clean"),
        ("/abs/salesreport/x.py", "not a clean"),
        ("salesreport/./x.py", "not a clean"),
        ("salesreport/notes.txt", "not in the layout"),
    ],
)
def test_a_path_off_the_layout_refuses_the_whole_build(path: str, why: str) -> None:
    problems = _refused(lambda tree: tree.update({path: "x = 1\n"}))
    assert any(why in p for p in problems), problems


def test_a_missing_required_file_refuses_the_build() -> None:
    for name in (
        "salesreport/__init__.py",
        "salesreport/__main__.py",
        "benchmarks/generate.py",
        "benchmarks/bench_salesreport.py",
        "README.md",
    ):
        problems = _refused(lambda tree, name=name: tree.pop(name))  # type: ignore[misc]
        assert f"missing {name}" in problems, problems


def test_unfit_contents_refuse_the_build() -> None:
    code = {"salesreport/x.py": "s = 'caf\u00e9'\n"}
    assert any("ASCII" in p for p in _refused(lambda t: t.update(code)))
    readme = {**_reference(SPEC), "README.md": "Caf\u00e9 \u2014 a report.\n"}
    assert bi.check_build(_entries(readme), SPEC)[1] == []  # prose may be wider
    assert any(
        "control" in p
        for p in _refused(lambda t: t.update({"README.md": "a\u202eb\n"}))
    )
    assert any(
        "control" in p for p in _refused(lambda t: t.update({"README.md": "a\x1bb\n"}))
    )
    big = "x" * (bi.FILE_MAX_CHARS + 1)
    assert any(
        "longer than" in p for p in _refused(lambda t: t.update({"README.md": big}))
    )

    def many(tree: dict[str, str]) -> None:
        for i in range(bi.BUILD_MAX_FILES):
            tree[f"salesreport/m{i}.py"] = "x = 1\n"

    assert any("files" in p for p in _refused(many))

    def wide(tree: dict[str, str]) -> None:
        for i in range(4):
            tree[f"salesreport/m{i}.py"] = "#" * (bi.FILE_MAX_CHARS - 10)

    assert any("in all" in p for p in _refused(wide))


def test_a_duplicate_path_refuses_the_build() -> None:
    tree = _reference(SPEC, small=False)
    entries = [*_entries(tree), ("README.md", "again\n")]
    accepted, problems = bi.check_build(entries, SPEC)
    assert accepted == {} and any("duplicate" in p for p in problems)


def test_the_tests_reply_must_be_fit_text() -> None:
    assert bi.check_tests("import unittest\n") is None
    assert bi.check_tests("") is not None
    assert bi.check_tests("x = '\u00e9'\n") == "not ASCII"
    assert bi.check_tests("x" * (bi.TESTS_MAX_CHARS + 1)) is not None
    assert bi.check_tests("a\x07\n") is not None


def test_the_full_tree_adds_the_tests_package_and_the_tests() -> None:
    tree = _reference(SPEC)
    full = bi.full_tree(tree, "import unittest\n")
    assert (
        full["tests/__init__.py"] == "" and full[bi.TESTS_PATH] == "import unittest\n"
    )
    assert {k: v for k, v in full.items() if not k.startswith("tests/")} == tree


def test_a_built_repo_runs_its_benchmark_as_the_workload(tmp_path: Path) -> None:
    repo = bi.built_repo(SPEC, tmp_path)
    assert repo.workload_argv == ("python", SPEC.bench_path)
    assert repo.path == tmp_path / SPEC.name and repo.kind == "slowdown"
    assert repo.expected == "none" and not any(h.aimed for h in repo.hypotheses)
    project = repo.project(tmp_path)
    assert repo.workload(project).command == ("python", SPEC.bench_path)
    kinds = {g.kind.value for g in repo.guardrails(project)}
    assert kinds == {"tests_pass", "output_equivalence"}  # the output check is on
    assert repo.objectives(project) == []  # the default: minimize wall time


# ---------------------------------------------------------------------------
# The sandbox: model code never runs in the host process
# ---------------------------------------------------------------------------


def _validate(tmp: Path, tree: Mapping[str, str], **kw: Any) -> tuple[Any, Any]:
    log = bi.IsolationLog()
    sandbox = bi.BuildSandbox(Path(os.path.realpath(tmp)) / "box", run=log)
    return bi.validate(sandbox, tree, SPEC, **kw), log


@pytest.mark.slow
@pytest.mark.parametrize("spec", bi.SPECS, ids=lambda s: s.name)
def test_each_reference_build_validates_in_the_sandbox(
    tmp_path: Path, spec: bi.BuildSpec
) -> None:
    _require_sandbox()
    tree = bi.full_tree(_reference(spec), _reference_tests(spec))
    log = bi.IsolationLog()
    sandbox = bi.BuildSandbox(Path(os.path.realpath(tmp_path)) / "box", run=log)
    found = bi.validate(sandbox, tree, spec)
    assert found.status == bi.VALIDATED and found.detail == "", found
    total = {"salesreport": 6, "wordpairs": 6, "gridroute": 5}[spec.name]
    assert (found.tests_passed, found.tests_total) == (total, total)
    assert found.deterministic is True and len(found.walls) == bi.WORKLOAD_RUNS
    assert all(0 < w <= bi.WORKLOAD_MAX_S for w in found.walls)
    assert len(log.launches) == 1 + bi.WORKLOAD_RUNS
    bi.check_isolated(log)
    assert all(
        launch == ("required", "required", True, True) for launch in log.launches
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    ("change", "status"),
    [
        ("failing_test", bi.TESTS_FAILED),
        ("crash", bi.WORKLOAD_FAILED),
        ("random", bi.NONDETERMINISTIC),
        ("slow", bi.WORKLOAD_FAILED),
        ("silent", bi.WORKLOAD_FAILED),
    ],
)
def test_each_validation_failure_is_told_apart(
    tmp_path: Path, change: str, status: str
) -> None:
    _require_sandbox()
    tests = _reference_tests(SPEC)
    tree = _reference(SPEC)
    bench = SPEC.bench_path
    kw: dict[str, Any] = {}
    if change == "failing_test":
        tests += (
            "\n\nclass Broken(unittest.TestCase):\n"
            "    def test_wrong(self):\n        self.assertEqual(1, 2)\n"
        )
    elif change == "crash":
        tree[bench] += "raise SystemExit(3)\n"
    elif change == "random":
        tree[bench] += "import os\nprint(os.urandom(8).hex())\n"
    elif change == "slow":
        kw["max_s"] = 1e-6
    else:
        tree[bench] = "pass\n"
    found, log = _validate(tmp_path, bi.full_tree(tree, tests), **kw)
    assert found.status == status, found
    bi.check_isolated(log)
    if change == "failing_test":
        assert (found.tests_passed, found.tests_total) == (6, 7)
    if change == "random":
        assert found.deterministic is False
    if change in ("crash", "silent"):
        assert found.deterministic is None
    if change == "slow":
        assert found.deterministic is True and "over the" in found.detail


FAILING = Reason("failure", "t.T.test_x", "AssertionError", "1 != 2", None, None)


@pytest.mark.parametrize(
    ("tests", "status", "counts"),
    [
        (RunResult("passed", 6), bi.WORKLOAD_FAILED, (6, 6)),
        (RunResult("failed", 7, (FAILING,)), bi.TESTS_FAILED, (6, 7)),
        (RunResult("empty", 0), bi.TESTS_FAILED, (0, 0)),
        # the shim keeps MAX_REASONS reasons: the passes are unknown
        (
            RunResult("failed", 30, (FAILING,) * MAX_REASONS),
            bi.TESTS_FAILED,
            (None, 30),
        ),
        # the sandbox never ran the tests: an engine-side failure, no counts
        (RunResult("run_failure", detail="spawn failed"), bi.TESTS_UNRUN, (None, None)),
        (RunResult("no_result", detail="two lines"), bi.TESTS_UNRUN, (None, None)),
    ],
    ids=["passed", "failed", "empty", "capped", "run_failure", "no_result"],
)
def test_the_test_counts_never_overstate_the_passes(
    tests: RunResult, status: str, counts: tuple[int | None, int | None]
) -> None:
    found = bi.Validation(tests, ())
    assert found.status == status
    assert (found.tests_passed, found.tests_total) == counts
    outcome = bi.BuildOutcome("salesreport", built=True)
    outcome.take(found)
    shown = "/".join("-" if n is None else str(n) for n in counts)
    assert f"tests {shown} pass," in outcome.note()
    assert not outcome.tests_pass or counts == (6, 6)
    if status == bi.TESTS_UNRUN:
        assert outcome.detail.startswith(f"tests {tests.status} ")
        assert tests.detail in outcome.detail


@pytest.mark.slow
def test_the_sandbox_has_no_network_and_cannot_write_outside(tmp_path: Path) -> None:
    """What the build's code could try: reach the network, write beside its
    copy. Both fail inside the sandbox; the workload still prints."""
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path))
    outside = root / "outside.txt"
    tree = _reference(SPEC)
    tree[SPEC.bench_path] = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=2)\n"
        "    print('net yes')\n"
        "except OSError:\n"
        "    print('net no')\n"
        "try:\n"
        f"    open({str(outside)!r}, 'w').write('x')\n"
        "    print('write yes')\n"
        "except OSError:\n"
        "    print('write no')\n"
    )
    log = bi.IsolationLog()
    sandbox = bi.BuildSandbox(root / "box", run=log)
    run = sandbox.workload(bi.full_tree(tree, "import unittest\n"), SPEC.bench_path)
    assert run.sample is not None, run.detail
    assert run.sample.stdout_head == b"net no\nwrite no\n"
    assert not outside.exists()
    bi.check_isolated(log)


def test_the_isolation_guard_refuses_any_unisolated_launch() -> None:
    log = bi.IsolationLog()
    with pytest.raises(AssertionError, match="no sandboxed launch"):
        bi.check_isolated(log)
    log.launches.append(("required", "required", True, True))
    bi.check_isolated(log)
    log.launches.append(("required", "required", None, None))  # a RunFailure
    bi.check_isolated(log)
    for bad in (
        ("best_effort", "required", True, True),
        ("required", "off", True, True),
        ("required", "required", False, True),
        ("required", "required", True, False),
    ):
        broken = bi.IsolationLog(launches=[bad])
        with pytest.raises(AssertionError):
            bi.check_isolated(broken)


def test_the_isolation_log_records_a_failed_launch_and_reraises(
    tmp_path: Path,
) -> None:
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise RunFailure("timed out")

    log = bi.IsolationLog(run=failing)
    sandbox = bi.BuildSandbox(Path(os.path.realpath(tmp_path)) / "box", run=log)
    found = sandbox.workload({"x.py": "pass\n"}, "x.py")
    assert found.sample is None and "timed out" in found.detail
    assert log.launches == [("required", "required", None, None)]
    assert bi.IsolationLog().run is run_once


# ---------------------------------------------------------------------------
# Notes, rows and the summary
# ---------------------------------------------------------------------------

HOSTILE = "kept | `x` [y](http://e.x) @here <b>\u00e9\u202e\n" + "z" * 300


def _done(**change: Any) -> bi.BuildOutcome:
    outcome = bi.BuildOutcome(
        spec="wordpairs",
        status=bi.IMPROVED,
        built=True,
        files=("README.md", "wordpairs/__init__.py"),
        tests_written=True,
        tests_status="passed",
        tests_total=12,
        tests_passed=12,
        deterministic=True,
        walls=(1.2345, 1.25),
        candidates=3,
        improved=True,
        gain_pct=23.456,
        kept=("use a Counter over zip", HOSTILE),
        engine_status="done",
        build_cost_usd=0.21,
        tests_cost_usd=0.05,
        phase_cost_usd=0.04,
        generation_cost_usd=0.02,
        engine_cost_usd=1.5,
        cost_usd=1.82,
    )
    for key, value in change.items():
        setattr(outcome, key, value)
    return outcome


def _plain_note(note: str) -> None:
    assert len(note) <= _CELL_MAX and note.isascii() and note.isprintable(), note


def test_the_verdict_note_has_the_brief_format_and_fits_one_cell() -> None:
    note = _done().note()
    _plain_note(note)
    assert note.startswith(
        "BUILD wordpairs: built y tests 12/12 pass, deterministic y, improved y "
        "gain 23.5% kept use a Counter over zip; kept "
    )
    assert note.endswith(", 1.8200 USD")
    failed = _done(
        status=bi.BUILD_FAILED,
        built=False,
        tests_written=False,
        tests_total=None,
        tests_passed=None,
        deterministic=None,
        improved=None,
        gain_pct=None,
        kept=(),
        cost_usd=0.4,
    ).note()
    assert failed == (
        "BUILD wordpairs: built n tests -/- pass, deterministic -, improved - "
        "gain - kept none, 0.4000 USD"
    )


def test_the_status_and_error_notes_are_plain_lines() -> None:
    outcome = _done(
        status=bi.NONDETERMINISTIC,
        detail=HOSTILE,
        generation_error=None,
        guard="ok",
    )
    notes = outcome.notes()
    assert len(notes) == 3
    for note in notes:
        _plain_note(note)
    assert notes[1].startswith(
        "BUILD wordpairs check: status nondeterministic; tests passed 12/12; "
        "runs 1.23/1.25 s (bound 10 s); ideas 3; guard ok"
    )
    assert notes[2].startswith("BUILD wordpairs detail: kept | `x` [y]")
    assert len(_done().notes()) == 2  # no detail: no third note


def test_the_summary_note_counts_every_stage() -> None:
    rows = [
        _done(),
        _done(spec="gridroute", status=bi.NOT_IMPROVED, improved=False, kept=()),
        _done(
            spec="salesreport", status=bi.TESTS_FAILED, tests_passed=3, improved=None
        ),
    ]
    note = bi.summary_note(rows)
    _plain_note(note)
    assert note == (
        "BUILD summary 3 spec(s): built 3/3, tests pass 2/3, deterministic 3/3, "
        "improved 1/3 (gains 23.5%), 5.4600 USD"
    )
    assert bi.summary_note([]) == "BUILD summary 0 spec(s)"
    unrun = _done(
        spec="salesreport",
        status=bi.TESTS_UNRUN,
        tests_status="run_failure",
        tests_passed=None,
        tests_total=None,
        improved=None,
    )
    assert "tests pass 1/2 (1 unrun)," in bi.summary_note([_done(), unrun])


def test_the_markdown_summary_sanitises_hostile_text() -> None:
    hostile = "x\n## injected <script>[l](https://e.example) `c` @here\n| forged |"
    text = bi.render_build([_done(detail=HOSTILE, kept=(hostile,))])
    body = text.split("\n", 1)[1]
    assert "<script>" not in body and "<b>" not in body
    assert "\n## injected" not in body and "\n| forged" not in body
    assert not re.search(r"(?<!\\)[\[\]`@]", body)  # no live link, code or mention
    assert text.startswith("## Build then improve")
    assert "BUILD summary 1 spec(s)" in text
    assert "No spec finished." in bi.render_build([])


def test_records_go_to_the_results_file_and_notes_to_the_run(dry: Path) -> None:
    results = dry / "results.jsonl"
    recorder = bi.BuildRecorder(
        bi.build_plan({}), ResultsSink({corpus.RESULTS_ENV: str(results)})
    )
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(dg._no_wire))
    recorder.record(_done(), run)
    recorder.note_summary(run)
    (line,) = [json.loads(x) for x in results.read_text().splitlines()]
    assert line["experiment"] == bi.EXPERIMENT and line["spec"] == "wordpairs"
    assert (
        line["walls"] == [1.2345, 1.25] and line["kept"][0] == "use a Counter over zip"
    )
    assert len(line["kept"][1]) <= corpus.JSON_TEXT_MAX
    assert len(run.notes) == 3 and run.notes[-1].startswith("BUILD summary 1 spec(s)")
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert echoed[0] == "## Build then improve"
    empty = bi.BuildRecorder(bi.build_plan({}), ResultsSink({}))
    empty.finish(echoed.append)
    assert echoed.count("## Build then improve") == 1


def test_a_relative_results_path_is_refused_before_any_spend() -> None:
    with pytest.raises(ValueError, match="absolute"):
        bi.BuildRecorder(
            bi.build_plan({}), ResultsSink({corpus.RESULTS_ENV: "x.jsonl"})
        )


def test_plain_reduces_model_text_to_one_ascii_line() -> None:
    assert bi.plain("a\nb\t\u00e9 \u202e c", 50) == "a b ? ? c"
    assert bi.plain("x" * 10, 4) == "xxx~"
    assert bi.plain("", 5) == ""


# ---------------------------------------------------------------------------
# The live module
# ---------------------------------------------------------------------------


def test_the_live_module_is_marked_parses_its_plan_first_and_runs_specs() -> None:
    source = (LIVE_DIR / "test_build_live.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]
    assert marks == ["pytest.mark.live"]
    tests = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert [t.name for t in tests] == ["test_build_then_improve"]
    args = [a.arg for a in tests[0].args.args]
    assert {"live", "live_root", "live_isolation"} <= set(args)
    assert '@pytest.fixture(scope="module")' in source
    assert "build_plan(os.environ)" in source
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(tests[0])
        if isinstance(node, ast.Call)
    }
    assert "run_spec" in calls and "live" not in calls


def test_model_code_reaches_no_host_execution_path() -> None:
    """No ``exec``, ``eval``, ``compile``, ``subprocess`` or ``importlib`` in
    the suite module: a build's code is run by the sandbox only."""
    tree = ast.parse((LIVE_DIR / "build_improve.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {
        alias.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for alias in n.names
    } | {
        (n.module or "").split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
    }
    assert not {"exec", "eval", "compile", "__import__"} & names
    assert not {"subprocess", "importlib", "runpy"} & imported


# ---------------------------------------------------------------------------
# Whole specs, rehearsed offline in the sandbox (only the wire is a mock)
# ---------------------------------------------------------------------------


def _rehearsal_answer(
    spec: bi.BuildSpec, *, build: Json | None = None, ideas: int = 1
) -> Callable[[Json], str]:
    reference = build or {
        "files": [{"path": p, "content": c} for p, c in _entries(_reference(spec))]
    }

    def answer(body: Json) -> str:
        if body.get("output_config", {}).get("format") is None:
            return "I leave the code as it is."
        keys = dg._schema_keys(body)
        if keys == {"files"}:
            assert body["model"] == OPUS
            return json.dumps(reference)
        if keys == {"content"}:
            assert body["model"] == SONNET
            return json.dumps({"content": _reference_tests(spec)})
        if "hypotheses" in keys:
            titles = ("count pairs in one pass", "precompile the word pattern")
            items = [{**dg._item(t), "hotspots": []} for t in titles[:ideas]]
            return json.dumps({"hypotheses": items})
        return dg._answer(body)

    return answer


def _bodies(run: LiveRun) -> list[Json]:
    return [exchange.json() for exchange in run.capture.messages()]


def _rehearse(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: Callable[[Json], str],
    spec: bi.BuildSpec = SPEC,
) -> tuple[bi.BuildOutcome, list[LiveRun], Path]:
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    wire = dg.Wire(answer)
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry[{len(runs)}]", cap_usd, wire=httpx2.MockTransport(wire))
        runs.append(run)
        return run

    results = root / "results.jsonl"
    recorder = bi.BuildRecorder(
        bi.build_plan({bi.TRIAL_CAP_ENV: "0.5"}),
        ResultsSink({corpus.RESULTS_ENV: str(results)}),
    )
    task = root / "task"
    task.mkdir()
    outcome = bi.run_spec(
        spec, live=start, root=task, isolation=REQUIRED, recorder=recorder
    )
    assert recorder.outcomes == [outcome]
    return outcome, runs, results


@pytest.mark.slow
def test_a_whole_spec_rehearsed_offline_in_the_sandbox(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_sandbox()
    before = settings.ENGINE_MODEL
    outcome, runs, results = _rehearse(dry, monkeypatch, _rehearsal_answer(SPEC))
    assert settings.ENGINE_MODEL == before
    first, gen, loop = runs
    assert (first.cap_usd, gen.cap_usd, loop.cap_usd) == (BUILD_RUN_CAP, GEN_CAP, 0.5)
    build_body, tests_body = _bodies(first)
    assert build_body["model"] == OPUS and tests_body["model"] == SONNET
    assert "fallbacks" not in build_body and "fallbacks" not in tests_body
    for line in _reference(SPEC)[f"{SPEC.package}/report.py"].splitlines():
        if len(line) > 30:
            assert json.dumps(line)[1:-1] not in json.dumps(tests_body), line
    understand_body, generate_body = _bodies(gen)
    assert understand_body["model"] == generate_body["model"] == SONNET
    assert {b["model"] for b in _bodies(loop)} == {SONNET}
    assert outcome.status == bi.NOT_IMPROVED, outcome
    assert outcome.guard == "ok" and outcome.engine_status == "done"
    assert outcome.built and outcome.tests_written and outcome.deterministic
    assert (outcome.tests_passed, outcome.tests_total) == (6, 6)
    assert outcome.candidates == 1 and outcome.improved is False
    assert outcome.cost_usd == pytest.approx(sum(r.spent_usd for r in runs))
    assert outcome.build_cost_usd + outcome.tests_cost_usd == pytest.approx(
        first.spent_usd
    )
    assert loop.notes[0].startswith(
        "BUILD salesreport: built y tests 6/6 pass, deterministic y, improved n "
    )
    assert loop.notes[1].startswith("BUILD salesreport check: status not-improved;")
    assert loop.notes[-1].startswith("BUILD summary 1 spec(s): built 1/1")
    assert not first.notes and not gen.notes
    (line,) = [json.loads(x) for x in results.read_text().splitlines()]
    assert line["status"] == bi.NOT_IMPROVED and line["experiment"] == bi.EXPERIMENT
    task = dry / "task"
    for name in ("phase", "improve"):
        tracked = git(task / name / "user", "ls-files").splitlines()
        assert set(tracked) == set(bi.full_tree(_reference(SPEC), "x")), name


@pytest.mark.slow
def test_a_refused_build_stops_after_one_request(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = [{"path": p, "content": c} for p, c in _entries(_reference(SPEC))]
    files.append({"path": "setup.py", "content": "import os\n"})
    answer = _rehearsal_answer(SPEC, build={"files": files})
    outcome, runs, _ = _rehearse(dry, monkeypatch, answer)
    (first,) = runs
    assert len(_bodies(first)) == 1  # no tests request, no sandbox run
    assert outcome.status == bi.BUILD_FAILED and not outcome.built
    assert "setup.py: not in the layout" in outcome.detail
    assert first.notes[0] == (
        f"BUILD salesreport: built n tests -/- pass, deterministic -, improved - "
        f"gain - kept none, {first.spent_usd:.4f} USD"
    )
    assert first.notes[2].startswith("BUILD salesreport detail: setup.py")
    assert not (dry / "task" / "validate").exists()


@pytest.mark.slow
def test_failing_tests_stop_the_spec_before_any_engine_run(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_sandbox()
    tree = _reference(SPEC)
    report = f"{SPEC.package}/report.py"
    tree[report] = tree[report].replace('f"{cents // 100}.', 'f"{cents // 10}.')
    build = {"files": [{"path": p, "content": c} for p, c in _entries(tree)]}
    outcome, runs, _ = _rehearse(dry, monkeypatch, _rehearsal_answer(SPEC, build=build))
    (first,) = runs  # no generation run, no loop
    assert outcome.status == bi.TESTS_FAILED, outcome
    assert outcome.tests_total == 6 and outcome.tests_passed is not None
    assert outcome.tests_passed < 6 and outcome.deterministic is True
    assert first.notes[0].startswith(
        f"BUILD salesreport: built y tests {outcome.tests_passed}/6 pass"
    )


@pytest.mark.slow
def test_an_unanswered_build_is_recorded_then_fails_the_test(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "WORKTREE_ROOT", dry / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")

    def refuse(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 900}, request=request)
        error = {"type": "error", "error": {"type": "invalid_request_error"}}
        return httpx2.Response(400, json=error, request=request)

    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        runs.append(LiveRun("dry", cap_usd, wire=httpx2.MockTransport(refuse)))
        return runs[-1]

    recorder = bi.BuildRecorder(bi.build_plan({}), ResultsSink({}))
    (dry / "task").mkdir()
    with pytest.raises(AssertionError, match="never answered"):
        bi.run_spec(
            SPEC, live=start, root=dry / "task", isolation=REQUIRED, recorder=recorder
        )
    (outcome,) = recorder.outcomes
    assert outcome.status == bi.BUILD_FAILED and outcome.guard.startswith("breach:")
    assert "LLMRequestError" in outcome.detail
    assert runs[0].notes[0].startswith("BUILD salesreport: built n")


@pytest.mark.slow
def test_a_spec_with_no_efficiency_idea_runs_no_loop(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_sandbox()
    base = _rehearsal_answer(SPEC)

    def answer(body: Json) -> str:
        if "hypotheses" in dg._schema_keys(body):
            item = {**dg._item("change the algorithm"), "hotspots": []}
            return json.dumps({"hypotheses": [{**item, "change_class": "behaviour"}]})
        return base(body)

    outcome, runs, _ = _rehearse(dry, monkeypatch, answer)
    first, gen = runs  # no loop
    assert outcome.status == bi.NO_HYPOTHESES and outcome.guard == "ok"
    assert (outcome.candidates, outcome.dropped) == (0, 1)
    assert outcome.generated == ("change the algorithm",)
    assert gen.notes[1].startswith(
        "BUILD salesreport check: status no-hypotheses; tests passed 6/6; runs "
    )
    assert "ideas 0 (+1 dropped)" in gen.notes[1]
    assert not (dry / "task" / "improve").exists()


def test_the_engine_outcome_sets_the_improve_verdict() -> None:
    outcome = bi.BuildOutcome("gridroute", status=bi.VALIDATED)
    won = corpus.CorpusOutcome(
        repo="gridroute",
        kind="slowdown",
        expected="none",
        status="done",
        engine_model=SONNET,
        served_models=(SONNET,),
        kept=("use a heap",),
        delivered=True,
        aimed_kept=False,
        gain_pct=41.0,
        best_trial_gain_pct=41.0,
        cost_usd=0.9,
        cap_usd=7.5,
        trials=3,
        violations=(),
        guard="ok",
    )
    outcome.take_engine(won, None)
    assert (outcome.status, outcome.improved, outcome.gain_pct) == (
        bi.IMPROVED,
        True,
        41.0,
    )
    assert outcome.kept == ("use a heap",) and outcome.engine_cost_usd == 0.9
    assert outcome.budget_exhausted is None and outcome.trial_budget_error is False
    outcome.take_engine(replace(won, delivered=False, kept=(), gain_pct=None), None)
    assert (outcome.status, outcome.improved) == (bi.NOT_IMPROVED, False)
    breach = replace(won, delivered=False, guard="breach: AssertionError: x")
    outcome.take_engine(breach, None)
    assert outcome.notes()[-1] == ("BUILD gridroute detail: breach: AssertionError: x")


def test_an_improve_loop_needs_a_candidate(dry: Path) -> None:
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(dg._no_wire))
    repo = bi.built_repo(SPEC, dry)
    with pytest.raises(ValueError, match="at least one candidate"):
        bi.start_improve_loop(repo, run, dry / "x", REQUIRED, settings, ())
    run.records.append(RequestRecord(SONNET, 1, 1, 0, 0, 0.0, 0.0, "end_turn"))
    with pytest.raises(ValueError, match="first spend"):
        bi.build_phase_one(repo, run, dry / "phase", REQUIRED, settings)


def test_the_budget_holds_one_build_and_one_tests_request(dry: Path) -> None:
    """``ask`` charges the run's budget like ``call()`` and records the
    models each request billed."""
    wire = dg.Wire(_rehearsal_answer(SPEC))
    run = wire.run(cap=bi.BUILD_RUN_CAP_USD)
    budget = Budget(run.cap_usd)
    built = bi.ask(
        run,
        budget,
        bi.build_settings(settings),
        bi.build_request(SPEC, Fence.new()),
        bi.BuildReply,
        "build the tool",
    )
    written = bi.ask(
        run,
        budget,
        bi.tests_settings(settings),
        bi.tests_request(SPEC, Fence.new()),
        bi.TestsReply,
        "write the tests",
    )
    assert built.reply is not None and written.reply is not None
    assert (built.models, written.models) == ((OPUS,), (SONNET,))
    bi.check_requests(run, budget, [built, written])
    assert built.cost_usd + written.cost_usd == pytest.approx(run.spent_usd)
    wrong = replace(built, models=(SONNET,))
    with pytest.raises(AssertionError):
        bi.check_requests(run, budget, [wrong, written])


def _timeout_wire(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/count_tokens"):
        return httpx2.Response(200, json={"input_tokens": 900}, request=request)
    raise httpx2.ReadTimeout("slow", request=request)


def _key_refused(request: httpx2.Request) -> httpx2.Response:
    if request.url.path.endswith("/count_tokens"):
        return httpx2.Response(200, json={"input_tokens": 900}, request=request)
    error = {"type": "error", "error": {"type": "authentication_error"}}
    return httpx2.Response(401, json=error, request=request)


def _ask_build(run: LiveRun) -> Any:
    return bi.ask(
        run,
        Budget(run.cap_usd),
        bi.build_settings(settings),
        bi.build_request(SPEC, Fence.new()),
        bi.BuildReply,
        "build the tool",
        sleep=lambda _: None,
    )


def test_a_timed_out_build_is_told_apart_from_a_refused_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout charges the estimate, so ``call()``'s retry is refused by
    the cap (``BudgetExceeded``) and the timeout itself is not in the error:
    ``ask`` adds it from what the transport saw."""
    restore_host_key(monkeypatch, "dry-run-key")
    slow = LiveRun(
        "dry", bi.BUILD_RUN_CAP_USD, wire=httpx2.MockTransport(_timeout_wire)
    )
    timed_out = _ask_build(slow)
    assert timed_out.reply is None and timed_out.error is not None
    assert "BudgetExceeded" in timed_out.error, timed_out.error
    assert "1 attempt timed out" in timed_out.error, timed_out.error
    assert slow.spent_usd > 0  # the timeout was charged its estimate
    key = LiveRun("dry", bi.BUILD_RUN_CAP_USD, wire=httpx2.MockTransport(_key_refused))
    refused = _ask_build(key)
    assert refused.error is not None and "LLMConfigError" in refused.error
    assert "timed out" not in refused.error


def test_an_unanswered_build_records_the_timeout_then_fails_the_test(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The documented behaviour: ``build-failed`` with the timeout in the
    detail note, then the answered guard turns the test red."""
    restore_host_key(monkeypatch, "dry-run-key")
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        runs.append(LiveRun("dry", cap_usd, wire=httpx2.MockTransport(_timeout_wire)))
        return runs[-1]

    recorder = bi.BuildRecorder(bi.build_plan({}), ResultsSink({}))
    (dry / "task").mkdir()
    with pytest.raises(AssertionError, match="never answered"):
        bi.run_spec(
            SPEC, live=start, root=dry / "task", isolation=REQUIRED, recorder=recorder
        )
    (outcome,) = recorder.outcomes
    assert outcome.status == bi.BUILD_FAILED and "timed out" in outcome.detail
    (detail,) = [n for n in runs[0].notes if n.startswith("BUILD salesreport detail")]
    _plain_note(detail)
    assert "timed out" in detail
    doc = bi.__doc__ or ""
    assert "fails the spec's test" in " ".join(doc.split())


def test_phase_one_reuses_the_discovery_wiring_at_the_oss_cap(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``build_phase_one`` is ``discovery.start_phase_one`` with the OSS
    phase-1 cap, not a copy of it."""
    seen: list[float] = []

    def spy(*args: Any, **kw: Any) -> Any:
        loop = start_phase_one(*args, **kw)
        seen.append(loop.cap_usd)
        return loop

    class StopError(Exception):
        pass

    def stop(loop: Any) -> Any:
        seen.append(loop.cap_usd)
        raise StopError

    monkeypatch.setattr(bi, "start_phase_one", spy)
    monkeypatch.setattr(corpus.Loop, "run", stop)
    monkeypatch.setattr(settings, "WORKTREE_ROOT", dry / "wt-root")
    tree = bi.full_tree(_reference(SPEC), _reference_tests(SPEC))
    write_tree(dry / "source" / SPEC.name, tree)
    repo = bi.built_repo(SPEC, dry / "source")
    run = LiveRun("dry", 5.0, wire=httpx2.MockTransport(dg._no_wire))
    with pytest.raises(StopError):
        bi.build_phase_one(repo, run, dry / "p", REQUIRED, settings)
    assert len(seen) == 2 and seen[-1] == bi.BUILD_PHASE_ONE_CAP_USD
