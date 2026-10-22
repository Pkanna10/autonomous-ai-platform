"""The process runner: strict report parsing, cross-checks, caps, fresh dirs, real runs.

In-process tests drive the pure pieces (``parse_report``, ``check_report``,
``judge``, ``kill_group``, ``drain_group``, ``reset_dirs``) and the output
pump on real pipes. The real tests run ``run_once`` on the real launcher:
unsandboxed on every platform, and under ``unshare`` and Landlock on Linux,
where they skip unless the host can sandbox (``REQUIRE_NETWORK_SANDBOX=1`` or
``REQUIRE_FS_SANDBOX=1`` turns the skip into a failure, as in
``test_launcher.py``). The darwin path is tested through the policy's
injected platform, plus one ``sandbox-exec`` run only the macOS job executes.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import resource
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import get_type_hints

import pytest

from autonomous_ai_agents.common.config import IsolationMode, Settings
from autonomous_ai_agents.execution import launcher, procrun
from autonomous_ai_agents.execution.procrun import (
    MISMATCH,
    Accounting,
    OutputCaps,
    OutputPump,
    RunFailure,
    RunOutcome,
    RunSample,
    check_report,
    drain_group,
    judge,
    kill_group,
    maxrss_scale,
    parse_report,
    reset_dirs,
    resolve_wrapper,
    run_once,
)
from autonomous_ai_agents.execution.protocols import LaunchReport
from autonomous_ai_agents.execution.sandbox import (
    UNSHARE_ARGV,
    SandboxPolicy,
    child_env,
    launcher_argv,
)

MIB = 1024 * 1024
GOOD: dict[str, object] = {
    "wall_ns": 5_000_000,
    "utime": 0.01,
    "stime": 0.002,
    "maxrss": 9000,
    "exit": 0,
    "fs_isolated": True,
    "net_isolated": True,
    "error": None,
}
OUTER = Accounting(wall_ns=5_000_000, utime=0.01, stime=0.002, maxrss=9000, exit=0)
CAPS = OutputCaps(max_output_bytes=10 * MIB, head_bytes=1000, stderr_tail_bytes=100)
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox")
darwin_only = pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec")


def encode(report: Mapping[str, object]) -> bytes:
    """The launcher's own encoding: ``json.dumps(report, sort_keys=True)``."""
    return json.dumps(report, sort_keys=True).encode()


def make_policy(
    root: Path,
    *,
    network: IsolationMode = "required",
    fs: IsolationMode = "required",
    platform: str = "linux",
) -> SandboxPolicy:
    return SandboxPolicy(
        network=network,
        fs=fs,
        writable=(root / "wt", root / "scratch"),
        probe_dir=root / "probe",
        platform=platform,
    )


# ---------------------------------------------------------------------------
# maxrss units and caps
# ---------------------------------------------------------------------------


def test_maxrss_scale_is_kib_on_linux_and_bytes_on_darwin() -> None:
    """
    GIVEN the two supported platforms
    WHEN their ru_maxrss unit is asked for
    THEN Linux reports KiB (x1024) and darwin bytes (x1)
    """
    assert maxrss_scale("linux") == 1024
    assert maxrss_scale("darwin") == 1


def test_maxrss_scale_refuses_an_unknown_platform() -> None:
    with pytest.raises(ValueError, match="win32"):
        maxrss_scale("win32")


def test_output_caps_come_from_settings() -> None:
    """
    GIVEN the default settings and a custom Settings object
    WHEN OutputCaps.from_settings reads them
    THEN the three output limits are copied verbatim
    """
    assert OutputCaps.from_settings() == OutputCaps(
        max_output_bytes=256 * MIB, head_bytes=64 * 1024, stderr_tail_bytes=8 * 1024
    )
    custom = Settings(MAX_OUTPUT_BYTES=10, OUTPUT_HEAD_BYTES=3, STDERR_TAIL_BYTES=2)
    assert OutputCaps.from_settings(custom) == OutputCaps(10, 3, 2)


@pytest.mark.parametrize(
    "values", [(0, 1, 1), (1, 0, 1), (1, 1, 0), (-5, 1, 1)], ids=str
)
def test_output_caps_refuse_values_below_one(values: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        OutputCaps(*values)


# ---------------------------------------------------------------------------
# Strict report parsing
# ---------------------------------------------------------------------------


def test_report_keys_match_the_launch_report_contract() -> None:
    assert set(get_type_hints(LaunchReport)) == procrun.REPORT_KEYS


def test_parse_report_accepts_the_launchers_own_format() -> None:
    """
    GIVEN a report encoded exactly as the launcher writes it (and a refusal)
    WHEN it is parsed
    THEN every field comes back with its type, a negative signal exit included
    """
    assert parse_report(encode(GOOD)) == GOOD
    signalled = {**GOOD, "exit": -9, "utime": 0.0, "error": "x"}
    assert parse_report(encode(signalled)) == signalled


def _replace(key: str, raw: bytes) -> bytes:
    """GOOD with one value replaced by raw JSON text."""
    text = encode({**GOOD, key: "@@"}).replace(b'"@@"', raw)
    return text


MALFORMED: list[tuple[bytes, str]] = [
    (b"", "malformed"),
    (b"not json", "malformed"),
    (b"\xff\xfe{}", "malformed"),
    (encode(GOOD) + encode(GOOD), "Extra data"),
    (encode(GOOD) + b" trailing", "Extra data"),
    (b"[1, 2]", "exactly the keys"),
    (b'"text"', "exactly the keys"),
    (encode({k: v for k, v in GOOD.items() if k != "error"}), "exactly the keys"),
    (encode({**GOOD, "forged": True}), "exactly the keys"),
    (encode(GOOD).replace(b'{"error"', b'{"exit": 3, "error"'), "duplicate key"),
    (_replace("utime", b"NaN"), "NaN"),
    (_replace("stime", b"Infinity"), "Infinity"),
    (_replace("utime", b"-Infinity"), "-Infinity"),
    (_replace("utime", b"1e400"), "utime must be a finite, non-negative float"),
    (_replace("utime", b"1"), "utime must be a finite, non-negative float"),
    (_replace("stime", b"-0.5"), "stime must be a finite, non-negative float"),
    (_replace("utime", b"true"), "utime must be a finite, non-negative float"),
    (_replace("wall_ns", b"true"), "wall_ns must be a non-negative integer"),
    (_replace("wall_ns", b"1.5"), "wall_ns must be a non-negative integer"),
    (_replace("wall_ns", b"-1"), "wall_ns must be a non-negative integer"),
    (_replace("maxrss", b"-1"), "maxrss must be a non-negative integer"),
    (_replace("maxrss", b'"9000"'), "maxrss must be a non-negative integer"),
    (_replace("exit", b"true"), "exit must be"),
    (_replace("exit", b"1.0"), "exit must be"),
    (_replace("exit", b"256"), "exit must be"),
    (_replace("exit", str(-signal.NSIG).encode()), "exit must be"),
    (_replace("fs_isolated", b"1"), "fs_isolated must be a boolean"),
    (_replace("net_isolated", b'"true"'), "net_isolated must be a boolean"),
    (_replace("error", b"5"), "error must be a string or null"),
    (_replace("error", b"{}"), "error must be a string or null"),
]


@pytest.mark.parametrize(("data", "fragment"), MALFORMED)
def test_parse_report_refuses_malformed_reports(data: bytes, fragment: str) -> None:
    """
    GIVEN a report that is not exactly one well-typed LaunchReport object:
        not JSON, not UTF-8, two objects, trailing data, missing, extra or
        duplicate keys, NaN or infinite numbers, bools for numbers, ints for
        flags, negative counters, an exit code outside the status range
    WHEN it is parsed
    THEN RunFailure says it is malformed and why
    """
    with pytest.raises(RunFailure) as caught:
        parse_report(data)

    assert caught.value.reason.startswith("malformed measurement report")
    assert fragment in caught.value.reason


def test_parse_report_accepts_the_exit_code_bounds() -> None:
    for code in (255, 1 - signal.NSIG, 125, 127):
        assert parse_report(encode({**GOOD, "exit": code}))["exit"] == code


# ---------------------------------------------------------------------------
# Cross-checks against the outer accounting
# ---------------------------------------------------------------------------


def test_check_report_accepts_a_report_inside_the_outer_accounting(
    tmp_path: Path,
) -> None:
    """
    GIVEN a report equal to the outer accounting (the boundary), and one whose
        CPU time is just inside the documented epsilon
    WHEN it is cross-checked
    THEN both pass
    """
    policy = make_policy(tmp_path)
    report = parse_report(encode(GOOD))
    check_report(report, OUTER, policy)
    slack = procrun.CPU_EPSILON_S * 0.9
    tight = Accounting(
        wall_ns=5_000_000, utime=0.01 - slack, stime=0.002, maxrss=9000, exit=0
    )
    check_report(report, tight, policy)


def _outer(**changes: float) -> Accounting:
    values: dict[str, float] = {
        "wall_ns": OUTER.wall_ns,
        "utime": OUTER.utime,
        "stime": OUTER.stime,
        "maxrss": OUTER.maxrss,
        "exit": OUTER.exit,
    }
    values.update(changes)
    return Accounting(
        wall_ns=int(values["wall_ns"]),
        utime=values["utime"],
        stime=values["stime"],
        maxrss=int(values["maxrss"]),
        exit=int(values["exit"]),
    )


@pytest.mark.parametrize(
    "outer",
    [
        _outer(wall_ns=4_999_999),
        _outer(utime=0.01 - 2 * 1e-3),
        _outer(stime=0.0, utime=0.0),
        _outer(maxrss=8999),
        _outer(exit=3),
        _outer(exit=125),
    ],
    ids=["wall", "cpu", "no-cpu", "maxrss", "exit", "exit-125"],
)
def test_check_report_refuses_a_report_beyond_the_outer_accounting(
    tmp_path: Path, outer: Accounting
) -> None:
    """
    GIVEN a report claiming more wall time, CPU time (beyond the epsilon) or
        memory than the wrapper's own accounting, or another exit status
    WHEN it is cross-checked
    THEN RunFailure says the report does not match the process accounting
    """
    with pytest.raises(RunFailure) as caught:
        check_report(parse_report(encode(GOOD)), outer, make_policy(tmp_path))

    assert caught.value.reason == MISMATCH


@pytest.mark.parametrize(
    ("report_exit", "wrapper_exit", "fits"),
    [
        (-9, 137, True),
        (-9, -9, True),
        (-9, 9, False),
        (137, -9, True),
        (-15, 143, True),
    ],
)
def test_a_signal_death_maps_to_128_plus_signal_on_both_sides(
    tmp_path: Path, report_exit: int, wrapper_exit: int, fits: bool
) -> None:
    """
    GIVEN a workload killed by a signal (report exit -N) and a wrapper that
        exits 128+N (the launcher's own status) or was itself signalled
    WHEN the exit statuses are compared
    THEN both sides map a signal to 128+signal before comparing
    """
    report = parse_report(encode({**GOOD, "exit": report_exit}))
    outer = _outer(exit=wrapper_exit)
    if fits:
        check_report(report, outer, make_policy(tmp_path))
    else:
        with pytest.raises(RunFailure, match="does not match"):
            check_report(report, outer, make_policy(tmp_path))


@pytest.mark.parametrize(("network", "fs"), [("off", "required"), ("required", "off")])
def test_check_report_refuses_an_isolation_flag_for_a_mode_that_is_off(
    tmp_path: Path, network: IsolationMode, fs: IsolationMode
) -> None:
    """
    GIVEN a report claiming isolation for a part whose mode is off (the
        launcher never reports that)
    WHEN it is cross-checked
    THEN it does not match
    """
    with pytest.raises(RunFailure) as caught:
        check_report(
            parse_report(encode(GOOD)),
            OUTER,
            make_policy(tmp_path, network=network, fs=fs),
        )
    assert caught.value.reason == MISMATCH


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_check_report_compares_raw_maxrss_on_every_platform(
    tmp_path: Path, platform: str
) -> None:
    """
    GIVEN the report and the wrapper's rusage, both in the platform's own
        ru_maxrss unit
    WHEN they are compared on either platform
    THEN the raw numbers decide (scaling both sides would change nothing)
    """
    policy = make_policy(tmp_path, platform=platform)
    check_report(parse_report(encode(GOOD)), OUTER, policy)
    with pytest.raises(RunFailure, match="does not match"):
        check_report(parse_report(encode(GOOD)), _outer(maxrss=8999), policy)


# ---------------------------------------------------------------------------
# judge: from a finished run to a sample or a failure
# ---------------------------------------------------------------------------


def finished(
    report: bytes | None = None,
    *,
    outer: Accounting = OUTER,
    report_complete: bool = True,
    outputs_complete: bool = True,
    group_drained: bool = True,
    timed_out: bool = False,
    overflow: str | None = None,
    stderr_tail: bytes = b"tail",
) -> RunOutcome:
    return RunOutcome(
        outer=outer,
        report=encode(GOOD) if report is None else report,
        report_complete=report_complete,
        outputs_complete=outputs_complete,
        group_drained=group_drained,
        timed_out=timed_out,
        timeout_s=2.5,
        overflow=overflow,
        stdout_sha256=hashlib.sha256(b"out").hexdigest(),
        stdout_head=b"out",
        stdout_bytes=3,
        stderr_tail=stderr_tail,
    )


@pytest.mark.parametrize(("platform", "scale"), [("linux", 1024), ("darwin", 1)])
def test_judge_builds_a_sample_with_scaled_maxrss(
    tmp_path: Path, platform: str, scale: int
) -> None:
    """
    GIVEN a clean run under both required modes on each platform
    WHEN it is judged
    THEN the sample carries the report's timings and exit, maxrss in bytes
        for that platform, the isolation flags and the captured output
    """
    sample = judge(finished(), make_policy(tmp_path, platform=platform))

    assert sample == RunSample(
        wall_ns=5_000_000,
        utime=0.01,
        stime=0.002,
        maxrss_bytes=9000 * scale,
        exit=0,
        fs_isolated=True,
        net_isolated=True,
        stdout_sha256=hashlib.sha256(b"out").hexdigest(),
        stdout_head=b"out",
        stdout_bytes=3,
        stderr_tail=b"tail",
        notes=(),
    )


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        (finished(timed_out=True, outer=_outer(exit=-9)), "timeout after 2.5 s"),
        (
            finished(overflow="output flood: more than 9 bytes"),
            "output flood: more than 9 bytes",
        ),
        (finished(report_complete=False), "report pipe was still open"),
        (
            finished(b"", stderr_tail=b"x\nunshare: failed: EPERM\n"),
            "unshare: failed: EPERM",
        ),
        (finished(b"", stderr_tail=b""), "no stderr"),
        (finished(b"{"), "malformed measurement report"),
        (finished(outer=_outer(wall_ns=1)), MISMATCH),
    ],
    ids=[
        "timeout",
        "flood",
        "report-open",
        "no-report",
        "silent",
        "malformed",
        "mismatch",
    ],
)
def test_judge_fails_closed(tmp_path: Path, run: RunOutcome, reason: str) -> None:
    """
    GIVEN a run that timed out, flooded, left the report pipe open, wrote no
        report (the wrapper's last stderr line is quoted), or wrote a
        malformed or mismatched one
    WHEN it is judged
    THEN RunFailure says which
    """
    with pytest.raises(RunFailure) as caught:
        judge(run, make_policy(tmp_path))

    assert reason in caught.value.reason
    assert caught.value.notes == ()


@pytest.mark.parametrize(
    "run",
    [
        finished(timed_out=True, outer=_outer(exit=-9)),
        finished(overflow="output flood"),
        finished(b"{"),
        finished(encode({**GOOD, "error": "refused"})),
    ],
    ids=["timeout", "flood", "malformed", "error"],
)
def test_judge_carries_the_run_notes_on_a_failure(
    tmp_path: Path, run: RunOutcome
) -> None:
    """
    GIVEN a failed run whose group outlived the drain cap and whose output
        pipe stayed open
    WHEN it is judged
    THEN the RunFailure still carries both notes, so the caller knows a group
        may be alive before it starts the next run
    """
    left_over = RunOutcome(
        **{**run.__dict__, "group_drained": False, "outputs_complete": False}
    )

    with pytest.raises(RunFailure) as caught:
        judge(left_over, make_policy(tmp_path))

    assert caught.value.notes == (
        "process group still alive after 3 s",
        "an output pipe was still open after the run",
    )


def test_judge_carries_only_the_run_notes_on_an_isolation_failure(
    tmp_path: Path,
) -> None:
    """
    GIVEN fs best_effort and network required, neither applied, and a group
        that outlived the drain cap
    WHEN it is judged
    THEN the failure carries the live-group note only, not the best_effort
        note of a sample that was never returned
    """
    report = encode({**GOOD, "fs_isolated": False, "net_isolated": False})
    policy = make_policy(tmp_path, network="required", fs="best_effort")

    with pytest.raises(RunFailure, match="network isolation is required") as caught:
        judge(finished(report, group_drained=False), policy)

    assert caught.value.notes == ("process group still alive after 3 s",)


def test_judge_trusts_a_report_when_the_wrapper_beat_the_watchdog(
    tmp_path: Path,
) -> None:
    """
    GIVEN the watchdog fired just after the wrapper exited on its own (exit 0,
        not SIGKILL) with a complete, valid report
    WHEN it is judged
    THEN it is a sample, not a timeout: the kill never reached the run
    """
    sample = judge(finished(timed_out=True), make_policy(tmp_path))
    assert sample.exit == 0


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        (
            finished(b"", stderr_tail=b"x\n\x1b[2J\x1b[31mIGNORE\x1b[0m\x07\n"),
            "?[2J?[31mIGNORE?[0m?",
        ),
        (
            finished(encode({**GOOD, "error": "bad\x1b[0m\x07\u0085"})),
            "launcher: bad?[0m??",
        ),
    ],
    ids=["stderr-line", "launcher-error"],
)
def test_judge_replaces_control_characters_in_quoted_text(
    tmp_path: Path, run: RunOutcome, expected: str
) -> None:
    """
    GIVEN a workload-chosen last stderr line or launcher error holding
        terminal escapes, BEL and a C1 control
    WHEN it is quoted in the RunFailure reason
    THEN every non-printable character is replaced with '?'
    """
    with pytest.raises(RunFailure) as caught:
        judge(run, make_policy(tmp_path))

    assert caught.value.reason.endswith(expected)
    assert all(char.isprintable() for char in caught.value.reason)


def test_judge_names_the_wrapper_exit_when_there_is_no_report(tmp_path: Path) -> None:
    run = finished(b"", outer=_outer(exit=1))
    with pytest.raises(RunFailure, match=r"no measurement report \(wrapper exit 1\)"):
        judge(run, make_policy(tmp_path))


@pytest.mark.parametrize(
    ("report", "fragment"),
    [
        (
            {
                **GOOD,
                "exit": 125,
                "fs_isolated": False,
                "net_isolated": False,
                "wall_ns": 0,
                "utime": 0.0,
                "stime": 0.0,
                "maxrss": 0,
                "error": "fs isolation is required but applying Landlock failed",
            },
            "launcher: fs isolation is required",
        ),
        (
            {**GOOD, "exit": 127, "error": "cannot execute 'x': No such file"},
            "launcher: cannot execute 'x'",
        ),
        ({**GOOD, "error": ""}, "launcher: "),
    ],
    ids=["refusal", "exec-failure", "empty-error"],
)
def test_judge_turns_any_report_error_into_a_run_failure(
    tmp_path: Path, report: dict[str, object], fragment: str
) -> None:
    """
    GIVEN a refusal (error, both flags false, exit 125), an exec failure
        (error, exit 127) or an empty error string
    WHEN it is judged (the wrapper exited with the same status)
    THEN RunFailure carries the launcher's text
    """
    code = report["exit"]
    assert isinstance(code, int)
    with pytest.raises(RunFailure) as caught:
        judge(finished(encode(report), outer=_outer(exit=code)), make_policy(tmp_path))

    assert caught.value.reason.startswith(fragment)


def test_judge_caps_the_error_text(tmp_path: Path) -> None:
    report = encode({**GOOD, "error": "x" * 5000})
    with pytest.raises(RunFailure) as caught:
        judge(finished(report), make_policy(tmp_path))
    assert len(caught.value.reason) < 600


@pytest.mark.parametrize(
    ("network", "fs", "flags", "part"),
    [
        ("required", "required", {"fs_isolated": False}, "fs"),
        ("required", "best_effort", {"net_isolated": False}, "network"),
    ],
)
def test_judge_refuses_a_required_part_that_was_not_isolated(
    tmp_path: Path,
    network: IsolationMode,
    fs: IsolationMode,
    flags: dict[str, object],
    part: str,
) -> None:
    run = finished(encode({**GOOD, **flags}))
    with pytest.raises(RunFailure, match=f"{part} isolation is required"):
        judge(run, make_policy(tmp_path, network=network, fs=fs))


def test_judge_records_a_weakened_best_effort_run_as_notes(tmp_path: Path) -> None:
    """
    GIVEN both modes best_effort and the launcher's weakened report (a W
        record: both flags false, error null, a stderr line)
    WHEN it is judged
    THEN the run is a sample with both flags false and one note per part,
        never a failure
    """
    report = encode({**GOOD, "fs_isolated": False, "net_isolated": False})
    policy = make_policy(tmp_path, network="best_effort", fs="best_effort")

    sample = judge(finished(report), policy)

    assert (sample.fs_isolated, sample.net_isolated) == (False, False)
    assert sample.notes == (
        "fs isolation was not applied (best_effort)",
        "network isolation was not applied (best_effort)",
    )


def test_judge_adds_no_note_for_parts_that_are_off(tmp_path: Path) -> None:
    report = encode({**GOOD, "fs_isolated": False, "net_isolated": False})
    sample = judge(finished(report), make_policy(tmp_path, network="off", fs="off"))
    assert sample.notes == ()


def test_judge_notes_a_live_group_and_an_open_output_pipe(tmp_path: Path) -> None:
    run = finished(group_drained=False, outputs_complete=False)
    sample = judge(run, make_policy(tmp_path))
    assert sample.notes == (
        "process group still alive after 3 s",
        "an output pipe was still open after the run",
    )


def test_a_workload_that_exits_125_is_a_sample_not_a_refusal(tmp_path: Path) -> None:
    """
    GIVEN a workload that itself exits 125: a normal report (error null, both
        flags true) and wrapper status 125
    WHEN it is judged
    THEN it is a sample with exit 125: status 125 alone never means refused
    """
    report = encode({**GOOD, "exit": 125})
    sample = judge(finished(report, outer=_outer(exit=125)), make_policy(tmp_path))
    assert sample.exit == 125


# ---------------------------------------------------------------------------
# Killing and draining the process group
# ---------------------------------------------------------------------------


class FakeGroup:
    """``os.killpg`` scripted: each call raises the next error, or succeeds."""

    def __init__(self, outcomes: Sequence[BaseException | None] = ()) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[int, int]] = []

    def killpg(self, pgid: int, sig: int) -> None:
        self.calls.append((pgid, sig))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome


@pytest.mark.parametrize(
    ("outcome", "alive"),
    [
        (None, True),
        (PermissionError(errno.EPERM, "zombies"), True),
        (ProcessLookupError(errno.ESRCH, "gone"), False),
    ],
)
def test_kill_group_sigkills_and_says_whether_the_group_exists(
    outcome: BaseException | None, alive: bool
) -> None:
    group = FakeGroup([outcome])
    assert kill_group(42, killpg=group.killpg) is alive
    assert group.calls == [(42, signal.SIGKILL)]


def test_drain_group_kills_until_esrch() -> None:
    """
    GIVEN a group that survives two kills (once with macOS's EPERM for a
        group of zombies) and then is gone
    WHEN it is drained
    THEN it is SIGKILLed three times, polled twice, and reported drained
    """
    group = FakeGroup([None, PermissionError(errno.EPERM, "x"), ProcessLookupError()])
    sleeps: list[float] = []

    drained = drain_group(
        7, killpg=group.killpg, sleep=sleeps.append, clock=lambda: 0.0
    )

    assert drained is True
    assert group.calls == [(7, signal.SIGKILL)] * 3
    assert len(sleeps) == 2


def test_drain_group_gives_up_after_the_cap() -> None:
    group = FakeGroup()
    times = iter([0.0, 1.0, 2.0, 3.5])
    sleeps: list[float] = []

    drained = drain_group(
        7,
        cap_s=3.0,
        killpg=group.killpg,
        sleep=sleeps.append,
        clock=lambda: next(times),
    )

    assert drained is False
    assert len(group.calls) == 3
    assert len(sleeps) == 2


# ---------------------------------------------------------------------------
# The output pump on real pipes, in-process
# ---------------------------------------------------------------------------


def feed(fd: int, data: bytes) -> threading.Thread:
    """Write ``data`` to ``fd`` on a thread, then close it (EPIPE ends it early)."""

    def write() -> None:
        view = memoryview(data)
        try:
            while view:
                view = view[os.write(fd, view) :]
        except BrokenPipeError:
            pass
        finally:
            os.close(fd)

    thread = threading.Thread(target=write, daemon=True)
    thread.start()
    return thread


class PumpPipes:
    """Three real pipes and a pump reading their read ends."""

    def __init__(self, caps: OutputCaps) -> None:
        self.out_r, self.out_w = os.pipe()
        self.err_r, self.err_w = os.pipe()
        self.rep_r, self.rep_w = os.pipe()
        self.reads = {self.out_r, self.err_r, self.rep_r}
        self.overflows = 0
        self.pump = OutputPump(
            caps,
            stdout=self.out_r,
            stderr=self.err_r,
            report=self.rep_r,
            on_overflow=self._overflowed,
        )

    def _overflowed(self) -> None:
        self.overflows += 1

    def close_reads(self) -> None:
        """Close the read ends still open (a blocked writer then gets EPIPE)."""
        while self.reads:
            os.close(self.reads.pop())


@pytest.fixture
def pipes() -> Iterator[Callable[[OutputCaps], PumpPipes]]:
    made: list[PumpPipes] = []

    def make(caps: OutputCaps) -> PumpPipes:
        made.append(PumpPipes(caps))
        return made[-1]

    yield make
    for each in made:
        each.close_reads()


def test_pump_hashes_all_stdout_and_keeps_the_head_and_the_stderr_tail(
    pipes: Callable[[OutputCaps], PumpPipes],
) -> None:
    """
    GIVEN 300 KiB of stdout (more than one pipe buffer), 20 KiB of stderr and
        a report, written concurrently
    WHEN the pump drains them to EOF
    THEN the sha256 covers the whole stdout stream, the head is its first
        head_bytes, the count is exact, stderr keeps only its last bytes, the
        report is whole and every pipe reached EOF
    """
    run = pipes(CAPS)
    stdout = bytes(range(256)) * 1200
    stderr = b"e" * 20000 + b"END"
    writers = [
        feed(run.out_w, stdout),
        feed(run.err_w, stderr),
        feed(run.rep_w, encode(GOOD)),
    ]

    run.pump.run()

    for writer in writers:
        writer.join(5)
    assert run.pump.sha256.hexdigest() == hashlib.sha256(stdout).hexdigest()
    assert bytes(run.pump.head) == stdout[:1000]
    assert run.pump.stdout_bytes == len(stdout)
    assert bytes(run.pump.tail) == stderr[-100:]
    assert run.pump.stderr_bytes == len(stderr)
    assert bytes(run.pump.report) == encode(GOOD)
    assert run.pump.open == set()
    assert (run.pump.overflow, run.overflows) == (None, 0)


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_pump_reports_an_output_flood_and_kills(
    pipes: Callable[[OutputCaps], PumpPipes], stream: str
) -> None:
    """
    GIVEN more than max_output_bytes on one stream
    WHEN the pump reads past the cap
    THEN it records "output flood", calls on_overflow (the group kill) and
        stops reading that stream
    """
    run = pipes(OutputCaps(max_output_bytes=1000, head_bytes=10, stderr_tail_bytes=10))
    flooded, quiet = (
        (run.out_w, run.err_w) if stream == "stdout" else (run.err_w, run.out_w)
    )
    os.close(quiet)
    os.close(run.rep_w)
    writer = feed(flooded, b"x" * 200_000)

    run.pump.run()

    assert run.pump.overflow == f"output flood: more than 1000 bytes on {stream}"
    assert run.overflows == 1
    run.close_reads()
    writer.join(5)
    assert not writer.is_alive()


def test_pump_caps_the_report_at_64_kib(
    pipes: Callable[[OutputCaps], PumpPipes],
) -> None:
    """
    GIVEN a report pipe flooded past 64 KiB (only a forger could write that)
    WHEN the pump reads it
    THEN it records the overflow and kills, and keeps at most the cap + one read
    """
    run = pipes(CAPS)
    os.close(run.out_w)
    os.close(run.err_w)
    writer = feed(run.rep_w, b"{" * (200 * 1024))

    run.pump.run()

    assert run.pump.overflow == "the measurement report is larger than 65536 bytes"
    assert run.overflows == 1
    assert run.rep_r in run.pump.open
    assert len(run.pump.report) <= procrun.REPORT_MAX_BYTES + 64 * 1024
    run.close_reads()
    writer.join(5)
    assert not writer.is_alive()


def test_pump_stops_at_the_deadline_when_a_pipe_stays_open(
    pipes: Callable[[OutputCaps], PumpPipes],
) -> None:
    """
    GIVEN a report pipe whose write end something keeps open
    WHEN the pump is told to finish with a short grace
    THEN it returns by the deadline, with that pipe still listed as open
    """
    run = pipes(CAPS)
    os.close(run.out_w)
    os.close(run.err_w)
    run.pump.finish(0.1)
    started = time.monotonic()

    run.pump.run()

    assert time.monotonic() - started < 2.0
    assert run.pump.open == {run.rep_r}
    os.close(run.rep_w)


# ---------------------------------------------------------------------------
# Fresh HOME/TMPDIR dirs
# ---------------------------------------------------------------------------


class Dirs:
    """A worktree, a scratch dir and a probe dir under a realpath'd root."""

    def __init__(self, root: Path) -> None:
        root = Path(os.path.realpath(root))
        self.root = root
        self.wt = root / "wt"
        self.scratch = root / "scratch"
        self.probe = root / "probe"
        for path in (self.wt, self.scratch, self.probe):
            path.mkdir()

    def policy(
        self,
        *,
        network: IsolationMode = "off",
        fs: IsolationMode = "off",
        writable: tuple[Path, ...] | None = None,
    ) -> SandboxPolicy:
        return SandboxPolicy(
            network=network,
            fs=fs,
            writable=writable or (self.wt, self.scratch),
            probe_dir=self.probe,
            platform=sys.platform,
        )


@pytest.fixture
def dirs(tmp_path: Path) -> Dirs:
    return Dirs(tmp_path)


def test_reset_dirs_creates_missing_dirs_and_their_parents(dirs: Dirs) -> None:
    home = dirs.scratch / "a" / "b" / "home"

    reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    assert home.is_dir()
    assert home.stat().st_mode & 0o777 == 0o700


def test_reset_dirs_empties_without_following_symlinks(dirs: Dirs) -> None:
    """
    GIVEN a HOME left by an earlier run with nested files, an empty dir and
        symlinks pointing at a file and a dir outside the writable area
    WHEN it is reset
    THEN HOME is empty and fresh, and the symlink targets are untouched
    """
    outside = dirs.root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    home = dirs.scratch / "home"
    (home / "deep" / "er").mkdir(parents=True)
    (home / "deep" / "er" / "f.txt").write_text("x")
    (home / "empty").mkdir()
    (home / "top.txt").write_text("y")
    (home / "to-dir").symlink_to(outside)
    (home / "deep" / "to-file").symlink_to(outside / "keep.txt")
    home.chmod(0o755)

    reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    assert list(home.iterdir()) == []
    assert home.stat().st_mode & 0o777 == 0o700
    assert (outside / "keep.txt").read_text() == "keep"


def test_reset_dirs_recreates_a_writable_dir_itself(dirs: Dirs) -> None:
    (dirs.scratch / "old").write_text("x")

    reset_dirs([dirs.scratch], dirs.policy(), cwd=dirs.wt)

    assert dirs.scratch.is_dir()
    assert list(dirs.scratch.iterdir()) == []


def test_reset_dirs_resets_parents_first(dirs: Dirs) -> None:
    """
    GIVEN a fresh dir listed before its own parent
    WHEN both are reset
    THEN the parent is reset first, so the child still exists afterwards
    """
    parent = dirs.scratch / "tmp"
    child = parent / "home"
    child.mkdir(parents=True)
    (child / "stale").write_text("x")

    reset_dirs([child, parent, child], dirs.policy(), cwd=dirs.wt)

    assert child.is_dir()
    assert list(child.iterdir()) == []
    assert list(parent.iterdir()) == [child]


@pytest.mark.parametrize("which", ["last", "middle"])
def test_reset_dirs_refuses_a_symlink(dirs: Dirs, which: str) -> None:
    """
    GIVEN an earlier run that replaced HOME (or a directory above it) with a
        symlink to a directory outside the writable area
    WHEN it is reset
    THEN RunFailure names the symlink and nothing outside is touched
    """
    outside = dirs.root / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    if which == "last":
        (dirs.scratch / "home").symlink_to(outside)
        home = dirs.scratch / "home"
    else:
        (dirs.scratch / "mid").symlink_to(outside)
        home = dirs.scratch / "mid" / "home"

    with pytest.raises(RunFailure, match="is a symlink"):
        reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    assert [p.name for p in outside.iterdir()] == ["keep.txt"]


@pytest.mark.parametrize("which", ["last", "middle"])
def test_reset_dirs_refuses_a_file(dirs: Dirs, which: str) -> None:
    (dirs.scratch / "node").write_text("x")
    home = dirs.scratch / "node" if which == "last" else dirs.scratch / "node" / "home"

    with pytest.raises(RunFailure, match="is not a directory"):
        reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    assert (dirs.scratch / "node").read_text() == "x"


def test_reset_dirs_refuses_paths_outside_the_writable_dirs(dirs: Dirs) -> None:
    """
    GIVEN a relative path, a path with '..', a path outside every writable
        dir, the worktree itself, a dir inside the worktree and a dir that
        holds the worktree
    WHEN they are reset
    THEN each is a ValueError and nothing is created
    """
    policy = dirs.policy()
    bad = [
        Path("scratch/home"),
        dirs.scratch / ".." / "escape",
        dirs.root / "elsewhere",
        dirs.wt,
        dirs.wt / "home",
    ]
    for path in bad:
        with pytest.raises(ValueError):
            reset_dirs([path], policy, cwd=dirs.wt)
    big = dirs.root / "big"
    (big / "work").mkdir(parents=True)
    wide = dirs.policy(writable=(dirs.wt, big))
    with pytest.raises(ValueError, match="overlaps"):
        reset_dirs([big], wide, cwd=big / "work")
    assert (big / "work").is_dir()
    assert not (dirs.root / "escape").exists()
    assert not (dirs.root / "elsewhere").exists()
    assert not (dirs.wt / "home").exists()


def test_reset_dirs_refuses_any_dir_in_the_writable_dir_holding_the_cwd(
    dirs: Dirs,
) -> None:
    """
    GIVEN cwd is a subdirectory of the worktree (a workload working_dir)
    WHEN a fresh dir elsewhere in the worktree is asked for
    THEN it is a ValueError: the worktree is never wiped as scratch
    """
    (dirs.wt / "sub").mkdir()
    (dirs.wt / "other").mkdir()
    (dirs.wt / "other" / "keep.py").write_text("x")

    with pytest.raises(ValueError, match="holds the working directory"):
        reset_dirs([dirs.wt / "other"], dirs.policy(), cwd=dirs.wt / "sub")

    assert (dirs.wt / "other" / "keep.py").read_text() == "x"


def test_reset_dirs_refuses_a_tree_nested_too_deep(dirs: Dirs) -> None:
    home = dirs.scratch / "home"
    deep = home
    for _ in range(procrun.MAX_RESET_DEPTH + 2):
        deep = deep / "d"
    deep.mkdir(parents=True)

    with pytest.raises(RunFailure, match="nested more than"):
        reset_dirs([home], dirs.policy(), cwd=dirs.wt)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores mode bits")
def test_reset_dirs_empties_dirs_a_run_left_without_permissions(dirs: Dirs) -> None:
    """
    GIVEN a HOME holding dirs a run left without read, write or search
        permission (mode 000, 0500, 0600), each with a file inside
    WHEN it is reset as a non-root user
    THEN the reset succeeds and HOME is empty: one run cannot break the rest
    """
    home = dirs.scratch / "home"
    for name, mode in (("locked", 0o000), ("readonly", 0o500), ("nosearch", 0o600)):
        (home / name).mkdir(parents=True)
        (home / name / "f").write_text("x")
        (home / name).chmod(mode)

    reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    assert list(home.iterdir()) == []


class LockedOpen:
    """``os.open`` and ``os.chmod`` spies: ``locked`` refuses to open until
    it was chmodded (or forever with ``stuck``), as for a mode-000 dir."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, stuck: bool) -> None:
        self.real_open, self.real_chmod = os.open, os.chmod
        self.stuck, self.unlocked = stuck, False
        self.chmods: list[tuple[str, int, bool]] = []
        monkeypatch.setattr(os, "open", self.open)
        monkeypatch.setattr(os, "chmod", self.chmod)

    def open(
        self, path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "locked" and not self.unlocked:
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return self.real_open(path, flags, mode, dir_fd=dir_fd)

    def chmod(
        self,
        path: str,
        mode: int,
        *,
        dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        self.chmods.append((path, mode, follow_symlinks))
        if self.stuck:
            raise NotImplementedError("chmod: follow_symlinks unavailable")
        self.real_chmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        self.unlocked = True


def test_reset_dirs_unlocks_a_dir_it_cannot_open(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a dir in HOME that refuses to open (as mode 000 does for non-root)
    WHEN HOME is reset
    THEN that dir is chmodded 0700 without following symlinks, then emptied
    """
    home = dirs.scratch / "home"
    (home / "locked").mkdir(parents=True)
    (home / "locked" / "f").write_text("x")
    spy = LockedOpen(monkeypatch, stuck=False)

    reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    monkeypatch.undo()
    assert spy.chmods == [("locked", 0o700, False)]
    assert list(home.iterdir()) == []


def test_reset_dirs_fails_closed_when_a_dir_cannot_be_unlocked(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = dirs.scratch / "home"
    (home / "locked").mkdir(parents=True)
    LockedOpen(monkeypatch, stuck=True)

    with pytest.raises(RunFailure, match="cannot reset fresh dir .*Permission denied"):
        reset_dirs([home], dirs.policy(), cwd=dirs.wt)


def test_reset_dirs_fails_closed_on_a_dir_it_may_not_chmod(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a dir in HOME whose mode the engine may not change (another uid's)
    WHEN HOME is reset
    THEN RunFailure, and the opened dir fd is closed again
    """
    home = dirs.scratch / "home"
    (home / "foreign").mkdir(parents=True)
    opened: list[int] = []
    real_open = os.open

    def spy_open(
        path: str, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        opened.append(real_open(path, flags, mode, dir_fd=dir_fd))
        return opened[-1]

    def refuse(fd: int, mode: int) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "fchmod", refuse)

    with pytest.raises(RunFailure, match="Operation not permitted"):
        reset_dirs([home], dirs.policy(), cwd=dirs.wt)

    monkeypatch.undo()
    for fd in opened:
        with pytest.raises(OSError, match="Bad file descriptor"):
            os.fstat(fd)


def test_reset_dirs_turns_an_os_error_into_a_run_failure(dirs: Dirs) -> None:
    missing = dirs.root / "gone"
    policy = dirs.policy(writable=(dirs.wt, missing))

    with pytest.raises(RunFailure, match="cannot reset fresh dir"):
        reset_dirs([missing / "home"], policy, cwd=dirs.wt)


# ---------------------------------------------------------------------------
# run_once: argument checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "timeout_s", [0.0, -1.0, math.nan, math.inf, threading.TIMEOUT_MAX * 2]
)
def test_run_once_refuses_a_bad_timeout(dirs: Dirs, timeout_s: float) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        run_once(["true"], dirs.wt, {}, dirs.policy(), timeout_s, CAPS)


def test_run_once_refuses_a_relative_cwd(dirs: Dirs) -> None:
    with pytest.raises(ValueError, match="cwd"):
        run_once(["true"], Path("wt"), {}, dirs.policy(), 5.0, CAPS)


# ---------------------------------------------------------------------------
# The sandbox wrapper binary: the engine's fixed path, never the child's PATH
# ---------------------------------------------------------------------------


def test_resolve_wrapper_finds_a_root_owned_system_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a fake 'true' first on the engine's own PATH
    WHEN the wrapper 'true' is resolved
    THEN it comes from the fixed system path (os.defpath): an absolute,
        root-owned file, not the fake
    """
    fake = tmp_path / "true"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

    found = resolve_wrapper("true")

    assert os.path.isabs(found) and not found.startswith(str(tmp_path))
    assert os.stat(found).st_uid == 0


def test_resolve_wrapper_refuses_a_missing_wrapper() -> None:
    with pytest.raises(RunFailure, match="'no-such-wrapper' is not installed"):
        resolve_wrapper("no-such-wrapper")


@pytest.mark.parametrize("problem", ["group-writable", "not-root-owned"])
def test_resolve_wrapper_refuses_a_file_others_could_replace(
    tmp_path: Path, problem: str
) -> None:
    """
    GIVEN a wrapper that is group-writable, or owned by a user other than root
    WHEN it is resolved from that path
    THEN RunFailure: only a root-owned file nobody else can write may hold
        the report fd and apply the sandbox
    """
    wrapper = tmp_path / "unshare"
    wrapper.write_text("#!/bin/sh\n")
    wrapper.chmod(0o775 if problem == "group-writable" else 0o755)
    if problem == "not-root-owned" and os.geteuid() == 0:
        os.chown(wrapper, 65534, -1)

    with pytest.raises(RunFailure, match="only root may write"):
        resolve_wrapper("unshare", path=str(tmp_path))


FAKE_WRAPPER = """#!/bin/sh
: > {marker}
exit 0
"""


def fake_wrapper_path(dirs: Dirs, name: str) -> tuple[dict[str, str], Path]:
    """A child env whose PATH starts with a dir holding a fake ``name``."""
    bindir, marker = dirs.root / "bin", dirs.root / "fake-wrapper-ran"
    bindir.mkdir()
    fake = bindir / name
    fake.write_text(FAKE_WRAPPER.format(marker=marker))
    fake.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}, marker


@linux_only
def test_run_once_never_takes_the_wrapper_from_the_child_path(dirs: Dirs) -> None:
    """
    GIVEN a darwin policy on Linux (wrapper sandbox-exec, absent from the
        system path) and a fake sandbox-exec first on the child env's PATH
    WHEN it runs
    THEN RunFailure says the wrapper is not installed; the fake never ran
    """
    base, marker = fake_wrapper_path(dirs, "sandbox-exec")
    env = child_env(home=dirs.scratch, tmpdir=dirs.scratch, worktree=dirs.wt, base=base)
    policy = SandboxPolicy(
        network="required",
        fs="required",
        writable=(dirs.wt, dirs.scratch),
        probe_dir=dirs.probe,
        platform="darwin",
    )

    with pytest.raises(RunFailure, match="'sandbox-exec' is not installed"):
        run_once(["/bin/true"], dirs.wt, env, policy, 30.0, CAPS)

    assert not marker.exists()


# ---------------------------------------------------------------------------
# Real runs of the real launcher, unsandboxed (every platform)
# ---------------------------------------------------------------------------


def run(
    dirs: Dirs,
    argv: Sequence[str],
    *,
    network: IsolationMode = "off",
    fs: IsolationMode = "off",
    timeout_s: float = 60.0,
    caps: OutputCaps = CAPS,
    fresh_dirs: Sequence[Path] = (),
    home: Path | None = None,
    python: str = sys.executable,
    writable: tuple[Path, ...] | None = None,
    base: Mapping[str, str] | None = None,
) -> RunSample:
    env = child_env(
        home=home or dirs.scratch, tmpdir=dirs.scratch, worktree=dirs.wt, base=base
    )
    policy = dirs.policy(network=network, fs=fs, writable=writable)
    return run_once(
        argv,
        dirs.wt,
        env,
        policy,
        timeout_s,
        caps,
        fresh_dirs=fresh_dirs,
        python=python,
    )


OUTPUT_WORKLOAD = r"""
import sys
sys.stdout.buffer.write(bytes(range(256)) * 800)
sys.stderr.buffer.write(b"e" * 20000 + b"END")
raise SystemExit(3)
"""


def test_real_run_passes_the_exit_code_and_captures_the_output(dirs: Dirs) -> None:
    """
    GIVEN a workload writing 200 KiB of stdout and 20 KiB of stderr, exit 3
    WHEN it runs once
    THEN the sample has exit 3 (a non-zero exit is not a failure here), the
        sha256 of the full stdout, its head and size, the stderr tail, and
        both flags false with no notes under modes off
    """
    sample = run(dirs, [sys.executable, "-c", OUTPUT_WORKLOAD])

    stdout = bytes(range(256)) * 800
    assert sample.exit == 3
    assert sample.stdout_sha256 == hashlib.sha256(stdout).hexdigest()
    assert sample.stdout_head == stdout[:1000]
    assert sample.stdout_bytes == len(stdout)
    assert sample.stderr_tail == (b"e" * 20000 + b"END")[-100:]
    assert (sample.fs_isolated, sample.net_isolated, sample.notes) == (False, False, ())
    assert 0 < sample.wall_ns and sample.utime + sample.stime > 0


def test_real_run_reports_a_signal_death_as_the_negative_signal(dirs: Dirs) -> None:
    killer = "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)"
    sample = run(dirs, [sys.executable, "-c", killer])
    assert sample.exit == -signal.SIGKILL


def test_real_run_of_a_workload_exiting_125_is_a_sample(dirs: Dirs) -> None:
    sample = run(dirs, [sys.executable, "-c", "raise SystemExit(125)"])
    assert sample.exit == 125


def test_real_run_maxrss_is_scaled_to_bytes(dirs: Dirs) -> None:
    """
    GIVEN /usr/bin/true (or this platform's true) under the launcher
    WHEN it runs
    THEN maxrss_bytes is a plausible byte count: above 1 MiB (the scale was
        applied on Linux) and below 50 MiB (the launcher keeps the floor low)
    """
    true = shutil.which("true")
    assert true is not None
    sample = run(dirs, [true])
    assert 1 * MIB < sample.maxrss_bytes < 50 * MIB


def test_real_run_maxrss_ignores_the_engines_own_memory(dirs: Dirs) -> None:
    """
    GIVEN the engine itself holding 200 MiB of touched memory
    WHEN /usr/bin/true runs
    THEN its maxrss stays under 50 MiB: the engine's RSS never leaks into a
        sample through fork and exec
    """
    hold = b"x" * (200 * MIB)
    engine = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    assert engine * maxrss_scale(sys.platform) >= 200 * MIB
    true = shutil.which("true")
    assert true is not None

    sample = run(dirs, [true])

    assert len(hold) == 200 * MIB
    assert sample.maxrss_bytes < 50 * MIB


def test_real_run_maxrss_tracks_the_workloads_own_allocation(dirs: Dirs) -> None:
    """
    GIVEN a workload that touches 50 MiB and a control on the same
        interpreter that allocates nothing
    WHEN both run
    THEN the maxrss difference is 50 MiB within 15% (the raw value also holds
        the interpreter's own floor)
    """
    allocate = "n = 50 * 1024 * 1024\nb = b'x' * n"
    control = run(dirs, [sys.executable, "-c", "pass"])
    allocated = run(dirs, [sys.executable, "-c", allocate])

    delta = allocated.maxrss_bytes - control.maxrss_bytes
    assert 0.85 * 50 * MIB <= delta <= 1.15 * 50 * MIB


CHILD = (
    "import sys, time\n"
    "open(sys.argv[1], 'w').close()\n"
    "time.sleep(2.0)\n"
    "open(sys.argv[2], 'w').close()"
)
"""Marks that it started, then that it survived 2 s."""


def test_real_run_times_out_and_kills_the_group(dirs: Dirs) -> None:
    """
    GIVEN a workload waiting on a child that marks its start and, 2 s later,
        that it survived
    WHEN it runs with a 1 s timeout
    THEN RunFailure says timeout after 1 s, the child had started, and it
        died with the group (no survival marker)
    """
    started, survived = dirs.wt / "started", dirs.wt / "survived"
    workload = (
        "import subprocess, sys\n"
        "subprocess.run([sys.executable, '-c', sys.argv[1], *sys.argv[2:]])"
    )
    clock = time.monotonic()

    with pytest.raises(RunFailure) as caught:
        run(
            dirs,
            [sys.executable, "-c", workload, CHILD, str(started), str(survived)],
            timeout_s=1.0,
        )

    assert caught.value.reason == "timeout after 1 s"
    assert time.monotonic() - clock < 6.0
    time.sleep(2.0)
    assert started.exists()
    assert not survived.exists()


def test_real_run_kills_an_output_flood(dirs: Dirs) -> None:
    flood = "import sys\nwhile True:\n    sys.stdout.buffer.write(b'x' * 65536)"
    caps = OutputCaps(max_output_bytes=1 * MIB, head_bytes=16, stderr_tail_bytes=16)

    with pytest.raises(RunFailure, match="^output flood: more than 1048576 bytes"):
        run(dirs, [sys.executable, "-c", flood], caps=caps, timeout_s=30.0)


def test_real_run_exec_failure_is_a_run_failure(dirs: Dirs) -> None:
    """
    GIVEN a command that does not exist
    WHEN the launcher cannot exec it (its report sets error, exit 127)
    THEN RunFailure carries the launcher's message
    """
    with pytest.raises(RunFailure, match="^launcher: cannot execute"):
        run(dirs, [str(dirs.wt / "no-such-command")])


def test_real_run_wrapper_that_cannot_start_is_a_run_failure(dirs: Dirs) -> None:
    with pytest.raises(RunFailure, match="cannot start '/nonexistent/python3'"):
        run(dirs, ["/bin/true"], python="/nonexistent/python3")


def test_real_run_in_a_missing_cwd_names_the_cwd(dirs: Dirs) -> None:
    missing = dirs.wt / "nope"
    env = child_env(home=dirs.scratch, tmpdir=dirs.scratch, worktree=dirs.wt)

    with pytest.raises(RunFailure) as caught:
        run_once(["/bin/true"], missing, env, dirs.policy(), 30.0, CAPS)

    assert f"in {missing}:" in caught.value.reason


FRESH_WORKLOAD = r"""
import os
home = os.environ["HOME"]
print(sorted(os.listdir(home)))
open(os.path.join(home, "state"), "w").close()
"""


def test_real_run_resets_fresh_dirs_before_every_launch(dirs: Dirs) -> None:
    """
    GIVEN a workload that lists HOME and leaves a file in it
    WHEN it runs twice with HOME as a fresh dir
    THEN both runs see an empty HOME: no state carries across runs
    """
    home = dirs.policy().writable[1] / "home"
    argv = [sys.executable, "-c", FRESH_WORKLOAD]

    first = run(dirs, argv, fresh_dirs=[home], home=home)
    second = run(dirs, argv, fresh_dirs=[home], home=home)

    assert first.stdout_head == second.stdout_head == b"[]\n"
    assert (home / "state").exists()


MEMO_WORKLOAD = r"""
import os
memo = os.path.join(os.environ["HOME"], "..", "memo")
print(os.path.exists(memo))
open(memo, "w").close()
"""


def test_real_run_resets_the_whole_scratch_root_when_asked(dirs: Dirs) -> None:
    """
    GIVEN a workload that leaves a memo next to HOME, in the writable scratch
        root, and reads it back on the next run
    WHEN it runs twice with the scratch root, HOME and TMPDIR as fresh dirs
    THEN neither run sees the memo: no state carries across runs anywhere
        the sandbox lets the workload write, except the worktree
    """
    scratch = dirs.policy().writable[1]
    home, tmp = scratch / "home", scratch / "tmp"
    argv = [sys.executable, "-c", MEMO_WORKLOAD]

    first = run(dirs, argv, fresh_dirs=[scratch, home, tmp], home=home)
    second = run(dirs, argv, fresh_dirs=[scratch, home, tmp], home=home)

    assert first.stdout_head == second.stdout_head == b"False\n"
    assert (scratch / "memo").exists()


def test_real_run_passes_the_probe_port_and_closes_the_listener(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN spies on the probe listener and on launcher_argv
    WHEN a run finishes
    THEN the launcher got the listener's 127.0.0.1 port, and the listener is
        closed afterwards
    """
    listeners: list[tuple[socket.socket, int]] = []
    ports: list[int | None] = []
    real_listener, real_argv = procrun._probe_listener, launcher_argv

    def listener() -> socket.socket:
        made = real_listener()
        listeners.append((made, made.getsockname()[1]))
        assert made.getsockname()[0] == "127.0.0.1"
        return made

    def argv_spy(
        policy: SandboxPolicy,
        *,
        fd: int,
        report_port: int | None,
        argv: Sequence[str],
        python: str = sys.executable,
    ) -> list[str]:
        ports.append(report_port)
        return real_argv(
            policy, fd=fd, report_port=report_port, argv=argv, python=python
        )

    monkeypatch.setattr(procrun, "_probe_listener", listener)
    monkeypatch.setattr(procrun, "launcher_argv", argv_spy)

    run(dirs, ["/bin/true"])

    [(sock, port)] = listeners
    assert ports == [port]
    assert sock.fileno() == -1


class Interrupted(BaseException):
    """Stands in for a Ctrl-C landing in the blocking wait."""


def test_real_run_interrupted_wait_kills_and_reaps_the_group(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a workload that would write a marker after 0.5 s
    WHEN the first os.wait4 is interrupted
    THEN the interruption propagates at once, the group was killed (no
        marker) and the wrapper was reaped
    """
    marker = dirs.wt / "survived"
    workload = "import sys, time\ntime.sleep(0.5)\nopen(sys.argv[1], 'w')"
    real_wait4 = os.wait4
    calls: list[int] = []

    def flaky(pid: int, options: int) -> tuple[int, int, resource.struct_rusage]:
        calls.append(pid)
        if len(calls) == 1:
            raise Interrupted
        return real_wait4(pid, options)

    monkeypatch.setattr(os, "wait4", flaky)  # the module procrun calls through

    with pytest.raises(Interrupted):
        run(dirs, [sys.executable, "-c", workload, str(marker)])

    monkeypatch.undo()
    assert len(calls) == 2
    with pytest.raises(ChildProcessError):
        os.waitpid(calls[0], os.WNOHANG)
    time.sleep(0.8)
    assert not marker.exists()


def test_real_run_interrupted_after_the_reap_still_raises_the_interrupt(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN an interrupt landing after os.wait4 reaped the wrapper but before
        its status was bound
    WHEN the recovery wait finds no child (ChildProcessError)
    THEN the original interruption propagates, not ChildProcessError or a
        TypeError, and Popen is not left polling a pid that may be reused
    """
    real_wait4 = os.wait4
    calls: list[int] = []
    procs: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        procs.append(real_popen(*args, **kwargs))  # type: ignore[call-overload]
        return procs[-1]

    def reaped(pid: int, options: int) -> tuple[int, int, resource.struct_rusage]:
        calls.append(pid)
        result = real_wait4(pid, options)
        if len(calls) == 1:
            raise Interrupted
        return result

    monkeypatch.setattr(os, "wait4", reaped)
    monkeypatch.setattr(subprocess, "Popen", popen)

    with pytest.raises(Interrupted):
        run(dirs, ["/bin/true"])

    monkeypatch.undo()
    assert len(calls) == 2
    [proc] = procs
    assert proc.returncode is not None


FORGER = """#!{python} -I
import os, sys
os.write(int(sys.argv[4]), {payload!r})
if {code!r} is None:
    os.execv({python!r}, [{python!r}, *sys.argv[1:]])
sys.exit({code!r})
"""


def forging_python(tmp_path: Path, payload: str, code: int | None) -> str:
    """A stand-in interpreter that writes ``payload`` to the report fd first.

    The launcher argv is ``python -I -S launcher.py <fd> ...``, so the report
    fd is ``argv[4]``. With ``code`` None it then execs the real launcher on
    the same argv; otherwise it exits with ``code`` without one.
    """
    script = tmp_path / "forging-python"
    script.write_text(
        FORGER.format(python=sys.executable, payload=payload.encode(), code=code)
    )
    script.chmod(0o755)
    return str(script)


def forged(**changes: object) -> str:
    report: dict[str, object] = {
        "wall_ns": 1000,
        "utime": 0.0,
        "stime": 0.0,
        "maxrss": 1,
        "exit": 0,
        "fs_isolated": False,
        "net_isolated": False,
        "error": None,
    }
    report.update(changes)
    return json.dumps(report, sort_keys=True)


def test_real_run_rejects_a_forged_second_report_object(dirs: Dirs) -> None:
    """
    GIVEN a process holding the inherited report fd that writes a well-formed
        forged report before the genuine launcher writes its own
    WHEN the run finishes
    THEN the pipe holds two objects and RunFailure says it is malformed
    """
    python = forging_python(dirs.root, forged(), None)

    with pytest.raises(RunFailure, match="^malformed measurement report: Extra data"):
        run(dirs, ["/bin/true"], python=python)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (forged(wall_ns=10**12), 0),
        (forged(utime=100.0), 0),
        (forged(maxrss=2**40), 0),
        (forged(), 3),
    ],
    ids=["wall", "cpu", "maxrss", "exit"],
)
def test_real_run_rejects_a_forged_report_beyond_the_accounting(
    dirs: Dirs, payload: str, code: int
) -> None:
    """
    GIVEN a stand-in launcher that writes one well-formed report claiming
        more wall time, CPU or memory than it used, or another exit status
    WHEN the run finishes
    THEN the outer wait4 accounting exposes it
    """
    python = forging_python(dirs.root, payload, code)

    with pytest.raises(RunFailure) as caught:
        run(dirs, ["/bin/true"], python=python)

    assert caught.value.reason == MISMATCH


ESCAPED_ORPHAN = r"""
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],
                         start_new_session=True)
print(child.pid)
"""


def test_real_run_notes_an_output_pipe_held_by_an_escaped_orphan(
    dirs: Dirs, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN network off (no PID namespace) and a workload whose setsid
        grandchild keeps stdout open (the documented limitation)
    WHEN it runs
    THEN run_once returns after the grace period instead of hanging, with a
        note that an output pipe was still open
    """
    monkeypatch.setattr(procrun, "IO_GRACE_S", 0.3)
    started = time.monotonic()

    sample = run(dirs, [sys.executable, "-c", ESCAPED_ORPHAN])

    orphan = int(sample.stdout_head)
    try:
        assert time.monotonic() - started < 5.0
        assert sample.exit == 0
        assert sample.notes == ("an output pipe was still open after the run",)
    finally:
        try:
            os.kill(orphan, signal.SIGKILL)
        except ProcessLookupError:
            pass


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


ISOLATION_WORKLOAD = r"""
import errno, sys
try:
    open(sys.argv[1], "w").close()
    print("ok")
except OSError as error:
    print(errno.errorcode[error.errno])
"""


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
@pytest.mark.parametrize("mode", ["required", "best_effort"])
def test_real_sandboxed_run_is_isolated(dirs: Dirs, mode: IsolationMode) -> None:
    """
    GIVEN both modes required (or best_effort, on a host that can isolate)
    WHEN a workload tries to write outside the writable dirs
    THEN the write is refused, the launcher's connect probe could not reach
        procrun's 127.0.0.1 listener (net_isolated), both flags are true and
        there is no note
    """
    outside = dirs.root / "outside.txt"

    sample = run(
        dirs,
        [sys.executable, "-c", ISOLATION_WORKLOAD, str(outside)],
        network=mode,
        fs=mode,
    )

    assert sample.stdout_head == b"EACCES\n"
    assert not outside.exists()
    assert (sample.fs_isolated, sample.net_isolated) == (True, True)
    assert (sample.exit, sample.notes) == (0, ())
    assert 1 * MIB < sample.maxrss_bytes < 200 * MIB


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_run_ignores_a_fake_unshare_on_the_child_path(
    dirs: Dirs,
) -> None:
    """
    GIVEN a fake unshare first on the child env's PATH
    WHEN a run under both modes required starts
    THEN the system unshare wraps it: the write outside is refused, both
        flags are true and the fake never ran
    """
    base, marker = fake_wrapper_path(dirs, "unshare")
    outside = dirs.root / "outside.txt"

    sample = run(
        dirs,
        [sys.executable, "-c", ISOLATION_WORKLOAD, str(outside)],
        network="required",
        fs="required",
        base=base,
    )

    assert sample.stdout_head == b"EACCES\n"
    assert (sample.fs_isolated, sample.net_isolated) == (True, True)
    assert not marker.exists()


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_refusal_is_a_run_failure(dirs: Dirs) -> None:
    """
    GIVEN fs required and a writable dir that does not exist, so Landlock
        cannot apply (the launcher refuses: error set, both flags false, 125)
    WHEN it runs
    THEN RunFailure carries the refusal and the workload never ran
    """
    marker = dirs.wt / "ran"

    with pytest.raises(RunFailure, match="^launcher: fs isolation is required"):
        run(
            dirs,
            [sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
            fs="required",
            writable=(dirs.wt, dirs.scratch / "missing"),
        )

    assert not marker.exists()


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_run_rejects_a_forged_second_report(dirs: Dirs) -> None:
    python = forging_python(
        dirs.root, forged(fs_isolated=True, net_isolated=True), None
    )

    with pytest.raises(RunFailure, match="^malformed measurement report: Extra data"):
        run(dirs, ["/bin/true"], python=python, network="required", fs="required")


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_timeout_kills_the_namespace(dirs: Dirs) -> None:
    """
    GIVEN both modes required and a workload whose setsid grandchild marks
        its start and, 2 s later, that it survived
    WHEN the run times out after 1 s
    THEN RunFailure says so, and the grandchild, out of the process group but
        inside the PID namespace, died with it
    """
    started, survived = dirs.wt / "started", dirs.wt / "survived"
    workload = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', sys.argv[1], *sys.argv[2:]],"
        " start_new_session=True)\n"
        "time.sleep(30)"
    )

    with pytest.raises(RunFailure, match="^timeout after 1 s$"):
        run(
            dirs,
            [sys.executable, "-c", workload, CHILD, str(started), str(survived)],
            network="required",
            fs="required",
            timeout_s=1.0,
        )

    time.sleep(2.0)
    assert started.exists()
    assert not survived.exists()


@pytest.fixture(scope="module")
def darwin_sandbox() -> None:
    """Skip (or fail under REQUIRE_*) when sandbox-exec is missing."""
    if shutil.which("sandbox-exec") is None:
        if _require():
            pytest.fail("sandbox required but sandbox-exec is not installed")
        pytest.skip("sandbox-exec is not installed")


@darwin_only
@pytest.mark.usefixtures("darwin_sandbox")
def test_real_run_under_sandbox_exec(dirs: Dirs) -> None:
    """
    GIVEN both modes required on darwin (sandbox-exec)
    WHEN a workload tries to write outside
    THEN the write is denied, both flags are true, and maxrss (bytes on
        darwin, scale 1) is plausible
    """
    outside = dirs.root / "outside.txt"

    sample = run(
        dirs,
        [sys.executable, "-c", ISOLATION_WORKLOAD, str(outside)],
        network="required",
        fs="required",
    )

    assert sample.stdout_head in (b"EPERM\n", b"EACCES\n")
    assert (sample.fs_isolated, sample.net_isolated) == (True, True)
    assert 1 * MIB < sample.maxrss_bytes < 1024 * MIB
