"""Git refname rules shared by the branch prefix setting, the nodes and the
publisher, and the one branch guard (``assert_safe_branch``).

The engine only ever creates branches it built itself (``engine/run-<id>``,
``engine/trial-<id>-<id>``), but the prefix comes from the environment and
the ids partly from the user, so every name is checked against the subset of
``git check-ref-format`` rules it could break: ``/``-separated segments of
``[A-Za-z0-9][A-Za-z0-9._-]*``, none empty, none containing ``..`` or ending
with ``.lock``, no ``@{`` and no trailing ``.``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from autonomous_ai_agents.common.errors import DeliveryError

if TYPE_CHECKING:  # config imports this module, models imports config: no cycle
    from autonomous_ai_agents.common.models import Project

REFNAME_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
"""One ``/``-separated segment of a branch name the engine may create."""
_SHOWN = 300
"""Characters of a branch or prefix an error message echoes."""


def refname_problem(branch: str) -> str | None:
    """Why ``branch`` is not a git refname the engine may create, or ``None``."""
    if "@{" in branch:
        return "contains '@{'"
    if branch.endswith("."):
        return "ends with '.'"
    for segment in branch.split("/"):
        if not segment:
            return "has an empty segment"
        if ".." in segment:
            return f"segment {segment!r} contains '..'"
        if segment.endswith(".lock"):
            return f"segment {segment!r} ends with '.lock'"
        if REFNAME_SEGMENT.fullmatch(segment) is None:
            return (
                f"segment {segment!r} must start with a letter or digit and use "
                "only letters, digits, '.', '_' and '-'"
            )
    return None


def branch_prefix_problem(prefix: str) -> str | None:
    """Why ``prefix`` cannot start every engine branch, or ``None``.

    The prefix must be non-empty, end with ``/`` and, followed by any valid
    segment, form a valid refname: that is what every branch built from it is.
    """
    if not prefix.endswith("/"):
        return "must be non-empty and end with '/'"
    return refname_problem(prefix + "x")


def _shown(text: str) -> str:
    """``text`` for a message: capped, every unprintable character a ``?``."""
    return repr("".join(ch if ch.isprintable() else "?" for ch in text[:_SHOWN]))


def assert_safe_branch(branch: str, project: Project, prefix: str) -> None:
    """Refuse a branch the engine must not create or deliver onto.

    ``prefix`` must be non-empty, end with ``/`` and form a valid refname
    (``branch_prefix_problem``); ``branch`` must not be the project's
    default branch in any case (a case-insensitive file system shares one
    loose ref file), must start with ``prefix`` and must be a valid refname
    (``refname_problem``). Raises ``DeliveryError``; what it echoes is
    capped and has no unprintable characters.
    """
    if not prefix.endswith("/"):
        raise DeliveryError(
            f"engine branch prefix {_shown(prefix)} must be non-empty and end with '/'"
        )
    problem = branch_prefix_problem(prefix)
    if problem is not None:
        raise DeliveryError(
            f"engine branch prefix {_shown(prefix)} is not a safe git refname"
            f" prefix: {problem[:_SHOWN]}"
        )
    if branch.casefold() == project.default_branch.casefold():
        raise DeliveryError(
            f"refusing to touch the default branch {_shown(branch)} of"
            f" {_shown(project.name)}"
        )
    if not branch.startswith(prefix):
        raise DeliveryError(
            f"branch {_shown(branch)} is outside the engine prefix {_shown(prefix)}"
        )
    problem = refname_problem(branch)
    if problem is not None:
        raise DeliveryError(
            f"branch {_shown(branch)} is not a safe git refname: {problem[:_SHOWN]}"
        )
