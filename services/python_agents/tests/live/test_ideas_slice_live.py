"""Live Ve: the ideas-slice suite, X1's execution slice (spec-idea-lab 6.3,
O36.2; 6.5's shadow judge).

Per library of ``$LIVE_SLICE_REPOS`` (at most two a dispatch of sqlparse,
pyparsing, tomli and the control sortedcontainers; a library left out is
skipped before it spends): the markers' run (the pinned clone's hot code,
each configuration's ideas ranked by the validated marker that did not
write them, every request counted and capped), then per configuration X1-0
to X1-3 one engine loop on a fresh clone with its top ideas, one trial each,
the combine after (``ideas_slice.run_library``).

The plan, X1's rows (``$LIVE_SLICE_IDEAS``), Vb's verdict
(``$LIVE_SLICE_MARKER``) and ``OP_COUNT_JUDGE`` are read and checked in the
module fixture, before any test spends: a plan past the 80 USD fuse, the
job's minutes or ``LIVE_SUITE_CAP_USD``, rows that do not join, or the
operation-count judge off, is refused. Per-trial records and combine
summaries go to ``$LIVE_RESULTS_PATH``, a note per loop to the cost table;
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
from .ideas_slice import (
    REPOS_ENV,
    SLICE_LIBRARIES,
    SliceRecorder,
    run_library,
    slice_plan,
)
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[SliceRecorder]:
    """The plan, X1's rows and Vb's verdict, read before any test spends."""
    yield SliceRecorder(slice_plan(os.environ), ResultsSink(os.environ))


@pytest.mark.parametrize("repo", SLICE_LIBRARIES, ids=[r.name for r in SLICE_LIBRARIES])
def test_ideas_slice(
    repo: OssRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: SliceRecorder,
) -> None:
    if repo not in recorder.plan.repos:
        pytest.skip(f"{REPOS_ENV} leaves {repo.name} out")
    run_library(
        repo, live=live, root=live_root, isolation=live_isolation, recorder=recorder
    )
