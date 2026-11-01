"""A3 (pilot P3, O18): Managed Agents for the arXiv WATCH fetch (live, CI only).

Three CI dispatches of the ``watch`` suite on three days, then nothing, or
``watch-cleanup`` to cancel. Each ``watch`` dispatch is one hosted run
(``watch_managed.Watch.dispatch``):

1. Read the account (environments, agents, deployments named
   ``watch_managed.NAME``, the deployment's metadata, its sessions). Refuse,
   changing nothing, when the pilot finished, its last run is less than
   20 hours old, or its spend plus this dispatch's cap could pass 3 USD; a
   set of objects that is not one consistent pilot, or a session a previous
   dispatch left, is cleaned up and fails the test.
2. Reserve one hosted run's worst case in the run's budget.
3. Upload the program; on day 1 create the environment (``limited``,
   ``export.arxiv.org`` only), read its networking back, create the agent
   and the deployment; on days 2 and 3 re-arm the deployment's date-pinned
   cron and unpause it. Read the schedule back (one fire, at the armed
   minute, about 5 minutes ahead).
4. Wait for the deployment run (at most 9 minutes of jitter plus 3), pause
   the deployment, watch the session to idle (interrupt at 20 minutes),
   record its list cost, pull ``listing.json`` and ``feed.xml``, read the
   summary line and the probe from the session's bash output, save the state
   in the deployment's metadata, delete the session and verify the delete.
5. Triage the papers with E2's code through the harness (sync and batch).
6. After the third run, or when a run fails: archive the deployment and the
   agent, delete every session and the environment, list them to verify,
   and compute the gate (``A3 gate`` note, ``summary`` row).

``watch-cleanup`` (``LIVE_WATCH_CANCEL=1``) runs step 6 only, recording at
its list cost any session no ledger saw. Rows go to ``$LIVE_RESULTS_PATH``
and the job summary; every hosted cost, object id and the cleanup's
verification go to ``run.note`` (the cost table) for the STATUS ledger.

Cost (D24): a ``watch`` dispatch needs ``watch_need()`` (one hosted run's
worst case, 1.60, plus a listing's triage, 0.25: suite need 2); the cleanup
needs ``cleanup_need()`` (one unrecorded session, 1.60: suite need 2). The
pilot's own cap is 3 USD across dispatches (enforced from the metadata).
Expected about 0.02-0.10 USD a dispatch (a few Haiku requests, under a
minute of running time, 50 abstracts triaged).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Final

import pytest

from ..conftest import StartLive
from .harness import ExperimentClient
from .recorder import ExperimentRecorder
from .test_probes_live import finish
from .watch_managed import Dispatch, Watch, cleanup_need, watch_need

pytestmark = pytest.mark.live

CANCEL_ENV: Final = "LIVE_WATCH_CANCEL"


def utc_now() -> datetime:
    return datetime.now(UTC)


pause: Callable[[float], None] = time.sleep


def cancelling(environ: Mapping[str, str]) -> bool:
    raw = environ.get(CANCEL_ENV, "").strip()
    if raw not in ("", "0", "1"):
        raise ValueError(f"{CANCEL_ENV} must be 0 or 1, got {raw!r}")
    return raw == "1"


def watch_cap(environ: Mapping[str, str]) -> float:
    """What the dispatch asks the ledger for (refused before any spend)."""
    return cleanup_need() if cancelling(environ) else watch_need()


def run_watch(
    start: StartLive,
    environ: Mapping[str, str],
    *,
    recorder: ExperimentRecorder,
    labels: ExperimentRecorder,
) -> Dispatch:
    cancel = cancelling(environ)
    run = start(watch_cap(environ))
    with ExperimentClient(
        run, recorder=recorder, clock=lambda: utc_now().timestamp(), sleep=pause
    ) as client:
        watch = Watch(client, recorder, labels, now=utc_now, sleep=pause)
        return watch.dispatch(cancel=cancel)


@pytest.fixture(scope="module")
def a3_recorder(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    recorder = ExperimentRecorder("A3 Managed Agents WATCH", os.environ)
    yield recorder
    finish(recorder, pytestconfig)


@pytest.fixture(scope="module")
def a3_labels(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    labels = ExperimentRecorder("A3 triage labels", os.environ)
    yield labels
    finish(labels, pytestconfig)


def test_a3_watch(
    live: StartLive, a3_recorder: ExperimentRecorder, a3_labels: ExperimentRecorder
) -> None:
    dispatch = run_watch(live, os.environ, recorder=a3_recorder, labels=a3_labels)
    assert not dispatch.failures, "; ".join(dispatch.failures)
    if dispatch.cleanup is not None:
        assert dispatch.cleanup.verified, (
            f"cleanup not verified: {dispatch.cleanup.metrics()}"
        )
