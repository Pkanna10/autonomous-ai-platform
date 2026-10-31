"""Live evolution (Window 0): does iterating compound gains on real code?

Per OSS library (``$LIVE_EVOLVE_REPOS``, default ``evolution.EVOLVE_REPOS``:
tabulate, tomli and markdown, the largest gains of the aimed OSS run; each
cloned at its pin by ``oss.prepare_repo``; the job needs github.com), up to
``$LIVE_EVOLVE_ROUNDS`` rounds (default and at most 10). Each round is one
generation run capped at ``EVOLVE_GEN_CAP_USD`` (phase 1 on the clone as it
stands, then one Sonnet 5.5 medium generation of 5 hypotheses, told what
earlier rounds delivered and tried) and one whole engine loop on the
round's efficiency hypotheses (Sonnet 5.5, no fallbacks), capped at
``$LIVE_EVOLVE_RUN_CAP_USD`` (default 3 USD), with every corpus guard. A
delivered round moves the clone's ``main`` to the engine's delivered commit,
so the next round measures the improved code; two empty rounds in a row
end the library's evolution. Then, if anything was delivered, the original
pin is measured against the final tip ABAB with the engine's own
measurement and noise rule (no Claude request; bounded by
``EVOLVE_RETEST_WALL_S``).

Gains are recorded (JSON lines to ``$LIVE_RESULTS_PATH``, a note per round,
one per library and the running summary in the cost table, the summary and
every row in the log), never asserted. The repositories and the arms are
read at collection (a bad ``$LIVE_EVOLVE_REPOS`` or ``$LIVE_EVOLVE_ARMS``
fails collection, before any spend); the whole plan is read, and checked
against ``$LIVE_SUITE_CAP_USD``, in the module fixture, before any test
spends. Arm P (V8, E4) evolves its own clone with the idea pipeline in
place of the blind generation, its rows named ``<repo>/P``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.common.config import settings

from .conftest import StartLive
from .discovery_io import ResultsSink
from .evolution import (
    EvolveRecorder,
    LiveSteps,
    check_suite_cap,
    evolve_arms,
    evolve_gen_cap,
    evolve_name,
    evolve_plan,
    evolve_repos,
    evolve_settings,
    run_evolution,
)
from .oss import OssRepo, prepare_repo

pytestmark = pytest.mark.live

EVOLVE_REPOS = evolve_repos(os.environ)
EVOLVE_ARMS = evolve_arms(os.environ)


@pytest.fixture(scope="module")
def evolve() -> Iterator[EvolveRecorder]:
    """The plan and the results path, checked before any test spends; the
    summary and every row at the end."""
    plan = evolve_plan(os.environ)
    check_suite_cap(plan, os.environ)
    if plan.repos != EVOLVE_REPOS:
        raise ValueError("the plan's repositories are not the collected ones")
    if plan.arms != EVOLVE_ARMS:
        raise ValueError("the plan's arms are not the collected ones")
    recorder = EvolveRecorder(plan, ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("arm", EVOLVE_ARMS)
@pytest.mark.parametrize("repo", EVOLVE_REPOS, ids=[r.name for r in EVOLVE_REPOS])
def test_evolution_on_real_code(
    repo: OssRepo,
    arm: str,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    evolve: EvolveRecorder,
) -> None:
    user = prepare_repo(repo, live_root / "user")  # refused clones spend nothing
    cfg = evolve_settings(settings)
    run_evolution(
        evolve_name(repo.name, arm),
        user,
        evolve.plan,
        LiveSteps(repo, live_isolation, cfg, pipeline=arm == "P"),
        start_gen=lambda: live(evolve_gen_cap(arm)),
        start_engine=lambda: live(evolve.plan.run_cap),
        recorder=evolve,
    )
