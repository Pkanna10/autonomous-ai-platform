"""Environment configuration management.

Loads configuration from environment variables using pydantic-settings.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    ANTHROPIC_API_KEY: str = "test-key-placeholder"
    """Anthropic API key for Claude access. Set via environment variable."""

    # ============================================
    # Claude models used by the engine
    # ============================================
    ENGINE_MODEL: str = "claude-opus-5-5"
    """Model for understanding code, extracting claims and writing trial edits."""

    TRIAGE_MODEL: str = "claude-haiku-5-5"
    """Cheap model for high-volume work such as daily paper triage."""

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

    MAX_COST_USD: float = 5.0
    """Hard cap on Claude API spend per engine run."""

    TRIAL_BRANCH_PREFIX: str = "engine/"
    """Prefix for trial and delivery branches; the default branch is never touched."""

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
