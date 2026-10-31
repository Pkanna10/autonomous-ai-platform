"""Live E5: does retrieval raise executed wins? (the central Step 3 bet)

Per repository (``AB_REPOS``: benchmark slowdowns and controls, the hard
corpus) and repetition (``$LIVE_AB_REPS``, default and at most 2; a higher
repetition is skipped before it spends): one generation run capped at
``AB_GEN_CAP_USD`` (the sum of its four requests' worst cases) holds phase 1 and both arms' requests (Sonnet 5.5,
medium effort, no fallbacks): A generates 3 hypotheses blind, B matches 3
playbook cards and generates 3 hypotheses from them. Then one whole engine
loop per arm (Sonnet 5.5, no fallbacks, ``$LIVE_AB_RUN_CAP_USD``, default
1 USD) with that arm's hypotheses as the candidates, ``hotspot_ids``
cleared, and every corpus guard.

Wins are recorded (JSON lines to ``$LIVE_RESULTS_PATH``; the summary with
the per-arm rates, the paired outcomes, McNemar's exact p and the
decision rule in the job summary), never asserted.

E3 (V8, ``$LIVE_AB_SET=v2-p``, the ``ab-v2-p`` suite): the repositories are
corpus v2's deep, misleading and uncommon slowdowns (read at collection),
the shared run is capped at ``AB_P_GEN_CAP_USD``, and arm P (the idea
pipeline on phase 1's facts and the code at its base commit) replaces B.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.research.playbook import load_playbook

from .conftest import StartLive
from .corpus import CorpusRepo, start_loop
from .discovery import (
    carry,
    check_untouched,
    phase_one,
    run_engine,
)
from .discovery_ab import (
    AB_MAX_REPS,
    REPS_ENV,
    AbRecorder,
    ab_plan,
    ab_settings,
    blind_arm,
    check_arm_calls,
    load_distractors,
    pipeline_arm,
    retrieval_arm,
    withheld,
)
from .discovery_io import (
    ResultsSink,
)

pytestmark = pytest.mark.live

AB_PLAN_REPOS = ab_plan(os.environ).repos  # a bad $LIVE_AB_SET fails collection


@pytest.fixture(scope="module")
def ab() -> Iterator[AbRecorder]:
    """The knobs and the distractors, read before any test spends."""
    recorder = AbRecorder(
        ab_plan(os.environ), ResultsSink(os.environ), load_distractors()
    )
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("rep", range(1, AB_MAX_REPS + 1))
@pytest.mark.parametrize("repo", AB_PLAN_REPOS, ids=[r.name for r in AB_PLAN_REPOS])
def test_retrieval_ab(
    repo: CorpusRepo,
    rep: int,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    ab: AbRecorder,
) -> None:
    if rep > ab.plan.reps:
        pytest.skip(f"{REPS_ENV} is {ab.plan.reps}")
    playbook = load_playbook()
    cfg = ab_settings(settings)
    gen = live(ab.plan.gen_cap)
    phase = phase_one(repo, gen, live_root / "phase", live_isolation, cfg)
    budget = Budget(gen.cap_usd, gen.spent_usd)
    arms = {"A": blind_arm(gen, budget, phase.facts)}
    if ab.plan.pipeline:
        protected, read_deny = withheld(phase.loop.context, phase.extra_protected)
        arms["P"] = pipeline_arm(
            gen,
            budget,
            phase.facts,
            commit=phase.loop.user.base,
            protected=protected,
            read_deny=read_deny,
        )
    else:
        arms["B"] = retrieval_arm(gen, budget, phase.facts, playbook=playbook)
    check_arm_calls(gen, budget, arms)
    check_untouched(phase)
    for label, produced in arms.items():
        candidates = carry(produced.hypotheses)
        if not candidates:
            ab.record(repo, rep, label, produced, None, run=gen)
            continue
        run = live(ab.plan.run_cap)
        loop = start_loop(
            repo,
            run,
            live_root / label,
            live_isolation,
            mode="blind",
            cfg=cfg,
            candidates=candidates,
        )
        record = functools.partial(ab.record, repo, rep, label, produced, run=run)
        run_engine(loop, run, live_isolation, model=cfg.ENGINE_MODEL, record=record)
