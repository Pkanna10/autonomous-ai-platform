"""Live hard corpus (STATUS Window 0): harder work than the benchmark corpus.

One whole loop per repository of ``tests/fixtures/live_corpus_hard``, exactly
as ``test_corpus_live.py`` runs the benchmark corpus (``corpus.start_loop``
on the captured real transport with the ``required`` sandbox, every guard of
``corpus.check_loop_guards``), capped at ``HARD_RUN_CAP_USD`` (5 USD):

- ``multi``: two or three independent hot spots; the summary records whether
  the delivered gain reached the reference fix's (every hot spot removed);
- ``large``: several modules, about 800 lines, the cost not in the obvious file;
- ``trap``: the obvious fix changes the printed output, so the equivalence
  judge must reject it and only a byte-identical fix can win;
- ``memory``: the run's objective is minimize peak RSS (``CorpusRepo.objectives``
  passed to ``Orchestrator.run``), not wall time.

``LIVE_CORPUS_MODE`` applies as in the benchmark corpus (aimed, blind, decoy).
Outcomes are recorded (one JSON line per run to ``$LIVE_RESULTS_PATH``, the
summary per mode and per category in the job summary), never asserted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .corpus import (
    HARD_CORPUS,
    HARD_RUN_CAP_USD,
    CorpusRecorder,
    CorpusRepo,
    check_loop_guards,
    mode_recorder,
    start_loop,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[CorpusRecorder]:
    """The module's outcomes in the environment's mode; the summary is
    written once, at the end."""
    corpus = mode_recorder("Hard corpus", os.environ)
    yield corpus
    corpus.finish(print)


@pytest.mark.parametrize("repo", HARD_CORPUS, ids=[repo.name for repo in HARD_CORPUS])
def test_hard_corpus_whole_loop(
    repo: CorpusRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: CorpusRecorder,
) -> None:
    run = live(HARD_RUN_CAP_USD)
    loop = start_loop(repo, run, live_root, live_isolation, mode=recorder.mode)
    with recorder.recording(repo, run) as slot:
        slot.result = loop.run()
        check_loop_guards(loop, run, slot.result, live_isolation)
