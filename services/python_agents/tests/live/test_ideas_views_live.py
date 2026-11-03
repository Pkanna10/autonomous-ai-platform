"""Live Va: the ideas-views suite, the views pass (idea-lab spec 6.1, O36.3).

No Claude request: the cap is 0 USD (``ideas_views.VIEWS_RUN_CAP_USD``),
and the suite is ``live`` only because it clones the pinned OSS libraries
over the network. Per library of E1's committed facts
(``tests/fixtures/ideas_probe/facts.jsonl``, the 8 development libraries),
``ideas_views.run_views``: a fresh clone at E1's recorded head, the pinned
tag's history up to the pin, every view G2 defines built by the engine's
own builders with the pipeline's limits, one ``ideas-views`` row per
(library, view) to ``$LIVE_RESULTS_PATH`` and a table to the job summary.
The plan is read in the module fixture, before any clone: facts naming a
library outside the pinned corpus, or a plan past the job's minutes, is
refused. Nothing about the views is asserted; a request, a transport or a
breach fails the case after its note.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import StartLive
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .ideas_views import VIEWS_RUN_CAP_USD, ViewsRecorder, run_views, views_plan
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def views() -> Iterator[ViewsRecorder]:
    """E1's facts and the plan, read before any test clones."""
    recorder = ViewsRecorder(views_plan(), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("repo", OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE])
def test_ideas_views(
    repo: OssRepo, live: StartLive, live_root: Path, views: ViewsRecorder
) -> None:
    if repo not in views.plan.repos:
        pytest.skip(f"E1 recorded no facts for {repo.name}")
    run = live(VIEWS_RUN_CAP_USD)
    run_views(repo, run=run, root=live_root, recorder=views)
