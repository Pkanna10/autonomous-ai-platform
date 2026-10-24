"""The one branch guard (``assert_safe_branch``) and the refname rules."""

from __future__ import annotations

import re

import pytest

from autonomous_ai_agents.common.errors import DeliveryError
from autonomous_ai_agents.common.models import Project
from autonomous_ai_agents.common.refnames import (
    assert_safe_branch,
    branch_prefix_problem,
    refname_problem,
)
from autonomous_ai_agents.orchestrator import nodes


@pytest.fixture
def project() -> Project:
    return Project(name="demo", root_path="/home/dev/demo", default_branch="main")


@pytest.mark.parametrize(
    ("branch", "prefix", "default", "message"),
    [
        pytest.param("main", "engine/", "main", "default branch 'main'", id="default"),
        pytest.param(
            "engine/RUN-1", "engine/", "engine/run-1", "default branch", id="casefold"
        ),
        pytest.param(
            "feature/x", "engine/", "main", "outside the engine prefix", id="outside"
        ),
        pytest.param(
            "refs/heads/engine/x", "engine/", "main", "outside the engine prefix",
            id="full ref",
        ),
        pytest.param("release", "", "main", "prefix '' must", id="empty prefix"),
        pytest.param(
            "engine-x", "engine", "main", "prefix 'engine' must", id="slashless"
        ),
        pytest.param(
            "a b/x", "a b/", "main", "not a safe git refname prefix", id="bad prefix"
        ),
        pytest.param("engine/../main", "engine/", "main", "contains '..'", id="parent"),
        pytest.param("engine/x.lock", "engine/", "main", "'.lock'", id="lock"),
        pytest.param("engine/@{-1}", "engine/", "main", "'@{'", id="reflog"),
        pytest.param("engine//x", "engine/", "main", "empty segment", id="empty"),
        pytest.param("engine/x.", "engine/", "main", "ends with '.'", id="dot"),
        pytest.param("engine/-x", "engine/", "main", "segment '-x'", id="dash"),
    ],
)  # fmt: skip
def test_assert_safe_branch_refuses_every_unsafe_branch(
    project: Project, branch: str, prefix: str, default: str, message: str
) -> None:
    """
    GIVEN a branch that is the default branch (any case), outside a valid
        prefix, or not a valid git refname
    WHEN the shared guard checks it
    THEN a DeliveryError names the rule it broke
    """
    target = project.model_copy(update={"default_branch": default})

    with pytest.raises(DeliveryError, match=re.escape(message)):
        assert_safe_branch(branch, target, prefix)


@pytest.mark.parametrize(
    ("branch", "prefix"),
    [
        ("engine/run-abc", "engine/"),
        ("engine/trial-run1-h1.v2_x", "engine/"),
        ("bots/engine/run-x", "bots/engine/"),
    ],
)
def test_assert_safe_branch_accepts_a_refname_under_the_prefix(
    project: Project, branch: str, prefix: str
) -> None:
    assert_safe_branch(branch, project, prefix)


def test_the_guard_quotes_and_caps_what_it_echoes(project: Project) -> None:
    branch = "engine/" + "‮" + "x" * 1000

    with pytest.raises(DeliveryError) as raised:
        assert_safe_branch(branch, project, "engine/")

    message = str(raised.value)
    assert "‮" not in message
    assert len(message) < 800


def test_nodes_keeps_the_guard_under_its_old_name() -> None:
    assert nodes.assert_safe_branch is assert_safe_branch


def test_refname_rules_are_unchanged() -> None:
    assert refname_problem("engine/run-1") is None
    assert branch_prefix_problem("engine/") is None
    assert branch_prefix_problem("engine") == "must be non-empty and end with '/'"
