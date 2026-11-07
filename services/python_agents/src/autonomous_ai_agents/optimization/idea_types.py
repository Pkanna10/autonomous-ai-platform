"""The idea pipeline's own frozen types (Step 3 Wave 2, N1a; spec amendment 3.3).

The enums name what a lane is (``Lane``), what a model may claim about an
idea (``Mechanism``, ``MorphCell``, ``Tier``, ``Typicality``) and what the
reviewer may answer (``ReviewVerdict``, ``ReviewReason``). The models carry
the code context the generator reads at the base commit (``FunctionSpan``,
``CodeDocument``, ``CodeContext``; D44), one validated idea with the facts
the engine derives for it (``IdeaCandidate``, ``Anchor``; D50-D52) and what
one pipeline call reports besides its hypotheses (``GenerateEvent``,
``IdeaStats``; D65).

None of them enters the checkpointed state: they cross one generator call,
and only the ``Hypothesis`` built from a candidate (with its ``tags``, D57)
travels on. So they are not in ``ENGINE_SERDE_ALLOWLIST``.

The quarantine (G3): a rule-relaxing lane (``RELAXING_LANES``) lifts one
frozen rule (``RelaxedRule``), so its ideas are proposals. An
``IdeaCandidate``'s ``proposal`` is its lane's rule, tied to the lane by the
validator and kept by every copy (``model_copy`` validates again); on a
``Hypothesis`` a ``proposal:<rule>`` tag or a relaxing lane's ``lane:`` tag
quarantines it (``is_proposal``), so losing one of the two is not enough.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Self

from pydantic import Field, field_validator, model_validator

from autonomous_ai_agents.common.models import (
    ChangeClass,
    EngineModel,
    EventLevel,
    Hypothesis,
    ScalarDict,
)


class Lane(StrEnum):
    """Where an idea came from: S1, one of six lenses, the leap (D45-D47) or a
    rule-relaxing lane (G3, ``RELAXING_LANES``)."""

    obvious = "obvious"
    eliminate = "eliminate"
    assume_less = "assume_less"
    name_the_problem = "name_the_problem"
    recombine = "recombine"
    resolve_tradeoff = "resolve_tradeoff"
    far = "far"
    leap = "leap"
    relax_dependency = "relax_dependency"
    relax_output_order = "relax_output_order"
    relax_precompute = "relax_precompute"
    relax_api = "relax_api"


class RelaxedRule(StrEnum):
    """The frozen rule a rule-relaxing lane lifts (G3); its ideas are proposals."""

    new_dependency = "new_dependency"
    output_order = "output_order"
    install_precompute = "install_precompute"
    api_change = "api_change"


RELAXING_LANES: Final[Mapping[Lane, RelaxedRule]] = MappingProxyType({
    Lane.relax_dependency: RelaxedRule.new_dependency,
    Lane.relax_output_order: RelaxedRule.output_order,
    Lane.relax_precompute: RelaxedRule.install_precompute,
    Lane.relax_api: RelaxedRule.api_change,
})  # fmt: skip
"""The rule-relaxing lanes and the rule each lifts (G3): never lenses, off
unless ``IDEAS_RELAX_LANES`` names them."""
PROPOSAL_TAG: Final = "proposal"
"""The ``Hypothesis.tags`` key of a quarantined idea: ``proposal:<rule>``."""
_RELAXING_LANE_TAGS: Final = {f"lane:{lane.value}": rule
                              for lane, rule in RELAXING_LANES.items()}  # fmt: skip


def proposal_tag(rule: RelaxedRule) -> str:
    return f"{PROPOSAL_TAG}:{rule.value}"


def relaxed_rules(hypothesis: Hypothesis) -> tuple[str, ...]:
    """The rules a hypothesis's tags say it relaxes, in tag order: each
    ``proposal:`` value (any value: fail closed) and each relaxing lane's
    rule. Non-empty means quarantined (G3)."""
    found: list[str] = []
    for tag in hypothesis.tags:
        key, _, value = tag.partition(":")
        rule = value if key == PROPOSAL_TAG else _RELAXING_LANE_TAGS.get(tag)
        if rule is not None and rule not in found:
            found.append(rule)
    return tuple(found)


def is_proposal(hypothesis: Hypothesis) -> bool:
    """Whether ``hypothesis`` is a quarantined proposal (G3): it then runs
    only in the proposals path, never trialled, delivered or counted."""
    return bool(relaxed_rules(hypothesis))


LENS_LANES: Final[tuple[Lane, ...]] = (
    Lane.eliminate,
    Lane.assume_less,
    Lane.name_the_problem,
    Lane.recombine,
    Lane.resolve_tradeoff,
    Lane.far,
)
"""The six lens lanes, evidence-ranked (D46): ``IDEAS_LENSES``'s default."""


class Mechanism(StrEnum):
    remove_work = "remove_work"
    precompute_or_cache = "precompute_or_cache"
    data_structure = "data_structure"
    algorithm = "algorithm"
    loop_or_control_flow = "loop_or_control_flow"
    lazy_or_streaming = "lazy_or_streaming"
    batching = "batching"
    specialised_fast_path = "specialised_fast_path"
    representation = "representation"
    allocation_or_copying = "allocation_or_copying"
    io_or_serialisation = "io_or_serialisation"
    other = "other"


MORPH_DIMENSIONS: Final = (
    "work",
    "timing",
    "granularity",
    "representation",
    "algorithm",
    "memory",
)
"""The six Bentley-style dimensions of ``MorphCell``, three cells each."""


class MorphCell(StrEnum):
    """``<dimension>:<cell>``; ``morph_cells[0]`` is an idea's primary cell."""

    work_eliminate = "work:eliminate"
    work_reuse = "work:reuse"
    work_defer = "work:defer"
    timing_precompute = "timing:precompute"
    timing_lazy = "timing:lazy"
    timing_incremental = "timing:incremental"
    granularity_batch = "granularity:batch"
    granularity_stream = "granularity:stream"
    granularity_fuse = "granularity:fuse"
    representation_compact = "representation:compact"
    representation_indexed = "representation:indexed"
    representation_specialised_type = "representation:specialised_type"
    algorithm_lower_complexity = "algorithm:lower_complexity"
    algorithm_better_constant = "algorithm:better_constant"
    algorithm_approximate_then_verify = "algorithm:approximate_then_verify"
    memory_cache_across_calls = "memory:cache_across_calls"
    memory_reuse_buffers = "memory:reuse_buffers"
    memory_drop_early = "memory:drop_early"


class Tier(StrEnum):
    combinational = "combinational"
    exploratory = "exploratory"
    transformational = "transformational"


class Typicality(StrEnum):
    common = "common"
    uncommon = "uncommon"
    rare = "rare"


class ReviewVerdict(StrEnum):
    feasible = "feasible"
    unknown = "unknown"
    infeasible = "infeasible"


class ReviewReason(StrEnum):
    none = "none"
    violates_constraint = "violates_constraint"
    precondition_false = "precondition_false"
    output_not_identical = "output_not_identical"
    duplicate_of = "duplicate_of"
    outside_hot_path = "outside_hot_path"


_Text = Annotated[str, Field(min_length=1)]
_Line = Annotated[int, Field(ge=1)]
_Unit = Annotated[float, Field(ge=0, le=1)]
_Count = Annotated[int, Field(ge=0)]


class FunctionSpan(EngineModel):
    """A ``def`` or ``class`` body found by ``ast`` (lines 1-based, inclusive)."""

    path: _Text
    qualname: _Text
    start_line: _Line
    end_line: _Line
    hotspot_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line {self.end_line} is before start_line {self.start_line}"
            )
        return self


class CodeDocument(EngineModel):
    """One shown file (or its shown lines): the line-numbered ``rendered``
    text sent to the model, the ``raw`` text the grounding check searches
    (same escaping), its hot function spans and its base spawn findings."""

    path: _Text
    start_line: _Line
    end_line: _Line
    rendered: str
    raw: str
    spans: tuple[FunctionSpan, ...] = ()
    spawn_findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _spans_inside(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line {self.end_line} is before start_line {self.start_line}"
            )
        for span in self.spans:
            inside = (
                self.start_line <= span.start_line <= span.end_line <= (self.end_line)
            )
            if span.path != self.path or not inside:
                raise ValueError(
                    f"span {span.qualname!r} ({span.path}:{span.start_line}-"
                    f"{span.end_line}) is not inside {self.path}:"
                    f"{self.start_line}-{self.end_line}"
                )
        return self


class CodeContext(EngineModel):
    """S0's output (D44): the shown documents, hottest first, each path once;
    each workload's profiled total time (for the Amdahl ceiling, D51)."""

    documents: tuple[CodeDocument, ...] = ()
    totals_by_workload: dict[str, Annotated[float, Field(ge=0)]] = Field(
        default_factory=dict
    )
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _each_path_once(self) -> Self:
        paths = [document.path for document in self.documents]
        repeated = sorted({path for path in paths if paths.count(path) > 1})
        if repeated:
            raise ValueError(f"each document path must appear once: {repeated}")
        return self


class Anchor(EngineModel):
    """The innermost shown hot function a grounded quote lies in (D50)."""

    path: _Text
    qualname: _Text


class IdeaCandidate(EngineModel):
    """One lane idea after schema validation, with the engine's facts.

    ``id`` is engine-assigned; ``lane`` comes from the request, never from
    the model. ``hotspot_ids`` are the resolved listed hotspots; ``anchor``,
    ``ceiling`` (the Amdahl ceiling, a share), ``review`` and ``plan`` stay
    ``None`` until the stage that derives them.
    """

    id: _Text
    lane: Lane
    title: _Text
    technique_slug: str | None = None
    hotspot_ids: tuple[str, ...] = ()
    change_summary: str
    justification_summary: str
    change_class: ChangeClass
    expected_gain: float = Field(ge=0)
    provability: _Unit
    risk: _Unit
    depends_on_path: str
    depends_on_quote: str
    precondition: str
    equivalence_summary: str
    mechanism: Mechanism
    morph_cells: tuple[MorphCell, ...] = Field(min_length=1, max_length=3)
    tier: Tier
    typicality: Typicality
    anchor: Anchor | None = None
    ceiling: _Unit | None = None
    review: ReviewVerdict | None = None
    plan: str | None = None
    proposal: RelaxedRule | None = None
    """The rule a rule-relaxing lane's idea relaxes (G3), set by the lane at
    birth and tied to it here; never read from a reply. Not ``None``: a
    quarantined proposal."""

    @model_validator(mode="after")
    def _proposal_is_the_lanes(self) -> Self:
        expected = RELAXING_LANES.get(self.lane)
        if self.proposal is not expected:
            raise ValueError(
                f"proposal must be {None if expected is None else expected.value!r}"
                f" for the {self.lane.value} lane, not "
                f"{None if self.proposal is None else self.proposal.value!r}"
            )
        return self

    def model_copy(
        self, *, update: Mapping[str, object] | None = None, deep: bool = False
    ) -> Self:
        """A copy validated again, so no copy can clear, change or orphan
        ``proposal`` (pydantic's own ``model_copy`` skips validation)."""
        copied = super().model_copy(update=update, deep=deep)
        return self.model_validate(dict(copied))


_EVENT_CODE: Final = re.compile(r"[a-z][a-z_]{0,39}")


class GenerateEvent(EngineModel):
    """An event the node emits after ``generated`` with its code and level
    (D65): ``discovery_unaffordable`` (warning), ``idea_dropped`` (info)."""

    code: str
    message: _Text
    level: EventLevel = EventLevel.info
    data: ScalarDict = Field(default_factory=dict)

    @field_validator("code")
    @classmethod
    def _a_word(cls, value: str) -> str:
        if _EVENT_CODE.fullmatch(value) is None:
            raise ValueError(f"code must match {_EVENT_CODE.pattern}")
        return value

    @field_validator("data")
    @classmethod
    def _code_is_the_events_own(cls, value: ScalarDict) -> ScalarDict:
        if "code" in value:  # the node writes data["code"] from ``code``
            raise ValueError("data must not hold a 'code' key")
        return value


class IdeaStats(EngineModel):
    """What one pipeline call counted (D65), for the ``ideas-probe`` harness;
    today's generator reports none (``GenerateResult.stats is None``)."""

    ideas_per_lane: dict[Lane, _Count] = Field(default_factory=dict)
    grounded: _Count = 0
    anchored: _Count = 0
    gate_passed: _Count = 0
    non_obvious: _Count = 0
    review_verdicts: dict[ReviewVerdict, _Count] = Field(default_factory=dict)
    unique_signatures: _Count = 0
    cost_usd: float = Field(default=0.0, ge=0)
    cache_read_tokens: _Count = 0
    stop_reasons: dict[str, str | None] = Field(default_factory=dict)
    """Each request's ``stop_reason`` by its stage or lane label."""
