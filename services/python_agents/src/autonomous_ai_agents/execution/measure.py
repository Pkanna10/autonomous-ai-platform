"""Measurement: warm-ups, N timed runs, output fingerprints, ABBA, the test suite.

Every launch (warm-up, timed, ABAB, test suite) first calls the phase's
``reset`` (``GitWorkspace.reset``: ``.git`` link check, scrub, ``checkout -f``,
``clean -ffdx``, link check), so no run sees what an earlier one left and the
test command never sees a module a workload dropped; ``run_once`` then empties
the whole scratch root and recreates HOME and TMPDIR in it (``fresh_dirs``).
A non-zero workload exit is a ``RunFailure`` here, like a timeout, a flood or
missing ``required`` isolation. Every ``RunSample.notes`` and
``RunFailure.notes`` reaches the caller, which emits the events (nothing here
imports the orchestrator). ``Workload.inputs`` is not passed and
``throughput_per_s`` is never produced.

Before every workload launch (never the suite) the phase's ``mask`` deletes
the quality check's frozen files after the reset (D37). Each run's exact
fingerprint is ``raw_fingerprint``; ``output_fingerprint`` is the canonical
one under the workload's ``output_tolerance`` (D39, ``outputs.py``) and
equals the raw one without it. The agreed output bytes (the output file, else
complete stdout, of the first timed run, kept when the canonical
fingerprints agree) travel in ``Measured.outputs`` for the quality scorer only,
never in a row, a note or a repr. Two sides alternate ABBA on one counter
across warm-ups and timed runs (D41). Each workload row's hardware carries
the worst launch's ``child_cpu_s`` and ``strays`` (D62, N0c; warm-ups
included, ``None`` once a launch did not report them); the suite's rows
carry neither.

``tests_passed`` needs the runner's own summary, never the exit code alone:
unittest's last ``Ran N tests`` line followed by ``OK`` (the suite keeps a
larger stderr tail), or the JUnit XML pytest writes into the scratch root
(the user's own ``--junitxml`` is replaced; size-capped, strict UTF-8, any
DTD refused). The count is passing tests, skips excluded; none, fewer than
``baseline_count`` or no summary is 0.0. Other runners pass on exit 0 with a
note that the count was not verified. Known limitation: code under test can
still print or write a fake summary (``atexit`` plus ``os._exit``); only human
review of the diff catches that.
"""

from __future__ import annotations

import functools
import hashlib
import os
import platform as _platform
import re
import stat
import sys

# Parses only the size-capped, UTF-8, DTD-free JUnit report (see _junit_count).
import xml.etree.ElementTree as ElementTree  # nosec B405
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePath
from typing import Protocol, TypeVar

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    JsonScalar,
    Measurement,
    Project,
    RunStats,
    Workload,
)
from autonomous_ai_agents.common.paths import normalize_path
from autonomous_ai_agents.execution.outputs import (
    Retained,
    RunOutput,
    check_mask,
    mask,
    resolve,
)
from autonomous_ai_agents.execution.procrun import (
    FailureKind,
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.protocols import WorktreeHandle
from autonomous_ai_agents.execution.sandbox import SandboxPolicy, child_env

JUNIT_NAME = "junit.xml"
"""pytest's report, in the phase's scratch root (wiped before every run)."""
JUNIT_MAX_BYTES = 16 * 1024 * 1024
SUITE_STDERR_TAIL_BYTES = 256 * 1024
"""The suite runs once, so it keeps more stderr than a timed run: unittest's
summary must survive whatever interpreter shutdown prints after it."""
UNITTEST, PYTEST, UNKNOWN = "unittest", "pytest", "unknown"

PYTHON_NAME = re.compile(r"(?:python|pypy)(?:\d+(?:\.\d+)*)?t?(?:-dbg)?")
"""The file names of a Python interpreter (``python3.12``, ``pypy3``...)."""
_JUNIT_FLAGS = ("--junitxml", "--junit-xml")
_RAN = re.compile(r"Ran (\d+) tests? in \d+(?:\.\d+)?s")
_STATUS = re.compile(r"OK(?: \(([a-z ]+=\d+(?:, [a-z ]+=\d+)*)\))?")
_SKIPPED = re.compile(r"(?:^|, )skipped=(\d+)")
_DTD = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_CHUNK, _TEXT_CAP = 64 * 1024, 200
CHILD_CPU_KEY, STRAYS_KEY = "child_cpu_s", "strays"
_N = TypeVar("_N", int, float)
"""The ``Measurement.hardware`` keys of the child-process tripwire (D62, N0c)."""


class RunOnce(Protocol):
    """``procrun.run_once`` as this module calls it (injected in tests)."""

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample: ...


class Resetter(Protocol):
    def reset(self, handle: WorktreeHandle) -> None: ...


@dataclass(frozen=True)
class Phase:
    """Where every run of one phase happens; ``policy.writable`` is exactly
    ``(worktree, scratch root)``, realpath'd. ``mask`` lists the literal
    project files deleted before each workload launch (D37)."""

    policy: SandboxPolicy
    env: Mapping[str, str]
    reset: Callable[[], None]
    caps: OutputCaps
    run: RunOnce = run_once
    mask: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.policy.writable) != 2:
            raise ValueError("a phase may write the worktree and the scratch root only")
        check_mask(self.mask)

    @property
    def worktree(self) -> Path:
        return self.policy.writable[0]

    @property
    def scratch(self) -> Path:
        return self.policy.writable[1]

    @property
    def fresh_dirs(self) -> tuple[Path, Path, Path]:
        """The whole scratch root, then HOME and TMPDIR inside it."""
        return (self.scratch, self.scratch / "home", self.scratch / "tmp")


def make_phase(
    git: Resetter,
    handle: WorktreeHandle,
    *,
    scratch: Path,
    probe: Path,
    network: IsolationMode | None = None,
    fs: IsolationMode | None = None,
    platform: str = sys.platform,
    base_env: Mapping[str, str] | None = None,
    caps: OutputCaps | None = None,
    run: RunOnce = run_once,
    mask: Sequence[str] = (),
) -> Phase:
    """The phase of ``handle`` with ``<run>/_scratch/<phase>`` and ``_probe/<phase>``.

    Modes default to the settings. Both dirs are created (0700) once the
    policy and the mask have been checked; the phase's owner removes them.
    """
    check_mask(mask)
    policy = SandboxPolicy(
        network=settings.NETWORK_ISOLATION if network is None else network,
        fs=settings.FS_ISOLATION if fs is None else fs,
        writable=(handle.path, scratch),
        probe_dir=probe,
        platform=platform,
    )
    worktree, root = policy.writable
    for made in (root, policy.probe_dir):
        made.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = child_env(
        home=root / "home", tmpdir=root / "tmp", worktree=worktree, base=base_env
    )
    reset = functools.partial(git.reset, handle)
    caps = caps or OutputCaps.from_settings()
    return Phase(policy, env, reset, caps, run, tuple(mask))


@dataclass(frozen=True)
class Measured:
    """Rows for one phase, the notes for events, the passing-test count, and
    the agreed output bytes for the quality scorer (D37; never shown)."""

    measurements: tuple[Measurement, ...]
    notes: tuple[str, ...] = ()
    tests_counted: int | None = None
    outputs: bytes | None = field(default=None, repr=False)


@dataclass(frozen=True)
class AbabMeasured:
    """Interleaved rows: ``a`` (the base side), ``b`` (the candidate side)."""

    a: tuple[Measurement, ...]
    b: tuple[Measurement, ...]
    notes: tuple[str, ...] = ()
    outputs_a: bytes | None = field(default=None, repr=False)
    outputs_b: bytes | None = field(default=None, repr=False)


class UnusableError(Exception):
    """A file or summary that cannot be trusted; the message says why."""


@dataclass
class _Series:
    wall: list[float] = field(default_factory=list)
    cpu: list[float] = field(default_factory=list)
    rss: list[float] = field(default_factory=list)
    prints: list[str | None] = field(default_factory=list)
    raws: list[str | None] = field(default_factory=list)
    data: bytes | None = field(default=None, repr=False)
    fs: int = 0
    net: int = 0
    child: list[float | None] = field(default_factory=list)
    strays: list[int | None] = field(default_factory=list)

    def launched(self, sample: RunSample) -> RunSample:
        self.child.append(sample.child_cpu_s)
        self.strays.append(sample.strays)
        return sample


def _worst(values: Sequence[_N | None]) -> _N | None:
    """The largest per-launch value, ``None`` unless every launch reported one."""
    known = [value for value in values if value is not None]
    return max(known) if known and len(known) == len(values) else None


def output_fingerprint(
    stdout_bytes: int, stdout_sha256: str, file: tuple[int, str] | None
) -> str:
    """sha256 over fixed-width (len, sha256) of stdout, then of the file.

    ``run_once`` streams stdout through sha256 and keeps no copy, so the
    digest stands in for the bytes; the encoding stays unambiguous.
    """
    parts = [stdout_bytes.to_bytes(8, "big"), bytes.fromhex(stdout_sha256)]
    if file is not None:
        parts += [b"file", file[0].to_bytes(8, "big"), bytes.fromhex(file[1])]
    return hashlib.sha256(b"aip-output/1" + b"".join(parts)).hexdigest()


def _quote(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_TEXT_CAP])


def _status(code: int) -> str:
    return f"exit status {code}" if code >= 0 else f"signal {-code}"


def _inside(worktree: Path, rel: str, what: str) -> Path:
    try:
        path = worktree / normalize_path(rel)
        real = Path(os.path.realpath(path))
    except ValueError as error:  # PathTraversalError, or a NUL byte
        reason = f"{what} {rel!r} is not a path inside the worktree: {error}"
        raise RunFailure(_quote(reason)) from None
    if not real.is_relative_to(worktree):
        raise RunFailure(f"{what} {rel!r} resolves outside the worktree")
    return path


def launch(
    phase: Phase,
    command: Sequence[str],
    workdir: str,
    timeout_s: float,
    where: str,
    notes: list[str],
    check_exit: bool = True,
    *,
    workload_id: str | None = None,
    masked: bool = True,
) -> RunSample:
    """Reset, then the phase's mask (only the suite passes ``masked=False``),
    then one ``run_once``; a repo-relative ``argv[0]`` is in the worktree.

    A non-zero exit (with ``check_exit``) is a ``RunFailure`` of kind ``exit``
    (``signal`` for a signal) carrying stderr's tail and ``workload_id``."""
    phase.reset()
    argv = list(command)
    try:
        if masked:
            mask(phase.worktree, phase.mask)
        if not os.path.isabs(argv[0]):
            argv[0] = str(_inside(phase.worktree, argv[0], "the command"))
        cwd = _inside(phase.worktree, workdir, "working_dir")
        args = (argv, cwd, phase.env, phase.policy, timeout_s, phase.caps)
        sample = phase.run(*args, fresh_dirs=phase.fresh_dirs)
    except RunFailure as failure:
        notes.extend(f"{where}: {note}" for note in failure.notes)
        raise RunFailure(f"{where}: {failure.reason}", tuple(notes)) from None
    notes.extend(f"{where}: {note}" for note in sample.notes)
    if check_exit and sample.exit != 0:
        lines = sample.stderr_tail.decode(errors="replace").strip().splitlines()
        last = _quote(lines[-1]) if lines else "no stderr"
        reason = f"{where}: the command ended with {_status(sample.exit)}: {last}"
        kind: FailureKind = "exit" if sample.exit > 0 else "signal"
        tail = sample.stderr_tail
        raise RunFailure(
            reason, tuple(notes), kind=kind, exit_tail=tail, workload_id=workload_id
        )
    return sample


def _run(phase: Phase, workload: Workload, where: str, notes: list[str]) -> RunSample:
    command, workdir = workload.command, workload.working_dir
    timeout, wid = workload.timeout_s, workload.id
    return launch(phase, command, workdir, timeout, where, notes, workload_id=wid)


def read_capped(path: Path, cap: int, sink: Callable[[bytes], object]) -> int:
    """Feed a regular file to ``sink`` in chunks; never follows the last link."""
    try:
        fd = os.open(path, _FILE_FLAGS)
    except FileNotFoundError:
        raise UnusableError("is missing") from None
    except OSError as error:
        raise UnusableError(f"cannot be opened ({error.strerror})") from None
    size = 0
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise UnusableError("is not a regular file")
        while chunk := os.read(fd, _CHUNK):
            size += len(chunk)
            if size > cap:
                raise UnusableError(f"is larger than {cap} bytes")
            sink(chunk)
    finally:
        os.close(fd)
    return size


def _output(phase: Phase, workload: Workload, sample: RunSample) -> RunOutput:
    """The run's fingerprints and bytes; ``UnusableError``: the file is unusable."""
    file, kept = None, None
    if workload.output_file is not None:
        real = Path(os.path.realpath(phase.worktree / workload.output_file))
        if not real.is_relative_to(phase.worktree):
            raise UnusableError("resolves outside the worktree")
        digest, kept = hashlib.sha256(), Retained(settings.OUTPUT_TOLERANCE_MAX_BYTES)

        def sink(chunk: bytes) -> None:
            digest.update(chunk)
            kept(chunk)

        size = read_capped(real, phase.caps.max_output_bytes, sink)
        file = (size, digest.hexdigest())
    raw = output_fingerprint(sample.stdout_bytes, sample.stdout_sha256, file)
    head = sample.stdout_head
    whole = len(head) == sample.stdout_bytes
    stdout = head if whole and _sha256(head) == sample.stdout_sha256 else None
    tolerance, head_bytes = workload.output_tolerance, phase.caps.head_bytes
    return resolve(raw, stdout, kept, tolerance, head_bytes)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _timed(
    phase: Phase,
    workload: Workload,
    into: _Series,
    where: tuple[str, str],
    notes: list[str],
) -> None:
    """One timed run; ``where`` is (this run, the series) for the notes."""
    sample = into.launched(_run(phase, workload, where[0], notes))
    output: RunOutput | None = None
    try:
        output = _output(phase, workload, sample)
    except UnusableError as problem:
        rel = workload.output_file
        notes.append(
            f"{where[0]}: output file {rel!r} {problem}; no output fingerprint"
        )
    if output is not None and output.note is not None:
        notes.append(f"{where[1]}: {output.note}")
    into.wall.append(sample.wall_ns / 1e9)
    into.cpu.append(sample.utime + sample.stime)
    into.rss.append(float(sample.maxrss_bytes))
    into.prints.append(None if output is None else output.canonical)
    into.raws.append(None if output is None else output.raw)
    if len(into.raws) == 1:  # the first timed run's bytes stand for the series
        into.data = None if output is None else output.data
    into.fs += sample.fs_isolated
    into.net += sample.net_isolated


def _host(policy: SandboxPolicy, runs: int, fs: int, net: int) -> dict[str, JsonScalar]:
    """The OS, machine, Python, CPU count, both modes and the isolated runs."""
    return {
        "os": _platform.system(),
        "machine": _platform.machine(),
        "python": _platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "network_isolation": policy.network,
        "fs_isolation": policy.fs,
        "runs": runs,
        "fs_isolated_runs": fs,
        "net_isolated_runs": net,
    }


def _row(
    workload: Workload,
    trial_id: str | None,
    metric: str,
    unit: str,
    values: Sequence[float],
    hardware: dict[str, JsonScalar],
    fingerprint: str | None = None,
    raw: str | None = None,
) -> Measurement:
    return Measurement(
        workload_id=workload.id,
        trial_id=trial_id,
        metric=metric,
        stats=RunStats.from_samples(values, unit=unit),
        samples=tuple(values),
        output_fingerprint=fingerprint,
        raw_fingerprint=raw,
        hardware=hardware,
    )


def _agreed(prints: Sequence[str | None]) -> str | None:
    found = set(prints)
    return found.pop() if len(found) == 1 else None


def _kept(series: _Series) -> bytes | None:
    """The first timed run's output bytes, only when every run's canonical
    fingerprint agreed (D37): the same bytes when the raws agree too, else
    one output equal to the others within the tolerance."""
    return series.data if _agreed(series.prints) is not None else None


def _rows(
    phase: Phase, workload: Workload, trial_id: str | None, series: _Series
) -> tuple[Measurement, ...]:
    """Wall, CPU and peak RSS; each fingerprint only when every run agreed."""
    fingerprint, raw = _agreed(series.prints), _agreed(series.raws)
    hardware = _host(phase.policy, len(series.wall), series.fs, series.net)
    hardware[CHILD_CPU_KEY] = _worst(series.child)
    hardware[STRAYS_KEY] = _worst(series.strays)
    return tuple(
        _row(workload, trial_id, metric, unit, values, hardware, fingerprint, raw)
        for metric, unit, values in (
            (METRIC_WALL_TIME_S, "s", series.wall),
            (METRIC_CPU_TIME_S, "s", series.cpu),
            (METRIC_PEAK_RSS_BYTES, "bytes", series.rss),
        )
    )


def _interleave(
    workload: Workload, sides: Sequence[tuple[str, Phase]], notes: list[str]
) -> list[_Series]:
    """``warmup_runs`` untimed, then ``max(MIN_RUNS, runs)`` timed, side by side.

    One counter runs across warm-ups and timed runs: the sides go in order on
    an even index and reversed on an odd one (ABBA), so a position effect
    is spread over both sides instead of biasing one (D41).
    """
    name = f"workload {workload.name!r}"
    warmups, runs = workload.warmup_runs, max(settings.MIN_RUNS, workload.runs)
    series = [_Series() for _ in sides]
    pairs = list(zip(sides, series, strict=True))
    for index in range(warmups + runs):
        for (side, phase), into in pairs[::-1] if index % 2 else pairs:
            if index < warmups:
                where = f"{name}{side} warm-up {index + 1}/{warmups}"
                into.launched(_run(phase, workload, where, notes))
            else:
                where = f"{name}{side} run {index - warmups + 1}/{runs}"
                _timed(phase, workload, into, (where, f"{name}{side}"), notes)
    for (side, _), into in pairs:
        if len(set(into.prints)) > 1:
            notes.append(
                f"{name}{side}: the {runs} timed runs did not agree on one output;"
                " no output fingerprint"
            )
    return series


def measure_workload(
    phase: Phase, workload: Workload, *, trial_id: str | None = None
) -> Measured:
    """Warm-ups, then N timed runs: one row each for wall, CPU and peak RSS.

    ``RunFailure`` carries every note gathered up to the failure.
    """
    notes: list[str] = []
    [series] = _interleave(workload, [("", phase)], notes)
    rows = _rows(phase, workload, trial_id, series)
    return Measured(rows, tuple(dict.fromkeys(notes)), outputs=_kept(series))


def measure_abab(
    a: Phase,
    b: Phase,
    workload: Workload,
    *,
    trial_id_a: str | None = None,
    trial_id_b: str | None = None,
) -> AbabMeasured:
    """A and B interleaved ABBA run by run (warm-ups too), each after its own
    reset; the name stays for its callers."""
    notes: list[str] = []
    series_a, series_b = _interleave(workload, [(" A", a), (" B", b)], notes)
    rows_a = _rows(a, workload, trial_id_a, series_a)
    rows_b = _rows(b, workload, trial_id_b, series_b)
    unique = tuple(dict.fromkeys(notes))
    return AbabMeasured(rows_a, rows_b, unique, _kept(series_a), _kept(series_b))


def python_module(argv: Sequence[str]) -> tuple[str, int] | None:
    """The ``-m`` module of a Python argv and the index after it, if any."""
    if PYTHON_NAME.fullmatch(PurePath(argv[0]).name) is None:
        return None
    index = 1
    while index < len(argv) and argv[index].startswith("-"):
        arg = argv[index]
        if arg in ("-", "--"):
            return None
        if arg.startswith("--"):
            index += 2 if arg == "--check-hash-based-pycs" else 1
            continue
        for at, flag in enumerate(arg[1:], start=2):
            if flag == "c":
                return None
            if flag == "m":
                if arg[at:]:
                    return arg[at:], index + 1
                return (argv[index + 1], index + 2) if index + 1 < len(argv) else None
            if flag in "WX":
                index += 0 if arg[at:] else 1
                break
        index += 1
    return None


def classify_runner(argv: Sequence[str]) -> str:
    """``pytest``, ``unittest`` or ``unknown`` for a test command."""
    if PurePath(argv[0]).name in ("pytest", "py.test"):
        return PYTEST
    found = python_module(argv)
    module = "" if found is None else found[0]
    return {"unittest": UNITTEST, "pytest": PYTEST}.get(module, UNKNOWN)


def _test_argv(command: Sequence[str], junit: Path) -> tuple[list[str], bool]:
    """pytest gets ``--junitxml`` right after its name (a later ``--`` is safe).

    pytest keeps the last report flag, so the user's own (either spelling,
    ``=value`` or two arguments, before any ``--``) is dropped; ``True`` then.
    """
    if classify_runner(command) != PYTEST:
        return list(command), False
    found = python_module(command)
    at = 1 if found is None else found[1]
    rest = list(command[at:])
    end = rest.index("--") if "--" in rest else len(rest)
    kept, index = list[str](), 0
    while index < end:
        arg = rest[index]
        index += 2 if arg in _JUNIT_FLAGS else 1
        if arg.split("=", 1)[0] not in _JUNIT_FLAGS:
            kept.append(arg)
    argv = [*command[:at], f"--junitxml={junit}", *kept, *rest[end:]]
    return argv, len(kept) < end


def _unittest_count(stderr: bytes, tail_bytes: int) -> int:
    """The last ``Ran N tests`` is the runner's own (a nested run comes first)."""
    lines = stderr.decode("utf-8", "replace").splitlines()
    ran = [i for i, line in enumerate(lines) if _RAN.fullmatch(line)]
    if not ran:
        raise UnusableError(
            f"exit 0 but no unittest summary in the last {tail_bytes} bytes of stderr"
        )
    status = next((line for line in lines[ran[-1] + 1 :] if line.strip()), "")
    match = _STATUS.fullmatch(status)
    if match is None:
        raise UnusableError(f"the unittest summary says {_quote(status)!r}, not OK")
    skipped = _SKIPPED.search(match[1] or "")
    return int(lines[ran[-1]].split()[1]) - (int(skipped[1]) if skipped else 0)


def _junit_count(path: Path) -> int:
    """Passing testcases in pytest's report; ``UnusableError`` for anything else."""
    data = bytearray()
    try:
        read_capped(path, JUNIT_MAX_BYTES, data.extend)
        text = data.decode("utf-8")
    except UnusableError as problem:
        raise UnusableError(f"the JUnit report {problem}") from None
    except UnicodeDecodeError:
        raise UnusableError("the JUnit report is not UTF-8") from None
    if _DTD.search(text):
        raise UnusableError("the JUnit report declares a DOCTYPE or ENTITY")
    try:
        # Untrusted XML: parsed from a str (expat ignores the declared
        # encoding) with no DTD (refused above), so no entity can expand
        # and expat never fetches an external one.
        root = ElementTree.fromstring(text)  # nosec B314
        if root.tag not in ("testsuite", "testsuites"):
            raise UnusableError(f"the JUnit report's root is <{_quote(root.tag)}>")
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        if not suites:
            raise UnusableError("the JUnit report has no testsuite")
        if any(
            int(s.get("errors", "0")) or int(s.get("failures", "0")) for s in suites
        ):
            raise UnusableError("the JUnit report counts failures or errors")
    except (ElementTree.ParseError, ValueError) as error:
        raise UnusableError(f"unreadable JUnit report: {_quote(str(error))}") from None
    outcomes = [{child.tag for child in case} for case in root.iter("testcase")]
    if any(tags & {"failure", "error"} for tags in outcomes):
        raise UnusableError("a test failed or errored")
    return sum("skipped" not in tags for tags in outcomes)


def _suite_count(
    runner: str, sample: RunSample, suite: Phase, baseline: int | None
) -> int | None:
    """Passing tests (``None``: an unknown runner); ``UnusableError``: failed."""
    if sample.exit != 0:
        raise UnusableError(f"exited with {_status(sample.exit)}")
    if runner == UNKNOWN:
        return None
    if runner == UNITTEST:
        count = _unittest_count(sample.stderr_tail, suite.caps.stderr_tail_bytes)
    else:
        count = _junit_count(suite.scratch / JUNIT_NAME)
    if count < 1:
        raise UnusableError("no test passed")
    if baseline is not None and count < baseline:
        raise UnusableError(
            f"{count} tests passed, fewer than the baseline's {baseline}"
        )
    return count


def run_tests(
    phase: Phase,
    project: Project,
    workloads: Sequence[Workload],
    *,
    baseline_count: int | None = None,
    trial_id: str | None = None,
) -> Measured:
    """Run ``project.test_command`` once from the root, right after a reset.

    One ``tests_passed`` row (1.0 or 0.0) per workload; nothing without a test
    command. Trials and the combine tip pass the baseline's passing-test count
    (``baseline_test_count``) and must reach it. ``RunFailure`` propagates.
    """
    if project.test_command is None:
        return Measured(())
    command, where, notes = project.test_command, "the test command", list[str]()
    tail = max(phase.caps.stderr_tail_bytes, SUITE_STDERR_TAIL_BYTES)
    suite = replace(phase, caps=replace(phase.caps, stderr_tail_bytes=tail))
    runner = classify_runner(command)
    argv, replaced = _test_argv(command, suite.scratch / JUNIT_NAME)
    if replaced:
        notes.append(f"{where}: its own --junitxml was replaced by the engine's report")
    timeout = settings.TEST_TIMEOUT_S
    sample = launch(suite, argv, ".", timeout, where, notes, False, masked=False)
    count: int | None = None
    try:
        count = _suite_count(runner, sample, suite, baseline_count)
        passed = 1.0
        if count is None:
            notes.append(
                f"{where}: {command[0]!r} is neither unittest nor pytest: it passed"
                " on its exit code alone; the test count could not be verified"
            )
    except UnusableError as problem:
        passed = 0.0
        notes.append(f"{where}: {problem}")
    hardware = _host(phase.policy, 1, int(sample.fs_isolated), int(sample.net_isolated))
    hardware["test_runner"] = runner
    if count is not None:
        hardware["tests_counted"] = count
    value = (passed,)
    rows = tuple(
        _row(load, trial_id, METRIC_TESTS_PASSED, "bool", value, hardware)
        for load in workloads
    )
    return Measured(rows, tuple(dict.fromkeys(notes)), count)


def baseline_test_count(measurements: Sequence[Measurement]) -> int | None:
    """The passing-test count a baseline's ``tests_passed`` rows recorded."""
    rows = (m for m in measurements if m.metric == METRIC_TESTS_PASSED)
    found = [c for m in rows if type(c := m.hardware.get("tests_counted")) is int]
    return max(found) if found else None
