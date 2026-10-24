"""Live E3: blind hypothesis generation across models and effort.

Per repository (``SWEEP_REPOS``: the benchmark slowdowns and controls, the
hard corpus) one run capped at ``SweepPlan.cap_for(repo)``, the sum of the
worst cases of every request it may send: phase 1 once
(``discovery.phase_one``: the real understand, baseline and profile, no
trial), then every arm of ``$LIVE_SWEEP_ARMS`` generates 5 hypotheses on
the same facts through its own one-model transport, then one
``claude-opus-4-8`` grader request per arm (a model no arm uses) scores them
against the reference fix (``discovery_grader``; controls are not graded).
With ``$LIVE_SWEEP_FABLE=1`` Fable 5.1 at medium also runs on the 12
benchmark slowdowns, in its own run (``FABLE_RUN_CAP_USD``). One more test
is the cache probe (``CACHE_PROBE_CAP_USD``).

Hits are recorded (JSON lines to ``$LIVE_RESULTS_PATH``, the summary per
arm in the job summary), never asserted. Asserted: phase 1's corpus guards,
every arm and grader answered and billed its own model, the spend held the
caps and matched the wire, and the user's repository is untouched.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import settings

from .conftest import StartLive
from .corpus import CORPUS, CorpusRepo
from .discovery import (
    PHASE_ONE_MODEL,
    check_calls,
    check_untouched,
    generate_arm,
    model_settings,
    phase_one,
)
from .discovery_grader import GRADER_MODEL, reference_patches
from .discovery_io import (
    ResultsSink,
)
from .discovery_sweep import (
    CACHE_PROBE_CAP_USD,
    FABLE_ARM,
    FABLE_REPOS,
    FABLE_RUN_CAP_USD,
    SWEEP_N,
    SWEEP_REPOS,
    SweepRecorder,
    cache_probe,
    grade_arm,
    sweep_plan,
    sweep_row,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def sweep() -> Iterator[SweepRecorder]:
    """The knobs, parsed before any test spends; the summary at the end."""
    recorder = SweepRecorder(sweep_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("repo", SWEEP_REPOS, ids=[r.name for r in SWEEP_REPOS])
def test_blind_hypothesis_sweep(
    repo: CorpusRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    sweep: SweepRecorder,
) -> None:
    patches = reference_patches(repo)  # read before any spend
    run = live(sweep.plan.cap_for(repo))
    cfg = model_settings(settings, PHASE_ONE_MODEL)
    phase = phase_one(repo, run, live_root / "phase", live_isolation, cfg)
    budget = Budget(run.cap_usd, run.spent_usd)
    arms = [
        generate_arm(arm, run, budget, phase.facts, n=SWEEP_N)
        for arm in sweep.plan.arms
    ]
    grades = [grade_arm(run, budget, repo, patches, arm) for arm in arms]
    sweep.record(
        [
            sweep_row(repo, a, g, phase.cost_usd)
            for a, g in zip(arms, grades, strict=True)
        ],
        run,
    )
    graded = [g for g in grades if g is not None and g.sent]
    assert all(g.answered and g.models == (GRADER_MODEL,) for g in graded), grades
    check_calls(run, budget, arms, answered=len(graded))
    check_untouched(phase)
    if not sweep.plan.fable or repo not in FABLE_REPOS:
        return
    fable = live(FABLE_RUN_CAP_USD)
    spend = Budget(fable.cap_usd)
    result = generate_arm(FABLE_ARM, fable, spend, phase.facts, n=SWEEP_N)
    mark = grade_arm(fable, spend, repo, patches, result)
    sweep.record([sweep_row(repo, result, mark, 0.0)], fable)
    check_calls(fable, spend, [result], answered=int(mark is not None and mark.sent))
    check_untouched(phase)


def test_generator_cache_probe(live: StartLive, sweep: SweepRecorder) -> None:
    """The same playbook twice: the second call reads the cached system block."""
    run = live(CACHE_PROBE_CAP_USD)
    probe = cache_probe(run, CORPUS[0])
    sweep.record_probe(probe, run)
    assert probe.answered, probe.error
    assert run.spent_usd <= run.cap_usd
