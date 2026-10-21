"""Anti-cheating rules: the frozen checks every trial is held to.

Pure functions, no I/O. A trial is rejected outright when it touches a
protected path (tests, benchmarks, CI, project config, the engine's own
configuration), when it measured too few runs, when its gain does not clear
the measured noise floor, or when its output fingerprint differs from the
baseline while outputs must stay equivalent.

``check_capture`` adds the Step 2 rules only the runner can see in the
trial's git diff (file modes, compiled or binary files, git metadata,
unrecorded writes, process spawning); a trial that breaks any is never run.
"""

from __future__ import annotations

import ast
import hashlib
import math
import sys
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence

from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    MIN_RUNS,
    Direction,
    Measurement,
    NoiseCheck,
    RunStats,
    Violation,
    ViolationRule,
)
from autonomous_ai_agents.common.paths import (
    GIT_METADATA_NAMES,
    WRITE_DENY_PATTERNS,
    matches_pattern,
)
from autonomous_ai_agents.common.paths import PathTraversalError as PathTraversalError
from autonomous_ai_agents.common.paths import normalize_path as normalize_path
from autonomous_ai_agents.execution.protocols import Change

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


# ---------------------------------------------------------------------------
# Capture rules (Step 2): the trial's git diff, before anything runs
# ---------------------------------------------------------------------------

PROCESS_SPAWN_METRICS: frozenset[str] = frozenset(
    {METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES}
)
"""Per-process metrics a child process would fake; ``process_spawn`` guards them."""

_NO_MODE = "000000"
_REGULAR_MODES = frozenset({"100644", "100755"})
_LINK_KINDS = {"120000": "a symlink", "160000": "a gitlink"}
_BINARY_PROBE_BYTES = 8000  # git's buffer_is_binary looks this far for a NUL
_GIT_DIR = ".git"
_VERBS = {"A": "adds", "M": "modifies", "D": "deletes", "T": "changes the type of"}
_SPAWN_MODULES = (
    "multiprocessing",
    "concurrent.futures",
    "subprocess",
    "asyncio.subprocess",
    "pty",
    "joblib",
    "loky",
)
_SPAWN_COMPONENT = "multiprocessing"  # wrappers such as torch.multiprocessing
_OS_MODULES = frozenset({"os", "posix"})
_OS_SPAWN_PREFIXES = ("fork", "spawn", "posix_spawn", "exec")
_OS_SPAWN_NAMES = frozenset({"system", "popen"})
_IMPORTLIB, _IMPORT_MODULE = "importlib", "import_module"
_CONCURRENT, _FUTURES = "concurrent", "futures"
_TRACKED_MODULES = _OS_MODULES | {_IMPORTLIB, _CONCURRENT}
"""Modules whose spawning attributes are matched through ``import x as y`` too."""
_SPAWN_NAMES = frozenset(
    {
        "__import__",
        "create_subprocess_exec",
        "create_subprocess_shell",
        "subprocess_exec",
        "subprocess_shell",
    }
)
"""Names that import dynamically or spawn under any owner (asyncio, an event loop)."""
_MAX_LISTED_FINDINGS = 3


def check_capture(
    changes: Sequence[Change],
    written: Mapping[str, int],
    blobs: Mapping[str, bytes],
    judged_metrics: frozenset[str],
) -> tuple[Violation, ...]:
    """Return the capture-rule violations of a trial's diff, one per (rule, path).

    ``changes`` come from ``git diff --raw --no-renames``, ``written`` is the
    editor's report and ``blobs`` maps every added or modified regular file to
    its new content; a missing blob fails closed. Paths are compared as text.
    ``process_spawn`` applies only when a ``PROCESS_SPAWN_METRICS`` metric is
    among ``judged_metrics``.

    Contract: decode the patch as strict UTF-8 first and fail the trial on an
    error (trial step 3). A path that is still not UTF-8 (a surrogate from
    ``os.fsdecode``) gives one path-less ``forbidden_file`` and nothing else,
    so every violation stays JSON-serialisable.
    """
    scan_spawn = not judged_metrics.isdisjoint(PROCESS_SPAWN_METRICS)
    found: dict[tuple[ViolationRule, str], Violation] = {}
    for change in changes:
        for violation in _change_violations(change, written, blobs, scan_spawn):
            found.setdefault((violation.rule, change.path), violation)
    return tuple(found.values())


def _violation(
    rule: ViolationRule, path: str | None, text: str, pattern: str | None = None
) -> Violation:
    return Violation(
        rule=rule, path=path, pattern=pattern, message=f"{rule.value}: {text}"
    )


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _change_violations(
    change: Change,
    written: Mapping[str, int],
    blobs: Mapping[str, bytes],
    scan_spawn: bool,
) -> Iterator[Violation]:
    path, verb = change.path, _VERBS[change.status]
    if not _is_utf8(path):
        text = f"trial {verb} {ascii(path)}, a path that is not valid UTF-8"
        yield _violation(ViolationRule.forbidden_file, None, text)
        return
    mode_problem = _mode_problem(change)
    if mode_problem is not None:
        yield _violation(ViolationRule.forbidden_file_mode, path, mode_problem)
    deny = next((p for p in WRITE_DENY_PATTERNS if matches_pattern(path, p)), None)
    if deny is not None:
        text = f"trial {verb} {path!r}, which matches the write-deny pattern {deny!r}"
        yield _violation(ViolationRule.forbidden_file, path, text, deny)
    name = _git_metadata_name(path)
    if name is not None:
        text = f"trial {verb} {path!r}, which is git metadata ({name!r})"
        yield _violation(ViolationRule.git_metadata, path, text, name)
    if path not in written:
        text = f"trial {verb} {path!r} but the editor did not report writing it"
        yield _violation(ViolationRule.unrecorded_write, path, text)
    if change.status not in ("A", "M") or change.new_mode not in _REGULAR_MODES:
        return
    blob = blobs.get(path)
    if blob is None:
        text = f"new content of {path!r} was not captured, so it cannot be checked"
        yield _violation(ViolationRule.forbidden_file, path, text)
    elif b"\0" in blob[:_BINARY_PROBE_BYTES]:
        text = (
            f"{path!r} is binary (a NUL byte in its first {_BINARY_PROBE_BYTES} bytes)"
        )
        yield _violation(ViolationRule.forbidden_file, path, text)
    elif scan_spawn and _is_python(path, blob):
        problem = _spawn_problem(blob)
        if problem is not None:
            text = f"{path!r} {problem} while cpu_time_s or peak_rss_bytes is judged"
            yield _violation(ViolationRule.process_spawn, path, text)


def _mode_problem(change: Change) -> str | None:
    """Why the change's modes are refused, or ``None``.

    A deletion's new mode is git's ``000000``; anything else must be a
    regular file, and an existing path must keep its mode.
    """
    path, old, new = change.path, change.old_mode, change.new_mode
    allowed = {_NO_MODE} if change.status == "D" else _REGULAR_MODES
    if new not in allowed:
        kind = _LINK_KINDS.get(new)
        if kind is not None:
            return f"{path!r} is {kind} (mode {new})"
        return f"{path!r} has the unsupported mode {new}"
    if change.status == "T" or (change.status == "M" and old != new):
        return f"{path!r} changes mode {old} -> {new}"
    return None


def _git_metadata_name(path: str) -> str | None:
    """The git metadata name ``path`` hits: a ``.git`` dir, or a metadata file name."""
    *dirs, name = path.split("/")
    if any(matches_pattern(part, _GIT_DIR) for part in dirs):
        return _GIT_DIR
    return next((n for n in GIT_METADATA_NAMES if matches_pattern(name, n)), None)


def _is_python(path: str, blob: bytes) -> bool:
    """A ``.py`` file, or a script whose first line is a python shebang."""
    if matches_pattern(path, "*.py"):
        return True
    first_line = blob.split(b"\n", 1)[0]
    return first_line.startswith(b"#!") and b"python" in first_line.lower()


def _spawn_problem(source: bytes) -> str | None:
    """Describe the process-spawning code in ``source``, or return ``None``.

    An AST scan, so comments and strings never match. It guards against
    honest mistakes, not against code set on hiding a spawn (``getattr``,
    ``exec``, ``sys.modules``). Source this interpreter cannot parse fails
    closed: the workload's Python may be newer (PEP 695 or 701 syntax on a
    3.11 engine) or allow deeper nesting, and still run it. Warnings are
    ignored while parsing, so the caller's filters cannot turn one into a
    ``SyntaxError`` and user code never warns on the engine's stderr.
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(source)
    except (SyntaxError, ValueError):  # ValueError: NUL bytes on older patch releases
        version = f"Python {sys.version_info.major}.{sys.version_info.minor}"
        return f"could not be scanned for process spawning ({version} cannot parse it)"
    except (RecursionError, MemoryError):
        return "could not be scanned for process spawning (too complex to parse)"
    findings = sorted(set(_spawn_findings(tree)))
    if not findings:
        return None
    listed = "; ".join(
        f"line {line}: {what}" for line, what in findings[:_MAX_LISTED_FINDINGS]
    )
    return f"may start processes ({listed})"


def _is_spawn_module(name: str) -> bool:
    return _SPAWN_COMPONENT in name.split(".") or any(
        name == m or name.startswith(m + ".") for m in _SPAWN_MODULES
    )


def _is_os_spawn(name: str) -> bool:
    return name in _OS_SPAWN_NAMES or name.startswith(_OS_SPAWN_PREFIXES)


def _from_import_finding(module: str, name: str) -> str | None:
    """What ``from module import name`` brings in that can spawn, or ``None``."""
    full = f"{module}.{name}"
    parent_of_spawn = name == "*" and any(
        m.startswith(module + ".") for m in _SPAWN_MODULES
    )
    spawns = (
        _is_spawn_module(module)
        or _is_spawn_module(full)
        or parent_of_spawn
        or (module in _OS_MODULES and (name == "*" or _is_os_spawn(name)))
        or (module == _IMPORTLIB and name in ("*", _IMPORT_MODULE))
        or name in _SPAWN_NAMES
    )
    return f"imports {full}" if spawns else None


def _attribute_finding(node: ast.Attribute, modules: Mapping[str, str]) -> str | None:
    """What ``owner.attr`` uses that can spawn, or ``None``.

    ``modules`` maps a local name to the tracked module it is bound to.
    ``import_module`` counts only on importlib, so a project's own loader
    method is not a dynamic import.
    """
    owner = node.value.id if isinstance(node.value, ast.Name) else ""
    module, attr = modules.get(owner), node.attr
    if (
        (module in _OS_MODULES and _is_os_spawn(attr))
        or (module == _IMPORTLIB and attr == _IMPORT_MODULE)
        or (module == _CONCURRENT and attr == _FUTURES)
    ):
        return f"uses {owner}.{attr}"
    return f"uses .{attr}" if attr in _SPAWN_NAMES else None


def _spawn_findings(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """(line, finding) for every spawning import, os call or dynamic import."""
    nodes = list(ast.walk(tree))
    modules = {name: name for name in _TRACKED_MODULES}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_spawn_module(alias.name):
                    yield node.lineno, f"imports {alias.name}"
                elif alias.asname is not None and alias.name in _TRACKED_MODULES:
                    modules[alias.asname] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                finding = _from_import_finding(node.module, alias.name)
                if finding is not None:
                    yield node.lineno, finding
    for node in nodes:
        if isinstance(node, ast.Attribute):
            finding = _attribute_finding(node, modules)
            if finding is not None:
                yield node.lineno, finding
        elif isinstance(node, ast.Name) and node.id in _SPAWN_NAMES:
            yield node.lineno, f"uses {node.id}"
