"""The stdlib-only launcher: in-process with a fake OS, then for real.

In-process tests drive ``launcher.main`` through ``FakeOS``: every OS call
the launcher makes (syscall, ioctl, prctl, open, connect, fork, execvp,
wait4, _exit, signal reset) is recorded and scripted, so the isolation
order, the fail-closed rules and the child's exec path are covered without
confining or forking the test process. The report fd is a real pipe.

The real tests run ``python -I -S launcher.py`` under ``unshare -rn -p -f``
with Landlock on this host. They skip when the host cannot sandbox, unless
``REQUIRE_NETWORK_SANDBOX=1`` or ``REQUIRE_FS_SANDBOX=1`` turns the skip
into a failure (CI sets both).
"""

from __future__ import annotations

import ast
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


def test_landlock_rules_cover_writable_dirs_shm_and_dev_null(tmp_path: Path) -> None:
    """
    GIVEN a writable dir, a writable file and /dev/shm present
    WHEN the rules are listed for ABI 3
    THEN dirs get the full mask, files and /dev/null only write and truncate
    """
    target = tmp_path / "out.txt"
    target.write_text("")
    full, file_mask = launcher.handled_access_fs(3), launcher.file_access_fs(3)

    rules = launcher.landlock_rules([str(tmp_path), str(target)], shm="/shm", abi=3)
    without = launcher.landlock_rules([str(tmp_path)], shm=None, abi=3)

    assert rules == [
        (str(tmp_path), full),
        (str(target), file_mask),
        ("/shm", full),
        ("/dev/null", file_mask),
    ]
    assert without == [(str(tmp_path), full), ("/dev/null", file_mask)]


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


class FakeOS:
    """Records every OS call and replays scripted results."""

    def __init__(
        self,
        *,
        platform: str = "linux",
        abi: int = 7,
        fail: dict[str, OSError] | None = None,
        probe_error: OSError | None = EACCES,
        connect_error: OSError | None = ECONNREFUSED,
        pid: int = 4242,
        status: int = 3 << 8,
        exec_error: Exception = ENOENT,
        probe_redirect: Path | None = None,
    ) -> None:
        self.platform = platform
        self.abi = abi
        self.fail = fail or {}
        self.probe_error = probe_error
        self.connect_error = connect_error
        self.pid = pid
        self.status = status
        self.exec_error = exec_error
        self.probe_redirect = probe_redirect
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
        self.calls.append(("prctl", option, arg2))
        self._maybe_fail("prctl")
        return 0

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

    def fork(self) -> int:
        self.calls.append(("fork",))
        return self.pid

    def execvp(self, file: str, args: list[str]) -> NoReturn:
        self.calls.append(("execvp", file, tuple(args)))
        raise self.exec_error

    def wait4(self, pid: int, options: int) -> tuple[int, int, resource.struct_rusage]:
        self.calls.append(("wait4", pid, options))
        return pid, self.status, rusage()

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
            open=self.open,
            connect=self.connect,
            fork=self.fork,
            execvp=self.execvp,
            wait4=self.wait4,
            exit=self.exit,
            reset_signals=self.reset_signals,
        )


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
    THEN lo comes up, no_new_privs, Landlock, the write probe and the
        connect probe run in that order before the fork; the report carries
        the raw rusage, exit 3 and both flags true; the launcher exits 0
    """
    fake = FakeOS()

    code, report = run_main(fake, pipe, spec_json(dirs))

    assert code == 0
    assert report == {
        "wall_ns": report["wall_ns"],
        "utime": 0.25,
        "stime": 0.125,
        "maxrss": 9000,
        "exit": 3,
        "fs_isolated": True,
        "net_isolated": True,
        "error": None,
    }
    assert isinstance(report["wall_ns"], int) and report["wall_ns"] >= 0
    shm = ["open_path", "add_rule"] if os.path.isdir("/dev/shm") else []
    assert fake.names() == [
        "get_flags",
        "set_flags",
        "prctl",
        "abi",
        "create_ruleset",
        *["open_path", "add_rule"] * 3,
        *shm,
        "restrict_self",
        "probe_write",
        "connect",
        "fork",
        "wait4",
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
    assert calls["get_flags"][1] == (b"lo" + b"\0" * 14, 0)
    assert calls["set_flags"][1] == (b"lo" + b"\0" * 14, 0x48 | 1)
    assert calls["prctl"] == ("prctl", 38, 1)
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


def test_darwin_runs_only_the_self_checks(dirs: Dirs, pipe: tuple[int, int]) -> None:
    """
    GIVEN a darwin spec with both modes required (sandbox-exec applied them)
    WHEN the probe write and connect fail with EPERM
    THEN no Linux step runs and both flags are true
    """
    eperm = OSError(errno.EPERM, "Operation not permitted")
    fake = FakeOS(platform="darwin", probe_error=eperm, connect_error=eperm)

    code, report = run_main(fake, pipe, spec_json(dirs, platform="darwin"))

    assert code == 0
    assert (report["fs_isolated"], report["net_isolated"]) == (True, True)
    assert fake.names() == ["probe_write", "connect", "fork", "wait4"]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_modes_off_skip_every_isolation_step(
    dirs: Dirs, pipe: tuple[int, int], platform: str
) -> None:
    """
    GIVEN a spec with both modes off
    WHEN the launcher runs
    THEN it only forks and waits, and both flags are false
    """
    fake = FakeOS(platform=platform)

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="off", net="off", platform=platform, port=None)
    )

    assert code == 0
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert fake.names() == ["fork", "wait4"]


def test_a_signalled_workload_reports_the_negative_signal(
    dirs: Dirs, pipe: tuple[int, int]
) -> None:
    """
    GIVEN a workload killed by SIGKILL
    WHEN the launcher reports
    THEN exit is -9, as os.waitstatus_to_exitcode gives it
    """
    code, report = run_main(FakeOS(status=signal.SIGKILL), pipe, spec_json(dirs))

    assert (code, report["exit"]) == (0, -9)


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
# In-process: fail closed under required, record under best_effort
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "part", "words"),
    [
        ("get_flags", "network", "bringing up lo"),
        ("set_flags", "network", "bringing up lo"),
        ("prctl", "fs", "no_new_privs"),
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
    assert fake.names() == ["get_flags"]


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
            "prctl": OSError(errno.EINVAL, "y"),
        }
    )

    code, report = run_main(
        fake, pipe, spec_json(dirs, fs="best_effort", net="best_effort")
    )

    assert code == 0
    assert report["error"] is None
    assert (report["fs_isolated"], report["net_isolated"]) == (False, False)
    assert fake.names() == ["get_flags", "set_flags", "prctl", "fork", "wait4"]


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
    THEN it resets the signal dispositions, execs argv, says why it failed
        and exits 127 without writing a report
    """
    fake = FakeOS(pid=0)
    read, write = pipe

    with pytest.raises(ExitedError) as exited:
        launcher.main([str(write), spec_json(dirs), "--", "/no/such", "x"], fake.ops())

    assert exited.value.code == launcher.EXIT_EXEC_FAILED == 127
    assert fake.names()[-4:] == ["fork", "reset_signals", "execvp", "exit"]
    assert ("execvp", "/no/such", ("/no/such", "x")) in fake.calls
    assert "cannot execute '/no/such'" in capsys.readouterr().err
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


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux syscalls")


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
        ["unshare", "-rn", "-p", "-f", "--", "true"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if probe.returncode != 0:
        return f"unshare -rn -p -f failed: {probe.stderr.decode(errors='replace')}"
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
            launcher_argv(built, fd=write, report_port=port, argv=argv),
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
print(json.dumps(result))
"""


def probe_argv(dirs: Dirs, tmp_path: Path, port: int) -> list[str]:
    shm = f"/dev/shm/aip-test-{os.getpid()}-{time.monotonic_ns()}"
    return [
        sys.executable,
        "-c",
        PROBE_WORKLOAD,
        str(tmp_path / "outside.txt"),
        str(dirs.wt / "inside.txt"),
        shm if os.path.isdir("/dev/shm") else "-",
        str(port),
    ]


@pytest.fixture
def listener() -> Iterator[int]:
    """The parent's 127.0.0.1 listener the sandboxed run must not reach."""
    with socket.create_server(("127.0.0.1", 0), backlog=8) as server:
        yield server.getsockname()[1]


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_confines_writes_and_network(
    dirs: Dirs, tmp_path: Path, listener: int
) -> None:
    """
    GIVEN the real launcher under unshare with both modes required
    WHEN the workload writes inside and outside, and connects out and to
        its own loopback
    THEN outside is EACCES, inside, HOME, /dev/null (with O_TRUNC) and
        /dev/shm work, the parent's listener is unreachable, its own lo
        works, and the report says both are isolated
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener),
        network="required",
        fs="required",
        port=listener,
    )

    assert run.code == 0, run.err
    results = run.results()
    assert results["outside"] == "EACCES"
    assert not (tmp_path / "outside.txt").exists()
    assert results["inside"] == results["home"] == results["devnull"] == "ok"
    assert results.get("shm", "ok") == "ok"
    assert results["parent"] in ("ECONNREFUSED", "ENETUNREACH")
    assert results["own_loopback"] == "ok"
    assert run.report is not None
    assert (run.report["fs_isolated"], run.report["net_isolated"]) == (True, True)
    assert (run.report["exit"], run.report["error"]) == (0, None)


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_launcher_control_run_is_not_isolated(
    dirs: Dirs, tmp_path: Path, listener: int
) -> None:
    """
    GIVEN the same workload with both modes off (the control)
    WHEN it runs
    THEN the outside write and the parent connect succeed and both flags are
        false, so the confined run above proves something
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener),
        network="off",
        fs="off",
        port=listener,
    )

    assert run.code == 0, run.err
    assert run.results()["outside"] == run.results()["parent"] == "ok"
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
@pytest.mark.parametrize(("network", "survives"), [("required", False), ("off", True)])
def test_real_launcher_pid_namespace_kills_setsid_orphans(
    dirs: Dirs, listener: int, network: IsolationMode, survives: bool
) -> None:
    """
    GIVEN a workload that starts a setsid grandchild, waits until it runs,
        and exits while the grandchild still has 0.5 s to live
    WHEN it runs in the PID namespace (and, as the control, without one)
    THEN the orphan dies with the launcher inside the namespace, and
        without one it lives on to write its "alive" marker
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
    assert alive.exists() is survives


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
    THEN the reports say 127, 3 and 0, and /bin/true's raw maxrss (KiB) is
        under 50 MiB: the launcher keeps the RSS floor low
    """
    runs = [
        launch(dirs, argv, network="required", fs="required", port=listener)
        for argv in (
            [str(dirs.wt / "no-such-command")],
            [sys.executable, "-c", "raise SystemExit(3)"],
            ["/bin/true"],
        )
    ]

    assert [run.code for run in runs] == [0, 0, 0]
    reports = [run.report for run in runs]
    assert [r["exit"] if r else None for r in reports] == [127, 3, 0]
    assert "cannot execute" in runs[0].err
    floor = reports[2]
    assert floor is not None and isinstance(floor["maxrss"], int)
    assert 0 < floor["maxrss"] * 1024 < 50 * 1024 * 1024


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
    dirs: Dirs, tmp_path: Path, listener: int
) -> None:
    """
    GIVEN the real launcher under sandbox-exec with both modes required
    WHEN the workload writes inside and outside and connects out
    THEN outside is denied, inside, HOME and /dev/null work, the parent's
        listener is unreachable and the report says both are isolated
    """
    run = launch(
        dirs,
        probe_argv(dirs, tmp_path, listener),
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
