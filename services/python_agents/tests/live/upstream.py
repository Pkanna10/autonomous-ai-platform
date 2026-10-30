"""The upstream corpus (V9; owner decision O20): performance fixes maintainers merged.

Each candidate is a real open-source performance commit. Under the setter,
attempter and marker rule (O19) the roles stay apart:

- **Setter:** the library's maintainers. The before-commit is the exam
  question; the maintainer's fix is the answer key, sealed in
  ``tests/fixtures/upstream_corpus/_keys/<id>.patch`` with its sha256 in
  ``manifest.json`` before any attempt (V9a mined them; V9b wrote the
  benchmark ``workloads/<id>.py`` blind to the keys and the diffs, though
  it saw the miner's ids, which name each fix's idea: blind to the diff,
  not to the idea, so ``workloads/README.md`` lists the candidates whose
  live hits are reported separately). Five keys say an AI
  agent wrote them (``key.ai_assisted``), four of them Claude models, the
  attempter's own family: ``setter`` names who set each key, ``pool`` adds
  what the before-tree hints at (``hint_in_before``: a TODO naming the fix,
  a maintainer benchmark of the hot shape, a changelog naming the same class
  of fix), and the live summary reports every pool apart
  (``pools_markdown``); the scored pool is human keys with no hint.
- **Attempter:** the engine, on ``prepare_repo``'s repository only: one root
  commit holding the before-tree (no upstream history, no later object, no
  remote, no shallow file, so the fix cannot be read or fetched from it) and
  the benchmark commit, exactly as ``oss.py`` installs a workload (the
  ``benchmarks/`` directory is protected). The keys are never copied into it:
  like the corpora's ``_solutions`` they live beside the repositories, and
  only the CI verifier (``upstream_verify``) reads them. The miner's ids
  hint at each fix ("ascii-fastpath"), so what the engine sees (the project
  and workload names, ``benchmarks/bench_<lib>.py``, the commit messages,
  the copied workload's docstring) names the library, the public calls and
  the input shape only; the touched files and functions and the coverage
  notes stay in ``_notes/workloads.md`` beside the keys, never in a clone
  (``test_upstream_guards`` checks every copied workload).
- **Marker:** the frozen judges, with the project's own tests
  (``test_command``) as the behaviour guard.

``UpstreamCase`` is one manifest entry, validated strictly
(``parse_manifest``): the https GitHub URL and the full before-commit sha, a
licence whose every operand is on ``oss.PERMISSIVE_LICENSES``, the package
and its module root, the touched files (under the module root), the
contamination risk (``low``: authored and committed after ``CUTOFF``, the
attempter models' shared training cutoff; ``medium``: a little-known fix
from before it; ``high`` is refused), the hint in the before-tree, the
test command, the packages a candidate needs beyond its checkout
(``requires``: hash-pinned in ``requirements.txt`` or already in the lock),
one-line stand-ins for build-written modules (``setup_files``), the CPython
range the before-tree supports (``requires_python``: ``prepare_repo``
refuses an interpreter outside it; the CI suites run ``UPSTREAM_PYTHON``,
inside every range), whether submodules are dropped from the tree
(``drops_submodules``: their content is never fetched, so the gitlinks are
removed rather than refused), the verification record (``verified``: null
until the CI ``upstream-verify`` suite has measured the key, then bound to
the workload's sha256, so a resized benchmark needs a new verification) and
the sealed key.

Batches: CI runs ``BATCH_SIZE`` candidates a dispatch (``$LIVE_UPSTREAM_BATCH``
1-3), so the verifier fits its job and the live suite's need stays at
``live_need()``. ``GitPolicy`` is the one seam, as in ``oss.py``: tests
inject a ``file://`` allowlist; production code never does. No third-party
code runs here: cloning, and running anything cloned, happens on CI only.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from e2e.conftest import UNTOUCHED_REFS, Isolation, LaunchLog, UserRepo
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import Project, Workload
from autonomous_ai_agents.orchestrator.factory import build_context

from .conftest import TESTS_DIR, LiveRun
from .corpus import CorpusOutcome, CorpusRepo, HypothesisSpec, Loop, role_wiring
from .discovery_io import cells, write_markdown
from .oss import (
    BENCH_PATH,
    GITHUB_URL,
    LICENSE_FILE,
    NAME,
    PACKAGE,
    PERMISSIVE_LICENSES,
    PIN,
    PRODUCTION,
    TARGET,
    CloneRefusedError,
    GitPolicy,
    _argv,
    _Git,
    _no_factory,
    _object,
    _refuse_unsupported,
    _scratch_git,
    _text,
    verify_head,
)

UPSTREAM_DIR: Final = TESTS_DIR / "fixtures" / "upstream_corpus"
MANIFEST: Final = UPSTREAM_DIR / "manifest.json"
WORKLOADS_DIR: Final = UPSTREAM_DIR / "workloads"
KEYS_DIR: Final = UPSTREAM_DIR / "_keys"
REQUIREMENTS: Final = UPSTREAM_DIR / "requirements.txt"
CUTOFF: Final = datetime.date(2026, 6, 30)
"""Opus 5.5, Sonnet 5.5 and Fable 5.1: training-data cutoff Jun 2026."""
MIN_CANDIDATES: Final = 8  # the owner's target: at least 8 low or medium
BATCH_SIZE: Final = 10
BATCH_ENV: Final = "LIVE_UPSTREAM_BATCH"
UPSTREAM_RUN_CAP_USD: Final = 5.0  # one wired loop, as an OSS run
LIVE_JOB_MINUTES: Final = 300  # ten loops, as the oss suite (D41's 2.6x)
MIN_GAIN: Final = 0.10
FLOOR_MULTIPLE: Final = 2.0
SETUP_MAX_BYTES: Final = 256
ID: Final = re.compile(r"[a-z][a-z0-9_]{0,23}(?:-[a-z0-9]{1,16}){1,5}")
REQUIREMENT: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
PYTHON_SPEC: Final = re.compile(r"[0-9<>=!~,. ]{0,40}")
FUNCTION: Final = re.compile(r"[<>A-Za-z0-9_.]{1,120}")
RISKS: Final = ("low", "medium")
UPSTREAM_PYTHON: Final = "3.12"
"""The CPython both CI upstream suites run (ci.yml): every candidate's
``requires_python`` admits it (the networkx before-trees need 3.12)."""
SETTERS: Final = ("human", "ai", "claude")
HINT_KINDS: Final[Mapping[str, str]] = {
    "fix_idea": "direct",  # e.g. a TODO naming the fix above the hot function
    "hot_shape": "direct",  # a maintainer benchmark of the exact hot shape
    "same_class": "class",  # the changelog names the same class of fix
}
POOLS: Final = tuple(
    f"{setter}, {tier} hint" for setter in SETTERS for tier in ("no", "class", "direct")
)
SCORED_POOL: Final = POOLS[0]
CLAUDE: Final = re.compile(r"claude", re.IGNORECASE)
AI_NOTE: Final = re.compile(r"[ -~]{1,200}")
EVIDENCE: Final = re.compile(
    r"[A-Za-z0-9_./-]{1,120}:[0-9]+(?:,[0-9]+)*: [ -~]{10,400}"
)
LICENCE_PHRASES: Final[Mapping[str, str]] = {
    **PERMISSIVE_LICENSES,
    "BSD-3-Clause": "used to endorse or promote products derived",
}
"""Each SPDX id's phrase, matched with whitespace collapsed (pypdf's BSD-3
text says "The name of the author may not be used", not "Neither the name")."""
WIRED: Final = (
    HypothesisSpec("upstream-wired", "Never handed over: wired mode.", True),
    HypothesisSpec("upstream-wired-neutral", "Never handed over: wired mode.", False),
)
"""``CorpusRepo`` needs a pair; the upstream suite runs ``wired`` only, so
the engine's own generator proposes every idea and these are never used."""
_ENTRY_KEYS: Final = frozenset(
    {"id", "lib", "url", "before_sha", "licence", "license_file", "package"}
    | {"module_root", "touched_files", "touched_functions", "contamination_risk"}
    | {"contamination_reason", "test_command", "tests_note", "requires"}
    | {"setup_files", "requires_python", "drops_submodules", "verified", "key"}
    | {"hint_in_before"}
)
_KEY_KEYS: Final = frozenset(
    {"patch", "sha256", "fix_sha", "commit_date", "author_date", "author", "link"}
    | {"commit_url", "message", "hot_path", "touched_functions", "diff_stats"}
    | {"other_files_in_commit", "ai_assisted"}
)
_VERIFIED_KEYS: Final = frozenset(
    {"run_id", "gain", "noise_floor", "threshold", "workload_sha256"}
)
_HINT_KEYS: Final = frozenset({"kind", "evidence"})
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
Environ = Mapping[str, str] | None

# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------


def threshold(floor: float) -> float:
    """The gain a key must clear: twice the measured floor, at least 10 %."""
    return max(FLOOR_MULTIPLE * floor, MIN_GAIN)


@dataclass(frozen=True)
class SealedKey:
    """What the loader needs of a key; the rest stays in the manifest."""

    sha256: str
    fix_sha: str
    commit_date: datetime.date
    author_date: datetime.date
    ai_assisted: tuple[str, ...] = ()  # the commit's own AI attributions


@dataclass(frozen=True)
class Verified:
    """The CI verification a candidate passed (``upstream-verify``), on the
    workload whose sha256 it records."""

    run_id: str
    gain: float
    noise_floor: float
    threshold: float
    workload_sha256: str


@dataclass(frozen=True)
class Hint:
    """What the before-tree the engine is handed shows of the fix:
    ``evidence`` is ``<path>:<line>: <what it says>``."""

    kind: str
    evidence: str


@dataclass(frozen=True)
class UpstreamCase:
    """One candidate of ``manifest.json``."""

    id: str
    lib: str
    url: str
    before_sha: str
    licence: str
    license_file: str
    package: str
    module_root: str
    touched_files: tuple[str, ...]
    touched_functions: Mapping[str, tuple[str, ...]]
    contamination_risk: str
    contamination_reason: str
    test_command: tuple[str, ...]
    tests_note: str
    requires: tuple[str, ...]
    setup_files: Mapping[str, str]
    requires_python: str
    drops_submodules: bool
    verified: Verified | None
    key: SealedKey
    hint_in_before: Hint | None
    workloads: Path = WORKLOADS_DIR
    keys: Path = KEYS_DIR

    @property
    def workload_source(self) -> Path:
        return self.workloads / f"{self.id}.py"

    @property
    def workload_sha256(self) -> str:
        return hashlib.sha256(self.workload_source.read_bytes()).hexdigest()

    @property
    def key_path(self) -> Path:
        return self.keys / f"{self.id}.patch"

    @property
    def bench_path(self) -> str:
        """Named after the library: the miner's id hints at the fix."""
        return f"benchmarks/bench_{self.lib}.py"

    @property
    def corpus(self) -> CorpusRepo:
        """A real-code ``slowdown`` with no fix the recorder knows."""
        return CorpusRepo(self.id, self.package, "slowdown", "none", WIRED)

    def project(self, root: Path) -> Project:
        """Named after the library, never the id (the engine sees the name)."""
        return Project(
            name=self.lib, root_path=str(root), test_command=self.test_command
        )

    def workload(self, project: Project) -> Workload:
        argv = ("python", self.bench_path)
        return Workload(project_id=project.id, name=self.lib, command=argv)


def setter(case: UpstreamCase) -> str:
    """Who set the key: the maintainers (``human``), an AI agent the commit
    names (``ai``) or a Claude model, the attempter's family (``claude``)."""
    notes = case.key.ai_assisted
    if not notes:
        return "human"
    return "claude" if any(CLAUDE.search(note) for note in notes) else "ai"


def pool(case: UpstreamCase) -> str:
    """The pool a result is reported in: the setter, then the hint's tier."""
    hint = case.hint_in_before
    tier = "no" if hint is None else HINT_KINDS[hint.kind]
    return f"{setter(case)}, {tier} hint"


def python_problem(case: UpstreamCase, version: str) -> str | None:
    """Why CPython ``version`` is outside the before-tree's ``requires_python``."""
    if SpecifierSet(case.requires_python).contains(version, prereleases=True):
        return None
    return f"{case.id} needs Python {case.requires_python}, this is {version}"


def _date(value: object, where: str) -> datetime.date:
    try:
        return datetime.datetime.fromisoformat(str(value)).date()
    except ValueError:
        raise ValueError(f"{where}: {value!r} is not an ISO date") from None


def _strings(value: object, where: str, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(v, str) and pattern.fullmatch(v) for v in value
    ):
        raise ValueError(f"{where}: expected a list matching {pattern.pattern}")
    if len(set(value)) != len(value):
        raise ValueError(f"{where}: duplicates")
    return tuple(value)


def _key(raw: dict[str, object], where: str, case_id: str, keys: Path) -> SealedKey:
    key = _object(raw["key"], _KEY_KEYS, f"{where}.key")
    if key["patch"] != f"_keys/{case_id}.patch":
        raise ValueError(f"{where}.key.patch: expected '_keys/{case_id}.patch'")
    path = keys / f"{case_id}.patch"
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{where}: no key {path.name} in {keys}")
    sha = _text(key, "sha256", f"{where}.key", _SHA256)
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise ValueError(f"{where}.key.sha256: {path.name} is not the sealed key")
    return SealedKey(
        sha,
        _text(key, "fix_sha", f"{where}.key", PIN),
        _date(key["commit_date"], f"{where}.key.commit_date"),
        _date(key["author_date"], f"{where}.key.author_date"),
        _strings(key["ai_assisted"], f"{where}.key.ai_assisted", AI_NOTE),
    )


def _hint(value: object, where: str) -> Hint | None:
    if value is None:
        return None
    raw = _object(value, _HINT_KEYS, where)
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in HINT_KINDS:
        raise ValueError(f"{where}.kind: expected one of {sorted(HINT_KINDS)}")
    return Hint(kind, _text(raw, "evidence", where, EVIDENCE))


def _verified(value: object, where: str, workload: Path) -> Verified | None:
    if value is None:
        return None
    raw = _object(value, _VERIFIED_KEYS, where)
    sha = raw["workload_sha256"]
    if sha != hashlib.sha256(workload.read_bytes()).hexdigest():
        raise ValueError(f"{where}.workload_sha256: not the workload in {workload}")
    run_id = raw["run_id"]
    numbers = [raw["gain"], raw["noise_floor"], raw["threshold"]]
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise ValueError(f"{where}.run_id: expected the CI run id")
    values: list[float] = []
    for number in numbers:
        if not isinstance(number, int | float) or isinstance(number, bool):
            raise ValueError(f"{where}: gain, noise_floor and threshold are numbers")
        values.append(float(number))
    gain, floor, least = values
    if not 0 < floor < 1 or abs(least - threshold(floor)) > 1e-9 or not gain > least:
        raise ValueError(f"{where}: the gain must clear max(2 x floor, 10 %)")
    return Verified(run_id, gain, floor, least, str(sha))


def _setup(value: object, where: str, module_root: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected an object")
    found: dict[str, str] = {}
    for path, text in value.items():
        under = isinstance(path, str) and TARGET.fullmatch(path) is not None
        if not under or not path.startswith(f"{module_root}/"):
            raise ValueError(f"{where}: {path!r} is not a module under {module_root}/")
        if not isinstance(text, str) or len(text) > SETUP_MAX_BYTES:
            raise ValueError(f"{where}: {path!r} over {SETUP_MAX_BYTES} ASCII bytes")
        if not text.isascii():
            raise ValueError(f"{where}: {path!r} over {SETUP_MAX_BYTES} ASCII bytes")
        found[path] = text
    return found


def _licence(raw: dict[str, object], where: str) -> str:
    licence = _text(raw, "licence", where)
    if not all(op in PERMISSIVE_LICENSES for op in licence.split(" OR ")):
        raise ValueError(f"{where}.licence: {licence!r} is not all on the allowlist")
    return licence


def _risk(raw: dict[str, object], where: str, key: SealedKey) -> str:
    risk = _text(raw, "contamination_risk", where)
    after = min(key.commit_date, key.author_date) > CUTOFF
    if risk not in RISKS or (risk == "low") is not after:
        raise ValueError(
            f"{where}.contamination_risk: {risk!r}; low means authored and"
            f" committed after {CUTOFF}, medium otherwise, high is refused"
        )
    return risk


def _touched(raw: dict[str, object], where: str, root: str) -> tuple[str, ...]:
    files = _strings(raw["touched_files"], f"{where}.touched_files", TARGET)
    if not files or not all(f.startswith(f"{root}/") for f in files):
        raise ValueError(f"{where}.touched_files: expected files under {root}/")
    return files


def _functions(
    value: object, where: str, files: Sequence[str]
) -> dict[str, tuple[str, ...]]:
    if not isinstance(value, dict) or set(value) != set(files):
        raise ValueError(f"{where}.touched_functions: one list per touched file")
    return {
        f: _strings(value[f], f"{where}.touched_functions", FUNCTION) for f in files
    }


def _identity(raw: dict[str, object], where: str) -> tuple[str, str]:
    case_id, lib = _text(raw, "id", where, ID), _text(raw, "lib", where, NAME)
    bench = f"benchmarks/bench_{lib}.py"
    if not case_id.startswith(f"{lib}-") or BENCH_PATH.fullmatch(bench) is None:
        raise ValueError(f"{where}.id: {case_id!r} must start {lib}- and fit a bench")
    return case_id, lib


def _flags(raw: dict[str, object], where: str) -> tuple[str, str, bool]:
    note, python, drops = (
        raw["tests_note"], raw["requires_python"], raw["drops_submodules"]
    )  # fmt: skip
    if not isinstance(drops, bool):
        raise ValueError(f"{where}.drops_submodules: expected true or false")
    if not isinstance(note, str) or not isinstance(python, str):
        raise ValueError(f"{where}: tests_note and requires_python are strings")
    try:
        SpecifierSet(python)  # python_problem's reading of the range
    except InvalidSpecifier:
        python = "?"
    if PYTHON_SPEC.fullmatch(python) is None:
        raise ValueError(f"{where}.requires_python: {python!r} is not a version spec")
    return note, python, drops


def _entry(value: object, where: str, workloads: Path, keys: Path) -> UpstreamCase:
    raw = _object(value, _ENTRY_KEYS, where)
    case_id, lib = _identity(raw, where)
    package = _text(raw, "package", where, PACKAGE)
    root = _text(raw, "module_root", where)
    if root not in (package, f"src/{package}"):
        raise ValueError(f"{where}.module_root: expected {package!r} or src/{package}")
    workload = workloads / f"{case_id}.py"
    if not workload.is_file():
        raise ValueError(f"{where}: no workload {case_id}.py in {workloads}")
    key = _key(raw, where, case_id, keys)
    files = _touched(raw, where, root)
    note, python, drops = _flags(raw, where)
    return UpstreamCase(
        id=case_id,
        lib=lib,
        url=_text(raw, "url", where, GITHUB_URL),
        before_sha=_text(raw, "before_sha", where, PIN),
        licence=_licence(raw, where),
        license_file=_text(raw, "license_file", where, LICENSE_FILE),
        package=package,
        module_root=root,
        touched_files=files,
        touched_functions=_functions(raw["touched_functions"], where, files),
        contamination_risk=_risk(raw, where, key),
        contamination_reason=_text(raw, "contamination_reason", where),
        test_command=_argv(raw["test_command"], where),
        tests_note=note,
        requires=_strings(raw["requires"], f"{where}.requires", REQUIREMENT),
        setup_files=_setup(raw["setup_files"], f"{where}.setup_files", root),
        requires_python=python,
        drops_submodules=drops,
        verified=_verified(raw["verified"], f"{where}.verified", workload),
        key=key,
        hint_in_before=_hint(raw["hint_in_before"], f"{where}.hint_in_before"),
        workloads=workloads,
        keys=keys,
    )


def parse_manifest(
    data: object, workloads: Path = WORKLOADS_DIR, keys: Path = KEYS_DIR
) -> tuple[UpstreamCase, ...]:
    """The candidates of ``manifest.json``, validated strictly."""
    top = frozenset({"cutoff", "cutoff_source", "candidates"})
    if not isinstance(data, dict) or set(data) != top:
        raise ValueError(f"manifest: expected exactly the keys {sorted(top)}")
    if _date(data["cutoff"], "manifest.cutoff") != CUTOFF:
        raise ValueError(f"manifest.cutoff: expected {CUTOFF}")
    entries = data["candidates"]
    if not isinstance(entries, list) or len(entries) < MIN_CANDIDATES:
        raise ValueError(f"manifest.candidates: at least {MIN_CANDIDATES}")
    cases = tuple(
        _entry(e, f"manifest.candidates[{i}]", workloads, keys)
        for i, e in enumerate(entries)
    )
    ids = [case.id for case in cases]
    if ids != sorted(set(ids)):
        raise ValueError("manifest.candidates: ids must be unique and sorted")
    return cases


UPSTREAM_CORPUS: Final = parse_manifest(
    json.loads(MANIFEST.read_text(encoding="utf-8"))
)
BATCHES: Final = -(-len(UPSTREAM_CORPUS) // BATCH_SIZE)


def licence_problem(case: UpstreamCase, text: str) -> str | None:
    """Why ``text`` (the checkout's licence file) is not ``case.licence``."""
    flat = " ".join(text.split())
    operands = case.licence.split(" OR ")
    if any(" ".join(LICENCE_PHRASES[op].split()) in flat for op in operands):
        return None
    return f"{case.license_file} holds no {case.licence} text"


def batch(
    cases: Sequence[UpstreamCase], environ: Mapping[str, str]
) -> tuple[UpstreamCase, ...]:
    """Batch ``$LIVE_UPSTREAM_BATCH`` (1 to ``BATCHES``, default 1) of ``cases``."""
    value = environ.get(BATCH_ENV, "1")
    if value not in {str(n) for n in range(1, BATCHES + 1)}:
        raise ValueError(f"{BATCH_ENV} must be 1 to {BATCHES}, got {value!r}")
    start = (int(value) - 1) * BATCH_SIZE
    return tuple(cases[start : start + BATCH_SIZE])


def live_cases(
    environ: Mapping[str, str], cases: Sequence[UpstreamCase] = UPSTREAM_CORPUS
) -> tuple[UpstreamCase, ...]:
    """The live suite's batch of the verified candidates only."""
    return batch([case for case in cases if case.verified is not None], environ)


def live_need() -> float:
    """What one live dispatch asks the ledger for: a batch at the run cap."""
    return BATCH_SIZE * UPSTREAM_RUN_CAP_USD


def pools_markdown(
    cases: Sequence[UpstreamCase], outcomes: Sequence[CorpusOutcome]
) -> str:
    """The live runs per pool (``pool``): a run counts as delivered only
    with its guards ``ok``. O19: the pools are reported apart, never summed."""
    by_id = {case.id: case for case in cases}
    found: dict[str, list[CorpusOutcome]] = {}
    for outcome in outcomes:
        case = by_id.get(outcome.repo)
        if case is None:
            raise ValueError(f"{outcome.repo!r} is not an upstream candidate")
        found.setdefault(pool(case), []).append(outcome)
    lines = [
        "## Upstream corpus by pool (who set the key, what the before-tree hints)",
        "",
        "| pool | runs | delivered | rate | ids |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name in (p for p in POOLS if p in found):
        runs = found[name]
        hits = sum(o.delivered and o.guard == "ok" for o in runs)
        ids = ", ".join(o.repo for o in runs)
        lines.append(cells([name, len(runs), hits, f"{hits / len(runs):.0%}", ids]))
    scored = (
        f"Scored: {SCORED_POOL} (maintainers' keys, no hint in the before-tree);"
        " a Claude-written key shares the attempter's family and a hint"
        " discounts a hit, so those pools are reported beside it, not in it."
    )
    return "\n".join([*lines, "", scored])


def write_pools(
    cases: Sequence[UpstreamCase],
    outcomes: Sequence[CorpusOutcome],
    environ: Mapping[str, str],
    echo: Callable[[str], None],
) -> None:
    """``pools_markdown`` to the job summary and the log; nothing if no run."""
    if outcomes:
        write_markdown("Upstream pools", pools_markdown(cases, outcomes), environ, echo)


# ---------------------------------------------------------------------------
# The user's repository: one root commit of the before-tree, then the bench
# ---------------------------------------------------------------------------


def _base_tree(git: _Git, case: UpstreamCase) -> str:
    """The before-tree, minus gitlinks and ``.gitmodules`` when the manifest
    drops submodules (their content is never fetched); else refused."""
    sha = case.before_sha
    found: list[str] = []
    for record in filter(
        None, git("ls-tree", "-r", "-z", "--full-tree", sha).split("\0")
    ):
        meta, _, path = record.partition("\t")
        if meta.startswith("160000 ") or path.rsplit("/", 1)[-1] == ".gitmodules":
            found.append(path)
    if bool(found) is not case.drops_submodules:
        has = (
            f"has submodules ({', '.join(found[:3])})" if found else "has no submodule"
        )
        raise CloneRefusedError(f"{case.id}: the before-tree {has}: drops_submodules")
    if not found:
        return git("rev-parse", "--verify", "--end-of-options", f"{sha}^{{tree}}")
    index = Path(tempfile.mkdtemp(prefix="upstream-index-"))
    try:
        env = {**git.env, "GIT_INDEX_FILE": str(index / "index")}
        staged = _Git(git.cwd, env, git.policy)
        staged("read-tree", sha)
        staged("update-index", "--force-remove", "--", *found)
        return staged("write-tree")
    finally:
        shutil.rmtree(index, ignore_errors=True)


def _root_commit(
    case: UpstreamCase, scratch: Path, policy: GitPolicy, environ: Environ
) -> str:
    """In ``scratch``: the before-commit fetched at depth 1 by its sha and
    checked, then one new root commit of its tree (fixed identity and date)."""
    with _scratch_git(scratch, policy, environ) as git:
        _Git(scratch.parent, git.env, policy)("init", "-q", "-b", "main", "--", str(scratch))  # fmt: skip
        git("fetch", "-q", "--depth", "1", "--no-tags", "--no-recurse-submodules",
            "--", case.url, case.before_sha)  # fmt: skip
        fetched = git(
            "rev-parse", "--verify", "--end-of-options", "FETCH_HEAD^{commit}"
        )
        if fetched != case.before_sha:
            raise CloneRefusedError(f"{case.url} gave {fetched}, not {case.before_sha}")
        message = f"import {case.lib}"  # neutral: no hint that a fix exists
        root = git("commit-tree", _base_tree(git, case), "-m", message)
        git("update-ref", "refs/heads/main", root)
        return root


def _fetch_base(
    case: UpstreamCase, dest: Path, policy: GitPolicy, environ: Environ
) -> str:
    """``dest`` holds the root commit's objects only, checked out on ``main``:
    fetched from the scratch repository, which is then removed."""
    scratch = Path(tempfile.mkdtemp(prefix="upstream-fetch-")) / "repo"
    try:
        root = _root_commit(case, scratch, policy, environ)
        with _scratch_git(dest, policy, environ) as git:
            _Git(dest.parent, git.env, policy)("init", "-q", "-b", "main", "--", str(dest))  # fmt: skip
            local = _Git(dest, {**git.env, "GIT_ALLOW_PROTOCOL": "file"}, policy)
            local("fetch", "-q", "--no-tags", "--", str(scratch), "refs/heads/main")
            git("checkout", "-q", "-B", "main", root)
            (dest / ".git" / "FETCH_HEAD").unlink()
            verify_head(dest, root, policy=policy, environ=git.env)
            _refuse_unsupported(git)
            if any("_keys" in p.split("/") for p in git("ls-files").splitlines()):
                raise CloneRefusedError(f"{case.id}: a _keys path in the before-tree")
        return root
    finally:
        shutil.rmtree(scratch.parent, ignore_errors=True)


def _install(
    case: UpstreamCase, dest: Path, policy: GitPolicy, environ: Environ
) -> str:
    """The workload as ``bench_path`` and the setup files: one commit."""
    folder = dest / "benchmarks"
    if os.path.islink(folder) or (os.path.lexists(folder) and not folder.is_dir()):
        raise CloneRefusedError(f"{folder} is not a plain directory in the repository")
    paths = [case.bench_path, *case.setup_files]
    for rel in paths:
        if os.path.lexists(dest / rel):
            raise CloneRefusedError(f"{rel} is already in the repository")
    folder.mkdir(exist_ok=True)
    shutil.copyfile(case.workload_source, dest / case.bench_path)
    for rel, text in case.setup_files.items():
        (dest / rel).write_text(text, encoding="ascii")
    for rel in paths:
        (dest / rel).chmod(0o644)
    with _scratch_git(dest, policy, environ) as git:
        git("add", "-f", "--", *paths)  # a .gitignore may name them
        git("commit", "-q", "--no-verify", "-m", "bench: the upstream corpus workload")
        return git("rev-parse", "--verify", "HEAD")


def prepare_repo(
    case: UpstreamCase,
    dest: Path,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Environ = None,
    python: str | None = None,
) -> UserRepo:
    """The user's repository at ``dest``: the before-tree as one root commit,
    the benchmark commit, the refs no run may touch; never a key or history.
    ``python`` (default: this interpreter, which runs the workload and the
    tests) must be inside ``requires_python``. ``CloneRefusedError`` leaves
    nothing at ``dest``."""
    problem = python_problem(case, python or platform.python_version())
    if problem is not None:
        raise CloneRefusedError(problem)
    if policy.allow.fullmatch(case.url) is None:
        raise CloneRefusedError(f"{case.url!r} is not on the allowlist {policy.allow.pattern}")  # fmt: skip
    if PIN.fullmatch(case.before_sha) is None:
        raise CloneRefusedError(f"{case.before_sha!r} is not a full 40-hex commit id")
    if not dest.is_absolute() or os.path.lexists(dest) or not dest.parent.is_dir():
        raise CloneRefusedError(f"{dest} exists already or has no parent directory")
    try:
        _fetch_base(case, dest, policy, environ)
        head = _install(case, dest, policy, environ)
        with _scratch_git(dest, policy, environ) as git:
            for ref, target in UNTOUCHED_REFS.items():
                git("update-ref", ref, target)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return UserRepo(dest, head)


def start_upstream_loop(
    case: UpstreamCase,
    run: LiveRun,
    root: Path,
    isolation: Isolation,
    *,
    policy: GitPolicy = PRODUCTION,
    environ: Environ = None,
) -> Loop:
    """``case`` prepared under ``root`` and wired: no candidate handed over,
    the generator on its own captured transport (``corpus.role_wiring``)."""
    user = prepare_repo(case, root / "user", policy=policy, environ=environ)
    before = user.snapshot()
    project = case.project(user.path)
    launches = LaunchLog()
    context = build_context(
        project,
        candidates=(),
        transport=run.transport(settings),
        role_transports=role_wiring(run, "wired"),
        transport_factory=_no_factory,
        network=isolation.mode,
        fs=isolation.mode,
        run=launches,
    )
    return Loop(
        case.corpus, user, before, project, case.workload(project), (), launches,
        context, run.cap_usd, "wired",
    )  # fmt: skip
