"""Tests for the worktree-confined text editor handler (unit U7).

``WorktreeEditor`` executes the Anthropic text editor tool's commands
(``view``, ``create``, ``str_replace``, ``insert``) for Claude against one
trial worktree that Claude only ever sees as ``/repo``. Everything that keeps
a hijacked model inside that worktree is enforced here, in code: strict input
validation, the virtual root, ``normalize_path``, git metadata, symlinks and
hard links, the read and write deny lists, the protected patterns and the
size limits. The git-side capture rules (U9) back these up after the edit.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

import pytest

from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import ViolationRule
from autonomous_ai_agents.common.paths import PathTraversalError
from autonomous_ai_agents.execution.editor_tools import (
    DEFAULT_MODULE_ROOTS,
    LIST_DEPTH,
    LIST_MAX_ENTRIES,
    RESERVED_MODULES,
    VIEW_MAX_CHARS,
    VIRTUAL_ROOT,
    EditorLimits,
    ToolOutcome,
    WorktreeEditor,
)
from autonomous_ai_agents.execution.protocols import Change, EditResult
from autonomous_ai_agents.optimization.anticheat import (
    DEFAULT_PROTECTED_PATTERNS,
    check_capture,
)

KIB = 1024
CORE = "def unique(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n"


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A small trial worktree plus an ``outside`` directory it must never reach."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOP SECRET\n", encoding="utf-8")
    (outside / "file").write_text("outside file\n", encoding="utf-8")
    wt = tmp_path / "wt"
    (wt / "src").mkdir(parents=True)
    (wt / "src" / "core.py").write_text(CORE, encoding="utf-8")
    (wt / "tests").mkdir()
    (wt / "tests" / "test_core.py").write_text("def test_x():\n    pass\n")
    (wt / "pkg" / "__pycache__").mkdir(parents=True)
    (wt / "pkg" / "__init__.py").write_text("")
    (wt / "pkg" / "__pycache__" / "m.cpython-311.pyc").write_bytes(b"\0\1")
    (wt / "config").mkdir()
    (wt / "config" / "credentials.json").write_text('{"token": "abc"}\n')
    # Directories whose *name* is a secret pattern: their children are secret too.
    (wt / "credentials").mkdir()
    (wt / "credentials" / "aws.json").write_text('{"aws": "TOP SECRET"}\n')
    (wt / "deploy" / ".env").mkdir(parents=True)
    (wt / "deploy" / ".env" / "prod").write_text("API_KEY=sk-123\nzone=a\n")
    (wt / "deploy" / "credentials" / "prod").mkdir(parents=True)
    (wt / "deploy" / "credentials" / "prod" / "db.txt").write_text("TOP SECRET\n")
    (wt / ".git").write_text("gitdir: /home/user/repo/.git/worktrees/trial\n")
    (wt / ".env").write_text("API_KEY=sk-123\n")
    (wt / "README.md").write_text("# demo\n")
    (wt / "link").symlink_to(outside, target_is_directory=True)
    (wt / "alias.py").symlink_to(outside / "secret.txt")
    return wt


@pytest.fixture
def editor(worktree: Path) -> WorktreeEditor:
    return WorktreeEditor(worktree, protected=DEFAULT_PROTECTED_PATTERNS)


def snapshot(base: Path) -> dict[str, tuple[str, bytes]]:
    """Every entry under ``base``: its kind and its bytes (or link target)."""
    found: dict[str, tuple[str, bytes]] = {}
    for dirpath, dirnames, filenames in os.walk(base):
        for name in [*dirnames, *filenames]:
            path = Path(dirpath) / name
            info = os.lstat(path)
            key = path.relative_to(base).as_posix()
            if stat.S_ISLNK(info.st_mode):
                found[key] = ("link", os.fsencode(os.readlink(path)))
            elif stat.S_ISDIR(info.st_mode):
                found[key] = ("dir", b"")
            elif stat.S_ISREG(info.st_mode):
                found[key] = (f"file:{info.st_mode:o}", path.read_bytes())
            else:
                found[key] = ("other", b"")
    return found


def run(editor: WorktreeEditor, **command: object) -> ToolOutcome:
    return editor.execute(command)


def assert_refused(outcome: ToolOutcome, *needles: str) -> None:
    assert outcome.is_error, outcome.content
    for needle in needles:
        assert needle in outcome.content, outcome.content


# --------------------------------------------------------------------------
# The attack list: every one is refused and nothing on disk changes.
# --------------------------------------------------------------------------

WRITE_ATTACKS: list[tuple[str, str]] = [
    ("git-hooks-upper", "/repo/.GIT/hooks/pre-commit"),
    ("git-link-file", "/repo/.git"),
    ("git-nested", "/repo/src/.git/config"),
    ("dotdot-at-root", "/repo/../x"),
    ("dotdot-nested", "/repo/x/../../y"),
    ("dotdot-inner", "/repo/src/../core.py"),
    ("absolute-outside", "/etc/passwd"),
    ("double-slash", "/repo//etc/passwd"),
    ("no-leading-slash", "repo/x.py"),
    ("prefix-confusion", "/repository/x.py"),
    ("home", "~/.ssh/id_rsa"),
    ("home-inside", "/repo/~/x"),
    # "./" collapses away, so these would become the names "~x" and "c:x",
    # which no EditResult can carry (normalize_path refuses them).
    ("dot-home", "/repo/./~x"),
    ("dot-slash-home", "/repo/.//~x"),
    ("dot-drive", "/repo/./c:x"),
    ("dot-dot-drive-upper", "/repo/././C:x.py"),
    ("symlinked-dir", "/repo/link/file"),
    ("symlinked-file", "/repo/alias.py"),
    ("protected-test", "/repo/tests/test_core.py"),
    ("protected-case", "/repo/TESTS/Test_A.py"),
    ("protected-conftest", "/repo/a/conftest.py"),
    ("protected-pyproject", "/repo/pyproject.toml"),
    ("env-file", "/repo/.env"),
    ("pycache", "/repo/pkg/__pycache__/m.pyc"),
    ("native-upper", "/repo/ext.SO"),
    ("dylib", "/repo/lib/fast.dylib"),
    ("lfsconfig-upper", "/repo/.LFSCONFIG"),
    ("gitattributes-nested", "/repo/sub/.gitattributes"),
    ("gitmodules-upper", "/repo/.GITMODULES"),
    ("secret-name", "/repo/config/credentials.json"),
    ("secret-dir-child", "/repo/credentials/new.py"),
    ("env-dir-child", "/repo/deploy/.env/new.py"),
    # A new top-level module on sys.path (<wt> and <wt>/src come first) that
    # shadows the stdlib or the test runner makes a failing suite "pass".
    ("shadow-unittest", "/repo/unittest.py"),
    ("shadow-pytest", "/repo/pytest.py"),
    ("shadow-pytest-pkg", "/repo/_pytest/__init__.py"),
    ("shadow-pytest-main", "/repo/pytest/__main__.py"),
    ("shadow-site", "/repo/site.py"),
    ("shadow-in-src", "/repo/src/unittest.py"),
    ("shadow-pkg-in-src", "/repo/src/pluggy/__init__.py"),
    ("shadow-dir-first", "/repo/json/notes.txt"),
    ("shadow-case", "/repo/PyTest.py"),
    ("shadow-src-case", "/repo/SRC/pytest.py"),
    ("nul-byte", "/repo/a\x00b.py"),
    ("newline", "/repo/a\nb.py"),
    ("line-separator", "/repo/a\u2028b.py"),
    ("paragraph-separator", "/repo/a\u2029b.py"),
    ("bidi-override", "/repo/src/\u202eyp.py"),
    ("lone-surrogate", "/repo/\ud800.py"),
    ("windows-drive", "C:\\repo\\x.py"),
    ("windows-separator", "/repo/src\\core.py"),
    ("root-itself", "/repo"),
    ("root-slash", "/repo/"),
    ("empty", ""),
]


@pytest.mark.parametrize(
    "path", [p for _, p in WRITE_ATTACKS], ids=[i for i, _ in WRITE_ATTACKS]
)
def test_create_attack_is_refused_and_nothing_changes(
    editor: WorktreeEditor, tmp_path: Path, path: str
) -> None:
    before = snapshot(tmp_path)
    outcome = run(editor, command="create", path=path, file_text="pwned\n")
    assert_refused(outcome)
    assert str(tmp_path) not in outcome.content
    assert snapshot(tmp_path) == before
    assert dict(editor.written) == {}


EDIT_ATTACKS: list[tuple[str, str]] = [
    ("git-link-file", "/repo/.git"),
    ("dotdot", "/repo/../outside/file"),
    ("dot-home", "/repo/./~x"),
    ("dot-drive", "/repo/./c:x"),
    ("symlinked-dir", "/repo/link/file"),
    ("symlinked-file", "/repo/alias.py"),
    ("protected-test", "/repo/tests/test_core.py"),
    ("env-file", "/repo/.env"),
    ("secret-name", "/repo/config/credentials.json"),
    ("secret-dir-child", "/repo/credentials/aws.json"),
    ("env-dir-child", "/repo/deploy/.env/prod"),
    ("pycache", "/repo/pkg/__pycache__/m.cpython-311.pyc"),
]


@pytest.mark.parametrize(
    "path", [p for _, p in EDIT_ATTACKS], ids=[i for i, _ in EDIT_ATTACKS]
)
@pytest.mark.parametrize("command", ["str_replace", "insert"])
def test_edit_attack_is_refused_and_nothing_changes(
    editor: WorktreeEditor, tmp_path: Path, path: str, command: str
) -> None:
    before = snapshot(tmp_path)
    if command == "str_replace":
        outcome = run(editor, command=command, path=path, old_str="a", new_str="b")
    else:
        outcome = run(
            editor, command=command, path=path, insert_line=0, insert_text="x"
        )
    assert_refused(outcome)
    assert str(tmp_path) not in outcome.content
    assert "TOP SECRET" not in outcome.content
    assert "sk-123" not in outcome.content
    assert snapshot(tmp_path) == before
    assert dict(editor.written) == {}


READ_ATTACKS: list[tuple[str, str]] = [
    ("git-link-file", "/repo/.git"),
    ("git-upper", "/repo/.GIT"),
    ("env-file", "/repo/.env"),
    ("env-variant", "/repo/deploy/.env.production"),
    ("secret-name", "/repo/config/credentials.json"),
    ("secret-dir", "/repo/credentials"),
    ("secret-dir-child", "/repo/credentials/aws.json"),
    ("env-dir-child", "/repo/deploy/.env/prod"),
    ("nested-secret-dir", "/repo/deploy/credentials/prod/db.txt"),
    ("ssh-key", "/repo/keys/id_ed25519"),
    ("pem", "/repo/certs/server.PEM"),
    ("symlinked-file", "/repo/alias.py"),
    ("symlinked-dir", "/repo/link"),
    ("through-symlinked-dir", "/repo/link/secret.txt"),
    ("dotdot", "/repo/../outside/secret.txt"),
    ("dot-home", "/repo/./~x"),
    ("dot-drive", "/repo/./c:x"),
    ("absolute-outside", "/etc/passwd"),
    ("nul-byte", "/repo/src/core.py\x00"),
    ("windows-separator", "/repo/src\\core.py"),
]


@pytest.mark.parametrize(
    "path", [p for _, p in READ_ATTACKS], ids=[i for i, _ in READ_ATTACKS]
)
def test_view_attack_is_refused_without_leaking(
    editor: WorktreeEditor, tmp_path: Path, path: str
) -> None:
    outcome = run(editor, command="view", path=path)
    assert_refused(outcome)
    for leak in ("TOP SECRET", "sk-123", "abc", "gitdir", str(tmp_path)):
        assert leak not in outcome.content


SMUGGLED_NAMES = [
    "/repo/./~notes.py",
    "/repo/.//~notes.py",
    "/repo/./c:notes.py",
    "/repo/././C:notes.py",
]


@pytest.mark.parametrize("path", SMUGGLED_NAMES)
def test_a_dot_prefix_cannot_smuggle_a_home_or_drive_name(
    worktree: Path, tmp_path: Path, path: str
) -> None:
    """``./~notes.py`` normalises to ``~notes.py``, which ``EditResult`` refuses.

    The files exist, so each command would succeed if the path got through;
    a write recorded under such a name would make ``EditResult`` raise.
    """
    for name in ("~notes.py", "c:notes.py", "C:notes.py"):
        (worktree / name).write_text("x = 1\n")
    editor = WorktreeEditor(worktree, protected=())
    before = snapshot(tmp_path)
    outcomes = (
        run(editor, command="view", path=path),
        run(editor, command="create", path=path, file_text="y = 2\n"),
        run(editor, command="str_replace", path=path, old_str="1", new_str="2"),
        run(editor, command="insert", path=path, insert_line=0, insert_text="z\n"),
    )
    for outcome in outcomes:
        assert_refused(outcome, "'~'", "drive")
        assert "x = 1" not in outcome.content
    assert snapshot(tmp_path) == before
    assert dict(editor.written) == {}


def test_every_written_key_is_one_an_edit_result_accepts(
    worktree: Path, editor: WorktreeEditor
) -> None:
    for path in ("/repo/./src/a.py", "/repo/src//b.py", "/repo/x/~y.py", "/repo/c.py"):
        outcome = run(editor, command="create", path=path, file_text="v = 1\n")
        assert not outcome.is_error, (path, outcome.content)
    result = EditResult(written=editor.written)
    assert set(result.written) == {"src/a.py", "src/b.py", "x/~y.py", "c.py"}


def test_git_metadata_refusal_names_the_rule(editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="create", path="/repo/.GIT/hooks/pre-commit", file_text="x"
    )
    assert_refused(outcome, "git metadata")


def test_symlink_refusal_names_the_rule(editor: WorktreeEditor) -> None:
    assert_refused(run(editor, command="view", path="/repo/link/file"), "symlink")


def test_protected_refusal_names_the_pattern(editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="create", path="/repo/tests/test_core.py", file_text="x"
    )
    assert_refused(outcome, "protected", "**/tests/**")


def test_write_deny_refusal_names_the_pattern(editor: WorktreeEditor) -> None:
    assert_refused(
        run(editor, command="create", path="/repo/ext.SO", file_text="x"), "*.so"
    )


def test_secret_refusal_names_the_pattern(editor: WorktreeEditor) -> None:
    assert_refused(run(editor, command="view", path="/repo/.env"), "secrets", ".env")


def test_extra_protected_pattern_is_enforced(worktree: Path) -> None:
    editor = WorktreeEditor(worktree, protected=("run.sh",))
    assert_refused(run(editor, command="create", path="/repo/RUN.sh", file_text="x"))
    created = run(editor, command="create", path="/repo/tests/new.py", file_text="x")
    assert not created.is_error


def test_shadowing_refusal_names_the_module(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="create", path="/repo/pytest.py", file_text="x")
    assert_refused(outcome, "'pytest'", "shadow")


def test_existing_modules_named_like_reserved_ones_stay_editable(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "profile.py").write_text("x = 1\n")
    (worktree / "src" / "json").mkdir()
    (worktree / "src" / "json" / "__init__.py").write_text("")
    edited = run(
        editor, command="str_replace", path="/repo/profile.py", old_str="1", new_str="2"
    )
    assert not edited.is_error, edited.content
    for path in (
        "/repo/src/json/fast.py",  # inside the user's own package
        "/repo/docs/json.py",  # docs/ is not on sys.path
        "/repo/src/pkg/pytest.py",  # a submodule never shadows a top-level one
        "/repo/src/core_json.py",
        "/repo/pytest.txt",  # not importable
    ):
        created = run(editor, command="create", path=path, file_text="x\n")
        assert not created.is_error, (path, created.content)


def test_reserved_modules_can_be_extended_or_replaced(worktree: Path) -> None:
    extended = WorktreeEditor(
        worktree, protected=(), reserved_modules=RESERVED_MODULES | {"numpy"}
    )
    for path, name in (("/repo/numpy/__init__.py", "numpy"), ("/repo/json.py", "json")):
        outcome = run(extended, command="create", path=path, file_text="")
        assert_refused(outcome, f"'{name}'")
    default = WorktreeEditor(worktree, protected=())
    assert not run(
        default, command="create", path="/repo/numpy.py", file_text=""
    ).is_error
    replaced = WorktreeEditor(worktree, protected=(), reserved_modules=frozenset())
    created = run(replaced, command="create", path="/repo/unittest.py", file_text="")
    assert not created.is_error


# --------------------------------------------------------------------------
# Module roots: the editor refuses what check_capture's module_shadow rejects.
# --------------------------------------------------------------------------

ROOTS = frozenset({"", "src", "scripts", "tools/bench"})


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/repo/scripts/json.py", "json"),
        ("/repo/scripts/pytest/__init__.py", "pytest"),
        ("/repo/scripts/json/data.txt", "json"),
        ("/repo/Scripts/JSON.py", "json"),
        ("/repo/tools/bench/site.py", "site"),
        ("/repo/unittest.py", "unittest"),
        ("/repo/src/unittest.py", "unittest"),
    ],
)
def test_every_module_root_refuses_new_reserved_modules(
    worktree: Path, path: str, name: str
) -> None:
    editor = WorktreeEditor(worktree, protected=(), module_roots=ROOTS)
    before = snapshot(worktree)
    outcome = run(editor, command="create", path=path, file_text="x\n")
    assert_refused(outcome, f"'{name}'", "shadow")
    assert snapshot(worktree) == before
    assert dict(editor.written) == {}


def test_module_roots_replace_the_defaults(worktree: Path) -> None:
    editor = WorktreeEditor(worktree, protected=(), module_roots=frozenset({"scripts"}))
    outside_roots = run(
        editor, command="create", path="/repo/unittest.py", file_text=""
    )
    assert not outside_roots.is_error, outside_roots.content
    inside = run(editor, command="create", path="/repo/scripts/site.py", file_text="")
    assert_refused(inside, "'site'")


def test_default_module_roots_are_the_capture_rule_defaults(worktree: Path) -> None:
    assert DEFAULT_MODULE_ROOTS == frozenset({"", "src"})
    editor = WorktreeEditor(worktree, protected=())
    for path in ("/repo/json.py", "/repo/src/json.py"):
        assert_refused(run(editor, command="create", path=path, file_text=""), "json")
    deeper = run(editor, command="create", path="/repo/scripts/json.py", file_text="")
    assert not deeper.is_error, deeper.content


def test_init_turning_a_reserved_directory_into_a_package_is_refused(
    worktree: Path,
) -> None:
    (worktree / "src" / "json").mkdir()
    (worktree / "src" / "json" / "notes.txt").write_text("x\n")
    editor = WorktreeEditor(worktree, protected=())
    outcome = run(
        editor, command="create", path="/repo/src/json/__init__.py", file_text=""
    )
    assert_refused(outcome, "'json'", "regular package")
    assert not (worktree / "src" / "json" / "__init__.py").exists()
    sibling = run(editor, command="create", path="/repo/src/json/fast.py", file_text="")
    assert not sibling.is_error, sibling.content
    nested = run(
        editor, command="create", path="/repo/src/json/sub/__init__.py", file_text=""
    )
    assert not nested.is_error, nested.content


def test_existing_init_of_a_reserved_package_stays_editable(worktree: Path) -> None:
    (worktree / "json").mkdir()
    (worktree / "json" / "__init__.py").write_text("x = 1\n")
    editor = WorktreeEditor(worktree, protected=())
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/json/__init__.py",
        old_str="1",
        new_str="2",
    )
    assert not outcome.is_error, outcome.content


def test_dotted_reserved_names_reserve_their_first_component(worktree: Path) -> None:
    editor = WorktreeEditor(
        worktree, protected=(), reserved_modules=frozenset({"MyPkg.cli"})
    )
    for path in ("/repo/mypkg/__init__.py", "/repo/src/mypkg.py"):
        assert_refused(
            run(editor, command="create", path=path, file_text=""), "'mypkg'"
        )
    other = run(editor, command="create", path="/repo/cli.py", file_text="")
    assert not other.is_error, other.content


def test_a_str_for_reserved_modules_is_a_type_error(worktree: Path) -> None:
    bad = cast("frozenset[str]", "json")
    with pytest.raises(TypeError, match="reserved_modules"):
        WorktreeEditor(worktree, protected=(), reserved_modules=bad)


def test_a_str_for_module_roots_is_a_type_error(worktree: Path) -> None:
    bad = cast("frozenset[str]", "src")
    with pytest.raises(TypeError, match="module_roots"):
        WorktreeEditor(worktree, protected=(), module_roots=bad)


@pytest.mark.parametrize("root", ["../x", "/abs", "~/x", "./~x", "./c:x"])
def test_a_module_root_outside_the_repo_is_refused(worktree: Path, root: str) -> None:
    with pytest.raises(PathTraversalError):
        WorktreeEditor(worktree, protected=(), module_roots=frozenset({root}))


PARITY_RESERVED = RESERVED_MODULES | {"mypkg"}
PARITY_ROOTS = frozenset({"", "src", "scripts"})
PARITY_PATHS = [
    "unittest.py",
    "src/unittest.py",
    "scripts/json.py",
    "scripts/json/x.txt",
    "json/x.txt",
    "src/json/__init__.py",  # src/json exists without an __init__.py
    "src/json/fast.py",
    "docs/json.py",
    "pytest.txt",
    "SRC/PyTest.py",
    "src/pkg/pytest.py",
    "mypkg/__init__.py",
    "src/fast_json.py",
    "pkg/json.py",
    "src/JSON/__init__.py",  # a case variant both refuse: it makes a package
]
CASE_VARIANTS = [
    # src/json exists in the base. Capture folds case against the base's
    # directories and allows these; the editor asks the disk, so on a
    # case-sensitive one (Linux) it refuses them as a new package: stricter.
    "SRC/JSON/x.txt",
    "Src/Json/fast.py",
]


def _directories(base: Path) -> frozenset[str]:
    found: set[str] = set()
    for dirpath, dirnames, _ in os.walk(base):
        for name in dirnames:
            path = Path(dirpath) / name
            if not path.is_symlink():
                found.add(path.relative_to(base).as_posix())
    return frozenset(found)


@pytest.mark.parametrize("path", [*PARITY_PATHS, *CASE_VARIANTS])
def test_editor_refuses_at_least_what_the_capture_rule_rejects(
    worktree: Path, path: str
) -> None:
    """Never looser than ``module_shadow``; exactly as strict unless the case differs."""
    (worktree / "src" / "json").mkdir()
    (worktree / "src" / "json" / "notes.txt").write_text("x\n")
    existing = _directories(worktree)
    editor = WorktreeEditor(
        worktree,
        protected=(),
        reserved_modules=PARITY_RESERVED,
        module_roots=PARITY_ROOTS,
    )
    outcome = run(editor, command="create", path=f"/repo/{path}", file_text="x\n")
    found = check_capture(
        [Change("A", "000000", "100644", path)],
        {path: 2},
        {path: b"x\n"},
        frozenset(),
        reserved_modules=PARITY_RESERVED,
        module_roots=PARITY_ROOTS,
        existing_dirs=existing,
    )
    shadowed = any(v.rule is ViolationRule.module_shadow for v in found)
    assert outcome.is_error >= shadowed, (outcome.content, found)  # never looser
    if path in CASE_VARIANTS:
        assert not shadowed, found
        spelled = worktree.joinpath(*path.split("/")[:2])
        assert outcome.is_error is not os.path.lexists(spelled), outcome.content
    else:
        assert outcome.is_error == shadowed, (outcome.content, found)


@pytest.mark.parametrize(
    "name",
    [
        # Every name pytest 9 reads, in its precedence order (findpaths.py).
        "pytest.toml",
        ".pytest.toml",
        "pytest.ini",
        ".pytest.ini",
        "pyproject.toml",
        "tox.ini",
        "setup.cfg",
    ],
)
def test_every_pytest_config_file_is_protected_by_default(
    worktree: Path, editor: WorktreeEditor, name: str
) -> None:
    text = "[pytest]\naddopts = --collect-only\n"
    outcome = run(editor, command="create", path=f"/repo/{name}", file_text=text)
    assert_refused(outcome, "protected")
    assert not (worktree / name).exists()


def test_protected_files_can_still_be_viewed(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="view", path="/repo/tests/test_core.py")
    assert not outcome.is_error
    assert "def test_x" in outcome.content


def test_symlink_loop_is_refused(worktree: Path, editor: WorktreeEditor) -> None:
    (worktree / "loop").symlink_to(worktree / "loop")
    assert_refused(run(editor, command="view", path="/repo/loop/x"), "symlink")
    assert_refused(run(editor, command="create", path="/repo/loop", file_text="x"))


def test_hard_linked_file_is_never_written(
    worktree: Path, tmp_path: Path, editor: WorktreeEditor
) -> None:
    os.link(tmp_path / "outside" / "file", worktree / "hl.py")
    before = snapshot(tmp_path)
    viewed = run(editor, command="view", path="/repo/hl.py")
    assert_refused(viewed, "hard link")
    assert "outside file" not in viewed.content
    assert_refused(
        run(editor, command="create", path="/repo/hl.py", file_text="x"), "hard link"
    )
    assert_refused(
        run(
            editor,
            command="str_replace",
            path="/repo/hl.py",
            old_str="outside",
            new_str="x",
        )
    )
    assert snapshot(tmp_path) == before


def test_fifo_is_refused_without_blocking(
    worktree: Path, editor: WorktreeEditor
) -> None:
    os.mkfifo(worktree / "pipe")
    assert_refused(run(editor, command="view", path="/repo/pipe"), "regular file")
    assert_refused(run(editor, command="create", path="/repo/pipe", file_text="x"))


def test_component_that_is_a_file_is_refused(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="create", path="/repo/README.md/x.py", file_text="x")
    assert_refused(outcome, "not a directory")


def test_os_errors_are_reported_without_the_real_root(
    editor: WorktreeEditor, worktree: Path
) -> None:
    outcome = run(editor, command="view", path="/repo/" + "n" * 300)
    assert_refused(outcome)
    assert str(worktree) not in outcome.content


# --------------------------------------------------------------------------
# Input validation: strict shapes, unknown keys and commands are errors.
# --------------------------------------------------------------------------

BAD_INPUTS: list[tuple[str, dict[str, object]]] = [
    ("missing-command", {"path": "/repo/src/core.py"}),
    ("command-not-str", {"command": 5, "path": "/repo/src/core.py"}),
    ("unknown-command", {"command": "delete", "path": "/repo/src/core.py"}),
    ("rename-command", {"command": "rename", "path": "/repo/src/core.py"}),
    ("unknown-key", {"command": "view", "path": "/repo/src/core.py", "mode": "x"}),
    ("missing-path", {"command": "view"}),
    ("path-not-str", {"command": "view", "path": 7}),
    ("path-bytes", {"command": "view", "path": b"/repo/src/core.py"}),
    ("create-no-text", {"command": "create", "path": "/repo/n.py"}),
    (
        "create-text-none",
        {"command": "create", "path": "/repo/n.py", "file_text": None},
    ),
    (
        "create-extra-key",
        {
            "command": "create",
            "path": "/repo/n.py",
            "file_text": "",
            "view_range": [1, 2],
        },
    ),
    ("replace-no-old", {"command": "str_replace", "path": "/repo/src/core.py"}),
    (
        "replace-old-int",
        {"command": "str_replace", "path": "/repo/src/core.py", "old_str": 1},
    ),
    (
        "insert-line-str",
        {
            "command": "insert",
            "path": "/repo/src/core.py",
            "insert_line": "1",
            "insert_text": "x",
        },
    ),
    (
        "insert-line-bool",
        {
            "command": "insert",
            "path": "/repo/src/core.py",
            "insert_line": True,
            "insert_text": "x",
        },
    ),
    (
        "insert-line-float",
        {
            "command": "insert",
            "path": "/repo/src/core.py",
            "insert_line": 1.0,
            "insert_text": "x",
        },
    ),
    (
        "insert-old-name",
        {
            "command": "insert",
            "path": "/repo/src/core.py",
            "insert_line": 1,
            "new_str": "x",
        },
    ),
    (
        "range-short",
        {"command": "view", "path": "/repo/src/core.py", "view_range": [1]},
    ),
    (
        "range-long",
        {"command": "view", "path": "/repo/src/core.py", "view_range": [1, 2, 3]},
    ),
    (
        "range-str",
        {"command": "view", "path": "/repo/src/core.py", "view_range": ["1", 2]},
    ),
    (
        "range-bool",
        {"command": "view", "path": "/repo/src/core.py", "view_range": [True, 2]},
    ),
    (
        "range-dict",
        {"command": "view", "path": "/repo/src/core.py", "view_range": {"a": 1}},
    ),
]


@pytest.mark.parametrize(
    "command", [c for _, c in BAD_INPUTS], ids=[i for i, _ in BAD_INPUTS]
)
def test_malformed_input_is_an_error_result(
    editor: WorktreeEditor, tmp_path: Path, command: dict[str, object]
) -> None:
    before = snapshot(tmp_path)
    outcome = editor.execute(command)
    assert_refused(outcome, "invalid input")
    assert snapshot(tmp_path) == before


def test_undo_edit_is_not_supported(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="undo_edit", path="/repo/src/core.py")
    assert_refused(outcome, "undo_edit", "not supported")


def test_validation_error_names_the_field(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="create", path="/repo/n.py")
    assert_refused(outcome, "file_text")


def test_execute_accepts_any_mapping(editor: WorktreeEditor) -> None:
    command: Mapping[str, object] = {"command": "view", "path": "/repo/README.md"}
    assert not editor.execute(MappingProxyType(dict(command))).is_error


# --------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------


def test_view_file_numbers_lines_like_cat_n(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "src" / "abc.py").write_text("a\nb\nc\n")
    outcome = run(editor, command="view", path="/repo/src/abc.py")
    assert outcome == ToolOutcome("     1\ta\n     2\tb\n     3\tc", is_error=False)


def test_view_accepts_dot_segments_and_nfc(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "src" / "café.py").write_text("x = 1\n")
    outcome = run(editor, command="view", path="/repo/./src/cafe\u0301.py")
    assert outcome.content == "     1\tx = 1"


@pytest.mark.parametrize(
    ("view_range", "expected"),
    [
        ([2, 3], "     2\tb\n     3\tc"),
        ([2, -1], "     2\tb\n     3\tc\n     4\td"),
        ([1, 1], "     1\ta"),
        ([4, 4], "     4\td"),
    ],
)
def test_view_range_selects_lines(
    worktree: Path, editor: WorktreeEditor, view_range: list[int], expected: str
) -> None:
    (worktree / "abcd.txt").write_text("a\nb\nc\nd")
    outcome = run(editor, command="view", path="/repo/abcd.txt", view_range=view_range)
    assert outcome == ToolOutcome(expected, is_error=False)


@pytest.mark.parametrize(
    "view_range", [[0, 1], [5, 5], [3, 2], [1, 5], [1, -2], [-1, -1]]
)
def test_view_range_out_of_bounds_is_an_error(
    worktree: Path, editor: WorktreeEditor, view_range: list[int]
) -> None:
    (worktree / "abcd.txt").write_text("a\nb\nc\nd\n")
    outcome = run(editor, command="view", path="/repo/abcd.txt", view_range=view_range)
    assert_refused(outcome, "view_range", "4 lines")


def test_view_empty_file(worktree: Path, editor: WorktreeEditor) -> None:
    (worktree / "empty.py").write_text("")
    outcome = run(editor, command="view", path="/repo/empty.py")
    assert outcome == ToolOutcome("/repo/empty.py is empty.", is_error=False)
    ranged = run(editor, command="view", path="/repo/empty.py", view_range=[1, 1])
    assert_refused(ranged, "0 lines")


def test_view_missing_file_is_an_error(editor: WorktreeEditor) -> None:
    assert_refused(
        run(editor, command="view", path="/repo/src/nope.py"), "does not exist"
    )


def test_view_binary_and_non_utf8_files_are_refused(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "blob.dat").write_bytes(b"abc\x00def")
    (worktree / "latin1.txt").write_bytes("caf\xe9\n".encode("latin-1"))
    assert_refused(run(editor, command="view", path="/repo/blob.dat"), "binary")
    assert_refused(run(editor, command="view", path="/repo/latin1.txt"), "UTF-8")


def test_view_of_oversized_file_is_refused(worktree: Path) -> None:
    editor = WorktreeEditor(
        worktree,
        protected=(),
        limits=EditorLimits(max_files=10, max_file_bytes=10, max_total_bytes=100),
    )
    (worktree / "big.txt").write_text("x" * 11)
    assert_refused(run(editor, command="view", path="/repo/big.txt"), "11 bytes", "10")


def test_view_output_is_capped(worktree: Path, editor: WorktreeEditor) -> None:
    (worktree / "long.txt").write_text("".join(f"line {i}\n" for i in range(5000)))
    outcome = run(editor, command="view", path="/repo/long.txt")
    assert not outcome.is_error
    assert "truncated" in outcome.content and "view_range" in outcome.content
    assert len(outcome.content) <= VIEW_MAX_CHARS + 200


def test_error_output_is_capped(worktree: Path) -> None:
    limits = EditorLimits(
        max_files=10, max_file_bytes=10, max_total_bytes=10, max_view_chars=50
    )
    editor = WorktreeEditor(worktree, protected=(), limits=limits)
    outcome = run(editor, command="view", path="/repo/" + "a/" * 100 + "x.py")
    assert outcome.is_error
    assert len(outcome.content) <= 50 + 200


def test_view_directory_lists_two_levels_in_order_and_hides_metadata(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "src" / "deep" / "deeper").mkdir(parents=True)
    (worktree / "src" / "deep" / "deeper" / "hidden.py").write_text("")
    (worktree / "src" / "bad\nname.py").write_text("")
    (worktree / "src" / "line sep.py").write_text("")
    (worktree / "src" / "para sep.py").write_text("")
    (worktree / "src" / ".GIT").mkdir()
    # '-' sorts before '/': a global sort would put src-old.py above src/.
    (worktree / "src-old.py").write_text("")
    outcome = run(editor, command="view", path="/repo")
    assert not outcome.is_error
    header, *listed = outcome.content.splitlines()
    assert header.startswith(f"Files and directories up to {LIST_DEPTH} levels deep")
    # Depth first, each level sorted by name; git metadata, secrets (and what
    # is inside a secret directory), __pycache__, unprintable names hidden.
    assert listed == [
        "/repo/README.md",
        "/repo/alias.py -> symlink, not followed",
        "/repo/config/",
        "/repo/deploy/",
        "/repo/link -> symlink, not followed",
        "/repo/pkg/",
        "/repo/pkg/__init__.py",
        "/repo/src/",
        "/repo/src/core.py",
        "/repo/src/deep/",
        "/repo/src-old.py",
        "/repo/tests/",
        "/repo/tests/test_core.py",
    ]


def test_view_subdirectory_lists_its_entries(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="view", path="/repo/src/")
    assert not outcome.is_error
    assert outcome.content.splitlines()[1:] == ["/repo/src/core.py"]


def test_view_directory_listing_is_bounded(
    worktree: Path, editor: WorktreeEditor
) -> None:
    many = worktree / "many"
    many.mkdir()
    for i in range(LIST_MAX_ENTRIES + 20):
        (many / f"m{i:04}.py").write_text("")
    outcome = run(editor, command="view", path="/repo/many")
    lines = outcome.content.splitlines()
    assert len(lines) == 1 + LIST_MAX_ENTRIES + 1
    assert "more entries not shown" in lines[-1]
    from_root = run(editor, command="view", path="/repo").content.splitlines()
    assert len(from_root) == 1 + LIST_MAX_ENTRIES + 1
    assert "/repo/many/" in from_root
    assert "more entries not shown" in from_root[-1]


def test_view_range_on_directory_is_an_error(editor: WorktreeEditor) -> None:
    outcome = run(editor, command="view", path="/repo/src", view_range=[1, 2])
    assert_refused(outcome, "directory")


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------


def test_create_new_file_in_new_directories(
    worktree: Path, editor: WorktreeEditor
) -> None:
    outcome = run(
        editor, command="create", path="/repo/src/fast/impl.py", file_text="x = 1\n"
    )
    assert outcome == ToolOutcome(
        "Created /repo/src/fast/impl.py (6 bytes).", is_error=False
    )
    target = worktree / "src" / "fast" / "impl.py"
    assert target.read_text() == "x = 1\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644
    assert os.listdir(target.parent) == ["impl.py"]  # no temporary file left
    assert dict(editor.written) == {"src/fast/impl.py": 6}


def test_create_overwrites_and_written_accumulates(
    worktree: Path, editor: WorktreeEditor
) -> None:
    first = run(editor, command="create", path="/repo/src/core.py", file_text="a\n")
    assert first == ToolOutcome(
        "Overwrote /repo/src/core.py (2 bytes).", is_error=False
    )
    run(editor, command="create", path="/repo/src/core.py", file_text="abc\n")
    assert (worktree / "src" / "core.py").read_text() == "abc\n"
    assert dict(editor.written) == {"src/core.py": 6}


def test_create_records_nfc_path(worktree: Path, editor: WorktreeEditor) -> None:
    outcome = run(editor, command="create", path="/repo/cafe\u0301.py", file_text="")
    assert not outcome.is_error
    assert dict(editor.written) == {"café.py": 0}
    assert "café.py" in os.listdir(worktree) or "cafe\u0301.py" in os.listdir(worktree)


def test_create_on_directory_is_an_error(editor: WorktreeEditor) -> None:
    assert_refused(
        run(editor, command="create", path="/repo/src", file_text="x"), "directory"
    )


@pytest.mark.parametrize(
    ("text", "needle"), [("a\x00b", "NUL"), ("bad \ud800 text", "Unicode")]
)
def test_create_refuses_unwritable_text(
    worktree: Path, editor: WorktreeEditor, text: str, needle: str
) -> None:
    assert_refused(
        run(editor, command="create", path="/repo/n.py", file_text=text), needle
    )
    assert not (worktree / "n.py").exists()
    assert dict(editor.written) == {}


def test_create_over_the_file_limit_is_refused(
    worktree: Path, editor: WorktreeEditor
) -> None:
    outcome = run(
        editor, command="create", path="/repo/big.py", file_text="x" * (300 * KIB)
    )
    assert_refused(outcome, str(300 * KIB), str(256 * KIB))
    assert not (worktree / "big.py").exists()
    assert dict(editor.written) == {}


def test_create_at_exactly_the_file_limit_is_allowed(editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="create", path="/repo/big.py", file_text="x" * (256 * KIB)
    )
    assert not outcome.is_error


def test_eleventh_file_is_refused(worktree: Path, editor: WorktreeEditor) -> None:
    for i in range(10):
        assert not run(
            editor, command="create", path=f"/repo/m{i}.py", file_text="x"
        ).is_error
    outcome = run(editor, command="create", path="/repo/m10.py", file_text="x")
    assert_refused(outcome, "10 files")
    assert not (worktree / "m10.py").exists()
    again = run(editor, command="create", path="/repo/m0.py", file_text="y")
    assert not again.is_error
    assert len(editor.written) == 10


def test_total_write_budget_is_enforced(worktree: Path) -> None:
    limits = EditorLimits(max_files=10, max_file_bytes=100, max_total_bytes=150)
    editor = WorktreeEditor(worktree, protected=(), limits=limits)
    assert not run(
        editor, command="create", path="/repo/a.py", file_text="a" * 100
    ).is_error
    outcome = run(editor, command="create", path="/repo/b.py", file_text="b" * 60)
    assert_refused(outcome, "150")
    assert not (worktree / "b.py").exists()
    assert not run(
        editor, command="create", path="/repo/b.py", file_text="b" * 50
    ).is_error
    assert dict(editor.written) == {"a.py": 100, "b.py": 50}


def test_written_is_a_read_only_snapshot(editor: WorktreeEditor) -> None:
    run(editor, command="create", path="/repo/a.py", file_text="a")
    written = editor.written
    with pytest.raises(TypeError):
        written["b.py"] = 1  # type: ignore[index]
    run(editor, command="create", path="/repo/b.py", file_text="b")
    assert dict(written) == {"a.py": 1}
    assert dict(editor.written) == {"a.py": 1, "b.py": 1}


class _FullDisk:
    """A write handle on a full disk: every ``write`` fails with ENOSPC."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def __enter__(self) -> _FullDisk:
        return self

    def __exit__(self, *exc_info: object) -> None:
        os.close(self._descriptor)

    def fileno(self) -> int:
        return self._descriptor

    def write(self, data: bytes) -> int:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))


def test_failed_write_keeps_the_old_content_and_records_nothing(
    worktree: Path,
    tmp_path: Path,
    editor: WorktreeEditor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_fdopen = os.fdopen

    def fdopen(descriptor: int, mode: str = "r") -> object:
        return _FullDisk(descriptor) if "w" in mode else real_fdopen(descriptor, mode)

    before = snapshot(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(os, "fdopen", fdopen)
        failed = run(
            editor, command="create", path="/repo/src/core.py", file_text="new\n"
        )
    assert_refused(failed, "/repo/src/core.py", os.strerror(errno.ENOSPC))
    assert str(tmp_path) not in failed.content
    assert snapshot(tmp_path) == before  # old content kept, no temporary file
    # Nothing changed, so nothing is recorded: 0 would read as a deletion, and
    # the replace is atomic, so no partial write can escape unrecorded_write.
    assert dict(editor.written) == {}
    retried = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str="    out = []\n",
        new_str="    out: list[int] = []\n",
    )
    assert not retried.is_error, retried.content
    assert os.listdir(worktree / "src") == ["core.py"]


def test_a_failed_replace_records_nothing_and_keeps_the_file_slot(
    worktree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limits = EditorLimits(max_files=1, max_file_bytes=KIB, max_total_bytes=KIB)
    editor = WorktreeEditor(worktree, protected=(), limits=limits)

    def full_disk(source: object, target: object) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", full_disk)
        failed = run(editor, command="create", path="/repo/src/new.py", file_text="x\n")
    assert_refused(failed, os.strerror(errno.ENOSPC))
    assert not (worktree / "src" / "new.py").exists()
    assert [p.name for p in (worktree / "src").iterdir()] == ["core.py"]
    assert dict(editor.written) == {}
    other = run(editor, command="create", path="/repo/src/other.py", file_text="y\n")
    assert not other.is_error, other.content  # the failed write used no file slot
    assert dict(editor.written) == {"src/other.py": 2}


def test_root_given_through_a_symlink_is_resolved(
    worktree: Path, tmp_path: Path
) -> None:
    alias = tmp_path / "alias-root"
    alias.symlink_to(worktree, target_is_directory=True)
    editor = WorktreeEditor(alias, protected=())
    assert not run(
        editor, command="create", path="/repo/n.py", file_text="n\n"
    ).is_error
    assert (worktree / "n.py").read_text() == "n\n"


def test_root_must_be_an_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        WorktreeEditor(tmp_path / "missing", protected=())
    (tmp_path / "file").write_text("")
    with pytest.raises(ValueError, match="not a directory"):
        WorktreeEditor(tmp_path / "file", protected=())


# --------------------------------------------------------------------------
# str_replace
# --------------------------------------------------------------------------


def test_str_replace_exactly_once(worktree: Path, editor: WorktreeEditor) -> None:
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str="        out.append(x)\n",
        new_str="        if x not in out:\n            out.append(x)\n",
    )
    assert not outcome.is_error
    expected = CORE.replace(
        "        out.append(x)\n",
        "        if x not in out:\n            out.append(x)\n",
    )
    assert (worktree / "src" / "core.py").read_text() == expected
    assert outcome.content.startswith("Edited /repo/src/core.py.")
    assert "     4\t        if x not in out:" in outcome.content
    assert "     5\t            out.append(x)" in outcome.content
    assert dict(editor.written) == {"src/core.py": len(expected.encode())}


def test_str_replace_new_str_defaults_to_deletion(
    worktree: Path, editor: WorktreeEditor
) -> None:
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str="    out = []\n",
    )
    assert not outcome.is_error
    assert "out = []" not in (worktree / "src" / "core.py").read_text()


def test_str_replace_can_empty_a_file(worktree: Path, editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="str_replace", path="/repo/README.md", old_str="# demo\n"
    )
    assert outcome == ToolOutcome(
        "Edited /repo/README.md; it is now empty.", is_error=False
    )
    assert (worktree / "README.md").read_text() == ""
    assert dict(editor.written) == {"README.md": 0}


@pytest.mark.parametrize(
    ("old_str", "needle"),
    [("missing text", "no match"), ("x", "times"), ("", "empty")],
)
def test_str_replace_needs_exactly_one_match(
    worktree: Path, editor: WorktreeEditor, old_str: str, needle: str
) -> None:
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str=old_str,
        new_str="y",
    )
    assert_refused(outcome, needle)
    assert (worktree / "src" / "core.py").read_text() == CORE
    assert dict(editor.written) == {}


def test_str_replace_counts_overlapping_matches(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "aaa.py").write_text("aaa\n")
    outcome = run(
        editor, command="str_replace", path="/repo/aaa.py", old_str="aa", new_str="b"
    )
    assert_refused(outcome, "2 times")


def test_str_replace_reports_the_match_count(editor: WorktreeEditor) -> None:
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str="out",
        new_str="o",
    )
    assert_refused(outcome, "3 times")


def test_str_replace_on_missing_file_is_an_error(editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="str_replace", path="/repo/nope.py", old_str="a", new_str="b"
    )
    assert_refused(outcome, "does not exist")


@pytest.mark.parametrize("command", ["str_replace", "insert"])
def test_editing_a_directory_is_an_error(editor: WorktreeEditor, command: str) -> None:
    if command == "str_replace":
        outcome = run(
            editor, command=command, path="/repo/src", old_str="a", new_str="b"
        )
    else:
        outcome = run(
            editor, command=command, path="/repo/src", insert_line=0, insert_text="x"
        )
    assert_refused(outcome, "/repo/src is a directory")


def test_str_replace_on_non_utf8_file_is_an_error(
    worktree: Path, editor: WorktreeEditor
) -> None:
    (worktree / "latin1.py").write_bytes(b"x = '\xe9'\n")
    outcome = run(
        editor, command="str_replace", path="/repo/latin1.py", old_str="x", new_str="y"
    )
    assert_refused(outcome, "UTF-8")


def test_str_replace_result_over_the_file_limit_is_refused(worktree: Path) -> None:
    limits = EditorLimits(max_files=10, max_file_bytes=10, max_total_bytes=100)
    editor = WorktreeEditor(worktree, protected=(), limits=limits)
    (worktree / "small.py").write_text("x = 1\n")
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/small.py",
        old_str="1",
        new_str="1234567",
    )
    assert_refused(outcome, "12 bytes")
    assert (worktree / "small.py").read_text() == "x = 1\n"


def test_str_replace_keeps_the_file_mode(
    worktree: Path, editor: WorktreeEditor
) -> None:
    script = worktree / "tool.py"
    script.write_text("print(1)\n")
    script.chmod(0o755)
    outcome = run(
        editor, command="str_replace", path="/repo/tool.py", old_str="1", new_str="2"
    )
    assert not outcome.is_error
    assert stat.S_IMODE(script.stat().st_mode) == 0o755
    assert script.read_text() == "print(2)\n"


def test_str_replace_refuses_nul_in_new_text(
    worktree: Path, editor: WorktreeEditor
) -> None:
    outcome = run(
        editor,
        command="str_replace",
        path="/repo/src/core.py",
        old_str="out = []",
        new_str="\x00",
    )
    assert_refused(outcome, "NUL")
    assert (worktree / "src" / "core.py").read_text() == CORE


# --------------------------------------------------------------------------
# insert
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "line", "text", "expected"),
    [
        ("a\nb\n", 0, "X", "X\na\nb\n"),
        ("a\nb\n", 1, "X\n", "a\nX\nb\n"),
        ("a\nb\n", 2, "X\nY", "a\nb\nX\nY\n"),
        ("a\nb", 2, "X", "a\nb\nX\n"),
        ("", 0, "X", "X\n"),
        ("a\n", 1, "", "a\n"),
    ],
)
def test_insert_after_line(
    worktree: Path,
    editor: WorktreeEditor,
    original: str,
    line: int,
    text: str,
    expected: str,
) -> None:
    (worktree / "ins.py").write_text(original)
    outcome = run(
        editor,
        command="insert",
        path="/repo/ins.py",
        insert_line=line,
        insert_text=text,
    )
    assert not outcome.is_error, outcome.content
    assert (worktree / "ins.py").read_text() == expected
    assert outcome.content.startswith("Edited /repo/ins.py.")
    assert dict(editor.written) == {"ins.py": len(expected.encode())}


def test_insert_snippet_shows_the_new_lines(
    worktree: Path, editor: WorktreeEditor
) -> None:
    outcome = run(
        editor,
        command="insert",
        path="/repo/src/core.py",
        insert_line=1,
        insert_text='    """Doc."""',
    )
    assert '     2\t    """Doc."""' in outcome.content
    assert "     1\tdef unique(xs):" in outcome.content


@pytest.mark.parametrize("line", [-1, 6])
def test_insert_line_out_of_range_is_an_error(
    worktree: Path, editor: WorktreeEditor, line: int
) -> None:
    outcome = run(
        editor,
        command="insert",
        path="/repo/src/core.py",
        insert_line=line,
        insert_text="x",
    )
    assert_refused(outcome, "insert_line", "5 lines")
    assert (worktree / "src" / "core.py").read_text() == CORE


def test_insert_on_missing_file_is_an_error(editor: WorktreeEditor) -> None:
    outcome = run(
        editor, command="insert", path="/repo/nope.py", insert_line=0, insert_text="x"
    )
    assert_refused(outcome, "does not exist")


# --------------------------------------------------------------------------
# Limits and constants
# --------------------------------------------------------------------------


def test_limits_default_to_settings() -> None:
    config = Settings(
        EDITOR_MAX_FILES=3, EDITOR_MAX_FILE_BYTES=7, EDITOR_MAX_TOTAL_BYTES=9
    )
    assert EditorLimits.from_settings(config) == EditorLimits(
        max_files=3, max_file_bytes=7, max_total_bytes=9, max_view_chars=VIEW_MAX_CHARS
    )
    default = EditorLimits.from_settings()
    assert (default.max_files, default.max_file_bytes, default.max_total_bytes) == (
        10,
        256 * KIB,
        1024 * KIB,
    )


def test_editor_uses_settings_limits_by_default(editor: WorktreeEditor) -> None:
    assert editor.limits == EditorLimits.from_settings()


@pytest.mark.parametrize(
    "field", ["max_files", "max_file_bytes", "max_total_bytes", "max_view_chars"]
)
def test_limits_must_be_positive(field: str) -> None:
    values = {
        "max_files": 1,
        "max_file_bytes": 1,
        "max_total_bytes": 1,
        "max_view_chars": 1,
    }
    values[field] = 0
    with pytest.raises(ValueError, match=field):
        EditorLimits(**values)


def _all_outcomes(editor: WorktreeEditor) -> Iterator[ToolOutcome]:
    yield run(editor, command="view", path="/repo")
    yield run(editor, command="view", path="/repo/src/core.py")
    yield run(editor, command="create", path="/repo/n.py", file_text="n")
    yield run(
        editor, command="str_replace", path="/repo/n.py", old_str="n", new_str="m"
    )
    yield run(
        editor, command="insert", path="/repo/n.py", insert_line=1, insert_text="o"
    )


def test_successful_outcomes_never_show_the_real_root(
    editor: WorktreeEditor, tmp_path: Path
) -> None:
    listing, viewed, *edits = _all_outcomes(editor)
    for outcome in (listing, viewed, *edits):
        assert not outcome.is_error, outcome.content
        assert str(tmp_path) not in outcome.content
    for outcome in (listing, *edits):  # results that name a path name it virtually
        assert f"{VIRTUAL_ROOT}/" in outcome.content, outcome.content
