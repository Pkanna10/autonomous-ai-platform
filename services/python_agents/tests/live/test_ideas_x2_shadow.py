"""Offline guards of S4's shadow record in the ideas-x2 suite (emergence
round 2): the X2-SV arm, its declared rider seconds and its row fields.

Not ``live``: these spend nothing. X2-SV is X2-C's settings plus
``SHADOW_VERIFY=record``, read by the trial runner only (no request, prompt
or verdict changes), so it is a pool draw like X2-0; it is off the dispatch
plan (``dispatches``) until the Lead and the owner put it there. Its
hypothesis rows carry the first measured trial's shadow reading
(``shadow_verify.shadow_reading`` over its twin's and its own
``shadow_calls`` rows) and its run row the base A/A count over every
measured trial's twin; other arms' rows carry neither. Fakes:
``test_ideas_x2_guards``'s ``_Engine`` and hand-built state stand for the
whole engine run.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import Measurement, RunStats, TrialStatus
from autonomous_ai_agents.execution.measure import (
    METRIC_SHADOW_CALLS,
    SHADOW_CAPTURED_KEY,
    SHADOW_CORPUS_KEY,
    SHADOW_DISTINCT_KEY,
    SHADOW_LEG_KEY,
    SHADOW_RAISED_KEY,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import test_ideas_x2_guards as xg
from .conftest import SUITE_CAP_ENV

x2_run = xg.x2_run


def test_x2_sv_is_x2_c_with_the_shadow_record_off_the_plan() -> None:
    assert x2.X2_SV.key == "X2-SV" and x2.X2_SV.repos == (
        "sqlparse",
        "tomli",
        "mistune",
    )
    assert dict(x2.X2_SV.update) == {**x2.X2_C.update, "SHADOW_VERIFY": "record"}
    assert x2.X2_SV.aa == "full" and x2.X2_SV not in x2.X2_ARMS
    assert x2.EVERY_ARM[-1] is x2.X2_SV  # listed last, off the plan
    assert x2.arm_cap(x2.X2_SV) == x2.arm_cap(x2.X2_0)
    assert x2.arm_env(x2.X2_SV)["SHADOW_VERIFY"] == "record"
    plan = x2.x2_plan(
        {x2.DISPATCH_ENV: "X2-SV:sqlparse,tomli,mistune", SUITE_CAP_ENV: "29"}
    )
    assert [r.name for _, r in plan.runs] == ["sqlparse", "tomli", "mistune"]


def test_the_shadow_riders_seconds_are_declared() -> None:
    """Two capture launches a trial (the twin and the trial) and one at the
    baseline, 7.4-7.9 s each on sqlparse in this container: 8 s a run and
    16 s a trial, in ``RIDER_SECONDS`` so the ledger itself counts them
    (review R4: ``run_minutes`` and ``check_plan`` see the rider); 21 trials
    a run stay under [87] (d)'s 10 minutes a library-run, and a 3-run
    dispatch still fits the job."""
    assert x2.SHADOW_RIDER == x2.Rider(run_s=8.0, trial_s=16.0)
    assert x2.RIDER_SECONDS[("SHADOW_VERIFY", "record")] == x2.SHADOW_RIDER
    shadow, count = x2.arm_settings(x2.X2_SV), x2.arm_settings(x2.X2_C)
    trials = sum(x2.run_trials(shadow))
    assert trials == sum(x2.run_trials(count)) and x2.rider_seconds(count) == 0.0
    seconds = x2.SHADOW_RIDER.run_s + trials * x2.SHADOW_RIDER.trial_s
    assert x2.rider_seconds(shadow) == seconds and seconds / 60 < 10
    assert x2.run_minutes(shadow) - x2.run_minutes(count) == math.ceil(seconds / 60)
    plan = x2.X2Plan("X2-SV", ((x2.X2_SV, x2.LIBRARIES["sqlparse"]),) * 3)
    assert x2.plan_minutes(plan) == 3 * x2.run_minutes(shadow) <= x2.JOB_MINUTES


class _Shadowed(xg._Engine):
    """The fake run with measured trials: the S1 idea's twin counts its legs
    900 / 300 and the trial 400 / 310 (a benchmark cut the distinct inputs
    lose); the lens trial is measured with no capture rows."""

    def __init__(self, *, drift: bool = False) -> None:
        super().__init__()
        self.drift = drift

    def start(self, *args: Any, **kwargs: Any) -> Any:
        loop = super().start(*args, **kwargs)
        loop.user.path = Path("/nonexistent-clone")  # no diff: nothing is read
        return loop

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str, record: Any) -> Any:  # fmt: skip
        state: dict[str, Any] = dict(xg._state().state)
        trials = list(state["trials"])
        base = _legs(901.0 if self.drift else 900.0, 300.0, None)
        trials[0] = trials[0].model_copy(update={"status": TrialStatus.measured,
            "base_measurements": _legs(900.0, 300.0, None),
            "measurements": _legs(400.0, 310.0, trials[0].id)})  # fmt: skip
        trials[1] = trials[1].model_copy(update={"status": TrialStatus.measured,
                                                 "base_measurements": base})  # fmt: skip
        state["trials"] = trials
        record(SimpleNamespace(guard="ok"), EngineRunResult("run", "done", cast(Any, state), None))  # fmt: skip


def _legs(
    sequence: float, point: float, trial_id: str | None
) -> tuple[Measurement, ...]:
    def one(leg: str, n: float) -> Measurement:
        hw: dict[str, str | int] = {SHADOW_LEG_KEY: leg, SHADOW_CORPUS_KEY: "e" * 64}
        if leg != "sequence":
            hw |= {
                SHADOW_CAPTURED_KEY: 12,
                SHADOW_DISTINCT_KEY: 4,
                SHADOW_RAISED_KEY: 0,
            }
        return Measurement(workload_id="w", trial_id=trial_id, metric=METRIC_SHADOW_CALLS,
                           stats=RunStats.from_samples((n,), unit="calls"), samples=(n,),
                           hardware=hw)  # fmt: skip

    return (one("sequence", sequence), one("pkg.f", point))


def test_x2_sv_rows_carry_the_shadow_reading_and_the_base_a_a(x2_run: Any) -> None:
    """
    GIVEN an X2-SV run whose S1 trial's legs read a memo and whose lens
        trial was measured without capture rows on its own side
    WHEN it is recorded
    THEN the S1 row reads ``repetition_fit`` (share 1), the lens row
        ``uncapturable``, an unmeasured trial and a pool idea none; the run
        row's base A/A is 0 (the two twins agree)
    """
    _, rows = x2_run(engine=_Shadowed(), arm=x2.X2_SV)

    ideas = {r["title"]: r for r in xg._rows(rows, x2.IDEA_EXPERIMENT)}
    s1 = next(r for t, r in ideas.items() if t.startswith("S1 idea"))["shadow_verify"]
    assert (s1["label"], s1["share"], s1["points"], s1["calls"], s1["distinct"]) == (
        "repetition_fit", 1.0, 1, 12, 4,
    )  # fmt: skip
    assert s1["bench_cut"] == pytest.approx(500 / 900)
    assert ideas["lens idea"]["shadow_verify"]["label"] == "uncapturable"
    assert ideas["leap idea"]["shadow_verify"] is None
    assert ideas["pool idea"]["shadow_verify"] is None
    [run] = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert run["shadow_aa"] == 0


def test_a_base_that_moves_between_trials_is_counted(x2_run: Any) -> None:
    _, rows = x2_run(engine=_Shadowed(drift=True), arm=x2.X2_SV)

    [run] = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert run["shadow_aa"] == 1


def test_other_arms_rows_carry_no_shadow_field(x2_run: Any) -> None:
    _, rows = x2_run(engine=_Shadowed(), arm=x2.X2_C)

    assert not any("shadow_verify" in r or "shadow_aa" in r for r in rows)
