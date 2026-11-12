"""Offline guards of the portfolio leap's records and report (U-portfolio,
``ideas_x2_frameworks``).

Not ``live``: pure code over rows and a fake run. Fakes and what they stand
for: ``_rows`` hand-makes the ``ideas-x2-round`` and ``ideas-x2-hypothesis``
rows ``ideas_x2.X2Recorder`` writes for a portfolio arm; the recorder test
feeds ``X2Recorder.record`` a fake engine state (``test_ideas_x2_guards``'s
helpers) whose events hold the pipeline's ``leap_procedure`` and
``leap_diagnosis`` data and whose leap hypothesis carries the
``framework:<id>`` tag, as ``idea_pipeline`` writes them. What only a live
run proves: that the engine's node carries these events into the state.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.config import Settings, leap_shape, settings
from autonomous_ai_agents.common.models import Trial, VerdictOutcome
from autonomous_ai_agents.optimization.idea_frameworks import DEAL_LIBRARIES
from autonomous_ai_agents.optimization.idea_portfolio_leap import (
    DIAGNOSIS_EVENT,
    PROCEDURE_EVENT,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import discovery_oss as dx
from . import ideas_x2 as x2
from . import ideas_x2_frameworks as fx
from . import ideas_x2_report as xr
from . import test_ideas_slice_guards as sg
from . import test_ideas_x2_guards as xg
from . import test_oss_guards as og
from .conftest import LiveRun
from .corpus import RESULTS_ENV, settings_trial_budget
from .discovery_io import ResultsSink

Row = dict[str, object]


def _proc(framework: str, outcome: str, present: str, required: int) -> Row:
    return {"framework": framework, "outcome": outcome, "steps_present": present,
            "steps_required": required}  # fmt: skip


def _rows() -> list[Row]:
    return [
        {"experiment": fx.ROUND_EXPERIMENT, "arm": "X2-P", "round": 1, "procedures": [
            _proc("bentley", "idea", "1,2,3,4,5", 5),
            _proc("sit", "not_applicable", "1,2", 4),
            _proc("recall", "dropped", "1,2,3", 3),
            "not a row", {"outcome": "idea"},  # skipped: no framework
            {"framework": "polya", "steps_required": "4", "steps_present": None},
        ]},
        {"experiment": fx.ROUND_EXPERIMENT, "arm": "X2-P", "round": 2, "procedures": [
            _proc("bentley", "idea", "1,2", 5),
            _proc("bentley", "no_reply", "", 5),  # unanswered: no adherence
            _proc("sit", "not_sent", "", 4),
        ]},
        {"experiment": fx.ROUND_EXPERIMENT, "arm": "X2-F", "procedures": [
            _proc("skiena", "idea", "1,2,3,4,5,6", 6),
        ]},
        {"experiment": fx.ROUND_EXPERIMENT, "arm": "X2-0", "round": 1},  # no portfolio
        {"experiment": fx.ROUND_EXPERIMENT, "arm": None, "procedures": [
            _proc("bentley", "idea", "1", 5)]},  # no arm: skipped
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-P", "framework": "bentley",
         "round": 1, "verdict": "keep", "gain_pct": 6.0, "floor_pct": 2.0},
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-P", "framework": "bentley",
         "round": 2, "verdict": "reject", "gain_pct": 1.0, "floor_pct": 2.0},
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-P", "framework": "bentley",
         "round": 2, "verdict": "keep", "gain_pct": True, "floor_pct": 2.0},
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-P", "framework": "bentley",
         "round": None, "verdict": "not_trialled"},  # left in the pool
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-F", "framework": "skiena",
         "round": 1, "verdict": "inconclusive", "gain_pct": 1.0, "floor_pct": 0.0},
        {"experiment": fx.IDEA_EXPERIMENT, "arm": "X2-P", "round": 1, "verdict": "keep"},
        {"experiment": "ideas-x2-run", "arm": "X2-P"},
    ]  # fmt: skip


def test_the_table_counts_dealt_ideas_trialled_kept_gain_and_adherence() -> None:
    table = fx.framework_table(_rows())
    assert [(x.arm, x.framework) for x in table] == [
        ("X2-F", "skiena"), ("X2-P", "bentley"), ("X2-P", "polya"),
        ("X2-P", "sit"), ("X2-P", "recall"),
    ]  # fmt: skip
    found = {(x.arm, x.framework): x for x in table}
    bentley = found["X2-P", "bentley"]
    assert (bentley.dealt, bentley.no_reply, bentley.not_sent, bentley.ideas,
            bentley.trialled, bentley.kept) == (3, 1, 0, 2, 3, 2)  # fmt: skip
    assert bentley.median_gain == pytest.approx(1.75)  # 3.0 and 0.5
    assert bentley.adherence == pytest.approx(7 / 10)  # the two answered ones
    sit = found["X2-P", "sit"]
    assert (sit.dealt, sit.not_sent, sit.ideas, sit.trialled, sit.median_gain) == (
        2, 1, 0, 0, None)  # fmt: skip
    assert sit.adherence == pytest.approx(0.5)
    polya = found["X2-P", "polya"]
    assert (polya.dealt, polya.adherence) == (1, None)
    skiena = found["X2-F", "skiena"]
    assert (skiena.trialled, skiena.median_gain, skiena.adherence) == (1, None, 1.0)


def test_an_unknown_framework_sorts_after_the_catalogue() -> None:
    rows: list[Row] = [{"experiment": fx.ROUND_EXPERIMENT, "arm": "A", "procedures": [
        _proc("zz_new", "idea", "1", 1), _proc("recall", "idea", "1", 3)]}]  # fmt: skip
    assert [x.framework for x in fx.framework_table(rows)] == ["recall", "zz_new"]


def test_the_section_is_a_table_or_one_line() -> None:
    assert fx.framework_section([]) == ["No portfolio leap recorded.", ""]
    lines = fx.framework_section(_rows())
    assert lines[0] == ("| arm | framework | dealt | no reply | not sent | ideas | "
                        "trialled | kept | median gain / floor | "
                        "adherence (answered) |")  # fmt: skip
    assert "| X2-P | bentley | 3 | 1 | 0 | 2 | 3 | 2 | 1.75 | 70% |" in lines
    assert "| X2-P | polya | 1 | 0 | 0 | 0 | 0 | 0 | - | - |" in lines
    assert lines[-1] == ""


def test_the_round_and_hypothesis_fields_are_empty_without_the_portfolio() -> None:
    assert fx.round_fields([{"code": "compound", "round": 2}]) == {}
    plain = xg._hyp("leap idea", "lane:leap")
    assert fx.hypothesis_fields(plain) == {}
    tagged = xg._hyp("leap idea", "lane:leap", "framework:per_element",
                     "steps_present:1.2.4")  # fmt: skip
    assert fx.hypothesis_fields(tagged) == {
        "framework": "per_element", "steps_present": "1,2,4", "not_applicable": None}  # fmt: skip
    for steps in ((), ("steps_present:none",)):
        none = xg._hyp("leap idea", "lane:leap", "framework:sit", *steps)
        assert fx.hypothesis_fields(none)["steps_present"] == ""
    found = fx.round_fields([
        {"code": PROCEDURE_EVENT, "framework": "sit", "tool": "division"},
        {"code": DIAGNOSIS_EVENT, "gap": "large"},
        {"code": "lane_view", "lane": "leap"},
    ])  # fmt: skip
    assert found == {"procedures": [{"framework": "sit", "tool": "division"}],
                     "diagnoses": [{"gap": "large"}]}  # fmt: skip


def test_the_deal_library_is_set_for_the_block_only_with_the_portfolio_on() -> None:
    before = settings.IDEAS_LEAP_DEAL_LIBRARY
    on = settings.model_copy(update={"IDEAS_LEAP_PORTFOLIO": True})
    with fx.deal_library("sqlparse", on):
        assert settings.IDEAS_LEAP_DEAL_LIBRARY == "sqlparse"
    assert settings.IDEAS_LEAP_DEAL_LIBRARY == before
    with fx.deal_library("sqlparse", settings):
        assert settings.IDEAS_LEAP_DEAL_LIBRARY == before
    refused = fx.deal_library("requests", on)
    with pytest.raises(ValueError, match="deal library"):
        refused.__enter__()
    assert settings.IDEAS_LEAP_DEAL_LIBRARY == before


def _portfolio_state() -> EngineRunResult:
    leap = xg._hyp("leap idea", "lane:leap", "framework:bentley",
                   "steps_present:1.2.3.4.5")  # fmt: skip
    lens = xg._hyp("lens idea", "lane:eliminate")
    trials = [Trial(hypothesis_id=h.id, round=1) for h in (leap, lens)]
    verdicts = [xg._verdict(leap, trials[0], VerdictOutcome.keep, 0.08),
                xg._verdict(lens, trials[1], VerdictOutcome.reject, -0.01)]  # fmt: skip
    events = [
        xg._event(code=DIAGNOSIS_EVENT, gap="the gap"),
        xg._event(code=PROCEDURE_EVENT, framework="bentley", outcome="idea",
                  steps_present="1,2,3,4,5", steps_required=5, hypothesis_id=leap.id),
        xg._event(code=PROCEDURE_EVENT, framework="sit", outcome="none",
                  steps_present="", steps_required=4, hypothesis_id=None),
        xg._event(round=1, ranked=2, candidates=2),
        xg._event(round=1, verdicts=2, keep=1),  # after the ranking: no round's
        xg._event(code="generated", kept=0),  # round 2's call: its lanes unsent
        xg._event(code=PROCEDURE_EVENT, framework="ifr", outcome="not_sent",
                  steps_present="", steps_required=4, hypothesis_id=None),
    ]  # fmt: skip
    state = {
        "objectives": [sg._objective()], "hypotheses": [leap, lens],
        "candidate_pool": [], "parked": [], "trials": trials, "verdicts": verdicts,
        "events": events, "combination": None, "delivery": None,
        "discovery_cost_usd": 0.5, "seeded_calls": 0, "seeded_cost_usd": 0.0,
    }  # fmt: skip
    return EngineRunResult("run", "done", cast(Any, state), None)


@pytest.mark.parametrize("portfolio", [True, False])
def test_the_recorder_writes_the_framework_and_procedure_rows(
    tmp_path: Path, portfolio: bool
) -> None:
    """GIVEN a run whose events hold the portfolio leap's rows (an arm with it
    on) or none (X2-0) THEN the hypothesis row of the leap idea carries its
    framework and the round row the procedures and diagnosis, and X2-0's
    rows carry neither."""
    arm = x2.X2_P if portfolio else x2.X2_0
    out = tmp_path / "rows.jsonl"
    plan = x2.X2Plan(f"{arm.key}:{xg.REPO}", ((arm, xg.TOMLI),))
    recorder = x2.X2Recorder(plan, ResultsSink({RESULTS_ENV: str(out)}),
                             base=_with_run(arm), commits={xg.REPO: xg.COMMIT})  # fmt: skip
    state = _portfolio_state()
    if not portfolio:
        st = cast(dict[str, Any], state.state)
        st["events"] = [e for e in st["events"] if "ranked" in e.data]
        st["hypotheses"][0] = xg._hyp("leap idea", "lane:leap")
    recorder.record(arm, xg.REPO, LiveRun("x", 9.0), xg.COMMIT, [],
                    cast(Any, SimpleNamespace(guard="ok")), state)  # fmt: skip
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    ideas = {r["title"]: r for r in rows if r["experiment"] == x2.IDEA_EXPERIMENT}
    round_rows = [r for r in rows if r["experiment"] == x2.ROUND_EXPERIMENT]
    round_row = round_rows[0]
    assert "framework" not in ideas["lens idea"]
    if not portfolio:
        assert len(round_rows) == 1
        assert "framework" not in ideas["leap idea"]
        assert "procedures" not in round_row and "diagnoses" not in round_row
        return
    leap = ideas["leap idea"]
    assert {k: leap[k] for k in ("framework", "steps_present", "not_applicable")} == {
        "framework": "bentley", "steps_present": "1,2,3,4,5", "not_applicable": None}  # fmt: skip
    joined = [p for r in round_rows for p in r["procedures"]
              if p["hypothesis_id"] == leap["hypothesis_id"]]  # fmt: skip
    assert len(joined) == 1 and joined[0]["framework"] == leap["framework"]
    assert [r["round"] for r in round_rows] == [1, 2]
    assert [p["outcome"] for p in round_rows[1]["procedures"]] == ["not_sent"]
    assert round_rows[1]["trialled"] == 0
    assert [p["framework"] for p in round_row["procedures"]] == ["bentley", "sit"]
    assert round_row["diagnoses"] == [{"gap": "the gap"}]
    table = {(x.arm, x.framework): x for x in fx.framework_table(rows)}
    bentley = table["X2-P", "bentley"]
    assert (bentley.dealt, bentley.ideas, bentley.trialled, bentley.kept) == (
        1,
        1,
        1,
        1,
    )
    assert bentley.median_gain == pytest.approx(4.0)  # 8 % over a 2 % floor
    assert table["X2-P", "sit"].adherence == 0.0
    assert (table["X2-P", "ifr"].not_sent, table["X2-P", "ifr"].adherence) == (1, None)


def test_by_round_keeps_only_portfolio_rows_after_the_last_ranking() -> None:
    """Other events after the last ``ranked`` stay dropped, as before."""
    events = [
        xg._event(code="generated"), xg._event(round=1, ranked=1, candidates=1),
        xg._event(code="compound"), xg._event(code=DIAGNOSIS_EVENT, gap="g"),
        xg._event(code=PROCEDURE_EVENT, framework="sit"),
    ]  # fmt: skip
    found = x2._by_round(events)
    assert [d.get("code") for d in found[1]] == ["generated"]
    assert [d.get("code") for d in found[2]] == [DIAGNOSIS_EVENT, PROCEDURE_EVENT]
    assert x2._by_round(events[2:3]) == {}
    assert [d.get("code") for d in x2._by_round(events[4:])[1]] == [PROCEDURE_EVENT]


# --------------------------------------------------------------------------
# The arms (X2-P, X2-F), the per-case library and the report page
# --------------------------------------------------------------------------

FOUR = ("sqlparse", "tomli", "mistune", "markdown")


def _with_run(arm: x2.X2Arm, run: int = 1) -> Settings:
    return xg._arm_cfg(arm).model_copy(update={"IDEAS_LEAP_DEAL_RUN": run})


def test_the_portfolio_arms_are_x2_0_with_the_leap_dealt_off_the_plan() -> None:
    assert dict(x2.X2_P.update) == {**x2.SHARED, "IDEAS_LEAP_PORTFOLIO": True}
    assert dict(x2.X2_F.update) == {**x2.X2_P.update, "IDEAS_LEAP_MODEL": x2.FABLE_52,
                                    "ALLOW_RETENTION_MODELS": True}  # fmt: skip
    assert x2.X2_P.repos == x2.X2_F.repos == FOUR == DEAL_LIBRARIES
    assert (x2.X2_P.aa, x2.X2_F.aa) == ("none", "none")
    keys = [a.key for a in x2.EVERY_ARM]
    assert keys[keys.index("X2-D") + 1 : keys.index("X2-S")] == ["X2-P", "X2-F", "X2-L"]
    assert not any(d.startswith(("X2-P", "X2-F")) for d in x2.dispatches())
    assert {"X2-P", "X2-F"} <= set(xr.ARMS) and not {"X2-P", "X2-F"} & xr.POOL


def test_the_portfolio_arms_caps_and_minutes() -> None:
    """The 32,000 leap priced through leap_shape, each earlier call charged
    its leap beyond X2-0's (``leap_extra_usd``): X2-P 10.55 USD, X2-F 21.10
    (its share at S2's check binds); both 113 minutes (the portfolio leap's
    951 s timeout); two runs a dispatch at a 20 % margin under the 360-minute
    job, three without. Every other arm's leap but X2-L's (the Fable leap,
    test_fable_leap_caps_guards) is X2-0's: no extra, its caps as pinned."""
    for arm, cap, minutes in ((x2.X2_P, 10.55, 113), (x2.X2_F, 21.10, 113)):
        cfg = x2.arm_settings(arm)
        shape = leap_shape(cfg)
        assert (shape.max_tokens, shape.timeout_s) == (32_000, 951.0)
        assert x2.leap_extra_usd(cfg) > 0
        assert (x2.arm_cap(arm), x2.run_minutes(cfg)) == (cap, minutes)
        assert int(x2.JOB_MINUTES * 0.8) // minutes == 2
        assert x2.JOB_MINUTES // minutes == 3
    for arm in x2.EVERY_ARM:
        if arm not in (*x2.PORTFOLIO_ARMS, x2.X2_L):  # O61: X2-L's Fable leap
            assert x2.leap_extra_usd(x2.arm_settings(arm)) == 0.0, arm.key
    assert (
        x2.arm_cap(x2.X2_0) == 9.35 and x2.run_minutes(x2.arm_settings(x2.X2_0)) == 89
    )


@pytest.mark.parametrize("arm", x2.EVERY_ARM, ids=lambda a: a.key)
def test_the_last_calls_lanes_pass_the_engines_check_at_the_worst(
    arm: x2.X2Arm,
) -> None:
    """The engine's discovery cap (``nodes._discovery_cap``): ``min(cap -
    trial reserve, cost + share * cap - discovery spent)``. At S2's check of
    the last (seeded) call, as run_cap prices it: every earlier call spent
    its ``call_usd`` (X1's dearest plus the arm's leap beyond X1's at its
    worst), S1 X1's measured dearest (``X1_S1_USD``), the earlier rounds'
    trials at X1's loop rate after phase 1; the engine's S2 estimate must
    still fit both terms, or S2 is skipped whole (``discovery_unaffordable``).
    X2-F's margin is the tightest (0.02 USD)."""
    cfg = x2.arm_settings(arm)
    cap = x2.arm_cap(arm)
    _, s2, _ = x2.seeded_stages(cfg)
    earlier = (cfg.MAX_TRIAL_ROUNDS - 1) * x2.call_usd(cfg)
    discovery = earlier + x2.X1_S1_USD
    trials = x2.X1_LOOP_USD / x2.LOOP_TRIALS * sum(x2.run_trials(cfg)[:-1])
    cost = dx.OSS_PHASE_ONE_WORST_USD + trials + discovery
    reserve = settings_trial_budget(cfg)
    room = min(cap - reserve, cost + cfg.IDEAS_DISCOVERY_MAX_SHARE * cap - discovery)
    assert room - cost >= s2, (arm.key, room - cost, s2)


def test_a_portfolio_arm_without_its_deal_run_is_refused_before_any_spend() -> None:
    with pytest.raises(ValueError, match="deal run"):
        x2.check_settings(x2.X2_P, xg._arm_cfg(x2.X2_P))
    with pytest.raises(ValueError, match="deal run"):
        x2.check_settings(x2.X2_F, _with_run(x2.X2_F, 4))
    x2.check_settings(x2.X2_F, _with_run(x2.X2_F, 3))
    x2.check_settings(x2.X2_0, xg._arm_cfg(x2.X2_0))  # no deal run needed


class _Seen(xg._Engine):
    """``xg._Engine`` noting the process-wide deal library at the loop's build."""

    library: str | None = "unset"

    def start(self, repo: Any, run: LiveRun, root: Path, isolation: Any, *,
              policy: object) -> Any:  # fmt: skip
        self.library = settings.IDEAS_LEAP_DEAL_LIBRARY
        return super().start(repo, run, root, isolation, policy=policy)


@pytest.mark.parametrize("arm", [x2.X2_P, x2.X2_0])
def test_run_one_sets_the_cases_library_only_while_the_loop_is_built(
    arm: x2.X2Arm, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _Seen()
    monkeypatch.setattr(x2, "start_x2_loop", engine.start)
    monkeypatch.setattr(x2, "run_engine", engine.run)
    plan = x2.X2Plan(f"{arm.key}:{xg.REPO}", ((arm, xg.TOMLI),))
    recorder = x2.X2Recorder(plan, ResultsSink({RESULTS_ENV: str(tmp_path / "o.jsonl")}),
                             base=_with_run(arm), commits={xg.REPO: xg.COMMIT})  # fmt: skip
    before = settings.IDEAS_LEAP_DEAL_LIBRARY
    x2.run_one(arm, xg.TOMLI, live=cast(Any, lambda cap: LiveRun("x", cap)),
               root=tmp_path / "root", isolation=xg.REQUIRED, recorder=recorder,
               policy=og.LOCAL)  # fmt: skip
    assert engine.library == (xg.REPO if arm is x2.X2_P else before)
    assert settings.IDEAS_LEAP_DEAL_LIBRARY == before


def test_the_report_writes_the_frameworks_page(tmp_path: Path) -> None:
    results = tmp_path / "r.jsonl"
    results.write_text("\n".join([*(json.dumps(r) for r in _rows()), "", "[1]"]),
                       encoding="utf-8")  # fmt: skip
    said: list[str] = []
    assert xr.main([str(results), "--out", str(tmp_path / "out"), "--frameworks"],
                   echo=said.append) == 0  # fmt: skip
    page = (tmp_path / "out" / "frameworks.md").read_text(encoding="utf-8")
    assert page.startswith("# X2 portfolio leap by framework")
    assert "adherence (answered)" in page and "over the answered procedures" in page
    assert "| X2-P | bentley | 3 | 1 | 0 | 2 | 3 | 2 | 1.75 | 70% |" in page
    assert said == [f"wrote frameworks.md to {tmp_path / 'out'}"]
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    assert xr.main([str(bad), "--out", str(tmp_path / "x"), "--frameworks"],
                   echo=said.append) == 2  # fmt: skip
    assert "not JSON" in said[-1] and not (tmp_path / "x").exists()
