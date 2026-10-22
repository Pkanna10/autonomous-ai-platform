"""Measurement launcher, run by path: ``python -I -S launcher.py <fd> <spec> -- argv``.

STDLIB ONLY, without even ``typing`` or ``dataclasses`` at run time: exec
keeps the forking process's RSS high-water mark, so the launcher's size is
the floor of every ``peak_rss_bytes`` (about 8 MiB).

Linux, in order. The launcher first makes itself non-dumpable
(``PR_SET_DUMPABLE`` 0) so a workload without capabilities cannot reach it
through ``/proc/<pid>/mem``, ``/proc/<pid>/fd`` or ptrace. With the network
isolated it runs inside ``sandbox.UNSHARE_ARGV`` (user, network, PID and IPC
namespaces and a private ``/proc``). Then: ``lo`` up, ``PR_SET_NO_NEW_PRIVS``,
Landlock handling writes only (the writable dirs and ``/dev/null``:
``/dev/shm`` is deliberately *not* writable, because it is shared across runs
and a workload could carry state from one timed run to the next; a per-run
tmpfs for workloads that need shared memory is a Step 5 item), then the
self-check: ``O_CREAT|O_EXCL`` in the probe dir must fail with EACCES/EPERM and
a connect to the parent's 127.0.0.1 probe listener must fail.

Before the fork the launcher resets its Python-level signal handlers (SIGINT)
to SIG_DFL: PID 1 of a namespace only receives a signal sent from inside it
when it has a handler, so the workload cannot kill the launcher unreported.

In the forked child, before exec, on Linux and in every mode (the report
channel needs it whatever the fs mode: a userns-root workload's CAP_SYS_PTRACE
would get past the non-dumpable launcher) the launcher sheds every privilege:
``PR_SET_NO_NEW_PRIVS``, the whole capability bounding set, the ambient set,
locked securebits and an empty ``capset``. Without CAP_SETPCAP (a non-root
launcher outside any user namespace) the bounding set and securebits cannot
change; that is accepted only when no effective or permitted capability is
held, since no_new_privs then stops execve from granting any. A failed drop
refuses the run (exit 125, the workload never runs) when either part is
``required``; otherwise the run continues and both flags go false. Child-side
outcomes travel on a close-on-exec error pipe (the pattern ``subprocess``
uses) as NUL-terminated records tagged R (refused), W (drop failed, run
continues) or E (exec failed); a clean exec closes the pipe with EOF, so a
workload's own exit status 125/126/127 is never read as a launcher failure.

On darwin ``sandbox-exec`` applied the policy, so only the self-check runs and
there is no privilege drop (there is no ``/proc``); report integrity there
rests on ``sandbox-exec`` plus the process runner's outer cross-checks (U11).

Under ``required`` a failed isolation step writes ``error`` and exits 125
without exec; ``best_effort`` records the flag as false; ``off`` skips. Then
fork/exec, ``wait4``, and one JSON ``LaunchReport`` on the fd with raw
``ru_maxrss`` (the engine scales it). After the report is written the launcher
exits with the workload's own status (128+signal for a signal), so the outer
wrapper's exit status is ground truth for the process runner's cross-check. A
refusal is a report whose ``error`` is set with both flags false (and exit 125
in it); a workload may itself exit 125, so that status alone never means a
refusal. Every OS call goes through ``Ops`` so tests run all of it in-process.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import signal
import socket
import struct
import sys
import time

TYPE_CHECKING = False
if TYPE_CHECKING:
    import ctypes
    import resource
    from collections.abc import Callable, Sequence
    from typing import NoReturn

    SysArg = int | bytes | None

SPEC_VERSION = 1
MODES = ("required", "best_effort", "off")
PLATFORMS = ("linux", "darwin")
EXIT_REFUSED = 125
EXIT_EXEC_FAILED = 127
PROBE_TIMEOUT_S = 2.0

_SPEC_KEYS = frozenset(
    {"version", "platform", "fs", "net", "writable", "probe_dir", "probe_port"}
)
_USAGE = "usage: launcher.py <fd> <spec-json> -- argv..."
_REFUSED = {"wall_ns": 0, "utime": 0.0, "stime": 0.0, "maxrss": 0, "exit": EXIT_REFUSED}

# netdevice(7): bring up lo inside the fresh network namespace.
_SIOCGIFFLAGS, _SIOCSIFFLAGS, _IFF_UP = 0x8913, 0x8914, 0x1
_IFREQ = "16sH22x"

# prctl(2) options. DUMPABLE guards the launcher's /proc; the rest shed
# privilege in the child so a userns-root workload has no capabilities.
_PR_SET_DUMPABLE = 4
_PR_SET_NO_NEW_PRIVS = 38
_PR_CAPBSET_DROP = 24
_PR_CAP_AMBIENT = 47
_PR_CAP_AMBIENT_CLEAR_ALL = 4
_PR_SET_SECUREBITS = 28
# NOROOT | NOROOT_LOCKED | NO_SETUID_FIXUP | NO_SETUID_FIXUP_LOCKED | KEEP_CAPS_LOCKED
_SECUREBITS = 0x2F
# capset(2) with _LINUX_CAPABILITY_VERSION_3 and two zeroed 32-bit data words.
_LINUX_CAPABILITY_VERSION_3 = 0x20080522
_CAP_HEADER = struct.pack("=II", _LINUX_CAPABILITY_VERSION_3, 0)
_CAP_DATA = struct.pack("=6I", 0, 0, 0, 0, 0, 0)
_CAP_LAST_CAP_PATH = "/proc/sys/kernel/cap_last_cap"
_CAP_BOUND_LIMIT = 63  # fall back ceiling if cap_last_cap is unreadable
_CHILD_REFUSE = b"R"  # error-pipe record: a required privilege drop failed
_CHILD_WEAKENED = b"W"  # a non-required privilege drop failed; the run goes on
_CHILD_EXEC = b"E"  # the workload could not be exec'd
_RECORD_END = b"\0"

# landlock(7). The syscall numbers are the same on x86_64 and aarch64.
_SYS_CREATE_RULESET, _SYS_ADD_RULE, _SYS_RESTRICT_SELF = 444, 445, 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_WRITE_FILE = 1 << 1
_WRITE_TREE = sum(1 << bit for bit in range(4, 13))  # REMOVE_DIR .. MAKE_SYM
_REFER = 1 << 13  # ABI 2
_TRUNCATE = 1 << 14  # ABI 3
_DEV_NULL = "/dev/null"
_O_PATH = getattr(os, "O_PATH", os.O_RDONLY)

_DENIED = frozenset({errno.EACCES, errno.EPERM})
_UNREACHABLE = _DENIED | {
    errno.ECONNREFUSED,
    errno.ENETUNREACH,
    errno.EHOSTUNREACH,
    errno.ENETDOWN,
    errno.EADDRNOTAVAIL,
}


def handled_access_fs(abi: int) -> int:
    """The write rights Landlock handles at ``abi``; never exec, reads or ioctl."""
    if abi < 1:
        raise ValueError(f"Landlock ABI {abi} is not supported")
    mask = _WRITE_FILE | _WRITE_TREE
    if abi >= 2:
        mask |= _REFER
    if abi >= 3:
        mask |= _TRUNCATE
    return mask


def file_access_fs(abi: int) -> int:
    """The rights a rule on a non-directory may carry: write and truncate."""
    return handled_access_fs(abi) & (_WRITE_FILE | _TRUNCATE)


def landlock_rules(writable: Sequence[str], *, abi: int) -> list[tuple[str, int]]:
    """``(path, allowed mask)`` per rule: the writable paths and /dev/null."""
    full, file_only = handled_access_fs(abi), file_access_fs(abi)
    rules = [(path, full if os.path.isdir(path) else file_only) for path in writable]
    return [*rules, (_DEV_NULL, file_only)]


def strictest(*modes: str) -> str:
    """The strictest of ``modes``: ``required``, then ``best_effort``, then ``off``."""
    return min(modes, key=MODES.index)


class LaunchSpec:
    """The parsed spec JSON; ``sandbox.launcher_argv`` writes it."""

    def __init__(
        self,
        *,
        platform: str,
        fs: str,
        net: str,
        writable: tuple[str, ...],
        probe_dir: str,
        probe_port: int | None,
    ) -> None:
        self.platform = platform
        self.fs = fs
        self.net = net
        self.writable = writable
        self.probe_dir = probe_dir
        self.probe_port = probe_port


def _absolute(path: object) -> bool:
    return isinstance(path, str) and os.path.isabs(path) and "\0" not in path


def parse_spec(text: str) -> LaunchSpec:
    """Validate the spec strictly: exact keys, exact types; ``ValueError``."""
    try:
        raw: object = json.loads(text)
    except ValueError as error:
        raise ValueError(f"spec is not JSON: {error}") from None
    if not isinstance(raw, dict) or set(raw) != _SPEC_KEYS:
        raise ValueError(f"spec must be an object with the keys {sorted(_SPEC_KEYS)}")
    version, port, writable = raw["version"], raw["probe_port"], raw["writable"]
    if type(version) is not int or version != SPEC_VERSION:
        raise ValueError(f"spec version must be {SPEC_VERSION}, got {version!r}")
    for key, allowed in (("platform", PLATFORMS), ("fs", MODES), ("net", MODES)):
        if not isinstance(raw[key], str) or raw[key] not in allowed:
            raise ValueError(f"spec {key} must be one of {allowed}, got {raw[key]!r}")
    if not isinstance(writable, list) or not all(map(_absolute, writable)):
        raise ValueError("spec writable must be a list of absolute paths")
    if not _absolute(raw["probe_dir"]):
        raise ValueError("spec probe_dir must be an absolute path")
    if port is not None and (type(port) is not int or not 0 < port < 65536):
        raise ValueError(f"spec probe_port must be null or a port, got {port!r}")
    return LaunchSpec(
        platform=raw["platform"],
        fs=raw["fs"],
        net=raw["net"],
        writable=tuple(writable),
        probe_dir=raw["probe_dir"],
        probe_port=port,
    )


def parse_args(argv: Sequence[str]) -> tuple[int, LaunchSpec, list[str]]:
    """``<fd> <spec-json> -- argv...`` -> (fd, spec, argv); ``ValueError``."""
    if len(argv) < 4 or argv[2] != "--":
        raise ValueError(_USAGE)
    if not (argv[0].isascii() and argv[0].isdigit()) or not 3 <= int(argv[0]) < 2**31:
        raise ValueError(f"report fd must be a number from 3, got {argv[0]!r}")
    return int(argv[0]), parse_spec(argv[1]), list(argv[3:])


class Ops:
    """Every OS call the launcher makes: real in ``default_ops``, fakes in tests."""

    def __init__(
        self,
        *,
        platform: str,
        syscall: Callable[[int, tuple[SysArg, ...]], int],
        ioctl: Callable[[int, int, bytes], bytes],
        prctl: Callable[[int, int], int],
        capset: Callable[[bytes, bytes], int],
        capget: Callable[[], tuple[int, int, int]],
        cap_last_cap: Callable[[], int | None],
        open: Callable[[str, int, int], int],
        connect: Callable[[str, int], None],
        pipe: Callable[[], tuple[int, int]],
        fork: Callable[[], int],
        execvp: Callable[[str, list[str]], NoReturn],
        wait4: Callable[[int, int], tuple[int, int, resource.struct_rusage]],
        exit: Callable[[int], NoReturn],
        reset_signals: Callable[[], None],
        clear_handlers: Callable[[], None],
    ) -> None:
        self.platform = platform
        self.syscall = syscall
        self.ioctl = ioctl
        self.prctl = prctl
        self.capset = capset
        self.capget = capget
        self.cap_last_cap = cap_last_cap
        self.open = open
        self.connect = connect
        self.pipe = pipe
        self.fork = fork
        self.execvp = execvp
        self.wait4 = wait4
        self.exit = exit
        self.reset_signals = reset_signals
        self.clear_handlers = clear_handlers


_LIBC: list[ctypes.CDLL] = []


def libc() -> ctypes.CDLL:
    """libc through ctypes, loaded on first use only."""
    if not _LIBC:
        import ctypes

        handle = ctypes.CDLL(None, use_errno=True)
        handle.syscall.restype = ctypes.c_long
        _LIBC.append(handle)
    return _LIBC[0]


def _checked(result: int) -> int:
    if result < 0:
        import ctypes

        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return result


def real_syscall(nr: int, args: tuple[SysArg, ...]) -> int:
    """``syscall(2)`` with every argument passed at full register width."""
    import ctypes

    converted: list[object] = [ctypes.c_long(nr)]
    for arg in args:
        if arg is None:
            converted.append(ctypes.c_void_p(None))
        elif isinstance(arg, bytes):
            converted.append(ctypes.c_char_p(arg))
        else:
            converted.append(ctypes.c_long(arg))
    return _checked(int(libc().syscall(*converted)))


def real_prctl(option: int, arg2: int) -> int:
    import ctypes

    zero = ctypes.c_ulong(0)
    call = libc().prctl(ctypes.c_int(option), ctypes.c_ulong(arg2), zero, zero, zero)
    return _checked(int(call))


def real_capset(header: bytes, data: bytes) -> int:
    """``capset(2)`` with the given header and data structs; ``OSError``."""
    import ctypes

    call = libc().capset(ctypes.c_char_p(header), ctypes.c_char_p(data))
    return _checked(int(call))


def real_capget() -> tuple[int, int, int]:
    """``capget(2)`` of this process: (effective, permitted, inheritable)."""
    import ctypes

    header = ctypes.create_string_buffer(_CAP_HEADER, len(_CAP_HEADER))
    data = ctypes.create_string_buffer(len(_CAP_DATA))
    _checked(int(libc().capget(header, data)))
    eff0, prm0, inh0, eff1, prm1, inh1 = struct.unpack("=6I", data.raw)
    return eff0 | eff1 << 32, prm0 | prm1 << 32, inh0 | inh1 << 32


def real_cap_last_cap() -> int | None:
    """The kernel's highest capability number, or ``None`` when unreadable."""
    try:
        with open(_CAP_LAST_CAP_PATH, encoding="ascii") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def real_connect(host: str, port: int) -> None:
    socket.create_connection((host, port), timeout=PROBE_TIMEOUT_S).close()


def restore_signals(
    set_handler: Callable[[int, signal.Handlers], object] = signal.signal,
) -> None:
    """Undo Python's startup SIG_IGN, as ``subprocess`` does before exec."""
    for name in ("SIGPIPE", "SIGXFSZ"):
        signum = getattr(signal, name, None)
        if signum is not None:
            set_handler(signum, signal.SIG_DFL)


def clear_signal_handlers(
    getsignal: Callable[[int], object] = signal.getsignal,
    set_handler: Callable[[int, signal.Handlers], object] = signal.signal,
) -> None:
    """Reset every Python-level handler (Python installs SIGINT's) to SIG_DFL.

    PID 1 of a namespace receives a signal sent from inside it only when a
    handler is installed, so with none left the workload cannot kill the
    launcher before it reaps and reports.
    """
    for signum in signal.valid_signals():
        if callable(getsignal(signum)):
            set_handler(signum, signal.SIG_DFL)


def default_ops() -> Ops:
    return Ops(
        platform=sys.platform,
        syscall=real_syscall,
        ioctl=fcntl.ioctl,
        prctl=real_prctl,
        capset=real_capset,
        capget=real_capget,
        cap_last_cap=real_cap_last_cap,
        open=os.open,
        connect=real_connect,
        pipe=os.pipe,
        fork=os.fork,
        execvp=os.execvp,
        wait4=os.wait4,
        exit=os._exit,
        reset_signals=restore_signals,
        clear_handlers=clear_signal_handlers,
    )


def loopback_up(ops: Ops) -> None:
    """Set IFF_UP on ``lo``, keeping its other flags."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        fd = sock.fileno()
        current = ops.ioctl(fd, _SIOCGIFFLAGS, struct.pack(_IFREQ, b"lo", 0))
        flags = struct.unpack(_IFREQ, current)[1]
        ops.ioctl(fd, _SIOCSIFFLAGS, struct.pack(_IFREQ, b"lo", flags | _IFF_UP))


def landlock_restrict(ops: Ops, writable: Sequence[str]) -> None:
    """Confine this process's writes to the rules; raises ``OSError``."""
    abi = ops.syscall(_SYS_CREATE_RULESET, (None, 0, _CREATE_RULESET_VERSION))
    if abi < 1:
        raise OSError(errno.EOPNOTSUPP, f"Landlock ABI {abi} is not usable")
    attr = struct.pack("=Q", handled_access_fs(abi))
    ruleset = ops.syscall(_SYS_CREATE_RULESET, (attr, len(attr), 0))
    try:
        for path, mask in landlock_rules(writable, abi=abi):
            fd = ops.open(path, _O_PATH | os.O_CLOEXEC, 0)
            try:
                rule = struct.pack("=Qi", mask, fd)
                ops.syscall(_SYS_ADD_RULE, (ruleset, _RULE_PATH_BENEATH, rule, 0))
            finally:
                os.close(fd)
        ops.syscall(_SYS_RESTRICT_SELF, (ruleset, 0))
    finally:
        os.close(ruleset)


def _drop_bounding_set(ops: Ops) -> None:
    """0..``cap_last_cap``, or up to the first EINVAL when that is unreadable."""
    last = ops.cap_last_cap()
    for cap in range((_CAP_BOUND_LIMIT if last is None else last) + 1):
        try:
            ops.prctl(_PR_CAPBSET_DROP, cap)
        except OSError as error:
            if last is None and error.errno == errno.EINVAL:
                return
            raise


def drop_capabilities(ops: Ops) -> None:
    """Shed every capability so a userns-root workload cannot reach the launcher.

    ``no_new_privs``, the whole bounding set, the ambient set, locked
    securebits and an empty ``capset``. Without CAP_SETPCAP the bounding set
    and securebits cannot change: that EPERM is accepted only when no effective
    or permitted capability is held (no_new_privs then stops execve from
    granting any, and the empty ``capset`` still clears the inheritable set).
    Raises ``OSError`` on any other failure.
    """
    ops.prctl(_PR_SET_NO_NEW_PRIVS, 1)
    privileged = True
    try:
        _drop_bounding_set(ops)
    except OSError as error:
        if error.errno != errno.EPERM or any(ops.capget()[:2]):
            raise
        privileged = False
    ops.prctl(_PR_CAP_AMBIENT, _PR_CAP_AMBIENT_CLEAR_ALL)
    if privileged:
        ops.prctl(_PR_SET_SECUREBITS, _SECUREBITS)
    ops.capset(_CAP_HEADER, _CAP_DATA)


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def probe_write(ops: Ops, probe_dir: str) -> str | None:
    """``None`` when creating a file in ``probe_dir`` is denied, else why not."""
    path = os.path.join(probe_dir, f".aip-probe-{os.urandom(8).hex()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = ops.open(path, flags, 0o600)
    except OSError as error:
        if error.errno in _DENIED:
            return None
        return f"the probe write got {_describe(error)}: it does not prove isolation"
    os.close(fd)
    os.unlink(path)
    return f"a write in the probe dir {probe_dir} succeeded"


def probe_connect(ops: Ops, port: int | None) -> str | None:
    """``None`` when the parent's 127.0.0.1 listener is unreachable, else why not."""
    if port is None:
        return "no probe port was given"
    try:
        ops.connect("127.0.0.1", port)
    except OSError as error:
        if error.errno in _UNREACHABLE:
            return None
        return f"the probe connect got {_describe(error)}: it does not prove isolation"
    return f"a connect to the parent's 127.0.0.1:{port} succeeded"


class RefusedError(Exception):
    """A ``required`` isolation part failed; the message goes in the report."""


class _Part:
    """One isolation part (fs or network): its mode and its first problem."""

    def __init__(self, name: str, mode: str) -> None:
        self.name = name
        self.mode = mode
        self.problem: str | None = None

    @property
    def intact(self) -> bool:
        """On, and nothing has failed so far."""
        return self.mode != "off" and self.problem is None

    def attempt(self, what: str, action: Callable[[], object]) -> None:
        if self.intact:
            try:
                action()
            except OSError as error:
                self._fail(f"{what} failed: {_describe(error)}")

    def verify(self, check: Callable[[], str | None]) -> None:
        if self.intact:
            try:
                problem = check()
            except OSError as error:
                problem = _describe(error)
            if problem is not None:
                self._fail(f"self-check failed: {problem}")

    def _fail(self, problem: str) -> None:
        self.problem = problem
        if self.mode == "required":
            raise RefusedError(f"{self.name} isolation is required but {problem}")


def isolate(spec: LaunchSpec, ops: Ops) -> tuple[bool, bool]:
    """Apply, then self-check: ``(fs_isolated, net_isolated)``; ``RefusedError``."""
    fs, net = _Part("fs", spec.fs), _Part("network", spec.net)
    if spec.platform == "linux":
        # Make the launcher non-dumpable before anything else, so a workload
        # sharing its namespace cannot read /proc/<pid>/mem or /proc/<pid>/fd.
        ops.prctl(_PR_SET_DUMPABLE, 0)
        net.attempt("bringing up lo", lambda: loopback_up(ops))
        fs.attempt("setting no_new_privs", lambda: ops.prctl(_PR_SET_NO_NEW_PRIVS, 1))
        fs.attempt("applying Landlock", lambda: landlock_restrict(ops, spec.writable))
    fs.verify(lambda: probe_write(ops, spec.probe_dir))
    net.verify(lambda: probe_connect(ops, spec.probe_port))
    return fs.intact, net.intact


def _say(message: str) -> int:
    print(f"launcher: {message}", file=sys.stderr, flush=True)
    return EXIT_REFUSED


def _child_fail(write_fd: int, tag: bytes, message: str) -> None:
    """Send one tagged, NUL-terminated record on the error pipe, best effort."""
    try:
        os.write(write_fd, tag + message.encode(errors="replace") + _RECORD_END)
    except OSError:
        pass


def _drop_privileges(ops: Ops, mode: str, errpipe_write: int) -> bool:
    """``drop_capabilities`` in the child; ``False`` when its failure refuses.

    Any exception counts as a failed drop: under ``required`` it sends an R
    record, otherwise a W record and the run goes on.
    """
    try:
        drop_capabilities(ops)
    except Exception as error:  # the child must refuse or record, never escape
        problem = f"dropping privileges failed: {_describe(error)}"
        if mode == "required":
            message = f"isolation is required but {problem}"
            _child_fail(errpipe_write, _CHILD_REFUSE, message)
            return False
        _child_fail(errpipe_write, _CHILD_WEAKENED, problem)
    return True


def _exec_child(
    argv: list[str], ops: Ops, *, drop_mode: str, errpipe_write: int
) -> NoReturn:
    """In the forked child: drop privilege (Linux), restore signals and exec.

    ``drop_mode`` is the strictest of the two modes: a failed drop under
    ``required`` exits 125 without exec. A failed exec reports and exits 127.
    The child always exits here and never returns into the parent's code.
    """
    code = EXIT_EXEC_FAILED
    try:
        if ops.platform == "linux" and not _drop_privileges(
            ops, drop_mode, errpipe_write
        ):
            code = EXIT_REFUSED
        else:
            ops.reset_signals()
            ops.execvp(argv[0], argv)
    except OSError as error:
        message = f"cannot execute {argv[0]!r}: {error.strerror}"
        _say(message)
        _child_fail(errpipe_write, _CHILD_EXEC, message)
    finally:
        ops.exit(code)


def _read_child_error(read_fd: int) -> bytes:
    """Drain the error pipe: the child's records, or empty on a clean exec."""
    chunks: list[bytes] = []
    while chunk := os.read(read_fd, 4096):
        chunks.append(chunk)
    return b"".join(chunks)


def run_workload(
    argv: list[str],
    ops: Ops,
    *,
    drop_mode: str,
    fs_isolated: bool,
    net_isolated: bool,
) -> tuple[dict[str, object], int]:
    """Fork, exec ``argv`` and ``wait4``: the report plus the launcher's exit code.

    The child's R record raises ``RefusedError``; a W record (its privilege
    drop failed, so the report could be forged) turns both flags false; an E
    record (it could not exec) becomes ``error``. The second return value is
    the launcher's own exit code (128+signal for a signalled workload), so the
    outer wrapper carries the workload's status.
    """
    ops.clear_handlers()
    read_fd, write_fd = ops.pipe()
    start = time.perf_counter_ns()
    pid = ops.fork()
    if pid == 0:
        _exec_child(argv, ops, drop_mode=drop_mode, errpipe_write=write_fd)
    try:
        os.close(write_fd)
        records = _read_child_error(read_fd).split(_RECORD_END)
    finally:
        os.close(read_fd)
    _, status, usage = ops.wait4(pid, 0)
    wall_ns = time.perf_counter_ns() - start
    exit_code = os.waitstatus_to_exitcode(status)
    error: str | None = None
    for record in records:
        tag, message = record[:1], record[1:].decode(errors="replace")
        if tag == _CHILD_REFUSE:
            raise RefusedError(message)
        if tag == _CHILD_WEAKENED:
            _say(f"{message}; the run continues under {drop_mode}")
            fs_isolated = net_isolated = False
        elif tag:
            error = message
    report: dict[str, object] = {
        "wall_ns": wall_ns,
        "utime": usage.ru_utime,
        "stime": usage.ru_stime,
        "maxrss": usage.ru_maxrss,
        "exit": exit_code,
        "fs_isolated": fs_isolated,
        "net_isolated": net_isolated,
        "error": error,
    }
    process_code = exit_code if exit_code >= 0 else 128 - exit_code
    return report, process_code


def _write_report(fd: int, report: dict[str, object]) -> int:
    data = json.dumps(report, sort_keys=True).encode()
    try:
        while data:
            data = data[os.write(fd, data) :]
    except OSError as error:
        return _say(f"cannot write the report: {error}")
    return 0


def main(argv: Sequence[str], ops: Ops | None = None) -> int:
    """Run one workload as the spec says; return the workload's own status.

    125 when refused (the report's ``error`` says why); a workload may exit 125
    itself, so only the report tells the two apart.
    """
    try:
        fd, spec, workload = parse_args(argv)
    except ValueError as error:
        return _say(str(error))
    try:
        os.set_inheritable(fd, False)  # the workload never inherits the report
    except OSError as error:
        return _say(f"report fd {fd} is not usable: {error}")
    ops = default_ops() if ops is None else ops
    try:
        if spec.platform != ops.platform:
            raise RefusedError(
                f"spec platform {spec.platform} does not match {ops.platform}"
            )
        fs_isolated, net_isolated = isolate(spec, ops)
        report, code = run_workload(
            workload,
            ops,
            drop_mode=strictest(spec.fs, spec.net),
            fs_isolated=fs_isolated,
            net_isolated=net_isolated,
        )
    except RefusedError as refused:
        _say(str(refused))
        flags = {"fs_isolated": False, "net_isolated": False}
        _write_report(fd, {**_REFUSED, **flags, "error": str(refused)})
        return EXIT_REFUSED
    written = _write_report(fd, report)
    return written or code


if __name__ == "__main__":
    os._exit(main(sys.argv[1:]))
