"""Live benchmark corpus (STATUS Window 0, stage E0; stage M with Sonnet).

One whole loop per repository of ``tests/fixtures/live_corpus`` (12 known
slowdowns, 3 already-fast controls), exactly as ``test_e2e_live.py``: the
repository committed by ``make_repo``, ``build_context`` on the captured real
transport with the ``required`` sandbox, two efficiency candidates, and
``Orchestrator.run`` capped at ``CORPUS_RUN_CAP_USD`` (5 USD).

``LIVE_CORPUS_MODE`` (the ``live-smoke`` job's ``mode`` input) picks what each
run is handed: ``aimed`` (default) the manifest's two candidates, ``blind``
one generic efficiency candidate that names no fix (discovery), ``decoy`` the
neutral candidate alone. An unknown mode fails the module fixture before any
run spends.

A guard breach fails the case: a run that does not finish, spend over the
cap or a ledger that does not match the wire, a changed user repository,
an unsandboxed launch, or a violating trial that ran. Whether a slowdown was
won, or a control kept a change, is recorded (one JSON line per run to
``$LIVE_RESULTS_PATH``, the corpus summary in the job summary, a note in
the cost table), never asserted, with the rates split by mode; a decoy win
is reported on its own line. The model is ``ENGINE_MODEL`` from the
environment (the ``live-smoke`` job's ``engine_model`` input).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .corpus import (
    CORPUS,
    CORPUS_RUN_CAP_USD,
    CorpusRecorder,
    CorpusRepo,
    check_loop_guards,
    mode_recorder,
    start_loop,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[CorpusRecorder]:
    """The module's outcomes; the summary is written once, at the end."""
    corpus = mode_recorder("Benchmark corpus", os.environ)
    yield corpus
    corpus.finish(print)


@pytest.mark.parametrize("repo", CORPUS, ids=[repo.name for repo in CORPUS])
def test_corpus_whole_loop(
    repo: CorpusRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: CorpusRecorder,
) -> None:
    run = live(CORPUS_RUN_CAP_USD)
    loop = start_loop(repo, run, live_root, live_isolation, mode=recorder.mode)
    with recorder.recording(repo, run) as slot:
        slot.result = loop.run()
        check_loop_guards(loop, run, slot.result, live_isolation)
