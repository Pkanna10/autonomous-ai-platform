"""Live OSS corpus (U24, STATUS Window 0): the whole loop on real libraries.

One whole loop per library of ``tests/fixtures/live_oss/manifest.json``
(8 to 10 pure-Python libraries, each pinned to a release commit): the
repository is cloned at its pin into the test's tmp dir by ``oss.py`` (a
depth-1 fetch of the tag over https from GitHub, refused unless it is the
pin), its benchmark committed as ``benchmarks/bench_<name>.py``, then exactly
as the corpus: ``build_context`` on the captured real transport with the
``required`` sandbox, the candidates of ``LIVE_CORPUS_MODE`` (``aimed``, the
default: the manifest's two efficiency candidates, one aimed at the
profiled hot spot, one neutral; ``wired``: none, the engine's generator on
its own captured transport), the library's own test subset as
the ``tests_pass`` guardrail, and ``Orchestrator.run`` capped at
``OSS_RUN_CAP_USD`` (5 USD).

A guard breach fails the case: a run that does not finish, spend over the
cap or a ledger that does not match the wire, a changed user repository,
an unsandboxed launch, or a violating trial that ran. A win is recorded
(one JSON line per run to ``$LIVE_RESULTS_PATH``, the corpus summary in
the job summary, a note in the cost table), never asserted: no fix is
known for real code. A clone that fails or is refused fails the case
before it spends anything. The job needs network access to github.com.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from e2e.conftest import Isolation

from .conftest import StartLive
from .corpus import CorpusRecorder, check_loop_guards, mode_recorder
from .oss import OSS_CORPUS, OSS_RUN_CAP_USD, OssRepo, start_oss_loop

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def recorder() -> Iterator[CorpusRecorder]:
    """The module's outcomes in the environment's mode (``$LIVE_CORPUS_MODE``,
    refused here before any run spends); the summary is written once, at the
    end."""
    corpus = mode_recorder("OSS corpus", os.environ)
    yield corpus
    corpus.finish(print)


@pytest.mark.parametrize("repo", OSS_CORPUS, ids=[repo.name for repo in OSS_CORPUS])
def test_oss_whole_loop(
    repo: OssRepo,
    live: StartLive,
    live_root: Path,
    live_isolation: Isolation,
    recorder: CorpusRecorder,
) -> None:
    run = live(OSS_RUN_CAP_USD)
    loop = start_oss_loop(repo, run, live_root, live_isolation, mode=recorder.mode)
    with recorder.recording(loop.repo, run) as slot:
        slot.result = loop.run()
        check_loop_guards(loop, run, slot.result, live_isolation)
