"""Live upstream corpus (V9c): the engine attempts real maintainers' exams.

One whole loop per verified candidate of ``$LIVE_UPSTREAM_BATCH``
(``upstream.live_cases``: only candidates whose ``verified`` record the CI
``upstream-verify`` suite earned, ten a dispatch). The user's repository is
``upstream.prepare_repo``'s: the before-tree as one root commit and the
blind benchmark, never the key or any later history. Then as the OSS suite in
``wired`` mode (the only mode here: the dispatch refuses another before any
run spends): ``build_context`` on the captured real transport with the
``required`` sandbox, the engine's own generator, the project's tests as the
guard, ``Orchestrator.run`` capped at ``UPSTREAM_RUN_CAP_USD`` (5 USD).

A guard breach fails the case; a win is recorded, never asserted (the
marker is the frozen judges; the key is compared offline, afterwards). With
no verified candidate in the batch the suite fails at its first test. Beside
the corpus summary, ``upstream.write_pools`` reports each pool apart (who
set the key: the maintainers, another AI agent or a Claude model, the
attempter's family; and whether the before-tree hints at the fix): O19
never pools a Claude-set or hinted exam with the scored, human-set ones.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .corpus import CorpusRecorder, check_loop_guards, mode_recorder
from .upstream import (
    BATCH_ENV,
    UPSTREAM_RUN_CAP_USD,
    UpstreamCase,
    live_cases,
    start_upstream_loop,
    write_pools,
)

pytestmark = pytest.mark.live

CASES = live_cases(os.environ)


@pytest.fixture(scope="module")
def recorder() -> Iterator[CorpusRecorder]:
    """Outcomes in ``$LIVE_CORPUS_MODE``, which must be ``wired``."""
    corpus = mode_recorder("Upstream corpus", os.environ)
    if corpus.mode != "wired":
        pytest.fail(f"the upstream corpus runs wired only, not {corpus.mode}")
    yield corpus
    corpus.finish(print)
    write_pools(CASES, corpus.outcomes, os.environ, print)


def test_the_batch_has_verified_candidates() -> None:
    assert CASES, f"no verified candidate in {BATCH_ENV} batch: run upstream-verify"


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
def test_upstream_whole_loop(
    case: UpstreamCase,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: CorpusRecorder,
) -> None:
    if recorder.mode != "wired":
        pytest.fail("wired only")
    run = live(UPSTREAM_RUN_CAP_USD)
    loop = start_upstream_loop(case, run, live_root, live_isolation)
    with recorder.recording(loop.repo, run) as slot:
        slot.result = loop.run()
        check_loop_guards(loop, run, slot.result, live_isolation)
