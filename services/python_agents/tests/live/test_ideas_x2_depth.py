"""Offline guards of X2-D, depth (Window 2): X2-0 with a third round, its
cap and minutes, the planner on it, and the report's ``--rounds`` page.

Not ``live``: these spend nothing. X2-D is X2-0's settings with
``PORTFOLIO_ROUNDS=3``, ``MAX_TRIAL_ROUNDS=3`` and ``GENERATOR_MAX_CALLS=3``
and nothing else (without the third call the router reaches round 3 only
for a waiting near-miss compound: every archived run left an empty pool
after round 2), off the
plan and not an A/A draw (``aa="none"``: a third round changes what is
trialled and delivered). Its cap and minutes are ``run_cap`` and
``run_minutes``' own derivation with a third round, cross-checked against
the X2 archives' measured per-round spend (``ideas_x2``'s comment). Fakes:
``test_ideas_x2_guards``'s ``_Engine`` and hand-built state stand for the
whole engine run; ``test_ideas_x2_report_guards._rows`` hand-makes a run's
rows as ``X2Recorder`` writes them. What only a live run proves: what the
third (seeded) call returns, what round 3 keeps, and its real spend and
minutes.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import (
    GENERATOR_MAX_CALLS_MAX,
    Settings,
    settings,
)
from autonomous_ai_agents.common.errors import BudgetExceeded
from autonomous_ai_agents.common.models import Baseline, Trial, VerdictOutcome
from autonomous_ai_agents.orchestrator.nodes import (
    _discovery_cap,
    _live_generator,
    make_router,
)
from autonomous_ai_agents.orchestrator.state import initial_state

from . import discovery_oss as dx
from . import ideas_probe as ip
from . import ideas_slice as isl
from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import test_ideas_slice_guards as sg
from . import test_ideas_x2_guards as xg
from . import test_ideas_x2_report_guards as rg
from . import test_oss_guards as og
from .conftest import SUITE_CAP_ENV, LiveRun, restore_host_key
from .corpus import settings_trial_budget

x2_run = xg.x2_run
upstream = og.upstream
DEPTH = ("sqlparse", "tomli", "mistune", "markdown")
# the X2 archives holding X2-0 and X2-0' runs (d3, d6 and d8 are X2-V's)
BASE_ARCHIVES = tuple(rg.X2_DIR / f"ideas-x2-{n}.jsonl" for n in (
    "d1-42149964562", "d2-42156498229", "d4-42165247794", "d5-42171711130",
    "d7-42181939377"))  # fmt: skip
ARCHIVES = (*sorted(rg.X2_DIR.glob("ideas-x2-d*.jsonl")),
            *sorted((rg.X2_DIR.parent / "emergence/round-1/live").glob("ideas-x2s-e*.jsonl")))  # fmt: skip


# ---------------------------------------------------------------------------
# The arm
# ---------------------------------------------------------------------------


def test_x2_d_is_x2_0_with_three_rounds_off_the_plan() -> None:
    """Three keys: the rounds (``PORTFOLIO_ROUNDS``, ``MAX_TRIAL_ROUNDS``)
    and a third generator call, since without it the router reaches round 3
    only for a waiting compound (the pool is empty after round 2)."""
    assert x2.X2_D.key == "X2-D" and x2.X2_D.repos == DEPTH
    assert dict(x2.X2_D.update) == {**x2.SHARED, "PORTFOLIO_ROUNDS": 3,
                                    "MAX_TRIAL_ROUNDS": 3,
                                    "GENERATOR_MAX_CALLS": 3}  # fmt: skip
    assert settings.GENERATOR_MAX_CALLS == 2 and "GENERATOR_MAX_CALLS" not in x2.SHARED
    assert 3 <= GENERATOR_MAX_CALLS_MAX  # within the Settings bound (5)
    assert x2.X2_D.aa == "none" and x2.X2_D not in x2.X2_ARMS
    assert x2.X2_D in x2.EVERY_ARM and "X2-D" in xr.ARMS and "X2-D" not in xr.POOL
    assert not any(d.startswith("X2-D") for d in x2.dispatches())
    env = x2.arm_env(x2.X2_D)
    assert (env["PORTFOLIO_ROUNDS"], env["MAX_TRIAL_ROUNDS"],
            env["GENERATOR_MAX_CALLS"]) == ("3", "3", "3")  # fmt: skip
    depth, base = (x2.arm_settings(a).model_dump() for a in (x2.X2_D, x2.X2_0))
    assert {k for k in depth if depth[k] != base[k]} == {"PORTFOLIO_ROUNDS",
                                                         "MAX_TRIAL_ROUNDS",
                                                         "GENERATOR_MAX_CALLS"}  # fmt: skip


# ---------------------------------------------------------------------------
# The cap and the minutes: X2-0's derivation with a third round
# ---------------------------------------------------------------------------


def test_x2_d_adds_one_round_to_x2_0s_cap_and_minutes() -> None:
    """Written out by hand, not through ``run_cap``: one trial's reserve
    0.40, the understand request at its worst 0.37825, a pipeline call a
    round at X1's dearest 0.9138, every trial at the slice's dearest loop
    0.7213 / 3 (10 + 11 + 11 = 32), and the dearest seeded stage 1.67875
    (X1's S1 0.1066 before an S2 at 1.57215): 12.8923 USD, 12.90 rounded
    up to 0.05; two rounds (21 trials, two calls) are 9.3337, 9.35. Minutes:
    a clone 1, 12 loops of 3 at 9, three calls at 8: 133 (89 for two)."""
    depth, base = x2.arm_settings(x2.X2_D), x2.arm_settings(x2.X2_0)
    assert x2.run_trials(depth) == (10, 11, 11) and x2.run_trials(base) == (10, 11)
    assert (settings_trial_budget(depth), dx.OSS_PHASE_ONE_WORST_USD) == (0.40, 0.37825)
    assert (x2.X1_CALL_USD, x2.X1_LOOP_USD, x2.X1_S1_USD) == (0.9138, 0.7213, 0.1066)
    assert x2.seeded_stages(depth) == pytest.approx((0.215, 1.57215, 0.54))
    three = 0.40 + 0.37825 + 3 * 0.9138 + 32 * 0.7213 / 3 + 0.1066 + 1.57215
    two = 0.40 + 0.37825 + 2 * 0.9138 + 21 * 0.7213 / 3 + 0.1066 + 1.57215
    assert three == pytest.approx(12.892267, abs=1e-6) and two == pytest.approx(
        9.3337, abs=1e-4
    )
    assert (x2.arm_cap(x2.X2_D), x2.arm_cap(x2.X2_0)) == (12.90, 9.35)
    assert math.ceil(ip.arm_seconds(ip.ARM_X1_0, depth) / 60) == 8
    assert (isl.CLONE_MINUTES, isl.LOOP_MINUTES) == (1, 9)
    assert (x2.run_minutes(depth), x2.run_minutes(base)) == (1 + 12 * 9 + 3 * 8, 1 + 8 * 9 + 2 * 8) == (133, 89)  # fmt: skip


def test_a_third_seeded_call_after_two_is_never_refused_and_the_cap_is_tight() -> None:
    """The third (seeded) call: after two calls and two rounds of trials at
    X1's dearest, the router still schedules it at X2-D's three calls and
    not at the default two (``_live_generator``, priced), and its stages
    pass the engine's reservations at the cap (the share holds both earlier
    calls, ``_discovery_cap``); the whole run, charged three calls and three
    rounds, keeps one trial's reserve, and 5 cents below the cap it does not."""
    cfg = x2.arm_settings(x2.X2_D)
    cap, trials = x2.arm_cap(x2.X2_D), x2.run_trials(cfg)
    s1, s2, review = x2.seeded_stages(cfg)
    reserve, per_trial = settings_trial_budget(cfg), x2.X1_LOOP_USD / x2.LOOP_TRIALS
    ctx = SimpleNamespace(discovery_max_share=cfg.IDEAS_DISCOVERY_MAX_SHARE,
                          min_trial_budget_usd=reserve)  # fmt: skip
    calls = 2 * x2.X1_CALL_USD
    cost = dx.OSS_PHASE_ONE_WORST_USD + calls + per_trial * sum(trials[:2])
    state = {"max_cost_usd": cap, "cost_usd": cost, "discovery_cost_usd": calls}
    d = _discovery_cap(cast(Any, ctx), cast(Any, state))
    live = {**state, "generator_calls": 2, "budget_exhausted": False,
            "discovery_exhausted": False}  # fmt: skip
    for calls_max, scheduled in ((cfg.GENERATOR_MAX_CALLS, True), (2, False)):
        gen = object()  # stands for the idea pipeline
        router = SimpleNamespace(
            **vars(ctx), generator=gen, generator_max_calls=calls_max
        )
        got: object = _live_generator(cast(Any, router), cast(Any, live), priced=True)
        assert (got is gen) is scheduled, calls_max
    for spent, stage in zip((0.0, x2.X1_S1_USD, x2.X1_S1_S2_USD), (s1, s2, review),
                            strict=True):  # fmt: skip
        Budget(cap_usd=d, spent_usd=cost + spent).check(stage)
    left = ctx.discovery_max_share * cap - s1 / 2  # half S1's reservation left
    short = {**state, "discovery_cost_usd": left}
    with pytest.raises(BudgetExceeded):  # the check is live: a short share refuses
        Budget(cap_usd=_discovery_cap(cast(Any, ctx), cast(Any, short)),
               spent_usd=cost).check(s1)  # fmt: skip
    share = (calls + max(s1, x2.X1_S1_USD + s2, x2.X1_S1_S2_USD + review)) / ctx.discovery_max_share  # fmt: skip
    assert share <= cap  # the share term (8.77) never binds X2-D
    run = (dx.OSS_PHASE_ONE_WORST_USD + 3 * x2.X1_CALL_USD + per_trial * sum(trials)
           + max(s1, x2.X1_S1_USD + s2, x2.X1_S1_S2_USD + review))  # fmt: skip
    assert run + reserve <= cap and run + reserve > cap - 0.05


def test_the_engines_router_makes_the_third_call_and_ends_after_round_3(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wired loop built with X2-D's env exported (as ci.yml does) and the
    engine's own router (``make_router``): after round 2 with a keep, an
    empty pool and two calls, it routes to a third call at
    ``GENERATOR_MAX_CALLS`` 3 and to combine at 2; after round 3 it
    combines, keep or none."""
    for key, value in x2.arm_env(x2.X2_D).items():
        monkeypatch.setenv(key, value)
    built = Settings(_env_file=None)
    for key in x2.X2_D.update:
        monkeypatch.setattr(settings, key, getattr(built, key))
    x2.check_settings(x2.X2_D, settings)
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    (root / "x2").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", x2.arm_cap(x2.X2_D), wire=httpx2.MockTransport(xg._no_wire))
    loop = x2.start_x2_loop(og._local_repo(url, commit), run, root / "x2", xg.REQUIRED,
                            policy=og.LOCAL)  # fmt: skip
    ctx = loop.context
    assert (ctx.portfolio_rounds, ctx.generator_max_calls) == (3, 3)
    state = initial_state(loop.project, [loop.workload], [sg._objective()], [],
                          max_cost_usd=run.cap_usd)  # fmt: skip
    state["baseline"] = Baseline(objectives=(sg._objective(),))
    kept = xg._hyp("kept")
    trial = Trial(hypothesis_id=kept.id, round=2)
    state["round"], state["generator_calls"] = 2, 2
    state["hypotheses"], state["trials"] = [kept], [trial]
    state["verdicts"] = [xg._verdict(kept, trial, VerdictOutcome.keep, 0.1)]
    assert state["max_rounds"] == 3 and state["candidate_pool"] == []
    assert make_router(ctx)(state) == "hypotheses"  # the third call
    two = dataclasses.replace(ctx, generator_max_calls=2)
    assert make_router(two)(state) == "combine"  # no call, no waiting compound
    state["round"], state["generator_calls"] = 3, 3
    assert make_router(ctx)(state) == "combine"
    state["verdicts"] = [xg._verdict(kept, trial, VerdictOutcome.reject, -0.1)]
    assert make_router(ctx)(state) == "combine"  # MAX_TRIAL_ROUNDS ends it


def _base_runs() -> list[dict[str, Any]]:
    """Each X2-0 and X2-0' run of the archives: its first call (discovery
    less the seeded), its seeded call, each round's trialled count and the
    spend a trial outside discovery."""
    runs: dict[tuple[str, str], dict[str, Any]] = {}
    for path in BASE_ARCHIVES:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            one = runs.setdefault((row["arm"], row["repo"]), {"trialled": {}})
            if row["experiment"] == x2.ROUND_EXPERIMENT:
                one["trialled"][row["round"]] = row["trialled"]
            elif row["experiment"] == x2.RUN_EXPERIMENT:
                one["run"] = row
    out = []
    for (arm, repo), one in sorted(runs.items()):
        run, tried = one["run"], one["trialled"]
        first = run["discovery_cost_usd"] - run["seeded_cost_usd"]
        each = (run["cost_usd"] - run["discovery_cost_usd"]) / sum(tried.values())
        out.append({"arm": arm, "repo": repo, "cost": run["cost_usd"],
                    "calls": (first, run["seeded_cost_usd"]), "each": each,
                    "rounds": (first + tried[1] * each, run["seeded_cost_usd"] + tried[2] * each)})  # fmt: skip
    return out


def test_the_archives_measured_rounds_sit_inside_each_rounds_allowance() -> None:
    """``ideas_x2``'s comment, recomputed: the 12 X2-0 and X2-0' runs, their
    dearest first call 0.84 and seeded call 0.71 under X1's 0.91 a call,
    their dearest trial 0.100 under the 0.240 the formula takes, so the
    dearest measured round (1.66, sqlparse round 1) is under the 3.56 a
    round the third round adds, and the dearest run (2.99) under X2-0's
    cap. Arm-level spend only: what round 3 really costs is a live fact."""
    runs = _base_runs()
    assert len(runs) == 12 and {r["arm"] for r in runs} == {"X2-0", "X2-0'"}
    first = max(r["calls"][0] for r in runs)
    seeded = max(r["calls"][1] for r in runs)
    each = max(r["each"] for r in runs)
    rounds = [max(r["rounds"][n] for r in runs) for n in (0, 1)]
    assert (round(first, 2), round(seeded, 2), round(each, 3)) == (0.84, 0.71, 0.100)
    assert [round(v, 2) for v in rounds] == [1.66, 1.41]
    allowance = x2.X1_CALL_USD + x2.X1_LOOP_USD / x2.LOOP_TRIALS * 11
    assert (
        max(first, seeded) < x2.X1_CALL_USD and each < x2.X1_LOOP_USD / x2.LOOP_TRIALS
    )
    assert max(rounds) < round(allowance, 2) == 3.56
    assert round(max(r["cost"] for r in runs), 2) == 2.99 < x2.arm_cap(x2.X2_0)


# ---------------------------------------------------------------------------
# The planner
# ---------------------------------------------------------------------------


def test_the_planner_takes_two_x2_d_runs_a_dispatch_and_refuses_three() -> None:
    """133 minutes a run: 2 fit the 360-minute job (266), 3 do not (399);
    the need is 12.90 a run; a library twice is refused."""
    plan = x2.x2_plan({x2.DISPATCH_ENV: "X2-D:markdown,sqlparse", SUITE_CAP_ENV: "26"})
    assert [(a.key, r.name) for a, r in plan.runs] == [("X2-D", "sqlparse"),
                                                        ("X2-D", "markdown")]  # fmt: skip
    assert x2.x2_need(plan) == 25.80 and x2.plan_minutes(plan) == 266
    with pytest.raises(ValueError, match="3 runs need 38.70 USD and 399 minutes"):
        x2.x2_plan(
            {x2.DISPATCH_ENV: "X2-D:sqlparse,tomli,mistune", SUITE_CAP_ENV: "80"}
        )
    for bad in ("X2-D:tomli,tomli", "X2-D:sqlparse,sqlparse,tomli", "X2-D:idna"):
        with pytest.raises(ValueError, match="LIVE_X2_DISPATCH"):
            x2.x2_plan({x2.DISPATCH_ENV: bad, SUITE_CAP_ENV: "80"})
    with pytest.raises(ValueError, match="below dispatch X2-D:sqlparse's need 12.90"):
        x2.x2_plan({x2.DISPATCH_ENV: "X2-D:sqlparse", SUITE_CAP_ENV: "12.89"})


def test_an_x2_d_run_is_capped_and_planned_at_its_own_figures(x2_run: Any) -> None:
    engine, rows = x2_run(arm=x2.X2_D)

    at = x2.EVERY_ARM.index(x2.X2_D)
    assert engine.calls == ["live 12.9", f"start {at}-tomli 12.9", "run"]
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert (run["arm"], run["cap_usd"], run["minutes_planned"]) == ("X2-D", 12.9, 133)


# ---------------------------------------------------------------------------
# The report: gain per round
# ---------------------------------------------------------------------------


def _gains(rows: list[rg.Row], gains: dict[str, float | None]) -> list[rg.Row]:
    """Each named hypothesis's standalone gain set (``rg._rows`` writes 3.0)."""
    for r in rows:
        if r.get("hypothesis_id") in gains:
            r["gain_pct"] = gains[str(r["hypothesis_id"])]
    return rows


def _record(delivered: bool) -> dict[str, object]:
    """S2's per-keep combine record, the fields the report reads."""
    return {"delivered": delivered, "skip_reason": None if delivered else "conflict",
            "duplicate_of": None, "component": 0, "best_subset": delivered,
            "gain_pct": 1.0, "reconcile": None}  # fmt: skip


def test_the_rounds_page_on_fixtures(tmp_path: Path) -> None:
    """
    GIVEN two X2-D runs of three rounds on sqlparse (one in each file, the
          first with per-keep combine records, its round 3 a compound alone)
          and one on tomli whose keep carries no gain, beside an X2-0 run
    WHEN the rounds page renders
    THEN each run prints each round's keeps as fresh ideas + compounds, the
         standalone points of each (vs base, not additive), the delivered
         keeps where combine records exist (else -), a round it did not
         reach -, and the delivered combine beside; each arm the same per
         run that reached the round; no share is printed
    """
    one = _gains(rg._rows("X2-D", "sqlparse", [(9, ["obvious", "leap"]), (7, ["far"]),
                                               (1, ["compound"])], gain=30.0),
                 {"sqlparse-1-0": 10.0, "sqlparse-1-1": 5.0, "sqlparse-2-0": 4.0,
                  "sqlparse-3-0": 1.0})  # fmt: skip
    for r in one:
        if r.get("verdict") == "keep":
            r["combine"] = _record(r["hypothesis_id"] != "sqlparse-2-0")
    two = _gains(rg._rows("X2-D", "sqlparse", [(8, ["obvious"]), (6, []), (1, ["compound"])],
                          gain=12.0, holds=False),
                 {"sqlparse-1-0": 6.0, "sqlparse-3-0": 2.0})  # fmt: skip
    flat = _gains(rg._rows("X2-D", "tomli", [(5, []), (4, ["obvious"]), (0, [])]),
                  {"tomli-2-0": None})  # fmt: skip
    base = rg._rows("X2-0", "sqlparse", [(9, ["obvious"] * 4), (7, ["far"] * 5)], gain=39.8)  # fmt: skip
    files = [rg._write(tmp_path / "a.jsonl", one, flat, base),
             rg._write(tmp_path / "b.jsonl", two)]  # fmt: skip

    text = xr.render_rounds(xr.draws(files))

    head = text.split("## 1 ")[0]
    for said in ("Not a contribution", "neither additive nor a round's share",
                 "read only from X2-D's delivered combine against the pool on the "
                 "variance page", "O59 section 5's primary measure",
                 "Fresh ideas + near-miss compounds", "per-keep combine records",
                 "each file alone", "a round it did not reach reads -"):  # fmt: skip
        assert said in head, said
    assert "share" not in text.split("## 1 ")[1]
    assert "| round 1 standalone points, ideas (vs base, not additive) |" in text
    assert "| a.jsonl | X2-D | sqlparse | 3 | 2 + 0 | +15.0 | +0.0 | 2 of 2 | 1 + 0 | +4.0 | +0.0 | 0 of 1 | 0 + 1 | +0.0 | +1.0 | 1 of 1 | +20.0 | +30.0 |" in text  # fmt: skip
    assert "| b.jsonl | X2-D | sqlparse | 3 | 1 + 0 | +6.0 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | 0 + 1 | +0.0 | +2.0 | - | +8.0 | +0.0 |" in text  # fmt: skip
    assert "| a.jsonl | X2-D | tomli | 3 | 0 + 0 | +0.0 | +0.0 | - | 1 + 0 | +0.0 | +0.0 | - | 0 + 0 | +0.0 | +0.0 | - | +0.0 | +5.0 |" in text  # fmt: skip
    assert "| a.jsonl | X2-0 | sqlparse | 2 | 4 + 0 | +12.0 | +0.0 | - | 5 + 0 | +15.0 | +0.0 | - | - | - | - | - | +27.0 | +39.8 |" in text  # fmt: skip
    arms = text.split("## 2 ")[1]
    assert "| X2-0 | 1 | 1 | 4.0 + 0.0 | +12.0 | +0.0 | - | 1 | 5.0 + 0.0 | +15.0 | +0.0 | - | 0 | - | - | - | - | +27.0 | +39.8 |" in arms  # fmt: skip
    assert "| X2-D | 3 | 3 | 1.0 + 0.0 | +7.0 | +0.0 | 2 of 2 | 3 | 0.7 + 0.0 | +1.3 | +0.0 | 0 of 1 | 3 | 0.0 + 0.7 | +0.0 | +1.0 | 1 of 1 | +9.3 | +11.7 |" in arms  # fmt: skip
    assert text.index("| X2-0 | 1 |") < text.index("| X2-D | 3 |")  # X2's order


def test_a_round_whose_compound_count_disagrees_with_its_ideas_is_refused(
    tmp_path: Path,
) -> None:
    rows = rg._rows("X2-D", "tomli", [(2, ["obvious"]), (1, ["compound"])])
    for r in rows:
        if r["experiment"] == x2.ROUND_EXPERIMENT and r["round"] == 2:
            r["compounds_kept"] = 0
    found = xr.draws([rg._write(tmp_path / "a.jsonl", rows)])
    with pytest.raises(ValueError, match="X2-D tomli: round 2 records 0 compounds kept, its ideas 1"):  # fmt: skip
        xr.render_rounds(found)


def test_the_rounds_page_on_an_archive() -> None:
    """d4's X2-0 sqlparse: round 1 kept 4 fresh ideas, round 2 4 and X2's
    first near-miss compound, against a delivered +39.8; no third round."""
    text = xr.render_rounds(xr.draws([BASE_ARCHIVES[2]]))
    row = next(r for r in text.splitlines() if r.startswith("| ideas-x2-d4-42165247794.jsonl | X2-0 | sqlparse |"))  # fmt: skip
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3:5] == ["2", "4 + 0"] and cells[8] == "4 + 1" and cells[-1] == "+39.8"
    assert cells[7] == cells[11] == "-"  # no combine record in d4
    assert cells[12:16] == ["-", "-", "-", "-"]  # no third round
    every = xr.render_rounds(xr.draws(ARCHIVES))  # every archive's counts agree
    assert "| X2-S | 5 | 5 |" in every.split("## 2 ")[1]


def test_the_plan_refusal_names_every_dispatchable_arm() -> None:
    with pytest.raises(ValueError) as got:
        x2.x2_plan({x2.DISPATCH_ENV: "X2-Q:tomli", SUITE_CAP_ENV: "80"})
    assert f"an arm ({', '.join(a.key for a in x2.EVERY_ARM)})" in str(got.value)
    assert "X2-D" in str(got.value) and "X2-SV" in str(got.value)


def test_the_cli_writes_the_rounds_page_only_on_request(tmp_path: Path) -> None:
    path = rg._write(
        tmp_path / "a.jsonl", rg._rows("X2-D", "tomli", [(2, ["obvious"])])
    )
    said: list[str] = []
    out = tmp_path / "o"
    assert xr.main([str(path), "--rounds", "--out", str(out)], said.append) == 0
    assert said == [f"wrote rounds.md to {out}"]
    assert sorted(p.name for p in out.iterdir()) == ["rounds.md"]
    text = (out / "rounds.md").read_text(encoding="utf-8")
    assert (
        text.startswith("# X2 keeps by round")
        and "| a.jsonl | X2-D | tomli | 1 | 1 + 0 |" in text
    )
    assert xr.main([str(tmp_path / "none.jsonl"), "--rounds"], said.append) == 2
    with pytest.raises(SystemExit):  # one page a call
        xr.main([str(path), "--rounds", "--variance"], said.append)
