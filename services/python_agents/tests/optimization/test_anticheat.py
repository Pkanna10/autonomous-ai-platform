"""Tests for the anti-cheating rules (Step 1 U2, Step 2 U9).

Pure functions: protected-path matching, path-traversal rejection, the
noise-floor rule, run-count rule and output fingerprints, plus the Step 2
capture rules on a trial's git diff (file modes, compiled and binary files,
git metadata, unrecorded writes, process spawning). These are the "frozen
evaluator" guarantees nothing a trial writes can bypass.
"""

from __future__ import annotations

import sys
import warnings
from collections.abc import Mapping, Sequence

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
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    PROCESS_SPAWN_METRICS,
    PathTraversalError,
    check_capture,
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
    return check_capture(changes, written, content, judged)


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
    "import concurrent.futures\n",
    "from concurrent.futures import ProcessPoolExecutor\n",
    "from concurrent.futures.process import ProcessPoolExecutor\n",
    "from concurrent import futures\n",
    "from concurrent import *\n",
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
