"""Tests for the anti-cheating rules (Step 1, unit U2).

Pure functions: protected-path matching, path-traversal rejection, the
noise-floor rule, run-count rule and output fingerprints. These are the
"frozen evaluator" guarantees nothing a trial writes can bypass.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common.models import (
    MIN_RUNS,
    Direction,
    Measurement,
    NoiseCheck,
    RunStats,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    PathTraversalError,
    check_diff,
    check_diff_all,
    check_path,
    check_run_count,
    compare_fingerprints,
    exceeds_noise,
    fingerprint,
    noise_floor,
    normalize_path,
    relative_gain,
)

BASELINE = RunStats(n=5, mean=1.80, stdev=0.04, min=1.75, max=1.85, unit="s")


def _stats(mean: float, stdev: float = 0.03) -> RunStats:
    return RunStats(
        n=5, mean=mean, stdev=stdev, min=mean - stdev, max=mean + stdev, unit="s"
    )


def _measurement(workload_id: str, digest: str | None) -> Measurement:
    return Measurement(
        workload_id=workload_id,
        metric="wall_time_s",
        stats=_stats(1.0),
        samples=(1.0, 1.0, 1.0, 1.0, 1.0),
        output_fingerprint=digest,
    )


# ---------------------------------------------------------------------------
# Path normalisation and protected paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("src/a.py", "src/a.py"),
        ("./src/a.py", "src/a.py"),
        ("src//a.py", "src/a.py"),
        ("tests\\test_win.py", "tests/test_win.py"),
    ],
)
def test_normalize_path_returns_posix_relative_paths(raw: str, expected: str) -> None:
    """
    GIVEN a relative path in various spellings
    WHEN normalised
    THEN it is a clean POSIX relative path
    """
    assert normalize_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["../x.py", "src/../../etc/passwd", "/etc/passwd", "C:\\Windows\\x.py", "~/x.py"],
)
def test_normalize_path_rejects_traversal_and_absolute_paths(raw: str) -> None:
    """
    GIVEN an absolute path, a home path or one with '..'
    WHEN normalised
    THEN PathTraversalError is raised and check_path reports path_traversal
    """
    with pytest.raises(PathTraversalError):
        normalize_path(raw)

    violation = check_path(raw)

    assert violation is not None
    assert violation.rule is ViolationRule.path_traversal
    assert violation.path == raw


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_x.py",
        "src/pkg/tests/test_y.py",
        "conftest.py",
        "a/b/conftest.py",
        "test_root.py",
        "src/x/test_data_loader.py",
        "src/x/loader_test.py",
        "benchmarks/bench.py",
        "src/bench_speed.py",
        "pyproject.toml",
        "sub/pyproject.toml",
        "pytest.ini",
        ".github/workflows/ci.yml",
        ".pre-commit-config.yaml",
        ".engine/judges.yaml",
        "engine.toml",
        "tests\\test_win.py",
        "./tests/test_dot.py",
        "src/Conftest.py",
        "PYPROJECT.TOML",
        "Tests/Test_Case.py",
        ".GitHub/workflows/CI.yml",
    ],
)
def test_protected_paths_are_detected(path: str) -> None:
    """
    GIVEN a path a trial must never modify
    WHEN checked against the default patterns
    THEN a protected_path violation names the path and the pattern
    """
    violation = check_path(path)

    assert violation is not None
    assert violation.rule is ViolationRule.protected_path
    assert violation.pattern in DEFAULT_PROTECTED_PATTERNS
    assert violation.path == normalize_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "src/attestsrc.py",
        "src/bridge/encoder.py",
        "src/latest_run.py",
        "src/contest/results.py",
        "docs/testing.md",
        "README.md",
        "src/engine_toolkit.py",
    ],
)
def test_ordinary_source_paths_are_not_protected(path: str) -> None:
    """
    GIVEN an ordinary source path that merely resembles a protected name
    WHEN checked
    THEN no violation is reported
    """
    assert check_path(path) is None


def test_check_diff_returns_first_violation_and_all_violations() -> None:
    """
    GIVEN a diff touching two protected paths and one clean path
    WHEN checked
    THEN check_diff returns the first violation and check_diff_all returns both
    """
    touched = ("src/a.py", "tests/test_a.py", "src/b.py", ".github/workflows/ci.yml")

    first = check_diff(touched)
    every = check_diff_all(touched)

    assert first is not None
    assert first.path == "tests/test_a.py"
    assert [v.path for v in every] == ["tests/test_a.py", ".github/workflows/ci.yml"]


def test_check_diff_is_clean_for_source_only_changes() -> None:
    """
    GIVEN a diff touching only source files
    WHEN checked
    THEN no violation is reported
    """
    assert check_diff(("src/a.py", "src/pkg/b.py")) is None
    assert check_diff_all(()) == ()


def test_check_diff_honours_custom_patterns() -> None:
    """
    GIVEN a project-specific protected pattern
    WHEN a touched path matches it
    THEN it is reported, and default patterns are not applied unless given
    """
    custom = ("configs/judge_*.yaml",)

    assert check_diff(("configs/judge_speed.yaml",), custom) is not None
    assert check_diff(("tests/test_a.py",), custom) is None


# ---------------------------------------------------------------------------
# Gains, noise floor and run counts
# ---------------------------------------------------------------------------


def test_relative_gain_for_both_directions() -> None:
    """
    GIVEN a baseline of 1.80 and a trial of 1.05
    WHEN the relative gain is computed
    THEN minimize reports +41.7% and maximize reports the mirror image
    """
    trial = _stats(1.05)

    assert relative_gain(BASELINE, trial, Direction.minimize) == pytest.approx(
        0.75 / 1.80
    )
    assert relative_gain(BASELINE, trial, Direction.maximize) == pytest.approx(
        -0.75 / 1.80
    )


def test_relative_gain_rejects_zero_baseline() -> None:
    """
    GIVEN a baseline whose mean is zero
    WHEN the relative gain is computed
    THEN a ValueError is raised instead of dividing by zero
    """
    with pytest.raises(ValueError, match="baseline mean is zero"):
        relative_gain(_stats(0.0, 0.0), _stats(1.0), Direction.minimize)


@pytest.mark.parametrize(
    ("baseline_stdev", "trial_stdev", "min_rel", "expected"),
    [
        (0.04, 0.03, 0.02, 0.08),  # baseline spread dominates: 2 * 0.04
        (0.01, 0.06, 0.02, 0.12),  # trial spread dominates: 2 * 0.06
        (0.01, 0.01, 0.05, 0.09),  # minimum relative gain dominates: 0.05 * 1.80
    ],
)
def test_noise_floor_takes_the_largest_source_of_doubt(
    baseline_stdev: float, trial_stdev: float, min_rel: float, expected: float
) -> None:
    """
    GIVEN baseline and trial spreads and a minimum relative gain
    WHEN the noise floor is computed
    THEN it is the largest of 2*stdev(baseline), 2*stdev(trial) and min_rel*|mean|
    """
    baseline = _stats(1.80, baseline_stdev)
    trial = _stats(1.05, trial_stdev)

    assert noise_floor(baseline, trial, min_rel) == pytest.approx(expected)


def test_noise_multiplier_is_configurable() -> None:
    """
    GIVEN a multiplier of 3
    WHEN the noise floor is computed
    THEN the stdev terms scale with it
    """
    assert noise_floor(
        BASELINE, _stats(1.05, 0.03), 0.0, multiplier=3.0
    ) == pytest.approx(0.12)


def test_exceeds_noise_passes_a_clear_gain() -> None:
    """
    GIVEN a 41.7% gain against a 4.4% noise floor
    WHEN checked
    THEN the check passes and reports absolute and relative figures
    """
    check = exceeds_noise(
        BASELINE, _stats(1.05), Direction.minimize, min_relative_gain=0.02
    )

    assert isinstance(check, NoiseCheck)
    assert check.passed is True
    assert check.gain_abs == pytest.approx(0.75)
    assert check.gain_rel == pytest.approx(0.75 / 1.80)
    assert check.floor_abs == pytest.approx(0.08)
    assert check.floor_rel == pytest.approx(0.08 / 1.80)


def test_exceeds_noise_fails_inside_the_floor_and_at_the_boundary() -> None:
    """
    GIVEN a gain inside the noise floor, and one exactly on it
    WHEN checked
    THEN neither passes (a gain must strictly exceed the floor)
    """
    inside = exceeds_noise(
        BASELINE, _stats(1.76), Direction.minimize, min_relative_gain=0.02
    )
    boundary = exceeds_noise(
        BASELINE, _stats(1.72), Direction.minimize, min_relative_gain=0.02
    )

    assert inside.passed is False
    assert inside.gain_abs == pytest.approx(0.04)
    assert boundary.gain_abs == pytest.approx(0.08)
    assert boundary.passed is False


def test_exceeds_noise_reports_regressions_as_negative_gain() -> None:
    """
    GIVEN a trial slower than the baseline
    WHEN checked
    THEN the gain is negative and the check fails
    """
    check = exceeds_noise(
        BASELINE, _stats(2.10), Direction.minimize, min_relative_gain=0.02
    )

    assert check.gain_abs < 0
    assert check.passed is False


def test_check_run_count_enforces_the_minimum() -> None:
    """
    GIVEN stats from fewer runs than the minimum, and exactly the minimum
    WHEN checked
    THEN only the former is a too_few_runs violation
    """
    too_few = RunStats(n=MIN_RUNS - 1, mean=1.0, stdev=0.0, min=1.0, max=1.0, unit="s")
    enough = RunStats(n=MIN_RUNS, mean=1.0, stdev=0.0, min=1.0, max=1.0, unit="s")

    violation = check_run_count(too_few)

    assert violation is not None
    assert violation.rule is ViolationRule.too_few_runs
    assert check_run_count(enough) is None
    assert check_run_count(enough, min_runs=MIN_RUNS + 1) is not None


# ---------------------------------------------------------------------------
# Fingerprints
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic_sha256_for_text_and_bytes() -> None:
    """
    GIVEN the same payload as text and as UTF-8 bytes
    WHEN fingerprinted
    THEN both give the same 64-hex-character sha256 digest
    """
    digest = fingerprint("hello")

    assert digest == fingerprint(b"hello")
    assert len(digest) == 64
    assert digest == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert fingerprint("hello!") != digest


def test_compare_fingerprints_matches_by_workload() -> None:
    """
    GIVEN baseline and trial measurements with equal fingerprints per workload
    WHEN compared
    THEN no violation is reported
    """
    digest = fingerprint("same output")

    violations = compare_fingerprints(
        (_measurement("w1", digest),), (_measurement("w1", digest),)
    )

    assert violations == ()


def test_compare_fingerprints_reports_mismatch_and_missing() -> None:
    """
    GIVEN a workload whose output changed and one the trial never measured
    WHEN compared
    THEN a fingerprint_mismatch and a missing_fingerprint violation are reported
    """
    baseline = (
        _measurement("w1", fingerprint("a")),
        _measurement("w2", fingerprint("b")),
    )
    trial = (_measurement("w1", fingerprint("changed")),)

    violations = compare_fingerprints(baseline, trial)

    assert [v.rule for v in violations] == [
        ViolationRule.fingerprint_mismatch,
        ViolationRule.missing_fingerprint,
    ]
    assert all(isinstance(v, Violation) for v in violations)


def test_compare_fingerprints_requires_baseline_fingerprints() -> None:
    """
    GIVEN a baseline measurement without a fingerprint
    WHEN compared
    THEN a missing_fingerprint violation is reported (equivalence cannot be proven)
    """
    violations = compare_fingerprints(
        (_measurement("w1", None),), (_measurement("w1", fingerprint("x")),)
    )

    assert len(violations) == 1
    assert violations[0].rule is ViolationRule.missing_fingerprint


# ---------------------------------------------------------------------------
# Review fixes: dependency/hook files, fingerprint pairing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "setup.py",
        "requirements.txt",
        "requirements-dev.txt",
        "uv.lock",
        "sub/poetry.lock",
        "Pipfile",
        "Pipfile.lock",
        "package.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "sitecustomize.py",
        "src/usercustomize.py",
        "venv/hook.pth",
        ".env",
        ".env.local",
    ],
)
def test_dependency_manifests_and_interpreter_hooks_are_protected(path: str) -> None:
    """
    GIVEN a dependency manifest, lockfile, interpreter hook or env file
    WHEN checked
    THEN it is protected (installs are approval-gated, hooks run code)
    """
    violation = check_path(path)

    assert violation is not None
    assert violation.rule is ViolationRule.protected_path


def test_compare_fingerprints_ignores_rows_without_fingerprints() -> None:
    """
    GIVEN measurement rows without a fingerprint listed first (e.g. tests_passed)
    WHEN compared
    THEN the fingerprinted rows are paired regardless of order
    """
    digest = fingerprint("same output")
    baseline = (_measurement("w1", None), _measurement("w1", digest))
    trial = (_measurement("w1", digest), _measurement("w1", None))

    assert compare_fingerprints(baseline, trial) == ()


def test_compare_fingerprints_flags_conflicting_rows_on_one_side() -> None:
    """
    GIVEN two rows of one workload on the baseline that disagree
    WHEN compared
    THEN one fingerprint_mismatch names the inconsistency and nothing else
    """
    baseline = (
        _measurement("w1", fingerprint("a")),
        _measurement("w1", fingerprint("b")),
    )
    trial = (_measurement("w1", fingerprint("a")),)

    violations = compare_fingerprints(baseline, trial)

    assert len(violations) == 1
    assert violations[0].rule is ViolationRule.fingerprint_mismatch
    assert "inconsistent" in violations[0].message
