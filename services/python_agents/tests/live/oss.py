"""The live OSS corpus (U24, STATUS Window 0): real libraries, cloned at run time.

The engine won 12 of 12 handed fixes on our own small corpus repositories;
this corpus asks whether it works on real code. ``tests/fixtures/live_oss``
holds the manifest of 8 to 10 small-to-medium pure-Python libraries
(permissive license, no runtime dependency outside the stdlib, importable
from a checkout, a fast test subset) and one benchmark workload per
library. Nothing upstream is vendored into this repository:

- ``OssRepo``: one manifest entry: the https GitHub URL, the release tag and
  its full 40-hex commit (verified when it was pinned), the SPDX license,
  the module root, the test argv, two efficiency hypotheses described by
  intent (one aimed at the hot spot the profile showed, one neutral), the
  library files each is about (``targets``: never one the engine's
  ``process_spawn`` rule refuses, checked on the network) and the profile
  note. ``corpus`` is the ``CorpusRepo`` the corpus helpers
  record it as (kind ``slowdown``, expected ``none``: no fix is known).
- ``clone_pinned``: a depth-1 fetch of the tag into a fresh repository (a
  full object set for that commit: never a partial clone, which preflight
  refuses), refused unless the tag is the pinned commit and ``HEAD`` is the
  pin on ``main``; argv only, a scratch git environment (no system or
  global config, no hooks, no prompt, https only), a timeout, and URLs
  matched against ``GITHUB_URL``. Submodules and LFS are refused here, as
  preflight would refuse them.
- ``install_workload`` / ``prepare_repo``: the workload committed as
  ``benchmarks/bench_<name>.py`` with a fixed identity and date, then the
  refs ``make_repo`` adds: the user's repository. The whole ``benchmarks/``
  directory is protected (``**/benchmarks/**``), not just the script: it is
  ``sys.path[0]`` when the benchmark runs, so a trial must not be able to
  add a copy of the library beside it.
- ``start_oss_loop``: the corpus ``Loop`` on it, wired as ``start_loop``.

``GitPolicy`` is the one seam: tests inject a ``file://`` allowlist to
serve local bare repositories; production code never does.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from e2e.conftest import UNTOUCHED_REFS, Isolation, LaunchLog, UserRepo

from autonomous_ai_agents.clients.transport import LLMTransport
from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.models import Hypothesis, Project, Workload
from autonomous_ai_agents.orchestrator.factory import build_context

from .conftest import TESTS_DIR, LiveRun
from .corpus import CorpusRepo, HypothesisSpec, Loop

OSS_DIR: Final = TESTS_DIR / "fixtures" / "live_oss"
MANIFEST: Final = OSS_DIR / "manifest.json"
WORKLOADS_DIR: Final = OSS_DIR / "workloads"
OSS_RUN_CAP_USD: Final = 5.0
MIN_REPOS: Final = 8
MAX_REPOS: Final = 10
CLONE_TIMEOUT_S: Final = 300.0
NETWORK_ENV: Final = "LIVE_OSS_NETWORK"
BENCH_AUTHOR: Final = ("OSS corpus", "oss-corpus@example.invalid")
BENCH_DATE: Final = "2026-01-01T00:00:00+00:00"

PERMISSIVE_LICENSES: Final[Mapping[str, str]] = {
    "MIT": "Permission is hereby granted, free of charge",
    "BSD-2-Clause": "Redistribution and use in source and binary forms",
    "BSD-3-Clause": "Neither the name",
    "Apache-2.0": "Apache License",
    "PSF-2.0": "PYTHON SOFTWARE FOUNDATION LICENSE",
    "ISC": "Permission to use, copy, modify, and/or distribute",
}
"""The SPDX ids allowed, each with a phrase its LICENSE file must hold."""

GITHUB_URL: Final = re.compile(
    r"https://github\.com/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}\.git"
)
PIN: Final = re.compile(r"[0-9a-f]{40}")
TAG: Final = re.compile(r"(?!.*\.\.)(?!.*\.lock$)[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
NAME: Final = re.compile(r"[a-z][a-z0-9_]{0,39}")
PACKAGE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
TITLE: Final = re.compile(r"[a-z][a-z0-9-]{0,47}")
BENCH_DIR: Final = "benchmarks"
BENCH_PATH: Final = re.compile(rf"{BENCH_DIR}/bench_[a-z][a-z0-9_]{{0,39}}\.py")
TARGET: Final = re.compile(
    r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}/){1,6}[A-Za-z_][\w]{0,63}\.py"
)
MAX_TARGETS: Final = 4
MAX_ATTRIBUTES_BYTES: Final = 1024 * 1024
LICENSE_FILE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_LFS: Final = re.compile(r"(?<!\S)filter=lfs(?!\S)", re.IGNORECASE)
Pair = tuple[tuple[str, ...], tuple[str, ...]]
"""The library files each of the two hypotheses is about."""
_KEYS: Final = frozenset(
    {"name", "url", "tag", "commit", "released", "license", "license_file"}
    | {"package", "module_root", "test_command", "hypotheses", "profile"}
)

# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OssRepo:
    """One pinned library of ``manifest.json``."""

    name: str
    url: str
    tag: str
    commit: str
    released: str
    license: str
    license_file: str
    package: str
    module_root: str
    test_command: tuple[str, ...]
    hypotheses: tuple[HypothesisSpec, HypothesisSpec]
    targets: Pair
    profile: str

    @property
    def workload_source(self) -> Path:
        return WORKLOADS_DIR / f"{self.name}.py"

    @property
    def bench_path(self) -> str:
        return f"{BENCH_DIR}/bench_{self.name}.py"

    @property
    def workload_argv(self) -> tuple[str, ...]:
        return ("python", self.bench_path)

    @property
    def corpus(self) -> CorpusRepo:
        """How the corpus recorder sees it: a real-code ``slowdown`` case
        with no known fix (``expected`` ``none``)."""
        return CorpusRepo(
            name=self.name,
            package=self.package,
            kind="slowdown",
            expected="none",
            hypotheses=self.hypotheses,
        )

    def project(self, root: Path) -> Project:
        return Project(
            name=self.name, root_path=str(root), test_command=self.test_command
        )

    def workload(self, project: Project) -> Workload:
        return Workload(
            project_id=project.id, name=self.name, command=self.workload_argv
        )

    def candidates(self, project: Project) -> list[Hypothesis]:
        return [spec.build(project) for spec in self.hypotheses]


def _text(
    raw: Mapping[str, object],
    key: str,
    where: str,
    pattern: re.Pattern[str] | None = None,
) -> str:
    value = raw[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}.{key}: expected a non-empty string")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{where}.{key}: {value!r} does not match {pattern.pattern}")
    return value


def _object(value: object, keys: frozenset[str], where: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(
            f"{where}: expected an object with exactly the keys {sorted(keys)}"
        )
    return {str(k): v for k, v in value.items()}


_HYPOTHESIS_KEYS: Final = frozenset({"title", "aimed", "rationale", "files"})
Hypotheses = tuple[tuple[HypothesisSpec, HypothesisSpec], Pair]


def _targets(value: object, at: str, module_root: str) -> tuple[str, ...]:
    """1 to ``MAX_TARGETS`` distinct ``.py`` files under ``module_root``."""
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= MAX_TARGETS
        or len(set(map(str, value))) != len(value)
        or not all(
            isinstance(f, str)
            and TARGET.fullmatch(f) is not None
            and f.startswith(f"{module_root}/")
            for f in value
        )
    ):
        raise ValueError(
            f"{at}.files: expected 1 to {MAX_TARGETS} distinct .py files "
            f"under {module_root}/"
        )
    return tuple(value)


def _hypotheses(value: object, where: str, module_root: str) -> Hypotheses:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{where}.hypotheses: expected exactly two")
    specs: list[HypothesisSpec] = []
    targets: list[tuple[str, ...]] = []
    for index, item in enumerate(value):
        at = f"{where}.hypotheses[{index}]"
        raw = _object(item, _HYPOTHESIS_KEYS, at)
        aimed = raw["aimed"]
        if not isinstance(aimed, bool):
            raise ValueError(f"{at}.aimed: expected true or false")
        title, rationale = _text(raw, "title", at, TITLE), _text(raw, "rationale", at)
        specs.append(
            HypothesisSpec(title, rationale, aimed, expected_gain=0.6 if aimed else 0.3)
        )
        targets.append(_targets(raw["files"], at, module_root))
    first, second = specs
    if (first.aimed, second.aimed) != (True, False):
        raise ValueError(f"{where}.hypotheses: one aimed (first), one neutral (second)")
    if first.title == second.title:
        raise ValueError(f"{where}.hypotheses: the titles must be distinct")
    return (first, second), (targets[0], targets[1])


def _argv(value: object, where: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or len(value) < 2
        or value[0] != "python"
        or not all(isinstance(a, str) and a and "\0" not in a for a in value)
    ):
        raise ValueError(
            f"{where}.test_command: expected an argv list starting with python"
        )
    return tuple(value)


def _entry(value: object, where: str, workloads: Path) -> OssRepo:
    raw = _object(value, _KEYS, where)
    name, package = (
        _text(raw, "name", where, NAME),
        _text(raw, "package", where, PACKAGE),
    )
    license_id = _text(raw, "license", where)
    if license_id not in PERMISSIVE_LICENSES:
        raise ValueError(
            f"{where}.license: {license_id!r} is not in {sorted(PERMISSIVE_LICENSES)}"
        )
    released = _text(raw, "released", where)
    try:
        datetime.date.fromisoformat(released)
    except ValueError:
        raise ValueError(f"{where}.released: {released!r} is not an ISO date") from None
    module_root = _text(raw, "module_root", where)
    if module_root not in (package, f"src/{package}"):
        raise ValueError(
            f"{where}.module_root: expected {package!r} or 'src/{package}'"
        )
    if not (workloads / f"{name}.py").is_file():
        raise ValueError(f"{where}: no workload {name}.py in {workloads}")
    hypotheses, (aimed_at, neutral_at) = _hypotheses(
        raw["hypotheses"], where, module_root
    )
    return OssRepo(
        name=name,
        url=_text(raw, "url", where, GITHUB_URL),
        tag=_text(raw, "tag", where, TAG),
        commit=_text(raw, "commit", where, PIN),
        released=released,
        license=license_id,
        license_file=_text(raw, "license_file", where, LICENSE_FILE),
        package=package,
        module_root=module_root,
        test_command=_argv(raw["test_command"], where),
        hypotheses=hypotheses,
        targets=(aimed_at, neutral_at),
        profile=_text(raw, "profile", where),
    )


def parse_manifest(
    data: object, workloads: Path = WORKLOADS_DIR
) -> tuple[OssRepo, ...]:
    """The libraries of ``manifest.json``, validated strictly."""
    if (
        not isinstance(data, dict)
        or set(data) != {"repos"}
        or not isinstance(data["repos"], list)
    ):
        raise ValueError("manifest: expected an object with one key, repos (a list)")
    entries = data["repos"]
    if len(entries) > MAX_REPOS:
        raise ValueError(f"manifest.repos: at most {MAX_REPOS} libraries")
    repos = tuple(
        _entry(e, f"manifest.repos[{i}]", workloads) for i, e in enumerate(entries)
    )
    names = [repo.name for repo in repos]
    if len(set(names)) != len(names):
        raise ValueError(f"manifest.repos: duplicate names in {names}")
    return repos


OSS_CORPUS: Final = parse_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))

# ---------------------------------------------------------------------------
# Cloning at run time
# ---------------------------------------------------------------------------


class CloneRefusedError(Exception):
    """A repository this corpus will not hand to the engine, and why."""


@dataclass(frozen=True)
class GitPolicy:
    """Which URLs and git transports a clone may use, how long git may take."""

    allow: re.Pattern[str] = GITHUB_URL
    protocols: str = "https"
    timeout_s: float = CLONE_TIMEOUT_S
    executable: str = "git"


PRODUCTION: Final = GitPolicy()
PASS_THROUGH: Final = (
    "PATH", "HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy",
    "GIT_SSL_CAINFO", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE",
)  # fmt: skip
"""What a clone needs from the host: the PATH, the proxy and its CA."""
_CONFIG: Final = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "core.autocrlf=false",
    "-c", "transfer.fsckObjects=true",
    "-c", "submodule.recurse=false",
    "-c", "commit.gpgsign=false",
    "-c", "advice.detachedHead=false",
)  # fmt: skip


def git_env(
    home: Path, policy: GitPolicy, environ: Mapping[str, str]
) -> dict[str, str]:
    """A scratch git environment: no system or global config (so no
    ``insteadOf``, hooks path or filters of the host), no prompt or askpass
    helper, only ``policy.protocols``, and the benchmark identity."""
    env = {name: environ[name] for name in PASS_THROUGH if name in environ}
    name, email = BENCH_AUTHOR
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_ASKPASS="",
        GIT_ALLOW_PROTOCOL=policy.protocols,
        LC_ALL="C",
        GIT_AUTHOR_NAME=name,
        GIT_AUTHOR_EMAIL=email,
        GIT_AUTHOR_DATE=BENCH_DATE,
        GIT_COMMITTER_NAME=name,
        GIT_COMMITTER_EMAIL=email,
        GIT_COMMITTER_DATE=BENCH_DATE,
    )
    return env


@dataclass(frozen=True)
class _Git:
    cwd: Path
    env: Mapping[str, str]
    policy: GitPolicy

    def __call__(self, *args: str) -> str:
        argv = [self.policy.executable, "-C", str(self.cwd), *_CONFIG, *args]
        try:
            proc = subprocess.run(  # an argv list of validated inputs, no shell
                argv,
                env=dict(self.env),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=self.policy.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise CloneRefusedError(
                f"git {args[0]} timed out after {self.policy.timeout_s:g} s"
            ) from None
        if proc.returncode != 0:
            tail = proc.stderr.decode(errors="replace").strip()[-500:]
            raise CloneRefusedError(
                f"git {args[0]} failed (exit {proc.returncode}): {tail}"
            )
        return proc.stdout.decode(errors="replace").strip()


@contextmanager
def _scratch_git(
    dest: Path, policy: GitPolicy, environ: Mapping[str, str] | None
) -> Iterator[_Git]:
    """Git on ``dest`` with a fresh, private (0700) ``HOME`` in the system
    temp dir, removed afterwards: nothing is left beside the repository."""
    host = os.environ if environ is None else environ
    home = Path(tempfile.mkdtemp(prefix="oss-git-home-"))
    try:
        yield _Git(dest, git_env(home, policy, host), policy)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def check_pin(url: str, tag: str, commit: str, policy: GitPolicy) -> None:
    """Refuse a URL off ``policy.allow``, a malformed tag or a short pin."""
    if policy.allow.fullmatch(url) is None:
        raise CloneRefusedError(
            f"{url!r} is not on the allowlist {policy.allow.pattern}"
        )
    if TAG.fullmatch(tag) is None:
        raise CloneRefusedError(f"tag {tag!r} is not a plain release tag name")
    if PIN.fullmatch(commit) is None:
        raise CloneRefusedError(f"pin {commit!r} is not a full 40-hex commit id")


def verify_head(
    dest: Path,
    commit: str,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Refuse a checkout whose ``HEAD`` is not ``commit`` on ``main``."""
    with _scratch_git(dest, policy, environ) as git:
        head = git("rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
        branch = git("symbolic-ref", "-q", "HEAD")
    if (head, branch) != (commit, "refs/heads/main"):
        raise CloneRefusedError(
            f"HEAD is {head} on {branch}, not the pin {commit} on main"
        )


def _attributes(git: _Git, path: str, mode: str, oid: str) -> str:
    """The committed blob of the attributes file ``path``, read from the
    object store (never the checkout, so a link is never followed) under
    ``MAX_ATTRIBUTES_BYTES``; anything but a regular file is refused."""
    if mode not in ("100644", "100755"):
        raise CloneRefusedError(f"{path}: not a regular file (mode {mode})")
    if int(git("cat-file", "-s", oid)) > MAX_ATTRIBUTES_BYTES:
        raise CloneRefusedError(f"{path}: over {MAX_ATTRIBUTES_BYTES} bytes")
    return git("cat-file", "blob", oid)


def _refuse_unsupported(git: _Git) -> None:
    """Submodules and LFS are refused (preflight refuses them too)."""
    listing = git("ls-tree", "-r", "-z", "--full-tree", "HEAD")
    for record in filter(None, listing.split("\0")):
        meta, _, path = record.partition("\t")
        mode, _, oid = meta.split(" ")
        base = path.rsplit("/", 1)[-1].casefold()
        if mode == "160000" or base == ".gitmodules":
            raise CloneRefusedError(f"{path}: submodules are not supported")
        if base == ".lfsconfig" or (
            base == ".gitattributes" and _LFS.search(_attributes(git, path, mode, oid))
        ):
            raise CloneRefusedError(f"{path}: the repository uses Git LFS")


def clone_pinned(
    url: str,
    tag: str,
    commit: str,
    dest: Path,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> str:
    """``tag`` of ``url`` at depth 1 into the new repository ``dest``, checked
    out on ``main``; the pinned ``commit``, or ``CloneRefusedError`` (and
    nothing left at ``dest``)."""
    check_pin(url, tag, commit, policy)
    if not dest.is_absolute():
        raise CloneRefusedError(f"{dest} must be an absolute path")
    if os.path.lexists(dest):
        raise CloneRefusedError(f"{dest} exists already")
    if not dest.parent.is_dir():
        raise CloneRefusedError(f"no directory for {dest}")
    with _scratch_git(dest, policy, environ) as git:
        try:
            _fetch_pin(git, url, tag, commit)
        except BaseException:
            shutil.rmtree(dest, ignore_errors=True)
            raise
    return commit


def _fetch_pin(git: _Git, url: str, tag: str, commit: str) -> None:
    dest = git.cwd
    _Git(dest.parent, git.env, git.policy)("init", "-q", "-b", "main", "--", str(dest))
    git("fetch", "-q", "--depth", "1", "--no-tags", "--no-recurse-submodules",
        "--", url, f"refs/tags/{tag}")  # fmt: skip
    fetched = git("rev-parse", "--verify", "--end-of-options", "FETCH_HEAD^{commit}")
    if fetched != commit:
        raise CloneRefusedError(
            f"{url} tag {tag} is {fetched}, not the pinned {commit}"
        )
    git("checkout", "-q", "-B", "main", commit)
    (dest / ".git" / "FETCH_HEAD").unlink()
    verify_head(dest, commit, policy=git.policy, environ=git.env)
    _refuse_unsupported(git)


def install_workload(
    dest: Path,
    source: Path,
    bench_path: str,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Commit ``source`` as ``bench_path`` in ``dest`` with the fixed
    benchmark identity and date; the new ``HEAD``."""
    if BENCH_PATH.fullmatch(bench_path) is None:
        raise CloneRefusedError(
            f"bench path {bench_path!r} is not {BENCH_DIR}/bench_<name>.py"
        )
    folder, target = dest / BENCH_DIR, dest / bench_path
    if os.path.islink(folder) or (os.path.lexists(folder) and not folder.is_dir()):
        raise CloneRefusedError(f"{folder} is not a plain directory in the repository")
    if os.path.lexists(target):
        raise CloneRefusedError(f"{bench_path} is already in the repository")
    folder.mkdir(exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)
    with _scratch_git(dest, policy, environ) as git:
        git("add", "-f", "--", bench_path)  # a .gitignore may name the folder
        git("commit", "-q", "--no-verify", "-m", "bench: the OSS corpus workload")
        return git("rev-parse", "--verify", "HEAD")


def prepare_repo(
    repo: OssRepo,
    dest: Path,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
) -> UserRepo:
    """``repo`` cloned at its pin with its workload committed, plus the refs
    no run may touch (``UNTOUCHED_REFS``): what ``make_repo`` gives."""
    clone_pinned(repo.url, repo.tag, repo.commit, dest, policy=policy, environ=environ)
    try:
        head = install_workload(
            dest, repo.workload_source, repo.bench_path, policy=policy, environ=environ
        )
        with _scratch_git(dest, policy, environ) as git:
            for ref, target in UNTOUCHED_REFS.items():
                git("update-ref", ref, target)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return UserRepo(dest, head)


# ---------------------------------------------------------------------------
# The whole loop (as corpus.start_loop, on the clone)
# ---------------------------------------------------------------------------


def _no_factory(cfg: Settings) -> LLMTransport:
    raise AssertionError("the OSS corpus must use the captured transport")


def start_oss_loop(
    repo: OssRepo,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Mapping[str, str] | None = None,
    candidates: Callable[[Project], Sequence[Hypothesis]] | None = None,
) -> Loop:
    """``repo`` prepared under ``root`` and ``build_context`` on the real
    transport (captured), with ``isolation`` (``required``). ``candidates``
    builds the hypotheses from the project (a discovery suite's own); without
    it the manifest's are used."""
    user = prepare_repo(repo, root / "user", policy=policy, environ=environ)
    before = user.snapshot()
    project = repo.project(user.path)
    chosen: Sequence[Hypothesis] = tuple(
        repo.candidates(project) if candidates is None else candidates(project)
    )
    launches = LaunchLog()
    context = build_context(
        project,
        candidates=chosen,
        transport=run.transport(settings),
        transport_factory=_no_factory,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
    )
    return Loop(
        repo.corpus,
        user,
        before,
        project,
        repo.workload(project),
        tuple(chosen),
        launches,
        context,
        run.cap_usd,
    )
