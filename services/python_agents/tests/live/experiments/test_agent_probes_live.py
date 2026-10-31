"""A0 (pilot P0, O18): kernel contract probes on our account (live, CI only).

Five probes (``agent_probes.PROBES``), each its own admitted run, each
recording per check what the docs say (with the URL), what the API did and a
verdict (``match``, ``differs``, ``inconclusive``):

1. ``count_web_tools`` (free): ``count_tokens`` with ``web_search`` and with
   ``web_fetch`` (documented 400), a client-only control, and the harness's
   own count path (server tools stripped).
2. ``environment_networking`` (free): a Managed Agents cloud environment
   created with no ``networking`` reports ``unrestricted``; it is deleted at
   once (one retry) and a retrieve must then 404. A deletion that is not
   verified fails the test and names the id, so the Lead can delete it.
3. ``effort_mid_conversation``: per-message effort (beta) after a cached
   turn keeps the cache; moving effort to the top level restarts it.
4. ``system_feedback``: a ``role: system`` message carrying fenced retry
   feedback is accepted and keeps the cache.
5. ``append_only``: an append-only continuation of a turn with thinking is
   accepted; editing the earlier user message is refused (documented 400 for
   accounts created on or after 2026-08-31; a 200 is ``inconclusive``).

The verdicts are recorded, never asserted: the gate (every probe matches
the docs, or the 3c kernel design changes first) is the Lead's reading of
the ``A0 gate`` note and the summary row. A test fails only when the API
never answered (or refused the key) or an environment is not verified
deleted. Rows go to ``$LIVE_RESULTS_PATH`` and the job summary, each check
also to ``run.note`` (``A0 <probe>/<check>: <verdict> (...)``).

Cost (D24): ``CAPS`` per probe, each the sum of its requests' worst cases
with the largest reply it resends, counted or not (proved offline in
``test_agent_probes``); the suite needs ``a0_need()`` (0.97, the unit cap
``A0_CAP_USD`` is 1). Expected about 0.10-0.20 USD (Opus 5.5, prompts of
about 6,000 tokens, short replies).
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

import pytest

from ..conftest import StartLive
from .agent_probes import PILOT, PROBES, ProbeResult, gate
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_probes_live import finish

pytestmark = pytest.mark.live

A0_CAP_USD: Final = 1.0  # spec-wave2-ideas 7c, row A0: cap 1, expected < 0.50
CAPS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "count_web_tools": 0.0,  # count_tokens is free
        "environment_networking": 0.0,  # environments are free; no session
        "effort_mid_conversation": 0.47,  # 3 requests, test_agent_probes
        "system_feedback": 0.30,  # 2 requests
        "append_only": 0.20,  # 3 requests
    }
)
assert list(CAPS) == list(PROBES) and math.fsum(CAPS.values()) <= A0_CAP_USD


def a0_need() -> float:
    """What the suite asks the ledger for: one run per probe at its cap."""
    return math.fsum(CAPS.values())


@dataclass
class A0Log:
    recorder: ExperimentRecorder
    results: list[ProbeResult] = field(default_factory=list)


def run_probe(start: StartLive, name: str, log: A0Log) -> ProbeResult:
    """One probe in its own admitted run; every check to the rows and the
    run's notes, then the running gate note."""
    run = start(CAPS[name])
    with ExperimentClient(run, recorder=log.recorder) as client:
        result = PROBES[name](client)
    for check in result.checks:
        log.recorder.record(PILOT, name, check.name, check.metrics())
        run.note(check.note())
    log.recorder.record(PILOT, name, "probe", result.metrics())
    log.results.append(result)
    run.note(gate(log.results)[1])
    return result


def close_log(log: A0Log, config: pytest.Config) -> None:
    """The gate row across probes, then the table and every row."""
    if log.results:
        log.recorder.record(PILOT, "summary", "gate", gate(log.results)[0])
    finish(log.recorder, config)


@pytest.fixture(scope="module")
def a0_log(pytestconfig: pytest.Config) -> Iterator[A0Log]:
    log = A0Log(ExperimentRecorder("A0 kernel contract probes", os.environ))
    yield log
    close_log(log, pytestconfig)


@pytest.mark.parametrize("name", list(PROBES))
def test_a0_probe(name: str, live: StartLive, a0_log: A0Log) -> None:
    result = run_probe(live, name, a0_log)
    assert result.answered, f"{name}: the API never answered (or refused the key)"
    assert not result.failures, "; ".join(result.failures)
