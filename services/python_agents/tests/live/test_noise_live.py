"""Live runner noise calibration (Window 0): an A/A test on the runner itself.

Per target of ``noise.NOISE_TARGETS`` (every ``oss.OSS_CORPUS`` library,
cloned at its pin over https from GitHub, then every corpus control), with
no trial and no edit: the engine's own preflight in the ``required``
sandbox, then ``LIVE_NOISE_K`` independent baselines (default 6, 2 to 10,
scaled down to fit the 60-minute ``noise.WALL_BUDGET_S``, which pairs
with the job's 90-minute timeout, ``noise.NOISE_JOB_MINUTES``) through
``GitBaselineRunner``, the baseline node's trust and noisy-host checks,
and the A/A test through the real judges (``noise.aa_counts``). No Claude request is sent, so each run's
cap is 0 USD, the sum of no worst case (``noise.NOISE_RUN_CAP_USD``).

The plan is read in the module fixture, before any test runs. CV, A/A
false wins and the 95th-percentile difference are recorded (one JSON line
per target and a summary to ``$LIVE_RESULTS_PATH``, the table to the job
summary and the log, the ``NOISE ...`` notes in the cost table), never
asserted. The guards fail a case: a request on the wire, spend over the
cap, an unsandboxed launch or another phase, a changed user repository;
the target is then an ``error`` row (``guards: ...``), not a clean one. A
clone that fails or is refused fails its case (recorded first). A target
that would start past the wall budget is recorded as ``skipped`` and
skipped. The last test notes the summary. The job needs network access to
github.com.

The paired path (Step 3, L0): live-smoke's ``noise`` suite exports
``LIVE_NOISE_PATH=paired`` with the Step 3 noise rule, and the same tests then
run ``noise.run_paired_target`` per target: one baseline and its calibration
(``NOISE_CALIBRATION_BLOCKS``), the floor raised as the baseline node raises
it, ``noise.AA_BLOCKS`` (10) A/A blocks ABBA judged as paired trials by the
real judges, each would-be keep confirmed on a fresh block
(``CONFIRM_WINNERS``). Recorded, never asserted: the single-look false wins
of the 130 looks (would-be keeps; the gate is at most
``noise.GATE_MAX_WINS``), the speed passes beside them, the kept count, the
mean signed A/A gap, the calibrated and judged floors and row O's clearance.
Still no request, so the cap stays 0 USD.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .discovery_io import ResultsSink
from .noise import (
    NOISE_RUN_CAP_USD,
    NOISE_TARGETS,
    NoiseRecorder,
    NoiseTarget,
    noise_plan,
    run_target,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def noise() -> Iterator[NoiseRecorder]:
    """The plan and the sink, read before any test runs; the table at the end."""
    recorder = NoiseRecorder(noise_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("target", NOISE_TARGETS, ids=[t.name for t in NOISE_TARGETS])
def test_runner_noise(
    target: NoiseTarget,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    noise: NoiseRecorder,
) -> None:
    run = live(NOISE_RUN_CAP_USD)
    if run_target(target, run, live_root, live_isolation, noise) is None:
        pytest.skip(f"{target.name}: past the wall budget (recorded)")


def test_runner_noise_summary(live: StartLive, noise: NoiseRecorder) -> None:
    """Runs last (file order): the pooled summary into the cost table."""
    noise.summarize(live(NOISE_RUN_CAP_USD))
