"""Offline guards of S1's variance accounting (emergence round 2): the A/A
pool flags, the rider-minutes ledger, the view record on the X2 rows and
the report's ``--variance`` page.

Not ``live``: these spend nothing. Fakes and what they stand for:
``test_ideas_x2_guards``'s ``_Engine`` and hand-built state stand for the
whole engine run; ``test_ideas_x2_report_guards._rows`` hand-makes one run's
rows as ``X2Recorder`` writes them. The ten committed archives (X2 d1-d8,
emergence round 1's E1 and E2) are the real thing and pin the replay: the
pool with the read arm left out reads the same 4 of 5 X2-S library-runs
outside that O51's one-pair band does (board [49], [76]), and the
delivered-sum refit of [78]. What only a live run proves: that every lane
request of a dispatched run carries its view hash, and the minutes a
dispatch really takes against the ledger's plan.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import test_ideas_x2_guards as xg
from . import test_ideas_x2_report_guards as rg
from .conftest import SUITE_CAP_ENV
from .corpus import RESULTS_ENV
from .discovery import SONNET
from .discovery_io import ResultsSink

x2_run = xg.x2_run
HANDOFF = rg.X2_DIR.parent
ARCHIVES = (*sorted(rg.X2_DIR.glob("ideas-x2-d*.jsonl")),
            *sorted((HANDOFF / "emergence/round-1/live").glob("ideas-x2s-e*.jsonl")))  # fmt: skip
VIEW = ("IDEAS_VIEW_RECORD", "true")


# ---------------------------------------------------------------------------
# The pool flags and the view record setting
# ---------------------------------------------------------------------------


def test_only_arms_with_x2_0s_requests_and_delivery_are_pool_draws() -> None:
    """Frozen before any run (judge [86]): X2-S's ``SITE_STACKS=on`` changes
    delivery and O52 called its kept count, so it never joins the pool."""
    assert {a.key: a.aa for a in x2.EVERY_ARM} == {
        "X2-0": "full", "X2-0'": "full", "X2-V": "none", "X2-S": "none", "X2-C": "full",
        "X2-SV": "full",
    }  # fmt: skip
    assert xr.POOL == frozenset({"X2-0", "X2-0'", "X2-C", "X2-SV"})


def test_every_arm_records_its_views_and_the_engine_default_is_off() -> None:
    assert settings.IDEAS_VIEW_RECORD is False
    assert all(a.update["IDEAS_VIEW_RECORD"] is True for a in x2.EVERY_ARM)
    assert x2.arm_env(x2.X2_0)["IDEAS_VIEW_RECORD"] == "true"


# ---------------------------------------------------------------------------
# The rider-minutes ledger
# ---------------------------------------------------------------------------


def _need(runs: int) -> dict[str, str]:
    names = ",".join(x2.X2_0.repos[:runs])
    return {x2.DISPATCH_ENV: f"X2-0:{names}", SUITE_CAP_ENV: "80"}


def test_the_default_ledger_adds_no_minute() -> None:
    cfg = x2.arm_settings(x2.X2_0)
    assert x2.RIDER_SECONDS == {
        VIEW: x2.Rider(),
        ("SHADOW_VERIFY", "record"): x2.SHADOW_RIDER,
    }
    assert x2.RIDER_MEASURED == {}
    assert x2.rider_seconds(cfg) == 0.0 and x2.run_minutes(cfg) == 89


def test_riders_declared_at_15_minutes_pass_3_runs_and_refuse_4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN the board's declared riders, about 15 minutes a library-run
          (VER-2 6, VER-1 3.5, INT-3 3, MEM-1 0.8, SCL-1 0.7, EXP-3 0.5,
          SCL-X 0.4: 894 s), on a setting every arm has on
    WHEN a dispatch is planned
    THEN a run plans 104 minutes, 3 runs (312) pass, 4 (416) are refused
         before any spend, and the plan carries 3 a dispatch
    """
    monkeypatch.setattr(x2, "RIDER_SECONDS", {VIEW: x2.Rider(run_s=894.0)})
    assert x2.run_minutes(x2.arm_settings(x2.X2_0)) == 104
    plan = x2.x2_plan(_need(3))
    assert x2.plan_minutes(plan) == 312 <= x2.JOB_MINUTES
    with pytest.raises(ValueError, match="416 minutes, past"):
        x2.x2_plan(_need(4))
    assert x2.dispatches()[0] == "X2-0:more_itertools,pyparsing,tomli"


def test_a_measured_rider_larger_than_declared_sizes_the_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Judge [87] (a): max(declared, last measured), per component."""
    cfg = x2.arm_settings(x2.X2_0)
    trials = sum(x2.run_trials(cfg))
    monkeypatch.setattr(x2, "RIDER_SECONDS", {VIEW: x2.Rider(run_s=894.0, keep_s=1.0)})
    monkeypatch.setattr(
        x2, "RIDER_MEASURED", {VIEW: x2.Rider(run_s=600.0, trial_s=2.0)}
    )
    assert x2.rider_seconds(cfg) == 894.0 + trials * (2.0 + 1.0)
    monkeypatch.setattr(x2, "RIDER_MEASURED", {VIEW: x2.Rider(run_s=1794.0)})
    assert x2.run_minutes(cfg) == 89 + math.ceil((1794.0 + trials) / 60)


def test_a_rider_on_a_setting_the_arm_leaves_off_adds_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(x2, "RIDER_SECONDS", {("SITE_STACKS", "record"): x2.Rider(run_s=6000.0)})  # fmt: skip
    assert x2.run_minutes(x2.arm_settings(x2.X2_S)) == 89  # X2-S is "on", not "record"


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


class _Viewed(xg._Engine):
    """The fake run with two lane-view events in round 1 and one in round 2."""

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str, record: Any) -> Any:  # fmt: skip
        state: dict[str, Any] = dict(xg._state().state)
        seen = [xg._event(code="lane_view", lane=lane, view_sha=sha, served_model=model)
                for lane, sha, model in (("obvious", "ab12cd34", SONNET),
                                         ("eliminate", "ff00ee11", None))]  # fmt: skip
        late = xg._event(code="lane_view", lane="far", view_sha="ab12cd34",
                         served_model=SONNET)  # fmt: skip
        events = list(state["events"])
        state["events"] = [events[0], *seen, *events[1:4], late, *events[4:]]
        record(SimpleNamespace(guard="ok"), EngineRunResult("run", "done", cast(Any, state), None))  # fmt: skip


def test_round_rows_carry_each_lane_requests_view_and_the_run_its_minutes(
    x2_run: Any,
) -> None:
    _, rows = x2_run(engine=_Viewed())

    rounds = xg._rows(rows, x2.ROUND_EXPERIMENT)
    assert [r["lane_views"] for r in rounds] == [
        [{"lane": "obvious", "view_sha": "ab12cd34", "served_model": SONNET},
         {"lane": "eliminate", "view_sha": "ff00ee11", "served_model": None}],
        [{"lane": "far", "view_sha": "ab12cd34", "served_model": SONNET}],
    ]  # fmt: skip
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert run["minutes_planned"] == 89 and 0.0 <= run["seconds_measured"] < 60.0


class _Clock:
    """``time.monotonic`` for ``ideas_x2`` alone: 1000 s, advanced 600 s by
    the clone (``start_x2_loop``) and 60 s by the engine run."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


class _SlowClone(_Viewed):
    def __init__(self, clock: _Clock) -> None:
        super().__init__()
        self.clock = clock

    def start(self, *args: Any, **kwargs: Any) -> Any:
        self.clock.now += 600.0
        return super().start(*args, **kwargs)

    def run(self, *args: Any, **kwargs: Any) -> Any:
        self.clock.now += 60.0
        return super().run(*args, **kwargs)


def test_the_measured_seconds_count_the_clone_the_plan_counts(
    x2_run: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: ``run_minutes`` plans the clone (CLONE_MINUTES), so the
    measured span starts before it, at run_one's first statement."""
    clock = _Clock()
    monkeypatch.setattr(x2, "time", clock)
    _, rows = x2_run(engine=_SlowClone(clock))
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert run["seconds_measured"] == 660.0


def test_an_arm_with_the_view_record_off_writes_none_of_it(tmp_path: Path) -> None:
    off = x2.X2Arm(
        "X2-0", x2.X2_0.repos, {**x2.SHARED, "IDEAS_VIEW_RECORD": False}, "off"
    )
    out = tmp_path / "x2.jsonl"
    plan = x2.x2_plan({**xg.X2_0_NEED, x2.DISPATCH_ENV: f"X2-0:{xg.REPO}"})
    recorder = x2.X2Recorder(plan, ResultsSink({RESULTS_ENV: str(out)}),
                             base=xg._arm_cfg(x2.X2_0), commits={xg.REPO: xg.COMMIT})  # fmt: skip
    recorder.record(off, xg.REPO, cast(Any, SimpleNamespace(cap_usd=9.35, spent_usd=0.0)),
                    xg.COMMIT, [], cast(Any, SimpleNamespace(guard="ok")), xg._state(),
                    started=0.0)  # fmt: skip

    text = out.read_text(encoding="utf-8")
    assert "lane_views" not in text and "minutes_planned" not in text


# ---------------------------------------------------------------------------
# The statistics
# ---------------------------------------------------------------------------


def test_a_rank_prints_its_position_and_the_null_rate_of_one_as_extreme() -> None:
    j, rate = xr.rank(5.0, [1.0, 2.0])
    assert j == 3 and rate == pytest.approx(2 / 3)  # [45]: k = 2
    assert xr.rank(0.0, [1.0, 2.0, 3.0]) == (1, 0.5)
    assert xr.rank(2.0, [1.0, 2.0, 3.0]) == (2, 1.0)
    assert xr.rank(2.0, [2.0, 2.0]) == (2, 1.0)  # ties read as not extreme
    assert xr.rank(6.0, [6.0, 4.0]) == (2, 1.0)


def _signs(arms: list[list[float]]) -> xr.SignCall:
    return xr.sign_call([([1.0, 2.0, 3.0], arm) for arm in arms])


def test_independent_signs_read_as_the_exact_binomial() -> None:
    """One run a library against an odd pool: each sign is 1/2 and the
    libraries are independent, so the stratified null is the binomial."""
    eight = _signs([[5.0]] * 8 + [[0.0]])
    assert (eight.up, eight.down) == (8, 1)
    assert (
        eight.p_above == pytest.approx(10 / 512) and round(eight.p_above, 4) == 0.0195
    )
    seven = _signs([[5.0]] * 7 + [[0.0]] * 2)
    assert seven.p_above == pytest.approx(46 / 512) and round(seven.p_above, 3) == 0.090
    assert eight.p_two == pytest.approx(20 / 512)
    assert xr.sign_cell(eight) == (
        "8 above, 1 below, 0 ties; two-sided p 0.0391 (above 0.0195, below 0.9980)"
    )
    five = _signs([[5.0]] * 4 + [[0.0], [2.0]])
    assert (five.up, five.down, five.ties) == (4, 1, 1)
    assert xr.sign_cell(five) == "4 above, 1 below, 1 ties; not tested (5)"


def test_runs_sharing_one_pool_median_are_not_counted_as_independent() -> None:
    """Judge [86]'s SIM, 2 libraries x 4 runs against a 3-draw pool: 7 of 8
    above is 0.035 as a binomial, 0.086 under the null that deals each
    library's draws anew; 3 of 3 on one library is 0.20, not 1/8."""
    call = _signs([[4.0, 5.0, 6.0, 7.0], [4.0, 5.0, 6.0, 0.0]])
    binomial = math.fsum(math.comb(8, i) for i in (7, 8)) / 2**8
    assert round(binomial, 3) == 0.035 and round(call.p_above, 3) == 0.086
    assert _signs([[4.0, 5.0, 6.0]]).p_above == pytest.approx(0.2)


def test_the_arm_call_is_two_sided_and_never_above_one() -> None:
    """Review: the bar reads one pre-registered p, two-sided, 2 x the
    smaller tail, capped at 1 (a sum at the null's centre has both tails
    over 1/2)."""
    even = _signs([[5.0]] * 3 + [[0.0]] * 3)
    assert even.p_above > 0.5 and even.p_below > 0.5 and even.p_two == 1.0
    assert xr.SIDES == "two-sided"


def test_an_even_pool_reads_against_its_lower_median() -> None:
    assert xr.lower_median([9.0, 7.0]) == 7.0 and xr.lower_median([6.0]) == 6.0
    call = xr.sign_call([([7.0, 9.0], [8.0])])
    assert (call.up, call.down) == (1, 0)


# ---------------------------------------------------------------------------
# The pool and the report, on fixtures
# ---------------------------------------------------------------------------


def _run(arm: str, repo: str, kept: int, gain: float | None, cost: float = 2.0) -> list[rg.Row]:  # fmt: skip
    return rg._rows(
        arm, repo, [(max(kept, 1), ["obvious"] * kept)], gain=gain, cost=cost
    )


def test_a_pool_holding_the_read_arms_own_run_is_refused(tmp_path: Path) -> None:
    found = xr.draws([rg._write(tmp_path / "a.jsonl", _run("X2-0", "tomli", 6, 22.0)),
                      rg._write(tmp_path / "b.jsonl", _run("X2-0", "tomli", 4, 18.0))])  # fmt: skip
    assert xr.pool(found, "X2-0", "tomli") == ()
    with pytest.raises(
        ValueError, match="X2-0 tomli: the pool holds the read arm's own run"
    ):
        xr.range_reading(found[0], found[1:])
    with pytest.raises(ValueError, match="own run"):
        xr.rank_cells(found[0], found[1:])


def test_a_file_read_twice_is_refused(tmp_path: Path) -> None:
    path = rg._write(tmp_path / "a.jsonl", _run("X2-0", "tomli", 6, 22.0))
    copy = tmp_path / "copy.jsonl"
    copy.write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="copy.jsonl: the same bytes as a.jsonl"):
        xr.draws([path, copy])


def test_the_variance_page_on_fixtures(tmp_path: Path) -> None:
    """
    GIVEN two X2-0 draws and one X2-0' draw on tomli, an X2-S draw read
          against them, an X2-0 draw on mistune alone and lane views
    WHEN the variance page renders
    THEN each read draw prints its k, ranks and rates and O51's range form
         with its arm left out; a draw with no pool or no X2-0 reads n/a;
         the arm calls print "not tested (n)"; the bars table prints each
         n-need; the views table names the distinct hashes
    """
    view = {"lane": "obvious", "view_sha": "ab12cd34", "served_model": "m"}
    first = _run("X2-0", "tomli", 6, 22.0)
    first[-2]["lane_views"] = [view, {**view, "lane": "far", "served_model": None}]
    second = _run("X2-0", "tomli", 6, 20.0)
    second[-2]["lane_views"] = [{**view, "view_sha": "ff00ee11"}]
    files = [rg._write(tmp_path / "a.jsonl", first, _run("X2-0'", "tomli", 5, 19.0),
                       _run("X2-0", "mistune", 4, None)),
             rg._write(tmp_path / "b.jsonl", second, _run("X2-S", "tomli", 3, 10.0, 3.0))]  # fmt: skip

    text = xr.render_variance(xr.draws(files))

    assert "| b.jsonl | X2-S | tomli | 3 | 3 | 1 of 4 | 0.50 | +10.0 | 1 of 4 | 0.50 | outside |" in text  # fmt: skip
    assert "| a.jsonl | X2-0' | tomli | 2 | 5 | 1 of 3 | 0.67 | +19.0 | 1 of 3 | 0.67 | inside |" in text  # fmt: skip
    assert "| a.jsonl | X2-0 | tomli | 1 | 6 | 2 of 2 | 1.00 | +22.0 | 2 of 2 | 1.00 | n/a |" in text  # fmt: skip
    assert "| a.jsonl | X2-0 | mistune | 0 | 4 | - | - | +0.0 | - | - | n/a |" in text
    assert "| tomli | 3 | 5, 6, 6 | +19.0, +20.0, +22.0 |" in text
    assert "| X2-S | kept | tomli | 0 above, 1 below, 0 ties; not tested (1) |" in text
    assert "| X2-S sign test, kept | 6 signs | 1 | not tested (1) |" in text
    assert "| rank call, tomli | k 39 | 3 | not tested (k 3) |" in text
    assert "| tomli | 1 | obvious | 2 | 2 | m |" in text
    assert "| tomli | 1 | far | 1 | 1 | - |" in text
    assert "O51 as amended and O52 stay the ruling reading" in text
    assert "| X2-S | 1 | 3.0 | +10.0 | 0.0 | 1.0000 | 0.300 |" in text


def test_the_cli_writes_the_variance_page_only_on_request(tmp_path: Path) -> None:
    path = rg._write(tmp_path / "a.jsonl", _run("X2-0", "tomli", 6, 22.0))
    said: list[str] = []
    assert (
        xr.main([str(path), "--variance", "--out", str(tmp_path / "o")], said.append)
        == 0
    )
    assert said == [f"wrote variance.md to {tmp_path / 'o'}"]
    assert not (tmp_path / "o" / "x2.md").exists()
    assert (
        (tmp_path / "o" / "variance.md")
        .read_text(encoding="utf-8")
        .startswith("# X2 variance")
    )
    assert xr.main([str(tmp_path / "none.jsonl"), "--variance"], said.append) == 2


# ---------------------------------------------------------------------------
# The ten archives: the replay and the refit
# ---------------------------------------------------------------------------


def test_the_arm_left_out_replay_reads_o51s_4_of_5_on_the_archives() -> None:
    """[49]/[76]: X2-S against the pool without itself: tomli 4 against
    {6, 6}, mistune 4 against {6}, sqlparse E1 11 and E2 3 against {9, 7},
    more_itertools 0 against {2}: 4 of 5 outside, as O51's one-pair band."""
    found = xr.draws(ARCHIVES)
    assert len(ARCHIVES) == 10 and len(found) == 25
    got = {(d.source[:13], d.repo): (len(p := xr.pool(found, d.arm, d.repo)),
                                     sorted(x.run.row.kept for x in p), xr.range_reading(d, p))
           for d in found if d.arm == "X2-S"}  # fmt: skip
    assert got == {
        ("ideas-x2s-e1-", "tomli"): (2, [6, 6], "outside"),
        ("ideas-x2s-e1-", "mistune"): (1, [6], "outside"),
        ("ideas-x2s-e1-", "sqlparse"): (2, [7, 9], "inside"),
        ("ideas-x2s-e2-", "sqlparse"): (2, [7, 9], "outside"),
        ("ideas-x2s-e2-", "more_itertools"): (1, [2], "outside"),
    }  # fmt: skip
    text = xr.render_variance(found)
    assert "| X2-S | kept | mistune, more_itertools, sqlparse, tomli | 1 above, 4 below, 0 ties; not tested (5) |" in text  # fmt: skip


def test_the_delivered_sum_refit_and_usd_per_delivered_point_on_the_archives() -> None:
    """[78]'s refit: delivered sum / combine on the runs with 2 or more
    delivered keeps (d1-d8 where every keep applied, E1/E2 by S2's
    record); [26]: X2-S 12.29 USD over 81.35 delivered points."""
    found = xr.draws(ARCHIVES)
    ratios = {(d.source[:13], d.repo): round(s / d.combine, 3) for d in found
              if (s := xr.delivered_sum(d.run)) is not None}  # fmt: skip
    assert ratios == {
        ("ideas-x2-d1-4", "sortedcontainers"): 1.144, ("ideas-x2-d3-4", "pyparsing"): 1.538,
        ("ideas-x2-d6-4", "mistune"): 1.179, ("ideas-x2s-e1-", "tomli"): 1.042,
        ("ideas-x2s-e1-", "mistune"): 1.202, ("ideas-x2s-e1-", "sqlparse"): 1.164,
        ("ideas-x2s-e2-", "sqlparse"): 0.923,
    }  # fmt: skip
    text = xr.render_variance(found)
    assert "| X2-S | 5 | 4.4 | +16.3 | 2.6 | 0.5585 | 0.151 |" in text
    # Review: X2-V's kept reads 0.046 on its lower tail, 0.093 two-sided:
    # printed, not called, and not significant on the pre-registered p.
    assert "| X2-V | kept |" in text and (
        "2 above, 5 below, 1 ties; two-sided p 0.0926 (above 0.9676, below 0.0463) |"
        in text
    )
    assert "| X2-V sign test, kept | 6 signs | 7 | read, two-sided p 0.0926 |" in text
    assert "two-sided" in text.split("## 1 The pool")[0]
    assert "7 runs with 2 or more delivered keeps: median 1.16, range 0.92-1.54, 7 at 0.9 or more" in text  # fmt: skip
