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
    ANTHROPIC_API_KEY: str
    """Anthropic API key for Claude access."""

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
