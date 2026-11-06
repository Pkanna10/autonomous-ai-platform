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

The counted run (G6a, ``count_workload``): one launch of a Python workload
under ``_opcount_shim``, as the profiler launches its shim (the phase's
sandbox, environment, reset and mask, the workload's interpreter and
options, the scratch root as the output channel, read capped and never
through a final link, parsed strictly: ``parse_counts``), gives one
``op_calls`` row (``n=1``, unit ``calls``; the Python and C split in its
hardware). It never raises for the workload's sake: a command the shim
cannot run, a failed run or unusable output is a note and no row. The row is
the operation-count judge's input only (shadow mode), and the workload
controls the interpreter, so its count is a hint, never proof.

The scaling runs (G6b, ``measure_scaling``): a workload whose
``Workload.scale`` is set runs at each of its sizes, the size in the
setting's environment variable on top of the phase's (a variable the phase
sets or the sandbox denies is a note and no run), ``runs`` timed launches
per size and side, each after its reset and mask like any workload run. With
a twin they interleave: the sizes forward on an even run and backward on an
odd one, the sides swapping order on every other turn, so neither a side nor
a size always runs first. One ``scale_wall_time_s`` row per side and size
(its size in ``hardware``, no fingerprint: outputs differ by size). A failed
launch at any size is a note and no rows on either side (a fit over the
sizes one side reached would compare unlike ranges). Wall time includes the
interpreter's start-up, which flattens the growth rate when the smallest
size's run is not well above it: the setter picks the sizes. The rows are
the scaling judge's input only (shadow mode).

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
import json
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
from typing import Final, Protocol, TypeVar

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
from autonomous_ai_agents.execution import _opcount_shim
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
from autonomous_ai_agents.execution.sandbox import SandboxPolicy, child_env, denied

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
METRIC_OP_CALLS = "op_calls"
"""The counted run's row (G6a): every call of one run, Python and C."""
PYTHON_CALLS_KEY, C_CALLS_KEY = "python_calls", "c_calls"
"""The ``op_calls`` row's ``hardware`` keys of the split."""
METRIC_UNIT_CALLS = "unit_calls"
UNIT_KEY, OUT_CALLS_KEY, CALLEE_KEY = "unit", "out_calls", "callee"
OPCOUNT_NAME = "opcount.json"
"""The shim's output, in the phase's scratch root (wiped before every run)."""
OPCOUNT_SHIM = Path(_opcount_shim.__file__).resolve()
OPCOUNT_TIMEOUT_FACTOR = 3.0
"""The counted run's timeout is the workload's times this (cProfile's
overhead, as for the profile run; the run is not timed)."""
MAX_CALLS = 2**53
METRIC_SCALE_WALL_S = "scale_wall_time_s"
"""The scaling runs' rows (G6b): one per workload, side and size."""
SCALE_SIZE_KEY = "scale_size"
"""The ``scale_wall_time_s`` row's ``hardware`` key of its size."""


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


class CountFormatError(Exception):
    """The shim's output is not a count document the engine accepts; says why."""


@dataclass(frozen=True)
class UnitCount:
    """One unit of a version 2 count (S1): its calls, the calls its frames
    made, its top callees by edge (name, calls)."""

    unit: str
    calls: int
    out: int
    callees: tuple[tuple[str, int], ...] = ()


_UNIT: Final = re.compile(r"[!-9;-~]+(?:/[!-9;-~]+)*::[!-9;-~]+")
"""``PATH::FUNCTION``: printable ASCII, no space, no other ``:``."""
MAX_UNIT_CHARS: Final = 256


def is_unit(spec: str) -> bool:
    """Whether ``spec`` names a unit the shim can count (``PATH::FUNCTION``)."""
    return len(spec) <= MAX_UNIT_CHARS and _UNIT.fullmatch(spec) is not None


@dataclass(frozen=True)
class OpCounts:
    """One counted run's calls."""

    python_calls: int
    c_calls: int
    units: tuple[UnitCount, ...] = ()

    @property
    def total(self) -> int:
        return self.python_calls + self.c_calls


@dataclass(frozen=True)
class Counted:
    """A counted run's row (none when it could not count) and its notes."""

    rows: tuple[Measurement, ...]
    notes: tuple[str, ...] = ()


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise CountFormatError("has an object with a repeated key")
    return found


def _constant(name: str) -> object:
    raise CountFormatError(f"holds {name}, which is not a number")


def _calls(value: object, what: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_CALLS:
        raise CountFormatError(f"{what} must be an integer from 0 to {MAX_CALLS}")
    return value


def _callee(value: object) -> tuple[str, int]:
    if not (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and len(value[0]) <= _opcount_shim.MAX_NAME_CHARS
        and value[0].isprintable()
    ):
        raise CountFormatError("a callee must be a printable name and its calls")  # fmt: skip
    return value[0], _calls(value[1], "a callee's calls")


def _unit_count(value: object) -> UnitCount:
    if not isinstance(value, dict) or set(value) != set(_opcount_shim.UNIT_KEYS):
        raise CountFormatError("a unit must hold exactly unit, calls, out, callees")
    unit, callees = value["unit"], value["callees"]
    if not isinstance(unit, str) or not is_unit(unit):
        raise CountFormatError("a unit name must be PATH::FUNCTION")
    if not isinstance(callees, list) or len(callees) > _opcount_shim.MAX_CALLEES:
        raise CountFormatError(f"callees must be a list of at most {_opcount_shim.MAX_CALLEES}")  # fmt: skip
    return UnitCount(unit, _calls(value["calls"], "calls"), _calls(value["out"], "out"),
                     tuple(map(_callee, callees)))  # fmt: skip


def _unit_counts(value: object) -> tuple[UnitCount, ...]:
    if not isinstance(value, list) or len(value) > _opcount_shim.MAX_UNITS:
        raise CountFormatError(f"units must be a list of at most {_opcount_shim.MAX_UNITS}")  # fmt: skip
    return tuple(map(_unit_count, value))


def parse_counts(data: bytes) -> OpCounts:
    """The shim's document, or ``CountFormatError``: ASCII JSON of at most
    the shim's cap, exactly its keys, version 1 (version 2 with units),
    bounded integer counts, printable bounded names."""
    if len(data) > _opcount_shim.MAX_DOC_BYTES:
        raise CountFormatError(f"is larger than {_opcount_shim.MAX_DOC_BYTES} bytes")
    if not data.isascii():
        raise CountFormatError("is not ASCII JSON")
    try:
        doc: object = json.loads(
            data.decode("ascii"), object_pairs_hook=_unique, parse_constant=_constant
        )
    except (ValueError, RecursionError):  # JSONDecodeError, int digit limit
        raise CountFormatError("is not valid JSON") from None
    doc = doc if isinstance(doc, dict) else {}
    units = set(doc) == set(_opcount_shim.UNITS_DOC_KEYS)
    if not units and set(doc) != set(_opcount_shim.DOC_KEYS):
        raise CountFormatError(
            "its top level must hold exactly version, python_calls, c_calls"
        )
    version = doc["version"]
    want = _opcount_shim.UNITS_VERSION if units else _opcount_shim.FORMAT_VERSION
    if type(version) is not int or version != want:
        raise CountFormatError(f"version must be the integer {want}")
    return OpCounts(
        _calls(doc["python_calls"], "python_calls"),
        _calls(doc["c_calls"], "c_calls"),
        _unit_counts(doc["units"]) if units else (),
    )


def counted_argv(command: Sequence[str], out: Path, units: Sequence[str] = ()) -> list[str]:  # fmt: skip
    """``command`` under the opcount shim, which writes ``out`` and counts
    ``units``; the profiler's ``NotProfiledError`` when the shim cannot run it."""
    # The profiler's CPython argv parser; imported here because the profiler
    # imports trial_runner, which imports this module.
    from autonomous_ai_agents.execution.profiler import _split

    options, kind, name, args = _split(command)
    flags = [part for unit in units for part in ("--unit", unit)]
    return [command[0], *options, str(OPCOUNT_SHIM), str(out), *flags, kind, name, *args]  # fmt: skip


def count_workload(
    phase: Phase,
    workload: Workload,
    *,
    trial_id: str | None = None,
    side: str = "",
    units: Sequence[str] = (),
) -> Counted:
    """One counted run of ``workload`` (module docstring); ``side`` (`` A``,
    `` B``) names the side in its notes. ``units`` (S1, each ``is_unit``,
    else ``ValueError``) ride the same launch and add ``unit_calls`` rows."""
    from autonomous_ai_agents.execution.profiler import NotProfiledError

    bad = [unit for unit in units if not is_unit(unit)]
    if bad:
        raise ValueError(f"{bad[0][:80]!r} is not a unit (PATH::FUNCTION)")
    label = f"workload {workload.name!r}{side}"
    out = phase.scratch / OPCOUNT_NAME
    try:
        argv = counted_argv(workload.command, out, units)
    except NotProfiledError as reason:
        return Counted((), (f"{label} is not counted: {reason}",))
    notes: list[str] = []
    timeout = workload.timeout_s * OPCOUNT_TIMEOUT_FACTOR
    try:
        sample = launch(
            phase, argv, workload.working_dir, timeout, "the counted run", notes,
            workload_id=workload.id,
        )  # fmt: skip
    except RunFailure as failure:
        said = [f"{label}: {note}" for note in notes]
        return Counted((), (*said, f"{label} is not counted: {failure.reason}"))
    said = [f"{label}: {note}" for note in notes]
    data = bytearray()
    try:
        read_capped(out, _opcount_shim.MAX_DOC_BYTES, data.extend)
        counts = parse_counts(bytes(data))
    except (UnusableError, CountFormatError) as problem:
        return Counted((), (*said, f"{label} is not counted: the count output {problem}"))  # fmt: skip
    hardware = _host(phase.policy, 1, int(sample.fs_isolated), int(sample.net_isolated))
    hardware |= {PYTHON_CALLS_KEY: counts.python_calls, C_CALLS_KEY: counts.c_calls}
    total = (float(counts.total),)
    row = _row(workload, trial_id, METRIC_OP_CALLS, "calls", total, hardware)
    return Counted((row, *_unit_rows(workload, trial_id, counts.units, hardware)), tuple(said))  # fmt: skip


def _unit_rows(
    workload: Workload, trial_id: str | None, units: Sequence[UnitCount],
    host: Mapping[str, JsonScalar],
) -> list[Measurement]:  # fmt: skip
    """Per unit a ``unit_calls`` row (its calls; ``out_calls`` in hardware),
    then one per callee edge (``callee``): never ``op_calls`` rows (S1)."""
    base = {k: v for k, v in host.items() if k not in (PYTHON_CALLS_KEY, C_CALLS_KEY)}
    rows: list[Measurement] = []
    for one in units:
        edges: list[tuple[dict[str, JsonScalar], int]] = [({OUT_CALLS_KEY: one.out}, one.calls)]  # fmt: skip
        edges += [({CALLEE_KEY: name}, n) for name, n in one.callees]
        for extra, n in edges:
            hardware: dict[str, JsonScalar] = {**base, UNIT_KEY: one.unit, **extra}
            rows.append(_row(workload, trial_id, METRIC_UNIT_CALLS, "calls", (float(n),), hardware))  # fmt: skip
    return rows


@dataclass(frozen=True)
class Scaled:
    """Scaling rows (G6b): ``a`` the base side (the twin), ``b`` the measured
    phase, each one row per size; the notes."""

    a: tuple[Measurement, ...]
    b: tuple[Measurement, ...]
    notes: tuple[str, ...] = ()


def _scaling_order(
    runs: int, sizes: Sequence[int], sides: Sequence[tuple[str, Phase]]
) -> list[tuple[int, int, str, Phase]]:
    """``(run, size, side, phase)`` launches: sizes forward on an even run
    and backward on an odd one, the sides swapping on every other turn."""
    order: list[tuple[int, int, str, Phase]] = []
    turn = 0
    for index in range(runs):
        for size in sizes[::-1] if index % 2 else sizes:
            for side, phase in sides[::-1] if turn % 2 else sides:
                order.append((index, size, side, phase))
            turn += 1
    return order


def measure_scaling(
    phase: Phase,
    workload: Workload,
    *,
    twin: Phase | None = None,
    trial_id: str | None = None,
) -> Scaled:
    """The scaling runs of ``workload`` (module docstring), interleaved with
    ``twin`` (the base side, `` A``) when given; nothing without a setting."""
    setting = workload.scale
    if setting is None:
        return Scaled((), ())
    label, var = f"workload {workload.name!r}", setting.env_var
    if denied(var) or var in phase.env or (twin is not None and var in twin.env):
        why = f"the size variable {var} is one the engine sets or keeps from workloads"  # fmt: skip
        return Scaled((), (), (f"{label} is not scaled: {why}",))
    sides = [("", phase)] if twin is None else [(" A", twin), (" B", phase)]
    sized = {
        (side, size): replace(at, env={**at.env, var: str(size)})
        for side, at in sides for size in setting.sizes
    }  # fmt: skip
    walls: dict[tuple[str, int], list[float]] = {key: [] for key in sized}
    isolated: dict[tuple[str, int], list[int]] = {key: [0, 0] for key in sized}
    notes: list[str] = []
    try:
        for index, size, side, _ in _scaling_order(setting.runs, setting.sizes, sides):
            where = f"{label}{side} size {size} run {index + 1}/{setting.runs}"
            sample = _run(sized[side, size], workload, where, notes)
            walls[side, size].append(sample.wall_ns / 1e9)
            isolated[side, size][0] += sample.fs_isolated
            isolated[side, size][1] += sample.net_isolated
    except RunFailure as failure:
        return Scaled((), (), (*failure.notes, f"{label} is not scaled: {failure.reason}"))  # fmt: skip
    rows: dict[str, tuple[Measurement, ...]] = {}
    for side, at in sides:
        found: list[Measurement] = []
        for size in setting.sizes:
            fs, net = isolated[side, size]
            hardware = _host(at.policy, setting.runs, fs, net) | {SCALE_SIZE_KEY: size}
            owner = None if side == " A" else trial_id
            found.append(_row(workload, owner, METRIC_SCALE_WALL_S, "s", walls[side, size], hardware))  # fmt: skip
        rows[side] = tuple(found)
    return Scaled(rows.get(" A", ()), rows[sides[-1][0]], tuple(dict.fromkeys(notes)))
