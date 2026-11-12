"""O61 addendum item 4: the combine's fates in the X2 rows (U-fate, Unit B).

Record-only, harness only: ``X2Recorder.record`` adds to each hypothesis row
``combine_fate`` (``ideas_x2.combine_fates``: what the run's combine did with
that kept change) and to the run row the combine's own record
(``fallback_trial_id``, ``combine_summary``, ``skipped``,
``baseline_floor_pct``, and ``conflicts`` on every run, ``None`` where no
dry merge ran). The engine, the
combine and the judges are untouched, so no request changes.

Fakes: the fates are read off ``Combination``s the real ``combine_kept``
builds from a scripted ``FakeCombiner`` and one stub judge (it passes the
tip iff the B rows hold a ``good`` row), so every greedy, fallback and skip
path is the combine node's own; the rows come from
``test_ideas_x2_guards``'s ``_Engine`` and hand-built state (the whole
engine run). The report pages read the new rows as they read the old.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import (
    Baseline,
    Combination,
    CombineSkip,
    JudgeOutcome,
    JudgeResult,
    KeepRecord,
    Measurement,
    NoiseCalibration,
    Objective,
    Project,
    RunStats,
    Trial,
    VerdictOutcome,
)
from autonomous_ai_agents.execution.combine import (
    CONFLICT,
    NOT_A_CHILD,
    NOT_A_COMMIT,
    NOTHING_LEFT,
)
from autonomous_ai_agents.execution.fakes import FakeCombiner
from autonomous_ai_agents.execution.protocols import CombineMeasured, KeptChange
from autonomous_ai_agents.orchestrator.combine_node import (
    CombineRules,
    CombineTarget,
    combine_kept,
)
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import ideas_x2_tokens as xt
from . import test_ideas_x2_guards as xg

x2_run = xg.x2_run
Json = dict[str, Any]
BASE, TIP = "b" * 40, "c" * 40
PATH = "tomli/_parser.py"


# ---------------------------------------------------------------------------
# The fates, read off the real combine node's records
# ---------------------------------------------------------------------------


class _Good:
    """The one stub judge: the tip passes iff its B rows hold a ``good`` row."""

    name = "speed"

    def applies_to(self, objective: Objective) -> bool:
        return True

    def evaluate(self, baseline: Baseline, trial: Trial) -> JudgeResult:
        good = any(m.metric == "good" for m in trial.measurements)
        return JudgeResult(judge=self.name, metric="wall",
                           outcome=JudgeOutcome.passed if good else JudgeOutcome.failed,
                           gain=0.1 if good else -0.1, reason="stub")  # fmt: skip


def _row(metric: str) -> Measurement:
    return Measurement(workload_id="w", metric=metric,
                       stats=RunStats.from_samples((1.0,), unit="s"), samples=(1.0,))  # fmt: skip


def _measured(applied: Sequence[str], skipped: Sequence[CombineSkip] = (), *,
              holds: bool = True) -> CombineMeasured:  # fmt: skip
    rows = (_row("good" if holds else "bad"),)
    return CombineMeasured(TIP, tuple(applied), tuple(skipped), rows, rows)


def _change(name: str, gain: float) -> KeptChange:
    return KeptChange(name, f"h-{name}", f"v-{name}", f"{ord(name):040x}", 0.5, gain)


RULES = CombineRules(judges=(_Good(),), objectives=(), guardrails=(), primary=None,
                     completeness=lambda rows: ())  # fmt: skip
TARGET = CombineTarget(run_id="r", project=Project(name="p", root_path="/p"),
                       base_commit=BASE, workloads=(), branch="engine/run-r", round=1)  # fmt: skip


def _combine(changes: Sequence[KeptChange], *script: CombineMeasured) -> Combination:
    combiner = FakeCombiner(script)
    comb = combine_kept(combiner, changes, RULES, TARGET).combination
    assert len(combiner.calls) == len(script)  # the scripted path was the node's
    return comb


def _fates(comb: Combination, changes: Sequence[KeptChange]) -> Json:
    return x2.combine_fates(comb, [c.trial_id for c in changes])


def _stages(comb: Combination) -> list[tuple[str, str]]:
    return [(str(s["trial_id"]), str(s["stage"])) for s in x2._skipped(comb, {})]


def _f(fate: str, paths: Sequence[str] = ()) -> Json:
    return {"fate": fate, "paths": list(paths)}


def _fb(fate: str, greedy: CombineSkip | None = None,
        own: CombineSkip | None = None) -> Json:  # fmt: skip
    """A fallback's fate: its own skip's reason and paths, its greedy skip."""
    return {"fate": fate, "reason": None if own is None else own.reason,
            "paths": [] if own is None else list(own.paths),
            "greedy": None if greedy is None
            else {"reason": greedy.reason, "paths": list(greedy.paths)}}  # fmt: skip


A, B, C = _change("a", 0.05), _change("b", 0.09), _change("c", 0.02)
B_CONFLICT = CombineSkip(trial_id="b", reason=CONFLICT, paths=(PATH,))


def test_a_held_greedy_combine_names_each_applied_change_and_each_skip() -> None:
    """
    GIVEN three kept changes: a applied, b skipped as a conflict in one
        file, c with nothing left to apply, and the tip holds
    WHEN the fates are read
    THEN a is applied, b and c carry the combine's own skip reasons, b its
        conflict paths; both skips are the greedy merge's
    """
    held = _measured(
        ["a"], [B_CONFLICT, CombineSkip(trial_id="c", reason=NOTHING_LEFT)]
    )
    comb = _combine([A, B, C], held)

    assert _fates(comb, [A, B, C]) == {
        "a": _f(x2.APPLIED), "b": _f(CONFLICT, [PATH]), "c": _f(NOTHING_LEFT),
    }  # fmt: skip
    assert _stages(comb) == [("b", x2.GREEDY), ("c", x2.GREEDY)]


def test_a_fallback_that_holds_drops_the_rest_of_the_failed_combination() -> None:
    """
    GIVEN a and b applied, c a conflict, the tip not holding, and the
        fallback (b, the largest gain) holding alone
    WHEN the fates are read
    THEN b is the fallback applied (greedy: applied, so none), a dropped at
        the re-test, c a conflict
    """
    c_conflict = CombineSkip(trial_id="c", reason=CONFLICT, paths=(PATH,))
    comb = _combine([A, B, C], _measured(["a", "b"], [c_conflict], holds=False),
                    _measured(["b"]))  # fmt: skip

    assert _fates(comb, [A, B, C]) == {
        "a": _f(x2.DROPPED_AT_RETEST), "b": _fb(x2.FALLBACK_APPLIED),
        "c": _f(CONFLICT, [PATH]),
    }  # fmt: skip
    assert _stages(comb) == [("c", x2.GREEDY)]


def test_a_fallback_that_does_not_hold_alone_failed() -> None:
    comb = _combine([A, B], _measured(["a", "b"], holds=False),
                    _measured(["b"], holds=False))  # fmt: skip

    assert _fates(comb, [A, B]) == {
        "a": _f(x2.DROPPED_AT_RETEST), "b": _fb(x2.FALLBACK_FAILED),
    }  # fmt: skip


def test_a_fallback_its_own_re_test_skipped_keeps_both_skips() -> None:
    """
    GIVEN a applied alone and failing, b skipped as not a commit, so the
        fallback is b, which its own re-test skips again
    WHEN the fates are read
    THEN b is the fallback skipped with that skip's reason, its greedy skip
        beside it; a dropped at the re-test; the run row's second skip is
        the fallback's
    """
    first = CombineSkip(trial_id="b", reason=NOT_A_COMMIT)
    again = CombineSkip(trial_id="b", reason=NOT_A_COMMIT)
    comb = _combine(
        [A, B], _measured(["a"], [first], holds=False), _measured([], [again])
    )

    assert _fates(comb, [A, B]) == {
        "a": _f(x2.DROPPED_AT_RETEST), "b": _fb(x2.FALLBACK_SKIPPED, first, again),
    }  # fmt: skip
    assert _stages(comb) == [("b", x2.GREEDY), ("b", x2.FALLBACK)]


def test_a_conflicting_change_can_be_the_fallback_that_holds() -> None:
    comb = _combine(
        [A, B], _measured(["a"], [B_CONFLICT], holds=False), _measured(["b"])
    )

    assert _fates(comb, [A, B]) == {
        "a": _f(x2.DROPPED_AT_RETEST), "b": _fb(x2.FALLBACK_APPLIED, B_CONFLICT),
    }  # fmt: skip
    assert _stages(comb) == [("b", x2.GREEDY)]


def test_a_lone_change_that_fails_has_no_fallback_and_is_dropped() -> None:
    comb = _combine([A], _measured(["a"], holds=False))

    assert _fates(comb, [A]) == {"a": _f(x2.DROPPED_AT_RETEST)}


def test_nothing_applied_falls_back_to_the_best_change() -> None:
    """Every change unfit: nothing applied never holds, so the fallback
    re-tests the largest gain, which is skipped again."""
    skips = [CombineSkip(trial_id="a", reason=NOT_A_CHILD),
             CombineSkip(trial_id="b", reason=NOT_A_CHILD)]  # fmt: skip
    again = CombineSkip(trial_id="b", reason=NOT_A_CHILD)
    comb = _combine([A, B], _measured([], skips), _measured([], [again]))

    assert _fates(comb, [A, B]) == {
        "a": _f(NOT_A_CHILD), "b": _fb(x2.FALLBACK_SKIPPED, skips[1], again),
    }  # fmt: skip
    assert _stages(comb) == [("a", x2.GREEDY), ("b", x2.GREEDY), ("b", x2.FALLBACK)]


def test_the_fate_values_are_five_names_and_the_combine_s_skip_reasons() -> None:
    assert (x2.APPLIED, x2.DROPPED_AT_RETEST, x2.FALLBACK_APPLIED, x2.FALLBACK_FAILED,
            x2.FALLBACK_SKIPPED) == ("applied", "dropped_at_retest", "fallback_applied",
                                     "fallback_failed", "fallback_skipped")  # fmt: skip
    assert (x2.GREEDY, x2.FALLBACK) == ("greedy", "fallback")
    assert (CONFLICT, NOTHING_LEFT, NOT_A_COMMIT, NOT_A_CHILD) == (
        "conflict", "nothing left to apply", "not a commit",
        "not a single-parent child of the base commit")  # fmt: skip


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


class _Changed(xg._Engine):
    """``_Engine`` whose state ``change`` edits before it is recorded."""

    def __init__(self, change: Callable[[dict[str, Any]], None]) -> None:
        super().__init__()
        self.change = change

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        result = xg._state()
        self.change(cast(dict[str, Any], result.state))
        record(SimpleNamespace(guard="ok"), result)


def _ideas(rows: list[Json]) -> dict[str, Json]:
    return {r["title"].split(" ")[0]: r for r in xg._rows(rows, x2.IDEA_EXPERIMENT)}


def _run(rows: list[Json]) -> Json:
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    return run


def _trial(st: dict[str, Any], title: str) -> str:
    (h,) = [h for h in st["hypotheses"] if h.title.startswith(title)]
    return str(next(t.id for t in st["trials"] if t.hypothesis_id == h.id))


def test_every_row_records_the_held_combine(x2_run: Any) -> None:
    """
    GIVEN the fake X2-0 run: S1 and leap kept and both applied, the lens
        idea inconclusive, the compound rejected, a pool idea, a calibrated
        3 % baseline floor
    WHEN it is recorded
    THEN each kept row is ``applied``, every other row ``None``, and the run
        row the fallback (none), the summary, no skip, the floor, and
        ``None`` conflicts (``SITE_STACKS`` off: no dry merge ran)
    """

    def floor(st: dict[str, Any]) -> None:
        st["baseline"] = Baseline(calibration=NoiseCalibration(blocks=3, floor=0.03))

    _, rows = x2_run(_Changed(floor))

    ideas = _ideas(rows)
    assert {t: r["combine_fate"] for t, r in ideas.items()} == {
        "S1": {"fate": x2.APPLIED, "paths": []}, "leap": {"fate": x2.APPLIED, "paths": []},
        "lens": None, "compound": None, "pool": None,
    }  # fmt: skip
    run = _run(rows)
    assert {k: run[k] for k in ("fallback_trial_id", "combine_summary", "skipped",
                                "baseline_floor_pct", "conflicts")} == {
        "fallback_trial_id": None, "combine_summary": "greedy held", "skipped": [],
        "baseline_floor_pct": pytest.approx(3.0), "conflicts": None,
    }  # fmt: skip


def test_a_fallback_and_a_skip_are_recorded_by_trial_and_hypothesis(
    x2_run: Any,
) -> None:
    """
    GIVEN S1 skipped as a conflict in one file (blocked by the leap keep), the
        greedy tip failing and the leap keep, the fallback, holding alone
    WHEN it is recorded
    THEN S1's row is the conflict with its paths, the leap's the fallback
        applied (its greedy merge applied it: no greedy skip); the run row
        names the fallback trial, the summary (redacted), and the skip with
        its trial, hypothesis, reason, paths, blocker and stage; no
        baseline, no floor
    """
    seen: dict[str, str] = {}

    def fallback(st: dict[str, Any]) -> None:
        s1, leap = _trial(st, "S1"), _trial(st, "leap")
        seen.update(
            s1=s1,
            leap=leap,
            h=next(t.hypothesis_id for t in st["trials"] if t.id == s1),
        )
        skip = CombineSkip(trial_id=s1, reason=CONFLICT, paths=(PATH,), blocked_by=leap)
        st["combination"] = st["combination"].model_copy(update={
            "applied_trial_ids": (leap,), "skipped": (skip,), "fallback_trial_id": leap,
            "summary": f"fallback held {xg.SECRET}"})  # fmt: skip

    _, rows = x2_run(_Changed(fallback))

    ideas = _ideas(rows)
    assert ideas["S1"]["combine_fate"] == {"fate": CONFLICT, "paths": [PATH]}
    assert ideas["leap"]["combine_fate"] == _fb(x2.FALLBACK_APPLIED)
    run = _run(rows)
    assert run["fallback_trial_id"] == seen["leap"]
    assert run["combine_summary"] == "fallback held [redacted]"
    assert run["skipped"] == [{"trial_id": seen["s1"], "hypothesis_id": seen["h"],
                               "reason": CONFLICT, "paths": [PATH],
                               "blocked_by": seen["leap"], "stage": x2.GREEDY}]  # fmt: skip
    assert run["baseline_floor_pct"] is None
    assert xg.SECRET not in json.dumps(rows)


def test_a_dry_merge_with_no_conflict_records_an_empty_list(x2_run: Any) -> None:
    """Keep records (``SITE_STACKS`` on or record): the dry merge ran, so no
    conflicting pair is a measured empty list, not ``None``."""

    def probed(st: dict[str, Any]) -> None:
        keep = KeepRecord(trial_id=_trial(st, "S1"), verdict_id="v", gain=0.1,
                          component=0, best_subset=True, delivered=True)  # fmt: skip
        st["combination"] = st["combination"].model_copy(update={"keeps": (keep,)})

    _, rows = x2_run(_Changed(probed))

    assert _run(rows)["conflicts"] == []


def test_a_keep_the_run_combine_was_not_offered_has_no_fate(x2_run: Any) -> None:
    """A keep whose output changed goes to the review set (``nodes``), never
    the run combine: its row carries ``None``, the S1 keep still its fate."""

    def changed(st: dict[str, Any]) -> None:
        st["verdicts"] = [v.model_copy(update={"judge_results": (*v.judge_results,
                          JudgeResult(judge="equivalence", outcome=JudgeOutcome.passed,
                                      reason="r", output_changed=True))})
                          if v.trial_id == _trial(st, "leap") else v for v in st["verdicts"]]  # fmt: skip

    _, rows = x2_run(_Changed(changed))

    ideas = _ideas(rows)
    assert (ideas["S1"]["combine_fate"], ideas["leap"]["combine_fate"]) == (
        {"fate": x2.APPLIED, "paths": []}, None)  # fmt: skip


def test_a_run_with_no_combine_records_no_fate_and_an_empty_record(x2_run: Any) -> None:
    def none(st: dict[str, Any]) -> None:
        st["verdicts"] = [v.model_copy(update={"outcome": VerdictOutcome.reject})
                          for v in st["verdicts"]]  # fmt: skip
        st["combination"], st["delivery"] = None, None

    _, rows = x2_run(_Changed(none))

    assert all(r["combine_fate"] is None for r in xg._rows(rows, x2.IDEA_EXPERIMENT))
    run = _run(rows)
    assert {k: run[k] for k in ("fallback_trial_id", "combine_summary", "skipped",
                                "baseline_floor_pct", "conflicts")} == {
        "fallback_trial_id": None, "combine_summary": None, "skipped": [],
        "baseline_floor_pct": None, "conflicts": None,
    }  # fmt: skip


def test_a_breached_run_writes_the_empty_record(x2_run: Any, tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="repository changed"):
        x2_run(xg._Engine(breach=True))
    lines = (tmp_path / "x2.jsonl").read_text(encoding="utf-8").splitlines()
    (run,) = [json.loads(x) for x in lines]
    assert {k: run[k] for k in ("fallback_trial_id", "combine_summary", "skipped",
                                "baseline_floor_pct", "conflicts")} == {
        "fallback_trial_id": None, "combine_summary": None, "skipped": [],
        "baseline_floor_pct": None, "conflicts": None,
    }  # fmt: skip


# ---------------------------------------------------------------------------
# The report reads the new rows as it reads the old
# ---------------------------------------------------------------------------

NEW_IDEA = ("combine_fate",)
NEW_RUN = ("fallback_trial_id", "combine_summary", "skipped", "baseline_floor_pct",
           "conflicts")  # fmt: skip


def _pages(path: Path) -> tuple[str, ...]:
    """Every page of ``path``, its input digest (``load``'s file list) masked."""
    found, digest = xr.draws([path]), hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    pages = (xr.render(xr.load([path])), xr.render_variance(found), xr.render_rounds(found),
             xt.render_tokens(found), xr.render_frameworks(xr.raw_rows([path])))  # fmt: skip
    assert digest in pages[0]
    return tuple(page.replace(digest, "<digest>") for page in pages)


def test_every_report_page_reads_old_and_new_rows_alike(
    x2_run: Any, tmp_path: Path
) -> None:
    """
    GIVEN one recorded run's rows, and the same rows without this unit's
        fields (the archived shape)
    WHEN every page renders each
    THEN the pages are the same text, but for each input's own digest
    """
    _, rows = x2_run()
    assert all(k in r for r in xg._rows(rows, x2.IDEA_EXPERIMENT) for k in NEW_IDEA)
    assert all(k in _run(rows) for k in NEW_RUN)
    gone = {*NEW_IDEA, *NEW_RUN}
    old = [{k: v for k, v in r.items() if k not in gone} for r in rows]
    paths = []
    for name, body in (("new", rows), ("old", old)):
        (tmp_path / name).mkdir()
        path = tmp_path / name / "x2.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in body), encoding="utf-8")
        paths.append(path)

    assert _pages(paths[0]) == _pages(paths[1])
