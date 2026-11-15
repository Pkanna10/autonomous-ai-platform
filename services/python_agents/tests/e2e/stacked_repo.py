"""The fixture project and edit sets of the stacked-rounds E2E (X2-DT U7).

Written to ``tmp_path`` by ``write_tree`` and ``write_edits`` rather than
kept as files under ``tests/``: the project has its own ``tests`` package
and its edit sets hold several copies of one module, which pytest would
collect and mypy would see as duplicate modules (``tests/fixtures/`` is
excluded from both; this directory is not).

The project, ``stages``, is three stages of controlled work:
``stages/<x>.py`` sleeps ``<X>_MS`` milliseconds and returns a constant, and
``python -m stages.main`` prints the results on one line. Wall time is the
sleeps plus interpreter start-up, so every speed difference is set by the
code, not by timing luck. Each scenario's origin sleeps only what its
edits need: E3-S1 A 400 + B 600 + C 60 ms (``S1_MS``), E3-S2 B 600 + C 60
(``S2_MS``):

- every win removes at least 400 ms, every loss adds 300 ms. A judge's
  floor is twice a side's spread over 5 runs, so one start-up spike of
  size X raises it to about 0.9 X: 400 ms stays clear of the spikes a host
  loaded to 3x its cores showed (150 ms wins were not, and 300 ms ones
  once at a load of 13: U7 review);
- no edit touches C (60 ms), so every base a run reaches still takes about
  100 ms rather than a bare start-up, whose relative spread is several
  times larger;
- the suite patches ``time.sleep``: it checks the results, not the timing,
  so each suite run costs a start-up, not the stages' sleeps.

Edit sets (``ScriptedEditor``: ``<title>/files/<path>`` replaces the file):

- ``skip-a``: ``A_MS = 0``.
- ``halve-b``: ``B_MS = 200``; ``drop-b``: ``B_MS = 0``. The same line, so a
  textual conflict pair, with ``drop-b`` the higher gain (600 ms against
  400).
- ``slow-b``: ``B_MS = 300``, on a base where it is 0: a measured loss.
- ``ghost-b``: ``B_MS = 200``, plus one extra stdout line in a worktree
  named ``combine`` (the combiner's tip side): a keep in its trial whose
  every combine re-test fails the equivalence judge. A deterministic
  stand-in for a keep that does not survive the combine, by outputs rather
  than by timing (a no-gain re-test can read as a gain on a loaded host).
- ``mask-b``: ``B_MS = 0``, plus one extra stdout line in a worktree named
  ``baseline`` (the baseline runner's): equal outputs in every trial and
  combine, different ones once its tip is measured as a new base. It edits
  ``ghost-b``'s line with the higher gain (600 ms against 400), so gain
  order offers it alone and ``ghost-b`` is skipped, blocked by it.
- ``edit-test-1``, ``edit-test-2``: an edit to the suite, a protected path.

A stage reads its worktree's name from its own file (the directory above
its package): the phase directory that ``execution.phase.phase_dirs`` lays
out. No other input is read. It uses ``os.path``, which every interpreter
has loaded before ``main`` runs, never ``pathlib``: importing ``pathlib``
pulls ``re``, ``fnmatch``, ``urllib.parse`` and ``ntpath`` in (about 1.4 MB
of peak RSS on 3.11), which put ``ghost-b`` and ``mask-b`` at the default
10 % peak-RSS guardrail on 3.11, so the guardrail judge failed beside the
judge the scenario is about.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

S1_MS: Final = {"a": 400, "b": 600, "c": 60}
S2_MS: Final = {"a": 0, "b": 600, "c": 60}
RESULTS: Final = {"a": 101, "b": 202, "c": 303}
TEST_COMMAND: Final = ("python", "-m", "unittest", "discover", "-s", "tests", "-t", ".")
WORKLOAD: Final = ("python", "-m", "stages.main")
SUITE: Final = "tests/test_stages.py"

_PHASE = (
    "_PHASE = os.path.basename(os.path.dirname(os.path.dirname("
    "os.path.realpath(__file__))))\n"
)


def stage(name: str, ms: str, *, phase: bool = False, extra: str = "") -> str:
    """``stages/<name>.py`` sleeping ``ms`` (a Python expression)."""
    upper = name.upper()
    imports = "import time\n"
    if phase:
        imports = "import os\nimport time\n\n" + _PHASE
    return (
        f'"""Stage {upper}: sleeps {upper}_MS milliseconds of controlled work."""\n\n'
        f"{imports}\n{upper}_MS = {ms}\n\n\n"
        f"def stage_{name}() -> int:\n"
        f"    time.sleep({upper}_MS / 1000){extra}\n"
        f"    return {RESULTS[name]}\n"
    )


_MAIN = '''"""The workload: ``python -m stages.main`` prints the stages' results."""

from stages.a import stage_a
from stages.b import stage_b
from stages.c import stage_c


def main() -> int:
    print(f"a={stage_a()} b={stage_b()} c={stage_c()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

_SUITE = '''"""The suite: each stage returns its constant (the sleeps patched out)."""

import unittest
from unittest import mock

from stages.a import stage_a
from stages.b import stage_b
from stages.c import stage_c


class StageTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch("time.sleep")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a(self) -> None:
        self.assertEqual(stage_a(), 101)

    def test_b(self) -> None:
        self.assertEqual(stage_b(), 202)

    def test_c(self) -> None:
        self.assertEqual(stage_c(), 303)
'''


def repo_files(origin_ms: Mapping[str, int]) -> dict[str, str]:
    """The project at its origin, ``origin_ms`` per stage."""
    return {
        "stages/__init__.py": '"""stages: the stacked-rounds E2E fixture project."""\n',
        **{f"stages/{x}.py": stage(x, str(ms)) for x, ms in origin_ms.items()},
        "stages/main.py": _MAIN,
        "tests/__init__.py": "",
        SUITE: _SUITE,
    }


def _mark(phase: str, line: str) -> str:
    """The lines that print ``line`` in a worktree named ``phase``."""
    return f'\n    if _PHASE == "{phase}":\n        print("{line}")'


EDITS: Final = {
    "skip-a": {"stages/a.py": stage("a", "0")},
    "halve-b": {"stages/b.py": stage("b", "200")},
    "drop-b": {"stages/b.py": stage("b", "0")},
    "slow-b": {"stages/b.py": stage("b", "300")},
    "ghost-b": {
        "stages/b.py": stage(
            "b", "200", phase=True, extra=_mark("combine", "b: combined")
        )
    },
    "mask-b": {
        "stages/b.py": stage("b", "0", phase=True, extra=_mark("baseline", "b: a base"))
    },
    "edit-test-1": {SUITE: _SUITE.replace("101)", "101, 'a')")},
    "edit-test-2": {SUITE: _SUITE.replace("202)", "202, 'b')")},
}
"""Each edit set's files, by title (module docstring)."""


def write_tree(root: Path, files: Mapping[str, str]) -> None:
    """``files`` (repo-relative path: text) under ``root``."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def write_edits(root: Path) -> Path:
    """Every edit set under ``root`` (``ScriptedEditor``'s ``edits_dir``)."""
    for title, files in EDITS.items():
        write_tree(root / title / "files", files)
    return root
