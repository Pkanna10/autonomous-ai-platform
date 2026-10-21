"""Measurement launcher, run by path: ``python -I -S launcher.py <fd> <spec> -- argv``.

STDLIB ONLY, without even ``typing`` or ``dataclasses`` at run time: exec
keeps the forking process's RSS high-water mark, so the launcher's size is
the floor of every ``peak_rss_bytes`` (about 8 MiB).

Linux, in order: ``lo`` up (inside ``unshare -rn``), ``PR_SET_NO_NEW_PRIVS``,
Landlock handling writes only (writable dirs and /dev/shm: every handled
right; /dev/null: write and truncate), then the self-check: ``O_CREAT|O_EXCL``
in the probe dir must fail with EACCES/EPERM and a connect to the parent's
127.0.0.1 probe listener must fail. On darwin ``sandbox-exec`` applied the
policy, so only the self-check runs. Under ``required`` a failed step writes
``error`` and exits 125 without exec; ``best_effort`` records false; ``off``
skips. Then fork/exec (127 in the child on failure), ``wait4``, and one JSON
``LaunchReport`` on the fd with raw ``ru_maxrss`` (the engine scales it).
Every OS call goes through ``Ops`` so tests run all of it in-process.
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
_PR_SET_NO_NEW_PRIVS = 38

# landlock(7). The syscall numbers are the same on x86_64 and aarch64.
_SYS_CREATE_RULESET, _SYS_ADD_RULE, _SYS_RESTRICT_SELF = 444, 445, 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_WRITE_FILE = 1 << 1
_WRITE_TREE = sum(1 << bit for bit in range(4, 13))  # REMOVE_DIR .. MAKE_SYM
_REFER = 1 << 13  # ABI 2
_TRUNCATE = 1 << 14  # ABI 3
_DEV_NULL = "/dev/null"
# A Landlock allow rule for POSIX shared memory, not a temp file.
_DEV_SHM = "/dev/shm"  # nosec B108
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


def landlock_rules(
    writable: Sequence[str], *, shm: str | None, abi: int
) -> list[tuple[str, int]]:
    """``(path, allowed mask)`` per rule: writable paths, /dev/shm, /dev/null."""
    full, file_only = handled_access_fs(abi), file_access_fs(abi)
    rules = [(path, full if os.path.isdir(path) else file_only) for path in writable]
    rules += [(shm, full)] if shm else []
    return [*rules, (_DEV_NULL, file_only)]


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
        open: Callable[[str, int, int], int],
        connect: Callable[[str, int], None],
        fork: Callable[[], int],
        execvp: Callable[[str, list[str]], NoReturn],
        wait4: Callable[[int, int], tuple[int, int, resource.struct_rusage]],
        exit: Callable[[int], NoReturn],
        reset_signals: Callable[[], None],
    ) -> None:
        self.platform = platform
        self.syscall = syscall
        self.ioctl = ioctl
        self.prctl = prctl
        self.open = open
        self.connect = connect
        self.fork = fork
        self.execvp = execvp
        self.wait4 = wait4
        self.exit = exit
        self.reset_signals = reset_signals


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


def default_ops() -> Ops:
    return Ops(
        platform=sys.platform,
        syscall=real_syscall,
        ioctl=fcntl.ioctl,
        prctl=real_prctl,
        open=os.open,
        connect=real_connect,
        fork=os.fork,
        execvp=os.execvp,
        wait4=os.wait4,
        exit=os._exit,
        reset_signals=restore_signals,
    )


def loopback_up(ops: Ops) -> None:
    """Set IFF_UP on ``lo``, keeping its other flags."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        fd = sock.fileno()
        current = ops.ioctl(fd, _SIOCGIFFLAGS, struct.pack(_IFREQ, b"lo", 0))
        flags = struct.unpack(_IFREQ, current)[1]
        ops.ioctl(fd, _SIOCSIFFLAGS, struct.pack(_IFREQ, b"lo", flags | _IFF_UP))


def landlock_restrict(ops: Ops, writable: Sequence[str], *, shm: str | None) -> None:
    """Confine this process's writes to the rules; raises ``OSError``."""
    abi = ops.syscall(_SYS_CREATE_RULESET, (None, 0, _CREATE_RULESET_VERSION))
    if abi < 1:
        raise OSError(errno.EOPNOTSUPP, f"Landlock ABI {abi} is not usable")
    attr = struct.pack("=Q", handled_access_fs(abi))
    ruleset = ops.syscall(_SYS_CREATE_RULESET, (attr, len(attr), 0))
    try:
        for path, mask in landlock_rules(writable, shm=shm, abi=abi):
            fd = ops.open(path, _O_PATH | os.O_CLOEXEC, 0)
            try:
                rule = struct.pack("=Qi", mask, fd)
                ops.syscall(_SYS_ADD_RULE, (ruleset, _RULE_PATH_BENEATH, rule, 0))
            finally:
                os.close(fd)
        ops.syscall(_SYS_RESTRICT_SELF, (ruleset, 0))
    finally:
        os.close(ruleset)


def _describe(error: OSError) -> str:
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
        net.attempt("bringing up lo", lambda: loopback_up(ops))
        fs.attempt("setting no_new_privs", lambda: ops.prctl(_PR_SET_NO_NEW_PRIVS, 1))
        shm = _DEV_SHM if os.path.isdir(_DEV_SHM) else None
        fs.attempt(
            "applying Landlock", lambda: landlock_restrict(ops, spec.writable, shm=shm)
        )
    fs.verify(lambda: probe_write(ops, spec.probe_dir))
    net.verify(lambda: probe_connect(ops, spec.probe_port))
    return fs.intact, net.intact


def _say(message: str) -> int:
    print(f"launcher: {message}", file=sys.stderr, flush=True)
    return EXIT_REFUSED


def _exec_child(argv: list[str], ops: Ops) -> NoReturn:
    """In the forked child: restore signals and exec; exit 127 if that fails."""
    try:
        ops.reset_signals()
        ops.execvp(argv[0], argv)
    except OSError as error:
        _say(f"cannot execute {argv[0]!r}: {error.strerror}")
    finally:
        ops.exit(EXIT_EXEC_FAILED)


def run_workload(argv: list[str], ops: Ops) -> dict[str, object]:
    """Fork, exec ``argv``, ``wait4`` it: wall time, rusage and exit code."""
    start = time.perf_counter_ns()
    pid = ops.fork()
    if pid == 0:
        _exec_child(argv, ops)
    _, status, usage = ops.wait4(pid, 0)
    wall_ns = time.perf_counter_ns() - start
    return {
        "wall_ns": wall_ns,
        "utime": usage.ru_utime,
        "stime": usage.ru_stime,
        "maxrss": usage.ru_maxrss,
        "exit": os.waitstatus_to_exitcode(status),
    }


def _write_report(fd: int, report: dict[str, object]) -> int:
    data = json.dumps(report, sort_keys=True).encode()
    try:
        while data:
            data = data[os.write(fd, data) :]
    except OSError as error:
        return _say(f"cannot write the report: {error}")
    return 0


def main(argv: Sequence[str], ops: Ops | None = None) -> int:
    """Run one workload as the spec says; exit 0, or 125 when refused."""
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
    except RefusedError as refused:
        _say(str(refused))
        flags = {"fs_isolated": False, "net_isolated": False}
        _write_report(fd, {**_REFUSED, **flags, "error": str(refused)})
        return EXIT_REFUSED
    report = run_workload(workload, ops)
    report |= {"fs_isolated": fs_isolated, "net_isolated": net_isolated, "error": None}
    return _write_report(fd, report)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
