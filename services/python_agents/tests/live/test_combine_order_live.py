"""Live O65 item 2: the combine-order replay, every archived held combine.

No Claude request: the cap is 0 USD (``order_cases.ORDER_RUN_CAP_USD``), and
the suite is ``live`` only because it clones the pinned libraries over the
network and runs third-party code in the ``required`` sandbox, as the
combine-replay suite does. The settings are checked against the X2 arms'
measurement settings before any clone (``check_settings``). One case per
library of ``$LIVE_ORDER_BATCH`` (``order_cases.batch``: three batches, so
each dispatch fits its job), ``combine_order.order_live``: every run's files
through integrity, the clone, one calibration, then per run today's score
order (a) and the measured-gain choice (b) re-tested a, b, b, a through the
combine node's path, each failed set's fallback as the engine would, and each
conflicting keep once alone.
Recorded, never asserted (one JSON line per run and per library to
``$LIVE_RESULTS_PATH``, the tables to the job summary). A mismatch, a crash
or a breach fails the library after its ``error`` row; a library with any
run not fully measured fails after all its rows.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .combine_order import OrderRecorder, order_live
from .conftest import StartLive
from .discovery_io import ResultsSink
from .order_cases import ORDER_RUN_CAP_USD, batch
from .replay_engine import check_settings

pytestmark = pytest.mark.live

LIBRARIES = batch(os.environ)


@pytest.fixture(scope="module")
def recorder() -> Iterator[OrderRecorder]:
    """The settings and the sink, checked before any test clones; the
    tables at the end."""
    check_settings()
    found = OrderRecorder(ResultsSink(os.environ))
    yield found
    found.finish(print)


@pytest.mark.parametrize("library", LIBRARIES, ids=list(LIBRARIES))
def test_every_held_combine_of_the_library_is_replayed(
    library: str,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: OrderRecorder,
) -> None:
    run = live(ORDER_RUN_CAP_USD)
    order_live(library, run, live_root, live_isolation, recorder)
