"""Tests for the engine data models (Step 1, unit U1).

These tests define the data contract that anticheat, judges, nodes and the
003 migration build on. Every model is frozen, forbids unknown fields,
carries a uuid4 string id and tz-aware UTC timestamps, and round-trips
through JSON unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.common import models as m
from autonomous_ai_agents.common.models import (
    ENGINE_MODEL_CLASSES,
    MIN_RUNS,
    ApprovalDecision,
    ApprovalItem,
    ApprovalRequest,
    Baseline,
    ChangeClass,
    Claim,
    Delivery,
    DeliveryKind,
    Direction,
    EngineEvent,
    EngineModel,
    Guardrail,
    GuardrailKind,
    Hotspot,
    Hypothesis,
    HypothesisSource,
    HypothesisStatus,
    JudgeOutcome,
    JudgeResult,
    Lesson,
    Measurement,
    NoiseCheck,
    Objective,
    ObjectiveKind,
    Paper,
    Precondition,
    Project,
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
    new_id,
    utc_now,
)

# ---------------------------------------------------------------------------
# Builders (one valid instance of every model)
# ---------------------------------------------------------------------------

SAMPLES: tuple[float, ...] = (1.80, 1.75, 1.85, 1.80, 1.80)


def _project() -> Project:
    return Project(name="bridge", root_path="/home/dev/bridge")


def _workload(project: Project) -> Workload:
    return Workload(
        project_id=project.id,
        name="train",
        command=("python", "train_bridge.py", "--steps", "200"),
    )


def _objective(project: Project) -> Objective:
    return Objective(
        project_id=project.id,
        kind=ObjectiveKind.runtime,
        metric=m.METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        description="minimize seconds per training step",
    )


def _guardrails(project: Project) -> tuple[Guardrail, ...]:
    return (
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.tests_pass,
            description="existing tests must pass",
        ),
        Guardrail(
            project_id=project.id,
            kind=GuardrailKind.metric_bound,
            metric="val_loss",
            max_drop=0.01,
            direction=Direction.minimize,
            description="validation loss within 1%",
        ),
    )


def _measurement(
    workload: Workload,
    *,
    trial_id: str | None = None,
    samples: tuple[float, ...] = SAMPLES,
    fingerprint: str | None = "a" * 64,
) -> Measurement:
    return Measurement(
        workload_id=workload.id,
        trial_id=trial_id,
        metric=m.METRIC_WALL_TIME_S,
        stats=RunStats.from_samples(samples, unit="s"),
        samples=samples,
        output_fingerprint=fingerprint,
    )


def _all_instances() -> list[EngineModel]:
    project = _project()
    workload = _workload(project)
    objective = _objective(project)
    guardrails = _guardrails(project)
    baseline_measurement = _measurement(workload)
    baseline = Baseline(
        commit="abc1234",
        measurements=(baseline_measurement,),
        objectives=(objective,),
        guardrails=guardrails,
    )
    hotspot = Hotspot(
        project_id=project.id,
        workload_id=workload.id,
        file_path="src/bridge/encoder.py",
        symbol="Encoder.forward",
        line_start=10,
        line_end=40,
        self_time_s=0.70,
        total_time_s=0.76,
        share=0.42,
        calls=200,
        tags=("frozen_recompute",),
    )
    precondition = Precondition(
        description="a frozen module is recomputed every epoch",
        check="hotspot.tag:frozen_recompute",
    )
    technique = Technique(
        slug="cache-frozen-outputs",
        name="Cache frozen-module outputs",
        summary="Compute once, store on disk, reuse across epochs.",
        change_class=ChangeClass.efficiency,
        preconditions=(precondition,),
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
        references=("https://example.org/playbook/cache-frozen",),
    )
    paper_id = new_id()
    claim = Claim(
        paper_id=paper_id,
        statement="Pruning half the visual tokens after layer 2 keeps accuracy within 1%.",
        expected_gain=0.2,
        preconditions=(precondition,),
        confidence=0.8,
    )
    paper = Paper(
        id=paper_id,
        arxiv_id="2403.06764",
        title="An Image is Worth 1/2 Tokens After Layer 2",
        authors=("L. Chen", "H. Zhao"),
        abstract="Visual tokens are redundant in deep layers.",
        published=date(2024, 3, 11),
        pdf_url="https://arxiv.org/pdf/2403.06764",
        claims=(claim,),
    )
    hypothesis = Hypothesis(
        project_id=project.id,
        hotspot_ids=(hotspot.id,),
        source=HypothesisSource.playbook,
        technique_id=technique.id,
        title="Cache CLIP embeddings to disk",
        rationale="Encoder is frozen; 42% of step time recomputes it.",
        change_class=ChangeClass.efficiency,
        expected_gain=0.4,
        provability=0.9,
        risk=0.1,
    )
    trial_measurement = _measurement(
        workload, trial_id="pending", samples=(1.05, 1.02, 1.08, 1.05, 1.05)
    )
    judge_result = JudgeResult(
        judge="speed",
        outcome=JudgeOutcome.passed,
        metric=m.METRIC_WALL_TIME_S,
        baseline=baseline_measurement.stats,
        trial=trial_measurement.stats,
        gain=0.417,
        noise_floor=0.044,
        reason="gain 41.7% exceeds noise floor 4.4%",
    )
    violation = Violation(
        rule=ViolationRule.protected_path,
        path="tests/test_cache.py",
        pattern="**/tests/**",
        message="trial modified a protected path",
    )
    trial = Trial(
        hypothesis_id=hypothesis.id,
        round=1,
        branch="engine/run-1/h1",
        touched_paths=("src/bridge/encoder.py",),
        status=TrialStatus.measured,
        measurements=(trial_measurement,),
        judge_results=(judge_result,),
    )
    verdict = Verdict(
        trial_id=trial.id,
        hypothesis_id=hypothesis.id,
        outcome=VerdictOutcome.keep,
        change_class=ChangeClass.efficiency,
        judge_results=(judge_result,),
        violations=(),
        gain=0.417,
        summary="kept: 41.7% faster, tests pass",
    )
    delivery = Delivery(
        project_id=project.id,
        kind=DeliveryKind.branch,
        branch="engine/run-1",
        verdict_ids=(verdict.id,),
        combined_diff="",
        report_markdown="# Report",
    )
    lesson = Lesson(
        project_id=project.id,
        verdict_id=verdict.id,
        hypothesis_id=hypothesis.id,
        technique_id=technique.id,
        context=("frozen_recompute", "python"),
        outcome=VerdictOutcome.keep,
        gain=0.417,
        text="frozen_recompute -> cache-frozen-outputs: keep (+41.7%)",
    )
    item = ApprovalItem(
        verdict_id=verdict.id,
        title=hypothesis.title,
        change_class=ChangeClass.behaviour,
        gain=0.17,
        summary="bf16 autocast changes numerics",
    )
    request = ApprovalRequest(
        run_id="run-1", items=(item,), message="1 change needs approval"
    )
    decision = ApprovalDecision(
        approved_verdict_ids=(verdict.id,),
        rejected_verdict_ids=(),
        approver="praveen",
    )
    event = EngineEvent(
        run_id="run-1",
        phase=RunPhase.baseline,
        message="5 runs -> 1.80 s/step +- 0.04",
        data={"n": 5, "mean": 1.8},
    )
    noise = NoiseCheck(
        gain_abs=0.75, gain_rel=0.417, floor_abs=0.08, floor_rel=0.044, passed=True
    )
    return [
        project,
        workload,
        objective,
        guardrails[0],
        guardrails[1],
        baseline_measurement.stats,
        baseline_measurement,
        baseline,
        hotspot,
        precondition,
        technique,
        claim,
        paper,
        hypothesis,
        judge_result,
        violation,
        trial,
        verdict,
        delivery,
        lesson,
        item,
        request,
        decision,
        event,
        noise,
    ]


# ---------------------------------------------------------------------------
# Conventions shared by every model
# ---------------------------------------------------------------------------


def test_ids_are_unique_uuid4_strings() -> None:
    """
    GIVEN two freshly built models
    WHEN their ids are inspected
    THEN they are distinct uuid4 strings
    """
    first, second = _project(), _project()

    assert first.id != second.id
    assert uuid.UUID(first.id).version == 4
    assert uuid.UUID(new_id()).version == 4


def test_timestamps_are_timezone_aware_utc() -> None:
    """
    GIVEN a freshly built model with a default timestamp
    WHEN the timestamp is inspected
    THEN it is tz-aware and in UTC
    """
    project = _project()

    assert project.created_at.tzinfo is UTC
    assert utc_now().tzinfo is UTC
    assert isinstance(project.created_at, datetime)


def test_models_are_frozen() -> None:
    """
    GIVEN a model instance
    WHEN a field is assigned
    THEN pydantic raises a ValidationError (frozen)
    """
    project = _project()

    with pytest.raises(ValidationError):
        project.name = "other"  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    """
    GIVEN an unknown keyword
    WHEN constructing a model
    THEN validation fails (extra = forbid)
    """
    with pytest.raises(ValidationError):
        Project(name="x", root_path="/tmp/x", colour="blue")  # type: ignore[call-arg]


def test_model_copy_with_update_produces_new_instance() -> None:
    """
    GIVEN a frozen model
    WHEN model_copy(update=...) is used
    THEN a new instance carries the change and the original is untouched
    """
    hypothesis = _all_instances()[13]
    assert isinstance(hypothesis, Hypothesis)

    updated = hypothesis.model_copy(update={"status": HypothesisStatus.kept})

    assert updated.status is HypothesisStatus.kept
    assert hypothesis.status is HypothesisStatus.proposed


@pytest.mark.parametrize("instance", _all_instances(), ids=lambda i: type(i).__name__)
def test_every_model_round_trips_through_json(instance: EngineModel) -> None:
    """
    GIVEN one valid instance of each model
    WHEN it is dumped to JSON and validated back
    THEN the result equals the original
    """
    restored = type(instance).model_validate_json(instance.model_dump_json())

    assert restored == instance


def test_engine_model_classes_lists_every_model() -> None:
    """
    GIVEN the ENGINE_MODEL_CLASSES allowlist used by the checkpointer
    WHEN compared with every EngineModel subclass defined in the module
    THEN they match exactly, so the list cannot drift
    """

    def subclasses(cls: type[EngineModel]) -> set[type[EngineModel]]:
        found: set[type[EngineModel]] = set()
        for sub in cls.__subclasses__():
            found.add(sub)
            found |= subclasses(sub)
        return found

    expected = {c for c in subclasses(EngineModel) if c.__module__ == m.__name__}

    assert set(ENGINE_MODEL_CLASSES) == expected
    assert len(ENGINE_MODEL_CLASSES) == len(set(ENGINE_MODEL_CLASSES))
    assert EngineModel not in ENGINE_MODEL_CLASSES


@pytest.mark.parametrize(
    "enum_cls",
    [
        RunPhase,
        ObjectiveKind,
        Direction,
        GuardrailKind,
        ChangeClass,
        HypothesisSource,
        HypothesisStatus,
        TrialStatus,
        JudgeOutcome,
        VerdictOutcome,
        ViolationRule,
        DeliveryKind,
        m.EventLevel,
    ],
)
def test_enums_serialize_as_lowercase_strings(enum_cls: type[StrEnum]) -> None:
    """
    GIVEN an engine enum
    WHEN its members are inspected
    THEN it is a StrEnum whose values are lowercase identifiers equal to their names
    """
    assert issubclass(enum_cls, StrEnum)
    for member in enum_cls:
        assert member.value == member.name
        assert member.value == member.value.lower()


def test_verdict_outcome_values_match_sql_check_list() -> None:
    """
    GIVEN the VerdictOutcome enum
    WHEN compared with the values the 003 migration constrains
    THEN they match verbatim
    """
    assert {v.value for v in VerdictOutcome} == {
        "keep",
        "reject",
        "inconclusive",
        "needs_approval",
    }
    assert VerdictOutcome("keep") is VerdictOutcome.keep


def test_violation_rules_cover_measurement_completeness() -> None:
    """
    GIVEN the ViolationRule enum
    WHEN the measurement-completeness rules are looked up by value
    THEN missing_measurement and duplicate_measurement exist next to the others
    """
    assert ViolationRule("missing_measurement") is ViolationRule.missing_measurement
    assert ViolationRule("duplicate_measurement") is ViolationRule.duplicate_measurement
    assert {rule.value for rule in ViolationRule} == {
        "protected_path",
        "path_traversal",
        "too_few_runs",
        "fingerprint_mismatch",
        "missing_fingerprint",
        "missing_measurement",
        "duplicate_measurement",
    }


def test_approval_request_error_defaults_to_none_and_round_trips() -> None:
    """
    GIVEN an ApprovalRequest without and with an error (a rejected resume payload)
    WHEN each is dumped to JSON and validated back
    THEN the error defaults to None and survives the round trip unchanged
    """
    plain = ApprovalRequest(run_id="run-1", message="1 change needs approval")
    flagged = plain.model_copy(
        update={"error": "invalid approval decision: approver is required"}
    )

    assert plain.error is None
    assert ApprovalRequest.model_validate_json(plain.model_dump_json()) == plain
    restored = ApprovalRequest.model_validate_json(flagged.model_dump_json())
    assert restored == flagged
    assert restored.error == "invalid approval decision: approver is required"
    assert ApprovalRequest.model_validate(flagged.model_dump(mode="json")) == flagged


# ---------------------------------------------------------------------------
# Validators and bounds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_path", ["relative/path", "./here", "/home/dev/../etc"])
def test_project_root_path_must_be_absolute_without_parent_segments(
    bad_path: str,
) -> None:
    """
    GIVEN a relative path or one containing '..'
    WHEN constructing a Project
    THEN validation fails (path traversal defence)
    """
    with pytest.raises(ValidationError):
        Project(name="x", root_path=bad_path)


def test_project_defaults() -> None:
    """
    GIVEN only the required Project fields
    WHEN constructed
    THEN default_branch is 'main', language is 'python' and hardware is empty
    """
    project = _project()

    assert project.default_branch == "main"
    assert project.language == "python"
    assert project.hardware == {}


def test_workload_command_is_argv_not_a_shell_string() -> None:
    """
    GIVEN a command given as a single shell string
    WHEN constructing a Workload
    THEN validation fails (argv tuple required; never passed to a shell)
    """
    project = _project()

    with pytest.raises(ValidationError):
        Workload(project_id=project.id, name="t", command="python train.py")
    with pytest.raises(ValidationError):
        Workload(project_id=project.id, name="t", command=())


@pytest.mark.parametrize(
    ("field", "value"),
    [("runs", MIN_RUNS - 1), ("timeout_s", 0.0), ("warmup_runs", -1)],
)
def test_workload_numeric_bounds(field: str, value: float) -> None:
    """
    GIVEN an out-of-range numeric field
    WHEN constructing a Workload
    THEN validation fails
    """
    project = _project()

    with pytest.raises(ValidationError):
        Workload(project_id=project.id, name="t", command=("python",), **{field: value})


def test_workload_defaults_use_min_runs() -> None:
    """
    GIVEN only the required Workload fields
    WHEN constructed
    THEN runs defaults to MIN_RUNS and warmup_runs to 1
    """
    workload = _workload(_project())

    assert workload.runs == MIN_RUNS
    assert workload.warmup_runs == 1
    assert workload.timeout_s == 600.0


def test_guardrail_metric_bound_requires_metric_max_drop_and_direction() -> None:
    """
    GIVEN a metric_bound guardrail missing its metric fields
    WHEN constructed
    THEN validation fails, while the other kinds do not need them
    """
    project = _project()

    with pytest.raises(ValidationError):
        Guardrail(
            project_id=project.id, kind=GuardrailKind.metric_bound, description="x"
        )
    assert Guardrail(
        project_id=project.id,
        kind=GuardrailKind.output_equivalence,
        description="same output",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("provability", 1.5), ("risk", -0.1), ("expected_gain", -1.0)],
)
def test_hypothesis_scores_are_bounded(field: str, value: float) -> None:
    """
    GIVEN an out-of-range ranking input
    WHEN constructing a Hypothesis
    THEN validation fails
    """
    project = _project()
    kwargs: dict[str, object] = {
        "project_id": project.id,
        "hotspot_ids": (),
        "source": HypothesisSource.novel,
        "title": "t",
        "rationale": "r",
        "change_class": ChangeClass.novel,
        "expected_gain": 0.1,
        "provability": 0.5,
        "risk": 0.5,
    }
    kwargs[field] = value

    with pytest.raises(ValidationError):
        Hypothesis(**kwargs)


def test_hypothesis_and_trial_defaults() -> None:
    """
    GIVEN the minimum fields
    WHEN constructing a Hypothesis and a Trial
    THEN status defaults are 'proposed' and 'pending' and score is 0
    """
    instances = _all_instances()
    hypothesis = instances[13]
    assert isinstance(hypothesis, Hypothesis)
    trial = Trial(hypothesis_id=hypothesis.id, round=1)

    assert hypothesis.status is HypothesisStatus.proposed
    assert hypothesis.score == 0.0
    assert trial.status is TrialStatus.pending
    assert trial.touched_paths == ()
    assert trial.cost_usd == 0.0


def test_hotspot_share_is_a_fraction() -> None:
    """
    GIVEN a share above 1
    WHEN constructing a Hotspot
    THEN validation fails
    """
    project = _project()
    workload = _workload(project)

    with pytest.raises(ValidationError):
        Hotspot(
            project_id=project.id,
            workload_id=workload.id,
            file_path="a.py",
            symbol="f",
            self_time_s=1.0,
            total_time_s=1.0,
            share=1.5,
        )


def test_paper_pdf_url_must_be_https() -> None:
    """
    GIVEN a plain-http PDF URL
    WHEN constructing a Paper
    THEN validation fails (SSRF / downgrade defence), while https and None pass
    """
    with pytest.raises(ValidationError):
        Paper(title="t", authors=(), abstract="a", pdf_url="http://arxiv.org/pdf/1")
    assert Paper(title="t", authors=(), abstract="a", pdf_url="https://arxiv.org/pdf/1")
    assert Paper(title="t", authors=(), abstract="a").pdf_url is None


def test_scalar_dicts_reject_nested_values() -> None:
    """
    GIVEN a nested dict for a scalar-only mapping field
    WHEN constructing the model
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        Project(name="x", root_path="/x", hardware={"gpu": {"name": "M4"}})


# ---------------------------------------------------------------------------
# RunStats and Measurement
# ---------------------------------------------------------------------------


def test_run_stats_from_samples_computes_sample_statistics() -> None:
    """
    GIVEN five timing samples
    WHEN RunStats.from_samples is called
    THEN n, mean, sample stdev, min, max and unit are filled
    """
    stats = RunStats.from_samples(SAMPLES, unit="s")

    assert stats.n == 5
    assert stats.mean == pytest.approx(1.80)
    assert stats.stdev == pytest.approx(0.035355, abs=1e-5)
    assert stats.min == pytest.approx(1.75)
    assert stats.max == pytest.approx(1.85)
    assert stats.unit == "s"


def test_run_stats_single_sample_has_zero_stdev() -> None:
    """
    GIVEN a single sample
    WHEN RunStats.from_samples is called
    THEN stdev is 0.0 and n is 1
    """
    stats = RunStats.from_samples((2.0,), unit="s")

    assert stats.n == 1
    assert stats.stdev == 0.0


def test_run_stats_requires_at_least_one_sample() -> None:
    """
    GIVEN no samples
    WHEN RunStats.from_samples is called
    THEN a ValueError is raised
    """
    with pytest.raises(ValueError, match="at least one sample"):
        RunStats.from_samples((), unit="s")


def test_measurement_samples_must_match_stats_n() -> None:
    """
    GIVEN samples whose length differs from stats.n
    WHEN constructing a Measurement
    THEN validation fails
    """
    workload = _workload(_project())

    with pytest.raises(ValidationError):
        Measurement(
            workload_id=workload.id,
            metric=m.METRIC_WALL_TIME_S,
            stats=RunStats.from_samples(SAMPLES, unit="s"),
            samples=SAMPLES[:3],
        )


def test_measurement_fingerprint_is_64_hex_chars_or_none() -> None:
    """
    GIVEN a malformed fingerprint
    WHEN constructing a Measurement
    THEN validation fails, while a sha256 hex digest or None passes
    """
    workload = _workload(_project())

    with pytest.raises(ValidationError):
        _measurement(workload, fingerprint="not-a-digest")
    assert _measurement(workload, fingerprint=None).output_fingerprint is None
    assert _measurement(workload).output_fingerprint == "a" * 64


# ---------------------------------------------------------------------------
# Review fixes: enum allowlist, approval overlap, path validators
# ---------------------------------------------------------------------------


def test_engine_enum_classes_and_serde_allowlist_list_every_enum() -> None:
    """
    GIVEN the enum allowlist and the combined serde allowlist
    WHEN compared with every StrEnum defined in the models module
    THEN they match exactly, so no enum can be left out of checkpoint allowlists
    """
    expected = {
        obj
        for obj in vars(m).values()
        if isinstance(obj, type)
        and issubclass(obj, StrEnum)
        and obj is not StrEnum
        and obj.__module__ == m.__name__
    }

    assert set(m.ENGINE_ENUM_CLASSES) == expected
    assert set(m.ENGINE_SERDE_ALLOWLIST) == set(ENGINE_MODEL_CLASSES) | expected
    assert len(m.ENGINE_SERDE_ALLOWLIST) == len(set(m.ENGINE_SERDE_ALLOWLIST))


def test_serde_allowlist_round_trips_models_and_enums(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    GIVEN the checkpoint serializer built with the engine allowlist
    WHEN a payload holding enums and a model is dumped and loaded
    THEN enums come back as enum members, the model as itself, with no
         "blocked deserialization" warning
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer(allowed_msgpack_modules=m.ENGINE_SERDE_ALLOWLIST)
    payload = {
        "phase": RunPhase.baseline,
        "outcome": VerdictOutcome.keep,
        "project": _project(),
    }

    with caplog.at_level(logging.WARNING):
        restored = serde.loads_typed(serde.dumps_typed(payload))

    assert restored["phase"] is RunPhase.baseline
    assert restored["outcome"] is VerdictOutcome.keep
    assert isinstance(restored["project"], Project)
    assert restored["project"] == payload["project"]
    blocked = [
        r
        for r in caplog.records
        if "locked" in r.getMessage() or "unregistered" in r.getMessage()
    ]
    assert blocked == []


def test_approval_decision_ids_must_be_disjoint() -> None:
    """
    GIVEN a verdict id listed as both approved and rejected
    WHEN constructing an ApprovalDecision
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        ApprovalDecision(
            approved_verdict_ids=("v1",), rejected_verdict_ids=("v1",), approver="p"
        )


@pytest.mark.parametrize("bad", ["../escape", "/abs/path", "C:\\x", "~/home"])
def test_workload_working_dir_and_hotspot_path_stay_inside_project(bad: str) -> None:
    """
    GIVEN a path that escapes the project root
    WHEN used as a workload working_dir or a hotspot file_path
    THEN validation fails, while relative paths are normalised
    """
    project = _project()

    with pytest.raises(ValidationError):
        Workload(project_id=project.id, name="t", command=("python",), working_dir=bad)
    with pytest.raises(ValidationError):
        Hotspot(
            project_id=project.id,
            workload_id="w",
            file_path=bad,
            symbol="f",
            self_time_s=0.0,
            total_time_s=0.0,
            share=0.0,
        )
    assert (
        Workload(
            project_id=project.id, name="t", command=("python",), working_dir="./sub"
        ).working_dir
        == "sub"
    )
    assert _workload(project).working_dir == "."
