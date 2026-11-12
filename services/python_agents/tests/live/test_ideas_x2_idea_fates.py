"""O61 addendum item 4: each round's idea fates in the X2 round rows (U-fate).

The hypotheses node keeps only a generator result's events, so the harness
taps the result: ``run_one`` wraps the loop's generator in
``ideas_x2.FateTap``, which hands every call to the real generator as made,
returns its result as is and keeps the result's ``idea_fates``. The
recorder gives each round the calls its ``generated`` events count (one per
returned call, before the round's ranking) and writes ``idea_fates`` (call
index in the round, idea id, lane, fate, quotas, duplicate, hypothesis id;
no title) and ``fate_counts`` (lane, fate, count). A loop with no generator
is not tapped, and its round rows carry neither.

Fakes: ``test_ideas_x2_guards``'s ``_Engine`` and state stand for the whole
engine run; ``_Generating`` gives its loop a scripted generator and calls
it as the hypotheses node would, once per ``generated`` event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import EngineEvent
from autonomous_ai_agents.optimization.idea_types import RESULT_FATE, IdeaFate, Lane
from autonomous_ai_agents.optimization.sources import GenerateResult
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import test_ideas_x2_fates as tf
from . import test_ideas_x2_guards as xg

x2_run = xg.x2_run
Json = dict[str, Any]
OBV, LEAP = Lane.obvious, Lane.leap


def _fate(lane: Lane, n: int, fate: str, **more: Any) -> IdeaFate:
    return IdeaFate(idea_id=f"{lane.value}-{n}", lane=lane, fate=fate,
                    title=f"title {n} {xg.SECRET}", **more)  # fmt: skip


# Round 1's call: two lanes, an idea at every stage (read, S4a, S3, S4b: a
# duplicate, two quotas missed, the relaxed fill's minimum; the bound, the
# result), in Unit A's vocabulary
FIRST = (
    _fate(OBV, 0, "read:too_long"), _fate(OBV, 1, "s4a:no_anchor"),
    _fate(OBV, 2, "s3:review_duplicate"), _fate(OBV, 3, RESULT_FATE, hypothesis_id="h-3"),
    _fate(LEAP, 4, "s4b:mechanism_duplicate", duplicate_of=f"kept twin {xg.SECRET}"),
    _fate(LEAP, 5, "s4b:quota_several", quotas=("lane", "anchor")),
    _fate(LEAP, 8, "s4b:minimum_reached"),
    _fate(LEAP, 6, "bound:novel"), _fate(LEAP, 7, RESULT_FATE, hypothesis_id="h-7"),
)  # fmt: skip
SECOND = (
    _fate(LEAP, 0, RESULT_FATE, hypothesis_id="h-9"),
    _fate(OBV, 1, "s4a:no_anchor"),
)


class _Scripted:
    """The real generator's stand-in: one scripted result per call; keeps
    the keywords each call was made with."""

    def __init__(self, *fates: tuple[IdeaFate, ...]) -> None:
        self.results = [GenerateResult(notes=(f"call {k}",), idea_fates=f)
                        for k, f in enumerate(fates)]  # fmt: skip
        self.seen: list[dict[str, object]] = []

    def generate(self, **kwargs: Any) -> GenerateResult:
        self.seen.append(kwargs)
        return self.results[len(self.seen) - 1]


@dataclass(frozen=True)
class _Ctx:
    judges: tuple[object, ...]
    generator: object | None


@dataclass(frozen=True)
class _Loop:
    user: object
    context: _Ctx


def _generated() -> EngineEvent:
    return xg._event(code="generated", kept=1)


class _Generating(xg._Engine):
    """The fake run with a generator: each round's ``generated`` events in
    ``per_round`` are calls made through the loop's (tapped) generator;
    ``calls`` makes that many calls instead (a misaligned run)."""

    def __init__(self, *fates: tuple[IdeaFate, ...], per_round: tuple[int, int] = (1, 1),
                 generator: bool = True, calls: int | None = None) -> None:  # fmt: skip
        super().__init__()
        self.inner = _Scripted(*fates)
        self.per_round, self.generator = per_round, generator
        self.n_calls = sum(per_round) if calls is None else calls
        self.got: list[GenerateResult] = []

    def start(self, *args: Any, **kwargs: Any) -> Any:
        loop = super().start(*args, **kwargs)
        return _Loop(loop.user, _Ctx(loop.context.judges,
                                     self.inner if self.generator else None))  # fmt: skip

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str, record: Any) -> Any:  # fmt: skip
        gen = loop.context.generator
        assert (gen is None) is (not self.generator)
        result = xg._state()
        st = cast(dict[str, Any], result.state)
        events = [e for e in st["events"] if e.data.get("code") != "generated"]
        at = next(k for k, e in enumerate(events) if e.data.get("ranked"))
        later = next(k for k, e in enumerate(events) if e.data.get("round") == 2
                     and e.data.get("ranked"))  # fmt: skip
        first, second = ([_generated()] * n for n in self.per_round)
        st["events"] = [*first, *events[:at + 1], *events[at + 1:later], *second,
                        *events[later:]]  # fmt: skip
        for k in range(self.n_calls if gen is not None else 0):
            self.got.append(gen.generate(n=3, call_index=k, run_id="run"))
        record(SimpleNamespace(guard="ok"), EngineRunResult("run", "done", cast(Any, st), None))  # fmt: skip


def _rounds(rows: list[Json]) -> list[Json]:
    return xg._rows(rows, x2.ROUND_EXPERIMENT)


def _row(call: int, f: IdeaFate) -> Json:
    dup = (
        None
        if f.duplicate_of is None
        else f.duplicate_of.replace(xg.SECRET, "[redacted]")
    )
    return {"call": call, "idea_id": f.idea_id, "lane": f.lane.value, "fate": f.fate,
            "quotas": list(f.quotas), "duplicate_of": dup,
            "hypothesis_id": f.hypothesis_id}  # fmt: skip


def test_a_whole_x2_run_records_each_round_s_idea_fates(x2_run: Any) -> None:
    """
    GIVEN an X2-0 run whose round 1 call read two lanes' ideas, one at
        every stage (read, S4a, S3, S4b with quotas and a duplicate, the
        bound, the result) and whose round 2 call read two more
    WHEN it is recorded
    THEN each round row lists its call's fates (call 0, no title, the
        duplicate redacted) and counts them by lane and fate
    """
    engine = _Generating(FIRST, SECOND)
    _, rows = x2_run(engine)

    one, two = _rounds(rows)
    assert one["idea_fates"] == [_row(0, f) for f in FIRST]
    assert one["fate_counts"] == {
        "obvious": {"read:too_long": 1, "s4a:no_anchor": 1, "s3:review_duplicate": 1,
                    "result": 1},
        "leap": {"s4b:mechanism_duplicate": 1, "s4b:quota_several": 1,
                 "s4b:minimum_reached": 1, "bound:novel": 1, "result": 1},
    }  # fmt: skip
    assert two["idea_fates"] == [_row(0, f) for f in SECOND]
    assert two["fate_counts"] == {
        "leap": {"result": 1},
        "obvious": {"s4a:no_anchor": 1},
    }
    assert "title" not in json.dumps(one["idea_fates"])
    assert xg.SECRET not in json.dumps(rows)
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert (run["fate_calls"], run["generated_events"]) == (2, 2)
    assert one["idea_fates_aligned"] is two["idea_fates_aligned"] is True


@pytest.mark.parametrize("calls", [3, 1])
def test_a_misaligned_run_says_so_on_every_round(x2_run: Any, calls: int) -> None:
    """
    GIVEN a run of two ``generated`` events whose tap saw a call more, or
        a call fewer
    WHEN it is recorded
    THEN the run row shows both counts and each round row is not aligned
    """
    _, rows = x2_run(_Generating(FIRST, SECOND, (), calls=calls))

    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert (run["fate_calls"], run["generated_events"]) == (calls, 2)
    assert [r["idea_fates_aligned"] for r in _rounds(rows)] == [False, False]


def test_the_tap_changes_no_call_and_no_result(x2_run: Any) -> None:
    """Every call reaches the generator with the keywords it was made with,
    and the node gets the generator's own result objects back."""
    engine = _Generating(FIRST, SECOND)
    x2_run(engine)

    assert engine.inner.seen == [
        {"n": 3, "call_index": k, "run_id": "run"} for k in (0, 1)
    ]
    assert all(a is b for a, b in zip(engine.got, engine.inner.results, strict=True))


def test_two_calls_in_a_round_are_numbered_within_it(x2_run: Any) -> None:
    _, rows = x2_run(_Generating(FIRST, SECOND, (), per_round=(2, 1)))

    one, two = _rounds(rows)
    assert one["idea_fates"] == [
        *(_row(0, f) for f in FIRST),
        *(_row(1, f) for f in SECOND),
    ]
    assert (two["idea_fates"], two["fate_counts"]) == ([], {})  # a call that read none


def test_a_round_with_no_call_records_none_read(x2_run: Any) -> None:
    _, rows = x2_run(_Generating(FIRST, per_round=(1, 0)))

    one, two = _rounds(rows)
    assert len(one["idea_fates"]) == len(FIRST)
    assert (two["idea_fates"], two["fate_counts"]) == ([], {})


@pytest.mark.parametrize(("make", "events"),
                         [(lambda: _Generating(FIRST, generator=False), 2), (xg._Engine, 1)])  # fmt: skip
def test_a_loop_without_a_generator_is_not_tapped(
    x2_run: Any, make: Any, events: int
) -> None:
    _, rows = x2_run(make())

    assert not any(k in r for r in rows
                   for k in ("idea_fates", "fate_counts", "idea_fates_aligned"))  # fmt: skip
    (run,) = xg._rows(rows, x2.RUN_EXPERIMENT)
    assert (run["fate_calls"], run["generated_events"]) == (None, events)


def test_the_tap_wraps_a_real_loop_s_generator_and_nothing_else() -> None:
    """``tap_fates`` on a dataclass loop: its context's generator becomes
    the tap around it, every other field the same object."""
    inner = _Scripted()
    loop = _Loop(user="u", context=_Ctx(judges=("j",), generator=inner))

    got, tap = x2.tap_fates(cast(Any, loop))
    tapped = cast(_Loop, got)

    assert tap is not None and tap.inner is inner and tap.calls == []
    assert tapped == replace(loop, context=replace(loop.context, generator=tap))
    assert tapped.user is loop.user and tapped.context.judges is loop.context.judges


NEW_FATE_KEYS = ("idea_fates", "fate_counts", "idea_fates_aligned", "fate_calls",
                 "generated_events")  # fmt: skip


def test_every_report_page_reads_round_rows_with_fates_alike(
    x2_run: Any, tmp_path: Path
) -> None:
    """The archived shape (no fates) and the new rows render the same pages,
    each input's own digest aside."""
    _, rows = x2_run(_Generating(FIRST, SECOND))
    assert all("idea_fates" in r and "fate_counts" in r for r in _rounds(rows))
    old = [{k: v for k, v in r.items() if k not in NEW_FATE_KEYS}
           for r in rows]  # fmt: skip
    paths = []
    for name, body in (("new", rows), ("old", old)):
        (tmp_path / name).mkdir()
        path = tmp_path / name / "x2.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in body), encoding="utf-8")
        paths.append(path)

    assert tf._pages(paths[0]) == tf._pages(paths[1])
