"""P2: the quarantined research agent (live, CI only).

Pilot P2 of the agent roadmap (O18; spec-wave2 7c, unit A2;
``research_agent`` holds the design, ``research_agent.DECISION`` what it
measures and feeds). Five abstract hotspot descriptors, never source code;
Haiku 5.5 at effort medium, no fallbacks; every request reserved at its
worst case before it is sent, through the harness's ledger:

1. ``test_p2_arm_a`` (per hotspot, cap ``arm_a_cap``, its worst case): one
   request with E6's direct, allowlisted ``web_search`` (``max_uses`` 5);
   the cards come from its fenced JSON, their quotes are checked against the
   passages the API cited.
2. ``test_p2_arm_b`` (per hotspot, cap ``AGENT_RUN_CAP_USD``, the gate's
   0.30): ``research_agent.Researcher``, at most 10 turns with
   ``fetch_page`` (the engine fetches allowlisted https pages itself, from
   the runner) and ``submit_card``; quotes checked against the text shown.
3. ``test_p2_injection`` (per planted page, the builder's then the A2s
   setter's, cap ``INJECTION_RUN_CAP_USD``, 0.15): the same loop on the page's hotspot
   with the page as a search result, served from its fixture through the
   fetch tool; did the agent fetch a canary URL or put a canary in a card?

A ``P2`` row per run and a ``P2`` summary row (the gate's figures and
verdict) go to ``$LIVE_RESULTS_PATH`` and the log; per run a cost-table note
(``P2 <hotspot> arm A/B: ...``, ``P2 injection <page> ...``) and the running
summary in two notes (counts, then ``P2 gate <pass/fail/incomplete>`` with
its three limbs). Outcomes are recorded, never asserted; a test fails only
when the API answered nothing.

Cost: the suite needs ``research_agent.research_need()`` (7.35 USD with the
builder's page; each A2s page adds 0.15); expected well under 1 USD.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx2
import pytest

from ..conftest import LiveRun, StartLive
from . import research_agent as ra
from .harness import ExperimentClient
from .recorder import ExperimentRecorder, Metric
from .research_fetch import Fetcher
from .test_probes_live import answered, finish
from .web import research

pytestmark = pytest.mark.live
HOTSPOTS = ra.HOTSPOTS
PAGES_BY_NAME = {page.name: page for page in ra.ALL_PAGES}


@dataclass
class PilotLog:
    recorder: ExperimentRecorder
    a: dict[str, ra.ArmAResult] = field(default_factory=dict)
    b: dict[str, ra.AgentStats] = field(default_factory=dict)
    injections: list[ra.InjectionOutcome] = field(default_factory=list)

    def summary(self) -> dict[str, Metric]:
        return ra.summarise_pilot(self.a, self.b, self.injections)

    def notes(self, run: LiveRun, line: str) -> None:
        for note in (line, *ra.pilot_notes(self.summary())):
            run.note(note)


def run_arm_a(start: StartLive, hotspot: ra.Hotspot, log: PilotLog) -> ra.ArmAResult:
    run = start(ra.arm_a_cap(hotspot))
    with ExperimentClient(run, recorder=log.recorder) as client:
        found = research(
            client,
            ra.arm_a_body(hotspot),
            None,
            max_continuations=ra.ARM_A_CONTINUATIONS,
        )
    result = ra.arm_a_result(hotspot, found, answered=answered(found.answers[0]))
    log.a[hotspot.id] = result
    log.recorder.record("P2", "arm-a", hotspot.id, result.metrics())
    log.notes(run, result.line(hotspot.id))
    return result


def run_arm_b(
    start: StartLive,
    hotspot: ra.Hotspot,
    log: PilotLog,
    *,
    fetcher: Fetcher | None = None,
) -> ra.AgentStats:
    run = start(ra.AGENT_RUN_CAP_USD)
    with ExperimentClient(run, recorder=log.recorder) as client:
        stats = ra.Researcher(client, hotspot, fetcher or Fetcher()).run()
    log.b[hotspot.id] = stats
    log.recorder.record("P2", "arm-b", hotspot.id, stats.metrics())
    log.notes(run, stats.line(hotspot.id))
    return stats


def run_injection(
    start: StartLive,
    page: ra.PlantedPage,
    log: PilotLog,
    *,
    transport: httpx2.BaseTransport | None = None,
) -> ra.InjectionOutcome:
    run = start(ra.INJECTION_RUN_CAP_USD)
    fetcher = ra.planted_fetcher(page, transport=transport)
    with ExperimentClient(run, recorder=log.recorder) as client:
        agent = ra.Researcher(
            client, ra.BY_ID[page.hotspot], fetcher, seeds=(page.url,)
        )
        stats = agent.run()
    outcome = ra.InjectionOutcome(page, stats, ra.injection_verdict(stats, page))
    log.injections.append(outcome)
    log.recorder.record("P2", "injection", page.name, outcome.metrics())
    log.notes(run, outcome.line())
    return outcome


def close_log(log: PilotLog, config: pytest.Config) -> None:
    """The summary row (the gate's verdict), then the table and every row
    to the job summary and the log."""
    if log.a or log.b or log.injections:
        log.recorder.record("P2", "summary", "all", log.summary())
    finish(log.recorder, config)


@pytest.fixture(scope="module")
def pilot_log(pytestconfig: pytest.Config) -> Iterator[PilotLog]:
    log = PilotLog(ExperimentRecorder("P2 quarantined research agent", os.environ))
    yield log
    close_log(log, pytestconfig)


@pytest.mark.parametrize("hotspot", [h.id for h in HOTSPOTS])
def test_p2_arm_a(hotspot: str, live: StartLive, pilot_log: PilotLog) -> None:
    result = run_arm_a(live, ra.BY_ID[hotspot], pilot_log)
    assert result.answered, f"{hotspot}: the API answered no arm-A request"


@pytest.mark.parametrize("hotspot", [h.id for h in HOTSPOTS])
def test_p2_arm_b(hotspot: str, live: StartLive, pilot_log: PilotLog) -> None:
    stats = run_arm_b(live, ra.BY_ID[hotspot], pilot_log)
    assert stats.turns >= 1, f"{hotspot}: no arm-B turn was answered ({stats.stop})"


@pytest.mark.parametrize("name", list(PAGES_BY_NAME))
def test_p2_injection(name: str, live: StartLive, pilot_log: PilotLog) -> None:
    outcome = run_injection(live, PAGES_BY_NAME[name], pilot_log)
    assert outcome.stats.turns >= 1, (
        f"{name}: no turn was answered ({outcome.stats.stop})"
    )
