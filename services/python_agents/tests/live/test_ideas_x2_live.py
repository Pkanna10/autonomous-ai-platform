"""Live X2a: the ideas-x2 suite, evolution on the levers X1 kept
(spec-idea-lab section 9, O48).

One dispatch per ``$LIVE_X2_DISPATCH``, an arm and its libraries
(``ARM:lib,lib``; ``ideas_x2.dispatches`` is the plan: X2-0 on the eight
libraries in two dispatches of four, its A/A twin X2-0' on sqlparse,
pyparsing, tomli and sortedcontainers in one, X2-V on the eight in two;
the cases are ``ideas_x2.EVERY_RUN``, the plan's then X2-S's and X2-C's).
Each (arm, library) is one whole engine run with the idea pipeline on,
wired (``oss.start_oss_loop``'s body with the Haiku lane's transport) at the
commit E1 recorded, two rounds with round 1 trialling the whole result so
round 2 is the seeded call, near-miss compounds and the op-count judge
(``ideas_x2.run_one``); a run outside the dispatch is skipped before it
spends.

The plan (fuse, job minutes, ``LIVE_SUITE_CAP_USD``) and the process
settings (the arm's env mapping, ci.yml's export, ``OP_COUNT_JUDGE`` on and
the Opus 5.5 engine) are read and checked in the module fixture, before any
test spends. Per-hypothesis, per-round and per-run rows go to
``$LIVE_RESULTS_PATH``, a note per run to the cost table; nothing about the
ideas is asserted. The job needs network access to github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .discovery_io import ResultsSink
from .ideas_x2 import DISPATCH_ENV, EVERY_RUN, X2Arm, X2Recorder, run_one, x2_plan
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[X2Recorder]:
    """The plan and the arm's settings, checked before any test spends."""
    yield X2Recorder(x2_plan(os.environ), ResultsSink(os.environ))


@pytest.mark.parametrize(
    ("arm", "repo"), EVERY_RUN, ids=[f"{a.key}-{r.name}" for a, r in EVERY_RUN]
)
def test_ideas_x2(
    arm: X2Arm,
    repo: OssRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: X2Recorder,
) -> None:
    if (arm, repo) not in recorder.plan.runs:
        pytest.skip(f"{DISPATCH_ENV} {recorder.plan.dispatch} leaves it out")
    run_one(
        arm,
        repo,
        live=live,
        root=live_root,
        isolation=live_isolation,
        recorder=recorder,
    )
