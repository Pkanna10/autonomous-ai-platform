"""Offline guards of the ideas-slice suite (Ve, ``ideas_slice.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_slice_live.py``, that X1's rows load strictly and join as Vd's
own recorder (``ideas_probe.ProbeRecorder``) writes them; the selection rule
(new to today's generator by the auditor's duplicate links, one idea per
duplicate class, returned efficiency ideas only, never a proposal, ranked by
the validated marker that did not write the idea, deterministic, the
pipeline's order labelled as the fallback when no marker passed O37); that
``OP_COUNT_JUDGE`` is asserted before any spend and the operation-count judge
is in every loop's judges and on every verdict; one engine loop per
(configuration, library) with one trial per pick on the pick's hypothesis;
records joinable to the ``ideas-idea`` rows, redacted and chunked; and the
plan's need, minutes, fuse and refusals.

Fakes and what they stand for: ``dg.Wire`` for the Messages API (the live
run's captured ``AnthropicTransport``); ``og.LOCAL`` and a ``file://`` bare
upstream for GitHub over https (``oss.PRODUCTION``); a fake
``start_arm_loop`` / ``run_engine`` with hand-built engine states for the
engine loop (the real loop's wiring is built once, unsent, on the local
upstream); hand-made ``HotCode`` for a pinned clone's hot code; a hand-built
``ideas_marker.Decision`` for Vb's verdict (one test reads a results file
through Vb's own offline scorer). What only a live run proves: the markers'
orders, the engine's verdicts, gains and op counts on the four libraries.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from anthropic.types.beta import BetaTextBlockParam
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.transport import LLMRequest
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    Combination,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Objective,
    RunStats,
    Trial,
    Verdict,
    VerdictOutcome,
    new_id,
)
from autonomous_ai_agents.optimization.idea_types import is_proposal
from autonomous_ai_agents.optimization.judges import OP_COUNT_JUDGE, OpCountJudge
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import discovery_oss as dx
from . import ideas_marker as im
from . import ideas_pool as ipool
from . import ideas_probe as ip
from . import ideas_report as report
from . import ideas_slice as sl
from . import test_discovery_guards as dg
from . import test_oss_guards as og
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun, StartLive, restore_host_key
from .corpus import JSON_TEXT_MAX, RESULTS_ENV
from .discovery import OPUS, SONNET, carry, ceil_usd
from .discovery_io import ResultsSink
from .discovery_oss import CAP_CEILING_USD, OSS_TRIAL_CAP_USD
from .ideas_probe import X1_FUSE_USD, ArmRun, Exchange, Pooled, ShownIdea
from .oss import OssRepo

dry = dg.dry
upstream = og.upstream

Json = dict[str, Any]
LIVE_DIR = TESTS_DIR / "live"
REQUIRED = Isolation("required", None)
REPO = "tomli"
OPUS_5 = im.OPUS_5_MARKER.model
SECRET = "sk-ant-api03-" + "notarealkey0123456789"  # planted, never a real key
CHOSEN_55 = im.Decision("opus-5-5", im.HIGHER, ("opus-5-5", "opus-5"), ())
CHOSEN_5 = im.Decision("opus-5", im.ONE, ("opus-5",), ())
NO_MARKER = im.Decision(None, im.NO_MARKER, (), ())
TWO = {sl.REPOS_ENV: "sqlparse,pyparsing", SUITE_CAP_ENV: "75"}


# ---------------------------------------------------------------------------
# X1's rows, written by Vd's own recorder
# ---------------------------------------------------------------------------


def _request(text: str) -> LLMRequest:
    content: list[BetaTextBlockParam] = [{"type": "text", "text": text}]
    return LLMRequest(system="s", messages=({"role": "user", "content": content},),
                      max_tokens=10)  # fmt: skip


def _item(title: str, *, cls: str = "efficiency", change: str = "") -> Json:
    return {
        "title": title, "technique_slug": None, "hotspots": [],
        "change_summary": change or f"Change {title}.",
        "justification_summary": f"{title} removes the hot loop.",
        "depends_on_path": "tomli/_parser.py", "depends_on_quote": "def parse",
        "precondition": "Inputs are str.", "equivalence_summary": "Same values.",
        "mechanism": "remove_work", "morph_cells": ["work:eliminate", "work:eliminate"],
        "tier": "exploratory", "typicality": "uncommon", "change_class": cls,
        "expected_gain": 3.0, "provability": 0.7, "risk": 0.2,
    }  # fmt: skip


def _exchange(
    lane: str, items: Sequence[Json], *, model: str = SONNET, role: str = "lane"
) -> Exchange:
    text = "x" if lane == "obvious" else f'<lens name="{lane}"> write ideas'
    return Exchange(role, lane, 10, _request(text), sent=True, model=model,
                    reply=json.dumps({"hypotheses": list(items)}))  # fmt: skip


def _hyp(title: str, lane: str) -> Hypothesis:
    return Hypothesis(
        project_id="p", source=HypothesisSource.novel, title=title, rationale="r",
        change_class=ChangeClass.efficiency, expected_gain=0.1, provability=0.5,
        risk=0.1, tags=(f"lane:{lane}",),
    )  # fmt: skip


def _arm(
    arm: ip.IdeaArm, exchanges: Sequence[Exchange], returned: Sequence[tuple[str, str]]
) -> ArmRun:
    result = GenerateResult(tuple(_hyp(t, lane) for t, lane in returned))
    return ArmRun(arm, result, None, 0.1, (SONNET,), (SONNET,), tuple(exchanges))


def _pooled(arm: str, lane: str, title: str) -> Pooled:
    idea = ShownIdea(
        id="x", lane=lane, title=title, change_class="efficiency", anchor=None,
        change_summary="c", precondition="", equivalence_summary="",
        depends_on_path="", depends_on_quote="",
    )  # fmt: skip
    return Pooled(arm, idea, None, True)


def _review(k: int, dup: int | None = None) -> Json:
    return {
        "idea": f"i{k:02d}", "verdict": "feasible" if dup is None else "infeasible",
        "reason": "none" if dup is None else "duplicate_of",
        "duplicate_of": None if dup is None else f"i{dup:02d}", "change_plan": "p",
    }  # fmt: skip


# pool order (the audit's ids): (arm, lane, title, the id it duplicates)
POOL: tuple[tuple[str, str, str, int | None], ...] = (
    ("A", "today", "a-one", None),  # i01, today's generator
    ("X1-0", "far", "f-new", None),  # i02
    ("X1-0", "far", "f-dup-a", 1),  # i03: repeats arm A
    ("X1-0", "leap", "leap-new", None),  # i04: written by Opus 5.5
    ("X1-0", "eliminate", "e-family", 2),  # i05: repeats i02, same configuration
    ("X1-0", "eliminate", "e-new", None),  # i06
    ("X1-0", "eliminate", "e-late", None),  # i07
    ("X1-1", "far", "x1-copies-x0", 2),  # i08: repeats X1-0's i02: still new
    ("X1-1", "far", "x1-via-a", 3),  # i09: repeats i03, which repeats arm A
    ("X1-0", "far", "f-behaviour", None),  # i10: a behaviour idea
    ("X1-2", "relax_api", "r-proposal", None),  # i11: a quarantined proposal
    ("X1-0", "eliminate", "e-dropped", None),  # i12: its reviewer dropped it
)


def _x1_rows(path: Path, repo: str = REPO) -> Path:
    far = [_item("f-new"), _item("f-dup-a"), _item("f-behaviour", cls="behaviour")]
    eliminate = [_item("e-family"), _item("e-new"), _item("e-late"),
                 _item("e-unaudited"), _item("e-dropped")]  # fmt: skip
    returned = [("f-new", "far"), ("f-dup-a", "far"), ("f-behaviour", "far"),
                ("leap-new", "leap"), ("e-family", "eliminate"), ("e-new", "eliminate"),
                ("e-late", "eliminate"), ("e-unaudited", "eliminate")]  # fmt: skip
    arms = [
        _arm(ip.ARM_A, [Exchange("generator", "generator", 5, _request("x"),
                                 sent=True, model=SONNET)], [("a-one", "today")]),
        _arm(ip.ARM_X1_0, [
            _exchange("obvious", [_item("o-obvious")]), _exchange("far", far),
            _exchange("eliminate", eliminate),
            _exchange("leap", [_item("leap-new")], model=OPUS, role="leap"),
        ], returned),
        _arm(ip.ARM_X1_1, [_exchange("far", [_item("x1-copies-x0"), _item("x1-via-a")])],
             [("x1-copies-x0", "far"), ("x1-via-a", "far")]),
        _arm(ip.ARM_X1_2, [_exchange("relax_api", [_item("r-proposal")])],
             [("r-proposal", "relax_api")]),
        _arm(ip.ARM_X1_3, [], []),
    ]  # fmt: skip
    pooled = [_pooled(arm, lane, title) for arm, lane, title, _ in POOL]
    reviews = [_review(k, dup) for k, (*_, dup) in enumerate(POOL, 1)]
    audit = ip.audit_of(json.dumps({"reviews": reviews}), len(pooled))
    recorder = ip.ProbeRecorder(
        ip.ProbePlan((), ()), ResultsSink({RESULTS_ENV: str(path)})
    )
    recorder.record(repo, arms, pooled, audit, LiveRun("dry", 1.0))
    return path


@pytest.fixture
def x1(tmp_path: Path) -> Path:
    return _x1_rows(tmp_path / "x1.jsonl")


def _titles(ideas: Sequence[sl.Idea]) -> list[str]:
    return [i.row.title for i in ideas]


def _picked(picks: Sequence[sl.Pick]) -> list[str]:
    return [p.idea.row.title for p in picks]


def _base(**update: object) -> Settings:
    return settings.model_copy(update={"OP_COUNT_JUDGE": True, **update})


def test_the_eligible_ideas_are_new_returned_efficiency_and_one_per_class(
    x1: Path,
) -> None:
    found = sl.load_ideas((x1,), (REPO,))
    assert set(found) == {(REPO, c) for c in sl.SLICE_CONFIGS}
    # i03 repeats arm A, i05 repeats i02 (one idea per class), the behaviour
    # idea, the unaudited, the dropped and S1's unreturned idea are out
    assert _titles(found[(REPO, "X1-0")]) == ["f-new", "leap-new", "e-new", "e-late"]
    assert [i.pool for i in found[(REPO, "X1-0")]] == [2, 4, 6, 7]
    # new to today's generator even though X1-0 had it first; i09 reaches arm A
    # through i03's link, so the class is today's generator's
    assert _titles(found[(REPO, "X1-1")]) == ["x1-copies-x0"]
    assert found[(REPO, "X1-1")][0].family == found[(REPO, "X1-0")][0].family == 2
    assert found[(REPO, "X1-2")] == () and found[(REPO, "X1-3")] == ()  # a proposal
    leap = found[(REPO, "X1-0")][1]
    assert (leap.row.lane, leap.row.model, leap.row.label) == ("leap", OPUS, "leap")
    assert leap.item.justification_summary == "leap-new removes the hot loop."


def test_loading_is_strict_and_refuses_what_it_cannot_join(
    x1: Path, tmp_path: Path
) -> None:
    lines = x1.read_text(encoding="utf-8").splitlines()
    with pytest.raises(ValueError, match="no ideas-audit rows"):
        sl.load_ideas((x1,), (REPO, "sqlparse"))
    idea = next(x for x in lines if '"experiment": "ideas-idea"' in x)
    other = tmp_path / "other.jsonl"
    other.write_text(idea + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="recorded in"):
        sl.load_ideas((x1, other), (REPO,))
    bad = tmp_path / "bad.jsonl"
    bad.write_text(idea.replace('"position": ', '"extra": 1, "position": ') + "\n")
    with pytest.raises(ValueError, match="extra"):
        sl.load_ideas((bad,), (REPO,))
    reply = next(x for x in lines if '"experiment": "ideas-reply"' in x
                 and '"role": "lane"' in x)  # fmt: skip
    twice = tmp_path / "twice.jsonl"
    twice.write_text("\n".join([*lines, reply]), encoding="utf-8")
    with pytest.raises(ValueError, match="two sent replies"):
        sl.load_ideas((twice,), (REPO,))
    rows = [json.loads(x) for x in lines]
    for row in rows:  # e-new's row now names e-late's place in its reply
        if row["experiment"] == ip.IDEA_EXPERIMENT and row["title"] == "e-new":
            row["position"] = 3
    moved = tmp_path / "moved.jsonl"
    moved.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows))
    with pytest.raises(ValueError, match="not the idea its reply holds"):
        sl.load_ideas((moved,), (REPO,))


def test_the_independence_rule_orders_the_graders(x1: Path) -> None:
    ideas = sl.load_ideas((x1,), (REPO,))[(REPO, "X1-0")]
    order = sl.grader_order(CHOSEN_55)
    assert order == (im.OPUS_55_MARKER, im.OPUS_5_MARKER)
    assert [sl.grader(i, order) for i in ideas] == [
        im.OPUS_55_MARKER, im.OPUS_5_MARKER, im.OPUS_55_MARKER, im.OPUS_55_MARKER,
    ]  # fmt: skip
    only = sl.grader_order(CHOSEN_5)
    assert only == (im.OPUS_5_MARKER, im.OPUS_55_MARKER)
    assert {sl.grader(i, only) for i in ideas} == {im.OPUS_5_MARKER}
    assert sl.grader_order(NO_MARKER) == ()
    assert sl.grader(ideas[0], ()) is None


def _reply(marker: im.Marker, scores: Sequence[float] | None) -> im.MarkerReply:
    s = sl.rank_set(REPO, "X1-0", ())
    return im.MarkerReply(s, marker, None if scores is None else tuple(scores),
                          None if scores else "x", 0.0, None)  # fmt: skip


def test_each_idea_takes_its_graders_score_and_ties_fall_to_pool_order(
    x1: Path,
) -> None:
    ideas = sl.load_ideas((x1,), (REPO,))[(REPO, "X1-0")]  # f, leap, e-new, e-late
    order = sl.grader_order(CHOSEN_55)
    replies = {
        "opus-5-5": _reply(im.OPUS_55_MARKER, (3.0, 1.0, 2.0, 4.0)),
        "opus-5": _reply(im.OPUS_5_MARKER, (1.0, 4.0, 2.0, 3.0)),
    }
    picks = sl.picks(ideas, order, replies)
    # the leap idea's 4 is Opus 5's (Opus 5.5 wrote it and put it last)
    assert _picked(picks) == ["leap-new", "e-late", "f-new"]
    assert [(p.grader, p.score, p.rank) for p in picks] == [
        ("opus-5", 4.0, 1), ("opus-5-5", 4.0, 2), ("opus-5-5", 3.0, 3),
    ]  # fmt: skip
    again = sl.picks(ideas, order, replies)  # deterministic
    assert [(p.idea, p.grader, p.score, p.rank) for p in again] == [
        (p.idea, p.grader, p.score, p.rank) for p in picks
    ]
    failed = {**replies, "opus-5": _reply(im.OPUS_5_MARKER, None)}
    assert _picked(sl.picks(ideas, order, failed)) == ["e-late", "f-new", "e-new"]
    fallback = sl.picks(ideas, (), {})
    assert _picked(fallback) == ["f-new", "leap-new", "e-new"]  # the pool's order
    assert {(p.grader, p.score) for p in fallback} == {(None, None)}
    assert sl.TOP == 3 and len(sl.shown(ideas * 4)) == sl.SHOWN_MAX


def test_a_pick_is_a_normal_efficiency_hypothesis_of_its_lane_idea(x1: Path) -> None:
    idea = sl.load_ideas((x1,), (REPO,))[(REPO, "X1-0")][1]
    h = sl.hypothesis(idea)
    assert h.title == "leap-new" and h.change_class is ChangeClass.efficiency
    assert h.rationale == (
        "Change leap-new.\nWhy it should win: leap-new removes the hot loop."
        "\nPrecondition: Inputs are str.\nWhy the output stays the same: Same values."
    )
    assert (h.expected_gain, h.provability, h.risk) == (1.0, 0.7, 0.2)  # clamped
    assert h.tags == ("lane:leap", "claimed_tier:exploratory",
                      "claimed_mechanism:remove_work", "claimed_cell:work:eliminate",
                      "claimed_typicality:uncommon")  # fmt: skip
    assert h.hotspot_ids == () and carry([h]) == (h,)
    assert not is_proposal(h)


# ---------------------------------------------------------------------------
# The plan: need, minutes, fuse, refusals before any spend
# ---------------------------------------------------------------------------


def test_the_need_is_the_worst_case_of_two_libraries_under_the_fuse() -> None:
    plan = sl.slice_plan(TWO)
    assert [r.name for r in plan.repos] == ["sqlparse", "pyparsing"]
    assert sl.TRIAL_USD == OSS_TRIAL_CAP_USD == 2.5  # E2's per-trial worst case
    assert sl.loop_cap(3) == 7.5 and sl.loop_cap(1) == 2.5
    assert sl.MARKER_LIBRARY_USD == ceil_usd(4 * im.set_usd()) == 2.0
    # O41's pooled tournament at its bound (40 ideas: 11 requests a marker)
    assert sl.POOL_LIBRARY_USD == ipool.library_usd() == 5.45
    assert plan.library_cap() == ceil_usd(4 * 7.5 + 2.0 + 5.45) == 37.45
    assert sl.slice_need(plan) == 74.9 <= X1_FUSE_USD < CAP_CEILING_USD
    one = sl.slice_plan({sl.REPOS_ENV: "sortedcontainers", SUITE_CAP_ENV: "38"})
    assert sl.slice_need(one) == 37.45
    assert sl.SLICE_REPOS == ("sqlparse", "pyparsing", "tomli", "sortedcontainers")
    assert sl.CONTROL == "sortedcontainers"
    # L2b's 4.2 minutes a loop of up to 3 trials, twice over: 9; a clone,
    # two marker requests a configuration at Vb's 2 minutes, and the pooled
    # tournament's 22 requests at 30 s at its bound
    assert plan.minutes() == 2 * (1 + 11 + 4 * (2 * 2 + 9)) == 128 <= sl.JOB_MINUTES


def test_three_libraries_are_past_the_fuse_and_the_job() -> None:
    three = sl.SlicePlan(sl.SLICE_LIBRARIES[:3])
    assert sl.slice_need(three) == pytest.approx(112.35) and 112.35 > X1_FUSE_USD
    assert three.minutes() == 192 > sl.JOB_MINUTES
    with pytest.raises(ValueError, match="80 USD fuse or the 150-minute job"):
        sl.check_fuse(three)
    sl.check_fuse(sl.SlicePlan(sl.SLICE_LIBRARIES[2:]))


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({SUITE_CAP_ENV: "64"}, "name the dispatch's libraries"),
        ({sl.REPOS_ENV: "sqlparse,pyparsing,tomli", SUITE_CAP_ENV: "113"}, "at most 2"),
        ({sl.REPOS_ENV: "idna", SUITE_CAP_ENV: "64"}, "must name distinct"),
        ({sl.REPOS_ENV: "tomli,tomli", SUITE_CAP_ENV: "64"}, "must name distinct"),
        ({sl.REPOS_ENV: "sqlparse,pyparsing", SUITE_CAP_ENV: "74.89"}, "below"),
        ({**TWO, sl.IDEAS_ENV: "tests/fixtures/ideas_slice/none.jsonl"}, "no X1"),
        ({**TWO, sl.MARKER_ENV: "/nowhere/marker.jsonl"}, "no marker"),
        ({**TWO, sl.MARKER_ENV: "pyproject.toml,uv.lock"}, "one results file"),
    ],
)
def test_a_bad_plan_is_refused(environ: Mapping[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        sl.slice_plan(environ)


def test_the_paths_are_read_relative_to_the_service(x1: Path) -> None:
    other = x1.with_name("x1-b.jsonl")
    other.write_text("", encoding="utf-8")
    plan = sl.slice_plan({**TWO, sl.IDEAS_ENV: f"{x1},{other}", sl.MARKER_ENV: str(x1)})
    assert plan.ideas == (x1, other) and plan.marker == x1
    with pytest.raises(ValueError, match="twice"):
        sl.slice_plan({**TWO, sl.IDEAS_ENV: f"{x1},{x1}"})
    assert sl.slice_plan(TWO).ideas == () and sl.slice_plan(TWO).marker is None


@pytest.mark.parametrize(
    ("update", "match"),
    [
        ({"OP_COUNT_JUDGE": False}, "OP_COUNT_JUDGE"),
        ({"ENGINE_MODEL": SONNET}, "Opus 5.5"),
        ({"EDITOR_MODEL": SONNET}, "Opus 5.5"),
    ],
)
def test_the_engine_is_checked_before_any_spend(
    update: Mapping[str, object], match: str, x1: Path
) -> None:
    base = _base(**update)
    with pytest.raises(ValueError, match=match):
        sl.check_engine(base)
    plan = sl.SlicePlan(sl.slice_plan(TWO).repos, (x1,), x1)
    with pytest.raises(ValueError, match=match):
        sl.SliceRecorder(plan, ResultsSink({}), base=base)
    started: list[float] = []

    def live(cap: float) -> LiveRun:
        started.append(cap)
        return LiveRun("x", cap)

    recorder = sl.SliceRecorder(plan, ResultsSink({}), base=_base(),
                                ideas={}, decision=NO_MARKER, pools={})  # fmt: skip
    with pytest.raises(ValueError, match=match):
        sl.run_library(dx.OSS_SELECTABLE[0], live=live, root=Path("/nowhere"),
                       isolation=REQUIRED, recorder=recorder, base=base)  # fmt: skip
    assert started == []
    sl.check_engine(_base())
    sl.check_engine(_base(EDITOR_MODEL=OPUS))


def test_the_recorder_needs_both_inputs_and_reads_vbs_verdict(
    x1: Path, tmp_path: Path
) -> None:
    repos = sl.slice_plan(TWO).repos
    with pytest.raises(ValueError, match=sl.IDEAS_ENV):
        sl.SliceRecorder(sl.SlicePlan(repos, (), x1), ResultsSink({}), base=_base())
    with pytest.raises(ValueError, match=sl.MARKER_ENV):
        sl.SliceRecorder(
            sl.SlicePlan(repos, (x1,), None), ResultsSink({}), base=_base()
        )
    tomli = tuple(r for r in dx.OSS_SELECTABLE if r.name == REPO)
    empty = tmp_path / "marker.jsonl"
    empty.write_text("", encoding="utf-8")  # no reply row: Vb's scorer passes none
    recorder = sl.SliceRecorder(sl.SlicePlan(tomli, (x1,), empty), ResultsSink({}),
                                base=_base())  # fmt: skip
    assert recorder.decision is not None and recorder.decision.chosen is None
    assert recorder.order == ()
    assert (
        recorder.selection.startswith("fallback") and im.NO_MARKER in recorder.selection
    )
    assert recorder.ideas is not None
    assert _titles(recorder.ideas[(REPO, "X1-0")])[:1] == ["f-new"]
    marked = sl.SliceRecorder(sl.SlicePlan(tomli, (x1,), empty), ResultsSink({}),
                              base=_base(), decision=CHOSEN_55)  # fmt: skip
    assert marked.selection == f"marker opus-5-5 ({im.HIGHER})"
    assert marked.pools is not None and len(marked.pools[REPO]) == 9  # O41's pool
    given = sl.SliceRecorder(sl.SlicePlan(tomli, (x1,), empty), ResultsSink({}),
                             base=_base(), decision=CHOSEN_55, pools={})  # fmt: skip
    assert given.pools == {}  # an override is kept, never reloaded
    # audits but no ideas-idea row: the pool refuses before any clone or request
    lines = x1.read_text(encoding="utf-8").splitlines()
    bare = tmp_path / "bare.jsonl"
    bare.write_text("\n".join(x for x in lines
                              if f'"experiment": "{ip.IDEA_EXPERIMENT}"' not in x))  # fmt: skip
    assert sl.load_ideas((bare,), (REPO,))[(REPO, "X1-0")] == ()  # the slice's own
    with pytest.raises(ValueError, match=f"{REPO}: no ideas-idea rows in the X1"):
        sl.SliceRecorder(sl.SlicePlan(tomli, (bare,), empty), ResultsSink({}),
                         base=_base(), decision=CHOSEN_55)  # fmt: skip


# ---------------------------------------------------------------------------
# One library: the markers, one loop per configuration, the records
# ---------------------------------------------------------------------------

ANSWERS: Mapping[str, Sequence[str]] = {
    OPUS: ("e-late", "f-new", "e-new", "leap-new", "x1-copies-x0"),
    OPUS_5: ("leap-new", "e-late", "e-new", "f-new"),
}


def _order(body: Json) -> str:
    text = "\n".join(block["text"] for block in body["messages"][0]["content"])
    lines = re.findall(r'^\{"id": "I\d+".*$', text, re.MULTILINE)
    ids = {d["title"]: d["id"] for d in map(json.loads, lines)}
    wanted = [t for t in ANSWERS[body["model"]] if t in ids]
    wanted += sorted(t for t in ids if t not in wanted)  # a pooled set's others
    return json.dumps({"order": [ids[t] for t in wanted]})


def _hot(repo: str = REPO) -> im.HotCode:
    return im.HotCode(repo, "cProfile: parse 1.0 s", (("tomli/_parser.py:parse lines 1-2", "def parse(): pass"),))  # fmt: skip


def _objective() -> Objective:
    return dg._facts(Path("/tmp/x")).objective


def _judges(gain: float, *, op: bool = True) -> tuple[JudgeResult, ...]:
    speed = JudgeResult(judge="speed", outcome=JudgeOutcome.passed,
                        metric=_objective().metric, gain=gain, noise_floor=0.02,
                        reason="r")  # fmt: skip
    count = JudgeResult(
        judge=OP_COUNT_JUDGE, outcome=JudgeOutcome.not_applicable, metric="op_calls",
        baseline=RunStats.from_samples((1000.0,), unit="calls"),
        trial=RunStats.from_samples((800.0,), unit="calls"), reason="shadow",
        details={"shadow": True, "change": -0.2},
    )  # fmt: skip
    return (speed, count) if op else (speed,)


def _state(hypotheses: Sequence[Hypothesis], *, op: bool = True) -> EngineRunResult:
    verdicts = [
        Verdict(trial_id=new_id(), hypothesis_id=h.id, change_class=h.change_class,
                outcome=VerdictOutcome.keep if k == 0 else VerdictOutcome.reject,
                judge_results=_judges(0.12 if k == 0 else 0.01, op=op),
                gain=0.12 if k == 0 else 0.01, summary="s")
        for k, h in enumerate(hypotheses)
    ]  # fmt: skip
    combination = Combination(
        base_commit="b" * 40, tip_commit="c" * 40,
        applied_trial_ids=(verdicts[0].trial_id,), judge_results=_judges(0.11),
        holds=True, summary=f"greedy held {SECRET} " + "x" * 900,
    )  # fmt: skip
    state = {
        "objectives": [_objective()], "verdicts": verdicts, "combination": combination,
        "trials": [Trial(hypothesis_id=h.id, round=1) for h in hypotheses],
        "delivery": object(), "seeded_calls": 1, "seeded_cost_usd": 0.25,
    }  # fmt: skip
    return EngineRunResult("run", "done", cast(Any, state), None)


class _Engine:
    """The fake loop: ``start_arm_loop`` and ``run_engine`` as the slice calls
    them, keeping each loop's candidates and its call order."""

    def __init__(self, *, op: bool = True, judged: bool = True) -> None:
        self.op, self.judged = op, judged
        self.loops: list[tuple[Path, tuple[Hypothesis, ...], float]] = []
        self.ran: list[Path] = []
        self.calls: list[str] = []

    def start(self, repo: OssRepo, run: LiveRun, root: Path, isolation: Isolation,
              candidates: Sequence[Hypothesis], *, policy: object) -> Any:  # fmt: skip
        assert isolation is REQUIRED and policy is og.LOCAL
        self.calls.append(f"start {root.name}")
        self.loops.append((root, tuple(candidates), run.cap_usd))
        judges = (OpCountJudge(),) if self.judged else ()
        return SimpleNamespace(root=root, candidates=tuple(candidates),
                               context=SimpleNamespace(judges=judges))  # fmt: skip

    def run(self, loop: Any, run: LiveRun, isolation: Isolation, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        assert model == OPUS
        self.calls.append(f"run {loop.root.name}")
        self.ran.append(loop.root)
        record(SimpleNamespace(guard="ok"), _state(loop.candidates, op=self.op))
        return None


@pytest.fixture
def slice_run(
    x1: Path, dry: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., tuple[list[LiveRun], dg.Wire, _Engine, Path]]]:
    def go(
        decision: im.Decision = CHOSEN_55, engine: _Engine | None = None
    ) -> tuple[list[LiveRun], dg.Wire, _Engine, Path]:
        engine = engine or _Engine()
        wire, runs = dg.Wire(_order), []
        out = tmp_path / "slice.jsonl"
        monkeypatch.setattr(sl, "start_arm_loop", engine.start)
        monkeypatch.setattr(sl, "run_engine", engine.run)
        cloned: list[Path] = []
        # the markers' and the pooled tournament's one clone (``ipool.hot_of``)
        monkeypatch.setattr(ipool, "clone_pinned", lambda *a, **k: cloned.append(a[3]))
        monkeypatch.setattr(ipool, "hot_code", lambda repo, dest: _hot(repo.name))

        def live(cap: float) -> LiveRun:
            engine.calls.append(f"live {cap:g}")
            runs.append(run := wire.run(cap))
            return run

        tomli = tuple(r for r in dx.OSS_SELECTABLE if r.name == REPO)
        plan = sl.SlicePlan(tomli, (x1,), x1)
        recorder = sl.SliceRecorder(plan, ResultsSink({RESULTS_ENV: str(out)}),
                                    base=_base(), decision=decision)  # fmt: skip
        sl.run_library(tomli[0], live=cast(StartLive, live), root=tmp_path / "root",
                       isolation=REQUIRED, recorder=recorder, policy=og.LOCAL,
                       base=_base(LLM_MAX_RETRIES=0))  # fmt: skip
        assert cloned == (
            [tmp_path / "root" / f"hot-{REPO}"] if decision.chosen else []
        )
        return runs, wire, engine, out

    yield go


def _records(path: Path, experiment: str) -> list[Json]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["experiment"] == experiment]


def test_one_loop_per_configuration_one_trial_per_pick(slice_run: Any) -> None:
    runs, wire, engine, out = slice_run()
    # the markers' run first (X1-0's set on both, X1-1's on Opus 5.5), every
    # request counted and capped before it went, then one loop per pick set
    marker_cap = ceil_usd(2 * im.request_worst(im.OPUS_55_MARKER)
                          + im.request_worst(im.OPUS_5_MARKER))  # fmt: skip
    # then the pooled tournament (O41): 9 lens-lane ideas, sets of 5 and 4,
    # then a final set of 4, on each marker: 3 requests each
    pool_cap = ceil_usd(3 * im.set_usd())
    assert [r.cap_usd for r in runs] == [marker_cap, pool_cap, 7.5, 2.5]
    assert [b["model"] for b in wire.bodies] == [OPUS, OPUS_5, OPUS, *[OPUS] * 3,
                                                 *[OPUS_5] * 3]  # fmt: skip
    assert len(wire.counted) == 9 and len(runs[0].records) == 3
    assert len(runs[1].records) == 6
    assert engine.calls == [f"live {marker_cap:g}", f"live {pool_cap:g}", "live 7.5",
                            "start X1-0", "run X1-0", "live 2.5", "start X1-1",
                            "run X1-1"]  # fmt: skip
    (root0, cands0, _), (root1, cands1, _) = engine.loops
    assert [h.title for h in cands0] == ["leap-new", "e-late", "f-new"]
    assert [h.title for h in cands1] == ["x1-copies-x0"]
    assert (root0.name, root1.name) == ("X1-0", "X1-1")
    assert cands0[1].rationale.startswith("Change e-late.\nWhy it should win:")


def test_the_records_join_the_ideas_idea_rows_and_carry_the_op_counts(
    slice_run: Any, x1: Path
) -> None:
    _, _, engine, out = slice_run()
    ideas = {(r["repo"], r["arm"], r["label"], r["position"]): r
             for r in _records(x1, ip.IDEA_EXPERIMENT)}  # fmt: skip
    trials = _records(out, sl.TRIAL_EXPERIMENT)
    assert [(t["arm"], t["title"], t["rank"]) for t in trials] == [
        ("X1-0", "leap-new", 1), ("X1-0", "e-late", 2), ("X1-0", "f-new", 3),
        ("X1-1", "x1-copies-x0", 1),
    ]  # fmt: skip
    for t in trials:
        source = ideas[(t["repo"], t["arm"], t["label"], t["position"])]
        assert (source["title"], source["lane"], source["model"]) == (
            t["title"], t["lane"], t["model"])  # fmt: skip
        assert t["mechanism"] == source["mechanism"] and t["target"] == source["target"]
        assert t["op_count"]["present"] and t["op_count"]["base"] == 1000.0
        assert t["op_count"]["cell"] == "1000 → 800 calls (-20.0%)"
        assert t["selection"] == f"marker opus-5-5 ({im.HIGHER})"
        assert "".join(t["rationale"]).startswith(f"Change {t['title']}.")
    first = trials[0]
    assert (first["grader"], first["score"], first["verdict"]) == (
        "opus-5",
        4.0,
        "keep",
    )
    assert first["gain_pct"] == pytest.approx(12.0)
    assert first["floor_pct"] == pytest.approx(2.0)
    assert first["hypothesis_id"] == engine.loops[0][1][0].id
    assert trials[1]["verdict"] == "reject"
    combines = {c["arm"]: c for c in _records(out, sl.COMBINE_EXPERIMENT)}
    assert set(combines) == set(sl.SLICE_CONFIGS)
    c0 = combines["X1-0"]
    assert (c0["eligible"], c0["picked"], c0["kept"], c0["holds"]) == (4, 3, 1, True)
    assert c0["gain_pct"] == pytest.approx(11.0) and c0["delivered"] is True
    assert c0["applied"] == 1 and c0["guard"] == "ok" and c0["cost_usd"] == 0.0
    assert (combines["X1-2"]["picked"], combines["X1-2"]["guard"]) == (
        0, sl.NO_IDEA)  # fmt: skip
    # D64's cost line reaches the report: the run's seeded counters, 0 / 0.0
    # for a configuration that ran no loop; Vf's loader reads the real rows
    assert (c0["seeded_calls"], c0["seeded_cost_usd"]) == (1, 0.25)
    assert (combines["X1-2"]["seeded_calls"], combines["X1-2"]["seeded_cost_usd"]) == (
        0, 0.0)  # fmt: skip
    parsed = report._parsed([out], [sl.COMBINE_EXPERIMENT, sl.TRIAL_EXPERIMENT])
    lines = [
        c for c in parsed[sl.COMBINE_EXPERIMENT] if isinstance(c, report.CombineLine)
    ]
    assert {(c.arm, c.seeded_calls) for c in lines} >= {("X1-0", 1), ("X1-2", 0)}
    assert len(parsed[sl.TRIAL_EXPERIMENT]) == len(trials)  # Vf reads Ve's trials too
    markers = _records(out, sl.MARKER_EXPERIMENT)
    assert [(m["arm"], m["marker"], len(m["shown"])) for m in markers] == [
        ("X1-0", "opus-5-5", 4), ("X1-0", "opus-5", 4), ("X1-1", "opus-5-5", 1),
    ]  # fmt: skip
    assert markers[0]["shown"][0] == {"label": "far", "position": 1}
    assert markers[1]["scores"] == [1.0, 4.0, 2.0, 3.0] and markers[0]["error"] is None
    text = out.read_text(encoding="utf-8")
    assert SECRET not in text and "[redacted]" in text
    for row in (*trials, *combines.values(), *markers):
        for value in row.values():
            chunks = value if isinstance(value, list) else [value]
            assert all(len(x) <= JSON_TEXT_MAX for x in chunks if isinstance(x, str))


def test_without_a_marker_the_slice_runs_the_fallback_and_says_so(
    slice_run: Any,
) -> None:
    runs, wire, engine, out = slice_run(NO_MARKER)
    assert wire.bodies == [] and [r.cap_usd for r in runs] == [7.5, 2.5]
    assert _records(out, ipool.RESULT_EXPERIMENT) == []  # no marker: no pooled rank
    assert [h.title for h in engine.loops[0][1]] == ["f-new", "leap-new", "e-new"]
    trials = _records(out, sl.TRIAL_EXPERIMENT)
    assert {t["selection"] for t in trials} == {f"fallback ({im.NO_MARKER}): "
                                                 f"{sl.FALLBACK}"}  # fmt: skip
    assert {(t["grader"], t["score"]) for t in trials} == {(None, None)}
    assert _records(out, sl.MARKER_EXPERIMENT) == []


def test_a_loop_without_the_op_count_judge_is_refused_before_it_runs(
    slice_run: Any,
) -> None:
    engine = _Engine(judged=False)
    with pytest.raises(AssertionError, match="op_count"):
        slice_run(engine=engine)
    assert engine.ran == [] and engine.calls[-1] == "start X1-0"


def test_a_verdict_without_the_op_count_column_fails_after_its_records(
    slice_run: Any, tmp_path: Path
) -> None:
    engine = _Engine(op=False)
    with pytest.raises(AssertionError, match="op-count column"):
        slice_run(engine=engine)
    trials = _records(tmp_path / "slice.jsonl", sl.TRIAL_EXPERIMENT)
    assert len(trials) == 3 and {t["op_count"]["present"] for t in trials} == {False}


def test_a_breach_is_recorded_then_raised(slice_run: Any, tmp_path: Path) -> None:
    class _Breach(_Engine):
        def run(self, loop: Any, run: LiveRun, isolation: Isolation, *, model: str,
                record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
            record(SimpleNamespace(guard=f"breach: AssertionError: {SECRET}"), None)
            raise AssertionError("the user's repository changed")

    with pytest.raises(AssertionError, match="repository changed"):
        slice_run(engine=_Breach())
    out = tmp_path / "slice.jsonl"
    trials = _records(out, sl.TRIAL_EXPERIMENT)
    assert {t["verdict"] for t in trials} == {dx.NO_RESULT}
    (combine,) = _records(out, sl.COMBINE_EXPERIMENT)
    assert combine["guard"].startswith("breach: ") and combine["combined"] is False
    assert SECRET not in out.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The real wiring, unsent: the engine's judges hold the op-count judge
# ---------------------------------------------------------------------------


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


def test_the_real_loop_is_the_oss_wiring_with_the_op_count_judge(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, x1: Path
) -> None:
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    repo = og._local_repo(url, commit)
    hypotheses = [p.hypothesis for p in
                  sl.picks(sl.load_ideas((x1,), (REPO,))[(REPO, "X1-0")], (), {})]  # fmt: skip
    run = LiveRun("dry", sl.loop_cap(3), wire=httpx2.MockTransport(_no_wire))
    monkeypatch.setattr(settings, "OP_COUNT_JUDGE", True)
    loop = dx.start_arm_loop(repo, run, root / "X1-0", REQUIRED, hypotheses,
                             policy=og.LOCAL)  # fmt: skip
    sl.check_judges(loop)
    assert [h.title for h in loop.context.candidates] == ["f-new", "leap-new", "e-new"]
    assert [h.id for h in loop.context.candidates] == [h.id for h in hypotheses]
    assert loop.context.max_hypotheses_per_round == 3 and loop.cap_usd == 7.5
    assert run.capture.exchanges == []
    monkeypatch.setattr(settings, "OP_COUNT_JUDGE", False)
    off = dx.start_arm_loop(repo, run, root / "X1-1", REQUIRED, hypotheses[:1],
                            policy=og.LOCAL)  # fmt: skip
    with pytest.raises(AssertionError, match="op_count"):
        sl.check_judges(off)


def test_the_live_module_reads_its_plan_first_and_runs_each_library() -> None:
    text = (LIVE_DIR / "test_ideas_slice_live.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live" in text
    assert '@pytest.fixture(scope="module")' in text
    assert "SliceRecorder(slice_plan(os.environ), ResultsSink(os.environ))" in text
    assert "run_library(" in text and "pytest.skip(" in text
    assert [r.name for r in sl.SLICE_LIBRARIES] == list(sl.SLICE_REPOS)


def test_a_title_past_the_markers_bound_is_clipped_not_refused(x1: Path) -> None:
    """Lane titles are unbounded upstream; Vb's RankRow takes at most 300
    characters, so the slice shows the first 300 instead of failing."""
    long = "Speed up " + "x" * 400
    ideas = next(v for v in sl.load_ideas([x1], ["tomli"]).values() if v)[:1]
    clipped = [dataclasses.replace(i, row=i.row.model_copy(update={"title": long}))
               for i in ideas]  # fmt: skip
    (row,) = sl.rank_set("tomli", "X1-0", clipped).rows
    assert row.title == long[:300]
    assert clipped[0].row.title == long  # only the request is clipped, never the record


# ---------------------------------------------------------------------------
# O39: each row says whether its grader passed O37, read from Vb's verdict
# ---------------------------------------------------------------------------

O39 = im.Decision("opus-5-5", im.ONE, ("opus-5-5",), ())  # Vb's verdict, 2026-11-03
VALIDATION = TESTS_DIR.parents[2] / ".claude/handoff/step3/idea-lab/x1-validation"
VB_RESULTS = VALIDATION / "ideas-marker-41642619744.jsonl"
O39_FIELDS = ("grader_validated", "validated", "grades")
# sha256 of the slice rows HEAD 8633ee3 wrote for ``slice_run(O39)``, without
# the random hypothesis ids (and O39's new fields, which HEAD did not write)
SLICE_GOLDEN = "eb1820c901a2c99b6b170216f3f855a14f37005838ac36cf91d7709a7d18a196"


def test_an_opus_5_5_idea_is_graded_by_opus_5_and_marked_unvalidated(
    slice_run: Any,
) -> None:
    _, _, _, out = slice_run(O39)
    trials = _records(out, sl.TRIAL_EXPERIMENT)
    leap = next(t for t in trials if t["title"] == "leap-new")
    assert (leap["lane"], leap["model"], leap["grader"], leap["grader_validated"]) == (
        "leap", OPUS, "opus-5", False)  # fmt: skip
    others = {(t["grader"], t["grader_validated"]) for t in trials if t is not leap}
    assert others == {("opus-5-5", True)}
    markers = _records(out, sl.MARKER_EXPERIMENT)
    assert [(m["arm"], m["marker"], m["validated"], m["grades"]) for m in markers] == [
        ("X1-0", "opus-5-5", True, [True, False, True, True]),
        ("X1-0", "opus-5", False, [False, True, False, False]),  # the leap's grade
        ("X1-1", "opus-5-5", True, [True]),
    ]  # fmt: skip
    # the report reads both fields as Ve writes them, through to its table cell
    # the report reads the trial's fields as Ve writes them, through to its
    # cell (O40 replaced the within-set count: the marker rows are not read)
    parsed = report._parsed([out], [sl.TRIAL_EXPERIMENT])
    (line,) = [t for t in parsed[sl.TRIAL_EXPERIMENT]
               if isinstance(t, report.TrialLine) and t.title == "leap-new"]  # fmt: skip
    assert report.trial_cell(line) == "keep (graded by opus-5, unvalidated)"
    assert sl.MARKER_EXPERIMENT not in report._KINDS


@pytest.mark.parametrize(
    ("decision", "graders"),
    [
        (CHOSEN_55, {("opus-5-5", True), ("opus-5", True)}),  # both passed
        (CHOSEN_5, {("opus-5", True)}),  # Opus 5 alone passed: it grades all
        (NO_MARKER, {(None, None)}),  # the fallback: no grader, nothing validated
    ],
)
def test_the_validated_field_follows_vbs_verdict_never_a_constant(
    slice_run: Any, decision: im.Decision, graders: set[tuple[str | None, bool | None]]
) -> None:
    _, _, _, out = slice_run(decision)
    trials = _records(out, sl.TRIAL_EXPERIMENT)
    assert {(t["grader"], t["grader_validated"]) for t in trials} == graders
    assert all(m["validated"] == (m["marker"] in decision.passed)
               for m in _records(out, sl.MARKER_EXPERIMENT))  # fmt: skip


def test_vbs_verdict_row_is_read_and_a_disagreeing_one_refused(
    x1: Path, tmp_path: Path
) -> None:
    tomli = tuple(r for r in dx.OSS_SELECTABLE if r.name == REPO)
    real = sl.SliceRecorder(sl.SlicePlan(tomli, (x1,), VB_RESULTS), ResultsSink({}),
                            base=_base())  # fmt: skip
    assert real.decision == O39
    assert (real.validated("opus-5-5"), real.validated("opus-5")) == (True, False)
    assert real.validated(None) is None
    lines = VB_RESULTS.read_text(encoding="utf-8").splitlines()
    verdict = next(x for x in lines if f'"{im.VERDICT_EXPERIMENT}"' in x)
    forged = verdict.replace(
        '"passed": ["opus-5-5"]', '"passed": ["opus-5-5", "opus-5"]'
    )
    for name, body, match in (
        ("forged", [x for x in lines if x != verdict] + [forged], "disagrees"),
        ("twice", [*lines, verdict], "twice"),
    ):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match=f"{im.VERDICT_EXPERIMENT}.*{match}"):
            sl.SliceRecorder(sl.SlicePlan(tomli, (x1,), path), ResultsSink({}),
                             base=_base())  # fmt: skip


def test_every_other_slice_field_is_heads(slice_run: Any) -> None:
    _, _, _, out = slice_run(O39)
    rows = [
        {
            k: v
            for k, v in json.loads(x).items()
            if k not in (*O39_FIELDS, "hypothesis_id")
        }
        for x in out.read_text(encoding="utf-8").splitlines()
        if '"experiment": "ideas-pool-' not in x
    ]  # O41's rows: their own test
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    assert digest == SLICE_GOLDEN


# ---------------------------------------------------------------------------
# O40/O41: the slice ranks its library's pool by the shared tournament
# ---------------------------------------------------------------------------


def test_the_slice_ranks_its_librarys_pool_by_the_shared_tournament(
    slice_run: Any, x1: Path
) -> None:
    _, wire, _, out = slice_run(O39)
    pool = ipool.load_pools((x1,), (REPO,))[REPO]
    assert {i.row.title for i in pool} == {
        "f-new",
        "f-dup-a",
        "f-behaviour",
        "e-family",
        "e-new",
        "e-late",
        "e-unaudited",
        "x1-copies-x0",
        "x1-via-a",
    }  # every returned lens-lane idea: audited or not, new or not, any class
    sets = _records(out, ipool.SET_EXPERIMENT)
    assert [(s["marker"], s["round"], len(s["ids"])) for s in sets] == [
        (m, r, n) for m in ("opus-5-5", "opus-5") for r, n in ((1, 5), (1, 4), (2, 4))
    ]  # fmt: skip
    results = _records(out, ipool.RESULT_EXPERIMENT)
    assert [(r["repo"], r["marker"], r["validated"]) for r in results] == [
        (REPO, "opus-5-5", True), (REPO, "opus-5", False)]  # fmt: skip
    assert all(len(r["members"]) == 9 and len(r["top"]) == 3 for r in results)
    assert all(sum(r["counts"].values()) == 3 for r in results)
    for body in wire.bodies[3:]:  # after the slice's three marker requests
        text = "\n".join(block["text"] for block in body["messages"][0]["content"])
        assert 1 < len(re.findall(r'^\{"id": "I\d+"', text, re.M)) <= ipool.SET_SIZE
    # the pool's hot code is the markers' one clone (``slice_run`` asserts it)
