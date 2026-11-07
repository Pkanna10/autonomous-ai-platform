"""Live Vb: the ideas-marker suite, the marker validation (O36.1, O37).

Per pinned OSS library with a rank set holding a kept idea and a trialled
rival (17 of the 18 oss-ab libraries; a library left out is skipped before
it spends), one run capped at its sets x both markers' worst cases
(``ideas_marker.run_library``): the pinned clone, the hot code its recorded
profile names, then Opus 5.5 and Opus 5 at ``high`` each ordering every
set's ideas blind. At the module's end the score (within-library AUC, a
cluster bootstrap over libraries) and O37's rule against the generator's
own order.

The plan is read in the module fixture, before any test spends: one past
the 150 USD ceiling, the job's minutes or ``LIVE_SUITE_CAP_USD`` is refused.
Replies, set AUCs, scores and the verdict go to ``$LIVE_RESULTS_PATH``, a
summary to the job summary; nothing about the markers is asserted. The job
needs network access to github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import StartLive
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .ideas_marker import MarkerRecorder, marker_plan, run_library
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def marker() -> Iterator[MarkerRecorder]:
    """The rows, the plan and its caps, read before any test spends."""
    recorder = MarkerRecorder(marker_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("repo", OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE])
def test_ideas_marker(
    repo: OssRepo, live: StartLive, live_root: Path, marker: MarkerRecorder
) -> None:
    if repo not in marker.plan.repos:
        pytest.skip(f"no rank set of {repo.name} holds a kept idea and a rival")
    run_library(repo, live=live, root=live_root, recorder=marker)
