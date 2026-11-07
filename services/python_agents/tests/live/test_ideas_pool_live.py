"""Live V-O40: the ideas-pool suite, the pooled marker-feasible ranking (O40,
O41) on the four development libraries outside the execution slice
(more_itertools, mistune, markdown, idna; the slice ranks its own four).

Per library: the pinned clone's hot code, then each ranker's tournament
(``ideas_pool.run_library``): the marker Vb's verdict chose ranks every lens
-lane idea of X1-0 to X1-3 less its own model's, the other candidate the
whole pool, marked unvalidated; sets of at most six, the top two of each set
advancing, every request counted and capped. No engine trial.

The plan, X1's rows (``$LIVE_POOL_IDEAS``) and Vb's verdict
(``$LIVE_POOL_MARKER``) are read and checked in the module fixture, before
any test spends: a need past ``LIVE_SUITE_CAP_USD``, rows that do not join, a
verdict row that disagrees with Vb's score, or a pool past the bound its
need was priced on, is refused. Every set request and each ranking's result
go to ``$LIVE_RESULTS_PATH``; nothing about the ideas is asserted. The job
needs network access to github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import StartLive
from .discovery_io import ResultsSink
from .ideas_pool import POOL_LIBRARIES, PoolRecorder, pool_plan, run_library
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[PoolRecorder]:
    """The plan, X1's rows and Vb's verdict, read before any test spends."""
    yield PoolRecorder(pool_plan(os.environ), ResultsSink(os.environ))


@pytest.mark.parametrize("repo", POOL_LIBRARIES, ids=[r.name for r in POOL_LIBRARIES])
def test_ideas_pool(
    repo: OssRepo, live: StartLive, live_root: Path, recorder: PoolRecorder
) -> None:
    run_library(repo, live=live, root=live_root, recorder=recorder)
