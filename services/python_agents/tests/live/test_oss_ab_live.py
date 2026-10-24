"""Live E5 on real code: does discovery deliver on the OSS corpus?

Per library of ``$LIVE_OSS_AB_REPOS`` (default the whole ``oss.OSS_CORPUS``,
10 pinned pure-Python libraries, cloned at run time over https from GitHub;
a library left out is skipped before it spends) and repetition
(``$LIVE_OSS_AB_REPS``, default 2; a higher repetition is skipped), one task
(``discovery_oss.run_task``): phase 1 on a fresh clone (zero candidates),
then each arm of ``$LIVE_OSS_AB_ARMS`` (a blind Sonnet 5.5 medium, b
playbook-matched Sonnet 5.5 medium, c blind Opus 5.5 low; default a,b)
generates ``$LIVE_OSS_AB_N`` hypotheses (default 10) from its facts in one
run capped at the sum of their worst cases, and each arm's efficiency
hypotheses all run in one round of one whole loop on a fresh clone (Sonnet
5.5, no fallbacks, capped at ``$LIVE_OSS_AB_TRIAL_CAP_USD`` a trial,
default 2.5 USD) with every corpus guard.

The plan is read in the module fixture, before any test spends: one whose
need passes the 150 USD ceiling is refused (the default plan needs about
1026 USD, one library about 103), so a dispatch names one library, or
lowers the trial cap. Wins, gains, each idea's verdict in rank order, win@k
and costs are recorded (JSON lines to ``$LIVE_RESULTS_PATH``, a cost-table
note per row and the running summary after every task, the summary in the
job summary and the log), never asserted. The job needs network access to
github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .discovery_ab import load_distractors
from .discovery_io import ResultsSink
from .discovery_oss import (
    OSS_AB_MAX_REPS,
    REPOS_ENV,
    REPS_ENV,
    OssAbRecorder,
    oss_ab_plan,
    run_task,
)
from .oss import OSS_CORPUS, OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def oss_ab() -> Iterator[OssAbRecorder]:
    """The knobs and the distractors, read before any test spends."""
    recorder = OssAbRecorder(
        oss_ab_plan(os.environ), ResultsSink(os.environ), load_distractors()
    )
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("rep", range(1, OSS_AB_MAX_REPS + 1))
@pytest.mark.parametrize("repo", OSS_CORPUS, ids=[r.name for r in OSS_CORPUS])
def test_oss_discovery_ab(
    repo: OssRepo,
    rep: int,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    oss_ab: OssAbRecorder,
) -> None:
    if repo not in oss_ab.plan.repos:
        pytest.skip(f"{REPOS_ENV} leaves {repo.name} out")
    if rep > oss_ab.plan.reps:
        pytest.skip(f"{REPS_ENV} is {oss_ab.plan.reps}")
    run_task(
        repo,
        rep,
        live=live,
        root=live_root,
        isolation=live_isolation,
        recorder=oss_ab,
    )
