"""Live V7: the ideas-probe suite (E0b, E1, E1b), idea-only, no trial.

Per library of the plan (``$LIVE_IDEAS_REPOS``, else the run's own: E0b's
ten, E1b's four; E1 names two of its eight a dispatch, as more would pass
the job's minutes; a library left out is skipped before it spends), one run
capped at its worst case (``ideas_probe.run_library``):
phase 1 on a fresh clone (or ``$LIVE_IDEAS_FACTS``'s recorded facts on a
fresh clone at the same head), each arm of ``$LIVE_IDEAS_ARMS`` (``count``
alone, or distinct of A-E, ``C-low``, ``C-high``; default A-E) generating
once from those facts, and with an E1 arm one auditor pass.

The plan is read in the module fixture, before any test spends: one past
the 150 USD ceiling or the job's minutes, or recorded facts that miss a
planned library, is refused. Rows, replies, facts and verdicts go to ``$LIVE_RESULTS_PATH``, a
note per library to the cost table and a summary to the job summary;
nothing about the ideas is asserted. The job needs network access to
github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .ideas_probe import REPOS_ENV, ProbeRecorder, probe_plan, run_library
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def probe() -> Iterator[ProbeRecorder]:
    """The knobs and any recorded facts, read before any test spends."""
    recorder = ProbeRecorder(probe_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("repo", OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE])
def test_ideas_probe(
    repo: OssRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    probe: ProbeRecorder,
) -> None:
    if repo not in probe.plan.repos:
        pytest.skip(f"{REPOS_ENV} or the run's arms leave {repo.name} out")
    run_library(
        repo, live=live, root=live_root, isolation=live_isolation, recorder=probe
    )
