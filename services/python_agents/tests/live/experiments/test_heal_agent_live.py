"""P1: the heal agent against today's single heal request (live, CI only).

Pilot P1 of the agent roadmap (O18; spec-wave2 7c, unit A1; ``heal_agent``
holds the design, ``heal_agent.DECISION`` what it measures and feeds). Per
bug of ``heal_agent.PLAN`` (the 12 new hard bugs, then the 16 saturated easy
and hard heal bugs as regression), on Sonnet 5.5 at effort medium, no
fallbacks, in ONE live run capped at ``heal_agent.bug_cap`` (0.40 USD for a
new bug, 0.20 for a regression bug; every request reserved at its worst case
before it is sent, through the harness's ledger):

1. Arm A is today's heal probe, unchanged: ``test_heal_live.run_repo``
   (request 1 writes the reproducer, the probe freezes it and runs it on the
   seed and the reference fix; request 2 fixes; one bounded retry after a
   fixable crash; the measurement). It records its own ``HEAL`` row and
   notes. Its own cap is ignored: it spends inside the bug's run.
2. Arm B, only when that frozen reproducer fails ``RUNS`` of ``RUNS`` times
   on the seed (as arm A's fix request): ``heal_agent.Fixer`` on a scratch
   copy, at most 12 turns with the text editor and ``run_reproducer``. The
   capture rules read the copy; the accepted change is measured on a fresh
   copy exactly as arm A's (the reproducer 5 times, the own suite, the
   hidden check, and on the hard sets the shallow patch's hidden run).

Every run of model-written code goes through ``procrun.run_once`` with
network and fs isolation ``required``; ``live_isolation`` fails the test
before anything is sent on a host that cannot sandbox. A ``P1`` ``arm-b``
row per bug and a ``P1`` summary row (the gate's figures and verdict) go to
``$LIVE_RESULTS_PATH`` and the log; per bug the note ``P1 <bug> (<group>):
A healed <y/n>, B healed <y/n> (stop, turns, runs, writes, test-edits), <A>
<B> USD`` and the running summary in two notes (counts, then ``P1 gate
<pass/fail/incomplete>`` with its three limbs). Outcomes are recorded, never
asserted; a test fails only when the API answered no reproducer request.

Cost: the suite needs ``heal_agent.agent_need()`` (8.00: the pilot cap,
``PILOT_CAP_USD``); expected 3-6 USD (arm A about 0.02 a bug, arm B a few
cents a turn with the history cached).
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.procrun import run_once

from ..conftest import LiveRun, StartLive
from .harness import ExperimentClient
from .heal import (
    HealOutcome,
    HealRepo,
    Sandbox,
    overlay,
    read_report,
    seed_tree,
    shallow_tree,
)
from .heal_agent import (
    PLAN,
    BugOutcome,
    Fixer,
    bug_cap,
    pilot_notes,
    summarise_pilot,
)
from .recorder import ExperimentRecorder
from .test_heal_live import run_repo
from .test_probes_live import finish

pytestmark = pytest.mark.live
BY_NAME = {repo.name: repo for repo in PLAN}


def _within(run: LiveRun) -> StartLive:
    """Arm A's ``start``: the bug's own run, whatever cap arm A asks for."""

    def start(cap_usd: float) -> LiveRun:
        return run

    return start


def run_arm_b(
    client: ExperimentClient,
    repo: HealRepo,
    arm_a: HealOutcome,
    base: Path,
    *,
    run: RunOnce = run_once,
) -> tuple[HealOutcome, Fixer]:
    """The fixer on arm A's frozen reproducer, then its change measured on
    a fresh copy as arm A's is."""
    assert arm_a.reproducer is not None
    tree, report, repro = seed_tree(repo), read_report(repo), arm_a.reproducer
    fixer = Fixer(client, repo, tree, report, repro, base / "fixer", run=run)
    stats = fixer.run()
    fix, stats.test_edits = fixer.capture()
    outcome = HealOutcome(
        repo,
        repro_outcome=arm_a.repro_outcome,
        answered=arm_a.answered,
        reproducer=repro,
        seed_runs=arm_a.seed_runs,
        reference_runs=arm_a.reference_runs,
    )
    sandbox = Sandbox(base / "measure", run=run)
    outcome.take(sandbox.attempt(tree, repo, repro, fix))
    if repo.hard and outcome.fix_applied:  # engine-owned code only
        outcome.shallow_run = sandbox.hidden(overlay(tree, shallow_tree(repo)), repo)
    outcome.fix_cost_usd = outcome.cost_usd = stats.cost_usd
    return outcome, fixer


def run_bug(
    start: StartLive,
    repo: HealRepo,
    base: Path,
    *,
    recorder: ExperimentRecorder,
    run: RunOnce = run_once,
    earlier: Sequence[BugOutcome] = (),
) -> BugOutcome:
    """Both arms on one bug in one run of ``bug_cap(repo)``; the row, the
    bug's note and the running summary over ``earlier`` plus this one."""
    live = start(bug_cap(repo))
    arm_a = run_repo(
        _within(live),
        repo,
        base / "arm-a",
        recorder=recorder,
        run=run,
        earlier=[o.a for o in earlier],
    )
    outcome = BugOutcome(repo, arm_a, None, None)
    if arm_a.reproducer is not None and arm_a.valid:
        with ExperimentClient(live, recorder=recorder) as client:
            arm_b, fixer = run_arm_b(client, repo, arm_a, base / "arm-b", run=run)
        outcome = BugOutcome(repo, arm_a, arm_b, fixer.stats)
    recorder.record("P1", "arm-b", repo.name, outcome.metrics())
    for note in [outcome.note(), *pilot_notes(summarise_pilot([*earlier, outcome]))]:
        live.note(note)
    return outcome


@dataclass
class PilotLog:
    recorder: ExperimentRecorder
    outcomes: list[BugOutcome] = field(default_factory=list)


def close_log(log: PilotLog, config: pytest.Config) -> None:
    """The summary row across bugs (the gate's verdict), then the table and
    every row to the job summary and the log."""
    if log.outcomes:
        log.recorder.record("P1", "summary", "all", summarise_pilot(log.outcomes))
    finish(log.recorder, config)


@pytest.fixture(scope="module")
def pilot_log(pytestconfig: pytest.Config) -> Iterator[PilotLog]:
    log = PilotLog(ExperimentRecorder("P1 heal agent vs single shot", os.environ))
    yield log
    close_log(log, pytestconfig)


@pytest.mark.parametrize("name", [repo.name for repo in PLAN])
def test_heal_agent_bug(
    live: StartLive,
    live_isolation: Isolation,
    pilot_log: PilotLog,
    tmp_path: Path,
    name: str,
) -> None:
    assert live_isolation.mode == "required"
    repo = BY_NAME[name]
    base = Path(os.path.realpath(tmp_path)) / "p1"
    outcome = run_bug(
        live, repo, base, recorder=pilot_log.recorder, earlier=pilot_log.outcomes
    )
    pilot_log.outcomes.append(outcome)
    assert outcome.a.answered, (
        f"{name}: the API answered no reproducer request ({outcome.a.repro_outcome})"
    )
