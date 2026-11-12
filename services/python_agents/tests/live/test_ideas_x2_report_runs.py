"""Offline guards of the X2 report's several runs per arm and library (O61).

Not ``live``: the report is pure code over results files and sends nothing.
The Window 2 sprint runs an arm three times on a library, one results file a
dispatch; the default page (``x2.md``) reads each (arm, library, file) as its
own run, never merged, sums its totals, lanes, hit rates and seeds over every
run of an arm, and reads its one-run-a-side sections (1, 3, 6) only where
each side has one run. Fakes: ``test_ideas_x2_report_guards._rows`` hand-makes
one run's rows as ``ideas_x2.X2Recorder`` writes them. The committed archives
are the real thing: X2's eight dispatches pin the single-run page byte for
byte against its committed ``x2.md``, and the sprint's files (X2-SV left out)
pin the per-lane hit rates against counts made from the rows apart from the
report.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import test_ideas_x2_report_guards as rg

X2_FILES = tuple(sorted(rg.X2_DIR.glob("ideas-x2-d*.jsonl")))
SPRINT = rg.X2_DIR.parent / "w2-sprint/live"
SPRINT_FILES = tuple(
    p for p in sorted(SPRINT.glob("ideas-x2-*.jsonl")) if "-X2-SV-" not in p.name
)


def _sprint_like(tmp_path: Path) -> list[Path]:
    """X2-0 three times on tomli (one file each, the last also on mistune),
    X2-D three times on tomli (two files) and once on mistune; the twin once
    on mistune and twice on tomli; X2-V once on mistune."""
    return [
        rg._write(tmp_path / "a.jsonl", rg._rows("X2-0", "tomli", [(3, ["leap"]), (2, [])], gain=10.0)),
        rg._write(tmp_path / "b.jsonl", rg._rows("X2-0", "tomli", [(2, ["obvious"]), (2, ["obvious"])], gain=8.0, cost=3.0)),
        rg._write(tmp_path / "c.jsonl", rg._rows("X2-0", "tomli", [(4, [])], gain=None, cost=1.0),
                  rg._rows("X2-0", "mistune", [(3, ["far"])], gain=4.0)),
        rg._write(tmp_path / "d.jsonl", rg._rows("X2-D", "tomli", [(3, ["leap", "leap"])], gain=12.0),
                  rg._rows("X2-D", "mistune", [(2, ["obvious"])], gain=6.0)),
        rg._write(tmp_path / "e.jsonl", rg._rows("X2-D", "tomli", [(2, [])], gain=None, cost=1.5)),
        rg._write(tmp_path / "f.jsonl", rg._rows("X2-D", "tomli", [(5, ["obvious"])], gain=3.0, cost=2.5)),
        rg._write(tmp_path / "g.jsonl", rg._rows("X2-0'", "mistune", [(3, ["far"])], gain=2.0),
                  rg._rows("X2-0'", "tomli", [(3, ["leap"])], gain=9.0)),
        rg._write(tmp_path / "h.jsonl", rg._rows("X2-0'", "tomli", [(3, [])], gain=None, cost=2.2)),
        rg._write(tmp_path / "i.jsonl", rg._rows("X2-V", "mistune", [(3, ["far", "far"])], gain=9.0)),
    ]  # fmt: skip


# ---------------------------------------------------------------------------
# The loader: each (arm, library, file) a run, never merged
# ---------------------------------------------------------------------------


def test_each_file_s_run_is_its_own_run(tmp_path: Path) -> None:
    report = xr.load(_sprint_like(tmp_path))
    assert list(report.every) == [
        ("X2-0", "tomli", "a.jsonl"), ("X2-0", "tomli", "b.jsonl"), ("X2-0", "tomli", "c.jsonl"),
        ("X2-0", "mistune", "c.jsonl"), ("X2-0'", "tomli", "g.jsonl"),
        ("X2-0'", "tomli", "h.jsonl"), ("X2-0'", "mistune", "g.jsonl"),
        ("X2-V", "mistune", "i.jsonl"), ("X2-D", "tomli", "d.jsonl"),
        ("X2-D", "tomli", "e.jsonl"), ("X2-D", "tomli", "f.jsonl"),
        ("X2-D", "mistune", "d.jsonl"),
    ]  # fmt: skip
    assert report.several
    assert report.counts["X2-0", "tomli"] == 3 and report.counts["X2-D", "mistune"] == 1
    assert [x.row.kept for x in report.of("X2-0", "tomli")] == [1, 2, 0]
    assert report.of("X2-F", "tomli") == ()
    assert list(report.runs) == [("X2-0", "mistune"), ("X2-0'", "mistune"),
                                 ("X2-V", "mistune"), ("X2-D", "mistune")]  # fmt: skip
    assert report.libs("X2-0") == ("tomli", "mistune")
    assert len(report.own("X2-D")) == 4
    one = xr.load([tmp_path / "c.jsonl"])
    assert not one.several and list(one.runs) == [
        ("X2-0", "tomli"),
        ("X2-0", "mistune"),
    ]


def test_the_same_run_in_two_files_is_refused(tmp_path: Path) -> None:
    run = rg._rows("X2-0", "tomli", [(2, ["leap"]), (1, [])])
    one, two = (
        rg._write(tmp_path / "a.jsonl", run),
        rg._write(tmp_path / "b.jsonl", run),
    )
    with pytest.raises(
        ValueError, match=r"X2-0 tomli: recorded twice \(a.jsonl and b.jsonl\)"
    ):
        xr.load([one, two])
    other = rg._rows("X2-0", "mistune", [(1, [])])  # more rows, the same run row
    three = rg._write(tmp_path / "c.jsonl", other, run)
    with pytest.raises(
        ValueError, match=r"X2-0 tomli: recorded twice \(a.jsonl and c.jsonl\)"
    ):
        xr.load([three, one])


def test_a_library_twice_in_one_file_is_refused(tmp_path: Path) -> None:
    """Two different runs of one (arm, library) in one file: a recorder
    writes a library once a dispatch, so it is an error, not a second run."""
    path = rg._write(tmp_path / "a.jsonl", rg._rows("X2-0", "tomli", [(1, [])]),
                     rg._rows("X2-0", "tomli", [(1, [])], cost=3.0))  # fmt: skip
    with pytest.raises(ValueError, match="X2-0 tomli: recorded twice"):
        xr.load([path])


def test_two_files_of_one_name_are_refused(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    one = rg._write(tmp_path / "x/r.jsonl", rg._rows("X2-0", "tomli", [(1, [])]))
    two = rg._write(
        tmp_path / "y/r.jsonl", rg._rows("X2-0", "tomli", [(1, [])], cost=3.0)
    )
    with pytest.raises(ValueError, match="X2-0 tomli: two runs in files named r.jsonl"):
        xr.load([one, two])


def test_a_run_split_across_files_is_refused(tmp_path: Path) -> None:
    """A run is one file's rows: its run row in one file and its rounds in
    another read as a run with no round (the files in name order), never as
    one run; the rounds alone have no run row."""
    run = rg._rows("X2-0", "tomli", [(2, ["leap"]), (1, [])])
    head = rg._write(tmp_path / "a.jsonl", run[-1:])
    rest = rg._write(tmp_path / "b.jsonl", run[:-1])
    with pytest.raises(ValueError, match="X2-0 tomli: no round recorded"):
        xr.load([rest, head])
    with pytest.raises(ValueError, match="X2-0 tomli: rounds with no ideas-x2-run row"):
        xr.load([rest])


def test_variance_draws_are_unchanged_by_several_runs(tmp_path: Path) -> None:
    found = xr.draws(_sprint_like(tmp_path))
    assert [(d.source, d.arm, d.repo) for d in found][:4] == [
        ("a.jsonl", "X2-0", "tomli"), ("b.jsonl", "X2-0", "tomli"),
        ("c.jsonl", "X2-0", "tomli"), ("c.jsonl", "X2-0", "mistune"),
    ]  # fmt: skip


# ---------------------------------------------------------------------------
# The page on several runs
# ---------------------------------------------------------------------------


def test_the_header_says_how_several_runs_read(tmp_path: Path) -> None:
    text = rg._text(*_sprint_like(tmp_path))
    first = text.index("## 1 ")
    assert ("- **Several runs per arm and library.** 3 (arm, library) pairs have more "
            "than one run: each run is its own row, identified by its arm, library and "
            "results file, never merged.") in text[:first]  # fmt: skip
    assert "Runs per arm and library:" in text[:first]
    for row in ("| X2-0 | tomli | 3 |", "| X2-0 | mistune | 1 |", "| X2-0' | tomli | 2 |",
                "| X2-D | tomli | 3 |", "| X2-D | mistune | 1 |"):  # fmt: skip
        assert row in text[:first], row


def test_each_run_is_a_row_with_its_file(tmp_path: Path) -> None:
    text = rg._text(*_sprint_like(tmp_path))
    two = rg._section(text, "## 2 ", "## 3 ")
    assert ("| arm | library | file | trialled | kept | combine | floor | held | cost USD |"
            in two)  # fmt: skip
    assert "| X2-0 | tomli | a.jsonl | 5 | 1 | +10.0% | 2.0% | yes | 2.00 |" in two
    assert "| X2-0 | tomli | b.jsonl | 4 | 2 | +8.0% | 2.0% | yes | 3.00 |" in two
    assert "| X2-0 | tomli | c.jsonl | 4 | 0 | none | 2.0% | yes | 1.00 |" in two
    # totals over every run: X2-0 tomli and mistune, 4 runs, (10 + 8 + 0 + 4) / 4
    assert ("| X2-0 | own (2 libraries), 4 runs | 16 | 4 | +5.5% | 8.00 | 2 | 1.00 | 0 "
            "| 0 | 2.0000 |") in two  # fmt: skip
    assert ("| X2-0 | every arm's (mistune 1), 1 run, combine the mean of library means "
            "| 3 | 1 | +4.0% |") in two  # fmt: skip


def test_the_every_arm_total_weights_each_library_once(tmp_path: Path) -> None:
    """Unequal runs per library: X2-0 twice on tomli (+10, none) and once on
    sqlparse (+20), library means 5 and 20, so +12.5 (runs' mean +10.0);
    X2-D once on tomli (+6) and three times on sqlparse (+9, +12, +15),
    library means 6 and 12, so +9.0 (runs' mean +10.5, its own row's)."""
    files = [rg._write(tmp_path / "a.jsonl", rg._rows("X2-0", "tomli", [(2, ["leap"])], gain=10.0),
                       rg._rows("X2-0", "sqlparse", [(3, ["leap", "leap"])], gain=20.0)),
             rg._write(tmp_path / "b.jsonl", rg._rows("X2-0", "tomli", [(2, [])], gain=None)),
             rg._write(tmp_path / "c.jsonl", rg._rows("X2-D", "tomli", [(1, ["obvious"])], gain=6.0),
                       rg._rows("X2-D", "sqlparse", [(1, [])], gain=9.0)),
             rg._write(tmp_path / "d.jsonl", rg._rows("X2-D", "sqlparse", [(1, [])], gain=12.0)),
             rg._write(tmp_path / "e.jsonl", rg._rows("X2-D", "sqlparse", [(1, [])], gain=15.0))]  # fmt: skip
    two = rg._section(rg._text(*files), "## 2 ", "## 3 ")
    means = "combine the mean of library means"
    assert (f"| X2-0 | every arm's (tomli 2, sqlparse 1), 3 runs, {means} | 7 | 3 | +12.5% "
            "| 6.00 | 0 | 0.00 | 0 | 0 | 2.0000 |") in two  # fmt: skip
    assert (f"| X2-D | every arm's (tomli 1, sqlparse 3), 4 runs, {means} | 4 | 1 | +9.0% "
            "| 8.00 | 0 | 0.00 | 0 | 0 | 8.0000 |") in two  # fmt: skip
    assert "| X2-0 | own (2 libraries), 3 runs | 7 | 3 | +10.0% |" in two
    assert "| X2-D | own (2 libraries), 4 runs | 4 | 1 | +10.5% |" in two
    assert ("takes as its combine the mean of the library means (each library weighted "
            "once, so arms with unequal runs per library compare like for like); the own "
            "row's combine is the mean over its runs.") in two  # fmt: skip
    assert "library means" not in rg._text(files[0])  # one run a library: as before


def test_no_library_every_arm_has_prints_no_every_arm_row(tmp_path: Path) -> None:
    text = rg._text(rg._write(tmp_path / "a.jsonl", rg._rows("X2-0", "tomli", [(1, [])]),
                              rg._rows("X2-V", "mistune", [(1, [])])))  # fmt: skip
    two = rg._section(text, "## 2 ", "## 3 ")
    assert "Totals over the libraries every arm has (none)" in two
    assert "every arm's" not in two and "| X2-V | own (1 libraries) |" in two


def test_hit_rates_sum_every_run_of_an_arm(tmp_path: Path) -> None:
    """X2-D: tomli's three runs keep 2 of 3, 0 of 2 and 1 of 5 (S1's one
    of 6, the leap 2 of 2), mistune 1 of 2: 4 of 12 over its four runs."""
    text = rg._text(*_sprint_like(tmp_path))
    rate = rg._section(text, "## 4b ", "## 5 ")
    assert ("| X2-D | leap | claude-opus-5-5 | 2 | 2 | 100.0 % | 0 | 0 | n/a | 2 | 2 | "
            "100.0 % |") in rate  # fmt: skip
    assert ("| X2-D | S1 (obvious) | claude-sonnet-5-5 | 2 | 10 | 20.0 % | 0 | 0 | n/a | "
            "2 | 10 | 20.0 % |") in rate  # fmt: skip
    assert ("| X2-D | all lanes | - | 4 | 12 | 33.3 % | 0 | 0 | n/a | 4 | 12 | 33.3 % |"
            in rate)  # fmt: skip
    per = rate[rate.index("runs behind each arm's rates") :]
    assert "| arm | library | runs | kept | trialled | hit rate |" in per
    assert "| X2-D | tomli | 3 | 3 | 10 | 30.0 % |" in per
    assert "| X2-D | mistune | 1 | 1 | 2 | 50.0 % |" in per
    assert "| X2-D | all libraries | 4 | 4 | 12 | 33.3 % |" in per
    assert "| X2-0 | tomli | 3 | 3 | 13 | 23.1 % |" in per
    lanes = rg._section(text, "## 4 ", "## 4b ")
    assert "| X2-D | all lanes | - | 4 | 0 | 4 |" in lanes


def test_seeds_name_each_library_s_runs(tmp_path: Path) -> None:
    seeds = rg._section(rg._text(*_sprint_like(tmp_path)), "## 5 ", "## 6 ")
    assert "| X2-0 | tomli (3 runs) | 4 | 1 | 4 | 2 | 1.00 | 1.0000 |" in seeds
    assert "| X2-0 | mistune (1 run) | 0 | 0 | 0 | 0 | 0.00 | n/a |" in seeds
    assert (
        "| X2-0 | all (own libraries, 4 runs) | 4 | 1 | 4 | 2 | 1.00 | 1.0000 |"
        in seeds
    )


def test_one_run_a_side_sections_read_only_single_pairs(tmp_path: Path) -> None:
    """mistune has one run of X2-0 and its twin: banded, measured and read
    against. tomli has several runs on both sides: listed as not read, for
    every arm; X2-V on mistune is read against its twin gap there (2.0 points)."""
    text = rg._text(*_sprint_like(tmp_path))
    band = rg._section(text, "## 1 ", "## 2 ")
    assert "| mistune | 1 | 1 | 0 | +4.0% | +2.0% | 2.0 |" in band
    assert "| tomli |" not in band.split("Not read here")[0]
    assert ("Not read here: several runs on one side or both (read on the variance "
            "page, ``--variance``, against the pool).") in band  # fmt: skip
    assert (
        "| library | X2-0 runs | X2-0' runs |" in band and "| tomli | 3 | 2 |" in band
    )
    three = rg._section(text, "## 3 ", "## 4 ")
    assert ("| X2-V | mistune | +1 | outside the measured band, not significant | +5.0 | "
            "outside its twin gap |") in three  # fmt: skip
    assert ("| X2-D | mistune | +0 | inside the measured band (its twin gap, 0 kept) | "
            "+2.0 | inside its twin gap (2.0 points) |") in three  # fmt: skip
    assert "| X2-D | tomli |" not in three.split("Not read one to one")[0]
    assert "| arm | library | arm runs | X2-0 runs | X2-0' runs |" in three
    assert "| X2-D | tomli | 3 | 3 | 2 |" in three
    six = rg._section(text, "## 6 ", None)
    assert "| mistune | +4.0% | +2.0% | 2.0 | 1 | 1 | 0 |" in six
    assert "| tomli | 3 | 2 |" in six


def test_a_library_whose_twin_ran_twice_is_not_read_against_a_fixed_band(
    tmp_path: Path,
) -> None:
    """X2-0 and X2-V once on tomli, the twin twice: the library has a twin,
    so it never takes the no-twin fixed band; it is not read one to one."""
    files = [rg._write(tmp_path / "a.jsonl", rg._rows("X2-0", "tomli", [(2, ["leap"])]),
                       rg._rows("X2-V", "tomli", [(2, [])], gain=None)),
             rg._write(tmp_path / "b.jsonl", rg._rows("X2-0'", "tomli", [(2, [])])),
             rg._write(tmp_path / "c.jsonl", rg._rows("X2-0'", "tomli", [(1, [])], cost=1.0))]  # fmt: skip
    text = rg._text(*files)
    band = rg._section(text, "## 1 ", "## 2 ")
    assert ("No twinned library with one run a side: every library read below takes "
            "the fixed band (O51 as amended).") in band  # fmt: skip
    assert "| tomli | 1 | 2 |" in band
    three = rg._section(text, "## 3 ", "## 4 ")
    assert "| X2-V | tomli | 1 | 1 | 2 |" in three
    assert "fixed band (no twin)" not in three
    six = rg._section(text, "## 6 ", None)
    assert "No twinned library with one run a side: no path-dependence measure." in six


def test_s1_and_s2_records_over_several_runs(tmp_path: Path) -> None:
    def marked(cost: float) -> list[rg.Row]:
        run = rg._rows("X2-C", "tomli", [(2, ["leap"])], cost=cost)
        run[0] = {**run[0],
                  "realisation": {"label": "fired", "anchor_touched": True, "kept_not_fired": False},
                  "combine": {"delivered": True, "skip_reason": None, "duplicate_of": None,
                              "component": 0, "best_subset": True, "gain_pct": 3.0,
                              "reconcile": None}}  # fmt: skip
        return run

    text = rg._text(rg._write(tmp_path / "a.jsonl", marked(2.0)),
                    rg._write(tmp_path / "b.jsonl", marked(3.0)))  # fmt: skip
    assert "| X2-C | fired | 2 | 2 |" in rg._section(text, "## 7 ", "## 8 ")
    eight = rg._section(text, "## 8 ", None)
    assert "| arm | library | file | kept | kept (duplicates once) |" in eight
    assert "| X2-C | tomli | a.jsonl | 1 | 1 | 1 | 1 | 0 | 0 | 0 |" in eight
    assert "| X2-C | tomli | b.jsonl | 1 | 1 | 1 | 1 | 0 | 0 | 0 |" in eight


# ---------------------------------------------------------------------------
# The committed archives
# ---------------------------------------------------------------------------


def test_x2_s_eight_dispatches_render_their_committed_page_byte_for_byte(
    tmp_path: Path,
) -> None:
    assert len(X2_FILES) == 8
    assert (
        xr.main([*map(str, X2_FILES), "--out", str(tmp_path)], echo=lambda _: None) == 0
    )
    assert (tmp_path / "x2.md").read_bytes() == (
        rg.X2_DIR / "report/x2.md"
    ).read_bytes()


def _apart(
    paths: tuple[Path, ...],
) -> tuple[Counter[str], Counter[str], Counter[tuple[str, str]]]:
    """Each arm's kept and trialled hypotheses and its runs per library,
    counted from the raw rows without the report."""
    kept: Counter[str] = Counter()
    tried: Counter[str] = Counter()
    runs: Counter[tuple[str, str]] = Counter()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("experiment") == x2.IDEA_EXPERIMENT and row["round"] is not None:
                kept[row["arm"]] += row["verdict"] == "keep"
                tried[row["arm"]] += row["verdict"] in (
                    "keep",
                    "inconclusive",
                    "reject",
                )
            elif row.get("experiment") == x2.RUN_EXPERIMENT:
                runs[row["arm"], row["repo"]] += 1
    return kept, tried, runs


def test_the_sprint_archives_read_with_x2_s(tmp_path: Path) -> None:
    """X2's eight dispatches and the sprint's files (X2-SV, a shadow arm,
    left out): the page is written, and each arm's all-lanes hit rate and
    runs per library are the raw rows' counts."""
    paths = (*X2_FILES, *SPRINT_FILES)
    assert len(SPRINT_FILES) == 18
    assert xr.main([*map(str, paths), "--out", str(tmp_path)], echo=lambda _: None) == 0
    text = (tmp_path / "x2.md").read_text(encoding="utf-8")
    rate = rg._section(text, "## 4b ", "## 5 ")
    kept, tried, runs = _apart(paths)
    for arm in ("X2-0", "X2-D", "X2-P", "X2-F"):
        mine = [
            line
            for line in rate.splitlines()
            if line.startswith(f"| {arm} | all lanes |")
        ]
        total = f"| {kept[arm]} | {tried[arm]} | {xr.hit_rate(kept[arm], tried[arm])} |"
        assert len(mine) == 1 and mine[0].endswith(total), arm
        own = sum(v for (a, _), v in runs.items() if a == arm)
        assert (
            f"| {arm} | all libraries | {own} | {kept[arm]} | {tried[arm]} |" in rate
        ), arm
        for lib in (lib for a, lib in runs if a == arm):
            assert f"| {arm} | {lib} | {runs[arm, lib]} |" in rate, (arm, lib)
    assert runs["X2-0", "tomli"] == 4 and runs["X2-D", "tomli"] == 3
