"""Tests for configuration management.

Verifies environment variable loading and settings validation.
"""

import json
import math
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import (
    EFFORT_LEVELS,
    IDEA_VIEWS,
    RETENTION_REQUIRED_MODELS,
    Settings,
    lane_chain,
    lane_models,
    lane_settings,
    role_chain,
    role_settings,
)
from autonomous_ai_agents.common.models import LongContextPrice, ModelPrice
from autonomous_ai_agents.optimization.idea_types import LENS_LANES, Lane


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
    "ENGINE_API_BASE_URL",
    "ANTHROPIC_BASE_URL",
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
    "UNDERSTAND_EFFORT",
    "EDITOR_EFFORT",
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
    # Pricing page (2026-10-23): Haiku 5.5 cache hits are $0.01 for prompts
    # up to 100K tokens, Sonnet 5.5's 0.05x input, Fable 5.1's 0.025x. Over
    # 100,000 prompt tokens Haiku 5.5 bills $0.50 / $2.50, writes $0.625 and
    # hits $0.05 ("Long context pricing"); no other model has a long tier.
    assert pricing["claude-haiku-5-5"] == ModelPrice(
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
    )
    assert [name for name, p in pricing.items() if p.long_context] == [
        "claude-haiku-5-5"
    ]
    assert pricing["claude-sonnet-5-5"] == ModelPrice(
        input=2.0, output=10.0, cache_write=2.5, cache_read=0.10
    )
    assert pricing["claude-fable-5-1"] == ModelPrice(
        input=10.0, output=50.0, cache_write=12.5, cache_read=0.25
    )
    for price in pricing.values():
        assert price.cache_write == pytest.approx(1.25 * price.input)
        if price.long_context is not None:
            long = price.long_context
            assert long.cache_write == pytest.approx(1.25 * long.input)


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
    names = ("m-engine", "m-fallback", "m-triage", "claude-sonnet-5-5")
    table = {name: rate for name in names}
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


def test_the_engine_api_base_url_defaults_to_the_official_api(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should talk to the official API unless the engine's own setting says otherwise.

    GIVEN ANTHROPIC_BASE_URL set in the environment (the SDK would read it)
    WHEN creating Settings instance without ENGINE_API_BASE_URL
    THEN the engine's base URL is still https://api.anthropic.com
    """
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example")

    assert Settings(_env_file=None).ENGINE_API_BASE_URL == "https://api.anthropic.com"


@pytest.mark.parametrize(
    "value", ["https://api.anthropic.com", "https://gateway.example:8443/anthropic"]
)
def test_the_engine_api_base_url_accepts_https(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should accept an explicit https base URL with a host.

    GIVEN ENGINE_API_BASE_URL set to an https URL
    WHEN creating Settings instance
    THEN the value is used as given
    """
    monkeypatch.setenv("ENGINE_API_BASE_URL", value)

    assert Settings(_env_file=None).ENGINE_API_BASE_URL == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://api.anthropic.com",
        "api.anthropic.com",
        "https://",
        "https://user:pw@api.anthropic.com",
        "file:///etc/passwd",
    ],
)
def test_the_engine_api_base_url_refuses_anything_but_plain_https(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, value: str
) -> None:
    """Should refuse a base URL that is not https, has no host, or carries credentials.

    GIVEN ENGINE_API_BASE_URL that is plain http, schemeless, hostless,
          carries userinfo, or is another scheme
    WHEN creating Settings instance
    THEN validation fails naming the setting, so the API key never leaves over
         plain http or to an unintended host
    """
    monkeypatch.setenv("ENGINE_API_BASE_URL", value)

    with pytest.raises(ValidationError, match="ENGINE_API_BASE_URL"):
        Settings(_env_file=None)


# ---------------------------------------------------------------------------
# Per-role effort (UNDERSTAND_EFFORT, EDITOR_EFFORT)
# ---------------------------------------------------------------------------

LEVELS = ("low", "medium", "high", "xhigh", "max")
EFFORT_SETTINGS = ("UNDERSTAND_EFFORT", "EDITOR_EFFORT")
RATE = {"input": 1.0, "output": 2.0, "cache_write": 1.25, "cache_read": 0.1}


def _priced_for(*models: str) -> str:
    """A MODEL_PRICING table that prices ``models``, the triage model and the
    Step 3 generator and matcher default (Sonnet 5.5)."""
    roles = ("claude-haiku-5-5", "claude-sonnet-5-5")
    return json.dumps({name: RATE for name in (*models, *roles)})


def test_effort_is_unset_by_default(clean_env: Path) -> None:
    """Should send no effort unless one is configured.

    GIVEN no effort env vars
    WHEN creating Settings instance
    THEN both roles' effort is None (the request then carries no effort key)
    """
    settings = Settings(_env_file=None)

    assert settings.UNDERSTAND_EFFORT is None
    assert settings.EDITOR_EFFORT is None


@pytest.mark.parametrize("key", EFFORT_SETTINGS)
@pytest.mark.parametrize("level", LEVELS)
def test_every_level_is_accepted_on_the_default_chain(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str, level: str
) -> None:
    """Should accept all five levels for the default Opus 5.5 -> Opus 4.8 chain.

    GIVEN UNDERSTAND_EFFORT or EDITOR_EFFORT set to a documented level
    WHEN creating Settings instance with the default chain
    THEN the level is kept (both models accept every level)
    """
    monkeypatch.setenv(key, level)

    assert getattr(Settings(_env_file=None), key) == level


@pytest.mark.parametrize("key", EFFORT_SETTINGS)
@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_effort_means_unset(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str, blank: str
) -> None:
    """Should read an empty value (an unset CI variable) as no effort.

    GIVEN an effort env var that is empty or whitespace
    WHEN creating Settings instance
    THEN the setting is None
    """
    monkeypatch.setenv(key, blank)

    assert getattr(Settings(_env_file=None), key) is None


@pytest.mark.parametrize("key", EFFORT_SETTINGS)
@pytest.mark.parametrize("value", ["adaptive", "HIGH", "none", "extra"])
def test_an_unknown_effort_level_is_refused(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str, value: str
) -> None:
    """Should refuse anything but the five documented level names.

    GIVEN an effort env var that is not low, medium, high, xhigh or max
    WHEN creating Settings instance
    THEN validation fails naming the setting
    """
    monkeypatch.setenv(key, value)

    with pytest.raises(ValidationError, match=key):
        Settings(_env_file=None)


def test_the_documented_levels_of_every_model_the_engine_names() -> None:
    """Should carry the effort page's per-model levels.

    GIVEN EFFORT_LEVELS (platform.claude.com effort page, read 2026-10-23)
    WHEN the chain models and the triage model are looked up
    THEN Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1 and Opus 4.8 accept all
         five levels; Opus 4.6 has max but not xhigh; Opus 4.5 only three
    """
    for model in (
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "claude-opus-4-8",
    ):
        assert EFFORT_LEVELS[model] == frozenset(LEVELS), model
    assert EFFORT_LEVELS["claude-opus-4-6"] == frozenset(
        {"low", "medium", "high", "max"}
    )
    assert EFFORT_LEVELS["claude-opus-4-5-20251101"] == frozenset(
        {"low", "medium", "high"}
    )
    for levels in EFFORT_LEVELS.values():
        assert levels <= frozenset(LEVELS)


@pytest.mark.parametrize("key", EFFORT_SETTINGS)
def test_a_level_a_fallback_model_rejects_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, key: str
) -> None:
    """Should refuse a level that a model the request may be served by rejects.

    GIVEN fallbacks on with Opus 4.6 in the chain, and xhigh configured
    WHEN creating Settings instance
    THEN validation fails naming the setting, the level and the model
    """
    monkeypatch.setenv(
        "MODEL_PRICING", _priced_for("claude-opus-5-5", "claude-opus-4-6")
    )
    monkeypatch.setenv("ENGINE_FALLBACK_MODELS", '["claude-opus-4-6"]')
    monkeypatch.setenv(key, "xhigh")

    with pytest.raises(ValidationError, match=f"{key}.*xhigh.*claude-opus-4-6"):
        Settings(_env_file=None)


def test_a_fallback_that_is_not_sent_does_not_limit_the_level(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should check only the models a request may really be served by.

    GIVEN Opus 4.6 listed as a fallback but ENGINE_FALLBACKS off, and xhigh
    WHEN creating Settings instance
    THEN the level is kept: only the engine model serves the request
    """
    monkeypatch.setenv(
        "MODEL_PRICING", _priced_for("claude-opus-5-5", "claude-opus-4-6")
    )
    monkeypatch.setenv("ENGINE_FALLBACK_MODELS", '["claude-opus-4-6"]')
    monkeypatch.setenv("ENGINE_FALLBACKS", "false")
    monkeypatch.setenv("EDITOR_EFFORT", "xhigh")

    assert Settings(_env_file=None).EDITOR_EFFORT == "xhigh"


def test_a_level_the_engine_model_rejects_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should refuse a level the engine model itself does not accept.

    GIVEN ENGINE_MODEL Opus 4.5 (low, medium and high only) and max
    WHEN creating Settings instance
    THEN validation fails naming the level, the model and what it accepts
    """
    monkeypatch.setenv(
        "MODEL_PRICING", _priced_for("claude-opus-4-5-20251101", "claude-opus-4-8")
    )
    monkeypatch.setenv("ENGINE_MODEL", "claude-opus-4-5-20251101")
    monkeypatch.setenv("UNDERSTAND_EFFORT", "max")

    with pytest.raises(
        ValidationError,
        match="UNDERSTAND_EFFORT 'max'.*claude-opus-4-5-20251101.*low, medium, high",
    ):
        Settings(_env_file=None)


def test_a_model_without_documented_levels_takes_no_effort(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should not guess whether an undocumented model accepts effort.

    GIVEN an engine model the effort page does not list
    WHEN creating Settings instance with and without EDITOR_EFFORT
    THEN without it the settings load; with it validation fails naming the
         model and saying the docs list no levels for it
    """
    monkeypatch.setenv(
        "MODEL_PRICING", _priced_for("claude-custom-1", "claude-opus-4-8")
    )
    monkeypatch.setenv("ENGINE_MODEL", "claude-custom-1")
    assert Settings(_env_file=None).EDITOR_EFFORT is None

    monkeypatch.setenv("EDITOR_EFFORT", "low")
    with pytest.raises(ValidationError, match="no effort levels for claude-custom-1"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "engine", ["claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-5-5"]
)
def test_max_is_accepted_on_the_other_current_engine_models(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path, engine: str
) -> None:
    """Should accept max on every current model in the experiments' sweep.

    GIVEN ENGINE_MODEL Sonnet 5.5, Fable 5.1 or Haiku 5.5 with the default
          Opus 4.8 fallback, and max for both roles
    WHEN creating Settings instance
    THEN both levels are kept
    """
    monkeypatch.setenv("MODEL_PRICING", _priced_for(engine, "claude-opus-4-8"))
    monkeypatch.setenv("ENGINE_MODEL", engine)
    monkeypatch.setenv("ALLOW_RETENTION_MODELS", "1")  # D63: Fable 5.1 needs it
    monkeypatch.setenv("UNDERSTAND_EFFORT", "max")
    monkeypatch.setenv("EDITOR_EFFORT", "max")

    settings = Settings(_env_file=None)

    assert (settings.UNDERSTAND_EFFORT, settings.EDITOR_EFFORT) == ("max", "max")


def test_a_long_context_tier_can_be_overridden_as_json(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should read a long-context tier from a MODEL_PRICING override.

    GIVEN MODEL_PRICING JSON whose triage model carries long_context
    WHEN creating Settings instance
    THEN the tier is parsed into a LongContextPrice
    """
    long = {
        "threshold_tokens": 100_000,
        "input": 0.5,
        "output": 2.5,
        "cache_write": 0.625,
        "cache_read": 0.05,
    }
    table = {
        "claude-opus-5-5": RATE,
        "claude-opus-4-8": RATE,
        "claude-sonnet-5-5": RATE,
        "claude-haiku-5-5": {**RATE, "long_context": long},
    }
    monkeypatch.setenv("MODEL_PRICING", json.dumps(table))

    price = Settings(_env_file=None).MODEL_PRICING["claude-haiku-5-5"]

    assert price.long_context == LongContextPrice.model_validate(long)


# ---------------------------------------------------------------------------
# The idea lab's price rows and per-lane models (G1; O15, O31)
# ---------------------------------------------------------------------------

SONNET_5, FABLE_5, HAIKU_4_5 = "claude-sonnet-5", "claude-fable-5", "claude-haiku-4-5"


def _cfg(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_the_idea_lab_price_rows_are_the_live_pricing_page_rates(
    clean_env: Path,
) -> None:
    """Should carry the three G1 rows exactly as the pricing page lists them.

    GIVEN the default pricing table
    WHEN read
    THEN Sonnet 5 is $2/$10 (footnote 3: now the standard price), writes
         $2.50, hits $0.20; Fable 5 $10/$50, writes $12.50, hits $1.00 (the
         standard 0.1x, not Fable 5.1's $0.25); Haiku 4.5 $1/$5, writes
         $1.25, hits $0.10 (pricing page, read 2026-11-02); none has a long
         tier, so a placeholder or a typo fails here
    """
    pricing = Settings(_env_file=None).MODEL_PRICING

    assert pricing[SONNET_5] == ModelPrice(
        input=2.0, output=10.0, cache_write=2.5, cache_read=0.20
    )
    assert pricing[FABLE_5] == ModelPrice(
        input=10.0, output=50.0, cache_write=12.5, cache_read=1.00
    )
    assert pricing[HAIKU_4_5] == ModelPrice(
        input=1.0, output=5.0, cache_write=1.25, cache_read=0.10
    )
    assert pricing[FABLE_5] != pricing["claude-fable-5-1"]


def test_with_no_lane_models_every_lane_runs_on_the_lane_model(
    clean_env: Path,
) -> None:
    """Should keep today's behaviour exactly while IDEAS_LANE_MODELS is empty."""
    cfg = _cfg()

    assert cfg.IDEAS_LANE_MODELS == {}
    assert lane_models(cfg) == (cfg.IDEAS_LANE_MODEL,)
    for lane in (Lane.obvious, *LENS_LANES):
        assert lane_chain(cfg, lane) == role_chain(cfg, "lane")
        assert lane_settings(cfg, lane) == role_settings(cfg, "lane")
    assert lane_chain(cfg, Lane.leap) == role_chain(cfg, "leap")
    assert lane_settings(cfg, Lane.leap) == role_settings(cfg, "leap")


def test_a_lane_may_name_its_own_model_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should read per-lane models as JSON and route only the named lanes.

    GIVEN IDEAS_LANE_MODELS naming Sonnet 5 for eliminate and Opus 5.5 for far
    WHEN the settings load
    THEN those two lanes bill their model alone, every other lane the lane
         model, and a lane's settings copy is a transport's for that model
    """
    models = {"eliminate": SONNET_5, "far": "claude-opus-5-5"}
    monkeypatch.setenv("IDEAS_LANE_MODELS", json.dumps(models))

    cfg = Settings(_env_file=None)

    assert cfg.IDEAS_LANE_MODELS == {Lane.eliminate: SONNET_5, Lane.far: models["far"]}
    assert lane_chain(cfg, Lane.eliminate) == (SONNET_5,)
    assert lane_chain(cfg, Lane.far) == ("claude-opus-5-5",)
    assert lane_chain(cfg, Lane.obvious) == ("claude-sonnet-5-5",)
    assert lane_models(cfg) == ("claude-sonnet-5-5", SONNET_5, "claude-opus-5-5")
    copy = lane_settings(cfg, Lane.eliminate)
    assert chain(copy) == (SONNET_5,)
    assert copy.IDEAS_LANE_EFFORT == cfg.IDEAS_LANE_EFFORT
    assert role_chain(copy, "lane") == (SONNET_5,)


@pytest.mark.parametrize(
    ("models", "extra", "match"),
    [
        pytest.param(
            {"sideways": SONNET_5}, {}, "IDEAS_LANE_MODELS names 'sideways'",
            id="unknown lane",
        ),
        pytest.param(
            {"leap": SONNET_5}, {}, "IDEAS_LEAP_MODEL", id="leap has its own model"
        ),
        pytest.param(
            {"far": SONNET_5}, {"IDEAS_LENSES": ("eliminate",)},
            "far.*not in IDEAS_LENSES", id="lane that never runs",
        ),
        pytest.param(
            {"far": "claude-unpriced-9"}, {},
            "far.*claude-unpriced-9.*MODEL_PRICING", id="no price row",
        ),
        pytest.param(
            {"far": HAIKU_4_5}, {}, "far.*claude-haiku-4-5.*deferred.*O31",
            id="Haiku 4.5 deferred",
        ),
        pytest.param(
            {"far": HAIKU_4_5}, {"IDEAS_LANE_EFFORT": None},
            "claude-haiku-4-5.*deferred.*O31", id="Haiku 4.5 deferred without effort",
        ),
    ],
)  # fmt: skip
def test_a_lane_model_the_engine_cannot_serve_is_refused(
    clean_env: Path,
    models: dict[str, str],
    extra: dict[str, object],
    match: str,
) -> None:
    """Should refuse, at load and with the pipeline off too, a lane override
    that names no running lane, no priced model, or Haiku 4.5 (O31)."""
    with pytest.raises(ValidationError, match=match):
        _cfg(IDEAS_LANE_MODELS=models, **extra)


def test_lane_models_that_are_not_a_mapping_are_refused(clean_env: Path) -> None:
    with pytest.raises(ValidationError, match="IDEAS_LANE_MODELS"):
        _cfg(IDEAS_LANE_MODELS=["eliminate", SONNET_5])


def test_a_lane_model_with_no_effort_row_is_refused(clean_env: Path) -> None:
    """Should refuse a priced lane model the effort docs list no levels for,
    with or without IDEAS_LANE_EFFORT (every lane model must take effort)."""
    pricing = {
        **_cfg().MODEL_PRICING,
        "claude-custom-1": ModelPrice.model_validate(RATE),
    }
    for effort in ("medium", None):
        with pytest.raises(
            ValidationError, match="far.*claude-custom-1.*no effort levels"
        ):
            _cfg(
                MODEL_PRICING=pricing,
                IDEAS_LANE_EFFORT=effort,
                IDEAS_LANE_MODELS={"far": "claude-custom-1"},
            )


def test_the_lane_effort_must_suit_every_lane_model(clean_env: Path) -> None:
    """Should check IDEAS_LANE_EFFORT against each lane's own model.

    GIVEN Sonnet 4.6 (no xhigh) priced and named for one lane
    WHEN IDEAS_LANE_EFFORT is xhigh, then high
    THEN xhigh is refused naming Sonnet 4.6; high loads
    """
    pricing = {
        **_cfg().MODEL_PRICING,
        "claude-sonnet-4-6": ModelPrice.model_validate(RATE),
    }
    values: dict[str, object] = {
        "MODEL_PRICING": pricing,
        "IDEAS_LANE_MODELS": {"recombine": "claude-sonnet-4-6"},
    }
    with pytest.raises(
        ValidationError, match="IDEAS_LANE_EFFORT 'xhigh'.*claude-sonnet-4-6"
    ):
        _cfg(IDEAS_LANE_EFFORT="xhigh", **values)
    assert _cfg(IDEAS_LANE_EFFORT="high", **values).IDEAS_LANE_EFFORT == "high"


@pytest.mark.parametrize(
    "key",
    [
        "ENGINE_MODEL",
        "EDITOR_MODEL",
        "GENERATOR_MODEL",
        "MATCHER_MODEL",
        "IDEAS_LANE_MODEL",
        "IDEAS_LEAP_MODEL",
        "IDEAS_REVIEWER_MODEL",
        "TRIAGE_MODEL",
    ],
)
def test_haiku_4_5_is_refused_wherever_a_model_is_named(
    clean_env: Path, key: str
) -> None:
    """Should not let the new price row admit a model whose request shape
    (thinking budget_tokens, no effort) is not built (O31)."""
    efforts = {
        name: None
        for name in (
            "GENERATOR_EFFORT",
            "MATCHER_EFFORT",
            "IDEAS_LANE_EFFORT",
            "IDEAS_LEAP_EFFORT",
            "IDEAS_REVIEWER_EFFORT",
        )
    }
    with pytest.raises(ValidationError, match=f"{key}.*claude-haiku-4-5.*O31"):
        _cfg(**{key: HAIKU_4_5}, **efforts)


def test_haiku_4_5_is_refused_among_the_engine_fallbacks(clean_env: Path) -> None:
    with pytest.raises(ValidationError, match="ENGINE_FALLBACK_MODELS.*O31"):
        _cfg(ENGINE_FALLBACKS=False, ENGINE_FALLBACK_MODELS=(HAIKU_4_5,))


def test_a_retention_model_on_a_lane_needs_the_flag(clean_env: Path) -> None:
    """Should run the existing retention guard (D63, O15) over every lane.

    GIVEN Fable 5 (30-day retention) named for the eliminate lane
    WHEN the settings load without, then with, ALLOW_RETENTION_MODELS
    THEN without the flag validation fails naming the lane, the model and
         the flag; with it the lane bills Fable 5, and the lane's settings
         copy keeps the flag (re-validated, so dropping it fails)
    """
    models = {"eliminate": FABLE_5}
    with pytest.raises(
        ValidationError, match="eliminate.*claude-fable-5.*ALLOW_RETENTION_MODELS"
    ):
        _cfg(IDEAS_LANE_MODELS=models)

    cfg = _cfg(IDEAS_LANE_MODELS=models, ALLOW_RETENTION_MODELS=True)

    assert lane_chain(cfg, Lane.eliminate) == (FABLE_5,)
    copy = lane_settings(cfg, Lane.eliminate)
    assert (copy.ENGINE_MODEL, copy.ALLOW_RETENTION_MODELS) == (FABLE_5, True)
    assert FABLE_5 in RETENTION_REQUIRED_MODELS
    with pytest.raises(ValidationError, match="ALLOW_RETENTION_MODELS"):
        Settings.model_validate({**copy.model_dump(), "ALLOW_RETENTION_MODELS": False})


# --------------------------------------------------------------------------
# G2: a view per lane (IDEAS_LANE_VIEWS)
# --------------------------------------------------------------------------


def test_with_no_lane_views_every_lane_sees_the_shared_block(clean_env: Path) -> None:
    """Should keep today's behaviour exactly while IDEAS_LANE_VIEWS is empty."""
    assert _cfg().IDEAS_LANE_VIEWS == {}
    assert IDEA_VIEWS == (
        "callers", "data_structures", "input_shape", "whole_module",
        "next_hotspots", "history",
    )  # fmt: skip


def test_a_lens_may_name_its_view_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    """Should read per-lane views as JSON, two lenses sharing one allowed."""
    views = {"eliminate": "callers", "far": "history", "recombine": "callers"}
    monkeypatch.setenv("IDEAS_LANE_VIEWS", json.dumps(views))

    cfg = Settings(_env_file=None)

    assert cfg.IDEAS_LANE_VIEWS == {
        Lane.eliminate: "callers", Lane.far: "history", Lane.recombine: "callers"
    }  # fmt: skip


@pytest.mark.parametrize(
    ("views", "extra", "match"),
    [
        pytest.param({"sideways": "callers"}, {},
                     "IDEAS_LANE_VIEWS names 'sideways'", id="unknown lane"),
        pytest.param({"obvious": "callers"}, {}, "obvious.*shared data block",
                     id="S1 keeps the shared block"),
        pytest.param({"leap": "callers"}, {}, "leap.*shared data block",
                     id="the leap keeps the shared block"),
        pytest.param({"far": "callers"}, {"IDEAS_LENSES": ("eliminate",)},
                     "IDEAS_LANE_VIEWS.*far.*not in IDEAS_LENSES",
                     id="lane that never runs"),
        pytest.param({"far": "everything"}, {}, "IDEAS_LANE_VIEWS",
                     id="unknown view"),
        pytest.param(["far", "callers"], {}, "IDEAS_LANE_VIEWS", id="not a mapping"),
    ],
)  # fmt: skip
def test_a_lane_view_the_pipeline_cannot_route_is_refused(
    clean_env: Path, views: object, extra: dict[str, object], match: str
) -> None:
    """Should refuse, at load and with the pipeline off too, a view for a
    lane that is no running lens, or a view that does not exist."""
    with pytest.raises(ValidationError, match=match):
        _cfg(IDEAS_LANE_VIEWS=views, **extra)


# --------------------------------------------------------------------------
# G5a: a framework per lane (IDEAS_LANE_FRAMEWORKS)
# --------------------------------------------------------------------------


def test_lane_frameworks_are_off_by_default(clean_env: Path) -> None:
    """Should keep every request as it was until a configuration turns them on."""
    assert _cfg().IDEAS_LANE_FRAMEWORKS is False


def test_lane_frameworks_turn_on_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    monkeypatch.setenv("IDEAS_LANE_FRAMEWORKS", "true")
    assert Settings(_env_file=None).IDEAS_LANE_FRAMEWORKS is True
    with pytest.raises(ValidationError, match="IDEAS_LANE_FRAMEWORKS"):
        _cfg(IDEAS_LANE_FRAMEWORKS="sometimes")


# --------------------------------------------------------------------------
# G5b: round seeds (IDEAS_ROUND_SEEDS)
# --------------------------------------------------------------------------


def test_round_seeds_are_off_by_default(clean_env: Path) -> None:
    """Should show no lane a verdict until a configuration turns seeds on."""
    assert _cfg().IDEAS_ROUND_SEEDS is False


def test_round_seeds_turn_on_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, clean_env: Path
) -> None:
    monkeypatch.setenv("IDEAS_ROUND_SEEDS", "true")
    assert Settings(_env_file=None).IDEAS_ROUND_SEEDS is True
    with pytest.raises(ValidationError, match="IDEAS_ROUND_SEEDS"):
        _cfg(IDEAS_ROUND_SEEDS="sometimes")
