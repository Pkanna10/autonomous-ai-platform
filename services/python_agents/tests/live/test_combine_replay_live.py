"""Live O62 item 5: the combine re-measure replay, on the archived tips.

No Claude request: the cap is 0 USD (``combine_replay.REPLAY_RUN_CAP_USD``),
and the suite is ``live`` only because it clones the pinned libraries over
the network and runs third-party code in the ``required`` sandbox, as the
noise and upstream-verify suites do. The settings are checked against the X2
arms' measurement settings before any clone (``check_settings``). Per case of
``combine_replay.CASES`` (the four archived rows at twice the baseline floor
or more, and markdown's calibration and profile), ``replay_live``: the
archive's integrity, the repository as the X2 run built it, the tip
committed beside it, the engine's preflight, define, baseline with its
calibration and profile, then the combine node's re-test three times.
Recorded, never asserted: gains, floors, verdicts, the rule, the seconds
(one JSON line per re-test and per case to ``$LIVE_RESULTS_PATH``, the
tables to the job summary). An integrity mismatch (a look that did not
measure the tip among them), a crash or a guard breach fails the case after
its rows are written; an ``EngineError`` stop is recorded, and a tip case
with fewer than three measured looks fails the job at the module's end,
after the tables.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .combine_replay import CASES, REPLAY_RUN_CAP_USD, ReplayRecorder, replay_live
from .conftest import StartLive
from .discovery_io import ResultsSink
from .replay_archive import ReplayCase
from .replay_engine import check_settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[ReplayRecorder]:
    """The settings and the sink, checked before any test clones; the
    tables at the end."""
    check_settings()
    found = ReplayRecorder(ResultsSink(os.environ))
    yield found
    found.finish(print)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_archived_tip_is_measured_again(
    case: ReplayCase,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: ReplayRecorder,
) -> None:
    run = live(REPLAY_RUN_CAP_USD)
    replay_live(case, run, live_root, live_isolation, recorder)
