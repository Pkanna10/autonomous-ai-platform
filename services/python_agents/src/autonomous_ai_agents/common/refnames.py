"""Git refname rules shared by the branch prefix setting and the nodes.

The engine only ever creates branches it built itself (``engine/run-<id>``,
``engine/trial-<id>-<id>``), but the prefix comes from the environment and
the ids partly from the user, so every name is checked against the subset of
``git check-ref-format`` rules it could break: ``/``-separated segments of
``[A-Za-z0-9][A-Za-z0-9._-]*``, none empty, none containing ``..`` or ending
with ``.lock``, no ``@{`` and no trailing ``.``.
"""

from __future__ import annotations

import re

REFNAME_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
"""One ``/``-separated segment of a branch name the engine may create."""


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
