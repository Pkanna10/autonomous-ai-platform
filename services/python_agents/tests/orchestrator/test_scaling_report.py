"""The scaling judge through the whole graph (G6b): a column, never a verdict.

The four design hypotheses (keep, reject, inconclusive, review) run on stub
runners wrapped to also report scaling rows (``Scaled``: the base grows as
n^2, each trial at its scripted rate): once with the default judges and
once with the scaling judge added (and once with both shadow judges). Every
verdict decides the same; the report gains a "Growth (shadow)" column only
when the judge ran, after the "Op calls (shadow)" one when both did.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

import pytest

from autonomous_ai_agents.common.models import (
    Baseline,
    Delivery,
    Guardrail,
    Hypothesis,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    Objective,
    Project,
    RunStats,
    Trial,
    VerdictOutcome,
    Workload,
)
from autonomous_ai_agents.execution.measure import (
    METRIC_OP_CALLS,
    METRIC_SCALE_WALL_S,
    SCALE_SIZE_KEY,
)
from autonomous_ai_agents.execution.protocols import TrialBrief
from autonomous_ai_agents.execution.runner import (
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
)
from autonomous_ai_agents.optimization.judges import (
    SCALING_JUDGE,
    Judge,
    OpCountJudge,
    ScalingJudge,
    default_judges,
)
from autonomous_ai_agents.orchestrator.main import EngineGraph, run_config
from autonomous_ai_agents.orchestrator.nodes import NodeContext, scaling_cell
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state

HEADER = "| Hypothesis | Outcome | Gain | Summary |"
RATES = {"Cache": 1.0, "Skip": 2.0, "Micro-tweak": 2.0, "Run": 3.0}
"""Each design hypothesis's scripted growth rate, by its title's first word
(the base grows as n^2)."""


def grown(workloads: Sequence[Workload], power: float, trial_id: str | None) -> tuple[Measurement, ...]:  # fmt: skip
    return tuple(
        Measurement(
            workload_id=w.id, trial_id=trial_id, metric=METRIC_SCALE_WALL_S,
            stats=RunStats.from_samples((t,) * 3, unit="s"), samples=(t,) * 3,
            hardware={SCALE_SIZE_KEY: size},
        )
        for w in workloads for size in (1000, 4000) if (t := 1e-8 * size**power)
    )  # fmt: skip


@dataclass
class Scaled:
    """A stub trial runner whose trials also carry scaling rows."""

    inner: StubTrialRunner

    def run(
        self, hypothesis: Hypothesis, workloads: Sequence[Workload], baseline: Baseline,
        *, round: int, branch: str, budget_usd: float, brief: TrialBrief,
    ) -> Trial:  # fmt: skip
        trial = self.inner.run(
            hypothesis, workloads, baseline, round=round, branch=branch,
            budget_usd=budget_usd, brief=brief,
        )  # fmt: skip
        if not trial.measurements:
            return trial
        rows = grown(workloads, RATES[hypothesis.title.split()[0]], trial.id)
        return trial.model_copy(update={"measurements": (*trial.measurements, *rows)})


@dataclass
class ScaledBase:
    inner: StubBaselineRunner

    def measure(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str | None
    ) -> tuple[Measurement, ...]:
        rows = self.inner.measure(workloads, run_id=run_id, commit=commit)
        return (*rows, *grown(workloads, 2.0, None))


def _with_counts(script: ScriptedOutcome) -> ScriptedOutcome:
    return replace(script, samples={**script.samples, METRIC_OP_CALLS: (100.0,) * 5})


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
) -> Callable[[tuple[Judge, ...]], EngineState]:
    scripts = {title: _with_counts(script) for title, script in design_scripts.items()}

    def go(judges: tuple[Judge, ...]) -> EngineState:
        ctx = make_context(
            [h1_cache, h2_protected, h3_noise, h4_behaviour], scripts,
            baseline_runner=ScaledBase(StubBaselineRunner(_with_counts(baseline_script))),
            runner=Scaled(StubTrialRunner(scripts)), judges=judges,
            max_hypotheses_per_round=4,
        )  # fmt: skip
        run_id = f"scaling-{len(judges)}"
        state = initial_state(
            sample_project, [sample_workload], [sample_objective], sample_guardrails,
            run_id=run_id, max_rounds=1,
        )  # fmt: skip
        output = engine_graph(ctx).invoke(state, run_config(run_id, 1), version="v2")
        assert output.interrupts == ()
        return output.value

    return go


def _report_of(state: EngineState) -> str:
    delivery = state["delivery"]
    assert isinstance(delivery, Delivery)
    return delivery.report_markdown


def test_the_verdicts_are_the_same_and_the_report_gains_the_column(
    run: Callable[[tuple[Judge, ...]], EngineState],
    h1_cache: Hypothesis,
    h2_protected: Hypothesis,
    h3_noise: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN H1 (keep, n^2 to n), H2 (reject, same growth), H3 (inconclusive,
        same growth) and H4 (review, n^2 to n^3)
    WHEN the run goes without the scaling judge, with it, and with both
        shadow judges
    THEN outcome, summary and gain of every verdict are identical in all
        three, the kept set is the same, and only the second and third
        reports have the growth column, after the op-calls column
    """
    plain = run(default_judges())
    scaled = run(default_judges(scaling=True))
    both = run(default_judges(op_count=True, scaling=True))

    def decided(state: EngineState) -> dict[str, tuple[object, ...]]:
        return {
            v.hypothesis_id: (v.outcome, v.summary, v.gain, v.change_class)
            for v in state["verdicts"]
        }

    assert decided(scaled) == decided(plain) == decided(both)
    assert {k: s[0] for k, s in decided(plain).items()} == {
        h1_cache.id: VerdictOutcome.keep,
        h2_protected.id: VerdictOutcome.reject,
        h3_noise.id: VerdictOutcome.inconclusive,
        h4_behaviour.id: VerdictOutcome.review,
    }
    assert len(scaled["kept_verdict_ids"]) == len(plain["kept_verdict_ids"]) == 1
    assert all(v.judge_results[-1].judge == SCALING_JUDGE for v in scaled["verdicts"])

    report = _report_of(scaled)
    assert HEADER + " Growth (shadow) |\n| --- | --- | --- | --- | --- |\n" in report
    lines = report.splitlines()
    cache = [line for line in lines if line.startswith("| Cache")]
    assert cache and cache[0].endswith("| n^2.00 → n^1.00 (-1.00) |")
    assert any(line.endswith("| n^2.00 → n^3.00 (+1.00) |") for line in lines)
    assert HEADER + " Op calls (shadow) | Growth (shadow) |\n" in _report_of(both)
    assert "Growth" not in _report_of(plain)
    assert HEADER + "\n| --- | --- | --- | --- |\n" in _report_of(plain)


def _result(**fields: object) -> JudgeResult:
    base: dict[str, object] = {
        "judge": SCALING_JUDGE, "outcome": JudgeOutcome.not_applicable, "reason": "r",
        "details": {"base_rate": 2.0, "trial_rate": 1.25, "change": -0.75},
    }  # fmt: skip
    return JudgeResult.model_validate({**base, **fields})


def test_the_cell_says_not_scaled_without_both_rates() -> None:
    assert scaling_cell(()) == "not scaled"
    assert scaling_cell((_result(judge="speed"),)) == "not scaled"
    assert scaling_cell((_result(details={"workloads": 0}),)) == "not scaled"
    assert scaling_cell((_result(details={"base_rate": 2.0, "trial_rate": "x", "change": 0.0}),)) == "not scaled"  # fmt: skip
    assert scaling_cell((_result(),)) == "n^2.00 → n^1.25 (-0.75)"
    assert scaling_cell((OpCountJudge().evaluate(Baseline(), Trial(hypothesis_id="h", round=1)), _result())) == "n^2.00 → n^1.25 (-0.75)"  # fmt: skip
    assert ScalingJudge().name == SCALING_JUDGE
