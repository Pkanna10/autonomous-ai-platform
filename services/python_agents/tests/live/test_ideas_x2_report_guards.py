"""Offline guards of the X2 report (V-x2rep, ``ideas_x2_report.py``).

Not ``live``: the report is pure code over results files and sends nothing.
Fakes and what they stand for: ``_rows`` hand-makes one (arm, library) run's
``ideas-x2-hypothesis``, ``ideas-x2-round`` and ``ideas-x2-run`` rows as
``ideas_x2.X2Recorder`` writes them (only the fields the report reads, plus
one it ignores). The three committed dispatches (X2-0, X2-0', X2-V on
pyparsing, tomli and sortedcontainers) are the real thing and pin the
figures; what only the five later dispatches prove is that their rows keep
these fields.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from .conftest import TESTS_DIR

Row = dict[str, object]
SERVICE = TESTS_DIR.parent
X2_DIR = SERVICE.parents[1] / ".claude/handoff/step3/idea-lab/x2"
REAL = tuple(X2_DIR / f"ideas-x2-{n}.jsonl" for n in
             ("d1-42149964562", "d2-42156498229", "d3-42160890340"))  # fmt: skip
SONNET, OPUS = "claude-sonnet-5-5", "claude-opus-5-5"


def _rows(arm: str, repo: str, rounds: Sequence[tuple[int, Sequence[str]]], *,
          gain: float | None = 5.0, holds: bool | None = True,
          cost: float = 2.0) -> list[Row]:  # fmt: skip
    """One run: each round (trialled, the kept ideas' lanes, "compound" for
    a kept compound); the rest of a round's trials inconclusive S1 ideas."""
    head: Row = {"arm": arm, "repo": repo}
    out: list[Row] = []
    for n, (trialled, keeps) in enumerate(rounds, 1):
        for k in range(trialled):
            lane = keeps[k] if k < len(keeps) else "obvious"
            compound = lane == "compound"
            out.append({**head, "experiment": x2.IDEA_EXPERIMENT, "round": n,
                        "hypothesis_id": f"{repo}-{n}-{k}", "compound": compound,
                        "lane": None if compound else lane,
                        "model": None if compound else (OPUS if lane == "leap" else SONNET),
                        "verdict": "keep" if k < len(keeps) else "inconclusive",
                        "gain_pct": 3.0, "floor_pct": 2.0, "title": "t"})  # fmt: skip
        out.append({**head, "experiment": x2.ROUND_EXPERIMENT, "round": n,
                    "trialled": trialled, "kept": len(keeps), "seeds": 2 * (n > 1),
                    "seeded_calls": int(n > 1), "seeded_cost_usd": 0.5 * (n > 1),
                    "compounds": keeps.count("compound"),
                    "compounds_kept": keeps.count("compound")})  # fmt: skip
    out.append({**head, "experiment": x2.RUN_EXPERIMENT, "dispatch": f"{arm}:{repo}",
                "cost_usd": cost, "seeded_calls": len(rounds) - 1,
                "seeded_cost_usd": 0.5 * (len(rounds) - 1),
                "kept": sum(len(k) for _, k in rounds), "combined": gain is not None,
                "holds": holds, "gain_pct": gain, "floor_pct": 2.0})  # fmt: skip
    return out


def _write(path: Path, *runs: list[Row]) -> Path:
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n"
                            for run in runs for r in run), encoding="utf-8")  # fmt: skip
    return path


def _text(*paths: Path) -> str:
    return xr.render(xr.load(paths))


def _real() -> str:
    return _text(*REAL)


# ---------------------------------------------------------------------------
# The three committed dispatches: the figures pinned
# ---------------------------------------------------------------------------


def test_the_real_files_pin_kept_counts_and_combines() -> None:
    report = xr.load(REAL)
    libs = ("pyparsing", "tomli", "sortedcontainers")
    for arm, kept, gains in (("X2-0", (1, 6, 2), ("+5.5%", "+22.6%", "+13.4%")),
                             ("X2-0'", (1, 6, 2), ("+2.8%", "+18.6%", "+10.2%")),
                             ("X2-V", (2, 4, 0), ("+5.7%", "+22.6%", "none"))):  # fmt: skip
        assert tuple(report.runs[arm, n].row.kept for n in libs) == kept
        assert tuple(xr.gain_cell(report.runs[arm, n]) for n in libs) == gains
    text = _real()
    assert (
        "| X2-0 | pyparsing | 9 | 1 | +5.5% | 2.0% | yes | 2.12 | 1 | 0.65 | 0 | 0 | 2.1192 |"
        in text
    )
    assert (
        "| X2-V | sortedcontainers | 9 | 0 | none | - | - | 2.22 | 1 | 0.61 | 0 | 0 | n/a |"
        in text
    )


def test_the_header_reads_arm_to_arm_and_the_band_before_any_comparison() -> None:
    text = _real()
    first = text.index("## 1 ")
    for said in ("arm to arm only", "not against X1 on wins",
                 "round 1 trials the whole idea result (O50)",
                 "under about 4 points of combine gain", "under 1 on the kept count",
                 "is noise (O51)", "O51 as amended",
                 "against its own twin gap where a twin exists",
                 "Only a library without a twin takes O51's fixed band"):  # fmt: skip
        assert -1 < text.index(said) < first, said
    for name, dispatch in zip(REAL, ("X2-0", "X2-0'", "X2-V"), strict=True):
        assert f"| {name.name} |" in text[:first]
        assert f"| {dispatch}\\:pyparsing,tomli,sortedcontainers |" in text[:first]


def test_the_twin_band_beside_o51s() -> None:
    text = _real()
    assert "| pyparsing | 1 | 1 | 0 | +5.5% | +2.8% | 2.7 |" in text
    assert "| tomli | 6 | 6 | 0 | +22.6% | +18.6% | 3.9 |" in text
    assert "| sortedcontainers | 2 | 2 | 0 | +13.4% | +10.2% | 3.2 |" in text
    band = text.split("## 1 ")[1].split("## 2 ")[0]
    assert "| kept gap (tk) |" in band and "| combine gap (tg, points) |" in band
    assert ("O51 as amended: each library with a twin is read against its own gaps "
            "above, a combine difference counting only beyond its tg and a kept-count "
            "difference only beyond its tk; only a library without a twin takes the "
            "fixed band of 4 points of combine gain and 1 on the kept count.") in band  # fmt: skip
    assert "O51 fixed the band" not in text


def test_each_arm_against_x2_0_carries_its_band_label() -> None:
    text = _real()
    one, out = "outside the measured band, not significant", "outside the measured band"
    assert (
        f"| X2-V | pyparsing | +1 | {one} | +0.2 | inside its twin gap (2.7 points) |"
        in text
    )
    assert (
        f"| X2-V | tomli | -2 | {out} | +0.0 | inside its twin gap (3.9 points) |"
        in text
    )
    assert (f"| X2-V | sortedcontainers | -2 | {out} | -13.4 | outside its twin gap |"
            in text)  # fmt: skip
    assert "| X2-0' | pyparsing |" not in text.split("## 3 ")[1].split("## 4 ")[0]


def test_the_header_states_o52s_rules_before_any_comparison() -> None:
    text = _real()
    first = text.index("## 1 ")
    for said in ("a kept-count difference within its twin gap is inside the measured band",
                 "one beyond it is outside the measured band, not significant",
                 "two or more beyond it are outside the measured band",
                 "with a twin gap of 0, O52's gaps of 0, 1 and 2 or more",
                 "keeps more only if it keeps more on more libraries than it keeps fewer",
                 "keeps fewer only if it keeps fewer on more libraries than it keeps more",
                 "else no difference",
                 "better only when it exceeds the twin's mean absolute gap",
                 "worse only when it is below minus that gap",
                 "else within the twin's mean gap",
                 "No single library decides (O52)"):  # fmt: skip
        assert -1 < text.index(said) < first, said
    assert text.index("(O51)") < text.index("(O52)") < first


def test_the_real_files_call_x2_v_against_x2_0() -> None:
    """X2-V keeps +1, -2, -2 (1 more, 2 fewer); its combine differences
    +0.15, +0.03, -13.38 points average -4.40, below minus the twin's mean
    gap (2.70 + 3.94 + 3.22) / 3 = 3.29."""
    text = _real()
    assert ("The twin's mean gap over its 3 libraries is 3.3 points of combine "
            "gain (O52's bar for an arm's combine).") in text  # fmt: skip
    call = text.split("Arm-level calls")[1].split("## 4 ")[0]
    assert ("| X2-V | pyparsing, tomli, sortedcontainers | 1 | 2 | 0 | "
            "keeps fewer, on 3 libraries | -4.4 | 3.3, on 3 libraries | "
            "worse, on 3 libraries |") in call  # fmt: skip
    assert "No single library decides (O52)" in call
    assert "| X2-0' |" not in call
    report = xr.load(REAL)
    assert xr.twin_gap(report) == pytest.approx(
        (5.499097605674446 - 2.8012439621748024 + 22.5779199527674
         - 18.635074871022987 + 13.37877315534008 - 10.160837166538679) / 3
    )  # fmt: skip


NOT_SIG, OUT_KEPT = (
    "outside the measured band, not significant",
    "outside the measured band",
)
FIXED_IN, FIXED_OUT = (
    "within the fixed band (no twin)",
    "outside the fixed band (no twin)",
)


@pytest.mark.parametrize(
    ("diff", "gap", "label"),
    [(0, 0, "inside the measured band (its twin gap, 0 kept)"),
     (1, 0, NOT_SIG), (-1, 0, NOT_SIG), (2, 0, OUT_KEPT), (-3, 0, OUT_KEPT),
     (3, 2, NOT_SIG), (-3, 2, NOT_SIG), (2, 2, "inside the measured band (its twin gap, 2 kept)"),
     (-1, 2, "inside the measured band (its twin gap, 2 kept)"), (4, 2, OUT_KEPT),
     (0, None, FIXED_IN), (1, None, FIXED_OUT), (-1, None, FIXED_OUT), (2, None, FIXED_OUT)],
)  # fmt: skip
def test_kept_reading(diff: int, gap: int | None, label: str) -> None:
    """O51 as amended: beyond the library's own kept gap tk (tk + 1 not
    significant, O52's 1 when tk is 0); without a twin, under 1 is noise."""
    assert xr.kept_reading(diff, gap) == label


@pytest.mark.parametrize(
    ("diffs", "call"),
    [((1, -2, -2), "keeps fewer"), ((-1, 0, 0), "keeps fewer"),
     ((2, 1, -3), "keeps more"), ((1, 0, 0), "keeps more"),
     ((1, -1, 0), "no difference"), ((0, 0, 0), "no difference"),
     ((3, -1, 2, -5), "no difference")],
)  # fmt: skip
def test_kept_call_is_a_sign_count(diffs: tuple[int, ...], call: str) -> None:
    assert xr.kept_call(diffs) == call


@pytest.mark.parametrize(
    ("mean", "gap", "call"),
    [(3.31, 3.3, "better"), (-3.31, 3.3, "worse"), (3.3, 3.3, "within the twin's mean gap"),
     (-3.3, 3.3, "within the twin's mean gap"), (0.0, 0.0, "within the twin's mean gap"),
     (0.1, 0.0, "better"), (-0.1, 0.0, "worse"), (9.0, None, "no band (unbanded)")],
)  # fmt: skip
def test_mean_call(mean: float, gap: float | None, call: str) -> None:
    assert xr.mean_call(mean, gap) == call


def test_an_arm_level_call_on_hand_made_rows(tmp_path: Path) -> None:
    """Twin on tomli and pyparsing (gaps 2 and 4: mean 3); X2-V on those and
    mistune keeps +1, +2, -1 (keeps more) and gains +4, +3, +3 (mean 3.33:
    better). The single library with the largest kept gain does not decide."""
    path = _write(tmp_path / "r.jsonl",
                  _rows("X2-0", "tomli", [(3, ["leap"]), (1, [])], gain=10.0),
                  _rows("X2-0'", "tomli", [(3, ["leap"]), (1, [])], gain=8.0),
                  _rows("X2-V", "tomli", [(3, ["leap", "far"]), (1, [])], gain=14.0),
                  _rows("X2-0", "pyparsing", [(3, ["leap"])], gain=6.0),
                  _rows("X2-0'", "pyparsing", [(3, ["leap"])], gain=2.0),
                  _rows("X2-V", "pyparsing", [(3, ["leap", "far", "far"])], gain=9.0),
                  _rows("X2-0", "mistune", [(3, ["leap", "far"])], gain=4.0),
                  _rows("X2-V", "mistune", [(3, ["leap"])], gain=7.0))  # fmt: skip
    text = _text(path)
    assert ("| X2-V | pyparsing, tomli, mistune | 2 | 1 | 0 | keeps more, on 3 libraries "
            "| +3.3 | 3.0, on 2 libraries | better, on 3 libraries |") in text  # fmt: skip
    assert f"| X2-V | mistune | -1 | {FIXED_OUT} | +3.0 | {FIXED_IN} |" in text
    assert ("| X2-V | pyparsing | +2 | outside the measured band | +3.0 | "
            "inside its twin gap (4.0 points) |") in text  # fmt: skip
    assert (f"| X2-V | tomli | +1 | {NOT_SIG} | +4.0 | outside its twin gap |"
            in text)  # fmt: skip


def test_an_arm_level_call_with_no_twin_is_unbanded(tmp_path: Path) -> None:
    path = _write(tmp_path / "r.jsonl",
                  _rows("X2-0", "mistune", [(3, ["leap"])], gain=4.0),
                  _rows("X2-V", "mistune", [(3, [])], gain=None))  # fmt: skip
    text = _text(path)
    assert ("| X2-V | mistune | 0 | 1 | 0 | keeps fewer, on 1 library | -4.0 | none | "
            "no band (unbanded), on 1 library |") in text  # fmt: skip
    assert xr.twin_gap(xr.load([path])) is None


def test_wins_by_lane_and_round() -> None:
    text = _real()
    for row in ("| X2-0 | leap | claude-opus-5-5 | 2 | 0 | 2 |",
                "| X2-0 | S1 (obvious) | claude-sonnet-5-5 | 1 | 2 | 3 |",
                "| X2-0 | name_the_problem | claude-sonnet-5-5 | 2 | 0 | 2 |",
                "| X2-0 | recombine | claude-sonnet-5-5 | 1 | 1 | 2 |",
                "| X2-0 | all lanes | - | 6 | 3 | 9 |",
                "| X2-V | S1 (obvious) | claude-sonnet-5-5 | 2 | 2 | 4 |",
                "| X2-V | all lanes | - | 3 | 3 | 6 |"):  # fmt: skip
        assert row in text, row
    lanes = text.split("## 4 ")[1].split("## 5 ")[0]
    assert lanes.index("| X2-0 | leap |") < lanes.index("| X2-0 | S1 (obvious) |")
    assert lanes.index("| X2-0 | S1 (obvious) |") < lanes.index("| X2-0 | name_the")


def test_seeds_and_totals() -> None:
    text = _real()
    assert "| X2-0 | pyparsing | 5 | 0 | 4 | 1 | 0.65 | n/a |" in text
    assert "| X2-0 | all (own libraries) | 16 | 3 | 17 | 3 | 1.79 | 0.5983 |" in text
    assert "| X2-V | all (own libraries) | 15 | 3 | 18 | 3 | 1.89 | 0.6305 |" in text
    common = "every arm's (pyparsing, tomli, sortedcontainers)"
    assert (
        f"| X2-0 | {common} | 33 | 9 | +13.8% | 6.45 | 3 | 1.79 | 0 | 0 | 0.7164 |"
        in text
    )
    assert (
        f"| X2-V | {common} | 33 | 6 | +9.4% | 7.62 | 3 | 1.89 | 0 | 0 | 1.2692 |"
        in text
    )


def test_the_output_is_byte_identical_whatever_the_order(tmp_path: Path) -> None:
    for n, paths in enumerate((REAL, REAL[::-1])):
        assert xr.main([*map(str, paths), "--out", str(tmp_path / str(n))],
                       echo=lambda _: None) == 0  # fmt: skip
    assert (tmp_path / "0/x2.md").read_bytes() == (tmp_path / "1/x2.md").read_bytes()
    assert (tmp_path / "0/x2.md").read_text(encoding="utf-8") == _real()


# ---------------------------------------------------------------------------
# Hand-made rows: the band edges, unbanded libraries, compounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("diff", "gap", "label"),
    [(10.0, 18.7, "inside its twin gap (18.7 points)"),
     (-18.7, 18.7, "inside its twin gap (18.7 points)"), (18.71, 18.7, "outside its twin gap"),
     (3.0, 2.7, "outside its twin gap"), (-3.0, 2.7, "outside its twin gap"),
     (2.7, 2.7, "inside its twin gap (2.7 points)"), (0.0, 0.0, "inside its twin gap (0.0 points)"),
     (0.1, 0.0, "outside its twin gap"),
     (3.9, None, FIXED_IN), (-3.99, None, FIXED_IN), (4.0, None, FIXED_OUT),
     (-4.0, None, FIXED_OUT), (0.0, None, FIXED_IN)],
)  # fmt: skip
def test_reading(diff: float, gap: float | None, label: str) -> None:
    """O51 as amended: a combine difference counts only beyond the library's
    own twin gap tg (the gap itself is inside); without a twin, under 4."""
    assert xr.reading(diff, gap) == label


def test_each_library_against_its_own_twin_gap(tmp_path: Path) -> None:
    """sqlparse-like: twin gaps 18.7 points and 2 kept, so +10 points is
    inside and +3 kept one beyond (not significant); pyparsing: 2.7 points and
    0 kept, so +3 points is outside; tomli: gap 2 points, 1 kept, both met
    exactly (inside); mistune, no twin: the fixed band. Arm calls as before."""
    path = _write(tmp_path / "r.jsonl",
                  _rows("X2-0", "sqlparse", [(9, ["leap"] * 7)], gain=21.1),
                  _rows("X2-0'", "sqlparse", [(9, ["leap"] * 9)], gain=39.8),
                  _rows("X2-V", "sqlparse", [(10, ["leap"] * 10)], gain=31.1),
                  _rows("X2-0", "pyparsing", [(3, ["leap"])], gain=5.5),
                  _rows("X2-0'", "pyparsing", [(3, ["leap"])], gain=2.8),
                  _rows("X2-V", "pyparsing", [(3, ["leap"])], gain=8.5),
                  _rows("X2-0", "tomli", [(3, ["leap"])], gain=10.0),
                  _rows("X2-0'", "tomli", [(3, ["leap", "far"])], gain=8.0),
                  _rows("X2-V", "tomli", [(3, [])], gain=12.0),
                  _rows("X2-0", "mistune", [(3, ["leap"])], gain=4.0),
                  _rows("X2-V", "mistune", [(3, ["leap"])], gain=7.9))  # fmt: skip
    text = _text(path)
    assert "| sqlparse | 7 | 9 | 2 | +21.1% | +39.8% | 18.7 |" in text
    assert (f"| X2-V | sqlparse | +3 | {NOT_SIG} | +10.0 | "
            "inside its twin gap (18.7 points) |") in text  # fmt: skip
    assert ("| X2-V | pyparsing | +0 | inside the measured band (its twin gap, 0 kept) | "
            "+3.0 | outside its twin gap |") in text  # fmt: skip
    assert ("| X2-V | tomli | -1 | inside the measured band (its twin gap, 1 kept) | +2.0 | "
            "inside its twin gap (2.0 points) |") in text  # fmt: skip
    assert f"| X2-V | mistune | +0 | {FIXED_IN} | +3.9 | {FIXED_IN} |" in text
    assert "unbanded" not in text.split("## 3 ")[1].split("Arm-level calls")[0]
    assert ("| X2-V | pyparsing, tomli, mistune, sqlparse | 1 | 1 | 2 | no difference, "
            "on 4 libraries | +4.7 | 7.8, on 3 libraries | within the twin's mean gap, "
            "on 4 libraries |") in text  # fmt: skip


def test_a_library_without_a_twin_takes_the_fixed_band(tmp_path: Path) -> None:
    path = _write(tmp_path / "r.jsonl",
                  _rows("X2-0", "mistune", [(3, ["leap"]), (2, [])], gain=4.0),
                  _rows("X2-V", "mistune", [(3, ["far", "leap"]), (2, ["compound"])],
                        gain=12.0))  # fmt: skip
    text = _text(path)
    assert f"| X2-V | mistune | +2 | {FIXED_OUT} | +8.0 | {FIXED_OUT} |" in text
    assert ("No twin rows: every library below takes the fixed band (O51 as "
            "amended).") in text  # fmt: skip
    assert "unbanded" not in text.split("## 3 ")[1].split("Arm-level calls")[0]
    assert "| X2-V | compound | - | 0 | 1 | 1 |" in text
    assert (
        "| X2-V | mistune | 5 | 3 | +12.0% | 2.0% | yes | 2.00 | 1 | 0.50 | 1 | 1 | 0.6667 |"
        in text
    )


def test_a_combine_that_did_not_hold_delivers_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path / "r.jsonl",
                  _rows("X2-0", "idna", [(2, ["leap"]), (1, [])], gain=9.0),
                  _rows("X2-V", "idna", [(2, ["leap"]), (1, [])], gain=9.0, holds=False))  # fmt: skip
    text = _text(path)
    assert "| X2-V | idna | 3 | 1 | +9.0% (did not hold) | 2.0% | no |" in text
    assert f"| X2-V | idna | +0 | {FIXED_IN} | -9.0 | {FIXED_OUT} |" in text


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def _refused(tmp_path: Path, rows: list[Row], why: str) -> None:
    path = _write(tmp_path / "bad.jsonl", rows)
    with pytest.raises(ValueError, match=why):
        xr.load([path])


def test_malformed_rows_are_refused(tmp_path: Path) -> None:
    good = _rows("X2-0", "tomli", [(2, ["leap"]), (1, [])])
    _refused(tmp_path, [{k: v for k, v in good[-1].items() if k != "kept"}, *good[:-1]],
             r"bad.jsonl:1: malformed ideas-x2-run row \(kept")  # fmt: skip
    _refused(
        tmp_path,
        [{**good[0], "round": "one"}, *good[1:]],
        "malformed ideas-x2-hypothesis row",
    )
    _refused(
        tmp_path,
        [{**good[2], "seeded_cost_usd": -1.0}, *good[:2], *good[3:]],
        "malformed ideas-x2-round row",
    )
    _refused(
        tmp_path,
        [{**good[0], "lane": "relax_dependency"}, *good[1:]],
        "not the leap, S1 or a lens",
    )
    _refused(
        tmp_path, [{**good[0], "lane": None}, *good[1:]], "not the leap, S1 or a lens"
    )
    _refused(tmp_path, [{**r, "arm": "X2-F"} for r in good], "unknown arm 'X2-F'")
    _refused(
        tmp_path, [{**r, "repo": "numpy"} for r in good], "unknown library 'numpy'"
    )
    (tmp_path / "x.jsonl").write_text("{\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"x.jsonl:1: not JSON"):
        xr.load([tmp_path / "x.jsonl"])


def test_a_library_or_arm_recorded_twice_is_refused(tmp_path: Path) -> None:
    run = _rows("X2-0", "tomli", [(2, ["leap"]), (1, [])])
    one, two = _write(tmp_path / "a.jsonl", run), _write(tmp_path / "b.jsonl", run)
    with pytest.raises(ValueError, match="X2-0 tomli: recorded twice"):
        xr.load([one, two])
    with pytest.raises(ValueError, match="X2-0 tomli: recorded twice"):
        xr.load([one, one])
    _refused(
        tmp_path, [*run[:3], run[2], *run[3:]], r"X2-0 tomli: round 1 recorded twice"
    )
    _refused(
        tmp_path, [run[0], *run], r"X2-0 tomli: hypothesis tomli-1-0 recorded twice"
    )


def test_a_run_whose_rounds_are_missing_is_refused(tmp_path: Path) -> None:
    run = _rows("X2-0", "tomli", [(2, ["leap"]), (1, [])])
    rounds = [i for i, r in enumerate(run) if r["experiment"] == x2.ROUND_EXPERIMENT]
    _refused(tmp_path, [r for i, r in enumerate(run) if i != rounds[0]],
             r"X2-0 tomli: rounds \[2\], not 1 to 2")  # fmt: skip
    _refused(tmp_path, [r for i, r in enumerate(run) if i not in rounds],
             "X2-0 tomli: no round recorded")  # fmt: skip
    _refused(tmp_path, run[:-1], "X2-0 tomli: rounds with no ideas-x2-run row")
    _refused(tmp_path, [{**run[rounds[0]], "kept": 2} if i == rounds[0] else r
                        for i, r in enumerate(run)],
             "X2-0 tomli: round 1 records 2 kept, its ideas 1")  # fmt: skip
    _refused(tmp_path, [{**run[-1], "kept": 3}, *run[:-1]],
             "X2-0 tomli: the run records 3 kept, its rounds 1")  # fmt: skip
    _refused(tmp_path, [{**run[0], "round": 3}, *run[1:]],
             "X2-0 tomli: hypothesis tomli-1-0 in round 3, not recorded")  # fmt: skip
    _refused(tmp_path, [{**run[0], "round": None}, *run[1:]],
             "X2-0 tomli: hypothesis tomli-1-0 kept in no round")  # fmt: skip
    pooled = [*run, {**run[1], "hypothesis_id": "left", "round": None}]
    assert (
        xr.load([_write(tmp_path / "ok.jsonl", pooled)]).runs["X2-0", "tomli"].trialled
        == 3
    )


def test_no_rows_is_refused(tmp_path: Path) -> None:
    _refused(tmp_path, [{"experiment": "ideas-x1-other"}], "no ideas-x2-run row")


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def test_main_refuses_and_writes_nothing(tmp_path: Path) -> None:
    said: list[str] = []
    bad = _write(tmp_path / "bad.jsonl", _rows("X2-0", "tomli", [(1, [])])[:-1])
    assert xr.main([str(bad), "--out", str(tmp_path / "out")], echo=said.append) == 2
    assert said[0].startswith("error: X2-0 tomli: rounds with no ideas-x2-run row")
    assert not (tmp_path / "out").exists()
    assert xr.main([str(tmp_path / "none.jsonl"), "--out", str(tmp_path / "out")],
                   echo=said.append) == 2  # fmt: skip
    assert not (tmp_path / "out").exists()


def test_the_module_runs_from_tests(tmp_path: Path) -> None:
    out = tmp_path / "out"
    env = {**os.environ, "PYTHONPATH": f"{SERVICE / 'src'}:{SERVICE / 'tests'}"}
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-m", "live.ideas_x2_report", *map(str, REAL), "--out", str(out)],
        cwd=SERVICE / "tests", env=env, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f"wrote x2.md to {out}"
    assert (out / "x2.md").read_text(encoding="utf-8") == _real()
    assert xr.REPORT_DIR == X2_DIR
