"""Process runner: one sandboxed, measured run of a workload or test command.

``run_once`` resets the fresh dirs (HOME/TMPDIR, fresh per run), opens a
probe listener on 127.0.0.1:0 and starts ``sandbox.launcher_argv`` in a new
session (stdin /dev/null, the report pipe in ``pass_fds``, write ends closed
in the parent at once). One selector thread drains stdout (sha256 over all of
it, its head, its size), stderr (its tail) and the report pipe (64 KiB cap),
so a flood or a pipe held open can neither block nor exhaust the engine; past
``max_output_bytes`` the group is killed ("output flood"). A watchdog SIGKILLs
the group on timeout. The main thread blocks in ``os.wait4`` on the wrapper and
sets ``returncode`` by hand; after every run the group is SIGKILLed until
ESRCH (3 s cap, then a note), and an interrupted wait kills and reaps first.

The report is parsed strictly and cross-checked against the outer accounting:
its wall time inside procrun's ``perf_counter_ns`` interval (the launcher's
clock), its CPU time inside the wrapper's ``wait4`` rusage plus
``CPU_EPSILON_S``, its maxrss under the wrapper's, its exit equal to the
wrapper's (128+signal on both sides). The outer rusage covers everything the
wrapper and launcher reaped, so a genuine report always fits; the checks bound
a forgery from above only, and an under-report rests on the launcher keeping
the report channel out of the workload's reach. A report ``error`` (refusal:
exit 125, both flags false; exec failure: 127) or a ``required`` part not
isolated raises ``RunFailure``; a ``best_effort`` part not isolated (a weakened
drop: both flags false, no error) is a note. A non-zero exit is not a failure
here. Callers turn notes into events; nothing here imports the orchestrator.
A bare wrapper name (``unshare``, ``sandbox-exec``) is resolved on the fixed
system path, never on the child environment's ``PATH``.

``RunFailure.reason`` quotes workload-chosen text (the last stderr line, the
launcher's error) with control characters replaced; it may still carry words a
workload picked, so consumers treat it as data. ``RunFailure.notes`` keeps the
leftover-group and open-pipe facts of a failed run.

Known limitation: with ``network=off`` on Linux there is no PID namespace, so
a ``setsid`` grandchild escapes ``killpg`` and may hold the output pipes open
(a note). Under the other Linux modes it dies with the launcher, PID 1 there.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import shutil
import signal
import socket
import stat
import subprocess  # nosec B404
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Literal, cast

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.execution.protocols import LaunchReport
from autonomous_ai_agents.execution.sandbox import SandboxPolicy, launcher_argv

WRAPPER_PATH = os.defpath
"""Where a bare wrapper name is looked up: ``/bin:/usr/bin`` on Linux and macOS."""

REPORT_MAX_BYTES = 64 * 1024
"""A genuine report is about 200 bytes; more is a flood or a forgery."""
CPU_EPSILON_S = 1e-3
"""CPU cross-check slack: both sides are the kernel's microsecond timevals as
floats and the outer side sums the same reaped processes, so only float
rounding separates a genuine report from the bound."""
DRAIN_CAP_S = 3.0
IO_GRACE_S = 2.0
"""How long the reader waits for EOF once the group is gone."""
MAX_RESET_DEPTH = 64
MISMATCH = "measurement report does not match the process accounting"

_MAXRSS_SCALE = {"linux": 1024, "darwin": 1}  # getrusage(2): KiB; xnu: bytes
_POLL_S, _DRAIN_POLL_S, _CHUNK, _TEXT_CAP = 0.05, 0.01, 64 * 1024, 500
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_seconds(value: object) -> bool:
    return type(value) is float and math.isfinite(value) and value >= 0


def _is_exit(value: object) -> bool:
    return type(value) is int and -signal.NSIG < value <= 255


def _is_flag(value: object) -> bool:
    return type(value) is bool


_FIELDS: dict[str, tuple[Callable[[object], bool], str]] = {
    "wall_ns": (_is_count, "a non-negative integer"),
    "utime": (_is_seconds, "a finite, non-negative float"),
    "stime": (_is_seconds, "a finite, non-negative float"),
    "maxrss": (_is_count, "a non-negative integer"),
    "exit": (_is_exit, "an exit code or a negative signal number"),
    "fs_isolated": (_is_flag, "a boolean"),
    "net_isolated": (_is_flag, "a boolean"),
    "error": (lambda value: value is None or type(value) is str, "a string or null"),
}
REPORT_KEYS = frozenset(_FIELDS)


FailureKind = Literal["exit", "signal", "other"]
"""``exit``/``signal``: the command ran and ended badly (``measure.launch``'s
exit branch, the only place that sets them); ``other``: anything else."""


class RunFailure(Exception):  # noqa: N818 - name fixed by the spec
    """A run that yielded no trustworthy measurement; ``reason`` says why.

    A crash carries the raw ``exit_tail`` (stderr's tail, workload-chosen
    bytes) and the workload's id for ``retry.classify``; it is never sent as
    is."""

    def __init__(
        self,
        reason: str,
        notes: tuple[str, ...] = (),
        *,
        kind: FailureKind = "other",
        exit_tail: bytes = b"",
        workload_id: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason, self.notes = reason, notes
        self.kind, self.exit_tail, self.workload_id = kind, exit_tail, workload_id


@dataclass(frozen=True)
class OutputCaps:
    """Output limits for one run; every value at least 1."""

    max_output_bytes: int
    head_bytes: int
    stderr_tail_bytes: int

    def __post_init__(self) -> None:
        for spec in fields(self):
            if getattr(self, spec.name) < 1:
                raise ValueError(f"{spec.name} must be at least 1")

    @classmethod
    def from_settings(cls, config: Settings | None = None) -> OutputCaps:
        source = settings if config is None else config
        return cls(
            source.MAX_OUTPUT_BYTES, source.OUTPUT_HEAD_BYTES, source.STDERR_TAIL_BYTES
        )


@dataclass(frozen=True)
class RunSample:
    """One trusted run: the launcher's numbers (maxrss in bytes, exit negative
    for a signal), the isolation flags, the captured output and the notes."""

    wall_ns: int
    utime: float
    stime: float
    maxrss_bytes: int
    exit: int
    fs_isolated: bool
    net_isolated: bool
    stdout_sha256: str
    stdout_head: bytes
    stdout_bytes: int
    stderr_tail: bytes
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Accounting:
    """procrun's wall clock and the wrapper's raw ``wait4`` rusage and exit."""

    wall_ns: int
    utime: float
    stime: float
    maxrss: int
    exit: int


@dataclass(frozen=True)
class RunOutcome:
    """What a finished run left behind, before ``judge`` trusts any of it."""

    outer: Accounting
    report: bytes
    report_complete: bool
    outputs_complete: bool
    group_drained: bool
    timed_out: bool
    timeout_s: float
    overflow: str | None
    stdout_sha256: str
    stdout_head: bytes
    stdout_bytes: int
    stderr_tail: bytes


def maxrss_scale(platform: str) -> int:
    """Bytes per ``ru_maxrss`` unit: 1024 on Linux, 1 on darwin."""
    try:
        return _MAXRSS_SCALE[platform]
    except KeyError:
        raise ValueError(f"no ru_maxrss unit is known for {platform!r}") from None


def process_status(code: int) -> int:
    """An exit code as a parent sees the status: 128+signal for a signal."""
    return code if code >= 0 else 128 - code


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(found := dict(pairs)) != len(pairs):
        raise ValueError("duplicate key")
    return found


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not a finite number")


def parse_report(data: bytes) -> LaunchReport:
    """Exactly one JSON object with exactly the ``LaunchReport`` keys and types."""
    try:
        raw: object = json.loads(
            data.decode(), object_pairs_hook=_unique_keys, parse_constant=_no_constant
        )
        if not isinstance(raw, dict) or set(raw) != REPORT_KEYS:
            keys = sorted(REPORT_KEYS)
            raise ValueError(f"it must be one object with exactly the keys {keys}")
        for key, (valid, kind) in _FIELDS.items():
            if not valid(raw[key]):
                raise ValueError(f"{key} must be {kind}")
    except ValueError as error:  # JSONDecodeError and UnicodeDecodeError too
        raise RunFailure(f"malformed measurement report: {error}") from None
    return cast(LaunchReport, raw)


def check_report(
    report: LaunchReport, outer: Accounting, policy: SandboxPolicy
) -> None:
    """``RunFailure(MISMATCH)`` unless the report fits the outer accounting."""
    fits = (
        report["wall_ns"] <= outer.wall_ns
        and report["utime"] + report["stime"]
        <= outer.utime + outer.stime + CPU_EPSILON_S
        and report["maxrss"] <= outer.maxrss  # same platform unit on both sides
        and process_status(report["exit"]) == process_status(outer.exit)
        and not (report["fs_isolated"] and policy.fs == "off")
        and not (report["net_isolated"] and policy.network == "off")
    )
    if not fits:
        raise RunFailure(MISMATCH)


def _quote(text: str) -> str:
    """Workload-chosen text, capped, with every non-printable character '?'."""
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_TEXT_CAP])


def judge(outcome: RunOutcome, policy: SandboxPolicy) -> RunSample:
    """Turn a finished run into a sample, or raise ``RunFailure`` (with notes)."""
    notes: list[str] = []
    if not outcome.group_drained:
        notes.append(f"process group still alive after {DRAIN_CAP_S:g} s")
    if not outcome.outputs_complete:
        notes.append("an output pipe was still open after the run")
    try:
        return _judge(outcome, policy, list(notes))
    except RunFailure as failure:
        raise RunFailure(failure.reason, tuple(notes)) from None


def _judge(outcome: RunOutcome, policy: SandboxPolicy, notes: list[str]) -> RunSample:
    # The watchdog's verdict counts only when its SIGKILL ended the wrapper; a
    # wrapper that exited on its own just before the deadline left a real run.
    if outcome.timed_out and outcome.outer.exit == -signal.SIGKILL:
        raise RunFailure(f"timeout after {outcome.timeout_s:g} s")
    if outcome.overflow is not None:
        raise RunFailure(outcome.overflow)
    if not outcome.report_complete:
        raise RunFailure("the measurement report pipe was still open after the run")
    if not outcome.report:
        lines = outcome.stderr_tail.decode(errors="replace").strip().splitlines()
        last = _quote(lines[-1]) if lines else "no stderr"
        code = outcome.outer.exit
        raise RunFailure(f"no measurement report (wrapper exit {code}): {last}")
    report = parse_report(outcome.report)
    check_report(report, outcome.outer, policy)
    if (error := report["error"]) is not None:
        raise RunFailure(f"launcher: {_quote(error)}")
    for part, mode, isolated in (
        ("fs", policy.fs, report["fs_isolated"]),
        ("network", policy.network, report["net_isolated"]),
    ):
        if isolated or mode == "off":
            continue
        if mode == "required":
            raise RunFailure(f"{part} isolation is required but was not applied")
        notes.append(f"{part} isolation was not applied ({mode})")
    return RunSample(
        wall_ns=report["wall_ns"],
        utime=report["utime"],
        stime=report["stime"],
        maxrss_bytes=report["maxrss"] * maxrss_scale(policy.platform),
        exit=report["exit"],
        fs_isolated=report["fs_isolated"],
        net_isolated=report["net_isolated"],
        stdout_sha256=outcome.stdout_sha256,
        stdout_head=outcome.stdout_head,
        stdout_bytes=outcome.stdout_bytes,
        stderr_tail=outcome.stderr_tail,
        notes=tuple(notes),
    )


def kill_group(pgid: int, *, killpg: Callable[[int, int], None] = os.killpg) -> bool:
    """SIGKILL the process group; ``False`` once it has no member (ESRCH)."""
    try:
        killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return False
    except PermissionError:  # macOS answers EPERM for a group of zombies
        pass
    return True


def drain_group(
    pgid: int,
    *,
    cap_s: float = DRAIN_CAP_S,
    killpg: Callable[[int, int], None] = os.killpg,
    sleep: Callable[[float], object] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """SIGKILL the group until ESRCH; ``False`` when it outlives ``cap_s``."""
    deadline = clock() + cap_s
    while kill_group(pgid, killpg=killpg):
        if clock() >= deadline:
            return False
        sleep(_DRAIN_POLL_S)
    return True


class OutputPump:
    """Drains stdout, stderr and the report pipe on one thread; never blocks.

    ``open`` holds the fds short of EOF. A stream past its cap is dropped,
    named in ``overflow`` and ``on_overflow`` (the group kill) is called.
    After ``finish(grace_s)`` the loop also ends at that deadline.
    """

    def __init__(
        self,
        caps: OutputCaps,
        *,
        stdout: int,
        stderr: int,
        report: int,
        on_overflow: Callable[[], object],
    ) -> None:
        self.caps, self.on_overflow, self.report_fd = caps, on_overflow, report
        self.sinks: dict[int, Callable[[bytes], str | None]] = {
            stdout: self._stdout,
            stderr: self._stderr,
            report: self._report,
        }
        self.open = set(self.sinks)
        self.sha256 = hashlib.sha256()
        self.head, self.tail, self.report = bytearray(), bytearray(), bytearray()
        self.stdout_bytes = self.stderr_bytes = 0
        self.overflow: str | None = None
        self._deadline = math.inf

    def finish(self, grace_s: float) -> None:
        self._deadline = time.monotonic() + grace_s

    def run(self) -> None:
        with selectors.DefaultSelector() as selector:
            for fd in self.open:
                selector.register(fd, selectors.EVENT_READ)
            while selector.get_map() and time.monotonic() < self._deadline:
                for key, _ in selector.select(_POLL_S):
                    if not (chunk := os.read(key.fd, _CHUNK)):
                        self.open.discard(key.fd)
                        selector.unregister(key.fd)
                    elif (problem := self.sinks[key.fd](chunk)) is not None:
                        selector.unregister(key.fd)
                        self.overflow = self.overflow or problem
                        self.on_overflow()

    def _flood(self, total: int, stream: str) -> str | None:
        if total <= self.caps.max_output_bytes:
            return None
        return f"output flood: more than {self.caps.max_output_bytes} bytes on {stream}"

    def _stdout(self, chunk: bytes) -> str | None:
        self.stdout_bytes += len(chunk)
        self.sha256.update(chunk)
        self.head += chunk[: max(0, self.caps.head_bytes - len(self.head))]
        return self._flood(self.stdout_bytes, "stdout")

    def _stderr(self, chunk: bytes) -> str | None:
        self.stderr_bytes += len(chunk)
        self.tail += chunk
        del self.tail[: -self.caps.stderr_tail_bytes]
        return self._flood(self.stderr_bytes, "stderr")

    def _report(self, chunk: bytes) -> str | None:
        self.report += chunk
        if len(self.report) > REPORT_MAX_BYTES:
            return f"the measurement report is larger than {REPORT_MAX_BYTES} bytes"
        return None


def reset_dirs(paths: Sequence[Path], policy: SandboxPolicy, *, cwd: Path) -> None:
    """Empty and recreate each dir (mode 0700), parents first, before a run.

    Each must be absolute, normalised and inside one of the policy's
    (realpath'd) writable dirs, but not the one that holds ``cwd`` (the
    worktree), and must neither hold nor sit inside ``cwd`` (``ValueError``).
    Every component is ``lstat``ed and opened ``O_NOFOLLOW`` relative to its
    parent and deletion goes through directory fds, so a symlink or file an
    earlier run planted is refused, never followed (``RunFailure``); a dir it
    left without owner permissions is chmodded 0700 first.

    Only what is listed is reset. To close every cross-run channel the
    sandbox leaves open, list each writable dir except the worktree itself
    (``_scratch/<phase>``), then HOME and TMPDIR inside it: a file written
    next to HOME otherwise survives into the next timed run.
    """
    work = Path(os.path.realpath(cwd))
    for path in sorted(set(paths), key=lambda item: len(item.parts)):
        if not path.is_absolute() or os.path.normpath(path) != str(path):
            raise ValueError(f"fresh dir {str(path)!r} must be absolute and normalised")
        if path.is_relative_to(work) or work.is_relative_to(path):
            raise ValueError(f"fresh dir {path} overlaps the working directory {work}")
        root = next((w for w in policy.writable if path.is_relative_to(w)), None)
        if root is None:
            raise ValueError(f"fresh dir {path} is not inside a writable dir")
        if work.is_relative_to(root):
            raise ValueError(f"fresh dir {path}: {root} holds the working directory")
        names = path.relative_to(root).parts or (root.name,)
        try:
            _recreate(root if path != root else root.parent, names, path)
        except OSError as error:
            raise RunFailure(f"cannot reset fresh dir {path}: {error}") from None


def _plain_dir(fd: int, name: str, path: Path) -> bool:
    """Whether ``name`` in ``fd`` exists as a directory; refuses anything else."""
    try:
        mode = os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        what = "a symlink" if stat.S_ISLNK(mode) else "not a directory"
        raise RunFailure(f"fresh dir {path}: {name!r} is {what}")
    return True


def _recreate(start: Path, names: tuple[str, ...], path: Path) -> None:
    fd = os.open(start, _DIR_FLAGS)
    try:
        for name in names[:-1]:
            if not _plain_dir(fd, name, path):
                os.mkdir(name, 0o700, dir_fd=fd)
            child = _open_dir(fd, name)
            os.close(fd)
            fd = child
        if _plain_dir(fd, names[-1], path):
            _remove_dir(fd, names[-1], path, depth=0)
        os.mkdir(names[-1], 0o700, dir_fd=fd)
    finally:
        os.close(fd)


def _open_dir(parent: int, name: str) -> int:
    """Open the dir ``name`` in ``parent`` (``O_NOFOLLOW``) and make it 0700.

    A dir a run left unreadable is chmodded first without following a
    symlink (unsupported or refused: the open fails as before); ``fchmod``
    then acts on the opened inode only, so emptying it cannot fail on its
    mode. A dir owned by another uid still fails closed (EPERM).
    """
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except PermissionError:
        try:
            os.chmod(name, 0o700, dir_fd=parent, follow_symlinks=False)
        except (OSError, NotImplementedError, ValueError):
            pass  # Python raises ValueError for a symlink here
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    try:
        os.fchmod(fd, 0o700)
    except OSError:
        os.close(fd)
        raise
    return fd


def _remove_dir(parent: int, name: str, path: Path, *, depth: int) -> None:
    """Delete the directory ``name`` in ``parent`` and everything below it."""
    if depth > MAX_RESET_DEPTH:
        raise RunFailure(f"fresh dir {path} is nested more than {MAX_RESET_DEPTH} deep")
    fd = _open_dir(parent, name)
    try:
        with os.scandir(fd) as entries:
            listing = [
                (item.name, item.is_dir(follow_symlinks=False)) for item in entries
            ]
        for child, is_dir in listing:
            if is_dir:
                _remove_dir(fd, child, path, depth=depth + 1)
            else:
                os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent)


def _probe_listener() -> socket.socket:
    """The 127.0.0.1 listener the launcher's connect self-check must not reach."""
    return socket.create_server(("127.0.0.1", 0), backlog=1)


def resolve_wrapper(name: str, *, path: str = WRAPPER_PATH) -> str:
    """The wrapper binary on ``path``: a root-owned file only root may write.

    It holds the report fd and applies the sandbox, so it never comes from
    the child environment's ``PATH`` (``Popen`` would look it up there).
    """
    found = shutil.which(name, path=path)
    if found is None:
        raise RunFailure(f"the sandbox wrapper {name!r} is not installed in {path}")
    real = os.path.realpath(found)
    info = os.stat(real)
    writable = info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or writable:
        raise RunFailure(
            f"the sandbox wrapper {real} is not a file only root may write"
        )
    return real


def _close(fds: list[int], *which: int) -> None:
    """Close each of ``which`` exactly once, dropping it from ``fds``."""
    for fd in which:
        fds.remove(fd)
        os.close(fd)


def run_once(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    sandbox: SandboxPolicy,
    timeout_s: float,
    caps: OutputCaps,
    *,
    fresh_dirs: Sequence[Path] = (),
    python: str = sys.executable,
) -> RunSample:
    """Run ``argv`` once in ``cwd`` under ``sandbox``; ``RunFailure``.

    ``fresh_dirs`` (HOME, TMPDIR) are reset first, see ``reset_dirs``.
    """
    if not (math.isfinite(timeout_s) and 0 < timeout_s <= threading.TIMEOUT_MAX):
        raise ValueError(
            f"timeout_s must be a positive number up to {threading.TIMEOUT_MAX:g},"
            f" got {timeout_s}"
        )
    if not cwd.is_absolute():
        raise ValueError(f"cwd {str(cwd)!r} must be absolute")
    fds: list[int] = []  # every pipe end still open
    try:
        with _probe_listener() as probe:
            for _ in range(3):
                fds += os.pipe()
            out_r, out_w, err_r, err_w, rep_r, rep_w = fds
            port: int = probe.getsockname()[1]
            command = launcher_argv(
                sandbox, fd=rep_w, report_port=port, argv=argv, python=python
            )
            bare = not os.path.isabs(command[0])
            executable = resolve_wrapper(command[0]) if bare else None
            reset_dirs(fresh_dirs, sandbox, cwd=cwd)
            start = time.perf_counter_ns()
            try:
                proc = subprocess.Popen(  # nosec B603
                    command,
                    executable=executable,
                    cwd=cwd,
                    env=dict(env),
                    stdin=subprocess.DEVNULL,
                    stdout=out_w,
                    stderr=err_w,
                    pass_fds=(rep_w,),
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as error:
                raise RunFailure(
                    f"cannot start {command[0]!r} in {cwd}: {error}"
                ) from None
            finally:
                _close(fds, out_w, err_w, rep_w)
            pump = OutputPump(
                caps,
                stdout=out_r,
                stderr=err_r,
                report=rep_r,
                on_overflow=lambda: kill_group(proc.pid),
            )
            outcome = _supervise(proc, start, timeout_s, pump)
    finally:
        _close(fds, *fds)
    return judge(outcome, sandbox)


def _supervise(
    proc: subprocess.Popen[bytes], start: int, timeout_s: float, pump: OutputPump
) -> RunOutcome:
    """Wait for the wrapper, then always kill and drain its group."""
    pgid, done, timed_out = proc.pid, threading.Event(), threading.Event()

    def watchdog() -> None:
        if not done.wait(timeout_s):
            timed_out.set()
            kill_group(pgid)

    threads: list[threading.Thread] = []
    status: int | None = None
    try:
        for job in (pump.run, watchdog):
            thread = threading.Thread(target=job, daemon=True)
            thread.start()
            threads.append(thread)
        _, status, usage = os.wait4(pgid, 0)
        done.set()  # first: the watchdog must not fire on a finished wrapper
        wall_ns = time.perf_counter_ns() - start
    finally:
        done.set()
        if status is None:  # interrupted (Ctrl-C): never leave the group running
            kill_group(pgid)
            try:
                _, status, _ = os.wait4(pgid, 0)
            except ChildProcessError:  # the interrupted wait4 had reaped it
                pass
        # Set by hand so Popen never polls (and reaps) a reused pid; when the
        # status was lost to the interrupt, SIGKILL is what the group got.
        proc.returncode = (
            -signal.SIGKILL if status is None else os.waitstatus_to_exitcode(status)
        )
        drained = drain_group(pgid)
        pump.finish(IO_GRACE_S)
        for thread in threads:
            thread.join(IO_GRACE_S + 1.0)
    return RunOutcome(
        outer=Accounting(
            wall_ns, usage.ru_utime, usage.ru_stime, usage.ru_maxrss, proc.returncode
        ),
        report=bytes(pump.report),
        report_complete=pump.report_fd not in pump.open,
        outputs_complete=pump.open <= {pump.report_fd},
        group_drained=drained,
        timed_out=timed_out.is_set(),
        timeout_s=timeout_s,
        overflow=pump.overflow,
        stdout_sha256=pump.sha256.hexdigest(),
        stdout_head=bytes(pump.head),
        stdout_bytes=pump.stdout_bytes,
        stderr_tail=bytes(pump.tail),
    )
