"""Offline tests of pilot P1, the heal agent (``heal_agent.py``, its live test).

None of them spends anything. Four groups:

- **The bug set** (``tests/fixtures/live_heal_agent``): twelve hard planted
  bugs in the hard set's manifest format. Per bug, in the real sandbox and
  through the heal probe's own shim: the own suite passes at the seed, on the
  reference fix and on the stored shallow patch; the hidden check fails at
  the seed for the manifest's reason and passes on the reference fix; the
  shallow patch fails it; the report's scenario fails ``RUNS`` of ``RUNS``
  times for the reported reason, passes on the reference fix, and on the
  shallow patch passes (fails, for a ``layered`` bug: fixing the reported
  crash only reveals the next defect).
- **The design pins**: the plan (the new bugs, then the 16 saturated bugs as
  regression), the caps summing to the pilot cap, the pre-registered gate,
  exactly two tools, the request shape, the fencing.
- **The tools and the loop**: the editor confined to the scratch copy (tests
  and the reproducer refused), ``run_reproducer``'s closed output (no judge,
  no timing), the capture rules, and the fixer loop on a scripted wire.
- **The live body dry** and the CI wiring (a guard that fails until the
  Lead applies ``ci.yml``'s and the corpus guards' patch).

Sandboxed tests skip when the host cannot isolate; ``REQUIRE_NETWORK_SANDBOX=1``
or ``REQUIRE_FS_SANDBOX=1`` (CI) turn the skip into a failure.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import cast

import httpx2
import pytest
from e2e.conftest import _sandbox_problem

from autonomous_ai_agents.clients.structured import Fence
from autonomous_ai_agents.execution.editor import EDITOR_TOOL, EDITOR_TOOL_NAME

from ..conftest import _CELL_MAX, TESTS_DIR, LiveRun
from . import heal_agent as agent
from . import test_heal_agent_live as live_agent
from .bounds import Json
from .harness import ExperimentClient
from .heal import (
    EFFORT,
    HARD_REPOS,
    REPOS,
    RUNS,
    SONNET,
    HealOutcome,
    HealRepo,
    Reason,
    Reproducer,
    RunResult,
    Sandbox,
    check_fix,
    check_reason,
    failing_tests,
    fix_request,
    overlay,
    read_report,
    read_tree,
    repro_request,
    scenario_reproducer,
    seed_tree,
    shallow_tree,
    solution_tree,
)
from .recorder import ExperimentRecorder
from .test_harness import host_key
from .test_heal import USAGE, DryStart, HealApi, _message, _repro_reply

__all__ = ["host_key"]  # the harness's fixture: the host key over the placeholder

BUGS = {bug.name: bug for bug in agent.HARD_BUGS}
BY_PLAN = {repo.name: repo for repo in agent.PLAN}
NAMES = sorted(BUGS)
SCENARIO = "tests/test_reported_scenario.py"
SERVICE_DIR = TESTS_DIR.parent
CI_WORKFLOW = TESTS_DIR.parents[2] / ".github" / "workflows" / "ci.yml"
LIVE_MODULE = "tests/live/experiments/test_heal_agent_live.py"


@pytest.fixture(scope="module")
def sandboxed() -> None:
    """Skip (or fail under REQUIRE_*) when this host cannot sandbox."""
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        if "1" in (
            os.environ.get("REQUIRE_NETWORK_SANDBOX"),
            os.environ.get("REQUIRE_FS_SANDBOX"),
        ):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(problem)


def _base(tmp_path: Path, name: str = "agent") -> Path:
    return Path(os.path.realpath(tmp_path)) / name


# ---------------------------------------------------------------------------
# The bug set
# ---------------------------------------------------------------------------


def test_the_manifest_lists_every_fixture_directory() -> None:
    root = agent.AGENT_DIR
    dirs = {p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert dirs - {"_hidden", "_solutions", "_shallow", "_repro"} == set(NAMES)
    for kept in ("_hidden", "_repro"):
        assert {p.name for p in (root / kept).iterdir()} == {f"{n}.py" for n in NAMES}
    for kept in ("_shallow", "_solutions"):
        assert {p.name for p in (root / kept).iterdir()} == set(NAMES), kept


def test_twelve_hard_bugs_of_the_planned_kinds_in_both_styles() -> None:
    bugs = agent.HARD_BUGS
    assert len(bugs) == 12 and agent.AGENT_DIR.name == "live_heal_agent"
    kinds = [bug.kind for bug in bugs]
    assert {k: kinds.count(k) for k in agent.AGENT_KINDS} == {
        "layered": 3,
        "multi_file": 3,
        "misleading_report": 2,
        "seed_dependent": 1,
        "order_dependent": 1,
        "shallow_trap": 2,
    }
    styles = [bug.report for bug in bugs]
    assert styles.count("traceback") == styles.count("symptom") == 6
    for bug in bugs:
        assert isinstance(bug, agent.AgentBug) and agent.is_new(bug)
        assert bug.hard and not bug.control and bug.root == agent.AGENT_DIR
        assert bug.path == agent.AGENT_DIR / bug.name
        assert bug.shallow == agent.AGENT_DIR / "_shallow" / bug.name
    others = {r.name for r in (*REPOS, *HARD_REPOS)}
    assert not others & set(NAMES)
    assert not any(agent.is_new(r) for r in (*REPOS, *HARD_REPOS))


def _entry(**changes: object) -> Json:
    entry: Json = {
        "name": "toy",
        "package": "toy",
        "kind": "layered",
        "report": "traceback",
        "exception": "builtins.ValueError",
        "frame": "toy.core.run",
        "message": "bad",
    }
    entry.update(changes)
    return entry


def test_a_well_formed_manifest_parses() -> None:
    (bug,) = agent.parse_agent_manifest({"version": 1, "repos": [_entry()]})
    assert (bug.name, bug.kind, bug.corpus, bug.frame) == (
        "toy",
        "layered",
        "hard",
        "toy.core.run",
    )
    assert bug.scenario == agent.AGENT_DIR / "_repro" / "toy.py"
    two = [_entry(), _entry(name="toy2", package="toy2", frame="toy2.core.run")]
    assert len(agent.parse_agent_manifest({"version": 1, "repos": two})) == 2


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"version": 2, "repos": []},
        {"version": 1, "repos": {}},
        {"version": 1, "repos": [], "extra": 1},
        {"version": 1, "repos": [_entry(kind="multi_file_x")]},
        {"version": 1, "repos": [_entry(kind="control_intended")]},
        {"version": 1, "repos": [_entry(report="email")]},
        {"version": 1, "repos": [_entry(name="Toy")]},
        {"version": 1, "repos": [_entry(frame="other.core.run")]},
        {"version": 1, "repos": [_entry(exception="ValueError")]},
        {"version": 1, "repos": [_entry(message="")]},
        {"version": 1, "repos": [{**_entry(), "extra": "x"}]},
        {"version": 1, "repos": [_entry(), _entry()]},
        {"version": 1, "repos": ["toy"]},
    ],
)
def test_a_malformed_manifest_is_refused(data: object) -> None:
    with pytest.raises(ValueError):
        agent.parse_agent_manifest(data)


@pytest.mark.parametrize("name", NAMES)
def test_the_bug_repo_is_well_formed(name: str) -> None:
    bug = BUGS[name]
    tree = seed_tree(bug)
    assert f"{bug.package}/__init__.py" in tree and "tests/__init__.py" in tree
    assert any(p.startswith("tests/test_") and p.endswith(".py") for p in tree)
    assert agent.REPORT_FILE not in tree and SCENARIO not in tree
    assert all(not p.endswith(".pyc") and "__pycache__" not in p for p in tree)
    report = read_report(bug)
    assert bug.exception.rsplit(".", 1)[1] in report and bug.message in report
    if bug.report == "traceback":
        assert "Traceback (most recent call last):" in report
        assert f"in {bug.frame.rsplit('.', 1)[1]}\n" in report
    else:
        assert "Traceback" not in report and "File " not in report
    assert scenario_reproducer(bug).path == SCENARIO
    assert sum(len(text) for text in tree.values()) <= agent.MAX_REPO_CHARS


@pytest.mark.parametrize("name", NAMES)
def test_the_patches_replace_package_files_only(name: str) -> None:
    """The reference fix and the shallow patch are whole package files the
    fix policy accepts, each a real change, and never the same change."""
    bug = BUGS[name]
    tree, fix, shallow = seed_tree(bug), solution_tree(bug), shallow_tree(bug)
    probe = Reproducer("tests/test_probe_only.py", "")
    for patch in (fix, shallow):
        assert patch
        assert check_fix(list(patch.items()), bug, tree, probe) == (patch, [])
        assert all(patch[p] != tree[p] for p in patch)
    assert overlay(tree, fix) != overlay(tree, shallow)


@pytest.mark.usefixtures("sandboxed")
@pytest.mark.parametrize("name", NAMES)
def test_the_bug_holds_in_the_sandbox(name: str, tmp_path: Path) -> None:
    bug = BUGS[name]
    sandbox = Sandbox(_base(tmp_path))
    seed = seed_tree(bug)
    fixed, shallow = overlay(seed, solution_tree(bug)), overlay(seed, shallow_tree(bug))
    scenario = scenario_reproducer(bug)

    own = sandbox.suite(seed, bug.package)
    assert own.status == "passed" and own.tests >= 2, own
    for tree in (fixed, shallow):
        after = sandbox.suite(tree, bug.package)
        assert after.status == "passed" and after.tests == own.tests, after
    hidden = sandbox.hidden(seed, bug)
    assert hidden.status == "failed", hidden
    assert any(
        r.type == bug.exception and r.frame == bug.frame and bug.message in r.message
        for r in hidden.reasons
    ), hidden.reasons
    assert sandbox.hidden(fixed, bug).status == "passed"
    trapped = sandbox.hidden(shallow, bug)
    assert trapped.status == "failed" and failing_tests(trapped), trapped

    check = check_reason(sandbox.reproducer(seed, bug.package, scenario), bug)
    assert check.reason_match and check.consistent, check
    (on_fix,) = sandbox.reproducer(fixed, bug.package, scenario, times=1)
    assert on_fix.status == "passed", on_fix
    (on_shallow,) = sandbox.reproducer(shallow, bug.package, scenario, times=1)
    layered = bug.kind == agent.LAYERED
    assert on_shallow.status == ("failed" if layered else "passed"), on_shallow
    if layered:  # the next defect shows: not the reported reason any more
        assert not check_reason([on_shallow] * RUNS, bug).type_match, on_shallow


INTERMITTENT = """import unittest

from retryplan.schedule import DeadlineError, plan


class Intermittent(unittest.TestCase):
    def test_some_seeds_fail_and_most_do_not(self):
        failed = 0
        for seed in range(200):
            try:
                plan(6, 4, 8, 48, seed=seed)
            except DeadlineError:
                failed += 1
        self.assertTrue(20 <= failed <= 100, failed)
"""

ORDER = """import unittest

from confload.cache import forget
from confload.loader import TableError, load_table

US = "sku,price,stock\\nA1,1.50,3\\n"
EU = "sku;price;stock\\nA1;1,50;3\\n"


class OrderDependent(unittest.TestCase):
    def setUp(self):
        forget()

    def test_alone_it_loads(self):
        self.assertEqual(len(load_table("eu_prices.csv", EU, ["sku", "price", "stock"])), 2)

    def test_after_another_csv_it_fails(self):
        load_table("us_prices.csv", US, ["sku", "price", "stock"])
        with self.assertRaises(TableError):
            load_table("eu_prices.csv", EU, ["sku", "price", "stock"])
"""


@pytest.mark.usefixtures("sandboxed")
@pytest.mark.parametrize(
    ("name", "module", "text"),
    [("retryplan", "test_intermittent", INTERMITTENT), ("confload", "test_order", ORDER)],
)  # fmt: skip
def test_the_flaky_symptoms_need_their_trigger(
    name: str, module: str, text: str, tmp_path: Path
) -> None:
    """retryplan fails for some seeds only; confload only after another file
    of its extension was loaded: a reproducer must pin the trigger."""
    bug = BUGS[name]
    assert bug.kind in ("seed_dependent", "order_dependent")
    tree = {**seed_tree(bug), f"tests/{module}.py": text}
    result = Sandbox(_base(tmp_path)).execute(
        tree, bug.package, "names", [f"tests.{module}"]
    )
    assert result.status == "passed" and result.tests >= 1, result


# ---------------------------------------------------------------------------
# The plan, the caps and the gate (pre-registered)
# ---------------------------------------------------------------------------


def test_the_plan_is_the_new_bugs_then_the_sixteen_saturated_ones() -> None:
    regression = [r for r in (*REPOS, *HARD_REPOS) if not r.control]
    assert len(regression) == 16 and agent.REGRESSION == tuple(regression)
    assert agent.PLAN == (*agent.HARD_BUGS, *regression)
    names = [r.name for r in agent.PLAN]
    assert len(set(names)) == len(names) == 28
    assert [agent.group_of(r) for r in agent.PLAN].count("hard") == 12
    assert agent.group_of(REPOS[0]) == agent.group_of(HARD_REPOS[0]) == "regression"


def test_the_bug_caps_add_up_to_the_pilot_cap() -> None:
    assert agent.PILOT_CAP_USD == 8.0  # spec-wave2 7c, A1: cap 8, expected 3-6
    assert agent.bug_cap(agent.HARD_BUGS[0]) == agent.HARD_BUG_CAP_USD
    assert agent.bug_cap(REPOS[0]) == agent.REGRESSION_BUG_CAP_USD
    assert agent.bug_cap(HARD_REPOS[0]) == agent.REGRESSION_BUG_CAP_USD
    assert agent.agent_need() == pytest.approx(agent.PILOT_CAP_USD)
    assert agent.agent_need(agent.HARD_BUGS) == pytest.approx(12 * 0.40)
    assert agent.agent_need(agent.PLAN[:1]) == pytest.approx(0.40)
    assert agent.HARD_BUG_CAP_USD < agent.MAX_USD_PER_BUG  # never past the gate
    assert agent.agent_need() <= 150.0  # live-smoke's ceiling


def test_the_gate_and_the_loop_bounds_are_pre_registered() -> None:
    assert (agent.MIN_EXTRA_FIXES, agent.MAX_TEST_EDITS) == (2, 0)
    assert agent.MAX_USD_PER_BUG == 0.50
    assert (agent.MAX_TURNS, agent.MAX_TOOL_CALLS) == (12, 24)
    assert agent.TOOL_RUNS == RUNS == 5
    assert (SONNET, EFFORT) == ("claude-sonnet-5-5", "medium")
    for words in ("measures", "feeds", "cheapest arm", "gate", "O18"):
        assert words in agent.DECISION, words
    assert agent.SUITE == "heal-agent"


@pytest.mark.parametrize("name", [repo.name for repo in agent.PLAN])
def test_every_request_fits_the_bug_cap_at_its_worst(name: str, host_key: str) -> None:
    """With ``count_tokens`` failing (the byte bound, the largest), on every
    bug: request 1, request 2 (a 3,000-character reproducer) and the
    fixer's first turn each fit the bug's cap; on a new bug all three at
    their worst together still do, so arm B always gets to start there."""
    repo = BY_PLAN[name]
    api = HealApi()
    api.count_status = 500
    client = ExperimentClient(LiveRun("dry", 100.0, wire=httpx2.MockTransport(api)))
    tree, report = seed_tree(repo), read_report(repo)
    repro = Reproducer("tests/test_reported_case.py", "x" * 3000)
    first = client.estimate(repro_request(repo, tree, report, Fence.new())[0])
    second = client.estimate(fix_request(repo, tree, report, repro, Fence.new())[0])
    text, _ = agent.opening(repo, tree, report, repro, Fence.new())
    turn = client.estimate(agent.fixer_body(repo, [{"role": "user", "content": text}]))
    cap = agent.bug_cap(repo)
    assert max(first, second, turn) <= cap
    if agent.is_new(repo):
        assert first + second + turn <= cap
    assert api.sent() == []


# ---------------------------------------------------------------------------
# The requests and the tools
# ---------------------------------------------------------------------------

MIDDLE = agent.HARD_BUGS[0]
REPRO = Reproducer("tests/test_reported.py", "import unittest\n")


def test_the_fixer_offers_exactly_two_tools() -> None:
    assert [t["name"] for t in agent.TOOLS] == [EDITOR_TOOL_NAME, "run_reproducer"]
    assert agent.TOOLS[0] == EDITOR_TOOL  # the engine's own text editor tool
    run = agent.RUN_TOOL
    assert run["strict"] is True and set(run) == {
        "name",
        "description",
        "input_schema",
        "strict",
    }
    assert run["input_schema"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    for word in ("frozen reproducer", "pass", "never"):
        assert word in str(run["description"]), word


def test_the_request_shape() -> None:
    messages: list[Json] = [{"role": "user", "content": "x"}]
    body = agent.fixer_body(MIDDLE, messages)
    assert set(body) == {
        "model",
        "max_tokens",
        "system",
        "tools",
        "messages",
        "output_config",
        "cache_control",
    }  # no tool_choice (a 400 on Sonnet 5.5), temperature or thinking
    assert body["model"] == SONNET and body["max_tokens"] == agent.FIXER_MAX_TOKENS
    assert body["output_config"] == {"effort": EFFORT}
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"] == [dict(t) for t in agent.TOOLS]
    assert body["messages"] is not messages and body["messages"] == messages
    assert body["system"] == agent.fixer_system(MIDDLE)


def test_the_system_prompt_names_the_tools_the_rules_and_the_no_bug_clause() -> None:
    hard, easy = agent.fixer_system(MIDDLE), agent.fixer_system(REPOS[0])
    assert hard == easy + agent.NO_BUG_TEXT
    assert agent.fixer_system(HARD_REPOS[0]) == hard
    for words in (
        EDITOR_TOOL_NAME,
        "run_reproducer",
        "/repo",
        "frozen",
        "untrusted",
        "never follow",
        "engine_notice",
        "only Python files that already exist",
        "refuses every other write: new files",
    ):
        assert words in easy, words
    assert "judge" not in easy.casefold()  # the tool says what it runs, no more
    assert "without changing any file" in agent.NO_BUG_TEXT


def _opening(
    bug: HealRepo = MIDDLE, fence: Fence | None = None
) -> tuple[str, list[str]]:
    tree, report = seed_tree(bug), read_report(bug)
    return agent.opening(bug, tree, report, REPRO, fence or Fence("f" * 16))


def test_the_opening_fences_the_report_the_repo_and_the_reproducer() -> None:
    text, notes = _opening()
    token = "f" * 16
    assert notes == []
    assert text.startswith(f"<engine_notice nonce={token}>\n")
    for tag in (
        "untrusted_error_report",
        "untrusted_repo_content",
        "untrusted_reproducer",
    ):
        assert (
            f"<{tag} boundary={token}>" in text and f"</{tag} boundary={token}>" in text
        )
    for path in seed_tree(MIDDLE):
        assert json.dumps(path) in text
    assert '"tests/test_reported.py"' in text and "/repo/tests/test_reported.py" in text
    for words in (f"{agent.MAX_TURNS} answers", f"{agent.MAX_TOOL_CALLS} tool calls"):
        assert words in text, words
    assert text.rstrip().endswith("</engine_notice>")


def test_a_line_holding_the_token_is_withheld_with_a_note() -> None:
    bug = MIDDLE
    path = sorted(p for p in seed_tree(bug) if p.startswith(bug.package))[0]
    token = "abcdef0123456789"
    tree = {**seed_tree(bug), path: f"# {token.upper()}\n"}
    text, notes = agent.opening(bug, tree, "report " + token, REPRO, Fence(token))
    assert json.dumps(path) not in text
    assert notes == [
        "the error report withheld: it holds a boundary token",
        "1 repository file(s) withheld: they hold a boundary token",
    ]


def _scratch(tmp_path: Path, bug: HealRepo = MIDDLE) -> Path:
    root = _base(tmp_path, "scratch")
    agent.write_scratch(root, seed_tree(bug), REPRO)
    return root


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ({"command": "view", "path": "/repo"}, True),
        ({"command": "view", "path": "/repo/tests/test_reported.py"}, True),
        ({"command": "create", "path": "/repo/tests/test_reported.py", "file_text": "x"}, False),
        ({"command": "str_replace", "path": "/repo/tests/test_reported.py", "old_str": "unittest", "new_str": "os"}, False),
        ({"command": "insert", "path": "/repo/tests/__init__.py", "insert_line": 0, "insert_text": "x"}, False),
        ({"command": "create", "path": "/repo/test_x.py", "file_text": "x"}, False),
        ({"command": "create", "path": "/repo/../escape.py", "file_text": "x"}, False),
        ({"command": "view", "path": "/etc/passwd"}, False),
        ({"command": "view", "path": "/repo/.git/config"}, False),
        ({"command": "undo_edit", "path": "/repo/x.py"}, False),
        ({"command": "create", "path": f"/repo/{MIDDLE.package}/helper.py", "file_text": "X = 1\n"}, False),
        ({"command": "create", "path": f"/repo/{MIDDLE.package}/data.txt", "file_text": "x"}, False),
        ({"command": "create", "path": "/repo/README.md", "file_text": "x"}, False),
        ({"command": "create", "path": "/repo/helper.py", "file_text": "X = 1\n"}, False),
    ],
)  # fmt: skip
def test_the_editor_is_confined_to_the_scratch_copy(
    command: Json, allowed: bool, tmp_path: Path
) -> None:
    root = _scratch(tmp_path)
    before = read_tree(root)
    outcome = _files(root).execute(command)
    assert outcome.is_error is not allowed, outcome
    assert read_tree(root) == before  # nothing refused was written
    assert str(root) not in outcome.content


def test_the_editor_writes_package_files(tmp_path: Path) -> None:
    root = _scratch(tmp_path)
    path, text = next(iter(solution_tree(MIDDLE).items()))
    files = _files(root)
    outcome = files.execute(
        {"command": "create", "path": f"/repo/{path}", "file_text": text}
    )
    assert not outcome.is_error and read_tree(root)[path] == text
    assert agent.EDITOR_LIMITS.max_files == agent.FIX_MAX_FILES


def _files(root: Path, bug: HealRepo = MIDDLE) -> agent.ScratchFiles:
    return agent.scratch_editor(root, bug, seed_tree(bug), REPRO)


@pytest.mark.parametrize(
    "command",
    [
        {"command": "create", "path": f"/repo/{MIDDLE.package}/helper.py", "file_text": "X = 1\n"},
        {"command": "create", "path": f"/repo/{MIDDLE.package}/sub/new.py", "file_text": "X = 1\n"},
        {"command": "create", "path": "/repo/README.md", "file_text": "x"},
        {"command": "insert", "path": "/repo/pyproject.toml", "insert_line": 0, "insert_text": "x"},
    ],
)  # fmt: skip
def test_the_editor_refuses_every_write_the_capture_rules_would_refuse(
    command: Json, tmp_path: Path
) -> None:
    """A write the capture rules refuse at the end (a new file, a file
    outside the package) is refused when it is made, with the rule, so a
    good edit beside it is not lost whole after the loop."""
    root = _scratch(tmp_path)
    before = read_tree(root)
    outcome = _files(root).execute(command)
    assert outcome.is_error and read_tree(root) == before
    assert outcome.content.startswith("refused: ")
    assert f"only Python files that already exist under {MIDDLE.package}/" in (
        outcome.content
    )
    assert str(root) not in outcome.content


def test_the_editor_leaves_paths_it_cannot_place_to_the_engine_editor(
    tmp_path: Path,
) -> None:
    """A path outside /repo or with '..' gets the engine editor's own
    refusal (the confinement adds rules, it never loosens one)."""
    root = _scratch(tmp_path)
    files = _files(root)
    for path in ("/etc/x.py", "/repo/../x.py", 7):
        outcome = files.execute({"command": "create", "path": path, "file_text": "x"})
        assert outcome.is_error and not outcome.content.startswith("refused: ")


def test_the_prompt_says_which_writes_the_editor_refuses() -> None:
    system = agent.fixer_system(MIDDLE)
    assert "already exist" in system and "new files" in system


def _run(status: str = "failed", *reasons: Reason, detail: str = "") -> RunResult:
    return RunResult(status, 1, reasons, 0, detail)  # type: ignore[arg-type]


ERR = Reason(
    "error",
    "tests.test_reported.T.test_x",
    "builtins.ValueError",
    "bad",
    "toy.core.run",
    None,
)


def test_the_run_output_is_closed_and_bounded() -> None:
    passed = RunResult("passed", 1, (), 0)
    lines = agent.run_lines((passed,) * RUNS, b"", REPRO)
    assert [json.loads(line) for line in lines] == [
        {"reproducer": REPRO.path, "runs": RUNS, "passed": RUNS, "verdict": "pass"}
    ]
    many = tuple(
        _run(
            "failed",
            Reason("error", f"t{i}", "builtins.ValueError", "m" * 900, None, None),
        )
        for i in range(RUNS)
    )
    tail = ("x" * 5000 + "TAIL").encode()
    lines = agent.run_lines(
        (*many[:2], _run("no_result", detail="d" * 900), *many[3:]), tail, REPRO
    )
    head, *rest = (json.loads(line) for line in lines)
    assert head == {
        "reproducer": REPRO.path,
        "runs": RUNS,
        "passed": 0,
        "verdict": "fail",
    }
    crashes = [r for r in rest if "crash" in r]
    assert len(crashes) == agent.MAX_RUN_REASONS
    assert all(set(c["crash"]) == {"type", "message", "test", "frame"} for c in crashes)
    assert all(len(c["crash"]["message"]) <= 200 for c in crashes)
    statuses = [r for r in rest if "run_status" in r]
    assert statuses == [{"run_status": "no_result", "detail": "d" * 200}]
    (stderr,) = [r for r in rest if "stderr_tail" in r]
    assert stderr["stderr_tail"].endswith("TAIL")
    assert len(stderr["stderr_tail"]) == agent.STDERR_TAIL_CHARS
    keys = {k for line in lines for k in json.loads(line)}
    assert keys <= {
        "reproducer",
        "runs",
        "passed",
        "verdict",
        "crash",
        "run_status",
        "detail",
        "stderr_tail",
    }
    for word in ("wall", "time", "hidden", "suite", "judge", "second", "duration"):
        assert not any(word in k for k in keys), word


def test_the_run_result_is_fenced_and_withholds_a_line_holding_the_token() -> None:
    fence = Fence("abcdef0123456789")
    lines = agent.run_lines(
        (_run("failed", ERR),) * RUNS, b"print ABCDEF0123456789", REPRO
    )
    text, withheld, leaked = agent.run_result_text(lines, fence)
    assert leaked == 0
    assert withheld == 1 and "ABCDEF" not in text
    assert text.startswith(f"<untrusted_run_output boundary={fence.token}>\n")
    assert text.endswith(f"</untrusted_run_output boundary={fence.token}>")
    assert "withheld" in text


def test_the_judge_markers_name_engine_owned_text_only() -> None:
    bug = BUGS["bookings"]
    report = read_report(bug)
    markers = agent.judge_markers(bug, (report,))
    assert str(agent.AGENT_DIR.parent) in markers
    assert {"_hidden", "_solutions", "_shallow", "live_heal"} <= set(markers)
    hidden = bug.hidden.read_text(encoding="utf-8")
    assert "def test_the_nights_exclude_the_departure_day(self):" in markers
    shown = {
        line.strip() for text in seed_tree(bug).values() for line in text.splitlines()
    }
    assert not shown & set(markers)
    assert all(
        m in hidden
        or m in str(agent.AGENT_DIR.parent)
        or m in agent.PATH_MARKERS
        or json.loads(f'"{m}"') in hidden
        for m in markers
    )


def test_run_output_carrying_a_judge_marker_is_withheld() -> None:
    fence = Fence("abcdef0123456789")
    bug = BUGS["bookings"]
    markers = agent.judge_markers(bug)
    leak = b"def test_back_to_back_stays(self):\n    room = Room(12, 8000)"
    lines = agent.run_lines((_run("failed", ERR),) * RUNS, leak, REPRO)
    text, withheld, leaked = agent.run_result_text(lines, fence, markers)
    assert (withheld, leaked) == (1, 1) and "back_to_back" not in text
    path = f"{agent.AGENT_DIR}/_hidden/bookings.py"
    message = Reason(
        "error", "t", "builtins.OSError", f"no such file: {path!r}", None, None
    )
    lines = agent.run_lines((_run("failed", message),) * RUNS, b"", REPRO)
    assert agent.run_result_text(lines, fence, markers)[1:] == (1, 1)
    files = agent.path_markers(bug)
    assert set(files) < set(markers)  # a fix is checked for paths only
    assert agent.judge_refs({"bookings/stay.py": f"open({path!r})"}, files) == (
        "bookings/stay.py",
    )


@pytest.mark.parametrize("name", sorted(BY_PLAN))
def test_no_true_or_shallow_fix_names_an_engine_owned_file(name: str) -> None:
    """A fix file is refused as reading a hidden check only when it names
    an engine-owned path: no stored fix of any planned bug trips it (a
    content line of the hidden check, an import line among them, would)."""
    bug = BY_PLAN[name]
    markers = agent.path_markers(bug)
    assert agent.judge_refs(solution_tree(bug), markers) == ()
    if agent.is_new(bug):
        assert agent.judge_refs(shallow_tree(bug), markers) == ()


def test_a_fix_holding_a_hidden_check_line_is_captured(
    tmp_path: Path, host_key: str
) -> None:
    """confload's shallow patch holds an import line its hidden check
    also holds: it is captured as a fix (measured by the judges), not
    refused as a leak."""
    bug = BUGS["confload"]
    shallow = shallow_tree(bug)
    edits = [_create(p, t, f"toolu_{i}") for i, (p, t) in enumerate(shallow.items())]
    stats, fixer, _, _ = _fixer(tmp_path, _turn(*edits), DONE, bug=bug)
    assert any(
        line.strip() in agent.judge_markers(bug)
        for text in shallow.values()
        for line in text.splitlines()
    )  # the content markers (run output only) would hit it
    fix, flagged = fixer.capture()
    assert (fix.outcome, dict(fix.files), flagged) == ("ok", shallow, ())
    assert stats.judge_refs == () and stats.writes == len(edits)


def test_a_refused_new_file_keeps_the_other_edits(
    tmp_path: Path, host_key: str
) -> None:
    bug = MIDDLE
    solution = solution_tree(bug)
    edits = [_create(p, t, f"toolu_{i}") for i, (p, t) in enumerate(solution.items())]
    helper = f"{bug.package}/helper.py"
    stats, fixer, api, _ = _fixer(
        tmp_path, _turn(_create(helper, "X = 1\n", "toolu_new"), *edits), DONE
    )
    new, *rest = _tool_results(api.sent()[1])
    assert new["is_error"] is True and "already exist" in json.dumps(new)
    assert all(r["is_error"] is False for r in rest) and len(rest) == len(edits)
    assert (stats.refused_writes, stats.writes, stats.test_write_attempts) == (
        1,
        len(edits),
        0,
    )
    assert helper not in read_tree(fixer.scratch)
    fix, flagged = fixer.capture()
    assert (fix.outcome, dict(fix.files), flagged) == ("ok", solution, ())


def test_the_capture_rules() -> None:
    bug = MIDDLE
    seed = seed_tree(bug)
    path, text = next(iter(solution_tree(bug).items()))
    base = {**seed, REPRO.path: REPRO.content}
    fix, flagged = agent.capture(seed, base, bug, REPRO)
    assert (fix.outcome, dict(fix.files), flagged) == ("empty", {}, ())
    fix, flagged = agent.capture(seed, {**base, path: text}, bug, REPRO)
    assert (fix.outcome, dict(fix.files), flagged) == ("ok", {path: text}, ())
    test = next(p for p in seed if p.startswith("tests/test_"))
    for changed in (
        {**base, REPRO.path: "import os\n"},
        {**base, test: "x = 1\n", path: text},
        {k: v for k, v in base.items() if k != REPRO.path},
    ):
        fix, flagged = agent.capture(seed, changed, bug, REPRO)
        assert fix.outcome == "refused" and fix.files == {} and len(flagged) == 1
    fix, flagged = agent.capture(
        seed, {**base, f"{bug.package}/extra.py": "x\n"}, bug, REPRO
    )
    assert fix.outcome == "refused" and flagged == ()
    assert "not an existing file" in fix.refused[0]


# ---------------------------------------------------------------------------
# The fixer loop on a scripted wire
# ---------------------------------------------------------------------------


def _turn(*blocks: Json, stop: str = "tool_use") -> Json:
    return {
        "id": "msg_01Fixer",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": list(blocks),
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": USAGE,
    }


def _use(name: str, value: Json, ident: str) -> Json:
    return {"type": "tool_use", "id": ident, "name": name, "input": value}


def _text(text: str) -> Json:
    return {"type": "text", "text": text}


def _create(path: str, text: str, ident: str = "toolu_create") -> Json:
    return _use(
        EDITOR_TOOL_NAME,
        {"command": "create", "path": f"/repo/{path}", "file_text": text},
        ident,
    )


RUN_USE = _use("run_reproducer", {}, "toolu_run")
DONE = _turn(_text("Fixed the root cause."), stop="end_turn")


def _fixer(
    tmp_path: Path,
    *replies: Json,
    bug: HealRepo = MIDDLE,
    repro: Reproducer | None = None,
    cap: float = 1.0,
) -> tuple[agent.FixerStats, agent.Fixer, HealApi, LiveRun]:
    api = HealApi(*replies)
    run = LiveRun("dry", cap, wire=httpx2.MockTransport(api))
    reproducer = repro or scenario_reproducer(bug)
    with ExperimentClient(run) as client:
        fixer = agent.Fixer(
            client, bug, seed_tree(bug), read_report(bug), reproducer, _base(tmp_path)
        )
        stats = fixer.run()
    return stats, fixer, api, run


def _tool_results(body: Json) -> list[Json]:
    last = cast(list[Json], body["messages"])[-1]
    return [
        b for b in cast(list[Json], last["content"]) if b.get("type") == "tool_result"
    ]


@pytest.mark.usefixtures("sandboxed")
def test_the_fixer_heals_a_bug_dry(tmp_path: Path, host_key: str) -> None:
    bug = MIDDLE
    (path, text), *more = solution_tree(bug).items()
    edits = [
        _create(p, t, f"toolu_{i}") for i, (p, t) in enumerate([(path, text), *more])
    ]
    stats, fixer, api, run = _fixer(
        tmp_path,
        _turn(_text("Run it first."), RUN_USE),
        _turn(*edits),
        _turn(RUN_USE),
        DONE,
    )
    assert (stats.stop, stats.turns, stats.runs_called) == ("done", 4, 2)
    assert (stats.writes, stats.refused_writes, stats.test_write_attempts) == (
        len(edits),
        0,
        0,
    )
    assert stats.last_run_pass is True and stats.cost_usd == pytest.approx(
        run.spent_usd
    )
    bodies = api.sent()
    assert len(bodies) == 4 and len(run.records) == 4
    for earlier, later in zip(bodies, bodies[1:], strict=False):  # append-only
        sent = cast(list[Json], earlier["messages"])
        assert cast(list[Json], later["messages"])[: len(sent)] == sent
    first = _tool_results(bodies[1])
    assert len(first) == 1 and '"verdict": "fail"' in str(first[0]["content"])
    assert first[0]["is_error"] is False
    assert len(_tool_results(bodies[2])) == len(edits)
    assert '"verdict": "pass"' in str(_tool_results(bodies[3])[0]["content"])
    for body in bodies:
        assert set(body) == set(agent.fixer_body(bug, []))
    fix, flagged = fixer.capture()
    assert (
        fix.outcome == "ok" and dict(fix.files) == solution_tree(bug) and flagged == ()
    )


@pytest.mark.usefixtures("sandboxed")
def test_a_write_to_the_reproducer_is_refused_counted_and_never_runs(
    tmp_path: Path, host_key: str
) -> None:
    bug = MIDDLE
    repro = scenario_reproducer(bug)
    stats, fixer, api, _ = _fixer(
        tmp_path,
        _turn(_create(repro.path, "import unittest\n")),
        _turn(RUN_USE),
        DONE,
        bug=bug,
        repro=repro,
    )
    assert (stats.test_write_attempts, stats.refused_writes, stats.writes) == (1, 1, 0)
    result = _tool_results(api.sent()[1])[0]
    assert result["is_error"] is True and "is the reproducer" in json.dumps(result)
    assert stats.last_run_pass is False  # the frozen reproducer still fails
    fix, flagged = fixer.capture()
    assert (fix.outcome, flagged) == ("empty", ())


def test_a_tool_result_holding_the_token_is_withheld(
    tmp_path: Path, host_key: str
) -> None:
    bug = MIDDLE
    token = "0123456789abcdef"
    path = f"{bug.package}/__init__.py"
    tree = {**seed_tree(bug), path: f'"""{token}"""\n'}
    api = HealApi(
        _turn(
            _use(
                EDITOR_TOOL_NAME,
                {"command": "view", "path": f"/repo/{path}"},
                "toolu_v",
            )
        ),
        _turn(
            _use(
                EDITOR_TOOL_NAME,
                {
                    "command": "str_replace",
                    "path": f"/repo/{path}",
                    "old_str": token,
                    "new_str": f"{token} again",
                },
                "toolu_s",
            )
        ),
        DONE,
    )
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(api))
    with ExperimentClient(run) as client:
        fixer = agent.Fixer(
            client,
            bug,
            tree,
            read_report(bug),
            REPRO,
            _base(tmp_path),
            fence=Fence(token),
        )
        stats = fixer.run()
    first, second, _ = api.sent()
    assert stats.notes == ["1 repository file(s) withheld: they hold a boundary token"]
    (viewed,) = _tool_results(second)
    assert viewed["is_error"] is True and "withheld" in str(viewed["content"])
    (written,) = _tool_results(api.sent()[2])
    assert written["is_error"] is False and "applied" in str(written["content"])
    assert stats.withheld == 2 and stats.writes == 1
    opened = cast(list[Json], first["messages"])[0]
    assert '{\\"path\\": \\"invoicer/tax.py\\"' in json.dumps(opened)  # the others
    assert f'{{\\"path\\": \\"{path}\\"' not in json.dumps(opened)


@pytest.mark.parametrize(
    ("path", "aimed"),
    [
        ("/repo/tests/test_reported.py", True),
        ("/repo/tests/__init__.py", True),
        ("/repo/pyproject.toml", True),
        ("/repo/invoicer/tax.py", False),
        ("/repo/../tests/x.py", False),
        ("tests/test_reported.py", False),
        (None, False),
    ],
)
def test_which_refused_writes_count_as_aimed_at_tests(
    path: object, aimed: bool
) -> None:
    assert agent._aims_at_tests(path, REPRO) is aimed


@pytest.mark.usefixtures("sandboxed")
def test_code_that_reads_the_hidden_check_is_withheld_and_refused(
    tmp_path: Path, host_key: str
) -> None:
    """The sandbox isolates writes, not reads: a fix that reads the hidden
    check and prints it gets that output withheld, and is refused."""
    bug = BUGS["bookings"]
    path = "bookings/stay.py"
    spy = (
        "import sys\n"
        f"sys.stderr.write(open({str(bug.hidden)!r}).read())\n" + seed_tree(bug)[path]
    )
    stats, fixer, api, _ = _fixer(
        tmp_path, _turn(_create(path, spy)), _turn(RUN_USE), DONE, bug=bug
    )
    result = str(_tool_results(api.sent()[2])[0]["content"])
    assert "HiddenCheck" not in result and "withheld" in result
    assert stats.leaks >= 1 and stats.runs_called == 1
    fix, flagged = fixer.capture()
    assert fix.outcome == "refused" and fix.files == {} and flagged == ()
    assert stats.judge_refs == (path,) and "engine-owned" in fix.refused[0]


@pytest.mark.parametrize(
    ("replies", "stop"),
    [
        ([_turn(_text("no"), stop="refusal")], "refusal"),
        ([_turn(_text("?"), stop="pause_turn")], "stopped_pause_turn"),
        ([_turn(stop="tool_use")], "error"),
        ([_turn(_text("only text"), stop="tool_use")], "error"),
        ([{"_status": 529, "type": "error", "error": {}}], "http_529"),
    ],
)
def test_the_loop_stops_on_what_it_cannot_continue(
    replies: list[Json], stop: str, tmp_path: Path, host_key: str
) -> None:
    stats, _, api, _ = _fixer(tmp_path, *replies)
    assert stats.stop == stop and len(api.sent()) == 1


def test_the_loop_stops_at_the_turn_limit_and_says_when_the_last_turn_comes(
    tmp_path: Path, host_key: str
) -> None:
    view = _turn(
        _use(EDITOR_TOOL_NAME, {"command": "view", "path": "/repo"}, "toolu_v")
    )
    stats, _, api, _ = _fixer(tmp_path, *[view] * agent.MAX_TURNS)
    bodies = api.sent()
    assert (stats.stop, stats.turns, len(bodies)) == (
        "max_turns",
        agent.MAX_TURNS,
        agent.MAX_TURNS,
    )
    last_user = json.dumps(cast(list[Json], bodies[-1]["messages"])[-1])
    assert "last turn" in last_user
    assert "last turn" not in json.dumps(cast(list[Json], bodies[-2]["messages"])[-1])


def test_tool_calls_past_the_limit_do_not_run(tmp_path: Path, host_key: str) -> None:
    view = _use(EDITOR_TOOL_NAME, {"command": "view", "path": "/repo"}, "toolu_v")
    many = _turn(
        *[{**view, "id": f"toolu_{i}"} for i in range(agent.MAX_TOOL_CALLS + 2)]
    )
    stats, _, api, _ = _fixer(tmp_path, many, _turn(view), DONE)
    results = _tool_results(api.sent()[1])
    refused = [r for r in results if "not run" in json.dumps(r)]
    assert len(results) == agent.MAX_TOOL_CALLS + 2 and len(refused) == 2
    assert stats.stop == "max_tool_calls" and stats.tool_calls == agent.MAX_TOOL_CALLS


def test_unknown_tools_bad_input_and_a_cut_off_answer(
    tmp_path: Path, host_key: str
) -> None:
    stats, _, api, _ = _fixer(
        tmp_path,
        _turn(
            _use("bash", {"command": "ls"}, "toolu_b"),
            _use("run_reproducer", {"x": 1}, "toolu_r"),
        ),
        _turn(
            _use(EDITOR_TOOL_NAME, {"command": "view", "path": "/repo"}, "toolu_c"),
            stop="max_tokens",
        ),
        DONE,
    )
    unknown, bad = _tool_results(api.sent()[1])
    assert unknown["is_error"] and "unknown tool" in json.dumps(unknown)
    assert bad["is_error"] and "no input" in json.dumps(bad)
    (cut,) = _tool_results(api.sent()[2])
    assert cut["is_error"] and "max_tokens" in json.dumps(cut)
    assert stats.stop == "done" and stats.runs_called == 0


def test_the_budget_stops_the_loop_before_a_turn_it_cannot_afford(
    tmp_path: Path, host_key: str
) -> None:
    stats, _, api, run = _fixer(tmp_path, DONE, cap=0.0001)
    assert stats.stop == "budget" and api.sent() == [] and run.records == []


# ---------------------------------------------------------------------------
# The live body dry, the summary and the gate
# ---------------------------------------------------------------------------


def _dry(
    tmp_path: Path, bug: HealRepo, *replies: Json
) -> tuple[agent.BugOutcome, HealApi, DryStart, ExperimentRecorder]:
    api = HealApi(*replies)
    start = DryStart(api)
    recorder = ExperimentRecorder("P1", {})
    outcome = live_agent.run_bug(start, bug, _base(tmp_path), recorder=recorder)
    return outcome, api, start, recorder


@pytest.mark.usefixtures("sandboxed")
def test_the_live_body_runs_both_arms_on_one_frozen_reproducer_dry(
    tmp_path: Path, host_key: str
) -> None:
    """Arm A (today's probe, unchanged) sends the shallow patch; arm B runs
    the reproducer, applies the reference fix and heals the bug."""
    bug = BUGS["bookings"]
    repro = scenario_reproducer(bug)
    name = repro.path.removeprefix("tests/")
    shallow = [{"path": p, "content": t} for p, t in shallow_tree(bug).items()]
    edits = [
        _create(p, t, f"toolu_{i}")
        for i, (p, t) in enumerate(solution_tree(bug).items())
    ]
    outcome, api, start, recorder = _dry(
        tmp_path,
        bug,
        _message(_repro_reply(name, repro.content)),
        _message(json.dumps({"files": shallow})),
        _turn(RUN_USE),
        _turn(*edits),
        _turn(RUN_USE),
        DONE,
    )
    (run,) = start.runs
    assert run.cap_usd == agent.HARD_BUG_CAP_USD and len(run.records) == 6
    a, b, stats = outcome.a, outcome.b, outcome.fixer
    assert a.valid and a.fix_applied and not a.healed and a.shallow_trap
    assert b is not None and stats is not None
    assert b.reproducer == a.reproducer and b.seed_runs == a.seed_runs  # shared
    assert b.healed and not b.hacked and b.shallow_trap is False
    assert stats.stop == "done" and stats.test_edits == ()
    assert outcome.b_cost_usd == pytest.approx(stats.cost_usd)
    assert a.cost_usd + stats.cost_usd == pytest.approx(run.spent_usd)
    bodies = api.sent()
    assert bodies[0]["system"] == heal_repro_system() and "tools" not in bodies[1]
    assert all(body["tools"] == [dict(t) for t in agent.TOOLS] for body in bodies[2:])
    rows = [(r.experiment, r.arm, r.item) for r in recorder.rows]
    assert rows == [("HEAL", "repo", bug.name), ("P1", "arm-b", bug.name)]
    assert run.notes[-3].startswith(f"P1 {bug.name} (hard): A healed n, B healed y ")
    assert all(len(note) <= _CELL_MAX for note in run.notes)


def heal_repro_system() -> str:
    from .heal import REPRO_SYSTEM

    return REPRO_SYSTEM


@pytest.mark.usefixtures("sandboxed")
def test_a_reproducer_that_passes_on_the_seed_runs_neither_arm(
    tmp_path: Path, host_key: str
) -> None:
    bug = MIDDLE
    passing = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        pass\n"
    outcome, api, start, _ = _dry(
        tmp_path, bug, _message(_repro_reply("test_ok.py", passing))
    )
    assert not outcome.a.valid and outcome.a.fix is None
    assert outcome.b is None and outcome.fixer is None and len(api.sent()) == 1
    assert "B not run" in start.runs[0].notes[-3]


def _outcome(
    bug: HealRepo, *, a: bool, b: bool | None, cost: float = 0.1, edits: int = 0,
    a_outcome: str = "ok",
) -> agent.BugOutcome:  # fmt: skip
    healed = RunResult("passed", 1, (), 0)
    broken = RunResult("failed", 1, (ERR,), 0)
    first = HealOutcome(bug, reproducer=REPRO, seed_runs=(broken,) * RUNS)
    first.repro_cost_usd = 0.01
    from .heal import Fix

    first.fix = Fix(a_outcome, {"x/y.py": "z"} if a_outcome == "ok" else {}, ())
    first.fix_repro_runs = (healed if a else broken,) * RUNS
    first.suite_run, first.hidden_run = healed, healed if a else broken
    if b is None:
        return agent.BugOutcome(bug, first, None, None)
    second = HealOutcome(bug, reproducer=REPRO, seed_runs=first.seed_runs)
    second.fix = Fix("ok", {"x/y.py": "w"}, ())
    second.fix_repro_runs = (healed if b else broken,) * RUNS
    second.suite_run, second.hidden_run = healed, healed if b else broken
    stats = agent.FixerStats(stop="done", cost_usd=cost)
    stats.test_edits = tuple(f"tests/t{i}.py" for i in range(edits))
    return agent.BugOutcome(bug, first, second, stats)


HARD = agent.HARD_BUGS
SAT = agent.REGRESSION


def test_the_gate_passes_with_two_more_hard_fixes_no_test_edit_and_the_cost() -> None:
    outcomes = [
        *(_outcome(bug, a=False, b=True) for bug in HARD[:2]),
        *(_outcome(bug, a=True, b=True) for bug in HARD[2:]),
        *(_outcome(bug, a=True, b=False) for bug in SAT[:1]),
        *(_outcome(bug, a=True, b=True) for bug in SAT[1:]),
    ]
    summary = agent.summarise_pilot(outcomes)
    assert (summary["hard_a_healed"], summary["hard_b_healed"]) == (10, 12)
    assert summary["extra_hard_fixes"] == 2 and summary["test_edits"] == 0
    assert summary["b_usd_per_hard_bug"] == pytest.approx(0.11)
    assert summary["regression_b_lost"] == 1
    assert summary["gate"] == "pass"
    notes = agent.pilot_notes(summary)
    assert notes[-1].startswith("P1 gate pass: B fixes 12/12 hard bugs, A 10/12 (+2,")
    assert all(len(note) <= _CELL_MAX for note in notes)


@pytest.mark.parametrize(
    ("change", "verdict"),
    [
        ({"b_wins": 1}, "fail"),
        ({"edits": 1}, "fail"),
        ({"cost": 0.60}, "fail"),
        ({"missing": 1}, "incomplete"),
        ({"a_unaffordable": 1}, "incomplete"),
    ],
)
def test_the_gate_fails_or_is_not_judged(
    change: dict[str, float], verdict: str
) -> None:
    wins = int(change.get("b_wins", 2))
    bugs = HARD[: len(HARD) - int(change.get("missing", 0))]
    outcomes = [
        _outcome(
            bug,
            a=i >= wins,
            b=True,
            cost=change.get("cost", 0.1),
            edits=int(change.get("edits", 0)) if i == 0 else 0,
            a_outcome="unaffordable"
            if i == 0 and change.get("a_unaffordable")
            else "ok",
        )
        for i, bug in enumerate(bugs)
    ]
    assert agent.summarise_pilot(outcomes)["gate"] == verdict


def test_bugs_without_a_valid_reproducer_count_as_unfixed_for_both_arms() -> None:
    no_repro = agent.BugOutcome(HARD[0], HealOutcome(HARD[0]), None, None)
    rest = [_outcome(bug, a=False, b=True) for bug in HARD[1:]]
    summary = agent.summarise_pilot([no_repro, *rest])
    assert (summary["hard_a_healed"], summary["hard_b_healed"]) == (0, 11)
    assert summary["hard_bugs"] == 12 and summary["hard_b_run"] == 11
    assert summary["gate"] == "pass"


def test_the_bug_note_fits_its_cell() -> None:
    bug = agent.BugOutcome(HARD[0], HealOutcome(HARD[0]), None, None)
    assert bug.note().startswith(f"P1 {HARD[0].name} (hard): A healed n, B not run")
    widest = _outcome(max(agent.PLAN, key=lambda r: len(r.name)), a=True, b=True)
    assert widest.fixer is not None
    widest.fixer.stop = "stopped_" + "x" * 40
    assert len(widest.note()) <= _CELL_MAX
    metrics = widest.metrics()
    assert (
        metrics["group"] == "regression" and metrics["fixer_stop"] == widest.fixer.stop
    )


# ---------------------------------------------------------------------------
# The live test and the CI wiring
# ---------------------------------------------------------------------------


def test_the_live_test_is_marked_live_and_takes_the_live_fixtures() -> None:
    assert live_agent.pytestmark == pytest.mark.live
    params = inspect.signature(live_agent.test_heal_agent_bug).parameters
    assert {"live", "live_isolation", "pilot_log"} <= set(params)
    source = inspect.getsource(live_agent.run_bug)
    assert "start(bug_cap(repo))" in source and "run_repo(" in source
    assert list(live_agent.BY_NAME) == [r.name for r in agent.PLAN]


def _ci_run_step() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Run live tests")
    return text[start : text.index("      - name: Upload live corpus", start)]


def test_ci_runs_the_pilot_as_its_own_suite_with_room_for_its_cap() -> None:
    """Fails until the Lead applies ``ci.yml``'s patch (A1-lead): the
    ``heal-agent`` suite runs this module alone, its need the pilot cap (D24),
    under Step 2's noise rule, with a timeout for 28 bugs."""
    step = _ci_run_step()
    suite = re.search(
        rf"^ *heal-agent\) paths=\({re.escape(LIVE_MODULE)}\); need=(\d+) ;;$",
        step,
        re.M,
    )
    assert suite is not None, "apply the A1-lead ci.yml patch"
    assert agent.agent_need() <= int(suite.group(1)) < agent.agent_need() + 1
    rule = re.search(r"^ *(.*\bheal-agent\b.*)\) noise_rule=(\w+) ;;$", step, re.M)
    assert rule is not None and rule.group(2) == "step2"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert f"inputs.suite == 'heal-agent' && {agent.JOB_MINUTES}" in text
    assert "heal-agent 8" in text  # named for the dispatcher
    assert (SERVICE_DIR / LIVE_MODULE).exists()


def test_the_corpus_guards_know_the_suite() -> None:
    """Fails until the Lead applies the corpus guards' patch (A1-lead)."""
    guards = (TESTS_DIR / "live" / "test_corpus_guards.py").read_text(encoding="utf-8")
    assert '"heal-agent",' in guards, "apply the A1-lead test_corpus_guards patch"
    assert '"heal-agent": heal_agent.agent_need(),' in guards
    assert f'"heal-agent": {agent.JOB_MINUTES},' in guards
