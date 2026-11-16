"""UEX (O71 item 4): the engine sits the four retired practical papers.

One unmodified X2-0 run per paper, **one paper a dispatch**, on key 2, with
the gain-ordered combine (``SITE_STACKS="on"``), labelled ``X2-EX``
(``X2_EX``: X2-0's mapping plus that one key, off ``ideas_x2.EVERY_ARM``, so
no X2 dispatch can select it).

**The target.** A paper reaches the X2 harness as an ``ExamRepo``, the
``OssRepo`` of a local tree: the committed manifest is checked against the
pins here (``ARCHIVE_SHA256``, ``SEAL_TREE_SHA256``, ``TIER_COMMITS``), then
the archive's bytes against the manifest, before anything is opened, and it
unpacks outside the repository (``exam_archive``); each tier is initialised
there as a git repository at its pinned commit (``init_paper``); then
``ideas_x2.start_x2_loop`` takes it, unchanged, through ``oss.prepare_repo``
over ``exam_policy`` (``file://``, those four repositories only). What the
engine sees is neutral: the library ``p1`` to ``p4``, the bench
``benchmarks/bench_pN.py`` (a wrapper running the repository's own
``bench.py``, which prints a time the byte-for-byte output check would
refuse at the baseline as nondeterministic), the commit "initial import".
The test command is the paper's (tier 3's ``PYTHONPATH=src`` is its
``pyproject.toml``'s ``pythonpath``, which pytest reads anyway).

**The cap and the fuse.** ``exam_run_cap``: X2's ``run_cap`` share term
alone, the least cap whose D55 discovery share still admits the seeded
call's dearest stage after a first call at X1's dearest measured: 6.50 (a
run whose ``unaffordable`` count is not 0 is not X2-0's). A dispatch names
its paper (``LIVE_EXAM_PAPER``) and what the earlier papers spent
(``LIVE_EXAM_SPENT_USD``, the Lead's running total); ``exam_plan`` refuses,
before any request, unless spent + 6.50 is at most the suite cap, itself at
most the owner's 14.50 (``EXAM_BUDGET_USD``, O72 item 1).

**The minutes.** ``paper_minutes``: every launch a run can make, counted
from the judges' rules (``launches``), at the paper's measured workload and
suite seconds (``ExamPaper``), plus setup, the clone, the editor's turns and
two pipeline calls at their worst, times ``MARGIN``; ``paper_timeout``
rounds it up to 5 minutes, ci.yml's timeout for the paper, and
``exam_plan`` refuses a paper past GitHub's 360.

**Isolation.** The run's lessons live in the in-memory repository
``build_context`` gives every X2 loop (none in, none out); X2-0 keeps
``GENERATOR_LESSONS`` off and no lane views; the example bank is engine
source. Its rows and patches go to the job's results artifact only, and the
Lead archives them under ``SITTING_ROWS``, a folder no archive reader lists
(``test_exam_sitting_guards``). The live module only delegates
(``open_sitting``, ``sit_case``), pinned by its syntax tree.
"""

from __future__ import annotations

import dataclasses
import functools
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from e2e.conftest import Isolation, UserRepo

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import discovery as dsc
from . import exam_archive as ea
from . import ideas_probe as ip
from . import ideas_slice as isl
from . import ideas_x2 as x2
from . import ideas_x2_frameworks as fx
from . import oss
from . import x2_looks as xl
from .conftest import TESTS_DIR, StartLive, key_window, suite_cap
from .corpus import HypothesisSpec
from .discovery import ceil_usd
from .discovery_io import ResultsSink
from .oss import GitPolicy, OssRepo

SITTING_ROWS: Final = (
    ea.REPO_ROOT / ".claude/handoff/step3/idea-lab/w2-sprint/live/exam-sitting"
)
WORKLOADS: Final = TESTS_DIR / "fixtures" / "exam_sitting" / "workloads"
BENCH_SCRIPT: Final = "bench.py"
EXAM_BUDGET_USD: Final = 14.5  # O72 item 1: the owner's budget (O71: 12)
EXAM_WINDOW: Final = "W2"  # key 2 (U-key)
PAPER_ENV: Final = "LIVE_EXAM_PAPER"
SPENT_ENV: Final = "LIVE_EXAM_SPENT_USD"
# Pinned from the Lead's build of the papers (python -m live.exam_archive):
# the committed manifest cannot be rewritten with the archive unnoticed.
ARCHIVE_SHA256: Final = (
    "3adcfdf72b8748cb8a8f7b51d85735f781db44d6ca27dfbecde49f16416cdd4a"
)
SEAL_TREE_SHA256: Final = (  # exam-seal.md, papers of the first sitting
    "015e9cbed23c2354f9e3550b500bf6f48640124b58ff0ec3b4c105868fd7a3f0"
)
TIER_COMMITS: Final[Mapping[str, str]] = {
    "tier-1": "7efdbf00fb7362121f2f53b91fc45dec2a66889c",
    "tier-2": "f245375e014446167cf4188b9fda316d8c1cad95",
    "tier-3": "856c33b94a7a03d3fc0a564d43bea0a90c31038a",
    "tier-4": "bf8c7496a19c6ea7899cac2ec74a3ad71b82b348",
}
PYTEST: Final = ("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests")
UNUSED: Final = (  # never trialled: an X2 loop runs wired, on the engine's own ideas
    HypothesisSpec("unused-aimed", "not trialled: the run is wired", True, 0.6),
    HypothesisSpec("unused-neutral", "not trialled: the run is wired", False, 0.3),
)
# The minutes (paper_minutes): per launch, the reset, the sandbox and the
# interpreter's start; the counted run (OP_COUNT_JUDGE: 1.5-3x a run) and the
# profile run at 3 runs each; a trial's editor turns; setup before the tests
# (checkout, uv sync, the sandbox probe, the papers unpacked and initialised)
LAUNCH_OVERHEAD_S: Final = 1.0
COUNTED_RUNS: Final = 3.0
PROFILE_RUNS: Final = 3.0
EDIT_SECONDS: Final = 60.0
SETUP_MINUTES: Final = 10
COMBINE_RETESTS: Final = 2  # the greedy merge's re-test and the fallback's
MARGIN: Final = 1.25
JOB_CEILING: Final = 360  # GitHub's most for a job


@dataclass(frozen=True)
class ExamPaper:
    """One practical paper: its tier, what the engine calls it (``name``),
    what it is, and its workload's and suite's measured seconds a run (the
    reviewer's and the builder's, the larger; 2026-11-15)."""

    tier: str
    library: str
    package: str
    module_root: str
    license: str
    license_file: str
    test_command: tuple[str, ...]
    workload_s: float
    suite_s: float

    @property
    def key(self) -> str:
        return f"t{self.tier.removeprefix('tier-')}"  # the dispatch's exam_paper

    @property
    def name(self) -> str:
        return ea.tag(self.tier)  # p1: neutral, oss.NAME, the bench path


EXAM_PAPERS: Final = (
    ExamPaper("tier-1", "tomli", "tomli", "src/tomli", "MIT", "LICENSE", PYTEST, 2.3, 2.0),
    ExamPaper("tier-2", "sqlparse", "sqlparse", "sqlparse", "BSD-3-Clause", "LICENSE",
              PYTEST, 16.5, 20.0),
    ExamPaper("tier-3", "mistune", "mistune", "src/mistune", "BSD-3-Clause", "LICENSE",
              PYTEST, 6.3, 4.0),
    ExamPaper("tier-4", "markdown", "markdown", "markdown", "BSD-3-Clause", "LICENSE.md",
              ("python", "-m", "unittest", "discover", "tests"), 11.3, 3.0),
)  # fmt: skip
BY_KEY: Final = {p.key: p for p in EXAM_PAPERS}
X2_EX: Final = x2.X2Arm("X2-EX", tuple(p.name for p in EXAM_PAPERS),
                        {**x2.X2_0.update, "SITE_STACKS": "on"},
                        "exam sitting (O71 item 4): X2-0 with the gain-ordered combine")  # fmt: skip


@dataclass(frozen=True)
class ExamRepo(OssRepo):
    """A paper as the X2 harness's library: the wrapper as its workload."""

    @property
    def workload_source(self) -> Path:
        return WORKLOADS / f"{self.name}.py"

    @property
    def workload_argv(self) -> tuple[str, ...]:
        return ("python", self.bench_path, BENCH_SCRIPT)  # protects bench.py


def exam_repo(paper: ExamPaper, url: str, commit: str) -> ExamRepo:
    return ExamRepo(
        name=paper.name, url=url, tag=paper.name, commit=commit, released="2026-11-13",
        license=paper.license, license_file=paper.license_file, package=paper.package,
        module_root=paper.module_root, test_command=paper.test_command, hypotheses=UNUSED,
        targets=((f"{paper.module_root}/__init__.py",),) * 2,
        profile=f"the {paper.name} workload",
    )  # fmt: skip


def exam_policy(source: Path) -> GitPolicy:
    """``file://`` to the four papers' repositories under ``source`` only."""
    prefix = re.escape(f"file://{source.resolve()}/")
    return GitPolicy(allow=re.compile(rf"{prefix}tier-[1-4]"), protocols="file")


# ---------------------------------------------------------------------------
# The cap, the fuse, the minutes, the plan
# ---------------------------------------------------------------------------


def exam_run_cap(cfg: Settings) -> float:
    """``ideas_x2.run_cap``'s share term alone (module docstring)."""
    s1, s2, review = x2.seeded_stages(cfg)
    stage = max(s1, x2.X1_S1_USD + s2, x2.X1_S1_S2_USD + review)
    earlier = (cfg.MAX_TRIAL_ROUNDS - 1) * x2.call_usd(cfg)
    return ceil_usd((earlier + stage) / cfg.IDEAS_DISCOVERY_MAX_SHARE)


def fuse_refusal(spent: float, cap: float, suite: float) -> str | None:
    """Why a paper cannot sit at ``cap`` when the earlier papers spent
    ``spent`` of the ``suite`` cap; ``None`` when it can."""
    if spent + cap <= suite + 1e-9:
        return None
    return (f"sitting fuse: {spent:.2f} USD spent + the {cap:.2f} an unmodified "
            f"X2-0 run needs > the {suite:.2f} USD suite cap; not sat")  # fmt: skip


@dataclass(frozen=True)
class Launches:
    """What one run can launch at most: workload runs and suite runs."""

    runs: float
    suites: int


def launches(cfg: Settings) -> Launches:
    """Every launch the judges' rules allow one X2 run, an upper bound.

    A side of an ABBA is a warm-up and ``MIN_RUNS`` timed runs (``Workload``'s
    defaults), so one ABBA is ``2 (1 + MIN_RUNS)``. The baseline: one side,
    its counted run and the suite; the calibration: ``NOISE_CALIBRATION_BLOCKS``
    A/A ABBAs, no suite; the profile: one run under cProfile. A trial: its
    paired ABBA, a counted run a side and the suite; its confirmation (every
    trial counted a would-be keep): one more ABBA and the suite; the combine:
    ``COMBINE_RETESTS`` ABBAs, each with the suite on its tip."""
    side = 1 + cfg.MIN_RUNS
    abab = 2 * side
    trials = sum(x2.run_trials(cfg))
    runs = (side + COUNTED_RUNS + cfg.NOISE_CALIBRATION_BLOCKS * abab + PROFILE_RUNS
            + trials * (abab + 2 * COUNTED_RUNS) + trials * abab
            + COMBINE_RETESTS * abab)  # fmt: skip
    return Launches(runs, 1 + 2 * trials + COMBINE_RETESTS)


def paper_minutes(paper: ExamPaper, cfg: Settings) -> float:
    """``MARGIN`` x (setup + the clone + two pipeline calls at their worst
    (``ideas_x2.run_minutes``' term) + a trial's editor turns each + every
    launch at its measured seconds plus ``LAUNCH_OVERHEAD_S`` + the riders)."""
    work = launches(cfg)
    call = ip.arm_seconds(ip.ARM_X1_0, cfg)
    seconds = (work.runs * (paper.workload_s + LAUNCH_OVERHEAD_S)
               + work.suites * (paper.suite_s + LAUNCH_OVERHEAD_S)
               + sum(x2.run_trials(cfg)) * EDIT_SECONDS + x2.rider_seconds(cfg))  # fmt: skip
    fixed = (SETUP_MINUTES + isl.CLONE_MINUTES
             + cfg.MAX_TRIAL_ROUNDS * math.ceil(call / 60))  # fmt: skip
    return MARGIN * (fixed + seconds / 60)


def paper_timeout(paper: ExamPaper, cfg: Settings) -> int:
    """ci.yml's timeout for ``paper``: ``paper_minutes`` up to a multiple of 5."""
    return 5 * math.ceil(paper_minutes(paper, cfg) / 5)


@dataclass(frozen=True)
class ExamPlan:
    paper: ExamPaper
    spent_usd: float  # what the earlier papers spent (the Lead's running total)
    cap_usd: float  # the suite cap: the sitting's whole budget
    run_cap: float
    minutes: int  # the job's timeout for this paper


def _spent(environ: Mapping[str, str]) -> float:
    raw = environ.get(SPENT_ENV, "").strip()
    try:
        spent = float(raw)
    except ValueError:
        spent = math.nan
    if not (math.isfinite(spent) and 0 <= spent <= EXAM_BUDGET_USD):
        raise ValueError(f"{SPENT_ENV} must be the USD the earlier papers spent, "
                         f"0 to {EXAM_BUDGET_USD:g}; got {raw[:20]!r}")  # fmt: skip
    return spent


def exam_plan(environ: Mapping[str, str], base: Settings = settings) -> ExamPlan:
    """Refused before any request: a key other than key 2, a paper other than
    t1 to t4, a malformed running spend, a suite cap below one run's or above
    the owner's budget, the fuse (``fuse_refusal``), or a paper whose minutes
    pass GitHub's ceiling."""
    window = key_window(environ)
    if window != EXAM_WINDOW:
        raise ValueError(
            f"the exam sitting runs on key 2 ({EXAM_WINDOW}), not {window}"
        )
    paper = BY_KEY.get(environ.get(PAPER_ENV, ""))
    if paper is None:
        raise ValueError(f"{PAPER_ENV} must be one of {', '.join(BY_KEY)}")
    cfg = x2.arm_settings(X2_EX, base)
    run, cap, spent = exam_run_cap(cfg), suite_cap(environ), _spent(environ)
    if not run <= cap <= EXAM_BUDGET_USD:
        raise ValueError(f"suite cap {cap:.2f} USD: a paper needs {run:.2f} and the "
                         f"sitting may not pass the owner's {EXAM_BUDGET_USD:g}")  # fmt: skip
    refusal = fuse_refusal(spent, run, cap)
    if refusal is not None:
        raise ValueError(refusal)
    minutes = paper_timeout(paper, cfg)
    if minutes > JOB_CEILING:
        raise ValueError(
            f"{paper.key}: {minutes} minutes pass the {JOB_CEILING}-minute job"
        )
    return ExamPlan(paper, spent, cap, run, minutes)


def sitting_need(base: Settings = settings) -> float:
    """What ci.yml needs of the suite cap: one paper at its run cap."""
    return exam_run_cap(x2.arm_settings(X2_EX, base))


# ---------------------------------------------------------------------------
# The papers, unpacked and initialised; one sitting
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pins:
    archive: str = ARCHIVE_SHA256
    seal: str = SEAL_TREE_SHA256
    commits: Mapping[str, str] = dataclasses.field(
        default_factory=lambda: dict(TIER_COMMITS)
    )


def check_pins(found: ea.Manifest, pins: Pins) -> None:
    """The manifest against the pins: its archive hash, the seal's tree hash
    it was packed under, and each tier's commit."""
    got = (found.sha256, found.seal, {t: p.commit for t, p in found.papers.items()})
    if got != (pins.archive, pins.seal, dict(pins.commits)):
        raise ea.ExamIntegrityError(
            "the manifest is not the pinned papers (exam_sitting.ARCHIVE_SHA256, "
            "SEAL_TREE_SHA256, TIER_COMMITS)"
        )


def prepare_papers(root: Path, *, archive: Path = ea.ARCHIVE, manifest: Path = ea.MANIFEST,
                   pins: Pins | None = None) -> tuple[dict[str, ExamRepo], GitPolicy]:  # fmt: skip
    """The manifest checked against the pins, the archive checked and
    unpacked under ``root / "papers"``, each tier a repository at its
    commit; the ``ExamRepo`` per name, and the policy that clones exactly
    those."""
    found = ea.load_manifest(manifest)
    check_pins(found, Pins() if pins is None else pins)
    trees = ea.unpack(archive, found, root / "papers")
    policy = exam_policy(root / "papers")
    repos: dict[str, ExamRepo] = {}
    for paper in EXAM_PAPERS:
        body = found.papers[paper.tier]
        ea.init_paper(
            trees[paper.tier], paper.tier, body.commit, body.files, policy=policy
        )
        url = f"file://{trees[paper.tier].resolve()}"
        repos[paper.name] = exam_repo(paper, url, body.commit)
    return repos, policy


def expected_heads(repos: Mapping[str, ExamRepo], root: Path,
                   policy: GitPolicy) -> dict[str, str]:  # fmt: skip
    """Each paper's head once its workload is committed (``prepare_repo``, a
    deterministic commit): what ``sit_one`` requires of the run's clone."""
    heads: dict[str, str] = {}
    for name, repo in repos.items():
        user: UserRepo = oss.prepare_repo(repo, root / f"head-{name}", policy=policy)
        heads[name] = user.base
    return heads


def sitting_plan(repo: ExamRepo) -> x2.X2Plan:
    return x2.X2Plan(f"{X2_EX.key}:{repo.name}", ((X2_EX, repo),))


@dataclass(frozen=True)
class Sitting:
    plan: ExamPlan
    repo: ExamRepo
    policy: GitPolicy
    recorder: x2.X2Recorder


def open_sitting(environ: Mapping[str, str], root: Path, *, base: Settings = settings,
                 archive: Path = ea.ARCHIVE, manifest: Path = ea.MANIFEST,
                 pins: Pins | None = None) -> Sitting:  # fmt: skip
    """The live module's fixture: the plan first (no file is touched when it
    is refused), the papers, the paper's expected head, and the recorder
    that checks the process against ``X2_EX``."""
    plan = exam_plan(environ, base)
    repos, policy = prepare_papers(root, archive=archive, manifest=manifest, pins=pins)
    repo = repos[plan.paper.name]
    heads = expected_heads({repo.name: repo}, root, policy)
    recorder = x2.X2Recorder(sitting_plan(repo), ResultsSink(environ), base=base,
                             commits=heads)  # fmt: skip
    return Sitting(plan, repo, policy, recorder)


def sit_case(paper: ExamPaper, sitting: Sitting, *, live: StartLive, root: Path,
             isolation: Isolation) -> None:  # fmt: skip
    """The live module's case: skipped unless it is the dispatch's paper, then
    ``sit_one`` with ``X2_EX``, the sitting's policy and recorder."""
    if paper != sitting.plan.paper:
        pytest.skip(f"{PAPER_ENV} {sitting.plan.paper.key}: not this dispatch's paper")
    sit_one(X2_EX, sitting.repo, live=live, root=root, isolation=isolation,
            recorder=sitting.recorder, policy=sitting.policy)  # fmt: skip


def sit_one(arm: x2.X2Arm, repo: ExamRepo, *, live: StartLive, root: Path,
            isolation: Isolation, recorder: x2.X2Recorder, policy: GitPolicy,
            cap_of: Callable[[Settings], float] = exam_run_cap) -> None:  # fmt: skip
    """``ideas_x2.run_one`` for a paper: the same calls in the same order
    (``test_exam_sitting_guards`` compares them), but the cap
    ``exam_run_cap`` and the folder named for the paper (no ``EVERY_ARM``
    index: the sitting's arm is off it)."""
    started = time.monotonic()
    x2.check_settings(arm, recorder.base)
    cap = cap_of(x2.arm_settings(arm, recorder.base))
    run = live(cap)
    where = root / f"run-{repo.name}"
    where.mkdir(parents=True)
    with fx.deal_library(repo.name, x2.arm_settings(arm, recorder.base)):
        loop = x2.start_x2_loop(repo, run, where, isolation, policy=policy)
    commit = (recorder.commits or {}).get(repo.name, "")
    if loop.user.base != commit:
        raise ValueError(
            f"{repo.name}: head {loop.user.base} is not the paper's {commit}"
        )
    isl.check_judges(loop)
    loop, tap = x2.tap_fates(loop)
    loop, looks = xl.tap_looks(loop, recorder.proc, recorder.sink.environ)
    seen: list[EngineRunResult | None] = []
    counted = x2.arm_settings(arm, recorder.base).IDEAS_COUNT_CONTRACT == "record"
    record = functools.partial(recorder.record, arm, repo.name, run, commit, seen,
                               clone=loop.user.path if counted else None,
                               started=started,
                               idea_fates=None if tap is None else tap.calls,
                               looks=looks)  # fmt: skip
    dsc.run_engine(
        loop, run, isolation, model=recorder.base.ENGINE_MODEL, record=record
    )
    run.note(ip._fit(f"X2 {arm.key} {repo.name}: {run.spent_usd:.3f} of {cap:.2f} USD"))
    isl.check_op_column(seen[-1])


def admitted(suite: float, spends: Mapping[str, float], cap: float) -> tuple[str, ...]:
    """The papers, dispatched in tier order with the running spend, that the
    fuse admits when each spends as ``spends`` says (the cap arithmetic)."""
    sat: list[str] = []
    spent = 0.0
    for paper in EXAM_PAPERS:
        if fuse_refusal(spent, cap, suite) is not None:
            break
        spent = math.fsum((spent, spends[paper.library]))
        sat.append(paper.name)
    return tuple(sat)
