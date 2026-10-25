"""Tests for the anti-cheating rules (Step 1 U2, Step 2 U9).

Pure functions: protected-path matching, path-traversal rejection, the
noise-floor rule, run-count rule and output fingerprints, plus the Step 2
capture rules on a trial's git diff (file modes, compiled and binary files,
git metadata, unrecorded writes, process spawning). These are the "frozen
evaluator" guarantees nothing a trial writes can bypass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unicodedata
import warnings
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path

import pytest

from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    MIN_RUNS,
    Direction,
    Measurement,
    NoiseCheck,
    RunStats,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.common.paths import RESERVED_MODULES
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_MODULE_ROOTS,
    DEFAULT_PROTECTED_PATTERNS,
    PROCESS_SPAWN_METRICS,
    PathTraversalError,
    check_capture,
    check_diff,
    check_diff_all,
    check_path,
    check_quality_references,
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
    [
        "../x.py",
        "src/../../etc/passwd",
        "/etc/passwd",
        "C:\\Windows\\x.py",
        "~/x.py",
        # A ./ prefix or doubled slash must not hide a ~ or a drive letter
        # that only appears once the prefix is collapsed.
        "./~x.py",
        ".//~/x.py",
        "./c:x.py",
        ".\\C:\\x.py",
        "././~notes.py",
    ],
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
        # unittest discovers test*.py by default, not only test_*.py.
        "checks/testcore.py",
        "tests.py",
        "src/pkg/TestHelpers.py",
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
        "src/pkg/latest.py",
        "src/contest.py",
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


PYTEST_CONFIG_FILES: tuple[tuple[str, str], ...] = (
    # Every file pytest 9 reads, in its precedence order (findpaths.py): the
    # first two outrank pyproject.toml, tox.ini and setup.cfg.
    ("pytest.toml", "**/pytest.toml"),
    (".pytest.toml", "**/.pytest.toml"),
    ("pytest.ini", "**/pytest.ini"),
    (".pytest.ini", "**/.pytest.ini"),
    ("pyproject.toml", "**/pyproject.toml"),
    ("tox.ini", "**/tox.ini"),
    ("setup.cfg", "**/setup.cfg"),
)


@pytest.mark.parametrize(("name", "pattern"), PYTEST_CONFIG_FILES)
@pytest.mark.parametrize("folder", ["", "sub/", "src/pkg/"])
def test_every_config_file_pytest_reads_is_protected(
    folder: str, name: str, pattern: str
) -> None:
    """
    GIVEN a config file pytest 9 reads (a new .pytest.ini or pytest.toml can
        add '--collect-only' and make a failing suite exit 0), at the root or
        nested (pytest searches every parent of the test paths)
    WHEN checked against the default patterns, in any case
    THEN it is a protected_path violation naming its own pattern
    """
    for path in (folder + name, (folder + name).upper()):
        violation = check_path(path)

        assert violation is not None, path
        assert violation.rule is ViolationRule.protected_path
        assert violation.pattern == pattern
        assert pattern in DEFAULT_PROTECTED_PATTERNS


TEST_RECIPE_FILES: tuple[tuple[str, str], ...] = (
    # make, just and coverage read these from the working directory, and make
    # itself resolves outside the repo, so argv protection never sees them.
    ("Makefile", "**/Makefile"),
    ("makefile", "**/Makefile"),
    ("GNUmakefile", "**/GNUmakefile"),
    ("rules.mk", "**/*.mk"),
    ("justfile", "**/justfile"),
    ("Justfile", "**/justfile"),
    (".justfile", "**/.justfile"),
    (".coveragerc", "**/.coveragerc"),
)


@pytest.mark.parametrize(("name", "pattern"), TEST_RECIPE_FILES)
@pytest.mark.parametrize("folder", ["", "sub/"])
def test_every_recipe_file_a_test_command_reads_is_protected(
    folder: str, name: str, pattern: str
) -> None:
    """
    GIVEN a recipe file 'make test' or 'just test' runs, an included make
        fragment, or coverage's config (a trial could rewrite 'test:' to
        'true' or lower fail_under and pass the suite)
    WHEN checked against the default patterns, in any case
    THEN it is a protected_path violation naming its own pattern
    """
    for path in (folder + name, (folder + name).upper()):
        violation = check_path(path)

        assert violation is not None, path
        assert violation.rule is ViolationRule.protected_path
        assert violation.pattern == pattern
        assert pattern in DEFAULT_PROTECTED_PATTERNS


@pytest.mark.parametrize(
    "path",
    [
        "src/makefile_gen.py",
        "src/coveragerc.py",
        "docs/justfile.md",
        "src/mk.py",
        "data/rules.mkd",
        "tasks/makefiles/notes.txt",
    ],
)
def test_recipe_file_lookalikes_are_not_protected(path: str) -> None:
    """
    GIVEN a source or data path that only resembles a recipe file name
    WHEN checked
    THEN no violation is reported
    """
    assert check_path(path) is None


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


# ---------------------------------------------------------------------------
# Capture rules (Step 2, U9): what the runner sees in the trial's git diff
# ---------------------------------------------------------------------------

NO_MODE = "000000"
FILE_MODE = "100644"
EXEC_MODE = "100755"
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
WALL_ONLY = frozenset({METRIC_WALL_TIME_S, METRIC_TESTS_PASSED})
RSS_JUDGED = frozenset({METRIC_WALL_TIME_S, METRIC_PEAK_RSS_BYTES})
PLAIN_SOURCE = b"def unique(xs):\n    return list(dict.fromkeys(xs))\n"


def _added(path: str, mode: str = FILE_MODE) -> Change:
    return Change("A", NO_MODE, mode, path)


def _modified(path: str, old: str = FILE_MODE, new: str = FILE_MODE) -> Change:
    return Change("M", old, new, path)


def _deleted(path: str, old: str = FILE_MODE) -> Change:
    return Change("D", old, NO_MODE, path)


def _capture(
    changes: Sequence[Change],
    *,
    blobs: Mapping[str, bytes] | None = None,
    written: Mapping[str, int] | None = None,
    judged: frozenset[str] = WALL_ONLY,
    reserved_modules: AbstractSet[str] = RESERVED_MODULES,
    module_roots: AbstractSet[str] = DEFAULT_MODULE_ROOTS,
    existing_dirs: AbstractSet[str] | None = None,
) -> tuple[Violation, ...]:
    """Run ``check_capture`` with honest defaults so only the rule under test fires.

    By default the editor reported every touched path and every added or
    modified path has plain source as its new content.
    """
    if written is None:
        written = {c.path: 0 if c.status == "D" else 1 for c in changes}
    if blobs is None:
        blobs = {}
    content = {c.path: PLAIN_SOURCE for c in changes if c.status in ("A", "M")}
    content.update(blobs)
    return check_capture(
        changes,
        written,
        content,
        judged,
        reserved_modules=reserved_modules,
        module_roots=module_roots,
        existing_dirs=existing_dirs,
    )


def _only(
    violations: tuple[Violation, ...], rule: ViolationRule, path: str
) -> Violation:
    """Assert exactly one violation, of ``rule`` on ``path``, naming both."""
    assert [(v.rule, v.path) for v in violations] == [(rule, path)]
    violation = violations[0]
    assert rule.value in violation.message
    assert repr(path) in violation.message
    return violation


def test_capture_is_clean_for_honest_source_edits() -> None:
    """
    GIVEN an edit, a new module, a new executable script, a deletion and the
        negatives the spec names (docs/so.md, a text .json, .gitignore)
    WHEN the capture rules run with RSS judged
    THEN nothing is reported
    """
    changes = (
        _modified("dedupe/core.py"),
        _added("dedupe/fast.py"),
        _added("scripts/run.sh", EXEC_MODE),
        _deleted("dedupe/old.py"),
        _added("docs/so.md"),
        _added("data/table.json"),
        _added(".gitignore"),
        _modified("sub/.gitignore"),
        _added("my.git/notes.txt"),
        _added("docs/.gitattributes.md"),
        _modified("pkg/mod.py", EXEC_MODE, EXEC_MODE),
    )
    blobs = {"data/table.json": b'{"rows": [1, 2, 3]}\n'}

    assert _capture(changes, blobs=blobs, judged=RSS_JUDGED) == ()


def test_capture_of_nothing_is_clean() -> None:
    """
    GIVEN no changes at all
    WHEN the capture rules run
    THEN nothing is reported (an empty diff is the runner's problem, not a rule's)
    """
    assert check_capture((), {}, {}, RSS_JUDGED) == ()


# forbidden_file --------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "pattern"),
    [
        (_added("pkg/__pycache__/m.cpython-311.pyc"), "**/__pycache__/**"),
        (_added("stale.pyc"), "*.pyc"),
        (_added("pkg/mod.pyo"), "*.pyo"),
        (_added("fast.SO"), "*.so"),
        (_modified("ext/_speedups.cpython-311-darwin.so"), "*.so"),
        (_added("lib.dylib"), "*.dylib"),
        (_added("win/mod.PYD"), "*.pyd"),
        (_added("win/helper.dll"), "*.dll"),
        (_deleted("_speedups.so"), "*.so"),
        (Change("T", SYMLINK_MODE, FILE_MODE, "native/core.so"), "*.so"),
    ],
)
def test_forbidden_file_flags_any_change_to_a_write_deny_path(
    change: Change, pattern: str
) -> None:
    """
    GIVEN an added, modified, deleted or retyped compiled artefact
    WHEN the capture rules run
    THEN one forbidden_file violation names the path and the matching pattern
    """
    found = _capture((change,))

    found = tuple(v for v in found if v.rule is ViolationRule.forbidden_file)
    violation = _only(found, ViolationRule.forbidden_file, change.path)
    assert violation.pattern == pattern
    assert repr(pattern) in violation.message


@pytest.mark.parametrize(
    "change", [_added("data/table.bin"), _modified("assets/logo.txt")]
)
def test_forbidden_file_flags_a_binary_blob(change: Change) -> None:
    """
    GIVEN an added or modified path whose new content holds a NUL byte
    WHEN the capture rules run
    THEN it is a forbidden_file violation (git's binary rule)
    """
    found = _capture((change,), blobs={change.path: b"\x89PNG\r\n\x1a\n\x00\x00"})

    violation = _only(found, ViolationRule.forbidden_file, change.path)
    assert violation.pattern is None
    assert "binary" in violation.message


def test_binary_rule_looks_at_the_first_8000_bytes_only() -> None:
    """
    GIVEN a NUL as byte 8000 (the last one git inspects) and one just past it
    WHEN the capture rules run
    THEN only the first is binary
    """
    inside = b"a" * 7999 + b"\x00"
    outside = b"a" * 8000 + b"\x00"
    changes = (_added("inside.dat"), _added("outside.dat"))

    found = _capture(changes, blobs={"inside.dat": inside, "outside.dat": outside})

    _only(found, ViolationRule.forbidden_file, "inside.dat")


def test_deleted_binary_is_not_inspected() -> None:
    """
    GIVEN the deletion of a tracked binary that is not a compiled artefact
    WHEN the capture rules run
    THEN nothing is reported: a deletion has no new content
    """
    assert _capture((_deleted("data/table.bin"),)) == ()


def test_uncaptured_content_fails_closed() -> None:
    """
    GIVEN an added regular file the caller supplied no blob for
    WHEN the capture rules run
    THEN it is a forbidden_file violation: content that was not checked is refused
    """
    change = _added("dedupe/fast.py")

    found = check_capture((change,), {change.path: 1}, {}, RSS_JUDGED)

    violation = _only(found, ViolationRule.forbidden_file, change.path)
    assert "not captured" in violation.message


# forbidden_file_mode ---------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (_added("dedupe/fast.py", SYMLINK_MODE), "symlink"),
        (_added("vendor/lib", GITLINK_MODE), "gitlink"),
        (_modified("dedupe/link.py", SYMLINK_MODE, SYMLINK_MODE), "symlink"),
        (_added("odd.py", "100664"), "100664"),
        (_modified("dedupe/core.py", FILE_MODE, EXEC_MODE), "100644 -> 100755"),
        (_modified("run.sh", EXEC_MODE, FILE_MODE), "100755 -> 100644"),
        (Change("T", FILE_MODE, SYMLINK_MODE, "dedupe/core.py"), "symlink"),
        (Change("T", SYMLINK_MODE, FILE_MODE, "dedupe/core.py"), "120000 -> 100644"),
        (Change("D", FILE_MODE, FILE_MODE, "gone.py"), "100644"),
    ],
)
def test_forbidden_file_mode_flags_links_odd_modes_and_mode_changes(
    change: Change, reason: str
) -> None:
    """
    GIVEN a symlink, a gitlink, an unusual mode, a chmod or a type change
    WHEN the capture rules run
    THEN exactly one forbidden_file_mode violation says why
    """
    found = _capture((change,))

    violation = _only(found, ViolationRule.forbidden_file_mode, change.path)
    assert reason in violation.message


@pytest.mark.parametrize(
    "change",
    [
        _deleted("old_link", SYMLINK_MODE),
        _deleted("vendor/old", GITLINK_MODE),
        _deleted("tool.sh", EXEC_MODE),
    ],
)
def test_deleting_a_link_or_executable_is_not_a_mode_violation(change: Change) -> None:
    """
    GIVEN the deletion of a tracked symlink, gitlink or executable
    WHEN the capture rules run
    THEN nothing is reported: deleting leaves no file of that kind behind
    """
    assert _capture((change,)) == ()


def test_links_need_no_blob() -> None:
    """
    GIVEN an added symlink and gitlink with no blob supplied (a gitlink has none)
    WHEN the capture rules run
    THEN only their mode violations are reported, not uncaptured content
    """
    changes = (_added("a", SYMLINK_MODE), _added("b", GITLINK_MODE))

    found = check_capture(changes, {"a": 1, "b": 1}, {}, RSS_JUDGED)

    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.forbidden_file_mode, "a"),
        (ViolationRule.forbidden_file_mode, "b"),
    ]


# git_metadata ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "name"),
    [
        (_added("sub/.gitattributes"), ".gitattributes"),
        (_added(".GITMODULES"), ".gitmodules"),
        (_added("x/.git/config"), ".git"),
        (_modified(".git/hooks/pre-commit"), ".git"),
        (_added("vendor/.Git"), ".git"),
        (_added(".lfsconfig"), ".lfsconfig"),
        (_deleted(".gitattributes"), ".gitattributes"),
        (_modified("a/b/.LfsConfig"), ".lfsconfig"),
    ],
)
def test_git_metadata_flags_git_dirs_and_git_control_files(
    change: Change, name: str
) -> None:
    """
    GIVEN a path inside a .git dir, or a .git, .gitattributes, .gitmodules or
        .lfsconfig file at any depth and in any case
    WHEN the capture rules run
    THEN one git_metadata violation names the path and the metadata name
    """
    found = _capture((change,))

    violation = _only(found, ViolationRule.git_metadata, change.path)
    assert violation.pattern == name


# unrecorded_write ------------------------------------------------------------


def test_unrecorded_write_flags_a_touched_path_the_editor_did_not_report() -> None:
    """
    GIVEN git reports two changed paths but the editor wrote only one
    WHEN the capture rules run
    THEN the other is an unrecorded_write; an extra written path is fine
    """
    changes = (_modified("dedupe/core.py"), _added("dedupe/cache.py"))
    written = {"dedupe/core.py": 120, "dedupe/unchanged.py": 40}

    found = _capture(changes, written=written)

    _only(found, ViolationRule.unrecorded_write, "dedupe/cache.py")


def test_unrecorded_write_covers_deletions_and_compares_paths_verbatim() -> None:
    """
    GIVEN an unreported deletion, a reported deletion (recorded as 0) and a git
        path with a backslash the editor reported in normalised form
    WHEN the capture rules run
    THEN the unreported deletion and the backslash path are unrecorded writes
    """
    changes = (_deleted("a.py"), _deleted("b.py"), _added("pkg\\mod.py"))
    written = {"b.py": 0, "pkg/mod.py": 10}

    found = _capture(changes, written=written)

    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.unrecorded_write, "a.py"),
        (ViolationRule.unrecorded_write, "pkg\\mod.py"),
    ]


# process_spawn ---------------------------------------------------------------

SPAWNING_SOURCES: tuple[str, ...] = (
    "import subprocess\n",
    "import subprocess as sp\n",
    "import multiprocessing\n",
    "import multiprocessing.pool as mp\n",
    # Wave 2b: threads are allowed, so only the process pool is flagged here;
    # 'import concurrent.futures' and 'from concurrent import futures' moved
    # to NON_SPAWNING_SOURCES.
    "from concurrent.futures import ProcessPoolExecutor\n",
    "from concurrent.futures import ProcessPoolExecutor as Pool\n",
    "from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor\n",
    "from concurrent.futures.process import ProcessPoolExecutor\n",
    "from concurrent.futures.process import _process_worker\n",
    "from concurrent.futures import process\n",
    "from concurrent.futures import *\n",
    "import concurrent.futures.process\n",
    "import concurrent.futures.process as cfp\n",
    "from concurrent import *\n",
    "import concurrent.futures\npool = concurrent.futures.ProcessPoolExecutor(2)\n",
    "import concurrent.futures as cf\nwith cf.ProcessPoolExecutor() as pool:\n"
    "    pass\n",
    "import concurrent.futures as cf\nmod = cf.process\n",
    "import concurrent.futures\nmod = concurrent.futures.process\n",
    "from concurrent import futures\nmod = futures.process\n",
    "from concurrent import futures as f\nf.process._process_worker\n",
    "from concurrent import futures as f\npool = f.ProcessPoolExecutor\n",
    "import concurrent as c\nmod = c.futures.process\n",
    "pool = ProcessPoolExecutor(max_workers=4)\n",
    "from subprocess import run as go\n",
    "from multiprocessing import *\n",
    "def helper():\n    import subprocess\n    return subprocess\n",
    "import os\nos.fork()\n",
    "import os\npid, fd = os.forkpty()\n",
    "import os\nos.posix_spawn('/bin/true', ['true'], {})\n",
    "import os as o\no.posix_spawnp('true', ['true'], {})\n",
    "import os\nlauncher = os.posix_spawn\n",
    "import os\nos.execv('/bin/true', ['true'])\n",
    "import os\nos.spawnlp(os.P_WAIT, 'true', 'true')\n",
    "import os\nos.system('true')\n",
    "import os\nos.popen('true')\n",
    "import posix\nposix.fork()\n",
    "from os import fork\n",
    "from os import posix_spawn as ps\n",
    "from os import *\n",
    "x = __import__('sub' + 'process')\n",
    "loader = __import__\n",
    "import builtins\nbuiltins.__import__('subprocess')\n",
    "import importlib\nimportlib.import_module('subprocess')\n",
    "import importlib as il\nmod = il.import_module(name)\n",
    "from importlib import import_module as im\nim('subprocess')\n",
    "from importlib import *\nimport_module('subprocess')\n",
    "import importlib.util\nimportlib.import_module('subprocess')\n",
    "from builtins import __import__ as imp\n",
    # Process APIs outside the three stdlib names the spec lists.
    "import torch.multiprocessing as mp\nmp.spawn(fn, nprocs=4)\n",
    "from torch import multiprocessing\n",
    "from joblib import Parallel, delayed\n",
    "import loky\n",
    "import pty\npty.spawn('true')\n",
    "from pty import fork\n",
    "import asyncio, concurrent\nconcurrent.futures.ProcessPoolExecutor()\n",
    "import concurrent as c\npool = c.futures.ProcessPoolExecutor\n",
    "import asyncio\nasyncio.create_subprocess_exec('true')\n",
    "from asyncio import create_subprocess_shell as sh\n",
    "from asyncio import subprocess\n",
    "import asyncio.subprocess\n",
    "from asyncio import *\n",
    "loop.subprocess_exec(factory, 'true')\n",
    # The stdlib's own fork+exec primitive and drop-in multiprocessing forks.
    "import _posixsubprocess\n_posixsubprocess.fork_exec\n",
    "from _posixsubprocess import fork_exec\n",
    "import multiprocess\nmultiprocess.Pool()\n",
    "from multiprocess.pool import Pool\n",
    "from billiard import Pool\n",
)


@pytest.mark.parametrize("source", SPAWNING_SOURCES)
def test_process_spawn_flags_process_and_dynamic_import_apis(source: str) -> None:
    """
    GIVEN a changed .py file that imports a process API, uses an os spawn
        function or imports dynamically
    WHEN the capture rules run with peak RSS judged
    THEN one process_spawn violation names the path and the line
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source.encode()}, judged=RSS_JUDGED)

    violation = _only(found, ViolationRule.process_spawn, change.path)
    assert "line " in violation.message


NON_SPAWNING_SOURCES: tuple[str, ...] = (
    "# import subprocess\nx = 1\n",
    "x = 1  # os.fork() would fake the RSS win\n",
    '"""Never import multiprocessing here."""\n',
    "s = 'os.posix_spawn(...)'\nt = \"__import__('subprocess')\"\n",
    "import os\nos.path.join('a', 'b')\nos.getpid()\n",
    "import os\nos.register_at_fork(after_in_child=print)\n",
    "import os.path as osp\nosp.exists('x')\n",
    "import concurrent\n",
    "import threading\nthreading.Thread(target=print).start()\n",
    "from . import subprocess\nfrom .multiprocessing import pool\n",
    "from os import path, getpid\n",
    "def fork():\n    return 1\nfork()\n",
    "cursor.execute('select 1')\nself.spawn_count = 2\n",
    "from importlib import resources\n",
    # A project's own import_module is not importlib's.
    "class Loader:\n"
    "    def import_module(self, name):\n"
    "        return self.registry[name]\n"
    "    def go(self):\n"
    "        return self.import_module('x')\n",
    "from mypkg import plugins\nplugins.import_module('x')\n",
    "from mypkg.loader import import_module\nimport_module('x')\n",
    "import_module = registry.get\nimport_module('x')\n",
    "import torch.nn as nn\nimport asyncio\nasyncio.run(main())\n",
    "import concurrent\nconcurrent.interpreters = None\n",
    # Wave 2b: threads share the process, so they cannot fake per-process CPU
    # or RSS accounting. These two were spawning sources before.
    "import concurrent.futures\n",
    "from concurrent import futures\n",
    "from concurrent.futures import ThreadPoolExecutor\n",
    "from concurrent.futures import ThreadPoolExecutor, as_completed, wait\n",
    "from concurrent.futures.thread import ThreadPoolExecutor\n",
    "import concurrent.futures\n"
    "with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:\n"
    "    list(pool.map(str, range(3)))\n",
    "import concurrent.futures as cf\ndone, _ = cf.wait([cf.Future()])\n",
    "from concurrent import futures as f\nf.ThreadPoolExecutor().submit(print)\n",
    "from concurrent import futures\nfutures.as_completed([])\n",
    "import concurrent.futures as cf\ncf.thread.ThreadPoolExecutor\n",
    "import asyncio\nloop.run_in_executor(None, print)\n",
    "worker.process(item)\nself.process = None\n",
    "self.executor.process(job)\n",
    # Names that only start like a spawning module.
    "import multiprocess_utils\nfrom billiards import table\n",
    "from posixsubprocess_docs import notes\n",
)


@pytest.mark.parametrize("source", NON_SPAWNING_SOURCES)
def test_process_spawn_ignores_comments_strings_and_harmless_names(source: str) -> None:
    """
    GIVEN a changed .py file that mentions process APIs only in comments or
        strings, or uses harmless os, threading or relative-import names
    WHEN the capture rules run with peak RSS judged
    THEN nothing is reported
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source.encode()}, judged=RSS_JUDGED)

    assert found == ()


@pytest.mark.parametrize(
    ("source", "finding"),
    [
        ("import concurrent.futures as cf\ncf.process\n", "line 2: uses cf.process"),
        (
            "import concurrent.futures\nconcurrent.futures.process\n",
            "line 2: uses concurrent.futures.process",
        ),
        ("pool = ProcessPoolExecutor()\n", "line 1: uses ProcessPoolExecutor"),
        (
            "import concurrent.futures as cf\ncf.ProcessPoolExecutor()\n",
            "line 2: uses .ProcessPoolExecutor",
        ),
        (
            "from concurrent.futures import ProcessPoolExecutor\n",
            "line 1: imports concurrent.futures.ProcessPoolExecutor",
        ),
    ],
)
def test_process_spawn_names_the_process_pool_it_found(
    source: str, finding: str
) -> None:
    """
    GIVEN a file that reaches concurrent.futures' process pool, but no thread pool
    WHEN the capture rules run with peak RSS judged
    THEN the violation names the process pool reference and its line
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source.encode()}, judged=RSS_JUDGED)

    message = _only(found, ViolationRule.process_spawn, change.path).message
    assert finding in message


def test_process_spawn_metrics_are_cpu_time_and_peak_rss() -> None:
    """
    GIVEN the module constant
    WHEN read
    THEN it names exactly the per-process metrics a child process would fake
    """
    assert (
        frozenset({METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES}) == PROCESS_SPAWN_METRICS
    )


@pytest.mark.parametrize(
    ("judged", "flagged"),
    [
        (frozenset({METRIC_WALL_TIME_S}), False),
        (frozenset(), False),
        (frozenset({METRIC_CPU_TIME_S}), True),
        (frozenset({METRIC_PEAK_RSS_BYTES}), True),
        (frozenset({METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES}), True),
    ],
)
def test_process_spawn_applies_only_when_cpu_or_rss_is_judged(
    judged: frozenset[str], flagged: bool
) -> None:
    """
    GIVEN a changed .py file that imports subprocess
    WHEN the capture rules run with different judged metrics
    THEN it is flagged (once) only when cpu_time_s or peak_rss_bytes is judged
    """
    change = _added("dedupe/fast.py")

    found = _capture(
        (change,), blobs={change.path: b"import subprocess\n"}, judged=judged
    )

    assert [v.rule for v in found] == ([ViolationRule.process_spawn] if flagged else [])


@pytest.mark.parametrize(
    ("change", "flagged"),
    [
        (_added("PKG/MOD.PY"), True),
        (_added("notes/spawn.md"), False),
        (_added("scripts/run.sh", EXEC_MODE), False),
        (_added("pkg/stub.pyi"), False),
        (_deleted("pkg/old.py"), False),
    ],
)
def test_process_spawn_scans_added_or_modified_python_files_only(
    change: Change, flagged: bool
) -> None:
    """
    GIVEN spawning code in a .py file (any case), a non-Python file or a deletion
    WHEN the capture rules run with peak RSS judged
    THEN only the Python file is flagged
    """
    found = _capture(
        (change,), blobs={change.path: b"import subprocess\n"}, judged=RSS_JUDGED
    )

    assert [v.rule for v in found] == ([ViolationRule.process_spawn] if flagged else [])


UNPARSEABLE_SOURCES: tuple[bytes, ...] = (
    b"x = 1\ndef broken(:\n",
    b"x = '\xff'\n",
    b"x = 1\n" + b"#" * 9000 + b"\x00\n",
)


@pytest.mark.parametrize("source", UNPARSEABLE_SOURCES)
def test_process_spawn_fails_closed_on_python_the_engine_cannot_parse(
    source: bytes,
) -> None:
    """
    GIVEN a changed .py file with a syntax error, invalid UTF-8 or a late NUL
    WHEN the capture rules run with peak RSS judged
    THEN it is a process_spawn violation naming the engine's Python: a file the
        engine cannot parse may still run under a newer workload interpreter

    Rewritten in review (was: no violation, "left to the tests"). That premise
    fails when the workload's Python is newer than the engine's.
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source}, judged=RSS_JUDGED)

    message = _only(found, ViolationRule.process_spawn, change.path).message
    assert "could not be scanned" in message
    assert f"Python {sys.version_info.major}.{sys.version_info.minor}" in message


@pytest.mark.parametrize(
    "source",
    [
        b"type _Rows = list[int]\nfrom multiprocessing import Pool\n",
        b"def first[T](xs: list[T]) -> T:\n    return xs[0]\nimport subprocess\n",
        b'd = {\'k\': 1}\ns = f"{d["k"]}"\nimport subprocess\n',
    ],
)
def test_process_spawn_catches_newer_syntax_on_any_engine_python(
    source: bytes,
) -> None:
    """
    GIVEN a spawn next to PEP 695 or PEP 701 syntax (valid on 3.12+, a
        SyntaxError on the 3.11 engine floor)
    WHEN the capture rules run with peak RSS judged
    THEN it is a process_spawn violation on every engine Python: found by the
        scan on 3.12+, refused as unscannable on 3.11
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source}, judged=RSS_JUDGED)

    _only(found, ViolationRule.process_spawn, change.path)


@pytest.mark.parametrize("source", UNPARSEABLE_SOURCES)
def test_unparseable_python_is_not_refused_when_no_spawn_metric_is_judged(
    source: bytes,
) -> None:
    """
    GIVEN a changed .py file the engine cannot parse
    WHEN the capture rules run with only wall time and tests judged
    THEN nothing is reported: the scan does not apply, so the tests decide
    """
    change = _modified("dedupe/core.py")

    assert _capture((change,), blobs={change.path: source}, judged=WALL_ONLY) == ()


WARNING_SOURCE = b"import subprocess\npattern = '\\d+'\n"
"""An invalid escape: a SyntaxWarning (DeprecationWarning on 3.11), not an error."""


def test_process_spawn_scan_ignores_the_callers_warning_filters() -> None:
    """
    GIVEN a spawning file with an invalid escape and warnings turned into errors
        (PYTHONWARNINGS=error, -W error)
    WHEN the capture rules run with peak RSS judged
    THEN the spawn is still found: a warning must not turn into a SyntaxError
    """
    change = _modified("dedupe/core.py")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        found = _capture(
            (change,), blobs={change.path: WARNING_SOURCE}, judged=RSS_JUDGED
        )

    message = _only(found, ViolationRule.process_spawn, change.path).message
    assert "imports subprocess" in message


def test_process_spawn_scan_keeps_user_code_warnings_off_the_engine() -> None:
    """
    GIVEN a scanned file whose source makes the compiler warn
    WHEN the capture rules run with every warning recorded
    THEN no warning reaches the engine
    """
    change = _modified("dedupe/core.py")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _capture((change,), blobs={change.path: WARNING_SOURCE}, judged=RSS_JUDGED)

    assert [str(w.message) for w in caught] == []


@pytest.mark.parametrize(
    ("source", "flagged"),
    [
        (b"#!/usr/bin/env python3\nimport subprocess\n", True),
        (b"#!/usr/bin/Python3.11 -I\nimport os\nos.fork()\n", True),
        (b"#!/usr/bin/env python3\nprint('ok')\n", False),
        (b"#!/bin/sh\nexec python3 -c 'import subprocess'\n", False),
        (b"import subprocess\n", False),
    ],
)
def test_process_spawn_scans_python_scripts_named_by_their_shebang(
    source: bytes, flagged: bool
) -> None:
    """
    GIVEN an added executable without a .py suffix (a workload may run it as
        ``python scripts/bench``)
    WHEN the capture rules run with peak RSS judged
    THEN it is scanned when its first line is a python shebang, and only then
        (a shell script is never parsed as Python)
    """
    change = _added("scripts/bench", EXEC_MODE)

    found = _capture((change,), blobs={change.path: source}, judged=RSS_JUDGED)

    assert [v.rule for v in found] == ([ViolationRule.process_spawn] if flagged else [])


# Paths that are not valid UTF-8 -----------------------------------------------


def test_capture_reports_a_non_utf8_path_once_without_embedding_it() -> None:
    """
    GIVEN a git path decoded with surrogateescape (a non-UTF-8 file name, as
        os.fsdecode returns it) that would also break other rules
    WHEN the capture rules run
    THEN exactly one forbidden_file violation is reported, with no path and an
        ascii-escaped name in the message, so the violation serialises to JSON
    """
    path = "x/.git/m\udcff.so"
    change = _added(path, SYMLINK_MODE)

    found = check_capture((change,), {}, {}, RSS_JUDGED)

    assert [(v.rule, v.path) for v in found] == [(ViolationRule.forbidden_file, None)]
    assert ascii(path) in found[0].message
    assert "UTF-8" in found[0].message
    assert "forbidden_file" in found[0].model_dump_json()


@pytest.mark.parametrize(
    "source",
    [
        b"x = " + b"+".join([b"1"] * 100_000) + b"\n",
        b"x = " + b"-" * 200_000 + b"1\n",
    ],
)
def test_process_spawn_fails_closed_on_python_too_deep_to_scan(source: bytes) -> None:
    """
    GIVEN a changed .py file that exhausts the parser's recursion or stack
        (it may still compile under the workload's own interpreter)
    WHEN the capture rules run with peak RSS judged
    THEN it is a process_spawn violation: unscanned code is refused
    """
    change = _modified("dedupe/core.py")

    found = _capture((change,), blobs={change.path: source}, judged=RSS_JUDGED)

    violation = _only(found, ViolationRule.process_spawn, change.path)
    assert "could not be scanned" in violation.message


def test_process_spawn_message_lists_findings_in_line_order() -> None:
    """
    GIVEN a file with several spawning constructs
    WHEN the capture rules run with CPU time judged
    THEN one violation lists them by line, at most three
    """
    source = (
        b"import os\n"
        b"def run():\n"
        b"    os.fork()\n"
        b"import subprocess\n"
        b"from multiprocessing import Pool\n"
        b"x = __import__('pty')\n"
    )
    change = _added("dedupe/fast.py")

    found = _capture(
        (change,), blobs={change.path: source}, judged=frozenset({METRIC_CPU_TIME_S})
    )

    message = _only(found, ViolationRule.process_spawn, change.path).message
    assert message.index("line 3") < message.index("line 4") < message.index("line 5")
    assert "line 6" not in message
    assert "os.fork" in message and "subprocess" in message


# One violation per (rule, path) ------------------------------------------------


def test_capture_reports_each_rule_once_per_path_in_change_order() -> None:
    """
    GIVEN a binary compiled artefact inside a .git dir listed twice, then an
        unreported symlink
    WHEN the capture rules run
    THEN each (rule, path) appears once, in change order, as Violation models
    """
    meta = _added(".git/hooks/evil.so")
    link = _added("dedupe/fast.py", SYMLINK_MODE)
    blobs = {meta.path: b"\x7fELF\x00\x00"}

    found = _capture((meta, meta, link), blobs=blobs, written={meta.path: 6})

    assert all(isinstance(v, Violation) for v in found)
    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.forbidden_file, meta.path),
        (ViolationRule.git_metadata, meta.path),
        (ViolationRule.forbidden_file_mode, link.path),
        (ViolationRule.unrecorded_write, link.path),
    ]
    assert found[0].pattern == "*.so"


def test_capture_follows_the_e2e_fixture_shapes() -> None:
    """
    GIVEN the E2E-B shapes: h2 deletes a test and edits core (both reported),
        h6 adds a reported symlink next to its edit
    WHEN the capture rules run with RSS judged
    THEN h2 is clean here (protected_path is check_diff_all's job) and h6 is
        exactly one forbidden_file_mode
    """
    h2 = (_deleted("tests/test_core.py"), _modified("dedupe/core.py"))
    h6 = (_added("dedupe/fast.py", SYMLINK_MODE), _modified("dedupe/core.py"))

    assert _capture(h2, judged=RSS_JUDGED) == ()
    h6_found = check_capture(
        h6,
        {"dedupe/fast.py": len(b"core.py"), "dedupe/core.py": 200},
        {"dedupe/core.py": PLAIN_SOURCE},
        RSS_JUDGED,
    )
    _only(h6_found, ViolationRule.forbidden_file_mode, "dedupe/fast.py")


# module_shadow (wave 2b) -------------------------------------------------------

SHADOWING_ADDS: tuple[tuple[str, str], ...] = (
    # python -m unittest and pytest put the working directory first on
    # sys.path, so these replace the runner and a failing suite "passes".
    ("unittest.py", "unittest"),
    ("pytest.py", "pytest"),
    ("_pytest/__init__.py", "_pytest"),
    ("pytest/__main__.py", "pytest"),
    ("site.py", "site"),
    ("__future__.py", "__future__"),
    ("src/unittest.py", "unittest"),
    ("src/pluggy/__init__.py", "pluggy"),
    ("src/json/deep/x.py", "json"),
    # A new reserved directory, whatever it holds, as the editor refuses it.
    ("json/notes.txt", "json"),
    # Case-insensitive, because macOS filesystems are.
    ("PyTest.py", "pytest"),
    ("SRC/pytest.py", "pytest"),
    ("Unittest/__init__.py", "unittest"),
)


@pytest.mark.parametrize("judged", [WALL_ONLY, RSS_JUDGED])
@pytest.mark.parametrize(("path", "name"), SHADOWING_ADDS)
def test_module_shadow_flags_a_new_reserved_top_level_module(
    path: str, name: str, judged: frozenset[str]
) -> None:
    """
    GIVEN an added path that creates a top-level module or package, at the
        repo root or directly under src/, named after a stdlib or test-runner
        module (the ScriptedEditor bypasses the editor's own refusal)
    WHEN the capture rules run, whatever metrics are judged
    THEN one module_shadow violation names the path and the module
    """
    found = _capture((_added(path),), judged=judged)

    violation = _only(found, ViolationRule.module_shadow, path)
    assert violation.pattern == name
    assert repr(name) in violation.message
    assert "shadow" in violation.message


@pytest.mark.parametrize(
    "change",
    [
        # The user's own modules named like stdlib ones stay editable.
        _modified("profile.py"),
        _modified("src/json/__init__.py"),
        _deleted("unittest.py"),
        _deleted("src/pytest/__init__.py"),
        # Not a top-level module on a trial's sys.path.
        _added("docs/json.py"),
        _added("src/pkg/pytest.py"),
        _added("lib/src/unittest.py"),
        _added("src/__init__.py"),
        # Not importable, or not reserved.
        _added("pytest.txt"),
        _added("unittest.pyi"),
        _added("src/json"),
        _added("src/core_json.py"),
        _added("numpy.py"),
        _added("src.py"),
        _added("dedupe/fast.py"),
    ],
)
def test_module_shadow_ignores_existing_nested_and_unimportable_paths(
    change: Change,
) -> None:
    """
    GIVEN a change that edits or deletes an existing module, adds a submodule,
        a path off sys.path, a data file or a module with an unreserved name
    WHEN the capture rules run
    THEN nothing is reported
    """
    assert _capture((change,)) == ()


@pytest.mark.parametrize(
    "changes",
    [
        (_modified("src/json/core.py"), _added("src/json/fast.py")),
        (_added("src/json/fast.py"), _modified("src/json/core.py")),
        (_deleted("code/old.py"), _added("code/new.py")),
        (_modified("JSON/core.py"), _added("json/fast.py")),
    ],
)
def test_module_shadow_allows_new_files_in_a_reserved_directory_the_base_has(
    changes: tuple[Change, ...],
) -> None:
    """
    GIVEN a reserved-named directory the user's repo already has, proven by a
        modified or deleted path under it in the same diff (in any order)
    WHEN the trial adds a module inside it
    THEN no new top-level package is created, so nothing is reported (the
        editor allows the same edit)
    """
    assert _capture(changes) == ()


def test_module_shadow_counts_a_retyped_path_as_proof_too() -> None:
    """
    GIVEN a retyped path under json/ next to a module added there
    WHEN the capture rules run
    THEN only the retyped path's mode is reported: json/ existed at the base
    """
    retyped = Change("T", FILE_MODE, SYMLINK_MODE, "json/link")

    found = _capture((retyped, _added("json/fast.py")))

    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.forbidden_file_mode, "json/link")
    ]


@pytest.mark.parametrize(
    ("changes", "path"),
    [
        # A namespace directory turned into a regular package wins the import.
        ((_modified("json/data.txt"), _added("json/__init__.py")), "json/__init__.py"),
        (
            (_modified("src/json/data.txt"), _added("src/json/__init__.py")),
            "src/json/__init__.py",
        ),
        # A file called json is not a json/ directory.
        ((_deleted("json"), _added("json/util.py")), "json/util.py"),
        # Proof at the other level does not count.
        ((_modified("src/json/core.py"), _added("json/x.txt")), "json/x.txt"),
        ((_modified("json/a.py"), _added("src/json/b.py")), "src/json/b.py"),
    ],
)
def test_module_shadow_needs_proof_that_the_base_had_the_directory(
    changes: tuple[Change, ...], path: str
) -> None:
    """
    GIVEN an added path under a reserved name whose directory the diff does not
        prove existed, or an added __init__.py that makes it a regular package
    WHEN the capture rules run
    THEN the added path is a module_shadow violation
    """
    _only(_capture(changes), ViolationRule.module_shadow, path)


def test_module_shadow_flags_every_added_path_of_a_new_reserved_package() -> None:
    """
    GIVEN two added files in a new reserved directory (one is no proof for the
        other)
    WHEN the capture rules run
    THEN both are module_shadow violations, in change order
    """
    found = _capture((_added("json/a.txt"), _added("JSON/b.txt")))

    assert [(v.rule, v.path, v.pattern) for v in found] == [
        (ViolationRule.module_shadow, "json/a.txt", "json"),
        (ViolationRule.module_shadow, "JSON/b.txt", "json"),
    ]


def test_module_shadow_reserved_names_can_be_extended_or_replaced() -> None:
    """
    GIVEN the trial runner's own reserved set (the default plus a workload's
        '-m' target, in any case), or an empty one
    WHEN the capture rules run
    THEN the extra name is reserved next to the default ones, and an empty set
        reserves nothing
    """
    numpy_pkg, json_mod = _added("numpy/__init__.py"), _added("json.py")

    extended = _capture(
        (numpy_pkg, json_mod), reserved_modules=RESERVED_MODULES | {"NumPy"}
    )

    assert [(v.rule, v.path, v.pattern) for v in extended] == [
        (ViolationRule.module_shadow, "numpy/__init__.py", "numpy"),
        (ViolationRule.module_shadow, "json.py", "json"),
    ]
    assert _capture((numpy_pkg,)) == ()
    assert _capture((_added("unittest.py"),), reserved_modules=frozenset()) == ()


def test_module_shadow_is_reported_next_to_the_other_rules() -> None:
    """
    GIVEN an added symlink called unittest.py, listed twice, that the editor
        did not report and that has no blob (a link has none)
    WHEN the capture rules run
    THEN its mode, the unrecorded write and the shadowing are each reported once
    """
    link = _added("unittest.py", SYMLINK_MODE)

    found = check_capture((link, link), {}, {}, RSS_JUDGED)

    assert [(v.rule, v.path) for v in found] == [
        (ViolationRule.forbidden_file_mode, link.path),
        (ViolationRule.unrecorded_write, link.path),
        (ViolationRule.module_shadow, link.path),
    ]


@pytest.mark.parametrize(
    ("changes", "effect"),
    [
        ((_added("unittest.py"),), "which creates the top-level module 'unittest'"),
        ((_added("json/notes.txt"),), "which creates the top-level package 'json'"),
        (
            (_modified("JSON/data.txt"), _added("JSON/__init__.py")),
            "which makes the existing directory 'JSON' the regular package 'json'",
        ),
        (
            (_modified("src/json/data.txt"), _added("src/json/__init__.py")),
            "which makes the existing directory 'src/json' the regular package 'json'",
        ),
    ],
)
def test_module_shadow_says_what_the_added_path_creates(
    changes: tuple[Change, ...], effect: str
) -> None:
    """
    GIVEN an added module, a file in a new reserved directory, or an
        __init__.py in a reserved directory the base already had
    WHEN the capture rules run
    THEN the message says whether it creates a module, a package, or turns
        the existing directory into a regular package
    """
    path = changes[-1].path

    message = _only(_capture(changes), ViolationRule.module_shadow, path).message

    assert f"trial adds {path!r}, {effect} that would shadow" in message


def test_module_shadow_refuses_a_str_for_a_set_of_names() -> None:
    """
    GIVEN reserved_modules passed as one str (iterating it would reserve its
        letters and let unittest.py through)
    WHEN the capture rules run
    THEN a TypeError names the keyword; the type: ignore below also fails
        mypy (warn_unused_ignores) if the signature ever accepts a str again
    """
    change = _added("unittest.py")

    with pytest.raises(TypeError, match="reserved_modules"):
        check_capture(
            (change,),
            {change.path: 1},
            {change.path: PLAIN_SOURCE},
            WALL_ONLY,
            reserved_modules="unittest",  # type: ignore[arg-type]
        )


def test_module_shadow_reserves_the_top_level_part_of_a_dotted_name() -> None:
    """
    GIVEN a reserved set extended with a dotted '-m' target ('dedupe.main')
    WHEN the trial adds the package or module that import starts from
    THEN both are module_shadow violations on the first component
    """
    reserved = RESERVED_MODULES | {"dedupe.main"}

    found = _capture(
        (_added("dedupe/__init__.py"), _added("Dedupe.py")), reserved_modules=reserved
    )

    assert [(v.rule, v.path, v.pattern) for v in found] == [
        (ViolationRule.module_shadow, "dedupe/__init__.py", "dedupe"),
        (ViolationRule.module_shadow, "Dedupe.py", "dedupe"),
    ]
    # The user's own package of that name, which the base has, stays editable.
    own = _capture(
        (_added("dedupe/fast.py"),),
        reserved_modules=reserved,
        existing_dirs=frozenset({"dedupe"}),
    )
    assert own == ()


# module_shadow: the base tree's directories and extra module roots ------------

BASE_TREE_DIRS = frozenset({"code", "src/email", "Queue", "dedupe"})


@pytest.mark.parametrize(
    "changes",
    [
        # The finding's case: nothing else under code/ changes.
        (_added("code/fast.py"), _modified("main.py")),
        (_added("code/sub/deep.py"),),
        (_added("src/email/fast.py"),),
        # Case-insensitive, because macOS filesystems are.
        (_added("queue/fast.py"),),
        (_added("CODE/notes.txt"),),
    ],
)
def test_module_shadow_trusts_the_base_tree_directories_it_is_given(
    changes: tuple[Change, ...],
) -> None:
    """
    GIVEN the base tree's directories (the trial runner lists them with
        git ls-tree), holding the user's own code/, src/email/ and Queue/
    WHEN the trial adds a file inside one, with no other change under it
    THEN nothing is reported: the WorktreeEditor allows the same write
    """
    assert _capture(changes, existing_dirs=BASE_TREE_DIRS) == ()


@pytest.mark.parametrize(
    "path",
    [
        # A regular package beats a namespace portion and the stdlib.
        "code/__init__.py",
        "src/email/__init__.py",
        # A module next to the directory, or a directory the base lacks.
        "code.py",
        "json/fast.py",
        # Listed at the other root only.
        "email/fast.py",
        "src/code/fast.py",
    ],
)
def test_module_shadow_still_flags_what_the_base_tree_does_not_have(path: str) -> None:
    """
    GIVEN the base tree's directories
    WHEN the trial adds an __init__.py to one, a reserved module beside it, or
        a file in a reserved directory the base does not have at that root
    THEN the added path is a module_shadow violation
    """
    _only(
        _capture((_added(path),), existing_dirs=BASE_TREE_DIRS),
        ViolationRule.module_shadow,
        path,
    )


def test_module_shadow_counts_the_diff_proof_next_to_the_base_tree() -> None:
    """
    GIVEN an empty base-tree listing (nothing at the roots is a directory)
    WHEN the diff itself proves json/ existed, or proves nothing
    THEN the proven directory stays open and the other is flagged
    """
    proven = (_modified("json/core.py"), _added("json/fast.py"))

    assert _capture(proven, existing_dirs=frozenset()) == ()
    _only(
        _capture((_added("code/fast.py"),), existing_dirs=frozenset()),
        ViolationRule.module_shadow,
        "code/fast.py",
    )


def test_default_module_roots_are_the_repo_root_and_src() -> None:
    """
    GIVEN the module roots check_capture uses by default
    WHEN read
    THEN they are the repo root ('') and src/, which python -m and the
        engine's PYTHONPATH put first on sys.path
    """
    assert frozenset({"", "src"}) == DEFAULT_MODULE_ROOTS


SCRIPT_ROOTS = DEFAULT_MODULE_ROOTS | {"scripts", "./Tools/bin/"}


@pytest.mark.parametrize(
    ("path", "name"),
    [
        # 'python scripts/run_tests.py' puts scripts/ first on sys.path.
        ("scripts/unittest.py", "unittest"),
        ("SCRIPTS/pytest/__init__.py", "pytest"),
        ("tools/bin/site.py", "site"),
        ("scripts/json/notes.txt", "json"),
        # The default roots stay covered.
        ("unittest.py", "unittest"),
        ("src/unittest.py", "unittest"),
    ],
)
def test_module_shadow_covers_every_module_root_it_is_given(
    path: str, name: str
) -> None:
    """
    GIVEN module roots extended with the directories of the test command's
        scripts (in any case and spelling: './Tools/bin/' is tools/bin)
    WHEN the trial adds a reserved top-level module or package to any root
    THEN it is a module_shadow violation naming the module
    """
    found = _capture((_added(path),), module_roots=SCRIPT_ROOTS)

    assert _only(found, ViolationRule.module_shadow, path).pattern == name


@pytest.mark.parametrize(
    "changes",
    [
        (_added("scripts/sub/unittest.py"),),
        (_added("tools/unittest.py"),),
        (_added("scripts/helper.py"),),
        (_modified("scripts/json/a.py"), _added("scripts/json/b.py")),
    ],
)
def test_module_shadow_ignores_what_no_module_root_imports_first(
    changes: tuple[Change, ...],
) -> None:
    """
    GIVEN extra module roots
    WHEN the trial adds a path nested below a root, beside one, unreserved, or
        inside a reserved directory the diff proves the base had
    THEN nothing is reported
    """
    assert _capture(changes, module_roots=SCRIPT_ROOTS) == ()


def test_module_shadow_roots_use_the_base_tree_and_are_the_full_set() -> None:
    """
    GIVEN a script root whose reserved-named directory the base tree has, the
        default roots, and a root set without the repo root
    WHEN the trial adds files there
    THEN the base directory stays open, scripts/ is no root by default, and a
        set without '' does not cover the repo root (callers pass the full set)
    """
    in_base = _capture(
        (_added("scripts/json/x.py"),),
        module_roots=SCRIPT_ROOTS,
        existing_dirs=frozenset({"scripts/json"}),
    )

    assert in_base == ()
    assert _capture((_added("scripts/unittest.py"),)) == ()
    assert _capture((_added("unittest.py"),), module_roots=frozenset({"src"})) == ()


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("module_roots", frozenset({"../outside"})),
        ("existing_dirs", frozenset({"/abs"})),
    ],
)
def test_module_shadow_refuses_paths_that_leave_the_repo(
    keyword: str, value: frozenset[str]
) -> None:
    """
    GIVEN a module root or a base directory that is absolute or uses '..'
    WHEN the capture rules run
    THEN PathTraversalError is raised (a caller bug, never a silent pass)
    """
    roots = value if keyword == "module_roots" else DEFAULT_MODULE_ROOTS
    dirs = value if keyword == "existing_dirs" else None

    with pytest.raises(PathTraversalError):
        _capture((_added("unittest.py"),), module_roots=roots, existing_dirs=dirs)


def test_module_shadow_refuses_a_str_for_the_path_sets() -> None:
    """
    GIVEN module_roots or existing_dirs passed as one str
    WHEN the capture rules run
    THEN a TypeError names the keyword (mypy refuses the call too)
    """
    change = _added("scripts/unittest.py")
    args = ((change,), {change.path: 1}, {change.path: PLAIN_SOURCE}, WALL_ONLY)

    with pytest.raises(TypeError, match="module_roots"):
        check_capture(*args, module_roots="scripts")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="existing_dirs"):
        check_capture(*args, existing_dirs="scripts")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# quality_data_reference (Step 3, D37): a tripwire on the added lines
# ---------------------------------------------------------------------------

LABELS_CSV = "data/labels.csv"


class _Patches:
    """Each modified file's ``-U0`` patch from real git (``--no-index`` on
    temporary copies), fed one byte at a time so a line spans chunks.
    ``asked`` lists the paths whose patch was requested, ``read`` those whose
    base was."""

    def __init__(self, blobs: Mapping[str, bytes], bases: Mapping[str, bytes]) -> None:
        self.blobs, self.bases = blobs, bases
        self.asked, self.read = list[str](), list[str]()

    def base_of(self, path: str) -> bytes | None:
        self.read.append(path)
        return self.bases.get(path)

    def __call__(self, path: str, sink: Callable[[bytes], None]) -> None:
        self.asked.append(path)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "old").write_bytes(self.bases[path])
            (Path(tmp) / "new").write_bytes(self.blobs[path])
            argv = ["git", "diff", "--no-index", "--no-color", "-U0", "old", "new"]
            env = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}  # fmt: skip
            done = subprocess.run(argv, cwd=tmp, env=env, capture_output=True, check=False)  # fmt: skip
        assert done.returncode in (0, 1), done.stderr  # 1: the files differ
        for byte in done.stdout:
            sink(bytes((byte,)))


def _references(
    new: Mapping[str, str | bytes],
    base: Mapping[str, str | bytes] | None = None,
    frozen: Sequence[str] = (LABELS_CSV,),
    patches: list[_Patches] | None = None,
) -> list[tuple[str | None, str | None]]:
    """(changed file, frozen path) of every quality_data_reference found."""

    def raw(text: str | bytes) -> bytes:
        return text if isinstance(text, bytes) else text.encode()

    blobs = {path: raw(text) for path, text in new.items()}
    bases = {path: raw(text) for path, text in (base or {}).items()}
    patch = _Patches(blobs, bases)
    found = check_quality_references(blobs, patch.base_of, frozen, patch)
    if patches is not None:
        patches.append(patch)
    assert {v.rule for v in found} <= {ViolationRule.quality_data_reference}
    return [(v.path, v.pattern) for v in found]


@pytest.mark.parametrize(
    "line",
    [
        "rows = open('data/labels.csv').read()",  # the frozen path
        'y = pd.read_csv("labels.csv")',  # its basename alone
        "p = Path(ROOT) / 'data' / 'labels.csv'",
        "load('../data/labels.csv')",
        r"load('C:\\work\\labels.csv')",
        "x = '/abs/mydata/labels.csv'",  # the basename after any '/'
        "# reads labels.csv.",  # a trailing dot ends the name
        "names = ['labels.csv', 'b']",
        "f(labels.csv)",
        "labels.csv",
    ],
)
def test_quality_reference_flags_an_added_line_naming_a_frozen_file(line: str) -> None:
    """
    GIVEN a frozen quality file and an added line that names it or its
          basename as a whole token
    WHEN the quality reference rule runs
    THEN one quality_data_reference names the changed file and the frozen path
    """
    assert _references({"predict.py": f"import x\n{line}\n"}) == [
        ("predict.py", LABELS_CSV)
    ]


@pytest.mark.parametrize(
    "line",
    [
        "old_labels.csv_backup",
        "labels.csv.bak",
        "labels.csv_v2",
        "labels.csvx",
        "mylabels.csv",
        "my-labels.csv",
        "labels.csv-old",
        ".labels.csv",
        "labels.csv2",
        "labels_csv",
        "labels.tsv",
        "labels",
        "data/labels.cs",
        "étiquettes.csv",
    ],
)
def test_quality_reference_needs_a_whole_token(line: str) -> None:
    """
    GIVEN an added line holding a longer or different file name
    WHEN the quality reference rule runs
    THEN nothing is flagged: letters, digits, '_', '.' or '-' on either side
         continue the name (a trailing run of '.' or '-' does not)
    """
    assert _references({"predict.py": f"x = '{line}'\n"}) == []


@pytest.mark.parametrize(
    ("frozen", "line"),
    [
        (LABELS_CSV, "open('DATA/LABELS.CSV')"),
        (LABELS_CSV, "open('Labels.Csv')"),
        ("data/étiquettes.csv", unicodedata.normalize("NFD", "x = 'étiquettes.csv'")),
        (unicodedata.normalize("NFD", "data/étiquettes.csv"), "x = 'étiquettes.csv'"),
        ("data/étiquettes.csv", "x = 'ÉTIQUETTES.CSV'"),
        ("data/STRASSE.csv", "x = 'straße.csv'"),
    ],
)
def test_quality_reference_folds_case_and_unicode_normalisation(
    frozen: str, line: str
) -> None:
    """
    GIVEN a spelling a case-insensitive, normalisation-insensitive file
          system (APFS) opens as the frozen file
    WHEN the quality reference rule runs
    THEN it is flagged (both sides NFC-normalised and case-folded)
    """
    assert _references({"a.py": line + "\n"}, frozen=(frozen,)) == [("a.py", frozen)]


def test_quality_reference_counts_only_added_lines() -> None:
    """
    GIVEN a modified file whose base already names the frozen file
    WHEN the trial keeps that line as context, removes it, or adds other lines
    THEN nothing is flagged; a second copy of the line, a changed line and a
         new file's lines are added lines and are flagged
    """
    base = {"a.py": "import x\nLABELS = 'data/labels.csv'\nrun()\n"}
    kept = {"a.py": "import x\nLABELS = 'data/labels.csv'\nrun(fast=True)\n"}
    removed = {"a.py": "import x\nrun()\n"}
    copied = {"a.py": base["a.py"] + "AGAIN = 'data/labels.csv'\n"}
    twice = {"a.py": base["a.py"] + "LABELS = 'data/labels.csv'\n"}
    changed = {"a.py": "import x\nLABELS = open('data/labels.csv')\nrun()\n"}

    assert _references(kept, base) == []
    assert _references(removed, base) == []
    two = {"a.py": "A = 'labels.csv'\nB = 'labels.csv'\n"}
    assert _references({"a.py": "A = 'labels.csv'\n"}, two) == []  # one removed
    assert _references(base, base) == []
    for new in (copied, twice, changed):
        assert _references(new, base) == [("a.py", LABELS_CSV)]
    assert _references({"b.py": base["a.py"]}, base) == [("b.py", LABELS_CSV)]


def test_quality_reference_applies_only_with_a_quality_check() -> None:
    """
    GIVEN no frozen paths (no quality check: Step 2)
    WHEN the quality reference rule runs on lines naming any file
    THEN it finds nothing
    """
    assert _references({"a.py": "open('data/labels.csv')\n"}, frozen=()) == []


def test_quality_reference_message_names_the_frozen_path_not_the_line() -> None:
    """
    GIVEN an added line naming a frozen file next to other content
    WHEN the quality reference rule runs
    THEN the message names the changed file and the frozen path, never the
         rest of the line
    """
    line = "TOKEN = 'sk-SECRET-123'; rows = open('labels.csv')\n"
    [found] = check_quality_references(
        {"a.py": line.encode()}, dict[str, bytes]().get, (LABELS_CSV,), _Patches({}, {})
    )

    assert found.rule is ViolationRule.quality_data_reference
    assert (found.path, found.pattern) == ("a.py", LABELS_CSV)
    assert LABELS_CSV in found.message and "a.py" in found.message
    assert "SECRET" not in found.message and "open" not in found.message
    assert found.message.startswith("quality_data_reference: ")


def test_quality_reference_reports_each_file_and_frozen_path_once() -> None:
    """
    GIVEN two changed files naming two frozen files, one of them many times
    WHEN the quality reference rule runs
    THEN one violation per (changed file, frozen path), in order
    """
    frozen = (LABELS_CSV, "score.py")
    new = {
        "a.py": "x = 'labels.csv'\ny = 'labels.csv'\nz = 'score.py'\n",
        "b.py": "w = 'data/labels.csv'\n",
        "c.py": "import score\n",
        "settings.yaml": "labels: data/labels.csv\n",
    }
    assert _references(new, frozen=frozen) == [
        ("a.py", LABELS_CSV),
        ("a.py", "score.py"),
        ("b.py", LABELS_CSV),
        ("settings.yaml", LABELS_CSV),
    ]


TRAIN = "import x\n\ndef train():\n    rows = open('data/labels.csv').read()\n    return rows\n\ndef predict():\n    return 1\n"  # fmt: skip
MOVED = "import x\n\ndef train():\n    return 0\n\ndef predict():\n    rows = open('data/labels.csv').read()\n    return rows\n"  # fmt: skip


@pytest.mark.parametrize(
    ("frozen", "spelled"),
    [
        (LABELS_CSV, "data/labels.csv"),
        (LABELS_CSV, "DATA/LABELS.CSV"),
        ("data/étiquettes.csv", unicodedata.normalize("NFD", "data/étiquettes.csv")),
    ],
)
def test_quality_reference_counts_a_moved_line_as_git_shows_it(
    frozen: str, spelled: str
) -> None:
    """
    GIVEN a base line naming the labels (in any spelling the file system
          opens) moved verbatim from train() into predict(), so the new
          content holds it as often as the base
    WHEN the quality reference rule runs
    THEN git's patch for that file is read and the line, which git shows as
         added, is flagged; a line git shows as context is not: here a
         reorder of the lines after it. A kept line whose neighbours are
         edited is context too, so it is not flagged: a tripwire, not
         closure; the review branch's diff is the backstop (D37)
    """
    patches: list[_Patches] = []
    train, moved = (t.replace(LABELS_CSV, spelled) for t in (TRAIN, MOVED))
    assert _references({"a.py": moved}, {"a.py": train}, (frozen,), patches) == [
        ("a.py", frozen)
    ]
    base = f"LABELS = '{spelled}'\nA = 1\nB = 2\n"
    reordered = f"LABELS = '{spelled}'\nB = 2\nA = 1\n"
    assert _references({"a.py": reordered}, {"a.py": base}, (frozen,), patches) == []
    assert [p.asked for p in patches] == [["a.py"], ["a.py"]]


def test_quality_reference_reads_every_needle_a_file_leaves_unsure() -> None:
    """
    GIVEN a moved base line naming two frozen files at once
    WHEN the quality reference rule runs
    THEN one patch read decides both, and both are flagged
    """
    frozen = (LABELS_CSV, "score.py")
    both = "open('data/labels.csv'), 'score.py'"
    train, moved = (t.replace("open('data/labels.csv')", both) for t in (TRAIN, MOVED))
    patches: list[_Patches] = []
    found = _references({"a.py": moved}, {"a.py": train}, frozen, patches)
    assert found == [("a.py", LABELS_CSV), ("a.py", "score.py")]
    assert patches[0].asked == ["a.py"]


def test_quality_reference_treats_a_binary_patch_as_naming_the_file() -> None:
    """
    GIVEN a base with a NUL in its first 8000 bytes, so git prints "Binary
          files ... differ" instead of lines, and a NUL-free new text that
          keeps the base's reference line
    WHEN the quality reference rule runs
    THEN it fails closed: the file is flagged as unreadable, naming the
         frozen path
    """
    base = b"# \x00 header\n" + TRAIN.encode()
    new = MOVED.encode()
    blobs, bases = {"a.py": new}, {"a.py": base}
    patch = _Patches(blobs, bases)
    found = check_quality_references(blobs, bases.get, (LABELS_CSV,), patch)
    assert patch.asked == ["a.py"]
    assert [(v.path, v.pattern) for v in found] == [("a.py", LABELS_CSV)]
    assert "could not be read as text" in found[0].message
    assert LABELS_CSV in found[0].message


def test_quality_reference_asks_git_only_when_the_fast_path_cannot_tell() -> None:
    """
    GIVEN an added file, a modified file whose counted added lines already
          name the labels, and one whose new content never names them
    WHEN the quality reference rule runs
    THEN no patch is read: only a modified file naming the labels as often
         as its base needs git
    """
    patches: list[_Patches] = []
    twice = TRAIN + "    rows = open('data/labels.csv').read()\n"  # a second copy
    new = {"new.py": TRAIN, "a.py": TRAIN + "B = 'labels.csv'\n", "d.py": twice, "c.py": "x = 2\n"}  # fmt: skip
    base = {"a.py": TRAIN, "d.py": TRAIN, "c.py": TRAIN}
    assert _references(new, base, patches=patches) == [
        ("new.py", LABELS_CSV),
        ("a.py", LABELS_CSV),
        ("d.py", LABELS_CSV),
    ]
    assert patches[0].asked == []
    assert patches[0].read == ["new.py", "a.py", "d.py"]  # c.py names nothing: unread


def test_quality_reference_reads_only_the_patchs_added_lines() -> None:
    """
    GIVEN a patch whose headers, removed lines and no-newline marker name
          the labels, and an added line starting with '++'
    WHEN the quality reference rule reads it
    THEN only the added lines count, a header is never one, and a hunk of a
         second file in the patch starts its headers again
    """
    header = b"diff --git a/labels.csv/a.py b/labels.csv/a.py\n--- a/labels.csv/a.py\n+++ b/labels.csv/a.py\n"  # fmt: skip
    quiet = header + b"@@ -1 +1 @@\n-x = 'a' + 'labels.csv'\n+x = 1\n\\ labels.csv\n"
    second = quiet + header + b"@@ -2 +2 @@\n"
    loud = quiet + b"@@ -3 +3 @@\n+++ 'labels.csv'"  # no final newline
    latin = quiet + b"@@ -4 +4 @@\n+x = '\xff' + open('labels.csv')\n"  # not UTF-8

    def check(patch: bytes) -> list[str | None]:
        def stream(path: str, sink: Callable[[bytes], None]) -> None:
            sink(patch)

        found = check_quality_references({"a.py": b"labels.csv\n"}, {"a.py": b"labels.csv\n"}.get, (LABELS_CSV,), stream)  # fmt: skip
        return [v.path for v in found]

    bare = header.split(b"\n", 1)[1] + b"@@ -1 +1 @@\n+x = 1\n"  # no 'diff' line
    assert check(quiet) == [] and check(second) == [] and check(bare) == []
    assert check(loud) == ["a.py"] and check(latin) == ["a.py"]


def test_quality_reference_reads_a_long_patch_line_in_linear_time() -> None:
    """
    GIVEN an 8 MiB added line arriving in 256-byte chunks
    WHEN the quality reference rule reads it
    THEN it is found, and quickly: no chunk re-copies the line read so far
         (that would copy about 128 GiB here)
    """
    line = b"+" + b"x" * (8 << 20) + b" open('labels.csv')\n"

    def stream(path: str, sink: Callable[[bytes], None]) -> None:
        sink(b"diff --git a/a.py b/a.py\n@@ -1 +1 @@\n")
        for start in range(0, len(line), 256):
            sink(line[start : start + 256])

    started = time.monotonic()
    found = check_quality_references({"a.py": b"labels.csv\n"}, {"a.py": b"labels.csv\n"}.get, (LABELS_CSV,), stream)  # fmt: skip
    assert [v.path for v in found] == ["a.py"]
    assert time.monotonic() - started < 3.0


def test_quality_reference_decodes_any_base_and_splits_every_line_end() -> None:
    """
    GIVEN a latin-1 base, and a CRLF base whose unchanged line names the labels
    WHEN the quality reference rule runs
    THEN nothing raises; a new reference is still flagged, an unchanged one not
    """
    latin = b"x = 1 # caf\xe9\n"
    assert _references({"a.py": latin + b"y = 2\n"}, {"a.py": latin}) == []
    named = latin + b"open('labels.csv')\n"
    assert _references({"a.py": named}, {"a.py": latin}) == [("a.py", LABELS_CSV)]
    crlf = b"LABELS = 'data/labels.csv'\r\nX = 1\r\n"
    changed = b"LABELS = 'data/labels.csv'\r\nX = 2\r\n"
    assert _references({"a.py": changed}, {"a.py": crlf}) == []
