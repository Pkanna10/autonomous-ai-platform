"""Live BUILD: build a tool from an English spec, then improve it (CI only).

Per spec of ``$LIVE_BUILD_SPECS`` (default every spec of
``tests/fixtures/build_specs``; one left out is skipped before it spends),
one task (``build_improve.run_spec``): one Opus 5.5 request builds the
package, a separate Sonnet 5.5 request writes unittest tests from the spec
alone, the sandbox runs the tests and the workload twice (pass, same
output, within the time bound; a failure is recorded and stops the spec),
then phase 1, ``AB_N`` blind hypotheses and one whole engine loop on Sonnet
5.5 without fallbacks, every corpus guard and the output check on.

The plan is read in the module fixture, before any test spends: one past
the 150 USD ceiling is refused (the default needs ``build_need``: 26.70
USD). Outcomes are recorded (JSON lines to ``$LIVE_RESULTS_PATH``, the notes
on each spec's last run, the summary in the job summary and the log), never
asserted; a test fails only on a guard (spend within the cap, the ledger
matching the wire, the sandbox used, the user's repository untouched, an
API that answered).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .build_improve import (
    SPECS,
    SPECS_ENV,
    BuildRecorder,
    BuildSpec,
    build_plan,
    run_spec,
)
from .conftest import StartLive
from .discovery_io import ResultsSink

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def builds() -> Iterator[BuildRecorder]:
    """The plan and the results sink, read before any test spends."""
    recorder = BuildRecorder(build_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_build_then_improve(
    spec: BuildSpec,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    builds: BuildRecorder,
) -> None:
    if spec not in builds.plan.specs:
        pytest.skip(f"{SPECS_ENV} leaves {spec.name} out")
    assert live_isolation.mode == "required"
    run_spec(
        spec,
        live=live,
        root=live_root,
        isolation=live_isolation,
        recorder=builds,
    )
