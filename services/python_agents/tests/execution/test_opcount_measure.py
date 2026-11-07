"""The counted run (G6a): one launch per side under the opcount shim, as notes on failure.

``count_workload`` runs a workload once under ``_opcount_shim`` the way the
profiler runs its shim: the phase's sandbox and environment, a reset (and the
quality mask) first, the workload's own interpreter and options, the
scratch root as the only output channel, read capped and parsed strictly.
It never raises for the workload's sake: anything it cannot count is a note
and no row. Fakes: ``FakeRun`` stands for ``procrun.run_once`` (it records
the launch and writes the document a shim would); one real test runs the
real shim through the real ``run_once`` (isolation off, the real sandbox is
procrun's and the profiler's business).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import autonomous_ai_agents
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import Workload
from autonomous_ai_agents.execution.measure import (
    C_CALLS_KEY,
    METRIC_OP_CALLS,
    OPCOUNT_NAME,
    OPCOUNT_SHIM,
    OPCOUNT_TIMEOUT_FACTOR,
    PYTHON_CALLS_KEY,
    Phase,
    count_workload,
    counted_argv,
)
from autonomous_ai_agents.execution.phase import phase_dirs
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy

PY = "/usr/bin/python3"
CAPS = OutputCaps(max_output_bytes=1 << 20, head_bytes=16, stderr_tail_bytes=4096)


def sample(*, exit: int = 0, stderr: bytes = b"", notes: tuple[str, ...] = ()) -> RunSample:  # fmt: skip
    return RunSample(1, 0.1, 0.0, 1 << 20, exit, True, False, "1" * 64, b"", 0, stderr, notes)  # fmt: skip


@dataclass
class FakeRun:
    """``run_once``: records each launch; ``write`` is what the shim leaves in
    OUT (``None``: nothing), ``answer`` the sample or failure it returns."""

    write: bytes | None = b'{"version": 1, "python_calls": 70, "c_calls": 30}'
    answer: Callable[[], RunSample] = sample
    calls: list[tuple[tuple[str, ...], Path, float, tuple[Path, ...]]] = field(
        default_factory=list
    )
    events: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        self.calls.append((tuple(argv), cwd, timeout_s, tuple(fresh_dirs)))
        self.events.append("run")
        if self.write is not None:
            Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1]).write_bytes(self.write)
        return self.answer()


@pytest.fixture
def area(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = Path(os.path.realpath(tmp_path))
    dirs = (root / "wt", root / "scratch", root / "probe")
    for path in dirs:
        path.mkdir()
    return dirs


def phase_of(area: tuple[Path, Path, Path], run: FakeRun | object, *, mask: tuple[str, ...] = ()) -> Phase:  # fmt: skip
    wt, scratch, probe = area
    policy = SandboxPolicy(network="off", fs="off", writable=(wt, scratch), probe_dir=probe, platform=sys.platform)  # fmt: skip
    events = run.events if isinstance(run, FakeRun) else []
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    return Phase(policy, env, lambda: events.append("reset"), CAPS, run, mask)  # type: ignore[arg-type]


def workload(*command: str, **changes: object) -> Workload:
    fields: dict[str, object] = {
        "project_id": "p1", "name": "bench", "command": command or (PY, "-O", "bench.py", "7"),
        "timeout_s": 40.0, "working_dir": "sub",
    }  # fmt: skip
    return Workload.model_validate({**fields, **changes})


def test_one_launch_under_the_shim_gives_one_op_calls_row(
    area: tuple[Path, Path, Path],
) -> None:
    """
    GIVEN a Python workload ``python -O bench.py 7`` in ``sub``
    WHEN it is counted
    THEN one launch, right after a reset, runs ``python -O <shim> <scratch>/
        opcount.json script bench.py 7`` from the working dir with the
        workload's timeout times the factor and the phase's fresh dirs; one
        ``op_calls`` row (n=1, unit ``calls``) holds the total, the split
        and the host, carrying the trial id
    """
    (area[0] / "sub").mkdir()
    run = FakeRun()
    phase = phase_of(area, run)

    counted = count_workload(phase, workload(), trial_id="t1")

    out = area[1] / OPCOUNT_NAME
    [(argv, cwd, timeout, fresh)] = run.calls
    assert argv == (PY, "-O", str(OPCOUNT_SHIM), str(out), "script", "bench.py", "7")
    assert cwd == area[0] / "sub" and fresh == phase.fresh_dirs
    assert timeout == pytest.approx(40.0 * OPCOUNT_TIMEOUT_FACTOR)
    assert OPCOUNT_TIMEOUT_FACTOR == 3.0
    assert run.events == ["reset", "run"]
    [row] = counted.rows
    assert (row.metric, row.trial_id, row.workload_id) == (
        METRIC_OP_CALLS,
        "t1",
        row.workload_id,
    )
    assert row.samples == (100.0,) and row.stats.n == 1 and row.stats.unit == "calls"
    assert row.hardware[PYTHON_CALLS_KEY] == 70 and row.hardware[C_CALLS_KEY] == 30
    assert row.hardware["runs"] == 1 and row.hardware["network_isolation"] == "off"
    assert row.output_fingerprint is None
    assert counted.notes == ()


def test_a_module_workload_is_counted_as_a_module_and_masked(
    area: tuple[Path, Path, Path],
) -> None:
    (area[0] / "eval").mkdir()
    (area[0] / "eval" / "labels.txt").write_text("secret\n")
    run = FakeRun()

    counted = count_workload(
        phase_of(area, run, mask=("eval/labels.txt",)),
        workload(PY, "-m", "pkg.main", "--n", "3", working_dir="."),
    )

    [(argv, _, _, _)] = run.calls
    assert argv[1:] == (str(OPCOUNT_SHIM), str(area[1] / OPCOUNT_NAME), "module", "pkg.main", "--n", "3")  # fmt: skip
    assert not (area[0] / "eval" / "labels.txt").exists()
    assert counted.rows[0].trial_id is None


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (("/bin/sh", "run.sh"), "is not a Python interpreter"),
        ((PY, "-c", "print(1)"), "inline code (-c)"),
    ],
)
def test_a_command_the_shim_cannot_run_is_a_note_and_never_launches(
    area: tuple[Path, Path, Path], command: tuple[str, ...], reason: str
) -> None:
    run = FakeRun()

    counted = count_workload(phase_of(area, run), workload(*command), side=" A")

    assert run.calls == [] and counted.rows == ()
    [note] = counted.notes
    assert note.startswith("workload 'bench' A is not counted: ") and reason in note


def test_a_failed_counted_run_is_a_note_with_its_notes_and_no_row(
    area: tuple[Path, Path, Path],
) -> None:
    """A non-zero exit (the counted run checks the exit as a timed run does) and
    every run note are notes; nothing raises, no row."""
    (area[0] / "sub").mkdir()
    run = FakeRun(answer=lambda: sample(exit=2, stderr=b"Boom: no\n", notes=("isolation note",)))  # fmt: skip

    counted = count_workload(phase_of(area, run), workload(), side=" B")

    assert counted.rows == ()
    assert counted.notes[0] == "workload 'bench' B: the counted run: isolation note"
    assert counted.notes[1].startswith("workload 'bench' B is not counted: the counted run: the command ended with exit status 2: Boom: no")  # fmt: skip


def test_a_run_failure_is_a_note_and_no_row(area: tuple[Path, Path, Path]) -> None:
    def fail() -> RunSample:
        raise RunFailure("timed out after 120 s", ("a note",))

    (area[0] / "sub").mkdir()
    counted = count_workload(phase_of(area, FakeRun(answer=fail)), workload())

    assert counted.rows == ()
    assert counted.notes == (
        "workload 'bench': the counted run: a note",
        "workload 'bench' is not counted: the counted run: timed out after 120 s",
    )


@pytest.mark.parametrize(
    ("written", "reason"),
    [
        (None, "the count output is missing"),
        (b'{"version": 1}', "the count output its top level must hold exactly version"),
        (b"\xff", "the count output is not ASCII JSON"),
    ],
)
def test_unusable_count_output_is_a_note_and_no_row(
    area: tuple[Path, Path, Path], written: bytes | None, reason: str
) -> None:
    (area[0] / "sub").mkdir()

    counted = count_workload(phase_of(area, FakeRun(write=written)), workload())

    assert counted.rows == ()
    [note] = counted.notes
    assert note.startswith(f"workload 'bench' is not counted: {reason}")


def test_a_planted_link_in_place_of_the_output_is_never_followed(
    area: tuple[Path, Path, Path],
) -> None:
    (area[0] / "sub").mkdir()
    target = area[0] / "elsewhere.json"
    target.write_bytes(b'{"version": 1, "python_calls": 1, "c_calls": 1}')

    class Planting(FakeRun):
        def __call__(self, argv: Sequence[str], *args: object, **kwargs: object) -> RunSample:  # fmt: skip
            out = Path(argv[argv.index(str(OPCOUNT_SHIM)) + 1])
            out.symlink_to(target)
            return sample()

    counted = count_workload(phase_of(area, Planting(write=None)), workload())

    assert counted.rows == ()
    assert "cannot be opened" in counted.notes[0]


REAL = """import sys


def leaf(i):
    return i + 1


total = sum(leaf(i) for i in range(int(sys.argv[1])))
print(total)
"""


@pytest.mark.skipif(sys.platform != "linux", reason="isolation off is Linux's")
def test_the_real_shim_counts_through_the_real_run_once(
    area: tuple[Path, Path, Path],
) -> None:
    """
    GIVEN a workload calling ``leaf`` N times, run by the engine's interpreter
    WHEN it is counted at N=100 and N=300 through the real ``run_once``
    THEN both counts parse, and the larger run counts exactly 200 more
        ``leaf`` calls plus their 200 generator resumptions more
    """
    (area[0] / "bench.py").write_text(REAL)
    phase = phase_of(area, run_once)
    small = count_workload(phase, workload(sys.executable, "bench.py", "100", working_dir="."))  # fmt: skip
    large = count_workload(phase, workload(sys.executable, "bench.py", "300", working_dir="."))  # fmt: skip

    [a], [b] = small.rows, large.rows
    assert b.samples[0] - a.samples[0] == 400
    assert json.dumps(b.hardware[PYTHON_CALLS_KEY]).isdigit()


def test_the_counting_shim_lives_outside_every_path_a_trial_or_workload_can_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN the engine's worktree root (its default and a test one) and a
        phase's run, worktree, scratch and probe dirs laid out under it
    WHEN the counted run's argv is built
    THEN it runs the engine package's own shim, which lies outside every one
        of those dirs: a trial's diff (paths in its own worktree, protected or
        not) cannot name it, the sandbox (writes to the worktree and scratch
        only) cannot change it, and a worktree copy of the file (the engine
        optimising its own repository) is never what runs
    """
    package = Path(autonomous_ai_agents.__file__).resolve().parent
    assert OPCOUNT_SHIM.is_relative_to(package)
    for root in (settings.WORKTREE_ROOT.expanduser().resolve(), tmp_path / "wt-root"):
        monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
        dirs = phase_dirs("run-1", "trial-x")
        for where in (dirs.run, dirs.worktree, dirs.scratch, dirs.probe):
            assert not OPCOUNT_SHIM.is_relative_to(where.resolve()), where
    argv = counted_argv((PY, "bench.py"), tmp_path / "out.json")
    assert argv[1] == str(OPCOUNT_SHIM)
