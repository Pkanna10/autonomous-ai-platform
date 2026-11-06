"""Offline guards of S2's combine record in the ideas-x2 suite (emergence
round 1): the X2-S arm, its per-keep rows and the report section.

Not ``live``: these spend nothing. X2-S is X2-0's settings plus
``IDEAS_COUNT_CONTRACT=record`` (S1's unit counts, which part 3's
eligibility reads) and ``SITE_STACKS=on``: no request or prompt changes and
part 3 trials none, so its cap and minutes are X2-0's; off the plan until
the Lead and the owner put it there. A run whose combination holds keep
records writes, per kept hypothesis, ``combine`` (delivered, the reason,
the blocker and the duplicate as hypothesis ids, the component, the best
subset, the order gain, part 3's eligibility) and the run row its conflict
pairs; a run without (every other arm) writes neither, and the report adds
its section only when a row has a record. Fakes: ``test_ideas_x2_guards``'s
``_Engine`` and hand-built state stand for the whole engine run.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import KeepRecord
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import test_ideas_x2_guards as xg
from . import test_ideas_x2_report_guards as rg
from .conftest import SUITE_CAP_ENV

x2_run = xg.x2_run


def test_x2_s_is_x2_0_with_the_count_record_and_site_stacks_on() -> None:
    assert x2.X2_S.key == "X2-S"
    assert x2.X2_S.repos == ("more_itertools", "tomli", "mistune", "sqlparse")
    assert dict(x2.X2_S.update) == {**x2.SHARED, "IDEAS_COUNT_CONTRACT": "record",
                                    "SITE_STACKS": "on"}  # fmt: skip
    assert x2.X2_S in x2.EVERY_ARM and x2.X2_S not in x2.X2_ARMS
    assert not any(d.startswith("X2-S") for d in x2.dispatches())
    assert x2.arm_cap(x2.X2_S) == x2.arm_cap(x2.X2_0)
    assert x2.run_minutes(x2.arm_settings(x2.X2_S)) == x2.run_minutes(x2.arm_settings(x2.X2_0))  # fmt: skip
    plan = x2.x2_plan({x2.DISPATCH_ENV: "X2-S:sqlparse,tomli", SUITE_CAP_ENV: "19"})
    assert [(a.key, r.name) for a, r in plan.runs] == [("X2-S", "tomli"), ("X2-S", "sqlparse")]  # fmt: skip
    assert xr.ARMS[-2:] == ("X2-S", "X2-C")


class _Stacked(xg._Engine):
    """The fake run with a combine record: the S1 keep delivered, the leap
    keep (its whitespace-variant duplicate) blocked by it and, as the engine
    records a duplicate, never offered for a reconcile; a conflict pair
    between them; X2-S counts, so the
    loop has a clone path (no trial is measured, so nothing is read)."""

    def start(self, *args: Any, **kwargs: Any) -> Any:
        loop = super().start(*args, **kwargs)
        loop.user.path = Path("/nonexistent")
        return loop

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str, record: Any) -> Any:  # fmt: skip
        state: dict[str, Any] = dict(xg._state().state)
        s1, _, leap, _ = state["trials"]
        keeps = (
            KeepRecord(trial_id=s1.id, verdict_id="v1", gain=0.12, component=0,
                       best_subset=True, delivered=True),
            KeepRecord(trial_id=leap.id, verdict_id="v2", gain=None, component=0,
                       best_subset=False, delivered=False, skip_reason="conflict",
                       blocked_by=s1.id, duplicate_of=s1.id),
        )  # fmt: skip
        state["combination"] = state["combination"].model_copy(
            update={"keeps": keeps, "conflicts": ((s1.id, leap.id),)}
        )
        record(SimpleNamespace(guard="ok"), EngineRunResult("run", "done", cast(Any, state), None))  # fmt: skip


def test_x2_s_rows_carry_each_keeps_combine_record(x2_run: Any) -> None:
    """
    GIVEN an X2-S run whose combine delivered the S1 keep and skipped the
        leap keep as a conflict blocked by it
    WHEN it is recorded
    THEN each kept row names its record by hypothesis id, a row with no
        record carries ``None``, and the run row carries the conflict pair
    """
    _, rows = x2_run(engine=_Stacked(), arm=x2.X2_S)

    ideas = {r["title"]: r for r in xg._rows(rows, x2.IDEA_EXPERIMENT)}
    s1 = next(r for t, r in ideas.items() if t.startswith("S1 idea"))
    leap = ideas["leap idea"]
    assert s1["combine"] == {
        "delivered": True, "skip_reason": None, "blocked_by": None, "duplicate_of": None,
        "superseded_by": None, "component": 0, "best_subset": True, "gain_pct": 12.0,
        "reconcile": None,
    }  # fmt: skip
    assert leap["combine"]["blocked_by"] == leap["combine"]["duplicate_of"] == s1["hypothesis_id"]  # fmt: skip
    assert leap["combine"]["gain_pct"] is leap["combine"]["reconcile"] is None
    assert ideas["lens idea"]["combine"] is None
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert run["conflicts"] == [[s1["hypothesis_id"], leap["hypothesis_id"]]]


def test_other_arms_rows_carry_no_combine_record(x2_run: Any) -> None:
    _, rows = x2_run()

    assert not any("combine" in r or "conflicts" in r for r in rows)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def _rec(delivered: bool, component: int, best: bool, gain: float | None,
         reason: str | None = None, **more: object) -> dict[str, object]:  # fmt: skip
    return {"delivered": delivered, "skip_reason": reason, "blocked_by": None,
            "duplicate_of": None, "superseded_by": None, "component": component,
            "best_subset": best, "gain_pct": gain, "reconcile": None, **more}  # fmt: skip


def _stacked(rows: list[rg.Row], recs: dict[str, dict[str, object]]) -> list[rg.Row]:
    return [{**r, "combine": recs.get(str(r["hypothesis_id"]))}
            if r["experiment"] == x2.IDEA_EXPERIMENT else r for r in rows]  # fmt: skip


def test_the_report_reads_the_combine_record_by_run(tmp_path: Path) -> None:
    """
    GIVEN an X2-S tomli run of 4 kept ideas: two conflicting (component 0)
        where the 9-point keep was delivered and is the best subset, the
        5-point one skipped as a conflict and eligible; a duplicate of a
        delivered keep; and one lost with the combination's reason missing
    WHEN the report renders
    THEN a combine section counts kept (duplicates once), delivered, not
        delivered and those with no reason per run, then the undelivered
        by reason, and each run's conflict components against their
        max-sum subset in standalone points
    """
    base = rg._rows("X2-0", "tomli", [(2, ["obvious"])])
    arm = _stacked(rg._rows("X2-S", "tomli", [(4, ["leap", "far", "obvious", "eliminate"])]), {
        "tomli-1-0": _rec(True, 0, True, 9.0),
        "tomli-1-1": _rec(False, 0, False, 5.0, "conflict", blocked_by="tomli-1-0",
                          reconcile="eligible"),
        "tomli-1-2": _rec(False, 1, True, 3.0, "nothing left to apply",
                          duplicate_of="tomli-1-3"),
        "tomli-1-3": _rec(False, 1, True, 3.5)})  # fmt: skip

    text = rg._text(rg._write(tmp_path / "x.jsonl", base, arm))

    section = text[text.index("## 8 Combine record (S2)") :]
    assert "| X2-S | tomli | 4 | 3 | 4 | 1 | 3 | 1 | 1 |" in section
    assert "| X2-S | tomli | conflict | 1 |" in section
    assert "| X2-S | tomli | nothing left to apply | 1 |" in section
    assert "| X2-S | tomli | (no reason) | 1 |" in section
    assert "| X2-S | tomli | 1 | 1 | 9.0 | 9.0 |" in section
    assert "X2-0 |" not in section


def test_without_a_record_the_report_has_no_combine_section(tmp_path: Path) -> None:
    base = rg._rows("X2-0", "tomli", [(2, ["obvious"])])

    assert "Combine record" not in rg._text(rg._write(tmp_path / "x.jsonl", base))


def test_a_malformed_combine_record_is_refused(tmp_path: Path) -> None:
    arm = _stacked(rg._rows("X2-S", "tomli", [(1, ["leap"])]), {
        "tomli-1-0": {"delivered": "yes"}})  # fmt: skip

    with pytest.raises(ValueError, match="combine"):
        rg._text(rg._write(tmp_path / "x.jsonl", arm))
