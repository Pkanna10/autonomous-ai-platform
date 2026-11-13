"""U8a: the look wrappers, the launch spans and the look rows, offline.

Swap points: the inner runner, calibrator and combiner are recording fakes
(the real ones are the factory's, checked once on a wired loop built from a
throwaway upstream, nothing sent); ``procrun.run_once`` is a fake under
``LookLaunches``; ``/proc`` is a synthetic tree in ``tmp_path``; the launch
spans are hand-made ``LaunchTime`` rows in ``measure_abab``'s order. The
engine's own gap (``trial_runner._gaps``) checks the calibration blocks'.
What only a live runner proves: the real phases' launch order, the real
``/proc`` and that the snapshots stay out of the timed runs' way.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import (
    Baseline,
    Combination,
    Measurement,
    NoiseCalibration,
    RunStats,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution import procrun
from autonomous_ai_agents.execution.combine import BASE, TIP
from autonomous_ai_agents.execution.protocols import CombineMeasured, KeptChange
from autonomous_ai_agents.execution.trial_runner import CALIBRATE_PHASES, _gaps
from autonomous_ai_agents.orchestrator.combine_node import ConflictProbe
from autonomous_ai_agents.orchestrator.nodes import NodeContext, ReplayRunner
from autonomous_ai_agents.persistence.repository import InMemoryRepository

from . import ideas_x2 as x2
from . import test_ideas_slice_guards as sg
from . import test_ideas_x2_guards as xg
from . import test_oss_guards as og
from . import x2_looks as xl
from .conftest import LiveRun, restore_host_key
from .x2_proc import ProcReader

upstream = og.upstream
W, R = 1, 5  # the default workload's warm-ups and timed runs
CAL_A, CAL_B = CALIBRATE_PHASES
HYP = xg._hyp("an idea")
WORKLOAD = Workload(project_id="p", name="bench", command=("python", "b.py"))


def _proc(tmp_path: Path) -> ProcReader:
    return ProcReader(tmp_path / "no-proc", pid=1)


def _abba(a: str, b: str, wa: Sequence[float], wb: Sequence[float], *,
          t0: float = 0.0, warm: tuple[float, float] = (9.0, 8.0)) -> list[xl.LaunchTime]:  # fmt: skip
    """``measure_abab``'s launch order: index i even A then B, odd B then A;
    the first ``W`` per side warm-ups (``warm``), then ``wa``/``wb`` timed."""
    sides = {a: [warm[0], *wa], b: [warm[1], *wb]}
    used = {a: 0, b: 0}
    out: list[xl.LaunchTime] = []
    for i in range(W + len(wa)):
        for p in (a, b) if i % 2 == 0 else (b, a):
            wall = sides[p][used[p]]
            used[p] += 1
            out.append(
                xl.LaunchTime(p, t0 + len(out), t0 + len(out) + 0.5, wall, wall / 2)
            )
    return out


def _rows(trial_id: str | None, wall: Sequence[float], *,
          later: bool = True) -> tuple[Measurement, ...]:  # fmt: skip
    """Wall and CPU rows, then (``later``) another wall row, as a counted
    or shadow run's would follow the A/B rows: the first one counts."""
    extra = [("wall_time_s", [99.0] * len(wall))] if later else []
    return tuple(Measurement(workload_id=WORKLOAD.id, trial_id=trial_id, metric=m,
                             stats=RunStats.from_samples(v, unit="s"), samples=tuple(v))
                 for m, v in (("wall_time_s", wall), ("cpu_time_s", [w / 2 for w in wall]),
                              *extra))  # fmt: skip


class _Runner:
    def __init__(self, trial: Trial, launches: xl.LookLaunches | None = None,
                 spans: Sequence[xl.LaunchTime] = (), error: Exception | None = None) -> None:  # fmt: skip
        self.trial, self.launches, self.spans, self.error = (
            trial,
            launches,
            spans,
            error,
        )
        self.calls: list[tuple[object, ...]] = []

    def _go(self, *args: object) -> Trial:
        self.calls.append(args)
        if self.launches is not None:
            self.launches.timed.extend(self.spans)
        if self.error is not None:
            raise self.error
        return self.trial

    def run(
        self, hypothesis: Any, workloads: Any, baseline: Any, **kwargs: Any
    ) -> Trial:
        return self._go(hypothesis, workloads, baseline, kwargs)


class _Replayer(_Runner):
    def replay(self, hypothesis: Any, parents: Any, workloads: Any, baseline: Any,
               **kwargs: Any) -> Trial:  # fmt: skip
        return self._go("replay", hypothesis, parents, workloads, baseline, kwargs)


class _Calibrator:
    def __init__(self, found: NoiseCalibration, launches: xl.LookLaunches | None = None,
                 spans: Sequence[xl.LaunchTime] = ()) -> None:  # fmt: skip
        self.found, self.launches, self.spans = found, launches, spans
        self.calls: list[tuple[object, ...]] = []

    def calibrate(self, workloads: Any, **kwargs: Any) -> NoiseCalibration:
        self.calls.append((workloads, kwargs))
        if self.launches is not None:
            self.launches.timed.extend(self.spans)
        return self.found


class _Combiner:
    def __init__(self, found: CombineMeasured, launches: xl.LookLaunches | None = None,
                 spans: Sequence[xl.LaunchTime] = ()) -> None:  # fmt: skip
        self.found, self.launches, self.spans = found, launches, spans
        self.calls: list[tuple[object, ...]] = []

    def combine(self, *args: Any, **kwargs: Any) -> CombineMeasured:
        self.calls.append((*args, kwargs))
        if self.launches is not None:
            self.launches.timed.extend(self.spans)
        return self.found


class _Noted(_Combiner):
    last_notes = ("a note", 3)


class _Probe(_Combiner):
    site_stacks = "record"

    def dry_merge(self, *args: Any) -> object:
        self.calls.append(("dry", *args))
        return "dry"


def _measured(wa: Sequence[float] = (), wb: Sequence[float] = ()) -> CombineMeasured:
    return CombineMeasured("t" * 40, ("t1",), (), _rows(None, wa) if wa else (),
                           _rows(None, wb) if wb else ())  # fmt: skip


def _change(trial_id: str) -> KeptChange:
    return KeptChange(trial_id, HYP.id, "v-" + trial_id, trial_id[0] * 40, 0.1, 0.1)


def _ctx(**seams: Any) -> NodeContext:
    return NodeContext(**{"runner": _Runner(Trial(hypothesis_id=HYP.id, round=1)),
                          "baseline_runner": object(), "judges": (),
                          "repository": InMemoryRepository(), **seams})  # fmt: skip


# ---------------------------------------------------------------------------
# LookLaunches and the wrappers
# ---------------------------------------------------------------------------


def test_look_launches_keeps_each_launchs_span_and_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(os.path.realpath(tmp_path)) / "wt"
    (root / "run" / "trial-h").mkdir(parents=True)
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    sample = procrun.RunSample(wall_ns=1_500_000_000, utime=0.75, stime=0.25,
                               maxrss_bytes=1, exit=0, fs_isolated=True,
                               net_isolated=True, stdout_sha256="0" * 64,
                               stdout_head=b"", stdout_bytes=0, stderr_tail=b"")  # fmt: skip
    outcomes: list[object] = [sample, procrun.RunFailure("boom")]

    def fake(*args: object, **kwargs: object) -> procrun.RunSample:
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return cast(procrun.RunSample, out)

    monkeypatch.setattr(procrun, "run_once", fake)
    ticks = iter([10.0, 12.0, 20.0])
    log = xl.LookLaunches(clock=lambda: next(ticks))
    policy = cast(Any, SimpleNamespace(network="required", fs="required"))
    got = log(["python", "-c", "x"], root / "run" / "trial-h", {}, policy, 5.0, cast(Any, None))  # fmt: skip
    assert got is sample and len(log.launches) == 1  # the LaunchLog's own record too
    assert log.timed == [xl.LaunchTime("trial-h", 10.0, 12.0, 1.5, 1.0)]
    with pytest.raises(procrun.RunFailure):
        log(["python"], root / "run" / "trial-h", {}, policy, 5.0, cast(Any, None))
    assert len(log.timed) == 1 and len(log.failures) == 1


def test_each_wrapper_hands_the_call_on_and_returns_its_result(tmp_path: Path) -> None:
    log = xl.LookLog(_proc(tmp_path))
    trial = Trial(hypothesis_id=HYP.id, round=1)
    inner = _Replayer(trial)
    runner = xl.LookReplayRunner(inner, log)
    base, flows = Baseline(), [WORKLOAD]
    keys = {"round": 2, "branch": "b", "budget_usd": 1.0, "brief": "brief"}
    assert runner.run(HYP, flows, base, **keys) is trial
    assert runner.replay(HYP, (trial,), flows, base, **keys) is trial
    assert inner.calls[0] == (HYP, flows, base, keys)
    assert inner.calls[1] == ("replay", HYP, (trial,), flows, base, keys)
    cal = NoiseCalibration(blocks=3, gaps={}, floor=0.02)
    calibrator = _Calibrator(cal)
    assert xl.LookCalibrator(calibrator, log).calibrate(flows, run_id="r", commit="c", blocks=3) is cal  # fmt: skip
    assert calibrator.calls == [(flows, {"run_id": "r", "commit": "c", "blocks": 3})]
    found, kept = _measured(), [_change("t1"), _change("t2")]
    probe = _Probe(found)
    looked = xl.LookProbe(probe, log)
    assert (
        looked.combine("r", cast(Any, "p"), "b", kept, flows, baseline_count=3) is found
    )
    assert cast(object, looked.dry_merge(cast(Any, "p"), "b", kept)) == "dry"
    assert looked.site_stacks == "record" and looked.last_notes == ()
    assert probe.calls == [("r", "p", "b", kept, flows, {"baseline_count": 3}),
                           ("dry", "p", "b", kept)]  # fmt: skip
    assert xl.LookCombiner(_Noted(found), log).last_notes == ("a note", "3")
    assert [(o.kind, o.hypothesis_id, o.trial_id, o.offered) for o in log.looks] == [
        ("trial", HYP.id, trial.id, ()), ("replay", HYP.id, trial.id, ()),
        ("calibration", None, None, ()), ("combine", None, None, ("t1", "t2")),
    ]  # fmt: skip
    assert log.looks[2].calibration is cal and log.looks[3].measured is found
    assert all(o.after is not None and o.error is None for o in log.looks)


def test_a_raising_call_is_a_look_with_its_error_and_raises_again(
    tmp_path: Path,
) -> None:
    log = xl.LookLog(_proc(tmp_path))
    error = KeyError("x")
    runner = xl.LookRunner(_Runner(Trial(hypothesis_id="h", round=1), error=error), log)
    with pytest.raises(KeyError) as caught:
        runner.run(HYP, [], Baseline())
    assert caught.value is error  # the inner's own exception, not a copy
    (one,) = log.looks
    assert (one.kind, one.error, one.trial_id) == ("trial", "KeyError", None)
    assert one.after is not None and log.proc_seconds() >= 0


def test_tap_context_keeps_the_protocols_the_nodes_test(tmp_path: Path) -> None:
    log = xl.LookLog(_proc(tmp_path))
    plain = xl.tap_context(_ctx(), log)
    assert type(plain.runner) is xl.LookRunner and not isinstance(
        plain.runner, ReplayRunner
    )
    assert plain.combiner is None and plain.calibrator is None
    cal = _Calibrator(NoiseCalibration(blocks=1, floor=0.02))
    full = xl.tap_context(_ctx(runner=_Replayer(Trial(hypothesis_id="h", round=1)),
                               combiner=_Probe(_measured()), calibrator=cal,
                               calibration_blocks=1, near_miss_compounds=True), log)  # fmt: skip
    assert isinstance(full.runner, xl.LookReplayRunner) and isinstance(full.runner, ReplayRunner)  # fmt: skip
    assert isinstance(full.combiner, xl.LookProbe) and isinstance(full.combiner, ConflictProbe)  # fmt: skip
    assert (
        isinstance(full.calibrator, xl.LookCalibrator) and full.calibrator.inner is cal
    )
    other = xl.tap_context(_ctx(combiner=_Combiner(_measured())), log)
    assert type(other.combiner) is xl.LookCombiner
    assert not isinstance(other.combiner, ConflictProbe)


def test_tap_looks_leaves_a_fake_loop_untapped(tmp_path: Path) -> None:
    loop = cast(Any, SimpleNamespace(context=SimpleNamespace(judges=())))
    assert xl.tap_looks(loop, _proc(tmp_path), {}) == (loop, None)


def test_tap_looks_wraps_the_wired_loops_own_seams(
    upstream: og.Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The factory's runner, calibrator and combiner behind the wrappers,
    still a ``ReplayRunner`` and a ``ConflictProbe``; the launches a
    ``LookLaunches``; the machine read from the reader's root; nothing sent."""
    for key, value in x2.arm_env(x2.X2_0).items():
        monkeypatch.setenv(key, value)
    built = Settings(_env_file=None)
    for key in x2.X2_0.update:
        monkeypatch.setattr(settings, key, getattr(built, key))
    url, commit = upstream()
    root = Path(os.path.realpath(tmp_path))
    (root / "x2").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", x2.arm_cap(x2.X2_0), wire=httpx2.MockTransport(xg._no_wire))
    loop = x2.start_x2_loop(og._local_repo(url, commit), run, root / "x2", xg.REQUIRED,
                            policy=og.LOCAL)  # fmt: skip
    proc = root / "proc"
    proc.mkdir()
    (proc / "cpuinfo").write_text("processor\t: 0\nmodel name\t: a cpu\n")
    tapped, log = xl.tap_looks(loop, ProcReader(proc, pid=1), {"RUNNER_NAME": "r1"})
    assert log is not None and isinstance(loop.launches, xl.LookLaunches)
    assert log.launches is loop.launches is tapped.launches
    assert (log.warmups, log.runs) == (loop.workload.warmup_runs,
                                       max(settings.MIN_RUNS, loop.workload.runs))  # fmt: skip
    assert log.machine is not None and log.machine["cpu_model"] == "a cpu"
    assert log.machine["RUNNER_NAME"] == "r1" and log.machine["ImageVersion"] is None
    ctx, old = tapped.context, loop.context
    assert (
        isinstance(ctx.runner, xl.LookReplayRunner) and ctx.runner.inner is old.runner
    )
    assert isinstance(ctx.combiner, xl.LookProbe) and ctx.combiner.inner is old.combiner
    assert ctx.combiner.site_stacks == cast(Any, old.combiner).site_stacks
    assert old.calibrator is not None and isinstance(ctx.calibrator, xl.LookCalibrator)
    assert (
        ctx.calibrator.inner is old.calibrator
        and ctx.baseline_runner is old.baseline_runner
    )
    assert ctx.generator is old.generator and ctx.judges == old.judges
    assert run.capture.exchanges == [] and run.records == []


# ---------------------------------------------------------------------------
# The rows
# ---------------------------------------------------------------------------


def test_windows_find_each_abba_in_order() -> None:
    one = _abba("a", "b", [1, 2, 3, 4, 5], [6, 7, 8, 9, 10])
    noise = [xl.LaunchTime("a", 0, 0, 0, 0), xl.LaunchTime("x", 0, 0, 0, 0)]
    found = xl.windows([*noise, *one, *one[:4], *one], "a", "b", W, R)
    assert len(found) == 2 and found[0].launches == tuple(one)
    assert found[1].launches != tuple(one)  # the cut-off start reads as one too
    every = xl.windows([*one[:4], *one], "a", "b", W, R, every=True)
    assert [w.launches == tuple(one) for w in every] == [False, True]
    w = found[0]
    assert w.timed("a") == [1, 2, 3, 4, 5] and w.timed("b", cpu=True) == [
        3,
        3.5,
        4,
        4.5,
        5,
    ]
    assert w.warm() == {"A": [9.0], "B": [8.0]}
    assert w.span() == {"start": one[0].start, "end": one[-1].end,
                        "warmup_wall_s": {"A": [9.0], "B": [8.0]}}  # fmt: skip
    assert xl.windows(one, "a", "b", 0, 0) == []  # no runs: no window
    assert xl.windows(one, "b", "a", W, R) == []  # B never leads


def _trial(wa: Sequence[float], wb: Sequence[float], hid: str = HYP.id) -> Trial:
    t = Trial(hypothesis_id=hid, round=1)
    return t.model_copy(update={"base_measurements": _rows(None, wa) if wa else (),
                                "measurements": _rows(t.id, wb) if wb else ()})  # fmt: skip


def test_each_look_row_reads_its_measured_window(tmp_path: Path) -> None:
    launches = xl.LookLaunches()
    log = xl.LookLog(_proc(tmp_path), launches, warmups=W, runs=R)
    wa, wb = [1.0, 1.1, 1.2, 1.3, 1.4], [0.9, 0.8, 0.85, 0.95, 0.9]
    good = _trial(wa, wb)
    phase = f"trial-{HYP.id}"
    failed = _abba("twin-" + phase, phase, [5.0] * 5, [6.0] * 5)[:4]  # cut off
    measured = _abba("twin-" + phase, phase, wa, wb, t0=100)
    xl.LookRunner(_Runner(good, launches, [*failed, *measured]), log).run(
        HYP, [], Baseline()
    )
    other = _trial(wa, wb, hid="other")
    xl.LookRunner(_Runner(other, launches, _abba("twin-x", "x", wa, [7.0] * 5)), log).run(
        xg._hyp("other"), [], Baseline())  # fmt: skip
    bare = Trial(hypothesis_id="bare", round=1)  # failed: no rows
    xl.LookRunner(_Runner(bare), log).run(xg._hyp("bare"), [], Baseline())
    alone = _trial([], wb, hid="alone")  # unpaired: no twin rows, nothing to align
    xl.LookRunner(_Runner(alone, launches, measured), log).run(xg._hyp("alone"), [], Baseline())  # fmt: skip
    combine = _abba(BASE, TIP, [2.0] * 5, [1.5] * 5, t0=200)
    combiner = xl.LookCombiner(_Combiner(_measured([2.0] * 5, [1.5] * 5), launches, combine), log)  # fmt: skip
    combiner.combine("r", cast(Any, "p"), "b", [_change(good.id)], [])
    st = cast(Any, {"trials": [good, other, bare, alone], "combination": None,
                    "events": [xg._event(code="x")]})  # fmt: skip
    rows = xl.look_rows(log, st)
    # no combine-phase event and no failed combiner call: never entered
    assert [r["kind"] for r in rows] == ["trial"] * 4 + ["confirm"]
    assert {r["proc_span"] for r in rows} == {"call"}
    assert rows[0]["proc_includes"] == xl.TRIAL_CALL
    assert rows[4]["proc_includes"] == xl.COMBINE_CALL
    first = rows[0]
    assert first["ab_aligned"] is True and first["trial_id"] == good.id
    assert first["ab"] == {"start": 100.0, "end": measured[-1].end,
                           "warmup_wall_s": {"A": [9.0], "B": [8.0]}}  # fmt: skip
    assert first["samples"] == {"A": {"wall_time_s": wa, "cpu_time_s": [w / 2 for w in wa]},
                                "B": {"wall_time_s": wb, "cpu_time_s": [w / 2 for w in wb]}}  # fmt: skip
    assert (rows[1]["ab"], rows[1]["ab_aligned"]) == (None, False)  # walls differ
    assert (rows[2]["samples"], rows[2]["ab"], rows[2]["ab_aligned"]) == (
        None,
        None,
        None,
    )
    assert rows[3]["samples"] is not None
    assert (rows[3]["ab"], rows[3]["ab_aligned"]) == (None, None)  # unpaired
    assert rows[4]["ab_aligned"] is True and rows[4]["offered"] == [HYP.id]
    assert rows[4]["ab"]["start"] == 200.0  # type: ignore[index]
    untimed = xl.LookLog(_proc(tmp_path), None)
    xl.LookRunner(_Runner(good), untimed).run(HYP, [], Baseline())
    (row,) = xl.look_rows(untimed, st)
    assert (row["ab"], row["ab_aligned"]) == (None, None) and row["samples"] is not None
    assert xl.look_rows(untimed, None)[0]["samples"] is None  # no state: no rows


def test_calibration_blocks_match_the_engines_own_gaps(tmp_path: Path) -> None:
    blocks = [([1.0, 1.0, 1.1, 1.0, 1.0], [1.05, 1.0, 1.0, 1.0, 1.1]),
              ([2.0, 2.0, 2.0, 2.0, 2.0], [2.2, 2.2, 2.2, 2.2, 2.2]),
              ([0.0] * 5, [0.0] * 5)]  # fmt: skip
    engine = [_gaps(_rows(None, a, later=False), _rows(None, b, later=False))[0][1]
              for a, b in blocks]  # fmt: skip
    largest = max(engine)
    cal = NoiseCalibration(blocks=3, gaps={f"{WORKLOAD.id}:wall_time_s": largest},
                           floor=max(0.02, 2 * largest))  # fmt: skip
    spans = [
        s
        for n, (a, b) in enumerate(blocks)
        for s in _abba(CAL_A, CAL_B, a, b, t0=50 * n)
    ]
    launches = xl.LookLaunches()
    log = xl.LookLog(_proc(tmp_path), launches)
    xl.LookCalibrator(_Calibrator(cal, launches, spans), log).calibrate([])
    (row,) = xl.look_rows(log, None)
    assert row["kind"] == "calibration" and row["ab_aligned"] is True
    assert (row["proc_span"], row["proc_includes"]) == ("call", ["all blocks"])
    got = cast(list[dict[str, Any]], row["blocks"])
    assert [b["gap"] for b in got] == engine and [b["block"] for b in got] == [1, 2, 3]
    first = got[0]
    assert first["sd"] == {"A": RunStats.from_samples(blocks[0][0], "s").stdev,
                           "B": RunStats.from_samples(blocks[0][1], "s").stdev}  # fmt: skip
    assert first["samples"]["A"]["wall_time_s"] == blocks[0][0]
    assert first["warmup_wall_s"] == {"A": [9.0], "B": [8.0]} and first["start"] == 0.0
    short = xl.LookLog(_proc(tmp_path), launches)
    xl.LookCalibrator(_Calibrator(cal, launches, spans[:12]), short).calibrate([])
    assert xl.look_rows(short, None)[0]["ab_aligned"] is False  # one block of three
    other = NoiseCalibration(blocks=3, gaps={"w": 0.5}, floor=1.0)
    wrong = xl.LookLog(_proc(tmp_path), launches)
    xl.LookCalibrator(_Calibrator(other, launches, spans), wrong).calibrate([])
    assert xl.look_rows(wrong, None)[0]["ab_aligned"] is False  # not its largest gap
    untimed = xl.LookLog(_proc(tmp_path))
    xl.LookCalibrator(_Calibrator(cal), untimed).calibrate([])
    assert xl.look_rows(untimed, None)[0]["blocks"] is None


def _comb(fallback: str | None = None) -> Combination:
    return Combination(base_commit="b" * 40, tip_commit="c" * 40, applied_trial_ids=(),
                       judge_results=sg._judges(0.1), holds=False, summary="s",
                       fallback_trial_id=fallback)  # fmt: skip


def test_combine_stages_end_with_the_run_combine_then_the_review_set() -> None:
    assert xl.combine_stages(0, None, None, completed=True, raised=False) == []
    assert xl.combine_stages(2, None, None, completed=True, raised=False) == [
        "confirm",
        "confirm",
    ]
    assert xl.combine_stages(3, _comb(), None, completed=True, raised=False) == [
        "confirm", "confirm", "greedy"]  # fmt: skip
    assert xl.combine_stages(4, _comb("t"), _comb(), completed=True, raised=False) == [
        "confirm", "greedy", "fallback", "review_greedy"]  # fmt: skip
    assert xl.combine_stages(3, _comb("t"), _comb("u"), completed=True, raised=False) == ["unknown"] * 3  # too few  # fmt: skip
    # F2: the combine node raised inside a combiner call: its calls cannot be
    # told apart from the confirmations before them
    assert xl.combine_stages(3, None, None, completed=False, raised=True) == ["unknown"] * 3  # fmt: skip
    # never entered (the run failed before it): every call was a confirmation
    assert xl.combine_stages(2, None, None, completed=False, raised=False) == [
        "confirm", "confirm"]  # fmt: skip


def test_the_combine_node_completed_by_its_combinations_or_its_events() -> None:
    from autonomous_ai_agents.common.models import RunPhase

    done = xg._event(code="x").model_copy(update={"phase": RunPhase.combine})
    assert xl.combine_completed(None) is False
    assert xl.combine_completed(cast(Any, {"events": []})) is False
    assert xl.combine_completed(cast(Any, {"events": [xg._event(code="x")]})) is False
    assert xl.combine_completed(cast(Any, {"events": [done]})) is True
    assert (
        xl.combine_completed(cast(Any, {"events": [], "combination": _comb()})) is True
    )
    assert xl.combine_completed(cast(Any, {"review_combination": _comb()})) is True


def test_a_look_row_carries_ids_span_and_its_proc_delta(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    (root / "40").mkdir(parents=True)
    stat = root / "40" / "stat"
    loads = iter(["1 1 1 1/9 2\n", "2 2 2 3/9 2\n"])
    stats = iter(["40 (w) S 1 0 0 0 0 0 0 0 0 0 5 0 0 0 0 0 0 0 7\n",
                  "40 (w) S 1 0 0 0 0 0 0 0 0 0 9 1 0 0 0 0 0 0 7\n"])  # fmt: skip

    class _Reader(ProcReader):
        def snapshot(self) -> Any:  # noqa: ANN401
            (root / "loadavg").write_text(next(loads))
            stat.write_text(next(stats))
            return super().snapshot()

    log = xl.LookLog(_Reader(root, pid=999))
    xl.LookCombiner(_Combiner(_measured()), log).combine("r", cast(Any, "p"), "b", [_change("zz")], [])  # fmt: skip
    st = cast(Any, {"trials": [], "combination": _comb(), "review_combination": None})
    (row,) = xl.look_rows(log, st)
    assert row["kind"] == "greedy" and row["offered"] == ["zz"]  # unknown trial: its id
    assert row["error"] is None and cast(float, row["end"]) >= cast(float, row["start"])
    proc = cast(dict[str, Any], row["proc"])
    assert (
        proc["before"]["loadavg"]["one"] == 1.0
        and proc["after"]["loadavg"]["one"] == 2.0
    )
    assert proc["top"] == [{"pid": 40, "comm": "w", "ticks": 5, "new": False}]
    assert proc["cpu_ticks"] is None and proc["pressure_stall_us"] is None
    assert log.proc_seconds() >= 0


def test_the_call_lists_name_what_each_call_runs() -> None:
    """``proc_includes``: the code's own steps, each conditional one with
    its setting; a replay has no editor and no retry, but the same capture
    and measurement as a trial."""
    assert xl.TRIAL_CALL[:4] == ["worktree at the base", "editor request",
                                 "capture and anti-cheat checks (quality references among them)",
                                 "commit"]  # fmt: skip
    assert "ABBA against the twin (PAIRED_TRIALS; else the trial's runs alone)" in xl.TRIAL_CALL  # fmt: skip
    assert "suite" in xl.TRIAL_CALL and xl.TRIAL_CALL[-1].startswith("one fix retry")
    for step in ("counted run per side (OP_COUNT_JUDGE; its units with IDEAS_COUNT_CONTRACT on)",
                 "scaling runs (SCALING_JUDGE)",
                 "capture launch per side (SHADOW_VERIFY on)",
                 "quality scoring (a quality check)"):  # fmt: skip
        assert step in xl.TRIAL_CALL and step in xl.REPLAY_CALL
    assert xl.REPLAY_CALL[:4] == ["cherry-pick of the parents", "worktree at the cherry-picked tree",
                                  "capture and anti-cheat checks (quality references among them)",
                                  "commit"]  # fmt: skip
    assert not any("editor" in s or "retry" in s for s in xl.REPLAY_CALL)
    assert xl.COMBINE_CALL == ["merge", "ABBA (when a change applied)",
                               "quality scoring (a quality check)", "suite"]  # fmt: skip
    assert xl.INCLUDES == {"trial": xl.TRIAL_CALL, "replay": xl.REPLAY_CALL,
                           "calibration": ["all blocks"]}  # fmt: skip


def _raise(*args: object, **kwargs: object) -> CombineMeasured:
    raise RuntimeError("the combiner failed")


def test_a_combine_look_that_raised_is_unknown_one_that_never_ran_confirm(tmp_path: Path) -> None:  # fmt: skip
    """Nit: no combine-phase event either way; a failed last combiner call
    marks the combine node as entered and raised, else it never ran."""
    st = cast(Any, {"trials": [], "combination": None, "events": []})
    ran = xl.LookLog(_proc(tmp_path))
    xl.LookCombiner(_Combiner(_measured()), ran).combine(
        "r", cast(Any, "p"), "b", [], []
    )
    assert [r["kind"] for r in xl.look_rows(ran, st)] == ["confirm"]
    failing = _Combiner(_measured())
    failing.combine = _raise  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        xl.LookCombiner(failing, ran).combine("r", cast(Any, "p"), "b", [], [])
    assert [r["kind"] for r in xl.look_rows(ran, st)] == ["unknown", "unknown"]
