"""Tests for the trial runner interface and its scripted stub (Step 1 U5, Step 2 U3).

``TrialRunner`` is the seam between the orchestrator and the hardware that
runs trials. ``StubTrialRunner`` replays scripted outcomes so the whole loop
can be tested without subprocesses, git or an LLM. Step 2 adds the money and
the brief to every trial (``budget_usd``, ``brief``) and the run id and
commit to every baseline (``run_id``, ``commit``).
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable
from datetime import UTC

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Baseline,
    ChangeClass,
    Hypothesis,
    HypothesisSource,
    Measurement,
    Project,
    RunStats,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.protocols import TrialBrief
from autonomous_ai_agents.execution.runner import (
    BaselineRunner,
    ScriptedOutcome,
    StubBaselineRunner,
    StubTrialRunner,
    TrialRunner,
)

WALL_SAMPLES: tuple[float, ...] = (1.05, 1.02, 1.08, 1.05, 1.05)
RSS_SAMPLES: tuple[float, ...] = (1.0e9, 1.1e9, 1.0e9, 1.0e9, 1.05e9)
FINGERPRINT = "a" * 64
BUDGET = 5.0
BRIEF = TrialBrief(understanding=None, hotspots=(), protected=("tests/**",))
COMMIT = "0123456789abcdef0123456789abcdef01234567"

FAST = ScriptedOutcome(
    touched_paths=("src/bridge/encoder.py",),
    samples={METRIC_WALL_TIME_S: WALL_SAMPLES, METRIC_PEAK_RSS_BYTES: RSS_SAMPLES},
    output_fingerprint=FINGERPRINT,
    tests_passed=True,
    cost_usd=0.12,
    tokens_used=3400,
)
BROKEN = ScriptedOutcome(
    touched_paths=("src/bridge/encoder.py",),
    error="SyntaxError: invalid syntax (encoder.py, line 12)",
    cost_usd=0.05,
    tokens_used=900,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _project() -> Project:
    return Project(name="bridge", root_path="/home/dev/bridge")


def _workloads(project: Project) -> tuple[Workload, Workload]:
    return (
        Workload(project_id=project.id, name="train", command=("python", "train.py")),
        Workload(project_id=project.id, name="eval", command=("python", "eval.py")),
    )


def _hypothesis(project: Project, title: str = "Cache CLIP embeddings") -> Hypothesis:
    return Hypothesis(
        project_id=project.id,
        source=HypothesisSource.playbook,
        title=title,
        rationale="Encoder is frozen; 42% of step time recomputes it.",
        change_class=ChangeClass.efficiency,
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
    )


def _baseline(workloads: tuple[Workload, ...]) -> Baseline:
    samples = (1.80, 1.75, 1.85, 1.80, 1.80)
    return Baseline(
        measurements=tuple(
            Measurement(
                workload_id=workload.id,
                metric=METRIC_WALL_TIME_S,
                stats=RunStats.from_samples(samples, unit="s"),
                samples=samples,
                output_fingerprint=FINGERPRINT,
            )
            for workload in workloads
        )
    )


def _by_metric(
    measurements: tuple[Measurement, ...], workload: Workload
) -> dict[str, Measurement]:
    return {m.metric: m for m in measurements if m.workload_id == workload.id}


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_stub_runner_satisfies_the_trial_runner_protocol() -> None:
    """
    GIVEN a StubTrialRunner
    WHEN checked against the runtime-checkable TrialRunner protocol
    THEN it conforms
    """
    assert isinstance(StubTrialRunner({}), TrialRunner)


# ---------------------------------------------------------------------------
# Measured trials
# ---------------------------------------------------------------------------


def test_run_builds_a_measured_trial_from_the_script() -> None:
    """
    GIVEN a hypothesis scripted with samples, a fingerprint and a cost
    WHEN the stub runner runs it
    THEN the trial carries the identity, status, paths, cost and timestamps
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=2,
        branch="engine/run-1/h1",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert trial.hypothesis_id == hypothesis.id
    assert trial.round == 2
    assert trial.branch == "engine/run-1/h1"
    assert trial.touched_paths == ("src/bridge/encoder.py",)
    assert trial.status is TrialStatus.measured
    assert trial.error is None
    assert trial.cost_usd == 0.12
    assert trial.tokens_used == 3400
    assert trial.started_at is not None and trial.started_at.tzinfo is UTC
    assert trial.finished_at is not None and trial.finished_at >= trial.started_at


def test_run_measures_every_workload_times_every_metric() -> None:
    """
    GIVEN two workloads and a script with two metrics plus tests_passed
    WHEN the stub runner runs the hypothesis
    THEN each workload gets one measurement per metric, all tied to the trial
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert len(trial.measurements) == 2 * 3
    assert all(m.trial_id == trial.id for m in trial.measurements)
    for workload in workloads:
        by_metric = _by_metric(trial.measurements, workload)
        assert set(by_metric) == {
            METRIC_WALL_TIME_S,
            METRIC_PEAK_RSS_BYTES,
            METRIC_TESTS_PASSED,
        }
        wall = by_metric[METRIC_WALL_TIME_S]
        assert wall.samples == WALL_SAMPLES
        assert wall.stats == RunStats.from_samples(WALL_SAMPLES, unit="s")
        assert wall.output_fingerprint == FINGERPRINT
        rss = by_metric[METRIC_PEAK_RSS_BYTES]
        assert rss.samples == RSS_SAMPLES
        assert rss.stats.unit == "bytes"
        assert rss.output_fingerprint == FINGERPRINT


def test_unknown_metric_gets_an_empty_unit() -> None:
    """
    GIVEN a script measuring a metric that is neither *_s nor *_bytes
    WHEN the stub runner runs it
    THEN the measurement's unit is empty
    """
    project = _project()
    workloads = _workloads(project)[:1]
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner(
        {hypothesis.id: ScriptedOutcome(samples={"val_loss": (0.41, 0.42)})}
    )

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert len(trial.measurements) == 1
    assert trial.measurements[0].metric == "val_loss"
    assert trial.measurements[0].stats.unit == ""
    assert trial.measurements[0].output_fingerprint is None


@pytest.mark.parametrize(
    ("tests_passed", "expected"), [(True, (1.0,)), (False, (0.0,))]
)
def test_tests_passed_becomes_a_boolean_measurement(
    tests_passed: bool, expected: tuple[float, ...]
) -> None:
    """
    GIVEN a script that reports whether the test suite passed
    WHEN the stub runner runs it
    THEN every workload gets a tests_passed measurement with unit "bool"
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner(
        {hypothesis.id: ScriptedOutcome(tests_passed=tests_passed)}
    )

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert len(trial.measurements) == len(workloads)
    for workload in workloads:
        measurement = _by_metric(trial.measurements, workload)[METRIC_TESTS_PASSED]
        assert measurement.samples == expected
        assert measurement.stats.unit == "bool"
        assert measurement.stats.n == 1
        assert measurement.output_fingerprint is None


def test_tests_passed_none_adds_no_measurement() -> None:
    """
    GIVEN a script that says nothing about the test suite
    WHEN the stub runner runs it
    THEN no tests_passed measurement is produced
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner(
        {hypothesis.id: ScriptedOutcome(samples={METRIC_WALL_TIME_S: WALL_SAMPLES})}
    )

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert {m.metric for m in trial.measurements} == {METRIC_WALL_TIME_S}


def test_run_is_deterministic_apart_from_ids_and_timestamps() -> None:
    """
    GIVEN the same script run twice
    WHEN the measurements are compared
    THEN metrics, samples and stats match while trial ids differ
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    first = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )
    second = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    def shape(trial_measurements: tuple[Measurement, ...]) -> list[tuple[object, ...]]:
        return [
            (m.workload_id, m.metric, m.samples, m.stats) for m in trial_measurements
        ]

    assert first.id != second.id
    assert shape(first.measurements) == shape(second.measurements)


# ---------------------------------------------------------------------------
# Failed trials
# ---------------------------------------------------------------------------


def test_error_script_yields_a_failed_trial_without_measurements() -> None:
    """
    GIVEN a script with an error
    WHEN the stub runner runs it
    THEN the trial is failed, carries the error and has no measurements
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: BROKEN})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert trial.status is TrialStatus.failed
    assert trial.error == BROKEN.error
    assert trial.measurements == ()
    assert trial.touched_paths == ("src/bridge/encoder.py",)
    assert trial.cost_usd == 0.05
    assert trial.tokens_used == 900
    assert trial.finished_at is not None


# ---------------------------------------------------------------------------
# Script lookup
# ---------------------------------------------------------------------------


def test_unscripted_hypothesis_without_default_raises_key_error() -> None:
    """
    GIVEN a runner with no script for the hypothesis and no default
    WHEN it runs the hypothesis
    THEN a KeyError names the hypothesis id and title
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({})

    with pytest.raises(KeyError, match=f"{hypothesis.id}.*{hypothesis.title}"):
        runner.run(
            hypothesis,
            workloads,
            _baseline(workloads),
            round=1,
            branch="engine/x",
            budget_usd=BUDGET,
            brief=BRIEF,
        )


def test_scripts_fall_back_to_title_then_default() -> None:
    """
    GIVEN scripts keyed by title and a default outcome
    WHEN hypotheses with and without a script are run
    THEN the title script wins for its hypothesis and the default covers the rest
    """
    project = _project()
    workloads = _workloads(project)
    titled = _hypothesis(project, title="Cache CLIP embeddings")
    other = _hypothesis(project, title="Use bf16 autocast")
    runner = StubTrialRunner({titled.title: FAST}, default=BROKEN)

    by_title = runner.run(
        titled,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )
    by_default = runner.run(
        other,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert by_title.status is TrialStatus.measured
    assert by_default.status is TrialStatus.failed
    assert by_default.error == BROKEN.error


def test_id_script_wins_over_title_script() -> None:
    """
    GIVEN scripts keyed by both the hypothesis id and its title
    WHEN the hypothesis is run
    THEN the id-keyed script is used
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST, hypothesis.title: BROKEN})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=BUDGET,
        brief=BRIEF,
    )

    assert trial.status is TrialStatus.measured


def test_runner_records_every_call() -> None:
    """
    GIVEN a runner used for two hypotheses across two rounds
    WHEN the calls are inspected
    THEN they list (hypothesis id, round) in order, including failed lookups
    """
    project = _project()
    workloads = _workloads(project)
    first, second, unscripted = (
        _hypothesis(project, "A"),
        _hypothesis(project, "B"),
        _hypothesis(project, "C"),
    )
    runner = StubTrialRunner({first.id: FAST, second.id: BROKEN})

    runner.run(
        first,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/a",
        budget_usd=BUDGET,
        brief=BRIEF,
    )
    runner.run(
        second,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/b",
        budget_usd=BUDGET,
        brief=BRIEF,
    )
    runner.run(
        first,
        workloads,
        _baseline(workloads),
        round=2,
        branch="engine/a2",
        budget_usd=BUDGET,
        brief=BRIEF,
    )
    with pytest.raises(KeyError):
        runner.run(
            unscripted,
            workloads,
            _baseline(workloads),
            round=2,
            branch="x",
            budget_usd=BUDGET,
            brief=BRIEF,
        )

    assert runner.calls == [
        (first.id, 1),
        (second.id, 1),
        (first.id, 2),
        (unscripted.id, 2),
    ]


def test_scripted_outcome_defaults_are_empty_and_frozen() -> None:
    """
    GIVEN a ScriptedOutcome built with no arguments
    WHEN its fields are read and one is assigned
    THEN the defaults are empty and the assignment is refused
    """
    outcome = ScriptedOutcome()

    assert outcome.touched_paths == ()
    assert dict(outcome.samples) == {}
    assert outcome.output_fingerprint is None
    assert outcome.tests_passed is None
    assert outcome.error is None
    assert outcome.cost_usd == 0.0
    assert outcome.tokens_used == 0
    with pytest.raises(AttributeError):
        outcome.error = "nope"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Baseline runner
# ---------------------------------------------------------------------------


def test_stub_baseline_runner_satisfies_the_baseline_runner_protocol() -> None:
    """
    GIVEN a StubBaselineRunner
    WHEN checked against the runtime-checkable BaselineRunner protocol
    THEN it conforms
    """
    assert isinstance(StubBaselineRunner(FAST), BaselineRunner)


def test_stub_baseline_runner_measures_every_workload_times_every_metric() -> None:
    """
    GIVEN two workloads and a script with two metrics plus tests_passed
    WHEN the stub baseline runner measures them
    THEN each workload gets one measurement per metric with no trial id
    """
    workloads = _workloads(_project())
    runner = StubBaselineRunner(FAST)

    measurements = runner.measure(workloads)

    assert len(measurements) == 2 * 3
    assert all(m.trial_id is None for m in measurements)
    for workload in workloads:
        by_metric = _by_metric(measurements, workload)
        assert set(by_metric) == {
            METRIC_WALL_TIME_S,
            METRIC_PEAK_RSS_BYTES,
            METRIC_TESTS_PASSED,
        }
        wall = by_metric[METRIC_WALL_TIME_S]
        assert wall.samples == WALL_SAMPLES
        assert wall.stats == RunStats.from_samples(WALL_SAMPLES, unit="s")
        assert wall.output_fingerprint == FINGERPRINT
        assert by_metric[METRIC_TESTS_PASSED].samples == (1.0,)


def test_stub_baseline_runner_records_every_call() -> None:
    """
    GIVEN a stub baseline runner measured twice with different workloads,
          once with a run id and commit and once without
    WHEN the calls are inspected
    THEN they list (workload ids, run id, commit) of each call in order,
         None standing for an argument that was not passed
    """
    train, evaluate = _workloads(_project())
    runner = StubBaselineRunner(FAST)

    runner.measure((train, evaluate), run_id="r1", commit=COMMIT)
    runner.measure((evaluate,))

    assert runner.calls == [
        ((train.id, evaluate.id), "r1", COMMIT),
        ((evaluate.id,), None, None),
    ]


def test_stub_baseline_runner_ignores_run_id_and_commit() -> None:
    """
    GIVEN the same script measured with and without a run id and commit
    WHEN the measurements are compared
    THEN they have the same shape: the stub measures nothing real
    """
    workloads = _workloads(_project())
    runner = StubBaselineRunner(FAST)

    plain = runner.measure(workloads)
    pinned = runner.measure(workloads, run_id="r1", commit=COMMIT)

    assert [(m.workload_id, m.metric, m.samples) for m in plain] == [
        (m.workload_id, m.metric, m.samples) for m in pinned
    ]


def test_stub_baseline_runner_with_an_empty_script_measures_nothing() -> None:
    """
    GIVEN a stub baseline runner scripted with no samples and no test flag
    WHEN it measures a workload
    THEN no measurements come back
    """
    workloads = _workloads(_project())

    assert StubBaselineRunner(ScriptedOutcome()).measure(workloads) == ()


# ---------------------------------------------------------------------------
# Step 2 signatures: budget, brief, run id and commit
# ---------------------------------------------------------------------------

KW = inspect.Parameter.KEYWORD_ONLY


def _params(method: Callable[..., object]) -> dict[str, inspect.Parameter]:
    params = inspect.signature(method).parameters
    return {name: p for name, p in params.items() if name != "self"}


@pytest.mark.parametrize("method", [TrialRunner.run, StubTrialRunner.run])
def test_trial_runner_requires_budget_and_brief_keywords(
    method: Callable[..., object],
) -> None:
    """
    GIVEN the TrialRunner protocol and the stub
    WHEN run's signature is inspected
    THEN round, branch, budget_usd and brief are keyword-only with no
         default, so no call site can forget the money or the brief
    """
    params = _params(method)

    assert list(params) == [
        "hypothesis",
        "workloads",
        "baseline",
        "round",
        "branch",
        "budget_usd",
        "brief",
    ]
    for name in ("round", "branch", "budget_usd", "brief"):
        assert params[name].kind is KW, name
        assert params[name].default is inspect.Parameter.empty, name


def test_baseline_runner_protocol_requires_run_id_and_commit_keywords() -> None:
    """
    GIVEN the BaselineRunner protocol and the stub
    WHEN measure's signatures are inspected
    THEN the protocol takes run_id and commit keyword-only with no default,
         and the stub accepts both with None defaults
    """
    protocol, stub = (
        _params(BaselineRunner.measure),
        _params(StubBaselineRunner.measure),
    )

    assert list(protocol) == list(stub) == ["workloads", "run_id", "commit"]
    for name in ("run_id", "commit"):
        assert protocol[name].kind is KW and stub[name].kind is KW
        assert protocol[name].default is inspect.Parameter.empty
        assert stub[name].default is None


def test_runner_records_every_budget_and_brief() -> None:
    """
    GIVEN a stub runner called twice with different budgets and briefs
    WHEN its records are inspected
    THEN budgets and briefs list what each call received, in call order,
         alongside the unchanged (hypothesis id, round) calls
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    other = TrialBrief(understanding=None, hotspots=(), protected=())
    runner = StubTrialRunner({hypothesis.id: FAST})

    runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/a",
        budget_usd=4.5,
        brief=BRIEF,
    )
    runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=2,
        branch="engine/a",
        budget_usd=0.25,
        brief=other,
    )

    assert runner.calls == [(hypothesis.id, 1), (hypothesis.id, 2)]
    assert runner.budgets == [4.5, 0.25]
    assert runner.briefs == [BRIEF, other]


@pytest.mark.parametrize(("budget", "tokens"), [(0.05, 1416), (0.0, 0)])
def test_scripted_cost_above_the_budget_fails_the_trial(
    budget: float, tokens: int
) -> None:
    """
    GIVEN a hypothesis scripted to cost 0.12 USD for 3400 tokens and a
          budget of 0.05 USD (or nothing)
    WHEN the stub runner runs it
    THEN the trial is failed with "scripted cost exceeds budget", has no
         measurements, is charged the whole budget and the same share of the
         tokens (3400 x 0.05 / 0.12, rounded down) and touched nothing: a
         real runner's editor stops at its budget check, before capture
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=budget,
        brief=BRIEF,
    )

    assert trial.status is TrialStatus.failed
    assert trial.error == "scripted cost exceeds budget"
    assert trial.measurements == ()
    assert trial.cost_usd == budget
    assert trial.tokens_used == tokens
    assert trial.touched_paths == ()


def test_scripted_cost_equal_to_the_budget_is_measured() -> None:
    """
    GIVEN a hypothesis scripted to cost exactly the budget
    WHEN the stub runner runs it
    THEN the trial is measured and charged its scripted cost (only a cost
         strictly above the budget fails)
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=FAST.cost_usd,
        brief=BRIEF,
    )

    assert trial.status is TrialStatus.measured
    assert trial.cost_usd == FAST.cost_usd


def test_scripted_error_wins_over_the_budget_error() -> None:
    """
    GIVEN a hypothesis scripted to fail and to cost more than the budget
    WHEN the stub runner runs it
    THEN the trial carries the scripted error and its scripted paths, and is
         charged at most the budget with the same share of the tokens
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: BROKEN})

    trial = runner.run(
        hypothesis,
        workloads,
        _baseline(workloads),
        round=1,
        branch="engine/x",
        budget_usd=0.01,
        brief=BRIEF,
    )

    assert trial.status is TrialStatus.failed
    assert trial.error == BROKEN.error
    assert trial.cost_usd == 0.01
    assert trial.tokens_used == 180  # 900 x 0.01 / 0.05
    assert trial.touched_paths == BROKEN.touched_paths


@pytest.mark.parametrize("budget", [-0.01, math.nan, math.inf, -math.inf])
def test_negative_or_non_finite_budget_is_refused(budget: float) -> None:
    """
    GIVEN a budget below 0, NaN or infinite
    WHEN the stub runner runs a hypothesis
    THEN a ValueError names budget_usd: NaN would let any cost through, and
         the node always passes a finite, clamped remainder
    """
    project = _project()
    workloads = _workloads(project)
    hypothesis = _hypothesis(project)
    runner = StubTrialRunner({hypothesis.id: FAST})

    with pytest.raises(ValueError, match="budget_usd"):
        runner.run(
            hypothesis,
            workloads,
            _baseline(workloads),
            round=1,
            branch="engine/x",
            budget_usd=budget,
            brief=BRIEF,
        )
