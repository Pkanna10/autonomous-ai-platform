"""Offline guards of the combine-order replay's (b)-only cases (O71 item 1).

The pre-registered X2-DT comparator is the 20 X2-D runs' delivered gain under
gain order. The O65 replay has rows for 17; the other three are measured on
the gain-ordered side alone (``order_cases.B_CASES``). Checked here, with no
network:

- the three cases resolve from the committed archive, pass integrity, and
  with the O65 rows cover every X2-D run; their failures on a scratch archive;
- the selector (``$LIVE_ORDER_BATCH`` ``b``): exactly these three, never the
  58, and the 58's batches never these;
- a library of (b)-only runs on a fake measurer: held, not held with the
  fallback held, nothing held (0), and the one-keep run; the row's schema;
- the real measurer on a local repository in the ``required`` sandbox;
- the minutes the three need.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.execution.protocols import KeptChange

from . import combine_order as co
from . import order_cases as oc
from . import order_readings as rd
from . import replay_archive as ra
from . import replay_engine as rx
from .conftest import LiveRun
from .discovery_io import ResultsSink
from .test_combine_order_guards import (
    T1,
    T2,
    T3,
    Archive,
    FakeOrder,
    _fake,
    _local_archive,
)
from .test_combine_replay_guards import Clock, _require_sandbox

THE_THREE = (
    "X2-D-43159144063-tomli",
    "X2-D-43145496896-mistune",
    "X2-D-43159154661-mistune",
)
O65_ROWS = "live/combine-order-43567670887-43567673362-43567675481.jsonl"


@pytest.fixture
def archive(tmp_path: Path) -> Archive:
    return Archive(Path(os.path.realpath(tmp_path)) / "archive")


@pytest.fixture
def sink(tmp_path: Path) -> ResultsSink:
    return ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl")})


def _lines(sink: ResultsSink) -> list[dict[str, object]]:
    path = Path(sink.environ["LIVE_RESULTS_PATH"])
    return [json.loads(line) for line in path.read_text().splitlines()]


# ---------------------------------------------------------------------------
# The three cases on the committed archive
# ---------------------------------------------------------------------------


def test_the_three_uncovered_x2_d_runs_resolve_and_pass_integrity() -> None:
    assert tuple(c.id for c in oc.B_CASES) == THE_THREE
    assert oc.B_RUNS == oc.b_census()
    assert tuple(r.id for r in oc.B_RUNS) == THE_THREE
    assert [(r.library, len(r.keeps)) for r in oc.B_RUNS] == [
        ("tomli", 1), ("mistune", 5), ("mistune", 7),
    ]  # fmt: skip
    for run, case in zip(oc.B_RUNS, oc.B_CASES, strict=True):
        assert (run.sides, run.applied, run.why_no_a) == (oc.SIDES_B, (), case.why)
        assert (run.greedy, run.greedy_reason) == (None, None)  # an (a) reading
        assert (run.case.tip, run.case.patch, run.case.arm) == (ra.NO_TIP, None, "X2-D")
        loaded = oc.load_b_run(run)
        assert loaded.run is run
        assert [p.name for _, p in loaded.diffs] == [
            f"trial-{k.trial_id}.diff" for k in run.keeps
        ]
        assert all(-1 < k.gain < 1 for k in run.keeps)
    tomli = oc.B_RUNS[0]
    assert tomli.case.base_commit == "e9735a7906565459e3a503348d7c6698a2b28cc2"
    assert round(tomli.keeps[0].gain * 100, 4) == 10.401  # its first look
    assert round(tomli.archived_gain_pct or 0, 2) == 10.52
    # why each has no row: the census says the same
    skipped = {s.id: s.reason for s in oc.SKIPPED}
    assert skipped[THE_THREE[0]] == oc.FEW_KEEPS
    assert skipped[THE_THREE[1]] == oc.NOT_HELD
    held = {r.id: r for r in oc.RUNS}
    assert held[THE_THREE[2]].greedy == oc.NOT_PROVABLE
    assert "fallback" in oc.B_CASES[2].why and "did not hold" in oc.B_CASES[1].why
    assert "one keep" in oc.B_CASES[0].why
    # the 59 both-sides cases are untouched
    assert len(oc.RUNS) == 59 and all(r.sides == oc.SIDES_AB for r in oc.RUNS)
    assert all(r.why_no_a is None for r in oc.RUNS)


def test_with_the_o65_rows_the_three_cover_every_x2_d_run() -> None:
    """The comparator: 17 X2-D runs have O65 rows, these three the rest."""
    every: set[str] = set()
    for path in (ra.ARCHIVE / "live").glob("ideas-x2-X2-D-*.jsonl"):
        dispatch = path.stem.rsplit("-", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("experiment") == "ideas-x2-run":
                every.add(f"X2-D-{dispatch}-{row['repo']}")
    rows = [
        json.loads(x)
        for x in (ra.ARCHIVE / O65_ROWS).read_text(encoding="utf-8").splitlines()
    ]
    measured = {str(r["id"]) for r in rows if r["kind"] == "run"}
    covered = {i for i in measured if i.startswith("X2-D-")}
    assert len(every) == 20 and len(covered) == 17
    assert every - covered == set(THE_THREE)


# ---------------------------------------------------------------------------
# A scratch archive: the cases and their integrity failures
# ---------------------------------------------------------------------------

ONE = oc.BCase("X2-D", "123456789", "tomli", "why one")
TWO = oc.BCase("X2-D", "987654321", "tomli", "why two")


def _b_runs(archive: Archive, **first: object) -> tuple[oc.OrderRun, ...]:
    """Run one: T1, T2 and T3 (T1 and T2 conflict on the fake); run two (another
    dispatch): T1 alone, one keep."""
    archive.write(gains={T1: 5.0, T2: 9.0, T3: 3.0}, **first)  # type: ignore[arg-type]
    single = Archive(archive.root, dispatch="987654321", texts={T1: "one\n"})
    single.write(applied=(T1,), gains={T1: 5.0})
    return oc.b_census(archive.root, (ONE, TWO))


def test_a_scratch_b_case_reads_every_keep_and_no_delivered_patch(
    archive: Archive,
) -> None:
    one, two = _b_runs(archive, row={"holds": False, "delivered_patch": None})
    assert (one.id, one.sides, one.why_no_a, one.applied) == (
        ONE.id,
        "b",
        "why one",
        (),
    )
    assert [(k.trial_id, k.gain) for k in one.keeps] == [
        (T1, 0.05), (T2, 0.09), (T3, 0.03),
    ]  # fmt: skip
    assert (one.archived_gain_pct, one.archived_floor_pct) == (20.0, 2.0)
    assert (two.id, len(two.keeps)) == (TWO.id, 1)
    loaded = oc.load_b_run(one, archive.root)  # nothing delivered: still loads
    assert [p.name for _, p in loaded.diffs] == [
        f"trial-{t}.diff" for t in (T1, T2, T3)
    ]
    archive.write(row={"gain_pct": None, "floor_pct": "x"})
    bare = oc.b_census(archive.root, (ONE,))[0]
    assert (bare.archived_gain_pct, bare.archived_floor_pct) == (None, None)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"gains": {T1: 5.0, T2: None, T3: 3.0}}, "no recorded gain for keep 22222222"),
        ({"row": {"kept": 4}}, "one entry per keep"),
        ({"row": {"kept": 0, "kept_diffs": []}}, "no keeps"),
        ({"row": {"repo": "mistune"}}, "0 run rows for tomli, not 1"),
        ({"extra": [{"experiment": "ideas-x2-run", "repo": "tomli"}]}, "2 run rows"),
    ],
)
def test_a_b_case_lacking_its_keeps_is_refused(
    archive: Archive, change: dict[str, object], match: str
) -> None:
    archive.write(**change)  # type: ignore[arg-type]
    with pytest.raises(ra.IntegrityError, match=match):
        oc.b_census(archive.root, (ONE,))


def test_a_b_case_with_no_run_file_or_a_kept_diff_written_partly_is_refused(
    archive: Archive,
) -> None:
    with pytest.raises(ra.IntegrityError, match="no run file"):
        oc.b_census(archive.root, (ONE,))
    archive.write()
    path = archive.root / "live" / "ideas-x2-X2-D-123456789.jsonl"
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    lines[-1]["kept_diffs"][1]["truncated"] = True
    path.write_text("\n".join(map(json.dumps, lines)) + "\n")
    with pytest.raises(ra.IntegrityError, match="not written whole"):
        oc.b_census(archive.root, (ONE,))


def test_integrity_failures_of_a_b_case_are_raised(archive: Archive) -> None:
    (run, _) = _b_runs(archive)
    (archive.folder / f"trial-{T2}.diff").write_text("tampered\n")
    with pytest.raises(ra.IntegrityError, match="sha256"):
        oc.load_b_run(run, archive.root)
    _b_runs(archive)
    moved = replace(run, keeps=(replace(run.keeps[0], hypothesis_id="h-other"),))
    with pytest.raises(ra.IntegrityError, match="another hypothesis"):
        oc.load_b_run(moved, archive.root)
    wrong = replace(run, case=replace(run.case, base_commit="b" * 40))
    with pytest.raises(ra.IntegrityError, match="base_commit"):
        oc.load_b_run(wrong, archive.root)
    off = replace(run, keeps=(replace(run.keeps[0], patch="../outside.diff"),))
    with pytest.raises(ra.IntegrityError, match="not under the archive"):
        oc.load_b_run(off, archive.root)


# ---------------------------------------------------------------------------
# The selector
# ---------------------------------------------------------------------------


def test_the_selector_runs_exactly_the_three_and_never_the_58() -> None:
    b = {oc.BATCH_ENV: oc.B_BATCH}
    assert oc.B_BATCH == "b" and oc.batch(b) == ("mistune", "tomli")
    assert oc.sides(b) == oc.SIDES_B
    assert oc.sides({}) == oc.sides({oc.BATCH_ENV: "3"}) == oc.SIDES_AB
    picked = [r for lib in oc.batch(b) for r in oc.cases(lib, oc.sides(b))]
    assert sorted(r.id for r in picked) == sorted(THE_THREE)
    assert all(r.sides == oc.SIDES_B for r in picked)
    for name in oc.BATCHES:  # the 58's batches never carry a (b)-only case
        env = {oc.BATCH_ENV: name}
        found = [r for lib in oc.batch(env) for r in oc.cases(lib, oc.sides(env))]
        assert found and all(r.sides == oc.SIDES_AB for r in found)
    assert oc.batch(b, b_runs=oc.B_RUNS[:1]) == ("tomli",)
    with pytest.raises(ValueError, match=r"1, 2, 3 or b, got '4'"):
        oc.batch({oc.BATCH_ENV: "4"})
    with pytest.raises(ValueError, match="sides"):
        oc.cases("tomli", "a")


def test_order_live_takes_the_recorders_cases(
    sink: ResultsSink, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, object] = {}
    done = rd.LibraryResult("mistune")

    def spy(library: str, runs: object, measurer: object, *a: object,
            **kw: object) -> rd.LibraryResult:  # fmt: skip
        seen.update(runs=runs, measurer=measurer)
        return done

    monkeypatch.setattr(co, "measure_library", spy)
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    found = co.order_live("mistune", LiveRun("x", 0.0), tmp_path,
                          Isolation("required", None), recorder)  # fmt: skip
    assert found is done
    assert seen["runs"] == oc.B_RUNS[1:]
    measurer = seen["measurer"]
    assert isinstance(measurer, co.EngineOrderMeasurer)
    assert (measurer.run_id, measurer.root) == ("order-b-mistune", tmp_path / "mistune")


def test_the_live_module_passes_the_selected_sides_to_its_recorder() -> None:
    source = (Path(__file__).parent / "test_combine_order_live.py").read_text()
    assert "OrderRecorder(ResultsSink(os.environ), sides(os.environ))" in source
    assert "batch(os.environ)" in source


def test_a_recorder_refuses_a_case_of_the_other_kind(
    archive: Archive, sink: ResultsSink
) -> None:
    """A dispatch is one kind: a (b)-only recorder never measures one of the
    58, nor the both-sides recorder a (b)-only case (an error row, raised)."""
    runs = _b_runs(archive)
    with pytest.raises(ValueError, match="sides"):
        co.OrderRecorder(sink, "a")
    for recorder, offered in ((co.OrderRecorder(sink), runs),
                              (co.OrderRecorder(sink, oc.SIDES_B), oc.RUNS[:1])):  # fmt: skip
        fake = _fake(archive)
        with pytest.raises(ValueError, match="this dispatch measures"):
            co.measure_library("tomli", offered, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
        assert fake.calls == [] and _lines(sink)[-1]["kind"] == "error"


# ---------------------------------------------------------------------------
# A (b)-only library on the fake measurer
# ---------------------------------------------------------------------------


def _measure(archive: Archive, sink: ResultsSink, fake: FakeOrder,
             ) -> tuple[rd.LibraryResult, co.OrderRecorder]:  # fmt: skip
    runs = _b_runs(archive)
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    found = co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                               archive=archive.root, clock=Clock())  # fmt: skip
    return found, recorder


def test_a_b_only_library_measures_b_b_then_the_singles_and_delivers_a_held_set(
    archive: Archive, sink: ResultsSink
) -> None:
    fake = _fake(archive)
    found, recorder = _measure(archive, sink, fake)
    one, two = ONE.id, TWO.id
    assert fake.calls == [
        "prepare", f"commit {one}-11111111", f"commit {one}-22222222",
        f"commit {one}-33333333", f"commit {two}-11111111", "connect", "baseline",
        "plan", "merge 22,33,11", "r0-b1", "r0-b2", "r0-s-11111111", "r0-s-22222222",
        "plan", "merge 11", "r1-b1", "r1-b2", "guards",
    ]  # no (a) merge, no delivered tip, no greedy probe  # fmt: skip
    first, second = found.runs
    assert (first.a_applied, first.b_applied, first.same) == ((), (T2, T3), None)
    assert [x.name for x in first.looks] == list(rd.B_PLAN) == ["b1", "b2"]
    assert first.mean("b") == pytest.approx(0.22) and first.mean("a") is None
    assert (first.prefers, first.clear, first.complete) == (None, None, True)
    assert second.mean("b") == pytest.approx(0.10) and second.complete
    assert second.conflicts == [] and second.singles == {}
    assert found.complete
    rows = _lines(sink)
    assert [r["kind"] for r in rows] == ["run", "run", "library"]
    row = rows[0]
    assert (row["sides"], row["a_null_reason"], row["id"]) == ("b", "why one", one)
    assert (row["applied_b"], row["b_gains_pct"], row["mean_b_pct"]) == (
        [T2, T3], [22.0, 22.0], 22.0,
    )  # fmt: skip
    assert (row["b_holds"], row["b_fallbacks"], row["b_set_gains_pct"]) == (
        [True, True], [None, None], [22.0, 22.0],
    )  # fmt: skip
    assert (row["b_higher"], row["decided_b"], row["b_beyond"], row["beyond_b"]) == (
        1, 1, 1, 1,
    )  # fmt: skip
    assert row["look_floor_pct"] == 2.0 and row["complete"] is True
    assert row["singles_pct"] == {T1: 10.0, T2: 20.0}
    (pair,) = cast(list[dict[str, object]], row["pairs"])
    assert (pair["b_kept"], pair["b_higher"], pair["b_beyond"]) == ([T2], True, True)
    assert (pair["a_kept"], pair["a_higher"], pair["a_beyond"]) == (None, None, None)
    assert rows[1]["mean_b_pct"] == 10.0 and rows[1]["a_null_reason"] == "why two"
    table = recorder.markdown()
    assert "(b) only" in table and "(a) is not measured on these runs" in table
    assert f"| {one} | 3 | why one | 2 | 22.0, 22.0 | 22.0 | 1 | 1 of 1 (1 of 1) |" in (
        table
    )
    assert f"| {two} | 1 | why two | 1 | 10.0, 10.0 | 10.0 | 0 | 0 of 0 (0 of 0) |" in (
        table
    )
    assert "2 run(s) counted, 0 not counted (incomplete), 0 error(s)" in table
    assert "mean (b) delivered over the counted runs: 16.0" in table
    assert "held-or-failed" not in table  # no (a)/(b) exclusion line
    assert "| tomli | 2 of 2 | 0 |" in table  # the wall-time table


def test_the_b_only_row_leaves_every_a_field_null_and_says_why(
    archive: Archive, sink: ResultsSink
) -> None:
    _measure(archive, sink, _fake(archive))
    row = _lines(sink)[0]
    both = rd.RunResult(oc.RUNS[0]).row()  # the existing schema
    assert set(row) == set(both)  # one schema; ``sides`` and the reason are new
    assert (both["sides"], both["a_null_reason"]) == ("ab", None)
    a_marked = {k for k in both if re.search(r"(^a_|_a$|_a_)", k)} - {"a_null_reason"}
    assert a_marked <= set(rd.A_FIELDS)
    assert set(rd.A_FIELDS) - a_marked == {
        "same", "greedy", "greedy_reason", "prefers", "clear",
    }  # fmt: skip
    assert {k: row[k] for k in rd.A_FIELDS} == dict.fromkeys(rd.A_FIELDS)
    assert row["b_order_basis"] == oc.ORDER_BASIS
    assert row["recorded_gains_pct"] == {T1: 5.0, T2: 9.0, T3: 3.0}


def test_a_b_set_that_does_not_hold_delivers_its_held_fallback(
    archive: Archive, sink: ResultsSink
) -> None:
    """The node's ``_fallback_candidate`` over (b)'s plan: T2, the best
    recorded gain, re-tested alone, held: it delivers its own gain."""
    fake = _fake(archive, unheld={"r0-b1", "r0-b2"})
    found, recorder = _measure(archive, sink, fake)
    assert fake.calls[9:15] == [
        "r0-b1", "r0-b1-f", "r0-b2", "r0-b2-f", "r0-s-11111111", "r0-s-22222222",
    ]  # fmt: skip
    first = found.runs[0]
    assert [(x.fallback, x.delivered) for x in first.looks] == [(T2, 0.20)] * 2
    assert first.raw_mean("b") == pytest.approx(0.22) and first.complete
    row = _lines(sink)[0]
    assert (row["b_holds"], row["b_fallbacks"], row["b_fallback_holds"]) == (
        [False, False], [T2, T2], [True, True],
    )  # fmt: skip
    assert (row["b_gains_pct"], row["mean_b_pct"]) == ([20.0, 20.0], 20.0)
    assert "20.0 (fallback 22222222), 20.0 (fallback 22222222)" in recorder.markdown()


def test_nothing_held_delivers_zero_and_one_keep_has_no_fallback(
    archive: Archive, sink: ResultsSink
) -> None:
    """Neither the set nor its fallback holds: 0, as live. The one-keep run's
    set is its single keep, so the node has no other single: no fallback
    look, 0."""
    unheld = {"r0-b1", "r0-b1-f", "r0-b2", "r0-b2-f", "r1-b1", "r1-b2"}
    fake = _fake(archive, unheld=unheld)
    found, recorder = _measure(archive, sink, fake)
    assert fake.calls[-3:] == ["r1-b1", "r1-b2", "guards"]  # no r1-b1-f
    first, second = found.runs
    assert [x.delivered for x in first.looks] == [0.0, 0.0]
    assert [(x.fallback, x.delivered) for x in second.looks] == [(None, 0.0)] * 2
    assert first.complete and second.complete and found.complete
    rows = _lines(sink)
    assert (rows[0]["mean_b_pct"], rows[0]["b_fallback_holds"]) == (0.0, [False, False])
    assert (rows[1]["mean_b_pct"], rows[1]["b_fallbacks"]) == (0.0, [None, None])
    table = recorder.markdown()
    assert "0.0 (did not hold), 0.0 (did not hold)" in table
    assert "mean (b) delivered over the counted runs: 0.0" in table


@dataclass
class ShortFake(FakeOrder):
    """``FakeOrder`` whose ``short`` looks apply one trial fewer than their set."""

    short: set[str] = field(default_factory=set)

    def retest_set(self, look: str, changes: Sequence[KeptChange]) -> rx.RetestLook:
        found = super().retest_set(look, changes)
        return (
            replace(found, applied=found.applied - 1) if look in self.short else found
        )


def test_a_b_look_that_measured_nothing_is_not_counted_and_fails_the_library(
    archive: Archive, sink: ResultsSink
) -> None:
    base = _fake(archive)
    fake = ShortFake(base.base, merges=base.merges, conflicts=base.conflicts,
                     gains=base.gains, short={"r1-b2"})  # fmt: skip
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    runs = _b_runs(archive)
    with pytest.raises(AssertionError, match=f"not every run measured: {TWO.id}"):
        co.measure_library("tomli", runs, fake, recorder, LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    second = recorder.runs[1]
    assert not second.complete and second.mean("b") == pytest.approx(0.10)
    assert [x.delivered for x in second.looks] == [pytest.approx(0.10), None]
    table = recorder.markdown()
    assert "1 run(s) counted, 1 not counted (incomplete), 0 error(s)" in table
    assert "mean (b) delivered over the counted runs: 22.0" in table
    assert "| 10.0, not measured |" in table
    assert _lines(sink)[1]["complete"] is False


def test_a_b_only_error_is_listed_and_an_empty_recorder_reads_none(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "summary.md"
    sink = ResultsSink({"GITHUB_STEP_SUMMARY": str(summary),
                        "LIVE_RESULTS_PATH": str(tmp_path / "rows.jsonl")})  # fmt: skip
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    recorder.record_error("X2-D-1-tomli", LiveRun("x", 0.0), "boom")
    recorder.finish(lambda line: None)
    text = summary.read_text()
    assert "| X2-D-1-tomli | error | boom |" in text
    assert "mean (b) delivered over the counted runs: -" in text
    rows = [json.loads(x) for x in (tmp_path / "rows.jsonl").read_text().splitlines()]
    assert [r["kind"] for r in rows] == ["error"]  # no census exclusions written


def test_a_b_recorder_with_runs_writes_no_census_exclusion(
    archive: Archive, tmp_path: Path
) -> None:
    """The census's excluded rows of tomli (the one-keep runs among them) are
    both-sides data: a (b)-only recorder that measured tomli writes none of
    them and no exclusion line; the both-sides recorder, on the same
    library, writes them."""
    assert any(s.library == "tomli" for s in oc.SKIPPED)
    for kind, excluded in ((oc.SIDES_B, False), (oc.SIDES_AB, True)):
        rows_path = tmp_path / f"rows-{kind}.jsonl"
        sink = ResultsSink({"LIVE_RESULTS_PATH": str(rows_path)})
        recorder = co.OrderRecorder(sink, kind)
        if kind == oc.SIDES_B:
            co.measure_library("tomli", _b_runs(archive), _fake(archive), recorder,
                               LiveRun("x", 0.0), archive=archive.root, clock=Clock())  # fmt: skip
            assert len(recorder.runs) == 2
        else:
            recorder.record_library(rd.LibraryResult("tomli"), LiveRun("x", 0.0))
        printed: list[str] = []
        recorder.finish(printed.append)
        kinds = [json.loads(x)["kind"] for x in rows_path.read_text().splitlines()]
        assert ("excluded" in kinds) is excluded, kind
        if not excluded:
            assert kinds == ["run", "run", "library"]
            assert not any("held-or-failed" in x for x in printed)


def test_an_engine_stop_on_a_b_look_is_recorded(
    archive: Archive, sink: ResultsSink
) -> None:
    fake = _fake(archive, fail={"r0-b2": EngineError("stopped at r0-b2")})
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    with pytest.raises(AssertionError, match=f"not every run measured: {ONE.id}"):
        co.measure_library("tomli", _b_runs(archive), fake, recorder, LiveRun("x", 0.0),
                           archive=archive.root, clock=Clock())  # fmt: skip
    first = _lines(sink)[0]
    assert first["stopped"] == "stopped at r0-b2" and first["complete"] is False


# ---------------------------------------------------------------------------
# The real measurer on a local repository in the required sandbox
# ---------------------------------------------------------------------------


@pytest.fixture
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    for key, value in {**rx.REPLAY_SETTINGS, "NOISE_CALIBRATION_BLOCKS": 1}.items():
        monkeypatch.setattr(settings, key, value)
    yield root


def test_the_engine_order_measurer_replays_b_alone(
    local: Path, sink: ResultsSink
) -> None:
    """The dry merge finds the T1-T2 conflict and ``plan_delivery`` by gain
    puts T2 (recorded 30 %) first, so (b) delivers T2 and T3, re-tested
    twice through the combine node's path, each conflicting keep once alone;
    no (a) merge and no delivered tip."""
    archive, repo, prepare = _local_archive(local)
    cases = (replace(ONE, library="pkg"), replace(TWO, library="pkg"))
    runs = oc.b_census(archive.root, cases)
    measurer = co.EngineOrderMeasurer(repo, local / "pkg", Isolation("required", None),
                                      run_id="order-b-pkg", prepare=prepare)  # fmt: skip
    recorder = co.OrderRecorder(sink, oc.SIDES_B)
    found = co.measure_library("pkg", runs, measurer, recorder,
                               LiveRun("offline", oc.ORDER_RUN_CAP_USD), archive=archive.root)  # fmt: skip
    first, second = found.runs
    assert (first.a_applied, first.b_applied, first.same) == ((), (T2, T3), None)
    assert first.conflicts == [(T1, T2)]
    assert [x.name for x in first.looks] == ["b1", "b2"]
    for look in first.looks:
        assert look.measured_tip and look.measured.applied == 2, look.measured.reason
        # as the both-sides test does: the measured gain is the plumbing under
        # test; whether it clears the floor (delivered) depends on the host's load
        assert look.measured.gain is not None and look.measured.gain > 0.3
        assert look.delivered is not None
    assert set(first.singles) == {T1, T2}
    assert second.b_applied == (T1, T3) and second.complete
    assert found.complete and first.complete
    rows = _lines(sink)
    assert [r["sides"] for r in rows if r["kind"] == "run"] == ["b", "b"]


# ---------------------------------------------------------------------------
# The minutes
# ---------------------------------------------------------------------------


def test_the_three_need_nine_minutes_inside_the_existing_job() -> None:
    """Two looks of (b)'s tip, each with its fallback, and every keep as a
    single when there are two or more (an upper bound): mistune 60 + 44 +
    14 x (1 + 9 + 11) s, tomli 60 + 22 + 6 x (1 + 4) s; 510 s."""
    assert [oc.run_looks(r) for r in oc.B_RUNS] == [4, 9, 11]
    assert oc.library_seconds("mistune", oc.B_RUNS) == 398.0
    assert oc.library_seconds("tomli", oc.B_RUNS) == 112.0
    minutes = oc.plan_minutes(oc.batch({oc.BATCH_ENV: oc.B_BATCH}), oc.B_RUNS)
    assert minutes == oc.B_PLAN_MINUTES == 9
    assert oc.JOB_SETUP_MINUTES + 2 * minutes <= oc.ORDER_JOB_MINUTES  # 33 <= 117
