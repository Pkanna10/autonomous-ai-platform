"""G6a wiring (the Lead's patch): ``OP_COUNT_JUDGE`` turns on the counted
runs in both runners and the shadow judge, last; off, nothing changes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.transport import ScriptedTransport
from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import Project
from autonomous_ai_agents.optimization.judges import OpCountJudge, default_judges
from autonomous_ai_agents.orchestrator import factory
from autonomous_ai_agents.orchestrator.factory import build_context


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", base / "wt-root")
    (base / "user").mkdir()
    return Project(name="dedupe", root_path=str(base / "user"))


@pytest.mark.parametrize("on", [False, True])
def test_the_setting_reaches_both_runners_and_the_judges(
    project: Project, monkeypatch: pytest.MonkeyPatch, on: bool
) -> None:
    assert settings.OP_COUNT_JUDGE is False  # the product default: off
    monkeypatch.setattr(settings, "OP_COUNT_JUDGE", on)
    seen: dict[str, bool] = {}
    for name in ("GitBaselineRunner", "GitTrialRunner"):
        real = getattr(factory, name)

        def recording(*args: object, _real: object = real, _name: str = name, **kwargs: object) -> object:  # fmt: skip
            seen[_name] = bool(kwargs["count_ops"])
            return _real(*args, **kwargs)  # type: ignore[operator]

        monkeypatch.setattr(factory, name, recording)

    ctx = build_context(project, transport=ScriptedTransport([]))

    assert ctx.judges == default_judges(settings.NOISE_MULTIPLIER, op_count=on)
    assert isinstance(ctx.judges[-1], OpCountJudge) is on
    assert seen == {"GitBaselineRunner": on, "GitTrialRunner": on}
