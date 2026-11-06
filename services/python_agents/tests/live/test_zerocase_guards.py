"""The zero-case guard of the live job (X2-zerocase, owner request 2026-11-06).

Emergence E1 (run 42232651527) skipped all 20 live cases and the job showed
green with 0 USD spent. With ``LIVE_REQUIRE_CASES`` set (the live job exports
the suite's name in its 'Run live tests' step only), a session in which no
``live`` test reached the end of its body (passed or failed in the call
phase) ends non-zero with one ``::error::`` line; with it unset nothing
changes. Each case runs a real pytest subprocess on a tiny module with the
live conftest as its plugin (or as the real conftest of a sibling
directory); no body touches the API (a dummy key, a closed local port).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

LIVE_DIR = Path(__file__).resolve().parent
SERVICE_DIR = LIVE_DIR.parents[1]
DUMMY_KEY = "sk-ant-api03-" + "ZEROCASE-0123456789abcdef"
MESSAGE = "::error::live suite ideas-x2: 0 cases ran; the dispatch selected nothing"
DROPPED_ENV = frozenset(
    {"ANTHROPIC_API_KEY", "PYTEST_ADDOPTS", "PYTEST_XDIST_WORKER", "LIVE_REQUIRE_CASES"}
)
MODULE = """
import pytest

@pytest.mark.live
def test_passes():
    assert True

@pytest.mark.live
def test_fails():
    assert False

@pytest.mark.live
def test_skips_in_body():
    pytest.skip("skipped inside the body")

def test_plain():
    assert True
"""
OTHER = """
import pytest

@pytest.mark.live
def test_live_elsewhere():
    assert True
"""


def _run(
    tmp_path: Path, *args: str, key: bool, suite: str | None, sibling: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run pytest on MODULE; ``sibling`` loads the live conftest as a real
    conftest of ``suite/`` (scoped to that directory, as ``tests/live``'s is)
    and adds a passing live test in ``other/``, outside its scope (stage-a's
    ``tests/execution/test_editor.py``)."""
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    live: the live marker\n", encoding="utf-8"
    )
    plugin: list[str] = ["-p", "live.conftest"]
    modules = [str(tmp_path / "test_cases.py")]
    if sibling:
        (tmp_path / "suite").mkdir()
        (tmp_path / "other").mkdir()
        (tmp_path / "suite" / "conftest.py").write_text(
            "from live.conftest import *  # noqa: F403\n", encoding="utf-8"
        )
        (tmp_path / "other" / "test_other.py").write_text(OTHER, encoding="utf-8")
        modules = [str(tmp_path / "suite" / "test_cases.py"), str(tmp_path / "other")]
        plugin = []
    Path(modules[0]).write_text(MODULE, encoding="utf-8")
    env = {
        name: value
        for name, value in os.environ.items()
        if name not in DROPPED_ENV and not name.upper().endswith("_PROXY")
    }
    env.update(
        PYTHONPATH=os.pathsep.join(
            (str(SERVICE_DIR / "src"), str(SERVICE_DIR / "tests"))
        ),
        ENGINE_API_BASE_URL="https://127.0.0.1:9",
        NO_PROXY="*",
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        COVERAGE_PROCESS_START="",
    )
    if key:
        env["ANTHROPIC_API_KEY"] = DUMMY_KEY
    if suite is not None:
        env["LIVE_REQUIRE_CASES"] = suite
    argv = [sys.executable, "-m", "pytest", "-c", str(tmp_path / "pytest.ini"),
            "--rootdir", str(tmp_path), "--import-mode=importlib", *plugin,
            "-p", "no:cacheprovider", "-p", "no:randomly", "-p", "no:xdist", "-q", "-rA",
            *args, *modules]  # fmt: skip
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.mark.parametrize(
    ("args", "key"),
    [
        (("-m", "live", "-k", "passes or fails"), False),  # the skip guard: no key
        (("-m", "live", "-k", "skips_in_body"), True),  # a skip in the body
        (("-m", "live or not live", "-k", "passes or plain"), True),  # unselected
    ],
    ids=["guard-skip", "body-skip", "only-a-plain-test-passes"],
)
def test_every_live_case_skipped_fails_with_the_flag(
    tmp_path: Path, args: tuple[str, ...], key: bool
) -> None:
    proc = _run(tmp_path, *args, key=key, suite="ideas-x2")
    output = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert MESSAGE in output.splitlines(), output


def test_one_live_case_passing_is_enough(tmp_path: Path) -> None:
    proc = _run(tmp_path, "-m", "live", "-k", "passes or skips_in_body", key=True,
                suite="ideas-x2")  # fmt: skip
    output = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.OK, output
    assert "1 passed, 1 skipped" in output and "::error::" not in output


def test_a_live_case_outside_the_conftest_directory_counts(tmp_path: Path) -> None:
    # Stage-a runs tests/live with tests/execution/test_editor.py, whose live
    # case sits outside the live conftest's directory: it must count.
    proc = _run(tmp_path, "-m", "live", "-k", "skips_in_body or elsewhere", key=True,
                suite="ideas-x2", sibling=True)  # fmt: skip
    output = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.OK, output
    assert "1 passed, 1 skipped" in output and "::error::" not in output, output


def test_a_failing_live_case_fails_as_before(tmp_path: Path) -> None:
    proc = _run(tmp_path, "-m", "live", "-k", "fails", key=True, suite="ideas-x2")
    output = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert "1 failed" in output and "::error::" not in output


@pytest.mark.parametrize(
    "args",
    [("-m", "live"), (), ("-m", "live", "-k", "nothing_matches")],
    ids=["guard-skip", "unselected", "deselected"],
)
def test_without_the_flag_nothing_changes(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    flagged = _run(tmp_path, *args, key=False, suite="")  # set but empty: off
    unset = _run(tmp_path, *args, key=False, suite=None)
    for proc in (flagged, unset):
        output = proc.stdout + proc.stderr
        wanted = pytest.ExitCode.NO_TESTS_COLLECTED if "-k" in args else 0
        assert proc.returncode == wanted, output
        assert "::error::" not in output


def test_a_dispatch_that_deselects_everything_fails_with_the_message(
    tmp_path: Path,
) -> None:
    proc = _run(tmp_path, "-m", "live", "-k", "nothing_matches", key=True,
                suite="ideas-x2")  # fmt: skip
    output = proc.stdout + proc.stderr
    assert proc.returncode != pytest.ExitCode.OK, output
    assert "4 deselected" in output and MESSAGE in output.splitlines(), output


def test_a_hostile_suite_name_cannot_forge_a_workflow_command(tmp_path: Path) -> None:
    proc = _run(tmp_path, "-m", "live", "-k", "fails", key=False,
                suite="x\n::warning::forged")  # fmt: skip
    output = proc.stdout + proc.stderr
    assert proc.returncode == pytest.ExitCode.TESTS_FAILED, output
    assert "::warning::" not in output
    assert "::error::live suite x???warning??forged: 0 cases ran" in output, output
