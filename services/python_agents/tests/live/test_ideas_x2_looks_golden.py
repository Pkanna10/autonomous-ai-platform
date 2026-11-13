"""U8a: the look wrappers change nothing the engine sends or decides.

U0's X2-D-shaped three-round run over fakes
(``tests/orchestrator/test_stacked_off_golden.py``, loaded here from its
file, unchanged) goes through the real graph with its context behind
``x2_looks.tap_context``: the runner, the calibrator and the combiner each
behind a look wrapper. Its fingerprint (every request, repository call,
event, the final state and both reports) must still be U0's ``GOLDEN``, and
the wrappers must have seen every call the recording seams saw: one look a
trial, a replay, the calibration and each combiner re-test, the combine
calls staged as confirmations, then the run combine, then the review set's.
The ``/proc`` root is an empty directory, so every snapshot reads as absent.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import Guardrail, Objective, Project, Workload
from autonomous_ai_agents.execution.fakes import FakeCombiner
from autonomous_ai_agents.execution.runner import ScriptedOutcome
from autonomous_ai_agents.orchestrator import main
from autonomous_ai_agents.orchestrator.main import Orchestrator

from . import x2_looks as xl
from .x2_proc import ProcReader

GOLDEN_FILE = Path(__file__).parents[1] / "orchestrator" / "test_stacked_off_golden.py"


def _load() -> ModuleType:
    name = "x2_u8a_stacked_off_golden"
    spec = importlib.util.spec_from_file_location(name, GOLDEN_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


golden = _load()
frozen = golden.frozen  # U0's frozen clock and numbered ids, autouse here too


def test_the_tapped_run_is_u0s_golden_and_every_call_is_a_look(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    baseline_script: ScriptedOutcome,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configs: list[dict[str, object]] = []
    real = main.run_config

    def spied(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        config = real(*args, **kwargs)
        configs.append({"args": args, "kwargs": kwargs, "result": config})
        return config

    monkeypatch.setattr(main, "run_config", spied)
    seams = golden._seams(sample_project, sample_workload, baseline_script)
    log = xl.LookLog(ProcReader(root=tmp_path))
    ctx = xl.tap_context(golden._context(seams), log)
    assert isinstance(ctx.runner, xl.LookReplayRunner)
    assert isinstance(ctx.calibrator, xl.LookCalibrator)
    assert isinstance(ctx.combiner, xl.LookCombiner)
    orchestrator = Orchestrator(context=ctx)
    result = orchestrator.run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id=golden.RUN_ID, max_rounds=3, max_cost_usd=golden.CAP_USD,
    )  # fmt: skip
    assert result.status == "done", result.state["error"]
    drawn = orchestrator.graph.get_graph()
    edges = sorted(
        (e.source, e.target, e.conditional, None if e.data is None else str(e.data))
        for e in drawn.edges
    )
    history = orchestrator.graph.get_state_history(
        {"configurable": {"thread_id": golden.RUN_ID}}
    )
    visits = [name for snap in reversed(list(history)) for name in snap.next]
    run = golden._Run(seams, result.state, tuple(sorted(drawn.nodes)), tuple(edges),
                      tuple(visits), tuple(configs))  # fmt: skip
    assert golden._fingerprint(golden._record(run)) == golden.GOLDEN

    kinds = [one.kind for one in log.looks]
    trials = len(seams.runner.calls) - kinds.count("replay")
    assert kinds.count("trial") == trials and kinds.count("replay") >= 1
    assert kinds.count("calibration") == len(seams.calibrator.calls) == 1
    assert kinds.count("combine") == len(seams.combiner.calls)
    assert all(one.error is None and one.after is not None for one in log.looks)
    rows = xl.look_rows(log, result.state)
    staged = [r["kind"] for r in rows if r["kind"] not in ("trial", "replay", "calibration")]  # fmt: skip
    st = result.state
    run_set, review = st["combination"], st["review_combination"]
    assert run_set is not None and review is not None
    tail = ["greedy", *(["fallback"] if run_set.fallback_trial_id else []), "review_greedy",
            *(["review_fallback"] if review.fallback_trial_id else [])]  # fmt: skip
    assert staged[len(staged) - len(tail) :] == tail
    assert set(staged[: len(staged) - len(tail)]) == {"confirm"}
    greedy = next(r for r in rows if r["kind"] == "greedy")
    applied = {
        t.hypothesis_id for t in st["trials"] if t.id in run_set.applied_trial_ids
    }
    assert applied <= set(greedy["offered"])  # type: ignore[call-overload]
    assert all(r["proc"]["cpu_ticks"] is None for r in rows)  # type: ignore[index]
    replays = [r for r in rows if r["kind"] == "replay"]
    assert replays and all(r["proc_includes"] == xl.REPLAY_CALL for r in replays)
    looked = [r for r in rows if r["kind"] == "trial"]
    assert looked and all(r["proc_includes"] == xl.TRIAL_CALL for r in looked)


def test_a_review_combine_that_raises_leaves_every_combine_look_unknown(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    baseline_script: ScriptedOutcome,
    tmp_path: Path,
) -> None:
    """F2: the run combine completes, then the review set's re-test raises;
    the combine node's delta never lands (no combination, no combine
    event), so its calls and the confirmations before them are ``unknown``,
    the failing look carries the error, the trial looks keep their kinds."""
    seams = golden._seams(sample_project, sample_workload, baseline_script)
    script = golden._combiner_script(sample_workload)
    failing = EngineError("the review re-test failed")
    seams = dataclasses.replace(seams, combiner=FakeCombiner([*script[:-1], failing]))
    log = xl.LookLog(ProcReader(root=tmp_path))
    result = Orchestrator(context=xl.tap_context(golden._context(seams), log)).run(
        sample_project, [sample_workload], [sample_objective], sample_guardrails,
        run_id=golden.RUN_ID, max_rounds=3, max_cost_usd=golden.CAP_USD,
    )  # fmt: skip
    st = result.state
    assert result.status == "failed" and st["combination"] is None
    assert not xl.combine_completed(st)
    combines = [one for one in log.looks if one.kind == "combine"]
    assert len(combines) == len(script) == len(seams.combiner.calls)
    assert combines[-1].error == "EngineError" and combines[-2].error is None
    rows = xl.look_rows(log, st)
    kinds = [r["kind"] for r in rows]
    assert kinds.count("unknown") == len(script) and "confirm" not in kinds
    assert "greedy" not in kinds and kinds.count("calibration") == 1
    assert {"trial", "replay"} <= set(kinds)
