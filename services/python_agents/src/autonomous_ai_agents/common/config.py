"""Environment configuration management.

Loads configuration from environment variables using pydantic-settings.
Complex values (``MODEL_PRICING``, ``ENGINE_FALLBACK_MODELS``) are read as
JSON. Everything is validated at startup, so a bad knob fails at import
rather than in the middle of a run.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, Self, get_args
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from autonomous_ai_agents.common.models import (
    NOISE_CALIBRATION_BLOCKS_MAX,
    ChangeClass,
    LongContextPrice,
    ModelPrice,
)
from autonomous_ai_agents.common.refnames import branch_prefix_problem
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane

IsolationMode = Literal["required", "best_effort", "off"]
"""``required`` fails closed; ``best_effort`` records what was applied; ``off``."""

Effort = Literal["low", "medium", "high", "xhigh", "max"]
"""``output_config.effort`` levels, lowest first (the SDK's own literal)."""

Retrieval = Literal["blind", "matched"]
"""How research picks techniques for the generator (D1): ``blind`` shows the
context's techniques as they are; ``matched`` asks the matcher first."""

Role = Literal["engine", "editor", "generator", "matcher", "lane", "leap", "reviewer"]
"""A Claude role with its own model chain (``role_chain``); ``lane``, ``leap``
and ``reviewer`` are the idea pipeline's (Step 3 Wave 2, D58)."""

_LEVELS: Final[tuple[Effort, ...]] = get_args(Effort)
_ALL: Final = frozenset(_LEVELS)
_NO_XHIGH: Final = _ALL - {"xhigh"}

# The effort page (platform.claude.com/docs/en/build-with-claude/effort, read
# 2026-10-23): its supported-model list and the "Effort levels" table. max:
# every listed model but Opus 4.5; xhigh: Fable 5.1 / 5, Mythos 5.1 / 5, Opus
# 5.5 / 5 / 4.8 / 4.7, Sonnet 5.5 / 5 and Haiku 5.5 ("Not every model that
# supports max supports xhigh"). The per-model sections say Opus 5.5, Sonnet
# 5.5, Haiku 5.5 and Fable 5.1 "support all five effort levels". Opus 4.5
# (claude-opus-4-5-20251101) is on the page's supported-model list but in
# neither the max nor the xhigh row, so it takes low, medium and high only.
# The lookup is an exact model-id match, like MODEL_PRICING: a model missing
# here (an alias such as claude-opus-4-5 included) is refused any effort
# setting, since the docs list no levels for that id.
EFFORT_LEVELS: Final[Mapping[str, frozenset[Effort]]] = MappingProxyType(
    {
        **dict.fromkeys(
            (
                "claude-fable-5-1",
                "claude-mythos-5-1",
                "claude-fable-5",
                "claude-mythos-5",
                "claude-opus-5-5",
                "claude-opus-5",
                "claude-opus-4-8",
                "claude-opus-4-7",
                "claude-sonnet-5-5",
                "claude-sonnet-5",
                "claude-haiku-5-5",
            ),
            _ALL,
        ),
        **dict.fromkeys(
            ("claude-mythos-preview", "claude-opus-4-6", "claude-sonnet-4-6"),
            _NO_XHIGH,
        ),
        "claude-opus-4-5-20251101": frozenset(_LEVELS[:3]),
    }
)

_KIB = 1024
_MIB = 1024 * _KIB

# USD per million tokens. Sources: the claude-api skill, shared/models.md
# (Opus 5.5 $4/$20 with cache reads $0.20; Opus 5 at Opus 4.8's $5/$25;
# Haiku 5.5 $0.10/$0.50 for prompts of 100K tokens or fewer) and
# shared/prompt-caching.md (5-minute cache writes cost 1.25x input; cache
# reads ~0.1x input elsewhere); the pricing page, read 2026-10-23, for Sonnet
# 5.5 ($2/$10, cache hits 0.05x input: $0.10), Fable 5.1 ($10/$50, cache hits
# 0.025x input: $0.25) and Haiku 5.5's cache hits ($0.01). Haiku 5.5 alone has
# a long-context tier (pricing page, "Long context pricing"): a request whose
# prompt (every input token, cache reads and writes included) is over 100,000
# tokens pays $0.50 / $2.50, 5-minute writes $0.625 and hits $0.05 on all of
# its tokens; ``clients/cost.py`` applies it per attempt. Every other model
# bills one price across its whole context window.
_DEFAULT_PRICING: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(
        input=4.0, output=20.0, cache_write=5.0, cache_read=0.20
    ),
    "claude-opus-5": ModelPrice(
        input=5.0, output=25.0, cache_write=6.25, cache_read=0.50
    ),
    "claude-opus-4-8": ModelPrice(
        input=5.0, output=25.0, cache_write=6.25, cache_read=0.50
    ),
    "claude-sonnet-5-5": ModelPrice(
        input=2.0, output=10.0, cache_write=2.5, cache_read=0.10
    ),
    "claude-fable-5-1": ModelPrice(
        input=10.0, output=50.0, cache_write=12.5, cache_read=0.25
    ),
    "claude-haiku-5-5": ModelPrice(
        input=0.10,
        output=0.50,
        cache_write=0.125,
        cache_read=0.01,
        long_context=LongContextPrice(
            threshold_tokens=100_000,
            input=0.50,
            output=2.50,
            cache_write=0.625,
            cache_read=0.05,
        ),
    ),
}


GENERATOR_N_MAX: Final = 20
"""Most hypotheses one generation request asks for (``GENERATOR_N``)."""
MATCHER_K_MAX: Final = 20
"""Most techniques one match request returns (``MATCHER_K``)."""
GENERATOR_MAX_CALLS_MAX: Final = 5
"""Most generation requests a run may send (``GENERATOR_MAX_CALLS``)."""
FIX_RETRIES_MAX: Final = 1
"""Most self-retries, per trial and per run, until B-R2 lifts it (O8)."""
PORTFOLIO_ROUNDS_MAX: Final = 3
"""Most rounds a keep waits for before it ends exploration (D54): the default
``MAX_TRIAL_ROUNDS``, past which rule 4 of the router ends the run anyway."""
RETENTION_REQUIRED_MODELS: Final = frozenset(
    {"claude-fable-5-1", "claude-fable-5", "claude-mythos-5-1", "claude-mythos-5"}
)
"""Models whose use requires 30-day data retention (D63; the advisor-tool docs
name all four): refused in every role that sends repository text unless
``ALLOW_RETENTION_MODELS`` is set."""


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Configuration is loaded from:
    1. Environment variables
    2. .env file (if present)
    3. Default values (defined here)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # Ignore extra fields in .env
    )

    # ============================================
    # Anthropic API
    # ============================================
    ANTHROPIC_API_KEY: SecretStr | None = None
    """Anthropic API key. Optional; only ``AnthropicTransport`` reads its value.

    A ``SecretStr`` so it never appears in ``repr``, ``str`` or a JSON dump.
    A blank or whitespace-only value counts as no key."""

    @field_validator("ANTHROPIC_API_KEY", mode="before")
    @classmethod
    def _blank_key_is_no_key(cls, value: object) -> object:
        """``ANTHROPIC_API_KEY=`` in a .env or an empty CI secret means None."""
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if isinstance(raw, str) and not raw.strip():
            return None
        return value

    ENGINE_API_BASE_URL: str = "https://api.anthropic.com"
    """Where ``AnthropicTransport`` sends requests (and the key).

    The SDK would otherwise read ``ANTHROPIC_BASE_URL`` from the environment,
    which a host or a tool may set for its own use; the engine follows only
    this setting. It must be ``https`` with a host and no credentials."""

    @field_validator("ENGINE_API_BASE_URL")
    @classmethod
    def _https_base_url(cls, value: str) -> str:
        """Plain https with a host, so the key never travels in the clear."""
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
            raise ValueError(
                f"ENGINE_API_BASE_URL {value!r} must be an https URL with a host "
                "and no credentials"
            )
        return value

    # ============================================
    # Claude models used by the engine
    # ============================================
    ENGINE_MODEL: str = "claude-opus-5-5"
    """Model for understanding code, extracting claims and writing trial edits."""

    TRIAGE_MODEL: str = "claude-haiku-5-5"
    """Cheap model for high-volume work such as daily paper triage."""

    ENGINE_FALLBACKS: bool = True
    """Send ``ENGINE_FALLBACK_MODELS`` as the request's server-side fallbacks."""

    ENGINE_FALLBACK_MODELS: tuple[str, ...] = ("claude-opus-4-8",)
    """Fallback chain sent verbatim; the cost estimate prices the same chain.

    One fallback by default: the pre-send estimate assumes every model in the
    chain could bill a full response, so each extra model multiplies the
    worst case a request must fit under the run's cost cap.
    """

    MODEL_PRICING: dict[str, ModelPrice] = Field(
        default_factory=lambda: dict(_DEFAULT_PRICING)
    )
    """USD per MTok per model. Must price every model the engine may bill."""

    UNDERSTAND_MAX_TOKENS: int = Field(default=8000, ge=1)
    """``max_tokens`` for the understand request (thinking counts toward it)."""

    UNDERSTAND_EFFORT: Effort | None = None
    """``output_config.effort`` for the understand request; ``None`` sends no
    effort key, so the model's own default applies (``medium`` on Opus 5.5)."""

    EDITOR_EFFORT: Effort | None = None
    """``output_config.effort`` on every editor request; ``None`` sends no
    ``output_config``. One value for a whole conversation keeps the cache."""

    # ============================================
    # Step 3: discovery roles (D5, D1, D9, D7) and the editor model (D16)
    # ============================================
    GENERATOR_MODEL: str = "claude-sonnet-5-5"
    GENERATOR_EFFORT: Effort | None = "medium"
    GENERATOR_N: int = Field(default=5, ge=1, le=GENERATOR_N_MAX)
    GENERATOR_MAX_TOKENS: int = Field(default=16000, ge=1)
    GENERATOR_MAX_CALLS: int = Field(default=2, ge=0, le=GENERATOR_MAX_CALLS_MAX)
    MATCHER_MODEL: str = "claude-sonnet-5-5"
    MATCHER_EFFORT: Effort | None = "medium"
    MATCHER_K: int = Field(default=3, ge=1, le=MATCHER_K_MAX)
    RESEARCH_RETRIEVAL: Retrieval = "blind"
    GENERATED_CLASSES: tuple[ChangeClass, ...] = (
        ChangeClass.efficiency,
        ChangeClass.behaviour,
    )
    """Generated classes that enter rounds; any other is parked (never ``novel``)."""
    DISCOVERY_MAX_SHARE: float = Field(default=0.25, gt=0, lt=1, allow_inf_nan=False)
    """Most of ``max_cost`` discovery (generator and matcher) may spend (D7)."""
    EDITOR_MODEL: str | None = None
    """``None`` keeps ``ENGINE_MODEL`` with its fallbacks; a model runs alone."""

    # ============================================
    # Step 3 Wave 2: the idea pipeline (D43-D65), opt-in until E2 passes.
    # Only the factory reads these; with IDEA_PIPELINE off nothing changes.
    # ============================================
    IDEA_PIPELINE: bool = False
    """Build ``IdeaPipelineGenerator`` instead of today's generator (D43)."""
    IDEAS_DISCOVERY_MAX_SHARE: float = Field(
        default=0.40, gt=0, lt=1, allow_inf_nan=False
    )
    """The discovery share with the pipeline on (D55); at least today's."""
    PORTFOLIO_ROUNDS: int = Field(default=0, ge=0, le=PORTFOLIO_ROUNDS_MAX)
    """Rounds before a keep ends exploration (D54); 0 keeps today's router."""
    IDEAS_LANE_MODEL: str = "claude-sonnet-5-5"
    IDEAS_LANE_EFFORT: Effort | None = "medium"
    IDEAS_LANE_MAX_TOKENS: int = Field(default=12000, ge=1)
    IDEAS_LANE_N: int = Field(default=6, ge=1, le=10)
    IDEAS_LENSES: tuple[Lane, ...] = LENS_LANES
    IDEAS_LANE_WORKERS: int = Field(default=4, ge=1, le=8)
    IDEAS_LEAP_MODEL: str = "claude-opus-5-5"
    IDEAS_LEAP_EFFORT: Effort | None = "high"
    IDEAS_LEAP_MAX_TOKENS: int = Field(default=12000, ge=1)
    IDEAS_LEAP_N: int = Field(default=3, ge=0, le=5)
    """Ideas from the leap lane; 0 skips the lane (D47)."""
    IDEAS_REVIEWER_MODEL: str = "claude-opus-5-5"
    IDEAS_REVIEWER_EFFORT: Effort | None = "high"
    IDEAS_REVIEWER_MAX_TOKENS: int = Field(default=16000, ge=1)
    IDEAS_REVIEW: bool = True
    """Off skips the reviewer: every idea ``unknown``, no plans (D49)."""
    IDEAS_REVIEW_MAX_IDEAS: int = Field(default=16, ge=1, le=48)
    """Most ideas the reviewer sees (D64); at least ``GENERATOR_N``."""
    IDEAS_HOT_FUNCTIONS: int = Field(default=8, ge=1, le=30)
    """Hot functions shown, by cumulative time (D44); 30 is ``MAX_HOTSPOTS``."""
    IDEAS_MAX_FILES: int = Field(default=8, ge=1, le=20)
    IDEAS_FILE_MAX_BYTES: int = Field(default=24 * _KIB, ge=1 * _KIB)
    """Below it a whole file is shown (D44)."""
    IDEAS_CODE_MAX_BYTES: int = Field(default=64 * _KIB, ge=1)
    """Rendered code per call, line prefixes included (D44, D55)."""
    IDEAS_PARSE_MAX_BYTES: int = Field(default=512 * _KIB, ge=1)
    """Most of a file S0 reads to parse it; past it, unparsable (D44)."""
    IDEAS_AMDAHL_MULTIPLIER: float = Field(default=1.0, ge=1.0, allow_inf_nan=False)
    """An idea's ceiling must reach this times the floor (D51)."""
    IDEAS_PORTFOLIO_MIN: int = Field(default=3, ge=1, le=10)
    IDEAS_PORTFOLIO_MAX: int = Field(default=5, ge=1, le=10)
    ALLOW_RETENTION_MODELS: bool = False
    """Admit ``RETENTION_REQUIRED_MODELS`` in repository-text roles (D63).
    Set only by the live harness, for fixture and pinned-OSS repositories."""

    @field_validator("IDEAS_LENSES")
    @classmethod
    def _lenses_are_distinct_lens_lanes(
        cls, value: tuple[Lane, ...]
    ) -> tuple[Lane, ...]:
        """A non-empty subset of the six lenses, each once (D46)."""
        if (
            not value
            or len(set(value)) != len(value)
            or not set(value) <= set(LENS_LANES)
        ):
            names = ", ".join(lane.value for lane in LENS_LANES)
            raise ValueError(
                f"IDEAS_LENSES must name each lens at most once, from {names}; "
                f"got {[lane.value for lane in value]}"
            )
        return value

    @model_validator(mode="after")
    def _idea_bounds_are_consistent(self) -> Self:
        """Byte caps in order and min <= max always; the knobs that bound
        against today's settings only with the pipeline on, so no setting
        valid with it off is refused (D43)."""
        problems = []
        if self.IDEAS_CODE_MAX_BYTES < self.IDEAS_FILE_MAX_BYTES:
            problems.append("IDEAS_CODE_MAX_BYTES must be >= IDEAS_FILE_MAX_BYTES")
        if self.IDEAS_PARSE_MAX_BYTES < self.IDEAS_FILE_MAX_BYTES:
            problems.append("IDEAS_PARSE_MAX_BYTES must be >= IDEAS_FILE_MAX_BYTES")
        if self.IDEAS_PORTFOLIO_MIN > self.IDEAS_PORTFOLIO_MAX:
            problems.append("IDEAS_PORTFOLIO_MIN must be <= IDEAS_PORTFOLIO_MAX")
        if self.IDEA_PIPELINE:
            if self.IDEAS_DISCOVERY_MAX_SHARE < self.DISCOVERY_MAX_SHARE:
                problems.append(
                    "IDEAS_DISCOVERY_MAX_SHARE must be >= DISCOVERY_MAX_SHARE"
                )
            if self.IDEAS_REVIEW_MAX_IDEAS < self.GENERATOR_N:
                problems.append("IDEAS_REVIEW_MAX_IDEAS must be >= GENERATOR_N")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @field_validator("GENERATED_CLASSES")
    @classmethod
    def _generated_classes_never_novel(
        cls, value: tuple[ChangeClass, ...]
    ) -> tuple[ChangeClass, ...]:
        """Novel ideas need approval no unattended run gives, so they park (D9)."""
        if not value or ChangeClass.novel in value:
            raise ValueError(
                "GENERATED_CLASSES must name efficiency and/or behaviour, never novel"
            )
        return tuple(dict.fromkeys(value))

    @field_validator(
        "UNDERSTAND_EFFORT",
        "EDITOR_EFFORT",
        "GENERATOR_EFFORT",
        "MATCHER_EFFORT",
        "IDEAS_LANE_EFFORT",
        "IDEAS_LEAP_EFFORT",
        "IDEAS_REVIEWER_EFFORT",
        mode="before",
    )
    @classmethod
    def _blank_effort_is_unset(cls, value: object) -> object:
        """An empty variable (an unset CI var) means no effort, not an error."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    LLM_MAX_RETRIES: int = Field(default=2, ge=0)
    """Extra attempts after a transient failure (so at most 3 in all)."""

    LLM_TIMEOUT_S: float = Field(default=300.0, gt=0, allow_inf_nan=False)
    """SDK client timeout per attempt, in seconds."""

    # ============================================
    # Editor limits (per trial)
    # ============================================
    EDITOR_MAX_TURNS: int = Field(default=16, ge=1)
    EDITOR_MAX_TOOL_CALLS: int = Field(default=40, ge=1)
    EDITOR_MAX_FILES: int = Field(default=10, ge=1)
    EDITOR_MAX_FILE_BYTES: int = Field(default=256 * _KIB, ge=1)
    EDITOR_MAX_TOTAL_BYTES: int = Field(default=1 * _MIB, ge=1)
    EDITOR_MAX_TOKENS: int = Field(default=8000, ge=1)
    """``max_tokens`` for each editor request (tool calls are short; this keeps
    the worst-case estimate of one request well under the default cost cap)."""

    # Self-retry (D12, D13). Both bounded 0-1: the run cap by the owner (O8,
    # until B-R2), the per-trial one because a run cap of 1 makes more
    # unreachable (spec section 8, Q17).
    EDITOR_FIX_RETRIES: int = Field(default=1, ge=0, le=FIX_RETRIES_MAX)
    EDITOR_FIX_RETRIES_PER_RUN: int = Field(default=1, ge=0, le=FIX_RETRIES_MAX)
    RETRY_CLOSURE_MAX_SOURCE_BYTES: int = Field(default=8 * _MIB, ge=1)
    """Most tracked source the retry's closure set reads (D13)."""

    # ============================================
    # Step 3: quality check and noise rule (D37-D41). The owner's choices
    # (O9, O10); only the factory reads them, so the nodes keep Step 2's
    # behaviour until it does (D4).
    # ============================================
    DEFAULT_OUTPUT_CHECK: bool = True
    """With no quality check, outputs must stay identical (O9)."""
    OUTPUT_TOLERANCE_MAX_BYTES: int = Field(default=16 * _MIB, ge=1)
    """Largest ``output_file`` compared under a tolerance; above, exact (D39)."""
    QUALITY_MAX_FROZEN_BYTES: int = Field(default=64 * _MIB, ge=1)
    """Most bytes a quality check's frozen files may hold (D37)."""
    QUALITY_MAX_ROWS: int = Field(default=1_000_000, ge=1)
    """Most lines a builtin measure scores (D37)."""
    QUALITY_TIMEOUT_S: float = Field(default=300.0, ge=1, allow_inf_nan=False)
    """Wall-clock limit of one scoring (D37)."""
    PAIRED_TRIALS: bool = True
    """Measure each trial alternately against its own base worktree (D41 a)."""
    CONFIRM_WINNERS: bool = True
    """Re-test every would-be keep or review before it stands (D41 b)."""
    NOISE_CALIBRATION_BLOCKS: int = Field(
        default=3, ge=0, le=NOISE_CALIBRATION_BLOCKS_MAX
    )
    """A/A blocks behind the per-project floor; 0 keeps Step 2 (D41 c)."""
    NOISE_GAP_MULTIPLIER: float = Field(default=2.0, ge=1, allow_inf_nan=False)
    """The floor is this many times the largest calibrated gap (D41 c)."""

    # ============================================
    # Engine: measurement rigour and budget
    # ============================================
    MIN_RUNS: int = 5
    """Minimum timed runs per measurement (baseline and every trial)."""

    NOISE_MULTIPLIER: float = 2.0
    """A gain must exceed this many standard deviations of the noisier side."""

    MIN_RELATIVE_GAIN: float = 0.02
    """Smallest relative gain worth keeping, as a fraction of the baseline."""

    MAX_TRIAL_ROUNDS: int = 3
    """Hypothesis -> trial rounds before the engine gives up on a workload."""

    MAX_COST_USD: float = Field(default=5.0, ge=0, allow_inf_nan=False)
    """Hard cap on Claude API spend per engine run (0 allows no paid calls)."""

    TRIAL_BRANCH_PREFIX: str = "engine/"
    """Prefix for trial and delivery branches; the default branch is never touched."""

    @field_validator("TRIAL_BRANCH_PREFIX")
    @classmethod
    def _safe_branch_prefix(cls, value: str) -> str:
        """Non-empty, ends with ``/`` and starts a valid git refname."""
        problem = branch_prefix_problem(value)
        if problem is not None:
            raise ValueError(f"TRIAL_BRANCH_PREFIX {value!r}: {problem}")
        return value

    # ============================================
    # Execution: isolation, worktrees, git, output
    # ============================================
    NETWORK_ISOLATION: IsolationMode = "required"
    """Network sandbox for workload and test runs."""

    FS_ISOLATION: IsolationMode = "required"
    """Write confinement (Landlock / sandbox-exec) for workload and test runs."""

    WORKTREE_ROOT: Path = Field(
        default=Path("~/.cache/aip/worktrees"), validate_default=True
    )
    """Where every phase's worktree lives; expanded and resolved at startup."""

    GIT_EXECUTABLE: str = "git"
    """A bare name looked up on PATH, or an absolute path."""

    GIT_TIMEOUT_S: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    TEST_TIMEOUT_S: float = Field(default=900.0, gt=0, allow_inf_nan=False)
    MAX_OUTPUT_BYTES: int = Field(default=256 * _MIB, ge=1)
    """Above this much stdout a run is killed as an output flood."""
    OUTPUT_HEAD_BYTES: int = Field(default=64 * _KIB, ge=1)
    STDERR_TAIL_BYTES: int = Field(default=8 * _KIB, ge=1)
    MAX_DIFF_BYTES: int = Field(default=1 * _MIB, ge=1)

    @field_validator("WORKTREE_ROOT")
    @classmethod
    def _absolute_worktree_root(cls, value: Path) -> Path:
        """Expand ``~``, refuse a relative root, resolve ``..`` and symlinks.

        Relative roots are refused so the root never resolves against the
        current directory; keeping it outside the checkout is preflight's job.
        """
        try:
            expanded = value.expanduser()
        except RuntimeError as error:  # HOME unset and no passwd entry
            raise ValueError(
                "WORKTREE_ROOT: cannot determine the home directory; "
                "set WORKTREE_ROOT to an absolute path"
            ) from error
        if not expanded.is_absolute():
            raise ValueError(
                f"WORKTREE_ROOT {str(value)!r} must be absolute or start with '~'"
            )
        return expanded.resolve()

    @field_validator("GIT_EXECUTABLE")
    @classmethod
    def _bare_or_absolute_git(cls, value: str) -> str:
        """Refuse anything that would resolve against the current directory."""
        has_separator = "/" in value or os.sep in value
        relative_path = has_separator and not os.path.isabs(value)
        if not value or "\x00" in value or relative_path:
            raise ValueError(
                f"GIT_EXECUTABLE {value!r} must be a bare name or an absolute path"
            )
        return value

    @model_validator(mode="after")
    def _every_billed_model_is_priced(self) -> Self:
        """Every model a request may bill needs a price, or no estimate is a bound.

        The idea pipeline's roles bill only with ``IDEA_PIPELINE`` on, so a
        price table valid today stays valid with it off (D43); a transport for
        one of them is built from ``role_settings``, whose engine model is the
        role's and is checked here either way.
        """
        roles = _ROLES if self.IDEA_PIPELINE else _TODAYS_ROLES
        needed = (
            self.ENGINE_MODEL,
            *self.ENGINE_FALLBACK_MODELS,
            self.TRIAGE_MODEL,
            *(model for role in roles for model in role_chain(self, role)),
        )
        missing = sorted({name for name in needed if name not in self.MODEL_PRICING})
        if missing:
            raise ValueError(f"MODEL_PRICING has no price for {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _effort_accepted_by_every_serving_model(self) -> Self:
        """A configured level must be one every model in its role's chain accepts.

        Each chain is ``role_chain``'s: understanding uses the engine's (the
        engine model, plus the fallbacks when they are sent; a fallback re-runs
        the same body, effort included), every other key its own role's.
        """
        keys: tuple[tuple[str, Role], ...] = (
            ("UNDERSTAND_EFFORT", "engine"),
            ("EDITOR_EFFORT", "editor"),
            ("GENERATOR_EFFORT", "generator"),
            ("MATCHER_EFFORT", "matcher"),
            ("IDEAS_LANE_EFFORT", "lane"),
            ("IDEAS_LEAP_EFFORT", "leap"),
            ("IDEAS_REVIEWER_EFFORT", "reviewer"),
        )
        for key, role in keys:
            level: Effort | None = getattr(self, key)
            serving = role_chain(self, role)
            for model in dict.fromkeys(serving) if level is not None else ():
                accepted = EFFORT_LEVELS.get(model)
                if accepted is None:
                    raise ValueError(
                        f"{key} {level!r}: the effort docs list no effort levels "
                        f"for {model}, which may serve the request; unset {key}"
                    )
                if level not in accepted:
                    takes = ", ".join(x for x in _LEVELS if x in accepted)
                    raise ValueError(
                        f"{key} {level!r} is not accepted by {model}, which may "
                        f"serve the request (it accepts {takes})"
                    )
        return self

    @model_validator(mode="after")
    def _retention_models_need_the_flag(self) -> Self:
        """A 30-day-retention model never receives repository text unless the
        live harness set the flag (D63): every role sends it, and the engine's
        fallbacks are checked whether or not they are sent (fail closed)."""
        if self.ALLOW_RETENTION_MODELS:
            return self
        chains: list[tuple[str, tuple[str, ...]]] = [
            (role, role_chain(self, role)) for role in _ROLES
        ]
        chains.append(("engine fallback", self.ENGINE_FALLBACK_MODELS))
        for role, models in chains:
            for model in models:
                if model in RETENTION_REQUIRED_MODELS:
                    raise ValueError(
                        f"the {role} role would send repository text to {model}, "
                        "which requires 30-day data retention; it runs only in the "
                        "live harness, which sets ALLOW_RETENTION_MODELS"
                    )
        return self

    # ============================================
    # Database
    # ============================================
    DATABASE_URL: str = "postgresql://dev:devpass@localhost:5432/ai_platform"
    """PostgreSQL connection URL."""

    # ============================================
    # Redis
    # ============================================
    REDIS_URL: str = "redis://localhost:6379"
    """Redis connection URL for caching and queues."""

    # ============================================
    # Qdrant Vector Database
    # ============================================
    QDRANT_URL: str = "http://localhost:6333"
    """Qdrant vector database URL."""

    # ============================================
    # Logging
    # ============================================
    LOG_LEVEL: str = "INFO"
    """Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""

    # ============================================
    # Application Settings
    # ============================================
    ENVIRONMENT: str = "development"
    """Environment name (development, staging, production)."""

    MAX_RETRIES: int = 3
    """Maximum number of retries for failed operations."""

    TIMEOUT_SECONDS: int = 30
    """Default timeout for external API calls."""


_ROLES: Final[tuple[Role, ...]] = get_args(Role)
PIPELINE_ROLES: Final[tuple[Role, ...]] = ("lane", "leap", "reviewer")
"""The idea pipeline's roles (D58): they send requests only with it on."""
_TODAYS_ROLES: Final = tuple(role for role in _ROLES if role not in PIPELINE_ROLES)


def role_chain(cfg: Settings, role: Role) -> tuple[str, ...]:
    """Every model one request of ``role`` may bill, in the order tried.

    The engine (and the editor while ``EDITOR_MODEL`` is unset) keeps
    ``cost.chain``'s: ``ENGINE_MODEL`` plus ``ENGINE_FALLBACK_MODELS`` when
    ``ENGINE_FALLBACKS`` is on. Every other role runs its model alone.
    """
    model = {
        "engine": None,
        "editor": cfg.EDITOR_MODEL,
        "generator": cfg.GENERATOR_MODEL,
        "matcher": cfg.MATCHER_MODEL,
        "lane": cfg.IDEAS_LANE_MODEL,
        "leap": cfg.IDEAS_LEAP_MODEL,
        "reviewer": cfg.IDEAS_REVIEWER_MODEL,
    }[role]
    if model is not None:
        return (model,)
    if cfg.ENGINE_FALLBACKS:
        return (cfg.ENGINE_MODEL, *cfg.ENGINE_FALLBACK_MODELS)
    return (cfg.ENGINE_MODEL,)


def role_settings(base: Settings, role: Role, **update: object) -> Settings:
    """A validated copy of ``base`` whose engine chain is ``role``'s.

    Promoted from ``tests/live/discovery.py``'s ``model_settings``: a role
    with its own model gets it as ``ENGINE_MODEL`` with fallbacks off, and the
    efforts of the other roles are cleared so they are not re-checked against
    a model they never run on; then ``update`` applies. So
    ``cost.chain(role_settings(base, role)) == role_chain(base, role)``, and
    a transport built from the copy serves that role. ``base`` is unchanged.
    """
    changes: dict[str, object] = {}
    model = role_chain(base, role)
    if model != role_chain(base, "engine"):
        changes = {
            "ENGINE_MODEL": model[0],
            "ENGINE_FALLBACKS": False,
            "EDITOR_MODEL": None,
            "UNDERSTAND_EFFORT": None,
            "EDITOR_EFFORT": base.EDITOR_EFFORT if role == "editor" else None,
        }
    copy = base.model_copy(update={**changes, **update})
    return type(base).model_validate(copy.model_dump())


# Global settings instance
settings = Settings()
