"""Offline guards of the pooled marker-feasible ranking (V-O40, ``ideas_pool.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_pool_live.py`` or the slice, that the pool is X1-0 to X1-3's
lens-lane results only, read from Vd's own rows; that the validated marker
never ranks its own model's ideas (listed apart) while the other candidate
ranks the whole pool, marked by Vb's verdict, never a constant; that the
tournament splits by sorted idea id (an id carrying no configuration, lane
or model) into ceil(n/6) sets as equal as possible, advances two a set and
ends in one final set, so no request shows more than the set size; that
the counts sum to min(3, pool size); that the request is Vb's blind one;
that every cap refuses before spend; and the new suite's plan and need.

Fakes and what they stand for: ``dg.Wire`` (and ``mg._Wire``, which counts
past the bound) for the Messages API; hand-made ``HotCode`` for a pinned
clone's hot code; a hand-built ``ideas_marker.Decision`` for Vb's verdict
(one test reads the committed results file through Vb's own scorer); a
``rank`` callback for the marker in the pure tournament tests. What only a
live run proves: the markers' orders on the eight libraries.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.optimization.idea_types import LENS_LANES

from . import ideas_marker as im
from . import ideas_pool as ipool
from . import ideas_probe as ip
from . import ideas_report as report
from . import test_discovery_guards as dg
from . import test_ideas_marker_guards as mg
from . import test_ideas_slice_guards as sg
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun
from .corpus import RESULTS_ENV
from .discovery import OPUS, SONNET, ceil_usd
from .discovery_io import ResultsSink
from .oss import OssRepo

dry = dg.dry

Json = dict[str, Any]
LIVE_DIR = TESTS_DIR / "live"
O55, O5 = im.OPUS_55_MARKER, im.OPUS_5_MARKER
O39 = im.Decision("opus-5-5", im.ONE, ("opus-5-5",), ())  # Vb's verdict, 2026-11-03
BOTH = im.Decision("opus-5-5", im.HIGHER, ("opus-5-5", "opus-5"), ())
ONLY_5 = im.Decision("opus-5", im.ONE, ("opus-5",), ())
NONE = im.Decision(None, im.NO_MARKER, (), ())
REPO = "idna"
FOUR = {SUITE_CAP_ENV: "22"}

# ---------------------------------------------------------------------------
# X1's rows, written by Vd's own recorder
# ---------------------------------------------------------------------------

# (arm, lane, model, role, [(title, class)], returned titles)
Spec = tuple[str, str, str, str, list[tuple[str, str]], list[str]]
ROWS: list[Spec] = [
    ("A", "today", SONNET, "generator", [], ["a-today"]),
    ("X1-0", "obvious", SONNET, "lane", [("s1-obvious", "efficiency")], ["s1-obvious"]),
    ("X1-0", "far", SONNET, "lane",
     [("x0-far", "efficiency"), ("x0-far-2", "behaviour")], ["x0-far", "x0-far-2"]),
    ("X1-0", "eliminate", SONNET, "lane",
     [("x0-elim", "efficiency"), ("x0-dropped", "efficiency")], ["x0-elim"]),
    ("X1-0", "leap", OPUS, "leap", [("x0-leap", "efficiency")], ["x0-leap"]),
    ("X1-1", "far", OPUS, "lane", [("x1-opus-lens", "efficiency")], ["x1-opus-lens"]),
    ("X1-1", "assume_less", ip.HAIKU, "lane",
     [("x1-haiku-lens", "efficiency")], ["x1-haiku-lens"]),
    ("X1-2", "eliminate", SONNET, "lane", [("x2-elim", "efficiency")], ["x2-elim"]),
    ("X1-2", "relax_api", SONNET, "lane", [("x2-relax", "efficiency")], ["x2-relax"]),
    ("X1-3", "far", SONNET, "lane", [("x3-far", "efficiency")], ["x3-far"]),
    ("X1-4", "relax_dependency", SONNET, "lane",
     [("x4-relax", "efficiency")], ["x4-relax"]),
]  # fmt: skip
POOLED = {"x0-far", "x0-far-2", "x0-elim", "x1-opus-lens", "x1-haiku-lens",
          "x2-elim", "x3-far"}  # fmt: skip
ARMS = {a.key: a for a in ip.X1_ARMS}


def write_x1(path: Path, repo: str = REPO, rows: Sequence[Spec] = ROWS) -> Path:
    """``rows`` recorded by ``ip.ProbeRecorder`` as an X1 dispatch writes them."""
    by_arm: dict[str, tuple[list[ip.Exchange], list[tuple[str, str]]]] = {}
    for arm, lane, model, role, items, returned in rows:
        exchanges, kept = by_arm.setdefault(arm, ([], []))
        if role == "generator":
            exchanges.append(ip.Exchange("generator", "generator", 5, sg._request("x"),
                                         sent=True, model=model))  # fmt: skip
        else:
            exchanges.append(sg._exchange(
                lane, [sg._item(t, cls=c) for t, c in items], model=model, role=role
            ))  # fmt: skip
        kept += [(t, lane) for t in returned]
    arms = [sg._arm(ARMS[a], ex, kept) for a, (ex, kept) in by_arm.items()]
    recorder = ip.ProbeRecorder(
        ip.ProbePlan((), ()), ResultsSink({RESULTS_ENV: str(path)})
    )
    recorder.record(repo, arms, [], None, LiveRun("dry", 1.0))
    return path


@pytest.fixture
def x1(tmp_path: Path) -> Path:
    return write_x1(tmp_path / "x1.jsonl")


def _titles(ideas: Sequence[ipool.PoolIdea]) -> set[str]:
    return {i.row.title for i in ideas}


def test_the_pool_is_x1_0_to_x1_3s_returned_lens_lane_ideas_only(x1: Path) -> None:
    pool = ipool.load_pools((x1,), (REPO,))[REPO]
    # never S1, the leap, a rule-relaxing lane, arm A or X1-4, an unreturned idea
    assert _titles(pool) == POOLED
    assert {i.row.lane for i in pool} <= ipool.LENSES
    assert {i.row.arm for i in pool} == set(ipool.POOL_CONFIGS)
    assert ipool.POOL_CONFIGS == ("X1-0", "X1-1", "X1-2", "X1-3")
    assert ipool.LENSES == {lane.value for lane in LENS_LANES}
    assert {i.row.title: i.change_class for i in pool}["x0-far-2"] == "behaviour"
    assert [i.id for i in pool] == sorted(i.id for i in pool)  # sorted id order
    assert ipool.load_pools((x1,), ()) == {}


def test_loading_refuses_rows_it_cannot_join(x1: Path, tmp_path: Path) -> None:
    lines = x1.read_text(encoding="utf-8").splitlines()
    idea = next(x for x in lines if '"title": "x3-far"' in x)
    other = tmp_path / "other.jsonl"
    other.write_text(idea + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="recorded in"):
        ipool.load_pools((x1, other), (REPO,))
    moved = tmp_path / "moved.jsonl"
    moved.write_text("\n".join(x.replace('"position": 1', '"position": 3')
                               if '"title": "x0-elim"' in x else x for x in lines))  # fmt: skip
    with pytest.raises(ValueError, match="not the idea its reply holds"):
        ipool.load_pools((moved,), (REPO,))
    reply = next(x for x in lines if '"experiment": "ideas-reply"' in x
                 and '"label": "far"' in x and '"arm": "X1-3"' in x)  # fmt: skip
    twice = tmp_path / "twice.jsonl"
    twice.write_text("\n".join([*lines, reply]), encoding="utf-8")
    with pytest.raises(ValueError, match="two sent replies"):
        ipool.load_pools((twice,), (REPO,))
    # a planned library with no row, or no returned lens-lane idea, is refused:
    # never a zero-count result (the slice refuses the same, before any spend)
    with pytest.raises(ValueError, match="tomli: no ideas-idea rows in the X1 results"):
        ipool.load_pools((x1,), ("tomli",))
    bare = write_x1(tmp_path / "bare.jsonl",
                    rows=[r for r in ROWS if r[0] not in ipool.POOL_CONFIGS
                          or r[1] not in ipool.LENSES])  # fmt: skip
    assert '"experiment": "ideas-idea"' in bare.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match=f"{REPO}: no returned lens-lane idea"):
        ipool.load_pools((bare,), (REPO,))
    again = tmp_path / "again.jsonl"
    again.write_text("\n".join([*lines, idea]), encoding="utf-8")
    with pytest.raises(ValueError, match="an ideas-idea row recorded twice"):
        ipool.load_pools((again,), (REPO,))


def test_the_markers_own_model_is_out_of_the_validated_pool_and_in_opus_5s(
    x1: Path,
) -> None:
    pool = ipool.load_pools((x1,), (REPO,))[REPO]
    first, second = ipool.rankers(pool, O39)
    assert (first.marker, first.validated) == (O55, True)
    assert _titles(first.ideas) == POOLED - {"x1-opus-lens"}
    assert _titles(first.apart) == {"x1-opus-lens"}  # listed apart, not ranked
    assert (second.marker, second.validated) == (O5, False)  # Vb: Opus 5 failed
    assert second.ideas == pool and second.apart == ()  # the whole pool
    a, b = ipool.rankers(pool, BOTH)  # validated follows Vb's verdict
    assert (a.validated, b.validated) == (True, True)
    c, d = ipool.rankers(pool, ONLY_5)  # Opus 5 alone passed: it is the marker
    assert (c.marker, c.validated, c.ideas, c.apart) == (O5, True, pool, ())
    assert (d.marker, d.validated, d.ideas) == (O55, False, pool)
    assert ipool.rankers(pool, NONE) == ()  # no candidate passed O37: no ranking


def _pool(n: int, configs: int = 4) -> list[ipool.PoolIdea]:
    rows = [(f"X1-{k % configs}", LENS_LANES[k % 6].value, SONNET, "lane",
             [(f"idea-{k}", "efficiency")], [f"idea-{k}"]) for k in range(n)]  # fmt: skip
    found: list[ipool.PoolIdea] = []
    for k, row in enumerate(rows):  # one reply a lane: one idea each, own label
        arm, lane, *_ = row
        idea = ipool.IdeaRow(
            experiment="ideas-idea", repo=REPO, arm=arm, lane=lane, label=f"l{k}",
            model=SONNET, position=1, title=f"idea-{k}", change="c", returned=True,
            proposal=False, relaxes=None, mechanism=None, cells=(), path=None,
            target=None,
        )  # fmt: skip
        found.append(ipool.PoolIdea(idea, "efficiency"))
    return sorted(found, key=lambda i: i.id)


def test_an_id_carries_no_configuration_lane_or_model_and_sets_mix_configurations(
    x1: Path,
) -> None:
    pool = ipool.load_pools((x1,), (REPO,))[REPO]
    for i in pool:
        assert re.fullmatch(r"p[0-9a-f]{12}", i.id), i.id
        for leak in (i.row.arm, i.row.lane, i.row.model, i.row.title, i.row.label):
            assert leak not in i.id
    again = ipool.load_pools((x1,), (REPO,))[REPO]
    assert [i.id for i in again] == [i.id for i in pool]  # deterministic
    big = _pool(40)
    by_id = {i.id: i for i in big}
    sets = ipool.split(list(by_id))
    assert all(len({by_id[x].row.arm for x in s}) >= 2 for s in sets)
    assert len({i.id for i in big}) == 40


@pytest.mark.parametrize("n", [1, 3, 6, 7, 13, 40, 100])
def test_the_split_is_deterministic_about_six_and_as_equal_as_possible(n: int) -> None:
    ids = [f"p{k:012x}" for k in range(n)]
    sets = ipool.split(list(reversed(ids)))
    assert len(sets) == math.ceil(n / ipool.SET_SIZE) and ipool.SET_SIZE == 6
    sizes = [len(s) for s in sets]
    assert max(sizes) <= ipool.SET_SIZE and max(sizes) - min(sizes) <= 1
    assert [x for s in sets for x in s] == sorted(ids)  # sorted idea-id order
    assert ipool.split(ids) == sets
    assert ipool.sizes(n) == tuple(sizes)
    assert ipool.split([]) == () and ipool.sizes(0) == ()


def _strength(ids: Sequence[str]) -> dict[str, int]:
    return {x: int(x[1:], 16) * 7919 % 1009 for x in ids}  # a fixed, mixed order


ROUNDS: Mapping[int, tuple[tuple[int, ...], ...]] = {
    0: (),
    1: ((1,),),
    3: ((3,),),
    6: ((6,),),
    7: ((4, 3), (4,)),
    13: ((5, 4, 4), (6,)),
    40: ((6, 6, 6, 6, 6, 5, 5), (5, 5, 4), (6,)),
    100: ((6,) * 15 + (5,) * 2, (6, 6, 6, 6, 5, 5), (6, 6), (4,)),
}


@pytest.mark.parametrize("n", sorted(ROUNDS))
def test_the_tournament_advances_two_a_set_and_ends_in_one_final_set(n: int) -> None:
    ids = [f"p{k:012x}" for k in range(n)]
    power = _strength(ids)
    asked: list[tuple[int, int, int, tuple[str, ...]]] = []

    def rank(rnd: int, k: int, of: int, shown: tuple[str, ...]) -> tuple[str, ...]:
        asked.append((rnd, k, of, shown))
        return tuple(sorted(shown, key=lambda x: -power[x]))

    sets, top = ipool.tournament(ids, rank)
    shape = tuple(tuple(len(s.ids) for s in sets if s.round == r)
                  for r in sorted({s.round for s in sets}))  # fmt: skip
    assert shape == ROUNDS[n] == ipool.rounds(n)
    assert all(len(s.ids) <= ipool.SET_SIZE for s in sets)  # never above the size
    for r in range(1, len(shape)):  # a round's ideas: the last round's top two
        last = [s for s in sets if s.round == r]
        nxt = sorted(x for s in sets if s.round == r + 1 for x in s.ids)
        assert nxt == sorted(x for s in last for x in s.advanced)
        assert all(s.advanced == (s.order or ())[:2] for s in last)
    final = [s for s in sets if s.round == len(shape)]
    assert len(final) == (1 if n else 0) and all(f.advanced == () for f in final)
    assert top == ((final[0].order or ())[: ipool.TOP] if n else ())
    assert top is not None and len(top) == min(ipool.TOP, n)
    # a set of one needs no request; every other set is one
    assert len(asked) == ipool.requests(n) == sum(len(s.ids) > 1 for s in sets)
    assert [(a[0], a[1], a[2]) for a in asked] == [
        (s.round, s.index, s.of) for s in sets if len(s.ids) > 1
    ]
    assert ipool.tournament(list(reversed(ids)), rank)[0] == sets  # deterministic


def test_a_set_without_an_order_stops_the_tournament() -> None:
    ids = [f"p{k:012x}" for k in range(13)]
    calls: list[int] = []

    def rank(
        rnd: int, k: int, of: int, shown: tuple[str, ...]
    ) -> tuple[str, ...] | None:
        calls.append(k)
        return None if k == 2 else shown

    sets, top = ipool.tournament(ids, rank)
    assert top is None and calls == [1, 2] and len(sets) == 2
    assert sets[-1].order is None and sets[-1].advanced == ()

    def wrong(rnd: int, k: int, of: int, shown: tuple[str, ...]) -> tuple[str, ...]:
        return shown[:-1]

    with pytest.raises(ValueError, match="not a permutation"):
        ipool.tournament(ids, wrong)


@pytest.mark.parametrize("n", [0, 1, 2, 3, 7, 40])
def test_the_counts_sum_to_the_smaller_of_three_and_the_pool(n: int) -> None:
    pool = _pool(n)
    by_id = {i.id: i for i in pool}
    power = _strength(list(by_id))
    _, top = ipool.tournament(
        list(by_id), lambda r, k, of, s: tuple(sorted(s, key=lambda x: -power[x]))
    )
    assert top is not None
    counts = ipool.counts(top, pool)
    assert set(counts) == set(ipool.POOL_CONFIGS)
    assert sum(counts.values()) == min(3, n)


# ---------------------------------------------------------------------------
# On the wire: blind, counted and capped, every set at the set size
# ---------------------------------------------------------------------------


def _hot() -> im.HotCode:
    return im.HotCode(REPO, "cProfile: encode 1.0 s",
                      (("idna/core.py:encode lines 1-2", "def encode(): pass"),))  # fmt: skip


def _ideas(body: Json) -> list[Json]:
    text = "\n".join(block["text"] for block in body["messages"][0]["content"])
    return [json.loads(x) for x in re.findall(r'^\{"id": "I\d+".*$', text, re.M)]


def _by_title(body: Json) -> str:
    """Most likely first: by title, descending (a fixed, checkable order)."""
    shown = sorted(_ideas(body), key=lambda d: d["title"], reverse=True)
    return json.dumps({"order": [d["id"] for d in shown]})


def _records(path: Path, experiment: str) -> list[Json]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["experiment"] == experiment]


def _rank_library(
    tmp_path: Path, pool: Sequence[ipool.PoolIdea], decision: im.Decision,
    wire: dg.Wire | None = None, name: str = "pool",
) -> tuple[dg.Wire, list[LiveRun], Path]:  # fmt: skip
    wire = wire or dg.Wire(_by_title)
    runs: list[LiveRun] = []
    out = tmp_path / f"{name}.jsonl"

    def live(cap: float) -> LiveRun:
        runs.append(run := wire.run(cap))
        return run

    hot: list[int] = []

    def get_hot() -> im.HotCode:
        hot.append(1)
        return _hot()

    ipool.rank_library(
        REPO, pool, decision, live=live, hot=get_hot,
        sink=ResultsSink({RESULTS_ENV: str(out)}),
        base=settings.model_copy(update={"LLM_MAX_RETRIES": 0}),
    )  # fmt: skip
    assert bool(hot) == bool(runs)  # the hot code only when a request goes
    return wire, runs, out


def test_the_request_is_vbs_blind_one_and_never_above_the_set_size(
    dry: Path, tmp_path: Path
) -> None:
    pool = _pool(40)
    wire, runs, out = _rank_library(tmp_path, pool, O39)
    assert len(wire.bodies) == 2 * ipool.requests(40) == 22
    assert len(wire.counted) == len(wire.bodies)  # each counted before it went
    assert [r.cap_usd for r in runs] == [ipool.pool_cap(ipool.rankers(pool, O39))]
    for body in wire.bodies:
        ideas = _ideas(body)
        assert 1 < len(ideas) <= ipool.SET_SIZE
        assert {d["title"] for d in ideas} <= {i.row.title for i in pool}
        assert all(set(d) == {"id", "title", "change_class"} for d in ideas)
        text = json.dumps(body)
        for leak in (*ipool.POOL_CONFIGS, SONNET, "eliminate", "assume_less", "lane"):
            assert leak not in text.replace("claude-opus-5", ""), leak
        assert not re.search(r"p[0-9a-f]{12}", text)  # the pool id is never shown
        assert body["max_tokens"] == im.MARKER_MAX_TOKENS
    rows = _records(out, ipool.SET_EXPERIMENT)
    assert len(rows) == 22 and max(len(r["ids"]) for r in rows) <= ipool.SET_SIZE
    first = rows[0]
    s = ipool.pool_set(REPO, first["name"], [next(i for i in pool if i.id == x)
                                            for x in first["ids"]])  # fmt: skip
    assert first["seed"] == f"{im.SHUFFLE_SEED}:{s.key}"
    assert first["shown"] == [first["ids"][k] for k in im.shown_order(s)]
    assert [d["title"] for d in _ideas(wire.bodies[0])] == [
        next(i for i in pool if i.id == x).row.title for x in first["shown"]
    ]


def test_each_set_and_each_result_is_recorded(dry: Path, tmp_path: Path) -> None:
    pool = _pool(13)
    by_id = {i.id: i for i in pool}
    _, _, out = _rank_library(tmp_path, pool, O39)
    rows = _records(out, ipool.SET_EXPERIMENT)
    shape = [(1, 1, 3, 5), (1, 2, 3, 4), (1, 3, 3, 4), (2, 1, 1, 6)]
    assert [
        (r["marker"], r["round"], r["set"], r["of"], len(r["ids"])) for r in rows
    ] == [(m, *x) for m in ("opus-5-5", "opus-5") for x in shape]
    for r in rows:
        titles = [by_id[x].row.title for x in r["order"]]
        assert titles == sorted(titles, reverse=True)  # the wire's order, read back
        assert r["advanced"] == (r["order"][:2] if r["of"] > 1 else [])
        assert r["validated"] is (r["marker"] == "opus-5-5")
        assert r["sent"] and r["error"] is None and r["cost_usd"] > 0
        assert r["repo"] == REPO and r["model"] in (OPUS, O5.model)
    results = _records(out, ipool.RESULT_EXPERIMENT)
    assert [(r["marker"], r["validated"]) for r in results] == [
        ("opus-5-5", True), ("opus-5", False)]  # fmt: skip
    for r in results:
        final = [x for x in rows if x["marker"] == r["marker"]][-1]
        assert r["top"] == final["order"][:3] and sum(r["counts"].values()) == 3
        assert r["requests"] == 4 and r["rounds"] == 2 and r["max_shown"] == 6
        assert sorted(m["id"] for m in r["members"]) == sorted(by_id)
        assert r["apart"] == []
        assert r["counts"] == ipool.counts(tuple(r["top"]), pool)
    # the report reads both kinds as the pool writes them
    parsed = report._parsed([out], [ipool.SET_EXPERIMENT, ipool.RESULT_EXPERIMENT])
    assert len(parsed[ipool.SET_EXPERIMENT]) == 8
    assert len(parsed[ipool.RESULT_EXPERIMENT]) == 2


def test_the_own_model_ideas_are_recorded_apart(
    dry: Path, tmp_path: Path, x1: Path
) -> None:
    pool = ipool.load_pools((x1,), (REPO,))[REPO]
    wire, _, out = _rank_library(tmp_path, pool, O39)
    first, second = _records(out, ipool.RESULT_EXPERIMENT)
    assert [a["label"] for a in first["apart"]] == ["far"]
    assert {a["arm"] for a in first["apart"]} == {"X1-1"}
    assert len(first["members"]) == 6 and len(second["members"]) == 7
    assert second["apart"] == []
    opus_55 = [b for b in wire.bodies if b["model"] == OPUS]
    assert all("x1-opus-lens" not in json.dumps(b) for b in opus_55)
    assert any("x1-opus-lens" in json.dumps(b) for b in wire.bodies)  # Opus 5's


def test_no_marker_spends_nothing_and_an_empty_pool_is_refused(
    dry: Path, tmp_path: Path
) -> None:
    wire, runs, out = _rank_library(tmp_path, _pool(7), NONE)
    assert (wire.bodies, runs, out.exists()) == ([], [], False)
    for decision in (O39, NONE):  # no zero-count result row, whatever the verdict
        wire = dg.Wire(_by_title)
        with pytest.raises(ValueError, match=f"{REPO}: no idea to pool"):
            _rank_library(tmp_path, (), decision, wire, name="empty")
        assert wire.bodies == [] and not (tmp_path / "empty.jsonl").exists()
    wire, runs, out = _rank_library(tmp_path, _pool(1), O39, name="one")  # no request
    assert (wire.bodies, runs) == ([], [])
    assert [len(r["top"]) for r in _records(out, ipool.RESULT_EXPERIMENT)] == [1, 1]


def test_a_request_past_its_bound_is_refused_before_the_wire_and_stops(
    dry: Path, tmp_path: Path
) -> None:
    wire = mg._Wire(_by_title, tokens=im.MARKER_PROMPT_BOUND + 1)
    _, runs, out = _rank_library(tmp_path, _pool(13), O39, wire)
    assert wire.bodies == [] and len(wire.counted) == 2  # one a marker, then stop
    assert runs[0].records == []
    rows = _records(out, ipool.SET_EXPERIMENT)
    assert [(r["marker"], r["set"]) for r in rows] == [("opus-5-5", 1), ("opus-5", 1)]
    assert all(r["order"] is None and r["error"].startswith("BudgetExceeded")
               for r in rows)  # fmt: skip
    assert [r["top"] for r in _records(out, ipool.RESULT_EXPERIMENT)] == [None, None]


def test_the_run_cap_is_each_requests_worst_case() -> None:
    pool = _pool(40)
    first, second = ipool.rankers(pool, O39)
    worst = 11 * im.request_worst(O55) + 11 * im.request_worst(O5)
    assert ipool.pool_cap((first, second)) == ceil_usd(worst) == 5.45
    assert ipool.requests(40) == 11 and ipool.requests(1) == 0
    assert ipool.library_usd() == 5.45  # 11 x (0.22 + 0.275), up to 0.05
    assert ipool.POOL_BOUND == 4 * (settings.GENERATOR_N + settings.IDEAS_PORTFOLIO_MAX)
    assert ipool.pool_cap(()) == 0.0


# ---------------------------------------------------------------------------
# The ideas-pool suite: plan, need, minutes, refusals before any spend
# ---------------------------------------------------------------------------

VALIDATION = TESTS_DIR.parents[2] / ".claude/handoff/step3/idea-lab/x1-validation"
VB_RESULTS = VALIDATION / "ideas-marker-41642619744.jsonl"


def _idna() -> tuple[OssRepo, ...]:
    return tuple(r for r in ipool.POOL_LIBRARIES if r.name == REPO)


def test_the_suite_ranks_the_four_libraries_outside_the_slice() -> None:
    from . import ideas_slice as sl

    assert ipool.POOL_REPOS == ("more_itertools", "mistune", "markdown", "idna")
    assert set(ipool.POOL_REPOS) | set(sl.SLICE_REPOS) == set(ip.E1_REPOS)
    assert not set(ipool.POOL_REPOS) & set(sl.SLICE_REPOS)
    plan = ipool.pool_plan(FOUR)
    assert [r.name for r in plan.repos] == list(ipool.POOL_REPOS)
    assert ipool.pool_need(plan) == pytest.approx(21.8) and ipool.pool_need(plan) <= 22
    # a clone and 22 requests at 30 s (Opus 5 measured 5.4 s, 5x margin) each
    assert plan.minutes() == 4 * (1 + 11) == 48 <= ipool.JOB_MINUTES == 60
    assert ipool.REQUEST_SECONDS == 30


def test_vbs_validated_set_sizes_are_the_ones_recorded() -> None:
    plan = im.plan_of(im.load_rows())
    sizes = [len(s.rows) for s in plan.sets]
    assert ipool.VB_SETS == (min(sizes), max(sizes), round(sum(sizes) / len(sizes), 1))
    assert ipool.VB_SETS == (3, 8, 4.6) and ipool.VB_SETS[0] <= 6 <= ipool.VB_SETS[1]


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({SUITE_CAP_ENV: "21.79"}, "below"),
        ({**FOUR, ipool.IDEAS_ENV: "tests/fixtures/ideas_slice/none.jsonl"}, "no X1"),
        ({**FOUR, ipool.MARKER_ENV: "/nowhere/marker.jsonl"}, "no marker"),
        ({**FOUR, ipool.MARKER_ENV: "pyproject.toml,uv.lock"}, "one results file"),
    ],
)
def test_a_bad_plan_is_refused(environ: Mapping[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        ipool.pool_plan(environ)


def test_the_recorder_reads_its_inputs_and_refuses_before_any_spend(
    x1: Path, tmp_path: Path
) -> None:
    four = ipool.PoolPlan(ipool.POOL_LIBRARIES, (x1,), VB_RESULTS)
    with pytest.raises(ValueError, match="more_itertools: no ideas-idea rows"):
        ipool.PoolRecorder(four, ResultsSink({}))  # a library the X1 files lack
    plan = ipool.PoolPlan(_idna(), (x1,), VB_RESULTS)
    recorder = ipool.PoolRecorder(plan, ResultsSink({}))
    assert recorder.decision == O39  # Vb's real verdict, through its scorer
    assert recorder.pools is not None and _titles(recorder.pools[REPO]) == POOLED
    assert set(recorder.pools) == {REPO}
    with pytest.raises(ValueError, match=ipool.IDEAS_ENV):
        ipool.PoolRecorder(ipool.PoolPlan(plan.repos, (), VB_RESULTS), ResultsSink({}))
    with pytest.raises(ValueError, match=ipool.MARKER_ENV):
        ipool.PoolRecorder(ipool.PoolPlan(plan.repos, (x1,), None), ResultsSink({}))
    lines = VB_RESULTS.read_text(encoding="utf-8").splitlines()
    verdict = next(x for x in lines if f'"{im.VERDICT_EXPERIMENT}"' in x)
    forged = tmp_path / "forged.jsonl"
    forged.write_text("\n".join([x for x in lines if x != verdict] + [verdict.replace(
        '"passed": ["opus-5-5"]', '"passed": ["opus-5-5", "opus-5"]')]) + "\n")  # fmt: skip
    with pytest.raises(ValueError, match="disagrees"):
        ipool.PoolRecorder(ipool.PoolPlan(plan.repos, (x1,), forged), ResultsSink({}))
    # priced by its requests' worst case: 41 or 42 ideas take the bound's 11
    # requests a marker, 43 take 12, past the need
    assert [ipool.requests(n) for n in (40, 42, 43)] == [11, 11, 12]
    ipool.PoolRecorder(plan, ResultsSink({}), pools={REPO: tuple(_pool(42))},
                       decision=O39)  # fmt: skip
    big = {REPO: tuple(_pool(ipool.POOL_BOUND + 3))}
    with pytest.raises(ValueError, match="past the 40 its need was priced on"):
        ipool.PoolRecorder(plan, ResultsSink({}), pools=big, decision=O39)
    ipool.PoolRecorder(plan, ResultsSink({}), pools=big, decision=NONE)  # no request


def test_run_library_clones_the_pinned_library_once_for_its_hot_code(
    dry: Path, tmp_path: Path, x1: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloned: list[Path] = []
    monkeypatch.setattr(ipool, "clone_pinned", lambda *a, **k: cloned.append(a[3]))
    monkeypatch.setattr(ipool, "hot_code", lambda repo, dest: _hot())
    wire, out = dg.Wire(_by_title), tmp_path / "pool.jsonl"
    plan = ipool.PoolPlan(_idna(), (x1,), VB_RESULTS)
    recorder = ipool.PoolRecorder(plan, ResultsSink({RESULTS_ENV: str(out)}))
    (idna,) = plan.repos
    ipool.run_library(idna, live=wire.run, root=tmp_path / "root", recorder=recorder,
                      base=settings.model_copy(update={"LLM_MAX_RETRIES": 0}))  # fmt: skip
    assert cloned == [tmp_path / "root" / f"hot-{REPO}"]
    assert len(_records(out, ipool.RESULT_EXPERIMENT)) == 2
    mistune = next(r for r in ipool.POOL_LIBRARIES if r.name == "mistune")
    with pytest.raises(ValueError, match="mistune: no idea to pool"):
        ipool.run_library(mistune, live=wire.run, root=tmp_path / "root",
                          recorder=recorder)  # fmt: skip
    assert len(cloned) == 1  # a library outside its pools sends and clones nothing


def test_the_live_module_reads_its_plan_first_and_runs_each_library() -> None:
    text = (LIVE_DIR / "test_ideas_pool_live.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live" in text
    assert '@pytest.fixture(scope="module")' in text
    assert "PoolRecorder(pool_plan(os.environ), ResultsSink(os.environ))" in text
    assert "run_library(" in text and "POOL_LIBRARIES" in text
    assert "engine" not in text.split('"""', 2)[2]  # no engine trial


def test_the_slice_and_the_pool_share_one_implementation() -> None:
    source = (LIVE_DIR / "ideas_slice.py").read_text(encoding="utf-8")
    assert "ipool.rank_library(" in source and "def tournament" not in source
    report_source = (LIVE_DIR / "ideas_report.py").read_text(encoding="utf-8")
    assert "def tournament" not in report_source
