"""S2 (emergence round 1): ``GitCombiner.dry_merge`` and its mode.

Against real throwaway repositories built with ``test_combine``'s own git
(no global config, fixed identity and dates): the dry merge runs
``merge-tree`` pairwise over the kept commits (objects only: no worktree,
no ref, no measurement) and reads each fit commit's ``base..commit`` diff;
an unfit commit (not a child of the base) is left out of both. The mode is
``SITE_STACKS`` unless the constructor names one.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import Project
from autonomous_ai_agents.execution.combine import DryMerge, GitCombiner
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.protocols import KeptChange

_ENV = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.devnull, "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_AUTHOR_DATE": "@1700000000 +0000", "GIT_COMMITTER_DATE": "@1700000000 +0000"}  # fmt: skip
APP = "".join(f"line {n}\n" for n in range(1, 11))


def run_git(cwd: Path, *args: str, stdin: bytes | None = None,
            env: Mapping[str, str] | None = None) -> str:  # fmt: skip
    proc = subprocess.run(["git", "-C", str(cwd), *args], input=stdin,
                          env={**_ENV, **(env or {})}, capture_output=True, check=True)  # fmt: skip
    return proc.stdout.decode().strip()


def edit_line(number: int, text: str) -> str:
    lines = APP.splitlines(keepends=True)
    lines[number - 1] = text + "\n"
    return "".join(lines)


def child(
    repo: Path, parent: str, files: Mapping[str, str | bytes], *, label: str
) -> str:
    """A commit on ``parent``'s tree with ``files`` rewritten, refs untouched."""
    env = {"GIT_INDEX_FILE": str(repo.parent / f"index-{label}")}
    run_git(repo, "read-tree", parent, env=env)
    for path, text in files.items():
        data = text if isinstance(text, bytes) else text.encode()
        blob = run_git(repo, "hash-object", "-w", "--stdin", stdin=data)
        run_git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)  # fmt: skip
    tree = run_git(repo, "write-tree", env=env)
    return run_git(repo, "commit-tree", tree, "-p", parent, "-m", label)


def kept(trial_id: str, commit: str) -> KeptChange:
    return KeptChange(trial_id, f"h-{trial_id}", f"v-{trial_id}", commit, 1.0, 0.5)


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text(APP, encoding="utf-8")
    run_git(root, "add", "app.py")
    run_git(root, "commit", "-q", "-m", "base")
    return root, run_git(root, "rev-parse", "HEAD")


def test_the_dry_merge_names_each_conflicting_pair_and_reads_each_diff(
    repo: tuple[Path, str],
) -> None:
    """
    GIVEN keeps a and b editing line 3 two ways, c editing line 9, and d a
        grandchild of the base
    WHEN the dry merge runs
    THEN only {a, b} conflicts, a, b and c carry their base..commit diffs,
        d is left out, and no ref or worktree was written
    """
    root, base = repo
    a = child(root, base, {"app.py": edit_line(3, "three a")}, label="a")
    b = child(root, base, {"app.py": edit_line(3, "three b")}, label="b")
    c = child(root, base, {"app.py": edit_line(9, "nine")}, label="c")
    d = child(root, c, {"app.py": edit_line(5, "five")}, label="d")
    refs = run_git(root, "for-each-ref")
    combiner = GitCombiner(git=GitWorkspace(root), site_stacks="record")

    dry = combiner.dry_merge(
        Project(name="p", root_path=str(root)),
        base,
        [kept("a", a), kept("b", b), kept("c", c), kept("d", d)],
    )

    assert isinstance(dry, DryMerge)
    assert dry.conflicts == frozenset({frozenset({"a", "b"})})
    assert sorted(dry.diffs) == ["a", "b", "c"]
    assert "+three a" in dry.diffs["a"] and "+nine" in dry.diffs["c"]
    assert run_git(root, "for-each-ref") == refs
    assert run_git(root, "worktree", "list").count("\n") == 0


def test_a_keep_whose_diff_is_not_text_has_no_diff(repo: tuple[Path, str]) -> None:
    root, base = repo
    raw = child(root, base, {"app.py": b"line 1\n\xff\xfe\n"}, label="raw")

    dry = GitCombiner(git=GitWorkspace(root)).dry_merge(
        Project(name="p", root_path=str(root)), base, [kept("raw", raw)]
    )

    assert dry == DryMerge(frozenset(), {})


def test_the_dry_merge_refuses_a_base_that_is_not_a_commit_id(
    repo: tuple[Path, str],
) -> None:
    root, _ = repo
    combiner = GitCombiner(git=GitWorkspace(root))

    with pytest.raises(ValueError, match="not a commit id"):
        combiner.dry_merge(Project(name="p", root_path=str(root)), "HEAD", [])


def test_the_mode_is_the_setting_unless_named(monkeypatch: pytest.MonkeyPatch) -> None:
    assert GitCombiner().site_stacks == "off" == settings.SITE_STACKS
    monkeypatch.setattr(settings, "SITE_STACKS", "on")
    assert GitCombiner().site_stacks == "on"
    assert GitCombiner(site_stacks="record").site_stacks == "record"
