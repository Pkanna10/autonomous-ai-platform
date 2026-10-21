"""Tests for the typed ``EngineState`` serde (Step 2, unit U8, decision 27).

``dump_state`` turns a state into plain JSON values (what a JSONB column
stores) and ``load_state`` re-types them: enums, models, tuples, dates and
datetimes come back as the classes the nodes expect, so ``==`` holds on
every key, the reducer channels included. ``TypeAdapter(EngineState)`` fails
on Python 3.11 (``typing.TypedDict``), so the module builds one adapter per
key; CI runs these tests on 3.11 and they run on 3.13 locally.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

import pytest
from langgraph.types import Command

from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    ApprovalDecision,
    ApprovalRequest,
    Baseline,
    CandidateModule,
    ChangeClass,
    Claim,
    Combination,
    CombineSkip,
    Delivery,
    DeliveryKind,
    EngineEvent,
    EventLevel,
    Guardrail,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    JudgeOutcome,
    JudgeResult,
    Lesson,
    Measurement,
    Objective,
    Paper,
    Precondition,
    Project,
    ProjectUnderstanding,
    RunPhase,
    RunStats,
    Technique,
    Trial,
    TrialStatus,
    Verdict,
    VerdictOutcome,
    Violation,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.orchestrator.main import EngineGraph, run_config
from autonomous_ai_agents.orchestrator.nodes import NodeContext
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import (
    REDUCER_KEYS,
    EngineState,
    initial_state,
)


def _assert_json_only(value: object, where: str = "state") -> None:
    """Fail unless ``value`` is built from JSON types only (no tuples, enums...)."""
    if isinstance(value, dict):
        for key, item in value.items():
            assert type(key) is str, f"{where}: key {key!r} is not a str"
            _assert_json_only(item, f"{where}[{key!r}]")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_json_only(item, f"{where}[{index}]")
    else:
        assert type(value) in (str, int, float, bool, type(None)), (
            f"{where}: {type(value).__name__} is not a JSON type"
        )


def _through_json(state: EngineState) -> EngineState:
    """Dump, encode as strict JSON, decode, load: what a JSONB column does."""
    dumped = dump_state(state)
    _assert_json_only(dumped)
    return load_state(json.loads(json.dumps(dumped, allow_nan=False)))


def _assert_round_trip(state: EngineState) -> EngineState:
    loaded = _through_json(state)
    assert set(loaded) == set(state)
    for key in state:
        assert loaded[key] == state[key], key  # type: ignore[literal-required]
    assert loaded == state
    return loaded


# ---------------------------------------------------------------------------
# A state that uses every model, enum and Step 2 key
# ---------------------------------------------------------------------------


def _rich_state(
    project: Project,
    workload: Workload,
    objective: Objective,
    guardrails: Sequence[Guardrail],
) -> EngineState:
    state = initial_state(
        project, [workload], [objective], guardrails, run_id="serde-1", max_cost_usd=2.5
    )
    stats = RunStats.from_samples((1.80, 1.75, 1.85, 1.80, 1.80), "s")
    measurement = Measurement(
        workload_id=workload.id,
        metric=METRIC_WALL_TIME_S,
        stats=stats,
        samples=(1.80, 1.75, 1.85, 1.80, 1.80),
        output_fingerprint="a" * 64,
        hardware={
            "os": "Linux",
            "cpus": 8,
            "load": 0.25,
            "isolated": True,
            "gpu": None,
        },
    )
    tests_row = Measurement(
        workload_id=workload.id,
        metric=METRIC_TESTS_PASSED,
        stats=RunStats.from_samples((1.0,), "bool"),
        samples=(1.0,),
    )
    baseline = Baseline(
        commit="0" * 40,
        measurements=(measurement, tests_row),
        objectives=(objective,),
        guardrails=tuple(guardrails),
    )
    hotspot = Hotspot(
        project_id=project.id,
        workload_id=workload.id,
        file_path="dedupe_fixture/core.py",
        symbol="unique_in_order",
        line_start=3,
        line_end=9,
        self_time_s=0.31,
        total_time_s=0.39,
        share=0.95,
        calls=10_000,
        tags=("hot_loop", "list_membership"),
    )
    precondition = Precondition(description="pure function", check="ast:pure")
    technique = Technique(
        slug="set-membership",
        name="Set membership",
        summary="Use a set for membership tests",
        change_class=ChangeClass.efficiency,
        preconditions=(precondition,),
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
        references=("https://docs.python.org/3/library/stdtypes.html#set",),
    )
    paper = Paper(
        arxiv_id="2301.12345",
        title="Hashing for speed",
        authors=("A. Author",),
        published=date(2023, 1, 15),
        pdf_url="https://arxiv.org/pdf/2301.12345",
        claims=(
            Claim(
                paper_id="p-1",
                statement="hash sets beat lists",
                expected_gain=0.4,
                preconditions=(precondition,),
                confidence=0.8,
            ),
        ),
    )
    hypothesis = Hypothesis(
        project_id=project.id,
        hotspot_ids=(hotspot.id,),
        source=HypothesisSource.playbook,
        technique_id=technique.id,
        title="h1",
        rationale="set membership",
        change_class=ChangeClass.efficiency,
        expected_gain=0.5,
        provability=0.9,
        risk=0.1,
        score=0.405,
    )
    judge = JudgeResult(
        judge="speed",
        outcome=JudgeOutcome.passed,
        metric=METRIC_WALL_TIME_S,
        baseline=stats,
        trial=RunStats.from_samples((1.05, 1.02, 1.08, 1.05, 1.05), "s"),
        gain=0.4167,
        noise_floor=0.071,
        reason="faster beyond the noise floor",
        details={"workloads": 1, "ratio": 1.71},
    )
    violation = Violation(
        rule=ViolationRule.forbidden_file_mode,
        path="link.py",
        message="symlink",
    )
    trial = Trial(
        hypothesis_id=hypothesis.id,
        round=1,
        worktree_path="/tmp/wt",
        branch="engine/trial-serde-1-h1",
        base_commit="0" * 40,
        commit="1" * 40,
        diff="--- a\n+++ b\n",
        touched_paths=("dedupe_fixture/core.py",),
        violations=(violation,),
        status=TrialStatus.measured,
        measurements=(measurement,),
        judge_results=(judge,),
        started_at=datetime(2026, 10, 21, 12, 0, 0, 123456).astimezone(),
        finished_at=datetime(2026, 10, 21, 12, 0, 5).astimezone(),
        tokens_used=3400,
        cost_usd=0.12,
    )
    verdict = Verdict(
        trial_id=trial.id,
        hypothesis_id=hypothesis.id,
        outcome=VerdictOutcome.keep,
        change_class=ChangeClass.efficiency,
        judge_results=(judge,),
        violations=(violation,),
        gain=0.4167,
        summary="keep (+41.7%)",
        approved_by="praveen",
    )
    lesson = Lesson(
        project_id=project.id,
        verdict_id=verdict.id,
        hypothesis_id=hypothesis.id,
        technique_id=technique.id,
        context=("hot_loop",),
        outcome=VerdictOutcome.keep,
        gain=0.4167,
        text="list membership -> set: keep (+41.7%)",
        weight=1.5,
    )
    event = EngineEvent(
        run_id="serde-1",
        phase=RunPhase.trials,
        level=EventLevel.warning,
        message="budget_exhausted",
        data={"remaining": 0.01, "trials": 1, "stopped": True, "why": None},
    )
    state["phase"] = RunPhase.combine
    state["round"] = 2
    state["baseline"] = baseline
    state["hotspots"] = [hotspot]
    state["techniques"] = [technique]
    state["papers"] = [paper]
    state["hypotheses"] = [hypothesis]
    state["trials"] = [trial]
    state["round_trials"] = [trial]
    state["verdicts"] = [verdict]
    state["pending_approval_ids"] = [verdict.id]
    state["approval"] = ApprovalDecision(
        approved_verdict_ids=(verdict.id,), approver="praveen", note="ok"
    )
    state["kept_verdict_ids"] = [verdict.id]
    state["delivery"] = Delivery(
        project_id=project.id,
        kind=DeliveryKind.branch,
        branch="engine/run-serde-1",
        commit="2" * 40,
        verdict_ids=(verdict.id,),
        combined_diff="diff",
        report_markdown="# report",
    )
    state["lessons"] = [lesson]
    state["events"] = [event]
    state["error"] = "none yet"
    state["tokens_used"] = 3400
    state["cost_usd"] = 0.12
    state["base_commit"] = "0" * 40
    state["understanding"] = ProjectUnderstanding(
        language="python",
        summary="dedupe fixture",
        entrypoints=("dedupe_fixture/__main__.py",),
        workload_notes={workload.name: "prints three lines"},
        candidate_modules=(
            CandidateModule(path="dedupe_fixture/core.py", reason="hot"),
        ),
        served_by_model="claude-opus-5-5",
    )
    state["combination"] = Combination(
        base_commit="0" * 40,
        tip_commit="2" * 40,
        applied_trial_ids=(trial.id,),
        skipped=(CombineSkip(trial_id="t-2", reason="conflict", paths=("core.py",)),),
        judge_results=(judge,),
        holds=True,
        summary="h1 applied; holds",
    )
    state["budget_exhausted"] = True
    state["extra_protected"] = ["run.sh"]
    return state


@pytest.fixture
def rich_state(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> EngineState:
    """A state with every model, enum and Step 2 key set to a non-default."""
    return _rich_state(
        sample_project, sample_workload, sample_objective, sample_guardrails
    )


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


def test_the_initial_state_round_trips_through_json(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
) -> None:
    """
    GIVEN a fresh initial state
    WHEN it is dumped, encoded as strict JSON, decoded and loaded
    THEN every key is equal and the phase is a RunPhase again
    """
    state = initial_state(
        sample_project, [sample_workload], [sample_objective], sample_guardrails
    )

    loaded = _assert_round_trip(state)

    assert loaded["phase"] is RunPhase.connect
    assert isinstance(loaded["project"], Project)
    assert loaded is not state


def test_a_state_using_every_model_round_trips_on_every_key(
    rich_state: EngineState,
) -> None:
    """
    GIVEN a state that sets every key, the Step 2 keys and reducer channels too
    WHEN it round-trips through JSON
    THEN each key is equal and nested values come back typed
    """
    loaded = _assert_round_trip(rich_state)

    assert REDUCER_KEYS <= set(loaded)
    assert loaded["phase"] is RunPhase.combine
    (trial,) = loaded["trials"]
    assert type(trial) is Trial
    assert trial.status is TrialStatus.measured
    assert type(trial.measurements) is tuple
    assert trial.violations[0].rule is ViolationRule.forbidden_file_mode
    assert trial.started_at is not None and trial.started_at.tzinfo is not None
    assert loaded["verdicts"][0].outcome is VerdictOutcome.keep
    assert loaded["events"][0].level is EventLevel.warning
    assert type(loaded["papers"][0].published) is date
    hardware = trial.measurements[0].hardware
    assert [type(hardware[k]) for k in ("os", "cpus", "load", "isolated", "gpu")] == [
        str,
        int,
        float,
        bool,
        type(None),
    ]
    understanding = loaded["understanding"]
    assert isinstance(understanding, ProjectUnderstanding)
    assert understanding.candidate_modules[0].path == "dedupe_fixture/core.py"
    combination = loaded["combination"]
    assert isinstance(combination, Combination)
    assert combination.skipped[0].paths == ("core.py",)
    assert loaded["budget_exhausted"] is True
    assert loaded["max_cost_usd"] == 2.5


def test_the_dump_is_plain_json_values_only(rich_state: EngineState) -> None:
    """
    GIVEN a rich state
    WHEN it is dumped
    THEN the result holds only dict, list, str, int, float, bool and None,
         and a JSON encode/decode cycle returns it unchanged
    """
    dumped = dump_state(rich_state)

    _assert_json_only(dumped)
    assert json.loads(json.dumps(dumped, allow_nan=False)) == dumped
    assert dumped["phase"] == "combine"
    assert dumped["trials"][0]["measurements"][0]["samples"] == [
        1.80,
        1.75,
        1.85,
        1.80,
        1.80,
    ]


def test_a_full_gated_engine_run_round_trips(
    make_context: Callable[..., NodeContext],
    engine_graph: Callable[..., EngineGraph],
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: tuple[Guardrail, ...],
    h1_cache: Hypothesis,
    h2_protected: Hypothesis,
    h3_noise: Hypothesis,
    h4_behaviour: Hypothesis,
) -> None:
    """
    GIVEN the briefing run: H1-H4 in one round, paused for H4, H4 approved
    WHEN its paused and its final state round-trip through JSON
    THEN both come back equal on every key (4 trials, 4 verdicts, 4 lessons,
         the events, the approval and the delivery)
    """
    ctx = make_context(
        [h1_cache, h2_protected, h3_noise, h4_behaviour], max_hypotheses_per_round=4
    )
    graph = engine_graph(ctx)
    cfg = run_config("serde-full", 3)
    start = initial_state(
        sample_project,
        [sample_workload],
        [sample_objective],
        sample_guardrails,
        run_id="serde-full",
    )
    paused = graph.invoke(start, cfg, version="v2")
    (interrupt,) = paused.interrupts
    (item,) = ApprovalRequest.model_validate(interrupt.value).items
    decision = ApprovalDecision(approved_verdict_ids=(item.verdict_id,), approver="p")
    final = graph.invoke(
        Command(resume=decision.model_dump(mode="json")), cfg, version="v2"
    ).value

    _assert_round_trip(paused.value)
    loaded = _assert_round_trip(final)

    assert len(loaded["trials"]) == len(loaded["verdicts"]) == 4
    assert len(loaded["lessons"]) == 4
    assert loaded["events"]
    assert loaded["approval"] == decision
    assert loaded["delivery"] is not None
    assert loaded["phase"] is RunPhase.done


# ---------------------------------------------------------------------------
# Re-typing values that are only partly typed
# ---------------------------------------------------------------------------


def test_load_state_retypes_a_checkpoint_snapshot(rich_state: EngineState) -> None:
    """
    GIVEN a snapshot as PostgresSaver returns it: models typed, but the phase
          a plain str (a StrEnum is stored as its str value)
    WHEN it is loaded
    THEN the phase is a RunPhase again and every model is unchanged
    """
    snapshot: dict[str, Any] = dict(rich_state)
    snapshot["phase"] = "verdicts"

    loaded = load_state(snapshot)

    assert loaded["phase"] is RunPhase.verdicts
    assert loaded["trials"] == rich_state["trials"]
    assert loaded["project"] == rich_state["project"]


def test_dump_state_accepts_a_checkpoint_snapshot(rich_state: EngineState) -> None:
    """
    GIVEN the same snapshot shape (phase a plain str)
    WHEN it is dumped
    THEN the dump equals the dump of the fully typed state
    """
    snapshot: dict[str, Any] = dict(rich_state)
    snapshot["phase"] = "combine"

    assert dump_state(snapshot) == dump_state(rich_state)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def _without(data: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in keys}


def test_dump_state_refuses_missing_and_unknown_keys(rich_state: EngineState) -> None:
    """
    GIVEN a state missing a key, and one with an unknown key
    WHEN it is dumped
    THEN ValueError names the offending keys
    """
    missing = _without(rich_state, "round", "combination")
    extra: dict[str, Any] = {**rich_state, "secret": 1}

    with pytest.raises(ValueError, match=r"missing \['combination', 'round'\]"):
        dump_state(missing)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"unknown \['secret'\]"):
        dump_state(extra)  # type: ignore[arg-type]


def test_load_state_refuses_missing_and_unknown_keys(rich_state: EngineState) -> None:
    """
    GIVEN stored data missing a key, and data with an unknown key
    WHEN it is loaded
    THEN ValueError names the offending keys
    """
    dumped = dump_state(rich_state)

    with pytest.raises(ValueError, match=r"missing \['budget_exhausted'\]"):
        load_state(_without(dumped, "budget_exhausted"))
    with pytest.raises(ValueError, match=r"unknown \['extra'\]"):
        load_state({**dumped, "extra": []})


def test_load_state_names_the_key_whose_value_is_invalid(
    rich_state: EngineState,
) -> None:
    """
    GIVEN stored data whose phase is not a RunPhase value
    WHEN it is loaded
    THEN ValueError names the key
    """
    dumped = dump_state(rich_state)

    with pytest.raises(ValueError, match=r"state\['phase'\]"):
        load_state({**dumped, "phase": "teleport"})


def test_dump_state_names_the_key_whose_value_is_invalid(
    rich_state: EngineState,
) -> None:
    """
    GIVEN a state whose round is not an int and whose trials are not Trials
    WHEN it is dumped
    THEN ValueError names the key instead of storing what cannot load back
    """
    bad_round: dict[str, Any] = {**rich_state, "round": "two"}
    bad_trials: dict[str, Any] = {**rich_state, "trials": [{"id": "t1"}]}

    with pytest.raises(ValueError, match=r"state\['round'\]"):
        dump_state(bad_round)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=r"state\['trials'\]"):
        dump_state(bad_trials)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_dump_state_refuses_a_non_finite_float(
    rich_state: EngineState, value: float
) -> None:
    """
    GIVEN a state whose cost is not finite (JSONB stores neither inf nor NaN)
    WHEN it is dumped
    THEN ValueError names the key instead of producing unstorable JSON
    """
    rich_state["cost_usd"] = value

    with pytest.raises(ValueError, match=r"state\['cost_usd'\]"):
        dump_state(rich_state)
