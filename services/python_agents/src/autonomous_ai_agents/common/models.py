"""Engine data models shared by every engine package.

Conventions:

- Every model is frozen and forbids unknown fields. Transitions use
  ``model_copy(update=...)``; nothing mutates in place.
- Ids are uuid4 strings; timestamps are tz-aware UTC. Both serialise
  identically to JSON, msgpack checkpoints, JSONB and the CLI.
- Collections inside models are tuples. Lists live only in the LangGraph
  state so ``operator.add`` reducers can append to them.
- Enums are ``StrEnum`` whose values equal their names, so they match the SQL
  ``CHECK`` lists in ``infrastructure/schema/003_engine.sql`` verbatim.
- ``ENGINE_MODEL_CLASSES`` is the allowlist handed to the LangGraph
  checkpointer serializer; a test asserts it lists every model here.
"""

from __future__ import annotations

import os
import re
import statistics
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import PurePath, PurePosixPath
from types import MappingProxyType
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autonomous_ai_agents.common.paths import literal_project_file, normalize_path

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

MIN_RUNS = 5
"""Minimum timed runs behind any measurement the engine will judge."""

METRIC_WALL_TIME_S = "wall_time_s"
METRIC_CPU_TIME_S = "cpu_time_s"
METRIC_PEAK_RSS_BYTES = "peak_rss_bytes"
METRIC_THROUGHPUT_PER_S = "throughput_per_s"
METRIC_TESTS_PASSED = "tests_passed"
"""Runner-reported metric: mean 1.0 when the project's test suite passed."""

SHA256_PATTERN = r"^[0-9a-f]{64}$"
QUALITY_METRIC_PREFIX = "quality:"
"""A quality check's guardrail metric is ``quality:<name>`` (D38)."""
NOISE_FLOOR_MIN = 0.02
"""A calibrated noise floor is never below 2 % (O10)."""
NOISE_CALIBRATION_BLOCKS_MAX = 5
"""Most A/A calibration blocks a baseline runs (``NOISE_CALIBRATION_BLOCKS``)."""
QUALITY_MAX_FROZEN_PATHS = 16
_SCORER_INTERPRETER = re.compile(r"python(3(\.\d+)?)?")
"""``scorer[0]``'s file name: the scorer runs as ``python -s -B`` (D37)."""

JsonScalar = str | int | float | bool | None
ScalarDict = dict[str, JsonScalar]

HYPOTHESIS_TAG: Final = re.compile(r"[a-z_]+:[a-z0-9_:.-]{1,64}")
"""One ``Hypothesis.tags`` entry, matched whole (D57): a key, a colon, a value."""
MAX_HYPOTHESIS_TAGS: Final = 24


def new_id() -> str:
    """Return a fresh uuid4 as a string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return the current time as a tz-aware UTC datetime."""
    return datetime.now(UTC)


def _project_file(field: str, value: str) -> str:
    """``normalize_path`` for a field that must name a file, not the root itself.

    ``normalize_path`` maps ``""`` and ``"."`` to ``"."``, which is right for
    ``working_dir`` but would make a file field point at the project root.
    """
    normalized = normalize_path(value)
    if normalized == ".":
        raise ValueError(f"{field} must name a file, got {value!r}")
    return normalized


def _optional_project_file(field: str, value: str | None) -> str | None:
    return None if value is None else _project_file(field, value)


def _quality_file(field: str, value: str) -> str:
    """``_project_file`` for a file a quality check freezes (D37): the shared
    ``literal_project_file`` rule, which the measurement mask applies too."""
    return literal_project_file(field, value)


def _unique_project_files(
    field: str,
    values: Sequence[str],
    *,
    check: Callable[[str, str], str] = _project_file,
) -> tuple[str, ...]:
    """Each checked and normalized; a path listed twice (in any spelling) is refused."""
    paths = tuple(check(field, value) for value in values)
    if len(set(paths)) != len(paths):
        raise ValueError(f"{field} must list each file once, got {list(values)}")
    return paths


class EngineModel(BaseModel):
    """Base for every engine model: frozen, strict about unknown fields.

    ``allow_inf_nan=False``: JSONB cannot store inf or NaN, and neither is a
    measurement, a price or a cost the judges or the budget can reason about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


# ---------------------------------------------------------------------------
# Enums (values == names, lowercase; mirrored by SQL CHECK constraints)
# ---------------------------------------------------------------------------


class RunPhase(StrEnum):
    connect = "connect"
    understand = "understand"
    define = "define"
    baseline = "baseline"
    profile = "profile"
    research = "research"
    hypotheses = "hypotheses"
    trials = "trials"
    judges = "judges"
    verdicts = "verdicts"
    approval = "approval"
    combine = "combine"
    deliver = "deliver"
    learn = "learn"
    watch = "watch"
    done = "done"
    failed = "failed"


class ObjectiveKind(StrEnum):
    runtime = "runtime"
    peak_memory = "peak_memory"
    throughput = "throughput"
    quality_metric = "quality_metric"
    custom = "custom"


class Direction(StrEnum):
    minimize = "minimize"
    maximize = "maximize"


class GuardrailKind(StrEnum):
    output_equivalence = "output_equivalence"
    tests_pass = "tests_pass"  # nosec B105: an enum value, not a password
    metric_bound = "metric_bound"


class ChangeClass(StrEnum):
    """Drives autonomy: efficiency ships, behaviour goes to review, novel needs approval."""

    efficiency = "efficiency"
    behaviour = "behaviour"
    novel = "novel"


class HypothesisSource(StrEnum):
    playbook = "playbook"
    paper = "paper"
    novel = "novel"
    lesson = "lesson"


class HypothesisStatus(StrEnum):
    proposed = "proposed"
    trialled = "trialled"
    kept = "kept"
    rejected = "rejected"
    inconclusive = "inconclusive"


class TrialStatus(StrEnum):
    pending = "pending"
    running = "running"
    measured = "measured"
    failed = "failed"
    rejected = "rejected"


class JudgeOutcome(StrEnum):
    passed = "passed"
    failed = "failed"
    inconclusive = "inconclusive"
    not_applicable = "not_applicable"


class VerdictOutcome(StrEnum):
    keep = "keep"
    reject = "reject"
    inconclusive = "inconclusive"
    needs_approval = "needs_approval"
    review = "review"  # Step 3 (D10): all judges passed; its own branch, no pause


class ViolationRule(StrEnum):
    protected_path = "protected_path"
    path_traversal = "path_traversal"
    too_few_runs = "too_few_runs"
    fingerprint_mismatch = "fingerprint_mismatch"
    missing_fingerprint = "missing_fingerprint"
    missing_measurement = "missing_measurement"
    duplicate_measurement = "duplicate_measurement"
    # Capture rules (Step 2): problems only the runner sees in the git diff.
    forbidden_file_mode = "forbidden_file_mode"
    forbidden_file = "forbidden_file"
    git_metadata = "git_metadata"
    unrecorded_write = "unrecorded_write"
    process_spawn = "process_spawn"
    module_shadow = "module_shadow"
    # Step 3 (D37): added lines name a frozen quality file (a tripwire).
    quality_data_reference = "quality_data_reference"
    # Step 3 Wave 2 (D62): a new blob the engine's parser cannot read.
    unparsable_source = "unparsable_source"
    # Step 3 Wave 2 (D62, N0c): a measured trial run started child processes
    # (the runtime backstop to process_spawn).
    child_processes = "child_processes"


class DeliveryKind(StrEnum):
    branch = "branch"
    pull_request = "pull_request"
    report_only = "report_only"


class EventLevel(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


class BuiltinMeasure(StrEnum):
    """A quality measure the engine computes itself, one value per line (D37)."""

    accuracy = "accuracy"
    error_rate = "error_rate"
    macro_f1 = "macro_f1"
    mae = "mae"
    rmse = "rmse"


class DropUnit(StrEnum):
    """How a guardrail's ``max_drop`` is read (D38): a fraction of the baseline
    mean (``relative``, Step 2's rule) or points of the metric (``absolute``)."""

    relative = "relative"
    absolute = "absolute"


BUILTIN_DIRECTIONS: Final = MappingProxyType(
    {
        BuiltinMeasure.accuracy: Direction.maximize,
        BuiltinMeasure.error_rate: Direction.minimize,
        BuiltinMeasure.macro_f1: Direction.maximize,
        BuiltinMeasure.mae: Direction.minimize,
        BuiltinMeasure.rmse: Direction.minimize,
    }
)
"""The direction each builtin fixes: higher is better or lower is better."""


ENGINE_ENUM_CLASSES: tuple[type[StrEnum], ...] = (
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
    EventLevel,
    BuiltinMeasure,
    DropUnit,
)
"""Every engine enum. Checkpoint deserialisation must allow these too, or
``state["phase"]`` comes back as a plain string after a resume."""


# ---------------------------------------------------------------------------
# Step 3: quality check, output tolerance, noise calibration (D37-D42)
# ---------------------------------------------------------------------------


class OutputTolerance(EngineModel):
    """When two outputs count as equal (D39): a workload option, never silent.

    ``float_digits`` compares decimal tokens at that many significant digits;
    ``unordered_lines`` ignores line order. A tolerance setting neither is
    refused: exact comparison is spelled ``Workload.output_tolerance=None``.
    """

    float_digits: int | None = Field(default=None, ge=6, le=15)
    unordered_lines: bool = False

    @model_validator(mode="after")
    def _tolerates_something(self) -> Self:
        if self.float_digits is None and not self.unordered_lines:
            raise ValueError(
                "an output tolerance needs float_digits or unordered_lines; "
                "omit it for exact comparison"
            )
        return self


class QualityCheck(EngineModel):
    """The quality number the user confirmed once (D37, D40), judged as the
    ``metric_bound`` guardrail ``quality:<name>`` (D38).

    Exactly one source: a builtin ``measure`` over a ``labels`` file, or an
    external ``scorer`` argv whose script (``scorer[1]``) is a project file.
    Either way the files it reads are ``frozen_paths`` (1-16 project files,
    the labels or the script among them): recorded at baseline, protected
    from trials, masked from workloads and hidden from the editor. A builtin
    fixes the direction; an external scorer must state one. ``max_drop`` is
    what the user allows to be lost (0: the same or better), in points of the
    metric by default (``absolute``, D38).
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    measure: BuiltinMeasure | None = None
    labels: str | None = None
    scorer: tuple[str, ...] = ()
    frozen_paths: tuple[str, ...] = Field(
        min_length=1, max_length=QUALITY_MAX_FROZEN_PATHS
    )
    direction: Direction | None = None
    max_drop: float = Field(default=0.0, ge=0)
    drop_unit: DropUnit = DropUnit.absolute

    @model_validator(mode="before")
    @classmethod
    def _builtin_fixes_the_direction(cls, data: object) -> object:
        """Fill an unset direction from the builtin; a wrong one fails below."""
        if not isinstance(data, dict) or data.get("direction") is not None:
            return data
        raw = data.get("measure")
        if not isinstance(raw, str) or raw not in BUILTIN_DIRECTIONS:
            return data  # none or unknown: the fields report it
        return {**data, "direction": BUILTIN_DIRECTIONS[BuiltinMeasure(raw)]}

    @field_validator("labels")
    @classmethod
    def _labels_inside_project(cls, value: str | None) -> str | None:
        return None if value is None else _quality_file("labels", value)

    @field_validator("frozen_paths")
    @classmethod
    def _frozen_paths_inside_project(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_project_files("frozen_paths", value, check=_quality_file)

    @field_validator("scorer")
    @classmethod
    def _scorer_runs_a_project_script(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            return value
        if len(value) < 2 or any(not arg or "\x00" in arg for arg in value):
            raise ValueError(
                "scorer must be an argv of an interpreter and a script, with no "
                f"empty or NUL argument; got {list(value)}"
            )
        if not _SCORER_INTERPRETER.fullmatch(PurePosixPath(value[0]).name):
            raise ValueError(
                "scorer[0] must be a Python interpreter (python, python3 or "
                f"python3.N, by name or path), got {value[0]!r}"
            )
        return (value[0], _quality_file("scorer[1]", value[1]), *value[2:])

    @model_validator(mode="after")
    def _exactly_one_source(self) -> Self:
        if self.measure is not None:
            if self.labels is None or self.scorer:
                raise ValueError("a builtin measure needs labels and no scorer")
            if self.direction is not BUILTIN_DIRECTIONS[self.measure]:
                raise ValueError(f"{self.measure} fixes the direction")
            needed = self.labels
        else:
            if self.labels is not None or not self.scorer:
                raise ValueError(
                    "a quality check is a builtin measure with labels or a scorer"
                )
            if self.direction is None:
                raise ValueError("an external scorer needs a direction")
            needed = self.scorer[1]
        if needed not in self.frozen_paths:
            raise ValueError(f"{needed!r} must be one of the frozen paths")
        return self

    @property
    def metric(self) -> str:
        """The guardrail metric this check is judged by."""
        return f"{QUALITY_METRIC_PREFIX}{self.name}"


class QualityProposal(EngineModel):
    """Understand's suggestion (D40): a builtin over a labels file, or an
    existing evaluation script. Model output, never activated by itself."""

    measure: BuiltinMeasure | None = None
    labels: str | None = None
    scorer_path: str | None = None

    @field_validator("labels", "scorer_path")
    @classmethod
    def _paths_inside_project(cls, value: str | None) -> str | None:
        return _optional_project_file("quality proposal path", value)

    @model_validator(mode="after")
    def _builtin_with_labels_or_a_script(self) -> Self:
        builtin = self.measure is not None and self.labels is not None
        partial = (self.measure is None) != (self.labels is None)
        if partial or builtin == (self.scorer_path is not None):
            raise ValueError(
                "a quality proposal is a measure with labels or a scorer path"
            )
        return self


class FrozenFile(EngineModel):
    """A quality file read at the base commit (D37), listed in the report."""

    path: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def _path_inside_project(cls, value: str) -> str:
        return _project_file("path", value)


class NoiseCalibration(EngineModel):
    """The per-project floor from A/A blocks of the base against itself (D41 c).

    ``gaps`` holds, per workload (and time objective, as the calibrator keys
    it), the largest relative gap |A - A'| over the blocks; ``floor`` is
    ``max(MIN_RELATIVE_GAIN, NOISE_GAP_MULTIPLIER * largest gap)``, so never
    below 2 % (O10) nor below any gap (the multiplier is at least 1).
    """

    blocks: int = Field(ge=1, le=NOISE_CALIBRATION_BLOCKS_MAX)
    gaps: dict[str, float] = Field(default_factory=dict)
    floor: float = Field(ge=NOISE_FLOOR_MIN)

    @field_validator("gaps")
    @classmethod
    def _gaps_are_magnitudes(cls, value: dict[str, float]) -> dict[str, float]:
        if any(gap < 0 for gap in value.values()):
            raise ValueError(f"calibration gaps must be at least 0, got {value}")
        return value

    @model_validator(mode="after")
    def _floor_covers_every_gap(self) -> Self:
        if self.gaps and self.floor < max(self.gaps.values()):
            raise ValueError("the noise floor must cover the largest calibrated gap")
        return self


# ---------------------------------------------------------------------------
# Project, workloads, objectives, guardrails
# ---------------------------------------------------------------------------


class Project(EngineModel):
    """A codebase the engine improves. Long-lived across runs.

    ``root_path`` is stored canonical (``os.path.realpath``), the form every
    git call already uses.

    ``test_command`` is the argv of the project's test suite (never a shell
    string). The caller supplies it; ``None`` means no suite is run, which
    preflight refuses when a ``tests_pass`` guardrail exists.
    """

    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1)
    root_path: str
    default_branch: str = "main"
    language: str = "python"
    hardware: ScalarDict = Field(default_factory=dict)
    test_command: tuple[str, ...] | None = Field(default=None, min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("root_path")
    @classmethod
    def _absolute_without_parent_segments(cls, value: str) -> str:
        """Absolute, no ``..``, and canonical (``realpath``: no trailing slash,
        ``.`` or link), so one repository has one spelling and the
        repository's one-project-per-root check cannot be bypassed."""
        if not os.path.isabs(value) or ".." in PurePath(value).parts:
            raise ValueError("root_path must be absolute and must not contain '..'")
        try:
            return os.path.realpath(value)
        except ValueError:  # a NUL names no directory: spelled canonically only
            return os.path.normpath(value)


class Workload(EngineModel):
    """Something the engine can run and time: an argv command, never a shell string.

    ``output_file`` is a project-relative file the workload writes; its bytes
    join stdout in the output fingerprint.
    """

    id: str = Field(default_factory=new_id)
    project_id: str
    name: str = Field(min_length=1)
    command: tuple[str, ...] = Field(min_length=1)
    working_dir: str = "."
    entrypoint: str | None = None
    output_file: str | None = None
    inputs: ScalarDict = Field(default_factory=dict)
    timeout_s: float = Field(default=600.0, gt=0)
    warmup_runs: int = Field(default=1, ge=0)
    runs: int = Field(default=MIN_RUNS, ge=MIN_RUNS)
    output_tolerance: OutputTolerance | None = None
    """``None`` compares outputs byte for byte (Step 2); see ``OutputTolerance``."""
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("working_dir")
    @classmethod
    def _working_dir_inside_project(cls, value: str) -> str:
        return normalize_path(value)

    @field_validator("output_file")
    @classmethod
    def _output_file_inside_project(cls, value: str | None) -> str | None:
        return None if value is None else _project_file("output_file", value)


class Objective(EngineModel):
    """What "better" means for one metric. The highest weight is the primary objective."""

    id: str = Field(default_factory=new_id)
    project_id: str
    kind: ObjectiveKind
    metric: str = Field(min_length=1)
    direction: Direction
    min_relative_gain: float = Field(default=0.02, ge=0, le=1)
    weight: float = Field(default=1.0, gt=0)
    description: str
    created_at: datetime = Field(default_factory=utc_now)


class Guardrail(EngineModel):
    """What must not get worse. A metric_bound guardrail needs metric, max_drop and direction."""

    id: str = Field(default_factory=new_id)
    project_id: str
    kind: GuardrailKind
    metric: str | None = None
    max_drop: float | None = Field(default=None, ge=0)
    direction: Direction | None = None
    drop_unit: DropUnit = DropUnit.relative
    """How ``max_drop`` is read (D38); only a ``metric_bound`` may change it."""
    description: str
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _metric_bound_is_complete(self) -> Self:
        if self.kind is GuardrailKind.metric_bound and (
            self.metric is None or self.max_drop is None or self.direction is None
        ):
            raise ValueError(
                "metric_bound guardrails need metric, max_drop and direction"
            )
        if (
            self.kind is not GuardrailKind.metric_bound
            and self.drop_unit is not DropUnit.relative
        ):
            raise ValueError("drop_unit applies to metric_bound guardrails only")
        return self


# ---------------------------------------------------------------------------
# Measurements
# ---------------------------------------------------------------------------


class RunStats(EngineModel):
    """Summary statistics over repeated runs of one metric."""

    n: int = Field(ge=1)
    mean: float
    stdev: float = Field(ge=0)
    min: float
    max: float
    unit: str

    @classmethod
    def from_samples(cls, samples: Sequence[float], unit: str) -> Self:
        """Build stats from raw samples (sample stdev; 0.0 for a single sample)."""
        values = [float(sample) for sample in samples]
        if not values:
            raise ValueError("RunStats needs at least one sample")
        spread = statistics.stdev(values) if len(values) > 1 else 0.0
        return cls(
            n=len(values),
            mean=statistics.fmean(values),
            stdev=spread,
            min=min(values),
            max=max(values),
            unit=unit,
        )


class Measurement(EngineModel):
    """One metric measured over N runs of a workload, for the baseline or a trial."""

    id: str = Field(default_factory=new_id)
    workload_id: str
    trial_id: str | None = None
    metric: str = Field(min_length=1)
    stats: RunStats
    samples: tuple[float, ...] = Field(min_length=1)
    output_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    raw_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    """The exact-bytes fingerprint (D39): equal to ``output_fingerprint``
    without a tolerance; ``None`` when the runs agreed only within one. Scores
    are cached by it, so a ``None`` row is scored uncached (D37)."""
    hardware: ScalarDict = Field(default_factory=dict)
    measured_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _samples_match_stats(self) -> Self:
        if len(self.samples) != self.stats.n:
            raise ValueError("samples length must equal stats.n")
        return self


class Baseline(EngineModel):
    """The reference every trial is judged against."""

    commit: str | None = None
    measurements: tuple[Measurement, ...] = ()
    objectives: tuple[Objective, ...] = ()
    guardrails: tuple[Guardrail, ...] = ()
    measured_at: datetime = Field(default_factory=utc_now)
    calibration: NoiseCalibration | None = None
    """The per-project noise floor (D41 c); ``None``: none was measured."""
    quality_files: tuple[FrozenFile, ...] = ()
    """The quality check's frozen files at the base commit (D37)."""

    @field_validator("quality_files")
    @classmethod
    def _each_quality_file_once(
        cls, value: tuple[FrozenFile, ...]
    ) -> tuple[FrozenFile, ...]:
        _unique_project_files("quality_files", [frozen.path for frozen in value])
        return value


class Hotspot(EngineModel):
    """Where time or memory goes, as found by the profiler."""

    id: str = Field(default_factory=new_id)
    project_id: str
    workload_id: str
    file_path: str
    symbol: str
    line_start: int | None = None
    line_end: int | None = None
    self_time_s: float = Field(ge=0)
    total_time_s: float = Field(ge=0)
    share: float = Field(ge=0, le=1)
    calls: int | None = None
    memory_bytes: int | None = None
    tags: tuple[str, ...] = ()

    @field_validator("file_path")
    @classmethod
    def _file_path_inside_project(cls, value: str) -> str:
        return _project_file("file_path", value)


# ---------------------------------------------------------------------------
# Research: techniques, papers, claims
# ---------------------------------------------------------------------------


class Precondition(EngineModel):
    """When a technique or claim applies. ``check`` is a machine key the matcher evaluates."""

    id: str = Field(default_factory=new_id)
    description: str
    check: str = Field(min_length=1)
    required: bool = True


class Technique(EngineModel):
    """A playbook entry: a known technique with preconditions and expected gain."""

    id: str = Field(default_factory=new_id)
    slug: str = Field(min_length=1)
    name: str
    summary: str
    change_class: ChangeClass
    preconditions: tuple[Precondition, ...] = ()
    expected_gain: float = Field(ge=0)
    provability: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    references: tuple[str, ...] = ()


class Claim(EngineModel):
    """One verifiable statement extracted from a paper."""

    id: str = Field(default_factory=new_id)
    paper_id: str
    statement: str
    expected_gain: float | None = Field(default=None, ge=0)
    preconditions: tuple[Precondition, ...] = ()
    confidence: float = Field(ge=0, le=1)
    evidence: str | None = None


class Paper(EngineModel):
    """A research paper and the claims extracted from it."""

    id: str = Field(default_factory=new_id)
    arxiv_id: str | None = None
    doi: str | None = None
    title: str
    authors: tuple[str, ...] = ()
    abstract: str = ""
    published: date | None = None
    pdf_url: str | None = None
    claims: tuple[Claim, ...] = ()

    @field_validator("pdf_url")
    @classmethod
    def _https_only(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("pdf_url must use https")
        return value


# ---------------------------------------------------------------------------
# Hypotheses, trials, judgements
# ---------------------------------------------------------------------------


class Hypothesis(EngineModel):
    """A ranked idea for improving specific hotspots."""

    id: str = Field(default_factory=new_id)
    project_id: str
    hotspot_ids: tuple[str, ...] = ()
    source: HypothesisSource
    technique_id: str | None = None
    claim_id: str | None = None
    lesson_ids: tuple[str, ...] = ()
    title: str
    rationale: str
    change_class: ChangeClass
    expected_gain: float = Field(ge=0)
    provability: float = Field(ge=0, le=1)
    risk: float = Field(ge=0, le=1)
    score: float = 0.0
    status: HypothesisStatus = HypothesisStatus.proposed
    parked_reason: str | None = Field(default=None, min_length=1)
    """Why a generated idea was parked instead of trialled (Step 3, D9)."""
    tags: tuple[str, ...] = Field(default=(), max_length=MAX_HYPOTHESIS_TAGS)
    """Engine facts (``lane:``, ``review:``) and model claims (``claimed_``)
    from the idea pipeline (Step 3 Wave 2, D57); recorded, read by nothing yet.
    Each matches ``HYPOTHESIS_TAG`` whole, so no tag carries free text."""

    @field_validator("tags")
    @classmethod
    def _tags_match_the_pattern(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [tag for tag in value if HYPOTHESIS_TAG.fullmatch(tag) is None]
        if bad:
            shown = [tag[:80] for tag in bad[:3]]
            raise ValueError(f"tags must match {HYPOTHESIS_TAG.pattern}: {shown}")
        return value


class JudgeResult(EngineModel):
    """What one judge concluded about one trial."""

    judge: str
    outcome: JudgeOutcome
    metric: str | None = None
    baseline: RunStats | None = None
    trial: RunStats | None = None
    gain: float | None = None
    noise_floor: float | None = None
    reason: str
    details: ScalarDict = Field(default_factory=dict)
    output_changed: bool | None = None
    """Set by the equivalence judge in quality mode (D35); ``None`` elsewhere."""


class Violation(EngineModel):
    """An anti-cheating rule the trial broke. Any violation rejects the trial."""

    rule: ViolationRule
    path: str | None = None
    pattern: str | None = None
    message: str


class Trial(EngineModel):
    """One attempt at a hypothesis, in its own worktree, with its measurements.

    ``commit`` is the measured trial commit (``None`` until committed).
    ``violations`` are capture-time problems only the runner can see in the
    git diff (modes, binaries, git metadata, unrecorded writes, the D37
    tripwire); a trial with any is ``failed`` and never executed. The one
    runtime rule, ``child_processes`` (D62, N0c), fails a measured trial and
    keeps its rows. The judges
    node also adds a measured paired trial's incomplete base rows here with a
    "paired base: " prefix, which rejects it.

    ``attempts`` counts editor attempts (2 after a fix retry, D12);
    ``retry_notes`` says why a retry ran or did not ("not retried: the
    run's fix retry is spent").
    """

    id: str = Field(default_factory=new_id)
    hypothesis_id: str
    round: int = Field(ge=1)
    worktree_path: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    commit: str | None = None
    diff: str = ""
    touched_paths: tuple[str, ...] = ()
    violations: tuple[Violation, ...] = ()
    status: TrialStatus = TrialStatus.pending
    measurements: tuple[Measurement, ...] = ()
    judge_results: tuple[JudgeResult, ...] = ()
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    attempts: int = Field(default=1, ge=1)
    retry_notes: tuple[str, ...] = ()
    base_measurements: tuple[Measurement, ...] = ()
    """The paired base (A) rows measured alternately with this trial (D41 a);
    empty: judged against the run baseline (Step 2)."""


class Verdict(EngineModel):
    """The engine's decision about a trial, derived from judges and violations."""

    id: str = Field(default_factory=new_id)
    trial_id: str
    hypothesis_id: str
    outcome: VerdictOutcome
    change_class: ChangeClass
    judge_results: tuple[JudgeResult, ...] = ()
    violations: tuple[Violation, ...] = ()
    gain: float | None = None
    summary: str
    decided_at: datetime = Field(default_factory=utc_now)
    approved_by: str | None = None
    approval_note: str | None = None
    confirmations: int = Field(default=1, ge=1)
    """Looks that passed (D42): 2 once the confirmation re-test held (D41 b)."""
    confirmed_gain: float | None = None
    """The confirmation look's primary gain; set only with a confirmation."""

    @model_validator(mode="after")
    def _a_confirmed_gain_needs_a_confirmation(self) -> Self:
        if self.confirmed_gain is not None and self.confirmations < 2:
            raise ValueError("confirmed_gain needs at least 2 confirmations")
        return self


class NoiseCheck(EngineModel):
    """Result of comparing a gain against the measured noise floor."""

    gain_abs: float
    gain_rel: float
    floor_abs: float
    floor_rel: float
    passed: bool


# ---------------------------------------------------------------------------
# Delivery, learning, approval, events
# ---------------------------------------------------------------------------


class Delivery(EngineModel):
    """What the engine hands back: a branch or PR plus a report, never the default branch."""

    id: str = Field(default_factory=new_id)
    project_id: str
    kind: DeliveryKind
    branch: str | None = None
    commit: str | None = None
    pr_url: str | None = None
    verdict_ids: tuple[str, ...] = ()
    combined_diff: str = ""
    report_markdown: str
    delivered_at: datetime = Field(default_factory=utc_now)


class Lesson(EngineModel):
    """What a verdict taught the engine; feeds the next hypothesis ranking."""

    id: str = Field(default_factory=new_id)
    project_id: str | None = None
    verdict_id: str | None = None
    hypothesis_id: str | None = None
    technique_id: str | None = None
    context: tuple[str, ...] = ()
    outcome: VerdictOutcome
    gain: float | None = None
    text: str
    weight: float = Field(default=1.0, gt=0)
    created_at: datetime = Field(default_factory=utc_now)


class ApprovalItem(EngineModel):
    verdict_id: str
    title: str
    change_class: ChangeClass
    gain: float | None = None
    summary: str


class ApprovalRequest(EngineModel):
    """Carried by the LangGraph interrupt: what the human must decide.

    ``error`` is set when the gate asks again because the previous resume
    payload was not a valid ``ApprovalDecision``.
    """

    run_id: str
    items: tuple[ApprovalItem, ...] = ()
    message: str
    error: str | None = None


class ApprovalDecision(EngineModel):
    """The human's answer, passed back through ``Command(resume=...)``."""

    approved_verdict_ids: tuple[str, ...] = ()
    rejected_verdict_ids: tuple[str, ...] = ()
    approver: str
    note: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _ids_are_disjoint(self) -> Self:
        overlap = set(self.approved_verdict_ids) & set(self.rejected_verdict_ids)
        if overlap:
            raise ValueError(f"verdicts both approved and rejected: {sorted(overlap)}")
        return self


class EngineEvent(EngineModel):
    """One line of the live log."""

    run_id: str
    phase: RunPhase
    level: EventLevel = EventLevel.info
    message: str
    at: datetime = Field(default_factory=utc_now)
    data: ScalarDict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step 2: pricing, understanding, combination
# ---------------------------------------------------------------------------


class LongContextPrice(EngineModel):
    """The rates a request pays once its prompt is over ``threshold_tokens``.

    Pricing page, "Long context pricing" (platform.claude.com, read
    2026-10-23), for Claude Haiku 5.5: a request whose prompt is over 100,000
    tokens pays the higher prices; the prompt counts all of its input tokens,
    cache reads and cache writes included; each request is priced on its own,
    and the long row prices every component, output included. Same units and
    meaning per field as ``ModelPrice``.
    """

    threshold_tokens: int = Field(ge=0, strict=True)
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_write: float = Field(ge=0)
    cache_read: float = Field(ge=0)


class ModelPrice(EngineModel):
    """What one Claude model bills, in USD per million tokens.

    ``cache_write`` is the 5-minute cache-write rate (the engine never asks
    for the 1-hour TTL); ``cache_read`` the cache-hit rate. ``long_context``
    replaces all four for a request whose prompt is over its threshold;
    ``None`` means one price at every prompt length.
    """

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_write: float = Field(ge=0)
    cache_read: float = Field(ge=0)
    long_context: LongContextPrice | None = None


class CandidateModule(EngineModel):
    """A module the understand node expects to be hot, with its reason."""

    path: str
    reason: str

    @field_validator("path")
    @classmethod
    def _path_inside_project(cls, value: str) -> str:
        return _project_file("path", value)


class ProjectUnderstanding(EngineModel):
    """What the understand node learned about the project at the base commit.

    ``workload_notes`` maps a workload id to one line about it.
    ``served_by_model`` is the model that actually answered (a fallback may
    have served the request).
    """

    language: str
    summary: str = Field(max_length=1500)
    entrypoints: tuple[str, ...] = ()
    workload_notes: dict[str, str] = Field(default_factory=dict)
    candidate_modules: tuple[CandidateModule, ...] = Field(default=(), max_length=10)
    served_by_model: str
    quality_proposal: QualityProposal | None = None
    """A suggested quality check, reported as not active (D40)."""


class CombineSkip(EngineModel):
    """A kept change the greedy combine could not apply, and why."""

    trial_id: str
    reason: str
    paths: tuple[str, ...] = ()


class Combination(EngineModel):
    """The kept changes merged onto the base commit and re-judged together.

    ``holds`` is true iff ``derive_verdict`` returned ``keep`` for the tested
    tip. ``fallback_trial_id`` names the single best change re-tested after
    the combination failed (``None`` when no fallback ran). ``summary``
    records the greedy result, the fallback attempt and the final outcome.
    """

    base_commit: str
    tip_commit: str | None = None
    applied_trial_ids: tuple[str, ...] = ()
    skipped: tuple[CombineSkip, ...] = ()
    judge_results: tuple[JudgeResult, ...] = ()
    holds: bool
    fallback_trial_id: str | None = None
    summary: str


class TechniqueMatchRecord(EngineModel):
    """A playbook technique the matcher found fitting (Step 3, matched mode).

    The state's copy of ``research.playbook.TechniqueMatch``; ``unmet_preconditions``
    holds precondition ``check`` keys of that technique.
    """

    slug: str = Field(min_length=1)
    fit: float = Field(ge=0, le=1)
    justification_summary: str
    unmet_preconditions: tuple[str, ...] = ()


ENGINE_MODEL_CLASSES: tuple[type[EngineModel], ...] = (
    Project,
    Workload,
    Objective,
    Guardrail,
    RunStats,
    Measurement,
    Baseline,
    Hotspot,
    Precondition,
    Technique,
    Claim,
    Paper,
    Hypothesis,
    JudgeResult,
    Violation,
    Trial,
    Verdict,
    NoiseCheck,
    Delivery,
    Lesson,
    ApprovalItem,
    ApprovalRequest,
    ApprovalDecision,
    EngineEvent,
    LongContextPrice,
    ModelPrice,
    CandidateModule,
    ProjectUnderstanding,
    CombineSkip,
    Combination,
    TechniqueMatchRecord,
    OutputTolerance,
    QualityCheck,
    QualityProposal,
    FrozenFile,
    NoiseCalibration,
)
"""Every model that may appear in checkpointed state (checkpointer allowlist)."""

ENGINE_SERDE_ALLOWLIST: tuple[type, ...] = (*ENGINE_MODEL_CLASSES, *ENGINE_ENUM_CLASSES)
"""Pass to ``JsonPlusSerializer(allowed_msgpack_modules=...)`` for the checkpointer."""
