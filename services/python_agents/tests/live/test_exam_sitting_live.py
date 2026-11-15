"""Live UEX (O71 item 4): the engine sits one retired practical paper a dispatch.

One unmodified X2-0 run with the gain-ordered combine
(``exam_sitting.X2_EX``), on key 2, for the paper ``$LIVE_EXAM_PAPER`` names
(t1 to t4), admitted only when ``$LIVE_EXAM_SPENT_USD`` (what the earlier
papers spent) plus one run's cap fits the suite cap. The module fixture is
``exam_sitting.open_sitting``: the plan is refused before any file is
touched, then the papers are checked against their pins and unpacked, then
the process is checked against the arm. Each case is ``sit_case``: skipped
unless it is the dispatch's paper. This module only delegates
(``test_exam_sitting_guards`` pins its syntax tree). Rows go to
``$LIVE_RESULTS_PATH`` as every X2 run's do; the Lead archives them under
``exam_sitting.SITTING_ROWS``. No network: the paper is served over
``file://`` from the unpacked archive.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from . import exam_sitting as ex
from .conftest import StartLive

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def sitting(tmp_path_factory: pytest.TempPathFactory) -> ex.Sitting:
    """The plan, the paper and the arm's settings, checked before any test spends."""
    return ex.open_sitting(os.environ, tmp_path_factory.mktemp("sources"))


@pytest.mark.parametrize("paper", ex.EXAM_PAPERS, ids=[p.name for p in ex.EXAM_PAPERS])
def test_run(
    paper: ex.ExamPaper,
    sitting: ex.Sitting,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
) -> None:
    ex.sit_case(paper, sitting, live=live, root=live_root, isolation=live_isolation)
