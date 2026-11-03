"""Offline guards of the X1 report (Vf, ``ideas_report.py``).

Not ``live``: the report is pure code over results files and sends nothing.
Every row here is hand-made (``_x1``, ``_e1``): two libraries, tomli (floor
2 %) and idna (floor 20 %), one file holding a hot function ``f`` (lines
10-40, 50 % of the workload) around a hotter-named inner ``g`` (lines 20-30,
10 %). Fakes and what they stand for: these rows for Vd's ``ideas-*`` rows
of an X1 dispatch, Vc's ``ideas-validate-score`` row, Ve's slice rows (the
contract the report states, ``ideas-slice-trial`` and
``ideas-slice-combine``) and E1's raw results directory. What only the
real X1 results prove: that Vd's and Ve's rows carry these fields as named.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
)
from autonomous_ai_agents.optimization import idea_dedupe as dd

from . import ideas_probe as ip
from . import ideas_report as ir
from . import ideas_slice as sl
from .conftest import TESTS_DIR

Row = dict[str, object]
SERVICE = TESTS_DIR.parent
KEY = "sk-ant-" + "a1b2c3d4e5f6"  # key-shaped, never a real key
FLOORS = {"tomli": 0.02, "idna": 0.2}


def _spot(repo: str, symbol: str, first: int, last: int, total: float) -> Hotspot:
    return Hotspot(
        id=f"h-{repo}-{symbol}", project_id=f"p-{repo}", workload_id="w1",
        file_path="pkg/a.py", symbol=symbol, line_start=first, line_end=last,
        self_time_s=total / 2, total_time_s=total, share=total / 20,
    )  # fmt: skip


def _facts(repo: str) -> Row:
    project = Project(id=f"p-{repo}", name=repo, root_path="/srv/lib")
    objective = Objective(
        project_id=project.id, kind=ObjectiveKind.runtime, metric="wall_time_s",
        direction=Direction.minimize, min_relative_gain=FLOORS[repo],
        description="faster",
    )  # fmt: skip
    body = ip.FactsBody(
        commit="c" * 40, run_id="r1", protected=(), project=project,
        understanding=None, objective=objective,
        hotspots=(_spot(repo, "f", 10, 40, 5.0), _spot(repo, "g", 20, 30, 1.0)),
    )  # fmt: skip
    return {"experiment": "ideas-facts", "repo": repo,
            "chunks": list(ip._chunks(body.model_dump_json()))}  # fmt: skip


def _idea(
    repo: str, arm: str, lane: str, model: str, pos: int, title: str,
    mech: str | None = "precompute_or_cache", cell: str = "work:eliminate",
    lines: tuple[int, int] | None = (20, 25), path: str = "pkg/a.py",
    relaxes: str | None = None, returned: bool = True,
) -> Row:  # fmt: skip
    return {
        "experiment": "ideas-idea", "repo": repo, "arm": arm, "lane": lane,
        "label": lane, "model": model, "position": pos, "title": title,
        "change": f"change of {title}", "returned": returned,
        "proposal": relaxes is not None, "relaxes": relaxes, "mechanism": mech,
        "cells": [] if mech is None else [cell],
        "path": None if mech is None else path,
        "target": None if lines is None else {"first": lines[0], "last": lines[1]},
    }  # fmt: skip


def _probe(
    repo: str, arm: str, ideas: int, good: int | None, usd: float,
    audited: int = 0, bad: int = 0,
) -> Row:  # fmt: skip
    return {"experiment": "ideas-probe", "repo": repo, "arm": arm, "ideas": ideas,
            "non_obvious": max(ideas - 2, 0), "good": good, "cost_usd": usd,
            "audited": audited, "auditor_infeasible": bad,
            "models": ["m"], "stats": None}  # fmt: skip


def _audit(
    i: str, arm: str, title: str, verdict: str | None, dup: str | None = None,
    in_result: bool = True,
) -> Row:  # fmt: skip
    return {"experiment": "ideas-audit", "repo": "tomli", "arm": arm, "id": i,
            "title": title, "lane": "x", "tier": 0, "in_result": in_result,
            "own": None,
            "auditor": verdict, "reason": None if dup is None else "duplicate_of",
            "duplicate_of": dup}  # fmt: skip


def _score(passed: bool) -> Row:
    score = dd.DedupeScore(
        labelled=10, agreed=9 if passed else 5, agreement=0.9 if passed else 0.5,
        same_pairs=5, same_merged=5, different_pairs=5, different_merged=0,
        different_merged_share=0.0, passed=passed, show_raw=not passed,
        why="passed the fixed bar" if passed else "agreement 50.0% is under 85%",
    )  # fmt: skip
    return {"experiment": "ideas-validate-score",
            "score": score.model_dump(mode="json"), "pairs": 10}  # fmt: skip


S5, HK, SN = ip.SONNET_5, ip.HAIKU, "claude-sonnet-5-5"
IDEAS: list[Row] = [
    _idea("tomli", "A", "today", "", 1, "Inline lookups", mech=None, lines=None),
    _idea("tomli", "A", "today", "", 2, "Cache tables", mech=None, lines=None),
    _idea("tomli", "X1-0", "eliminate", SN, 1, "Cache the parse table"),
    _idea("tomli", "X1-0", "far", SN, 1, "Memoise tables", lines=(22, 28)),
    _idea(
        "tomli",
        "X1-0",
        "obvious",
        SN,
        1,
        "Use a dict",
        "data_structure",
        "representation:compact",
        (35, 38),
    ),  # fmt: skip
    _idea(  # the arm's reviewer removed it: outside the configuration's result
        "tomli",
        "X1-0",
        "far",
        SN,
        2,
        "Precompute keys",
        "algorithm",
        "work:reuse",
        (30, 32),
        returned=False,
    ),  # fmt: skip
    _idea("tomli", "X1-2", "eliminate", SN, 1, "Cache parse table", lines=(21, 21)),
    _idea(
        "tomli",
        "X1-3",
        "far",
        SN,
        1,
        "Stream input",
        "lazy_or_streaming",
        "granularity:stream",
        (1, 2),
        path="pkg/b.py",
    ),  # fmt: skip
    _idea("tomli", "X1-1", "eliminate", S5, 1, "Skip work"),
    _idea("tomli", "X1-1", "eliminate", S5, 2, "Skip more work", lines=(24, 26)),
    _idea(
        "tomli",
        "X1-1",
        "assume_less",
        HK,
        1,
        "Assume ASCII",
        "algorithm",
        "work:reuse",
        (12, 14),
    ),  # fmt: skip
    _idea(
        "tomli",
        "X1-4",
        "relax_dependency",
        SN,
        1,
        f"Use a C parser {KEY}",
        relaxes="new_dependency",
    ),  # fmt: skip
    _idea("tomli", "X1-4", "relax_api", SN, 1, "Change the API", relaxes="api_change"),
    _idea("idna", "X1-0", "eliminate", SN, 1, "Fast | path", "specialised_fast_path"),
]
ARMS = ("A", "X1-0", "X1-1", "X1-2", "X1-3", "X1-4")
X1_IDEAS = {"tomli": dict(zip(ARMS, (5, 5, 9, 6, 7, 0), strict=True)),
            "idna": dict(zip(ARMS, (5, 4, 6, 4, 4, 0), strict=True))}  # fmt: skip
AUDITS: list[Row] = [
    _audit("i01", "A", "Inline lookups", "feasible"),
    _audit("i02", "X1-0", "Cache the parse table", "feasible"),
    _audit("i03", "X1-0", "Memoise tables", "infeasible", "i01"),
    _audit("i04", "X1-2", "Cache parse table", "infeasible", "i02"),
    _audit("i05", "X1-0", "Use a dict", "unknown"),
    _audit("i06", "X1-3", "Stream input", None),
    _audit("i07", "A", "Cache tables", "infeasible", "i02"),  # A repeats X1-0's
    _audit("i08", "X1-0", "Precompute keys", "feasible", in_result=False),
]
TRIALS: list[Row] = [  # Ve's rows as ``SliceRecorder.record`` writes them
    {"experiment": "ideas-slice-trial", "repo": "tomli", "arm": "X1-0",
     "label": "eliminate", "position": 1, "lane": "eliminate", "model": SN,
     "title": "Cache the parse table", "verdict": "keep", "gain_pct": 12.0,
     "floor_pct": 3.0, "guard": "ok", "rationale": ["why"],
     "op_count": {"present": True, "cell": "-20.0%", "base": 10.0, "trial": 8.0,
                  "change": -0.2}},
    {"experiment": "ideas-slice-trial", "repo": "tomli", "arm": "X1-0",
     "label": "obvious", "position": 1, "lane": "obvious", "model": SN,
     "title": "Use a dict", "verdict": "reject", "gain_pct": None,
     "floor_pct": 3.0, "guard": "ok", "rationale": [],
     "op_count": {"present": True, "cell": None, "base": None, "trial": None,
                  "change": None}},
]  # fmt: skip
COMBINE: Row = {  # Ve's combine row, with D64's two columns (asked of Ve)
    "experiment": "ideas-slice-combine", "repo": "tomli", "arm": "X1-0",
    "summary": ["combined 1 ", "of 1"], "cost_usd": 0.6, "kept": 1,
    "gain_pct": 11.0, "floor_pct": 3.0, "guard": "ok", "seeded_calls": 1,
    "seeded_cost_usd": 0.2,
}  # fmt: skip
PROPOSAL: Row = {
    "experiment": "ideas-proposal", "repo": "tomli", "arm": "X1-4",
    "title": f"Use a C parser {KEY}", "lane": "relax_dependency",
    "relaxes": ["new_dependency"], "rationale": ["a compiled ", "parser"],
}  # fmt: skip


def _x1(**override: list[Row]) -> list[Row]:
    probes = [
        _probe(
            repo,
            arm,
            n,
            None if arm == "X1-4" else 1,
            0.5,
            4,
            3 if arm == "X1-2" else 1,
        )
        for repo, by_arm in X1_IDEAS.items()
        for arm, n in by_arm.items()
    ]
    kinds: dict[str, list[Row]] = {
        "ideas": IDEAS, "probes": probes, "audits": AUDITS, "trials": TRIALS,
        "combine": [COMBINE], "proposals": [PROPOSAL], "score": [_score(False)],
        "other": [{"experiment": "ideas-reply", "repo": "tomli", "chunks": []}],
    }  # fmt: skip
    kinds.update(override)
    return [row for rows in kinds.values() for row in rows]


def _e1(tmp: Path, arms: str = "ABCDE", good: int | None = 2) -> Path:
    e1 = tmp / "e1"
    e1.mkdir(exist_ok=True)
    values = {"tomli": {"B": 7, "C": 9, "D": 7}, "idna": {"B": 6, "C": 6, "D": 4}}
    bad = {"tomli": {"B": 1, "C": 0, "D": 2}, "idna": {"B": 1, "C": 1, "D": 1}}
    rows = [_facts("tomli"), _facts("idna")] + [
        _probe(repo, arm, values[repo].get(arm, 5), good, 0.4, 5 if repo == "tomli"
               else 4, bad[repo].get(arm, 0))
        for repo in values
        for arm in arms
    ]  # fmt: skip
    (e1 / "live-results-1.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    return e1


def _write(tmp: Path, rows: list[Row], name: str = "x1.jsonl") -> Path:
    path = tmp / name
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _report(tmp: Path, rows: list[Row] | None = None) -> ir.Report:
    return ir.report_of([_write(tmp, _x1() if rows is None else rows)], _e1(tmp))


# ---------------------------------------------------------------------------
# Section 6.2's measures
# ---------------------------------------------------------------------------


def test_ceiling_is_the_innermost_enclosing_hotspots_share_or_unknown(
    tmp_path: Path,
) -> None:
    facts, _ = ir.load_e1(_e1(tmp_path))
    rows = ir.load_rows([_write(tmp_path, _x1())])
    by_title = {i.title: i for i in rows.ideas}
    tomli = facts["tomli"]
    assert ir.ceiling(by_title["Cache the parse table"], tomli) == pytest.approx(0.1)
    assert ir.ceiling(by_title["Use a dict"], tomli) == pytest.approx(0.5)
    assert ir.ceiling(by_title["Stream input"], tomli) is None  # no hot file
    assert ir.ceiling(by_title["Inline lookups"], tomli) is None  # no target


def test_measures_per_configuration(tmp_path: Path) -> None:
    m = _report(tmp_path).measures
    x0 = m["X1-0"]
    # the returned set: "Precompute keys" (returned False) drops out
    assert (x0.proposed, x0.unique, x0.raw) == (4, 3, 4)  # cache + memoise merged
    assert x0.lane == 5  # every lane-reply idea, the reviewer's removal included
    # memoise repeats A's i01; A's i07 repeats X1-0's i02, which is so not new;
    # i08 is outside the result (in_result False): not audited here
    assert (x0.audited, x0.new, x0.feasible) == (3, 1, 2)
    assert (x0.above, x0.known) == (3, 4)  # idna's 10 % is under its 20 % floor
    assert x0.families == 3
    assert x0.cost_usd == pytest.approx(1.0)
    assert (m["X1-2"].audited, m["X1-2"].new, m["X1-2"].feasible) == (1, 0, 0)
    assert m["X1-3"].audited == 0  # an unreviewed idea is not audited
    assert m["X1-4"].proposed == 0  # proposals are never counted as ideas
    assert m["X1-1"].unique == 2  # its two eliminate ideas share one mechanism
    assert m["A"].new is None  # today's generator is the reference


def test_new_to_today_joins_duplicate_links_either_way_as_the_slice_does(
    tmp_path: Path,
) -> None:
    audits = ir.load_rows([_write(tmp_path, _x1())]).audits
    # i07 (arm A) names X1-0's i02 as its earlier duplicate: i02 is not new
    assert ir.fresh(audits) == {("tomli", "i05"), ("tomli", "i06"), ("tomli", "i08")}
    family = sl.families({str(a["id"]): sl._AuditRow.model_validate(a) for a in AUDITS})
    taken = {family[str(a["id"])] for a in AUDITS if a["arm"] == "A"}
    assert {i for _, i in ir.fresh(audits)} == {
        i for i, f in family.items() if f not in taken
    }
    broken = _audit("i09", "X1-0", "Loose", "infeasible", "i99")  # no such id
    cycle = [_audit("i10", "X1-3", "P", "infeasible", "i11"),
             _audit("i11", "X1-3", "Q", "infeasible", "i10")]  # fmt: skip
    rows = ir.load_rows([_write(tmp_path, _x1(audits=[broken, *cycle]))])
    assert ir.fresh(rows.audits) == {("tomli", i) for i in ("i09", "i10", "i11")}


def test_the_measures_file_states_its_population_and_the_missing_band(
    tmp_path: Path,
) -> None:
    text = ir.render(_report(tmp_path))["measures.md"]
    assert "returned" in text and "in_result" in text and "lane ideas" in text
    assert "no A/A band" in text and "provisional" in text
    x0 = next(r for r in text.splitlines() if r.startswith("| X1-0 | 4 | 5 |"))
    assert "1/3" in x0  # new to today's generator, of audited


def test_the_raw_count_shows_until_the_dedupe_passes(tmp_path: Path) -> None:
    failed = ir.render(_report(tmp_path))["measures.md"]
    assert "raw titles" in failed and "agreement 50.0" in failed
    rows = _x1(score=[_score(True)])
    passed = ir.render(_report(tmp_path, rows))["measures.md"]
    assert "raw titles" not in passed and "passed the fixed bar" in passed


def test_x1_4_proposals_are_counted_by_rule_with_no_score(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report.proposals == {"api_change": 1, "new_dependency": 1}
    text = ir.render(report)["measures.md"]
    section = text[text.index("## X1-4 proposals") :]
    assert "new_dependency | 1" in section and "score" in section


# ---------------------------------------------------------------------------
# One file per library and configuration
# ---------------------------------------------------------------------------


def test_one_markdown_file_per_library_and_configuration(tmp_path: Path) -> None:
    files = ir.render(_report(tmp_path))
    per = {name for name in files if name.count("-") and name.endswith(".md")}
    assert {f"tomli-{a}.md" for a in ARMS} | {f"idna-{a}.md" for a in ARMS} <= per
    x0 = files["tomli-X1-0.md"]
    for part in ("Cache the parse table", "precompute_or_cache", "20-25",
                 "feasible", "keep", "12.0% / 3.0%", "-20.0%", "eliminate", SN):  # fmt: skip
        assert part in x0, part
    memo = next(line for line in x0.splitlines() if "Memoise tables" in line)
    assert "Inline lookups" in memo  # duplicate-of names the idea, not its id
    x4 = files["tomli-X1-4.md"]
    assert "## Proposals" in x4 and "a compiled parser" in x4
    assert x4.index("## Proposals") < x4.index("Change the API")


def test_model_text_is_redacted_and_inert(tmp_path: Path) -> None:
    files = ir.render(_report(tmp_path))
    assert all(KEY not in text for text in files.values())
    assert "\\[redacted\\]" in files["tomli-X1-4.md"]  # escaped as markdown
    idna = files["idna-X1-0.md"]
    assert "Fast | path" not in idna and "Fast \\| path" in idna


# ---------------------------------------------------------------------------
# The four comparison tables
# ---------------------------------------------------------------------------


def test_table_1_mechanism_by_configuration_overlap(tmp_path: Path) -> None:
    clusters = _report(tmp_path).overlap
    cache = next(c for c in clusters if "Cache the parse table" in c.titles)
    assert cache.counts == {"X1-0": 2, "X1-1": 2, "X1-2": 1}
    stream = next(c for c in clusters if c.titles == ("Stream input",))
    assert stream.counts == {"X1-3": 1}
    assert all(c.counts.keys() <= set(ARMS) - {"A"} for c in clusters)
    tables = ir.render(_report(tmp_path))["tables.md"]
    assert "only X1-3" in tables


def test_table_2_model_by_lens_from_the_square(tmp_path: Path) -> None:
    square = _report(tmp_path).square
    assert square[(S5, "eliminate")] == (2, 1, 2)
    assert square[(HK, "assume_less")] == (1, 1, 1)
    assert (SN, "eliminate") not in square  # only X1-1's lenses
    tables = ir.render(_report(tmp_path))["tables.md"]
    assert "2/1/2" in tables


def test_table_3_ceiling_quantiles_and_a_deterministic_plot(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report.margins["X1-0"] == pytest.approx((-0.1, 0.08, 0.08, 0.48))
    assert ir.quantiles((0.0, 1.0, 2.0, 3.0, 4.0)) == (0.0, 1.0, 2.0, 3.0, 4.0)
    assert ir.quantiles((0.5,)) == (0.5,) * 5
    assert ir.quantiles(()) is None
    one, two = ir.render(report)["ceilings.svg"], ir.render(_report(tmp_path))
    assert one == two["ceilings.svg"] and one.startswith("<svg")
    assert "<script" not in one and "href" not in one and "@import" not in one
    assert "X1-0" in one and "floor" in one


def test_table_4_every_levers_delta_beside_the_noise(tmp_path: Path) -> None:
    deltas = _report(tmp_path).deltas
    # spread: tomli {7, 9, 7, X1-0's 5} = 4, idna {6, 6, 4, 4} = 2, mean 3
    assert deltas[("X1-1", "ideas")] == pytest.approx((3.0, 3.0))
    assert deltas[("X1-2", "ideas")] == pytest.approx((0.5, 3.0))
    no_good, good_spread = deltas[("X1-4", "good")]
    assert no_good is None and good_spread == pytest.approx(1.0)
    # feasible = audited - auditor_infeasible; spread: tomli {4, 5, 3, X1-0's 3}
    # = 2, idna {3, 3, 3, 3} = 0, mean 1; X1-2's 1 less X1-0's 3 = -2
    assert deltas[("X1-2", "feasible")] == pytest.approx((-2.0, 1.0))
    assert deltas[("X1-1", "feasible")] == pytest.approx((0.0, 1.0))
    # no band offline (E1 has no ideas-idea rows): the lever's delta alone
    unique, new = deltas[("X1-2", "unique")], deltas[("X1-2", "new")]
    assert unique[0] == pytest.approx(-1.0) and unique[1] is None  # 1-2, 0-1
    assert new[0] == pytest.approx(-0.5) and new[1] is None  # 0-1, 0-0
    assert {m for _, m in deltas} >= {"above", "families"}
    tables = ir.render(_report(tmp_path))["tables.md"]
    lines = tables.splitlines()
    row = next(r for r in lines if r.startswith("| X1-1 | ideas"))
    assert "inside" in row
    assert "beyond" in next(r for r in lines if r.startswith("| X1-2 | feasible"))
    row = next(r for r in lines if r.startswith("| X1-2 | unique"))
    assert "-1.00" in row and "no A/A band" in row


def test_e1_without_arms_b_c_d_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="arms B, C and D"):
        ir.report_of([_write(tmp_path, _x1())], _e1(tmp_path, arms="AE"))


def test_a_measure_e1_never_recorded_has_no_band(tmp_path: Path) -> None:
    report = ir.report_of([_write(tmp_path, _x1())], _e1(tmp_path, good=None))
    assert report.deltas[("X1-1", "good")] == (0.0, None)  # X1-0's value alone
    row = next(r for r in ir.render(report)["tables.md"].splitlines()
               if r.startswith("| X1-1 | good"))  # fmt: skip
    assert "no A/A band" in row


def test_e1_facts_recorded_twice_are_refused(tmp_path: Path) -> None:
    e1 = _e1(tmp_path)
    (e1 / "live-results-2.jsonl").write_text(json.dumps(_facts("idna")) + "\n")
    with pytest.raises(ValueError, match="facts for idna recorded twice"):
        ir.load_e1(e1)


# ---------------------------------------------------------------------------
# Cost, the seeded column
# ---------------------------------------------------------------------------


def test_cost_per_configuration_with_the_seeded_column(tmp_path: Path) -> None:
    costs = _report(tmp_path).costs
    x0 = costs["X1-0"]
    assert (x0.idea_usd, x0.slice_usd) == pytest.approx((1.0, 0.6))
    assert (x0.seeded_calls, x0.wins) == (1, 1)
    assert x0.seeded_usd == pytest.approx(0.2)
    assert x0.per_win == pytest.approx(0.6)
    x2 = costs["X1-2"]
    assert (x2.seeded_calls, x2.seeded_usd, x2.wins, x2.per_win) == (0, 0.0, 0, None)
    no_slice = _report(tmp_path, _x1(trials=[], combine=[])).costs["X1-0"]
    assert (no_slice.seeded_calls, no_slice.seeded_usd) == (0, 0.0)
    measures = ir.render(_report(tmp_path))["measures.md"]
    assert "seeded calls" in measures and "seeded USD" in measures
    assert "not recorded" not in measures
    row = next(r for r in measures.splitlines() if r.startswith("| X1-0 | 1.0000"))
    assert "| 1 | 0.2000 |" in row


@pytest.mark.parametrize("field", ["seeded_calls", "seeded_cost_usd"])
def test_a_combine_row_without_d64s_seeded_columns_is_refused(
    tmp_path: Path, field: str
) -> None:
    bare = {k: v for k, v in COMBINE.items() if k != field}
    with pytest.raises(ValueError, match=f"malformed ideas-slice-combine.*{field}"):
        _report(tmp_path, _x1(combine=[bare]))


# ---------------------------------------------------------------------------
# The owner-read sample
# ---------------------------------------------------------------------------


def test_the_sample_is_a_seeded_draw_across_configurations_lanes_and_models(
    tmp_path: Path,
) -> None:
    ideas = ir.load_rows([_write(tmp_path, _x1())]).ideas
    small = ir.owner_sample(ideas, seed=7, size=4)
    assert small == ir.owner_sample(tuple(reversed(ideas)), seed=7, size=4)
    assert len({(i.arm, i.lane, i.model) for i in small}) == 4
    assert all(i.arm != "A" and not i.proposal for i in small)
    every = ir.owner_sample(ideas, size=ir.SAMPLE_SIZE)
    assert all(i.returned for i in every)  # the configurations' results only
    assert len(every) == 9  # the pool is smaller than the sample
    assert ir.SAMPLE_SIZE in range(20, 31)


def test_the_sample_hides_its_source_and_the_key_maps_it_back(tmp_path: Path) -> None:
    files = ir.render(_report(tmp_path))
    sample = files["owner-sample.md"]
    for hidden in ("X1-", SN, S5, HK, "eliminate", "assume_less"):
        assert hidden not in sample, hidden
    key = json.loads(files["owner-sample-key.json"])
    assert sorted(key) == [f"S{k:02d}" for k in range(1, 10)]
    assert all(set(v) == {"repo", "arm", "lane", "model", "label", "position"}
               for v in key.values())  # fmt: skip
    first = key["S01"]
    assert f"S01 | {first['repo']}" in sample


# ---------------------------------------------------------------------------
# Refusals, determinism, the CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"ideas": []}, "no ideas-idea row"),
        ({"probes": []}, "no ideas-probe row"),
        ({"score": []}, "no ideas-validate-score row"),
        ({"score": [_score(True), _score(False)]}, "ideas-validate-score.*twice"),
        ({"other": [_probe("tomli", "A", 1, 1, 0.1)]}, "ideas-probe.*tomli A twice"),
        ({"other": [{**_probe("tomli", "B", 1, 1, 0.1)}]}, "not an X1 arm"),
        ({"other": [_idea("mistune", "X1-0", "far", SN, 1, "x")]}, "no facts"),
        ({"other": [{"experiment": "ideas-idea", "repo": "tomli"}]}, "malformed"),
        ({"other": [{**IDEAS[1], "mechanism": "magic"}]}, "malformed"),
        ({"other": [{**TRIALS[0], "gain_pct": "big"}]}, "malformed"),
    ],
)
def test_a_missing_or_malformed_row_kind_is_refused(
    tmp_path: Path, override: dict[str, list[Row]], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _report(tmp_path, _x1(**override))


def test_a_line_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, _x1())
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="x1.jsonl:.*not JSON"):
        ir.report_of([path], _e1(tmp_path))


def test_the_cli_writes_byte_identical_files_in_other_processes(
    tmp_path: Path,
) -> None:
    results, e1 = _write(tmp_path, _x1()), _e1(tmp_path)
    outs = []
    for seed in ("0", "12345"):
        out = tmp_path / f"out-{seed}"
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": f"{SERVICE / 'src'}:{SERVICE / 'tests'}"}  # fmt: skip
        done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            [sys.executable, "-m", "live.ideas_report", str(results),
             "--e1", str(e1), "--out", str(out)],
            cwd=SERVICE / "tests", env=env, capture_output=True, text=True,
            check=False, timeout=120,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        outs.append({p.name: p.read_bytes() for p in sorted(out.iterdir())})
    assert outs[0] == outs[1]
    assert {"measures.md", "tables.md", "ceilings.svg", "owner-sample.md",
            "owner-sample-key.json", "tomli-X1-0.md"} <= set(outs[0])  # fmt: skip


def test_the_cli_reports_a_refusal_and_exits_2(tmp_path: Path) -> None:
    lines: list[str] = []
    path = _write(tmp_path, _x1(ideas=[]))
    code = ir.main([str(path), "--e1", str(_e1(tmp_path)),
                    "--out", str(tmp_path / "o")], echo=lines.append)  # fmt: skip
    assert code == 2 and "no ideas-idea row" in lines[0]
    assert not (tmp_path / "o").exists()


def test_main_writes_into_the_out_directory(tmp_path: Path) -> None:
    lines: list[str] = []
    out = tmp_path / "x1"
    code = ir.main([str(_write(tmp_path, _x1())), "--e1", str(_e1(tmp_path)),
                    "--out", str(out)], echo=lines.append)  # fmt: skip
    assert code == 0 and (out / "measures.md").is_file()
    assert lines == [f"wrote {len(list(out.iterdir()))} files to {out}"]
    assert ir.REPORT_DIR.parts[-3:] == ("step3", "idea-lab", "x1")


def test_the_report_sends_nothing() -> None:
    source = (TESTS_DIR / "live" / "ideas_report.py").read_text(encoding="utf-8")
    for forbidden in ("transport", "call(", "Anthropic", "httpx", "urllib"):
        assert forbidden not in source, forbidden


def test_the_committed_e1_results_load_as_the_noise_and_the_facts() -> None:
    facts, noise = ir.load_e1(ir.E1_DIR)
    assert sorted(facts) == sorted(ip.E1_REPOS)
    assert sorted({(p.repo, p.arm) for p in noise}) == sorted(
        (repo, arm) for repo in ip.E1_REPOS for arm in ir.NOISE_ARMS
    )
