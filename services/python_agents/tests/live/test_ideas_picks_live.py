"""Live V-picks: the ideas-picks suite, the blind reader's would-try ideas
as ordinary engine trials (O48; spec-idea-lab 9.6 item 2, 9.7).

Per library of ``ideas_picks.PICKS_REPOS`` (sqlparse S20, S04, S12;
more_itertools S13, S23; mistune S07; tomli S09; a library none of
``$LIVE_PICKS_IDS`` names is skipped before it spends): one engine loop on
a fresh clone with its picks, every one trialled in the loop's round, the
combine after (``ideas_picks.run_library``).

The ideas are resolved through the committed sample key against the slice's
committed inputs, the plan (each loop's cap from the engine's own
reservations at measured rates, under the owner's 8 USD) and
``OP_COUNT_JUDGE`` are checked in the module fixture, before any test
spends: an id that does not resolve, resolves twice or shows another title,
a need past 8 USD, the job's minutes or ``LIVE_SUITE_CAP_USD``, or the
operation-count judge off, is refused. Per-idea trial rows and per-library
combine rows go to ``$LIVE_RESULTS_PATH``, a note per loop to the cost
table; nothing about the ideas is asserted. The job needs network access to
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
from .ideas_picks import (
    IDS_ENV,
    PICKS_LIBRARIES,
    PicksRecorder,
    picks_plan,
    run_library,
)
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[PicksRecorder]:
    """The resolved ideas and the plan, read before any test spends."""
    yield PicksRecorder(picks_plan(os.environ), ResultsSink(os.environ))


@pytest.mark.parametrize("repo", PICKS_LIBRARIES, ids=[r.name for r in PICKS_LIBRARIES])
def test_ideas_picks(
    repo: OssRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: PicksRecorder,
) -> None:
    if not recorder.plan.of(repo.name):
        pytest.skip(f"{IDS_ENV} names no idea on {repo.name}")
    run_library(
        repo, live=live, root=live_root, isolation=live_isolation, recorder=recorder
    )
