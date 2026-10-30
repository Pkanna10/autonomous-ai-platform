"""The stdlib-only launcher: in-process with a fake OS, then for real.

In-process tests drive ``launcher.main`` through ``FakeOS``: every OS call
the launcher makes (syscall, ioctl, prctl, capget/capset, open, connect,
fork, execvp, wait4, waitid, the child-CPU read, the children listing, kill,
_exit, signal handling) is recorded and scripted, so the isolation order, the
fail-closed rules, the child's exec path and the stray drain are covered
without confining or forking the test process. The report fd is a real pipe.

The real tests run ``python -I -S launcher.py`` under ``unshare`` (user,
network, PID and IPC namespaces with a private ``/proc``) with Landlock on
this host. They skip when the host cannot sandbox, unless
``REQUIRE_NETWORK_SANDBOX=1`` or ``REQUIRE_FS_SANDBOX=1`` turns the skip
into a failure (CI sets both).
"""

from __future__ import annotations

import ast
import ctypes
import errno
import json
import os
import resource
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import types
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import NoReturn, get_type_hints

import pytest

from autonomous_ai_agents.common.config import IsolationMode
from autonomous_ai_agents.execution import launcher
from autonomous_ai_agents.execution.protocols import LaunchReport
from autonomous_ai_agents.execution.sandbox import (
    LAUNCHER_PATH,
    UNSHARE_ARGV,
    SandboxPolicy,
    child_env,
    launcher_argv,
)

ABI1 = 1 << 1 | sum(1 << bit for bit in range(4, 13))
REFER, TRUNCATE = 1 << 13, 1 << 14
NEVER_HANDLED = 1 << 0 | 1 << 2 | 1 << 3 | 1 << 15  # EXECUTE, READ_*, IOCTL_DEV
IFREQ = "16sH22x"
EACCES = OSError(errno.EACCES, "Permission denied")
ECONNREFUSED = OSError(errno.ECONNREFUSED, "Connection refused")
ENOENT = OSError(errno.ENOENT, "No such file or directory")
EPERM = OSError(errno.EPERM, "Operation not permitted")
USERNS_ROOT = (0x1FF, 0x1FF, 0)  # (effective, permitted, inheritable) as capget
NO_CAPS = (0, 0, 0)


# ---------------------------------------------------------------------------
# Landlock masks (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("abi", "handled", "file_mask"),
    [
        (1, ABI1, 1 << 1),
        (2, ABI1 | REFER, 1 << 1),
        (3, ABI1 | REFER | TRUNCATE, 1 << 1 | TRUNCATE),
        (7, ABI1 | REFER | TRUNCATE, 1 << 1 | TRUNCATE),
    ],
)
def test_landlock_masks_are_capped_by_the_abi(
    abi: int, handled: int, file_mask: int
) -> None:
    """
    GIVEN a Landlock ABI version
    WHEN the handled and the file masks are computed
    THEN writes are handled (REFER from ABI 2, TRUNCATE from ABI 3), and
        exec, reads and device ioctls never are
    """
    assert launcher.handled_access_fs(abi) == handled
    assert launcher.file_access_fs(abi) == file_mask
    assert launcher.handled_access_fs(abi) & NEVER_HANDLED == 0


def test_landlock_masks_refuse_abi_zero() -> None:
    """
    GIVEN ABI 0 (no Landlock)
    WHEN a mask is computed
    THEN ValueError
    """
    with pytest.raises(ValueError, match="ABI"):
        launcher.handled_access_fs(0)


def test_landlock_rules_cover_writable_dirs_and_dev_null(tmp_path: Path) -> None:
    """
    GIVEN a writable dir and a writable file
    WHEN the rules are listed for ABI 3
    THEN dirs get the full mask, files and /dev/null only write and truncate,
        and /dev/shm is never a rule (it is shared across runs)
    """
    target = tmp_path / "out.txt"
    target.write_text("")
    full, file_mask = launcher.handled_access_fs(3), launcher.file_access_fs(3)

    rules = launcher.landlock_rules([str(tmp_path), str(target)], abi=3)
    one = launcher.landlock_rules([str(tmp_path)], abi=3)

    assert rules == [
        (str(tmp_path), full),
        (str(target), file_mask),
        ("/dev/null", file_mask),
    ]
    assert one == [(str(tmp_path), full), ("/dev/null", file_mask)]
    assert not any(path == "/dev/shm" for path, _ in rules)


# ---------------------------------------------------------------------------
# The seccomp AF_UNIX filter (pure)
# ---------------------------------------------------------------------------


def _decode_bpf(program: bytes) -> list[tuple[int, int, int, int]]:
    assert len(program) % 8 == 0
    count = len(program) // 8
    return [struct.unpack("=HBBI", program[i * 8 : i * 8 + 8]) for i in range(count)]


@pytest.mark.parametrize(
    ("machine", "audit_arch", "socket_nr"),
    [("x86_64", 0xC000003E, 41), ("aarch64", 0xC00000B7, 198)],
)
def test_seccomp_filter_denies_only_socket_af_unix(
    machine: str, audit_arch: int, socket_nr: int
) -> None:
    """
    GIVEN a supported architecture
    WHEN the AF_UNIX seccomp filter is built
    THEN it checks the arch, allows every syscall but socket(), and returns
        EACCES only for socket() whose domain is AF_UNIX (1)
    """
    instructions = _decode_bpf(launcher.seccomp_filter(machine))

    assert instructions[0] == (0x20, 0, 0, 4)  # load arch
    assert instructions[1] == (0x15, 0, 6, audit_arch)  # wrong arch -> kill
    assert instructions[4] == (0x15, 0, 4, socket_nr)  # not socket() -> allow
    assert instructions[6] == (0x15, 0, 2, 1)  # not AF_UNIX -> allow
    assert instructions[7] == (0x06, 0, 0, 0x00050000 | errno.EACCES)  # EACCES
    assert instructions[8] == (0x06, 0, 0, 0x80000000)  # kill
    assert instructions[9] == (0x06, 0, 0, 0x7FFF0000)  # allow


def test_seccomp_filter_refuses_an_unsupported_architecture() -> None:
    """
    GIVEN an architecture with no known syscall numbers
    WHEN the filter is built
    THEN it raises OSError(EOPNOTSUPP), so the network self-check fails closed
    """
    with pytest.raises(OSError) as info:
        launcher.seccomp_filter("s390x")

    assert info.value.errno == errno.EOPNOTSUPP


# ---------------------------------------------------------------------------
# The fake OS
# ---------------------------------------------------------------------------


class ExitedError(Exception):
    """Raised by the fake ``_exit`` so the child path returns to the test."""

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


def rusage(
    utime: float = 0.25, stime: float = 0.125, maxrss: int = 9000
) -> resource.struct_rusage:
    return resource.struct_rusage((utime, stime, maxrss, *([0] * 13)))


_PRCTL_NAMES = {
    4: "set_dumpable",
    38: "no_new_privs",
    24: "capbset_drop",
    47: "cap_ambient",
    28: "securebits",
    36: "subreaper",
}


class FakeOS:
    """Records every OS call and replays scripted results."""

    def __init__(
        self,
        *,
        platform: str = "linux",
        abi: int = 7,
        fail: dict[str, Exception] | None = None,
        probe_error: OSError | None = EACCES,
        connect_error: OSError | None = ECONNREFUSED,
        unix_error: OSError | None = EACCES,
        pid: int = 4242,
        status: int = 0,
        exec_error: Exception = ENOENT,
        probe_redirect: Path | None = None,
        cap_last_cap: int | None = 2,
        capbset_einval_at: int | None = None,
        child_error: bytes | None = None,
        caps: tuple[int, int, int] = USERNS_ROOT,
        child_cpu: float | Exception = 0.5,
        reaps: Sequence[int] = (),
        children: Sequence[Sequence[int] | Exception] = (),
    ) -> None:
        self.platform = platform
        self.abi = abi
        self.fail = fail or {}
        self.probe_error = probe_error
        self.connect_error = connect_error
        self.unix_error = unix_error
        self.pid = pid
        self.status = status
        self.exec_error = exec_error
        self.probe_redirect = probe_redirect
        self._cap_last_cap = cap_last_cap
        self.capbset_einval_at = capbset_einval_at
        self.child_error = child_error
        self.caps = caps
        self.child_cpu = child_cpu
        self.reaps = list(reaps)  # wait4(-1): a pid, 0 (a live child), then ECHILD
        self.children = list(children)  # one listing per call, then []
        self.errpipe: tuple[int, int] | None = None
        self.calls: list[tuple[object, ...]] = []

    def names(self) -> list[str]:
        return [str(call[0]) for call in self.calls]

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise self.fail[name]

    def syscall(self, nr: int, args: tuple[int | bytes | None, ...]) -> int:
        name = {444: "create_ruleset", 445: "add_rule", 446: "restrict_self"}[nr]
        if nr == 444 and args[2] == 1:
            name = "abi"
        self.calls.append((name, *args))
        self._maybe_fail(name)
        if name == "abi":
            return self.abi
        if name == "create_ruleset":
            return os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        return 0

    def ioctl(self, fd: int, request: int, arg: bytes) -> bytes:
        name = {0x8913: "get_flags", 0x8914: "set_flags"}[request]
        self.calls.append((name, struct.unpack(IFREQ, arg)))
        self._maybe_fail(name)
        return struct.pack(IFREQ, b"lo", 0x48)

    def prctl(self, option: int, arg2: int) -> int:
        name = _PRCTL_NAMES.get(option, f"prctl_{option}")
        self.calls.append((name, option, arg2))
        if name == "capbset_drop" and self.capbset_einval_at is not None:
            if arg2 >= self.capbset_einval_at:
                raise OSError(errno.EINVAL, "Invalid argument")
        self._maybe_fail(name)
        return 0

    def capset(self, header: bytes, data: bytes) -> int:
        self.calls.append(("capset", header, data))
        self._maybe_fail("capset")
        return 0

    def capget(self) -> tuple[int, int, int]:
        self.calls.append(("capget",))
        self._maybe_fail("capget")
        return self.caps

    def cap_last_cap(self) -> int | None:
        return self._cap_last_cap

    def clear_handlers(self) -> None:
        self.calls.append(("clear_handlers",))

    def pipe(self) -> tuple[int, int]:
        read, write = os.pipe()
        self.errpipe = (read, write)
        if self.child_error is not None:
            os.write(write, self.child_error)
        return read, write

    def open(self, path: str, flags: int, mode: int) -> int:
        if not flags & os.O_CREAT:
            self.calls.append(("open_path", path))
            return os.open(path, flags, mode)
        self.calls.append(("probe_write", path))
        if self.probe_error is not None:
            raise self.probe_error
        if self.probe_redirect is not None:
            path = str(self.probe_redirect)
        return os.open(path, flags, mode)

    def connect(self, host: str, port: int) -> None:
        self.calls.append(("connect", host, port))
        if self.connect_error is not None:
            raise self.connect_error

    def seccomp(self) -> None:
        self.calls.append(("seccomp",))
        self._maybe_fail("seccomp")

    def unix_socket(self) -> None:
        self.calls.append(("unix_socket",))
        if self.unix_error is not None:
            raise self.unix_error

    def fork(self) -> int:
        self.calls.append(("fork",))
        return self.pid

    def execvp(self, file: str, args: list[str]) -> NoReturn:
        self.calls.append(("execvp", file, tuple(args)))
        raise self.exec_error

    def wait4(self, pid: int, options: int) -> tuple[int, int, resource.struct_rusage]:
        if pid > 0:
            self.calls.append(("wait4", pid, options))
            return pid, self.status, rusage()
        self.calls.append(("reap_any", pid, options))
        if not self.reaps:
            raise ChildProcessError(errno.ECHILD, "No child processes")
        found = self.reaps.pop(0)
        return found, 0, rusage(0.0625, 0.0625) if found else rusage(0.0, 0.0, 0)

    def waitid(self, pid: int) -> None:
        self.calls.append(("waitid", pid))

    def read_child_cpu(self, pid: int) -> float:
        self.calls.append(("child_cpu", pid))
        if isinstance(self.child_cpu, Exception):
            raise self.child_cpu
        return self.child_cpu

    def list_children(self) -> list[int]:
        self.calls.append(("children",))
        found = self.children.pop(0) if self.children else []
        if isinstance(found, Exception):
            raise found
        return list(found)

    def kill(self, pid: int, signum: int) -> None:
        self.calls.append(("kill", pid, signum))
        self._maybe_fail("kill")

    def exit(self, code: int) -> NoReturn:
        self.calls.append(("exit", code))
        raise ExitedError(code)

    def reset_signals(self) -> None:
        self.calls.append(("reset_signals",))

    def ops(self) -> launcher.Ops:
        return launcher.Ops(
            platform=self.platform,
            syscall=self.syscall,
            ioctl=self.ioctl,
            prctl=self.prctl,
            capset=self.capset,
            capget=self.capget,
            cap_last_cap=self.cap_last_cap,
            open=self.open,
            connect=self.connect,
            seccomp=self.seccomp,
            unix_socket=self.unix_socket,
            pipe=self.pipe,
            fork=self.fork,
            execvp=self.execvp,
            wait4=self.wait4,
            waitid=self.waitid,
            child_cpu=self.read_child_cpu,
            children=self.list_children,
            kill=self.kill,
            exit=self.exit,
            reset_signals=self.reset_signals,
            clear_handlers=self.clear_handlers,
        )

    def errpipe_records(self) -> list[bytes]:
        """What the child wrote on the error pipe, split into its records."""
        assert self.errpipe is not None
        os.close(self.errpipe[1])
        data = b""
        while chunk := os.read(self.errpipe[0], 65536):
            data += chunk
        os.close(self.errpipe[0])
        self.errpipe = None
        return [record for record in data.split(b"\0") if record]

    def close_errpipe(self) -> None:
        """Close the internal error pipe a child-path test did not drain away."""
        for fd in self.errpipe or ():
            try:
                os.close(fd)
            except OSError:
                pass


class Dirs:
    def __init__(self, tmp_path: Path) -> None:
        self.wt = tmp_path / "wt"
        self.scratch = tmp_path / "scratch"
        self.probe = tmp_path / "probe"
        for path in (self.wt, self.scratch, self.probe):
            path.mkdir()


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    return Dirs(tmp_path)


def spec_json(
    dirs: Dirs,
    *,
    fs: str = "required",
    net: str = "required",
    platform: str = "linux",
    port: int | None = 40000,
) -> str:
    return json.dumps(
        {
            "version": 1,
            "platform": platform,
            "fs": fs,
            "net": net,
            "writable": [str(dirs.wt), str(dirs.scratch)],
            "probe_dir": str(dirs.probe),
            "probe_port": port,
        }
    )


@pytest.fixture
def pipe() -> Iterator[tuple[int, int]]:
    read, write = os.pipe()
    yield read, write
    for fd in (read, write):
        try:
            os.close(fd)
        except OSError:
            pass


def read_report(read_fd: int) -> dict[str, object]:
    data = b""
    while chunk := os.read(read_fd, 65536):
        data += chunk
    loaded = json.loads(data)
    assert isinstance(loaded, dict)
    return loaded


def run_main(
    fake: FakeOS, pipe: tuple[int, int], spec: str, *argv: str
) -> tuple[int, dict[str, object]]:
    read, write = pipe
    code = launcher.main(
        [str(write), spec, "--", *(argv or ("prog", "arg"))], fake.ops()
    )
    os.close(write)
    return code, read_report(read)


# ---------------------------------------------------------------------------
# In-process: the happy paths
# ---------------------------------------------------------------------------


def test_linux_applies_isolation_in_order_then_runs_and_reports(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a Linux spec with both modes required and Landlock ABI 7
    WHEN the launcher runs a workload that exits 3
    THEN the launcher makes itself non-dumpable, lo comes up, the AF_UNIX
        seccomp filter, no_new_privs, Landlock (writable dirs and /dev/null
        only, never /dev/shm), the write probe, the connect probe, the AF_UNIX
        probe and the clearing of Python's signal handlers
        (so a workload cannot kill PID 1 with SIGINT) run in that order before
        the fork, the launcher becomes the child subreaper; after the fork it
        waits for the exit without reaping, reads the child CPU, reaps, then
        drains strays (none); the report carries the raw rusage, exit 3, both
        flags true, the child CPU and 0 strays; the launcher exits with the
        workload's status (3)
    """
    fake = FakeOS(status=3 << 8)

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == 3
    assert report == {
        "wall_ns": report["wall_ns"],
        "utime": 0.25,
        "stime": 0.125,
        "maxrss": 9000,
        "exit": 3,
        "fs_isolated": True,
        "net_isolated": True,
        "error": None,
        "child_cpu": 0.5,
        "strays": 0,
    }
    assert isinstance(report["wall_ns"], int) and report["wall_ns"] >= 0
    assert fake.names() == [
        "set_dumpable",
        "get_flags",
        "set_flags",
        "seccomp",
        "no_new_privs",
        "abi",
        "create_ruleset",
        *["open_path", "add_rule"] * 3,
        "restrict_self",
        "probe_write",
        "connect",
        "unix_socket",
        "clear_handlers",
        "subreaper",
        "fork",
        "waitid",
        "child_cpu",
        "wait4",
        "reap_any",
    ]


def test_linux_steps_send_the_spec_values(dirs: Dirs, pipe: tuple[int, int]) -> None:
    """
    GIVEN a Linux spec with both modes required and Landlock ABI 2
    WHEN the launcher runs
    THEN lo gets its old flags plus IFF_UP, prctl sets NO_NEW_PRIVS, the
        ruleset handles the ABI 2 mask, each rule carries its mask, the
        probe connects to 127.0.0.1:<port> and wait4 waits for the child
    """
    fake = FakeOS(abi=2)

    run_main(fake, pipe, spec_json(dirs, port=40000))

    calls = {call[0]: call for call in fake.calls}
    assert calls["set_dumpable"] == ("set_dumpable", 4, 0)
    assert calls["get_flags"][1] == (b"lo" + b"\0" * 14, 0)
    assert calls["set_flags"][1] == (b"lo" + b"\0" * 14, 0x48 | 1)
    assert calls["no_new_privs"] == ("no_new_privs", 38, 1)
    assert calls["abi"] == ("abi", None, 0, 1)
    assert calls["create_ruleset"][1:] == (struct.pack("=Q", ABI1 | REFER), 8, 0)
    rules = [call for call in fake.calls if call[0] == "add_rule"]
    attrs = [call[3] for call in rules]
    masks = [struct.unpack("=Qi", attr)[0] for attr in attrs if isinstance(attr, bytes)]
    assert len(masks) == len(rules)
    assert [call[2] for call in rules] == [1] * len(rules)
    assert masks[:2] == [ABI1 | REFER] * 2
    assert masks[-1] == 1 << 1
    assert calls["restrict_self"][2:] == (0,)
    assert calls["connect"] == ("connect", "127.0.0.1", 40000)
    assert calls["wait4"] == ("wait4", 4242, 0)
    assert calls["subreaper"] == ("subreaper", 36, 1)
    assert calls["waitid"] == ("waitid", 4242)
    assert calls["child_cpu"] == ("child_cpu", 4242)
    assert calls["reap_any"] == ("reap_any", -1, os.WNOHANG)


def test_darwin_runs_only_the_self_checks(dirs: Dirs, pipe: tuple[int, int]) -> None:
    """
    GIVEN a darwin spec with both modes required (sandbox-exec applied them)
    WHEN the probe write and connect fail with EPERM
    THEN no Linux step runs, both flags are true, and the child CPU and
        strays are null (D3: no route proven on darwin yet)
    """
    eperm = OSError(errno.EPERM, "Operation not permitted")
    fake = FakeOS(platform="darwin", probe_error=eperm, connect_error=eperm)

    code, report = run_main(fake, pipe, spec_json(dirs, platform="darwin"))

    assert code == 0
    assert (report["fs_isolated"], report["net_isolated"]) == (True, True)
    assert (report["child_cpu"], report["strays"]) == (None, None)
    assert fake.names() == ["probe_write", "connect", "clear_handlers", "fork", "wait4"]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_modes_off_skip_every_isolation_step(
    dirs: Dirs, pipe: tuple[int, int], platform: str
) -> None:
    """
    GIVEN a spec with both modes off
    WHEN the launcher runs
    THEN it only clears the signal handlers, forks and waits (Linux still makes
        itself non-dumpable first and the child subreaper, reads the child
        CPU and drains strays), and both flags are false
    """
    fake = FakeOS(platform=platform)

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="off", net="off", platform=platform, port=None)
    )

    assert code == 0
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    linux = platform == "linux"
    dumpable = ["set_dumpable"] if linux else []
    after = ["subreaper", "fork", "waitid", "child_cpu", "wait4", "reap_any"]
    assert fake.names() == [
        *dumpable,
        "clear_handlers",
        *(after if linux else ["fork", "wait4"]),
    ]


def test_a_signalled_workload_reports_the_negative_signal(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a workload killed by SIGKILL
    WHEN the launcher reports
    THEN the report exit is -9 (os.waitstatus_to_exitcode), and the launcher
        itself exits 128+9 == 137 so the outer wrapper carries the signal
    """
    code, report = run_main(FakeOS(status=signal.SIGKILL), pipe, spec_json(dirs))

    assert (code, report["exit"]) == (137, -9)


def test_report_keys_match_the_launch_report_contract(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the engine's LaunchReport TypedDict
    WHEN the launcher writes a report
    THEN the keys are exactly the TypedDict's
    """
    _, report = run_main(FakeOS(), pipe, spec_json(dirs))

    assert set(report) == set(get_type_hints(LaunchReport))


# ---------------------------------------------------------------------------
# In-process: the child-process tripwire (D62, N0c)
# ---------------------------------------------------------------------------


def test_strays_are_reaped_counted_and_the_live_ones_killed_first(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the workload left an exited stray (77), then live strays (90, 91)
        that the listing names, and 91 had already gone (ProcessLookupError)
    WHEN the launcher drains after reaping the workload
    THEN 77 is counted, both live ones are SIGKILLed and only then waited for
        blocking, every stray is counted once and its CPU joins child_cpu
    """
    fake = FakeOS(
        reaps=[77, 0, 90, 91],
        children=[[90, 91]],
        fail={"kill": ProcessLookupError(errno.ESRCH, "No such process")},
    )

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == 0
    assert (report["strays"], report["child_cpu"]) == (3, 0.5 + 3 * 0.125)
    drain = [c for c in fake.calls if c[0] in {"reap_any", "children", "kill"}]
    assert drain == [
        ("reap_any", -1, os.WNOHANG),
        ("reap_any", -1, os.WNOHANG),
        ("children",),
        ("kill", 90, signal.SIGKILL),
        ("kill", 91, signal.SIGKILL),
        ("reap_any", -1, 0),
        ("reap_any", -1, os.WNOHANG),
        ("reap_any", -1, os.WNOHANG),
    ]


@pytest.mark.parametrize(
    "listing", [[], OSError(errno.EACCES, "denied")], ids=["none", "error"]
)
def test_a_live_stray_it_cannot_name_counts_and_is_never_waited_for(
    dirs: Dirs, pipe: tuple[int, int], listing: list[int] | Exception
) -> None:
    """
    GIVEN a live stray (wait4 gives 0) that the children listing does not
        name, or the listing fails
    WHEN the launcher drains
    THEN it counts one stray and stops: no kill, no blocking wait
    """
    fake = FakeOS(reaps=[0], children=[listing])

    _, report = run_main(fake, pipe, spec_json(dirs))

    assert report["strays"] == 1
    assert "kill" not in fake.names()
    assert ("reap_any", -1, 0) not in fake.calls


def test_the_drain_stops_at_the_stray_cap(
    dirs: Dirs, pipe: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN more exited strays than the cap (a fork bomb's leftovers)
    WHEN the launcher drains
    THEN it stops at the cap; the count already flags the run
    """
    monkeypatch.setattr(launcher, "STRAYS_MAX", 3)
    fake = FakeOS(reaps=[50, 51, 52, 53, 54])

    _, report = run_main(fake, pipe, spec_json(dirs))

    assert report["strays"] == 3
    assert fake.names().count("reap_any") == 3


def test_an_unreadable_child_cpu_is_null_and_the_workload_still_reaped(
    dirs: Dirs, pipe: tuple[int, int], capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN /proc/<pid>/stat cannot be read for the exited workload
    WHEN the launcher reports
    THEN child_cpu is null (procrun refuses such a Linux run), the workload is
        still reaped and the strays drained, and stderr says why
    """
    fake = FakeOS(child_cpu=OSError(errno.ENOENT, "gone"))

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == 0
    assert (report["child_cpu"], report["strays"]) == (None, 0)
    assert fake.names()[-4:] == ["waitid", "child_cpu", "wait4", "reap_any"]
    assert "cannot read the workload's child CPU" in capsys.readouterr().err


def test_a_failed_subreaper_refuses_before_the_fork(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN prctl(PR_SET_CHILD_SUBREAPER) fails
    WHEN the launcher runs, in any mode
    THEN it refuses with exit 125 and a null child CPU and strays, no fork
    """
    fake = FakeOS(fail={"subreaper": OSError(errno.EINVAL, "Invalid argument")})

    code, report = run_main(fake, pipe, spec_json(dirs, fs="off", net="off", port=None))

    assert code == 125
    assert "child subreaper" in str(report["error"])
    assert (report["child_cpu"], report["strays"]) == (None, None)
    assert "fork" not in fake.names()


@pytest.mark.parametrize(
    ("comm", "cpu"), [(b"python3", 0.42), (b"a) b (c", 0.42), (b")", 0.42)]
)
def test_stat_child_cpu_reads_fields_16_and_17_past_any_comm(
    comm: bytes, cpu: float
) -> None:
    """
    GIVEN a /proc/<pid>/stat line whose comm may hold ") " and spaces
    WHEN the child CPU is read at 100 ticks per second
    THEN it is (cutime + cstime) / ticks: fields 16 and 17, counted from
        the last ")"
    """
    fields = [b"Z", b"1", *[b"0"] * 9, b"7", b"8", b"30", b"12", b"20", b"0"]
    line = b"42 (" + comm + b") " + b" ".join(fields) + b"\n"

    assert launcher.stat_child_cpu(line, 100) == pytest.approx(cpu)


@pytest.mark.parametrize(
    ("line", "ticks"),
    [(b"42 (x) Z 1 2", 100), (b"no paren", 100), (b"42 (x) " + b"a " * 20, 100),
     (b"42 (x) " + b"0 " * 20, 0)],
)  # fmt: skip
def test_stat_child_cpu_refuses_a_malformed_line(line: bytes, ticks: int) -> None:
    with pytest.raises(ValueError):
        launcher.stat_child_cpu(line, ticks)


# ---------------------------------------------------------------------------
# In-process: fail closed under required, record under best_effort
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "part", "words"),
    [
        ("get_flags", "network", "bringing up lo"),
        ("set_flags", "network", "bringing up lo"),
        ("seccomp", "network", "blocking AF_UNIX sockets"),
        ("no_new_privs", "fs", "no_new_privs"),
        ("abi", "fs", "Landlock"),
        ("create_ruleset", "fs", "Landlock"),
        ("add_rule", "fs", "Landlock"),
        ("restrict_self", "fs", "Landlock"),
    ],
)
def test_a_failed_required_step_refuses_without_exec(
    dirs: Dirs, pipe: tuple[int, int], step: str, part: str, words: str
) -> None:
    """
    GIVEN a Linux spec with both modes required and one step failing
    WHEN the launcher runs
    THEN it writes an error report and exits 125 without forking
    """
    fake = FakeOS(fail={step: OSError(errno.ENOSYS, "Function not implemented")})

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == launcher.EXIT_REFUSED == 125
    error = report["error"]
    assert isinstance(error, str)
    assert f"{part} isolation is required" in error
    assert words in error and "Function not implemented" in error
    assert report["exit"] == 125
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert "fork" not in fake.names()


def test_landlock_abi_below_one_is_a_failed_step(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a kernel reporting Landlock ABI 0
    WHEN fs is required
    THEN the launcher refuses with exit 125
    """
    code, report = run_main(FakeOS(abi=0), pipe, spec_json(dirs, net="off"))

    assert code == 125
    assert "ABI 0" in str(report["error"])


def test_a_missing_writable_dir_is_a_failed_landlock_step(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a writable dir that does not exist
    WHEN fs is required
    THEN opening it for the rule fails, no restrict_self runs, exit 125
    """
    shutil.rmtree(dirs.scratch)
    fake = FakeOS()

    code, report = run_main(fake, pipe, spec_json(dirs, net="off"))

    assert code == 125
    assert "Landlock" in str(report["error"])
    assert "restrict_self" not in fake.names()


def test_required_network_failure_stops_before_the_fs_steps(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN lo cannot be brought up and the network is required
    WHEN the launcher runs
    THEN no fs step runs after the failure
    """
    fake = FakeOS(fail={"get_flags": OSError(errno.EPERM, "denied")})

    code, _ = run_main(fake, pipe, spec_json(dirs))

    assert code == 125
    assert fake.names() == ["set_dumpable", "get_flags"]


def test_best_effort_failures_record_false_and_still_run(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN both modes best_effort, lo failing and no_new_privs failing
    WHEN the launcher runs
    THEN neither Landlock nor a self-check runs, both flags are false, the
        report has no error and the workload still runs
    """
    fake = FakeOS(
        fail={
            "set_flags": OSError(errno.EPERM, "x"),
            "no_new_privs": OSError(errno.EINVAL, "y"),
        }
    )

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="best_effort", net="best_effort")
    )

    assert code == 0
    assert report["error"] is None
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert fake.names() == [
        "set_dumpable",
        "get_flags",
        "set_flags",
        "no_new_privs",
        "clear_handlers",
        "subreaper",
        "fork",
        "waitid",
        "child_cpu",
        "wait4",
        "reap_any",
    ]


def test_a_probe_write_that_succeeds_is_not_isolation(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the Landlock steps reported success but the probe write succeeds
    WHEN fs is required
    THEN exit 125 naming the self-check, and the probe file is removed
    """
    fake = FakeOS(probe_error=None)

    code, report = run_main(fake, pipe, spec_json(dirs, net="off"))

    assert code == 125
    assert "self-check failed" in str(report["error"])
    assert "succeeded" in str(report["error"])
    assert list(dirs.probe.iterdir()) == []


def test_a_probe_write_that_succeeds_under_best_effort_is_recorded(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN fs best_effort and a probe write that succeeds
    WHEN the launcher runs
    THEN fs_isolated is false and the workload runs
    """
    fake = FakeOS(probe_error=None)

    code, report = run_main(fake, pipe, spec_json(dirs, fs="best_effort", net="off"))

    assert (code, report["fs_isolated"], report["error"]) == (0, False, None)
    assert "fork" in fake.names()


@pytest.mark.parametrize(
    "probe_error",
    [OSError(errno.ENOENT, "No such file"), OSError(errno.EEXIST, "File exists")],
)
def test_a_probe_write_failing_for_another_reason_proves_nothing(
    dirs: Dirs, pipe: tuple[int, int], probe_error: OSError
) -> None:
    """
    GIVEN the probe write fails with neither EACCES nor EPERM
    WHEN fs is required
    THEN that is not proof of confinement: exit 125
    """
    code, report = run_main(
        FakeOS(probe_error=probe_error), pipe, spec_json(dirs, net="off")
    )

    assert code == 125
    assert "does not prove isolation" in str(report["error"])


def test_a_probe_cleanup_error_counts_as_a_failed_self_check(
    dirs: Dirs, pipe: tuple[int, int], tmp_path: Path
) -> None:
    """
    GIVEN a probe write that succeeds but whose file cannot be removed
    WHEN fs is required
    THEN the self-check fails closed with the OS error
    """
    fake = FakeOS(probe_error=None, probe_redirect=tmp_path / "elsewhere")

    code, report = run_main(fake, pipe, spec_json(dirs, net="off"))

    assert code == 125
    assert "self-check failed" in str(report["error"])
    assert "No such file or directory" in str(report["error"])


@pytest.mark.parametrize(
    ("connect_error", "port", "words"),
    [
        (None, 40000, "succeeded"),
        (TimeoutError("timed out"), 40000, "does not prove isolation"),
        (OSError(errno.ECONNRESET, "reset"), 40000, "does not prove isolation"),
        (OSError(errno.ECONNREFUSED, "refused"), None, "no probe port"),
    ],
)
def test_the_connect_self_check_fails_closed(
    dirs: Dirs,
    pipe: tuple[int, int],
    connect_error: OSError | None,
    port: int | None,
    words: str,
) -> None:
    """
    GIVEN a connect that succeeds, times out, fails oddly, or no port
    WHEN the network is required
    THEN exit 125 with the reason, and no fork
    """
    fake = FakeOS(connect_error=connect_error)

    code, report = run_main(fake, pipe, spec_json(dirs, port=port))

    assert code == 125
    assert words in str(report["error"])
    assert "fork" not in fake.names()


@pytest.mark.parametrize(
    "blocked",
    [errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM],
)
def test_blocked_connects_prove_network_isolation(
    dirs: Dirs, pipe: tuple[int, int], blocked: int
) -> None:
    """
    GIVEN the probe connect fails with a blocking errno
    WHEN the network is required
    THEN net_isolated is true
    """
    fake = FakeOS(connect_error=OSError(blocked, os.strerror(blocked)))

    code, report = run_main(fake, pipe, spec_json(dirs, fs="off"))

    assert (code, report["net_isolated"]) == (0, True)


def test_a_connect_that_succeeds_under_best_effort_is_recorded(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the network best_effort and a probe connect that succeeds
    WHEN the launcher runs
    THEN net_isolated is false and the workload runs
    """
    fake = FakeOS(connect_error=None)

    code, report = run_main(fake, pipe, spec_json(dirs, net="best_effort", fs="off"))

    assert (code, report["net_isolated"], report["error"]) == (0, False, None)


def test_a_best_effort_seccomp_failure_records_false_and_still_runs(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the network best_effort and the seccomp install failing
    WHEN the launcher runs
    THEN net_isolated is false, there is no error and the workload still runs
    """
    fake = FakeOS(fail={"seccomp": OSError(errno.ENOSYS, "no seccomp")})

    code, report = run_main(fake, pipe, spec_json(dirs, net="best_effort", fs="off"))

    assert (code, report["net_isolated"], report["error"]) == (0, False, None)
    assert "fork" in fake.names()
    assert "unix_socket" not in fake.names()


@pytest.mark.parametrize(
    ("unix_error", "words"),
    [
        (None, "could be created"),
        (OSError(errno.ENOSYS, "no socket"), "does not prove isolation"),
    ],
)
def test_the_unix_self_check_fails_closed(
    dirs: Dirs, pipe: tuple[int, int], unix_error: OSError | None, words: str
) -> None:
    """
    GIVEN the seccomp install reported success but an AF_UNIX socket can still
        be made, or the probe fails for another reason
    WHEN the network is required
    THEN the run is refused with exit 125 and no fork
    """
    fake = FakeOS(unix_error=unix_error)

    code, report = run_main(fake, pipe, spec_json(dirs, fs="off"))

    assert code == 125
    assert words in str(report["error"])
    assert "fork" not in fake.names()


def test_a_reachable_unix_socket_under_best_effort_is_recorded(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the network best_effort and an AF_UNIX socket that can be created
    WHEN the launcher runs
    THEN net_isolated is false and the workload still runs
    """
    fake = FakeOS(unix_error=None)

    code, report = run_main(fake, pipe, spec_json(dirs, net="best_effort", fs="off"))

    assert (code, report["net_isolated"], report["error"]) == (0, False, None)
    assert "fork" in fake.names()


def test_the_unix_self_check_is_skipped_on_darwin(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a darwin spec (sandbox-exec's (deny network*) covers AF_UNIX connect)
    WHEN the launcher runs
    THEN neither the seccomp install nor the AF_UNIX probe runs
    """
    eperm = OSError(errno.EPERM, "Operation not permitted")
    fake = FakeOS(platform="darwin", probe_error=eperm, connect_error=eperm)

    code, report = run_main(fake, pipe, spec_json(dirs, platform="darwin"))

    assert (code, report["net_isolated"]) == (0, True)
    assert "seccomp" not in fake.names() and "unix_socket" not in fake.names()


def test_a_spec_for_another_platform_is_refused(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a darwin spec on a Linux host
    WHEN the launcher runs
    THEN exit 125 before any isolation step (no wrong-platform syscalls)
    """
    fake = FakeOS(platform="linux")

    code, report = run_main(fake, pipe, spec_json(dirs, platform="darwin"))

    assert code == 125
    assert "does not match" in str(report["error"])
    assert fake.calls == []


# ---------------------------------------------------------------------------
# In-process: the child after fork
# ---------------------------------------------------------------------------


def test_the_child_resets_signals_execs_and_exits_127_on_failure(
    dirs: Dirs, pipe: tuple[int, int], capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN fork returns 0 (we are the child) and exec fails
    WHEN the launcher continues in the child
    THEN it drops privilege, resets signals, execs argv, says why it failed,
        tells the parent on the error pipe and exits 127 without a report
    """
    fake = FakeOS(pid=0)
    read, write = pipe

    with pytest.raises(ExitedError) as exited:
        launcher.main([str(write), spec_json(dirs), "--", "/no/such", "x"], fake.ops())

    assert exited.value.code == launcher.EXIT_EXEC_FAILED == 127
    assert fake.names()[-3:] == ["reset_signals", "execvp", "exit"]
    assert {"fork", "capset", "no_new_privs"} <= set(fake.names())
    assert ("execvp", "/no/such", ("/no/such", "x")) in fake.calls
    assert "cannot execute '/no/such'" in capsys.readouterr().err
    assert fake.errpipe is not None
    assert os.read(fake.errpipe[0], 65536).startswith(b"Ecannot execute '/no/such'")
    fake.close_errpipe()
    os.set_blocking(read, False)
    with pytest.raises(BlockingIOError):
        os.read(read, 1)


def test_the_child_exits_127_even_when_a_non_os_error_escapes(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN fork returns 0 and exec raises something other than OSError
    WHEN the launcher continues in the child
    THEN the child still exits 127 rather than returning into the parent code
    """
    fake = FakeOS(pid=0, exec_error=ValueError("embedded null byte"))

    with pytest.raises(ExitedError) as exited:
        launcher.main([str(pipe[1]), spec_json(dirs), "--", "prog"], fake.ops())

    assert exited.value.code == 127
    fake.close_errpipe()


# ---------------------------------------------------------------------------
# In-process: dropping privilege in the child (anti-forge hardening)
# ---------------------------------------------------------------------------


def test_drop_capabilities_sheds_the_bounding_ambient_securebits_and_caps() -> None:
    """
    GIVEN a kernel whose highest capability is 2
    WHEN the child drops privilege
    THEN it sets no_new_privs, drops caps 0..2, clears the ambient set, sets the
        locked securebits and capsets to empty, in that order
    """
    fake = FakeOS(cap_last_cap=2)

    launcher.drop_capabilities(fake.ops())

    assert fake.names() == [
        "no_new_privs",
        "capbset_drop",
        "capbset_drop",
        "capbset_drop",
        "cap_ambient",
        "securebits",
        "capset",
    ]
    dropped = [call[2] for call in fake.calls if call[0] == "capbset_drop"]
    assert dropped == [0, 1, 2]
    assert ("no_new_privs", 38, 1) in fake.calls
    assert ("cap_ambient", 47, 4) in fake.calls
    assert ("securebits", 28, 0x2F) in fake.calls
    assert ("capset", launcher._CAP_HEADER, launcher._CAP_DATA) in fake.calls


def test_drop_capabilities_loops_until_einval_when_cap_last_cap_is_unknown() -> None:
    """
    GIVEN cap_last_cap is unreadable and PR_CAPBSET_DROP gives EINVAL at cap 5
    WHEN the child drops privilege
    THEN it drops caps 0..4, probes cap 5 (the EINVAL that ends the set) and
        then finishes with the ambient, securebits and capset steps
    """
    fake = FakeOS(cap_last_cap=None, capbset_einval_at=5)

    launcher.drop_capabilities(fake.ops())

    attempted = [call[2] for call in fake.calls if call[0] == "capbset_drop"]
    assert attempted == [0, 1, 2, 3, 4, 5]
    assert fake.names()[-3:] == ["cap_ambient", "securebits", "capset"]


@pytest.mark.parametrize(
    ("error", "caps"),
    [
        (EPERM, USERNS_ROOT),  # caps held but no CAP_SETPCAP: a real failure
        (EPERM, (0, 1, 0)),  # one permitted cap is enough to refuse
        (OSError(errno.EINVAL, "Invalid argument"), NO_CAPS),  # not EPERM
    ],
)
def test_drop_capabilities_reraises_a_real_bounding_set_error(
    error: OSError, caps: tuple[int, int, int]
) -> None:
    """
    GIVEN PR_CAPBSET_DROP fails while capabilities are held, or fails with
        anything but EPERM (with a known cap_last_cap)
    WHEN the child drops privilege
    THEN the OSError propagates: it is neither an EINVAL end-of-set nor the
        harmless EPERM of a process that holds no capability
    """
    fake = FakeOS(fail={"capbset_drop": error}, caps=caps)

    with pytest.raises(OSError) as raised:
        launcher.drop_capabilities(fake.ops())

    assert raised.value is error
    assert ("capget" in fake.names()) is (error.errno == errno.EPERM)
    assert "capset" not in fake.names()


@pytest.mark.parametrize("caps", [NO_CAPS, (0, 0, 0x4)])
def test_drop_capabilities_accepts_eperm_when_no_capability_is_held(
    caps: tuple[int, int, int],
) -> None:
    """
    GIVEN an unprivileged launcher outside any user namespace: PR_CAPBSET_DROP
        gives EPERM (no CAP_SETPCAP) and capget shows no effective or permitted
        capability (an inheritable bit alone grants nothing under no_new_privs)
    WHEN the child drops privilege
    THEN that is not a failure: it skips the bounding set and the securebits
        (both need CAP_SETPCAP), still clears the ambient set and capsets to
        empty (which clears the inheritable set), and raises nothing
    """
    fake = FakeOS(fail={"capbset_drop": EPERM}, caps=caps)

    launcher.drop_capabilities(fake.ops())

    assert fake.names() == [
        "no_new_privs",
        "capbset_drop",
        "capget",
        "cap_ambient",
        "capset",
    ]
    assert ("capset", launcher._CAP_HEADER, launcher._CAP_DATA) in fake.calls


@pytest.mark.parametrize(
    ("fs", "net"),
    [
        ("required", "required"),
        ("off", "required"),
        ("off", "best_effort"),
        ("best_effort", "off"),
        ("off", "off"),
    ],
)
def test_the_linux_child_drops_privilege_before_exec_in_every_mode(
    dirs: Dirs, pipe: tuple[int, int], fs: str, net: str
) -> None:
    """
    GIVEN fork returns 0 on Linux, in any combination of modes (the drop guards
        the report channel, which every mode relies on, not the filesystem)
    WHEN the launcher continues in the child
    THEN it sheds the bounding set and capsets to empty before it execs
    """
    fake = FakeOS(pid=0)

    with pytest.raises(ExitedError):
        launcher.main(
            [str(pipe[1]), spec_json(dirs, fs=fs, net=net), "--", "prog"], fake.ops()
        )

    names = fake.names()
    assert "capbset_drop" in names
    assert names.index("capset") < names.index("execvp")
    fake.close_errpipe()


@pytest.mark.parametrize(
    ("fs", "net"),
    [
        ("required", "required"),
        ("off", "required"),
        ("required", "off"),
        ("best_effort", "required"),
        ("required", "best_effort"),
    ],
)
def test_the_child_refuses_without_exec_when_a_required_drop_fails(
    dirs: Dirs,
    pipe: tuple[int, int],
    capsys: pytest.CaptureFixture[str],
    fs: str,
    net: str,
) -> None:
    """
    GIVEN fork returns 0, capset fails, and either part is required (a required
        flag attested by a forgeable report would prove nothing)
    WHEN the launcher continues in the child
    THEN it never execs, sends one R record on the error pipe and exits 125
    """
    fake = FakeOS(pid=0, fail={"capset": EPERM})

    with pytest.raises(ExitedError) as exited:
        launcher.main(
            [str(pipe[1]), spec_json(dirs, fs=fs, net=net), "--", "prog"], fake.ops()
        )

    assert exited.value.code == launcher.EXIT_REFUSED == 125
    assert "execvp" not in fake.names()
    assert "reset_signals" not in fake.names()
    assert "cannot execute" not in capsys.readouterr().err
    records = fake.errpipe_records()
    assert len(records) == 1
    assert records[0].startswith(b"Risolation is required but dropping privileges")


@pytest.mark.parametrize(
    ("fs", "net"),
    [
        ("best_effort", "off"),
        ("off", "best_effort"),
        ("best_effort", "best_effort"),
        ("off", "off"),
    ],
)
def test_the_child_records_and_continues_when_a_best_effort_drop_fails(
    dirs: Dirs, pipe: tuple[int, int], fs: str, net: str
) -> None:
    """
    GIVEN fork returns 0, the bounding-set drop fails while capabilities are
        held, and no part is required
    WHEN the launcher continues in the child
    THEN it sends a W record (so the parent can record it) and still resets
        signals and execs; the failed exec then adds its own E record
    """
    fake = FakeOS(pid=0, fail={"capbset_drop": EPERM})

    with pytest.raises(ExitedError) as exited:
        launcher.main(
            [str(pipe[1]), spec_json(dirs, fs=fs, net=net), "--", "prog"], fake.ops()
        )

    assert exited.value.code == 127
    assert fake.names()[-3:] == ["reset_signals", "execvp", "exit"]
    records = fake.errpipe_records()
    assert [record[:1] for record in records] == [b"W", b"E"]
    assert records[0].startswith(b"Wdropping privileges failed: PermissionError")


def test_an_unprivileged_child_without_capabilities_runs_under_required(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a non-root launcher with the network off (no user namespace), so
        PR_CAPBSET_DROP gives EPERM and capget shows no capability, fs required
    WHEN the launcher continues in the child
    THEN the run is not refused: the child execs and only the exec's own
        record reaches the error pipe (no R, no W)
    """
    fake = FakeOS(pid=0, fail={"capbset_drop": EPERM}, caps=NO_CAPS)

    with pytest.raises(ExitedError) as exited:
        launcher.main(
            [str(pipe[1]), spec_json(dirs, net="off"), "--", "prog"], fake.ops()
        )

    assert exited.value.code == 127
    assert "execvp" in fake.names()
    assert [record[:1] for record in fake.errpipe_records()] == [b"E"]


def test_a_drop_that_raises_a_non_os_error_still_refuses_without_exec(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN fork returns 0, both modes required, and the privilege drop raises
        something other than OSError
    WHEN the launcher continues in the child
    THEN that is a failed drop too: an R record naming it, exit 125, no exec,
        and the child never returns into the parent's code (no wait4, no
        second report)
    """
    fake = FakeOS(pid=0, fail={"capset": RuntimeError("unexpected")})

    with pytest.raises(ExitedError) as exited:
        launcher.main([str(pipe[1]), spec_json(dirs), "--", "prog"], fake.ops())

    assert exited.value.code == 125
    assert {"execvp", "wait4"}.isdisjoint(fake.names())
    records = fake.errpipe_records()
    assert len(records) == 1
    assert records[0].startswith(b"R") and b"RuntimeError: unexpected" in records[0]


def test_the_darwin_child_skips_the_privilege_drop(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a darwin child (no /proc, no capabilities to drop)
    WHEN the launcher continues in the child
    THEN it resets signals and execs without any capability syscall
    """
    fake = FakeOS(platform="darwin", pid=0)

    with pytest.raises(ExitedError) as exited:
        launcher.main(
            [str(pipe[1]), spec_json(dirs, platform="darwin"), "--", "prog"], fake.ops()
        )

    assert exited.value.code == 127
    assert {"capset", "capbset_drop", "no_new_privs"}.isdisjoint(fake.names())
    assert fake.names()[-3:] == ["reset_signals", "execvp", "exit"]
    fake.close_errpipe()


def test_a_child_that_cannot_drop_privilege_refuses_the_run(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the error pipe already holds an R record from a failed required drop
    WHEN the parent reads it after the child exits
    THEN the run is refused: exit 125, the reason in error, both flags false
    """
    fake = FakeOS(
        child_error=b"Risolation is required but dropping privileges failed: x\0"
    )

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == 125
    assert report["exit"] == 125
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert "dropping privileges failed" in str(report["error"])
    assert "execvp" not in fake.names()


def test_a_best_effort_drop_failure_turns_both_flags_false(
    dirs: Dirs, pipe: tuple[int, int], capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN both modes best_effort, isolation applied, and a W record from the
        child (its privilege drop failed, so the report could be forged)
    WHEN the parent reads it
    THEN the workload's status stands, both flags are false (no new key, no
        error), and stderr says why
    """
    fake = FakeOS(child_error=b"Wdropping privileges failed: OSError: x\0")

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="best_effort", net="best_effort")
    )

    assert code == 0
    assert (report["exit"], report["error"]) == (0, None)
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert "dropping privileges failed" in capsys.readouterr().err


def test_a_weakened_drop_then_an_exec_failure_reports_both(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a W record followed by an E record, and the child exited 127
    WHEN the parent reads them
    THEN the flags are false and the exec failure is the error, exit 127
    """
    fake = FakeOS(
        status=127 << 8,
        child_error=b"Wdropping privileges failed: x\0Ecannot execute 'prog': nope\0",
    )

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="best_effort", net="best_effort")
    )

    assert (code, report["exit"]) == (127, 127)
    assert report["error"] == "cannot execute 'prog': nope"
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)


def test_a_child_exec_failure_is_reported_with_its_message_and_exit(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN the error pipe holds an E<reason> and the child exited 127
    WHEN the parent reads it
    THEN the report carries that error and exit 127 (not a 125 refusal)
    """
    fake = FakeOS(
        status=127 << 8,
        child_error=b"Ecannot execute 'prog': No such file or directory\0",
    )

    code, report = run_main(fake, pipe, spec_json(dirs, fs="off", net="off", port=None))

    assert code == 127
    assert report["exit"] == 127
    assert report["error"] == "cannot execute 'prog': No such file or directory"


def test_a_workload_that_exits_125_is_not_a_refusal(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a fully isolated workload that itself exits 125
    WHEN the launcher reports
    THEN the launcher also exits 125 (it carries the workload's status), but the
        report is a normal one: error null, both flags true, exit 125. A
        refusal is told apart by its error, never by the status alone
    """
    code, report = run_main(FakeOS(status=125 << 8), pipe, spec_json(dirs))

    assert code == 125
    assert (report["exit"], report["error"]) == (125, None)
    assert (report["fs_isolated"], report["net_isolated"]) == (True, True)


@pytest.mark.parametrize(
    "tag", [launcher._CHILD_REFUSE, launcher._CHILD_WEAKENED, launcher._CHILD_EXEC]
)
def test_child_fail_writes_a_tagged_record_to_the_error_pipe(tag: bytes) -> None:
    """
    GIVEN an open error pipe
    WHEN the child announces a failure
    THEN the tag, the message and a NUL record terminator land on it
    """
    read, write = os.pipe()
    try:
        launcher._child_fail(write, tag, "something broke")
        os.close(write)
        assert os.read(read, 65536) == tag + b"something broke\0"
    finally:
        os.close(read)


def test_child_fail_swallows_a_broken_error_pipe() -> None:
    """
    GIVEN an error-pipe fd that is already closed
    WHEN the child tries to announce a failure
    THEN it does not raise (the exit code still carries the failure)
    """
    read, write = os.pipe()
    os.close(read)
    os.close(write)

    launcher._child_fail(write, launcher._CHILD_EXEC, "broke")


def test_clear_signal_handlers_resets_only_python_level_handlers() -> None:
    """
    GIVEN Python's SIGINT handler (a callable), an ignored SIGTERM, a SIGHUP
        with no Python-visible handler and every other signal at SIG_DFL
    WHEN the parent clears its handlers before the fork
    THEN only SIGINT is set to SIG_DFL: PID 1 of a namespace receives a signal
        from inside it only when a handler is installed, so with none left a
        workload cannot kill the launcher before it reports
    """
    handlers: dict[int, object] = {
        signal.SIGINT: signal.default_int_handler,
        signal.SIGTERM: signal.SIG_IGN,
        signal.SIGHUP: None,
    }
    seen: list[tuple[int, object]] = []

    launcher.clear_signal_handlers(
        getsignal=lambda signum: handlers.get(signum, signal.SIG_DFL),
        set_handler=lambda signum, handler: seen.append((signum, handler)),
    )

    assert seen == [(signal.SIGINT, signal.SIG_DFL)]


# ---------------------------------------------------------------------------
# In-process: invocation errors
# ---------------------------------------------------------------------------


def good_spec() -> dict[str, object]:
    return {
        "version": 1,
        "platform": "linux",
        "fs": "required",
        "net": "off",
        "writable": ["/w"],
        "probe_dir": "/p",
        "probe_port": None,
    }


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"version": 2}, "version"),
        ({"version": True}, "version"),
        ({"platform": "win32"}, "platform"),
        ({"platform": ["linux"]}, "platform"),
        ({"fs": "on"}, "fs"),
        ({"net": None}, "net"),
        ({"writable": "/w"}, "writable"),
        ({"writable": ["rel"]}, "writable"),
        ({"writable": [1]}, "writable"),
        ({"probe_dir": "rel"}, "probe_dir"),
        ({"probe_dir": 5}, "probe_dir"),
        ({"probe_port": True}, "probe_port"),
        ({"probe_port": 0}, "probe_port"),
        ({"probe_port": 65536}, "probe_port"),
        ({"probe_port": "80"}, "probe_port"),
        ({"extra": 1}, "keys"),
    ],
)
def test_parse_spec_refuses_malformed_specs(
    change: dict[str, object], message: str
) -> None:
    """
    GIVEN a spec with one malformed field or an unknown key
    WHEN it is parsed
    THEN ValueError names the field
    """
    with pytest.raises(ValueError, match=message):
        launcher.parse_spec(json.dumps(good_spec() | change))


@pytest.mark.parametrize(
    ("text", "message"),
    [("{", "not JSON"), ("[]", "keys"), ('{"version": 1}', "keys")],
)
def test_parse_spec_refuses_non_objects(text: str, message: str) -> None:
    """
    GIVEN text that is not JSON, not an object or missing keys
    WHEN it is parsed
    THEN ValueError
    """
    with pytest.raises(ValueError, match=message):
        launcher.parse_spec(text)


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["5", "{}", "--"],
        ["5", "{}", "x", "prog"],
        ["five", json.dumps(good_spec()), "--", "prog"],
        ["+5", json.dumps(good_spec()), "--", "prog"],
        ["2", json.dumps(good_spec()), "--", "prog"],
        ["99999999999999999999", json.dumps(good_spec()), "--", "prog"],
        ["5", "{", "--", "prog"],
    ],
)
def test_main_refuses_a_bad_invocation_with_125(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN a wrong arity, no '--', a bad fd or a bad spec
    WHEN the launcher starts
    THEN it says why on stderr, exits 125 and touches nothing else
    """
    fake = FakeOS()

    assert launcher.main(argv, fake.ops()) == 125
    assert "launcher:" in capsys.readouterr().err
    assert fake.calls == []


def test_main_refuses_a_closed_report_fd(
    dirs: Dirs, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN a report fd that is not open
    WHEN the launcher starts
    THEN exit 125 without running anything
    """
    read, write = os.pipe()
    os.close(read)
    os.close(write)
    fake = FakeOS()

    assert launcher.main([str(write), spec_json(dirs), "--", "prog"], fake.ops()) == 125
    assert "report fd" in capsys.readouterr().err
    assert fake.calls == []


def test_a_report_that_cannot_be_written_exits_125(
    dirs: Dirs, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    GIVEN a report pipe whose read end is closed
    WHEN the launcher writes the report
    THEN it says so and exits 125
    """
    read, write = os.pipe()
    os.close(read)
    try:
        code = launcher.main(
            [str(write), spec_json(dirs, fs="off", net="off"), "--", "p"],
            FakeOS().ops(),
        )
    finally:
        os.close(write)

    assert code == 125
    assert "cannot write the report" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The real OS wrappers, on harmless calls only
# ---------------------------------------------------------------------------


def test_default_ops_are_the_real_os_calls() -> None:
    """
    GIVEN the default ops
    WHEN they are inspected
    THEN they name the host platform and the os functions
    """
    ops = launcher.default_ops()

    assert ops.platform == sys.platform
    assert (ops.fork, ops.execvp, ops.wait4, ops.exit) == (
        os.fork,
        os.execvp,
        os.wait4,
        os._exit,
    )
    assert ops.open is os.open
    assert ops.pipe is os.pipe
    assert ops.capset is launcher.real_capset
    assert ops.capget is launcher.real_capget
    assert ops.cap_last_cap is launcher.real_cap_last_cap
    assert ops.seccomp is launcher.real_seccomp
    assert ops.unix_socket is launcher.real_unix_socket
    assert ops.clear_handlers is launcher.clear_signal_handlers
    assert ops.kill is os.kill
    assert ops.waitid is launcher.real_waitid
    assert ops.child_cpu is launcher.real_child_cpu
    assert ops.children is launcher.real_children


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux syscalls")


@linux_only
def test_real_waitid_leaves_the_exited_child_for_its_cpu_read_and_reap() -> None:
    """
    GIVEN a child that waited for a grandchild doing about 60 ms of CPU
    WHEN real_waitid returns
    THEN the child is exited but unreaped: real_child_cpu reads the
        grandchild's CPU from its /proc stat, real_children names it, and
        wait4 still reaps it
    """
    busy = "import time\nt=time.process_time()\nwhile time.process_time()-t<0.06: pass"
    code = f"import subprocess, sys\nsubprocess.run([sys.executable, '-c', {busy!r}])"
    child = subprocess.Popen([sys.executable, "-c", code])

    launcher.real_waitid(child.pid)
    cpu = launcher.real_child_cpu(child.pid)
    named = child.pid in launcher.real_children()
    pid, status, _ = os.wait4(child.pid, 0)
    child.returncode = os.waitstatus_to_exitcode(status)

    assert (pid, child.returncode, named) == (child.pid, 0, True)
    assert 0.04 <= cpu < 5.0


@linux_only
def test_real_children_names_a_live_child_and_skips_a_vanished_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a live child and a /proc listing that also holds a pid whose stat
        is gone (it exited meanwhile) and a name that is no pid
    WHEN the children are listed
    THEN the live child is named and the others are skipped
    """
    real_listdir = os.listdir
    monkeypatch.setattr(
        os, "listdir", lambda path: [*real_listdir(path), "999999999", "self"]
    )
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        found = launcher.real_children()
    finally:
        child.kill()
        child.wait()

    assert child.pid in found
    assert 999999999 not in found


@linux_only
def test_real_syscall_queries_landlock_and_maps_errors() -> None:
    """
    GIVEN the ctypes syscall wrapper
    WHEN it asks for the Landlock ABI, creates (never applies) a ruleset and
        passes invalid flags
    THEN it returns the ABI and an fd, and raises OSError with the errno
    """
    syscall = launcher.default_ops().syscall
    try:
        abi = syscall(444, (None, 0, 1))
    except OSError as error:
        assert error.errno in (errno.ENOSYS, errno.EOPNOTSUPP)
    else:
        assert abi >= 1
    try:
        ruleset = syscall(444, (struct.pack("=Q", 1 << 1), 8, 0))
    except OSError as error:
        assert error.errno in (errno.ENOSYS, errno.EOPNOTSUPP)
    else:
        os.close(ruleset)

    with pytest.raises(OSError) as invalid:
        syscall(444, (None, 0, 0xFFFF))
    assert invalid.value.errno in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP)


@linux_only
def test_real_capset_rejects_an_invalid_request() -> None:
    """
    GIVEN the ctypes capset wrapper and a header with an unsupported version
    WHEN it is called
    THEN capset refuses it (no capability is changed) and OSError is raised
    """
    with pytest.raises(OSError):
        launcher.real_capset(struct.pack("=II", 0, 0), b"\0" * 24)


@linux_only
def test_real_capget_matches_proc_self_status() -> None:
    """
    GIVEN the ctypes capget wrapper (read-only: it changes nothing)
    WHEN it reads this process's capability sets
    THEN effective, permitted and inheritable match /proc/self/status
    """
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )

    effective, permitted, inheritable = launcher.real_capget()

    assert effective == int(status["CapEff"], 16)
    assert permitted == int(status["CapPrm"], 16)
    assert inheritable == int(status["CapInh"], 16)


@linux_only
def test_real_cap_last_cap_reads_the_kernel_value() -> None:
    """
    GIVEN this Linux host exposes /proc/sys/kernel/cap_last_cap
    WHEN the helper reads it
    THEN it returns a non-negative capability number
    """
    last = launcher.real_cap_last_cap()

    assert isinstance(last, int)
    assert last >= 0


def test_real_cap_last_cap_returns_none_when_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN the cap_last_cap file cannot be read
    WHEN the helper reads it
    THEN it returns None so the drop falls back to looping until EINVAL
    """
    monkeypatch.setattr(launcher, "_CAP_LAST_CAP_PATH", "/no/such/cap_last_cap")

    assert launcher.real_cap_last_cap() is None


@linux_only
def test_real_prctl_reads_no_new_privs_and_maps_errors() -> None:
    """
    GIVEN the ctypes prctl wrapper
    WHEN it reads PR_GET_NO_NEW_PRIVS (harmless) and an invalid option
    THEN it returns 0 or 1, then raises OSError EINVAL
    """
    prctl = launcher.default_ops().prctl

    assert prctl(39, 0) in (0, 1)
    with pytest.raises(OSError) as invalid:
        prctl(0x7FFF_FFFF, 0)
    assert invalid.value.errno == errno.EINVAL


def test_real_connect_reaches_a_listener_and_raises_when_refused() -> None:
    """
    GIVEN a listener on 127.0.0.1 and a closed port
    WHEN the real connect probe runs against each
    THEN the first returns and the second raises ConnectionRefusedError
    """
    connect = launcher.default_ops().connect
    with socket.create_server(("127.0.0.1", 0), backlog=1) as server:
        port = server.getsockname()[1]
        connect("127.0.0.1", port)
    with pytest.raises(ConnectionRefusedError):
        connect("127.0.0.1", port)


def test_real_unix_socket_creates_one_when_unconfined() -> None:
    """
    GIVEN an unconfined process
    WHEN the AF_UNIX probe runs
    THEN it creates and closes the socket without raising (the self-check then
        reports network isolation is missing)
    """
    launcher.real_unix_socket()


@linux_only
def test_install_seccomp_maps_a_rejected_filter_to_oserror() -> None:
    """
    GIVEN an empty (zero-instruction) BPF program the kernel rejects
    WHEN _install_seccomp calls seccomp(2) with it
    THEN it raises OSError and installs nothing, so the test process is intact
    """
    seccomp_nr = launcher._SECCOMP_ARCH[os.uname().machine][2]

    with pytest.raises(OSError) as info:
        launcher._install_seccomp(seccomp_nr, b"")

    assert info.value.errno == errno.EINVAL
    launcher.real_unix_socket()  # proves no filter was installed in this process


def test_real_seccomp_builds_the_filter_for_this_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a supported host
    WHEN real_seccomp runs with the install stubbed out
    THEN it installs this machine's filter with the right seccomp syscall nr
    """
    machine = os.uname().machine
    if machine not in launcher._SECCOMP_ARCH:
        pytest.skip(f"no seccomp numbers for {machine}")
    calls: list[tuple[int, bytes]] = []
    monkeypatch.setattr(
        launcher, "_install_seccomp", lambda nr, program: calls.append((nr, program))
    )

    launcher.real_seccomp()

    assert calls == [
        (launcher._SECCOMP_ARCH[machine][2], launcher.seccomp_filter(machine))
    ]


def test_real_seccomp_refuses_an_unsupported_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    GIVEN a host whose architecture has no known syscall numbers
    WHEN real_seccomp runs
    THEN it raises OSError(EOPNOTSUPP) before touching the install path
    """
    fake = os.uname_result(("Linux", "h", "6", "#1", "s390x"))
    monkeypatch.setattr(os, "uname", lambda: fake)

    with pytest.raises(OSError) as info:
        launcher.real_seccomp()

    assert info.value.errno == errno.EOPNOTSUPP


def test_restore_signals_resets_the_python_ignored_signals() -> None:
    """
    GIVEN Python ignores SIGPIPE and SIGXFSZ at startup
    WHEN the child restores dispositions before exec
    THEN each one that exists on this platform is set to SIG_DFL
    """
    seen: list[tuple[int, object]] = []

    launcher.restore_signals(lambda signum, handler: seen.append((signum, handler)))

    assert (signal.SIGPIPE, signal.SIG_DFL) in seen
    assert (signal.SIGXFSZ, signal.SIG_DFL) in seen
    assert all(handler is signal.SIG_DFL for _, handler in seen)


def test_restore_signals_skips_a_signal_this_platform_lacks() -> None:
    """
    GIVEN a ``signal`` module that has SIGPIPE but not SIGXFSZ
    WHEN the child restores dispositions before exec
    THEN only the present signal is reset and the absent one is skipped
    """
    present = types.SimpleNamespace(SIGPIPE=signal.SIGPIPE, SIG_DFL=signal.SIG_DFL)
    seen: list[tuple[int, object]] = []

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(launcher, "signal", present)
        launcher.restore_signals(lambda signum, handler: seen.append((signum, handler)))

    assert seen == [(signal.SIGPIPE, signal.SIG_DFL)]


@linux_only
def test_libc_is_loaded_once() -> None:
    """
    GIVEN the lazily loaded libc handle
    WHEN it is asked for twice
    THEN the same handle comes back
    """
    assert launcher.libc() is launcher.libc()


# ---------------------------------------------------------------------------
# Stdlib only
# ---------------------------------------------------------------------------


def test_launcher_imports_only_the_standard_library() -> None:
    """
    GIVEN the launcher's source
    WHEN every import in it is listed
    THEN each is a standard-library module, none is the engine, none relative
    """
    tree = ast.parse(LAUNCHER_PATH.read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            names.append(node.module)

    assert names
    assert {name.split(".")[0] for name in names} <= sys.stdlib_module_names


def test_launcher_runs_standalone_and_stays_lean() -> None:
    """
    GIVEN the launcher run by path as python -I -S with -X importtime
    WHEN it is started without arguments
    THEN it exits 125 with its usage, and never imports the engine, typing
        or dataclasses (the workload's RSS floor is the launcher's RSS)
    """
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-X", "importtime", str(LAUNCHER_PATH)],
        capture_output=True,
        text=True,
        env={},
        timeout=60,
        check=False,
    )

    assert proc.returncode == 125
    assert "usage" in proc.stderr
    imported = {
        line.rsplit("|", 1)[-1].strip()
        for line in proc.stderr.splitlines()
        if line.startswith("import time:")
    }
    assert imported.isdisjoint({"typing", "dataclasses", "autonomous_ai_agents"})


# ---------------------------------------------------------------------------
# Real runs under the host sandbox
# ---------------------------------------------------------------------------


def _require() -> bool:
    return "1" in (
        os.environ.get("REQUIRE_NETWORK_SANDBOX"),
        os.environ.get("REQUIRE_FS_SANDBOX"),
    )


def _linux_sandbox_problem() -> str | None:
    if shutil.which("unshare") is None:
        return "unshare is not installed"
    probe = subprocess.run(
        [*UNSHARE_ARGV, "true"], capture_output=True, timeout=30, check=False
    )
    if probe.returncode != 0:
        detail = probe.stderr.decode(errors="replace")
        return f"{' '.join(UNSHARE_ARGV)} true failed: {detail}"
    try:
        launcher.default_ops().syscall(444, (None, 0, 1))
    except OSError as error:
        return f"Landlock is unavailable: {error}"
    return None


@pytest.fixture(scope="module")
def linux_sandbox() -> None:
    """Skip (or fail under REQUIRE_*) when this Linux host cannot sandbox."""
    problem = _linux_sandbox_problem()
    if problem is not None:
        if _require():
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(problem)


class Launch:
    """One real launcher run: its exit code, report and output."""

    def __init__(
        self, code: int, report: dict[str, object] | None, out: str, err: str
    ) -> None:
        self.code = code
        self.report = report
        self.out = out
        self.err = err

    def results(self) -> dict[str, object]:
        loaded = json.loads(self.out)
        assert isinstance(loaded, dict)
        return loaded


def launch(
    dirs: Dirs,
    argv: Sequence[str],
    *,
    network: IsolationMode,
    fs: IsolationMode,
    port: int | None = None,
    writable: Sequence[Path] | None = None,
    prefix: Sequence[str] = (),
    python: str = sys.executable,
) -> Launch:
    built = SandboxPolicy(
        network=network,
        fs=fs,
        writable=tuple(writable or (dirs.wt, dirs.scratch)),
        probe_dir=dirs.probe,
        platform=sys.platform,
    )
    env = child_env(home=dirs.scratch, tmpdir=dirs.scratch, worktree=dirs.wt)
    read, write = os.pipe()
    try:
        proc = subprocess.Popen(
            [
                *prefix,
                *launcher_argv(
                    built, fd=write, report_port=port, argv=argv, python=python
                ),
            ],
            cwd=dirs.wt,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=(write,),
            start_new_session=True,
            close_fds=True,
        )
    finally:
        os.close(write)
    out, err = proc.communicate(timeout=120)
    with os.fdopen(read, "rb") as reader:
        data = reader.read()
    report = json.loads(data) if data else None
    return Launch(proc.returncode, report, out.decode(), err.decode())


PROBE_WORKLOAD = r"""
import errno, json, os, socket, sys
outside, inside, shm, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
unix_path = sys.argv[5]
def write(path, flags=os.O_WRONLY | os.O_CREAT | os.O_TRUNC):
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        return errno.errorcode[error.errno]
    os.write(fd, b"x")
    os.close(fd)
    return "ok"
def connect(target):
    try:
        socket.create_connection(target, timeout=2).close()
    except OSError as error:
        return errno.errorcode.get(error.errno, str(error))
    return "ok"
def make_unix():
    try:
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM).close()
    except OSError as error:
        return errno.errorcode.get(error.errno, str(error))
    return "ok"
def unix_connect(path):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    except OSError as error:
        return errno.errorcode.get(error.errno, str(error))
    try:
        sock.settimeout(2)
        sock.connect(path)
        sock.sendall(b"EXFIL")
    except OSError as error:
        return errno.errorcode.get(error.errno, str(error))
    finally:
        sock.close()
    return "ok"
result = {"outside": write(outside), "inside": write(inside),
          "devnull": write(os.devnull), "home": write(os.environ["HOME"] + "/h")}
if shm != "-":
    result["shm"] = write(shm)
    if result["shm"] == "ok":
        os.unlink(shm)
result["parent"] = connect(("127.0.0.1", port))
try:
    with socket.create_server(("127.0.0.1", 0)) as own:
        result["own_loopback"] = connect(own.getsockname())
except OSError as error:
    result["own_loopback"] = errno.errorcode.get(error.errno, str(error))
result["unix_make"] = make_unix()
result["unix_host"] = unix_connect(unix_path)
print(json.dumps(result))
"""


def probe_argv(dirs: Dirs, tmp_path: Path, port: int, unix_path: Path) -> list[str]:
    shm = f"/dev/shm/aip-test-{os.getpid()}-{time.monotonic_ns()}"
    return [
        sys.executable,
        "-c",
        PROBE_WORKLOAD,
        str(tmp_path / "outside.txt"),
        str(dirs.wt / "inside.txt"),
        shm if os.path.isdir("/dev/shm") else "-",
        str(port),
        str(unix_path),
    ]


@pytest.fixture
def listener() -> Iterator[int]:
    """The parent's 127.0.0.1 listener the sandboxed run must not reach."""
    with socket.create_server(("127.0.0.1", 0), backlog=8) as server:
        yield server.getsockname()[1]


@pytest.fixture
def unix_listener() -> Iterator[Path]:
    """
    A host AF_UNIX listener the sandboxed run must not reach (exfil target).

    It lives in a short directory under /tmp: macOS caps sun_path at 104 bytes
    and its per-user tmp_path is already longer than that.
    """
    short = Path(tempfile.mkdtemp(prefix="aip-sock-", dir="/tmp"))
    path = short / "host.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
        server.listen(8)
        yield path
    finally:
        server.close()
        shutil.rmtree(short)


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_confines_writes_and_network(
    dirs: Dirs, tmp_path: Path, listener: int, unix_listener: Path
) -> None:
    """
    GIVEN the real launcher under unshare with both modes required
    WHEN the workload writes inside and outside, connects out and to its own
        loopback, and tries to reach a host AF_UNIX socket
    THEN outside is EACCES, inside, HOME and /dev/null (with O_TRUNC) work,
        /dev/shm is now denied (shared across runs, removed from the rules),
        the parent's listener is unreachable, its own lo works, creating an
        AF_UNIX socket and reaching the host unix socket are both denied by the
        seccomp filter (no breach), and the report says both are isolated
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener, unix_listener),
        network="required",
        fs="required",
        port=listener,
    )

    assert run.code == 0, run.err
    results = run.results()
    assert results["outside"] == "EACCES"
    assert not (tmp_path / "outside.txt").exists()
    assert results["inside"] == results["home"] == results["devnull"] == "ok"
    assert results.get("shm", "EACCES") in ("EACCES", "EPERM")
    assert results["parent"] in ("ECONNREFUSED", "ENETUNREACH")
    assert results["own_loopback"] == "ok"
    assert results["unix_make"] in ("EACCES", "EPERM")
    assert results["unix_host"] in ("EACCES", "EPERM")
    assert run.report is not None
    assert (run.report["fs_isolated"], run.report["net_isolated"]) == (True, True)
    assert (run.report["exit"], run.report["error"]) == (0, None)


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_control_run_is_not_isolated(
    dirs: Dirs, tmp_path: Path, listener: int, unix_listener: Path
) -> None:
    """
    GIVEN the same workload with both modes off (the control)
    WHEN it runs
    THEN the outside write, the parent connect and reaching the host AF_UNIX
        socket all succeed and both flags are false, so the confined run above
        proves something
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener, unix_listener),
        network="off",
        fs="off",
        port=listener,
    )

    assert run.code == 0, run.err
    results = run.results()
    assert results["outside"] == results["parent"] == "ok"
    assert results["unix_make"] == results["unix_host"] == "ok"
    assert run.report is not None
    assert (run.report["fs_isolated"], run.report["net_isolated"]) == (False, False)


ORPHAN_WORKLOAD = r"""
import os, subprocess, sys, time
started, alive = sys.argv[1], sys.argv[2]
subprocess.Popen([sys.executable, "-c",
    "import sys, time\n"
    "open(sys.argv[1], 'w').close()\n"
    "time.sleep(0.5)\n"
    "open(sys.argv[2], 'w').close()",
    started, alive], start_new_session=True)
deadline = time.monotonic() + 30
while not os.path.exists(started) and time.monotonic() < deadline:
    time.sleep(0.01)
"""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize("network", ["required", "off"])
def test_real_launcher_pid_namespace_kills_setsid_orphans(
    dirs: Dirs, listener: int, network: IsolationMode
) -> None:
    """
    GIVEN a workload that starts a setsid grandchild, waits until it runs,
        and exits while the grandchild still has 0.5 s to live
    WHEN it runs in the PID namespace and without one
    THEN the orphan never writes its "alive" marker: in the namespace it dies
        with the launcher, and without one the launcher, its child
        subreaper, kills it (N0c); both reports count it as one stray
    """
    started, alive = dirs.wt / "orphan-started", dirs.wt / "orphan-alive"

    run = launch(
        dirs,
        [sys.executable, "-c", ORPHAN_WORKLOAD, str(started), str(alive)],
        network=network,
        fs="off",
        port=listener,
    )
    deadline = time.monotonic() + 1.5
    while not alive.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    assert run.code == 0, run.err
    assert started.exists()
    assert alive.exists() is False
    assert run.report is not None and run.report["strays"] == 1


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_refuses_without_exec_when_landlock_cannot_apply(
    dirs: Dirs,
) -> None:
    """
    GIVEN fs required and a writable dir that does not exist
    WHEN the real launcher runs
    THEN it exits 125 with an error report and the workload never runs
    """
    marker = dirs.wt / "ran"

    run = launch(
        dirs,
        [sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
        network="off",
        fs="required",
        writable=(dirs.wt, dirs.scratch / "missing"),
    )

    assert run.code == 125
    assert run.report is not None
    assert "fs isolation is required" in str(run.report["error"])
    assert not marker.exists()


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_reports_exec_failure_exit_codes_and_a_low_floor(
    dirs: Dirs, listener: int
) -> None:
    """
    GIVEN a missing command, a workload exiting 3 and /bin/true, all fully
        isolated
    WHEN each runs under the real launcher
    THEN the reports say 127, 3 and 0, the outer wrapper now carries the same
        status (the launcher exits with the workload's), and /bin/true's raw
        maxrss (KiB) is under 50 MiB: the launcher keeps the RSS floor low
    """
    runs = [
        launch(dirs, argv, network="required", fs="required", port=listener)
        for argv in (
            [str(dirs.wt / "no-such-command")],
            [sys.executable, "-c", "raise SystemExit(3)"],
            ["/bin/true"],
        )
    ]

    assert [run.code for run in runs] == [127, 3, 0]
    reports = [run.report for run in runs]
    assert [r["exit"] if r else None for r in reports] == [127, 3, 0]
    assert "cannot execute" in runs[0].err
    floor = reports[2]
    assert floor is not None and isinstance(floor["maxrss"], int)
    assert 0 < floor["maxrss"] * 1024 < 50 * 1024 * 1024


# ---------------------------------------------------------------------------
# Defensive regression tests: the sandbox holds against a hostile workload.
# These verify the anti-forge controls the way a firewall test verifies a
# firewall; they never escape the sandbox or write a forged report.
# ---------------------------------------------------------------------------


PROC_FD_WALK = r"""
import json, os, re
def unescape(field):
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), field)
mounts = set()
with open("/proc/self/mountinfo") as handle:
    for line in handle:
        left, _, right = line.partition(" - ")
        if right.split(" ", 1)[0] == "proc":
            mounts.add(unescape(left.split(" ")[4]))
opened_foreign = []
for mount in sorted(mounts):
    try:
        own = os.readlink(mount + "/self")
    except OSError:
        own = None
    try:
        entries = os.listdir(mount)
    except OSError:
        continue
    for entry in entries:
        if not entry.isdigit() or entry == own:
            continue
        fd_dir = "%s/%s/fd" % (mount, entry)
        try:
            names = os.listdir(fd_dir)
        except OSError:
            continue
        for name in names:
            path = fd_dir + "/" + name
            try:
                fd = os.open(path, os.O_WRONLY)
            except OSError:
                continue
            os.close(fd)
            opened_foreign.append(path)
print(json.dumps({"procfs_mounts": sorted(mounts), "opened_foreign": opened_foreign}))
"""
"""Walks every procfs mount (not only ``/proc``), so a host where another
procfs of the outer PID namespace is visible fails loudly instead of passing."""

DEFENDED = [
    ("required", "required"),
    ("required", "best_effort"),
    ("required", "off"),
    ("off", "required"),
]
"""``(network, fs)``: every mode in which a user namespace exists, plus fs-only."""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize(("network", "fs"), DEFENDED)
def test_real_launcher_report_pipe_cannot_be_forged_through_proc(
    dirs: Dirs, listener: int, network: IsolationMode, fs: IsolationMode
) -> None:
    """
    GIVEN a hostile workload that walks every <procfs>/<pid>/fd and tries to
        open each entry for writing
    WHEN it runs under each defended mode, fs=off included (the privilege drop
        guards the report channel whatever the fs mode)
    THEN it can open nothing outside its own process, and the parent receives
        exactly one report, the launcher's genuine one
    """
    run = launch(
        dirs,
        [sys.executable, "-c", PROC_FD_WALK],
        network=network,
        fs=fs,
        port=listener,
    )

    assert run.code == 0, run.err
    results = run.results()
    mounts = results["procfs_mounts"]
    assert isinstance(mounts, list) and "/proc" in mounts
    assert results["opened_foreign"] == []
    assert run.report is not None  # launch() parses the pipe: a second object fails
    assert (run.report["exit"], run.report["error"]) == (0, None)
    assert run.report["net_isolated"] is (network != "off")
    assert run.report["fs_isolated"] is (fs != "off")


PTRACE_WORKLOAD = r"""
import ctypes, json, os
libc = ctypes.CDLL(None, use_errno=True)
libc.ptrace.restype = ctypes.c_long
libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
PTRACE_ATTACH, PTRACE_DETACH, WALL = 16, 17, 0x40000000
target = os.getppid()
ctypes.set_errno(0)
rc = libc.ptrace(PTRACE_ATTACH, target, None, None)
err = ctypes.get_errno()
if rc == 0:  # the control failed: release the launcher at once
    os.waitpid(target, WALL)
    libc.ptrace(PTRACE_DETACH, target, None, None)
print(json.dumps({"target": target, "rc": rc, "errno": err}))
"""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize(("network", "fs"), DEFENDED)
def test_real_launcher_workload_cannot_ptrace_the_launcher(
    dirs: Dirs, listener: int, network: IsolationMode, fs: IsolationMode
) -> None:
    """
    GIVEN a hostile workload that tries ptrace(PTRACE_ATTACH) on the launcher,
        its parent (PID 1 inside the namespace)
    WHEN it runs under each defended mode
    THEN the attach is refused
    """
    run = launch(
        dirs,
        [sys.executable, "-c", PTRACE_WORKLOAD],
        network=network,
        fs=fs,
        port=listener,
    )

    assert run.code == 0, run.err
    results = run.results()
    assert results["rc"] == -1
    assert results["errno"] in (errno.EPERM, errno.EACCES)
    if network != "off":
        assert results["target"] == 1


PROC_PIDS_WORKLOAD = r"""
import json, os
print(json.dumps({"pids": sorted(int(e) for e in os.listdir("/proc") if e.isdigit())}))
"""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_proc_lists_only_namespace_pids(
    dirs: Dirs, listener: int
) -> None:
    """
    GIVEN --mount-proc gives the namespace its own /proc
    WHEN a workload lists it
    THEN only this namespace's PIDs are there (the launcher is PID 1, the host's
        PIDs are hidden)
    """
    run = launch(
        dirs,
        [sys.executable, "-c", PROC_PIDS_WORKLOAD],
        network="required",
        fs="required",
        port=listener,
    )

    assert run.code == 0, run.err
    pids = run.results()["pids"]
    assert isinstance(pids, list)
    assert 1 in pids
    assert len(pids) <= 8


PROC_STATUS_CAPS_WORKLOAD = r"""
import json
wanted = {"CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb", "NoNewPrivs"}
found = {}
with open("/proc/self/status") as handle:
    for line in handle:
        key, _, value = line.partition(":")
        if key in wanted:
            found[key] = value.strip()
print(json.dumps(found))
"""
ZERO_CAPS = "0000000000000000"


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize("fs", ["required", "best_effort", "off"])
def test_real_launcher_workload_runs_with_no_capabilities(
    dirs: Dirs, listener: int, fs: IsolationMode
) -> None:
    """
    GIVEN a user namespace (network required) and any fs mode
    WHEN the workload reads /proc/self/status
    THEN all five capability masks are empty and NoNewPrivs is 1: the child
        dropped every capability before exec, fs=off included
    """
    run = launch(
        dirs,
        [sys.executable, "-c", PROC_STATUS_CAPS_WORKLOAD],
        network="required",
        fs=fs,
        port=listener,
    )

    assert run.code == 0, run.err
    status = run.results()
    for key in ("CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb"):
        assert status[key] == ZERO_CAPS, key
    assert status["NoNewPrivs"] == "1"


SIGINT_LAUNCHER_WORKLOAD = r"""
import json, os, signal, time
target = os.getppid()
os.kill(target, signal.SIGINT)
time.sleep(0.2)
print(json.dumps({"target": target}))
"""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize("fs", ["required", "off"])
def test_real_launcher_survives_a_sigint_from_the_workload(
    dirs: Dirs, listener: int, fs: IsolationMode
) -> None:
    """
    GIVEN a hostile workload that sends SIGINT to the launcher, PID 1 of its
        namespace
    WHEN it runs
    THEN the signal is discarded (the launcher left no handler installed), the
        workload finishes, and the parent receives exactly one genuine report
    """
    run = launch(
        dirs,
        [sys.executable, "-c", SIGINT_LAUNCHER_WORKLOAD],
        network="required",
        fs=fs,
        port=listener,
    )

    assert run.code == 0, run.err
    assert run.results() == {"target": 1}
    assert run.report is not None
    assert (run.report["exit"], run.report["error"]) == (0, None)


SYSV_WORKLOAD = r"""
import ctypes, json, sys
libc = ctypes.CDLL(None, use_errno=True)
libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
key, mode = int(sys.argv[1]), sys.argv[2]
IPC_CREAT, IPC_EXCL = 0o1000, 0o2000
if mode == "store":
    shmid = libc.shmget(key, 4096, IPC_CREAT | IPC_EXCL | 0o600)
else:
    shmid = libc.shmget(key, 0, 0)
print(json.dumps({"shmid": shmid, "errno": ctypes.get_errno()}))
"""


def _host_shm_remove(key: int) -> bool:
    """Remove a SysV segment with ``key`` from this (the host's) IPC namespace."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.shmget.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_int]
    shmid = int(libc.shmget(key, 0, 0))
    if shmid < 0:
        return False
    libc.shmctl(shmid, 0, None)  # IPC_RMID
    return True


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_sysv_ipc_does_not_survive_into_the_next_run(
    dirs: Dirs, listener: int
) -> None:
    """
    GIVEN a workload that creates a SysV shared memory segment in one run (as a
        warm-up could, to memoise an answer) and looks for it in the next
    WHEN both run in the namespace
    THEN the second run cannot find it, and it never reached the host: each run
        has its own IPC namespace, which dies with the run
    """
    key = 0x41490000 | ((os.getpid() ^ time.monotonic_ns()) & 0xFFFF)
    try:
        runs = [
            launch(
                dirs,
                [sys.executable, "-c", SYSV_WORKLOAD, str(key), mode],
                network="required",
                fs="required",
                port=listener,
            )
            for mode in ("store", "read")
        ]
    finally:
        leaked = _host_shm_remove(key)

    assert [run.code for run in runs] == [0, 0], [run.err for run in runs]
    stored = runs[0].results()["shmid"]
    assert isinstance(stored, int) and stored >= 0
    assert runs[1].results() == {"shmid": -1, "errno": errno.ENOENT}
    assert not leaked


@pytest.fixture
def shared_dirs() -> Iterator[Dirs]:
    """Dirs a non-root user can reach: pytest's base temp dir is 0700."""
    root = Path(tempfile.mkdtemp(prefix="aip-launcher-"))
    try:
        root.chmod(0o755)
        made = Dirs(root)
        for path in (made.wt, made.scratch, made.probe):
            path.chmod(0o777)  # the probe too, so only Landlock can deny it
        yield made
    finally:
        shutil.rmtree(root, ignore_errors=True)


def non_root_prefix(python: str) -> list[str]:
    """Nothing when this process is not root (CI); else setpriv down to nobody.

    Skips when root cannot hand the run to uid 65534: no setpriv, or nobody
    cannot run ``python`` on the launcher (it must exit 125 with its usage).
    """
    if os.geteuid() != 0:
        return []
    setpriv = shutil.which("setpriv")
    if setpriv is None:
        pytest.skip("running as root without setpriv to drop to a non-root user")
    prefix = [setpriv, "--reuid=65534", "--regid=65534", "--clear-groups", "--"]
    probe = subprocess.run(
        [*prefix, python, "-I", "-S", str(LAUNCHER_PATH)],
        capture_output=True,
        cwd="/",
        timeout=30,
        check=False,
    )
    if probe.returncode != launcher.EXIT_REFUSED:
        pytest.skip(f"uid 65534 cannot run {python} on the launcher: {probe.stderr!r}")
    return prefix


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_confines_writes_as_non_root_without_a_user_namespace(
    shared_dirs: Dirs,
) -> None:
    """
    GIVEN a non-root launcher (this process on CI, else setpriv to nobody) with
        the network off, so there is no user namespace and PR_CAPBSET_DROP has
        no CAP_SETPCAP, and fs required
    WHEN /bin/true, the capability reader and the /proc fd walk run
    THEN none is refused (no 125): each exits 0 with fs_isolated true, the
        workload holds no effective, permitted, inheritable or ambient
        capability under no_new_privs (the bounding set stays, and execve can
        grant nothing), and it can open no other process's fd
    """
    python = os.path.realpath(sys.executable)  # a venv may sit in a 0700 dir
    prefix = non_root_prefix(python)

    runs = [
        launch(
            shared_dirs,
            argv,
            network="off",
            fs="required",
            prefix=prefix,
            python=python,
        )
        for argv in (
            ["/bin/true"],
            [python, "-c", PROC_STATUS_CAPS_WORKLOAD],
            [python, "-c", PROC_FD_WALK],
        )
    ]

    for run in runs:
        assert run.code == 0, run.err
        assert run.report is not None
        assert (run.report["error"], run.report["fs_isolated"]) == (None, True)
    status = runs[1].results()
    for key in ("CapEff", "CapPrm", "CapInh", "CapAmb"):
        assert status[key] == ZERO_CAPS, key
    assert status["NoNewPrivs"] == "1"
    assert runs[2].results()["opened_foreign"] == []


def test_real_launcher_exits_with_the_workloads_own_status(dirs: Dirs) -> None:
    """
    GIVEN a workload that exits 3, and one that kills itself with SIGKILL
    WHEN each runs under the real launcher
    THEN the wrapper's exit status is the workload's: 3, and 128+9 == 137 for
        the signal, while the report keeps the raw -9
    """
    three = launch(
        dirs,
        [sys.executable, "-c", "raise SystemExit(3)"],
        network="off",
        fs="off",
    )
    assert three.code == 3
    assert three.report is not None and three.report["exit"] == 3

    killer = "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"
    killed = launch(dirs, [sys.executable, "-c", killer], network="off", fs="off")
    assert killed.code == 137
    assert killed.report is not None and killed.report["exit"] == -9


darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec")


@pytest.fixture(scope="module")
def darwin_sandbox() -> None:
    """Skip (or fail under REQUIRE_*) when sandbox-exec is missing."""
    if shutil.which("sandbox-exec") is None:
        if _require():
            pytest.fail("sandbox required but sandbox-exec is not installed")
        pytest.skip("sandbox-exec is not installed")


@darwin_only
@pytest.mark.usefixtures("darwin_sandbox")
def test_real_launcher_under_sandbox_exec(
    dirs: Dirs, tmp_path: Path, listener: int, unix_listener: Path
) -> None:
    """
    GIVEN the real launcher under sandbox-exec with both modes required
    WHEN the workload writes inside and outside and connects out
    THEN outside is denied, inside, HOME and /dev/null work, the parent's
        listener and the host AF_UNIX socket are unreachable ((deny network*)
        covers AF_UNIX connect) and the report says both are isolated
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener, unix_listener),
        network="required",
        fs="required",
        port=listener,
    )

    assert run.report is not None, run.err
    assert run.report["error"] is None, run.report
    assert (run.report["fs_isolated"], run.report["net_isolated"]) == (True, True)
    results = run.results()
    assert results["outside"] in ("EPERM", "EACCES")
    assert results["inside"] == results["home"] == results["devnull"] == "ok"
    assert results["parent"] != "ok"
    assert results["unix_host"] != "ok"
