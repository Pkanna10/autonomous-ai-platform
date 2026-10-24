"""Tests for the engine data models (Step 1, unit U1).

These tests define the data contract that anticheat, judges, nodes and the
003 migration build on. Every model is frozen, forbids unknown fields,
carries a uuid4 string id and tz-aware UTC timestamps, and round-trips
through JSON unchanged.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

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
    CandidateModule,
    ChangeClass,
    Claim,
    Combination,
    CombineSkip,
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
    LongContextPrice,
    Measurement,
    ModelPrice,
    NoiseCheck,
    Objective,
    ObjectiveKind,
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
    price = ModelPrice(input=4.0, output=20.0, cache_write=5.0, cache_read=0.2)
    long_tier = LongContextPrice(
        threshold_tokens=100_000,
        input=0.5,
        output=2.5,
        cache_write=0.625,
        cache_read=0.05,
    )
    long_price = ModelPrice(
        input=0.1,
        output=0.5,
        cache_write=0.125,
        cache_read=0.01,
        long_context=long_tier,
    )
    candidate = CandidateModule(path="src/bridge/encoder.py", reason="hot loop")
    understanding = ProjectUnderstanding(
        language="python",
        summary="Trains a vision-language bridge.",
        entrypoints=("train_bridge.py",),
        workload_notes={workload.id: "200 training steps"},
        candidate_modules=(candidate,),
        served_by_model="claude-opus-5-5",
    )
    skip = CombineSkip(
        trial_id=trial.id, reason="conflict", paths=("src/bridge/encoder.py",)
    )
    combination = Combination(
        base_commit="a" * 40,
        tip_commit="b" * 40,
        applied_trial_ids=(trial.id,),
        skipped=(skip,),
        judge_results=(judge_result,),
        holds=True,
        fallback_trial_id=None,
        summary="greedy: 1 applied, 1 skipped; holds",
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
        price,
        candidate,
        understanding,
        skip,
        combination,
        long_tier,
        long_price,
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
        # Step 2 capture rules (spec decision 13)
        "forbidden_file_mode",
        "forbidden_file",
        "git_metadata",
        "unrecorded_write",
        "process_spawn",
        # Wave 2b: a new top-level module that shadows the stdlib or the runner
        "module_shadow",
    }
    assert ViolationRule("module_shadow").name == "module_shadow"


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


def test_project_root_path_is_one_spelling_per_directory(tmp_path: Path) -> None:
    """
    GIVEN one repository spelled with a trailing slash, a doubled slash, a
        '.' segment, or through a symlink
    WHEN constructing Projects with those root paths
    THEN every root_path is the same canonical path (one project per repo
        root: the persistence clash check compares this string)
    """
    repo = tmp_path.resolve() / "repo"
    repo.mkdir()
    (tmp_path / "alias").symlink_to(repo)
    spellings = [
        f"{repo}/",
        f"{repo.parent}//repo",
        f"{repo}/.",
        str(tmp_path / "alias"),
    ]

    roots = {Project(name="x", root_path=spelled).root_path for spelled in spellings}

    assert roots == {str(repo)}
    assert Project(name="x", root_path="/srv/missing/").root_path == "/srv/missing"
    assert Project(name="x", root_path="/srv/a\0b//").root_path == "/srv/a\0b"


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


@pytest.mark.parametrize("path", ["", ".", "./"])
def test_hotspot_file_path_must_name_a_file(path: str) -> None:
    """
    GIVEN a hotspot file path that normalises to the project root
    WHEN constructing a Hotspot
    THEN validation fails: a hotspot points at a file, not the whole project
    """
    project = _project()
    workload = _workload(project)

    with pytest.raises(ValidationError, match="must name a file"):
        Hotspot(
            project_id=project.id,
            workload_id=workload.id,
            file_path=path,
            symbol="f",
            self_time_s=1.0,
            total_time_s=1.0,
            share=0.5,
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


# ---------------------------------------------------------------------------
# Step 2 (U1): finite numbers, new fields, new models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_engine_models_refuse_non_finite_numbers(bad: float) -> None:
    """
    GIVEN an infinite or NaN float (JSONB cannot store either)
    WHEN it is used for a measurement sample, a cost or a scalar-dict value
    THEN validation fails on every model, because EngineModel forbids inf/nan
    """
    workload = _workload(_project())
    stats = RunStats.from_samples(SAMPLES, unit="s")

    with pytest.raises(ValidationError):
        Measurement(
            workload_id=workload.id,
            metric=m.METRIC_WALL_TIME_S,
            stats=stats,
            samples=(1.0, 1.0, bad, 1.0, 1.0),
        )
    with pytest.raises(ValidationError):
        RunStats(n=1, mean=bad, stdev=0.0, min=1.0, max=1.0, unit="s")
    with pytest.raises(ValidationError):
        Trial(hypothesis_id="h", round=1, cost_usd=bad)
    with pytest.raises(ValidationError):
        Project(name="x", root_path="/x", hardware={"ghz": bad})
    assert EngineModel.model_config.get("allow_inf_nan") is False


def test_project_test_command_is_optional_argv() -> None:
    """
    GIVEN a project with and without a test command
    WHEN constructed
    THEN it defaults to None and keeps a non-empty argv tuple, while an empty
         tuple or a single shell string is refused
    """
    command = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")

    assert _project().test_command is None
    project = Project(name="x", root_path="/x", test_command=command)
    assert project.test_command == command
    assert Project.model_validate_json(project.model_dump_json()) == project
    with pytest.raises(ValidationError):
        Project(name="x", root_path="/x", test_command=())
    with pytest.raises(ValidationError):
        Project(name="x", root_path="/x", test_command="python -m pytest")


def test_workload_output_file_is_normalised_and_contained() -> None:
    """
    GIVEN a workload output file
    WHEN constructed
    THEN it defaults to None, is normalised like working_dir, and a path that
         escapes the project or names the project root itself is refused
    """
    project = _project()

    assert _workload(project).output_file is None
    workload = Workload(
        project_id=project.id,
        name="t",
        command=("python",),
        output_file="./out//result.json",
    )
    assert workload.output_file == "out/result.json"
    for bad in ("../result.json", "/tmp/result.json", "~/result.json"):
        with pytest.raises(ValidationError):
            Workload(
                project_id=project.id, name="t", command=("python",), output_file=bad
            )
    for root in ("", ".", "./", ".//."):
        with pytest.raises(ValidationError, match="output_file must name a file"):
            Workload(
                project_id=project.id, name="t", command=("python",), output_file=root
            )


def test_trial_and_delivery_record_commits_and_capture_violations() -> None:
    """
    GIVEN the runner's new trial fields and the delivery commit
    WHEN a trial and a delivery are built with and without them
    THEN commit defaults to None, violations to (), and both round-trip
    """
    violation = Violation(
        rule=ViolationRule.forbidden_file_mode,
        path="src/link.py",
        message="symlink added",
    )
    plain = Trial(hypothesis_id="h", round=1)
    trial = Trial(
        hypothesis_id="h",
        round=1,
        commit="c" * 40,
        status=TrialStatus.failed,
        violations=(violation,),
    )
    delivery = Delivery(project_id="p", kind=DeliveryKind.branch, report_markdown="# r")

    assert plain.commit is None
    assert plain.violations == ()
    assert trial.violations == (violation,)
    assert Trial.model_validate_json(trial.model_dump_json()) == trial
    assert delivery.commit is None
    assert delivery.model_copy(update={"commit": "d" * 40}).commit == "d" * 40


def test_new_capture_rules_exist_by_value() -> None:
    """
    GIVEN the Step 2 capture rules
    WHEN looked up by value
    THEN each is a ViolationRule member whose value equals its name
    """
    for value in (
        "forbidden_file_mode",
        "forbidden_file",
        "git_metadata",
        "unrecorded_write",
        "process_spawn",
    ):
        rule = ViolationRule(value)
        assert rule.name == value


def test_model_price_rates_are_non_negative() -> None:
    """
    GIVEN per-MTok prices
    WHEN a ModelPrice is built
    THEN all four rates are kept, and a negative rate or an unknown field fails
    """
    price = ModelPrice(input=0.1, output=0.5, cache_write=0.125, cache_read=0.1)

    assert (price.input, price.output, price.cache_write, price.cache_read) == (
        0.1,
        0.5,
        0.125,
        0.1,
    )
    assert ModelPrice(input=0, output=0, cache_write=0, cache_read=0).input == 0
    for field in ("input", "output", "cache_write", "cache_read"):
        rates: dict[str, float] = {
            "input": 1.0,
            "output": 1.0,
            "cache_write": 1.0,
            "cache_read": 1.0,
        }
        rates[field] = -0.01
        with pytest.raises(ValidationError):
            ModelPrice(**rates)
    with pytest.raises(ValidationError):
        ModelPrice.model_validate(
            {
                "input": 1,
                "output": 1,
                "cache_write": 1,
                "cache_read": 1,
                "cache_write_1h": 2,
            }
        )


LONG_RATES: dict[str, object] = {
    "threshold_tokens": 100_000,
    "input": 0.5,
    "output": 2.5,
    "cache_write": 0.625,
    "cache_read": 0.05,
}


def test_a_model_price_has_no_long_context_tier_by_default() -> None:
    """
    GIVEN a ModelPrice built from the four flat rates
    WHEN its long_context is read
    THEN it is None: every prompt length bills the flat rates
    """
    price = ModelPrice(input=4.0, output=20.0, cache_write=5.0, cache_read=0.2)

    assert price.long_context is None


def test_a_long_context_tier_keeps_its_threshold_and_rates() -> None:
    """
    GIVEN the Haiku 5.5 long-context tier
    WHEN it is built and nested in a ModelPrice, also from JSON-like data
    THEN the threshold and the four rates are kept
    """
    tier = LongContextPrice.model_validate(LONG_RATES)
    price = ModelPrice.model_validate(
        {
            "input": 0.1,
            "output": 0.5,
            "cache_write": 0.125,
            "cache_read": 0.01,
            "long_context": LONG_RATES,
        }
    )

    assert price.long_context == tier
    assert (tier.threshold_tokens, tier.input, tier.output) == (100_000, 0.5, 2.5)
    assert (tier.cache_write, tier.cache_read) == (0.625, 0.05)


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("threshold_tokens", -1),
        ("threshold_tokens", True),
        ("threshold_tokens", 1.5),
        ("threshold_tokens", "100000"),
        ("input", -0.01),
        ("output", -0.01),
        ("cache_write", -0.01),
        ("cache_read", -0.01),
        ("input", math.inf),
    ],
)
def test_a_long_context_tier_refuses_a_bad_value(field: str, bad: object) -> None:
    """
    GIVEN a long-context tier with a negative, boolean, fractional or textual
          threshold, or a negative or infinite rate
    WHEN it is validated
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        LongContextPrice.model_validate({**LONG_RATES, field: bad})


def test_a_long_context_tier_refuses_unknown_and_missing_fields() -> None:
    """
    GIVEN a long-context tier with an extra field, or without its threshold
    WHEN it is validated
    THEN validation fails (extra = forbid, every field required)
    """
    with pytest.raises(ValidationError):
        LongContextPrice.model_validate({**LONG_RATES, "cache_write_1h": 1.0})
    without = {key: value for key, value in LONG_RATES.items() if key != "input"}
    with pytest.raises(ValidationError):
        LongContextPrice.model_validate(without)


def test_candidate_module_path_stays_inside_the_project() -> None:
    """
    GIVEN a candidate module suggested by the understand node
    WHEN its path is validated
    THEN it is normalised, and an escaping path or the project root itself is
         refused
    """
    assert CandidateModule(path="./src//core.py", reason="r").path == "src/core.py"
    for bad in ("../core.py", "/etc/passwd", "C:\\x.py"):
        with pytest.raises(ValidationError):
            CandidateModule(path=bad, reason="r")
    for root in ("", ".", "./", ".//."):
        with pytest.raises(ValidationError, match="path must name a file"):
            CandidateModule(path=root, reason="r")


def _understanding(**overrides: object) -> ProjectUnderstanding:
    fields: dict[str, object] = {
        "language": "python",
        "summary": "s",
        "entrypoints": (),
        "workload_notes": {},
        "candidate_modules": (),
        "served_by_model": "claude-opus-5-5",
    }
    fields.update(overrides)
    return ProjectUnderstanding.model_validate(fields)


def test_project_understanding_caps_summary_and_candidates() -> None:
    """
    GIVEN the understand node's structured answer
    WHEN the summary or the candidate list is at and past its cap
    THEN 1500 characters and 10 candidates pass, 1501 and 11 fail
    """
    candidate = CandidateModule(path="src/a.py", reason="r")

    assert len(_understanding(summary="x" * 1500).summary) == 1500
    ten = _understanding(candidate_modules=(candidate,) * 10).candidate_modules
    assert len(ten) == 10
    with pytest.raises(ValidationError):
        _understanding(summary="x" * 1501)
    with pytest.raises(ValidationError):
        _understanding(candidate_modules=(candidate,) * 11)


def test_project_understanding_workload_notes_are_strings() -> None:
    """
    GIVEN workload notes keyed by workload id
    WHEN a value is not a string
    THEN validation fails (no coercion), while string notes are kept
    """
    assert _understanding(workload_notes={"w1": "note"}).workload_notes == {
        "w1": "note"
    }
    with pytest.raises(ValidationError):
        _understanding(workload_notes={"w1": 3})


def test_combination_defaults_and_skip_paths() -> None:
    """
    GIVEN a combination with only the required fields
    WHEN constructed
    THEN the optional fields default to None or empty tuples, and a skip
         records its conflict paths
    """
    combination = Combination(base_commit="a" * 40, holds=False, summary="none held")
    skip = CombineSkip(trial_id="t1", reason="conflict")

    assert combination.tip_commit is None
    assert combination.applied_trial_ids == ()
    assert combination.skipped == ()
    assert combination.judge_results == ()
    assert combination.fallback_trial_id is None
    assert skip.paths == ()


def test_checkpoint_serde_round_trips_the_new_state_models() -> None:
    """
    GIVEN the checkpoint serializer built with the engine allowlist
    WHEN a ProjectUnderstanding and a Combination are dumped and loaded
    THEN both come back as themselves, nested models included
    """
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    serde = JsonPlusSerializer(allowed_msgpack_modules=m.ENGINE_SERDE_ALLOWLIST)
    instances = _all_instances()
    understanding = next(i for i in instances if isinstance(i, ProjectUnderstanding))
    combination = next(i for i in instances if isinstance(i, Combination))
    payload = {"understanding": understanding, "combination": combination}

    restored = serde.loads_typed(serde.dumps_typed(payload))

    assert restored["understanding"] == understanding
    assert restored["combination"] == combination
    assert isinstance(restored["combination"].skipped[0], CombineSkip)
