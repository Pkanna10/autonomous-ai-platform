"""Live understand: ``ClaudeUnderstander`` on three differently shaped repos.

The dedupe fixture (a package run with ``-m``), a src-layout package with a
command-line entry point (``live_repos/cli_pkg``) and a plain script project
(``live_repos/script_proj``), each committed in ``tmp_path`` and read from
git at the base commit with the engine's real settings. Each must be
understood strictly: a schema-valid answer, every entrypoint and candidate
module a file tracked at the base commit, one note per workload, and every
understander note one of the explained snapshot notes (nothing dropped from
Claude's answer, no API failure). One hard budget covers all three.
"""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from e2e.conftest import DEDUPE_REPO, git

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import Project, Workload
from autonomous_ai_agents.orchestrator.understand import ClaudeUnderstander

from .conftest import LIVE_REPOS, StartLive, make_repo

pytestmark = pytest.mark.live

CAP_USD = 1.0
EXPLAINED_NOTES = (
    re.compile(r"\d+ secret-like file\(s\) omitted from the listing and never read"),
    re.compile(r"\d+ file name\(s\) that are unprintable or not UTF-8 left out"),
    re.compile(r"listing: \d+ more path\(s\) not shown .*"),
    re.compile(r"\d+ file\(s\) (not sent|truncated|not read|unreadable) .*"),
    re.compile(r"the answer came from the fallback model .*"),
)
"""Notes on what the snapshot left out, or who answered; anything else
(a dropped path, a schema or API failure) fails the test."""


@dataclass(frozen=True)
class Case:
    name: str
    source: Path
    commands: Sequence[tuple[str, ...]]
    hot_module: str  # recorded, not asserted: a quality signal, not a contract


CASES = (
    Case("dedupe", DEDUPE_REPO, [("python", "-m", "dedupe.main")], "dedupe/core.py"),
    Case(
        "cli_pkg",
        LIVE_REPOS / "cli_pkg",
        [("python", "-m", "wordfreq.cli", "--words", "20000")],
        "src/wordfreq/counter.py",
    ),
    Case(
        "script_proj",
        LIVE_REPOS / "script_proj",
        [("python", "report.py", "5000")],
        "stats_helpers.py",
    ),
)


def test_understand_three_repository_shapes_strictly(
    live: StartLive, live_root: Path
) -> None:
    run = live(CAP_USD)
    understander = ClaudeUnderstander(
        run.transport(settings), config=settings, sleep=time.sleep
    )
    for case in CASES:
        repo = make_repo(case.source, live_root / case.name)
        project = Project(name=case.name, root_path=str(repo.path))
        workloads = [
            Workload(project_id=project.id, name=f"{case.name}-{i}", command=command)
            for i, command in enumerate(case.commands)
        ]
        tracked = set(git(repo.path, "ls-files").splitlines())

        result = understander.understand(
            project, workloads, commit=repo.base, budget=run.budget
        )

        understanding = result.understanding
        assert understanding is not None, (case.name, result.notes)
        for note in result.notes:
            assert any(p.fullmatch(note) for p in EXPLAINED_NOTES), (case.name, note)
        assert understanding.language == "python", case.name
        assert understanding.served_by_model in chain(settings)
        assert understanding.entrypoints, case.name
        assert set(understanding.entrypoints) <= tracked, case.name
        modules = [module.path for module in understanding.candidate_modules]
        assert modules and set(modules) <= tracked, case.name
        assert set(understanding.workload_notes) == {w.id for w in workloads}
        hot = "named" if case.hot_module in modules else "missed"
        run.note(
            f"{case.name}: entrypoints {list(understanding.entrypoints)}, "
            f"candidates {modules} (hot module {case.hot_module} {hot})"
        )
    assert run.spent_usd == pytest.approx(run.budget.spent_usd, rel=1e-9)
    assert run.budget.spent_usd <= CAP_USD
