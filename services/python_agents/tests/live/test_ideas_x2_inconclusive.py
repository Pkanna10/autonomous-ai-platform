"""U8a (O63, record-only): an X2 run writes the diff of each inconclusive
trial whose first-look gain is above the run's calibrated baseline floor,
as kept diffs are written, and (O64-3) its looks and machine on the run row.

The fakes run is ``test_ideas_x2_patches``'s (``run_one`` with the loop and
the engine faked, ``$LIVE_RESULTS_PATH`` in ``tmp_path``): its state has a
diff per trial; each case sets the baseline's calibration and the lens
idea's inconclusive verdict. The tapped case hands ``run_one`` a loop with a
real ``NodeContext`` over fakes, whose fake engine calls the context's
runner and combiner as the nodes would; ``/proc`` is a synthetic tree on the
recorder. Every older row key keeps its value (the X2 guards, unchanged).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import (
    Baseline,
    NoiseCalibration,
    Trial,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.optimization.judges import OpCountJudge
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.persistence.repository import InMemoryRepository

from . import ideas_x2 as x2
from . import test_ideas_x2_guards as xg
from . import test_ideas_x2_patches as xpt
from . import test_oss_guards as og
from . import x2_looks as xl
from . import x2_patches as xp
from .conftest import LiveRun, StartLive
from .corpus import RESULTS_ENV, Loop
from .discovery_io import ResultsSink
from .x2_proc import ProcReader

x2_run = xg.x2_run
Json = dict[str, Any]
NEW_RUN_KEYS = {"inconclusive_diffs", "inconclusive_diffs_note", "machine", "looks",
                "looks_proc_seconds"}  # fmt: skip


def _lens(gain: float | None, floor: float | None,
          orphan: bool = False) -> Callable[[dict[str, Any]], None]:  # fmt: skip
    """The lens idea's inconclusive verdict at ``gain``, the baseline
    calibrated at ``floor`` (``None``: no baseline)."""

    def change(st: dict[str, Any]) -> None:
        st["verdicts"] = [v.model_copy(update={"gain": gain})
                          if v.outcome is VerdictOutcome.inconclusive else v
                          for v in st["verdicts"]]  # fmt: skip
        if floor is not None:
            cal = NoiseCalibration(blocks=3, gaps={"w": floor / 2}, floor=floor)
            st["baseline"] = Baseline(calibration=cal)
        if orphan:
            lens = next(
                v for v in st["verdicts"] if v.outcome is VerdictOutcome.inconclusive
            )
            st["trials"] = [t for t in st["trials"] if t.id != lens.trial_id]

    return change


def _inconclusive(st: dict[str, Any]) -> tuple[str, Trial]:
    v = next(v for v in st["verdicts"] if v.outcome is VerdictOutcome.inconclusive)
    return v.hypothesis_id, next(t for t in st["trials"] if t.id == v.trial_id)


def test_an_inconclusive_gain_above_the_floor_writes_its_diff(x2_run: Any, tmp_path: Path) -> None:  # fmt: skip
    engine = xpt._Diffs(_lens(0.05, 0.03))
    _, rows = x2_run(engine)
    hid, trial = _inconclusive(engine.state)
    ideas, run = xpt._ideas(rows), xpt._run_row(rows)
    entry = ideas[hid]["inconclusive_diff"]
    assert entry["trial_id"] == trial.id and entry["gain_pct"] == pytest.approx(5.0)
    assert entry["file"] == f"{xpt.RUN_DIR}/{xp.trial_file(trial.id)}"
    assert (tmp_path / entry["file"]).read_bytes() == trial.diff.encode("utf-8")
    assert (entry["commit"], entry["base_commit"], entry["error"]) == (trial.commit, xpt.BASE, None)  # fmt: skip
    assert run["inconclusive_diffs"] == [{"hypothesis_id": hid, **entry}]
    assert run["inconclusive_diffs_note"] is None
    assert all("inconclusive_diff" not in r for h, r in ideas.items() if h != hid)
    kept = [r for r in ideas.values() if r["verdict"] == "keep"]
    assert len(kept) == 2 and all("diff" in r for r in kept)  # the kept ones as before
    assert len(run["kept_diffs"]) == 2 and run["baseline_floor_pct"] == pytest.approx(
        3.0
    )


@pytest.mark.parametrize(
    ("gain", "floor", "note"),
    [(0.05, None, x2.NO_FLOOR), (0.03, 0.03, x2.NONE_ABOVE), (0.01, 0.02, x2.NONE_ABOVE),
     (None, 0.02, x2.NONE_ABOVE)],
    ids=["uncalibrated", "at-the-floor", "below", "no-gain"],
)  # fmt: skip
def test_no_diff_is_written_at_or_below_the_floor(
    gain: float | None, floor: float | None, note: str, x2_run: Any, tmp_path: Path
) -> None:
    engine = xpt._Diffs(_lens(gain, floor))
    _, rows = x2_run(engine)
    hid, trial = _inconclusive(engine.state)
    run = xpt._run_row(rows)
    assert run["inconclusive_diffs"] == [] and run["inconclusive_diffs_note"] == note
    assert "inconclusive_diff" not in xpt._ideas(rows)[hid]
    assert not (tmp_path / xpt.RUN_DIR / xp.trial_file(trial.id)).exists()


def test_an_inconclusive_verdict_with_no_recorded_trial_says_so(x2_run: Any) -> None:
    engine = xpt._Diffs(_lens(0.05, 0.03, orphan=True))
    _, rows = x2_run(engine)
    (entry,) = xpt._run_row(rows)["inconclusive_diffs"]
    assert entry["file"] is None and entry["error"] == x2.INCONCLUSIVE_ORPHAN
    assert "inconclusive" in entry["error"] and entry["error"] != xp.ORPHAN  # its own


def test_a_calibration_less_baseline_is_uncalibrated(x2_run: Any) -> None:
    def change(st: dict[str, Any]) -> None:
        _lens(0.05, None)(st)
        st["baseline"] = Baseline()

    _, rows = x2_run(xpt._Diffs(change))
    run = xpt._run_row(rows)
    assert (
        run["inconclusive_diffs"] == []
        and run["inconclusive_diffs_note"] == x2.NO_FLOOR
    )


def test_an_untapped_run_records_no_looks(x2_run: Any) -> None:
    """The fakes loop has no ``NodeContext``: nothing is tapped, the three
    look keys are ``None`` (the other run keys: the guards above, unchanged)."""
    _, rows = x2_run()
    run = xpt._run_row(rows)
    assert NEW_RUN_KEYS <= set(run)
    assert [run[k] for k in ("machine", "looks", "looks_proc_seconds")] == [None] * 3


# ---------------------------------------------------------------------------
# A tapped run: the run row carries the looks
# ---------------------------------------------------------------------------


class _Runner:
    def run(
        self, hypothesis: Any, workloads: Any, baseline: Any, **kwargs: Any
    ) -> Trial:
        return Trial(hypothesis_id=hypothesis.id, round=1)


class _Engine:
    """``start_x2_loop`` gives a ``Loop`` on a real ``NodeContext``;
    ``run_engine`` calls its runner, as the trials node would, then records."""

    def __init__(self) -> None:
        self.seen: list[object] = []

    def start(self, repo: Any, run: LiveRun, root: Path, isolation: Any, *, policy: object) -> Any:  # fmt: skip
        ctx = NodeContext(runner=cast(Any, _Runner()), baseline_runner=cast(Any, object()),
                          judges=(OpCountJudge(),), repository=InMemoryRepository())  # fmt: skip
        flow = Workload(project_id="p", name="bench", command=("python", "b.py"))
        return Loop(cast(Any, None), cast(Any, SimpleNamespace(base=xg.COMMIT, path=root)),
                    cast(Any, None), cast(Any, None), flow, (), xl.LookLaunches(), ctx, 1.0,
                    "wired")  # fmt: skip

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        self.seen.append(loop.context.runner)
        result = xg._state()
        trial = loop.context.runner.run(xg._hyp("looked"), [], Baseline(), round=1)
        cast(dict[str, Any], result.state)["trials"].append(trial)
        record(SimpleNamespace(guard="ok"), result)


def test_a_tapped_run_records_its_machine_and_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _Engine()
    monkeypatch.setattr(x2, "start_x2_loop", engine.start)
    monkeypatch.setattr(x2, "run_engine", engine.run)
    out, proc = tmp_path / "x2.jsonl", tmp_path / "proc"
    proc.mkdir()
    (proc / "loadavg").write_text("0.5 0.5 0.5 1/100 7\n")
    (proc / "meminfo").write_text("MemTotal: 2048 kB\n")
    plan = x2.x2_plan({**xg.X2_0_NEED, x2.DISPATCH_ENV: f"X2-0:{xg.REPO}"})
    sink = ResultsSink({RESULTS_ENV: str(out), "ImageVersion": "20261102.1"})
    recorder = x2.X2Recorder(plan, sink, base=xg._arm_cfg(x2.X2_0), commits={xg.REPO: xg.COMMIT},
                             proc=ProcReader(proc, pid=1))  # fmt: skip

    def live(cap: float) -> LiveRun:
        return LiveRun("x", cap)

    x2.run_one(x2.X2_0, xg.TOMLI, live=cast(StartLive, live), root=tmp_path / "root",
               isolation=xg.REQUIRED, recorder=recorder, policy=og.LOCAL)  # fmt: skip
    assert isinstance(engine.seen[0], xl.LookRunner)
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    run = xpt._run_row(rows)
    assert run["machine"]["memory_bytes"] == 2048 * 1024
    assert (
        run["machine"]["ImageVersion"] == "20261102.1"
        and run["machine"]["RUNNER_NAME"] is None
    )
    (look,) = run["looks"]
    assert (look["kind"], look["look"], look["error"]) == ("trial", 1, None)
    assert look["proc"]["before"]["loadavg"]["total"] == 100.0
    assert (look["samples"], look["ab"], look["ab_aligned"]) == (None, None, None)
    assert run["looks_proc_seconds"] >= 0


def test_a_run_with_no_state_says_so(x2_run: Any, tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="repository changed"):
        x2_run(xg._Engine(breach=True))  # recorded with no result, then raised
    lines = (tmp_path / "x2.jsonl").read_text(encoding="utf-8").splitlines()
    run = xpt._run_row([json.loads(x) for x in lines])
    assert (
        run["inconclusive_diffs"] == []
        and run["inconclusive_diffs_note"] == x2.NO_STATE
    )
    assert x2.NO_STATE not in (x2.NO_FLOOR, x2.NONE_ABOVE)
