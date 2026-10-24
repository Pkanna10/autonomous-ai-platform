"""Offline guards of the OSS discovery A/B (``discovery_oss.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_oss_ab_live.py``, that every run's cap is the sum of the worst cases
of its requests on any OSS clone (a loop's scaled with its trial count),
that a plan past the 150 USD ceiling is refused, the defaults (arms a,b, 10
ideas, 2 reps), that each arm bills its own model, that every loop runs on
Sonnet 5.5 without fallbacks through the production OSS wiring with every
candidate in one round, how win@k reads the rank-ordered rows, and what the
results file, the notes and the summary say. A ``slow`` rehearsal runs one
whole task (phase 1, three arms, two loops) in the sandbox on a local
upstream with only the wire mocked; the network case (``LIVE_OSS_NETWORK=1``)
checks each pinned clone against the bounds the caps assume.

Fakes and what they stand for: ``dg.Wire`` / ``ScriptedTransport`` for the
Messages API (the live run's captured ``AnthropicTransport``); ``og.LOCAL``
and a ``file://`` bare upstream for GitHub over https (``oss.PRODUCTION``);
hand-built ``Verdict`` / ``Trial`` states for the engine's (the rehearsal
uses the real engine).
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from e2e.conftest import Isolation, git

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import EFFORT_LEVELS, settings
from autonomous_ai_agents.common.models import (
    CandidateModule,
    ChangeClass,
    Hotspot,
    Hypothesis,
    JudgeOutcome,
    JudgeResult,
    Objective,
    ProjectUnderstanding,
    Trial,
    Verdict,
    VerdictOutcome,
    new_id,
)
from autonomous_ai_agents.execution.profiler import MAX_HOTSPOTS, MAX_SYMBOL_CHARS
from autonomous_ai_agents.optimization.generate import (
    GENERATE_MAX_TOKENS,
    generate_hypotheses,
)
from autonomous_ai_agents.orchestrator import understand
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.understand import (
    ClaudeUnderstander,
    ReadLimits,
)
from autonomous_ai_agents.research.playbook import (
    MATCH_MAX_TOKENS,
    load_playbook,
    match_techniques,
)

from . import corpus, oss
from . import discovery_ab as ab
from . import discovery_oss as dx
from . import test_discovery_guards as dg
from . import test_oss_guards as og
from .conftest import TESTS_DIR, LiveRun, StartLive, restore_host_key
from .corpus import Loop
from .discovery import (
    BLIND_PROMPT_BOUND,
    CARDS_PROMPT_BOUND,
    MATCH_PROMPT_BOUND,
    OPUS,
    SONNET,
    UNDERSTAND_PROMPT_BOUND,
    PhaseOne,
    RepoFacts,
    carry,
    ceil_usd,
    check_calls,
    generate_arm,
    worst_usd,
)
from .discovery_io import ResultsSink
from .oss import OSS_CORPUS, OSS_RUN_CAP_USD, OssRepo

# Fixtures shared with the discovery and OSS guards (registered by name).
dry = dg.dry
upstream = og.upstream
network_root = og.network_root

LIVE_DIR = TESTS_DIR / "live"
REQUIRED = Isolation("required", None)
Json = dict[str, Any]
FIRST = OSS_CORPUS[:1]
# What the suite needs (the sum of the caps its tests ask the ledger for);
# the Lead copies these into ci.yml. Per task: the generation run (1.30 USD
# for a,b at n = 10) plus one 10-trial loop per arm (10 x 2.50 = 25 USD).
DEFAULT_NEED = 1026.0  # 2 reps x 10 libs x (1.30 + 2 x 25): refused, > 150
ONE_ARM_NEED = {"a": 513.0, "b": 521.0, "c": 519.0}  # 2 x 10 x (gen + 25): refused
ONE_REPO_NEED = 102.6  # 2 reps x 1 lib x (1.30 + 2 x 25): one dispatch a library
ONE_REPO_ONE_ARM_NEED = {"a": 51.3, "b": 52.1, "c": 51.9}
ONE_REPO_ALL_ARMS_NEED = 153.7  # a,b,c on one library: refused
ONE_DISPATCH_TRIAL_CAP = "0.31"  # every library, a,b, n 10 in one dispatch
ONE_DISPATCH_NEED = 150.0  # 2 x 10 x (1.30 + 2 x 3.10)


# ---------------------------------------------------------------------------
# Knobs, arms and caps
# ---------------------------------------------------------------------------


def test_the_defaults_are_arms_a_b_ten_ideas_and_two_reps() -> None:
    """Unset knobs: arms a,b (C is opt-in), 10 ideas an arm, 2 reps (20
    pairs on the corpus), 2.50 USD a trial, every library."""
    assert dx.oss_ab_arms({}) == dx.DEFAULT_ARMS == (dx.ARM_A, dx.ARM_B)
    assert dx.oss_ab_repos({}) == OSS_CORPUS
    assert (dx.OSS_AB_N, dx.OSS_AB_MAX_N, dx.OSS_AB_REPS) == (10, 10, 2)
    assert dx.OSS_AB_N >= ab.AB_N
    assert dx.OSS_TRIAL_CAP_USD == OSS_RUN_CAP_USD / 2 == 2.5
    assert dx.WIN_AT == (1, 3, 5, 10)
    plan = dx.oss_ab_plan({dx.REPOS_ENV: FIRST[0].name})
    assert plan == dx.OssAbPlan(2, dx.DEFAULT_ARMS, 10, 2.5, FIRST)
    assert dx.oss_ab_plan({dx.TRIAL_CAP_ENV: ONE_DISPATCH_TRIAL_CAP}).repos == (
        OSS_CORPUS
    )
    pairs = plan.reps * len(OSS_CORPUS)
    assert pairs == 20  # the McNemar decision's pooled pairs of B vs A


def test_knobs_parse_strictly_before_any_spend() -> None:
    assert dx.oss_ab_arms({dx.ARMS_ENV: "b"}) == (dx.ARM_B,)
    assert dx.oss_ab_arms({dx.ARMS_ENV: "c,a"}) == (dx.ARM_A, dx.ARM_C)  # canonical
    assert dx.oss_ab_arms({dx.ARMS_ENV: "a,b,c"}) == dx.OSS_ARMS
    for value in ("", "d", "a,a", "a,", " a", "A", "a, b", "a;b", "abc"):
        with pytest.raises(ValueError, match=dx.ARMS_ENV):
            dx.oss_ab_arms({dx.ARMS_ENV: value})
    last, first = OSS_CORPUS[-1].name, OSS_CORPUS[0].name
    assert dx.oss_ab_repos({dx.REPOS_ENV: f"{last},{first}"}) == (
        OSS_CORPUS[0],
        OSS_CORPUS[-1],
    )  # the manifest's order
    for value in ("", "nope", f"{first},{first}", first.upper(), f"{first}, {last}"):
        with pytest.raises(ValueError, match=dx.REPOS_ENV):
            dx.oss_ab_repos({dx.REPOS_ENV: value})
    one = {dx.REPOS_ENV: first}
    for value in ("0", "4", "2.0", " 2", "", "two", "٢"):
        with pytest.raises(ValueError, match=dx.REPS_ENV):
            dx.oss_ab_plan({**one, dx.REPS_ENV: value})
    for value in ("2", "11", "0", "3.0", " 3", "ten"):
        with pytest.raises(ValueError, match=dx.N_ENV):
            dx.oss_ab_plan({**one, dx.N_ENV: value})
    assert dx.oss_ab_plan({**one, dx.N_ENV: "3"}).n == ab.AB_N
    assert dx.oss_ab_plan({**one, dx.N_ENV: "10"}).n == 10
    for value in ("0", "-1", "nan", "inf", "2.51", " 1", "x"):
        with pytest.raises(ValueError, match=dx.TRIAL_CAP_ENV):
            dx.oss_ab_plan({**one, dx.TRIAL_CAP_ENV: value})
    assert dx.oss_ab_plan({**one, dx.TRIAL_CAP_ENV: "1.5"}).trial_cap == 1.5


def test_a_plan_past_the_ceiling_is_refused_and_one_library_fits() -> None:
    """The default plan needs more than live-smoke's 150 USD, and so does
    each arm alone: refused, naming the ways to split; one library fits."""
    default = dx.OssAbPlan(2, dx.DEFAULT_ARMS, 10, dx.OSS_TRIAL_CAP_USD)
    assert dx.oss_ab_need(default) == pytest.approx(DEFAULT_NEED)
    with pytest.raises(ValueError) as refused:
        dx.oss_ab_plan({})
    for name in (dx.REPOS_ENV, dx.ARMS_ENV, dx.TRIAL_CAP_ENV, dx.N_ENV, dx.REPS_ENV):
        assert name in str(refused.value), name
    assert "1026.00" in str(refused.value) and "150" in str(refused.value)
    one = {dx.REPOS_ENV: FIRST[0].name}
    for key, need in ONE_ARM_NEED.items():
        plan = replace(default, arms=tuple(a for a in dx.OSS_ARMS if a.key == key))
        assert dx.oss_ab_need(plan) == pytest.approx(need)
        with pytest.raises(ValueError, match="ceiling"):
            dx.oss_ab_plan({dx.ARMS_ENV: key})
        alone = dx.oss_ab_plan({**one, dx.ARMS_ENV: key})
        assert dx.oss_ab_need(alone) == pytest.approx(ONE_REPO_ONE_ARM_NEED[key])
    assert dx.oss_ab_need(dx.oss_ab_plan(one)) == pytest.approx(ONE_REPO_NEED)
    with pytest.raises(ValueError, match="ceiling"):
        dx.oss_ab_plan({**one, dx.ARMS_ENV: "a,b,c"})
    assert dx.oss_ab_need(
        replace(default, arms=dx.OSS_ARMS, repos=FIRST)
    ) == pytest.approx(ONE_REPO_ALL_ARMS_NEED)
    with pytest.raises(ValueError, match="ceiling"):
        dx.oss_ab_plan({**one, dx.REPS_ENV: "3"})  # 3 x 51.30 > 150
    whole = dx.oss_ab_plan({dx.TRIAL_CAP_ENV: ONE_DISPATCH_TRIAL_CAP})
    assert dx.oss_ab_need(whole) == pytest.approx(ONE_DISPATCH_NEED)
    assert dx.CAP_CEILING_USD == dg.CAP_CEILING_USD == 150


def test_the_arms_are_a_b_and_c_on_priced_models_and_accepted_efforts() -> None:
    assert [a.key for a in dx.OSS_ARMS] == ["a", "b", "c"]
    assert [a.label for a in dx.OSS_ARMS] == ["A", "B", "C"]
    assert dx.ARM_A.setting == dx.ARM_B.setting == ab.AB_ARM
    assert (dx.ARM_A.retrieval, dx.ARM_B.retrieval, dx.ARM_C.retrieval) == (
        False,
        True,
        False,
    )
    assert (dx.ARM_C.setting.model, dx.ARM_C.setting.effort) == (OPUS, "low")
    assert dx.ARM_C.setting.label == "opus-5-5-low"
    for arm in dx.OSS_ARMS:
        assert arm.setting.model in settings.MODEL_PRICING, arm
        assert arm.setting.effort in EFFORT_LEVELS[arm.setting.model], arm


def _rounded(total: float, cap: float) -> None:
    assert total <= cap < total + 0.05 + 1e-9, (total, cap)


@pytest.mark.parametrize("n", [ab.AB_N, 4, dx.OSS_AB_N])
def test_each_generation_cap_is_the_sum_of_its_worst_cases(n: int) -> None:
    """No request of the generation run can be refused: it holds phase 1's
    understand request and every selected arm's requests at their worst on
    the OSS bounds, rounded up to 0.05 USD; ten ideas get the generator's
    default output, three E5's 8000."""
    phase = worst_usd(
        dx.OSS_UNDERSTAND_PROMPT_BOUND, settings.UNDERSTAND_MAX_TOKENS, SONNET
    )
    _rounded(phase, dx.OSS_PHASE_ONE_CAP_USD)
    assert dx.OSS_PHASE_ONE_WORST_USD == pytest.approx(phase)
    tokens = ab.AB_GENERATE_MAX_TOKENS if n <= ab.AB_N else GENERATE_MAX_TOKENS
    assert dx.generate_max_tokens(n) == tokens
    worst = {
        "a": worst_usd(dx.OSS_BLIND_PROMPT_BOUND, tokens, SONNET),
        "b": worst_usd(dx.OSS_MATCH_PROMPT_BOUND, MATCH_MAX_TOKENS, SONNET)
        + worst_usd(dx.OSS_CARDS_PROMPT_BOUND, tokens, SONNET),
        "c": worst_usd(dx.OSS_BLIND_PROMPT_BOUND, tokens, OPUS),
    }
    for arm in dx.OSS_ARMS:
        assert dx.arm_worst_usd(arm, n) == pytest.approx(worst[arm.key])
    for picked in ((dx.ARM_A,), (dx.ARM_B,), (dx.ARM_C,), dx.DEFAULT_ARMS, dx.OSS_ARMS):
        total = phase + math.fsum(worst[a.key] for a in picked)
        _rounded(total, dx.gen_cap_usd(picked, n))


def test_the_generation_caps_of_the_default_plan() -> None:
    assert dx.gen_cap_usd(dx.DEFAULT_ARMS, dx.OSS_AB_N) == 1.3
    assert dx.gen_cap_usd(dx.OSS_ARMS, dx.OSS_AB_N) == 1.85
    assert dx.gen_cap_usd(dx.DEFAULT_ARMS, ab.AB_N) == 1.15


def test_a_loop_cap_scales_with_its_trial_count() -> None:
    """A loop has no prompt bound, so its worst case is U24's per trial
    (OSS_RUN_CAP_USD for the manifest's two), times the trials it runs."""
    plan = dx.OssAbPlan(2, dx.DEFAULT_ARMS, 10, dx.OSS_TRIAL_CAP_USD)
    assert plan.loop_cap(dx.OSS_MANIFEST_TRIALS) == OSS_RUN_CAP_USD == 5.0
    caps = [plan.loop_cap(k) for k in range(1, 11)]
    assert caps == [ceil_usd(2.5 * k) for k in range(1, 11)]
    assert caps == sorted(caps) and len(set(caps)) == 10
    assert caps[-1] == 25.0
    for trial_cap, k in ((0.31, 10), (0.33, 3), (0.07, 1), (1.5, 7)):
        cap = replace(plan, trial_cap=trial_cap).loop_cap(k)
        _rounded(k * trial_cap, cap)
    for k in (0, -1):
        with pytest.raises(ValueError, match="at least one trial"):
            plan.loop_cap(k)


def test_the_suite_need_is_the_sum_of_the_caps_run_task_asks_for() -> None:
    tree = ast.parse((LIVE_DIR / "discovery_oss.py").read_text(encoding="utf-8"))
    task = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_task"
    )
    asked = {
        ast.unparse(node.args[0])
        for node in ast.walk(task)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "live"
    }
    assert asked == {"gen_cap_usd(plan.arms, plan.n)", "plan.loop_cap(len(candidates))"}
    for plan in (
        dx.OssAbPlan(1, (dx.ARM_B,), 3, 2.0),
        dx.OssAbPlan(2, dx.OSS_ARMS, 10, 1.0),
        dx.OssAbPlan(3, (dx.ARM_A, dx.ARM_C), 5, 0.5, OSS_CORPUS[:3]),
    ):
        per_task = dx.gen_cap_usd(plan.arms, plan.n) + len(plan.arms) * plan.loop_cap(
            plan.n
        )
        expected = plan.reps * len(plan.repos) * per_task
        assert dx.oss_ab_need(plan) == pytest.approx(expected)
        # a loop gets at most n candidates (the generator keeps the first n)
        assert all(plan.loop_cap(k) <= plan.loop_cap(plan.n) for k in range(1, plan.n))
    assert len(OSS_CORPUS) == 10


# ---------------------------------------------------------------------------
# The OSS prompt bounds: the widest facts any pinned clone may produce
# ---------------------------------------------------------------------------


def _wide_path(index: int, width: int = dx.OSS_MAX_PATH_CHARS) -> str:
    stem = f"d{index:04d}/"
    return stem + "p" * (width - len(stem) - 3) + ".py"


def _widest_facts(root: Path) -> RepoFacts:
    """Every field the generator and the matcher show at its cap: 30 hotspots
    on paths of ``OSS_MAX_PATH_CHARS`` and symbols of the profiler's cap,
    every understanding field full (one workload: one note)."""
    repo = max(OSS_CORPUS, key=lambda r: len(r.name))
    project = repo.project(root)
    spots = tuple(
        Hotspot(
            project_id=project.id,
            workload_id=new_id(),
            file_path=_wide_path(i),
            symbol="s" * MAX_SYMBOL_CHARS,
            line_start=10_000,
            line_end=20_000,
            self_time_s=123.456789,
            total_time_s=123.456789,
            share=0.1234,
            calls=12_345_678,
        )
        for i in range(MAX_HOTSPOTS)
    )
    understanding = ProjectUnderstanding(
        language="p" * understand.MAX_LANGUAGE_CHARS,
        summary="s" * understand.MAX_SUMMARY_CHARS,
        entrypoints=tuple(_wide_path(i) for i in range(understand.MAX_ENTRYPOINTS)),
        workload_notes={new_id(): "n" * understand.MAX_TEXT_CHARS},
        candidate_modules=tuple(
            CandidateModule(path=_wide_path(i), reason="r" * understand.MAX_TEXT_CHARS)
            for i in range(understand.MAX_MODULES)
        ),
        served_by_model=SONNET,
    )
    objective = dg._facts(root).objective.model_copy(
        update={"project_id": project.id, "description": "minimize peak memory"}
    )
    return RepoFacts(project, understanding, spots, objective)


def _generate_n(
    transport: ScriptedTransport,
    facts: RepoFacts,
    techniques: Sequence[Any],
    n: int,
) -> object:
    """The generator's request for ``n`` ideas (the suite's widest ask)."""
    return generate_hypotheses(
        transport,
        Budget(9.0),
        project=facts.project,
        understanding=facts.understanding,
        hotspots=facts.hotspots,
        objective=facts.objective,
        techniques=techniques,
        n=n,
        max_tokens=dx.generate_max_tokens(n),
        sleep=dg._no_sleep,
    )


def test_the_oss_bounds_hold_on_the_widest_facts(tmp_path: Path) -> None:
    facts = _widest_facts(tmp_path)
    playbook = load_playbook()
    cards = sorted(playbook, key=lambda t: -len(t.model_dump_json()))[: ab.AB_K]
    measured = {
        "blind": max(
            dg._count(lambda t: dg._generate(t, facts, ())),
            dg._count(lambda t: _generate_n(t, facts, (), dx.OSS_AB_MAX_N)),
        ),
        "cards": max(
            dg._count(lambda t: dg._generate(t, facts, cards)),
            dg._count(lambda t: _generate_n(t, facts, cards, dx.OSS_AB_MAX_N)),
        ),
        "match": dg._count(
            lambda t: match_techniques(
                t,
                Budget(9.0),
                understanding=facts.understanding,
                hotspots=facts.hotspots,
                techniques=playbook,
                sleep=dg._no_sleep,
            )
        ),
    }
    assert measured["blind"] <= dx.OSS_BLIND_PROMPT_BOUND
    assert measured["cards"] <= dx.OSS_CARDS_PROMPT_BOUND
    assert measured["match"] <= dx.OSS_MATCH_PROMPT_BOUND
    # Wider than the corpus's: its bounds would not hold on OSS clones.
    assert measured["blind"] > BLIND_PROMPT_BOUND
    assert measured["cards"] > CARDS_PROMPT_BOUND
    assert measured["match"] > MATCH_PROMPT_BOUND


@dataclass(frozen=True)
class _FullReader:
    """A repository at every ``ReadLimits`` cap: more entries of the widest
    paths than the listing takes, and every file ``size`` bytes of a byte
    JSON escapes to two (the worst printable ASCII allows)."""

    paths: tuple[str, ...]
    size: int
    fill: bytes = b'"'

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        return self.paths

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = self.fill * self.size
        return data if limit is None else data[:limit]


@pytest.mark.parametrize("size", [3333, 8000, 9000])
@pytest.mark.parametrize("fill", [b'"', b"\\", b"\t"])
def test_the_understand_bound_holds_at_every_read_limit(
    size: int, fill: bytes, tmp_path: Path
) -> None:
    """Repository-independent: what the understander may send is capped by
    ``ReadLimits`` (12 files, 40,000 content bytes, 24,000 listing bytes),
    so the widest paths and escape-only text bound every clone."""
    repo = max(OSS_CORPUS, key=lambda r: len(r.name))
    project = repo.project(tmp_path)
    limits = ReadLimits()
    paths = (
        *(_wide_path(i) for i in range(limits.max_tree_entries + 10)),
        repo.bench_path,
        "README.md",
        "pyproject.toml",
    )
    reader = _FullReader(paths, size, fill)
    scripted = ScriptedTransport([dg._reply("{}")])
    with contextlib.suppress(Exception):  # the reply is unusable: only the request
        ClaudeUnderstander(
            scripted, sleep=dg._no_sleep, reader=lambda _project: reader
        ).understand(
            project, [repo.workload(project)], commit="a" * 40, budget=Budget(9.0)
        )
    (request,) = scripted.requests
    counted = scripted.count_input_tokens(request)
    assert counted <= dx.OSS_UNDERSTAND_PROMPT_BOUND
    assert counted > UNDERSTAND_PROMPT_BOUND  # the corpus bound would not hold


def test_clone_shape_flags_wide_paths_and_non_ascii_names(
    upstream: og.Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    fine = oss.prepare_repo(
        og._local_repo(url, commit), tmp_path / "fine", policy=og.LOCAL
    )
    assert dx.clone_problems(fine.path) == []
    wide = "w" * (dx.OSS_MAX_PATH_CHARS + 1)
    url, commit = upstream(
        {
            "pkg/__init__.py": "def café():\n    return 1\n\nclass Ok:\n    pass\n",
            f"pkg/{wide}.py": "X = 1\n",
            "pkg/old.py": "print 'python 2'\n",  # unparsable: skipped
            "LICENSE": "Permission is hereby granted, free of charge\n",
        }
    )
    bad = oss.prepare_repo(
        og._local_repo(url, commit), tmp_path / "bad", policy=og.LOCAL
    )
    problems = dx.clone_problems(bad.path)
    assert len(problems) == 2, problems
    assert any(wide in p and "characters" in p for p in problems)
    assert any("pkg/__init__.py" in p and "non-ASCII" in p for p in problems)


@pytest.mark.slow
@og.NETWORK
@pytest.mark.parametrize("repo", OSS_CORPUS, ids=og.OSS_IDS)
def test_each_pinned_clone_fits_the_oss_bounds(
    repo: OssRepo, network_root: Path
) -> None:
    """The bounds' one assumption on real clones: tracked paths of at most
    ``OSS_MAX_PATH_CHARS`` printable ASCII and ASCII function and class
    names; and the real understand request on the clone within its bound."""
    user = oss.prepare_repo(repo, network_root / "user")  # the production policy
    assert dx.clone_problems(user.path) == []
    project = repo.project(user.path)
    scripted = ScriptedTransport([dg._reply("{}")])
    with contextlib.suppress(Exception):
        ClaudeUnderstander(scripted, sleep=dg._no_sleep).understand(
            project, [repo.workload(project)], commit=user.base, budget=Budget(9.0)
        )
    counted = scripted.count_input_tokens(scripted.requests[0])
    assert counted <= dx.OSS_UNDERSTAND_PROMPT_BOUND


def test_the_network_case_is_gated_on_its_variable() -> None:
    marks = {
        mark.name
        for mark in getattr(
            test_each_pinned_clone_fits_the_oss_bounds, "pytestmark", []
        )
    }
    assert {"slow", "skipif", "parametrize"} <= marks, marks


# ---------------------------------------------------------------------------
# The engine's settings, phase 1, each arm and the arms' loops
# ---------------------------------------------------------------------------


def test_engine_settings_run_sonnet_without_fallbacks_and_restore() -> None:
    before = (settings.ENGINE_MODEL, settings.ENGINE_FALLBACKS)
    dump = settings.model_dump()
    cfg = ab.ab_settings(settings)
    with dx.engine_settings(cfg):
        assert (settings.ENGINE_MODEL, settings.ENGINE_FALLBACKS) == (SONNET, False)
        assert chain(settings) == (SONNET,)
        assert corpus.settings_trial_budget(settings) == corpus.settings_trial_budget(
            cfg
        )
    assert (settings.ENGINE_MODEL, settings.ENGINE_FALLBACKS) == before
    with pytest.raises(RuntimeError), dx.engine_settings(cfg):
        raise RuntimeError("a breach inside the task")
    assert settings.model_dump() == dump
    assert dx.ENGINE_FIELDS == ("ENGINE_MODEL", "ENGINE_FALLBACKS")


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


@pytest.fixture
def local(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[OssRepo, Path]:
    """A manifest entry on a local upstream, ``WORKTREE_ROOT`` and the key."""
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    return og._local_repo(url, commit), root


def test_phase_one_is_a_zero_candidate_oss_loop_that_spends_first(
    local: tuple[OssRepo, Path], dry: Path
) -> None:
    repo, root = local
    run = LiveRun(
        "dry",
        dx.gen_cap_usd(dx.OSS_ARMS, dx.OSS_AB_N),
        wire=httpx2.MockTransport(_no_wire),
    )
    loop = dx.start_oss_phase_one(repo, run, root / "phase", REQUIRED, policy=og.LOCAL)
    assert loop.candidates == () and tuple(loop.context.candidates) == ()
    assert loop.cap_usd == dx.OSS_PHASE_ONE_CAP_USD < run.cap_usd
    assert loop.mode == "blind" and loop.user.path == root / "phase" / "user"
    assert loop.repo == repo.corpus and run.capture.exchanges == []
    spent = dg.Wire(dg._answer).run()
    generate_arm(ab.AB_ARM, spent, Budget(5.0), dg._facts(dry), n=1)
    with pytest.raises(ValueError, match="first spend"):
        dx.oss_phase_one(repo, spent, root / "again", REQUIRED, policy=og.LOCAL)
    assert not (root / "again").exists()


@pytest.mark.parametrize("n", [ab.AB_N, dx.OSS_AB_N])
def test_each_arm_generates_on_its_own_model_and_effort(dry: Path, n: int) -> None:
    wire = dg.Wire(dg._answer)  # five ideas a generation request
    run = wire.run(cap=dx.gen_cap_usd(dx.OSS_ARMS, n))
    budget = Budget(run.cap_usd)
    playbook = load_playbook()
    produced = [
        dx.generate(arm, run, budget, dg._facts(dry), playbook=playbook, n=n)
        for arm in dx.OSS_ARMS
    ]
    blind, match, cards, opus = wire.bodies
    expected = [(blind, SONNET, "medium"), (match, SONNET, "medium")]
    expected += [(cards, SONNET, "medium"), (opus, OPUS, "low")]
    for body, model, effort in expected:
        assert body["model"] == model and "fallbacks" not in body
        assert body["output_config"]["effort"] == effort
    for body in (blind, cards, opus):
        assert body["max_tokens"] == dx.generate_max_tokens(n)
        assert "hypotheses" in dg._schema_keys(body)
    assert "matches" in dg._schema_keys(match)
    text = "No playbook techniques"
    assert text in blind["messages"][0]["content"][0]["text"]
    assert text in opus["messages"][0]["content"][0]["text"]
    assert "set-membership-test" in cards["system"][0]["text"]
    assert [len(p.hypotheses) for p in produced] == [min(n, 5)] * 3
    assert produced[1].matches and not produced[0].matches
    check_calls(run, budget, produced)


def test_an_arm_loop_is_the_oss_wiring_on_sonnet_with_the_arms_ideas(
    local: tuple[OssRepo, Path], dry: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, root = local
    seen: dict[str, Any] = {}
    real = build_context

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(oss, "build_context", spy)
    produced = dg._generated(dry, ["a", "b"])
    assert all(h.hotspot_ids for h in produced.hypotheses)
    run = LiveRun("dry", OSS_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))
    cfg = ab.ab_settings(settings)
    before = settings.ENGINE_MODEL
    with dx.engine_settings(cfg):
        loop = dx.start_arm_loop(
            repo, run, root / "A", REQUIRED, carry(produced.hypotheses), policy=og.LOCAL
        )
    assert seen["transport"].chain == (SONNET,)
    assert seen["candidates"] == loop.candidates
    assert loop.context.min_trial_budget_usd == corpus.settings_trial_budget(cfg)
    assert [h.title for h in loop.candidates] == ["a", "b"]
    for hypothesis in loop.context.candidates:
        assert hypothesis.hotspot_ids == () and hypothesis.project_id == loop.project.id
    assert loop.mode == "blind" and loop.cap_usd == OSS_RUN_CAP_USD
    assert loop.user.path == root / "A" / "user"
    assert run.capture.exchanges == []
    assert settings.ENGINE_MODEL == before  # restored after the block
    # Every candidate in the loop's one round (the router stops after the
    # first round with a keep), ids kept for the rank rows.
    assert loop.context.max_hypotheses_per_round == len(loop.candidates) == 2
    ids = [h.id for h in produced.hypotheses]
    assert [h.id for h in loop.context.candidates] == ids
    with pytest.raises(ValueError, match="at least one candidate"):
        dx.start_arm_loop(repo, run, root / "B", REQUIRED, (), policy=og.LOCAL)
    assert not (root / "B").exists()


# ---------------------------------------------------------------------------
# Rows, rank rows, win@k, notes, the results file and the summary
# ---------------------------------------------------------------------------

REPO = OSS_CORPUS[0]
KEEP, REJECT = VerdictOutcome.keep, VerdictOutcome.reject


def _row(
    dry: Path,
    rep: int,
    arm: str,
    won: bool | None,
    *,
    guard: str = "ok",
    repo: OssRepo = REPO,
) -> ab.AbRow:
    """``won`` ``None``: no loop ran (no efficiency idea)."""
    produced = dg._generated(dry, ["a"])
    outcome = None if won is None else dg._outcome(repo.corpus, won)
    if outcome is not None:
        outcome = replace(outcome, guard=guard)
    return ab.ab_row(repo.corpus, rep, arm, produced, outcome, frozenset())


def _ideas(dry: Path, classes: str) -> tuple[Hypothesis, ...]:
    """Hypotheses in rank order, one per letter: e efficiency, b behaviour;
    one title for all on purpose (rows match by id, not title)."""
    (base,) = dg._generated(dry, ["same title"]).hypotheses
    kinds = {"e": ChangeClass.efficiency, "b": ChangeClass.behaviour}
    return tuple(
        base.model_copy(update={"id": new_id(), "change_class": kinds[c]})
        for c in classes
    )


def _verdict(
    h: Hypothesis, outcome: VerdictOutcome, gain: float, floor: float, metric: str
) -> Verdict:
    judges = (
        JudgeResult(
            judge="memory",
            outcome=JudgeOutcome.failed,
            metric="peak_memory_bytes",
            gain=0.0,
            noise_floor=0.5,
            reason="r",
        ),
        JudgeResult(
            judge="speed",
            outcome=JudgeOutcome.passed,
            metric=metric,
            gain=gain,
            noise_floor=floor,
            reason="r",
        ),
    )
    return Verdict(
        trial_id=new_id(),
        hypothesis_id=h.id,
        outcome=outcome,
        change_class=h.change_class,
        judge_results=judges,
        gain=gain,
        summary="s",
    )


def _result(
    objective: Objective,
    verdicts: Sequence[Verdict],
    trialled: Sequence[Hypothesis] = (),
) -> EngineRunResult:
    """A finished engine state with these verdicts (the engine's own shape;
    the rehearsal below checks the real one)."""
    ids = {v.hypothesis_id for v in verdicts} | {h.id for h in trialled}
    trials = [Trial(hypothesis_id=i, round=1) for i in sorted(ids)]
    state = {
        "objectives": [objective],
        "trials": trials,
        "verdicts": list(verdicts),
        "budget_exhausted": False,
    }
    return EngineRunResult("run", "done", cast(Any, state), None)


def test_rank_rows_follow_the_generators_order_and_read_each_verdict(
    dry: Path,
) -> None:
    ideas = _ideas(dry, "ebeee")
    objective = dg._facts(dry).objective
    metric = objective.metric
    verdicts = [
        _verdict(ideas[2], KEEP, 0.12, 0.02, metric),
        _verdict(ideas[0], REJECT, 0.01, 0.03, metric),
    ]
    result = _result(objective, verdicts, trialled=[ideas[3]])  # 5: budget stop
    rows = dx.rank_rows("r", 2, "B", ideas, result, guard="ok")
    assert [r.rank for r in rows] == [1, 2, 3, 4, 5]
    assert [r.verdict for r in rows] == [
        "reject",
        dx.NOT_HANDED,
        "keep",
        dx.NO_VERDICT,
        dx.NOT_TRIALLED,
    ]
    assert [r.change_class for r in rows] == [
        "efficiency",
        "behaviour",
        "efficiency",
        "efficiency",
        "efficiency",
    ]
    assert rows[2].gain_pct == pytest.approx(12.0)
    assert rows[2].noise_floor_pct == pytest.approx(2.0)  # the primary judge's
    assert rows[0].noise_floor_pct == pytest.approx(3.0)
    assert rows[1].gain_pct is None and rows[1].noise_floor_pct is None
    assert {(r.repo, r.rep, r.arm, r.title, r.guard) for r in rows} == {
        ("r", 2, "B", "same title", "ok")
    }
    assert dx.kept_ranks(rows) == (3,)
    none = dx.rank_rows("r", 1, "A", ideas, None, guard="breach: x")
    assert [r.verdict for r in none] == [
        dx.NO_RESULT,
        dx.NOT_HANDED,
        *[dx.NO_RESULT] * 3,
    ]
    record = rows[2].record()
    assert record["experiment"] == dx.RANK_EXPERIMENT == "E5-oss-ab-rank"
    assert record["rank"] == 3 and record["verdict"] == "keep"


def _task(
    dry: Path,
    arm: str,
    kept: Sequence[int],
    *,
    rep: int = 1,
    n: int = 10,
    guard: str = "ok",
) -> tuple[ab.AbRow, list[dx.RankRow]]:
    """One task's row and its ``n`` rank rows, ``kept`` the ranks kept."""
    ideas = _ideas(dry, "e" * n)
    objective = dg._facts(dry).objective
    verdicts = [
        _verdict(h, KEEP if rank in kept else REJECT, 0.1, 0.02, objective.metric)
        for rank, h in enumerate(ideas, start=1)
    ]
    result = _result(objective, verdicts)
    ranks = dx.rank_rows(REPO.name, rep, arm, ideas, result, guard=guard)
    return _row(dry, rep, arm, bool(kept), guard=guard), ranks


def test_win_at_k_reads_the_rank_ordered_prefix(dry: Path) -> None:
    _, ranks = _task(dry, "A", kept=(3, 7))
    assert [dx.win_at(ranks, k) for k in (1, 2, 3, 5, 7, 10)] == [
        False,
        False,
        True,  # a keep at rank exactly k counts for k
        True,
        True,
        True,
    ]
    _, ties = _task(dry, "A", kept=(1, 2, 3))
    assert [dx.win_at(ties, k) for k in (1, 3, 10)] == [True] * 3  # one win, not 3
    _, short = _task(dry, "A", kept=(4,), n=4)
    assert dx.win_at(short, 10) and dx.win_at(short, 5)  # past the list: all of it
    assert not dx.win_at(short, 3)
    assert not dx.win_at([], 10)


def test_win_curve_counts_tasks_whose_guards_held(dry: Path) -> None:
    """Per arm, (wins, tasks) for k in 1, 3, 5, 10: ties count once, an arm
    with no efficiency idea is a held loss, a breach leaves the count."""
    tasks = [
        _task(dry, "A", kept=(1,), rep=1),
        _task(dry, "A", kept=(4, 5), rep=2),  # tied keeps: one task won from k = 5
        _task(dry, "A", kept=(10,), rep=3),
        _task(dry, "A", kept=(2,), rep=4, guard="breach: x"),  # not counted
        _task(dry, "B", kept=(), rep=1),
    ]
    rows = [row for row, _ in tasks]
    ranks = [r for _, group in tasks for r in group]
    rows.append(_row(dry, 99, "B", None))  # no efficiency idea: no loop ran
    behaviour = _ideas(dry, "bb")
    ranks += dx.rank_rows(REPO.name, 99, "B", behaviour, None, guard="ok")
    assert len({(r.repo, r.rep, r.arm) for r in rows}) == len(rows)
    assert dx.win_curve(rows, ranks, "A") == {
        1: (1, 3),
        3: (1, 3),
        5: (2, 3),
        10: (3, 3),
    }
    assert dx.win_curve(rows, ranks, "B") == {k: (0, 2) for k in dx.WIN_AT}
    assert dx.win_curve(rows, ranks, "C") == {k: (0, 0) for k in dx.WIN_AT}
    _, middle = dx.summary_notes(rows, ranks)[:2]
    assert middle == "OSS-AB win in top 1/3/5/10: A 1,1,2,3 of 3; B 0,0,0,0 of 2"
    text = dx.render_oss_ab(rows, ranks)
    assert (
        "| arm | win in top 1 | win in top 3 | win in top 5 | win in top 10 |" in text
    )
    assert "| A | 1/3 (33.3%) | 1/3 (33.3%) | 2/3 (66.7%) | 3/3 (100.0%) |" in text
    assert "| B | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) | 0/2 (0.0%) |" in text
    assert f"| {REPO.name} | 99 | B | 2 | same title | behaviour | not_handed |" in text


def test_rows_go_to_the_results_file_and_each_run_gets_a_note(dry: Path) -> None:
    results = dry / "results.jsonl"
    sink = ResultsSink({corpus.RESULTS_ENV: str(results)})
    plan = dx.OssAbPlan(1, dx.OSS_ARMS, 3, 1.0)
    recorder = dx.OssAbRecorder(plan, sink, ab.load_distractors())
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    produced = dg._generated(dry, ["a", "b"])
    objective = dg._facts(dry).objective
    first, second = produced.hypotheses
    result = _result(
        objective,
        [
            _verdict(first, REJECT, 0.01, 0.02, objective.metric),
            _verdict(second, KEEP, 0.2, 0.02, objective.metric),
        ],
    )
    won = replace(dg._outcome(REPO.corpus, True), kept=("cache the rows",))
    recorder.record(REPO, 1, dx.ARM_A, produced, won, result, run=run, phase_cost=0.031)
    recorder.record(REPO, 1, dx.ARM_C, produced, None, run=run, phase_cost=0.031)
    breach = "breach: AssertionError: the arm billed another model"
    recorder.record(
        REPO, 1, dx.ARM_B, produced, None, run=run, phase_cost=0.031, guard=breach
    )
    gen = f"{produced.cost_usd:.4f}"
    assert run.notes == [
        f"OSS-AB {REPO.name} rep 1 arm A: delivered yes, gain 50.0%, keep ranks 2, "
        f"kept cache the rows, {gen}+0.0500 USD, guard ok",
        f"OSS-AB {REPO.name} rep 1 arm C: delivered no, gain -, keep ranks -, kept "
        f"none, {gen}+0.0000 USD, guard ok",
        f"OSS-AB {REPO.name} rep 1 arm B: delivered no, gain -, keep ranks -, kept "
        f"none, {gen}+0.0000 USD, guard breach",
    ]
    lines = [json.loads(x) for x in results.read_text().splitlines()]
    rows = [x for x in lines if x["experiment"] == dx.OSS_EXPERIMENT]
    ranked = [x for x in lines if x["experiment"] == dx.RANK_EXPERIMENT]
    assert [x["experiment"] for x in lines] == [
        dx.OSS_EXPERIMENT,
        *[dx.RANK_EXPERIMENT] * 2,
    ] * 3
    assert [x["arm"] for x in rows] == ["A", "C", "B"]
    assert [x["arm_setting"] for x in rows] == [
        "sonnet-5-5-medium",
        "opus-5-5-low",
        "sonnet-5-5-medium",
    ]
    assert [x["retrieval"] for x in rows] == [False, False, True]
    assert {x["n"] for x in rows} == {3}
    assert rows[0]["phase_one_cost_usd"] == 0.031 and rows[0]["win"] is True
    assert rows[1]["status"] == "no_hypotheses" and rows[1]["guard"] == "ok"
    assert rows[2]["status"] == "not_run" and rows[2]["guard"] == breach
    assert [(x["arm"], x["rank"], x["verdict"]) for x in ranked] == [
        ("A", 1, "reject"),
        ("A", 2, "keep"),
        ("C", 1, dx.NO_RESULT),
        ("C", 2, dx.NO_RESULT),
        ("B", 1, dx.NO_RESULT),
        ("B", 2, dx.NO_RESULT),
    ]
    assert ranked[1]["gain_pct"] == pytest.approx(20.0)
    assert ranked[1]["noise_floor_pct"] == pytest.approx(2.0)
    assert ranked[4]["guard"] == breach
    assert [r.arm for r in recorder.rows] == ["A", "C", "B"]
    assert len(recorder.ranks) == 6


def test_the_longest_note_fits_one_cost_table_cell(dry: Path) -> None:
    """A note past the cost table's 200-character cell is cut: the cost at
    its end would be lost, so the kept titles get what is left."""
    title = "t" * 120  # the generator's title cap
    row = replace(
        _row(dry, 3, "C", True),
        repo="r" * 40,  # the manifest's longest name
        gain_pct=-100.0,
        kept=(title, title, title),
        generation_cost_usd=9.9999,
        engine_cost_usd=9.9999,
        guard="breach: x",
    )
    note = dx.run_note(row, tuple(range(1, 11)))
    assert len(note) == dx.NOTE_CHARS == 200, len(note)
    assert note.endswith("9.9999+9.9999 USD, guard breach")
    assert "keep ranks 1,2,3,4,5,6,7,8,9,10, kept ttt" in note and "…" in note
    short = dx.run_note(replace(row, kept=("x",)), ())
    assert "keep ranks -, kept x, " in short and "…" not in short
    rows = [replace(row, arm=a, rep=i) for i in range(30) for a in "ABC"]
    notes = dx.summary_notes(rows, [])
    assert all(len(n) <= dx.NOTE_CHARS for n in notes), notes


def _rows(dry: Path) -> list[ab.AbRow]:
    repos = OSS_CORPUS[:5]
    plan = {  # repo index: (A, B, C); None: no loop; "breach": B's loop breached
        0: (True, False, True),
        1: (False, True, True),
        2: (False, True, None),
        3: (True, "breach", False),
    }
    rows: list[ab.AbRow] = []
    for index, wins in plan.items():
        for label, won in zip("ABC", wins, strict=True):
            if won == "breach":
                rows.append(
                    _row(dry, 1, label, True, guard="breach: x", repo=repos[index])
                )
            else:
                assert won is None or isinstance(won, bool)
                rows.append(_row(dry, 1, label, won, repo=repos[index]))
    rows.append(_row(dry, 1, "A", False, repo=repos[4]))  # B and C never ran
    return rows


def test_the_summary_pairs_b_and_c_against_a_with_mcnemar(dry: Path) -> None:
    rows = _rows(dry)
    pairs, b, c, excluded = dx.versus(rows, "B")
    assert (len(pairs), b, c, excluded) == (3, 1, 2, 2)
    pairs, b, c, excluded = dx.versus(rows, "C")
    assert (len(pairs), b, c, excluded) == (4, 1, 1, 1)
    assert dx.versus([*rows, *rows], "B")[1:3] == (1, 2)  # the first row per arm
    text = dx.render_oss_ab(rows)
    assert text.startswith("## OSS discovery A/B")
    assert "B vs A: 3 paired task(s) (excluded 2" in text
    assert "C vs A: 4 paired task(s) (excluded 1" in text
    assert "b = 1 (A won, B lost), c = 2 (A lost, B won)" in text
    assert f"McNemar p = {ab.mcnemar_exact(1, 2):.4f}" in text
    assert "Context: aimed hypotheses, run 40061541473: 6/10 delivered" in text
    assert "| A | sonnet-5-5-medium | 2/5 (40.0%) | 50.0 |" in text
    assert "| B | sonnet-5-5-medium | 2/3 (66.7%) | 50.0 |" in text  # 1 breach
    assert "| C | opus-5-5-low | 2/4 (50.0%) | 50.0 |" in text
    first, curve, second = dx.summary_notes(rows)
    assert first.startswith("OSS-AB arms after 5 task(s): A 2/5 won, gain 50.0%")
    assert "B 2/3 won" in first and "C 2/4 won" in first and "USD/win" in first
    assert curve == (  # no rank rows: no idea was kept at any rank
        "OSS-AB win in top 1/3/5/10: A 0,0,0,0 of 5; B 0,0,0,0 of 3; C 0,0,0,0 of 4"
    )
    assert second == (
        "OSS-AB paired: B vs A 3 pair(s), b 1, c 2, p 1.0000, excl 2; "
        "C vs A 4 pair(s), b 1, c 1, p 1.0000, excl 1"
    )
    only_a = [r for r in rows if r.arm == "A"]
    assert "B vs A: no pairs" in dx.render_oss_ab(only_a)
    assert dx.summary_notes(only_a)[2] == (
        "OSS-AB paired: B vs A 0 pair(s), excl 5; C vs A 0 pair(s), excl 5"
    )
    assert "No OSS A/B task finished." in dx.render_oss_ab([])
    assert dx.summary_notes([])[1] == "OSS-AB win in top 1/3/5/10: no task"


def test_the_summary_sanitises_hostile_text(dry: Path) -> None:
    hostile = dg._hostile_outcome()
    row = replace(
        _row(dry, 1, "A", True),
        repo=hostile.repo,
        guard=hostile.guard,
        kept=("[x](https://e.example) `c` <b>",),
    )
    rank = dx.RankRow(
        hostile.repo, 1, "A", 1, hostile.repo, "efficiency", "keep", 1.0, 0.1, "ok"
    )
    dg._check_inert(dx.render_oss_ab([row], [rank]))


def test_finish_writes_the_summary_once_and_echoes_it(dry: Path) -> None:
    summary = dry / "summary.md"
    environ = {corpus.SUMMARY_ENV: str(summary)}
    recorder = dx.OssAbRecorder(
        dx.OssAbPlan(1, dx.OSS_ARMS, 3, 1.0), ResultsSink(environ), frozenset()
    )
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert echoed == [] and not summary.exists()
    run = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    recorder.record(
        REPO, 1, dx.ARM_A, dg._generated(dry, ["a"]), None, run=run, phase_cost=0.0
    )
    recorder.note_summary(run)
    assert run.notes[-3].startswith("OSS-AB arms after 1 task(s)")
    assert run.notes[-2].startswith("OSS-AB win in top 1/3/5/10: A 0,0,0,0 of 1")
    assert run.notes[-1] == (
        "OSS-AB paired: B vs A 0 pair(s), excl 1; C vs A 0 pair(s), excl 1"
    )
    recorder.finish(echoed.append)
    assert echoed[0].endswith("written to the job summary")
    assert echoed[1:] == summary.read_text().splitlines()
    assert any(line.startswith("| arm | win in top 1 |") for line in echoed)


def _starter(wire: dg.Wire) -> tuple[list[LiveRun], StartLive]:
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry[{len(runs)}]", cap_usd, wire=httpx2.MockTransport(wire))
        runs.append(run)
        return run

    return runs, start


SMALL = {dx.TRIAL_CAP_ENV: "0.1"}  # every library in one plan, within the ceiling


def test_a_phase_one_failure_is_noted_on_its_run_then_raised(
    local: tuple[OssRepo, Path],
) -> None:
    repo, root = local  # a file:// upstream: the production policy refuses it
    runs, start = _starter(dg.Wire(dg._answer))
    recorder = dx.OssAbRecorder(dx.oss_ab_plan(SMALL), ResultsSink({}), frozenset())
    with pytest.raises(oss.CloneRefusedError):
        dx.run_task(
            repo, 2, live=start, root=root, isolation=REQUIRED, recorder=recorder
        )
    (gen,) = runs
    assert gen.cap_usd == dx.gen_cap_usd(dx.DEFAULT_ARMS, dx.OSS_AB_N)
    assert gen.records == [] and recorder.rows == []
    assert gen.notes[0].startswith(
        f"OSS-AB {repo.name} rep 2: phase 1 breach: CloneRefusedError: "
    )
    assert [n.split(":")[0] for n in gen.notes[1:]] == [
        "OSS-AB arms after 0 task(s)",
        "OSS-AB win in top 1/3/5/10",
        "OSS-AB paired",
    ]


def test_a_loop_that_cannot_start_is_recorded_then_raised(
    local: tuple[OssRepo, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, root = local
    probe = LiveRun("dry", 1.0, wire=httpx2.MockTransport(_no_wire))
    loop = dx.start_oss_phase_one(
        repo, probe, root / "phase", REQUIRED, policy=og.LOCAL
    )
    phase = PhaseOne(loop, dg._facts(root), 0.0)
    monkeypatch.setattr(dx, "oss_phase_one", lambda *a, **k: phase)

    def refused(*args: object, **kwargs: object) -> Loop:
        raise oss.CloneRefusedError("git fetch failed (exit 128): reset")

    monkeypatch.setattr(dx, "start_arm_loop", refused)
    runs, start = _starter(dg.Wire(dg._answer))
    recorder = dx.OssAbRecorder(dx.oss_ab_plan(SMALL), ResultsSink({}), frozenset())
    before = settings.ENGINE_MODEL
    with pytest.raises(oss.CloneRefusedError):
        dx.run_task(
            repo, 1, live=start, root=root, isolation=REQUIRED, recorder=recorder
        )
    gen, first = runs  # B never started: the task failed at A's clone
    assert len(_bodies(gen)) == 3  # A, B's matcher and generator
    assert first.cap_usd == recorder.plan.loop_cap(5) == 0.5  # A's five ideas
    (row,) = recorder.rows
    assert (row.arm, row.status, row.win) == ("A", "not_run", False)
    assert row.guard == "breach: CloneRefusedError: git fetch failed (exit 128): reset"
    assert [r.verdict for r in recorder.ranks] == [dx.NO_RESULT] * 5
    assert first.notes[0].endswith("guard breach")
    assert first.notes[1].startswith("OSS-AB arms after 1 task(s): A 0/0 won")
    assert first.notes[2] == "OSS-AB win in top 1/3/5/10: A 0,0,0,0 of 0"
    assert dx.versus(recorder.rows, "B")[3] == 1  # excluded from every pair
    assert settings.ENGINE_MODEL == before  # restored after the failure


# ---------------------------------------------------------------------------
# The live module
# ---------------------------------------------------------------------------


def test_the_live_module_is_marked_parses_its_plan_first_and_runs_tasks() -> None:
    source = (LIVE_DIR / "test_oss_ab_live.py").read_text(encoding="utf-8")
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
    assert [t.name for t in tests] == ["test_oss_discovery_ab"]
    assert "live" in [a.arg for a in tests[0].args.args]  # admits and refuses xdist
    assert '@pytest.fixture(scope="module")' in source
    assert "oss_ab_plan(os.environ)" in source and "load_distractors()" in source
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(tests[0])
        if isinstance(node, ast.Call)
    }
    assert "run_task" in calls and "live" not in calls


# ---------------------------------------------------------------------------
# A whole task, rehearsed offline in the sandbox (only the wire is a mock)
# ---------------------------------------------------------------------------

LIBRARY = {
    "pkg/__init__.py": (
        "def total(n):\n    out = 0\n    for i in range(n):\n"
        "        out += i * i\n    return out\n"
    ),
    "tests/__init__.py": "",
    "tests/test_pkg.py": (
        "import unittest\n\nimport pkg\n\n\nclass TotalTest(unittest.TestCase):\n"
        "    def test_total(self):\n        self.assertEqual(pkg.total(4), 14)\n"
    ),
    "LICENSE": "Permission is hereby granted, free of charge\n",
}
WORKLOAD = "import pkg\n\nprint(pkg.total(300_000))\n"


@dataclass(frozen=True)
class _Rehearsal(OssRepo):
    """A manifest entry whose workload is a file of the test's own."""

    source: Path = Path()

    @property
    def workload_source(self) -> Path:
        return self.source


def _rehearsal_answer(body: Json) -> str:
    """Understand, match and generate as the dry wire does (Sonnet's two
    ideas are efficiency-class; Opus's one is behaviour-class, so arm C hands
    no candidate over); the editor gets a plain answer, so every trial
    changes nothing."""
    if body.get("output_config", {}).get("format") is None:
        return "I leave the code as it is."
    if "hypotheses" in dg._schema_keys(body):
        if body["model"] == OPUS:
            item = {**dg._item("cache the totals"), "hotspots": []}
            return json.dumps({"hypotheses": [{**item, "change_class": "behaviour"}]})
        titles = ("cache the totals", "use a closed form")
        items = [{**dg._item(t), "hotspots": []} for t in titles]
        return json.dumps({"hypotheses": items})
    return dg._answer(body)


def _bodies(run: LiveRun) -> list[Json]:
    return [exchange.json() for exchange in run.capture.messages()]


@pytest.mark.slow
def test_a_whole_task_rehearsed_offline_in_the_sandbox(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    og._require_sandbox()
    url, commit = upstream(LIBRARY)
    root = Path(os.path.realpath(tmp_path))
    bench = root / "bench.py"
    bench.write_text(WORKLOAD, encoding="utf-8")
    base = og._local_repo(url, commit)
    repo = _Rehearsal(
        **{f.name: getattr(base, f.name) for f in fields(OssRepo)}, source=bench
    )
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    wire = dg.Wire(_rehearsal_answer)
    runs: list[LiveRun] = []

    def start(cap_usd: float) -> LiveRun:
        run = LiveRun(f"dry[{len(runs)}]", cap_usd, wire=httpx2.MockTransport(wire))
        runs.append(run)
        return run

    results = root / "results.jsonl"
    plan = dx.oss_ab_plan(
        {dx.REPS_ENV: "1", dx.ARMS_ENV: "a,b,c", dx.N_ENV: "3", dx.TRIAL_CAP_ENV: "0.5"}
    )
    recorder = dx.OssAbRecorder(
        plan, ResultsSink({corpus.RESULTS_ENV: str(results)}), ab.load_distractors()
    )
    before = settings.ENGINE_MODEL
    task = root / "task"
    task.mkdir()
    dx.run_task(
        repo,
        1,
        live=start,
        root=task,
        isolation=REQUIRED,
        recorder=recorder,
        policy=og.LOCAL,
    )
    assert settings.ENGINE_MODEL == before  # restored after the task
    assert [(r.arm, r.status, r.guard) for r in recorder.rows] == [
        ("A", "done", "ok"),
        ("B", "done", "ok"),
        ("C", "no_hypotheses", "ok"),
    ]
    gen, loop_a, loop_b = runs
    assert (gen.cap_usd, loop_a.cap_usd, loop_b.cap_usd) == (1.5, 1.0, 1.0)
    assert gen.cap_usd == dx.gen_cap_usd(dx.OSS_ARMS, 3)
    assert loop_a.cap_usd == plan.loop_cap(2)  # two ideas handed over
    understand_body, *arm_bodies = _bodies(gen)
    assert understand_body["model"] == SONNET and "fallbacks" not in understand_body
    assert [b["model"] for b in arm_bodies] == [SONNET, SONNET, SONNET, OPUS]
    for run in (loop_a, loop_b):
        bodies = _bodies(run)
        assert len(bodies) >= 3  # understand and an editor turn a trial
        assert {b["model"] for b in bodies} == {SONNET}
        assert not any("fallbacks" in b for b in bodies)
    assert {(r.repo, r.rep) for r in recorder.rows} == {(repo.name, 1)}
    for row in recorder.rows[:2]:
        assert row.candidates == 2 and not row.win and row.engine_cost_usd > 0
    # Both ideas trialled in each arm's one loop, matched by id to the rank.
    ranked = [(r.arm, r.rank, r.title, r.verdict) for r in recorder.ranks]
    assert [x[:3] for x in ranked] == [
        ("A", 1, "cache the totals"),
        ("A", 2, "use a closed form"),
        ("B", 1, "cache the totals"),
        ("B", 2, "use a closed form"),
        ("C", 1, "cache the totals"),
    ]
    assert {v for _, _, _, v in ranked[:4]} <= {"reject", "inconclusive"}, ranked
    assert ranked[4][3] == dx.NOT_HANDED
    assert recorder.rows[2].dropped == 1 and recorder.rows[2].engine_cost_usd == 0
    assert [n.split(":")[0] for n in gen.notes] == [f"OSS-AB {repo.name} rep 1 arm C"]
    assert loop_a.notes[0].startswith(f"OSS-AB {repo.name} rep 1 arm A: delivered no")
    assert loop_b.notes[0].startswith(f"OSS-AB {repo.name} rep 1 arm B: delivered no")
    assert len(loop_b.notes) == 4
    assert "keep ranks -" in loop_b.notes[0]
    assert loop_b.notes[1].startswith("OSS-AB arms after 1 task(s): A 0/1 won")
    assert (
        loop_b.notes[2]
        == "OSS-AB win in top 1/3/5/10: A 0,0,0,0 of 1; B 0,0,0,0 of 1; C 0,0,0,0 of 1"
    )
    assert loop_b.notes[3].startswith(
        "OSS-AB paired: B vs A 1 pair(s), b 0, c 0, p 1.0000, excl 0; "
    )
    lines = [json.loads(x) for x in results.read_text().splitlines()]
    ab_exp, rank_exp = dx.OSS_EXPERIMENT, dx.RANK_EXPERIMENT
    assert [(x["experiment"], x["arm"]) for x in lines] == [
        (ab_exp, "A"),
        (rank_exp, "A"),
        (rank_exp, "A"),
        (ab_exp, "B"),
        (rank_exp, "B"),
        (rank_exp, "B"),
        (ab_exp, "C"),
        (rank_exp, "C"),
    ]
    for name in ("phase", "A", "B"):
        assert git(task / name / "user", "rev-parse", "HEAD") == git(
            task / "phase" / "user", "rev-parse", "HEAD"
        )
    assert not (task / "C").exists()
