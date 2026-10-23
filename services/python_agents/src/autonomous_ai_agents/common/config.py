"""Environment configuration management.

Loads configuration from environment variables using pydantic-settings.
Complex values (``MODEL_PRICING``, ``ENGINE_FALLBACK_MODELS``) are read as
JSON. Everything is validated at startup, so a bad knob fails at import
rather than in the middle of a run.
"""

import os
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from autonomous_ai_agents.common.models import ModelPrice
from autonomous_ai_agents.common.refnames import branch_prefix_problem

IsolationMode = Literal["required", "best_effort", "off"]
"""``required`` fails closed; ``best_effort`` records what was applied; ``off``."""

_KIB = 1024
_MIB = 1024 * _KIB

# USD per million tokens. Sources: the claude-api skill, shared/models.md
# (Opus 5.5 $4/$20 with cache reads $0.20; Opus 5 at Opus 4.8's $5/$25;
# Haiku 5.5 $0.10/$0.50 for prompts of 100K tokens or fewer) and
# shared/prompt-caching.md (5-minute cache writes cost 1.25x input; cache
# reads ~0.1x input elsewhere); the pricing page, read 2026-10-23, for Sonnet
# 5.5 ($2/$10, cache hits 0.05x input: $0.10), Fable 5.1 ($10/$50, cache hits
# 0.025x input: $0.25) and Haiku 5.5's cache hits ($0.01). Haiku 5.5's
# >100K-token rates ($0.50/$2.50, hits $0.05) are not modelled, so triage
# prompts must stay at or under 100K tokens (Step 3).
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
        input=0.10, output=0.50, cache_write=0.125, cache_read=0.01
    ),
}


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
        """Every model a request may bill needs a price, or no estimate is a bound."""
        needed = (self.ENGINE_MODEL, *self.ENGINE_FALLBACK_MODELS, self.TRIAGE_MODEL)
        missing = sorted({name for name in needed if name not in self.MODEL_PRICING})
        if missing:
            raise ValueError(f"MODEL_PRICING has no price for {', '.join(missing)}")
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


# Global settings instance
settings = Settings()
