"""X2-DT U2: the git seam of stacked rounds (``execution/stacking.py``).

``GitStacker`` squashes a round tip onto a base (one commit, the tip's tree,
the base its only parent, deterministic), reads the capped ``base..tip``
diff, and parses the paths that diff changes, failing closed on a truncated
or unparsable diff. Against real throwaway repositories built with this
module's own git (no global config, fixed identity and dates), the shape of
``test_combine_dry_merge``'s fixtures. ``FakeStacker`` is the scripted,
recording double the node tests use.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import Project
from autonomous_ai_agents.execution.combine import _unfit
from autonomous_ai_agents.execution.fakes import (
    FAKE_SQUASH,
    FakeStacker,
    StackCall,
)
from autonomous_ai_agents.execution.git import GitWorkspace, MergeResult
from autonomous_ai_agents.execution.protocols import Stacker
from autonomous_ai_agents.execution.stacking import GitStacker, parse_changed_paths
from autonomous_ai_agents.optimization.anticheat import check_diff_all

_ENV = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.devnull, "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_AUTHOR_DATE": "@1700000000 +0000", "GIT_COMMITTER_DATE": "@1700000000 +0000"}  # fmt: skip
APP = "".join(f"line {n}\n" for n in range(1, 11))
_DELETE = object()


def run_git(cwd: Path, *args: str, stdin: bytes | None = None,
            env: Mapping[str, str] | None = None) -> str:  # fmt: skip
    proc = subprocess.run(["git", "-C", str(cwd), *args], input=stdin,
                          env={**_ENV, **(env or {})}, capture_output=True, check=True)  # fmt: skip
    return proc.stdout.decode().strip()


def child(
    repo: Path,
    parent: str,
    files: Mapping[str, str | bytes | object],
    *,
    label: str,
    mode: str = "100644",
) -> str:
    """A commit on ``parent``'s tree with ``files`` rewritten (``_DELETE``
    removes one), refs untouched."""
    env = {"GIT_INDEX_FILE": str(repo.parent / f"index-{label}")}
    run_git(repo, "read-tree", parent, env=env)
    for path, text in files.items():
        if text is _DELETE:
            run_git(repo, "update-index", "--force-remove", "--", path, env=env)
            continue
        data = text if isinstance(text, bytes) else str(text).encode()
        blob = run_git(repo, "hash-object", "-w", "--stdin", stdin=data)
        info = f"{mode},{blob},{path}"
        run_git(repo, "update-index", "--add", "--cacheinfo", info, env=env)
    tree = run_git(repo, "write-tree", env=env)
    return run_git(repo, "commit-tree", tree, "-p", parent, "-m", label)


def _tag(commit: str) -> bytes:
    return (
        f"object {commit}\ntype commit\ntag v1\n"
        "tagger T <t@example.invalid> 1700000000 +0000\n\nv1\n"
    ).encode()


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    run_git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text(APP, encoding="utf-8")
    (root / "old.py").write_text("old\n", encoding="utf-8")
    (root / "my notes.txt").write_text("notes\n", encoding="utf-8")
    run_git(root, "add", "app.py", "old.py", "my notes.txt")
    run_git(root, "commit", "-q", "-m", "base")
    return root, run_git(root, "rev-parse", "HEAD")


def project(root: Path) -> Project:
    return Project(name="p", root_path=str(root))


def stacker(root: Path, **kwargs: int) -> GitStacker:
    return GitStacker(git=GitWorkspace(root), **kwargs)


# --------------------------------------------------------------------------
# squash
# --------------------------------------------------------------------------


def test_the_squash_has_the_tips_tree_and_the_base_as_its_only_parent(
    repo: tuple[Path, str],
) -> None:
    """
    GIVEN a round tip two commits above the base (tip_1, then tip_2 on it)
    WHEN it is squashed onto the base
    THEN the squash carries tip_2's tree, the base is its one parent, the
        engine identity and the base's dates, the label is in its message,
        no ref moved, and the FIXED combiner takes it as one trial's diff
    """
    root, base = repo
    tip_1 = child(root, base, {"app.py": APP.replace("line 3", "three")}, label="t1")
    tip_2 = child(root, tip_1, {"new.py": "x = 1\n"}, label="t2")
    refs = run_git(root, "for-each-ref")
    git = GitWorkspace(root)

    squash = GitStacker(git=git).squash(project(root), base, tip_2, "run-1")

    assert run_git(root, "rev-parse", f"{squash}^{{tree}}") == run_git(
        root, "rev-parse", f"{tip_2}^{{tree}}"
    )
    assert run_git(root, "rev-list", "--parents", "-n", "1", squash).split() == [
        squash,
        base,
    ]
    assert run_git(root, "log", "-1", "--format=%an %ae %at %ct", squash) == (
        "aip-engine engine@aip.invalid 1700000000 1700000000"
    )
    assert "run-1" in run_git(root, "log", "-1", "--format=%B", squash)
    assert _unfit(git, base, squash) is None
    assert run_git(root, "for-each-ref") == refs


def test_the_squash_is_deterministic_for_the_same_inputs(
    repo: tuple[Path, str],
) -> None:
    """
    GIVEN one base, one tip and one label
    WHEN squashed twice, once through a fresh workspace on the same repo
    THEN both give the same SHA; another label gives another one
    """
    root, base = repo
    tip = child(root, base, {"app.py": APP.replace("line 9", "nine")}, label="t")

    first = stacker(root).squash(project(root), base, tip, "run-1")
    again = GitStacker().squash(project(root), base, tip, "run-1")
    other = stacker(root).squash(project(root), base, tip, "run-2")

    assert first == again
    assert other != first


def test_a_single_child_tip_squashes_to_its_own_tree(repo: tuple[Path, str]) -> None:
    root, base = repo
    tip = child(root, base, {"old.py": _DELETE}, label="t")

    squash = stacker(root).squash(project(root), base, tip, "run-1")

    assert run_git(root, "rev-parse", f"{squash}^{{tree}}") == run_git(
        root, "rev-parse", f"{tip}^{{tree}}"
    )
    assert _unfit(GitWorkspace(root), base, squash) is None


@pytest.mark.parametrize("shape", ["sibling", "reversed"])
def test_a_tip_that_does_not_descend_from_the_base_is_refused(
    repo: tuple[Path, str], shape: str
) -> None:
    """
    GIVEN a tip on a sibling line of history, or the base's own ancestor
    WHEN it is squashed onto the base
    THEN EngineError names the refusal and no commit is written
    """
    root, origin = repo
    upper = child(root, origin, {"app.py": "a\n"}, label="upper")
    sibling = child(root, origin, {"app.py": "b\n"}, label="sibling")
    base, tip = (upper, sibling) if shape == "sibling" else (upper, origin)
    objects = run_git(root, "count-objects")

    with pytest.raises(EngineError, match="does not descend from"):
        stacker(root).squash(project(root), base, tip, "run-1")

    assert run_git(root, "count-objects") == objects


def test_a_tip_equal_to_the_base_has_nothing_to_squash(repo: tuple[Path, str]) -> None:
    root, base = repo

    with pytest.raises(EngineError, match="nothing to squash"):
        stacker(root).squash(project(root), base, base, "run-1")


def test_a_conflicting_merge_is_refused(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A descendant cannot conflict with its ancestor; if git ever says so,
    the squash fails closed instead of committing nothing."""
    root, base = repo
    tip = child(root, base, {"app.py": "a\n"}, label="t")
    git = GitWorkspace(root)
    monkeypatch.setattr(git, "merge", lambda acc, commit: MergeResult(None, ("x",)))

    with pytest.raises(EngineError, match="did not merge cleanly"):
        GitStacker(git=git).squash(project(root), base, tip, "run-1")


def test_a_squash_whose_tree_is_not_the_tips_is_refused(
    repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    GIVEN a merge that (wrongly) answers the base's own tree for base + tip
    WHEN the tip is squashed
    THEN the squash's tree is checked against the tip's and EngineError
    """
    root, base = repo
    tip = child(root, base, {"app.py": "a\n"}, label="t")
    git = GitWorkspace(root)
    real = git.merge

    def merge(acc: str, commit: str) -> MergeResult:
        return real(base, base) if (acc, commit) == (base, tip) else real(acc, commit)

    monkeypatch.setattr(git, "merge", merge)
    objects = run_git(root, "count-objects")

    with pytest.raises(EngineError, match="tree is not the tip's"):
        GitStacker(git=git).squash(project(root), base, tip, "run-1")
    assert run_git(root, "count-objects") == objects  # no commit was written


@pytest.mark.parametrize("label", ["", "a/b", "a b", "-x", "x" * 65, "a\nb"])
def test_an_unsafe_label_is_refused(repo: tuple[Path, str], label: str) -> None:
    root, base = repo
    tip = child(root, base, {"app.py": "a\n"}, label="t")

    with pytest.raises(EngineError, match="label"):
        stacker(root).squash(project(root), base, tip, label)


@pytest.mark.parametrize("which", ["base", "tip"])
@pytest.mark.parametrize("value", ["abc123", "0" * 40, "tree", "tag", "HEAD"])
def test_ids_that_are_not_commits_are_refused_by_every_method(
    repo: tuple[Path, str], which: str, value: str
) -> None:
    """
    GIVEN a short id, an unknown full id, a tree's id, an annotated tag's
        id (it resolves to another commit) or a ref name
    WHEN it stands for the base or the tip of any method
    THEN EngineError: only full ids of commit objects are taken
    """
    root, base = repo
    tip = child(root, base, {"app.py": "a\n"}, label="t")
    bad = {
        "tree": lambda: run_git(root, "rev-parse", f"{tip}^{{tree}}"),
        "tag": lambda: run_git(root, "mktag", stdin=_tag(tip)),
    }.get(value, lambda: value)()
    pair = (bad, tip) if which == "base" else (base, bad)
    stack = stacker(root)

    with pytest.raises(EngineError, match=f"{which} .* is not a commit"):
        stack.squash(project(root), *pair, "run-1")
    with pytest.raises(EngineError, match=f"{which} .* is not a commit"):
        stack.diff(project(root), *pair)
    with pytest.raises(EngineError, match=f"{which} .* is not a commit"):
        stack.changed_paths(project(root), *pair)


def test_the_diff_cap_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_diff_bytes"):
        GitStacker(max_diff_bytes=0)


# --------------------------------------------------------------------------
# diff and changed paths
# --------------------------------------------------------------------------


def test_the_diff_is_the_capped_diff_commits(repo: tuple[Path, str]) -> None:
    root, base = repo
    tip = child(root, base, {"app.py": APP.replace("line 3", "three")}, label="t")
    git = GitWorkspace(root)

    full = GitStacker(git=git).diff(project(root), base, tip)
    capped = GitStacker(git=git, max_diff_bytes=40).diff(project(root), base, tip)

    assert full == git.diff_commits(base, tip)
    assert "-line 3\n+three\n" in full
    assert capped == git.diff_commits(base, tip, max_bytes=40)
    assert "[diff truncated: 40 of" in capped


def test_changed_paths_cover_add_modify_delete_and_a_path_with_spaces(
    repo: tuple[Path, str],
) -> None:
    """
    GIVEN a tip that adds a file under a new directory, modifies app.py,
        deletes old.py, edits "my notes.txt" and adds "a b/c b/d.py"
        (a name holding " b/", the header's own separator)
    WHEN its changed paths are read against the base
    THEN each path is listed once, verbatim, in git's order
    """
    root, base = repo
    files: dict[str, str | object] = {
        "pkg/new.py": "x = 1\n",
        "app.py": APP.replace("line 3", "three"),
        "old.py": _DELETE,
        "my notes.txt": "more notes\n",
        "a b/c b/d.py": "y = 2\n",
    }
    tip = child(root, base, files, label="t")

    paths = stacker(root).changed_paths(project(root), base, tip)

    assert paths == ("a b/c b/d.py", "app.py", "my notes.txt", "old.py", "pkg/new.py")


def test_changed_paths_decode_names_git_quotes(repo: tuple[Path, str]) -> None:
    """
    GIVEN a tip adding a non-ASCII name, one with a tab, one with a double
        quote and one with a backslash (git prints each in C quotes)
    WHEN its changed paths are read
    THEN each is decoded back to the name git stored
    """
    root, base = repo
    names = ("café.py", "tab\there.py", 'quo"te.py', "back\\slash.py")
    tip = child(root, base, dict.fromkeys(names, "z = 3\n"), label="t")

    paths = stacker(root).changed_paths(project(root), base, tip)

    assert sorted(paths) == sorted(names)


def test_a_mode_or_type_change_lists_its_path_once(repo: tuple[Path, str]) -> None:
    """
    GIVEN a tip turning app.py into a symlink (git prints a delete and an
        add under one name) and making old.py executable
    WHEN its changed paths are read
    THEN each path appears once
    """
    root, base = repo
    link = child(root, base, {"app.py": "old.py"}, label="link", mode="120000")
    tip = child(root, link, {"old.py": "old\n"}, label="exec", mode="100755")

    paths = stacker(root).changed_paths(project(root), base, tip)

    assert paths == ("app.py", "old.py")


def test_an_unchanged_tree_has_no_changed_paths(repo: tuple[Path, str]) -> None:
    root, base = repo
    same = child(root, base, {}, label="same")

    assert stacker(root).changed_paths(project(root), base, same) == ()


def test_a_truncated_diff_is_refused(repo: tuple[Path, str]) -> None:
    """
    GIVEN a tip whose diff is longer than the stacker's cap
    WHEN its changed paths are read
    THEN EngineError: a path past the cut could be a protected one
    """
    root, base = repo
    files = {f"f{n}.py": f"v = {n}\n" for n in range(20)}
    tip = child(root, base, files, label="t")

    with pytest.raises(EngineError, match="truncated"):
        stacker(root, max_diff_bytes=200).changed_paths(project(root), base, tip)


def test_a_diff_that_is_not_text_is_refused(repo: tuple[Path, str]) -> None:
    root, base = repo
    tip = child(root, base, {"app.py": b"line 1\n\xff\xfe\n"}, label="raw")

    with pytest.raises(EngineError, match="not UTF-8"):
        stacker(root).changed_paths(project(root), base, tip)


def blob(repo: Path, data: bytes) -> str:
    return run_git(repo, "hash-object", "-w", "--stdin", stdin=data)


def commit_with(
    repo: Path, parent: str, entries: Mapping[str, tuple[str, str] | None], label: str
) -> str:
    """A commit on ``parent``'s tree with each path set to ``(mode, oid)``
    (any mode, a gitlink included) or removed (``None``)."""
    env = {"GIT_INDEX_FILE": str(repo.parent / f"index-{label}")}
    run_git(repo, "read-tree", parent, env=env)
    for path, entry in entries.items():
        if entry is None:
            run_git(repo, "update-index", "--force-remove", "--", path, env=env)
        else:
            info = f"{entry[0]},{entry[1]},{path}"
            run_git(repo, "update-index", "--add", "--cacheinfo", info, env=env)
    tree = run_git(repo, "write-tree", env=env)
    return run_git(repo, "commit-tree", tree, "-p", parent, "-m", label)


def name_only(repo: Path, base: str, tip: str) -> tuple[str, ...]:
    """git's own answer: ``diff --name-only --no-renames``, NUL-separated."""
    argv = ["git", "-C", str(repo), "diff", "--name-only", "--no-renames",
            "--no-color", "-z", base, tip, "--"]  # fmt: skip
    out = subprocess.run(argv, env=_ENV, capture_output=True, check=True).stdout
    return tuple(os.fsdecode(path) for path in out.split(b"\0") if path)


@pytest.fixture
def rich(repo: tuple[Path, str]) -> tuple[Path, str, str]:
    """A base with a test, a source file, a binary and a script, and a tip
    that renames into and out of tests/, modifies and adds a binary, makes
    the script executable, adds an empty file, turns old.py into a
    directory, adds a non-ASCII name and a gitlink."""
    root, origin = repo
    test_a, src_b = blob(root, b"def test_a(): pass\n"), blob(root, b"b = 1\n")
    base = commit_with(root, origin, {
        "tests/test_a.py": ("100644", test_a), "src/b.py": ("100644", src_b),
        "data.bin": ("100644", blob(root, b"\0one")),
        "tool.sh": ("100644", blob(root, b"echo hi\n")),
        "blank.py": ("100644", blob(root, b"a = 1\n\nb = 2\n")),
    }, "rich-base")  # fmt: skip
    tip = commit_with(root, base, {
        "tests/test_a.py": None, "src/a.py": ("100644", test_a),
        "src/b.py": None, "tests/b.py": ("100644", src_b),
        "data.bin": ("100644", blob(root, b"\0two")),
        "new.bin": ("100644", blob(root, b"\0new")),
        "tool.sh": ("100755", blob(root, b"echo hi\n")),
        "blank.py": ("100644", blob(root, b"a = 1\n\nb = 3\n")),
        "empty.txt": ("100644", blob(root, b"")),
        "old.py": None, "old.py/inner.py": ("100644", blob(root, b"i = 1\n")),
        "caf\u00e9.py": ("100644", blob(root, b"c = 1\n")),
        "sub": ("160000", origin),
    }, "rich-tip")  # fmt: skip
    return root, base, tip


def test_every_kind_of_change_is_listed_as_git_names_it(
    rich: tuple[Path, str, str],
) -> None:
    """
    GIVEN the rich tip (renames across tests/, binaries, a mode-only change,
        an empty add, a file turned directory, a gitlink)
    WHEN its changed paths are read
    THEN they are exactly git's own ``--name-only --no-renames`` answer, and
        both sides of each rename reach the protected-path check
    """
    root, base, tip = rich

    paths = stacker(root).changed_paths(project(root), base, tip)

    assert paths == name_only(root, base, tip)
    assert {"tests/test_a.py", "src/a.py", "src/b.py", "tests/b.py"} <= set(paths)
    assert {"data.bin", "new.bin", "tool.sh", "empty.txt", "sub"} <= set(paths)
    assert {"old.py", "old.py/inner.py", "caf\u00e9.py"} <= set(paths)
    flagged = {violation.path for violation in check_diff_all(paths)}
    assert {"tests/test_a.py", "tests/b.py"} <= flagged


@pytest.mark.parametrize(
    "config",
    [
        ("diff.noprefix", "true"),
        ("diff.mnemonicPrefix", "true"),
        ("color.ui", "always"),
        ("color.diff", "always"),
        ("core.quotePath", "false"),
        ("diff.renames", "copies"),
        ("diff.renames", "true"),
        ("diff.suppressBlankEmpty", "true"),
    ],
)
def test_a_repo_config_never_changes_the_listed_paths(
    rich: tuple[Path, str, str], config: tuple[str, str]
) -> None:
    """
    GIVEN the user's repo sets a config that reshapes ``git diff`` output
    WHEN the rich tip's changed paths are read
    THEN the list is still exactly git's ``--name-only --no-renames``: the
        engine's flags (prefixes, no color, no renames) win, and a rename
        lists both its paths
    """
    root, base, tip = rich
    run_git(root, "config", *config)

    paths = stacker(root).changed_paths(project(root), base, tip)

    assert paths == name_only(root, base, tip)
    assert {"tests/test_a.py", "src/a.py"} <= set(paths)


@pytest.mark.parametrize("mode", ["log", "diff"])
@pytest.mark.parametrize("change", ["add", "bump"])
def test_a_gitlink_printed_without_a_header_fails_closed(
    repo: tuple[Path, str], mode: str, change: str
) -> None:
    """
    GIVEN ``diff.submodule=log`` (or ``diff``), under which git prints a
        gitlink as a ``Submodule <path> ...`` line with no ``diff --git``
    WHEN a tip adding or bumping a gitlink is read
    THEN EngineError: the path would otherwise be missing from the list
    """
    root, origin = repo
    added = commit_with(root, origin, {"sub": ("160000", origin)}, "add")
    bumped = commit_with(root, added, {"sub": ("160000", added)}, "bump")
    base, tip = (origin, added) if change == "add" else (added, bumped)
    assert stacker(root).changed_paths(project(root), base, tip) == ("sub",)
    run_git(root, "config", "diff.submodule", mode)

    with pytest.raises(EngineError, match="Submodule sub"):
        stacker(root).changed_paths(project(root), base, tip)


# --------------------------------------------------------------------------
# the header parser on its own
# --------------------------------------------------------------------------


def test_the_parser_reads_headers_only_never_content_lines() -> None:
    """
    GIVEN a patch whose added and context lines spell a header, and one
        whose content holds a line separator other than newline
    WHEN its paths are parsed
    THEN only real header lines count
    """
    diff = (
        "diff --git a/x.py b/x.py\n"
        "index 1..2 100644\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n"
        "-diff --git a/fake b/fake\n"
        "+a diff --git a/sep b/sep\n"
        " diff --git a/ctx b/ctx\n"
    )

    assert parse_changed_paths(diff) == ("x.py",)


@pytest.mark.parametrize(
    "header",
    [
        "diff --git a/x b/y",
        "diff --git a/x  b/x",
        "diff --git a/ b/",
        "diff --git x x",
        "diff --cc x.py",
        "diff -r a b",
        'diff --git "a/x" b/x',
        'diff --git "a/x" "b/y"',
        'diff --git "a/x\\q" "b/x\\q"',
        'diff --git "a/x\\4" "b/x\\4"',
        "diff --git a/../x b/../x",
        "diff --git a/x//y b/x//y",
        "diff --git a//x b//x",
        "diff --git a/./x b/./x",
        'diff --git "a/x\\000" "b/x\\000"',
    ],
)
def test_a_header_that_does_not_parse_fails_closed(header: str) -> None:
    with pytest.raises(EngineError, match="diff header"):
        parse_changed_paths(f"{header}\nindex 1..2\n")


_HEAD = "diff --git a/x b/x\n"


@pytest.mark.parametrize(
    "body",
    [
        "Submodule x 0000000...165f168 (new submodule)\n",
        "rename from y\nrename to x\n",
        "copy from y\n",
        "+a stray added line before any hunk\n",
        "index 1..2\n@@ -1 +1 @@\n-a\n+b\nindex 3..4\n",
        "@@ -1 +1 @@\n-a\nSubmodule x 1...2\n",
        "\nindex 1..2\n",
        "\\ No newline at end of file\n",
        "GIT binary patch\n",
        "Binary files a/x and b/x differ\n@@ -1 +1 @@\nBinary files differ\n",
    ],
)
def test_a_line_of_no_known_kind_fails_closed(body: str) -> None:
    """Every line is a header, a known header line, a hunk line or a hunk's
    content (an empty line there is blank context: ``diff.suppressBlankEmpty``);
    anything else (a ``Submodule`` line, a rename, a stray line, an empty
    line before a file's first hunk) raises, so no path can hide in it."""
    with pytest.raises(EngineError, match="line"):
        parse_changed_paths(_HEAD + body)


def test_a_line_before_the_first_header_fails_closed() -> None:
    with pytest.raises(EngineError, match="line"):
        parse_changed_paths("Submodule x 1...2\n" + _HEAD)


def test_every_known_line_kind_parses() -> None:
    diff = (
        "diff --git a/m b/m\nold mode 100644\nnew mode 100755\n"
        "diff --git a/n b/n\nnew file mode 100644\nindex 0..1\n"
        "Binary files /dev/null and b/n differ\n"
        "diff --git a/d b/d\ndeleted file mode 100644\nindex 1..0\n"
        "--- a/d\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-one\n-two\n"
        "\\ No newline at end of file\n"
        "diff --git a/r b/r\ndissimilarity index 90%\nsimilarity index 10%\n"
        "index 1..2 100644\n--- a/r\n+++ b/r\n@@ -1 +1 @@\n-a\n+b\n"
        "@@ -5,2 +5,3 @@ def f():\n c\n\n+d\n"
    )

    assert parse_changed_paths(diff) == ("m", "n", "d", "r")


def test_a_patch_without_a_final_newline_still_parses() -> None:
    assert parse_changed_paths("diff --git a/x b/x\nindex 1..2") == ("x",)
    assert parse_changed_paths("") == ()


def test_the_parser_decodes_every_c_escape_and_raw_bytes() -> None:
    """Git's quote_c_style: \\a \\b \\t \\n \\v \\f \\r \\" \\\\ and octal bytes
    (which may not be UTF-8: decoded as ``os.fsdecode`` decodes git's paths)."""
    body = 'e\\a\\b\\t\\n\\v\\f\\r\\"\\\\\\303\\251\\377'
    diff = f'diff --git "a/{body}" "b/{body}"\n'

    (path,) = parse_changed_paths(diff)

    assert path == os.fsdecode(b'e\a\b\t\n\v\f\r"\\\xc3\xa9\xff')


def test_the_parser_refuses_a_truncation_marker_anywhere() -> None:
    diff = "diff --git a/x b/x\n\n[diff truncated: 10 of 99 bytes shown]\n"

    with pytest.raises(EngineError, match="truncated"):
        parse_changed_paths(diff)


# --------------------------------------------------------------------------
# protocol and fake
# --------------------------------------------------------------------------


def test_the_real_and_the_fake_stacker_meet_the_protocol() -> None:
    assert isinstance(GitStacker(), Stacker)
    assert isinstance(FakeStacker(), Stacker)
    assert not isinstance(object(), Stacker)


def test_the_fake_returns_its_script_and_records_every_call(tmp_path: Path) -> None:
    """
    GIVEN a FakeStacker scripted with a squash id, and a diff and changed
        paths per (base, tip)
    WHEN each method is called
    THEN it returns the script (an unscripted pair gets the defaults) and
        records the method, project, base, tip and label in order
    """
    p = project(tmp_path)
    fake = FakeStacker(
        squash="f" * 40,
        diffs={("b1", "t1"): "diff one"},
        default_diff="none",
        paths={("b1", "t1"): ["a.py", "b.py"]},
        default_paths=["z.py"],
    )

    assert fake.squash(p, "b1", "t1", "run-1") == "f" * 40
    assert fake.diff(p, "b1", "t1") == "diff one"
    assert fake.diff(p, "b2", "t2") == "none"
    assert fake.changed_paths(p, "b1", "t1") == ("a.py", "b.py")
    assert fake.changed_paths(p, "b2", "t2") == ("z.py",)
    assert fake.calls == [
        StackCall("squash", p, "b1", "t1", "run-1"),
        StackCall("diff", p, "b1", "t1"),
        StackCall("diff", p, "b2", "t2"),
        StackCall("changed_paths", p, "b1", "t1"),
        StackCall("changed_paths", p, "b2", "t2"),
    ]


def test_the_fake_defaults_and_raises_what_it_was_scripted_with(
    tmp_path: Path,
) -> None:
    p = project(tmp_path)
    plain = FakeStacker()
    assert plain.squash(p, "b", "t", "x") == FAKE_SQUASH
    assert plain.diff(p, "b", "t") == ""
    assert plain.changed_paths(p, "b", "t") == ()

    failing = FakeStacker(
        squash=EngineError("no squash"),
        diffs={("b", "t"): EngineError("no diff")},
        paths={("b", "t"): EngineError("no paths")},
    )
    with pytest.raises(EngineError, match="no squash"):
        failing.squash(p, "b", "t", "x")
    with pytest.raises(EngineError, match="no diff"):
        failing.diff(p, "b", "t")
    with pytest.raises(EngineError, match="no paths"):
        failing.changed_paths(p, "b", "t")
    assert [call.method for call in failing.calls] == [
        "squash",
        "diff",
        "changed_paths",
    ]


@pytest.mark.parametrize("label", ["", "a/b", "-x", "x" * 65, "a\nb"])
def test_the_fake_squash_refuses_what_the_real_one_refuses(
    tmp_path: Path, label: str
) -> None:
    """The fake applies the real squash's label rule and refuses a tip equal
    to the base, each an EngineError, and records the call first."""
    p = project(tmp_path)
    fake = FakeStacker()

    with pytest.raises(EngineError, match="label"):
        fake.squash(p, "b", "t", label)
    with pytest.raises(EngineError, match="nothing to squash"):
        fake.squash(p, "b", "b", "run-1")
    assert [call.label for call in fake.calls] == [label, "run-1"]


@pytest.mark.parametrize(
    "script",
    [{"paths": {("b", "t"): "a.py"}}, {"default_paths": "a.py"}],
)
def test_the_fake_refuses_one_string_as_its_paths(
    script: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match="paths"):
        FakeStacker(**script)  # type: ignore[arg-type]
