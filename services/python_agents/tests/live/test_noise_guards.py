"""Offline guards of the runner noise calibration (``noise.py``, Window 0).

Not ``live``: these run in the normal suite and spend nothing. They prove
the numbers the live suite records are the ones it claims:

- the arithmetic: the CV (sample stdev over the mean), the interpolated
  95th percentile, the ordered pairs and their relative differences;
- the A/A test on synthetic measurements: the real ``SpeedJudge`` and its
  noise rule decide every ordered pair (checked pair by pair against the
  judge itself), the real verdict path (``derive_verdict`` over the active
  default judges) and the real ``MemoryJudge``;
- one repository's summary, the per-repository and summary notes (their
  exact format, under the cost table's 200-character cell), the rows;
- the plan: ``LIVE_NOISE_K`` bounds, the wall-time model and how K scales
  down past the budget, the cap (no Claude request: 0 USD) and the need;
- the targets: every OSS library and every corpus control, once each;
- the guards: a request on the wire, an unsandboxed launch or a changed
  repository each fail them;
- the whole driver offline, in the real sandbox, on the ``lettertally``
  control (``make_repo`` stands in for the clone; the real preflight,
  baseline runner, ``run_once`` and judges run): two baselines, measured,
  judged and recorded, the repository untouched.
"""

from __future__ import annotations

import functools
import json
import math
import os
import statistics
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from e2e.conftest import Isolation, Launch, LaunchLog, UserRepo, _sandbox_problem

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_CPU_TIME_S,
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    Baseline,
    JudgeOutcome,
    Measurement,
    RunStats,
)
from autonomous_ai_agents.optimization.judges import SpeedJudge

from . import noise
from .conftest import LiveRun, make_repo
from .corpus import CORPUS
from .discovery_io import ResultsSink
from .oss import OSS_CORPUS, CloneRefusedError

PID = "project-noise"
WID = "workload-noise"
PRINT = "a" * 64
NOTE_CHARS = 200  # the cost table's cell


def _row(metric: str, samples: Sequence[float], fingerprint: str | None) -> Measurement:
    unit = "bytes" if metric == METRIC_PEAK_RSS_BYTES else "s"
    return Measurement(
        workload_id=WID,
        metric=metric,
        stats=RunStats.from_samples(samples, unit=unit),
        samples=tuple(samples),
        output_fingerprint=fingerprint,
    )


def _baseline(
    wall: Sequence[float],
    rss: Sequence[float] = (100e6,) * 5,
    fingerprint: str | None = PRINT,
) -> tuple[Measurement, ...]:
    """What ``GitBaselineRunner.measure`` returns without a test command."""
    return (
        _row(METRIC_WALL_TIME_S, wall, fingerprint),
        _row(METRIC_CPU_TIME_S, wall, fingerprint),
        _row(METRIC_PEAK_RSS_BYTES, rss, fingerprint),
    )


def _around(mean: float, spread: float = 0.001) -> tuple[float, ...]:
    return (mean - 2 * spread, mean - spread, mean, mean + spread, mean + 2 * spread)


# ---------------------------------------------------------------------------
# Arithmetic
# ---------------------------------------------------------------------------


def test_cv_is_the_sample_stdev_over_the_absolute_mean() -> None:
    assert noise.cv([1.0, 2.0, 3.0]) == pytest.approx(0.5)
    assert noise.cv([-1.0, -2.0, -3.0]) == pytest.approx(0.5)
    assert noise.cv([2.0, 2.0]) == 0.0
    assert noise.cv([5.0]) is None  # no spread from one value
    assert noise.cv([]) is None
    assert noise.cv([-1.0, 1.0]) is None  # a zero mean


def test_percentile_interpolates_between_closest_ranks() -> None:
    assert noise.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.95) == pytest.approx(4.8)
    assert noise.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == pytest.approx(3.0)
    assert noise.percentile([1.0, 2.0], 0.0) == 1.0
    assert noise.percentile([1.0, 2.0], 1.0) == 2.0
    assert noise.percentile([7.0], 0.95) == 7.0
    with pytest.raises(ValueError, match="no values"):
        noise.percentile([], 0.95)
    with pytest.raises(ValueError, match="quantile"):
        noise.percentile([1.0], 1.5)


def test_ordered_pairs_are_every_i_j_with_i_not_j() -> None:
    assert noise.ordered_pairs(1) == ()
    assert noise.ordered_pairs(3) == ((0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1))
    assert len(noise.ordered_pairs(10)) == 90


def test_pair_diffs_are_relative_to_the_first_of_each_pair() -> None:
    diffs = noise.pair_diffs([1.0, 1.1])
    assert diffs == pytest.approx((0.1, 0.1 / 1.1))
    assert noise.pair_diffs([0.0, 1.0]) == pytest.approx((1.0,))  # i's mean 0: skip
    assert noise.pair_diffs([2.0]) == ()


# ---------------------------------------------------------------------------
# The A/A test through the real judges
# ---------------------------------------------------------------------------


def test_aa_pairs_are_decided_by_the_real_speed_judge() -> None:
    """B2 is 5 % faster than B1 and B3 with a tight spread: exactly (1, 2)
    and (3, 2) clear max(2 stdev, 2 %); every pair matches the judge."""
    baselines = [
        _baseline(_around(1.0)),
        _baseline(_around(0.95)),
        _baseline(_around(1.0)),
    ]
    counts = noise.aa_counts(PID, baselines)
    assert (counts.pairs, counts.speed_wins) == (6, 2)
    judge = SpeedJudge(noise_multiplier=settings.NOISE_MULTIPLIER)
    objective = noise.runtime_objective(PID)
    expected = 0
    for i, j in noise.ordered_pairs(3):
        base = Baseline(measurements=baselines[i], objectives=(objective,))
        trial = noise.as_trial(noise.aa_hypothesis(PID), baselines[j])
        expected += judge.evaluate(base, trial).outcome is JudgeOutcome.passed
    assert counts.speed_wins == expected
    assert counts.keeps == 2  # equivalent output, RSS unchanged: both would ship
    assert counts.memory_wins == 0


def test_aa_respects_the_relative_floor_and_the_stdev_floor() -> None:
    inside = [_baseline(_around(1.0)), _baseline(_around(0.985))]  # 1.5 % < 2 %
    assert noise.aa_counts(PID, inside).speed_wins == 0
    wide = [_baseline(_around(1.0, 0.03)), _baseline(_around(0.95, 0.03))]
    assert noise.aa_counts(PID, wide).speed_wins == 0  # 5 % < 2 stdev (9.5 %)
    assert noise.runtime_objective(PID).min_relative_gain == settings.MIN_RELATIVE_GAIN


def test_aa_keep_needs_the_whole_verdict() -> None:
    """A speed win on a different output is rejected by the equivalence
    judge; a memory win counts under a peak-memory objective only."""
    split = [_baseline(_around(1.0)), _baseline(_around(0.9), fingerprint="b" * 64)]
    counts = noise.aa_counts(PID, split)
    assert (counts.speed_wins, counts.keeps) == (1, 0)
    leaner = [
        _baseline(_around(1.0), rss=_around(100e6, 1e3)),
        _baseline(_around(1.0), rss=_around(90e6, 1e3)),
    ]
    counts = noise.aa_counts(PID, leaner)
    assert (counts.speed_wins, counts.keeps, counts.memory_wins) == (0, 0, 1)


def test_aa_of_fewer_than_two_baselines_has_no_pair() -> None:
    assert noise.aa_counts(PID, [_baseline(_around(1.0))]).pairs == 0
    assert noise.aa_counts(PID, []).pairs == 0


# ---------------------------------------------------------------------------
# One repository's summary, the notes, the rows
# ---------------------------------------------------------------------------


def _repo(
    name: str = "lettertally", means: Sequence[float] = (1.0, 0.95, 1.0)
) -> noise.RepoNoise:
    baselines = [_baseline(_around(mean)) for mean in means]
    return noise.summarize_repo(
        name, "control", len(means) + 1, PID, baselines, ("baseline 4: boom",), 12.3
    )


def test_summarize_repo_reports_within_between_and_pairs() -> None:
    found = _repo()
    assert found.k == 3 and found.k_planned == 4
    assert found.cv_time == pytest.approx(0.001 * math.sqrt(2.5))  # the median
    assert found.cv_mem == 0.0
    assert found.between_time == pytest.approx(noise.cv([1.0, 0.95, 1.0]))
    assert found.aa.speed_wins == 2 and found.aa.pairs == 6
    assert found.diffs == pytest.approx(noise.pair_diffs([1.0, 0.95, 1.0]))
    assert found.p95_diff == pytest.approx(noise.percentile(found.diffs, 0.95))
    assert found.floor_too_low is True  # p95 0.0526 > 0.02
    assert found.noisy == 0  # mean 1 s, floor 2 %: not a noisy host
    assert found.floor_median == pytest.approx(settings.MIN_RELATIVE_GAIN)
    assert found.failures == ("baseline 4: boom",)


def test_a_short_workload_is_flagged_noisy_by_the_engines_own_check() -> None:
    baselines = [_baseline(_around(0.3)), _baseline(_around(0.3))]
    found = noise.summarize_repo("tiny", "control", 2, PID, baselines, (), 1.0)
    assert found.noisy == 2  # under 0.5 s: dominated by start-up
    assert found.floor_too_low is False  # identical means: p95 0


def test_a_repository_with_one_baseline_has_no_pair_statistics() -> None:
    found = noise.summarize_repo(
        "one", "oss", 6, PID, [_baseline(_around(1.0))], (), 1.0
    )
    assert (found.k, found.aa.pairs, found.p95_diff, found.between_time) == (
        1,
        0,
        None,
        None,
    )
    assert found.floor_too_low is None
    assert "aa_wins 0/0 p95_diff n/a" in noise.repo_note(found)


def test_repo_note_has_the_agreed_format_and_fits_a_cell() -> None:
    found = _repo()
    note = noise.repo_note(found)
    assert note == (
        f"NOISE lettertally: k 3 cv_time {found.cv_time:.4f} cv_mem 0.0000 "
        f"aa_wins 2/6 p95_diff {found.p95_diff:.4f}"
    )
    longest = _repo("more_itertools", (1.0,) * 10)
    for text in (noise.repo_note(longest), noise.spread_note(longest)):
        assert len(text) <= NOTE_CHARS, text
    spread = noise.spread_note(found)
    assert spread.startswith("NOISE spread lettertally: between_time ")
    assert "noisy 0/3" in spread and "aa_keeps 2/6" in spread
    assert "failed 1/4" in spread


def test_summary_pools_pairs_and_counts_repos_past_the_floor() -> None:
    quiet = _repo("quiet", (1.0, 1.001, 0.999))
    loud = _repo("loud", (1.0, 0.95, 1.0))
    one = noise.summarize_repo("one", "oss", 6, PID, [_baseline(_around(1.0))], (), 1.0)
    found = noise.summarize([quiet, loud, one])
    assert found.measured == 2  # "one" has no pair
    assert found.wins == loud.aa.speed_wins + quiet.aa.speed_wins
    assert found.pairs == 12
    cvs = [r.cv_time for r in (quiet, loud, one) if r.cv_time is not None]
    assert len(cvs) == 3
    assert found.median_cv == pytest.approx(statistics.median(cvs))
    assert found.p95_diff == pytest.approx(
        noise.percentile([*quiet.diffs, *loud.diffs], 0.95)
    )
    assert found.too_low == 1
    note = noise.summary_note(found)
    assert note == (
        f"NOISE summary: median cv {found.median_cv:.4f}, aa false-win rate "
        f"{found.wins / found.pairs:.4f}, p95 diff {found.p95_diff:.4f}, floor 0.02 "
        "too low on 1/2 repos"
    )
    assert len(note) <= NOTE_CHARS


def test_an_empty_summary_says_na() -> None:
    note = noise.summary_note(noise.summarize([]))
    assert note == (
        "NOISE summary: median cv n/a, aa false-win rate n/a, p95 diff n/a, "
        "floor 0.02 too low on 0/0 repos"
    )


def test_rows_and_notes_reach_the_sink_the_run_and_the_log(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    plan = noise.noise_plan({}, noise.NOISE_TARGETS[:1])
    recorder = noise.NoiseRecorder(plan, sink)
    run = LiveRun("noise", noise.NOISE_RUN_CAP_USD)
    recorder.record(_repo(), run)
    recorder.record_error("idna", run, "CloneRefusedError: no route")
    summary_run = LiveRun("summary", noise.NOISE_RUN_CAP_USD)
    recorder.summarize(summary_run)
    rows = [json.loads(line) for line in results.read_text().splitlines()]
    assert [row["kind"] for row in rows] == ["control", "error", "summary"]
    assert rows[0]["repo"] == "lettertally" and rows[0]["aa_wins"] == 2
    assert rows[1] == {"experiment": "noise", "kind": "error", "repo": "idna",
                       "error": "CloneRefusedError: no route"}  # fmt: skip
    assert run.notes[0].startswith("NOISE lettertally: k 3 ")
    assert run.notes[1].startswith("NOISE spread lettertally: ")
    assert run.notes[2] == "NOISE idna: error CloneRefusedError: no route"
    assert summary_run.notes[0].startswith("NOISE summary: median cv ")
    assert summary_run.notes[1].startswith("NOISE summary detail: k ")
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert any(line.startswith("| lettertally | control | 3 |") for line in echoed)
    assert any(line.startswith("| idna | error |") for line in echoed)


# ---------------------------------------------------------------------------
# The plan: K, wall time, cap, need
# ---------------------------------------------------------------------------


def test_k_defaults_to_six_and_is_bounded() -> None:
    assert noise.noise_plan({}).k_requested == noise.NOISE_K == 6
    assert noise.noise_plan({noise.NOISE_K_ENV: "10"}).k_requested == 10
    assert noise.noise_plan({noise.NOISE_K_ENV: "2"}).k == 2
    for bad in ("1", "11", "0", "six", " 6", "6.0", ""):
        with pytest.raises(ValueError, match=noise.NOISE_K_ENV):
            noise.noise_plan({noise.NOISE_K_ENV: bad})


def test_the_wall_time_model_adds_setup_and_every_baseline() -> None:
    runs = noise.baseline_runs()
    assert runs == 1 + settings.MIN_RUNS  # one warm-up, N timed
    target = noise.NOISE_TARGETS[0]
    one = runs * (target.run_s * noise.RUNNER_SLOWDOWN + noise.LAUNCH_OVERHEAD_S)
    assert noise.baseline_s(target) == pytest.approx(one + noise.BASELINE_OVERHEAD_S)
    assert noise.estimate_s([target], 3) == pytest.approx(
        target.setup_s + 3 * noise.baseline_s(target)
    )


def test_the_default_plan_fits_the_hour_and_k_scales_down_past_it() -> None:
    plan = noise.noise_plan({})
    assert plan.k == plan.k_requested == 6
    assert plan.estimate_s <= noise.WALL_BUDGET_S
    assert noise.noise_plan({noise.NOISE_K_ENV: "10"}).k == 10  # about 37 min
    targets = noise.NOISE_TARGETS
    budget = noise.estimate_s(targets, 4) + 1.0
    scaled = noise.noise_plan({noise.NOISE_K_ENV: "10"}, targets, budget)
    assert (scaled.k_requested, scaled.k) == (10, 4)
    assert scaled.estimate_s == pytest.approx(noise.estimate_s(targets, 4))
    with pytest.raises(ValueError, match="even K=2"):
        noise.noise_plan({}, targets, noise.estimate_s(targets, 2) - 1.0)


def test_the_cap_is_the_sum_of_worst_cases_of_no_request() -> None:
    assert noise.NOISE_REQUESTS_WORST_USD == ()  # no Claude call at all
    assert noise.NOISE_RUN_CAP_USD == 0.0
    plan = noise.noise_plan({noise.NOISE_K_ENV: "10"})
    assert plan.runs == len(plan.targets) + 1  # one per repository, the summary
    assert noise.noise_need(plan) == 0.0
    LiveRun("admitted", noise.NOISE_RUN_CAP_USD)  # a 0 USD cap is a valid run


def test_targets_are_every_oss_library_and_every_corpus_control() -> None:
    names = [t.name for t in noise.NOISE_TARGETS]
    controls = [repo.name for repo in CORPUS if repo.kind == "control"]
    assert names == [repo.name for repo in OSS_CORPUS] + controls
    assert "lettertally" in controls and len(set(names)) == len(names)
    for target, repo in zip(noise.NOISE_TARGETS, OSS_CORPUS, strict=False):
        assert target.kind == "oss" and target.argv == repo.workload_argv
        assert 0.3 <= target.run_s <= 5.0  # the profile's "(x s plain)"
    for target in noise.NOISE_TARGETS[len(OSS_CORPUS) :]:
        assert target.kind == "control" and target.run_s == noise.CONTROL_RUN_S


def test_plain_seconds_reads_the_profile_or_refuses() -> None:
    assert (
        noise.plain_seconds("cProfile, 3.6 s under the profiler (0.8 s plain)") == 0.8
    )
    with pytest.raises(ValueError, match="plain"):
        noise.plain_seconds("cProfile, 3.6 s under the profiler")


# ---------------------------------------------------------------------------
# The guards and the whole driver, offline in the sandbox
# ---------------------------------------------------------------------------


def _require_sandbox() -> None:
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        required = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
        if any(os.environ.get(name) == "1" for name in required):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(f"the host cannot sandbox: {problem}")


def _control() -> noise.NoiseTarget:
    (target,) = [t for t in noise.NOISE_TARGETS if t.name == "lettertally"]
    return target


@pytest.fixture(scope="module")
def measured(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[tuple[noise.TargetRun, LaunchLog]]:
    """Two baselines of ``lettertally``, once for the module (about 7 s)."""
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path_factory.mktemp("noise")))
    (root / "wt-root").mkdir()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
        launches = LaunchLog()
        found = noise.measure_target(
            _control(), root, Isolation("required", None), launches, 2
        )
        yield found, launches


def test_the_driver_measures_a_control_offline_in_the_sandbox(
    measured: tuple[noise.TargetRun, LaunchLog],
) -> None:
    found, launches = measured
    assert found.failures == () and len(found.baselines) == 2
    for rows in found.baselines:
        assert {m.metric for m in rows} == {
            METRIC_WALL_TIME_S, METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES
        }  # fmt: skip
        assert all(m.stats.n == settings.MIN_RUNS for m in rows)
        assert all(m.output_fingerprint is not None for m in rows)
    assert launches.phases() == {"preflight", "baseline"}
    per_baseline = noise.baseline_runs()
    baseline_launches = [x for x in launches.launches if x.phase == "baseline"]
    assert len(baseline_launches) == 2 * per_baseline  # no test suite launch
    run = LiveRun("offline", noise.NOISE_RUN_CAP_USD)
    noise.check_noise_guards(run, found, launches, Isolation("required", None))
    repo = noise.summarize_target(_control(), found, 2)
    assert repo.k == 2 and repo.aa.pairs == 2 and repo.p95_diff is not None


def test_the_guards_refuse_any_request_on_the_wire(
    measured: tuple[noise.TargetRun, LaunchLog],
) -> None:
    found, launches = measured
    run = LiveRun("offline", noise.NOISE_RUN_CAP_USD)
    run.records.append(object())  # type: ignore[arg-type]  # a recorded request
    with pytest.raises(AssertionError, match="no request"):
        noise.check_noise_guards(run, found, launches, Isolation("required", None))


def test_the_guards_refuse_a_breach_another_phase_or_a_changed_repo(
    measured: tuple[noise.TargetRun, LaunchLog],
) -> None:
    found, launches = measured
    isolation = Isolation("required", None)
    run = LiveRun("offline", noise.NOISE_RUN_CAP_USD)
    with pytest.raises(AssertionError):
        noise.check_noise_guards(run, found, launches, Isolation("best_effort", "x"))
    for extra in (
        Launch("baseline", "off", "off", False, False),
        Launch("baseline", "required", "required", False, True),
        Launch("profile", "required", "required", True, True),
    ):
        widened = LaunchLog()
        widened.launches = [*launches.launches, extra]
        with pytest.raises(AssertionError):
            noise.check_noise_guards(run, found, widened, isolation)
    stray = found.user.path / "stray.txt"
    stray.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(AssertionError):
            noise.check_noise_guards(run, found, launches, isolation)
    finally:
        stray.unlink()
    noise.check_noise_guards(run, found, launches, isolation)  # as before


@pytest.mark.parametrize(
    ("main", "reason"),
    [
        ("raise SystemExit(3)\n", "exit status 3"),
        ("import random\nprint(random.random())\n", "nondeterministic"),
    ],
    ids=["crash", "nondeterministic"],
)
def test_an_untrusted_baseline_is_recorded_not_raised(
    main: str, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _require_sandbox()
    root = Path(os.path.realpath(tmp_path))
    (root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    source = root / "src"
    (source / "flaky").mkdir(parents=True)
    (source / "flaky" / "__init__.py").write_text("", encoding="utf-8")
    (source / "flaky" / "main.py").write_text(main, encoding="utf-8")
    target = noise.NoiseTarget(
        "flaky", "control", ("python", "-m", "flaky.main"), 0.1, 1.0,
        functools.partial(make_repo, source),
    )  # fmt: skip
    launches = LaunchLog()
    found = noise.measure_target(target, root, Isolation("required", None), launches, 1)
    assert found.baselines == ()
    (failure,) = found.failures
    assert failure.startswith("baseline 1: ") and reason in failure
    noise.check_noise_guards(
        LiveRun("x", 0.0), found, launches, Isolation("required", None)
    )
    empty = noise.summarize_target(target, found, 1)
    assert (empty.k, empty.cv_time, empty.aa.pairs, empty.mean_time_s) == (
        0,
        None,
        0,
        None,
    )


def test_a_failed_preparation_is_recorded_then_raised(tmp_path: Path) -> None:
    def refuse(dest: Path) -> UserRepo:
        raise CloneRefusedError("no route to github.com")

    target = noise.NoiseTarget("gone", "oss", ("python", "x.py"), 1.0, 1.0, refuse)
    recorder = noise.NoiseRecorder(noise.noise_plan({}, [target]), ResultsSink({}))
    run = LiveRun("gone", noise.NOISE_RUN_CAP_USD)
    with pytest.raises(CloneRefusedError):
        noise.run_target(target, run, tmp_path, Isolation("required", None), recorder)
    assert recorder.errors == [("gone", "CloneRefusedError: no route to github.com")]
    assert run.notes == ["NOISE gone: error CloneRefusedError: no route to github.com"]


# ---------------------------------------------------------------------------
# Review findings: the job timeout, a guard failure's row, the baselines' span
# ---------------------------------------------------------------------------


def test_the_job_timeout_covers_setup_the_budget_and_an_overrun() -> None:
    """The Lead sets live-smoke's ``noise`` timeout to ``NOISE_JOB_MINUTES``:
    job setup, the wall budget, then the target in flight when the budget
    runs out (twice its estimate at the largest K) still fit inside it, and
    a runner twice as slow as the model still finishes the default plan."""
    job_s = noise.NOISE_JOB_MINUTES * 60
    largest = max(noise.estimate_s([t], noise.NOISE_MAX_K) for t in noise.NOISE_TARGETS)
    assert noise.JOB_SETUP_S + noise.WALL_BUDGET_S + 2 * largest <= job_s
    assert noise.WALL_BUDGET_S == job_s - noise.JOB_SETUP_S - noise.OVERRUN_S
    assert 2 * noise.largest_target_s() <= noise.OVERRUN_S
    assert 2 * noise.noise_plan({}).estimate_s <= noise.WALL_BUDGET_S
    assert noise.noise_plan({}).budget_s == noise.WALL_BUDGET_S
    assert noise.NOISE_JOB_MINUTES <= 360  # the hosted maximum


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_target_past_the_wall_budget_is_skipped_and_recorded(
    tmp_path: Path,
) -> None:
    def never(dest: Path) -> UserRepo:
        raise AssertionError("prepared past the budget")

    target = noise.NoiseTarget("late", "oss", ("python", "x.py"), 1.0, 1.0, never)
    results = tmp_path / "results.jsonl"
    clock = _Clock()
    plan = noise.noise_plan({}, [target])
    recorder = noise.NoiseRecorder(
        plan, ResultsSink({"LIVE_RESULTS_PATH": str(results)}), clock=clock
    )
    clock.now += plan.budget_s  # exactly at the budget: still measured
    assert not recorder.past_budget()
    clock.now += 1.0
    assert recorder.past_budget()
    run = LiveRun("late", noise.NOISE_RUN_CAP_USD)
    found = noise.run_target(
        target, run, tmp_path, Isolation("required", None), recorder
    )
    assert found is None and recorder.results == []
    (row,) = [json.loads(line) for line in results.read_text().splitlines()]
    assert row["kind"] == "skipped" and row["repo"] == "late"
    assert run.notes == [
        f"NOISE late: skipped past the wall budget ({plan.budget_s / 60:.0f} min)"
    ]
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert any(line.startswith("| late | skipped |") for line in echoed)


def _faked_driver(
    monkeypatch: pytest.MonkeyPatch, measured: tuple[noise.TargetRun, LaunchLog]
) -> None:
    """``measure_target`` replaced by the module's real offline measurement
    (the fake stands for the live driver: same rows, same launches)."""
    found, real = measured

    def replay(
        target: noise.NoiseTarget,
        root: Path,
        isolation: Isolation,
        launches: LaunchLog,
        k: int,
    ) -> noise.TargetRun:
        launches.launches.extend(real.launches)
        return found

    monkeypatch.setattr(noise, "measure_target", replay)


def test_a_guard_failure_is_an_error_row_not_a_clean_one(
    measured: tuple[noise.TargetRun, LaunchLog],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _faked_driver(monkeypatch, measured)
    results = tmp_path / "results.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(results)})
    recorder = noise.NoiseRecorder(noise.noise_plan({}, [_control()]), sink)
    run = LiveRun("breach", noise.NOISE_RUN_CAP_USD)
    run.records.append(object())  # type: ignore[arg-type]  # a request was sent
    with pytest.raises(AssertionError, match="no request"):
        noise.run_target(
            _control(), run, tmp_path, Isolation("required", None), recorder
        )
    assert recorder.results == []  # kept out of the table's rows and the pool
    ((name, error),) = recorder.errors
    assert name == "lettertally" and error.startswith("guards: no request")
    (row,) = [json.loads(line) for line in results.read_text().splitlines()]
    assert row["kind"] == "error" and row["error"].startswith("guards: no request")
    assert row["measured"]["kind"] == "control"  # the numbers are not lost
    assert row["measured"]["k"] == 2
    assert run.notes == [f"NOISE lettertally: error {error}"]
    assert noise.summarize(recorder.results).measured == 0


def test_a_clean_target_is_recorded_after_its_guards_pass(
    measured: tuple[noise.TargetRun, LaunchLog],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _faked_driver(monkeypatch, measured)
    recorder = noise.NoiseRecorder(noise.noise_plan({}, [_control()]), ResultsSink({}))
    run = LiveRun("clean", noise.NOISE_RUN_CAP_USD)
    found = noise.run_target(
        _control(), run, tmp_path, Isolation("required", None), recorder
    )
    assert found is not None and recorder.results == [found]
    assert recorder.errors == []
    assert run.notes[0].startswith("NOISE lettertally: k 2 ")


def test_every_guard_names_itself(
    measured: tuple[noise.TargetRun, LaunchLog],
) -> None:
    """A guard failure's row and note say which guard failed."""
    found, launches = measured
    isolation = Isolation("required", None)
    run = LiveRun("offline", noise.NOISE_RUN_CAP_USD)
    with pytest.raises(AssertionError, match="^isolation not required"):
        noise.check_noise_guards(run, found, launches, Isolation("best_effort", "x"))
    for extra, label in (
        (Launch("baseline", "off", "off", False, False), "unsandboxed launch"),
        (
            Launch("baseline", "required", "required", False, True),
            "launch not isolated",
        ),
        (Launch("profile", "required", "required", True, True), "phases outside"),
    ):
        widened = LaunchLog()
        widened.launches = [*launches.launches, extra]
        with pytest.raises(AssertionError, match=f"^{label}"):
            noise.check_noise_guards(run, found, widened, isolation)
    preflight_only = LaunchLog()
    preflight_only.launches = [x for x in launches.launches if x.phase == "preflight"]
    with pytest.raises(AssertionError, match="^no baseline launch"):
        noise.check_noise_guards(run, found, preflight_only, isolation)
    with pytest.raises(AssertionError, match="^phases outside"):
        noise.check_noise_guards(run, found, LaunchLog(), isolation)
    stray = found.user.path / "stray.txt"
    stray.write_text("x", encoding="utf-8")
    try:
        with pytest.raises(AssertionError, match="^user repository changed"):
            noise.check_noise_guards(run, found, launches, isolation)
    finally:
        stray.unlink()


def test_the_baselines_span_is_recorded(
    measured: tuple[noise.TargetRun, LaunchLog],
) -> None:
    found, _ = measured
    assert len(found.offsets_s) == len(found.baselines) == 2
    assert found.offsets_s[0] == 0.0 < found.offsets_s[1]
    repo = noise.summarize_target(_control(), found, 2)
    assert repo.span_s == pytest.approx(found.offsets_s[1])
    assert repo.row()["offsets_s"] == list(found.offsets_s)


def test_span_reaches_the_row_the_notes_and_the_summary() -> None:
    baselines = [_baseline(_around(1.0)) for _ in range(3)]
    repo = noise.summarize_repo(
        "lettertally",
        "control",
        3,
        PID,
        baselines,
        (),
        30.0,
        offsets_s=(0.0, 5.0, 12.5),
    )
    assert repo.span_s == 12.5 and repo.row()["span_s"] == 12.5
    assert "span_s 12" in noise.spread_note(repo)
    one = noise.summarize_repo(
        "one", "oss", 6, PID, baselines[:1], (), 1.0, offsets_s=(3.0,)
    )
    assert one.span_s is None
    found = noise.summarize([repo, one])
    assert found.span_max_s == 12.5
    plan = noise.noise_plan({})
    detail = noise.detail_note(found, plan, 60.0)
    assert "span max 12 s" in detail and "lower bound" in detail
    worst = noise.NoiseSummary(
        0.123456, 0.123456, 1170, 1170, 1170, 1170, 0.123456, 13, 13, 99999.0
    )
    big = noise.NoisePlan(plan.targets, 10, 10, 360 * 60.0, plan.budget_s)
    for text in (noise.detail_note(worst, big, 360 * 60.0), noise.summary_note(worst)):
        assert len(text) <= NOTE_CHARS, text
    longest = noise.summarize_repo(
        "more_itertools", "oss", 10, PID, [_baseline(_around(1.0))] * 10, ("x",) * 10,
        9999.0, offsets_s=tuple(float(i * 999) for i in range(10)),
    )  # fmt: skip
    assert len(noise.spread_note(longest)) <= NOTE_CHARS
    assert "span_s n/a" in noise.spread_note(one)
