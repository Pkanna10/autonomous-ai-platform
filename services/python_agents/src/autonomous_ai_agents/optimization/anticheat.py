"""Anti-cheating rules: the frozen checks every trial is held to.

Pure functions, no I/O. A trial is rejected outright when it touches a
protected path (tests, benchmarks, CI, project config, the engine's own
configuration), when it measured too few runs, when its gain does not clear
the measured noise floor, or when its output fingerprint differs from the
baseline while outputs must stay equivalent.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Sequence

from autonomous_ai_agents.common.models import (
    MIN_RUNS,
    Direction,
    Measurement,
    NoiseCheck,
    RunStats,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.common.paths import PathTraversalError as PathTraversalError
from autonomous_ai_agents.common.paths import matches_pattern
from autonomous_ai_agents.common.paths import normalize_path as normalize_path

DEFAULT_PROTECTED_PATTERNS: tuple[str, ...] = (
    # Tests and benchmarks: a trial may not change what judges it.
    "**/tests/**",
    "**/test/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
    "**/benchmarks/**",
    "**/benchmark/**",
    "**/bench_*.py",
    # Project and test configuration (dependencies, pytest options).
    "**/pyproject.toml",
    "**/pytest.ini",
    "**/tox.ini",
    "**/setup.cfg",
    "**/noxfile.py",
    # Dependency manifests and lockfiles: a trial may not install packages
    # on its own (installs are vetted and approval-gated).
    "**/setup.py",
    "**/requirements*.txt",
    "**/uv.lock",
    "**/poetry.lock",
    "**/Pipfile",
    "**/Pipfile.lock",
    "**/package.json",
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    # Interpreter start-up hooks and environment files.
    "**/sitecustomize.py",
    "**/usercustomize.py",
    "**/*.pth",
    "**/.env",
    "**/.env.*",
    # CI and hooks.
    ".github/**",
    ".gitlab-ci.yml",
    ".circleci/**",
    "Jenkinsfile",
    ".pre-commit-config.yaml",
    # The engine's own judge and objective configuration.
    ".engine/**",
    "**/engine.toml",
    "**/engine.yaml",
)
"""Paths a trial must never modify. Matched case-insensitively on POSIX relative paths."""


def check_path(
    path: str, patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS
) -> Violation | None:
    """Return the violation ``path`` causes, or ``None`` when it is safe to touch."""
    try:
        normalized = normalize_path(path)
    except PathTraversalError as exc:
        return Violation(rule=ViolationRule.path_traversal, path=path, message=str(exc))
    for pattern in patterns:
        if matches_pattern(normalized, pattern):
            return Violation(
                rule=ViolationRule.protected_path,
                path=normalized,
                pattern=pattern,
                message=f"trial modified protected path {normalized!r} ({pattern!r})",
            )
    return None


def check_diff(
    touched_paths: Iterable[str], patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS
) -> Violation | None:
    """Return the first violation among ``touched_paths``, or ``None``."""
    for path in touched_paths:
        violation = check_path(path, patterns)
        if violation is not None:
            return violation
    return None


def check_diff_all(
    touched_paths: Iterable[str], patterns: Sequence[str] = DEFAULT_PROTECTED_PATTERNS
) -> tuple[Violation, ...]:
    """Return every violation among ``touched_paths`` for the report."""
    found = (check_path(path, patterns) for path in touched_paths)
    return tuple(violation for violation in found if violation is not None)


def check_run_count(stats: RunStats, min_runs: int = MIN_RUNS) -> Violation | None:
    """Reject measurements built from fewer than ``min_runs`` runs."""
    if stats.n < min_runs:
        return Violation(
            rule=ViolationRule.too_few_runs,
            message=f"{stats.n} runs measured; at least {min_runs} required",
        )
    return None


def _improvement(baseline: RunStats, trial: RunStats, direction: Direction) -> float:
    """Absolute improvement in the metric's own unit; positive means better."""
    if direction is Direction.minimize:
        return baseline.mean - trial.mean
    return trial.mean - baseline.mean


def relative_gain(baseline: RunStats, trial: RunStats, direction: Direction) -> float:
    """Improvement as a fraction of the baseline mean (0.25 == 25% better)."""
    if baseline.mean == 0:
        raise ValueError("baseline mean is zero; relative gain is undefined")
    return _improvement(baseline, trial, direction) / abs(baseline.mean)


def noise_floor(
    baseline: RunStats,
    trial: RunStats,
    min_relative_gain: float,
    multiplier: float = 2.0,
) -> float:
    """Smallest absolute improvement that counts, given the spread on both sides."""
    return max(
        multiplier * baseline.stdev,
        multiplier * trial.stdev,
        min_relative_gain * abs(baseline.mean),
    )


def exceeds_noise(
    baseline: RunStats,
    trial: RunStats,
    direction: Direction,
    min_relative_gain: float,
    multiplier: float = 2.0,
) -> NoiseCheck:
    """Decide whether a trial's gain clears the noise floor (strictly)."""
    gain_abs = _improvement(baseline, trial, direction)
    gain_rel = relative_gain(baseline, trial, direction)
    floor_abs = noise_floor(baseline, trial, min_relative_gain, multiplier)
    floor_rel = floor_abs / abs(baseline.mean)
    on_the_line = math.isclose(gain_abs, floor_abs, rel_tol=1e-9, abs_tol=1e-12)
    return NoiseCheck(
        gain_abs=gain_abs,
        gain_rel=gain_rel,
        floor_abs=floor_abs,
        floor_rel=floor_rel,
        passed=gain_abs > floor_abs and not on_the_line,
    )


def fingerprint(payload: bytes | str) -> str:
    """sha256 hex digest of canonical output bytes (callers canonicalise first)."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def _fingerprints_by_workload(
    measurements: Sequence[Measurement],
) -> tuple[dict[str, str | None], tuple[str, ...]]:
    """Per workload: the agreed fingerprint (None when absent) and the conflicts.

    Rows without a fingerprint (for example ``tests_passed``) are ignored, so
    row order never matters. A workload whose rows disagree is a conflict.
    """
    seen: dict[str, set[str]] = {}
    for measurement in measurements:
        digests = seen.setdefault(measurement.workload_id, set())
        if measurement.output_fingerprint is not None:
            digests.add(measurement.output_fingerprint)
    agreed = {
        workload_id: next(iter(digests)) if len(digests) == 1 else None
        for workload_id, digests in seen.items()
    }
    conflicts = tuple(
        workload_id for workload_id, digests in seen.items() if len(digests) > 1
    )
    return agreed, conflicts


def compare_fingerprints(
    baseline: Sequence[Measurement], trial: Sequence[Measurement]
) -> tuple[Violation, ...]:
    """Pair baseline and trial outputs per workload and report every difference."""
    expected, baseline_conflicts = _fingerprints_by_workload(baseline)
    actual, trial_conflicts = _fingerprints_by_workload(trial)
    violations: list[Violation] = [
        Violation(
            rule=ViolationRule.fingerprint_mismatch,
            message=f"workload {workload_id}: inconsistent fingerprints on {side}",
        )
        for side, conflicts in (
            ("baseline", baseline_conflicts),
            ("trial", trial_conflicts),
        )
        for workload_id in conflicts
    ]
    skip = set(baseline_conflicts) | set(trial_conflicts)
    for workload_id, baseline_digest in expected.items():
        if workload_id in skip:
            continue
        trial_digest = actual.get(workload_id)
        if baseline_digest is None or trial_digest is None:
            side = "baseline" if baseline_digest is None else "trial"
            violations.append(
                Violation(
                    rule=ViolationRule.missing_fingerprint,
                    message=f"workload {workload_id}: no output fingerprint on {side}",
                )
            )
        elif baseline_digest != trial_digest:
            violations.append(
                Violation(
                    rule=ViolationRule.fingerprint_mismatch,
                    message=f"workload {workload_id}: output changed",
                )
            )
    return tuple(violations)
