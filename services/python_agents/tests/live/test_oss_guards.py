"""Offline guards of the live OSS corpus (U24, STATUS Window 0).

Not ``live``: these run in the normal suite and spend nothing, and only the
``slow`` network tests at the end (skipped unless ``LIVE_OSS_NETWORK=1``)
reach the internet. They prove the corpus is what it claims before a
dollar is spent on it:

- the manifest (``tests/fixtures/live_oss/manifest.json``): 8 to 10 real
  libraries, each pinned to a full commit SHA of a tagged release on an
  https GitHub URL, a permissive SPDX license, its workload file, a test
  command and two hypotheses (one aimed at a profiled hot spot, one
  neutral); malformed entries are refused;
- the workloads: deterministic by construction (a seeded ``Random``, no
  clock, no network, no process or file access), each checking that the
  library it times is the checkout's;
- the clone helper (``tests/live/oss.py``), against local bare
  repositories served over ``file://`` through a policy injected only
  here: the pin is checked out on ``main``, a URL off the allowlist, a
  malformed pin, a moved tag, a HEAD off the pin, a refused protocol,
  submodules, LFS and a hung git are refused, and the user's global git
  configuration never applies;
- the benchmark commit and the repository shape ``make_repo`` gives, the
  production wiring of ``start_oss_loop`` (only the wire is a mock), and a
  whole loop on a shallow clone that preflight accepts;
- with ``LIVE_OSS_NETWORK=1``: each pinned repository cloned for real, its
  license, its workload (deterministic, 0.3 to 5 s) and its test subset,
  preflight on it, and a dress rehearsal of the whole loop in the sandbox
  with a no-op editor and no Claude.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import posixpath
import re
import subprocess
import sys
import time
import types
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import httpx2
import pytest
from e2e.conftest import (
    UNTOUCHED_REFS,
    Isolation,
    LaunchLog,
    UserRepo,
    _sandbox_problem,
    git,
)
from e2e.test_step2 import _check_repo_untouched

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import IsolationMode, Settings, settings
from autonomous_ai_agents.common.models import (
    ChangeClass,
    DeliveryKind,
    Hypothesis,
    HypothesisSource,
    Project,
)
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.protocols import EditResult, EditTask
from autonomous_ai_agents.execution.sandbox import child_env
from autonomous_ai_agents.optimization.anticheat import _spawn_problem, check_path
from autonomous_ai_agents.orchestrator.factory import build_context
from autonomous_ai_agents.orchestrator.main import Orchestrator

from .conftest import LiveRun, check_sandboxed, guardrails, restore_host_key
from .corpus import (
    ALL_MODES,
    MODE_ENV,
    CorpusRecorder,
    HypothesisSpec,
    check_loop_guards,
    mode_hypotheses,
    mode_recorder,
)
from .oss import (
    BENCH_AUTHOR,
    GITHUB_URL,
    MANIFEST,
    MAX_REPOS,
    MIN_REPOS,
    NETWORK_ENV,
    OSS_CORPUS,
    OSS_RUN_CAP_USD,
    PERMISSIVE_LICENSES,
    PRODUCTION,
    WORKLOADS_DIR,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    _no_factory,
    check_pin,
    clone_pinned,
    git_env,
    install_workload,
    parse_manifest,
    prepare_repo,
    start_oss_loop,
    verify_head,
)

LOCAL = GitPolicy(allow=re.compile(r"file:///[^\s?#]+\.git"), protocols="file")
"""Local bare repositories over file://: injected by these tests only."""
RUN_TIMEOUT_S = 120
NETWORK = pytest.mark.skipif(
    os.environ.get(NETWORK_ENV) != "1",
    reason=f"clones real repositories over the network: set {NETWORK_ENV}=1",
)
OSS_IDS = [repo.name for repo in OSS_CORPUS]
_CLEAN_GIT = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Upstream",
    "GIT_AUTHOR_EMAIL": "upstream@example.invalid",
    "GIT_COMMITTER_NAME": "Upstream",
    "GIT_COMMITTER_EMAIL": "upstream@example.invalid",
}


def _raw() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _entry(**changes: object) -> dict[str, object]:
    """The first manifest entry with ``changes`` (``None`` drops a key)."""
    repos = _raw()["repos"]
    assert isinstance(repos, list)
    entry = dict(repos[0])
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def test_manifest_lists_eight_to_ten_libraries_one_workload_each() -> None:
    assert MIN_REPOS <= len(OSS_CORPUS) <= MAX_REPOS == 10
    names = [repo.name for repo in OSS_CORPUS]
    assert len(set(names)) == len(names)
    assert {p.stem for p in WORKLOADS_DIR.glob("*.py")} == set(names)
    assert parse_manifest(_raw()) == OSS_CORPUS


@pytest.mark.parametrize("repo", OSS_CORPUS, ids=OSS_IDS)
def test_entry_is_pinned_permissive_and_complete(repo: OssRepo) -> None:
    assert GITHUB_URL.fullmatch(repo.url), repo.url
    assert re.fullmatch(r"[0-9a-f]{40}", repo.commit), repo.commit
    assert repo.license in PERMISSIVE_LICENSES
    assert repo.workload_source.is_file()
    assert repo.module_root in (repo.package, f"src/{repo.package}")
    assert [spec.aimed for spec in repo.hypotheses] == [True, False]
    assert repo.test_command[0] == "python" and repo.profile.strip()
    assert repo.workload_argv == ("python", f"benchmarks/bench_{repo.name}.py")
    # The benchmark is protected: no trial may edit what judges it.
    assert check_path(repo.bench_path) is not None
    assert not any("bench" in arg for arg in repo.test_command)
    # Its directory is sys.path[0] when it runs, ahead of the checkout: the
    # whole directory is protected, so no trial can add a copy of the
    # library (or anything else) beside it for the benchmark to import.
    folder = posixpath.dirname(repo.bench_path)
    for added in (
        f"{repo.package}.py",
        f"{repo.package}/__init__.py",
        "__init__.py",
        "helper.py",
        "data/rows.json",
    ):
        assert check_path(f"{folder}/{added}") is not None, added
    # Each hypothesis names the library files it is about, none of them a
    # file the process_spawn rule refuses outright (checked on the network).
    for files in repo.targets:
        assert files and all(f.startswith(f"{repo.module_root}/") for f in files)
        assert all(check_path(f) is None for f in files), files


def test_manifest_entries_build_efficiency_candidates(tmp_path: Path) -> None:
    repo = OSS_CORPUS[0]
    project = repo.project(tmp_path)
    assert project.test_command == repo.test_command
    built = repo.candidates(project)
    assert [h.title for h in built] == [s.title for s in repo.hypotheses]
    assert {h.change_class for h in built} == {ChangeClass.efficiency}
    assert repo.workload(project).command == repo.workload_argv
    corpus = repo.corpus
    assert (corpus.name, corpus.kind, corpus.expected) == (
        repo.name,
        "slowdown",
        "none",
    )
    assert corpus.hypotheses == repo.hypotheses


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"url": "http://github.com/a/b.git"}, "url"),
        ({"url": "git@github.com:a/b.git"}, "url"),
        ({"url": "ssh://git@github.com/a/b.git"}, "url"),
        ({"url": "https://github.com.evil.example/a/b.git"}, "url"),
        ({"url": "https://user@github.com/a/b.git"}, "url"),
        ({"url": "https://github.com/a/b/c.git"}, "url"),
        ({"url": "https://github.com/a/b.git?x=1"}, "url"),
        ({"url": "https://github.com/a/b.git\n"}, "url"),
        ({"url": "https://github.com/a/..git"}, "url"),
        ({"url": "https://github.com/a/b"}, "url"),
        ({"commit": "3b4cd50"}, "commit"),
        ({"commit": "3B4CD509820E4C45CD2AABA833AA585EA6308B94"}, "commit"),
        ({"commit": "z" * 40}, "commit"),
        ({"commit": "a" * 64}, "commit"),
        ({"tag": "../v1"}, "tag"),
        ({"tag": "-v1"}, "tag"),
        ({"tag": "v1.lock"}, "tag"),
        ({"tag": "refs/tags/v1"}, "tag"),
        ({"license": "GPL-3.0-only"}, "license"),
        ({"license": "mit"}, "license"),
        ({"name": "no_such_workload"}, "workload"),
        ({"name": "Bad-Name"}, "name"),
        ({"module_root": "../tabulate"}, "module_root"),
        ({"module_root": "lib/tabulate"}, "module_root"),
        ({"package": "tab ulate"}, "package"),
        ({"released": "2026-13-01"}, "released"),
        ({"test_command": []}, "test_command"),
        ({"test_command": "python -m pytest"}, "test_command"),
        ({"test_command": ["pytest", "test"]}, "test_command"),
        ({"test_command": ["python", ""]}, "test_command"),
        ({"test_command": ["python", "a\x00b"]}, "test_command"),
        ({"hypotheses": []}, "hypotheses"),
        ({"profile": " "}, "profile"),
        ({"license_file": "../LICENSE"}, "license_file"),
        ({"extra": 1}, "keys"),
        ({"profile": None}, "keys"),
    ],
)
def test_parse_manifest_refuses_a_malformed_entry(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_manifest({"repos": [_entry(**changes)]})


def _hyp(
    title: str, aimed: object, files: object = ("tabulate/__init__.py",)
) -> dict[str, object]:
    listed = list(files) if isinstance(files, tuple) else files
    return {"title": title, "aimed": aimed, "rationale": "a reason", "files": listed}


@pytest.mark.parametrize(
    ("hypotheses", "message"),
    [
        ([_hyp("a", True)], "exactly two"),
        ([_hyp("a", True), _hyp("b", True)], "one aimed"),
        ([_hyp("a", False), _hyp("b", False)], "one aimed"),
        ([_hyp("a", True), _hyp("a", False)], "distinct"),
        ([_hyp("a", "yes"), _hyp("b", False)], "aimed"),
        ([_hyp("Bad Title", True), _hyp("b", False)], "title"),
        ([{"title": "a", "aimed": True}, _hyp("b", False)], "keys"),
        ([_hyp("a", True), {**_hyp("b", False), "rationale": ""}], "rationale"),
        ([_hyp("a", True, ()), _hyp("b", False)], "files"),
        ([_hyp("a", True, "tabulate/x.py"), _hyp("b", False)], "files"),
        ([_hyp("a", True, ("tabulate/x.py",) * 5), _hyp("b", False)], "files"),
        ([_hyp("a", True, (1,)), _hyp("b", False)], "files"),
        ([_hyp("a", True, ("tabulate/../x.py",)), _hyp("b", False)], "files"),
        ([_hyp("a", True, ("/tabulate/x.py",)), _hyp("b", False)], "files"),
        ([_hyp("a", True, ("other/x.py",)), _hyp("b", False)], "files"),
        ([_hyp("a", True, ("tabulate/x.txt",)), _hyp("b", False)], "files"),
        (
            [_hyp("a", True, ("tabulate/x.py", "tabulate/x.py")), _hyp("b", False)],
            "files",
        ),
        ([_hyp("a", True, ("tabulate//x.py",)), _hyp("b", False)], "files"),
    ],
)
def test_parse_manifest_refuses_malformed_hypotheses(
    hypotheses: list[object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_manifest({"repos": [_entry(hypotheses=hypotheses)]})


def test_parse_manifest_refuses_a_bad_shape_too_many_or_duplicates() -> None:
    shapes: tuple[object, ...] = (
        {},
        {"repos": {}},
        {"repos": [1]},
        [],
        {"repos": [], "x": 1},
    )
    for data in shapes:
        with pytest.raises(ValueError, match="manifest"):
            parse_manifest(data)
    entry = _entry()
    with pytest.raises(ValueError, match="at most 10"):
        parse_manifest({"repos": [entry] * 11})
    with pytest.raises(ValueError, match="duplicate"):
        parse_manifest({"repos": [entry, entry]})
    with pytest.raises(ValueError, match="workload"):
        parse_manifest({"repos": [entry]}, workloads=WORKLOADS_DIR / "missing")


# ---------------------------------------------------------------------------
# The workloads: deterministic by construction
# ---------------------------------------------------------------------------

ALLOWED_IMPORTS = frozenset({"__future__", "hashlib", "json", "pathlib", "random"})


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("repo", OSS_CORPUS, ids=OSS_IDS)
def test_workload_is_deterministic_and_times_the_checkout(repo: OssRepo) -> None:
    source = repo.workload_source.read_text(encoding="utf-8")
    tree = ast.parse(source)
    # Only the library and a few pure stdlib modules: no clock, network,
    # process, environment or file access beyond its own path.
    assert _imports(tree) <= ALLOWED_IMPORTS | {repo.package}, _imports(tree)
    assert repo.package in _imports(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "random":
                # Only seeded generators: random.Random(<int literal>).
                assert node.func.attr == "Random", ast.unparse(node)
                (seed,) = node.args
                assert isinstance(seed, ast.Constant) and isinstance(seed.value, int)
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "input", "exec", "eval", "__import__"}
    # The library it times is exactly the checkout's package, never a copy
    # beside the script, at the root or installed (see the test below).
    parts = [*repo.module_root.split("/"), "__init__.py"]
    expected = "PACKAGE_INIT = ROOT / " + " / ".join(f'"{p}"' for p in parts)
    assert expected in source, expected
    assert ".__file__).resolve() != PACKAGE_INIT:" in source
    assert "is_relative_to" not in source and "_checked()" in source
    assert 'if __name__ == "__main__":' in source


def _load_workload(
    repo: OssRepo, root: Path, imported_from: Path, monkeypatch: pytest.MonkeyPatch
) -> types.ModuleType:
    """``repo``'s workload, as committed under ``root``, with its library
    replaced by a stand-in whose ``__file__`` is ``imported_from``."""
    script = root / repo.bench_path
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_bytes(repo.workload_source.read_bytes())
    library = types.ModuleType(repo.package)
    library.__file__ = str(imported_from)
    library.__dict__["__getattr__"] = lambda name: object()  # from x import y
    monkeypatch.setitem(sys.modules, repo.package, library)
    spec = importlib.util.spec_from_file_location(f"bench_{repo.name}", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("repo", OSS_CORPUS, ids=OSS_IDS)
def test_workload_refuses_a_library_that_is_not_the_checkouts_package(
    repo: OssRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copy of the library beside the script (``sys.path[0]``), a module
    at the root (ahead of ``src/`` on the engine's ``PYTHONPATH``) or an
    installed copy is refused: the timed code is the code the tests judge."""
    root = Path(os.path.realpath(tmp_path)) / "user"
    package_init = root / repo.module_root / "__init__.py"
    folder = (root / repo.bench_path).parent
    for shadow in (
        folder / f"{repo.package}.py",
        folder / repo.package / "__init__.py",
        root / f"{repo.package}.py",
        root / "build" / "lib" / repo.module_root / "__init__.py",
        Path(sys.prefix) / "site-packages" / repo.package / "__init__.py",
    ):
        module = _load_workload(repo, root, shadow, monkeypatch)
        with pytest.raises(SystemExit, match=f"{repo.package} imported from"):
            module._checked()
    module = _load_workload(repo, root, package_init, monkeypatch)
    assert module.PACKAGE_INIT == package_init
    module._checked()  # the checkout's own package: accepted


# ---------------------------------------------------------------------------
# The clone helper, on local bare repositories over file://
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=_CLEAN_GIT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


Upstream = Callable[..., tuple[str, str]]


@pytest.fixture
def upstream(tmp_path: Path) -> Upstream:
    """``make(files, gitlink=False, annotated=False, links={})``: a bare
    upstream repository with one commit tagged ``v1`` (``links`` maps a path
    to the target of a symlink committed there); ``(file:// url, commit)``."""
    count = 0

    def make(
        files: Mapping[str, str] | None = None,
        *,
        gitlink: bool = False,
        annotated: bool = False,
        links: Mapping[str, str] | None = None,
    ) -> tuple[str, str]:
        nonlocal count
        count += 1
        work = tmp_path / f"upstream-{count}"
        tree = dict(
            files
            or {
                "pkg/__init__.py": "VALUE = 1\n",
                "tests/test_pkg.py": "import pkg\n",
                "LICENSE": "Permission is hereby granted, free of charge\n",
            }
        )
        for rel, text in tree.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text, encoding="utf-8")
        for rel, target in (links or {}).items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).symlink_to(target)
        _git(tmp_path, "init", "-q", "-b", "trunk", str(work))
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", "first")
        if gitlink:
            sha = _git(work, "rev-parse", "HEAD")
            _git(work, "update-index", "--add", "--cacheinfo", f"160000,{sha},vendor")
            _git(work, "commit", "-q", "-m", "submodule")
        _git(work, "commit", "-q", "--allow-empty", "-m", "release")
        commit = _git(work, "rev-parse", "HEAD")
        _git(work, *(["tag", "-a", "-m", "v1", "v1"] if annotated else ["tag", "v1"]))
        bare = tmp_path / f"upstream-{count}.git"
        _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
        return f"file://{bare}", commit

    return make


def _dest(tmp_path: Path) -> Path:
    return Path(os.path.realpath(tmp_path)) / "user"


def _beside(dest: Path) -> list[str]:
    """What a clone left next to ``dest`` (the upstreams aside)."""
    return sorted(
        p.name for p in dest.parent.iterdir() if not p.name.startswith("upstream-")
    )


@pytest.mark.parametrize("annotated", [False, True], ids=["light", "annotated"])
def test_clone_checks_out_the_pin_on_main_shallow_without_a_remote(
    upstream: Upstream, tmp_path: Path, annotated: bool
) -> None:
    url, commit = upstream(annotated=annotated)
    dest = _dest(tmp_path)
    assert clone_pinned(url, "v1", commit, dest, policy=LOCAL) == commit
    assert git(dest, "rev-parse", "HEAD") == commit
    assert git(dest, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(dest, "remote") == ""  # nothing to push to
    assert git(dest, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
    assert (dest / ".git" / "shallow").is_file()  # depth 1, but not partial
    config = (dest / ".git" / "config").read_text(encoding="utf-8").casefold()
    assert "promisor" not in config and "partialclone" not in config
    assert not (dest / ".git" / "FETCH_HEAD").exists()
    hooks = dest / ".git" / "hooks"
    assert not [p for p in hooks.glob("*") if not p.name.endswith(".sample")]
    assert git(dest, "status", "--porcelain") == ""
    assert _beside(dest) == ["user"]  # no scratch git home left beside it


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/x.git",
        "http://github.com/a/b.git",
        "git@github.com:a/b.git",
        "git://github.com/a/b.git",
        "https://github.com.evil.example/a/b.git",
        "https://token@github.com/a/b.git",
        "https://github.com/a/b.git\n",
        "-uhttps://github.com/a/b.git",
    ],
)
def test_clone_refuses_a_url_off_the_allowlist_before_git_runs(
    url: str, tmp_path: Path
) -> None:
    dest = _dest(tmp_path)
    with pytest.raises(CloneRefusedError, match="allowlist"):
        clone_pinned(url, "v1", "a" * 40, dest)
    assert not dest.exists()


@pytest.mark.parametrize(
    ("tag", "commit", "message"),
    [
        ("v1", "abc123", "40-hex"),
        ("v1", "A" * 40, "40-hex"),
        ("v1", "g" * 40, "40-hex"),
        ("v1", "a" * 64, "40-hex"),
        ("v1..2", "a" * 40, "tag"),
        ("-v1", "a" * 40, "tag"),
        ("v1.lock", "a" * 40, "tag"),
        ("a/b", "a" * 40, "tag"),
        ("v 1", "a" * 40, "tag"),
    ],
)
def test_clone_refuses_a_malformed_pin(
    tag: str, commit: str, message: str, tmp_path: Path
) -> None:
    with pytest.raises(CloneRefusedError, match=message):
        check_pin("https://github.com/a/b.git", tag, commit, PRODUCTION)
    with pytest.raises(CloneRefusedError, match=message):
        clone_pinned("https://github.com/a/b.git", tag, commit, _dest(tmp_path))


def test_clone_refuses_a_tag_that_moved_off_the_pin(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    pinned = "0" * 40 if commit != "0" * 40 else "1" * 40
    dest = _dest(tmp_path)
    with pytest.raises(
        CloneRefusedError, match=f"v1 is {commit}, not the pinned {pinned}"
    ):
        clone_pinned(url, "v1", pinned, dest, policy=LOCAL)
    assert not dest.exists()  # nothing half-made is left behind
    assert _beside(dest) == []  # nor a scratch git home beside it


def test_verify_head_refuses_a_checkout_off_the_pin(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    dest = _dest(tmp_path)
    clone_pinned(url, "v1", commit, dest, policy=LOCAL)
    verify_head(dest, commit, policy=LOCAL)  # the pin: accepted
    (dest / "pkg" / "__init__.py").write_text("VALUE = 2\n", encoding="utf-8")
    git(dest, "commit", "-q", "-am", "drift")
    with pytest.raises(CloneRefusedError, match="HEAD"):
        verify_head(dest, commit, policy=LOCAL)


def test_clone_refuses_a_missing_tag_and_an_existing_destination(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    dest = _dest(tmp_path)
    with pytest.raises(CloneRefusedError, match="git fetch failed"):
        clone_pinned(url, "v9", commit, dest, policy=LOCAL)
    assert not dest.exists() and _beside(dest) == []
    dest.mkdir()
    with pytest.raises(CloneRefusedError, match="exists"):
        clone_pinned(url, "v1", commit, dest, policy=LOCAL)
    with pytest.raises(CloneRefusedError, match="absolute"):
        clone_pinned(url, "v1", commit, Path("relative/user"), policy=LOCAL)
    with pytest.raises(CloneRefusedError, match="no directory"):
        clone_pinned(url, "v1", commit, dest / "a" / "b", policy=LOCAL)


def test_git_itself_refuses_a_protocol_the_policy_does_not_allow(
    upstream: Upstream, tmp_path: Path
) -> None:
    """Defence in depth: an allowlist that lets file:// through still meets
    ``GIT_ALLOW_PROTOCOL=https`` in git."""
    url, commit = upstream()
    permissive = GitPolicy(allow=LOCAL.allow)  # protocols stay "https"
    with pytest.raises(CloneRefusedError, match="git fetch failed"):
        clone_pinned(url, "v1", commit, _dest(tmp_path), policy=permissive)


def test_clone_ignores_the_users_git_configuration(
    upstream: Upstream, tmp_path: Path
) -> None:
    """A global or system config that rewrites the URL, adds hooks or LFS
    filters never applies: the scratch environment drops it."""
    url, commit = upstream()
    config = tmp_path / "hostile.gitconfig"
    config.write_text(
        f'[url "file:///nonexistent/"]\n\tinsteadOf = {url}\n'
        f"[core]\n\thooksPath = {tmp_path}\n"
        '[filter "lfs"]\n\tsmudge = false\n\trequired = true\n',
        encoding="utf-8",
    )
    host = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": str(config),
        "GIT_CONFIG_SYSTEM": str(config),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "url.file:///nonexistent/.insteadOf",
        "GIT_CONFIG_VALUE_0": url,
        "GIT_DIR": str(tmp_path / "elsewhere"),
    }
    dest = _dest(tmp_path)
    assert clone_pinned(url, "v1", commit, dest, policy=LOCAL, environ=host) == commit


def test_git_env_is_a_scratch_environment(tmp_path: Path) -> None:
    host = {
        "PATH": "/usr/bin:/bin",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "NO_PROXY": "localhost",
        "GIT_SSL_CAINFO": "/etc/ca.pem",
        "SSL_CERT_FILE": "/etc/ca.pem",
        "ANTHROPIC_API_KEY": "sk-not-passed",
        "GITHUB_TOKEN": "ghp-not-passed",
        "GIT_CONFIG_COUNT": "3",
        "GIT_ASKPASS": "/bin/askpass",
        "LD_PRELOAD": "/tmp/x.so",
    }
    env = git_env(tmp_path, PRODUCTION, host)
    for name in ("HTTPS_PROXY", "NO_PROXY", "GIT_SSL_CAINFO", "SSL_CERT_FILE", "PATH"):
        assert env[name] == host[name]
    for name in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "GIT_CONFIG_COUNT", "LD_PRELOAD"):
        assert name not in env
    assert env["GIT_ASKPASS"] == ""
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["HOME"] == str(tmp_path)
    assert env["GIT_AUTHOR_NAME"] == env["GIT_COMMITTER_NAME"] == BENCH_AUTHOR[0]


def test_a_hung_git_is_refused_at_the_timeout(tmp_path: Path) -> None:
    hung = tmp_path / "git"
    hung.write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
    hung.chmod(0o755)
    policy = GitPolicy(
        allow=LOCAL.allow, protocols="file", timeout_s=0.5, executable=str(hung)
    )
    start = time.monotonic()
    with pytest.raises(CloneRefusedError, match="timed out"):
        clone_pinned("file:///x.git", "v1", "a" * 40, _dest(tmp_path), policy=policy)
    assert time.monotonic() - start < 10


@pytest.mark.parametrize(
    ("files", "gitlink", "message"),
    [
        ({"a.py": "x = 1\n", ".gitmodules": "[submodule]\n"}, False, "submodule"),
        ({"a.py": "x = 1\n"}, True, "submodule"),
        ({"a.py": "x = 1\n", ".lfsconfig": "[lfs]\n"}, False, "LFS"),
        (
            {"a.py": "x = 1\n", "d/.gitattributes": "*.bin filter=lfs diff=lfs\n"},
            False,
            "LFS",
        ),
        (
            {"a.py": "x = 1\n", "benchmarks": "a file, not a directory\n"},
            False,
            "benchmarks",
        ),
    ],
)
def test_prepare_refuses_submodules_lfs_and_a_bench_clash(
    upstream: Upstream,
    tmp_path: Path,
    files: dict[str, str],
    gitlink: bool,
    message: str,
) -> None:
    url, commit = upstream(files, gitlink=gitlink)
    dest = _dest(tmp_path)
    with pytest.raises(CloneRefusedError, match=message):
        prepare_repo(_local_repo(url, commit), dest, policy=LOCAL)
    assert not dest.exists() and _beside(dest) == []


@pytest.mark.parametrize(
    "target",
    ["/nonexistent/attributes", "HOST", "../outside-attributes", "pkg"],
    ids=["dangling", "host-file", "relative-out", "directory"],
)
def test_prepare_refuses_a_linked_attributes_file_without_reading_it(
    upstream: Upstream, tmp_path: Path, target: str
) -> None:
    """A ``.gitattributes`` the pin commits as a symlink is refused as one:
    the LFS check reads blobs from the object store, never the checkout, so
    a link to a host file (which says ``filter=lfs`` here) is never read."""
    host = tmp_path / "host-attributes"
    host.write_text("* filter=lfs\n", encoding="utf-8")
    (tmp_path / "outside-attributes").write_text("* filter=lfs\n", encoding="utf-8")
    link = str(host) if target == "HOST" else target
    url, commit = upstream(
        {"pkg/__init__.py": "VALUE = 1\n"}, links={"sub/.gitattributes": link}
    )
    dest = _dest(tmp_path)
    with pytest.raises(CloneRefusedError) as refused:
        prepare_repo(_local_repo(url, commit), dest, policy=LOCAL)
    assert "sub/.gitattributes: not a regular file (mode 120000)" in str(refused.value)
    assert "LFS" not in str(refused.value)
    assert not dest.exists()


def test_prepare_reads_attributes_from_the_pinned_blob_with_a_cap(
    upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attributes checked are the committed blob's: an oversized one is
    refused rather than read in part, a plain one without LFS is accepted."""
    big = "# padding\n" * 120_000 + "* filter=lfs\n"  # past the cap, LFS at the end
    url, commit = upstream({"pkg/__init__.py": "VALUE = 1\n", ".gitattributes": big})
    dest = _dest(tmp_path)
    with pytest.raises(CloneRefusedError, match=r"\.gitattributes: over 1048576 bytes"):
        prepare_repo(_local_repo(url, commit), dest, policy=LOCAL)
    assert not dest.exists()
    url, commit = upstream(
        {"pkg/__init__.py": "VALUE = 1\n", ".gitattributes": "*.py text eol=lf\n"}
    )
    assert prepare_repo(_local_repo(url, commit), dest, policy=LOCAL).path == dest


def test_no_hook_runs_while_the_benchmark_is_committed(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    dest = _dest(tmp_path)
    clone_pinned(url, "v1", commit, dest, policy=LOCAL)
    marker = tmp_path / "hook-ran"
    for name in ("pre-commit", "post-commit", "reference-transaction"):
        hook = dest / ".git" / "hooks" / name
        hook.write_text(f"#!/bin/sh\necho {name} >> {marker}\n", encoding="utf-8")
        hook.chmod(0o755)
    install_workload(
        dest, OSS_CORPUS[0].workload_source, "benchmarks/bench_x.py", policy=LOCAL
    )
    assert not marker.exists()


def test_install_refuses_a_bench_link_out_of_the_tree(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    dest = _dest(tmp_path)
    clone_pinned(url, "v1", commit, dest, policy=LOCAL)
    outside = tmp_path / "outside"
    outside.mkdir()
    (dest / "benchmarks").symlink_to(outside)
    with pytest.raises(CloneRefusedError, match="benchmarks"):
        install_workload(
            dest, OSS_CORPUS[0].workload_source, "benchmarks/bench_x.py", policy=LOCAL
        )
    assert list(outside.iterdir()) == []
    (dest / "benchmarks").unlink()
    (dest / "benchmarks").mkdir()
    (dest / "benchmarks" / "bench_x.py").write_text("x\n", encoding="utf-8")
    with pytest.raises(CloneRefusedError, match="already"):
        install_workload(
            dest, OSS_CORPUS[0].workload_source, "benchmarks/bench_x.py", policy=LOCAL
        )
    with pytest.raises(CloneRefusedError, match="bench path"):
        install_workload(
            dest, OSS_CORPUS[0].workload_source, "../bench_x.py", policy=LOCAL
        )


# ---------------------------------------------------------------------------
# The benchmark commit and the repository the engine is handed
# ---------------------------------------------------------------------------


def _local_repo(url: str, commit: str, source: OssRepo | None = None) -> OssRepo:
    """A manifest entry re-pointed at a local upstream (its workload kept)."""
    base = source or OSS_CORPUS[0]
    return OssRepo(
        name=base.name,
        url=url,
        tag="v1",
        commit=commit,
        released=base.released,
        license=base.license,
        license_file="LICENSE",
        package="pkg",
        module_root="pkg",
        test_command=("python", "-m", "unittest", "discover", "-s", "tests", "-t", "."),
        hypotheses=base.hypotheses,
        targets=(("pkg/__init__.py",), ("pkg/__init__.py",)),
        profile=base.profile,
    )


def test_prepare_commits_the_benchmark_with_a_fixed_identity(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream()
    repo = _local_repo(url, commit)
    user = prepare_repo(repo, _dest(tmp_path), policy=LOCAL)
    assert isinstance(user, UserRepo) and user.path == _dest(tmp_path)
    assert _beside(user.path) == ["user"]  # no scratch git home beside it
    assert git(user.path, "rev-parse", "HEAD") == user.base != commit
    assert git(user.path, "rev-parse", "HEAD^") == commit  # on top of the pin
    assert git(user.path, "diff", "--name-only", commit, "HEAD") == repo.bench_path
    tracked = (user.path / repo.bench_path).read_bytes()
    assert tracked == repo.workload_source.read_bytes()
    assert git(user.path, "ls-files", "-s", repo.bench_path).startswith("100644 ")
    author = git(
        user.path,
        "log",
        "-1",
        "--format=%an <%ae> %ad %cn <%ce> %cd",
        "--date=iso-strict",
    )
    name, email = BENCH_AUTHOR
    assert author.startswith(f"{name} <{email}> ")
    assert git(user.path, "status", "--porcelain", "--ignored") == ""
    # The shape make_repo gives: main plus the refs no run may touch.
    refs = user.refs()
    assert set(refs) == {"refs/heads/main", *UNTOUCHED_REFS}
    assert set(refs.values()) == {user.base}
    assert user.worktrees() == [f"worktree {user.path}"]
    assert user.snapshot().head_ref == "refs/heads/main"
    # Deterministic: a second preparation gives the very same commit.
    again = prepare_repo(repo, Path(os.path.realpath(tmp_path)) / "again", policy=LOCAL)
    assert again.base == user.base


def test_prepare_survives_an_ignored_bench_directory(
    upstream: Upstream, tmp_path: Path
) -> None:
    url, commit = upstream(
        {"pkg/__init__.py": "VALUE = 1\n", ".gitignore": "benchmarks/\n*.py[co]\n"}
    )
    user = prepare_repo(_local_repo(url, commit), _dest(tmp_path), policy=LOCAL)
    assert OSS_CORPUS[0].bench_path in git(user.path, "ls-files")


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


def test_start_oss_loop_is_the_production_wiring_on_the_captured_wire(
    upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the live cases build, minus the run: only the wire is a mock
    (and the upstream is local, through the injected policy)."""
    url, commit = upstream()
    repo = _local_repo(url, commit)
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")  # as the live fixture does
    run = LiveRun("dry", OSS_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))
    loop = start_oss_loop(repo, run, root, Isolation("required", None), policy=LOCAL)
    assert loop.cap_usd == OSS_RUN_CAP_USD == 5.0
    assert loop.user.path == root / "user"
    assert loop.project.root_path == str(root / "user")
    assert loop.project.test_command == repo.test_command
    assert loop.workload.command == repo.workload_argv
    assert [h.title for h in loop.candidates] == [s.title for s in repo.hypotheses]
    assert tuple(loop.context.candidates) == loop.candidates
    assert loop.repo == repo.corpus
    assert loop.before == loop.user.snapshot()
    assert run.capture.exchanges == [] and run.records == []
    with pytest.raises(AssertionError, match="captured transport"):
        _no_factory(settings)  # build_context was handed the captured one


def test_start_oss_loop_takes_generated_candidates_instead_of_the_manifest(
    upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery suites hand the loop their own hypotheses; the manifest's
    are used only when none are given."""
    url, commit = upstream()
    repo = _local_repo(url, commit)
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", OSS_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))

    def mine(project: Project) -> tuple[Hypothesis, ...]:
        return (
            Hypothesis(
                project_id=project.id,
                source=HypothesisSource.novel,
                title="generated-idea",
                rationale="from the generator",
                change_class=ChangeClass.efficiency,
                expected_gain=0.1,
                provability=0.5,
                risk=0.1,
            ),
        )

    loop = start_oss_loop(
        repo, run, root, Isolation("required", None), policy=LOCAL, candidates=mine
    )
    assert [h.title for h in loop.candidates] == ["generated-idea"]
    assert all(h.project_id == loop.project.id for h in loop.candidates)
    assert tuple(loop.context.candidates) == loop.candidates


@pytest.mark.parametrize("mode", ALL_MODES)
def test_start_oss_loop_hands_the_engine_the_mode_the_live_module_reads(
    mode: str, upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As ``test_oss_live.py`` builds it: the recorder from
    ``$LIVE_CORPUS_MODE``, its mode into ``start_oss_loop``; under ``wired``
    no candidate is handed over and the generator is on."""
    url, commit = upstream()
    repo = _local_repo(url, commit)
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    recorder = mode_recorder("OSS corpus", {MODE_ENV: mode})
    run = LiveRun("dry", OSS_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))
    loop = start_oss_loop(
        repo, run, root, Isolation("required", None), policy=LOCAL,
        mode=recorder.mode,
    )  # fmt: skip
    assert loop.mode == recorder.mode == mode
    titles = [h.title for h in loop.candidates]
    assert titles == [s.title for s in mode_hypotheses(repo.corpus, recorder.mode)]
    assert tuple(loop.context.candidates) == loop.candidates
    assert (loop.context.generator is not None) is (mode == "wired")
    if mode == "wired":
        assert loop.candidates == ()
    source = (Path(__file__).parent / "test_oss_live.py").read_text(encoding="utf-8")
    assert 'mode_recorder("OSS corpus", os.environ)' in source
    assert "mode=recorder.mode" in source
    assert run.capture.exchanges == [] and run.records == []


def _unauthorized(request: httpx2.Request) -> httpx2.Response:
    error = {"type": "authentication_error", "message": "invalid x-api-key"}
    return httpx2.Response(401, json={"type": "error", "error": error})


def _require_sandbox() -> None:
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        required = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
        if any(os.environ.get(name) == "1" for name in required):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(f"the host cannot sandbox: {problem}")


def test_a_whole_loop_on_a_shallow_clone_offline(
    upstream: Upstream, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Loop.run`` as a live case runs it, on a depth-1 clone with the
    benchmark commit: preflight (in the sandbox) accepts it, and the run
    then fails at understand for nothing (the wire refuses every request,
    as a bad key would), the repository untouched, the breach recorded."""
    _require_sandbox()
    url, commit = upstream()
    repo = _local_repo(url, commit)
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("offline", OSS_RUN_CAP_USD, wire=httpx2.MockTransport(_unauthorized))
    isolation = Isolation("required", None)
    loop = start_oss_loop(repo, run, root, isolation, policy=LOCAL)
    recorder = CorpusRecorder("OSS corpus", {})
    with (
        pytest.raises(AssertionError) as raised,
        recorder.recording(loop.repo, run) as slot,
    ):
        slot.result = loop.run()
        check_loop_guards(loop, run, slot.result, isolation)
    assert "401 authentication_error" in str(raised.value)
    assert slot.result is not None and slot.result.status == "failed"
    assert loop.launches.phases() == {"preflight"}  # preflight passed the clone
    for launch in loop.launches.launches:
        assert launch.net_isolated and launch.fs_isolated, launch
    after = loop.user.snapshot()
    assert (after.head, after.index_sha256, after.status, after.refs) == (
        loop.before.head,
        loop.before.index_sha256,
        loop.before.status,
        loop.before.refs,
    )
    (outcome,) = recorder.outcomes
    assert (outcome.repo, outcome.status, outcome.delivered) == (
        repo.name,
        "failed",
        False,
    )
    assert outcome.cost_usd == 0 and "401 authentication_error" in outcome.guard


# ---------------------------------------------------------------------------
# The network: every pinned repository for real (LIVE_OSS_NETWORK=1 only)
# ---------------------------------------------------------------------------


def _argv(argv: tuple[str, ...]) -> list[str]:
    return [sys.executable if argv[0] == "python" else argv[0], *argv[1:]]


def _run(
    root: Path, argv: tuple[str, ...]
) -> tuple[subprocess.CompletedProcess[str], float]:
    """``argv`` in ``root`` with the engine's own child environment."""
    scratch = root.parent / f".{root.name}-run"
    home, tmpdir = scratch / "home", scratch / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmpdir.mkdir(exist_ok=True)
    env = child_env(home=home, tmpdir=tmpdir, worktree=root)
    start = time.perf_counter()
    proc = subprocess.run(
        _argv(argv),
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_S,
        check=False,
    )
    return proc, time.perf_counter() - start


@pytest.fixture
def network_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    yield root


@pytest.mark.slow
@NETWORK
@pytest.mark.parametrize("repo", OSS_CORPUS, ids=OSS_IDS)
def test_pinned_repo_clones_runs_and_passes(
    repo: OssRepo, network_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    start = time.perf_counter()
    user = prepare_repo(repo, network_root / "user")  # the production policy
    cloned = time.perf_counter() - start
    assert git(user.path, "rev-parse", "HEAD^") == repo.commit
    license_text = (user.path / repo.license_file).read_text(encoding="utf-8")
    assert PERMISSIVE_LICENSES[repo.license] in license_text, repo.license
    assert (user.path / repo.module_root / "__init__.py").is_file()
    outputs: list[str] = []
    seconds: list[float] = []
    for _ in range(2):
        proc, took = _run(user.path, repo.workload_argv)
        assert proc.returncode == 0, proc.stderr
        outputs.append(proc.stdout)
        seconds.append(took)
    assert outputs[0] == outputs[1] and outputs[0].strip(), outputs
    assert all(0.3 <= s <= 5.0 for s in seconds), seconds
    proc, tests = _run(user.path, repo.test_command)
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    mode: IsolationMode = (
        "required" if _sandbox_problem(sys.platform) is None else "off"
    )
    project = repo.project(user.path)
    report = GitPreflight(network=mode, fs=mode).check(
        project, [repo.workload(project)], guardrails(project)
    )
    assert report.head_commit == user.base
    assert repo.bench_path in report.extra_protected
    # Library files the process_spawn rule rejects any edit of: none of
    # them may be a file a hypothesis is about, or every trial on it is
    # refused before it is measured (the default objective judges memory).
    spawning = sorted(
        path.relative_to(user.path).as_posix()
        for path in (user.path / repo.module_root).rglob("*.py")
        if _spawn_problem(path.read_bytes()) is not None
    )
    for files in repo.targets:
        for name in files:
            assert (user.path / name).is_file(), name
            assert name not in spawning, f"{name} is spawn-flagged"
    with capsys.disabled():
        print(
            f"\n[oss] {repo.name}: clone {cloned:.1f}s, workload "
            f"{seconds[0]:.2f}s/{seconds[1]:.2f}s, tests {tests:.1f}s, "
            f"preflight {mode}, spawn-flagged {spawning or 'none'}: "
            f"{outputs[0].strip()[:72]}"
        )


PROCESS_MODULES = ("subprocess", "multiprocessing", "concurrent", "os.fork")


def _noop_target(root: Path, module_root: str) -> str:
    """The first module of the package that starts no process: the engine's
    ``process_spawn`` rule scans the whole of each changed file, so a no-op
    edit of a file importing ``subprocess`` (pycparser's ``__init__.py``,
    for ``cpp``) is rejected before it is measured."""
    for path in sorted((root / module_root).glob("*.py")):
        if not any(
            name in path.read_text(encoding="utf-8") for name in PROCESS_MODULES
        ):
            return path.relative_to(root).as_posix()
    raise AssertionError(f"every module of {module_root} names a process module")


class _NoopEditor:
    """Appends one comment line to ``target``: a trial with a real diff and
    no behaviour change, edited without Claude."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.calls = 0

    def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult:
        self.calls += 1
        path = worktree / self.target
        text = path.read_text(encoding="utf-8") + "\n# engine dress rehearsal\n"
        path.write_text(text, encoding="utf-8")
        return EditResult(written={self.target: len(text.encode())})


def _no_transport(cfg: Settings) -> LLMTransport:
    raise AssertionError("the dress rehearsal must not build a transport")


@pytest.mark.slow
@NETWORK
@pytest.mark.parametrize("repo", OSS_CORPUS, ids=OSS_IDS)
def test_pinned_repo_dress_rehearsal_in_the_sandbox(
    repo: OssRepo,
    network_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole loop the live case runs, in the ``required`` sandbox, but
    with no Claude (the understand stub) and a no-op editor: connect,
    baseline, profile, one trial with its test suite, judges, delivery.
    What only the live run proves is the editor's own work."""
    _require_sandbox()
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    user = prepare_repo(repo, network_root / "user")
    before = user.snapshot()
    project = repo.project(user.path)
    spec = HypothesisSpec("dress-rehearsal", "a no-op comment", aimed=True)
    candidates = [spec.build(project)]
    editor = _NoopEditor(_noop_target(user.path, repo.module_root))
    launches = LaunchLog()
    context = build_context(
        project,
        candidates=candidates,
        editor=lambda **_: editor,
        transport_factory=_no_transport,
        min_trial_budget_usd=0.0,
        network="required",
        fs="required",
        run=launches,
    )
    start = time.perf_counter()
    result = Orchestrator(context=context).run(
        project, [repo.workload(project)], [], guardrails(project)
    )
    took = time.perf_counter() - start
    state = result.state
    assert result.status == "done", state["error"]
    (trial,) = state["trials"]
    assert editor.calls == 1 and trial.commit is not None, trial.error
    assert trial.measurements, "the trial was never measured"
    assert state["baseline"] is not None, "no baseline"
    committed = {spec.title}
    _check_repo_untouched(user, before, result, candidates, committed)
    check_sandboxed(launches, Isolation("required", None))
    delivery = state["delivery"]
    assert delivery is not None
    with capsys.disabled():
        print(
            f"\n[oss] {repo.name}: dress rehearsal {took:.0f}s, delivery "
            f"{delivery.kind.value}, verdict {[v.outcome.value for v in state['verdicts']]}"
        )
    assert delivery.kind in (DeliveryKind.report_only, DeliveryKind.branch)


def test_network_tests_are_gated_on_their_variable() -> None:
    """The network cases never run in normal CI: ``slow`` and skipped
    unless ``LIVE_OSS_NETWORK=1``."""
    for test in (
        test_pinned_repo_clones_runs_and_passes,
        test_pinned_repo_dress_rehearsal_in_the_sandbox,
    ):
        marks = {mark.name for mark in getattr(test, "pytestmark", [])}
        assert {"slow", "skipif", "parametrize"} <= marks, marks
    assert NETWORK.kwargs["reason"].endswith(f"{NETWORK_ENV}=1")
