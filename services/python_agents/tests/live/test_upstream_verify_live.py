"""Live verification of the upstream corpus (V9c): the maintainer's fix, measured.

No Claude request: the cap is 0 USD (``upstream_verify.VERIFY_RUN_CAP_USD``),
and the suite is ``live`` only because it clones over the network and runs
third-party code in the ``required`` sandbox, as the noise suite does. Per
candidate of ``$LIVE_UPSTREAM_BATCH`` (``upstream.batch``: ten a dispatch),
``upstream_verify.verify_case``: the user's repository as the live suite
builds it, the sealed key committed beside it, the engine's preflight, the
Step 3 calibration, the base against the key ABBA, the project's tests on
both sides. Recorded, never asserted: gain, threshold, margin, tests, output,
verified (one JSON line each to ``$LIVE_RESULTS_PATH``, the table to the job
summary). A guard breach, or a preparation that fails, fails the case after
its ``error`` row is written.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .discovery_io import ResultsSink
from .upstream import UPSTREAM_CORPUS, UpstreamCase, batch
from .upstream_verify import VERIFY_RUN_CAP_USD, VerifyRecorder, verify_case

pytestmark = pytest.mark.live

CASES = batch(UPSTREAM_CORPUS, os.environ)


@pytest.fixture(scope="module")
def recorder() -> Iterator[VerifyRecorder]:
    """The sink, read before any test runs; the table at the end."""
    found = VerifyRecorder(ResultsSink(os.environ))
    yield found
    found.finish(print)


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_the_maintainer_fix_is_measured(
    case: UpstreamCase,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: VerifyRecorder,
) -> None:
    run = live(VERIFY_RUN_CAP_USD)
    verify_case(case, run, live_root, live_isolation, recorder)
