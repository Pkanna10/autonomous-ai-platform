"""Offline guards of the ideas-picks suite (V-picks, ``ideas_picks.py``).

Not ``live``: these spend nothing. They prove, before a dollar goes to
``test_ideas_picks_live.py``, that the blind reader's seven would-try ideas
resolve through the committed sample key against the slice's committed
inputs (and that an id which resolves to none, to two, or to a title the
reader was not shown is refused before any spend); that each becomes the
slice's own ``Hypothesis``; that each library runs one engine loop with
every pick in its round, the operation-count judge on and asserted; that
each loop's cap is its measured spend plus the engine's dearest
reservation, within the owner's 8 USD; the records; and O48's rule.

Fakes and what they stand for: the slice guards' ``_Engine`` (a fake
``start_arm_loop`` / ``run_engine`` with hand-built engine states) for the
engine loop, whose real wiring is built once, unsent, on a ``file://``
upstream (``og.LOCAL`` for GitHub over https); hand-written trial rows for
a live run's results in the rule's cases (one case reads the suite's own
rows). The key, the sample and the inputs are the real committed files.
What only a live run proves: the verdicts, gains, floors and op counts.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import count_margin, preflight_estimate
from autonomous_ai_agents.common.config import Role, role_chain, settings
from autonomous_ai_agents.orchestrator.factory import min_trial_budget

from . import discovery_oss as dx
from . import ideas_picks as pk
from . import ideas_slice as sl
from . import test_ideas_slice_guards as sg
from . import test_oss_guards as og
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun, StartLive, restore_host_key
from .corpus import JSON_TEXT_MAX, RESULTS_ENV
from .discovery import ceil_usd
from .discovery_io import ResultsSink

upstream = og.upstream

Json = dict[str, Any]
LIVE_DIR = TESTS_DIR / "live"
PLAN_ENV = {SUITE_CAP_ENV: "8"}
BY_LIBRARY = {
    "sqlparse": ["S20", "S04", "S12"],  # the rule's ideas lead their loop
    "more_itertools": ["S13", "S23"],
    "mistune": ["S07"],
    "tomli": ["S09"],
}
CAPS = {"sqlparse": 1.6, "more_itertools": 2.15, "mistune": 2.15, "tomli": 1.65}
SLICE_TRIAL_FIELDS = {  # ideas_slice.SliceRecorder.record's trial row
    "experiment", "repo", "arm", "label", "position", "lane", "model", "audit_id",
    "selection", "grader", "score", "grader_validated", "rank", "title",
    "mechanism", "cells", "path", "target", "rationale", "hypothesis_id",
    "verdict", "gain_pct", "floor_pct", "op_count", "guard",
}  # fmt: skip
SLICE_COMBINE_FIELDS = {  # ideas_slice.SliceRecorder.combine's row
    "experiment", "repo", "arm", "selection", "eligible", "picked", "kept",
    "combined", "holds", "applied", "fallback", "gain_pct", "floor_pct",
    "delivered", "summary", "cost_usd", "guard", "seeded_calls", "seeded_cost_usd",
}  # fmt: skip


def _plan(environ: Mapping[str, str] = PLAN_ENV, **files: Any) -> pk.PicksPlan:
    return pk.picks_plan(environ, **files)


# ---------------------------------------------------------------------------
# Resolution through the committed key, before any spend
# ---------------------------------------------------------------------------


def test_the_seven_ideas_resolve_on_the_committed_files() -> None:
    plan = _plan()
    assert [p.sample for p in plan.picks] == list(pk.PICK_IDS)
    assert [r.name for r in plan.repos] == list(BY_LIBRARY)
    assert {r.name: [p.sample for p in plan.of(r.name)] for r in plan.repos} == (
        BY_LIBRARY
    )
    for r in plan.repos:  # a budget stop never lands on S13 or S20 (O48)
        order = [p.sample in pk.RULE_IDS for p in plan.of(r.name)]
        assert order == sorted(order, reverse=True)
    key = json.loads(pk.KEY.read_text(encoding="utf-8"))
    for p in plan.picks:
        row, k = p.idea.row, key[p.sample]
        assert (row.repo, row.arm, row.label, row.position, row.lane, row.model) == (
            k["repo"], k["arm"], k["label"], k["position"], k["lane"], k["model"])  # fmt: skip
        built = sl.hypothesis(p.idea).model_dump(exclude={"id"})
        assert p.hypothesis.model_dump(exclude={"id"}) == built  # the slice's own
        assert row.returned and not row.proposal and p.idea.item.title == row.title
    assert [p.audit_id for p in plan.picks] == [
        "i07", "i09", "i35", "i08", "i08", "i13", "i48"]  # fmt: skip
    fable = {p.sample: (p.idea.row.lane, p.idea.row.model) for p in plan.picks
             if p.sample in pk.RULE_IDS}  # fmt: skip
    assert fable == {"S13": ("resolve_tradeoff", "claude-fable-5-1"),
                     "S20": ("resolve_tradeoff", "claude-fable-5")}  # fmt: skip


def test_a_subset_runs_only_its_libraries() -> None:
    plan = _plan({**PLAN_ENV, pk.IDS_ENV: "S20,S13"})
    assert [p.sample for p in plan.picks] == ["S13", "S20"]  # the key's order
    assert [r.name for r in plan.repos] == ["sqlparse", "more_itertools"]
    assert plan.of("tomli") == () and pk.picks_need(plan) == pytest.approx(3.75)


def _copies(
    tmp: Path, *, key: Json | None = None, sample: str | None = None,
    extra: tuple[str, ...] = (),
) -> dict[str, Any]:  # fmt: skip
    """The committed files copied under ``tmp``, one of them changed."""
    paths = {"key": tmp / "key.json", "sample": tmp / "sample.md"}
    found = json.loads(pk.KEY.read_text(encoding="utf-8")) if key is None else key
    paths["key"].write_text(json.dumps(found), encoding="utf-8")
    text = pk.SAMPLE.read_text(encoding="utf-8") if sample is None else sample
    paths["sample"].write_text(text, encoding="utf-8")
    inputs = []
    for n, source in enumerate(pk.INPUTS):
        lines = source.read_text(encoding="utf-8").splitlines()
        copy = tmp / f"in-{n}.jsonl"
        copy.write_text("\n".join([*lines, *(extra if n == 0 else ())]) + "\n",
                        encoding="utf-8")  # fmt: skip
        inputs.append(copy)
    return {**paths, "inputs": tuple(inputs)}


def _idea_line(repo: str, arm: str, label: str, position: int) -> str:
    for source in pk.INPUTS:
        for line in source.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["experiment"] == "ideas-idea" and (
                row["repo"],
                row["arm"],
                row["label"],
                row["position"],
            ) == (repo, arm, label, position):
                return line
    raise AssertionError("no such row")


def test_an_id_that_resolves_to_no_row_is_refused(tmp_path: Path) -> None:
    key = json.loads(pk.KEY.read_text(encoding="utf-8"))
    key["S09"]["position"] = 99
    with pytest.raises(ValueError, match="S09: tomli X1-2 obvious #99 resolves to "
                       "no ideas-idea row"):  # fmt: skip
        _plan(**_copies(tmp_path, key=key))


def test_an_id_the_key_lost_is_refused(tmp_path: Path) -> None:
    key = json.loads(pk.KEY.read_text(encoding="utf-8"))
    del key["S23"]
    with pytest.raises(ValueError, match="S23: not in the sample key"):
        _plan(**_copies(tmp_path, key=key))


def test_an_id_that_resolves_twice_is_refused(tmp_path: Path) -> None:
    twice = _idea_line("tomli", "X1-2", "obvious", 1)
    with pytest.raises(ValueError, match="S09: tomli X1-2 obvious #1 resolves to "
                       "2 ideas-idea rows"):  # fmt: skip
        _plan(**_copies(tmp_path, extra=(twice,)))


def test_a_title_the_reader_was_not_shown_is_refused(tmp_path: Path) -> None:
    text = pk.SAMPLE.read_text(encoding="utf-8")
    shown = "Replace skip_chars per-character loop"
    assert text.count(shown) == 1
    changed = text.replace(shown, "Replace the skip_chars loop")
    with pytest.raises(ValueError, match="S09: its title is not the one "
                       "owner-sample.md shows"):  # fmt: skip
        _plan(**_copies(tmp_path, sample=changed))
    gone = "\n".join(x for x in text.splitlines() if not x.startswith("| S09 |"))
    with pytest.raises(ValueError, match="S09: owner-sample.md has 0 rows"):
        _plan(**_copies(tmp_path, sample=gone))


@pytest.mark.parametrize(
    ("environ", "match"),
    [
        ({pk.IDS_ENV: "S04,S04"}, "distinct entries"),
        ({pk.IDS_ENV: "S99"}, "distinct entries"),
        ({pk.IDS_ENV: ""}, "distinct entries"),
        ({pk.IDS_ENV: "S08"}, "S08: idna is not one of"),  # in the key, not here
        ({SUITE_CAP_ENV: "7.54"}, "below the picks' need 7.55"),
    ],
)
def test_a_bad_plan_is_refused(environ: Mapping[str, str], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _plan({**PLAN_ENV, **environ})


# ---------------------------------------------------------------------------
# The caps: measured spend plus the engine's own dearest reservation
# ---------------------------------------------------------------------------


def test_the_measured_rates_are_the_slices_cost_tables() -> None:
    """Runs 41796813265 and 41803612871: per library the dearest loop's
    spend and the widest loop's input plus cache-write tokens."""
    assert pk.MEASURED == {
        "sqlparse": pk.Measured(0.5064, 3, 15_851 + 35_204),
        "pyparsing": pk.Measured(0.7212, 3, 20_760 + 57_752),
        "tomli": pk.Measured(0.4471, 3, 26_640 + 33_980),
        "sortedcontainers": pk.Measured(0.2591, 3, 20_709 + 18_284),
    }
    assert pk.WIDEST == pk.Measured(0.7212, 3, 78_512)  # pyparsing's, both


def test_each_loops_cap_admits_every_request_at_measured_rates() -> None:
    plan = _plan()
    caps = {r.name: plan.loop_cap(r.name) for r in plan.repos}
    assert caps == CAPS
    assert pk.picks_need(plan) == pytest.approx(7.55)
    assert pk.picks_need(plan) <= pk.PICKS_CAP_USD == 8.0  # the owner's cap
    for repo, cap in caps.items():
        m = pk.MEASURED.get(repo, pk.WIDEST)
        spent = m.spend_usd * max(1.0, len(plan.of(repo)) / m.trials)
        counted = m.prompt_tokens + count_margin(m.prompt_tokens)
        reserve = 0.0
        requests: tuple[tuple[Role, int], ...] = (
            ("engine", settings.UNDERSTAND_MAX_TOKENS),  # the understand
            ("editor", settings.EDITOR_MAX_TOKENS),  # every editor request
        )
        for role, out in requests:
            estimate = preflight_estimate(counted, out, role_chain(settings, role),
                                          settings.MODEL_PRICING)  # fmt: skip
            Budget(cap, spent).check(estimate)  # call()'s check: never refused
            reserve = max(reserve, estimate)
        assert cap - spent >= min_trial_budget() > 0  # the trial floor
        assert cap == ceil_usd(spent + reserve) and cap - 0.05 < spent + reserve
    assert pk.loop_need("tomli", 6) == ceil_usd(2 * 0.4471 + pk.reserve_usd(60_620))


def test_a_need_past_the_owners_cap_is_refused_never_lowered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(pk.MEASURED, "sqlparse", pk.Measured(1.1, 3, 51_055))
    with pytest.raises(ValueError, match="need 8.15 USD, past the owner's 8 USD"):
        _plan()


def test_the_minutes_fit_the_job(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _plan()
    assert plan.minutes() == 4 * sl.LOOP_MINUTES == 36 <= pk.JOB_MINUTES == 45
    monkeypatch.setattr(pk, "JOB_MINUTES", 35)
    with pytest.raises(ValueError, match="36 minutes, past the 35-minute job"):
        pk.check_fuse(plan)


# ---------------------------------------------------------------------------
# One loop per library, every pick in its round, then the combine
# ---------------------------------------------------------------------------


@pytest.fixture
def picks_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., tuple[list[LiveRun], sg._Engine, Path, pk.PicksPlan]]]:
    out = tmp_path / "picks.jsonl"

    def go(
        repo: str = "sqlparse", engine: sg._Engine | None = None, **base: object
    ) -> tuple[list[LiveRun], sg._Engine, Path, pk.PicksPlan]:
        engine = engine or sg._Engine()
        monkeypatch.setattr(pk, "start_arm_loop", engine.start)
        monkeypatch.setattr(pk, "run_engine", engine.run)
        runs: list[LiveRun] = []

        def live(cap: float) -> LiveRun:
            engine.calls.append(f"live {cap:g}")
            runs.append(run := LiveRun("x", cap))
            return run

        plan = _plan()
        recorder = pk.PicksRecorder(plan, ResultsSink({RESULTS_ENV: str(out)}),
                                    base=sg._base())  # fmt: skip
        library = next(r for r in plan.repos if r.name == repo)
        pk.run_library(library, live=cast(StartLive, live), root=tmp_path / "root",
                       isolation=sg.REQUIRED, recorder=recorder, policy=og.LOCAL,
                       base=sg._base(**base))  # fmt: skip
        return runs, engine, out, plan

    yield go


def _records(path: Path, experiment: str) -> list[Json]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["experiment"] == experiment]


def test_one_loop_per_library_with_every_pick_in_its_round(picks_run: Any) -> None:
    runs, engine, _, plan = picks_run()
    assert [r.cap_usd for r in runs] == [CAPS["sqlparse"]]
    assert engine.calls == ["live 1.6", "start sqlparse", "run sqlparse"]
    ((root, candidates, cap),) = engine.loops
    assert root.name == "sqlparse" and cap == 1.6
    assert [h.id for h in candidates] == [p.hypothesis.id for p in plan.of("sqlparse")]


def test_the_records_are_the_slices_rows_with_the_sample_ids(
    picks_run: Any,
) -> None:
    _, engine, out, plan = picks_run()
    trials = _records(out, pk.TRIAL_EXPERIMENT)
    assert [t["sample"] for t in trials] == BY_LIBRARY["sqlparse"]
    key = json.loads(pk.KEY.read_text(encoding="utf-8"))
    for t, p in zip(trials, plan.of("sqlparse"), strict=True):
        assert set(t) == SLICE_TRIAL_FIELDS | {"sample", "reader"}
        k = key[t["sample"]]
        assert (t["repo"], t["arm"], t["label"], t["position"], t["lane"],
                t["model"]) == (k["repo"], k["arm"], k["label"], k["position"],
                                k["lane"], k["model"])  # fmt: skip
        assert t["title"] == p.idea.row.title and t["hypothesis_id"] == p.hypothesis.id
        assert (t["reader"], t["selection"]) == (pk.READER_MARK, pk.SELECTION)
        assert (t["grader"], t["score"], t["grader_validated"]) == (None, None, None)
        assert t["op_count"]["present"] and t["op_count"]["base"] == 1000.0
        assert t["audit_id"] == p.audit_id and t["guard"] == "ok"
        assert "".join(t["rationale"]) == p.hypothesis.rationale
    assert [t["rank"] for t in trials] == [1, 2, 3]
    assert (trials[0]["verdict"], trials[1]["verdict"]) == ("keep", "reject")
    assert trials[0]["gain_pct"] == pytest.approx(12.0)
    assert trials[0]["floor_pct"] == pytest.approx(2.0)
    (combine,) = _records(out, pk.COMBINE_EXPERIMENT)
    assert set(combine) == SLICE_COMBINE_FIELDS | {"samples"}
    assert (combine["repo"], combine["arm"], combine["samples"]) == (
        "sqlparse", pk.READER_ARM, BY_LIBRARY["sqlparse"])  # fmt: skip
    assert (combine["eligible"], combine["picked"], combine["kept"]) == (3, 3, 1)
    assert combine["holds"] is True and combine["gain_pct"] == pytest.approx(11.0)
    assert (combine["seeded_calls"], combine["seeded_cost_usd"]) == (1, 0.25)
    text = out.read_text(encoding="utf-8")
    assert sg.SECRET not in text and "[redacted]" in text
    for row in (*trials, combine):
        for value in row.values():
            chunks = value if isinstance(value, list) else [value]
            assert all(len(x) <= JSON_TEXT_MAX for x in chunks if isinstance(x, str))


def test_the_engine_is_checked_before_any_spend(picks_run: Any) -> None:
    with pytest.raises(ValueError, match="OP_COUNT_JUDGE"):
        pk.PicksRecorder(_plan(), ResultsSink({}), base=sg._base(OP_COUNT_JUDGE=False))
    engine = sg._Engine()
    with pytest.raises(ValueError, match="OP_COUNT_JUDGE"):
        picks_run(engine=engine, OP_COUNT_JUDGE=False)
    assert engine.calls == []  # no live run, no clone


def test_a_library_with_no_pick_runs_no_loop(tmp_path: Path) -> None:
    plan = _plan({**PLAN_ENV, pk.IDS_ENV: "S13"})
    started: list[float] = []

    def live(cap: float) -> LiveRun:
        started.append(cap)
        return LiveRun("x", cap)

    recorder = pk.PicksRecorder(plan, ResultsSink({}), base=sg._base())
    with pytest.raises(ValueError, match="tomli: no pick, no loop"):
        pk.run_library(pk.PICKS_LIBRARIES[-1], live=cast(StartLive, live),
                       root=tmp_path, isolation=sg.REQUIRED, recorder=recorder,
                       base=sg._base())  # fmt: skip
    assert started == []


def test_a_loop_without_the_op_count_judge_is_refused_before_it_runs(
    picks_run: Any,
) -> None:
    engine = sg._Engine(judged=False)
    with pytest.raises(AssertionError, match="op_count"):
        picks_run(engine=engine)
    assert engine.ran == [] and engine.calls[-1] == "start sqlparse"


def test_a_verdict_without_the_op_count_column_fails_after_its_records(
    picks_run: Any, tmp_path: Path
) -> None:
    with pytest.raises(AssertionError, match="op-count column"):
        picks_run(engine=sg._Engine(op=False))
    trials = _records(tmp_path / "picks.jsonl", pk.TRIAL_EXPERIMENT)
    assert len(trials) == 3 and {t["op_count"]["present"] for t in trials} == {False}


def test_a_breach_is_recorded_then_raised(picks_run: Any, tmp_path: Path) -> None:
    class _Breach(sg._Engine):
        def run(self, loop: Any, run: LiveRun, isolation: Any, *, model: str,
                record: Callable[..., None]) -> Any:  # fmt: skip
            record(SimpleNamespace(guard=f"breach: {sg.SECRET}"), None)
            raise AssertionError("the user's repository changed")

    with pytest.raises(AssertionError, match="repository changed"):
        picks_run(engine=_Breach())
    out = tmp_path / "picks.jsonl"
    assert {t["verdict"] for t in _records(out, pk.TRIAL_EXPERIMENT)} == {dx.NO_RESULT}
    (combine,) = _records(out, pk.COMBINE_EXPERIMENT)
    assert combine["guard"].startswith("breach: ") and combine["combined"] is False
    assert sg.SECRET not in out.read_text(encoding="utf-8")


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


def test_the_real_loop_is_the_slices_oss_wiring_with_the_op_count_judge(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    monkeypatch.setattr(settings, "OP_COUNT_JUDGE", True)
    restore_host_key(monkeypatch, "dry-run-key")
    plan = _plan()
    hypotheses = [p.hypothesis for p in plan.of("sqlparse")]
    run = LiveRun("dry", plan.loop_cap("sqlparse"), wire=httpx2.MockTransport(_no_wire))
    loop = dx.start_arm_loop(og._local_repo(url, commit), run, root / "sqlparse",
                             sg.REQUIRED, hypotheses, policy=og.LOCAL)  # fmt: skip
    sl.check_judges(loop)
    assert [h.id for h in loop.context.candidates] == [h.id for h in hypotheses]
    assert loop.context.max_hypotheses_per_round == 3 and loop.cap_usd == 1.6
    assert run.capture.exchanges == []


def test_the_live_module_reads_its_plan_first_and_runs_each_library() -> None:
    text = (LIVE_DIR / "test_ideas_picks_live.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live" in text
    assert '@pytest.fixture(scope="module")' in text
    assert "PicksRecorder(picks_plan(os.environ), ResultsSink(os.environ))" in text
    assert "run_library(" in text and "pytest.skip(" in text
    assert [r.name for r in pk.PICKS_LIBRARIES] == list(pk.PICKS_REPOS)


# ---------------------------------------------------------------------------
# O48's rule and the reader-vs-judge table, offline
# ---------------------------------------------------------------------------


def _row(sample: str, verdict: str = "keep", gain: float | None = 12.0,
         floor: float | None = 2.0) -> Json:  # fmt: skip
    return {"experiment": pk.TRIAL_EXPERIMENT, "sample": sample, "reader": "would try",
            "verdict": verdict, "gain_pct": gain, "floor_pct": floor, "repo": "x"}  # fmt: skip


def _results(tmp: Path, rows: list[Json]) -> Path:
    path = tmp / "results.jsonl"
    other = {"experiment": pk.COMBINE_EXPERIMENT, "repo": "x"}
    path.write_text("".join(json.dumps(r) + "\n" for r in [other, *rows]),
                    encoding="utf-8")  # fmt: skip
    return path


@pytest.mark.parametrize(
    ("s13", "s20", "verdict"),
    [
        (("keep", 4.0, 2.0), ("reject", -1.0, 2.0), pk.ADD_LANE),  # exactly 2x
        (("keep", 3.9, 2.0), ("keep", 5.9, 3.0), pk.NO_FABLE),  # under 2x
        (("reject", 30.0, 2.0), ("keep", 6.0, 3.0), pk.ADD_LANE),  # S20 alone
        (("keep", 10.0, None), ("keep", None, 2.0), pk.NO_FABLE),  # no floor/gain
    ],
)
def test_o48s_rule(
    tmp_path: Path, s13: tuple[Any, ...], s20: tuple[Any, ...], verdict: str
) -> None:
    lines = pk.readout(_results(tmp_path, [_row("S04"), _row("S13", *s13),
                                           _row("S20", *s20)]))  # fmt: skip
    assert [x.sample for x in lines] == ["S04", "S13", "S20"]
    assert pk.fable_rule(lines) == verdict


@pytest.mark.parametrize(
    "unanswered", ["not_trialled", "no_verdict", "no_result", "not_handed"]
)
@pytest.mark.parametrize("sid", ["S13", "S20"])
def test_a_rule_idea_never_judged_is_refused_not_read_as_no_fable(
    tmp_path: Path, sid: str, unanswered: str
) -> None:
    """A budget stop, a run that ended before the verdict, a breach or an idea
    never handed over leaves O48's question open, whatever the other idea."""
    for other in (("keep", 12.0, 2.0), ("reject", -1.0, 2.0)):
        rows = {"S13": _row("S13", *other), "S20": _row("S20", *other)}
        rows[sid] = _row(sid, unanswered, None, None)
        lines = pk.readout(_results(tmp_path, list(rows.values())))
        with pytest.raises(ValueError, match=f"{sid}: {unanswered}; O48's rule "
                                             "needs a judged trial"):  # fmt: skip
            pk.fable_rule(lines)


def test_the_readout_refuses_a_rule_idea_missing_or_a_sample_twice(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="S20: no ideas-picks-trial row"):
        pk.fable_rule(pk.readout(_results(tmp_path, [_row("S13")])))
    with pytest.raises(ValueError, match="S13: two ideas-picks-trial rows"):
        pk.readout(_results(tmp_path, [_row("S13"), _row("S13")]))


def test_the_cli_prints_the_table_and_the_rule(tmp_path: Path) -> None:
    path = _results(tmp_path, [_row("S13", "keep", 9.0, 3.0), _row("S20", "reject")])
    echoed: list[str] = []
    assert pk.main([str(path)], echo=echoed.append) == 0
    text = "\n".join(echoed)
    assert "| sample | reader | verdict | gain % | floor % |" in text
    assert "| S13 | would try | keep | 9.00 | 3.00 |" in text
    assert text.endswith(f"O48's rule: {pk.ADD_LANE}")
    echoed.clear()
    assert pk.main([str(tmp_path / "none.jsonl")], echo=echoed.append) == 2
    assert echoed[0].startswith("error: ")
    echoed.clear()
    path = _results(tmp_path, [_row("S13", "reject", -1.0, 2.0),
                               _row("S20", "not_trialled", None, None)])  # fmt: skip
    assert pk.main([str(path)], echo=echoed.append) == 2  # the table, then why
    assert "| S20 | would try | not_trialled | - | - |" in echoed
    assert echoed[-1] == "error: S20: not_trialled; O48's rule needs a judged trial"
    assert not any(x.startswith("O48's rule:") for x in echoed)


def test_the_rule_reads_the_suites_own_rows(picks_run: Any) -> None:
    """The fake engine keeps each loop's first pick (12 % on a 2 % floor):
    S13 and S20 lead their loops."""
    _, _, out, _ = picks_run("more_itertools")
    with pytest.raises(ValueError, match="S20: no ideas-picks-trial row"):
        pk.fable_rule(pk.readout(out))
    picks_run("sqlparse")
    lines = pk.readout(out)
    assert [(x.sample, x.verdict) for x in lines] == [
        ("S13", "keep"), ("S23", "reject"), ("S20", "keep"), ("S04", "reject"),
        ("S12", "reject")]  # fmt: skip
    assert pk.fable_rule(lines) == pk.ADD_LANE
