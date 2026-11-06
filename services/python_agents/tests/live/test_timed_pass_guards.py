"""Offline guards of the timed pass (O49).

The discovery corpus's CPU-time guards (``timed``) fail under the parallel
suite's own load and pass alone, so every place that runs the suite runs it
in two passes: the parallel pass deselects ``timed`` (``pyproject.toml``'s
addopts), then the ``timed`` cases run once, serially, with ``--cov-append``
so the coverage of both passes combines. These guards keep the marker set and
every invocation in agreement: a new CPU-time guard cannot slip into the
parallel pass, and no pass drops a timed case.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

from . import test_discovery_corpus_guards as discovery_guards
from .test_corpus_guards import SERVICE_DIR, STAGE_GATE, _ci_block, _step

PYPROJECT = SERVICE_DIR / "pyproject.toml"
PACKAGE_JSON = SERVICE_DIR.parents[1] / "package.json"
DOCS = (SERVICE_DIR.parents[1] / "README.md", SERVICE_DIR / "CLAUDE.md")
PARALLEL = "not live and not timed"
TIMED = "timed and not live"
PARALLEL_STEP = "Run tests with parallelization"
TIMED_STEP = "Run the timed guards alone"
COV = "--cov --cov-report=xml --cov-report=term"
TIMED_TESTS = frozenset(
    {
        "test_reference_fix_reaches_its_gain_and_the_textbook_falls_short",
        "test_a_decoy_tempting_idea_gains_nothing",
        "test_a_deep_cost_is_a_builtin_far_below_main",
        "test_a_spread_cost_has_no_dominant_hotspot",
        "test_a_misleading_fix_sits_below_the_top_hotspots",
        "test_a_decoy_spends_its_time_outside_the_project",
    }
)


def _marked(name: str) -> frozenset[str]:
    """The discovery corpus guards' test functions that carry mark ``name``."""
    found: set[str] = set()
    for attr, value in vars(discovery_guards).items():
        marks: list[pytest.Mark] = getattr(value, "pytestmark", [])
        if attr.startswith("test_") and any(mark.name == name for mark in marks):
            found.add(attr)
    return frozenset(found)


def _pytest_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if "uv run pytest" in line]


def test_every_cpu_time_guard_of_the_discovery_corpus_is_timed() -> None:
    """The ``slow`` cases there are the CPU-time and profile guards (from the
    reference fix's gain down): each is ``timed``, and nothing else is."""
    assert _marked("slow") == TIMED_TESTS
    assert _marked("timed") == TIMED_TESTS


def test_the_default_run_is_the_parallel_pass() -> None:
    """A plain ``pytest`` deselects live and timed cases, in parallel."""
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    options = config["tool"]["pytest"]["ini_options"]
    addopts: list[str] = options["addopts"]
    assert addopts[addopts.index("-m") + 1] == PARALLEL
    assert "-n=auto" in addopts
    markers: list[str] = options["markers"]
    assert any(marker.startswith("timed: ") for marker in markers)


def test_the_python_job_runs_the_timed_guards_alone_after_the_parallel_pass() -> None:
    job = _ci_block("  python:\n", "  python-macos:\n")
    parallel = f'run: uv run pytest -m "{PARALLEL}" -n auto {COV}'
    timed = f'run: uv run pytest -m "{TIMED}" -n 0 --cov-append {COV}'
    assert _pytest_lines(job) == [parallel, timed]
    names = re.findall(r"^      - name: (.+)$", job, flags=re.MULTILINE)
    assert names.index(PARALLEL_STEP) + 1 == names.index(TIMED_STEP)
    condition = "        if: hashFiles('services/python_agents/tests/**/*.py') != ''\n"
    for name in (PARALLEL_STEP, TIMED_STEP):
        step = _step(job, name)
        assert condition in step  # the same condition: both run, or neither
        assert "continue-on-error" not in step and "|| true" not in step


def test_the_macos_job_keeps_timed_cases_out_of_its_parallel_run() -> None:
    job = _ci_block("  python-macos:\n", "  live-smoke:\n")
    expected = f'run: uv run pytest tests/execution --no-cov -m "{PARALLEL}" -n auto'
    assert _pytest_lines(job) == [expected]


def test_the_stage_gate_runs_both_passes_in_order() -> None:
    found = re.findall(r"uv run pytest[^\"\n]*", STAGE_GATE.read_text(encoding="utf-8"))
    assert found == [
        f"uv run pytest -m '{PARALLEL}'",
        f"uv run pytest -m '{TIMED}' -n 0 --cov-append",
    ]


def test_the_package_python_test_script_runs_both_passes_in_order() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
    assert scripts["python:test"] == (
        f"cd services/python_agents && pytest && pytest -m '{TIMED}' -n 0 --cov-append"
    )


def _runs_in_parallel(line: str) -> bool:
    """Whether a documented ``pytest`` on this line runs under xdist: an
    explicit ``-n`` decides; else ``-o addopts`` drops the default ``-n=auto``."""
    if re.search(r"-n[ =]0\b", line):
        return False
    if re.search(r"-n[ =](auto|[1-9])", line):
        return True
    return "-o addopts" not in line


@pytest.mark.parametrize("doc", DOCS, ids=lambda doc: doc.name)
def test_the_docs_keep_timed_cases_out_of_every_parallel_run(doc: Path) -> None:
    """README and the service CLAUDE.md name the timed pass, and every ``-m``
    they give a parallel run deselects ``timed`` (a ``-m`` replaces addopts')."""
    text = doc.read_text(encoding="utf-8")
    assert f'pytest -m "{TIMED}" -n 0 --cov-append' in text
    leaks = [
        f"{number}: {expression}"
        for number, line in enumerate(text.splitlines(), start=1)
        if _runs_in_parallel(line)
        for _, expression in re.findall(r"-m ([\"'])(.+?)\1", line)
        if "not timed" not in expression
    ]
    assert leaks == []
