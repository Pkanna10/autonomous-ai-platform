"""Live E8a: "cheap first, escalate on failure", on our judges.

Per benchmark repository (12 slowdowns, 3 controls), aimed mode: a first
whole loop with Sonnet 5.5 (no fallbacks) and ``EDITOR_EFFORT`` low
(``FIRST_CAP_USD``); a slowdown that did not win runs again with Opus 5.5
at ``EDITOR_EFFORT`` high, no fallbacks (``ESCALATED_CAP_USD``).
Each pass uses a validated settings copy; every corpus guard is asserted
on every pass. Outcomes and costs are recorded (one JSON line per pass to
``$LIVE_RESULTS_PATH``; the summary, with the U22 baseline, in the job
summary), never asserted.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from autonomous_ai_agents.common.config import Settings, settings

from .conftest import StartLive
from .corpus import CorpusOutcome, CorpusRepo, start_loop
from .discovery import (
    run_engine,
)
from .discovery_escalation import (
    ESCALATION_REPOS,
    EscalationRecorder,
    Stage,
    run_escalation,
)
from .discovery_io import (
    ResultsSink,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def escalation() -> Iterator[EscalationRecorder]:
    """The results path, checked before any test spends; the summary at the end."""
    recorder = EscalationRecorder(ResultsSink(os.environ))
    yield recorder
    recorder.finish(print)


@pytest.mark.parametrize(
    "repo", ESCALATION_REPOS, ids=[r.name for r in ESCALATION_REPOS]
)
def test_cheap_editor_then_escalate(
    repo: CorpusRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    escalation: EscalationRecorder,
) -> None:
    def run_pass(stage: Stage, cfg: Settings, cap: float) -> CorpusOutcome:
        run = live(cap)
        loop = start_loop(repo, run, live_root / stage, live_isolation, cfg=cfg)
        record = functools.partial(escalation.record_pass, stage, run=run)
        return run_engine(
            loop, run, live_isolation, model=cfg.ENGINE_MODEL, record=record
        )

    escalation.add(run_escalation(repo, run_pass, settings))
