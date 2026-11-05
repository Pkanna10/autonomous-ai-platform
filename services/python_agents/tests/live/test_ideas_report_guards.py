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

import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
)
from autonomous_ai_agents.optimization import idea_dedupe as dd
from autonomous_ai_agents.optimization.idea_types import FunctionSpan, Lane

from . import ideas_marker as im
from . import ideas_pool as ipool
from . import ideas_probe as ip
from . import ideas_report as ir
from . import ideas_slice as sl
from .conftest import TESTS_DIR, LiveRun
from .corpus import RESULTS_ENV
from .discovery import FABLE, OPUS, SONNET
from .discovery_io import ResultsSink

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
    audited: int = 0, bad: int = 0, **later: object,
) -> Row:  # fmt: skip
    """``later``: fields E1's rows predate (good_corrected, good_strict)."""
    return {"experiment": "ideas-probe", "repo": repo, "arm": arm, "ideas": ideas,
            "non_obvious": max(ideas - 2, 0), "good": good, "cost_usd": usd,
            "audited": audited, "auditor_infeasible": bad,
            "models": ["m"], "stats": None, **later}  # fmt: skip


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
        same_pairs=5, same_merged=5 if passed else 0, different_pairs=5,
        different_merged=0,
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
     "grader": "opus-5-5", "grader_validated": True,
     "op_count": {"present": True, "cell": "-20.0%", "base": 10.0, "trial": 8.0,
                  "change": -0.2}},
    {"experiment": "ideas-slice-trial", "repo": "tomli", "arm": "X1-0",
     "label": "obvious", "position": 1, "lane": "obvious", "model": SN,
     "title": "Use a dict", "verdict": "reject", "gain_pct": None,
     "floor_pct": 3.0, "guard": "ok", "rationale": [],
     "grader": "opus-5-5", "grader_validated": True,
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
            good_corrected=None if arm == "X1-4" else 2,
            good_strict=None if arm in ("A", "X1-4") else 1,
        )
        for repo, by_arm in X1_IDEAS.items()
        for arm, n in by_arm.items()
    ]
    kinds: dict[str, list[Row]] = {
        "ideas": IDEAS, "probes": probes, "audits": AUDITS, "trials": TRIALS,
        "combine": [COMBINE], "proposals": [PROPOSAL], "score": [_score(False)],
        "other": [{"experiment": "ideas-reply", "repo": "tomli", "arm": "A",
                   "role": "generator", "label": "generator", "sent": True,
                   "usage": [900, 300, 0, 0], "chunks": []}],
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
    # O43: the corrected and strict counts, never the as-coded one; E1's rows
    # predate both, so neither has an A/A band
    assert ("X1-1", "good") not in deltas
    assert deltas[("X1-4", "good_corrected")] == (None, None)
    assert deltas[("X1-1", "good_corrected")] == (0.0, None)
    assert deltas[("X1-1", "good_strict")] == (0.0, None)
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
    rows = [{**r, "good_corrected": 3} if r["experiment"] == "ideas-probe" else r
            for r in _x1()]  # fmt: skip
    e1 = _e1(tmp_path, good=None)
    report = ir.report_of([_write(tmp_path, rows)], e1)
    assert report.deltas[("X1-1", "good_corrected")] == (0.0, None)  # X1-0's alone
    row = next(r for r in ir.render(report)["tables.md"].splitlines()
               if r.startswith("| X1-1 | good_corrected"))  # fmt: skip
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


# ---------------------------------------------------------------------------
# O39: the marker-feasible headline, the unvalidated grades, the dedupe's bound
# ---------------------------------------------------------------------------

O55, O5 = "claude-opus-5-5", "claude-opus-5"
UPPER = "upper bound, the dedupe under-merges (O39)"
LEAP = _idea("tomli", "X1-0", "leap", O55, 1, "Leap idea")
LENS_55 = _idea("tomli", "X1-1", "far", O55, 1, "Opus lens idea")  # X1-1's Opus lens
LEAP_TRIAL: Row = {**TRIALS[0], "label": "leap", "lane": "leap", "model": O55,
                   "title": "Leap idea", "grader": "opus-5",
                   "grader_validated": False}  # fmt: skip
VALIDATION = SERVICE.parents[1] / ".claude/handoff/step3/idea-lab/x1-validation"


# O40/O41's pooled tournament, as ``ideas_pool.rank_library`` writes it (the
# pool guards read the module's own rows through ``_parsed``): tomli's lens-lane
# results (X1-0 to X1-3), X1-1's Opus 5.5 lens apart from the Opus 5.5 ranking
MEMBERS = {"p1a": ("X1-0", "eliminate", 1), "p2b": ("X1-0", "far", 1),
           "p3c": ("X1-2", "eliminate", 1), "p4d": ("X1-3", "far", 1),
           "p5e": ("X1-1", "eliminate", 1), "p6f": ("X1-1", "eliminate", 2),
           "p7g": ("X1-1", "assume_less", 1)}  # fmt: skip
OWN = {"p8h": ("X1-1", "far", 1)}  # LENS_55, written by Opus 5.5


def _set(marker: str, rnd: int, k: int, of: int, shown: list[str],
         order: list[str] | None) -> Row:  # fmt: skip
    name = f"{marker}-r{rnd}-s{k}"
    return {"experiment": "ideas-pool-set", "repo": "tomli", "marker": marker,
            "model": O55 if marker == "opus-5-5" else O5,
            "validated": marker == "opus-5-5", "round": rnd, "set": k, "of": of,
            "name": name, "ids": sorted(shown), "seed": f"20261103:tomli:1:{name}",
            "shown": shown, "order": order,
            "advanced": [] if order is None or of == 1 else order[:2],
            "error": None, "cost_usd": 0.02, "counted": 900, "sent": True,
            "chunks": []}  # fmt: skip


def _keys(ids: Mapping[str, tuple[str, str, int]], with_id: bool = True) -> list[Row]:
    return [{**({"id": i} if with_id else {}), "arm": a, "label": label, "position": n}
            for i, (a, label, n) in ids.items()]  # fmt: skip


def _result(marker: str, members: Mapping[str, tuple[str, str, int]],
            apart: Mapping[str, tuple[str, str, int]], top: list[str] | None,
            requests: int = 3, rounds: int = 2) -> Row:  # fmt: skip
    return {"experiment": "ideas-pool-result", "repo": "tomli", "marker": marker,
            "model": O55 if marker == "opus-5-5" else O5,
            "validated": marker == "opus-5-5", "members": _keys(members),
            "apart": _keys(apart, False), "top": top, "counts": None,
            "requests": requests, "rounds": rounds, "max_shown": 4}  # fmt: skip


SETS: list[Row] = [
    _set("opus-5-5", 1, 1, 2, ["p3c", "p1a", "p4d", "p2b"], ["p4d", "p1a", "p3c", "p2b"]),
    _set("opus-5-5", 1, 2, 2, ["p6f", "p7g", "p5e"], ["p7g", "p5e", "p6f"]),
    _set("opus-5-5", 2, 1, 1, ["p5e", "p1a", "p7g", "p4d"], ["p5e", "p1a", "p7g", "p4d"]),
    _set("opus-5", 1, 1, 2, ["p1a", "p2b", "p3c", "p4d"], ["p1a", "p2b", "p3c", "p4d"]),
    _set("opus-5", 1, 2, 2, ["p5e", "p6f", "p7g", "p8h"], ["p8h", "p6f", "p5e", "p7g"]),
    _set("opus-5", 2, 1, 1, ["p1a", "p2b", "p6f", "p8h"], ["p8h", "p2b", "p1a", "p6f"]),
]  # fmt: skip
TOP_55, TOP_5 = ["p5e", "p1a", "p7g"], ["p8h", "p2b", "p1a"]
RESULTS: list[Row] = [
    _result("opus-5-5", MEMBERS, OWN, TOP_55),
    _result("opus-5", {**MEMBERS, **OWN}, {}, TOP_5),
]
OLD_MARKER: Row = {  # O39's within-set row: no longer read
    "experiment": "ideas-slice-marker", "repo": "tomli", "arm": "X1-0",
    "marker": "opus-5-5", "shown": [], "grades": [], "scores": None,
    "validated": True,
}  # fmt: skip


def _pooled(**override: list[Row]) -> list[Row]:
    return _x1(**{"other": [LEAP, LENS_55, OLD_MARKER], "pool": [*SETS, *RESULTS],
                  **override})  # fmt: skip


def _section(report: ir.Report) -> str:
    """The marker section alone: up to the next section (V-rep's)."""
    text = ir.render(report)["measures.md"]
    text = text[text.index("## Marker-feasible") :]
    return text[: text.index("\n## ")]


def test_the_pooled_counts_validated_with_opus_5s_unvalidated_beside(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path, _pooled())
    (validated, other) = report.pools["tomli"]
    assert (validated.marker, validated.validated) == ("opus-5-5", True)
    assert validated.counts() == {"X1-0": 1, "X1-1": 2, "X1-2": 0, "X1-3": 0}
    assert other.counts() == {"X1-0": 2, "X1-1": 1, "X1-2": 0, "X1-3": 0}
    assert sum((validated.counts() or {}).values()) == 3 == ir.MARKER_TOP == ipool.TOP
    relaxing = {lane.value for lane in Lane if lane.value.startswith("relax_")}
    assert not set(ir.LENSES) & {"obvious", "leap", *relaxing} and len(relaxing) == 4
    lines = _section(report).splitlines()
    assert ("| library | ranked by | X1-0 | X1-1 | X1-2 | X1-3 | pooled | not ranked "
            "(the marker's own model) | requests | rounds |") in lines  # fmt: skip
    assert "| tomli | opus-5-5 (validated) | 1 | 2 | 0 | 0 | 7 | 1 | 3 | 2 |" in lines
    assert ("| tomli | opus-5 (unvalidated) | 2 unvalidated | 1 unvalidated | "
            "0 unvalidated | 0 unvalidated | 8 | 0 | 3 | 2 |") in lines  # fmt: skip
    assert (
        "| all libraries | opus-5-5 (validated) | 1 | 2 | 0 | 0 | 7 | 1 | 3 | 2 |"
        in lines
    )
    assert not any(x.startswith(("| A |", "| X1-4 |")) for x in lines)


def test_the_full_tournament_record_and_the_own_model_ideas_apart(
    tmp_path: Path,
) -> None:
    section = _section(_report(tmp_path, _pooled()))
    lines = section.splitlines()
    assert "### tomli" in lines
    assert ("#### Ranked by opus-5-5 (claude-opus-5-5), validated: 7 ideas, 3 "
            "requests in 2 rounds") in lines  # fmt: skip
    assert ("#### Ranked by opus-5 (claude-opus-5), unvalidated: 8 ideas, 3 "
            "requests in 2 rounds") in lines  # fmt: skip
    assert "| 1 | p5e | Skip work | X1-1 | eliminate | claude-sonnet-5 |" in lines
    assert ("| 1 | 1 | p3c, p1a, p4d, p2b | 20261103\\:tomli\\:1\\:opus-5-5-r1-s1 | "
            "p4d, p1a, p3c, p2b | p4d, p1a |") in lines  # fmt: skip
    assert ("| 2 | 1 | p5e, p1a, p7g, p4d | 20261103\\:tomli\\:1\\:opus-5-5-r2-s1 | "
            "p5e, p1a, p7g, p4d | final, the top 3 |") in lines  # fmt: skip
    assert "| p8h | Opus lens idea | X1-1 | far | claude-opus-5-5 |" in lines
    head = section.index("#### Ranked by opus-5-5")
    apart = section.index("Not ranked (written by claude-opus-5-5, the marker's own")
    assert head < apart < section.index("#### Ranked by opus-5 (")
    assert section.count("none") >= 1  # Opus 5 ranked the whole pool: none apart


def test_the_note_says_tournament_and_the_validated_set_size(tmp_path: Path) -> None:
    section = _section(_report(tmp_path, _pooled()))
    assert "a tournament, not one ranking of the whole pool" in section
    assert ("Every request showed 3 to 4 ideas, at most 6: the set size the "
            "marker was validated on (Vb's 48 scored sets: 3 to 8 ideas, 4.6 on "
            "average)") in section  # fmt: skip
    assert "S1, the leap or the rule-relaxing lanes" in section
    assert (
        "(opus-5 failed O37)" in section and "X1-1 has a comparable number" in section
    )
    assert (
        (ir.SET_SIZE, ir.VB_SETS) == (ipool.SET_SIZE, ipool.VB_SETS) == (6, (3, 8, 4.6))
    )


def test_the_within_set_version_and_its_columns_are_gone(tmp_path: Path) -> None:
    report = _report(tmp_path, _pooled())
    assert not hasattr(ir, "MarkerLine") and not hasattr(report, "marked")
    assert "ideas-slice-marker" not in ir._KINDS
    text = ir.render(report)["measures.md"]
    for old in ("lens lanes (headline, validated grades)", "all lanes (validated)",
                "of its shown set", "graded by a marker that failed O37"):  # fmt: skip
        assert old not in text, old


def test_without_a_pool_row_there_is_no_marker_feasible_count(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    assert report.pools == {}
    assert "no marker-feasible count" in ir.render(report)["measures.md"]
    stopped = _report(tmp_path, _pooled(pool=[*SETS[:3], SETS[3], {
        **SETS[4], "order": None, "advanced": [], "error": "BudgetExceeded: x"},
        RESULTS[0], {**RESULTS[1], "top": None, "requests": 2, "rounds": 1}]))  # fmt: skip
    lines = _section(stopped).splitlines()
    assert "| tomli | opus-5 (unvalidated) | - | - | - | - | 8 | 0 | 2 | 1 |" in lines
    assert any("no order (BudgetExceeded\\: x), the tournament stopped" in x
               for x in lines)  # fmt: skip


def test_a_pool_of_one_idea_needs_no_request_and_is_its_own_top(
    tmp_path: Path,
) -> None:
    one = _result("opus-5-5", {"p1a": MEMBERS["p1a"]}, {}, ["p1a"], 0, 0)
    report = _report(tmp_path, _pooled(pool=[one]))
    (pool,) = report.pools["tomli"]
    assert pool.sets == () and pool.counts() == {"X1-0": 1, "X1-1": 0, "X1-2": 0,
                                                 "X1-3": 0}  # fmt: skip
    section = _section(report)
    assert "No set request was sent." in section
    assert "| tomli | opus-5-5 (validated) | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |" in section


def test_an_opus_5_5_idea_graded_by_opus_5_is_unvalidated_in_its_file(
    tmp_path: Path,
) -> None:
    files = ir.render(_report(tmp_path, _pooled(trials=[*TRIALS, LEAP_TRIAL])))
    lines = files["tomli-X1-0.md"].splitlines()
    leap = next(x for x in lines if "Leap idea" in x)
    assert "| keep (graded by opus-5, unvalidated) |" in leap
    assert sum("unvalidated" in x for x in lines) == 1
    validated = ir.TrialLine.model_validate({k: v for k, v in TRIALS[0].items()
                                             if k in ir.TrialLine.model_fields})  # fmt: skip
    assert ir.trial_cell(validated) == "keep"
    fallback = validated.model_copy(update={"grader": None, "grader_validated": None})
    assert ir.trial_cell(fallback) == "keep"


_OBVIOUS = {"p0z": ("X1-0", "obvious", 1)}
_X1_4 = {"p0z": ("X1-4", "relax_api", 1)}
_GONE = {"p0z": ("X1-3", "far", 9)}


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"trials": [{k: v for k, v in TRIALS[0].items()
                      if k != "grader_validated"}]}, "malformed.*grader_validated"),
        ({"trials": [{**TRIALS[0], "grader": None}]}, "malformed.*grader"),
        ({"pool": [*SETS, _result("opus-5-5", {**MEMBERS, **_GONE}, OWN, TOP_55),
                   RESULTS[1]]}, "far #9: a pooled idea with no ideas-idea row"),
        ({"pool": [*SETS, _result("opus-5-5", {**MEMBERS, **_OBVIOUS}, OWN,
                                  TOP_55), RESULTS[1]]},
         "not a lens-lane idea of X1-0 to X1-3"),
        ({"pool": [*SETS, _result("opus-5-5", {**MEMBERS, **_X1_4}, OWN,
                                  TOP_55), RESULTS[1]]}, "not one of X1-0"),
        ({"pool": [*SETS, _result("opus-5-5", {**MEMBERS, **OWN}, {}, TOP_55),
                   RESULTS[1]]}, "written by the marker's own model"),
        ({"pool": [*SETS, RESULTS[0], _result("opus-5", MEMBERS, OWN, TOP_5)]},
         "listed apart but not the marker's model"),
        ({"pool": [*SETS, _result("opus-5-5", MEMBERS, OWN, ["p1a", "p5e", "p7g"]),
                   RESULTS[1]]}, "not the final set's"),
        ({"pool": [*SETS, *RESULTS, RESULTS[0]]}, "opus-5-5 twice"),
        ({"pool": [*SETS[:2], {**SETS[2], "order": ["p5e"]}, *SETS[3:], *RESULTS]},
         "malformed ideas-pool-set"),
        ({"pool": [*SETS[:2], _set("opus-5-5", 2, 1, 1, [*MEMBERS][:7],
                                   [*MEMBERS][:7]), *SETS[3:], *RESULTS]},
         "past the validated set size"),
        ({"pool": [{**SETS[0], "repo": "flask"}, *SETS[1:], *RESULTS]}, "not one of the 8"),
        ({"pool": [{**SETS[0], "titles": ["one"]}, *SETS[1:], *RESULTS]},
         "the titles are not one per id"),
        ({"pool": [{**SETS[0], "advanced": ["p1a", "p4d"]}, *SETS[1:], *RESULTS]},
         "advanced is not the order's top two"),
        ({"pool": [*SETS, RESULTS[0], {**RESULTS[1], "top": None}]}, "not the final"),
        ({"pool": [_result("opus-5-5", {"p1a": MEMBERS["p1a"]}, {}, None, 0, 0)]},
         "not the final"),  # one idea, no request: its top is that idea
    ],
)  # fmt: skip
def test_a_malformed_or_inconsistent_row_is_refused(
    tmp_path: Path, override: dict[str, list[Row]], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _report(tmp_path, _pooled(**override))


def test_the_upper_bound_labels_sit_where_the_two_measures_appear(
    tmp_path: Path,
) -> None:
    files = ir.render(_report(tmp_path))  # Vc's score: failed by under-merging
    measures = files["measures.md"]
    assert measures.count(UPPER) == 2
    head = next(x for x in measures.splitlines()
                if x.startswith("| configuration | ideas proposed"))  # fmt: skip
    assert f"unique mechanisms ({UPPER}) | raw titles |" in head  # the raw count
    assert f"new to today's generator ({UPPER})" in head
    tables = files["tables.md"]
    assert tables.count(UPPER) == 2 + 2 + 2 * len(ir.LEVERS)  # 2b's two (O42)
    assert f"## 1 Mechanism x configuration overlap ({UPPER})" in tables
    assert f"unique mechanisms ({UPPER})/ceilings" in tables
    for lever in ir.LEVERS:
        for m in ("unique", "new"):
            assert f"| {lever} | {m} ({UPPER}) |" in tables, (lever, m)
    libraries = {n: t for n, t in files.items() if n.startswith(("tomli-", "idna-"))}
    assert len(libraries) == 12 and all(t.count(UPPER) == 1 for t in libraries.values())
    assert UPPER not in files["owner-sample.md"] + files["ceilings.svg"]
    assert "10 labelled pairs are the dedupe's development set" in measures
    passed = ir.render(_report(tmp_path, _x1(score=[_score(True)])))
    for name, text in passed.items():
        assert "upper bound" not in text and "development set" not in text, name


def _scored(**update: object) -> dd.DedupeScore:
    failed = _score(False)["score"]
    assert isinstance(failed, dict)
    return dd.DedupeScore.model_validate({**failed, **update})


def test_the_bound_is_read_from_vcs_score_row(tmp_path: Path) -> None:
    real = ir._parsed(list(VALIDATION.glob("ideas-validate-*.jsonl")),
                      ["ideas-validate-score"])["ideas-validate-score"]  # fmt: skip
    (row,) = [r for r in real if isinstance(r, ir.DedupeLine)]
    assert row.score is not None and row.score.labelled == 380
    assert ir.bound(row.score) == UPPER  # 42 of 116 merged, 2.3 % different
    over = _scored(same_merged=5, different_merged=2, different_merged_share=0.4)
    both = _scored(different_merged=2, different_merged_share=0.4)
    assert ir.bound(over) == "lower bound, the dedupe over-merges"
    assert ir.bound(both) == "unvalidated, the dedupe failed its bar"
    assert ir.bound(None) == "unvalidated, no pair labelled"
    assert ir.bound(_scored(passed=True, show_raw=False)) is None


GOLDEN = {  # sha256 of HEAD 2c3f76b's render on these fixtures, in this view
    "failed": "8a2764d5cc49a6d90ae52a780695facaef77ce2024843b967283007b29680a66",
    "passed": "dc53fb3ec5153003723eb8a34885441b13eddfbfe1b857344f2d938ad0e052e3",
}  # (8633ee3's, before V-rep's view: fd2abae2... and 3b70392f...)
_GOOD_ROW = re.compile(r"\| X1-\d \| good")  # Table 4's good rows (O43 swapped them)


def _head_view(files: Mapping[str, str]) -> str:
    """O39's, V-rep's and V-rep3's additions taken out: the bound tags, the
    note, source and extents lines (each with its blank line), everything
    from the marker section on in measures.md, Table 2b, the wins by lane
    and Table 4's good rows (as coded at HEAD; corrected and strict now)."""
    out = {}
    notes = (*ir.NOTE_PREFIXES, "Sources (O44): ", "Extents: ")
    for name, text in files.items():
        text = text.replace(f" ({UPPER})", "")
        for cut in ("\n## Marker-feasible", "\n## Slice wins by lane"):
            text = text[: text.index(cut)] if cut in text else text
        if "\n## 2b " in text:
            text = text[: text.index("\n## 2b ")] + text[text.index("\n## 3 ") :]
        lines = text.split("\n")
        keep = [x for k, x in enumerate(lines)
                if not x.startswith(notes) and not _GOOD_ROW.match(x)
                and not (k and lines[k - 1].startswith(notes))]  # fmt: skip
        out[name] = "\n".join(keep)
    return hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize("score", ["failed", "passed"])
def test_every_other_number_is_heads(tmp_path: Path, score: str) -> None:
    rows = _x1(score=[_score(score == "passed")])
    assert _head_view(ir.render(_report(tmp_path, rows))) == GOLDEN[score]


# ---------------------------------------------------------------------------
# V-rep (O42, O43, O44): good counts, self/cross, X1-1's cost, the sources
# ---------------------------------------------------------------------------

RUN1 = (SERVICE.parents[1] / ".claude/handoff/step3/idea-lab/x1"
        / "ideas-probe-x1-run1-41679255224.jsonl")  # fmt: skip
SCORE = next(VALIDATION.glob("ideas-validate-*.jsonl"))  # Vc's one score row
POOLED = ("X1-0", "X1-1", "X1-2", "X1-3")
HANDED_ON = "what the arm handed on (in-result rows)"
GENERATED = "every idea the lanes generated (all audit rows)"
FABLE_5, FABLE_51 = ip.FABLE_5, FABLE


def _lines(path: Path) -> list[Row]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run1(*more: Path, **swap: Path) -> ir.Report:
    return ir.report_of([RUN1, SCORE, *more], ir.E1_DIR, **swap)


def _sums(by: Mapping[tuple[str, str], Counter[str]], kind: str) -> tuple[int, ...]:
    return tuple(sum(c[kind] for (_, a), c in by.items() if a == arm) for arm in POOLED)


def test_run_1s_self_and_cross_repeats_within_each_library() -> None:
    """O44's figures: one link per audit row, its target looked up in its own
    library, self when the target is the same arm's."""
    report = _run1()
    every, handed = report.repeats[GENERATED], report.repeats[HANDED_ON]
    assert _sums(every, "self") == (9, 3, 0, 0)
    assert _sums(every, "cross") == (18, 21, 37, 26)
    assert _sums(handed, "self") == (0, 0, 0, 0)
    assert _sums(handed, "cross") == (5, 13, 18, 16)
    assert not any(
        c["unresolved"] for by in report.repeats.values() for c in by.values()
    )
    a = [c for (_, arm), c in every.items() if arm == "A"]
    assert len(a) == 4 and not any(sum(c.values()) for c in a)  # read first: none


def test_an_id_only_lookup_gives_other_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bug O44 records: ids restart in every library (i01, i02, ...), so a
    target found by id alone is another library's idea."""

    def by_id(audits: tuple[ir.AuditLine, ...]) -> Callable[[ir.AuditLine], object]:
        first: dict[str, ir.AuditLine] = {}
        for a in audits:
            first.setdefault(a.id, a)
        return lambda a: first.get(a.duplicate_of or "")

    monkeypatch.setattr(ir, "_index", by_id)
    report = _run1()
    every, handed = report.repeats[GENERATED], report.repeats[HANDED_ON]
    assert _sums(every, "self") != (9, 3, 0, 0)
    assert _sums(every, "cross") != (18, 21, 37, 26)
    assert _sums(handed, "self") != (0, 0, 0, 0)


def test_the_self_cross_tables_state_their_filter_beside_every_number() -> None:
    text = ir.render(_run1())["measures.md"]
    head, second = (
        text.index(f"### {HANDED_ON.capitalize()}"),
        text.index(f"### {GENERATED.capitalize()}"),
    )
    assert head < second
    lines = text.splitlines()
    for tag in ("in-result rows", "all audit rows"):
        assert (f"| library | configuration | self ({tag}) | cross ({tag}) | "
                f"target not found ({tag}) |") in lines  # fmt: skip
    assert "| all libraries | X1-2 | 0 (in-result rows) | 18 (in-result rows) | 0 (in-result rows) |" in lines  # fmt: skip
    assert "| all libraries | X1-0 | 9 (all audit rows) | 18 (all audit rows) | 0 (all audit rows) |" in lines  # fmt: skip
    assert "| tomli | A | 0 (all audit rows) |" in text


def test_audit_rows_alone_reproduce_run_1s_good_and_audited_counts(
    tmp_path: Path,
) -> None:
    """The pooled re-audit writes no probe row (O44): its counts come from its
    audit rows by ``ideas_probe.scores``' rules, checked on run 1's file."""
    rows = ir.load_rows([RUN1, SCORE])
    scored = ir.audit_scores(rows.audits)
    fields = ("audited", "auditor_infeasible", "good", "good_corrected", "good_strict")
    probes = {(p.repo, p.arm): p for p in rows.probes}
    assert len(scored) == 20  # four libraries, five pooled arms
    for key, got in scored.items():
        assert got == {f: getattr(probes[key], f) for f in fields}, key
    failed = [a.model_copy(update={"auditor": None}) for a in rows.audits
              if a.repo == "tomli"]  # fmt: skip
    assert {v["good_corrected"] for v in ir.audit_scores(failed).values()} == {None}
    links = ir.load_rows([_write(tmp_path, _x1(audits=[
        _audit("i01", "A", "a", "feasible"),
        _audit("i02", "X1-0", "b", "infeasible", "i01"),  # root A: its verdict
        _audit("i03", "X1-0", "c", "infeasible", "i99"),  # no such id: its own
        _audit("i04", "X1-2", "d", "infeasible", "i05"),  # a loop: its own
        _audit("i05", "X1-2", "e", "infeasible", "i04"),
    ]))]).audits  # fmt: skip
    small = ir.audit_scores(links)
    assert small[("tomli", "X1-0")] == {"audited": 2, "auditor_infeasible": 2,
                                        "good": 0, "good_corrected": 1,
                                        "good_strict": 0}  # fmt: skip
    assert small[("tomli", "X1-2")]["good_corrected"] == 0


def test_the_headline_good_counts_are_corrected_and_strict_only() -> None:
    report = _run1()
    assert report.good == {"A": (19, None), "X1-0": (13, 13), "X1-1": (13, 12),
                           "X1-2": (11, 10), "X1-3": (14, 11), "X1-4": (None, None)}  # fmt: skip
    files = ir.render(report)
    text = files["measures.md"]
    lines = text.splitlines()
    assert "| A | 19 | - |" in lines and "| X1-0 | 13 | 13 |" in lines
    appendix = text.index("## Appendix")
    assert text.count("as coded") == text[appendix:].count("as coded") >= 1
    assert "as coded (reading-order artifact)" in text[appendix:]
    assert "| tomli | X1-2 | 3 | 3 | 0 |" in lines  # as coded last, appendix only
    tables = files["tables.md"]
    assert "as coded" not in tables
    assert not any(re.match(r"\| X1-\d \| good \|", x) for x in tables.splitlines())
    assert re.search(r"\| X1-3 \| good_strict \|", tables)
    assert {m for _, m in report.deltas} >= {"good_corrected", "good_strict"}


def test_x1_1s_cost_per_unique_new_mechanism_per_model() -> None:
    report = _run1()
    usd = {FABLE_5: 2.997555, FABLE_51: 3.254315, ip.HAIKU: 0.019405,
           OPUS: 0.846018, ip.SONNET_5: 0.558745, SONNET: 0.070942}  # fmt: skip
    unique = {FABLE_5: 1, FABLE_51: 1, ip.HAIKU: 1, OPUS: 1, ip.SONNET_5: 3,
              SONNET: 2}  # fmt: skip
    assert set(report.lens_costs) == set(ip.SQUARE_MODELS) == set(usd)
    for model, c in report.lens_costs.items():
        assert c.requests == 4, model  # one lens a library, every library
        assert c.usd == pytest.approx(usd[model], abs=1e-6), model
        assert c.unique == unique[model], model
    spent = math.fsum(c.usd for c in report.lens_costs.values())
    x1_1 = math.fsum(p.cost_usd for p in report.rows.probes if p.arm == "X1-1")
    assert spent < x1_1  # S1, the leap and the reviewer left out
    tables = ir.render(report)["tables.md"]
    section = tables[tables.index("## 2b ") : tables.index("## 3 ")]
    assert tables.index("## 2 ") < tables.index("## 2b ")  # beside the counts
    assert "ideas-reply" in section and "MODEL_PRICING" in section
    assert f"new to today's generator ({UPPER})" in section
    assert f"unique new mechanisms ({UPPER})" in section
    assert f"| {ip.SONNET_5} | 4 | 0.5587 | 3 | 3 | 3 | 0.1862 |" in section


def test_a_model_with_no_unique_new_mechanism_shows_its_cost_alone(
    tmp_path: Path,
) -> None:
    probes = [{**r, "lane_models": {"eliminate": S5, "far": O55}}
              if r["experiment"] == "ideas-probe" and r["arm"] == "X1-1" else r
              for r in _x1()]  # fmt: skip
    reply: Row = {"experiment": "ideas-reply", "repo": "tomli", "arm": "X1-1",
                  "role": "lane", "label": "far", "sent": True,
                  "usage": [1_000_000, 0, 0, 0], "chunks": []}  # fmt: skip
    report = _report(tmp_path, [*probes, reply])
    opus, rate = report.lens_costs[O55], settings.MODEL_PRICING[O55].input
    assert (opus.requests, opus.unique) == (1, 0) and opus.usd == pytest.approx(rate)
    tables = ir.render(report)["tables.md"]
    assert (f"| {O55} | 1 | {rate:.4f} | 0 | 0 | 0 | no unique new mechanism |"
            in tables)  # fmt: skip
    assert report.lens_costs[ip.HAIKU].requests == 0  # no lane_models row for it


def _rerun(
    tmp: Path,
    edit: Callable[[list[Row]], list[Row]] = lambda rows: rows,
    rerun_rows: Callable[[list[Row]], list[Row]] = lambda rows: rows,
) -> dict[str, Path]:
    """A re-run made from run 1 (its A and X1-1 on the four libraries, X1-1's
    ideas retitled and its lane output doubled) and its pooled re-audit (run
    1's audit rows, X1-1's retitled, under ``ideas-reaudit`` with both
    digests), as ``ideas_reaudit.ReauditSink`` writes them."""

    def again(r: Row) -> Row:
        if r["arm"] != "X1-1":
            return r
        if r["experiment"] in ("ideas-idea", "ideas-audit"):
            return {**r, "title": f"R {r['title']}"}
        if r["experiment"] == "ideas-reply":
            usage = r["usage"]
            assert isinstance(usage, list)
            return {**r, "usage": [usage[0], 2 * usage[1], *usage[2:]]}
        return {**r, "lever": f"{r['lever']}, lane output cap 32,000 (O42)"}

    run1 = _lines(RUN1)
    kinds = ("ideas-probe", "ideas-idea", "ideas-reply", "ideas-audit")
    rerun = _write(tmp, rerun_rows([again(r) for r in run1 if r["experiment"] in kinds
                                    and r["arm"] in ("A", "X1-1")]), "rerun.jsonl")  # fmt: skip
    digests = {"run1_sha256": _sha(RUN1), "rerun_sha256": _sha(rerun)}
    audits = [{**again(r), "experiment": "ideas-reaudit", **digests}
              for r in run1 if r["experiment"] == "ideas-audit"]  # fmt: skip
    reply: Row = {
        "experiment": "ideas-reply",
        "repo": "tomli",
        "arm": "auditor",
        **digests,
    }
    reaudit = _write(tmp, [*edit(audits), reply], "reaudit.jsonl")
    return {"rerun": rerun, "reaudit": reaudit}


def _infeasible(rows: list[Row]) -> list[Row]:  # tomli's X1-0: no link, all out
    return [{**r, "auditor": "infeasible", "reason": "precondition_false",
             "duplicate_of": None}
            if (r["repo"], r["arm"]) == ("tomli", "X1-0") else r for r in rows]  # fmt: skip


def test_the_re_run_and_its_pooled_re_audit_replace_run_1s_rows(
    tmp_path: Path,
) -> None:
    report = _run1(**_rerun(tmp_path, _infeasible))
    x1_1 = [i for i in report.rows.ideas if i.arm == "X1-1"]
    assert x1_1 and all(i.title.startswith("R ") for i in x1_1)  # the re-run's
    assert [p.lever.endswith("(O42)") for p in report.rows.probes
            if p.arm == "X1-1"] == [True] * 4  # fmt: skip
    every = report.repeats[GENERATED]
    assert every[("tomli", "X1-0")]["self"] + every[("tomli", "X1-0")]["cross"] == 0
    assert _sums(every, "self")[1:] == (3, 0, 0)  # the rest as run 1's
    probe = {(p.repo, p.arm): p for p in report.rows.probes}
    tomli = probe[("tomli", "X1-0")]
    assert (tomli.audited, tomli.auditor_infeasible) == (10, 10)  # the re-audit's
    assert (tomli.good_corrected, tomli.good_strict) == (0, 0)  # run 1: 4 and 4
    assert probe[("tomli", "X1-4")].good_corrected is None  # never pooled
    first = _run1()
    for model, c in report.lens_costs.items():  # the re-run's replies priced
        assert c.usd > first.lens_costs[model].usd, model
        assert c.unique == first.lens_costs[model].unique, model
    for name in ("measures.md", "tables.md"):
        text = ir.render(report)[name]
        header = text[: text.index("\n## ")]
        assert header.count("Sources (O44): ") == 1, name
        for repo in ir.REAUDIT_REPOS:
            assert (f"{repo}: X1-1's probe, idea and reply rows from rerun.jsonl; "
                    "every audit-based figure (share-new, self/cross, good counts, "
                    "auditor-feasible) from reaudit.jsonl; the rest from "
                    f"{RUN1.name}") in header, (name, repo)  # fmt: skip


def test_without_a_re_run_the_header_names_run_1s_file() -> None:
    text = ir.render(_run1())["measures.md"]
    header = text[: text.index("\n## ")]
    assert f"Sources (O44): more_itertools: {RUN1.name}; pyparsing: " in header
    assert "rerun" not in header


def _without_tomli(rows: list[Row]) -> list[Row]:
    return [r for r in rows if r["repo"] != "tomli"]


def _stranger(rows: list[Row]) -> list[Row]:
    return [*rows, {**rows[0], "arm": "X1-0"}]  # an X1-0 row: not the re-run


@pytest.mark.parametrize(
    ("swap", "match"),
    [
        (lambda f: {"rerun": f["rerun"]}, "go together"),
        (lambda f: {"reaudit": f["reaudit"]}, "go together"),
        (lambda f: {"more": f["rerun"]}, "rerun.jsonl: holds the X1-1 re-run"),
        (lambda f: {**f, "more": f["rerun"]}, "rerun.jsonl: holds the X1-1 re-run"),
    ],
)
def test_the_re_run_alone_or_mixed_with_run_1s_rows_is_refused(
    tmp_path: Path, swap: Callable[[dict[str, Path]], dict[str, Path]], match: str
) -> None:
    named = swap(_rerun(tmp_path))
    more = named.pop("more", None)
    with pytest.raises(ValueError, match=match):
        _run1(*(() if more is None else (more,)), **named)


@pytest.mark.parametrize(
    ("edit", "rerun_rows", "match"),
    [
        (lambda rows: [{**r, "run1_sha256": "0" * 64} for r in rows],
         lambda rows: rows, "digests do not name"),
        (lambda rows: [{**r, "rerun_sha256": "0" * 64} for r in rows],
         lambda rows: rows, "digests do not name"),
        (_without_tomli, lambda rows: rows, "re-audits .* the re-run ran"),
        (lambda rows: rows, _stranger, "not the X1-1 re-run"),
        (lambda rows: rows, lambda rows: [], "not the X1-1 re-run"),
    ],
)  # fmt: skip
def test_a_re_audit_that_is_not_the_re_runs_is_refused(
    tmp_path: Path,
    edit: Callable[[list[Row]], list[Row]],
    rerun_rows: Callable[[list[Row]], list[Row]],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _run1(**_rerun(tmp_path, edit, rerun_rows))


def test_the_cli_takes_the_re_run_and_its_re_audit(tmp_path: Path) -> None:
    named = _rerun(tmp_path)
    lines: list[str] = []
    out = tmp_path / "out"
    code = ir.main([str(RUN1), str(SCORE), "--rerun", str(named["rerun"]),
                    "--reaudit", str(named["reaudit"]), "--out", str(out)],
                   echo=lines.append)  # fmt: skip
    assert code == 0, lines
    assert "rerun.jsonl" in (out / "measures.md").read_text(encoding="utf-8")
    code = ir.main([str(RUN1), str(SCORE), "--rerun", str(named["rerun"]),
                    "--out", str(tmp_path / "o")], echo=lines.append)  # fmt: skip
    assert code == 2 and "go together" in lines[-1]


def _trial(arm: str, label: str, position: int, title: str) -> Row:
    return {**TRIALS[0], "arm": arm, "label": label, "lane": label,
            "position": position, "title": title}  # fmt: skip


TOMLI_X1_1: tuple[str, str, int] = ("X1-1", "obvious", 1)  # run 1 tomli
TOMLI_X1_1_TITLE = next(str(r["title"]) for r in _lines(RUN1)
                        if r["experiment"] == "ideas-idea" and r["repo"] == "tomli"
                        and (r["arm"], r["label"], r["position"]) == TOMLI_X1_1)  # fmt: skip


@pytest.mark.parametrize(
    ("stale", "match"),
    [
        (_trial(*TOMLI_X1_1, TOMLI_X1_1_TITLE),  # Ve's trial of run 1's idea
         "tomli X1-1 slice row names run 1's idea, not the re-run's (O44)"),
        ({**COMBINE, "arm": "X1-1"},  # no trial: nothing proves its ideas
         "tomli X1-1 slice combine has no trial row to prove its ideas (O44)"),
        (_result("opus-5-5", {"p1": ("X1-1", "name_the_problem", 1)}, {}, ["p1"],
                 0, 0),  # a member (Fable 5.1's), no set row
         "tomli opus-5-5 pool result has no ideas-pool-set row (O44)"),
        ({**_result("sonnet-5", {"p1": ("X1-0", "far", 1)},
                    {"q": ("X1-1", "resolve_tradeoff", 3)}, ["p1"], 0, 0),
          "model": "claude-sonnet-5"},  # listed apart: the marker's own model's
         "tomli sonnet-5 pool result has no ideas-pool-set row (O44)"),
    ],
)  # fmt: skip
def test_run_1s_x1_1_slice_and_pool_rows_beside_the_re_run_are_refused(
    tmp_path: Path, stale: Row, match: str
) -> None:
    """O44: run 1's X1-1 slice and pool rows on a re-run library would join the
    re-run's ideas by (label, position): refused, never silently attached."""
    more = _write(tmp_path, [stale], "slice.jsonl")
    _run1(more)  # without the re-run: run 1's own rows, accepted
    with pytest.raises(ValueError, match=re.escape(f"slice.jsonl: {match}")):
        _run1(more, **_rerun(tmp_path))


O39 = im.Decision("opus-5-5", im.ONE, ("opus-5-5",), ())  # Vb's verdict


def _pool_ideas(repo: str, x1_1: Path) -> list[Row]:
    """The pool the report joins on a re-run library: run 1's X1-0, X1-2 and
    X1-3 idea rows with ``x1_1``'s X1-1 ones."""
    rows = [*(r for r in _lines(RUN1) if r.get("arm") != "X1-1"),
            *(r for r in _lines(x1_1) if r.get("arm") == "X1-1")]  # fmt: skip
    return [r for r in rows if r["experiment"] == "ideas-idea" and r["repo"] == repo]


def _pool_of(rows: list[Row], change_class: str = "caching") -> list[ipool.PoolIdea]:
    """``ideas_pool.members``' pool of ``rows`` (one change class for all)."""
    fields = ipool.IdeaRow.model_fields
    ideas = [ipool.IdeaRow.model_validate({k: v for k, v in r.items() if k in fields})
             for r in rows]  # fmt: skip
    found = [ipool.PoolIdea(i, change_class) for i in ideas if ipool.pooled(i)]
    return sorted(found, key=lambda i: i.id)


def _ranked(monkeypatch: pytest.MonkeyPatch, tmp: Path, repo: str,
            pool: list[ipool.PoolIdea], name: str) -> list[Row]:  # fmt: skip
    """``ideas_pool.rank_library``'s own rows on ``pool`` under O39 (the real
    sets, shown orders and results), each marker's order faked as its rows
    reversed: nothing is sent."""

    def ask(marker: im.Marker, run: LiveRun, s: im.RankSet, hot: im.HotCode,
            *, base: object) -> im.MarkerReply:  # fmt: skip
        return im.MarkerReply(s, marker, tuple(map(float, range(len(s.rows)))),
                              None, 0.02, None)  # fmt: skip

    monkeypatch.setattr(im, "ask", ask)  # ``ideas_pool`` calls ``im.ask``
    out = tmp / f"{name}.jsonl"
    ipool.rank_library(repo, pool, O39, live=lambda cap: cast(LiveRun, object()),
                       hot=lambda: im.HotCode(repo, "", ()),
                       sink=ResultsSink({RESULTS_ENV: str(out)}))  # fmt: skip
    return _lines(out)


def test_the_re_runs_x1_1_slice_and_pool_rows_are_accepted_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O44 under O46: the slice and the pool run on the re-run's X1-1 ideas;
    their rows join, counted, beside the re-run."""
    named = _rerun(tmp_path)
    title = f"R {TOMLI_X1_1_TITLE}"  # ``_rerun``'s retitled X1-1 idea there
    pooled = _ranked(monkeypatch, tmp_path, "more_itertools",
                     _pool_of(_pool_ideas("more_itertools", named["rerun"])), "pool")  # fmt: skip
    more = _write(tmp_path, [_trial(*TOMLI_X1_1, title), {**COMBINE, "arm": "X1-1"},
                             *pooled], "slice.jsonl")  # fmt: skip
    report = _run1(more, **named)
    assert (report.costs["X1-1"].wins, report.costs["X1-1"].slice_usd) == (1, 0.6)
    assert f"| 1 | {title} |" in ir.render(report)["tomli-X1-1.md"]
    validated, other = report.pools["more_itertools"]
    assert any(i.arm == "X1-1" for i in validated.members.values())
    assert [i.arm for i in validated.apart] == ["X1-1"]  # Opus 5.5's: Opus 5 shows it
    written = [r["counts"] for r in pooled if r["experiment"] == "ideas-pool-result"]
    assert [validated.counts(), other.counts()] == written
    assert all(isinstance(c, dict) and sum(c.values()) == 3 for c in written)


def test_a_re_run_trial_with_another_title_is_still_refused_by_the_join(
    tmp_path: Path,
) -> None:
    more = _write(tmp_path, [_trial(*TOMLI_X1_1, "Another idea")], "slice.jsonl")
    with pytest.raises(ValueError, match="tomli X1-1 obvious #1: the trial's "
                       "'Another idea' is not the idea there"):  # fmt: skip
        _run1(more, **_rerun(tmp_path))


@pytest.mark.parametrize(
    ("drop", "match"),
    [
        ((), "opus-5-5 pool: X1-1 "),  # ranked on run 1's titles
        (("opus-5-5", "opus-5"), "opus-5-5 pool result has no ideas-pool-set row"),
        (("opus-5",), "opus-5-5 pool: X1-1 "),  # its apart idea shown nowhere
    ],
)
def test_a_pool_not_shown_with_the_re_runs_titles_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drop: tuple[str, ...], match: str
) -> None:
    named = _rerun(tmp_path)
    x1_1 = named["rerun"] if drop else RUN1
    pooled = _ranked(monkeypatch, tmp_path, "more_itertools",
                     _pool_of(_pool_ideas("more_itertools", x1_1)), "pool")  # fmt: skip
    more = _write(tmp_path, [r for r in pooled if r["experiment"] != "ideas-pool-set"
                             or r["marker"] not in drop], "slice.jsonl")  # fmt: skip
    if not drop:
        _run1(more)  # run 1's own ranking without the re-run: accepted
    with pytest.raises(
        ValueError, match=re.escape(f"slice.jsonl: more_itertools {match}")
    ):
        _run1(more, **named)


@pytest.mark.parametrize("shown", ["rerun", "run1"])
def test_a_set_rows_own_titles_are_matched_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shown: str
) -> None:
    """A set row that records its titles proves the pool by them, not by the
    order: the re-run's ranking with run 1's titles written in passes the order
    check and is refused."""
    named = _rerun(tmp_path)
    pool = _pool_of(_pool_ideas("more_itertools", named["rerun"]))
    title = {i.id: i.row.title[: ipool.MARKER_TITLE_MAX] for i in pool}
    if shown == "run1":  # the same keys, so the same ids: run 1's titles there
        title |= {i.id: i.row.title[: ipool.MARKER_TITLE_MAX]
                  for i in _pool_of(_pool_ideas("more_itertools", RUN1))}  # fmt: skip
    pooled = _ranked(monkeypatch, tmp_path, "more_itertools", pool, "pool")
    _run1(_write(tmp_path, pooled, "slice.jsonl"), **named)  # the order check passes
    titled = [{**r, "titles": [title[x] for x in cast("list[str]", r["ids"])]}
              if r["experiment"] == "ideas-pool-set" else r for r in pooled]  # fmt: skip
    more = _write(tmp_path, titled, "slice.jsonl")
    if shown == "rerun":
        assert [p.counts() for p in _run1(more, **named).pools["more_itertools"]] == [
            r["counts"] for r in pooled if r["experiment"] == "ideas-pool-result"]  # fmt: skip
        return
    with pytest.raises(ValueError, match=re.escape(
            "slice.jsonl: more_itertools opus-5-5 pool: X1-1 ")):  # fmt: skip
        _run1(more, **named)


def test_other_arms_slice_rows_beside_the_re_run_are_kept(tmp_path: Path) -> None:
    title = next(str(r["title"]) for r in _lines(RUN1) if r["experiment"] == "ideas-idea"
                 and (r["repo"], r["arm"], r["label"], r["position"])
                 == ("tomli", "X1-0", "obvious", 1))  # fmt: skip
    other = _result("opus-5-5", {"p1": ("X1-0", "far", 1)}, {}, ["p1"], 0, 0)
    more = _write(tmp_path, [_trial("X1-0", "obvious", 1, title), other], "slice.jsonl")
    report = _run1(more, **_rerun(tmp_path))
    assert report.costs["X1-0"].wins == 1 and report.costs["X1-1"].wins == 0
    assert f"| 1 | {title} |" in ir.render(report)["tomli-X1-0.md"]
    assert [p.counts() for p in report.pools["tomli"]] == [  # no X1-1 idea: no set
        {"X1-0": 1, "X1-1": 0, "X1-2": 0, "X1-3": 0}]  # fmt: skip


X1_DIR = RUN1.parent
SLICE_X1_1 = TESTS_DIR / "fixtures/ideas_slice/x1-1.jsonl"  # O46's slice input
TODAY_FILES = (RUN1, X1_DIR / "ideas-probe-x1-run2a-41773968543.jsonl",
               X1_DIR / "ideas-probe-x1-run2b-41780421911.jsonl",
               VALIDATION / "ideas-marker-41642619744.jsonl", SCORE)  # fmt: skip
TODAY_RERUN = {"rerun": TESTS_DIR / "fixtures/ideas_reaudit/x1-1-rerun.jsonl",
               "reaudit": X1_DIR / "ideas-reaudit-41772132719.jsonl"}  # fmt: skip


def test_todays_committed_files_build_the_report_without_refusal() -> None:
    """Run 1, run 2a and 2b, Vb's and Vc's results, the re-run and its re-audit."""
    report = ir.report_of(TODAY_FILES, ir.E1_DIR, **TODAY_RERUN)
    assert len(ir.render(report)) == 53


def test_the_real_slice_inputs_rows_join_the_real_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The slice's real input (x1-1.jsonl: the re-run's X1-1) ranked from the
    pool's own loader, with an X1-1 trial of it: accepted beside the real
    re-run and re-audit; the same ranking on run 1's X1-1 titles is refused."""
    repo = "pyparsing"
    pool = list(ipool.load_pools([SLICE_X1_1], [repo])[repo])  # real classes
    idea = next(i.row for i in pool if i.row.arm == "X1-1")
    trial = {**_trial("X1-1", idea.label, idea.position, idea.title), "repo": repo}
    more = _write(tmp_path, [trial, {**COMBINE, "repo": repo, "arm": "X1-1"},
                             *_ranked(monkeypatch, tmp_path, repo, pool, "pool")],
                  "slice.jsonl")  # fmt: skip
    report = ir.report_of([*TODAY_FILES, more], ir.E1_DIR, **TODAY_RERUN)
    assert report.costs["X1-1"].wins == 1 and len(report.pools[repo]) == 2
    old = _ranked(monkeypatch, tmp_path, repo, _pool_of(_pool_ideas(repo, RUN1)), "old")
    stale = _write(tmp_path, old, "stale.jsonl")
    with pytest.raises(ValueError, match=f"stale.jsonl: {repo} opus-5-5 pool: X1-1 "):
        ir.report_of([*TODAY_FILES, stale], ir.E1_DIR, **TODAY_RERUN)


def test_a_trial_is_joined_to_its_idea_only_when_the_titles_match(
    tmp_path: Path,
) -> None:
    ok = _write(tmp_path, [_trial(*TOMLI_X1_1, TOMLI_X1_1_TITLE)], "ok.jsonl")
    row = next(x for x in ir.render(_run1(ok))["tomli-X1-1.md"].splitlines()
               if x.startswith(f"| 1 | {TOMLI_X1_1_TITLE} |"))  # fmt: skip
    assert "| keep | 12.0% / 3.0% |" in row
    bad = _write(tmp_path, [_trial(*TOMLI_X1_1, "Another idea")], "bad.jsonl")
    with pytest.raises(ValueError, match="tomli X1-1 obvious #1: the trial's "
                       "'Another idea' is not the idea there"):  # fmt: skip
        _run1(bad)
    lost = _write(tmp_path, [_trial("X1-1", "obvious", 99, "Lost")], "lost.jsonl")
    with pytest.raises(ValueError, match="obvious #99: a trial with no ideas-idea"):
        _run1(lost)


# ---------------------------------------------------------------------------
# V-rep3 (O47): wins by lane; the predicted ceiling from Va's recorded spans
# ---------------------------------------------------------------------------

FULL = (*TODAY_FILES, X1_DIR / "ideas-slice-1-41796813265.jsonl",
        X1_DIR / "ideas-slice-2-41803612871.jsonl",
        X1_DIR / "ideas-pool-41808508958.jsonl")  # fmt: skip


def _span(
    name: str, first: int, last: int, *ids: str, path: str = "pkg/a.py"
) -> FunctionSpan:
    return FunctionSpan(path=path, qualname=name, start_line=first, end_line=last,
                        hotspot_ids=ids)  # fmt: skip


def _hand_body(tmp: Path) -> ip.FactsBody:
    facts, _ = ir.load_e1(_e1(tmp))
    body = facts["tomli"]  # f: 10-40 (50 %) around g: 20-30 (10 %)
    spots = tuple(h.model_copy(update={"line_end": None}) for h in body.hotspots)
    return body.model_copy(update={"hotspots": spots})


def _aimed(first: int, last: int, path: str = "pkg/a.py") -> ir.IdeaLine:
    return ir.IdeaLine.model_validate(
        {k: v for k, v in _idea("tomli", "X1-0", "far", SN, 1, "T", lines=(first, last),
                                path=path).items() if k != "experiment"})  # fmt: skip


def test_a_hotspot_with_no_end_takes_its_recorded_functions_span(
    tmp_path: Path,
) -> None:
    body = _hand_body(tmp_path)
    spans = (
        _span("f", 9, 40, "h-tomli-f"),  # decorated: the span starts above
        _span("f.<locals>.g", 20, 30, "h-tomli-g"),
        _span("f.<locals>.k", 32, 36),  # no hotspot of its own
        _span("other", 50, 60, "h-tomli-f", path="pkg/b.py"),
    )  # another file
    assert ir.ceiling(_aimed(21, 22), body) is None  # cProfile's first line only
    fixed, taken = ir.with_extents(body, spans[:3])
    assert taken == 2
    assert ir.ceiling(_aimed(21, 22), fixed) == pytest.approx(0.1)  # innermost: g
    assert ir.ceiling(_aimed(35, 38), fixed) == pytest.approx(0.5)  # f, not g
    assert ir.ceiling(_aimed(33, 34), fixed) == pytest.approx(0.5)  # k is unprofiled
    assert ir.ceiling(_aimed(9, 9), fixed) == pytest.approx(0.5)  # the decorator
    assert ir.ceiling(_aimed(41, 45), fixed) is None  # outside every hotspot
    assert ir.ceiling(_aimed(38, 42), fixed) is None  # straddles f's end
    assert ir.ceiling(_aimed(21, 22, "pkg/b.py"), fixed) is None  # another file
    kept = body.model_copy(update={"hotspots": tuple(
        h.model_copy(update={"line_end": 12}) for h in body.hotspots)})  # fmt: skip
    assert ir.with_extents(kept, spans[:3])[1] == 0  # a recorded end is kept
    with pytest.raises(ValueError, match="h-tomli-f: Va's views record 2 spans"):
        ir.with_extents(body, spans)


def test_the_real_profile_records_no_end_and_the_paths_already_match() -> None:
    """The root cause, on the real files: E1's hotspots carry no line_end,
    while every targeted idea's path is one of its library's hotspot paths."""
    before = ir.report_of(FULL, ir.E1_DIR, views=None, **TODAY_RERUN)
    spots = [h for b in before.facts.values() for h in b.hotspots]
    assert len(spots) == 80 and all(h.line_end is None for h in spots)
    aimed = [i for i in before.rows.ideas if i.returned and not i.proposal
             and i.target is not None]  # fmt: skip
    paths = {(r, h.file_path) for r, b in before.facts.items() for h in b.hotspots}
    assert len(aimed) == 253 and all((i.repo, i.path) in paths for i in aimed)
    assert {a: m.known for a, m in before.measures.items()} == dict.fromkeys(
        ir.CONFIGS, 0
    )
    after = ir.report_of(FULL, ir.E1_DIR, **TODAY_RERUN)
    assert after.extents == (50, 80)
    assert {a: (m.known, m.proposed) for a, m in after.measures.items()} == KNOWN
    assert {a: m.above for a, m in after.measures.items()} == ABOVE


KNOWN = {
    "A": (0, 39),
    "X1-0": (37, 51),
    "X1-1": (45, 63),
    "X1-2": (40, 56),
    "X1-3": (42, 53),
    "X1-4": (18, 30),
}  # (with a ceiling, ideas): A has no target
ABOVE = {"A": 0, "X1-0": 37, "X1-1": 45, "X1-2": 40, "X1-3": 42, "X1-4": 18}


def test_the_views_change_only_the_ceilings() -> None:
    """Every figure but a ceiling's is the same with and without the views."""
    before = ir.render(ir.report_of(FULL, ir.E1_DIR, views=None, **TODAY_RERUN))
    after = ir.render(ir.report_of(FULL, ir.E1_DIR, **TODAY_RERUN))
    assert before.keys() == after.keys() and len(after) == 53
    changed: Counter[str] = Counter()
    assert before["ceilings.svg"] != after["ceilings.svg"]  # one dot per ceiling
    for name in sorted(set(after) - {"ceilings.svg"}):
        old, new = before[name].split("\n"), after[name].split("\n")
        assert len(old) == len(new), name
        for x, y in zip(old, new, strict=True):
            changed[name] += x != y
            if x == y:
                continue
            xs, ys = x.split(" | "), y.split(" | ")
            cols = [k for k, (u, v) in enumerate(zip(xs, ys, strict=True)) if u != v]
            if name == "measures.md":
                assert cols == [6], y  # ceiling over the floor (of known)
            elif name != "tables.md":
                assert cols == [4], y  # the library file's ceiling column
            elif y.startswith("Extents: "):
                assert x.startswith("Extents: 0 of 80 "), x
            elif xs[0] in {f"| {c}" for c in ir.CONFIGS}:
                assert len(xs) == 9 or xs[1] == "above", y  # Table 3; 4's above
            else:  # Table 2's cells: ideas/unique mechanisms/ceilings over floor
                assert all(
                    u.split("/")[:2] == v.split("/")[:2]
                    for u, v in zip(xs, ys, strict=True)
                ), y
    assert changed["measures.md"] == 5 and changed["tables.md"] > 0
    assert changed["owner-sample.md"] == changed["owner-sample-key.json"] == 0


def test_the_full_real_report_is_byte_identical_in_other_processes(
    tmp_path: Path,
) -> None:
    outs = []
    for seed in ("0", "12345"):
        out = tmp_path / f"out-{seed}"
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": f"{SERVICE / 'src'}:{SERVICE / 'tests'}"}  # fmt: skip
        done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            [sys.executable, "-m", "live.ideas_report", *map(str, FULL),
             "--rerun", str(TODAY_RERUN["rerun"]), "--reaudit",
             str(TODAY_RERUN["reaudit"]), "--out", str(out)],
            cwd=SERVICE / "tests", env=env, capture_output=True, text=True,
            check=False, timeout=300,
        )  # fmt: skip
        assert done.returncode == 0, done.stdout + done.stderr
        outs.append({p.name: p.read_bytes() for p in sorted(out.iterdir())})
    assert outs[0] == outs[1] and len(outs[0]) == 53


def test_the_slices_wins_by_the_lane_that_produced_them() -> None:
    """O47: 9 wins, leap 5, S1 2, lens 2; X1-2's sequential labels read
    through the idea row's lane (tomli's leap-2 is the leap)."""
    wins = ir.report_of(FULL, ir.E1_DIR, **TODAY_RERUN).wins
    by = _grouped_wins(wins)
    assert [round(w.gain_pct or 0, 1) for w in by["leap"]] == [14.6, 9.9, 9.9, 7.0, 4.4]
    assert [(w.repo, w.arm) for w in by["leap"]] == [
        ("sqlparse", "X1-1"), ("tomli", "X1-1"), ("tomli", "X1-0"),
        ("tomli", "X1-2"), ("pyparsing", "X1-3")]  # fmt: skip
    assert by["leap"][3].label == "leap-2" and by["leap"][3].lane == "leap"
    assert {w.model for w in by["leap"]} == {O55}
    assert [(w.repo, w.arm) for w in by["S1 (obvious)"]] == [
        ("sqlparse", "X1-3"), ("sqlparse", "X1-0")]  # fmt: skip
    far, haiku = by["lens lanes"]
    assert (far.repo, far.arm, far.lane, round(far.gain_pct or 0, 1)) == (
        "sqlparse", "X1-3", "far", 9.5)  # fmt: skip
    assert (haiku.arm, haiku.lane, haiku.model) == ("X1-1", "eliminate", HK)
    assert (f"{haiku.gain_pct:.2f}", f"{haiku.floor_pct:.2f}") == ("3.54", "3.53")
    files = ir.render(ir.report_of(FULL, ir.E1_DIR, **TODAY_RERUN))
    for name in ("measures.md", "tables.md"):
        text = files[name]
        assert "## Slice wins by lane (O47)" in text, name
        assert "| all configurations | 5 | 2 | 2 (far, eliminate) | 9 |" in text
        assert "| X1-2 | 1 | 0 | 0 | 1 |" in text
        assert "| X1-1 | 2 | 0 | 1 (eliminate) | 3 |" in text
        assert (f"| pyparsing | X1-1 | lens lanes | eliminate | eliminate | {HK} "
                "| 3.54% / 3.53% |") in text  # fmt: skip
    measures = files["measures.md"]
    assert (measures.index("## Cost per configuration")
            < measures.index("## Slice wins by lane")
            < measures.index("## Marker-feasible"))  # fmt: skip


def _grouped_wins(wins: tuple[ir.Win, ...]) -> dict[str, list[ir.Win]]:
    out: dict[str, list[ir.Win]] = {}
    for w in wins:
        out.setdefault(w.group, []).append(w)
    return out


def test_the_hand_made_win_is_counted_under_its_lane(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert [(w.arm, w.group, w.lane, w.model) for w in report.wins] == [
        ("X1-0", "lens lanes", "eliminate", SN)]  # fmt: skip
    text = ir.render(report)["tables.md"]
    assert "| X1-0 | 0 | 0 | 1 (eliminate) | 1 |" in text
    assert "| tomli | X1-0 | lens lanes | eliminate | eliminate | " in text


@pytest.mark.parametrize(
    ("trial", "match"),
    [
        ({**TRIALS[0], "lane": "far"},
         "tomli X1-0 eliminate #1: the trial's lane 'far' is not the idea's "
         "\\('eliminate'\\)"),
        ({**TRIALS[0], "arm": "A", "label": "today", "lane": "today",
          "title": "Inline lookups"},
         "tomli A today #1: a win from lane 'today', not the leap, S1 or a lens"),
    ],
)  # fmt: skip
def test_a_trial_off_its_ideas_lane_or_a_win_off_the_slices_lanes_is_refused(
    tmp_path: Path, trial: Row, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _report(tmp_path, _x1(trials=[trial]))


def test_the_cli_reads_the_views_it_is_given(tmp_path: Path) -> None:
    lines: list[str] = []
    code = ir.main([str(_write(tmp_path, _x1())), "--e1", str(_e1(tmp_path)),
                    "--views", str(tmp_path / "none.jsonl"), "--out",
                    str(tmp_path / "o")], echo=lines.append)  # fmt: skip
    assert code == 2 and "none.jsonl" in lines[0]
    assert ir.VIEWS == SERVICE / ip.VIEWS_FIXTURE


def test_the_real_measure_reads_its_ceilings() -> None:
    measures = ir.render(ir.report_of(FULL, ir.E1_DIR, **TODAY_RERUN))["measures.md"]
    rows = [x for x in measures.splitlines() if x.startswith("| X1-0 | 51 |")]
    assert len(rows) == 1 and "| 37/37 |" in rows[0], rows  # was 0/0 known
