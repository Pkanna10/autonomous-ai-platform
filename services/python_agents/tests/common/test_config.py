"""Tests for configuration management.

Verifies environment variable loading and settings validation.
"""

import json
import math
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import ModelPrice


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
    assert settings.ANTHROPIC_API_KEY is not None
    assert settings.ANTHROPIC_API_KEY.get_secret_value() == "test-key-123"
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


@pytest.mark.parametrize(
    "prefix",
    [
        pytest.param("", id="empty"),
        pytest.param("engine", id="no trailing slash"),
        pytest.param("engine/../", id="parent segment"),
        pytest.param("engine..x/", id="double dot"),
        pytest.param("eng ine/", id="space"),
        pytest.param("engine~1/", id="tilde"),
        pytest.param("engine@{/", id="reflog syntax"),
        pytest.param("engine:x/", id="colon"),
        pytest.param("/", id="root slash"),
        pytest.param("//", id="double slash"),
        pytest.param(".engine/", id="dot segment"),
        pytest.param("engine//", id="empty segment"),
        pytest.param("-x/", id="dash start"),
        pytest.param("a.lock/", id="lock suffix"),
        pytest.param("engine/.x/", id="dot inner segment"),
    ],
)
def test_settings_reject_an_unsafe_trial_branch_prefix(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    """Should refuse a branch prefix that cannot safely start a git branch.

    GIVEN TRIAL_BRANCH_PREFIX set to an empty, slash-less, traversing or
          non-refname value
    WHEN creating Settings instance
    THEN validation fails, so no node ever builds a branch from it
    """
    # ARRANGE
    monkeypatch.setenv("TRIAL_BRANCH_PREFIX", prefix)

    # ACT / ASSERT
    with pytest.raises(ValidationError, match="TRIAL_BRANCH_PREFIX"):
        Settings()


@pytest.mark.parametrize("prefix", ["engine/", "bots/engine/", "ai_1.x-y/"])
def test_settings_accept_a_safe_trial_branch_prefix(
    monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    """Should keep a prefix made of refname characters ending with a slash.

    GIVEN TRIAL_BRANCH_PREFIX set to a safe value
    WHEN creating Settings instance
    THEN the value is used as given
    """
    # ARRANGE
    monkeypatch.setenv("TRIAL_BRANCH_PREFIX", prefix)

    # ACT
    settings = Settings()

    # ASSERT
    assert settings.TRIAL_BRANCH_PREFIX == prefix


def test_settings_anthropic_api_key_is_an_optional_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should treat the API key as optional and keep it out of every rendering.

    GIVEN no ANTHROPIC_API_KEY, then a key set in the environment
    WHEN creating Settings instances
    THEN the key is None when absent, a SecretStr when set, and its value
         never appears in repr, str or the JSON dump of the settings
    """
    # ARRANGE
    secret = "sk-ant-test-never-print-me"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # ACT
    absent = Settings(_env_file=None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    present = Settings(_env_file=None)

    # ASSERT
    assert absent.ANTHROPIC_API_KEY is None
    assert isinstance(present.ANTHROPIC_API_KEY, SecretStr)
    assert present.ANTHROPIC_API_KEY.get_secret_value() == secret
    for rendering in (repr(present), str(present), present.model_dump_json()):
        assert secret not in rendering
    assert secret not in repr(present.ANTHROPIC_API_KEY)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_settings_blank_anthropic_api_key_means_no_key(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """Should read a blank API key as no key at all.

    GIVEN ANTHROPIC_API_KEY set but empty or whitespace-only (``ANTHROPIC_API_KEY=``
          left in a .env, an empty CI secret), in the environment or passed in
    WHEN creating Settings instances
    THEN the key is None, so the "no key configured" branch fires before the run
         starts instead of a 401 after connect and preflight
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", blank)

    assert Settings(_env_file=None).ANTHROPIC_API_KEY is None
    assert (
        Settings(_env_file=None, ANTHROPIC_API_KEY=SecretStr(blank)).ANTHROPIC_API_KEY
        is None
    )


def test_settings_keep_a_non_blank_api_key_passed_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Should keep a real key whether it arrives as text or as a SecretStr.

    GIVEN a non-blank key passed to Settings directly as a SecretStr
    WHEN creating Settings instance
    THEN the key is kept unchanged
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    key = Settings(_env_file=None, ANTHROPIC_API_KEY=SecretStr("k")).ANTHROPIC_API_KEY

    assert key is not None
    assert key.get_secret_value() == "k"


# ---------------------------------------------------------------------------
# Step 2 (U1): pricing, isolation, worktrees, git and limits
# ---------------------------------------------------------------------------

STEP2_ENV = (
    "ENGINE_MODEL",
    "TRIAGE_MODEL",
    "ENGINE_FALLBACKS",
    "ENGINE_FALLBACK_MODELS",
    "MODEL_PRICING",
    "NETWORK_ISOLATION",
    "FS_ISOLATION",
    "WORKTREE_ROOT",
    "GIT_EXECUTABLE",
    "GIT_TIMEOUT_S",
    "TEST_TIMEOUT_S",
    "MAX_OUTPUT_BYTES",
    "OUTPUT_HEAD_BYTES",
    "STDERR_TAIL_BYTES",
    "MAX_DIFF_BYTES",
    "EDITOR_MAX_TURNS",
    "EDITOR_MAX_TOOL_CALLS",
    "EDITOR_MAX_FILES",
    "EDITOR_MAX_FILE_BYTES",
    "EDITOR_MAX_TOTAL_BYTES",
    "EDITOR_MAX_TOKENS",
    "UNDERSTAND_MAX_TOKENS",
    "LLM_MAX_RETRIES",
    "LLM_TIMEOUT_S",
)

KIB = 1024
MIB = 1024 * KIB


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Clear every Step 2 setting and point HOME at a temporary directory."""
    for key in STEP2_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_settings_step2_defaults(clean_env: Path) -> None:
    """Should expose every Step 2 knob with the spec's default.

    GIVEN no Step 2 env vars
    WHEN creating Settings instance
    THEN fallbacks, isolation, git, output, editor and LLM limits hold the
         values from the spec table
    """
    # ACT
    settings = Settings(_env_file=None)

    # ASSERT
    assert settings.ENGINE_FALLBACKS is True
    assert settings.ENGINE_FALLBACK_MODELS == ("claude-opus-4-8",)
    assert settings.NETWORK_ISOLATION == "required"
    assert settings.FS_ISOLATION == "required"
    assert settings.GIT_EXECUTABLE == "git"
    assert settings.GIT_TIMEOUT_S == 60
    assert settings.TEST_TIMEOUT_S == 900
    assert settings.MAX_OUTPUT_BYTES == 256 * MIB
    assert settings.OUTPUT_HEAD_BYTES == 64 * KIB
    assert settings.STDERR_TAIL_BYTES == 8 * KIB
    assert settings.MAX_DIFF_BYTES == 1 * MIB
    assert settings.EDITOR_MAX_TURNS == 16
    assert settings.EDITOR_MAX_TOOL_CALLS == 40
    assert settings.EDITOR_MAX_FILES == 10
    assert settings.EDITOR_MAX_FILE_BYTES == 256 * KIB
    assert settings.EDITOR_MAX_TOTAL_BYTES == 1 * MIB
    assert settings.EDITOR_MAX_TOKENS == 8000
    assert settings.UNDERSTAND_MAX_TOKENS == 8000
    assert settings.LLM_MAX_RETRIES == 2
    assert settings.LLM_TIMEOUT_S == 300


def test_settings_default_pricing_matches_the_documented_rates(
    clean_env: Path,
) -> None:
    """Should price every model the engine can bill, in USD per MTok.

    GIVEN the default pricing table
    WHEN read
    THEN the engine model, both fallbacks and the triage model carry the
         documented rates (5-minute cache writes at 1.25x input)
    """
    # ACT
    pricing = Settings(_env_file=None).MODEL_PRICING

    # ASSERT
    assert pricing["claude-opus-5-5"] == ModelPrice(
        input=4.0, output=20.0, cache_write=5.0, cache_read=0.20
    )
    assert pricing["claude-opus-5"] == ModelPrice(
        input=5.0, output=25.0, cache_write=6.25, cache_read=0.50
    )
    assert pricing["claude-opus-4-8"] == ModelPrice(
        input=5.0, output=25.0, cache_write=6.25, cache_read=0.50
    )
    assert pricing["claude-haiku-5-5"] == ModelPrice(
        input=0.10, output=0.50, cache_write=0.125, cache_read=0.10
    )
    for price in pricing.values():
        assert price.cache_write == pytest.approx(1.25 * price.input)


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        pytest.param({"ENGINE_MODEL": "claude-unpriced-1"}, "claude-unpriced-1"),
        pytest.param({"TRIAGE_MODEL": "claude-unpriced-2"}, "claude-unpriced-2"),
        pytest.param(
            {"ENGINE_FALLBACK_MODELS": '["claude-opus-5", "claude-unpriced-3"]'},
            "claude-unpriced-3",
        ),
        pytest.param(
            {
                "ENGINE_FALLBACKS": "false",
                "ENGINE_FALLBACK_MODELS": '["claude-unpriced-4"]',
            },
            "claude-unpriced-4",
            id="fallbacks off still priced",
        ),
        pytest.param(
            {
                "MODEL_PRICING": json.dumps(
                    {
                        "claude-opus-5-5": {
                            "input": 4,
                            "output": 20,
                            "cache_write": 5,
                            "cache_read": 0.2,
                        }
                    }
                )
            },
            "claude-haiku-5-5",
            id="override drops a required model",
        ),
    ],
)
def test_settings_refuse_an_unpriced_model(
    monkeypatch: pytest.MonkeyPatch,
    clean_env: Path,
    env: dict[str, str],
    missing: str,
) -> None:
    """Should fail at startup when a model the engine may bill has no price.

    GIVEN an engine, fallback or triage model missing from MODEL_PRICING
    WHEN creating Settings instance
    THEN validation fails naming MODEL_PRICING and the unpriced model, so the
         pre-send cost estimate can never be computed without a price
    """
    # ARRANGE
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    # ACT / ASSERT
    with pytest.raises(ValidationError, match=f"MODEL_PRICING.*{missing}"):
        Settings(_env_file=None)


def test_settings_pricing_and_fallbacks_can_be_overridden(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should read a JSON pricing table and fallback chain from the environment.

    GIVEN MODEL_PRICING and ENGINE_FALLBACK_MODELS as JSON plus a new engine model
    WHEN creating Settings instance
    THEN the overrides are parsed into ModelPrice values and a tuple
    """
    # ARRANGE
    rate = {"input": 1.0, "output": 2.0, "cache_write": 1.25, "cache_read": 0.1}
    table = {name: rate for name in ("m-engine", "m-fallback", "m-triage")}
    monkeypatch.setenv("MODEL_PRICING", json.dumps(table))
    monkeypatch.setenv("ENGINE_MODEL", "m-engine")
    monkeypatch.setenv("TRIAGE_MODEL", "m-triage")
    monkeypatch.setenv("ENGINE_FALLBACK_MODELS", '["m-fallback"]')
    monkeypatch.setenv("ENGINE_FALLBACKS", "false")

    # ACT
    settings = Settings(_env_file=None)

    # ASSERT
    assert settings.ENGINE_FALLBACK_MODELS == ("m-fallback",)
    assert settings.ENGINE_FALLBACKS is False
    assert settings.MODEL_PRICING["m-engine"] == ModelPrice(**rate)


def test_settings_refuse_a_negative_price(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should refuse a pricing table with a negative rate.

    GIVEN MODEL_PRICING with a negative output rate
    WHEN creating Settings instance
    THEN validation fails
    """
    # ARRANGE
    bad = {"input": 4, "output": -20, "cache_write": 5, "cache_read": 0.2}
    monkeypatch.setenv("MODEL_PRICING", json.dumps({"claude-opus-5-5": bad}))

    # ACT / ASSERT
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("mode", ["required", "best_effort", "off"])
def test_settings_accept_every_isolation_mode(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, mode: str
) -> None:
    """Should accept the three documented isolation modes.

    GIVEN NETWORK_ISOLATION and FS_ISOLATION set to a documented mode
    WHEN creating Settings instance
    THEN both carry that mode
    """
    # ARRANGE
    monkeypatch.setenv("NETWORK_ISOLATION", mode)
    monkeypatch.setenv("FS_ISOLATION", mode)

    # ACT
    settings = Settings(_env_file=None)

    # ASSERT
    assert settings.NETWORK_ISOLATION == mode
    assert settings.FS_ISOLATION == mode


@pytest.mark.parametrize("key", ["NETWORK_ISOLATION", "FS_ISOLATION"])
def test_settings_refuse_an_unknown_isolation_mode(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str
) -> None:
    """Should refuse an isolation mode outside the documented three.

    GIVEN an isolation setting of "Required" or "maybe"
    WHEN creating Settings instance
    THEN validation fails, so a typo can never weaken isolation
    """
    for value in ("maybe", "Required"):
        monkeypatch.setenv(key, value)
        with pytest.raises(ValidationError, match=key):
            Settings(_env_file=None)


def test_settings_worktree_root_defaults_under_the_home_cache(
    clean_env: Path,
) -> None:
    """Should default the worktree root to ~/.cache/aip/worktrees, resolved.

    GIVEN HOME pointing at a temporary directory and no WORKTREE_ROOT
    WHEN creating Settings instance
    THEN the root is that home's .cache/aip/worktrees, absolute and resolved
    """
    # ACT
    root = Settings(_env_file=None).WORKTREE_ROOT

    # ASSERT
    assert root == (clean_env / ".cache" / "aip" / "worktrees").resolve()
    assert root.is_absolute()


def test_settings_worktree_root_expands_and_resolves_overrides(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should expand ``~`` and resolve ``..`` and symlinks in an override.

    GIVEN WORKTREE_ROOT set to a home-relative path and to a path with '..'
          that passes through a symlink
    WHEN creating Settings instances
    THEN each root is the absolute real path
    """
    # ARRANGE
    real = clean_env / "real"
    real.mkdir()
    (clean_env / "link").symlink_to(real)

    # ACT
    monkeypatch.setenv("WORKTREE_ROOT", "~/wt")
    home_relative = Settings(_env_file=None).WORKTREE_ROOT
    monkeypatch.setenv("WORKTREE_ROOT", str(clean_env / "link" / "x" / ".." / "wt"))
    through_link = Settings(_env_file=None).WORKTREE_ROOT

    # ASSERT
    assert home_relative == (clean_env / "wt").resolve()
    assert through_link == (real / "wt").resolve()


@pytest.mark.parametrize("value", ["wt", "./wt", "cache/../wt"])
def test_settings_refuse_a_relative_worktree_root(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should refuse a relative worktree root.

    GIVEN WORKTREE_ROOT relative to the current directory
    WHEN creating Settings instance
    THEN validation fails, so the root never resolves against the current
         directory (keeping it out of the checkout is preflight's job)
    """
    monkeypatch.setenv("WORKTREE_ROOT", value)

    with pytest.raises(ValidationError, match="WORKTREE_ROOT"):
        Settings(_env_file=None)


def test_settings_explain_a_missing_home_directory(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should turn an unknown home directory into a settings error that says what to set.

    GIVEN the default '~'-relative worktree root and no way to find the home
          directory (HOME unset and no passwd entry, as in some containers)
    WHEN creating Settings instance
    THEN validation fails naming WORKTREE_ROOT, instead of a bare RuntimeError
         escaping from the import
    """
    monkeypatch.delenv("HOME")
    monkeypatch.setattr("os.path.expanduser", lambda path: path)

    with pytest.raises(ValidationError, match="WORKTREE_ROOT.*home directory"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["git", "/usr/bin/git", "/opt/homebrew/bin/git"])
def test_settings_accept_a_bare_or_absolute_git(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should accept git as a bare name (PATH lookup) or an absolute path.

    GIVEN GIT_EXECUTABLE set to a bare name or an absolute path
    WHEN creating Settings instance
    THEN the value is used as given
    """
    monkeypatch.setenv("GIT_EXECUTABLE", value)

    assert Settings(_env_file=None).GIT_EXECUTABLE == value


@pytest.mark.parametrize("value", ["", "./git", "bin/git", "~/bin/git", "git\x00"])
def test_settings_refuse_a_relative_or_empty_git(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should refuse a git executable that would resolve against the cwd.

    GIVEN GIT_EXECUTABLE empty, relative with a slash, home-relative or with NUL
    WHEN creating Settings instance
    THEN validation fails, so a repo-planted ./git can never be run
    """
    if "\x00" in value:
        # The OS cannot carry NUL in an env var; pass it as an init kwarg.
        with pytest.raises(ValidationError, match="GIT_EXECUTABLE"):
            Settings(_env_file=None, GIT_EXECUTABLE=value)
        return
    monkeypatch.setenv("GIT_EXECUTABLE", value)

    with pytest.raises(ValidationError, match="GIT_EXECUTABLE"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("GIT_TIMEOUT_S", "0"),
        ("TEST_TIMEOUT_S", "-1"),
        ("LLM_TIMEOUT_S", "0"),
        ("MAX_OUTPUT_BYTES", "0"),
        ("OUTPUT_HEAD_BYTES", "0"),
        ("STDERR_TAIL_BYTES", "-1"),
        ("MAX_DIFF_BYTES", "0"),
        ("EDITOR_MAX_TURNS", "0"),
        ("EDITOR_MAX_TOOL_CALLS", "0"),
        ("EDITOR_MAX_FILES", "0"),
        ("EDITOR_MAX_FILE_BYTES", "0"),
        ("EDITOR_MAX_TOTAL_BYTES", "0"),
        ("EDITOR_MAX_TOKENS", "0"),
        ("UNDERSTAND_MAX_TOKENS", "0"),
        ("LLM_MAX_RETRIES", "-1"),
        ("GIT_TIMEOUT_S", "inf"),
        ("LLM_TIMEOUT_S", "nan"),
    ],
)
def test_settings_refuse_non_positive_limits(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str, value: str
) -> None:
    """Should refuse a zero, negative or non-finite limit.

    GIVEN a timeout, byte cap, editor cap or retry count out of range
    WHEN creating Settings instance
    THEN validation fails naming the setting
    """
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=key):
        Settings(_env_file=None)


def test_settings_allow_zero_retries(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should allow LLM_MAX_RETRIES=0 (a single attempt, no retries).

    GIVEN LLM_MAX_RETRIES set to 0
    WHEN creating Settings instance
    THEN the value is kept
    """
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    assert Settings(_env_file=None).LLM_MAX_RETRIES == 0


@pytest.mark.parametrize("value", ["-0.01", "inf", "nan"])
def test_settings_refuse_a_bad_cost_cap(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should refuse a negative or non-finite MAX_COST_USD.

    GIVEN MAX_COST_USD that no Budget could hold
    WHEN creating Settings instance
    THEN validation fails, while 0 (no paid calls at all) is allowed
    """
    monkeypatch.setenv("MAX_COST_USD", value)

    with pytest.raises(ValidationError, match="MAX_COST_USD"):
        Settings(_env_file=None)

    monkeypatch.setenv("MAX_COST_USD", "0")
    assert Settings(_env_file=None).MAX_COST_USD == 0.0
    assert math.isfinite(Settings(_env_file=None).MAX_COST_USD)
