"""Offline guards of the evolution experiment (``tests/live/evolution.py``).

No ``live`` marker, no network, no key. They prove before a dollar is spent:

- the knobs parse strictly (10 rounds and the three repositories of the
  aimed OSS run's largest gains by default), every run's cap is the sum of
  the worst cases of the requests it may send, and the suite need is the
  sum of the caps, inside live-smoke's 150 USD ceiling;
- the generator's prompt bound holds with the largest facts an OSS clone
  can give plus the largest history, and the history reaches the
  generator as plain, capped text inside the untrusted fence, the newest
  rounds kept first;
- the clone moves to the engine's own delivered commit only (a fast-forward
  of ``main`` with the hardened git helper, nothing else changed), and
  anything else is refused before git moves;
- the round wiring is the production one on Sonnet 5.5 alone; the driver
  stops after two consecutive empty rounds (a round without an efficiency
  idea is empty), and only then;
- the final re-test measures the original base against the final tip with
  the engine's own ABAB phases and gain judge (a fake measurer here, the
  real one in the slow rehearsal), leaves the clone as it found it, and
  every row, note and summary figure is what the decision reads.

Fakes and what they stand for: ``FakeSteps`` stands for ``LiveSteps`` (phase
1 plus generation, the engine loop, the move, the re-test); ``Wire`` and
``EngineWire`` for the Anthropic API; ``fake_measure`` for
``measure.measure_abab`` (the real sandboxed launches); ``LOCAL`` (a
``file://`` git policy) for GitHub over https.
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import httpx2
import pytest
from e2e.conftest import (
    UNTOUCHED_REFS,
    Isolation,
    Launch,
    LaunchLog,
    UserRepo,
    _sandbox_problem,
)

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import EFFORT_LEVELS, settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    CandidateModule,
    ChangeClass,
    Combination,
    Delivery,
    DeliveryKind,
    Direction,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    ObjectiveKind,
    Project,
    ProjectUnderstanding,
    RunStats,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Workload,
    new_id,
)
from autonomous_ai_agents.execution.editor import EDITOR_TOOL_NAME
from autonomous_ai_agents.execution.measure import AbabMeasured, Phase, measure_abab
from autonomous_ai_agents.execution.procrun import RunFailure
from autonomous_ai_agents.execution.profiler import MAX_HOTSPOTS, MAX_SYMBOL_CHARS
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    MAX_TITLE_CHARS,
    generate_hypotheses,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.state import initial_state

from . import evolution as evo
from .conftest import TESTS_DIR, LiveRun, RequestRecord, guardrails, restore_host_key
from .corpus import outcome_of, settings_trial_budget
from .discovery import (
    PHASE_ONE_CAP_USD,
    PHASE_ONE_WORST_USD,
    SONNET,
    ArmResult,
    RepoFacts,
    worst_usd,
)
from .discovery_ab import AB_ARM
from .discovery_io import ResultsSink
from .oss import (
    OSS_CORPUS,
    OSS_RUN_CAP_USD,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    prepare_repo,
)

LIVE_DIR = TESTS_DIR / "live"
CAP_CEILING_USD = 150  # live-smoke's suite_cap_usd ceiling
EVOLVE_NEED = 103.5  # 3 repos x 10 rounds x (0.45 + 3.00); the Lead copies it
LOCAL = GitPolicy(allow=re.compile(r"file:///[^\s?#]+\.git"), protocols="file")
"""Local bare repositories over file://: injected by these tests only."""
REQUIRED = Isolation("required", None)
_CLEAN_GIT = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Engine",
    "GIT_AUTHOR_EMAIL": "engine@example.invalid",
    "GIT_COMMITTER_NAME": "Engine",
    "GIT_COMMITTER_EMAIL": "engine@example.invalid",
}
Json = dict[str, Any]

# ---------------------------------------------------------------------------
# Knobs, caps and the suite need
# ---------------------------------------------------------------------------


def test_the_plan_parses_strictly_before_any_spend() -> None:
    assert evo.evolve_plan({}) == evo.EvolvePlan(
        rounds=10, run_cap=3.0, repos=evo.EVOLVE_REPOS
    )
    assert (evo.EVOLVE_ROUNDS, evo.EVOLVE_MAX_ROUNDS) == (10, 10)
    for rounds in ("1", "2", "9", "10"):
        assert evo.evolve_plan({evo.ROUNDS_ENV: rounds}).rounds == int(rounds)
    for value in ("0", "11", "3.0", " 3", "", "three", "\u0663"):
        with pytest.raises(ValueError, match=evo.ROUNDS_ENV):
            evo.evolve_plan({evo.ROUNDS_ENV: value})
    assert evo.evolve_plan({evo.RUN_CAP_ENV: "5"}).run_cap == OSS_RUN_CAP_USD
    assert evo.evolve_plan({evo.RUN_CAP_ENV: "2.5"}).run_cap == 2.5
    for value in ("0", "-1", "nan", "inf", "5.01", " 1", "x"):
        with pytest.raises(ValueError, match=evo.RUN_CAP_ENV):
            evo.evolve_plan({evo.RUN_CAP_ENV: value})


def test_the_default_repos_are_the_aimed_runs_largest_gains() -> None:
    """Run 40061541473 delivered tabulate 14.3 %, tomli 13.3 %, markdown
    10.2 %, idna 10.1 %, sqlparse 4.0 %, mistune 3.2 %: the top three."""
    assert evo.EVOLVE_DEFAULT_REPOS == ("tabulate", "tomli", "markdown")
    assert [r.name for r in evo.EVOLVE_REPOS] == list(evo.EVOLVE_DEFAULT_REPOS)
    assert all(r in OSS_CORPUS for r in evo.EVOLVE_REPOS)
    assert evo.evolve_repos({}) == evo.EVOLVE_REPOS
    picked = evo.evolve_repos({evo.REPOS_ENV: "idna,tabulate"})
    assert [r.name for r in picked] == ["idna", "tabulate"]  # in the order given
    every = ",".join(r.name for r in OSS_CORPUS)
    assert evo.evolve_repos({evo.REPOS_ENV: every}) == OSS_CORPUS
    for value in ("", "tabulate,", "tabulate,tabulate", "Tabulate", " tomli", "x"):
        with pytest.raises(ValueError, match=evo.REPOS_ENV):
            evo.evolve_plan({evo.REPOS_ENV: value})


def test_the_generation_run_cap_is_the_sum_of_its_worst_cases() -> None:
    """Phase 1 (one understand request) and the one generation request, at
    their worst on Sonnet 5.5 alone, rounded up to 0.05 USD: neither can
    be refused for the budget, however phase 1 spent."""
    total = PHASE_ONE_WORST_USD + worst_usd(
        evo.EVOLVE_PROMPT_BOUND, evo.EVOLVE_GENERATE_MAX_TOKENS, SONNET
    )
    assert total <= evo.EVOLVE_GEN_CAP_USD < total + 0.05 + 1e-9
    assert evo.EVOLVE_GEN_CAP_USD == 0.45
    assert evo.EVOLVE_GENERATE_MAX_TOKENS == GENERATE_MAX_TOKENS  # as E3's n=5 arm
    assert evo.EVOLVE_ARM == AB_ARM and evo.EVOLVE_N == 5
    assert evo.EVOLVE_ARM.model in settings.MODEL_PRICING
    assert evo.EVOLVE_ARM.effort == "medium" in EFFORT_LEVELS[evo.EVOLVE_ARM.model]
    assert PHASE_ONE_CAP_USD < evo.EVOLVE_GEN_CAP_USD


def test_the_suite_needs_the_sum_of_every_cap_it_may_ask_for() -> None:
    """3 repositories x 10 rounds x (generation + engine run), every one at
    its worst, inside live-smoke's ceiling: the run cap did not have to come
    down for ten rounds. The final re-test sends no request."""
    plan = evo.evolve_plan({})
    per_round = evo.EVOLVE_GEN_CAP_USD + plan.run_cap
    assert len(plan.repos) == 3 and plan.rounds == 10
    need = len(plan.repos) * plan.rounds * per_round
    assert evo.evolve_need(plan) == pytest.approx(need) == pytest.approx(EVOLVE_NEED)
    assert evo.evolve_need(plan) <= CAP_CEILING_USD
    # A fourth repository still fits; a fifth, or OSS_RUN_CAP_USD a run, not.
    four = evo.evolve_plan({evo.REPOS_ENV: "tabulate,tomli,markdown,idna"})
    assert evo.evolve_need(four) == pytest.approx(138.0)
    assert evo.evolve_need(four) <= CAP_CEILING_USD
    five = evo.evolve_plan({evo.REPOS_ENV: "tabulate,tomli,markdown,idna,sqlparse"})
    assert evo.evolve_need(five) > CAP_CEILING_USD
    widest = evo.evolve_plan({evo.RUN_CAP_ENV: str(OSS_RUN_CAP_USD)})
    assert evo.evolve_need(widest) == pytest.approx(163.5)
    assert evo.evolve_need(widest) > CAP_CEILING_USD
    fewer = evo.evolve_plan({evo.ROUNDS_ENV: "2", evo.REPOS_ENV: "tomli"})
    assert evo.evolve_need(fewer) == pytest.approx(2 * per_round)


def test_a_suite_cap_below_the_plans_need_is_refused_before_any_spend() -> None:
    plan = evo.evolve_plan({})
    evo.check_suite_cap(plan, {"LIVE_SUITE_CAP_USD": "104"})
    evo.check_suite_cap(plan, {"LIVE_SUITE_CAP_USD": "150"})
    for cap in ("103.49", "12"):
        with pytest.raises(ValueError, match="LIVE_SUITE_CAP_USD"):
            evo.check_suite_cap(plan, {"LIVE_SUITE_CAP_USD": cap})
    with pytest.raises(ValueError, match="LIVE_SUITE_CAP_USD"):
        evo.check_suite_cap(plan, {})  # the default 12 USD suite cap
    widest = evo.evolve_plan({evo.RUN_CAP_ENV: str(OSS_RUN_CAP_USD)})
    with pytest.raises(ValueError, match="163.50 USD"):
        evo.check_suite_cap(widest, {"LIVE_SUITE_CAP_USD": "150"})


def test_engine_rounds_bill_sonnet_alone_and_the_global_settings_never_change() -> None:
    before = settings.model_dump()
    cfg = evo.evolve_settings(settings)
    assert (cfg.ENGINE_MODEL, cfg.ENGINE_FALLBACKS) == (SONNET, False)
    assert chain(cfg) == (SONNET,)
    assert settings.model_dump() == before
    plan = evo.evolve_plan({})
    assert settings_trial_budget(cfg) < plan.run_cap <= OSS_RUN_CAP_USD


# ---------------------------------------------------------------------------
# The generator's prompt bound and the history
# ---------------------------------------------------------------------------


def _reply(text: str) -> Json:
    return {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": SONNET,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def _no_sleep(_seconds: float) -> None:
    return None


def _largest_facts(repo: OssRepo, root: Path) -> RepoFacts:
    """The largest facts an OSS clone can give the generator: 30 hotspots on
    ``OSS_PATH_BOUND``-character paths with symbols at the profiler's cap,
    and every understanding field at its cap (the understander's limits)."""
    project = repo.project(root)
    stem = "p" * (evo.OSS_PATH_BOUND - len(repo.module_root) - len("/.py"))
    path = f"{repo.module_root}/{stem}.py"
    assert len(path) == evo.OSS_PATH_BOUND
    spots = tuple(
        Hotspot(
            project_id=project.id,
            workload_id=new_id(),
            file_path=path,
            symbol="s" * MAX_SYMBOL_CHARS,
            line_start=10_000,
            line_end=20_000,
            self_time_s=123.456789,
            total_time_s=123.456789,
            share=0.1234,
            calls=12_345_678,
            memory_bytes=12_345_678_901,
        )
        for _ in range(MAX_HOTSPOTS)
    )
    understanding = ProjectUnderstanding(
        language="python",
        summary="s" * 1500,
        entrypoints=(path,) * 20,
        workload_notes={new_id(): "n" * 500},
        candidate_modules=tuple(
            CandidateModule(path=path, reason="r" * 500) for _ in range(10)
        ),
        served_by_model=SONNET,
    )
    return RepoFacts(project, understanding, spots, _objective(project))


def _objective(project: Project) -> Objective:
    return Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=0.02,
        description="minimize wall time",
    )


WORST_TITLE = ('"\\' * MAX_TITLE_CHARS)[: 3 * MAX_TITLE_CHARS]


def _largest_history() -> tuple[evo.RoundHistory, ...]:
    """Every earlier round of the deepest plan, each with more titles than
    a round can try, every title over the cap and full of characters JSON
    escapes."""
    titles = tuple(f"{i}{WORST_TITLE}" for i in range(2 * evo.EVOLVE_N))
    return tuple(
        evo.RoundHistory(k, titles, titles, -123456.789)
        for k in range(1, evo.EVOLVE_MAX_ROUNDS)
    )


def _count(facts: RepoFacts) -> int:
    scripted = ScriptedTransport([_reply('{"hypotheses": []}')])
    with contextlib.suppress(Exception):  # only the request counts
        generate_hypotheses(
            scripted,
            Budget(9.0),
            project=facts.project,
            understanding=facts.understanding,
            hotspots=facts.hotspots,
            objective=facts.objective,
            n=evo.EVOLVE_N,
            max_tokens=evo.EVOLVE_GENERATE_MAX_TOKENS,
            sleep=_no_sleep,
        )
    return scripted.count_input_tokens(scripted.requests[0])


@pytest.mark.parametrize("repo", OSS_CORPUS, ids=[r.name for r in OSS_CORPUS])
def test_the_prompt_bound_holds_with_the_largest_facts_and_history(
    repo: OssRepo, tmp_path: Path
) -> None:
    """The count is the byte bound plus the allowance (no token covers less
    than a byte), so the API's count cannot exceed it."""
    facts = _largest_facts(repo, tmp_path)
    history = _largest_history()
    told = evo.with_history(facts, history)
    assert len(evo.history_text(history)) <= evo.HISTORY_MAX_CHARS
    assert _count(facts) < _count(told) <= evo.EVOLVE_PROMPT_BOUND


def _facts(root: Path) -> RepoFacts:
    project = OSS_CORPUS[0].project(root)
    spot = Hotspot(
        project_id=project.id,
        workload_id="w1",
        file_path="tabulate/__init__.py",
        symbol="_format",
        self_time_s=1.0,
        total_time_s=1.0,
        share=0.9,
    )
    return RepoFacts(project, None, (spot,), _objective(project))


def test_round_one_is_told_nothing_and_later_rounds_every_earlier_one(
    tmp_path: Path,
) -> None:
    facts = _facts(tmp_path)
    assert evo.history_text(()) == ""
    assert evo.with_history(facts, ()) is facts
    history = (
        evo.RoundHistory(
            1, ("cache the column widths",), ("inline the padding",), 14.3
        ),
        evo.RoundHistory(2, ("precompile the regex",), (), None),
    )
    told = evo.with_history(facts, history)
    # Only the objective's description changes; every other fact is the same.
    assert replace(told, objective=facts.objective) == facts
    assert told.objective.model_copy(
        update={"description": facts.objective.description}
    ) == (facts.objective)
    text = told.objective.description
    assert text.startswith("minimize wall time. ")
    assert text.endswith(evo.history_text(history))
    for needle in (
        evo.HISTORY_LEAD,
        'round 1: delivered with a 14.3 % gain: "cache the column widths"; '
        'tried without surviving the judges: "inline the padding".',
        'round 2: delivered with a - % gain: "precompile the regex"; '
        "tried without surviving the judges: none.",
    ):
        assert needle in text, needle


def test_history_titles_are_plain_ascii_one_line_capped_and_bounded() -> None:
    weird = 'caché‮ the\nrows "fast" \\ path\x00' + "x" * 300
    (line,) = evo.history_text((evo.RoundHistory(1, (weird,), (), 2.0),)).split(
        "round 1: "
    )[1:]
    title = line.split('"')[1]
    assert title.isascii() and title.isprintable()
    assert len(title) == evo.HISTORY_TITLE_CHARS == MAX_TITLE_CHARS
    assert title.startswith("cach?? the?rows 'fast' / path?x")
    many = tuple(f"t{i}" for i in range(evo.EVOLVE_N + 3))
    text = evo.history_text((evo.RoundHistory(1, many, many, 1.0),))
    assert text.count('"t') == 2 * evo.EVOLVE_N  # at most n titles per list
    assert len(evo.history_text(_largest_history())) <= evo.HISTORY_MAX_CHARS


def test_the_newest_rounds_reach_the_generator_when_the_history_outgrows_its_cap() -> (
    None
):
    history = _largest_history()
    text = evo.history_text(history)
    assert len(text) <= evo.HISTORY_MAX_CHARS
    last = history[-1].round
    assert f"round {last}: delivered with a -123456.8 % gain: " in text
    shown = [k for k in range(1, last + 1) if f"round {k}: " in text]
    assert shown == list(range(shown[0], last + 1))  # a contiguous newest run
    assert shown[0] > 1
    assert f"rounds 1-{shown[0] - 1} not shown. round {shown[0]}: " in text
    assert text.startswith(f"{evo.HISTORY_LEAD}: rounds 1-")
    # A history that fits is told whole, oldest first, with no marker.
    small = (
        evo.RoundHistory(1, (), ("a",), None),
        evo.RoundHistory(2, (), (), None, generated=False),
        evo.RoundHistory(3, ("b",), (), 4.0),
    )
    told = evo.history_text(small)
    assert "not shown" not in told
    assert told == (
        f"{evo.HISTORY_LEAD}: round 1: delivered nothing; tried without surviving "
        'the judges: "a". round 2: generated no efficiency hypothesis. round 3: '
        'delivered with a 4.0 % gain: "b"; tried without surviving the judges: '
        "none."
    )


class Wire:
    """Answers count_tokens with a fixed count and each message request with
    five efficiency ideas; keeps every message body."""

    def __init__(self) -> None:
        self.bodies: list[Json] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body: Json = json.loads(request.read())
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 900}, request=request)
        self.bodies.append(body)
        ideas: list[Json] = [
            {
                "title": f"idea {i}",
                "technique_slug": None,
                "hotspots": [],
                "change_summary": "Change it.",
                "justification_summary": "It dominates.",
                "change_class": "efficiency",
                "expected_gain": 0.2,
                "provability": 0.8,
                "risk": 0.1,
            }
            for i in range(5)
        ]
        message = {
            "id": f"msg_{len(self.bodies)}",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": json.dumps({"hypotheses": ideas})}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
        }
        return httpx2.Response(200, json=message, request=request)


@pytest.fixture
def dry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real-path tmp dir, the dry-run key, ``WORKTREE_ROOT`` beside it."""
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    return root


def test_the_generator_is_told_the_history_inside_the_untrusted_fence(
    dry: Path,
) -> None:
    wire = Wire()
    run = LiveRun("dry", evo.EVOLVE_GEN_CAP_USD, wire=httpx2.MockTransport(wire))
    budget = Budget(run.cap_usd)
    history = (evo.RoundHistory(1, ("cache the widths",), ("inline it",), 9.5),)
    produced = evo.generate_round(run, budget, evo.with_history(_facts(dry), history))
    (body,) = wire.bodies
    assert body["model"] == SONNET and "fallbacks" not in body
    assert body["output_config"]["effort"] == "medium"
    assert body["max_tokens"] == evo.EVOLVE_GENERATE_MAX_TOKENS
    text = body["messages"][0]["content"][0]["text"]
    opening = re.search(r"<untrusted_repo_content boundary=(\w+)>", text)
    assert opening is not None
    closing = f"</untrusted_repo_content boundary={opening.group(1)}>"
    fenced = text[opening.end() : text.index(closing)]
    # The description travels JSON-encoded in the objective's data line.
    assert json.dumps(evo.history_text(history))[1:-1] in fenced
    assert "Write at most 5 hypotheses" in text[text.index(closing) :]
    assert produced.models == (SONNET,) and len(produced.hypotheses) == 5
    assert produced.arm == evo.EVOLVE_ARM and produced.error is None


# ---------------------------------------------------------------------------
# Gains
# ---------------------------------------------------------------------------


def test_round_gains_compound_against_the_original_code() -> None:
    assert evo.cumulative_pct([]) == 0.0
    assert evo.cumulative_pct([10.0, 10.0]) == pytest.approx(19.0)
    assert evo.cumulative_pct([14.3]) == pytest.approx(14.3)
    assert evo.cumulative_pct([14.3, None, 0.0]) == pytest.approx(14.3)
    assert evo.cumulative_pct([50.0, 50.0, 50.0]) == pytest.approx(87.5)
    assert evo.compound(19.0, 10.0) == pytest.approx(27.1)
    assert evo.compound(19.0, None) == pytest.approx(19.0)


# ---------------------------------------------------------------------------
# The clone, moved to the engine's delivered commit (real git, local upstream)
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str, env: Mapping[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=dict(_CLEAN_GIT if env is None else env),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


LICENSE_TEXT = "Permission is hereby granted, free of charge\n"


def _upstream(root: Path, files: Mapping[str, str]) -> tuple[str, str]:
    """A local bare upstream holding ``files``, one commit tagged ``v1``:
    its ``file://`` URL and the commit."""
    work = root / "upstream"
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    _git(root, "init", "-q", "-b", "trunk", str(work))
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "release")
    commit = _git(work, "rev-parse", "HEAD")
    _git(work, "tag", "v1")
    bare = root / "upstream.git"
    _git(root, "clone", "-q", "--bare", str(work), str(bare))
    return f"file://{bare}", commit


def _local_user(tmp_path: Path) -> tuple[OssRepo, UserRepo]:
    """A tagged local upstream, cloned and prepared as a live case does
    (through the injected file:// policy): the user's repository."""
    root = Path(os.path.realpath(tmp_path))
    files = {
        "pkg/__init__.py": "VALUE = 1\n",
        "tests/test_pkg.py": "import pkg\n",
        "LICENSE": LICENSE_TEXT,
    }
    url, commit = _upstream(root, files)
    base = OSS_CORPUS[0]
    repo = replace(
        base,
        url=url,
        tag="v1",
        commit=commit,
        license_file="LICENSE",
        package="pkg",
        module_root="pkg",
        test_command=("python", "-m", "unittest", "discover", "-s", "tests"),
        targets=(("pkg/__init__.py",), ("pkg/__init__.py",)),
    )
    return repo, prepare_repo(repo, root / "user", policy=LOCAL)


def _deliver(
    user: UserRepo,
    files: Mapping[str, str],
    *,
    run_id: str = "run1",
    parent: str | None = None,
    ref: bool = True,
) -> evo.Delivered:
    """What the engine's publisher leaves: a commit on top of the measured
    base (built without touching the user's index or working tree) and the
    create-only ``engine/run-<id>`` branch at it."""
    on = user.base if parent is None else parent
    index = user.path.parent / f"index-{new_id()}"
    env = {**_CLEAN_GIT, "GIT_INDEX_FILE": str(index)}
    _git(user.path, "read-tree", on, env=env)
    for rel, text in files.items():
        blob = subprocess.run(
            ["git", "-C", str(user.path), "hash-object", "-w", "--stdin"],
            env=env,
            input=text,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        _git(
            user.path,
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},{rel}",
            env=env,
        )
    tree = _git(user.path, "write-tree", env=env)
    commit = _git(user.path, "commit-tree", tree, "-p", on, "-m", "engine", env=env)
    index.unlink()
    branch = f"{settings.TRIAL_BRANCH_PREFIX}run-{run_id}"
    if ref:
        _git(user.path, "update-ref", f"refs/heads/{branch}", commit)
    return evo.Delivered(run_id=run_id, branch=branch, commit=commit, base=user.base)


def test_the_clone_moves_to_the_engines_delivered_commit_and_nothing_else(
    tmp_path: Path,
) -> None:
    _repo, user = _local_user(tmp_path)
    delivered = _deliver(user, {"pkg/__init__.py": "VALUE = 2\n"})
    before = user.snapshot()
    moved = evo.advance_clone(user, delivered, policy=LOCAL)
    after = moved.snapshot()
    assert moved == UserRepo(user.path, delivered.commit)
    assert (after.head, after.head_ref) == (delivered.commit, "refs/heads/main")
    assert after.refs == {**before.refs, "refs/heads/main": delivered.commit}
    assert after.status == before.status == "" and after.config == before.config
    assert (after.hooks, after.info) == (before.hooks, before.info)
    assert (user.path / "pkg/__init__.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert moved.worktrees() == [f"worktree {user.path}"]
    # The next round moves on from there.
    again = _deliver(moved, {"pkg/__init__.py": "VALUE = 3\n"}, run_id="run2")
    assert evo.advance_clone(moved, again, policy=LOCAL).base == again.commit


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("foreign-branch", "not the engine's delivery branch"),
        ("short-commit", "not a full commit id"),
        ("no-ref", "is not at"),
        ("ref-elsewhere", "is not at"),
        ("not-a-descendant", "not a descendant"),
        ("other-base", "measured"),
        ("protected-test", "protected"),
        ("protected-bench", "protected"),
        ("moved-head", "HEAD is"),
    ],
)
def test_anything_but_the_engines_own_descendant_is_refused_before_git_moves(
    tmp_path: Path, case: str, reason: str
) -> None:
    repo, user = _local_user(tmp_path)
    good = _deliver(user, {"pkg/__init__.py": "VALUE = 2\n"})
    delivered = good
    if case == "foreign-branch":
        delivered = replace(good, branch="feature")
    elif case == "short-commit":
        delivered = replace(good, commit=good.commit[:12])
    elif case == "no-ref":
        delivered = _deliver(
            user, {"pkg/__init__.py": "VALUE = 4\n"}, run_id="r9", ref=False
        )
    elif case == "ref-elsewhere":
        other = _deliver(
            user, {"pkg/__init__.py": "VALUE = 5\n"}, run_id="r8", ref=False
        )
        delivered = replace(good, commit=other.commit)
    elif case == "not-a-descendant":
        sibling = _git(user.path, "rev-parse", "HEAD^")
        delivered = _deliver(user, {"pkg/x.py": "X = 1\n"}, run_id="r7", parent=sibling)
    elif case == "other-base":
        delivered = replace(good, base="0" * 40)
    elif case == "protected-test":
        delivered = _deliver(user, {"tests/test_pkg.py": "pass\n"}, run_id="r6")
    elif case == "protected-bench":
        delivered = _deliver(user, {repo.bench_path: "print(1)\n"}, run_id="r5")
    else:  # the clone is not where the round started
        pin = _git(user.path, "rev-parse", "HEAD^")
        user, delivered = UserRepo(user.path, pin), replace(good, base=pin)
    before = user.snapshot()
    with pytest.raises(CloneRefusedError, match=reason):
        evo.advance_clone(user, delivered, policy=LOCAL)
    assert user.snapshot() == before  # nothing moved


def test_a_local_change_the_move_would_overwrite_is_refused(tmp_path: Path) -> None:
    _repo, user = _local_user(tmp_path)
    delivered = _deliver(user, {"pkg/__init__.py": "VALUE = 2\n"})
    (user.path / "pkg/__init__.py").write_text("VALUE = 9\n", encoding="utf-8")
    before = user.snapshot()
    with pytest.raises(CloneRefusedError):
        evo.advance_clone(user, delivered, policy=LOCAL)
    after = user.snapshot()
    assert (after.head, after.refs, after.status) == (
        before.head,
        before.refs,
        before.status,
    )


def test_no_hook_of_the_user_runs_while_the_clone_moves(tmp_path: Path) -> None:
    _repo, user = _local_user(tmp_path)
    delivered = _deliver(user, {"pkg/__init__.py": "VALUE = 2\n"})
    marker = tmp_path / "hook-ran"
    for name in ("post-checkout", "reference-transaction", "post-merge"):
        hook = user.path / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\necho {name} >> {marker}\n", encoding="utf-8")
        hook.chmod(0o755)
    # A plain git command of the user's would run them (the hooks are live).
    _git(user.path, "update-ref", "refs/heads/probe", user.base)
    assert set(marker.read_text(encoding="utf-8").split()) == {"reference-transaction"}
    _git(user.path, "update-ref", "-d", "refs/heads/probe")
    marker.unlink()
    evo.advance_clone(user, delivered, policy=LOCAL)
    assert not marker.exists()


# ---------------------------------------------------------------------------
# Engine results: what was delivered and tried
# ---------------------------------------------------------------------------


def _hypothesis(project: Project, title: str) -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.novel,
        title=title,
        rationale="from the generator",
        change_class=ChangeClass.efficiency,
        expected_gain=0.2,
        provability=0.8,
        risk=0.1,
    )


def _result(
    project: Project,
    *,
    delivered: Sequence[str] = (),
    tried: Sequence[str] = (),
    gain: float | None = 0.1,
    floor: float | None = 0.03,
    commit: str = "c" * 40,
    base: str = "b" * 40,
    run_id: str = "run1",
) -> EngineRunResult:
    """A finished engine state: ``delivered`` kept and applied, ``tried``
    trialled and rejected (a branch delivery when anything was delivered)."""
    state = initial_state(project, [], [], guardrails(project), run_id=run_id)
    hypotheses = [_hypothesis(project, t) for t in (*delivered, *tried)]
    trials = [
        Trial(hypothesis_id=h.id, round=1, status=TrialStatus.measured, commit="d" * 40)
        for h in hypotheses
    ]
    verdicts = [
        Verdict(
            trial_id=t.id,
            hypothesis_id=h.id,
            outcome=VerdictOutcome.keep
            if h.title in delivered
            else VerdictOutcome.reject,
            change_class=ChangeClass.efficiency,
            summary="s",
        )
        for h, t in zip(hypotheses, trials, strict=True)
    ]
    kept = [v.id for v in verdicts if v.outcome is VerdictOutcome.keep]
    state["hypotheses"] = hypotheses
    state["trials"] = trials
    state["verdicts"] = verdicts
    state["base_commit"] = base
    branch = f"{settings.TRIAL_BRANCH_PREFIX}run-{run_id}"
    if kept:
        state["combination"] = Combination(
            base_commit=base,
            tip_commit=commit,
            applied_trial_ids=tuple(t.id for t in trials[: len(delivered)]),
            judge_results=(
                JudgeResult(
                    judge="speed",
                    outcome=JudgeOutcome.passed,
                    metric=METRIC_WALL_TIME_S,
                    gain=gain,
                    noise_floor=floor,
                    reason="r",
                ),
            ),
            holds=True,
            summary="s",
        )
        state["delivery"] = Delivery(
            project_id=project.id,
            kind=DeliveryKind.branch,
            branch=branch,
            commit=commit,
            verdict_ids=tuple(kept),
            report_markdown="r",
        )
    else:
        state["delivery"] = Delivery(
            project_id=project.id, kind=DeliveryKind.report_only, report_markdown="r"
        )
    return EngineRunResult(run_id, "done", state, None)


def test_only_a_branch_delivery_with_a_commit_is_a_delivered_commit(
    tmp_path: Path,
) -> None:
    project = OSS_CORPUS[0].project(tmp_path)
    assert evo.delivered_of(None) is None
    assert evo.delivered_of(_result(project, tried=("a",))) is None
    found = evo.delivered_of(_result(project, delivered=("a",), run_id="r1"))
    assert found == evo.Delivered("r1", "engine/run-r1", "c" * 40, "b" * 40)
    no_commit = _result(project, delivered=("a",))
    delivery = no_commit.state["delivery"]
    assert delivery is not None
    no_commit.state["delivery"] = delivery.model_copy(update={"commit": None})
    assert evo.delivered_of(no_commit) is None


def test_round_titles_split_the_delivered_from_the_tried(tmp_path: Path) -> None:
    project = OSS_CORPUS[0].project(tmp_path)
    result = _result(project, delivered=("b", "a"), tried=("c", "d"))
    assert evo.round_titles(result) == (("b", "a"), ("c", "d"))
    assert evo.round_titles(_result(project, tried=("c",))) == ((), ("c",))
    assert evo.round_titles(None) == ((), ())


# ---------------------------------------------------------------------------
# The round wiring: the production engine on Sonnet 5.5 alone
# ---------------------------------------------------------------------------


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


def test_a_round_loop_is_the_production_wiring_on_the_moved_clone(
    dry: Path,
) -> None:
    repo, user = _local_user(dry)
    cfg = evo.evolve_settings(settings)
    run = LiveRun("dry", 3.0, wire=httpx2.MockTransport(_no_wire))
    ideas = [
        _hypothesis(repo.project(dry / "elsewhere"), f"idea {i}") for i in range(3)
    ]
    loop = evo.start_round_loop(repo, run, user, REQUIRED, cfg, ideas)
    assert loop.user == user and loop.before == user.snapshot()
    assert loop.project.root_path == str(user.path)
    assert loop.project.test_command == repo.test_command
    assert loop.workload.command == repo.workload_argv
    assert [h.title for h in loop.candidates] == ["idea 0", "idea 1", "idea 2"]
    assert all(h.project_id == loop.project.id for h in loop.candidates)
    assert tuple(loop.context.candidates) == loop.candidates
    assert (loop.repo, loop.mode, loop.cap_usd) == (repo.corpus, "blind", 3.0)
    assert loop.context.min_trial_budget_usd == settings_trial_budget(cfg)
    assert run.capture.exchanges == [] and run.records == []
    phase = evo.start_round_loop(
        repo, run, user, REQUIRED, cfg, (), cap_usd=PHASE_ONE_CAP_USD
    )
    assert phase.candidates == () and phase.cap_usd == PHASE_ONE_CAP_USD
    assert (
        evo.start_round_loop(repo, run, user, REQUIRED, cfg, (), cap_usd=9).cap_usd
        == 3.0
    )


# ---------------------------------------------------------------------------
# The driver, on scripted rounds
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Script:
    """One scripted round: how many efficiency ideas the generator gives
    (and how many behaviour ones), what the engine delivers and tries."""

    ideas: int = 3
    others: int = 0
    delivered: tuple[str, ...] = ()
    tried: tuple[str, ...] = ()
    gain: float | None = 0.1
    fail: str | None = None  # "generate", "improve" or "advance"


WIN = Script(delivered=("win",), tried=("lose",), gain=0.1)
EMPTY = Script(tried=("lose",))
NO_IDEAS = Script(ideas=0, others=2)


def _spend(run: LiveRun, usd: float) -> None:
    run.records.append(RequestRecord(SONNET, 1, 1, 0, 0, usd, usd, "end_turn"))


def _retest_of(gain: float | None, floor: float | None, holds: bool) -> evo.FinalRetest:
    return evo.FinalRetest(
        gain_pct=gain,
        floor_pct=floor,
        holds=holds,
        same_output=None if gain is None else True,
        reason="r",
        wall_s=12.0,
        bound_s=evo.EVOLVE_RETEST_WALL_S,
        launch_timeout_s=75.0,
    )


@dataclass
class FakeSteps:
    """``LiveSteps`` scripted: each round's generation and engine loop, the
    move, and the final re-test (the fake measurer: ``retested`` gives
    what it measures, ``retest_fail`` makes it a breach)."""

    project: Project
    scripts: list[Script]
    retested: evo.FinalRetest = field(
        default_factory=lambda: _retest_of(8.0, 2.0, True)
    )
    retest_fail: bool = False
    told: list[tuple[evo.RoundHistory, ...]] = field(default_factory=list)
    handed: list[tuple[str, ...]] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    retests: list[tuple[str, str, str]] = field(default_factory=list)  # base, tip, run

    def generate(
        self,
        run: LiveRun,
        round_no: int,
        user: UserRepo,
        history: Sequence[evo.RoundHistory],
    ) -> evo.Generated:
        script = self.scripts[round_no - 1]
        self.told.append(tuple(history))
        _spend(run, 0.03)
        if script.fail == "generate":
            raise AssertionError("phase one broke a guard")
        ideas = [
            _hypothesis(self.project, f"r{round_no} idea {i}")
            for i in range(script.ideas)
        ]
        others = [
            _hypothesis(self.project, f"r{round_no} other {i}").model_copy(
                update={"change_class": ChangeClass.behaviour}
            )
            for i in range(script.others)
        ]
        _spend(run, 0.02)
        produced = ArmResult(
            evo.EVOLVE_ARM, (*ideas, *others), 0.02, (), (SONNET,), 1.0, None
        )
        return evo.Generated(phase_cost_usd=0.03, produced=produced)

    def improve(
        self, run: LiveRun, user: UserRepo, candidates: Sequence[Hypothesis]
    ) -> evo.Improved:
        round_no = int(candidates[0].title.split()[0][1:])
        script = self.scripts[round_no - 1]
        self.handed.append(tuple(h.title for h in candidates))
        _spend(run, 0.25)
        if script.fail == "improve":
            raise AssertionError("the engine broke a guard")
        result = _result(
            self.project,
            delivered=script.delivered,
            tried=script.tried,
            gain=script.gain,
            commit=f"{round_no:x}" * 40,
            base=user.base,
            run_id=f"run{round_no}",
        )
        outcome = outcome_of(
            OSS_CORPUS[0].corpus, run, result, guard="ok", mode="blind"
        )
        return evo.Improved(replace(outcome, engine_model=SONNET), result)

    def advance(self, user: UserRepo, delivered: evo.Delivered) -> UserRepo:
        round_no = int(delivered.run_id.removeprefix("run"))
        if self.scripts[round_no - 1].fail == "advance":
            raise CloneRefusedError("HEAD moved")
        self.moved.append(delivered.commit)
        return UserRepo(user.path, delivered.commit)

    def retest(
        self, user: UserRepo, base: str, last: EngineRunResult
    ) -> evo.FinalRetest:
        self.retests.append((base, user.base, last.state["run_id"]))
        if self.retest_fail:
            raise CloneRefusedError("the final re-test changed the clone")
        return self.retested


@dataclass
class Runs:
    made: list[LiveRun] = field(default_factory=list)

    def start(self, cap: float) -> Callable[[], LiveRun]:
        def make() -> LiveRun:
            run = LiveRun(f"run{len(self.made) + 1}", cap)
            self.made.append(run)
            return run

        return make


ORIGIN = "0" * 40


def _evolve(
    tmp_path: Path,
    scripts: list[Script],
    *,
    rounds: int = 10,
    steps: FakeSteps | None = None,
) -> tuple[evo.EvolveRecorder, FakeSteps, Runs, tuple[evo.EvolveRow, ...]]:
    project = OSS_CORPUS[0].project(tmp_path)
    steps = FakeSteps(project, scripts) if steps is None else steps
    runs = Runs()
    recorder = evo.EvolveRecorder(evo.EvolvePlan(rounds, 3.0), ResultsSink({}))
    rows = evo.run_evolution(
        "tabulate",
        UserRepo(tmp_path, ORIGIN),
        recorder.plan,
        steps,
        start_gen=runs.start(evo.EVOLVE_GEN_CAP_USD),
        start_engine=runs.start(3.0),
        recorder=recorder,
    )
    return recorder, steps, runs, rows


def test_the_stop_rule_is_two_consecutive_empty_rounds() -> None:
    assert evo.EVOLVE_EMPTY_STOP == 2
    assert not evo.should_stop([])
    assert not evo.should_stop([False])
    assert evo.should_stop([False, False])
    assert not evo.should_stop([False, True])
    assert not evo.should_stop([False, True, False])
    assert evo.should_stop([True, False, True, False, False])
    assert not evo.should_stop([True, True, True])


def test_two_empty_rounds_in_a_row_stop_the_repository(tmp_path: Path) -> None:
    scripts = [EMPTY, EMPTY, WIN, WIN]
    recorder, steps, runs, rows = _evolve(tmp_path, scripts)
    assert [r.round for r in rows] == [1, 2] and rows == tuple(recorder.rows)
    assert steps.moved == [] and len(runs.made) == 4  # 2 x (generation + engine)
    # Round 2 was told round 1's failure; the clone never moved.
    assert steps.told == [(), (evo.RoundHistory(1, (), ("lose",), None),)]
    assert [r.cumulative_pct for r in rows] == [0.0, 0.0]
    # Nothing delivered: nothing to re-test, and the final says so.
    assert steps.retests == []
    (final,) = recorder.finals
    assert (final.rounds, final.delivered_rounds, final.retest) == (2, 0, None)
    assert (final.base, final.tip, final.claimed_pct) == (ORIGIN, ORIGIN, 0.0)
    assert runs.made[-1].notes[-3] == (
        "EVOLVE tabulate final: rounds 2 claimed 0.0% retest - floor - holds -"
    )


def test_a_win_between_empty_rounds_keeps_the_repository_going(
    tmp_path: Path,
) -> None:
    scripts = [EMPTY, Script(delivered=("r2 idea 0",), gain=0.125), EMPTY, EMPTY, WIN]
    recorder, steps, _runs, rows = _evolve(tmp_path, scripts)
    assert [(r.round, r.delivered) for r in rows] == [
        (1, False),
        (2, True),
        (3, False),
        (4, False),
    ]
    assert steps.moved == ["2" * 40]  # moved once, after the delivering round
    # Each round measures the clone as the last delivery left it.
    assert rows[1].commit == "2" * 40 and rows[2].commit is None
    assert [r.cumulative_pct for r in rows] == pytest.approx([0.0, 12.5, 12.5, 12.5])
    # Round 4's generator was told every earlier round, the failures included.
    assert [len(told) for told in steps.told] == [0, 1, 2, 3]
    assert steps.told[3][2] == evo.RoundHistory(3, (), ("lose",), None)
    # The re-test: the original base against the final tip, after round 4.
    assert steps.retests == [(ORIGIN, "2" * 40, "run4")]
    (final,) = recorder.finals
    assert (final.rounds, final.delivered_rounds, final.tip) == (4, 1, "2" * 40)


def test_a_round_without_efficiency_ideas_is_empty_and_runs_no_engine(
    tmp_path: Path,
) -> None:
    scripts = [WIN, NO_IDEAS, WIN, NO_IDEAS, NO_IDEAS, WIN]
    recorder, steps, runs, rows = _evolve(tmp_path, scripts)
    assert [r.status for r in rows] == [
        "done",
        "no_hypotheses",
        "done",
        "no_hypotheses",
        "no_hypotheses",
    ]
    idle = rows[1]
    assert (idle.candidates, idle.dropped, idle.delivered) == (0, 2, False)
    assert (idle.floor_pct, idle.trialled) == (None, 0)
    assert idle.engine_cost_usd == 0 and idle.cost_usd == pytest.approx(0.05)
    assert len(steps.handed) == 2 and len(runs.made) == 7  # no engine run when idle
    assert idle.cumulative_pct == pytest.approx(rows[0].cumulative_pct)
    # Behaviour ideas are never handed to the engine (they would pause it).
    assert all("other" not in t for told in steps.handed for t in told)
    # The next generator hears that the round produced nothing to try.
    assert evo.RoundHistory(2, (), (), None, generated=False) in steps.told[2]
    # The last engine state is round 3's: the re-test uses its workloads.
    assert steps.retests == [(ORIGIN, "3" * 40, "run3")]
    assert recorder.finals[0].rounds == 5


def test_evolution_runs_at_most_the_planned_rounds_and_compounds(
    tmp_path: Path,
) -> None:
    scripts = [Script(delivered=(f"r{k} idea 0",), gain=0.125) for k in range(1, 11)]
    _recorder, steps, _runs, rows = _evolve(tmp_path, scripts, rounds=2)
    assert [r.round for r in rows] == [1, 2] and len(steps.moved) == 2
    assert rows[-1].cumulative_pct == pytest.approx(23.4375)  # 1 - 0.875 ** 2
    assert [len(told) for told in steps.told] == [0, 1]
    recorder, steps, _runs, rows = _evolve(tmp_path, scripts)
    assert len(rows) == 10 and len(steps.moved) == 10
    assert rows[-1].cumulative_pct == pytest.approx(100 * (1 - 0.875**10))
    assert steps.told[2] == (
        evo.RoundHistory(1, ("r1 idea 0",), (), 12.5),
        evo.RoundHistory(2, ("r2 idea 0",), (), 12.5),
    )
    assert steps.retests == [(ORIGIN, "a" * 40, "run10")]  # f"{10:x}" is "a"
    assert recorder.finals[0].claimed_pct == pytest.approx(rows[-1].cumulative_pct)


def test_claimed_is_the_product_of_round_gains_next_to_the_measured_retest(
    tmp_path: Path,
) -> None:
    """Claimed: 1 - (1 - 0.10)(1 - 0.20) = 28 %; the fake measurer says the
    original base against the final tip gains 15 % over a 3 % floor."""
    scripts = [
        Script(delivered=("r1 idea 0",), gain=0.10),
        Script(delivered=("r2 idea 0",), gain=0.20),
        EMPTY,
        EMPTY,
    ]
    project = OSS_CORPUS[0].project(tmp_path)
    steps = FakeSteps(project, scripts, retested=_retest_of(15.0, 3.0, True))
    recorder, steps, runs, rows = _evolve(tmp_path, scripts, steps=steps)
    (final,) = recorder.finals
    assert final.claimed_pct == pytest.approx(28.0)
    assert final.claimed_pct == pytest.approx(rows[-1].cumulative_pct)
    assert final.retest == _retest_of(15.0, 3.0, True)
    note = next(n for n in runs.made[-1].notes if " final: " in n)
    assert note == (
        "EVOLVE tabulate final: rounds 4 claimed 28.0% retest 15.0% floor 3.0% "
        "holds yes"
    )
    record = final.record()
    assert record["experiment"] == "evolve-final"
    assert record["claimed_pct"] == pytest.approx(28.0)
    assert record["retest"] == {**asdict(_retest_of(15.0, 3.0, True))}
    # A re-test inside the floor, and one that could not measure.
    for retested, tail in (
        (_retest_of(1.0, 3.0, False), "retest 1.0% floor 3.0% holds no"),
        (
            evo.FinalRetest(None, None, False, None, "not re-tested: t", 1, 900, 75),
            "retest - floor - holds no, not re-tested: t",
        ),
    ):
        steps = FakeSteps(project, scripts, retested=retested)
        recorder, _steps, runs, _rows = _evolve(tmp_path, scripts, steps=steps)
        assert evo.final_note(recorder.finals[0]).endswith(tail)


@pytest.mark.parametrize("stage", ["generate", "improve", "advance", "retest"])
def test_a_breach_is_recorded_then_raised(tmp_path: Path, stage: str) -> None:
    second = Script(delivered=("r2 idea 0",), fail=None if stage == "retest" else stage)
    scripts = [Script(delivered=("r1 idea 0",)), second, EMPTY, EMPTY]
    project = OSS_CORPUS[0].project(tmp_path)
    steps = FakeSteps(project, scripts, retest_fail=stage == "retest")
    runs = Runs()
    recorder = evo.EvolveRecorder(evo.EvolvePlan(10, 3.0), ResultsSink({}))
    with pytest.raises((AssertionError, CloneRefusedError)):
        evo.run_evolution(
            "tabulate",
            UserRepo(tmp_path, ORIGIN),
            recorder.plan,
            steps,
            start_gen=runs.start(evo.EVOLVE_GEN_CAP_USD),
            start_engine=runs.start(3.0),
            recorder=recorder,
        )
    last = runs.made[-1]
    assert any(n.startswith("EVOLVE summary") for n in last.notes)  # even then
    if stage == "retest":
        (final,) = recorder.finals
        assert final.guard.startswith("breach: CloneRefusedError")
        assert final.retest is None and len(recorder.rows) == 4
        assert any(n.startswith("EVOLVE tabulate final: ") for n in last.notes)
        summary = evo.summarise(recorder.rows, rounds=10, finals=recorder.finals)
        assert (summary.repos, summary.excluded, summary.retested) == (0, 1, 0)
        return
    first, breach = recorder.rows
    assert first.guard == "ok" and breach.round == 2 and recorder.finals == []
    assert breach.guard.startswith("breach: ") and breach.status == "error"
    assert breach.delivered is (stage == "advance")
    assert any(n.startswith("EVOLVE tabulate r2:") for n in last.notes)
    assert breach.cost_usd == pytest.approx(
        math.fsum(r.spent_usd for r in runs.made[2:])
    )
    assert steps.retests == []


def test_round_notes_carry_every_figure_the_decision_reads(tmp_path: Path) -> None:
    long = tuple("t" * 120 + str(i) for i in range(5))
    scripts = [Script(delivered=long, tried=("x", "y"), gain=0.123), EMPTY, NO_IDEAS]
    _recorder, _steps, runs, rows = _evolve(tmp_path, scripts)
    notes = [n for run in runs.made for n in run.notes]
    assert notes[:3] == [
        "EVOLVE tabulate r1: delivered yes gain 12.3% floor 3.0% tried 7",
        "EVOLVE tabulate r2: delivered no gain - floor - tried 1",
        "EVOLVE tabulate r3: delivered no gain - floor - tried 0, status no_hypotheses",
    ]
    assert notes[3].startswith("EVOLVE tabulate final: rounds 3 claimed 12.3% ")
    assert notes[4].startswith("EVOLVE summary over 1 repo(s)")
    assert notes[5].startswith("EVOLVE summary: improved by round 2.. 0/1 0/1")
    assert all(len(n) <= evo.NOTE_MAX_CHARS for n in notes)
    assert rows[0].trialled == 7
    breach = replace(rows[1], status="error", guard="breach: E: " + "x" * 300)
    assert len(evo.round_note(breach)) == evo.NOTE_MAX_CHARS


# ---------------------------------------------------------------------------
# The final re-test: the engine's ABAB phases and judge (real git, fake measurer)
# ---------------------------------------------------------------------------


def _stats_row(workload: Workload, metric: str, values: Sequence[float]) -> Measurement:
    return Measurement(
        workload_id=workload.id,
        metric=metric,
        stats=RunStats.from_samples(values, unit="s"),
        samples=tuple(values),
        output_fingerprint="f" * 64,
    )


@dataclass
class FakeMeasure:
    """Stands for ``measure.measure_abab``: records the phases it is handed
    and returns fixed wall times (A: the base side, B: the tip side)."""

    a: Sequence[float]
    b: Sequence[float]
    fail: str | None = None
    seen: list[tuple[Path, Path, Workload]] = field(default_factory=list)
    runs: list[tuple[object, object]] = field(default_factory=list)

    def __call__(self, a: Phase, b: Phase, workload: Workload) -> AbabMeasured:
        self.seen.append((a.worktree, b.worktree, workload))
        self.runs.append((a.run, b.run))
        assert a.worktree.is_dir() and b.worktree.is_dir()
        if self.fail is not None:
            raise RunFailure(self.fail)
        return AbabMeasured(
            (_stats_row(workload, METRIC_WALL_TIME_S, self.a),),
            (_stats_row(workload, METRIC_WALL_TIME_S, self.b),),
        )


def _retest_case(dry: Path) -> tuple[UserRepo, UserRepo, Workload, Objective]:
    """The local clone moved one delivery on: (original, moved), the
    workload, the engine's default objective."""
    (dry / "wt-root").mkdir()
    repo, user = _local_user(dry)
    delivered = _deliver(user, {"pkg/__init__.py": "VALUE = 2\n"})
    moved = evo.advance_clone(user, delivered, policy=LOCAL)
    project = repo.project(user.path)
    return user, moved, repo.workload(project), _objective(project)


def test_the_final_retest_measures_the_original_base_against_the_final_tip(
    dry: Path,
) -> None:
    """Base 1.0 s, tip 0.8 s (tight samples): a 20 % gain past the floor,
    judged by the engine's own gain judge; the clone is left as found."""
    user, moved, workload, objective = _retest_case(dry)
    before, trees = moved.snapshot(), moved.worktrees()
    fake = FakeMeasure([1.0, 1.001, 0.999, 1.0, 1.0], [0.8, 0.801, 0.799, 0.8, 0.8])
    found = evo.retest_final(
        moved,
        user.base,
        [workload],
        [objective],
        mode="required",
        noise_multiplier=settings.NOISE_MULTIPLIER,
        run_id="evolve-test",
        measure=fake,
    )
    ((a, b, measured),) = fake.seen
    # Both phases launch through one recording log (the "sandbox used" guard).
    ((run_a, run_b),) = fake.runs
    assert isinstance(run_a, LaunchLog) and run_a is run_b
    assert found.launches == 0  # the fake measurer launched nothing
    root = settings.WORKTREE_ROOT / "evolve-test"
    assert (a, b) == (root / evo.RETEST_BASE, root / evo.RETEST_TIP)
    assert not root.exists()  # both phases cleaned up
    assert moved.snapshot() == before and moved.worktrees() == trees
    # The bound: 2 sides x (1 warm-up + 5 runs) launches share 900 s.
    assert measured.timeout_s == found.launch_timeout_s == pytest.approx(75.0)
    assert evo.launch_timeout_s([workload], 900.0) == pytest.approx(75.0)
    assert found.bound_s == evo.EVOLVE_RETEST_WALL_S == 900.0
    assert found.gain_pct == pytest.approx(20.0) and found.holds
    assert found.floor_pct is not None and 1.99 < found.floor_pct < 20.0
    assert found.same_output is True and "improved" in found.reason
    # Inside the noise floor: measured, recorded, does not hold.
    noisy = FakeMeasure([1.0, 1.4, 0.6, 1.0, 1.0], [0.99, 1.39, 0.59, 0.99, 0.99])
    inside = evo.retest_final(
        moved, user.base, [workload], [objective], mode="required",
        noise_multiplier=2.0, run_id="evolve-noisy", measure=noisy,
    )  # fmt: skip
    assert inside.gain_pct is not None and inside.floor_pct is not None
    assert inside.gain_pct == pytest.approx(1.0) and not inside.holds
    assert inside.floor_pct > inside.gain_pct


def test_a_retest_run_failure_is_recorded_and_a_bad_tip_refused(dry: Path) -> None:
    user, moved, workload, objective = _retest_case(dry)
    common: dict[str, Any] = {
        "mode": "required",
        "noise_multiplier": 2.0,
        "run_id": "evolve-fail",
    }
    timed_out = evo.retest_final(
        moved,
        user.base,
        [workload],
        [objective],
        measure=FakeMeasure([1.0], [1.0], fail="timed out"),
        **common,
    )
    assert (timed_out.gain_pct, timed_out.holds) == (None, False)
    assert timed_out.reason == "not re-tested: timed out"
    assert not (settings.WORKTREE_ROOT / "evolve-fail").exists()
    with pytest.raises(ValueError, match="moved tip"):
        evo.retest_final(user, user.base, [workload], [objective], **common)
    with pytest.raises(ValueError, match="workload"):
        evo.retest_final(moved, user.base, [], [objective], **common)
    with pytest.raises(CloneRefusedError, match="full commit id"):
        evo.retest_final(moved, "abc", [workload], [objective], **common)
    elsewhere = _deliver(moved, {"pkg/y.py": "Y = 1\n"}, run_id="r3", parent=moved.base)
    with pytest.raises(CloneRefusedError, match="does not descend"):
        evo.retest_final(
            UserRepo(moved.path, user.base), elsewhere.commit, [workload],
            [objective], **common,
        )  # fmt: skip


def test_a_retest_that_changes_the_clone_is_refused(dry: Path) -> None:
    user, moved, workload, objective = _retest_case(dry)

    @dataclass
    class Tamper(FakeMeasure):
        def __call__(self, a: Phase, b: Phase, workload: Workload) -> AbabMeasured:
            _git(moved.path, "update-ref", "refs/heads/planted", moved.base)
            return super().__call__(a, b, workload)

    with pytest.raises(CloneRefusedError, match="changed the clone"):
        evo.retest_final(
            moved, user.base, [workload], [objective], mode="required",
            noise_multiplier=2.0, run_id="evolve-tamper",
            measure=Tamper([1.0] * 5, [0.5] * 5),
        )  # fmt: skip


@dataclass
class Unsandboxed(FakeMeasure):
    """A launch the log recorded as not ``required`` or not isolated (the
    real ``LaunchLog`` records what ``run_once`` was given and applied)."""

    launch: Launch = field(
        default_factory=lambda: Launch(
            evo.RETEST_BASE, "required", "required", True, True
        )
    )

    def __call__(self, a: Phase, b: Phase, workload: Workload) -> AbabMeasured:
        assert isinstance(a.run, LaunchLog)
        a.run.launches.append(self.launch)
        return super().__call__(a, b, workload)


@pytest.mark.parametrize(
    ("launch", "fail"),
    [
        (Launch(evo.RETEST_BASE, "off", "required", True, True), None),
        (Launch(evo.RETEST_TIP, "required", "best_effort", True, True), None),
        (Launch(evo.RETEST_TIP, "required", "required", False, True), None),
        (Launch(evo.RETEST_BASE, "required", "required", True, False), None),
        # A fall-back that then fails to measure is a breach, not a failure.
        (Launch(evo.RETEST_BASE, "required", "required", False, False), "boom"),
    ],
)
def test_a_retest_launch_that_was_not_sandboxed_is_a_breach(
    dry: Path, launch: Launch, fail: str | None
) -> None:
    user, moved, workload, objective = _retest_case(dry)
    with pytest.raises(CloneRefusedError, match="not sandboxed"):
        evo.retest_final(
            moved, user.base, [workload], [objective], mode="required",
            noise_multiplier=2.0, run_id="evolve-unsandboxed",
            measure=Unsandboxed([1.0] * 5, [0.5] * 5, fail=fail, launch=launch),
        )  # fmt: skip
    assert not (settings.WORKTREE_ROOT / "evolve-unsandboxed").exists()
    # Every launch sandboxed and isolated: counted, measured, no breach.
    fine = Launch(evo.RETEST_TIP, "required", "required", True, True)
    found = evo.retest_final(
        moved, user.base, [workload], [objective], mode="required",
        noise_multiplier=2.0, run_id="evolve-sandboxed",
        measure=Unsandboxed([1.0] * 5, [0.5] * 5, launch=fine),
    )  # fmt: skip
    assert found.launches == 1 and found.gain_pct == 50.0


def test_live_steps_retest_with_the_last_runs_workloads_and_objectives(
    dry: Path,
) -> None:
    user, moved, workload, objective = _retest_case(dry)
    last = _result(OSS_CORPUS[0].project(dry))
    last.state["workloads"] = [workload]
    last.state["objectives"] = [objective]
    fake = FakeMeasure([1.0] * 5, [0.5] * 5)
    repo = OSS_CORPUS[0]
    steps = evo.LiveSteps(repo, REQUIRED, evo.evolve_settings(settings), measure=fake)
    found = steps.retest(moved, user.base, last)
    ((_a, _b, measured),) = fake.seen
    assert measured.command == workload.command and found.gain_pct == 50.0
    assert evo.LiveSteps(repo, REQUIRED, settings).measure is measure_abab


# ---------------------------------------------------------------------------
# The summary, the results file and the log
# ---------------------------------------------------------------------------


def _row(
    repo: str, k: int, gain: float | None, cumulative: float, cost: float
) -> evo.EvolveRow:
    return evo.EvolveRow(
        repo=repo,
        round=k,
        status="done",
        delivered=gain is not None,
        commit=None if gain is None else "c" * 40,
        kept=() if gain is None else (f"{repo} r{k}",),
        verdict_kept=(),
        tried=(),
        gain_pct=gain,
        floor_pct=None if gain is None else 2.5,
        cumulative_pct=cumulative,
        phase_cost_usd=0.0,
        generation_cost_usd=0.0,
        engine_cost_usd=cost,
        candidates=3,
        dropped=0,
        history_rounds=k - 1,
        engine_model=SONNET,
        served_models=(SONNET,),
        guard="ok",
        generation_error=None,
        budget_exhausted=False,
        trial_budget_error=False,
    )


ROWS = (
    _row("a", 1, 10.0, 10.0, 0.3),
    _row("a", 2, 10.0, 19.0, 0.3),
    _row("a", 3, None, 19.0, 0.3),
    _row("b", 1, None, 0.0, 0.3),
    _row("c", 1, 20.0, 20.0, 0.3),
    _row("c", 2, None, 20.0, 0.3),
)


def test_the_summary_means_improvements_and_cost_per_extra_point() -> None:
    summary = evo.summarise(ROWS, rounds=3)
    assert (summary.repos, summary.excluded) == (3, 0)
    assert summary.mean_cumulative == pytest.approx((10.0, 13.0, 13.0))
    assert summary.improved == {2: (1, 2), 3: (0, 1)}
    assert summary.first_cost == pytest.approx(0.9) and summary.first_pp == 30.0
    assert summary.extra_cost == pytest.approx(0.9)
    assert summary.extra_pp == pytest.approx(9.0)
    assert (summary.retested, summary.held) == (0, 0)
    assert evo.summary_notes(summary) == (
        "EVOLVE summary over 3 repo(s) (0 excluded): mean cumulative % by round "
        "10.0/13.0/13.0",
        "EVOLVE summary: improved by round 2.. 1/2 0/1; USD per extra pp after "
        "round 1 0.1000 (round 1 0.0300); final re-test held 0/0",
    )
    finals = (
        _final("a", 19.0, _retest_of(15.0, 2.0, True)),
        _final("b", 0.0, None),
        _final("c", 20.0, _retest_of(1.0, 2.0, False)),
    )
    with_finals = evo.summarise(ROWS, rounds=3, finals=finals)
    assert (with_finals.retested, with_finals.held) == (2, 1)
    assert evo.summary_notes(with_finals)[1].endswith("final re-test held 1/2")


def _final(
    repo: str, claimed: float, retest: evo.FinalRetest | None
) -> evo.EvolveFinal:
    return evo.EvolveFinal(
        repo=repo,
        rounds=3,
        delivered_rounds=0 if retest is None else 2,
        base="0" * 40,
        tip="0" * 40 if retest is None else "c" * 40,
        claimed_pct=claimed,
        retest=retest,
    )


def test_the_summary_notes_fit_one_cell_each_at_the_deepest_plan() -> None:
    """10 repositories, 10 rounds, every figure at its widest."""
    rows = tuple(
        _row(f"repo_{i:02d}_" + "x" * 30, k, 99.9, 99.9, 9.9)
        for i in range(10)
        for k in range(1, 11)
    )
    finals = tuple(_final(r.repo, 99.9, _retest_of(9.9, 9.9, True)) for r in rows[::10])
    for note in evo.summary_notes(
        evo.summarise(rows, rounds=evo.EVOLVE_MAX_ROUNDS, finals=finals)
    ):
        assert len(note) <= evo.NOTE_MAX_CHARS and not note.endswith("/"), note
    deepest = evo.summary_notes(evo.summarise(rows, rounds=10))
    assert deepest[0].endswith("/".join(["99.9"] * 10))
    assert "2.. " + " ".join(["10/10"] * 9) + ";" in deepest[1]


def test_a_repo_with_a_breach_is_left_out_and_nothing_divides_by_zero() -> None:
    breach = replace(ROWS[1], guard="breach: AssertionError: x")
    summary = evo.summarise((*ROWS[:1], breach, *ROWS[3:]), rounds=3)
    assert (summary.repos, summary.excluded) == (2, 1)
    assert summary.mean_cumulative == pytest.approx((10.0, 10.0, 10.0))
    empty = evo.summarise((), rounds=3)
    assert (empty.repos, empty.mean_cumulative) == (0, (0.0, 0.0, 0.0))
    assert "pp after round 1 n/a (round 1 n/a)" in evo.summary_notes(empty)[1]
    # A final breach excludes its repository like a round breach.
    breached = replace(_final("c", 20.0, None), guard="breach: E: x")
    summary = evo.summarise(ROWS, rounds=3, finals=(breached,))
    assert (summary.repos, summary.excluded) == (2, 1)
    assert evo.render_evolve((), rounds=3).endswith("No evolution round finished.")


def test_the_rendered_summary_is_sanitised_and_names_every_figure() -> None:
    hostile = replace(ROWS[0], kept=("a | b [x](https://e.invalid) <i>",))
    text = evo.render_evolve((hostile, *ROWS[1:]), rounds=3)
    assert "a \\| b" in text and "<i>" not in text and "[x](" not in text
    for needle in (
        "After round 1: mean cumulative gain 10.0 % over 3 repo(s).",
        "After round 3: mean cumulative gain 13.0 % over 3 repo(s).",
        "Improved in round 2: 1 of the 2 repo(s) that reached it.",
        "Improved in round 3: 0 of the 1 repo(s) that reached it.",
        "Rounds 2+: 0.9000 USD for 9.00 pp (0.1000 USD per pp); "
        "round 1: 0.9000 USD for 30.00 pp (0.0300 USD per pp).",
        "2 empty rounds in a row end the repository.",
    ):
        assert needle in text, needle
    finals = (_final("a", 19.0, _retest_of(15.0, 2.0, True)), _final("b", 0.0, None))
    text = evo.render_evolve(ROWS, rounds=3, finals=finals)
    for needle in (
        "| a | 3 | 2 | 19.0 | 15.0 | 2.0 | yes | yes | 12 | ok |",
        "| b | 3 | 0 | 0.0 | - | - | - | - | - | ok |",
        "Final re-test (original base vs final tip, ABAB): 1 of 1 held past the "
        "noise floor.",
    ):
        assert needle in text, needle


def test_rows_go_to_the_results_file_and_in_full_to_the_log(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    recorder = evo.EvolveRecorder(
        evo.EvolvePlan(3, 3.0), ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    )
    run = LiveRun("dry", 1.0)
    for row in ROWS:
        recorder.record(row, run)
    lines = [json.loads(x) for x in results.read_text(encoding="utf-8").splitlines()]
    assert [(x["experiment"], x["repo"], x["round"]) for x in lines] == [
        ("evolve", r.repo, r.round) for r in ROWS
    ]
    assert lines[1]["cumulative_pct"] == 19.0 and lines[1]["cost_usd"] == 0.3
    assert len(run.notes) == len(ROWS)
    recorder.record_final(_final("a", 19.0, _retest_of(15.0, 2.0, True)), run)
    final = json.loads(results.read_text(encoding="utf-8").splitlines()[-1])
    assert (final["experiment"], final["repo"], final["claimed_pct"]) == (
        "evolve-final",
        "a",
        19.0,
    )
    assert final["retest"]["gain_pct"] == 15.0 and final["retest"]["holds"] is True
    assert run.notes[-1].startswith("EVOLVE a final: rounds 3 claimed 19.0% retest")
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert "## Evolution on real code" in echoed
    assert sum(line.startswith("row {") for line in echoed) == len(ROWS)
    assert sum(line.startswith("final {") for line in echoed) == 1
    quiet: list[str] = []
    evo.EvolveRecorder(evo.EvolvePlan(3, 3.0), ResultsSink({})).finish(quiet.append)
    assert quiet == []


# ---------------------------------------------------------------------------
# Real rounds offline: the sandbox, real git and measurement, a mock wire
# ---------------------------------------------------------------------------

DEDUPE = TESTS_DIR / "fixtures" / "dedupe_repo"
BENCH = "from dedupe.main import main\n\nraise SystemExit(main())\n"
SLOW = (
    "    result: list[int] = []\n"
    "    for item in items:\n"
    "        if item not in result:\n"
    "            result.append(item)\n"
)
FAST = (
    "    result: list[int] = []\n"
    "    seen: set[int] = set()\n"
    "    for item in items:\n"
    "        if item not in seen:\n"
    "            seen.add(item)\n"
    "            result.append(item)\n"
)
FIX, IDLE = "membership in a set", "nothing left to try"
UNDERSTOOD: Json = {
    "language": "python",
    "summary": "A small command-line workload.",
    "entrypoints": [],
    "workload_notes": [],
    "candidate_modules": [],
}


@dataclass(frozen=True)
class Rehearsal(OssRepo):
    """A manifest entry whose workload is a local file (the dedupe main)."""

    source: Path = Path("/nonexistent")

    @property
    def workload_source(self) -> Path:
        return self.source


def _rehearsal_user(root: Path) -> tuple[OssRepo, UserRepo]:
    """The dedupe fixture as an upstream library, prepared as a live case."""
    files = {
        p.relative_to(DEDUPE).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(DEDUPE.rglob("*.py"))
        if "__pycache__" not in p.parts
    }
    url, commit = _upstream(root, {**files, "LICENSE": LICENSE_TEXT})
    bench = root / "bench.py"
    bench.write_text(BENCH, encoding="utf-8")
    base = OSS_CORPUS[0]
    repo = Rehearsal(
        name=base.name,
        url=url,
        tag="v1",
        commit=commit,
        released=base.released,
        license=base.license,
        license_file="LICENSE",
        package="dedupe",
        module_root="dedupe",
        test_command=("python", "-m", "unittest", "discover", "-s", "tests", "-t", "."),
        hypotheses=base.hypotheses,
        targets=(("dedupe/core.py",), ("dedupe/core.py",)),
        profile=base.profile,
        source=bench,
    )
    return repo, prepare_repo(repo, root / "user", policy=LOCAL)


def _message(
    request: httpx2.Request, body: Json, content: list[Json], stop: str
) -> httpx2.Response:
    message = {
        "id": f"msg_{new_id()}",
        "type": "message",
        "role": "assistant",
        "model": body["model"],
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 200},
    }
    return httpx2.Response(200, json=message, request=request)


def _idea(title: str) -> Json:
    return {
        "title": title,
        "technique_slug": None,
        "hotspots": [],
        "change_summary": "Test membership against a set of the values seen.",
        "justification_summary": "The list membership test dominates.",
        "change_class": "efficiency",
        "expected_gain": 0.5,
        "provability": 0.9,
        "risk": 0.1,
    }


class EngineWire:
    """Plays Claude for whole rounds: the understander; the generator (the
    fix in round 1, an idle idea after it); an editor that makes the fix
    for the fix's trial and changes nothing for any other."""

    def __init__(self) -> None:
        self.bodies: list[Json] = []
        self.generations: list[Json] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        body: Json = json.loads(request.read())
        if request.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 900}, request=request)
        self.bodies.append(body)
        if "tools" in body:
            return self._edit(request, body)
        keys = set(body["output_config"]["format"]["schema"]["properties"])
        if "language" in keys:
            return _message(request, body, [_text(json.dumps(UNDERSTOOD))], "end_turn")
        self.generations.append(body)
        title = FIX if len(self.generations) == 1 else IDLE
        ideas = json.dumps({"hypotheses": [_idea(title)]})
        return _message(request, body, [_text(ideas)], "end_turn")

    def _edit(self, request: httpx2.Request, body: Json) -> httpx2.Response:
        messages = body["messages"]
        if FIX in json.dumps(messages[0]) and len(messages) == 1:
            change = {"command": "str_replace", "path": "/repo/dedupe/core.py"}
            use = {
                "type": "tool_use",
                "id": "toolu_fix",
                "name": EDITOR_TOOL_NAME,
                "input": {**change, "old_str": SLOW, "new_str": FAST},
            }
            return _message(request, body, [use], "tool_use")
        return _message(request, body, [_text("Done.")], "end_turn")


def _text(text: str) -> Json:
    return {"type": "text", "text": text}


@dataclass(frozen=True)
class SpySteps(evo.LiveSteps):
    """The real rounds, keeping each engine run's final state."""

    results: list[EngineRunResult | None] = field(default_factory=list)

    def improve(
        self, run: LiveRun, user: UserRepo, candidates: Sequence[Hypothesis]
    ) -> evo.Improved:
        improved = super().improve(run, user, candidates)
        self.results.append(improved.result)
        return improved


def _require_sandbox() -> None:
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        required = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
        if any(os.environ.get(name) == "1" for name in required):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(f"the host cannot sandbox: {problem}")


def _wall_mean(result: EngineRunResult | None) -> float:
    assert result is not None
    baseline = result.state["baseline"]
    assert baseline is not None
    (wall,) = [m for m in baseline.measurements if m.metric == METRIC_WALL_TIME_S]
    return wall.stats.mean


@pytest.mark.slow
def test_real_rounds_offline_measure_the_moved_clone_and_retest_the_original(
    dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``LiveSteps`` exactly as the live module runs it, every guard
    included, on the dedupe fixture served as a pinned upstream: round 1
    delivers the fix and moves the clone; round 2 measures the delivered
    commit, its generator is told round 1, and its idle idea delivers
    nothing; round 3 is told both and is empty too, so the stop rule ends
    it. Then the real ABAB re-test (sandboxed launches, the engine's
    judge) measures the original pin against the final tip.

    The noise rule (D41) is off here, as in Step 2: this checks the
    evolution mechanics, and A/A calibration of the millisecond dedupe
    workload on a loaded host can set a floor above 100 %, which stops
    the run by design (U13 picks each live suite's noise mode)."""
    for key, value in {
        "PAIRED_TRIALS": False,
        "CONFIRM_WINNERS": False,
        "NOISE_CALIBRATION_BLOCKS": 0,
    }.items():
        monkeypatch.setattr(settings, key, value)
    _require_sandbox()
    (dry / "wt-root").mkdir()
    repo, user = _rehearsal_user(dry)
    wire = EngineWire()
    runs: list[LiveRun] = []

    def start(cap: float) -> Callable[[], LiveRun]:
        def make() -> LiveRun:
            run = LiveRun(f"run{len(runs) + 1}", cap, wire=httpx2.MockTransport(wire))
            runs.append(run)
            return run

        return make

    steps = SpySteps(repo, REQUIRED, evo.evolve_settings(settings), policy=LOCAL)
    recorder = evo.EvolveRecorder(evo.EvolvePlan(10, 3.0), ResultsSink({}))
    rows = evo.run_evolution(
        repo.name,
        user,
        recorder.plan,
        steps,
        start_gen=start(evo.EVOLVE_GEN_CAP_USD),
        start_engine=start(3.0),
        recorder=recorder,
    )
    first, second, third = rows
    assert all(r.guard == "ok" for r in rows)
    assert (first.delivered, first.kept, first.status) == (True, (FIX,), "done")
    assert first.gain_pct is not None and first.gain_pct > 50
    assert first.floor_pct is not None and first.floor_pct < first.gain_pct
    assert first.commit is not None and first.cumulative_pct == first.gain_pct
    assert (second.delivered, second.history_rounds) == (False, 1)
    assert (third.delivered, third.history_rounds) == (False, 2)
    assert third.cumulative_pct == first.cumulative_pct
    # The clone moved to the delivered commit; the refs no run may touch held.
    after = user.snapshot()
    assert (after.head, after.head_ref) == (first.commit, "refs/heads/main")
    assert {ref: after.refs[ref] for ref in UNTOUCHED_REFS} == dict.fromkeys(
        UNTOUCHED_REFS, user.base
    )
    assert "seen.add(item)" in (user.path / "dedupe/core.py").read_text(
        encoding="utf-8"
    )
    # Rounds 2 and 3 measured the delivered code: its base, a far faster baseline.
    one, two, three = steps.results
    assert two is not None and two.state["base_commit"] == first.commit
    assert three is not None and three.state["base_commit"] == first.commit
    assert _wall_mean(two) < _wall_mean(one) / 3
    # Round 2's generator was told round 1, inside the fence; round 1's nothing.
    told = [g["messages"][0]["content"][0]["text"] for g in wire.generations]
    assert len(told) == 3 and evo.HISTORY_LEAD not in told[0]
    assert evo.HISTORY_LEAD in told[1] and f'\\"{FIX}\\"' in told[1]  # JSON-escaped
    assert f'\\"{IDLE}\\"' in told[2] and "round 2: delivered nothing" in told[2]
    assert all(b["model"] == SONNET and "fallbacks" not in b for b in wire.bodies)
    assert len(runs) == 6  # a generation run and an engine run per round
    # The final re-test: the original pin against the delivered tip, for real.
    (final,) = recorder.finals
    assert (final.base, final.tip, final.rounds) == (user.base, first.commit, 3)
    assert final.claimed_pct == pytest.approx(first.gain_pct)
    retest = final.retest
    assert retest is not None and retest.holds, retest
    assert retest.gain_pct is not None and retest.gain_pct > 50
    assert retest.same_output is True and retest.wall_s < retest.bound_s
    # Every planned launch went through the log, sandboxed and isolated.
    assert retest.launches == round(retest.bound_s / retest.launch_timeout_s) > 0
    assert after == user.snapshot()  # the re-test left the clone as it found it
    notes = runs[-1].notes
    assert notes[0].startswith("EVOLVE tabulate r3: delivered no")
    assert notes[1].startswith("EVOLVE tabulate final: rounds 3 claimed ")
    assert notes[1].endswith(" holds yes")
    assert runs[1].notes[0].startswith("EVOLVE tabulate r1: delivered yes")
    assert notes[-2].startswith("EVOLVE summary over 1 repo(s)")
    assert notes[-1].endswith("final re-test held 1/1")
    assert all(run.spent_usd <= run.cap_usd for run in runs)


# ---------------------------------------------------------------------------
# The live module
# ---------------------------------------------------------------------------


def _tree() -> ast.Module:
    return ast.parse((LIVE_DIR / "test_evolution_live.py").read_text(encoding="utf-8"))


def test_the_live_module_is_marked_parses_its_plan_first_and_asks_for_its_caps() -> (
    None
):
    tree = _tree()
    source = ast.unparse(tree)
    marks = [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]
    assert marks == ["pytest.mark.live"]
    assert "@pytest.fixture(scope='module')" in source
    assert "evolve_plan(os.environ)" in source
    assert "check_suite_cap(plan, os.environ)" in source
    # The repositories are read at collection, and the plan must agree.
    assert "EVOLVE_REPOS = evolve_repos(os.environ)" in source
    assert "if plan.repos != EVOLVE_REPOS:" in source
    asked = {
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "live"
    }
    assert asked == {"EVOLVE_GEN_CAP_USD", "evolve.plan.run_cap"}
    tests = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert [t.name for t in tests] == ["test_evolution_on_real_code"]
    (test,) = tests
    assert "live" in [a.arg for a in test.args.args]
    decorators = [ast.unparse(d) for d in test.decorator_list]
    assert any("EVOLVE_REPOS" in d for d in decorators), decorators
