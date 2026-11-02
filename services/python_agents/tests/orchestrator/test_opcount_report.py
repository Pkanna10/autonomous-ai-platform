"""The operation-count judge through the whole graph (G6a): a column, never a verdict.

The four design hypotheses (keep, reject, inconclusive, review) run on stub
runners whose scripts also report ``op_calls``: once with the default judges
and once with the operation-count judge added. Every verdict decides the
same; the report gains an "Op calls (shadow)" column only in the second run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

import pytest

from autonomous_ai_agents.common.models import (
    Delivery,
    Guardrail,
    Hypothesis,
    JudgeOutcome,
    JudgeResult,
    Objective,
    Project,
    RunStats,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.measure import METRIC_OP_CALLS
from autonomous_ai_agents.execution.runner import ScriptedOutcome, StubBaselineRunner
from autonomous_ai_agents.optimization.judges import OP_COUNT_JUDGE, default_judges
from autonomous_ai_agents.orchestrator.main import EngineGraph, run_config
from autonomous_ai_agents.orchestrator.nodes import NodeContext, op_count_cell
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

HEADER = "| Hypothesis | Outcome | Gain | Summary |"
SHADOW_HEADER = HEADER + " Op calls (shadow) |"
COUNTS = {"Cache": 800.0, "Skip": 1000.0, "Micro-tweak": 400.0, "Run": 1200.0}
"""Each design hypothesis's scripted call count, by its title's first word."""


def _with_counts(script: ScriptedOutcome, calls: float) -> ScriptedOutcome:
    return replace(script, samples={**script.samples, METRIC_OP_CALLS: (calls,) * 5})


@pytest.fixture
def run(
    make_context: Callable[..., NodeContext],
    engine_graph: Callable[..., EngineGraph],
    baseline_script: ScriptedOutcome,
    design_scripts: Mapping[str, ScriptedOutcome],
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
    h2_protected: Hypothesis,
    h3_noise: Hypothesis,
    h4_behaviour: Hypothesis,
) -> Callable[[bool], EngineState]:
    scripts = {
        title: _with_counts(script, COUNTS[title.split()[0]])
        for title, script in design_scripts.items()
    }
    baseline = StubBaselineRunner(_with_counts(baseline_script, 1000.0))

    def go(op_count: bool) -> EngineState:
        ctx = make_context(
            [h1_cache, h2_protected, h3_noise, h4_behaviour], scripts,
            baseline_runner=baseline, judges=default_judges(op_count=op_count),
            max_hypotheses_per_round=4,
        )  # fmt: skip
        run_id = f"opcount-{int(op_count)}"
        state = initial_state(
            sample_project, [sample_workload], [sample_objective], sample_guardrails,
            run_id=run_id, max_rounds=1,
        )  # fmt: skip
        output = engine_graph(ctx).invoke(state, run_config(run_id, 1), version="v2")
        assert output.interrupts == ()
        return output.value

    return go


def test_the_verdicts_are_the_same_and_the_report_gains_the_column(
    run: Callable[[bool], EngineState],
    h1_cache: Hypothesis,
    h2_protected: Hypothesis,
    h3_noise: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN H1 (keep, 20 % fewer calls), H2 (reject, same calls), H3
        (inconclusive although it removes 60 % of the calls) and H4 (review,
        20 % more calls)
    WHEN the run goes once without and once with the operation-count judge
    THEN outcome, summary and gain of every verdict are identical, the kept
        set is the same, and only the second report has the shadow column,
        one cell per verdict row
    """
    plain, shadowed = run(False), run(True)

    def decided(state: EngineState) -> dict[str, tuple[object, ...]]:
        return {
            v.hypothesis_id: (v.outcome, v.summary, v.gain, v.change_class)
            for v in state["verdicts"]
        }

    assert decided(shadowed) == decided(plain)
    outcomes = {key: shape[0] for key, shape in decided(plain).items()}
    assert outcomes == {
        h1_cache.id: VerdictOutcome.keep,
        h2_protected.id: VerdictOutcome.reject,
        h3_noise.id: VerdictOutcome.inconclusive,
        h4_behaviour.id: VerdictOutcome.review,
    }
    assert len(shadowed["kept_verdict_ids"]) == len(plain["kept_verdict_ids"]) == 1
    assert all(
        v.judge_results[-1].judge == OP_COUNT_JUDGE for v in shadowed["verdicts"]
    )
    assert all(
        r.judge != OP_COUNT_JUDGE for v in plain["verdicts"] for r in v.judge_results
    )

    report = _report_of(shadowed)
    assert SHADOW_HEADER in report and HEADER + "\n" not in report
    assert "| --- | --- | --- | --- | --- |" in report
    rows = [line for line in report.splitlines() if line.startswith("| Cache")]
    assert rows and rows[0].endswith("| 1000 → 800 calls (-20.0%) |")
    assert any(line.endswith("| 1000 → 400 calls (-60.0%) |") for line in report.splitlines())  # fmt: skip
    plain_report = _report_of(plain)
    assert HEADER + "\n| --- | --- | --- | --- |\n" in plain_report
    assert "Op calls" not in plain_report


def _report_of(state: EngineState) -> str:
    delivery = state["delivery"]
    assert isinstance(delivery, Delivery)
    return delivery.report_markdown


def _result(**fields: object) -> JudgeResult:
    base: dict[str, object] = {
        "judge": OP_COUNT_JUDGE, "outcome": JudgeOutcome.not_applicable,
        "metric": METRIC_OP_CALLS, "reason": "r",
    }  # fmt: skip
    return JudgeResult.model_validate({**base, **fields})


def test_the_cell_says_not_counted_without_both_counts_and_handles_a_zero_base() -> None:  # fmt: skip
    zero, five = (RunStats.from_samples((v,), unit="calls") for v in (0.0, 5.0))

    assert op_count_cell(()) == "not counted"
    assert op_count_cell((_result(judge="speed"),)) == "not counted"
    assert op_count_cell((_result(),)) == "not counted"
    assert op_count_cell((_result(baseline=zero, trial=five),)) == "0 → 5 calls"
    assert op_count_cell((_result(baseline=five, trial=five),)) == "5 → 5 calls (+0.0%)"
