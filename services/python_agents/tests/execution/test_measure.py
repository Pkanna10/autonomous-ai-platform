"""Measurement: warm-ups, N timed runs, resets, fingerprints, ABAB, the test suite.

The logic runs on an injected ``run_once`` double and a recorded reset, so
every launch, its arguments and its order are asserted exactly. A few real
tests then drive the real launcher on a real git worktree: unsandboxed on
every platform and under ``unshare`` plus Landlock on Linux (skipped unless
the host can sandbox; ``REQUIRE_NETWORK_SANDBOX=1`` or ``REQUIRE_FS_SANDBOX=1``
turns the skip into a failure, as in ``test_procrun.py``). They include the
dropped ``unittest.py`` reset and real unittest and pytest summaries.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import pytest

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import RepoTamperedError
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Measurement,
    Project,
    RunStats,
    Workload,
)
from autonomous_ai_agents.execution import launcher
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.measure import (
    JUNIT_MAX_BYTES,
    JUNIT_NAME,
    SUITE_STDERR_TAIL_BYTES,
    AbabMeasured,
    Measured,
    Phase,
    baseline_test_count,
    classify_runner,
    make_phase,
    measure_abab,
    measure_workload,
    output_fingerprint,
    run_tests,
)
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.protocols import WorktreeHandle
from autonomous_ai_agents.execution.sandbox import UNSHARE_ARGV, SandboxPolicy

MIB = 1024 * 1024
CAPS = OutputCaps(max_output_bytes=64, head_bytes=16, stderr_tail_bytes=4096)
PY = "/usr/bin/python3"
SHA_A = hashlib.sha256(b"a\n").hexdigest()
SHA_B = hashlib.sha256(b"b\n").hexdigest()
UNITTEST_CMD = (PY, "-m", "unittest", "discover", "-s", "tests", "-t", ".")
PYTEST_CMD = (PY, "-m", "pytest", "-q", "tests")
linux_only = pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox")


def sample(
    *,
    wall_ns: int = 1_500_000_000,
    utime: float = 0.5,
    stime: float = 0.25,
    maxrss: int = 10 * MIB,
    exit: int = 0,
    fs: bool = True,
    net: bool = True,
    sha: str = SHA_A,
    size: int = 2,
    stderr: bytes = b"",
    notes: tuple[str, ...] = (),
) -> RunSample:
    return RunSample(
        wall_ns=wall_ns,
        utime=utime,
        stime=stime,
        maxrss_bytes=maxrss,
        exit=exit,
        fs_isolated=fs,
        net_isolated=net,
        stdout_sha256=sha,
        stdout_head=b"",
        stdout_bytes=size,
        stderr_tail=stderr,
        notes=notes,
    )


class Call(NamedTuple):
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    sandbox: SandboxPolicy
    timeout_s: float
    caps: OutputCaps
    fresh_dirs: tuple[Path, ...]


Respond = Callable[[Call], RunSample]


@dataclass
class FakeRun:
    """A ``run_once`` double: records each call, logs it, answers via ``respond``."""

    events: list[str]
    respond: Respond = lambda call: sample()
    calls: list[Call] = field(default_factory=list)
    tag: str = "run"

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
    ) -> RunSample:
        call = Call(tuple(argv), cwd, env, sandbox, timeout_s, caps, tuple(fresh_dirs))
        self.calls.append(call)
        self.events.append(self.tag)
        return self.respond(call)


def scripted(*answers: RunSample | RunFailure) -> Respond:
    """Answers in order, then the last one forever; a RunFailure is raised."""
    queue = list(answers)

    def respond(call: Call) -> RunSample:
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, RunFailure):
            raise answer
        return answer

    return respond


class Area:
    """A realpath'd worktree, scratch root and probe dir."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.realpath(root))
        self.wt = self.root / "wt"
        self.scratch = self.root / "scratch"
        self.probe = self.root / "probe"
        for path in (self.wt, self.scratch, self.probe):
            path.mkdir(parents=True)

    def phase(
        self,
        run: FakeRun,
        *,
        reset_tag: str = "reset",
        caps: OutputCaps = CAPS,
        network: IsolationMode = "required",
        fs: IsolationMode = "required",
    ) -> Phase:
        policy = SandboxPolicy(
            network=network,
            fs=fs,
            writable=(self.wt, self.scratch),
            probe_dir=self.probe,
            platform="linux",
        )
        return Phase(
            policy=policy,
            env={"HOME": str(self.scratch / "home")},
            reset=lambda: run.events.append(reset_tag),
            caps=caps,
            run=run,
        )


@pytest.fixture
def area(tmp_path: Path) -> Area:
    return Area(tmp_path)


@pytest.fixture
def events() -> list[str]:
    return []


def workload(**changes: object) -> Workload:
    fields: dict[str, object] = {
        "project_id": "p1",
        "name": "bench",
        "command": (PY, "bench.py"),
        "warmup_runs": 1,
        "runs": 5,
        "timeout_s": 42.0,
    }
    fields.update(changes)
    return Workload.model_validate(fields)


def project(test_command: tuple[str, ...] | None = UNITTEST_CMD) -> Project:
    return Project(name="demo", root_path="/srv/demo", test_command=test_command)


def by_metric(measured: Sequence[Measurement]) -> dict[str, Measurement]:
    found = {m.metric: m for m in measured}
    assert len(found) == len(measured)
    return found


# ---------------------------------------------------------------------------
# Phase construction
# ---------------------------------------------------------------------------


class RecordingGit:
    def __init__(self) -> None:
        self.resets: list[WorktreeHandle] = []

    def reset(self, handle: WorktreeHandle) -> None:
        self.resets.append(handle)


def test_make_phase_builds_the_policy_env_and_reset(tmp_path: Path) -> None:
    """
    GIVEN a worktree handle and the phase's scratch and probe paths, not yet
        created
    WHEN make_phase builds the phase with explicit modes
    THEN the policy may write the worktree and the scratch root only, probes
        the probe dir, HOME and TMPDIR sit under the scratch root, the reset
        resets that handle, and both dirs now exist (mode 0700)
    """
    root = Path(os.path.realpath(tmp_path))
    wt = root / "run1" / "trial-h1"
    wt.mkdir(parents=True)
    handle = WorktreeHandle(path=wt, gitdir=root / "gitdir", link_bytes=b"gitdir: x")
    scratch, probe = (
        root / "run1" / "_scratch" / "trial-h1",
        root / "run1" / "_probe" / "x",
    )
    git = RecordingGit()
    run = FakeRun([])

    phase = make_phase(
        git,
        handle,
        scratch=scratch,
        probe=probe,
        network="best_effort",
        fs="off",
        platform="darwin",
        base_env={"PATH": "/usr/bin:relative", "AWS_SECRET_KEY": "s"},
        run=run,
    )

    assert phase.policy == SandboxPolicy(
        network="best_effort",
        fs="off",
        writable=(wt, scratch),
        probe_dir=probe,
        platform="darwin",
    )
    assert (phase.worktree, phase.scratch) == (wt, scratch)
    assert phase.fresh_dirs == (scratch, scratch / "home", scratch / "tmp")
    assert phase.env["HOME"] == str(scratch / "home")
    assert phase.env["TMPDIR"] == str(scratch / "tmp")
    assert phase.env["PATH"] == "/usr/bin"
    assert phase.env["PYTHONPATH"] == str(wt)
    assert "AWS_SECRET_KEY" not in phase.env
    assert phase.caps == OutputCaps.from_settings()
    assert phase.run is run
    for made in (scratch, probe):
        assert made.is_dir() and made.stat().st_mode & 0o777 == 0o700
    phase.reset()
    assert git.resets == [handle]


def test_make_phase_defaults_to_the_settings_modes_and_the_real_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "NETWORK_ISOLATION", "off")
    monkeypatch.setattr(settings, "FS_ISOLATION", "best_effort")
    root = Path(os.path.realpath(tmp_path))
    (root / "wt").mkdir()
    handle = WorktreeHandle(path=root / "wt", gitdir=root / "g", link_bytes=b"")

    phase = make_phase(
        RecordingGit(), handle, scratch=root / "scratch", probe=root / "probe"
    )

    assert (phase.policy.network, phase.policy.fs) == ("off", "best_effort")
    assert phase.policy.platform == sys.platform
    assert phase.run is run_once


def test_make_phase_refuses_relative_dirs_before_creating_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = Path(os.path.realpath(tmp_path))
    handle = WorktreeHandle(path=root, gitdir=root / "g", link_bytes=b"")

    with pytest.raises(ValueError, match="must be absolute"):
        make_phase(
            RecordingGit(), handle, scratch=Path("rel-scratch"), probe=root / "p"
        )

    assert not (tmp_path / "rel-scratch").exists()


def test_a_phase_needs_exactly_the_worktree_and_the_scratch_root(area: Area) -> None:
    policy = SandboxPolicy(
        network="off",
        fs="off",
        writable=(area.wt,),
        probe_dir=area.probe,
        platform="linux",
    )

    with pytest.raises(ValueError, match="worktree and the scratch root"):
        Phase(policy=policy, env={}, reset=lambda: None, caps=CAPS)


# ---------------------------------------------------------------------------
# measure_workload: launches, resets, samples
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("warmups", "launches"), [(0, 5), (2, 7)])
def test_warmups_then_n_timed_runs_each_after_a_reset(
    area: Area, events: list[str], warmups: int, launches: int
) -> None:
    """
    GIVEN warmup_runs 0 or 2 and runs 5 (= MIN_RUNS)
    WHEN the workload is measured
    THEN run_once is launched exactly warm-ups + 5 times, each right after a
        reset, and only the 5 timed runs become samples
    """
    run = FakeRun(events)

    measured = measure_workload(area.phase(run), workload(warmup_runs=warmups))

    assert events == ["reset", "run"] * launches
    assert all(len(m.samples) == 5 for m in measured.measurements)


@pytest.mark.parametrize(("min_runs", "runs", "expected"), [(7, 5, 7), (5, 9, 9)])
def test_n_is_the_larger_of_min_runs_and_the_workload_runs(
    area: Area,
    events: list[str],
    monkeypatch: pytest.MonkeyPatch,
    min_runs: int,
    runs: int,
    expected: int,
) -> None:
    monkeypatch.setattr(settings, "MIN_RUNS", min_runs)
    run = FakeRun(events)

    measured = measure_workload(area.phase(run), workload(warmup_runs=0, runs=runs))

    assert len(run.calls) == expected
    assert {m.stats.n for m in measured.measurements} == {expected}


def test_every_launch_gets_the_phase_sandbox_and_fresh_scratch(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN a workload with inputs and a working_dir
    WHEN it is measured
    THEN each launch runs the command verbatim (inputs are never passed) in
        <worktree>/<working_dir>, with the phase's env, policy and caps, the
        workload's timeout, and the whole scratch root plus HOME and TMPDIR
        as fresh dirs
    """
    (area.wt / "sub").mkdir()
    phase = area.phase(run := FakeRun(events))

    measure_workload(phase, workload(working_dir="sub", inputs={"n": 3}))

    expected = Call(
        argv=(PY, "bench.py"),
        cwd=area.wt / "sub",
        env=phase.env,
        sandbox=phase.policy,
        timeout_s=42.0,
        caps=CAPS,
        fresh_dirs=(area.scratch, area.scratch / "home", area.scratch / "tmp"),
    )
    assert run.calls == [expected] * 6


def test_a_repo_relative_command_resolves_inside_the_worktree(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events)

    measure_workload(area.phase(run), workload(command=("scripts/bench", "-q")))

    assert run.calls[0].argv == (str(area.wt / "scripts" / "bench"), "-q")


@pytest.mark.parametrize("what", ["command", "working_dir"])
def test_a_command_or_working_dir_escaping_the_worktree_is_a_run_failure(
    area: Area, events: list[str], what: str
) -> None:
    """
    GIVEN a committed symlink in the worktree pointing outside it
    WHEN it is used as the working dir or the command
    THEN the run fails before anything is launched
    """
    outside = area.root / "outside"
    outside.mkdir()
    (area.wt / "link").symlink_to(outside)
    changes: dict[str, object] = (
        {"command": ("link/bench",)} if what == "command" else {"working_dir": "link"}
    )
    run = FakeRun(events)

    with pytest.raises(RunFailure, match="resolves outside the worktree"):
        measure_workload(area.phase(run), workload(**changes))

    assert run.calls == []


@pytest.mark.parametrize("name", ["../bench", "~/bench", "C:bench", "be\0nch"])
@pytest.mark.parametrize("where", ["workload", "test command"])
def test_a_command_that_is_no_path_inside_the_worktree_is_a_run_failure(
    area: Area, events: list[str], name: str, where: str
) -> None:
    """
    GIVEN a relative argv[0] with '..', '~', a drive letter or a NUL byte
    WHEN it is the workload's command or the test command
    THEN a RunFailure (the error callers map to a failed trial) is raised,
        not a bare ValueError, and nothing is launched
    """
    run = FakeRun(events)

    with pytest.raises(RunFailure, match="is not a path inside the worktree"):
        if where == "workload":
            measure_workload(area.phase(run), workload(command=(name, "-q")))
        else:
            run_tests(area.phase(run), project((name, "-q")), [workload()])

    assert run.calls == []


def test_samples_become_wall_cpu_and_peak_rss_measurements(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN runs reporting different wall times, CPU times and maxrss
    WHEN the workload is measured for a trial
    THEN exactly three rows come back (never throughput_per_s): wall seconds,
        user+system CPU seconds and peak RSS bytes, sample by sample, with
        the trial id and the workload id
    """
    answers = [
        sample(wall_ns=(i + 1) * 100_000_000, utime=0.1 * i, stime=0.01, maxrss=i * MIB)
        for i in range(6)
    ]
    run = FakeRun(events, scripted(*answers))
    load = workload()

    measured = measure_workload(area.phase(run), load, trial_id="t1")

    rows = by_metric(measured.measurements)
    assert set(rows) == {METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES}
    timed = answers[1:]  # the first launch is the warm-up
    assert rows[METRIC_WALL_TIME_S].samples == tuple(s.wall_ns / 1e9 for s in timed)
    assert rows[METRIC_CPU_TIME_S].samples == tuple(s.utime + s.stime for s in timed)
    assert rows[METRIC_PEAK_RSS_BYTES].samples == tuple(
        float(s.maxrss_bytes) for s in timed
    )
    assert rows[METRIC_WALL_TIME_S].stats == RunStats.from_samples(
        rows[METRIC_WALL_TIME_S].samples, unit="s"
    )
    assert rows[METRIC_CPU_TIME_S].stats.unit == "s"
    assert rows[METRIC_PEAK_RSS_BYTES].stats.unit == "bytes"
    for row in rows.values():
        assert (row.workload_id, row.trial_id) == (load.id, "t1")


def test_hardware_records_the_host_the_modes_and_the_isolated_runs(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN best_effort modes, where two of five timed runs were not
        fs-isolated and one was not net-isolated (warm-ups do not count)
    WHEN the workload is measured
    THEN every row's hardware names the OS, machine, Python, CPU count, both
        modes and how many timed runs each part isolated
    """
    run = FakeRun(
        events,
        scripted(
            sample(fs=False, net=False),
            sample(fs=False),
            sample(fs=False, net=False),
            sample(),
        ),
    )
    phase = area.phase(run, network="best_effort", fs="best_effort")

    measured = measure_workload(phase, workload())

    expected = {
        "os": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "network_isolation": "best_effort",
        "fs_isolation": "best_effort",
        "runs": 5,
        "fs_isolated_runs": 3,
        "net_isolated_runs": 4,
    }
    assert [m.hardware for m in measured.measurements] == [expected] * 3
    for row in measured.measurements:
        assert type(row.hardware["fs_isolated_runs"]) is int
        assert type(row.hardware["net_isolated_runs"]) is int


# ---------------------------------------------------------------------------
# Failures and notes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "says"), [(3, "exit status 3"), (-9, "signal 9")], ids=["exit", "signal"]
)
def test_a_non_zero_exit_is_a_run_failure_with_the_last_stderr_line(
    area: Area, events: list[str], code: int, says: str
) -> None:
    """
    GIVEN a third timed run that exits non-zero after a run that left a note
    WHEN the workload is measured
    THEN RunFailure names the workload and the run, the status and the last
        stderr line (control characters replaced), carries every note so
        far, and no further run starts
    """
    run = FakeRun(
        events,
        scripted(
            sample(),
            sample(notes=("process group still alive after 3 s",)),
            sample(),
            sample(exit=code, stderr=b"Traceback\nValueError: bad\x1b[0m\n"),
        ),
    )

    with pytest.raises(RunFailure) as caught:
        measure_workload(area.phase(run), workload())

    assert caught.value.reason == (
        f"workload 'bench' run 3/5: the command ended with {says}: ValueError: bad?[0m"
    )
    assert caught.value.notes == (
        "workload 'bench' run 1/5: process group still alive after 3 s",
    )
    assert len(run.calls) == 4


def test_a_warm_up_failure_is_a_run_failure_too(area: Area, events: list[str]) -> None:
    run = FakeRun(events, scripted(sample(exit=1)))

    with pytest.raises(RunFailure, match=r"^workload 'bench' warm-up 1/2: .*no stderr"):
        measure_workload(area.phase(run), workload(warmup_runs=2))


def test_a_run_failure_keeps_its_reason_and_every_note(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN a timeout (RunFailure with its own note) on the second timed run,
        after a run that left a note
    WHEN the workload is measured
    THEN the RunFailure is re-raised with the run named and both notes
    """
    run = FakeRun(
        events,
        scripted(
            sample(notes=("fs isolation was not applied (best_effort)",)),
            sample(),
            RunFailure("timeout after 42 s", ("an output pipe was still open",)),
        ),
    )

    with pytest.raises(RunFailure) as caught:
        measure_workload(area.phase(run), workload())

    assert caught.value.reason == "workload 'bench' run 2/5: timeout after 42 s"
    assert caught.value.notes == (
        "workload 'bench' warm-up 1/1: fs isolation was not applied (best_effort)",
        "workload 'bench' run 2/5: an output pipe was still open",
    )


def test_every_sample_note_reaches_the_caller_once(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample(), sample(notes=("n1", "n1")), sample()))

    measured = measure_workload(area.phase(run), workload())

    assert measured.notes == ("workload 'bench' run 1/5: n1",)


def test_a_tampered_worktree_propagates_from_the_reset(area: Area) -> None:
    def tampered() -> None:
        raise RepoTamperedError("wt/.git changed")

    run = FakeRun([])
    phase = Phase(
        policy=area.phase(run).policy, env={}, reset=tampered, caps=CAPS, run=run
    )

    with pytest.raises(RepoTamperedError):
        measure_workload(phase, workload())

    assert run.calls == []


# ---------------------------------------------------------------------------
# Output fingerprints
# ---------------------------------------------------------------------------


def test_output_fingerprint_is_length_prefixed_and_covers_the_file() -> None:
    plain = output_fingerprint(2, SHA_A, None)
    with_file = output_fingerprint(2, SHA_A, (2, SHA_B))

    assert (
        plain
        == hashlib.sha256(
            b"aip-output/1" + (2).to_bytes(8, "big") + bytes.fromhex(SHA_A)
        ).hexdigest()
    )
    assert (
        with_file
        == hashlib.sha256(
            b"aip-output/1"
            + (2).to_bytes(8, "big")
            + bytes.fromhex(SHA_A)
            + b"file"
            + (2).to_bytes(8, "big")
            + bytes.fromhex(SHA_B)
        ).hexdigest()
    )
    assert len({plain, with_file, output_fingerprint(3, SHA_A, None)}) == 3


def test_the_fingerprint_is_the_one_all_timed_runs_agree_on(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN a warm-up with other output and five timed runs with equal stdout
    WHEN the workload is measured
    THEN all three rows carry the agreed fingerprint (warm-ups do not vote)
    """
    run = FakeRun(events, scripted(sample(sha=SHA_B), sample(sha=SHA_A)))

    measured = measure_workload(area.phase(run), workload())

    expected = output_fingerprint(2, SHA_A, None)
    assert {m.output_fingerprint for m in measured.measurements} == {expected}


def test_runs_that_disagree_have_no_fingerprint_and_a_note(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN timed runs whose stdout differs in one run (no guardrail needed)
    WHEN the workload is measured
    THEN no row has a fingerprint and a note says the output was not
        deterministic, so the caller can warn even without an equivalence
        guardrail
    """
    run = FakeRun(events, scripted(sample(), sample(), sample(sha=SHA_B), sample()))

    measured = measure_workload(area.phase(run), workload())

    assert {m.output_fingerprint for m in measured.measurements} == {None}
    assert measured.notes == (
        "workload 'bench': the 5 timed runs did not agree on one output; "
        "no output fingerprint",
    )


def test_abab_names_the_side_whose_runs_disagree(
    tmp_path: Path, events: list[str]
) -> None:
    a_run = FakeRun(events, tag="A")
    b_run = FakeRun(events, scripted(sample(), sample(sha=SHA_B), sample()), tag="B")
    a, b = Area(tmp_path / "a").phase(a_run), Area(tmp_path / "b").phase(b_run)

    result = measure_abab(a, b, workload(warmup_runs=0))

    assert {m.output_fingerprint for m in result.a} == {
        output_fingerprint(2, SHA_A, None)
    }
    assert {m.output_fingerprint for m in result.b} == {None}
    assert result.notes == (
        "workload 'bench' B: the 5 timed runs did not agree on one output; "
        "no output fingerprint",
    )


def writes_output(area: Area, contents: Sequence[bytes]) -> Respond:
    """Each launch writes the next of ``contents`` to <wt>/out/result.txt."""
    queue = list(contents)

    def respond(call: Call) -> RunSample:
        target = area.wt / "out" / "result.txt"
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(queue.pop(0))
        return sample()

    return respond


def test_the_declared_output_file_joins_the_fingerprint(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, writes_output(area, [b"warm"] + [b"42\n"] * 5))

    measured = measure_workload(area.phase(run), workload(output_file="out/result.txt"))

    digest = hashlib.sha256(b"42\n").hexdigest()
    expected = output_fingerprint(2, SHA_A, (3, digest))
    assert {m.output_fingerprint for m in measured.measurements} == {expected}


def test_an_output_file_that_differs_between_runs_gives_no_fingerprint(
    area: Area, events: list[str]
) -> None:
    contents = [b"w", b"1", b"1", b"2", b"1", b"1"]
    run = FakeRun(events, writes_output(area, contents))

    measured = measure_workload(area.phase(run), workload(output_file="out/result.txt"))

    assert {m.output_fingerprint for m in measured.measurements} == {None}
    assert measured.notes == (
        "workload 'bench': the 5 timed runs did not agree on one output; "
        "no output fingerprint",
    )


def test_an_output_file_missing_in_one_run_names_that_run(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN an output file that only the third timed run fails to write
    WHEN the workload is measured
    THEN the note names run 3/5, and the runs' disagreement is noted too
    """
    target = area.wt / "out.txt"
    launches: list[int] = []

    def respond(call: Call) -> RunSample:
        launches.append(1)
        target.unlink(missing_ok=True)
        if len(launches) != 4:  # launch 1 is the warm-up, 4 is timed run 3
            target.write_bytes(b"ok")
        return sample()

    run = FakeRun(events, respond)

    measured = measure_workload(area.phase(run), workload(output_file="out.txt"))

    assert {m.output_fingerprint for m in measured.measurements} == {None}
    assert measured.notes == (
        "workload 'bench' run 3/5: output file 'out.txt' is missing; "
        "no output fingerprint",
        "workload 'bench': the 5 timed runs did not agree on one output; "
        "no output fingerprint",
    )


def plant(area: Area, kind: str) -> None:
    """Leave <wt>/out.txt as something the fingerprint must refuse."""
    target = area.wt / "out.txt"
    if kind == "escaping symlink":
        (area.root / "secret.txt").write_text("secret")
        target.symlink_to(area.root / "secret.txt")
    elif kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "too large":
        target.write_bytes(b"x" * (CAPS.max_output_bytes + 1))


@pytest.mark.parametrize(
    ("kind", "says"),
    [
        ("missing", "is missing"),
        ("escaping symlink", "resolves outside the worktree"),
        ("directory", "is not a regular file"),
        ("fifo", "is not a regular file"),
        ("too large", f"is larger than {CAPS.max_output_bytes} bytes"),
    ],
)
def test_an_unusable_output_file_gives_no_fingerprint_and_a_note(
    area: Area, events: list[str], kind: str, says: str
) -> None:
    """
    GIVEN a declared output file that is missing, a symlink out of the
        worktree, a directory, a FIFO or larger than the output cap
    WHEN the workload is measured
    THEN no row has a fingerprint, the file is never read through the link
        or blocked on, and each timed run's note says why
    """
    plant(area, kind)
    run = FakeRun(events)

    measured = measure_workload(area.phase(run), workload(output_file="out.txt"))

    assert {m.output_fingerprint for m in measured.measurements} == {None}
    assert measured.notes == tuple(
        f"workload 'bench' run {i}/5: output file 'out.txt' {says}; "
        "no output fingerprint"
        for i in range(1, 6)
    )


def test_an_output_symlink_inside_the_worktree_is_followed(
    area: Area, events: list[str]
) -> None:
    (area.wt / "real.txt").write_bytes(b"ok")
    (area.wt / "out.txt").symlink_to(area.wt / "real.txt")
    run = FakeRun(events)

    measured = measure_workload(area.phase(run), workload(output_file="out.txt"))

    digest = hashlib.sha256(b"ok").hexdigest()
    expected = output_fingerprint(2, SHA_A, (2, digest))
    assert {m.output_fingerprint for m in measured.measurements} == {expected}


def test_an_unreadable_output_file_gives_no_fingerprint(
    area: Area, events: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (area.wt / "out.txt").write_bytes(b"ok")
    real_open = os.open

    def refuse(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fsdecode(path).endswith("out.txt"):
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", refuse)
    run = FakeRun(events)

    measured = measure_workload(
        area.phase(run), workload(output_file="out.txt", runs=5, warmup_runs=0)
    )

    assert measured.notes == tuple(
        f"workload 'bench' run {i}/5: output file 'out.txt' cannot be opened "
        "(Permission denied); no output fingerprint"
        for i in range(1, 6)
    )


# ---------------------------------------------------------------------------
# measure_abab
# ---------------------------------------------------------------------------


def test_abab_interleaves_the_two_phases_with_a_reset_before_each_run(
    tmp_path: Path, events: list[str]
) -> None:
    """
    GIVEN phase A (base) and phase B (combined tip) and one warm-up
    WHEN a workload is measured ABAB
    THEN warm-ups and timed runs alternate A, B, each after its own phase's
        reset; each side gets its own rows, fingerprint and trial id, and
        the notes name the side
    """
    a_area, b_area = Area(tmp_path / "a"), Area(tmp_path / "b")
    a_run = FakeRun(events, scripted(sample(sha=SHA_A, notes=("na",))), tag="A")
    b_run = FakeRun(events, scripted(sample(sha=SHA_B, wall_ns=500_000_000)), tag="B")
    a, b = (
        a_area.phase(a_run, reset_tag="reset A"),
        b_area.phase(b_run, reset_tag="reset B"),
    )
    load = workload()

    result = measure_abab(a, b, load, trial_id_b="combined")

    assert isinstance(result, AbabMeasured)
    assert events == ["reset A", "A", "reset B", "B"] * 6
    assert {c.cwd for c in a_run.calls} == {a_area.wt}
    assert {c.cwd for c in b_run.calls} == {b_area.wt}
    a_rows, b_rows = by_metric(result.a), by_metric(result.b)
    assert a_rows[METRIC_WALL_TIME_S].samples == (1.5,) * 5
    assert b_rows[METRIC_WALL_TIME_S].samples == (0.5,) * 5
    assert {m.trial_id for m in result.a} == {None}
    assert {m.trial_id for m in result.b} == {"combined"}
    assert {m.output_fingerprint for m in result.a} == {
        output_fingerprint(2, SHA_A, None)
    }
    assert {m.output_fingerprint for m in result.b} == {
        output_fingerprint(2, SHA_B, None)
    }
    assert result.notes[:2] == (
        "workload 'bench' A warm-up 1/1: na",
        "workload 'bench' A run 1/5: na",
    )


def test_abab_without_warm_ups_starts_with_a_timed_a_run(
    tmp_path: Path, events: list[str]
) -> None:
    a_run, b_run = FakeRun(events, tag="A"), FakeRun(events, tag="B")
    a, b = Area(tmp_path / "a").phase(a_run), Area(tmp_path / "b").phase(b_run)

    result = measure_abab(a, b, workload(warmup_runs=0))

    assert events[:4] == ["reset", "A", "reset", "B"]
    assert len(a_run.calls) == len(b_run.calls) == 5
    assert result.notes == ()


def test_abab_failure_names_the_side(tmp_path: Path, events: list[str]) -> None:
    a_run = FakeRun(events, tag="A")
    b_run = FakeRun(events, scripted(sample(), sample(exit=2)), tag="B")
    a, b = Area(tmp_path / "a").phase(a_run), Area(tmp_path / "b").phase(b_run)

    with pytest.raises(RunFailure, match=r"^workload 'bench' B run 1/5: "):
        measure_abab(a, b, workload())


# ---------------------------------------------------------------------------
# run_tests: runners and argv
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "kind"),
    [
        (UNITTEST_CMD, "unittest"),
        (("/usr/bin/python3.11", "-B", "-W", "ignore", "-m", "unittest"), "unittest"),
        (("/usr/bin/python3", "-Bmunittest", "-v"), "unittest"),
        (("/usr/bin/python3", "-Wignore", "-X", "utf8", "-m", "pytest"), "pytest"),
        ((PY, "--check-hash-based-pycs", "never", "-m", "pytest"), "pytest"),
        ((PY, "--version", "-m", "unittest"), "unittest"),
        ((PY, "-I", "--", "-m", "pytest"), "unknown"),
        (("/venv/bin/pytest", "-q"), "pytest"),
        (("/venv/bin/py.test",), "pytest"),
        ((PY, "-m", "unittest.mock"), "unknown"),
        ((PY, "-c", "import unittest; unittest.main()"), "unknown"),
        ((PY, "run_tests.py", "-m", "unittest"), "unknown"),
        ((PY, "-m"), "unknown"),
        ((PY, "-"), "unknown"),
        (("/usr/bin/make", "test"), "unknown"),
        (("/usr/bin/uv", "run", "pytest"), "unknown"),
        (("/usr/bin/python3.13t", "-m", "unittest"), "unittest"),
        (("/usr/bin/python3-dbg", "-m", "pytest"), "pytest"),
        (("/usr/bin/python3.12-dbg", "-m", "unittest"), "unittest"),
        (("/venv/bin/pypy3", "-m", "pytest"), "pytest"),
        (("/opt/pypy/bin/pypy3.10", "-m", "unittest"), "unittest"),
        (("/usr/bin/pythonista", "-m", "pytest"), "unknown"),
        (("/usr/bin/env", "python3", "-m", "pytest"), "unknown"),
    ],
)
def test_the_runner_is_read_from_the_command(argv: tuple[str, ...], kind: str) -> None:
    assert classify_runner(argv) == kind


def test_no_test_command_runs_nothing(area: Area, events: list[str]) -> None:
    run = FakeRun(events)

    result = run_tests(area.phase(run), project(None), [workload()])

    assert result == Measured(measurements=())
    assert events == []


UNITTEST_OK = (
    b"..s.\n----------------------------------------------------------------------\n"
    b"Ran 4 tests in 0.012s\n\nOK (skipped=1)\n"
)


def test_unittest_ok_gives_one_passing_row_per_workload(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN the unittest summary 'Ran 4 tests' then 'OK (skipped=1)', exit 0
    WHEN the suite runs for a trial with two workloads
    THEN it ran once, right after a reset, from the worktree root with the
        test timeout and the fresh scratch; each workload gets a tests_passed
        row of 1.0 recording the runner and 3 passing tests (skips excluded)
    """
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK, fs=False)))
    phase = area.phase(run, fs="best_effort")
    loads = [workload(name="a"), workload(name="b")]

    result = run_tests(phase, project(), loads, trial_id="t1")

    assert events == ["reset", "run"]
    [call] = run.calls
    assert call.argv == UNITTEST_CMD
    assert (call.cwd, call.timeout_s) == (area.wt, settings.TEST_TIMEOUT_S)
    assert call.fresh_dirs == phase.fresh_dirs
    assert (result.tests_counted, result.notes) == (3, ())
    assert [(m.workload_id, m.trial_id) for m in result.measurements] == [
        (loads[0].id, "t1"),
        (loads[1].id, "t1"),
    ]
    for row in result.measurements:
        assert row.metric == METRIC_TESTS_PASSED
        assert row.samples == (1.0,)
        assert row.stats == RunStats.from_samples((1.0,), unit="bool")
        assert row.output_fingerprint is None
        assert row.hardware["test_runner"] == "unittest"
        assert row.hardware["tests_counted"] == 3
        # Counts like the workload rows, never JSON booleans (False == 0).
        assert type(row.hardware["fs_isolated_runs"]) is int
        assert type(row.hardware["net_isolated_runs"]) is int
        assert row.hardware["fs_isolated_runs"] == 0
        assert row.hardware["net_isolated_runs"] == 1
        assert row.hardware["runs"] == 1
        assert row.hardware["fs_isolation"] == "best_effort"


def test_the_suite_runs_right_after_the_workload_runs_reset(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK)))
    phase = area.phase(run)

    measure_workload(phase, workload(warmup_runs=0))
    run_tests(phase, project(), [workload()])

    assert events == ["reset", "run"] * 6


@pytest.mark.parametrize(
    ("stderr", "says"),
    [
        (b"", "no unittest summary"),
        (b"all good\n", "no unittest summary"),
        (
            b"Ran 4 tests in 0.1s\n\nFAILED (failures=1)\n",
            "'FAILED (failures=1)', not OK",
        ),
        (b"Ran 0 tests in 0.000s\n\nNO TESTS RAN\n", "'NO TESTS RAN', not OK"),
        (b"Ran 2 tests in 0.1s\n", "'', not OK"),
        (b"Ran 2 tests in 0.1s\n\nOK (skipped=x)\n", "not OK"),
        (
            b"Ran 2 tests in 0.1s\n\nOK\nRan 9 tests in 0.1s\n\nFAILED (errors=1)\n",
            "'FAILED (errors=1)', not OK",
        ),
        (b"Ran 0 tests in 0.000s\n\nOK\n", "no test passed"),
        (b"Ran 2 tests in 0.1s\n\nOK (skipped=2)\n", "no test passed"),
    ],
    ids=[
        "empty",
        "no-summary",
        "failed",
        "no-tests-ran",
        "no-status",
        "bad-skipped",
        "last-summary-failed",
        "zero-tests",
        "all-skipped",
    ],
)
def test_unittest_exit_0_without_a_passing_summary_fails(
    area: Area, events: list[str], stderr: bytes, says: str
) -> None:
    run = FakeRun(events, scripted(sample(stderr=stderr)))

    result = run_tests(area.phase(run), project(), [workload()])

    [row] = result.measurements
    assert row.samples == (0.0,)
    [note] = result.notes
    assert note.startswith("the test command: ") and says in note


def test_unittest_summary_with_trailing_warnings_still_counts(
    area: Area, events: list[str]
) -> None:
    stderr = (
        b"Ran 1 test in 0.001s\n\nOK (expected failures=1)\nsys:1: ResourceWarning\n"
    )
    run = FakeRun(events, scripted(sample(stderr=stderr)))

    result = run_tests(area.phase(run), project(), [workload()])

    assert (result.measurements[0].samples, result.tests_counted) == ((1.0,), 1)


@pytest.mark.parametrize(
    "nested",
    [
        b"Ran 1 test in 0.000s\n\nOK\n",
        b"Ran 3 tests in 0.002s\n\nFAILED (failures=1)\n",
    ],
    ids=["nested-ok", "nested-failed"],
)
def test_the_last_unittest_summary_is_the_runners_own(
    area: Area, events: list[str], nested: bytes
) -> None:
    """
    GIVEN a suite whose tests run 'python -m unittest' in a subprocess with
        inherited stderr (a CLI project), so the nested summary comes first
    WHEN the outer runner ends with 'Ran 2 tests' and OK, exit 0
    THEN the final summary is the runner's own: 2 tests passed
    """
    stderr = nested + b"..\n" + b"-" * 70 + b"\nRan 2 tests in 0.010s\n\nOK\n"
    run = FakeRun(events, scripted(sample(stderr=stderr)))

    result = run_tests(area.phase(run), project(), [workload()])

    assert (result.measurements[0].samples, result.tests_counted) == ((1.0,), 2)


def test_the_suite_keeps_a_larger_stderr_tail_and_names_it(
    area: Area, events: list[str]
) -> None:
    """
    GIVEN a suite that exits 0 without a unittest summary in its stderr tail
    WHEN the suite runs
    THEN only its launch keeps the larger suite tail (other caps unchanged),
        and the note names how much of stderr was searched
    """
    run = FakeRun(events, scripted(sample(stderr=b"x\n")))
    phase = area.phase(run)

    result = run_tests(phase, project(), [workload()])

    [call] = run.calls
    assert call.caps == OutputCaps(
        max_output_bytes=CAPS.max_output_bytes,
        head_bytes=CAPS.head_bytes,
        stderr_tail_bytes=SUITE_STDERR_TAIL_BYTES,
    )
    assert SUITE_STDERR_TAIL_BYTES >= 256 * 1024
    assert result.notes == (
        "the test command: exit 0 but no unittest summary in the last "
        f"{SUITE_STDERR_TAIL_BYTES} bytes of stderr",
    )


def test_a_larger_configured_stderr_tail_is_kept_for_the_suite(
    area: Area, events: list[str]
) -> None:
    caps = OutputCaps(64, 16, SUITE_STDERR_TAIL_BYTES * 2)
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK)))

    run_tests(area.phase(run, caps=caps), project(), [workload()])

    assert run.calls[0].caps == caps


def test_a_non_zero_exit_fails_whatever_the_summary_says(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample(exit=1, stderr=UNITTEST_OK)))

    result = run_tests(area.phase(run), project(), [workload()])

    assert result.measurements[0].samples == (0.0,)
    assert result.notes == ("the test command: exited with exit status 1",)
    assert result.tests_counted is None


@pytest.mark.parametrize(("baseline", "value"), [(3, 1.0), (2, 1.0), (4, 0.0)])
def test_fewer_passing_tests_than_the_baseline_fails(
    area: Area, events: list[str], baseline: int, value: float
) -> None:
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK)))

    result = run_tests(
        area.phase(run), project(), [workload()], baseline_count=baseline
    )

    assert result.measurements[0].samples == (value,)
    assert result.tests_counted == (3 if value else None)
    if value == 0.0:
        assert result.notes == (
            "the test command: 3 tests passed, fewer than the baseline's 4",
        )


def test_an_unknown_runner_passes_on_exit_0_with_a_note(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample()))

    result = run_tests(
        area.phase(run),
        project(("/usr/bin/make", "test")),
        [workload()],
        baseline_count=5,
    )

    assert result.measurements[0].samples == (1.0,)
    assert result.tests_counted is None
    assert "tests_counted" not in result.measurements[0].hardware
    assert result.measurements[0].hardware["test_runner"] == "unknown"
    assert result.notes == (
        "the test command: '/usr/bin/make' is neither unittest nor pytest: it "
        "passed on its exit code alone; the test count could not be verified",
    )


def test_an_unknown_runner_fails_on_a_non_zero_exit(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample(exit=2)))

    result = run_tests(
        area.phase(run), project(("/usr/bin/make", "test")), [workload()]
    )

    assert result.measurements[0].samples == (0.0,)


def test_a_test_run_failure_propagates_with_its_notes(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(RunFailure("timeout after 900 s", ("leftover",))))

    with pytest.raises(RunFailure) as caught:
        run_tests(area.phase(run), project(), [workload()])

    assert caught.value.reason == "the test command: timeout after 900 s"
    assert caught.value.notes == ("the test command: leftover",)


def test_the_test_run_notes_reach_the_caller(area: Area, events: list[str]) -> None:
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK, notes=("held open",))))

    result = run_tests(area.phase(run), project(), [workload()])

    assert result.notes == ("the test command: held open",)


# ---------------------------------------------------------------------------
# run_tests: pytest and its JUnit report
# ---------------------------------------------------------------------------


def junit(cases: str, *, suite: str = 'errors="0" failures="0"') -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="pytest" {suite} skipped="0" tests="3">{cases}'
        "</testsuite></testsuites>"
    ).encode()


PASSING = (
    '<testcase name="a"/><testcase name="b"/><testcase name="c"><skipped/></testcase>'
)


def writes_junit(payload: bytes | None, *, exit: int = 0) -> Respond:
    """A pytest stand-in: writes ``payload`` where --junitxml points."""

    def respond(call: Call) -> RunSample:
        [flag] = [arg for arg in call.argv if arg.startswith("--junitxml=")]
        if payload is not None:
            Path(flag.removeprefix("--junitxml=")).write_bytes(payload)
        return sample(exit=exit)

    return respond


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (PYTEST_CMD, (PY, "-m", "pytest", "{junit}", "-q", "tests")),
        (
            ("/venv/bin/pytest", "--", "tests"),
            ("/venv/bin/pytest", "{junit}", "--", "tests"),
        ),
        ((PY, "-mpytest"), (PY, "-mpytest", "{junit}")),
    ],
)
def test_pytest_gets_a_junit_report_in_the_scratch_root(
    area: Area, events: list[str], command: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    """
    GIVEN a pytest command and a JUnit report with two passes and a skip
    WHEN the suite runs
    THEN --junitxml=<scratch>/junit.xml is inserted right after pytest (so a
        '--' in the user's args cannot swallow it), and 2 tests passed
    """
    run = FakeRun(events, writes_junit(junit(PASSING)))

    result = run_tests(area.phase(run), project(command), [workload()])

    flag = f"--junitxml={area.scratch / JUNIT_NAME}"
    assert run.calls[0].argv == tuple(flag if a == "{junit}" else a for a in expected)
    assert (result.measurements[0].samples, result.tests_counted) == ((1.0,), 2)
    assert result.measurements[0].hardware["test_runner"] == "pytest"


@pytest.mark.parametrize(
    "own",
    [
        ("--junitxml=reports/own.xml",),
        ("--junit-xml=reports/own.xml",),
        ("--junitxml", "reports/own.xml"),
        ("--junit-xml", "reports/own.xml"),
    ],
)
@pytest.mark.parametrize("start", [(PY, "-m", "pytest"), ("/venv/bin/pytest",)])
def test_the_users_own_junit_report_flag_is_replaced(
    area: Area,
    events: list[str],
    own: tuple[str, ...],
    start: tuple[str, ...],
) -> None:
    """
    GIVEN a pytest command that already names its own JUnit report, in any
        spelling (pytest keeps the last one, so the engine's would be lost)
    WHEN the suite runs
    THEN the user's flag is dropped, the engine's report is read (2 passed)
        and a note says the engine replaced it; other flags are kept
    """
    command = (*start, "-q", *own, "--junit-prefix=x", "tests")
    run = FakeRun(events, writes_junit(junit(PASSING)))

    result = run_tests(area.phase(run), project(command), [workload()])

    flag = f"--junitxml={area.scratch / JUNIT_NAME}"
    assert run.calls[0].argv == (*start, flag, "-q", "--junit-prefix=x", "tests")
    assert (result.measurements[0].samples, result.tests_counted) == ((1.0,), 2)
    assert result.notes == (
        "the test command: its own --junitxml was replaced by the engine's report",
    )


def test_a_junit_flag_after_the_separator_is_a_positional_and_kept(
    area: Area, events: list[str]
) -> None:
    command = ("/venv/bin/pytest", "--junitxml", "own.xml", "--", "--junitxml=x")
    run = FakeRun(events, scripted(sample()))

    result = run_tests(area.phase(run), project(command), [workload()])

    flag = f"--junitxml={area.scratch / JUNIT_NAME}"
    assert run.calls[0].argv == ("/venv/bin/pytest", flag, "--", "--junitxml=x")
    assert result.notes[0].endswith("replaced by the engine's report")


def test_a_trailing_junit_flag_without_a_value_is_dropped(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, writes_junit(junit(PASSING)))

    run_tests(area.phase(run), project((*PYTEST_CMD, "--junitxml")), [workload()])

    flag = f"--junitxml={area.scratch / JUNIT_NAME}"
    assert run.calls[0].argv == (PY, "-m", "pytest", flag, "-q", "tests")


def test_a_bare_testsuite_root_is_accepted(area: Area, events: list[str]) -> None:
    report = b'<testsuite errors="0" failures="0"><testcase name="a"/></testsuite>'
    run = FakeRun(events, writes_junit(report))

    result = run_tests(area.phase(run), project(PYTEST_CMD), [workload()])

    assert result.tests_counted == 1


BILLION_LAUGHS = (
    b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
    b"<testsuites><testsuite><testcase name='&lol2;'/></testsuite></testsuites>"
)


@pytest.mark.parametrize(
    ("payload", "says"),
    [
        (None, "JUnit report is missing"),
        (junit('<testcase name="a"><failure/></testcase>'), "a test failed or errored"),
        (junit('<testcase name="a"><error/></testcase>'), "a test failed or errored"),
        (junit(PASSING, suite='errors="1" failures="0"'), "counts failures or errors"),
        (junit(PASSING, suite='errors="0" failures="x"'), "unreadable JUnit report"),
        (junit('<testcase name="a"><skipped/></testcase>'), "no test passed"),
        (b"<testsuites/>", "has no testsuite"),
        (b"<html/>", "root is <html>"),
        (b"<testsuites><testsuite>", "unreadable JUnit report"),
        (BILLION_LAUGHS, "declares a DOCTYPE or ENTITY"),
        (b"<!entity x 'y'><testsuites/>", "declares a DOCTYPE or ENTITY"),
        ('<?xml version="1.0" encoding="UTF-16"?><a/>'.encode("utf-16"), "not UTF-8"),
        (b"x" * (JUNIT_MAX_BYTES + 1), f"is larger than {JUNIT_MAX_BYTES} bytes"),
    ],
    ids=[
        "missing",
        "failure",
        "error",
        "suite-errors",
        "bad-count",
        "all-skipped",
        "no-suite",
        "wrong-root",
        "truncated",
        "billion-laughs",
        "entity",
        "utf-16",
        "too-large",
    ],
)
def test_pytest_without_a_clean_junit_report_fails(
    area: Area, events: list[str], payload: bytes | None, says: str
) -> None:
    """
    GIVEN pytest exiting 0 but a JUnit report that is missing, counts a
        failure, error or nothing passing, is malformed, declares a DTD
        (entity expansion), is not UTF-8 or is larger than the cap
    WHEN the suite runs
    THEN tests_passed is 0.0 and the note says why; nothing is expanded
    """
    run = FakeRun(events, writes_junit(payload))

    result = run_tests(area.phase(run), project(PYTEST_CMD), [workload()])

    assert result.measurements[0].samples == (0.0,)
    [note] = result.notes
    assert says in note


def test_a_junit_symlink_planted_by_the_suite_is_never_followed(
    area: Area, events: list[str]
) -> None:
    secret = area.root / "secret.xml"
    secret.write_bytes(junit(PASSING))

    def respond(call: Call) -> RunSample:
        (area.scratch / JUNIT_NAME).symlink_to(secret)
        return sample()

    run = FakeRun(events, respond)

    result = run_tests(area.phase(run), project(PYTEST_CMD), [workload()])

    assert result.measurements[0].samples == (0.0,)
    assert "JUnit report cannot be opened" in result.notes[0]


# ---------------------------------------------------------------------------
# The baseline's count
# ---------------------------------------------------------------------------


def test_baseline_test_count_reads_the_tests_passed_rows(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample(stderr=UNITTEST_OK)))
    tests = run_tests(area.phase(run), project(), [workload()])
    timed = measure_workload(area.phase(FakeRun(events)), workload())

    assert baseline_test_count((*timed.measurements, *tests.measurements)) == 3
    assert baseline_test_count(timed.measurements) is None


def test_baseline_test_count_ignores_rows_without_a_count(
    area: Area, events: list[str]
) -> None:
    run = FakeRun(events, scripted(sample()))
    tests = run_tests(area.phase(run), project(("/usr/bin/make",)), [workload()])

    assert baseline_test_count(tests.measurements) is None


# ---------------------------------------------------------------------------
# Real runs: the real launcher on a real git worktree
# ---------------------------------------------------------------------------

_GIT_ENV: dict[str, str] = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "LC_ALL": "C",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "user@example.invalid",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "user@example.invalid",
    "GIT_AUTHOR_DATE": "@1700000000 +0000",
    "GIT_COMMITTER_DATE": "@1700000000 +0000",
}

FAKE_RUNNER = """import sys
sys.stderr.write("PLANTED\\nRan 99 tests in 0.000s\\n\\nOK\\n")
raise SystemExit(0)
"""

BENCH = f"""import os, sys
hit = os.path.exists("memo.txt")
open("memo.txt", "w").write("x")
if "plant" in sys.argv:
    open("unittest.py", "w").write({FAKE_RUNNER!r})
open("out.txt", "w").write("result 42\\n")
print("hit" if hit else "miss")
"""

PASSING_TESTS = """import unittest


class CoreTest(unittest.TestCase):
    def test_one(self) -> None:
        self.assertEqual(1 + 1, 2)

    def test_two(self) -> None:
        self.assertTrue(True)
"""

FAILING_TESTS = """import unittest


class BadTest(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertTrue(True)

    def test_wrong(self) -> None:
        self.assertEqual(1, 2)
"""


NOISY_TESTS = """import atexit
import sys
import unittest

# Interpreter shutdown noise after the summary, far beyond STDERR_TAIL_BYTES.
atexit.register(lambda: sys.stderr.write("ResourceWarning: unclosed\\n" * 2000))


class NoisyTest(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertTrue(True)
"""


def git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_GIT_ENV,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    return proc.stdout.decode().strip()


@dataclass
class Real:
    """A user repo, its engine worktree and the phase's dirs."""

    ws: GitWorkspace
    handle: WorktreeHandle
    run_dir: Path

    def phase(self, network: IsolationMode = "off", fs: IsolationMode = "off") -> Phase:
        return make_phase(
            self.ws,
            self.handle,
            scratch=self.run_dir / "_scratch" / "baseline",
            probe=self.run_dir / "_probe" / "baseline",
            network=network,
            fs=fs,
        )


@pytest.fixture
def real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Real:
    root = Path(os.path.realpath(tmp_path)) / "wt-root"
    root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    repo = tmp_path / "user"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "bench.py").write_text(BENCH)
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "tests" / "test_core.py").write_text(PASSING_TESTS)
    (repo / "failing").mkdir()
    (repo / "failing" / "__init__.py").write_text("")
    (repo / "failing" / "test_bad.py").write_text(FAILING_TESTS)
    (repo / "noisy").mkdir()
    (repo / "noisy" / "__init__.py").write_text("")
    (repo / "noisy" / "test_noisy.py").write_text(NOISY_TESTS)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    ws = GitWorkspace(repo)
    run_dir = root / "run1"
    handle = ws.add_worktree(run_dir / "baseline", ws.head_commit())
    return Real(ws, handle, run_dir)


def real_workload(*extra: str, runs: int = 5, warmups: int = 1) -> Workload:
    return workload(
        command=(sys.executable, "bench.py", *extra),
        output_file="out.txt",
        warmup_runs=warmups,
        runs=runs,
        timeout_s=60.0,
    )


def unittest_cmd(start: str = "tests") -> tuple[str, ...]:
    return (sys.executable, "-m", "unittest", "discover", "-s", start, "-t", ".")


def test_real_runs_cannot_memoise_across_runs(real: Real) -> None:
    """
    GIVEN a workload that leaves memo.txt in the worktree and prints 'hit'
        when it finds one, and writes out.txt
    WHEN it is measured with one warm-up and five timed runs
    THEN every run printed 'miss' (the reset removed the memo each time), so
        all runs agree on the fingerprint of stdout and out.txt, and the
        three rows hold real, positive numbers
    """
    measured = measure_workload(real.phase(), real_workload())

    expected = output_fingerprint(
        5,
        hashlib.sha256(b"miss\n").hexdigest(),
        (10, hashlib.sha256(b"result 42\n").hexdigest()),
    )
    rows = by_metric(measured.measurements)
    assert {m.output_fingerprint for m in measured.measurements} == {expected}
    assert all(v > 0 for m in measured.measurements for v in m.samples)
    assert 1 * MIB < rows[METRIC_PEAK_RSS_BYTES].stats.mean < 200 * MIB
    assert measured.notes == ()


def test_real_dropped_unittest_is_gone_when_the_suite_starts(real: Real) -> None:
    """
    GIVEN a workload that drops a fake unittest.py at the repo root, which
        would print 'Ran 99 tests ... OK' and exit 0 if it ever ran
    WHEN the suite runs after the workload measurement
    THEN the real stdlib runner ran the real two tests: the reset before the
        test command removed the planted module
    """
    phase = real.phase()
    measure_workload(phase, real_workload("plant", runs=5, warmups=0))
    assert (real.handle.path / "unittest.py").exists()

    result = run_tests(phase, project(unittest_cmd()), [real_workload()])

    assert result.tests_counted == 2
    assert result.measurements[0].samples == (1.0,)
    assert not (real.handle.path / "unittest.py").exists()


def test_real_unittest_failure_is_counted_as_failing(real: Real) -> None:
    result = run_tests(
        real.phase(), project(unittest_cmd("failing")), [real_workload()]
    )

    assert result.measurements[0].samples == (0.0,)
    assert result.notes == ("the test command: exited with exit status 1",)


def test_real_unittest_summary_survives_noisy_interpreter_shutdown(real: Real) -> None:
    """
    GIVEN a passing suite that writes ~50 KiB to stderr at exit, after OK
    WHEN it runs through the real launcher with the default output caps
    THEN the suite's larger stderr tail still holds the summary: 1 passed
    """
    phase = real.phase()
    assert phase.caps.stderr_tail_bytes == settings.STDERR_TAIL_BYTES

    result = run_tests(phase, project(unittest_cmd("noisy")), [real_workload()])

    assert (result.tests_counted, result.measurements[0].samples) == (1, (1.0,))


@pytest.mark.parametrize(("start", "count"), [("tests", 2), ("failing", None)])
def test_real_pytest_summary_comes_from_its_junit_report(
    real: Real, start: str, count: int | None
) -> None:
    command = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", start)

    result = run_tests(real.phase(), project(command), [real_workload()])

    assert result.tests_counted == count
    assert result.measurements[0].samples == ((1.0,) if count else (0.0,))


def test_real_pytest_with_its_own_junit_report_flag_still_counts(real: Real) -> None:
    """
    GIVEN a CI-style pytest command that writes its own JUnit report
    WHEN the suite runs through the real launcher
    THEN the engine's report replaced it (pytest keeps the last flag), so
        the 2 passing tests are counted and the user's file is not written
    """
    command = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    own = (*command, "--junit-xml", "own.xml", "tests")

    result = run_tests(real.phase(), project(own), [real_workload()])

    assert (result.tests_counted, result.measurements[0].samples) == (2, (1.0,))
    assert not (real.handle.path / "own.xml").exists()


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


@linux_only
@pytest.mark.usefixtures("linux_sandbox")
def test_real_sandboxed_measurement_and_suite_are_isolated(real: Real) -> None:
    """
    GIVEN both isolation modes required
    WHEN the workload is measured and pytest runs under the same sandbox
    THEN every timed run was fs- and net-isolated, the memo still never
        survives a run, and pytest could write its JUnit report into the
        scratch root (2 tests passed)
    """
    phase = real.phase(network="required", fs="required")

    measured = measure_workload(phase, real_workload())
    command = (sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests")
    tests = run_tests(phase, project(command), [real_workload()])

    hardware = measured.measurements[0].hardware
    assert (hardware["fs_isolated_runs"], hardware["net_isolated_runs"]) == (5, 5)
    assert {m.output_fingerprint for m in measured.measurements} != {None}
    assert (tests.tests_counted, tests.measurements[0].samples) == (2, (1.0,))
    assert tests.measurements[0].hardware["fs_isolated_runs"] == 1
