"""Step 3 contracts (U17): the quality and noise settings, models and seams.

Spec sections 3.1, 3.3 and 3.4, D4 and D35-D42: the new models validate and
round-trip through the state serde; every model, serde and ``NodeContext``
default reproduces Step 2, while the ``Settings`` defaults carry the owner's
choices (O9: output check on; O10: paired trials, confirmation, 3 blocks).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    NOISE_CALIBRATION_BLOCKS_MAX,
    Baseline,
    BuiltinMeasure,
    ChangeClass,
    Direction,
    DropUnit,
    FrozenFile,
    Guardrail,
    GuardrailKind,
    JudgeOutcome,
    JudgeResult,
    Measurement,
    NoiseCalibration,
    Objective,
    OutputTolerance,
    Project,
    ProjectUnderstanding,
    QualityCheck,
    QualityProposal,
    RunStats,
    Trial,
    Verdict,
    VerdictOutcome,
    ViolationRule,
    Workload,
)
from autonomous_ai_agents.orchestrator.nodes import NodeContext, NoiseCalibrator
from autonomous_ai_agents.orchestrator.serde import dump_state, load_state
from autonomous_ai_agents.orchestrator.state import initial_state

ContextFactory = Callable[..., NodeContext]
MIB = 1024 * 1024
SHA = "ab" * 32
LABELS = "data/labels.csv"


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def _builtin(**values: object) -> QualityCheck:
    fields: dict[str, object] = {
        "name": "accuracy",
        "measure": "accuracy",
        "labels": LABELS,
        "frozen_paths": (LABELS,),
    }
    return QualityCheck.model_validate({**fields, **values})


def _external(**values: object) -> QualityCheck:
    fields: dict[str, object] = {
        "name": "bleu",
        "scorer": ("python3", "./eval/score.py"),
        "frozen_paths": ("eval/score.py", "eval/truth.txt"),
        "direction": "maximize",
    }
    return QualityCheck.model_validate({**fields, **values})


def _measurement(trial_id: str | None = None) -> Measurement:
    return Measurement(
        workload_id="w1",
        trial_id=trial_id,
        metric=METRIC_WALL_TIME_S,
        stats=RunStats.from_samples([1.0] * 5, "s"),
        samples=(1.0,) * 5,
        output_fingerprint="cd" * 32,
        raw_fingerprint=SHA,
    )


def _calibration(**values: object) -> NoiseCalibration:
    fields: dict[str, object] = {"blocks": 3, "gaps": {"w1": 0.006}, "floor": 0.02}
    return NoiseCalibration.model_validate({**fields, **values})


# ---------------------------------------------------------------------------
# Settings (section 3.1)
# ---------------------------------------------------------------------------


def test_the_quality_and_noise_settings_carry_the_owners_choices() -> None:
    """
    GIVEN no environment
    WHEN the settings load
    THEN the output check, paired trials and confirmation are on, with 3
         calibration blocks at a 2x gap multiplier (O9, O10) and the spec's caps
    """
    cfg = _settings()

    assert (cfg.DEFAULT_OUTPUT_CHECK, cfg.PAIRED_TRIALS, cfg.CONFIRM_WINNERS) == (
        True,
        True,
        True,
    )
    assert (cfg.NOISE_CALIBRATION_BLOCKS, cfg.NOISE_GAP_MULTIPLIER) == (3, 2.0)
    assert cfg.OUTPUT_TOLERANCE_MAX_BYTES == 16 * MIB
    assert cfg.QUALITY_MAX_FROZEN_BYTES == 64 * MIB
    assert (cfg.QUALITY_MAX_ROWS, cfg.QUALITY_TIMEOUT_S) == (1_000_000, 300.0)


@pytest.mark.parametrize(
    "values",
    [
        {"OUTPUT_TOLERANCE_MAX_BYTES": 0},
        {"QUALITY_MAX_FROZEN_BYTES": 0},
        {"QUALITY_MAX_ROWS": 0},
        {"QUALITY_TIMEOUT_S": 0.5},
        {"QUALITY_TIMEOUT_S": float("inf")},
        {"QUALITY_TIMEOUT_S": float("nan")},
        {"NOISE_CALIBRATION_BLOCKS": -1},
        {"NOISE_CALIBRATION_BLOCKS": 6},
        {"NOISE_GAP_MULTIPLIER": 0.99},
        {"NOISE_GAP_MULTIPLIER": float("inf")},
    ],
)
def test_out_of_range_quality_and_noise_settings_are_refused(
    values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _settings(**values)


def test_the_quality_and_noise_bounds_are_accepted() -> None:
    cfg = _settings(
        NOISE_CALIBRATION_BLOCKS=0,
        NOISE_GAP_MULTIPLIER=1.0,
        QUALITY_TIMEOUT_S=1,
        QUALITY_MAX_ROWS=1,
        DEFAULT_OUTPUT_CHECK=False,
    )
    assert (cfg.NOISE_CALIBRATION_BLOCKS, cfg.NOISE_GAP_MULTIPLIER) == (0, 1.0)
    assert cfg.DEFAULT_OUTPUT_CHECK is False
    assert _settings(NOISE_CALIBRATION_BLOCKS=5).NOISE_CALIBRATION_BLOCKS == 5


# ---------------------------------------------------------------------------
# QualityCheck, QualityProposal, OutputTolerance (D37-D40)
# ---------------------------------------------------------------------------


def test_a_builtin_check_fixes_its_direction_and_defaults_to_no_drop() -> None:
    """
    GIVEN a builtin measure over a frozen labels file
    WHEN the check validates
    THEN the builtin sets the direction, the drop is 0 absolute points and
         the guardrail metric is ``quality:<name>``
    """
    check = _builtin()

    assert check.measure is BuiltinMeasure.accuracy
    assert check.direction is Direction.maximize
    assert (check.max_drop, check.drop_unit) == (0.0, DropUnit.absolute)
    assert check.metric == "quality:accuracy"
    assert check.scorer == ()
    minimizing = {
        BuiltinMeasure.error_rate,
        BuiltinMeasure.mae,
        BuiltinMeasure.rmse,
    }
    for measure in BuiltinMeasure:
        expected = Direction.minimize if measure in minimizing else Direction.maximize
        assert _builtin(measure=measure).direction is expected
    assert _builtin(measure="mae", direction="minimize").direction is Direction.minimize


def test_an_external_check_normalises_its_script_and_keeps_its_direction() -> None:
    check = _external(max_drop=0.5, drop_unit="relative", name="b" * 32)

    assert check.scorer == ("python3", "eval/score.py")
    assert check.frozen_paths == ("eval/score.py", "eval/truth.txt")
    assert (check.direction, check.measure, check.labels) == (
        Direction.maximize,
        None,
        None,
    )
    assert (check.max_drop, check.drop_unit) == (0.5, DropUnit.relative)
    assert _external(scorer=("python3", "eval/score.py", "--strict")).scorer[2] == (
        "--strict"
    )
    for interpreter in ("python", "python3", "python3.12", "/usr/bin/python3.12"):
        assert _external(scorer=(interpreter, "eval/score.py")).scorer[0] == (
            interpreter
        )


@pytest.mark.parametrize(
    "build",
    [
        lambda: _builtin(scorer=("python3", LABELS)),  # builtin and scorer
        lambda: _builtin(measure=None),  # labels without a measure
        lambda: _builtin(labels=None),  # a measure without labels
        lambda: _builtin(frozen_paths=("data/other.csv",)),  # labels not frozen
        lambda: _builtin(direction="minimize"),  # against the builtin
        lambda: _builtin(measure="f1"),
        lambda: _builtin(name="Accuracy"),
        lambda: _builtin(name="1acc"),
        lambda: _builtin(name="a-b"),
        lambda: _builtin(name=""),
        lambda: _builtin(name="a" * 33),
        lambda: _builtin(frozen_paths=()),
        lambda: _builtin(frozen_paths=(LABELS, *(f"f{i}.txt" for i in range(16)))),
        lambda: _builtin(frozen_paths=(LABELS, "./data/labels.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "../secret.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "/etc/passwd")),
        lambda: _builtin(frozen_paths=(LABELS, ".")),
        lambda: _builtin(max_drop=-0.1),
        lambda: _builtin(max_drop=float("inf")),
        lambda: _builtin(max_drop=float("nan")),
        lambda: _builtin(colour="blue"),
        lambda: _external(scorer=()),  # neither builtin nor scorer
        lambda: _external(scorer=("eval/score.py",)),  # no script argument
        lambda: _external(scorer=("python3", "eval/other.py")),  # not frozen
        lambda: _external(scorer=("python3", "/abs/score.py")),
        lambda: _external(scorer=("python3", "eval/score.py", "")),
        lambda: _external(scorer=("python3", "eval/score.py", "a\x00b")),
        lambda: _external(direction=None),  # an external needs a direction
        # Frozen paths are literal names that pattern matchers would misread.
        lambda: _builtin(frozen_paths=(LABELS, "data/[v1]labels.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "data/a*b.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "data/a?.csv")),
        lambda: _builtin(labels="data/[v1].csv", frozen_paths=("data/[v1].csv",)),
        lambda: _external(
            scorer=("python3", "eval/s[1].py"),
            frozen_paths=("eval/s[1].py",),
        ),
        # Control characters defeat line-based checks.
        lambda: _builtin(frozen_paths=(LABELS, "data/l\x00abels.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "data/l\nabels.csv")),
        lambda: _builtin(frozen_paths=(LABELS, "data/l\rabels.csv")),
        # A script an interpreter would read as a flag.
        lambda: _external(scorer=("python3", "-c"), frozen_paths=("-c",)),
        # Git metadata is never a tracked blob.
        lambda: _builtin(frozen_paths=(LABELS, ".git/config")),
        lambda: _builtin(frozen_paths=(LABELS, "sub/.GITMODULES")),
        # The scorer runs as ``python -E -s``, so it is a Python interpreter.
        lambda: _external(scorer=("/bin/sh", "eval/score.py")),
        lambda: _external(scorer=("bash", "eval/score.py")),
        lambda: _external(scorer=("python3x", "eval/score.py")),
        lambda: _external(scorer=("pythonw", "eval/score.py")),
        lambda: _external(labels=LABELS),  # labels belong to a builtin
    ],
)
def test_an_invalid_quality_check_is_refused(build: Callable[[], object]) -> None:
    """
    GIVEN a check that is not exactly one of builtin (measure + frozen labels)
          or external (argv whose script is frozen), a bad name, 0 or 17
          frozen paths, a duplicate or escaping path, or a bad drop
    WHEN it validates
    THEN validation fails
    """
    with pytest.raises(ValidationError):
        build()


def test_the_check_is_frozen() -> None:
    check = _builtin()
    with pytest.raises(ValidationError):
        check.max_drop = 1.0  # type: ignore[misc]


def test_a_proposal_names_a_builtin_with_labels_or_a_script() -> None:
    builtin = QualityProposal(measure=BuiltinMeasure.macro_f1, labels="./y.csv")
    script = QualityProposal(scorer_path="eval/score.py")

    assert (builtin.labels, builtin.scorer_path) == ("y.csv", None)
    assert (script.measure, script.labels) == (None, None)
    for bad in (
        {},
        {"measure": "accuracy"},
        {"labels": "y.csv"},
        {"measure": "accuracy", "labels": "y.csv", "scorer_path": "s.py"},
        {"scorer_path": "../s.py"},
        {"measure": "bleu", "labels": "y.csv"},
    ):
        with pytest.raises(ValidationError):
            QualityProposal.model_validate(bad)


@pytest.mark.parametrize(
    ("values", "valid"),
    [
        ({"float_digits": 6}, True),
        ({"float_digits": 15}, True),
        ({"unordered_lines": True}, True),
        ({"float_digits": 9, "unordered_lines": True}, True),
        ({"float_digits": 5}, False),
        ({"float_digits": 16}, False),
        ({}, False),  # tolerates nothing: omit the tolerance instead
        ({"float_digits": None, "unordered_lines": False}, False),
    ],
)
def test_an_output_tolerance_has_digits_6_to_15_or_unordered_lines(
    values: dict[str, object], valid: bool
) -> None:
    if valid:
        assert (
            OutputTolerance.model_validate(values).model_dump(exclude_unset=True)
            == values
        )
    else:
        with pytest.raises(ValidationError):
            OutputTolerance.model_validate(values)


# ---------------------------------------------------------------------------
# Noise and frozen files (D37, D41, D42)
# ---------------------------------------------------------------------------


def test_a_calibration_is_bounded_and_its_floor_covers_its_gaps() -> None:
    """
    GIVEN calibration results
    WHEN they validate
    THEN 1-5 blocks, finite gaps of at least 0 and a floor of at least 2 %
         (O10) that is no smaller than the largest gap are accepted
    """
    assert _calibration().floor == 0.02
    assert _calibration(blocks=1, gaps={}, floor=0.5).gaps == {}
    assert _calibration(blocks=5, gaps={"w1": 0.03}, floor=0.06).blocks == 5
    for bad in (
        {"blocks": 0},
        {"blocks": 6},
        {"floor": 0.019},
        {"gaps": {"w1": -0.01}},
        {"gaps": {"w1": float("nan")}},
        {"gaps": {"w1": 0.03}, "floor": 0.025},
        {"floor": float("inf")},
    ):
        with pytest.raises(ValidationError):
            _calibration(**bad)


def test_a_frozen_file_names_a_project_file_by_sha256_and_size() -> None:
    frozen = FrozenFile(path="./data/labels.csv", sha256=SHA, size=0)

    assert frozen.path == LABELS
    for bad in (
        {"path": "../x", "sha256": SHA, "size": 1},
        {"path": "x", "sha256": "AB" * 32, "size": 1},
        {"path": "x", "sha256": SHA[:-1], "size": 1},
        {"path": "x", "sha256": SHA, "size": -1},
    ):
        with pytest.raises(ValidationError):
            FrozenFile.model_validate(bad)
    with pytest.raises(ValidationError, match="once"):
        Baseline(quality_files=(frozen, frozen))


def test_confirmations_count_looks_and_a_confirmed_gain_needs_two() -> None:
    verdict = Verdict(
        trial_id="t",
        hypothesis_id="h",
        outcome=VerdictOutcome.keep,
        change_class=ChangeClass.efficiency,
        summary="kept",
    )
    confirmed = verdict.model_validate(
        {**verdict.model_dump(), "confirmations": 2, "confirmed_gain": 0.18}
    )

    assert (verdict.confirmations, verdict.confirmed_gain) == (1, None)
    assert confirmed.confirmed_gain == 0.18
    for bad in ({"confirmations": 0}, {"confirmed_gain": 0.18}):
        with pytest.raises(ValidationError):
            Verdict.model_validate({**verdict.model_dump(), **bad})


def test_a_raw_fingerprint_is_a_sha256() -> None:
    fields = _measurement().model_dump()
    with pytest.raises(ValidationError):
        Measurement.model_validate({**fields, "raw_fingerprint": "not-a-sha"})


def test_drop_unit_defaults_to_relative_and_applies_to_metric_bounds_only(
    sample_project: Project,
) -> None:
    bound = Guardrail(
        project_id=sample_project.id,
        kind=GuardrailKind.metric_bound,
        metric="quality:accuracy",
        max_drop=0.005,
        direction=Direction.maximize,
        drop_unit=DropUnit.absolute,
        description="accuracy may drop 0.5 points",
    )
    same = Guardrail(
        project_id=sample_project.id,
        kind=GuardrailKind.output_equivalence,
        description="outputs unchanged",
    )

    assert bound.drop_unit is DropUnit.absolute
    assert same.drop_unit is DropUnit.relative
    with pytest.raises(ValidationError, match="metric_bound"):
        same.model_validate({**same.model_dump(), "drop_unit": "absolute"})


# ---------------------------------------------------------------------------
# Step 2 defaults and serde (D4)
# ---------------------------------------------------------------------------


def test_every_new_model_field_defaults_to_step2(
    sample_project: Project, sample_workload: Workload
) -> None:
    trial = Trial(hypothesis_id="h", round=1)
    judged = JudgeResult(judge="speed", outcome=JudgeOutcome.passed, reason="ok")
    understanding = ProjectUnderstanding(
        language="python", summary="s", served_by_model="m"
    )

    assert sample_workload.output_tolerance is None
    assert ViolationRule("quality_data_reference").value == "quality_data_reference"
    assert (trial.base_measurements, judged.output_changed) == ((), None)
    assert (
        Measurement.model_validate(
            {**_measurement().model_dump(), "raw_fingerprint": None}
        ).raw_fingerprint
        is None
    )
    assert (Baseline().calibration, Baseline().quality_files) == (None, ())
    assert understanding.quality_proposal is None


def test_the_quality_and_noise_fields_round_trip_through_the_state_serde(
    sample_project: Project,
    sample_workload: Workload,
    sample_objective: Objective,
    sample_guardrails: Sequence[Guardrail],
) -> None:
    """
    GIVEN a state whose baseline, workloads, guardrails, trials, verdicts and
          understanding carry every new field at a non-default value
    WHEN it is dumped, JSON-encoded, decoded and loaded
    THEN every key comes back equal and typed
    """
    tolerant = sample_workload.model_copy(
        update={"output_tolerance": OutputTolerance(float_digits=9)}
    )
    bound = sample_guardrails[1].model_copy(update={"drop_unit": DropUnit.absolute})
    state = initial_state(
        sample_project, [tolerant], [sample_objective], [sample_guardrails[0], bound]
    )
    frozen = FrozenFile(path=LABELS, sha256=SHA, size=12)
    state["baseline"] = Baseline(
        measurements=(_measurement(),),
        calibration=_calibration(),
        quality_files=(frozen,),
    )
    judged = JudgeResult(
        judge="equivalence",
        outcome=JudgeOutcome.passed,
        reason="changed",
        output_changed=True,
    )
    trial = Trial(
        hypothesis_id="h",
        round=1,
        measurements=(_measurement("t"),),
        base_measurements=(_measurement(),),
        judge_results=(judged,),
    )
    state["trials"] = [trial]
    state["verdicts"] = [
        Verdict(
            trial_id=trial.id,
            hypothesis_id="h",
            outcome=VerdictOutcome.review,
            change_class=ChangeClass.efficiency,
            summary="confirmed",
            confirmations=2,
            confirmed_gain=0.3,
        )
    ]
    state["understanding"] = ProjectUnderstanding(
        language="python",
        summary="s",
        served_by_model="m",
        quality_proposal=QualityProposal(measure="accuracy", labels=LABELS),
    )

    loaded = load_state(json.loads(json.dumps(dump_state(state), allow_nan=False)))

    assert loaded == state
    baseline = loaded["baseline"]
    assert baseline is not None and type(baseline.calibration) is NoiseCalibration
    assert type(baseline.quality_files[0]) is FrozenFile
    assert loaded["trials"][0].base_measurements[0].raw_fingerprint == SHA
    assert loaded["guardrails"][1].drop_unit is DropUnit.absolute
    understanding = loaded["understanding"]
    assert understanding is not None and understanding.quality_proposal is not None
    assert understanding.quality_proposal.measure is BuiltinMeasure.accuracy
    assert _builtin() == QualityCheck.model_validate_json(_builtin().model_dump_json())
    assert _external() == QualityCheck.model_validate_json(
        _external().model_dump_json()
    )


# ---------------------------------------------------------------------------
# NodeContext seams (section 3.4)
# ---------------------------------------------------------------------------


class _Calibrator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def calibrate(
        self, workloads: Sequence[Workload], *, run_id: str, commit: str, blocks: int
    ) -> NoiseCalibration:
        self.calls.append((run_id, commit, blocks))
        return _calibration(blocks=blocks)


def test_node_context_quality_and_noise_defaults_reproduce_step2(
    make_context: ContextFactory,
) -> None:
    """
    GIVEN a context built as in Step 2
    WHEN the quality and noise fields are read
    THEN no quality check, no default output check, no calibrator, 0 blocks
         and no confirmation (only the factory reads the settings, D4)
    """
    ctx = make_context()

    assert (ctx.quality, ctx.calibrator) == (None, None)
    assert (ctx.default_output_check, ctx.confirm_winners) == (False, False)
    assert ctx.calibration_blocks == 0


def test_node_context_keeps_the_quality_and_noise_seams(
    make_context: ContextFactory, sample_workload: Workload
) -> None:
    calibrator = _Calibrator()
    ctx = make_context(
        quality=_builtin(),
        default_output_check=True,
        calibrator=calibrator,
        calibration_blocks=5,
        confirm_winners=True,
    )

    assert isinstance(calibrator, NoiseCalibrator)
    assert not isinstance(object(), NoiseCalibrator)
    assert ctx.calibrator is calibrator and ctx.quality == _builtin()
    result = calibrator.calibrate([sample_workload], run_id="r", commit="c", blocks=5)
    assert (result.blocks, calibrator.calls) == (5, [("r", "c", 5)])
    assert make_context(calibrator=calibrator).calibration_blocks == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"calibration_blocks": -1, "calibrator": _Calibrator()}, "0-5"),
        ({"calibration_blocks": 6, "calibrator": _Calibrator()}, "0-5"),
        ({"calibration_blocks": 1}, "calibrator"),
    ],
)
def test_node_context_refuses_bad_calibration_knobs(
    make_context: ContextFactory, overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        make_context(**overrides)


def test_the_settings_and_the_calibration_share_one_block_bound() -> None:
    """``NOISE_CALIBRATION_BLOCKS`` and ``NoiseCalibration.blocks`` stop at
    the same constant, so raising one cannot leave the other behind."""
    top = NOISE_CALIBRATION_BLOCKS_MAX
    assert _calibration(blocks=top).blocks == top
    assert _settings(NOISE_CALIBRATION_BLOCKS=top).NOISE_CALIBRATION_BLOCKS == top
    with pytest.raises(ValueError):
        _calibration(blocks=top + 1)
    with pytest.raises(ValueError):
        _settings(NOISE_CALIBRATION_BLOCKS=top + 1)
