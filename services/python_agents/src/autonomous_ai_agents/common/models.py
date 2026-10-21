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
import statistics
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import PurePath
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autonomous_ai_agents.common.paths import normalize_path

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

JsonScalar = str | int | float | bool | None
ScalarDict = dict[str, JsonScalar]


def new_id() -> str:
    """Return a fresh uuid4 as a string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return the current time as a tz-aware UTC datetime."""
    return datetime.now(UTC)


class EngineModel(BaseModel):
    """Base for every engine model: frozen, strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


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
    tests_pass = "tests_pass"
    metric_bound = "metric_bound"


class ChangeClass(StrEnum):
    """Drives autonomy: efficiency ships, behaviour is flagged, novel needs approval."""

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


class ViolationRule(StrEnum):
    protected_path = "protected_path"
    path_traversal = "path_traversal"
    too_few_runs = "too_few_runs"
    fingerprint_mismatch = "fingerprint_mismatch"
    missing_fingerprint = "missing_fingerprint"


class DeliveryKind(StrEnum):
    branch = "branch"
    pull_request = "pull_request"
    report_only = "report_only"


class EventLevel(StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


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
)
"""Every engine enum. Checkpoint deserialisation must allow these too, or
``state["phase"]`` comes back as a plain string after a resume."""


# ---------------------------------------------------------------------------
# Project, workloads, objectives, guardrails
# ---------------------------------------------------------------------------


class Project(EngineModel):
    """A codebase the engine improves. Long-lived across runs."""

    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1)
    root_path: str
    default_branch: str = "main"
    language: str = "python"
    hardware: ScalarDict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("root_path")
    @classmethod
    def _absolute_without_parent_segments(cls, value: str) -> str:
        if not os.path.isabs(value) or ".." in PurePath(value).parts:
            raise ValueError("root_path must be absolute and must not contain '..'")
        return value


class Workload(EngineModel):
    """Something the engine can run and time: an argv command, never a shell string."""

    id: str = Field(default_factory=new_id)
    project_id: str
    name: str = Field(min_length=1)
    command: tuple[str, ...] = Field(min_length=1)
    working_dir: str = "."
    entrypoint: str | None = None
    inputs: ScalarDict = Field(default_factory=dict)
    timeout_s: float = Field(default=600.0, gt=0)
    warmup_runs: int = Field(default=1, ge=0)
    runs: int = Field(default=MIN_RUNS, ge=MIN_RUNS)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("working_dir")
    @classmethod
    def _working_dir_inside_project(cls, value: str) -> str:
        return normalize_path(value)


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
    output_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
        return normalize_path(value)


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


class Violation(EngineModel):
    """An anti-cheating rule the trial broke. Any violation rejects the trial."""

    rule: ViolationRule
    path: str | None = None
    pattern: str | None = None
    message: str


class Trial(EngineModel):
    """One attempt at a hypothesis, in its own worktree, with its measurements."""

    id: str = Field(default_factory=new_id)
    hypothesis_id: str
    round: int = Field(ge=1)
    worktree_path: str | None = None
    branch: str | None = None
    base_commit: str | None = None
    diff: str = ""
    touched_paths: tuple[str, ...] = ()
    status: TrialStatus = TrialStatus.pending
    measurements: tuple[Measurement, ...] = ()
    judge_results: tuple[JudgeResult, ...] = ()
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    tokens_used: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


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
    """Carried by the LangGraph interrupt: what the human must decide."""

    run_id: str
    items: tuple[ApprovalItem, ...] = ()
    message: str


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
)
"""Every model that may appear in checkpointed state (checkpointer allowlist)."""

ENGINE_SERDE_ALLOWLIST: tuple[type, ...] = (*ENGINE_MODEL_CLASSES, *ENGINE_ENUM_CLASSES)
"""Pass to ``JsonPlusSerializer(allowed_msgpack_modules=...)`` for the checkpointer."""
