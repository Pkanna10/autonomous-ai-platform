"""Offline guards of the combine-order replay (O65 item 2; ``order_cases.py``,
``combine_order.py``).

What is checked here, with no network:

- the census: every archived held combine with two or more keeps (59 runs on
  four libraries), every other row listed with why, none lacking data;
- integrity of every case's files on the committed archive, and its failures
  on a scratch archive;
- the readings: which side each choice kept of a conflicting pair, which side
  the re-measured singles favour, which choice the measurement prefers;
- a whole library on a fake measurer and a fake clock (the look order a, b,
  a, b, then the singles; rows; tables; timings), and every failure path;
- the real measurer on a local repository in the ``required`` sandbox: the
  dry merge, ``plan_delivery`` by gain, the greedy merge of each choice, and
  the combine node's re-test of each tip and single;
- the batches, the minutes and the ci.yml row.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import pytest
from e2e.conftest import Isolation, UserRepo, git

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.execution.combine import DryMerge
from autonomous_ai_agents.execution.protocols import KeptChange
from autonomous_ai_agents.orchestrator.combine_node import DeliveryPlan, plan_delivery

from . import combine_order as co
from . import ideas_x2
from . import order_cases as oc
from . import order_readings as rd
from . import replay_archive as ra
from . import replay_engine as rx
from .conftest import TESTS_DIR, LiveRun, make_repo
from .discovery_io import ResultsSink
from .oss import OssRepo
from .test_combine_replay_guards import Clock, _require_sandbox, _retest
from .test_corpus_guards import (
    EXPERIMENT_MINUTES,
    _ci_block,
    _dispatch,
    _run_script,
)

T1, T2, T3 = (
    f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-00000000000{n}" for n in (1, 2, 3)
)
DELIVERED_TIP = "d" * 40  # the fake's delivered commit


def _tip(ids: Sequence[str]) -> str:
    """The fake's tip of a merge: a 40-character stand-in per applied set."""
    return hashlib.sha1("+".join(ids).encode()).hexdigest()  # noqa: S324 - a name


# ---------------------------------------------------------------------------
# The census on the committed archive
# ---------------------------------------------------------------------------


def test_the_census_is_every_held_combine_with_two_or_more_keeps() -> None:
    runs, skipped = oc.census()
    assert (runs, skipped) == (oc.RUNS, oc.SKIPPED)
    assert len(runs) == 59 and len({r.id for r in runs}) == 59
    per = {lib: sum(r.library == lib for r in runs) for lib in oc.LOOK_S}
    assert per == {"tomli": 14, "mistune": 14, "sqlparse": 16, "markdown": 15}
    assert {r.case.arm for r in runs} == {"X2-0", "X2-D", "X2-F", "X2-L", "X2-P"}
    for run in runs:
        assert len(run.keeps) >= 2 and set(run.applied) <= {
            k.trial_id for k in run.keeps
        }
        assert all(-1 < k.gain < 1 for k in run.keeps)
    assert [s for s in skipped if s.data] == []  # nothing in scope lacks (b)'s data
    reasons = sorted((s.reason, s.id) for s in skipped)
    assert [r for r, _ in reasons].count(oc.OUT_OF_SCOPE["X2-SV"]) == 3
    assert ("the combine did not hold", "X2-D-43145496896-mistune") in reasons
    assert [i for r, i in reasons if r == oc.NOT_HELD] == ["X2-D-43145496896-mistune"]
    assert [i for r, i in reasons if r == oc.FEW_KEEPS] == [
        "X2-D-43159144063-tomli", "X2-L-43154396382-mistune", "X2-P-43100257776-tomli",
    ]  # fmt: skip
    assert len(skipped) == 7
    failed = next(s for s in skipped if s.id == "X2-D-43145496896-mistune")
    assert (failed.library, failed.keeps) == ("mistune", 5)
    # F3: the deliveries whose greediness the archive cannot prove
    flagged = {r.id for r in runs if r.greedy == oc.NOT_PROVABLE}
    assert flagged == {"X2-L-43151990527-tomli", "X2-P-43107418692-tomli",
                       "X2-D-43159154661-mistune"}  # the last: NotGreedyError  # fmt: skip
    basis = {r.id: r.greedy_reason for r in runs}
    assert basis["X2-0-43181006070-tomli"] == oc.BY_ROW
    assert basis["X2-D-43085626757-markdown"] == oc.NOT_FALLBACK
    assert basis["X2-F-43100253551-tomli"] == oc.ALL_APPLIED
    o62 = next(r for r in runs if r.id == "X2-D-43093773731-tomli")
    assert o62.applied == ("593eb066-67ec-5df3-b776-470dfb3586b4",
                           "c56d3403-cecc-5b3b-b70c-48e11a9e5cec")  # fmt: skip
    assert o62.left_out and len(o62.keeps) == 4
    assert round(o62.archived_gain_pct or 0, 2) == 18.75


def test_the_exclusion_line_counts_only_failed_combines_of_two_or_more_keeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The census lists a row with fewer than two keeps as such before its
    hold (N1), so every "did not hold" row has two or more; the line keeps
    its own filter, so a one-keep failure is never counted as excluded."""
    assert all(s.keeps >= 2 for s in oc.SKIPPED if s.reason == oc.NOT_HELD)
    one = oc.Skipped("X2-D-1-sqlparse", oc.NOT_HELD, False, "sqlparse", 1)
    monkeypatch.setattr(oc, "SKIPPED", (*oc.SKIPPED, one))
    assert oc.exclusion_line(("sqlparse",), 16, []).endswith("none excluded.")


def test_the_exclusion_line_counts_from_the_census() -> None:
    """F2: what the measured runs are a part of, and what was left out."""
    every = tuple(oc.BATCHES["1"] + oc.BATCHES["2"] + oc.BATCHES["3"])
    line = oc.exclusion_line(every, 58, ["X2-D-43159154661-mistune"])
    assert line == (
        "58 measured of 60 held-or-failed runs with two or more keeps (X2-SV aside);"
        " 2 excluded because today's set failed its re-test (X2-D-43159154661-mistune,"
        " fallback delivered; X2-D-43145496896-mistune, nothing delivered). The"
        " gain-ordered choice cannot be measured on them; the exclusion does not"
        " favour it."
    )
    assert oc.exclusion_line(("sqlparse",), 16, []) == (
        "16 measured of 16 held-or-failed runs with two or more keeps (X2-SV aside);"
        " none excluded."
    )


def test_every_run_passes_integrity_on_the_committed_archive() -> None:
    for run in oc.RUNS:
        found = oc.load_run(run)
        assert found.delivered.name == "delivered.patch" and len(found.diffs) == len(
            run.keeps
        )
        for keep, path in found.diffs:
            assert path.name == f"trial-{keep.trial_id}.diff"


# ---------------------------------------------------------------------------
# A scratch archive: the data gaps and the integrity failures
# ---------------------------------------------------------------------------

BASE = "a" * 40


@dataclass
class Archive:
    """One run file of one dispatch, its patch directory and its rows."""

    root: Path
    base: str = BASE
    dispatch: str = "123456789"
    library: str = "tomli"
    texts: dict[str, str] = field(default_factory=dict)  # trial -> diff text

    @property
    def folder(self) -> Path:
        return (
            self.root
            / "live"
            / f"patches-X2-D-{self.dispatch}"
            / f"X2-D-{self.library}"
        )

    def write(self, *, delivered: str = "d\n", applied: Sequence[str] = (T1, T3),
              gains: Mapping[str, float | None] | None = None,
              row: Mapping[str, object] | None = None, extra: Sequence[object] = ()) -> None:  # fmt: skip
        texts = self.texts or {T1: "one\n", T2: "two\n", T3: "three\n"}
        gains = {T1: 5.0, T2: 9.0, T3: 3.0} if gains is None else gains
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / "delivered.patch").write_text(delivered)
        sha = {t: hashlib.sha256(x.encode()).hexdigest() for t, x in texts.items()}
        for trial, text in texts.items():
            (self.folder / f"trial-{trial}.diff").write_text(text)
        run_dir = f"live-patches/X2-D-{self.library}"
        entries = [{"trial_id": t, "hypothesis_id": f"h-{t}", "file": f"{run_dir}/trial-{t}.diff",
                    "sha256": sha[t], "base_commit": self.base, "truncated": False,
                    "error": None, "applied": t in applied} for t in texts]  # fmt: skip
        run = {"experiment": "ideas-x2-run", "repo": self.library, "arm": "X2-D",
               "dispatch": f"X2-D:{self.library}", "base_commit": self.base, "holds": True,
               "kept": len(texts), "gain_pct": 20.0, "floor_pct": 2.0, "kept_diffs": entries,
               "delivered_patch": {"file": f"{run_dir}/delivered.patch",
                                   "sha256": hashlib.sha256(delivered.encode()).hexdigest(),
                                   "base_commit": self.base, "truncated": False,
                                   "error": None, "applied_trial_ids": list(applied)},
               **(row or {})}  # fmt: skip
        hyps = [{"experiment": "ideas-x2-hypothesis", "repo": self.library,
                 "hypothesis_id": f"h-{t}", "gain_pct": g} for t, g in gains.items()]  # fmt: skip
        lines = [json.dumps(x) for x in (*hyps, run, *extra)]
        path = self.root / "live" / f"ideas-x2-X2-D-{self.dispatch}.jsonl"
        path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    return Archive(Path(os.path.realpath(tmp_path)) / "archive")


@pytest.mark.parametrize(
    ("change", "greedy", "reason"),
    [
        ({}, "proven", "SEVERAL"),  # T1 and T3 delivered
        ({"applied": (T1, T2, T3)}, "proven", "ALL_APPLIED"),
        ({"applied": (T3,)}, "proven", "NOT_FALLBACK"),  # the weakest of three
        ({"applied": (T2,)}, "not provable", "ONE_OF_TWO"),  # the best single
        ({"applied": (T1,)}, "not provable", "ONE_OF_TWO"),  # the second best
        ({"applied": (T2,), "row": {"fallback_trial_id": None}}, "proven", "BY_ROW"),
    ],
)
def test_each_run_says_whether_its_delivery_is_provably_greedy(
    archive: Archive, change: dict[str, object], greedy: str, reason: str
) -> None:
    """F3: a fallback delivers one change, the best single by recorded gain
    (the second best when the failed greedy set was the best alone)."""
    archive.write(**change)  # type: ignore[arg-type]
    (run,), _ = oc.census(archive.root)
    assert (run.greedy, run.greedy_reason) == (greedy, getattr(oc, reason))


def test_a_tie_on_gain_ranks_by_hypothesis_id_as_the_node_does(
    archive: Archive,
) -> None:
    """N2: three keeps of equal recorded gain, listed against id order: the
    node's key (gain, then hypothesis id) ranks h-1111 and h-2222 first, so
    the delivered T3 (h-3333) cannot be the fallback; the row's order would
    put T3 first."""
    archive.texts = {T3: "three\n", T2: "two\n", T1: "one\n"}
    archive.write(applied=(T3,), gains={T1: 5.0, T2: 5.0, T3: 5.0})
    (run,), _ = oc.census(archive.root)
    assert [k.trial_id for k in run.keeps] == [T3, T2, T1]
    assert (run.greedy, run.greedy_reason) == (oc.PROVEN, oc.NOT_FALLBACK)


def test_a_scratch_run_is_read_whole(archive: Archive) -> None:
    archive.write()
    (run,), skipped = oc.census(archive.root)
    assert skipped == ()
    assert run.id == "X2-D-123456789-tomli" and run.applied == (T1, T3)
    assert [(k.trial_id, k.gain) for k in run.keeps] == [
        (T1, 0.05),
        (T2, 0.09),
        (T3, 0.03),
    ]
    assert (
        run.keeps[0].patch == f"live/patches-X2-D-123456789/X2-D-tomli/trial-{T1}.diff"
    )
    assert (run.archived_gain_pct, run.archived_floor_pct, run.left_out) == (
        20.0,
        2.0,
        True,
    )
    loaded = oc.load_run(run, archive.root)
    assert loaded.delivered == archive.folder / "delivered.patch"
    assert [p.name for _, p in loaded.diffs] == [
        f"trial-{t}.diff" for t in (T1, T2, T3)
    ]
    archive.write(row={"gain_pct": None, "floor_pct": "x"})
    (bare,), _ = oc.census(archive.root)
    assert (bare.archived_gain_pct, bare.archived_floor_pct) == (None, None)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"row": {"kept": 4}}, "one entry per keep"),
        ({"row": {"kept_diffs": "none"}}, "one entry per keep"),
        ({"gains": {T1: 5.0, T2: None, T3: 3.0}}, "no recorded gain for keep 22222222"),
        ({"gains": {T1: 5.0, T2: True, T3: 3.0}}, "no recorded gain for keep 22222222"),
        ({"applied": ()}, "no delivered patch"),
        ({"row": {"delivered_patch": None}}, "no delivered patch"),
        ({"applied": (T1, "x")}, "not a keep"),
        ({"applied": (T1, T1)}, "not a keep"),
        ({"row": {"fallback_trial_id": T1}}, "delivered by the fallback"),
    ],
)
def test_a_row_lacking_what_b_needs_is_listed_and_skipped(
    archive: Archive, change: dict[str, object], reason: str
) -> None:
    archive.write(**change)  # type: ignore[arg-type]
    runs, (skip,) = oc.census(archive.root)
    assert runs == () and skip.data and reason in skip.reason
    assert skip.id == "X2-D-123456789-tomli"


def test_a_keep_written_partly_is_listed(archive: Archive) -> None:
    archive.write()
    path = archive.root / "live" / "ideas-x2-X2-D-123456789.jsonl"
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    lines[-1]["kept_diffs"][1]["truncated"] = True
    path.write_text("\n".join(map(json.dumps, lines)) + "\n")
    (skip,) = oc.census(archive.root)[1]
    assert skip.data and skip.reason == "a kept diff was not written whole"


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"holds": False}, oc.NOT_HELD),
        ({"holds": None}, oc.NOT_HELD),
        ({"kept": 1}, oc.FEW_KEEPS),
        ({"kept": 0, "holds": None}, oc.FEW_KEEPS),  # N1: no keeps, no combine
        ({"kept": 1, "holds": False}, oc.FEW_KEEPS),
    ],
)
def test_rows_out_of_scope_are_listed_not_as_data_gaps(
    archive: Archive, row: dict[str, object], reason: str
) -> None:
    archive.write(row=row)
    (skip,) = oc.census(archive.root)[1]
    assert (skip.reason, skip.data) == (reason, False)


def test_a_file_off_the_naming_is_refused(archive: Archive) -> None:
    archive.write()
    (archive.root / "live" / "ideas-x2-bad.jsonl").write_text("")
    with pytest.raises(ra.IntegrityError, match="not an ideas-x2 run file name"):
        oc.census(archive.root)


def test_integrity_failures_of_a_run_are_raised(archive: Archive) -> None:
    archive.write()
    (run,), _ = oc.census(archive.root)
    (archive.folder / f"trial-{T2}.diff").write_text("tampered\n")
    with pytest.raises(ra.IntegrityError, match="sha256"):
        oc.load_run(run, archive.root)
    archive.write()
    moved = replace(run, keeps=(replace(run.keeps[0], hypothesis_id="h-other"),))
    with pytest.raises(ra.IntegrityError, match="another hypothesis"):
        oc.load_run(moved, archive.root)
    lost = replace(run, keeps=(replace(run.keeps[0], patch=""),))
    with pytest.raises(ra.IntegrityError, match="declares no patch"):
        oc.load_run(lost, archive.root)
    wrong = replace(run, case=replace(run.case, base_commit="b" * 40))
    with pytest.raises(ra.IntegrityError, match="base_commit"):
        oc.load_run(wrong, archive.root)
    archive.write(row={"delivered_patch": {"file": "elsewhere/delivered.patch"}})
    assert oc.census(archive.root)[1][0].reason.startswith("no delivered patch")
    off = {"file": "elsewhere/delivered.patch", "applied_trial_ids": [T1, T3]}
    archive.write(row={"delivered_patch": off})  # not under live-patches/
    (outside,), _ = oc.census(archive.root)
    assert outside.case.patch is None
    with pytest.raises(ra.IntegrityError):
        oc.load_run(outside, archive.root)


# ---------------------------------------------------------------------------
# The readings
# ---------------------------------------------------------------------------


def test_a_pair_reads_each_choices_side_and_the_stronger_single_past_its_floor() -> (
    None
):
    pair = rd.Pair(T1, T2, a_kept=(T1,), b_kept=(T2,), gains=(0.10, 0.20),
                   floors=(0.03, 0.04))  # fmt: skip
    assert (pair.higher, pair.a_higher, pair.b_higher) == (T2, False, True)
    assert pair.decided and (pair.a_beyond, pair.b_beyond) == (False, True)
    near = replace(pair, gains=(0.17, 0.20))  # 3 points apart, floors up to 4
    assert (near.higher, near.decided, near.a_higher, near.a_beyond) == (
        T2,
        False,
        False,
        None,
    )
    flipped = replace(pair, gains=(0.30, 0.20))
    assert (flipped.higher, flipped.a_higher, flipped.b_higher) == (T1, True, False)
    assert replace(pair, gains=(0.2, 0.2)).higher is None  # a tie favours neither
    assert replace(pair, gains=(None, 0.2)).a_higher is None  # a single not measured
    assert not replace(pair, floors=(None, 0.04)).decided  # a floor unknown
    both, neither = replace(pair, a_kept=(T1, T2)), replace(pair, b_kept=())
    assert (both.a_higher, neither.b_higher, both.a_beyond) == (None, None, None)
    assert pair.row() == {
        "first": T1, "second": T2, "a_kept": [T1], "b_kept": [T2],
        "gains_pct": [10.0, 20.0], "floors_pct": [3.0, 4.0], "higher": T2,
        "decided": True, "a_higher": False, "b_higher": True, "a_beyond": False,
        "b_beyond": True,
    }  # fmt: skip


def _raw(gain: float | None, *, holds: bool = True, applied: int = 2, rows: bool = True,
         floor: float = 0.02) -> rx.RetestLook:  # fmt: skip
    return replace(_retest(gain, floor, holds), applied=applied, rows=rows)


def _look(name: str, gain: float | None, *, expected: int = 2, holds: bool = True,
          applied: int = 2, rows: bool = True, floor: float = 0.02,
          fallback: str | None = None, fb: rx.RetestLook | None = None) -> rd.TipLook:  # fmt: skip
    found = _raw(gain, holds=holds, applied=applied, rows=rows, floor=floor)
    return rd.TipLook(
        name, expected, found, 3.0, fallback, fb, None if fb is None else 1.5
    )


def _single(gain: float | None, *, rows: bool = True) -> rd.SingleLook:
    return rd.SingleLook(replace(_retest(gain, 0.02, True), rows=rows), 2.0)


def _prefers(result: rd.RunResult) -> str | None:
    """Read a property afresh (mypy would keep an earlier assert's narrowing)."""
    return result.prefers


def _complete(result: rd.RunResult) -> bool:
    return result.complete


def test_a_look_delivers_what_the_engine_would() -> None:
    """The set's gain if it holds; else the fallback single's if that holds;
    else 0. ``None`` when the set or the fallback did not measure."""
    held = _look("a1", 0.20)
    assert (held.delivered, held.set_gain, held.floor, held.complete) == (
        0.20,
        0.20,
        0.02,
        True,
    )
    saved = _look(
        "a1", 0.20, holds=False, fallback=T2, fb=_raw(0.15, applied=1, floor=0.05)
    )
    assert (saved.delivered, saved.set_gain, saved.floor, saved.complete) == (
        0.15,
        0.20,
        0.05,
        True,
    )
    lost = _look(
        "a1", 0.20, holds=False, fallback=T2, fb=_raw(0.15, holds=False, applied=1)
    )
    assert (lost.delivered, lost.set_gain) == (0.0, 0.20)
    alone = _look("a1", 0.20, holds=False)  # no other single to fall back on
    assert (alone.delivered, alone.complete) == (0.0, True)
    # F1: a re-test with no rows is a re-test that did not hold, as
    # combine_kept treats a RunFailure: it falls back, else delivers 0
    blank = _look("a1", 0.2, holds=False, fallback=T2,
                  fb=_raw(None, applied=1, rows=False, floor=0.09))  # fmt: skip
    assert blank.floor == 0.02  # N2: a fallback with no rows has no floor to read
    assert (blank.delivered, blank.complete, blank.fallback_no_rows) == (
        0.0,
        True,
        True,
    )
    assert not held.no_rows and not held.fallback_no_rows
    crashed = _look("a1", None, rows=False, fallback=T2,
                    fb=_raw(0.15, applied=1, floor=0.05))  # fmt: skip
    assert (crashed.no_rows, crashed.delivered, crashed.set_gain) == (True, 0.15, None)
    assert crashed.floor == 0.05 and crashed.complete
    nothing = _look("a1", None, rows=False)  # no rows, no other single
    assert (nothing.no_rows, nothing.delivered, nothing.floor) == (True, 0.0, None)
    unmerged = _look("a1", 0.2, holds=False, fallback=T2,
                     fb=_raw(None, applied=0, rows=False))  # fmt: skip
    assert (unmerged.delivered, unmerged.complete) == (None, False)  # not applied
    pending = _look("a1", 0.2, holds=False, fallback=T2)  # its look not taken
    assert (pending.delivered, pending.complete) == (None, False)
    skipped = _look("a1", 0.2, applied=1)  # the set was not merged whole
    assert (skipped.delivered, skipped.set_gain, skipped.floor) == (None, None, None)


def test_each_table_cell_names_what_delivered() -> None:
    fb = _raw(0.15, applied=1)
    assert co._cell(_look("a1", 0.20)) == "20.0"
    assert co._cell(_look("a1", 0.2, applied=1)) == "not measured"
    assert co._cell(_look("a1", None, rows=False)) == "0.0 (no rows)"
    assert co._cell(_look("a1", None, rows=False, fallback=T2, fb=fb)) == (
        "15.0 (no rows; fallback 22222222)"
    )
    lost = _raw(None, applied=1, rows=False)
    assert co._cell(_look("a1", 0.2, holds=False, fallback=T2, fb=lost)) == (
        "0.0 (fallback no rows)"
    )
    failed = _raw(0.1, holds=False, applied=1)
    assert co._cell(_look("a1", 0.2, holds=False, fallback=T2, fb=failed)) == (
        "0.0 (did not hold)"
    )
    assert co._cell(_look("a1", None, rows=False, fallback=T2, fb=failed)) == (
        "0.0 (no rows)"
    )


def test_the_preference_reads_the_delivered_gain_against_the_largest_look_floor() -> (
    None
):
    run = oc.RUNS[0]
    found = rd.RunResult(run)
    assert (found.prefers, found.clear, found.mean("a")) == (None, None, None)
    found.same = False
    found.looks = [_look("a1", 0.20), _look("b1", 0.25), _look("b2", 0.27),
                   _look("a2", 0.22)]  # fmt: skip
    assert found.mean("a") == pytest.approx(0.21)
    assert found.mean("b") == pytest.approx(0.26)
    assert (found.prefers, found.clear, found.look_floor) == ("b", True, 0.02)
    found.looks[1:3] = [_look("b1", 0.215, floor=0.06), _look("b2", 0.215)]
    assert (found.prefers, found.clear, found.look_floor) == ("b", False, 0.06)
    found.looks[1:3] = [_look("b1", 0.21), _look("b2", 0.21)]  # (a)'s mean
    assert found.prefers == "tie"
    # (b) does not hold and its fallback delivers less: (a) is preferred on
    # delivered gain although (b)'s raw set gain is larger
    fb = _raw(0.05, applied=1)
    found.looks[1:3] = [_look("b1", 0.30, holds=False, fallback=T2, fb=fb),
                        _look("b2", 0.30, holds=False, fallback=T2, fb=fb)]  # fmt: skip
    assert found.raw_mean("b") == pytest.approx(0.30)
    assert found.mean("b") == pytest.approx(0.05)
    assert (found.prefers, found.clear) == ("a", True)
    found.looks[0] = _look("a1", 0.2, applied=1)  # did not measure (a)'s tip
    assert found.measured("a") == [0.22] and found.complete is False
    found.looks = [_look("b1", 0.2, applied=1), _look("a1", 0.2)]  # not merged whole
    assert found.mean("b") is None and _prefers(found) is None
    found.looks = [_look("b1", 0.2, rows=False), _look("a1", 0.2)]  # no rows: 0
    assert found.mean("b") == 0.0 and _prefers(found) == "a"
    same = rd.RunResult(run, same=True, looks=[_look("a1", 0.2), _look("a2", 0.3)])
    assert (same.prefers, same.clear) == ("same", None)


def test_a_run_is_complete_only_with_every_look_fallback_and_single_measured() -> None:
    run = oc.RUNS[0]
    whole = rd.RunResult(run, same=True, looks=[_look("a1", 0.2), _look("a2", 0.2)])
    assert _complete(whole)
    whole.singles = {T1: _single(0.1), T2: _single(None, rows=False)}
    assert not _complete(whole)
    assert not rd.RunResult(run, same=True, looks=[_look("a1", 0.2)]).complete
    assert not rd.RunResult(run, same=False, looks=[_look("a1", 0.2)] * 2).complete
    order = [_look(n, 0.2) for n in ("a1", "b1", "a2", "b2")]  # not a, b, b, a
    assert not rd.RunResult(run, same=False, looks=order).complete
    abba = [_look(n, 0.2) for n in rd.LOOK_PLAN]
    assert rd.LOOK_PLAN == ("a1", "b1", "b2", "a2")
    assert rd.RunResult(run, same=False, looks=abba).complete
    pending = [*abba[:3], _look("a2", 0.2, holds=False, fallback=T2)]
    assert not rd.RunResult(run, same=False, looks=pending).complete
    assert not replace(
        rd.RunResult(run, same=True, looks=whole.looks), stopped="x"
    ).complete
    assert not rd.RunResult(run).complete


# ---------------------------------------------------------------------------
# A whole library on a fake measurer and a fake clock
# ---------------------------------------------------------------------------


@dataclass
class FakeOrder:
    """Two runs' engine on canned results: (a) and (b) merge as given, every
    look and single a canned gain; ``unheld`` looks do not hold; ``fail``
    raises at a step."""

    base: str
    merges: dict[tuple[str, ...], tuple[str, ...]] = field(default_factory=dict)
    trees: dict[tuple[str, str], bool] = field(default_factory=dict)
    conflicts: frozenset[frozenset[str]] = frozenset()
    gains: dict[str, float] = field(default_factory=dict)
    fail: dict[str, BaseException] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    lost: set[str] = field(default_factory=set)  # looks that measure nothing
    unheld: set[str] = field(default_factory=set)  # looks whose re-test fails

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def prepare(self) -> str:
        self._step("prepare")
        return self.base

    def commit_tip(self, patch: Path, label: str) -> str:
        self._step(f"commit {label}")
        return DELIVERED_TIP if label.endswith("-d") else _tip((label,))

    def connect(self) -> None:
        self._step("connect")

    def baseline(self) -> rx.BaselineLook:
        self._step("baseline")
        return rx.BaselineLook(0.02, 0.02, 0.01, 30.0, 12)

    def plan(
        self, changes: Sequence[KeptChange], gains: Mapping[str, float | None]
    ) -> DeliveryPlan:
        self._step("plan")
        ids = {c.trial_id for c in changes}
        pairs = frozenset(p for p in self.conflicts if p <= ids)  # as dry_merge's
        # no diffs: each keep is its own node (hunk_signature of "" is None)
        return plan_delivery(changes, gains, DryMerge(pairs, {}), by_gain=True)

    def merged(self, changes: Sequence[KeptChange]) -> co.Merged:
        ids = tuple(c.trial_id for c in changes)
        self._step(f"merge {','.join(i[:2] for i in ids)}")
        applied = self.merges.get(ids, ids)
        return co.Merged(_tip(applied), applied)

    def same_tree(self, left: str, right: str) -> bool:
        """The delivered tree matches a rebuilt tip unless ``trees`` says not."""
        return self.trees.get((left, right), right == DELIVERED_TIP or left == right)

    def _found(self, look: str, gain: float, applied: int) -> rx.RetestLook:
        return replace(_retest(gain, 0.02, look not in self.unheld), applied=applied,
                       rows=look not in self.lost)  # fmt: skip

    def retest_set(self, look: str, changes: Sequence[KeptChange]) -> rx.RetestLook:
        self._step(look)
        ids = tuple(c.trial_id for c in changes)
        applied = self.merges.get(ids, ids)
        return self._found(
            look, sum(self.gains.get(t, 0.0) for t in applied), len(applied)
        )

    def retest(self, look: str, change: KeptChange) -> rx.RetestLook:
        self._step(look)
        return self._found(look, self.gains[change.trial_id], 1)

    def check_guards(self, run: LiveRun) -> None:
        self._step("guards")


def _two_runs(archive: Archive) -> tuple[oc.OrderRun, ...]:
    """Run 1: T1 and T2 conflict, (a) kept T1 and T3, (b) by gain T2 and T3.
    Run 2 (another dispatch): T1 and T3 only, both choices the same."""
    archive.write(gains={T1: 5.0, T2: 9.0, T3: 3.0})
    second = Archive(archive.root, dispatch="987654321",
                     texts={T1: "one\n", T3: "three\n"})  # fmt: skip
    second.write(gains={T1: 5.0, T3: 3.0})
    runs, _ = oc.census(archive.root)
    return runs


def _fake(archive: Archive, **changes: object) -> FakeOrder:
    fake = FakeOrder(
        archive.base,
        merges={(T2, T3, T1): (T2, T3),  # (b)'s plan: T2 and T3, then T1 skipped
                (T1, T3, T2): (T1, T3)},  # T2 conflicts on (a)'s tip: greedy
        conflicts=frozenset({frozenset({T1, T2})}),
        gains={T1: 0.10, T2: 0.20, T3: 0.02},
    )  # fmt: skip
    for key, value in changes.items():
        setattr(fake, key, value)
    return fake


@pytest.fixture
def sink(tmp_path: Path) -> ResultsSink:
    return ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl")})


def _lines(sink: ResultsSink) -> list[dict[str, object]]:
    path = Path(sink.environ["LIVE_RESULTS_PATH"])
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_whole_library_measures_a_b_b_a_then_the_singles(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    fake = _fake(archive)
    recorder = co.OrderRecorder(sink)
    found = co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
    one, two = (r.id for r in runs)
    assert fake.calls[:8] == [
        "prepare", f"commit {one}-d", f"commit {one}-11111111", f"commit {one}-22222222",
        f"commit {one}-33333333", f"commit {two}-d", f"commit {two}-11111111",
        f"commit {two}-33333333",
    ]  # fmt: skip
    assert fake.calls[8:] == [
        "connect", "baseline",
        "merge 11,33", "merge 11,33,22", "plan", "merge 22,33,11",
        "r0-a1", "r0-b1", "r0-b2", "r0-a2", "r0-s-11111111", "r0-s-22222222",
        "merge 11,33", "plan", "merge 11,33", "r1-a1", "r1-a2",
        "guards",
    ]  # fmt: skip
    first, second = found.runs
    assert (first.a_applied, first.b_applied, first.same) == ((T1, T3), (T2, T3), False)
    assert first.mean("a") == pytest.approx(0.12)
    assert first.mean("b") == pytest.approx(0.22)
    assert (first.prefers, first.clear, first.complete) == ("b", True, True)
    (pair,) = first.pairs
    assert (pair.a_kept, pair.b_kept, pair.higher, pair.decided) == (
        (T1,),
        (T2,),
        T2,
        True,
    )
    assert (pair.a_higher, pair.b_higher) == (False, True)
    assert (pair.a_beyond, pair.b_beyond, pair.floors) == (False, True, (0.02, 0.02))
    assert (second.same, second.prefers) == (True, "same")
    assert [x.name for x in second.looks] == ["a1", "a2"]
    assert second.pairs == [] and second.singles == {}
    # the fake clock ticks 1 s a call
    assert (found.setup_s, found.connect_s, found.baseline_s) == (1.0, 1.0, 1.0)
    assert [x.seconds for x in first.looks] == [1.0] * 4 and first.plan_s == 1.0
    assert [s.seconds for s in first.singles.values()] == [1.0, 1.0]
    assert found.complete and found.wall_s is not None
    rows = _lines(sink)
    assert [r["kind"] for r in rows] == ["run", "run", "library"]
    row = rows[0]
    assert row["experiment"] == oc.ORDER_EXPERIMENT == "combine-order"
    assert (row["applied_a"], row["applied_b"], row["same"]) == (
        [T1, T3],
        [T2, T3],
        False,
    )
    assert (row["a_gains_pct"], row["b_gains_pct"]) == ([12.0, 12.0], [22.0, 22.0])
    assert (row["a_set_gains_pct"], row["b_set_gains_pct"]) == (
        [12.0, 12.0],
        [22.0, 22.0],
    )
    assert (row["a_holds"], row["b_outcomes"]) == ([True, True], ["keep", "keep"])
    assert (row["a_fallbacks"], row["b_fallback_gains_pct"]) == (
        [None, None],
        [None, None],
    )
    assert (row["prefers"], row["clear"], row["look_floor_pct"]) == ("b", True, 2.0)
    assert row["conflicts"] == [[T1, T2]] and row["pairs"] == [pair.row()]
    assert (row["a_higher"], row["b_higher"], row["decided_a"], row["decided_b"]) == (
        0,
        1,
        1,
        1,
    )
    assert (row["a_beyond"], row["b_beyond"], row["beyond_a"], row["beyond_b"]) == (
        0,
        1,
        1,
        1,
    )
    assert row["recorded_gains_pct"] == {T1: 5.0, T2: 9.0, T3: 3.0}
    assert row["singles_pct"] == {T1: 10.0, T2: 20.0} and row["complete"] is True
    assert row["singles_floor_pct"] == {T1: 2.0, T2: 2.0}
    assert row["look_s"] == [1.0] * 4 and row["singles_s"] == {T1: 1.0, T2: 1.0}
    library = rows[-1]
    assert (library["library"], library["runs"], library["baseline_floor_pct"]) == (
        "tomli",
        2,
        2.0,
    )
    assert (library["calibration_s"], library["complete"], library["skipped"]) == (
        30.0,
        True,
        [],
    )
    table = recorder.markdown()
    assert f"| {one} | 3 | 2 | 2 | no | 12.0, 12.0 | 22.0, 22.0 | b (clear) |" in table
    assert "| 1 | 0 of 1 (0 of 1) | 1 of 1 (1 of 1) |" in table
    assert (
        "2 run(s) counted, 0 not counted (incomplete), 0 skipped, 0 error(s)" in table
    )
    assert "noisier than the engine's mean-of-two order" in table  # the basis
    assert row["b_order_basis"] == "first look" and row["a_no_rows"] == [False, False]
    assert (row["greedy"], row["greedy_reason"]) == ("proven", oc.SEVERAL)
    assert "prefers a 0 (0 clear), b 1 (1 clear)" in table
    assert "(a) picked the stronger single 0 of 1 (0 of 1 past the floor)" in table


def test_a_set_that_does_not_hold_falls_back_as_the_engine_would(
    archive: Archive, sink: ResultsSink
) -> None:
    """(a) does not hold on a1: the engine's ``_fallback_candidate`` over every
    keep is T2 (the best recorded gain), re-tested alone, which delivers; (b)
    does not hold on b2 and its fallback (T2, its best single) fails too."""
    runs = _two_runs(archive)
    fake = _fake(archive, unheld={"r0-a1", "r0-b2-f", "r0-b2"})
    recorder = co.OrderRecorder(sink)
    found = co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
    assert fake.calls[14:22] == [
        "r0-a1", "r0-a1-f", "r0-b1", "r0-b2", "r0-b2-f", "r0-a2",
        "r0-s-11111111", "r0-s-22222222",
    ]  # fmt: skip
    first = found.runs[0]
    a1, b1, b2, a2 = first.looks
    assert (a1.fallback, a1.delivered) == (T2, 0.20)
    assert a1.set_gain == pytest.approx(0.12)
    assert (b2.fallback, b2.delivered) == (T2, 0.0)
    assert first.mean("a") == pytest.approx(0.16)
    assert first.mean("b") == pytest.approx(0.11)
    assert first.raw_mean("b") == pytest.approx(0.22) and first.prefers == "a"
    assert first.complete and found.complete
    row = _lines(sink)[0]
    assert row["a_fallbacks"] == [T2, None] and row["a_holds"] == [False, True]
    assert row["a_fallback_gains_pct"] == [20.0, None]
    assert row["b_fallback_holds"] == [None, False] and row["b_gains_pct"] == [
        22.0,
        0.0,
    ]
    assert row["fallback_s"] == [1.0, None, 1.0, None]
    table = recorder.markdown()
    assert "| 20.0 (fallback 22222222), 12.0 | 22.0, 0.0 (did not hold) |" in table


def test_a_failed_set_with_no_other_single_delivers_nothing(archive: Archive) -> None:
    """The engine's fallback never re-tests the failed set: with the failed
    single as the only change there is no candidate, no fallback look, 0."""
    runs = _two_runs(archive)
    fake = _fake(archive, unheld={"r0-a1"})
    only = [KeptChange(T1, f"h-{T1}", "replay", "1" * 40, 0.0, 0.05)]
    found = co._look(0, "a1", fake, only, (T1,), only, Clock())
    assert (found.fallback, found.fallback_look, found.delivered) == (None, None, 0.0)
    assert fake.calls == ["r0-a1"] and runs


def test_a_delivery_that_was_not_the_greedy_merge_is_skipped_as_a_data_gap(
    archive: Archive, sink: ResultsSink
) -> None:
    """A left-out keep that merges cleanly onto (a)'s tip: the delivery was
    the fallback, and today's greedy set is not recorded, so the run is
    listed, never guessed; the library goes on and passes."""
    runs = _two_runs(archive)
    fake = _fake(archive)
    fake.merges[(T1, T3, T2)] = (T1, T3, T2)
    recorder = co.OrderRecorder(sink)
    found = co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
    assert found.complete and found.skipped == [runs[0].id] and len(found.runs) == 1
    rows = _lines(sink)
    assert [r["kind"] for r in rows] == ["skipped", "run", "library"]
    assert "22222222 merges cleanly onto (a)'s tip" in str(rows[0]["reason"])
    assert rows[-1]["skipped"] == [runs[0].id]
    assert "1 run(s) counted, 0 not counted (incomplete), 1 skipped, 0 error(s)" in (
        recorder.markdown()
    )
    printed: list[str] = []
    recorder.finish(printed.append)  # S2: the recorder's skips reach the line
    line = next(x for x in printed if "held-or-failed runs" in x)
    assert line.startswith("1 measured of 2 held-or-failed runs")
    assert f"1 excluded because today's set failed its re-test ({runs[0].id}," in line
    assert "fallback delivered)" in line


def test_a_rebuilt_tip_that_is_not_the_delivered_tree_fails_its_run_at_the_end(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    one = runs[0].id
    fake = _fake(archive, trees={(_tip((T1, T3)), DELIVERED_TIP): False})
    recorder = co.OrderRecorder(sink)
    with pytest.raises(AssertionError, match=f"tomli: not every run measured: {one}"):
        co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    rows = _lines(sink)
    assert [r["kind"] for r in rows] == ["error", "error", "library"]
    assert "is not the delivered patch's tree" in str(rows[0]["error"])
    assert rows[0]["id"] == one and rows[-1]["errors"] == [one, runs[1].id]


def test_a_merge_that_drops_an_archived_trial_is_an_integrity_error(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    fake = _fake(archive)
    fake.merges[(T1, T3)] = (T1,)  # the archived T3 no longer applies
    recorder = co.OrderRecorder(sink)
    with pytest.raises(AssertionError, match="not every run measured"):
        co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    assert "(a) rebuilt from its applied trials applied" in str(
        _lines(sink)[0]["error"]
    )


def test_a_look_or_single_that_measured_nothing_fails_the_library_after_its_rows(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    fake = _fake(archive, lost={"r0-b1", "r0-s-22222222"})
    recorder = co.OrderRecorder(sink)
    with pytest.raises(AssertionError, match=f"not every run measured: {runs[0].id}"):
        co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    assert "r0-a2" in fake.calls and "r1-a2" in fake.calls  # every look still ran
    assert "r0-b1-f" in fake.calls  # no rows on b1: the engine's fallback ran
    rows = _lines(sink)
    assert [r["kind"] for r in rows] == ["run", "run", "library"]
    first = rows[0]
    assert first["complete"] is False and first["b_gains_pct"] == [20.0, 22.0]
    assert first["b_no_rows"] == [True, False] and first["b_fallbacks"] == [T2, None]
    assert first["b_fallback_no_rows"] == [False, False]  # b1's fallback had rows
    assert first["singles_pct"] == {T1: 10.0, T2: None}
    assert first["pairs"][0]["higher"] is None  # type: ignore[index]
    table = recorder.markdown()
    assert "20.0 (no rows; fallback 22222222)" in table and "not measured" in table
    # F4: the incomplete run is listed apart and not counted
    assert "1 run(s) counted, 1 not counted (incomplete)" in table
    assert f"Not counted (a look or single lost): {runs[0].id}" in table
    assert "prefers a 0 (0 clear), b 0 (0 clear), same 1" in table


def test_an_engine_stop_is_recorded_and_fails_the_library_at_the_end(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    for step, stopped in (("baseline", "library"), ("r0-b2", "run")):
        fake = _fake(archive, fail={step: EngineError(f"stopped at {step}")})
        recorder = co.OrderRecorder(sink)
        with pytest.raises(AssertionError, match="not every run measured"):
            co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
        assert fake.calls[-1] == "guards"
        last = _lines(sink)[-1]
        assert last["kind"] == "library"
        if stopped == "library":
            assert last["stopped"] == "stopped at baseline" and last["runs"] == 0
        else:
            assert last["stopped"] is None and last["runs"] == 2
            assert "r1-a1" in fake.calls  # the next run still measured


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ("prepare", "clone refused"),
        ("commit X2-D-123456789-tomli-d", "does not apply"),
        ("guards", "unsandboxed"),
    ],
)
def test_a_crash_before_the_runs_or_a_breach_writes_an_error_row_then_raises(
    archive: Archive, sink: ResultsSink, step: str, match: str
) -> None:
    runs = _two_runs(archive)
    error = (
        AssertionError("unsandboxed launch") if step == "guards" else ValueError(match)
    )
    fake = _fake(archive, fail={step: error})
    with pytest.raises((AssertionError, ValueError), match=match):
        co.measure_library("tomli", runs, fake, co.OrderRecorder(sink), LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    rows = _lines(sink)
    assert rows[-1]["kind"] == "error" and rows[-1]["id"] == "tomli"
    if step == "guards":
        assert str(rows[-1]["error"]).startswith("guards:") and "measured" in rows[-1]


def test_integrity_and_base_failures_measure_nothing(
    archive: Archive, sink: ResultsSink
) -> None:
    runs = _two_runs(archive)
    (archive.folder / f"trial-{T2}.diff").write_text("tampered\n")
    fake = _fake(archive)
    with pytest.raises(ra.IntegrityError, match="sha256"):
        co.measure_library("tomli", runs, fake, co.OrderRecorder(sink), LiveRun("x", 0.0),
                           archive=archive.root)  # fmt: skip
    assert fake.calls == []
    _two_runs(archive)
    other = _fake(archive, base="c" * 40)
    with pytest.raises(ra.IntegrityError, match="is not the archived"):
        co.measure_library("tomli", runs, other, co.OrderRecorder(sink), LiveRun("x", 0.0),
                           archive=archive.root)  # fmt: skip
    assert other.calls == ["prepare"]


def test_the_recorder_writes_the_census_exclusions_and_the_greedy_flags(
    archive: Archive, tmp_path: Path
) -> None:
    """F2: the census's excluded rows of the recorded libraries go to the sink
    and the summary with the exclusion line; F3: unprovable runs are listed."""
    runs = _two_runs(archive)
    flagged = replace(runs[1], greedy=oc.NOT_PROVABLE, greedy_reason=oc.ONE_OF_TWO)
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "rows.jsonl"),
                        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")})  # fmt: skip
    recorder = co.OrderRecorder(sink)
    fake = _fake(archive)
    co.measure_library("mistune", (runs[0], flagged), fake, recorder,
                       LiveRun("x", 0.0), archive=archive.root, clock=Clock())  # fmt: skip
    recorder.finish(lambda line: None)
    rows = [json.loads(x) for x in (tmp_path / "rows.jsonl").read_text().splitlines()]
    excluded = [r for r in rows if r["kind"] == "excluded"]
    assert {r["id"] for r in excluded} == {
        s.id for s in oc.SKIPPED if s.library == "mistune"
    }
    assert all(r["reason"] and "data" in r for r in excluded)
    text = (tmp_path / "summary.md").read_text()
    assert "2 measured of 3 held-or-failed runs" in text  # the scratch runs + mistune's
    assert "X2-D-43145496896-mistune, nothing delivered" in text
    assert f"Greedy not provable (measured, flagged): {flagged.id}" in text
    assert "| X2-D-43145496896-mistune | excluded | the combine did not hold |" in text
    assert [r["greedy"] for r in rows if r["kind"] == "run"] == [
        "proven",
        "not provable",
    ]


def test_incomplete_runs_enter_no_total_and_no_measured_count(tmp_path: Path) -> None:
    """S1 (F4): an incomplete run with a decided pair and a same-tree run
    with a lost look are listed, never counted: not in "picked the stronger
    single", not in "same N", not in the exclusion line's "N measured"."""
    tomli = [r for r in oc.RUNS if r.library == "tomli"][:3]
    decided = rd.Pair(T1, T2, (T1,), (T2,), (0.10, 0.30), (0.02, 0.02))
    assert decided.decided and decided.b_beyond
    lost_look = rd.RunResult(
        tomli[0], same=False,
        looks=[_look("a1", 0.2, applied=1), _look("b1", 0.3), _look("b2", 0.3),
               _look("a2", 0.2)],
        singles={T1: _single(0.10), T2: _single(0.30)}, pairs=[decided],
    )  # fmt: skip
    lost_same = rd.RunResult(tomli[1], same=True,
                             looks=[_look("a1", 0.2), _look("a2", 0.2, applied=1)])  # fmt: skip
    whole = rd.RunResult(
        tomli[2], same=True, looks=[_look("a1", 0.2), _look("a2", 0.2)]
    )
    assert [r.complete for r in (lost_look, lost_same, whole)] == [False, False, True]
    recorder = co.OrderRecorder(ResultsSink({}))
    live = LiveRun("x", 0.0)
    for result in (lost_look, lost_same, whole):
        recorder.record_run(result, live)
    recorder.record_library(
        rd.LibraryResult("tomli", ids=tuple(r.id for r in tomli)), live
    )
    table = recorder.markdown()
    assert "1 run(s) counted, 2 not counted (incomplete)" in table
    assert "same 1, tie 0" in table  # the lost same-tree run is not one
    assert ("(a) picked the stronger single 0 of 0 (0 of 0 past the floor),"
            " (b) 0 of 0 (0 of 0 past the floor)") in table  # fmt: skip
    assert "1 measured of 3 held-or-failed runs" in table
    assert f"Not counted (a look or single lost): {tomli[0].id}, {tomli[1].id}" in table


def test_the_recorder_writes_its_tables_and_totals(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    recorder = co.OrderRecorder(ResultsSink({"GITHUB_STEP_SUMMARY": str(summary)}))
    recorder.record_error("X2-D-1-tomli", LiveRun("x", 0.0), "boom")
    echoed: list[str] = []
    recorder.finish(echoed.append)
    text = summary.read_text()
    assert "Combine order replay" in text and "| X2-D-1-tomli | error | boom |" in text
    assert "0 measured of 0 held-or-failed runs" in text
    assert "0 run(s) counted, 0 not counted (incomplete), 0 skipped, 1 error(s)" in text
    assert echoed[0].endswith("written to the job summary")


# ---------------------------------------------------------------------------
# The real measurer on a local repository in the required sandbox
# ---------------------------------------------------------------------------

SOURCE = '''"""A tiny library with a quadratic hot spot and a slow sum."""


def unique(items):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


def total(items):
    out = 0
    for item in items:
        out = out + item
    return out
'''
SUITE = """import unittest

import pkg


class TestPkg(unittest.TestCase):
    def test_unique_keeps_first_occurrences_in_order(self):
        self.assertEqual(pkg.unique([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_total(self):
        self.assertEqual(pkg.total([1, 2, 3]), 6)
"""
BENCH = """import hashlib

import pkg

items = [i % 3000 for i in range(12000)]
found = pkg.unique(items)
print(f"unique={len(found)} total={pkg.total(items)}"
      f" sha256={hashlib.sha256(repr(found).encode()).hexdigest()}")
"""
SET_FIX = ("    seen = []\n    for item in items:\n        if item not in seen:\n"
           "            seen.append(item)\n    return seen\n",
           "    seen = set()\n    found = []\n    for item in items:\n"
           "        if item not in seen:\n            seen.add(item)\n"
           "            found.append(item)\n    return found\n")  # fmt: skip
DICT_FIX = (SET_FIX[0], "    return list(dict.fromkeys(items))\n")
SUM_FIX = ("    out = 0\n    for item in items:\n        out = out + item\n    return out\n",
           "    return sum(items)\n")  # fmt: skip


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    for key, value in {**rx.REPLAY_SETTINGS, "NOISE_CALIBRATION_BLOCKS": 1}.items():
        monkeypatch.setattr(settings, key, value)
    yield root


def _local_archive(root: Path) -> tuple[Archive, OssRepo, rx.Prepare]:
    """A local library ``pkg`` and an archive of two held combines on it:
    run 1 keeps T1 (set fix), T2 (dict fix, conflicts with T1) and T3 (sum
    fix), recorded gains putting T2 first while (a) applied T1 then T3; run
    2 keeps T1 and T3 alone."""
    repo = replace(
        ideas_x2.LIBRARIES["tomli"], name="pkg", package="pkg", module_root="pkg",
        test_command=("python", "-m", "unittest", "discover", "-s", "tests"),
    )  # fmt: skip
    source = root / "source"
    for rel, text in {"pkg/__init__.py": SOURCE, "tests/__init__.py": "",
                      "tests/test_pkg.py": SUITE, repo.bench_path: BENCH}.items():  # fmt: skip
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text(text, encoding="utf-8")
    probe = make_repo(source, root / "probe")
    init = probe.path / "pkg" / "__init__.py"

    def diff(*fixes: tuple[str, str]) -> str:
        text = SOURCE
        for old, new in fixes:
            text = text.replace(old, new)
        init.write_text(text, encoding="utf-8")
        found = git(probe.path, "diff", "--no-color") + "\n"
        git(probe.path, "checkout", "--", "pkg/__init__.py")
        return found

    archive = Archive(root / "archive", base=probe.base, library="pkg",
                      texts={T1: diff(SET_FIX), T2: diff(DICT_FIX), T3: diff(SUM_FIX)})  # fmt: skip
    archive.write(delivered=diff(SET_FIX, SUM_FIX), gains={T1: 5.0, T2: 30.0, T3: 3.0})
    second = Archive(archive.root, base=probe.base, library="pkg", dispatch="987654321",
                     texts={T1: archive.texts[T1], T3: archive.texts[T3]})  # fmt: skip
    second.write(delivered=diff(SET_FIX, SUM_FIX), gains={T1: 5.0, T3: 3.0})

    def prepare(dest: Path) -> UserRepo:
        return make_repo(source, dest)

    return archive, repo, prepare


def test_the_engine_order_measurer_replays_both_choices_and_the_singles(
    local: Path, sink: ResultsSink
) -> None:
    """The dry merge finds the T1-T2 conflict, ``plan_delivery`` by gain puts
    T2 (recorded 30 %) first, so (b) delivers T2 and T3 where (a) delivered T1
    and T3; each tip re-tested twice through the combine node's path, each
    conflicting keep once alone; run 2's choices agree and measure once."""
    archive, repo, prepare = _local_archive(local)
    runs, _ = oc.census(archive.root)
    measurer = co.EngineOrderMeasurer(repo, local / "pkg", Isolation("required", None),
                                      run_id="order-pkg", prepare=prepare)  # fmt: skip
    recorder = co.OrderRecorder(sink)
    found = co.measure_library("pkg", runs, measurer, recorder,
                               LiveRun("offline", oc.ORDER_RUN_CAP_USD), archive=archive.root)  # fmt: skip
    first, second = found.runs
    assert (first.a_applied, first.b_applied, first.same) == ((T1, T3), (T2, T3), False)
    assert first.conflicts == [(T1, T2)] and first.duplicates == 0
    assert [x.name for x in first.looks] == ["a1", "b1", "b2", "a2"]
    for look in first.looks:
        assert look.measured_tip and look.measured.applied == 2, look.measured.reason
        assert look.measured.gain is not None and look.measured.gain > 0.3
    assert set(first.singles) == {T1, T2} and all(
        s.look.measured_tip for s in first.singles.values()
    )
    (pair,) = first.pairs
    assert (pair.a_kept, pair.b_kept) == ((T1,), (T2,)) and pair.higher in (
        T1,
        T2,
        None,
    )
    assert (second.same, [x.name for x in second.looks]) == (True, ["a1", "a2"])
    assert found.complete and first.complete and second.complete
    assert found.baseline is not None and (found.baseline.floor or 0) >= 0.02
    phases = measurer.launches.phases()
    assert (
        phases <= rx.REPLAY_PHASES and {"combine", "combine-base", "baseline"} <= phases
    )


def test_a_b_tip_that_crashes_falls_back_and_delivers_nothing(local: Path) -> None:
    """F1 on the real engine: (b)'s set (the crashing T2 with T3) leaves no
    rows, a RunFailure the node treats as not holding; its fallback, the
    crashing T2 alone (the best recorded gain), leaves none either: 0."""
    archive, repo, prepare = _local_archive(local)
    crash = archive.texts[T2].replace("+    return list(dict.fromkeys(items))",
                                      "+    raise SystemExit(3)")  # fmt: skip
    assert crash != archive.texts[T2]
    path = local / "crash.patch"
    path.write_text(crash, encoding="utf-8")
    measurer = co.EngineOrderMeasurer(repo, local / "crash", Isolation("required", None),
                                      run_id="crash-pkg", prepare=prepare)  # fmt: skip
    measurer.prepare()
    t2 = measurer.commit_tip(path, "crash-t2")
    t3 = measurer.commit_tip(archive.folder / f"trial-{T3}.diff", "crash-t3")
    measurer.connect()
    measurer.baseline()
    offered = [KeptChange(T2, f"h-{T2}", "v", t2, 0.0, 0.30),
               KeptChange(T3, f"h-{T3}", "v", t3, 0.0, 0.03)]  # fmt: skip
    found = co._look(0, "b1", measurer, offered, (T2, T3), offered, time.monotonic)
    assert (found.no_rows, found.fallback, found.fallback_no_rows) == (True, T2, True)
    assert (found.delivered, found.set_gain, found.complete) == (0.0, None, True)


def test_the_engine_measurer_retests_a_set_through_the_combine_nodes_path(
    local: Path,
) -> None:
    archive, repo, prepare = _local_archive(local)
    measurer = rx.EngineMeasurer(repo, local / "set", Isolation("required", None),
                                 run_id="set-pkg", prepare=prepare)  # fmt: skip
    measurer.prepare()
    tips = [
        measurer.commit_tip(archive.folder / f"trial-{t}.diff", f"set-{t[:8]}")
        for t in (T1, T2)
    ]
    measurer.connect()
    measurer.baseline()
    changes = [
        KeptChange(t, f"h-{t}", "v", c, 0.0, None)
        for t, c in zip((T1, T2), tips, strict=True)
    ]
    found = measurer.retest_set("s1", changes)  # T2 conflicts with T1: skipped
    assert (found.applied, found.rows) == (1, True)


# ---------------------------------------------------------------------------
# Batches, minutes, the live module and the ci.yml row
# ---------------------------------------------------------------------------


def test_the_batches_cover_every_library_once_and_fit_the_job() -> None:
    libraries = [lib for libs in oc.BATCHES.values() for lib in libs]
    assert sorted(libraries) == sorted({r.library for r in oc.RUNS})
    whole = oc.plan_minutes(libraries)
    assert (
        oc.JOB_SETUP_MINUTES + 2 * whole > oc.MAX_JOB_MINUTES
    )  # one job would not fit
    worst = max(oc.plan_minutes(libs) for libs in oc.BATCHES.values())
    assert (
        oc.ORDER_JOB_MINUTES == oc.JOB_SETUP_MINUTES + 2 * worst <= oc.MAX_JOB_MINUTES
    )
    assert [oc.plan_minutes(oc.BATCHES[b]) for b in sorted(oc.BATCHES)] == [47, 48, 51]
    assert whole == 145
    assert oc.batch({}) == oc.batch({oc.BATCH_ENV: "1"}) == ("sqlparse",)
    assert oc.batch({oc.BATCH_ENV: "2"}) == ("markdown",)
    assert oc.batch({oc.BATCH_ENV: "3"}) == ("mistune", "tomli")
    assert oc.batch({oc.BATCH_ENV: "2"}, oc.RUNS[:1]) == ()  # only libraries with runs
    for bad in ("0", "4", "", "1;id"):
        with pytest.raises(ValueError, match=oc.BATCH_ENV):
            oc.batch({oc.BATCH_ENV: bad})


def test_the_look_seconds_are_the_o62_runs_measured_times() -> None:
    """``o62/combine-replay-43194422719.jsonl``'s case rows, rounded up."""
    path = ra.ARCHIVE / "o62" / "combine-replay-43194422719.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    cases = [r for r in rows if r["kind"] == "case"]
    looks: dict[str, float] = {}
    base: dict[str, float] = {}
    for r in cases:
        lib = str(r["library"])
        base[lib] = max(base.get(lib, 0.0), float(r["baseline_s"]))
        for s in cast(list[float], r["retest_s"]):
            looks[lib] = max(looks.get(lib, 0.0), float(s))
    assert {k: float(math.ceil(v)) for k, v in base.items()} == dict(oc.BASELINE_S)
    measured = {k: float(math.ceil(v)) for k, v in looks.items()}
    assert {**measured, "markdown": max(measured.values())} == dict(oc.LOOK_S)
    assert oc.run_looks(next(r for r in oc.RUNS if not r.left_out)) == 4
    assert oc.order_need() == oc.ORDER_RUN_CAP_USD == 0.0


def test_the_live_module_runs_what_this_file_checks() -> None:
    path = TESTS_DIR / "live" / "test_combine_order_live.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [ast.unparse(n.value) for n in tree.body if isinstance(n, ast.Assign)
             and [ast.unparse(t) for t in n.targets] == ["pytestmark"]]  # fmt: skip
    assert marks == ["pytest.mark.live"]
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]  # fmt: skip
    assert tests == ["test_every_held_combine_of_the_library_is_replayed"]
    assert "live(ORDER_RUN_CAP_USD)" in source and "order_live(" in source
    assert "check_settings()" in source and "batch(os.environ)" in source


def test_order_live_wires_the_library_and_a_fresh_measurer(
    archive: Archive, sink: ResultsSink, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}

    done = rd.LibraryResult("tomli")

    def spy(library: str, runs: Sequence[oc.OrderRun], measurer: object, *a: object,
            **kw: object) -> rd.LibraryResult:  # fmt: skip
        seen.update(library=library, runs=runs, measurer=measurer)
        return done

    monkeypatch.setattr(co, "measure_library", spy)
    found = co.order_live("tomli", LiveRun("x", 0.0), tmp_path, Isolation("required", None),
                          co.OrderRecorder(sink))  # fmt: skip
    assert found is done and seen["library"] == "tomli"
    runs = cast(Sequence[oc.OrderRun], seen["runs"])
    assert all(r.library == "tomli" for r in runs) and len(runs) == 14
    measurer = seen["measurer"]
    assert isinstance(measurer, co.EngineOrderMeasurer)
    assert (
        measurer.repo is ideas_x2.LIBRARIES["tomli"]
        and measurer.run_id == "order-tomli"
    )
    assert measurer.root == tmp_path / "tomli"


def test_the_ci_row_batch_need_timeout_rule_and_stage_a_ignore(tmp_path: Path) -> None:
    assert "combine-order" in _ci_block("      suite:", "      mode:")
    cap_help = _ci_block("      suite_cap_usd:", "\n\n")
    assert "combine-order 0 (no request, but the cap must be above 0)" in cap_help
    batch = _ci_block("      order_batch:", "\n      idea_pipeline:")
    assert "options: ['1', '2', '3']" in batch and "default: '1'" in batch
    block = _ci_block("  live-smoke:", "    defaults:")
    assert f"inputs.suite == 'combine-order' && {oc.ORDER_JOB_MINUTES} ||" in block
    assert EXPERIMENT_MINUTES["combine-order"] == oc.ORDER_JOB_MINUTES
    script = _run_script()
    assert (
        "combine-order) paths=(tests/live/test_combine_order_live.py); need=0 ;;"
        in script
    )
    rule = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    rule = rule[: rule.index("esac")]
    assert any(
        re.search(r"\bcombine-order\b", x) for x in rule.splitlines() if "step3" in x
    )
    assert "--ignore=tests/live/test_combine_order_live.py" in script
    for name in ("ok", "two", "bad", "zero"):
        (tmp_path / name).mkdir()
    code, output, calls = _dispatch(
        tmp_path / "ok", "combine-order", "claude-opus-5-5", "1"
    )
    assert code == 0, output
    assert calls.splitlines()[0] == (
        "run pytest tests/live/test_combine_order_live.py -m live --no-cov -n 0 -rA"
    )
    env = (tmp_path / "ok" / "env.txt").read_text(encoding="utf-8").splitlines()
    assert "OP_COUNT_JUDGE=true" in env and f"{oc.BATCH_ENV}=1" in env
    assert (tmp_path / "ok" / "rule.txt").read_text().split()[:3] == [
        "true",
        "true",
        "3",
    ]
    code, output, _ = _dispatch(tmp_path / "two", "combine-order", "claude-opus-5-5", "1",
                                order_batch="2")  # fmt: skip
    env = (tmp_path / "two" / "env.txt").read_text(encoding="utf-8").splitlines()
    assert code == 0 and f"{oc.BATCH_ENV}=2" in env, output
    code, output, calls = _dispatch(tmp_path / "bad", "combine-order", "claude-opus-5-5", "1",
                                    order_batch="4")  # fmt: skip
    assert (code, calls) == (1, "") and "order_batch must be 1, 2 or 3" in output
    (tmp_path / "empty").mkdir()
    code, output, calls = _dispatch(tmp_path / "empty", "combine-order", "claude-opus-5-5",
                                    "1", order_batch="")  # fmt: skip
    assert (code, calls) == (1, "") and "order_batch must be 1, 2 or 3" in output
    code, output, calls = _dispatch(
        tmp_path / "zero", "combine-order", "claude-opus-5-5", "0"
    )
    assert (code, calls) == (1, "") and "above 0" in output
