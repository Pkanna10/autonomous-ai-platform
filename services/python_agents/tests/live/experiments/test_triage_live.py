"""E2: Haiku 5.5 triage of about 500 recent arXiv abstracts (live, CI only).

Fetches the newest abstracts of cs.PF, cs.DC and cs.LG from the arXiv API
(``arxiv_fetch``, spaced 3 s apart), sends all of them as one Haiku 5.5
Message Batch and the first 50 also synchronously (``triage.run_triage``),
and records cost per abstract (batch and sync), cache reads and writes,
batch latency (submit to ended), sync-vs-batch agreement per field, refusals
and the failed custom ids (resubmitted once, synchronously). The labelled
set (id, title, verdict) goes to ``$LIVE_RESULTS_PATH`` as JSON lines, one
``"arm": "label"`` row per paper; the summary to the job summary.

Knobs (``triage.triage_config``): ``LIVE_TRIAGE_COUNT`` (500),
``LIVE_TRIAGE_SYNC`` (50), ``LIVE_TRIAGE_WAIT_S`` (3600, at most 5.5 h),
``LIVE_TRIAGE_POLL_S`` (30), ``LIVE_TRIAGE_RESUBMIT`` (50). A batch still
running after the wait is recorded as pending with its id (collect it later)
and charged its worst case; the test does not fail on it.

Cost: expected about 0.06 USD (500 batch requests at about 0.0001 and 50
sync at about 0.0002 with the rubric cached); ``E2_CAP_USD`` is the worst
case of every request (``test_triage`` proves it with the counts failing).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Mapping

import pytest

from ..conftest import StartLive
from .arxiv_fetch import ArxivFetcher, FetchError, FetchRefusedError, recent
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_probes_live import finish
from .triage import TriageReport, run_triage, triage_config

pytestmark = pytest.mark.live

E2_CAP_USD = 1.25
SHARES: Mapping[str, float] = {"cs.PF": 0.3, "cs.DC": 0.3, "cs.LG": 0.4}


def quotas(count: int) -> dict[str, int]:
    """Per category, its share of ``count`` (cs.LG takes the remainder)."""
    out = {c: int(count * s) for c, s in SHARES.items() if c != "cs.LG"}
    out["cs.LG"] = count - sum(out.values())
    return out


def run_e2(
    start: StartLive,
    fetcher: ArxivFetcher,
    environ: Mapping[str, str],
    *,
    recorder: ExperimentRecorder,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TriageReport:
    """Fetch, then triage; nothing is spent unless enough abstracts came."""
    config = triage_config(environ)
    error = ""
    try:
        entries = recent(fetcher, quotas(config.count))
    except (FetchError, FetchRefusedError) as exc:
        error = str(exc)
        recorder.record("E2", "fetch", "failed", {"error": error})
        entries = ()
    recorder.record("E2", "fetch", "arxiv", {"abstracts": len(entries)})
    assert len(entries) >= max(1, config.sync_count), (
        f"arXiv returned {len(entries)} abstracts; E2 needs at least "
        f"{config.sync_count} ({error[:200] or 'no fetch error'})"
    )
    labels = ExperimentRecorder("E2 labelled set", environ)
    run = start(E2_CAP_USD)
    with ExperimentClient(run, recorder=recorder, clock=clock, sleep=sleep) as client:
        report = run_triage(
            client,
            entries,
            config=config,
            recorder=recorder,
            labels=labels,
            clock=clock,
        )
    run.note(f"E2 batch {report.batch_id}: {report.status}")
    return report


@pytest.fixture(scope="module")
def e2_recorder(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    recorder = ExperimentRecorder("E2 Haiku triage batch", os.environ)
    yield recorder
    finish(recorder, pytestconfig)


def test_e2_triage(live: StartLive, e2_recorder: ExperimentRecorder) -> None:
    with ArxivFetcher() as fetcher:
        report = run_e2(live, fetcher, os.environ, recorder=e2_recorder)
    answered = any(
        answer.status is not None
        for arm in report.arms.values()
        for answer in arm.answers.values()
    )
    assert answered or report.batch_id is not None, (
        "the API took neither the batch nor any synchronous request"
    )
