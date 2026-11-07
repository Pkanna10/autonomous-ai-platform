"""Live V-reaudit: the ideas-reaudit suite, the pooled re-audit of the X1-1
re-run (O44), one auditor request a library, no idea generation.

Per library of X1 run 1 (more_itertools, pyparsing, tomli, sortedcontainers;
``ideas_reaudit.run_library``): the recorded facts on a fresh clone, run 1's
A, X1-0, X1-2 and X1-3 and the re-run's X1-1 rebuilt by replaying their
recorded replies (nothing sent), each replay checked against its own file's
audit, then ``ideas_probe.pool`` and ``ideas_probe.run_audit``'s one request,
capped at its worst case.

Both results files (``$LIVE_REAUDIT_RUN1``, ``$LIVE_REAUDIT_RERUN``) are read
and checked in the module fixture, before any test spends: a file missing,
other libraries, a re-run without X1-1 (or with more than A and X1-1), or a
need past ``LIVE_SUITE_CAP_USD``, is refused; a replay that does not
reproduce its file refuses its library before its run is admitted. The
audit's rows (``ideas-reaudit``, both files' sha256 on each) and the
auditor's reply go to ``$LIVE_RESULTS_PATH``; nothing about the ideas is
asserted. The job needs network access to github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from .conftest import StartLive
from .ideas_reaudit import REAUDIT_LIBRARIES, Reaudit, reaudit_plan, run_library
from .oss import OssRepo

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def reaudit() -> Iterator[Reaudit]:
    """Both results files, the facts and X1-3's views, read before any spend."""
    yield Reaudit(reaudit_plan(os.environ), os.environ)


@pytest.mark.parametrize(
    "repo", REAUDIT_LIBRARIES, ids=[r.name for r in REAUDIT_LIBRARIES]
)
def test_ideas_reaudit(
    repo: OssRepo, live: StartLive, live_root: Path, reaudit: Reaudit
) -> None:
    run_library(repo, live=live, root=live_root, reaudit=reaudit)
