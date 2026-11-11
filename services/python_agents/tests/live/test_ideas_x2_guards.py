"""Offline guards of the ideas-x2 suite (X2a, ``ideas_x2.py``; spec-idea-lab
section 9, O48).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_x2_live.py``, that each arm is its settings exactly (the shared
setup, Haiku 5.5 on the eliminate lens, X2-V's views ``ideas_probe.X1_VIEWS``
with no framework); that an arm's env mapping, as ci.yml exports it, builds
exactly that arm's ``Settings`` and reaches the engine the wired loop
builds (``start_x2_loop``: ``oss.start_oss_loop`` with each own-model lane's
captured transport, which ``start_oss_loop`` does not pass); that the twin runs on its four libraries only; that the per-run cap
holds the seeded call at X1's measured rates under the engine's own
reservation rule (``nodes._discovery_cap`` and ``Budget.check``) and is
tight; the need, the fuse, the job's minutes and the suite cap refused
before any spend; ``OP_COUNT_JUDGE`` asserted before spend; and the
per-run, per-round and per-hypothesis records.

Fakes and what they stand for: ``og.LOCAL`` and a ``file://`` bare upstream
for GitHub over https (``oss.PRODUCTION``); a ``MockTransport`` that fails
any request for the Messages API (the wiring is built, never sent); a fake
``start_x2_loop`` / ``run_engine`` with a hand-built engine state for the
whole engine run (events, trials, verdicts and the combine as the nodes
write them). What only a live run proves: the engine's verdicts, seeds,
compounds and costs on the eight libraries.
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import os
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import Settings, lane_chain, settings
from autonomous_ai_agents.common.errors import BudgetExceeded
from autonomous_ai_agents.common.models import (
    Baseline,
    ChangeClass,
    Combination,
    EngineEvent,
    Hypothesis,
    HypothesisSource,
    RunPhase,
    Trial,
    Verdict,
    VerdictOutcome,
)
from autonomous_ai_agents.optimization.evolve import COMPOUND_TAG, compound_id
from autonomous_ai_agents.optimization.idea_dedupe import KEY_EVENT
from autonomous_ai_agents.optimization.idea_pipeline import (
    SEEDED_CALL,
    IdeaPipelineGenerator,
)
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane
from autonomous_ai_agents.optimization.judges import OP_COUNT_JUDGE, OpCountJudge
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.nodes import (
    _discovery_cap,
    make_nodes,
    make_router,
)
from autonomous_ai_agents.orchestrator.state import initial_state

from . import discovery_oss as dx
from . import ideas_probe as ip
from . import ideas_slice as isl
from . import ideas_x2 as x2
from . import oss
from . import test_ideas_slice_guards as sg
from . import test_ideas_x2_live as live
from . import test_oss_guards as og
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun, StartLive, restore_host_key
from .corpus import RESULTS_ENV, settings_trial_budget
from .discovery import FABLE, OPUS, SONNET, ceil_usd
from .discovery_io import ResultsSink

upstream = og.upstream

Json = dict[str, Any]
REQUIRED = Isolation("required", None)
SECRET = sg.SECRET
FIRST, SECOND = ",".join(ip.E1_REPOS[:4]), ",".join(ip.E1_REPOS[4:])
X2_0_NEED = {x2.DISPATCH_ENV: f"X2-0:{FIRST}", SUITE_CAP_ENV: "38"}


def _cfg(**update: object) -> Settings:
    return settings.model_copy(update=update)


def _arm_cfg(arm: x2.X2Arm) -> Settings:
    return x2.arm_settings(arm, _cfg())


# ---------------------------------------------------------------------------
# The arms: each its settings exactly
# ---------------------------------------------------------------------------


def test_the_arms_and_their_libraries() -> None:
    assert [a.key for a in x2.X2_ARMS] == ["X2-0", "X2-0'", "X2-V"]
    assert x2.X2_0.repos == x2.X2_V.repos == ip.E1_REPOS
    assert x2.X2_0_TWIN.repos == isl.SLICE_REPOS  # the four slice libraries
    assert x2.X2_0.update == x2.X2_0_TWIN.update == x2.SHARED
    assert x2.X2_V.update == {**x2.SHARED, "IDEAS_LANE_VIEWS": dict(ip.X1_VIEWS)}
    twin = ",".join(isl.SLICE_REPOS)
    assert x2.dispatches() == (f"X2-0:{FIRST}", f"X2-0:{SECOND}", f"X2-0':{twin}",
                               f"X2-V:{FIRST}", f"X2-V:{SECOND}")  # fmt: skip
    plans = [x2.x2_plan({x2.DISPATCH_ENV: d, SUITE_CAP_ENV: "38"})
             for d in x2.dispatches()]  # fmt: skip
    assert [r for p in plans for r in p.runs] == list(x2.ALL_RUNS)  # each run once


@pytest.mark.parametrize("arm", x2.X2_ARMS, ids=lambda a: a.key)
def test_every_arm_runs_the_shared_setup(arm: x2.X2Arm) -> None:
    cfg = _arm_cfg(arm)
    assert cfg.IDEA_PIPELINE and cfg.PORTFOLIO_ROUNDS == cfg.MAX_TRIAL_ROUNDS == 2
    assert cfg.IDEAS_ROUND_SEEDS and cfg.NEAR_MISS_COMPOUNDS and cfg.OP_COUNT_JUDGE
    assert not cfg.GENERATOR_LESSONS  # lessons are X3's
    assert not cfg.IDEAS_SEQUENTIAL_LANES and not cfg.IDEAS_MECHANISM_DEDUPE
    assert cfg.IDEAS_RELAX_LANES == () and cfg.IDEAS_LENSES == LENS_LANES
    assert not cfg.IDEAS_LANE_FRAMEWORKS and not cfg.IDEAS_THINK_LINE_ALL
    models = {lane: lane_chain(cfg, lane)[0] for lane in (Lane.obvious, *LENS_LANES)}
    assert models == {
        lane: ip.HAIKU if lane is Lane.eliminate else SONNET for lane in models
    }
    assert (lane_chain(cfg, Lane.leap)[0], cfg.IDEAS_REVIEWER_MODEL) == (OPUS, OPUS)
    assert FABLE not in {*models.values(), cfg.IDEAS_LEAP_MODEL}  # no Fable lane
    views = dict(ip.X1_VIEWS) if arm is x2.X2_V else {}
    assert cfg.IDEAS_LANE_VIEWS == views


def test_the_shared_setup_is_x1_0_with_x2s_changes_alone() -> None:
    """X1-0's settings (``ideas_probe.arm_config``, the think line as there)
    and X2-0's differ only in what X2 adds; X2-V only in its views."""
    base = _cfg()
    project = dx.OSS_SELECTABLE[0].project(Path("/x"))
    x1 = ip.arm_config(ip.ARM_X1_0, project, base).model_dump()
    ours = x2.arm_settings(x2.X2_0, base).model_dump()
    moved = {k for k in ours if ours[k] != x1[k]}
    assert moved <= {"PORTFOLIO_ROUNDS", "MAX_TRIAL_ROUNDS", "IDEAS_ROUND_SEEDS",
                     "NEAR_MISS_COMPOUNDS", "OP_COUNT_JUDGE", "IDEAS_LANE_MODELS",
                     "IDEAS_VIEW_RECORD"}  # fmt: skip
    assert "IDEAS_LANE_MODELS" in moved
    views = x2.arm_settings(x2.X2_V, base).model_dump()
    assert {k for k in views if views[k] != ours[k]} == {"IDEAS_LANE_VIEWS"}


@pytest.mark.parametrize("arm", x2.X2_ARMS, ids=lambda a: a.key)
def test_an_arms_env_builds_exactly_its_settings(
    arm: x2.X2Arm, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ci.yml exports ``arm_env`` into the job: the engine's ``Settings``
    built from it are the arm's on every field, and on no other."""
    env = x2.arm_env(arm)
    assert set(env) == set(arm.update)
    assert env["IDEAS_LANE_MODELS"] == '{"eliminate":"claude-haiku-5-5"}'
    assert env["IDEAS_RELAX_LANES"] == "[]" and env["OP_COUNT_JUDGE"] == "true"
    assert json.loads(env["IDEAS_LANE_VIEWS"]) == dict(
        ip.X1_VIEWS if arm is x2.X2_V else {}
    )
    plain = Settings(_env_file=None)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    built = Settings(_env_file=None)
    assert built.model_dump() == x2.arm_settings(arm, plain).model_dump()
    x2.check_settings(arm, built)


@pytest.mark.parametrize(
    ("update", "match"),
    [
        ({"IDEAS_LANE_MODELS": {}}, "IDEAS_LANE_MODELS"),
        ({"IDEAS_LANE_VIEWS": dict(ip.X1_VIEWS)}, "IDEAS_LANE_VIEWS"),
        ({"IDEAS_LANE_FRAMEWORKS": True}, "IDEAS_LANE_FRAMEWORKS"),
        ({"IDEAS_ROUND_SEEDS": False}, "IDEAS_ROUND_SEEDS"),
        ({"OP_COUNT_JUDGE": False}, "OP_COUNT_JUDGE"),
    ],
)
def test_a_process_off_its_arms_settings_is_refused(
    update: dict[str, object], match: str
) -> None:
    good = _arm_cfg(x2.X2_0)
    x2.check_settings(x2.X2_0, good)
    with pytest.raises(ValueError, match=match):
        x2.check_settings(x2.X2_0, good.model_copy(update=update))
    with pytest.raises(ValueError, match="Opus 5.5"):  # Ve's engine check too
        x2.check_settings(x2.X2_0, good.model_copy(update={"EDITOR_MODEL": SONNET}))


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


@pytest.mark.parametrize("arm", [x2.X2_0, x2.X2_V], ids=lambda a: a.key)
def test_the_arms_settings_reach_the_engine_the_loop_wires(
    arm: x2.X2Arm,
    upstream: og.Upstream,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``start_oss_loop`` reads the process-wide settings: with the arm's env
    exported it refuses the Haiku 5.5 lens (it passes no lane transport), so
    ``start_x2_loop`` is its body with ``lane_wiring``'s captured lane; the
    wired loop's generator is the pipeline on the arm's lanes and views,
    seeds and compounds on, one portfolio round, D55's share, the op-count
    judge; nothing is sent."""
    for key, value in x2.arm_env(arm).items():
        monkeypatch.setenv(key, value)
    built = Settings(_env_file=None)
    for key in arm.update:
        monkeypatch.setattr(settings, key, getattr(built, key))
    x2.check_settings(arm, settings)
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    for name in ("oss", "x2", "a", "b"):
        (root / name).mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", x2.arm_cap(arm), wire=httpx2.MockTransport(_no_wire))
    repo = og._local_repo(url, commit)
    with pytest.raises(ValueError, match="eliminate lane runs on claude-haiku-5-5"):
        oss.start_oss_loop(repo, run, root / "oss", REQUIRED, policy=og.LOCAL,
                           mode="wired")  # fmt: skip
    lanes = x2.lane_wiring(run)
    assert set(lanes) == {Lane.eliminate} and lanes[Lane.eliminate].chain == (ip.HAIKU,)
    loop = x2.start_x2_loop(repo, run, root / "x2", REQUIRED, policy=og.LOCAL)
    ctx = loop.context
    assert loop.mode == "wired" and loop.candidates == () == ctx.candidates
    assert loop.cap_usd == run.cap_usd and loop.user.base != commit  # the bench commit
    assert isinstance(ctx.generator, IdeaPipelineGenerator)
    cfg = ctx.generator._cfg
    assert cfg.IDEAS_LANE_MODELS == {Lane.eliminate: ip.HAIKU}
    assert cfg.IDEAS_LANE_VIEWS == (dict(ip.X1_VIEWS) if arm is x2.X2_V else {})
    assert cfg.IDEAS_ROUND_SEEDS and not cfg.IDEAS_LANE_FRAMEWORKS
    assert ctx.near_miss_compounds and ctx.portfolio_rounds == 2
    largest = cfg.GENERATOR_N + cfg.IDEAS_PORTFOLIO_MAX  # the pipeline's bound
    assert ctx.max_hypotheses_per_round == x2.round_trials(cfg) == largest
    assert ctx.discovery_max_share == settings.IDEAS_DISCOVERY_MAX_SHARE == 0.40
    isl.check_judges(loop)
    assert any(j.name == OP_COUNT_JUDGE for j in ctx.judges)
    assert run.capture.exchanges == [] and run.records == []
    # two rounds in all, by the engine's own router: a keep in round 1 explores
    # on (at PORTFOLIO_ROUNDS 1 it would combine), round 2 combines
    state = initial_state(loop.project, [loop.workload],
                          loop.repo.objectives(loop.project), [],
                          max_cost_usd=run.cap_usd)  # fmt: skip
    kept = _hyp("kept")
    trial = Trial(hypothesis_id=kept.id, round=1)
    state["round"], state["trials"] = 1, [trial]
    state["candidate_pool"] = [_hyp("next")]
    state["verdicts"] = [_verdict(kept, trial, VerdictOutcome.keep, 0.1)]
    assert state["max_rounds"] == 2 and make_router(ctx)(state) == "hypotheses"
    assert make_router(dataclasses.replace(ctx, portfolio_rounds=1))(state) == "combine"
    state["round"] = 2
    assert make_router(ctx)(state) == "combine"
    # the seeded call (D64) is round 2 only on an empty pool: the node calls
    # the generator only then, so round 1 trials the whole result
    assert _second_call(loop, ctx, x2.round_trials(cfg)) == (True, 0)
    small = dataclasses.replace(ctx, max_hypotheses_per_round=x2.FACTORY_ROUND)
    assert _second_call(loop, small, 5) == (False, 2)  # seeds dormant: a pool of 2


class _Ideas:
    """The pipeline's result, ``count`` ideas a call, every call kept."""

    def __init__(self, count: int) -> None:
        self.count, self.calls = count, 0

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.calls += 1
        return GenerateResult(hypotheses=tuple(
            _hyp(f"call {self.calls} idea {i}") for i in range(self.count)))  # fmt: skip


def _second_call(loop: Any, ctx: Any, count: int) -> tuple[bool, int]:
    """The engine's hypotheses node, rounds 1 and 2 (round 1's ranked all
    trialled): whether round 2 called the generator, and round 1's pool."""
    ideas = _Ideas(count)
    node = make_nodes(dataclasses.replace(ctx, generator=ideas))["hypotheses"]
    state = initial_state(loop.project, [loop.workload], [sg._objective()], [],
                          max_cost_usd=x2.arm_cap(x2.X2_0))  # fmt: skip
    state["baseline"] = Baseline(objectives=(sg._objective(),))
    first = node(state)
    events = [*state["events"], *cast(list[EngineEvent], first["events"])]
    state = cast(Any, {**state, **first, "events": events})
    state["trials"] = [Trial(hypothesis_id=h.id, round=1) for h in state["hypotheses"]]
    pool = len(state["candidate_pool"])
    node(state)
    return ideas.calls == 2, pool


def _factory_round() -> int:
    default = inspect.signature(build_context).parameters["max_hypotheses_per_round"]
    return cast(int, default.default)


def test_the_x2_loop_is_the_oss_loop_where_no_lane_has_its_own_model(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in {**x2.SHARED, "IDEAS_LANE_MODELS": {}}.items():
        monkeypatch.setattr(settings, key, value)
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    for name in ("oss", "x2", "a", "b"):
        (root / name).mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", 6.5, wire=httpx2.MockTransport(_no_wire))
    repo = og._local_repo(url, commit)
    assert x2.lane_wiring(run) == {}
    theirs = oss.start_oss_loop(repo, run, root / "a", REQUIRED, policy=og.LOCAL,
                                mode="wired")  # fmt: skip
    ours = x2.start_x2_loop(repo, run, root / "b", REQUIRED, policy=og.LOCAL)
    assert (ours.repo, ours.mode, ours.candidates, ours.cap_usd, ours.user.base) == (
        theirs.repo,
        theirs.mode,
        theirs.candidates,
        theirs.cap_usd,
        theirs.user.base,
    )
    a, b = theirs.context, ours.context
    fields = ("protected_patterns", "min_trial_budget_usd",
              "generator_n", "generator_max_calls", "discovery_max_share",
              "calibration_blocks", "confirm_winners", "portfolio_rounds",
              "near_miss_compounds", "retrieval")  # fmt: skip
    assert [getattr(b, f) for f in fields] == [getattr(a, f) for f in fields]
    assert a.max_hypotheses_per_round == x2.FACTORY_ROUND == _factory_round()
    assert b.max_hypotheses_per_round == x2.round_trials(settings) == 10
    assert [j.name for j in b.judges] == [j.name for j in a.judges]
    assert type(b.generator) is type(a.generator) is IdeaPipelineGenerator
    assert run.capture.exchanges == []


# ---------------------------------------------------------------------------
# The cap, the need, the fuse and the job: derived, then refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arm", "whole", "cap"),
    [(x2.X2_0, True, 9.35), (x2.X2_V, True, 9.45),
     (x2.X2_0, False, 6.50), (x2.X2_V, False, 6.70)],
)  # fmt: skip
def test_a_run_at_x1s_measured_rates_is_never_refused(
    arm: x2.X2Arm, whole: bool, cap: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeded second call (D64) after a round-1 call at X1's dearest and
    round 1's trials at the slice's dearest loop: each of its stages passes
    the engine's own reservation (``_discovery_cap``, then ``Budget.check``
    with what X1 measured before that stage) at the cap; the whole run at
    those rates (round 2's call and trials, its compound) keeps one trial's
    reserve; and the cap is tight on one or the other, 5 cents below it.
    ``whole`` off is the factory's 3 a round (seeds dormant, spec 9.5's plan)."""
    monkeypatch.setattr(x2, "WHOLE_POOL", whole)
    cfg = _arm_cfg(arm)
    assert x2.run_cap(cfg) == x2.arm_cap(arm) == cap
    trials = x2.run_trials(cfg)
    first = cfg.GENERATOR_N + cfg.IDEAS_PORTFOLIO_MAX if whole else x2.FACTORY_ROUND
    assert trials == (first, first + 1)  # round 2's near-miss compound
    s1, s2, review = x2.seeded_stages(cfg)
    before = (0.0, x2.X1_S1_USD, x2.X1_S1_S2_USD)
    reserve = settings_trial_budget(cfg)
    ctx = SimpleNamespace(discovery_max_share=cfg.IDEAS_DISCOVERY_MAX_SHARE,
                          min_trial_budget_usd=reserve)  # fmt: skip
    per_trial = x2.X1_LOOP_USD / x2.LOOP_TRIALS
    cost = dx.OSS_PHASE_ONE_WORST_USD + x2.X1_CALL_USD + per_trial * trials[0]

    def refused(cap_usd: float) -> list[float]:
        state = {"max_cost_usd": cap_usd, "cost_usd": cost,
                 "discovery_cost_usd": x2.X1_CALL_USD}  # fmt: skip
        d = _discovery_cap(cast(Any, ctx), cast(Any, state))
        out = []
        for spent, stage in zip(before, (s1, s2, review), strict=True):
            try:
                Budget(cap_usd=d, spent_usd=cost + spent).check(stage)
            except BudgetExceeded:
                out.append(stage)
        return out

    run = (dx.OSS_PHASE_ONE_WORST_USD + 2 * x2.X1_CALL_USD + per_trial * sum(trials)
           + max(s1, x2.X1_S1_USD + s2, x2.X1_S1_S2_USD + review))  # fmt: skip
    assert refused(cap) == [] and run + reserve <= cap
    assert refused(round(cap - 0.05, 2)) != [] or run + reserve > cap - 0.05
    assert (refused(round(cap - 0.05, 2)) != []) is not whole  # which one binds
    unseeded = ip.pipeline_usd(cfg)
    assert s1 + s2 + review > unseeded  # the seeds block priced on every lane
    assert ceil_usd(run + reserve) <= cap


def test_the_dispatch_plan_need_minutes_and_fuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = x2.x2_plan(X2_0_NEED)
    assert plan.dispatch == f"X2-0:{FIRST}"
    assert [(a.key, r.name) for a, r in plan.runs] == [
        ("X2-0", n) for n in ip.E1_REPOS[:4]
    ]
    assert x2.x2_need(plan) == 37.4 <= x2.X2_FUSE_USD
    assert x2.plan_minutes(plan) == 4 * 89 <= x2.JOB_MINUTES == 360
    # a clone, round 1's 10 trials in 4 loops, round 2's 11 in 4, two calls
    assert x2.run_minutes(_arm_cfg(x2.X2_0)) == (
        isl.CLONE_MINUTES + 8 * isl.LOOP_MINUTES + 2 * 8
    )
    twin = x2.x2_plan({x2.DISPATCH_ENV: "X2-0':tomli,sqlparse", SUITE_CAP_ENV: "19"})
    assert [(a.key, r.name) for a, r in twin.runs] == [
        ("X2-0'", "sqlparse"), ("X2-0'", "tomli")  # the arm's order
    ]  # fmt: skip
    views = x2.x2_plan({x2.DISPATCH_ENV: f"X2-V:{SECOND}", SUITE_CAP_ENV: "38"})
    assert x2.x2_need(views) == 37.8 and x2.plan_minutes(views) == 4 * 89
    monkeypatch.setattr(x2, "WHOLE_POOL", False)  # seeds dormant: 3 a round
    assert x2.run_minutes(_arm_cfg(x2.X2_0)) == isl.CLONE_MINUTES + 3 * 9 + 16 == 44
    assert x2.dispatches() == (f"X2-0:{','.join(ip.E1_REPOS)}",
                               f"X2-0':{','.join(isl.SLICE_REPOS)}",
                               f"X2-V:{','.join(ip.E1_REPOS)}")  # fmt: skip
    eight = x2.x2_plan({x2.DISPATCH_ENV: x2.dispatches()[2], SUITE_CAP_ENV: "54"})
    assert x2.x2_need(eight) == 53.6 and x2.plan_minutes(eight) == 8 * 44


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({}, "LIVE_X2_DISPATCH"),
        ({x2.DISPATCH_ENV: "X2-F:tomli"}, "LIVE_X2_DISPATCH"),  # an owner decision
        ({x2.DISPATCH_ENV: "X2-0"}, "LIVE_X2_DISPATCH"),  # no libraries
        ({x2.DISPATCH_ENV: "X2-0:"}, "LIVE_X2_DISPATCH"),
        ({x2.DISPATCH_ENV: "X2-0':mistune"}, "LIVE_X2_DISPATCH"),  # off the twin's
        ({x2.DISPATCH_ENV: "X2-0:tomli,tomli"}, "LIVE_X2_DISPATCH"),
        ({x2.DISPATCH_ENV: "X2-0:tomli,nope"}, "LIVE_X2_DISPATCH"),
        ({x2.DISPATCH_ENV: "x2-0:tomli"}, "LIVE_X2_DISPATCH"),
        ({**X2_0_NEED, SUITE_CAP_ENV: "37.39"}, "below"),
        ({x2.DISPATCH_ENV: f"X2-V:{SECOND}", SUITE_CAP_ENV: "37.79"}, "below"),
    ],
)
def test_a_bad_dispatch_is_refused(environ: dict[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        x2.x2_plan(environ)


def test_past_the_fuse_or_the_job_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = x2.x2_plan(X2_0_NEED)
    five = x2.X2Plan("X2-0", (*plan.runs, plan.runs[0]))  # 46.75 USD, 445 minutes
    with pytest.raises(ValueError, match="445 minutes"):
        x2.check_plan(five, 150.0)
    with pytest.raises(ValueError, match="5 runs need 46.75 USD"):
        x2.x2_plan({x2.DISPATCH_ENV: f"X2-0:{FIRST},mistune", SUITE_CAP_ENV: "150"})
    monkeypatch.setattr(x2, "JOB_MINUTES", 10_000)
    nine = x2.X2Plan("X2-0", (*plan.runs, *plan.runs, plan.runs[0]))  # 84.15 USD
    with pytest.raises(ValueError, match="84.15 USD"):
        x2.check_plan(nine, 150.0)
    x2.check_plan(x2.X2Plan("X2-0", (*plan.runs, *plan.runs)), 74.8)  # 8: 74.80


# ---------------------------------------------------------------------------
# One run: checked before spend, then the whole engine run and its records
# ---------------------------------------------------------------------------

REPO = "tomli"
TOMLI = x2.LIBRARIES[REPO]
COMMIT = "a" * 40


def _hyp(title: str, *tags: str, source: HypothesisSource = HypothesisSource.novel,
         hid: str | None = None) -> Hypothesis:  # fmt: skip
    extra = {} if hid is None else {"id": hid}
    return Hypothesis(project_id="p", source=source, title=title, rationale="r",
                      change_class=ChangeClass.efficiency, expected_gain=0.1,
                      provability=0.5, risk=0.1, tags=tags, **extra)  # fmt: skip


def _event(**data: object) -> EngineEvent:
    return EngineEvent(run_id="r", phase=RunPhase.hypotheses, message="m",
                       data=cast(Any, data))  # fmt: skip


def _verdict(h: Hypothesis, trial: Trial, outcome: VerdictOutcome, gain: float,
             *, op: bool = True) -> Verdict:  # fmt: skip
    return Verdict(trial_id=trial.id, hypothesis_id=h.id, change_class=h.change_class,
                   outcome=outcome, judge_results=sg._judges(gain, op=op), gain=gain,
                   summary="s")  # fmt: skip


def _state(*, op: bool = True) -> EngineRunResult:
    s1 = _hyp(f"S1 idea {SECRET}", "lane:obvious", "claimed_mechanism:cache")
    lens = _hyp("lens idea", "lane:eliminate", "claimed_mechanism:batch")
    leap = _hyp("leap idea", "lane:leap", "claimed_mechanism:batch")
    comp = _hyp("compound", COMPOUND_TAG, "compound_parent:t-b", "compound_parent:t-a",
                source=HypothesisSource.lesson, hid=compound_id("t-a", "t-b"))  # fmt: skip
    pool = _hyp("pool idea", "lane:far")
    trials = [Trial(hypothesis_id=h.id, round=n)
              for h, n in ((s1, 1), (lens, 1), (leap, 2), (comp, 2))]  # fmt: skip
    outcomes = (VerdictOutcome.keep, VerdictOutcome.inconclusive,
                VerdictOutcome.keep, VerdictOutcome.reject)  # fmt: skip
    verdicts = [_verdict(h, t, o, g, op=op) for h, t, o, g in
                zip((s1, lens, leap, comp), trials, outcomes, (0.12, 0.01, 0.09, -0.01),
                    strict=True)]  # fmt: skip
    key = {"code": KEY_EVENT, "hypothesis_id": lens.id, "path": "tomli/_parser.py",
           "function": "parse", "first": 10, "last": 20, "mechanism": "remove_work",
           "cell": "work:eliminate"}  # fmt: skip
    events = [
        _event(code="generated", kept=4), _event(**key),
        _event(round=1, ranked=2, candidates=4),
        _event(code=SEEDED_CALL, seeds=2, lanes="eliminate,far,leap"),
        _event(code="seeded_call_cost", cost_usd=0.31, seeded_calls=1),
        _event(code="compound", round=2, parents="t-a,t-b"),
        _event(code="discovery_unaffordable"),
        _event(round=2, ranked=1, candidates=1),
        _event(round=2, verdicts=2, keep=1),  # after the last ranking: no round's
    ]  # fmt: skip
    combination = Combination(
        base_commit="b" * 40, tip_commit="c" * 40,
        applied_trial_ids=(trials[0].id, trials[2].id), judge_results=sg._judges(0.18),
        holds=True, summary="greedy held",
    )  # fmt: skip
    state = {
        "objectives": [sg._objective()], "hypotheses": [s1, lens, comp, leap],
        "candidate_pool": [pool], "parked": [_hyp("parked", "lane:far")],
        "trials": trials, "verdicts": verdicts, "events": events,
        "combination": combination, "delivery": object(),
        "discovery_cost_usd": 1.4, "seeded_calls": 1, "seeded_cost_usd": 0.31,
    }  # fmt: skip
    return EngineRunResult("run", "done", cast(Any, state), None)


class _Engine:
    """The fake whole run: ``start_x2_loop`` and ``run_engine`` as ``run_one``
    calls them, its call order kept."""

    def __init__(self, *, head: str = COMMIT, judged: bool = True,
                 op: bool = True, breach: bool = False) -> None:  # fmt: skip
        self.head, self.judged, self.op, self.breach = head, judged, op, breach
        self.calls: list[str] = []

    def start(self, repo: Any, run: LiveRun, root: Path, isolation: Isolation, *,
              policy: object) -> Any:  # fmt: skip
        assert isolation is REQUIRED and policy is og.LOCAL and repo is TOMLI
        assert root.is_dir()
        self.calls.append(f"start {root.name} {run.cap_usd:g}")
        judges = (OpCountJudge(),) if self.judged else ()
        return SimpleNamespace(user=SimpleNamespace(base=self.head),
                               context=SimpleNamespace(judges=judges))  # fmt: skip

    def run(self, loop: Any, run: LiveRun, isolation: Isolation, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        assert model == OPUS
        self.calls.append("run")
        if self.breach:
            record(SimpleNamespace(guard=f"breach: AssertionError: {SECRET}"), None)
            raise AssertionError("the user's repository changed")
        record(SimpleNamespace(guard="ok"), _state(op=self.op))
        return None


@pytest.fixture
def x2_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., tuple[_Engine, list[Json]]]]:
    def go(engine: _Engine | None = None, base: Settings | None = None,
           arm: x2.X2Arm = x2.X2_0,
           environ: Mapping[str, str] | None = None) -> tuple[_Engine, list[Json]]:  # fmt: skip
        engine = engine or _Engine()
        monkeypatch.setattr(x2, "start_x2_loop", engine.start)
        monkeypatch.setattr(x2, "run_engine", engine.run)
        out = tmp_path / "x2.jsonl"
        plan = x2.x2_plan({**X2_0_NEED, x2.DISPATCH_ENV: f"{arm.key}:{REPO}"})
        sink = ResultsSink({**(environ or {}), RESULTS_ENV: str(out)})
        recorder = x2.X2Recorder(plan, sink,
                                 base=_arm_cfg(arm), commits={REPO: COMMIT})  # fmt: skip
        if base is not None:
            recorder.base = base

        def live(cap: float) -> LiveRun:
            engine.calls.append(f"live {cap:g}")
            return LiveRun("x", cap)

        try:
            x2.run_one(arm, TOMLI, live=cast(StartLive, live), root=tmp_path / "root",
                       isolation=REQUIRED, recorder=recorder, policy=og.LOCAL)  # fmt: skip
        finally:
            rows = [json.loads(x) for x in
                    (out.read_text(encoding="utf-8").splitlines() if out.exists() else [])]  # fmt: skip
        return engine, rows

    yield go


def _rows(rows: list[Json], experiment: str) -> list[Json]:
    return [r for r in rows if r["experiment"] == experiment]


def test_one_run_is_capped_wired_and_recorded(x2_run: Any) -> None:
    engine, rows = x2_run()
    assert engine.calls == ["live 9.35", "start 0-tomli 9.35", "run"]
    ideas = {r["title"]: r for r in _rows(rows, x2.IDEA_EXPERIMENT)}
    assert len(ideas) == 5 and SECRET not in json.dumps(rows)  # pool idea too
    lens = ideas["lens idea"]
    assert {k: lens[k] for k in ("repo", "arm", "round", "lane", "label", "model",
                                 "mechanism", "target", "compound", "verdict")} == {
        "repo": REPO, "arm": "X2-0", "round": 1, "lane": "eliminate",
        "label": "eliminate", "model": ip.HAIKU, "mechanism": "remove_work",
        "target": {"path": "tomli/_parser.py", "first": 10, "last": 20},
        "compound": False, "verdict": "inconclusive",
    }  # fmt: skip
    assert lens["gain_pct"] == pytest.approx(1.0) and lens["floor_pct"] == 2.0
    assert lens["op_count"]["present"] and lens["op_count"]["change"] == -0.2
    s1 = next(r for t, r in ideas.items() if t.startswith("S1 idea"))
    assert (s1["model"], s1["mechanism"], s1["target"], s1["verdict"]) == (
        SONNET,
        "cache",
        None,
        "keep",
    )
    assert (ideas["leap idea"]["model"], ideas["leap idea"]["round"]) == (OPUS, 2)
    comp = ideas["compound"]
    assert (comp["lane"], comp["model"], comp["compound"], comp["parents"]) == (
        None,
        None,
        True,
        ["t-a", "t-b"],
    )
    assert (ideas["pool idea"]["round"], ideas["pool idea"]["verdict"]) == (
        None,
        dx.NOT_TRIALLED,
    )
    rounds = _rows(rows, x2.ROUND_EXPERIMENT)
    assert [{k: r[k] for k in ("round", "trialled", "kept", "seeds", "seeded_lanes",
                               "seeded_calls", "seeded_cost_usd", "compounds",
                               "compounds_kept")} for r in rounds] == [
        {"round": 1, "trialled": 2, "kept": 1, "seeds": 0, "seeded_lanes": [],
         "seeded_calls": 0, "seeded_cost_usd": 0.0, "compounds": 0, "compounds_kept": 0},
        {"round": 2, "trialled": 2, "kept": 1, "seeds": 2,
         "seeded_lanes": ["eliminate,far,leap"], "seeded_calls": 1,
         "seeded_cost_usd": 0.31, "compounds": 1, "compounds_kept": 0},
    ]  # fmt: skip
    (run,) = _rows(rows, x2.RUN_EXPERIMENT)
    assert {k: run[k] for k in ("repo", "arm", "dispatch", "commit", "cap_usd",
                                "cost_usd", "discovery_cost_usd", "seeded_calls",
                                "seeded_cost_usd", "unaffordable", "hypotheses",
                                "parked", "kept", "combined", "holds", "applied",
                                "delivered", "guard")} == {
        "repo": REPO, "arm": "X2-0", "dispatch": "X2-0:tomli", "commit": COMMIT,
        "cap_usd": 9.35, "cost_usd": 0.0, "discovery_cost_usd": 1.4,
        "seeded_calls": 1, "seeded_cost_usd": 0.31, "unaffordable": 1,
        "hypotheses": 5, "parked": 1, "kept": 2, "combined": True, "holds": True,
        "applied": 2, "delivered": True, "guard": "ok",
    }  # fmt: skip
    assert run["gain_pct"] == pytest.approx(18.0) and run["floor_pct"] == 2.0


def test_x2_v_records_its_arm_and_the_twin_its_own(x2_run: Any) -> None:
    _, rows = x2_run(arm=x2.X2_V)
    assert {r["arm"] for r in rows} == {"X2-V"}
    _, rows = x2_run(arm=x2.X2_0_TWIN)
    (run,) = [r for r in _rows(rows, x2.RUN_EXPERIMENT) if r["arm"] == "X2-0'"]
    assert (run["cap_usd"], run["dispatch"]) == (9.35, "X2-0':tomli")


@pytest.mark.parametrize(
    ("update", "match"),
    [({"OP_COUNT_JUDGE": False}, "OP_COUNT_JUDGE"),
     ({"IDEAS_LANE_MODELS": {}}, "IDEAS_LANE_MODELS")],
)  # fmt: skip
def test_the_settings_and_the_op_count_judge_are_asserted_before_spend(
    update: dict[str, object], match: str, x2_run: Any
) -> None:
    bad = _arm_cfg(x2.X2_0).model_copy(update=update)
    with pytest.raises(ValueError, match=match):
        x2.X2Recorder(x2.x2_plan(X2_0_NEED), ResultsSink({}), base=bad, commits={})
    engine = _Engine()
    with pytest.raises(ValueError, match=match):
        x2_run(engine, base=bad)
    assert engine.calls == []  # nothing started, nothing spent


def test_a_loop_without_the_op_count_judge_never_runs(x2_run: Any) -> None:
    engine = _Engine(judged=False)
    with pytest.raises(AssertionError, match=OP_COUNT_JUDGE):
        x2_run(engine)
    assert engine.calls[-1].startswith("start")


def test_a_head_off_e1s_recorded_commit_never_runs(x2_run: Any) -> None:
    engine = _Engine(head="f" * 40)
    with pytest.raises(ValueError, match="not E1's recorded"):
        x2_run(engine)
    assert engine.calls[-1].startswith("start")


def test_a_verdict_without_the_op_count_column_fails_after_its_records(
    x2_run: Any, tmp_path: Path
) -> None:
    with pytest.raises(AssertionError, match="op-count column"):
        x2_run(_Engine(op=False))
    out = (tmp_path / "x2.jsonl").read_text(encoding="utf-8")
    assert x2.RUN_EXPERIMENT in out


def test_a_breach_is_recorded_then_raised(x2_run: Any, tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="repository changed"):
        x2_run(_Engine(breach=True))
    rows = [json.loads(x) for x in
            (tmp_path / "x2.jsonl").read_text(encoding="utf-8").splitlines()]  # fmt: skip
    (run,) = rows
    assert run["experiment"] == x2.RUN_EXPERIMENT and run["guard"].startswith("breach")
    assert (run["hypotheses"], run["combined"], run["seeded_calls"]) == (0, False, 0)
    assert SECRET not in json.dumps(rows)


def test_the_recorder_reads_e1s_commits_by_default() -> None:
    recorder = x2.X2Recorder(x2.x2_plan(X2_0_NEED), ResultsSink({}),
                             base=_arm_cfg(x2.X2_0))  # fmt: skip
    facts = ip.load_facts(ip.SERVICE_DIR / ip.FACTS_FIXTURE)
    assert recorder.commits == {name: body.commit for name, body in facts.items()}
    assert set(ip.E1_REPOS) <= set(recorder.commits or {})


def test_the_live_module_reads_its_plan_first_and_runs_each_planned_run() -> None:
    text = (TESTS_DIR / "live" / "test_ideas_x2_live.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live" in text
    assert '@pytest.fixture(scope="module")' in text
    assert "X2Recorder(x2_plan(os.environ), ResultsSink(os.environ))" in text
    assert "run_one(" in text and "pytest.skip(" in text
    assert len(x2.ALL_RUNS) == 20 and {(a.key, r.name) for a, r in x2.ALL_RUNS} == {
        (a.key, n) for a in x2.X2_ARMS for n in a.repos
    }


def _live_cases() -> tuple[x2.Run, ...]:
    """``test_ideas_x2``'s parametrised (arm, library) cases, as collected."""
    marks = cast(list[pytest.Mark], vars(live.test_ideas_x2)["pytestmark"])
    (mark,) = [m for m in marks if m.name == "parametrize"]
    assert mark.kwargs["ids"] == [f"{a.key}-{r.name}" for a, r in mark.args[1]]
    return tuple(mark.args[1])


def _arm_plan(arm: x2.X2Arm, names: str) -> x2.X2Plan:
    environ = {**x2.arm_env(arm), x2.DISPATCH_ENV: f"{arm.key}:{names}"}
    return x2.x2_plan({**environ, SUITE_CAP_ENV: "38"})


def test_every_arms_dispatch_selects_live_cases_only() -> None:
    """E1 (run 42232651527): ``X2-S:sqlparse,tomli,mistune`` selected runs no
    case held, so the job skipped all 20 and passed at 0 USD. Every arm's
    every library, and E1's and E2's dispatches, select only live cases."""
    cases = _live_cases()
    for arm in x2.EVERY_ARM:
        for name in arm.repos:
            runs = _arm_plan(arm, name).runs
            assert len(runs) == 1 and runs[0] in cases, f"{arm.key}:{name}"
    for names, n in (("sqlparse,tomli,mistune", 3), ("sqlparse,more_itertools", 2)):
        runs = _arm_plan(x2.X2_S, names).runs
        assert len(runs) == n and all(r in cases for r in runs), names


def test_the_live_cases_are_every_arms_runs_the_plans_first() -> None:
    assert _live_cases() == x2.EVERY_RUN
    assert x2.EVERY_RUN[: len(x2.ALL_RUNS)] == x2.ALL_RUNS  # the 20 ids unchanged
    assert [(a.key, r.name) for a, r in x2.EVERY_RUN] == [
        (a.key, n) for a in x2.EVERY_ARM for n in a.repos
    ]
    assert len({(a.key, r.name) for a, r in x2.EVERY_RUN}) == len(x2.EVERY_RUN) == 39
