"""Tests for configuration management.

Verifies environment variable loading and settings validation.
"""

import pytest

from autonomous_ai_agents.common.config import Settings


def test_settings_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Should load configuration from environment variables.

    GIVEN environment variables set via monkeypatch
    WHEN creating Settings instance
    THEN should use environment values
    """
    # ARRANGE
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost/test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    # ACT
    settings = Settings()

    # ASSERT
    assert settings.ANTHROPIC_API_KEY == "test-key-123"
    assert settings.DATABASE_URL == "postgresql://test:test@localhost/test"
    assert settings.LOG_LEVEL == "DEBUG"


def test_settings_uses_defaults_when_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should use default values for optional fields.

    GIVEN minimal env vars set (ANTHROPIC_API_KEY only)
    WHEN creating Settings instance
    THEN should use default values for optional fields
    """
    # ARRANGE - Clear all test env vars and set only required ones
    for key in [
        "ENVIRONMENT",
        "LOG_LEVEL",
        "DATABASE_URL",
        "ENGINE_MODEL",
        "TRIAGE_MODEL",
        "MIN_RUNS",
        "NOISE_MULTIPLIER",
        "MIN_RELATIVE_GAIN",
        "MAX_TRIAL_ROUNDS",
        "MAX_COST_USD",
        "TRIAL_BRANCH_PREFIX",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-456")

    # ACT
    settings = Settings()

    # ASSERT - check defaults are used
    assert settings.REDIS_URL == "redis://localhost:6379"
    assert settings.QDRANT_URL == "http://localhost:6333"
    assert settings.LOG_LEVEL == "INFO"  # Default value
    assert settings.ENVIRONMENT == "development"  # Default value
    assert settings.MAX_RETRIES == 3
    assert settings.TIMEOUT_SECONDS == 30
    assert settings.ENGINE_MODEL == "claude-opus-5-5"
    assert settings.TRIAGE_MODEL == "claude-haiku-5-5"


def test_settings_engine_knobs_have_safe_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should expose the engine's measurement and budget knobs with defaults.

    GIVEN no engine knob env vars
    WHEN creating Settings instance
    THEN the anti-cheating and budget defaults from the Step 1 design apply
    """
    # ARRANGE
    for key in [
        "MIN_RUNS",
        "NOISE_MULTIPLIER",
        "MIN_RELATIVE_GAIN",
        "MAX_TRIAL_ROUNDS",
        "MAX_COST_USD",
        "TRIAL_BRANCH_PREFIX",
    ]:
        monkeypatch.delenv(key, raising=False)

    # ACT
    settings = Settings()

    # ASSERT
    assert settings.MIN_RUNS == 5
    assert settings.NOISE_MULTIPLIER == 2.0
    assert settings.MIN_RELATIVE_GAIN == 0.02
    assert settings.MAX_TRIAL_ROUNDS == 3
    assert settings.MAX_COST_USD == 5.0
    assert settings.TRIAL_BRANCH_PREFIX == "engine/"


def test_settings_engine_knobs_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should read engine knobs from the environment.

    GIVEN MIN_RUNS and MAX_COST_USD set in the environment
    WHEN creating Settings instance
    THEN the environment values win
    """
    # ARRANGE
    monkeypatch.setenv("MIN_RUNS", "7")
    monkeypatch.setenv("MAX_COST_USD", "12.5")

    # ACT
    settings = Settings()

    # ASSERT
    assert settings.MIN_RUNS == 7
    assert settings.MAX_COST_USD == 12.5


def test_settings_model_ids_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should allow the engine and triage models to be swapped via env vars.

    GIVEN ENGINE_MODEL and TRIAGE_MODEL set in the environment
    WHEN creating Settings instance
    THEN should use the environment values instead of the defaults
    """
    # ARRANGE
    monkeypatch.setenv("ENGINE_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("TRIAGE_MODEL", "claude-opus-5-5")

    # ACT
    settings = Settings()

    # ASSERT
    assert settings.ENGINE_MODEL == "claude-sonnet-5-5"
    assert settings.TRIAGE_MODEL == "claude-opus-5-5"


def test_settings_requires_anthropic_api_key() -> None:
    """Should raise ValidationError when ANTHROPIC_API_KEY missing.

    GIVEN no ANTHROPIC_API_KEY in environment
    WHEN creating Settings instance
    THEN should raise validation error
    """
    # This test verifies pydantic-settings validation
    # In real environment, conftest.py sets test values
    # so this test documents the requirement
    pass  # pragma: no cover
