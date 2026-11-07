"""The scaling runs (G6b): each workload at its 2-3 sizes, both sides interleaved.

``measure_scaling`` runs a workload whose ``Workload.scale`` is set at each
size, the size handed over in the setting's environment variable, a few
timed runs per size and side: one ``scale_wall_time_s`` row per side and
size (the size in its hardware). Runs interleave like the ABBA measurement:
the sizes go forward on an even run and backward on an odd one, and the two
sides swap order on every other (run, size) turn, so neither a side nor a
size always runs first. It never raises for the workload's sake: anything it
cannot run is a note and no rows, on either side. Fakes: ``Clock`` stands for
``procrun.run_once`` (it records each launch's side and size and answers a
wall time from ``time(side, size, launch)``); the last test runs real
scripts through the real ``run_once`` (isolation off).
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from autonomous_ai_agents.common.models import (
    Baseline,
    ScaleSetting,
    Trial,
    TrialStatus,
    Workload,
)
from autonomous_ai_agents.execution.measure import (
    METRIC_SCALE_WALL_S,
    SCALE_SIZE_KEY,
    Phase,
    Scaled,
    measure_scaling,
)
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.optimization.judges import GROWTH_TOLERANCE, ScalingJudge

PY = "/usr/bin/python3"
VAR = "BENCH_N"
CAPS = OutputCaps(max_output_bytes=1 << 20, head_bytes=16, stderr_tail_bytes=4096)
Time = Callable[[str, int, int], float]


def quadratic(side: str, size: int, launch: int) -> float:
    return 1e-7 * size**2


@dataclass
class Clock:
    """``run_once``: records ``(side, size)`` per launch (the side is the
    worktree's name, ``a`` or ``b``) and answers ``time(side, size, n)``
    seconds for the n-th launch; ``fail`` makes a launch exit 3."""

    time: Time = quadratic
    fail: Callable[[str, int], bool] = lambda side, size: False
    calls: list[tuple[str, int]] = field(default_factory=list)
    envs: list[Mapping[str, str]] = field(default_factory=list)
    seen: list[tuple[tuple[str, ...], Path, float]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)

    def __call__(
        self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
        sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:  # fmt: skip
        side, size = sandbox.writable[0].name, int(env[VAR])
        self.calls.append((side, size))
        self.envs.append(dict(env))
        self.seen.append((tuple(argv), cwd, timeout_s))
        self.events.append("run")
        wall = round(self.time(side, size, len(self.calls)) * 1e9)
        exit, err = (
            (3, b"MemoryError: too big\n") if self.fail(side, size) else (0, b"")
        )
        return RunSample(wall, 0.1, 0.0, 1 << 20, exit, True, False, "1" * 64, b"", 0, err)  # fmt: skip


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path))


def phase_of(root: Path, side: str, run: object, events: list[str] | None = None) -> Phase:  # fmt: skip
    wt, scratch, probe = root / side, root / f"scratch-{side}", root / f"probe-{side}"
    for path in (wt, scratch, probe):
        path.mkdir(exist_ok=True)
    policy = SandboxPolicy(network="off", fs="off", writable=(wt, scratch), probe_dir=probe, platform=sys.platform)  # fmt: skip
    env = {"PATH": os.defpath, "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    log = [] if events is None else events
    return Phase(policy, env, lambda: log.append(f"reset {side}"), CAPS, run)  # type: ignore[arg-type]


def workload(sizes: tuple[int, ...] = (100, 400), runs: int = 2, **changes: object) -> Workload:  # fmt: skip
    fields: dict[str, object] = {
        "project_id": "p1", "name": "bench", "command": (PY, "bench.py"),
        "timeout_s": 40.0, "scale": ScaleSetting(env_var=VAR, sizes=sizes, runs=runs),
    }  # fmt: skip
    return Workload.model_validate({**fields, **changes})


def judged(scaled: Scaled) -> tuple[float, float, float]:
    """The scaling judge's base rate, trial rate and change over ``scaled``."""
    base = Baseline(measurements=scaled.a)
    trial = Trial(hypothesis_id="h1", round=1, status=TrialStatus.measured, measurements=scaled.b)  # fmt: skip
    details = ScalingJudge().evaluate(base, trial).details
    rates = (details["base_rate"], details["trial_rate"], details["change"])
    assert all(isinstance(rate, float) for rate in rates), details
    return rates  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# What runs, in which order, with which size
# ---------------------------------------------------------------------------


def test_a_workload_without_a_size_setting_is_never_scaled(root: Path) -> None:
    clock = Clock()

    scaled = measure_scaling(phase_of(root, "b", clock), workload(scale=None), twin=phase_of(root, "a", clock))  # fmt: skip

    assert scaled == Scaled((), (), ())
    assert clock.calls == []


def test_both_sides_run_each_size_interleaved_with_the_size_in_the_variable(
    root: Path,
) -> None:
    """
    GIVEN a paired phase and a workload scaled at sizes 100 and 400, 2 runs
    WHEN it is scaled
    THEN run 1 goes through the sizes forward and run 2 backward, the sides
        swapping order on every other turn (A B, B A, A B, B A); each launch
        follows its own side's reset, runs the workload's own command, working
        dir and timeout, and sees the size in ``BENCH_N`` on top of the
        phase's environment, which stays unchanged; one row per side and
        size, in size order, the base side without a trial id
    """
    events: list[str] = []
    clock = Clock(events=events)
    a, b = phase_of(root, "a", clock, events), phase_of(root, "b", clock, events)
    (root / "b" / "sub").mkdir()

    scaled = measure_scaling(b, workload(working_dir="sub"), twin=a, trial_id="t1")

    assert clock.calls == [("a", 100), ("b", 100), ("b", 400), ("a", 400),
                           ("a", 400), ("b", 400), ("b", 100), ("a", 100)]  # fmt: skip
    assert events == [x for side, _ in clock.calls for x in (f"reset {side}", "run")]
    assert all(env == {**a.env, VAR: str(size)} for env, (_, size) in zip(clock.envs, clock.calls, strict=True))  # fmt: skip
    assert VAR not in a.env and VAR not in b.env
    assert {seen[0] for seen in clock.seen} == {(PY, "bench.py")}
    assert {(seen[1], seen[2]) for seen in clock.seen if seen[1].parent == root / "b"} == {(root / "b" / "sub", 40.0)}  # fmt: skip
    assert [(r.metric, r.trial_id, r.hardware[SCALE_SIZE_KEY]) for r in scaled.a] == [
        (METRIC_SCALE_WALL_S, None, 100), (METRIC_SCALE_WALL_S, None, 400),
    ]  # fmt: skip
    assert [(r.trial_id, r.hardware[SCALE_SIZE_KEY]) for r in scaled.b] == [("t1", 100), ("t1", 400)]  # fmt: skip
    small = scaled.b[0]
    assert small.samples == pytest.approx((1e-3, 1e-3)) and small.stats.unit == "s"
    assert small.hardware["runs"] == 2 and small.hardware["fs_isolated_runs"] == 2
    assert small.output_fingerprint is None and small.workload_id == scaled.a[0].workload_id  # fmt: skip
    assert scaled.notes == ()


def test_an_unpaired_phase_scales_itself_only(root: Path) -> None:
    clock = Clock()

    scaled = measure_scaling(phase_of(root, "b", clock), workload(sizes=(10, 20, 40), runs=1))  # fmt: skip

    assert clock.calls == [("b", 10), ("b", 20), ("b", 40)]
    assert scaled.a == ()
    assert [(r.trial_id, r.hardware[SCALE_SIZE_KEY], r.stats.n) for r in scaled.b] == [
        (None, 10, 1), (None, 20, 1), (None, 40, 1),
    ]  # fmt: skip


def test_a_failed_run_at_any_size_is_a_note_and_no_rows_on_either_side(
    root: Path,
) -> None:
    """The base fails at the largest size: no side keeps any row (a fit over
    the sizes one side reached would compare unlike ranges), the run stops,
    and the notes say why."""
    clock = Clock(fail=lambda side, size: side == "a" and size == 400)

    scaled = measure_scaling(phase_of(root, "b", clock), workload(), twin=phase_of(root, "a", clock))  # fmt: skip

    assert (scaled.a, scaled.b) == ((), ())
    assert clock.calls == [("a", 100), ("b", 100), ("b", 400), ("a", 400)]
    assert scaled.notes[-1] == (
        "workload 'bench' is not scaled: workload 'bench' A size 400 run 1/2:"
        " the command ended with exit status 3: MemoryError: too big"
    )


def test_a_run_failure_keeps_its_notes(root: Path) -> None:
    def fail(*args: object, **kwargs: object) -> RunSample:
        raise RunFailure("timed out after 40 s", ("an isolation note",))

    scaled = measure_scaling(phase_of(root, "b", fail), workload())

    assert (scaled.a, scaled.b) == ((), ())
    assert scaled.notes == (
        "workload 'bench' size 100 run 1/2: an isolation note",
        "workload 'bench' is not scaled: workload 'bench' size 100 run 1/2: timed out after 40 s",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("name", "env"),
    [("BENCH_N", {"BENCH_N": "5"}), ("MY_TOKEN", {}), ("CLAUDE_N", {})],
)
def test_a_variable_the_engine_sets_or_denies_is_a_note_and_never_launches(
    root: Path, name: str, env: dict[str, str]
) -> None:
    """A size variable the phase already sets, or one the sandbox would drop
    as a secret's or an owner's name, never reaches the workload."""
    clock = Clock()
    phase = phase_of(root, "b", clock)
    phase = Phase(phase.policy, {**phase.env, **env}, phase.reset, phase.caps, clock)
    scale = ScaleSetting(env_var=name, sizes=(100, 400))

    scaled = measure_scaling(phase, workload(scale=scale))

    assert clock.calls == [] and (scaled.a, scaled.b) == ((), ())
    assert scaled.notes == (
        f"workload 'bench' is not scaled: the size variable {name} is one the"
        " engine sets or keeps from workloads",
    )


# ---------------------------------------------------------------------------
# What the fit sees: the growth rate through the measurement
# ---------------------------------------------------------------------------


def jitter(time: Time, spread: float = 0.04) -> Time:
    """``time`` with a deterministic +-``spread`` wobble that differs per launch."""
    return lambda side, size, n: time(side, size, n) * (1 + spread * math.sin(7.3 * n))


def test_a_quadratic_to_linear_change_lowers_the_growth_rate_by_one(root: Path) -> None:
    def time(side: str, size: int, n: int) -> float:
        return 2e-8 * size**2 if side == "a" else 3e-5 * size

    clock = Clock(time=jitter(time))

    base, trial, change = judged(measure_scaling(phase_of(root, "b", clock), workload(sizes=(1000, 2000, 4000), runs=3), twin=phase_of(root, "a", clock)))  # fmt: skip

    assert base == pytest.approx(2.0, abs=0.06)
    assert trial == pytest.approx(1.0, abs=0.06)
    assert change == pytest.approx(-1.0, abs=0.1)
    assert abs(change) > GROWTH_TOLERANCE


def test_a_constant_factor_speed_up_keeps_the_growth_rate(root: Path) -> None:
    """Three times faster at every size: the same rate within the tolerance,
    although every run is far faster (a micro-tweak, not an algorithm)."""

    def time(side: str, size: int, n: int) -> float:
        return 2e-8 * size**2 / (1 if side == "a" else 3)

    clock = Clock(time=jitter(time))

    base, trial, change = judged(measure_scaling(phase_of(root, "b", clock), workload(sizes=(1000, 2000, 4000), runs=3), twin=phase_of(root, "a", clock)))  # fmt: skip

    assert base == pytest.approx(2.0, abs=0.06) and trial == pytest.approx(2.0, abs=0.06)  # fmt: skip
    assert abs(change) < GROWTH_TOLERANCE


def test_identical_code_gives_the_same_rate_within_the_stated_tolerance(
    root: Path,
) -> None:
    """A/A: the same n log n cost on both sides, each launch wobbling by up to
    5 %, over the narrowest span the setting allows (4x, two sizes): the
    rates differ by less than ``GROWTH_TOLERANCE`` (0.15)."""

    def time(side: str, size: int, n: int) -> float:
        return 1e-6 * size * math.log(size)

    clock = Clock(time=jitter(time, 0.05))

    base, trial, change = judged(measure_scaling(phase_of(root, "b", clock), workload(sizes=(1000, 4000), runs=3), twin=phase_of(root, "a", clock)))  # fmt: skip

    assert GROWTH_TOLERANCE == 0.15
    assert abs(change) < GROWTH_TOLERANCE
    assert base == pytest.approx(1.17, abs=0.1)


QUADRATIC = """import os
n = int(os.environ["BENCH_N"])
total = 0
for i in range(n):
    for j in range(n):
        total += i ^ j
print(total)
"""
LINEAR = """import os
n = int(os.environ["BENCH_N"])
total = sum(i ^ (n - i) for i in range(n))
print(total)
"""


@pytest.mark.skipif(sys.platform != "linux", reason="isolation off is Linux's")
def test_real_runs_see_the_size_and_a_quadratic_loop_grow_faster(root: Path) -> None:
    """
    GIVEN a quadratic script on the base side and a linear one on the trial
        side, run by the engine's interpreter through the real ``run_once``
    WHEN scaled at 600 and 2400, two runs each
    THEN both scripts read the size (they would fail without it), every row
        holds two real timings, and the base grows clearly faster than the
        trial (start-up cost flattens both rates, so the margin is wide)
    """
    a, b = phase_of(root, "a", run_once), phase_of(root, "b", run_once)
    (root / "a" / "bench.py").write_text(QUADRATIC)
    (root / "b" / "bench.py").write_text(LINEAR)

    scaled = measure_scaling(b, workload(sizes=(600, 2400), command=(sys.executable, "bench.py")), twin=a)  # fmt: skip

    assert scaled.notes == ()
    assert [r.stats.n for r in (*scaled.a, *scaled.b)] == [2, 2, 2, 2]
    base, trial, change = judged(scaled)
    assert base > 1.0 and change < -0.6
