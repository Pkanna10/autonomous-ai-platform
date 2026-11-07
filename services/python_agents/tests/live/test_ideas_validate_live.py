"""Live Vc: the ideas-validate suite, X1's last validations before any idea
configuration runs (idea-lab spec section 6.1; O36.5e; G4's acceptance).

Two parts, in this order: the smoke requests, one minimal structured
request each to Sonnet 5 and Fable 5 (the two models X1 adds), each its own
run capped at its worst case; a refusal or an error fails the suite. Then
the dedupe labels: Opus 5 (outside every model that wrote or judged E1's
ideas) labels the chosen candidate pairs same or different mechanism, each
request counted and capped before it is sent, and refused unless every
smoke passed. At the module's end ``idea_dedupe.score`` against its fixed
bar and the owner's seeded spot-check sample.

The plan is read in the module fixture, before any test spends: one past
the 150 USD ceiling, the job's minutes or ``LIVE_SUITE_CAP_USD`` is refused.
Smoke rows, label replies, labels, the score and the sample go to
``$LIVE_RESULTS_PATH``, a summary to the job summary; nothing about the
labels is asserted. No clone: the code is V6's vendored files.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from .conftest import StartLive
from .discovery_io import ResultsSink
from .ideas_validate import (
    SMOKE_MODELS,
    ValidateRecorder,
    run_labels,
    run_smoke,
    validate_plan,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def validate() -> Iterator[ValidateRecorder]:
    """The pairs, the writers, the plan and its caps, before any spend."""
    recorder = ValidateRecorder(validate_plan(os.environ), ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize("model", SMOKE_MODELS)
def test_smoke(model: str, live: StartLive, validate: ValidateRecorder) -> None:
    run_smoke(model, live=live, recorder=validate)


def test_dedupe_labels(live: StartLive, validate: ValidateRecorder) -> None:
    run_labels(live=live, recorder=validate)
