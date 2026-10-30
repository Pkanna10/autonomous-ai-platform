"""Offline guards of the upstream corpus (V9c; owner decision O20, O19).

Not ``live``: these run in the normal suite, spend nothing and run no
third-party code (the libraries are only cloned and run on CI). They prove
the corpus is what it claims before any attempt:

- the manifest (``tests/fixtures/upstream_corpus/manifest.json``): every
  candidate pinned to a full before-commit on an https GitHub URL, a licence
  on the allowlist, its contamination risk consistent with the models'
  shared cutoff (each reason true to the release notes), a test command and
  its sealed key; who wrote each key (``setter``: the maintainers, another
  AI agent or a Claude model, the attempter's own family) and what the
  before-tree hints at (``hint_in_before``), so the live summary reports
  those pools apart; the Python range the CI suites run inside; malformed
  entries are refused;
- the keys (``_keys/<id>.patch``): each sha256 matches the manifest (sealed
  before any attempt), each a diff of exactly the touched files, and nothing
  else in ``_keys``; whether each applies to its before-tree, and the speed-up
  it gives, is the CI ``upstream-verify`` suite's job;
- the workloads: one per candidate, parsing, deterministic by construction
  and timing the checkout's own package;
- the user's repository (``upstream.prepare_repo``, on local bare upstreams
  over ``file://``): one root commit of the before-tree and the benchmark
  commit, no upstream history, no fix object, no shallow file, no remote, no
  key, the submodule and LFS rules;
- the verifier (``upstream_verify``): the key commit, the gain and its
  threshold, the results table, and one whole verification in the sandbox on
  a local upstream whose "maintainer fix" is known;
- the live wiring (wired, verified candidates only, per-run cap) and the CI
  patches (``V9-lead``), which fail here until the Lead applies them.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import httpx2
import pytest
from e2e.conftest import (
    UNTOUCHED_REFS,
    Isolation,
    Launch,
    LaunchLog,
    _sandbox_problem,
    git,
)

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import (
    METRIC_TESTS_PASSED,
    METRIC_WALL_TIME_S,
    Measurement,
    NoiseCalibration,
    RunStats,
)
from autonomous_ai_agents.execution.measure import AbabMeasured, Measured

from . import upstream, upstream_verify
from .conftest import TESTS_DIR, LiveRun, restore_host_key
from .corpus import CorpusOutcome
from .discovery_io import ResultsSink
from .oss import PERMISSIVE_LICENSES, CloneRefusedError, GitPolicy
from .upstream import (
    BATCH_ENV,
    BATCH_SIZE,
    KEYS_DIR,
    MANIFEST,
    REQUIREMENTS,
    UPSTREAM_CORPUS,
    UPSTREAM_RUN_CAP_USD,
    WORKLOADS_DIR,
    SealedKey,
    UpstreamCase,
    Verified,
    batch,
    live_cases,
    live_need,
    parse_manifest,
    prepare_repo,
    start_upstream_loop,
)
from .upstream_verify import (
    KEY_REF,
    VERIFY_PHASES,
    VERIFY_RUN_CAP_USD,
    KeyResult,
    VerifyRecorder,
    check_verify_guards,
    commit_key,
    summarize,
    threshold,
    verify_case,
)

LOCAL = GitPolicy(allow=re.compile(r"file:///[^\s?#]+\.git"), protocols="file")
"""Local bare repositories over file://: injected by these tests only."""
SERVICE_DIR = TESTS_DIR.parent
CI_WORKFLOW = SERVICE_DIR.parents[1] / ".github" / "workflows" / "ci.yml"
IDS = [case.id for case in UPSTREAM_CORPUS]
_CLEAN_GIT = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "HOME": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Maintainer",
    "GIT_AUTHOR_EMAIL": "maintainer@example.invalid",
    "GIT_COMMITTER_NAME": "Maintainer",
    "GIT_COMMITTER_EMAIL": "maintainer@example.invalid",
}


def _raw() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _entries() -> list[dict[str, object]]:
    entries = _raw()["candidates"]
    assert isinstance(entries, list)
    return [dict(e) for e in entries]


def _with(index: int, **changes: object) -> dict[str, object]:
    """The manifest with entry ``index`` changed (``None`` drops a key)."""
    data = _raw()
    entries = _entries()
    entry = entries[index]
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    data["candidates"] = entries
    return data


# ---------------------------------------------------------------------------
# The manifest, the keys, the contamination risk, the licences
# ---------------------------------------------------------------------------


def test_the_manifest_holds_the_mined_candidates_sorted_and_unique() -> None:
    assert len(UPSTREAM_CORPUS) == 30  # V9a kept 30 (25 low, 5 medium)
    assert IDS == sorted(IDS) and len(set(IDS)) == len(IDS)
    risks = [case.contamination_risk for case in UPSTREAM_CORPUS]
    assert risks.count("low") == 25 and risks.count("medium") == 5
    assert len(UPSTREAM_CORPUS) >= upstream.MIN_CANDIDATES  # the owner's 8
    for case in UPSTREAM_CORPUS:
        assert case.id.startswith(f"{case.lib}-"), case.id
        assert case.verified is None  # no verification has run yet
        assert case.bench_path == f"benchmarks/bench_{case.lib}.py"


@pytest.mark.parametrize("case", UPSTREAM_CORPUS, ids=IDS)
def test_every_key_is_sealed_with_the_hash_the_manifest_records(
    case: UpstreamCase,
) -> None:
    data = case.key_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == case.key.sha256
    assert case.key_path == KEYS_DIR / f"{case.id}.patch"
    assert case.key.fix_sha != case.before_sha
    # A plain git diff of exactly the touched source files, nothing else.
    text = data.decode("utf-8")
    pairs = re.findall(r"^diff --git a/(\S+) b/(\S+)$", text, re.MULTILINE)
    assert pairs and all(a == b for a, b in pairs), pairs
    assert [a for a, _ in pairs] == list(case.touched_files)
    assert all(path.startswith(f"{case.module_root}/") for path in case.touched_files)
    assert "GIT binary patch" not in text and "\nrename from " not in text


@pytest.mark.parametrize("case", UPSTREAM_CORPUS, ids=IDS)
def test_nothing_the_engine_sees_carries_the_miners_id(case: UpstreamCase) -> None:
    """The ids were written by the miner, who knew each fix ("ascii-fastpath",
    "str-cache", "no-early-peek"): under O19 the attempter never sees one.
    The project, the workload, its argv, the benchmark path and the copied
    workload's text name the library only. A name the blind writer was
    given (a touched file or function, e.g. ``nth_permutation``) may stay."""
    hint = case.id.removeprefix(f"{case.lib}-")
    project = case.project(Path("/repo"))
    workload = case.workload(project)
    seen = (project.name, workload.name, case.bench_path, *workload.command)
    source = case.workload_source.read_text(encoding="utf-8")
    given = " ".join(
        [
            *case.touched_files,
            *(f for fs in case.touched_functions.values() for f in fs),
        ]
    )
    for spelling in {case.id, hint, case.id.replace("-", "_"), hint.replace("-", "_")}:
        assert not [text for text in seen if spelling in text], spelling
        assert spelling not in source or spelling in given, spelling
    assert project.name == workload.name == case.lib
    assert case.bench_path == f"benchmarks/bench_{case.lib}.py"


def test_the_keys_directory_holds_exactly_one_key_per_candidate() -> None:
    assert {p.name for p in KEYS_DIR.iterdir()} == {f"{i}.patch" for i in IDS}
    assert all(p.is_file() and not p.is_symlink() for p in KEYS_DIR.iterdir())


def test_contamination_risk_is_recorded_against_the_shared_cutoff() -> None:
    """``low``: authored and committed after every attempter model's cutoff;
    ``medium``: either date before it (a small, little-discussed fix);
    ``high`` (a famous fix) is no exam and is refused by the loader."""
    assert _raw()["cutoff"] == upstream.CUTOFF.isoformat() == "2026-06-30"
    for case in UPSTREAM_CORPUS:
        after = min(case.key.commit_date, case.key.author_date) > upstream.CUTOFF
        assert (case.contamination_risk == "low") is after, case.id
        assert len(case.contamination_reason) > 40, case.id
    boltons = next(c for c in UPSTREAM_CORPUS if c.lib == "boltons")
    assert boltons.contamination_risk == "medium"  # authored before, committed after
    assert boltons.key.commit_date > upstream.CUTOFF > boltons.key.author_date


@pytest.mark.parametrize("case", UPSTREAM_CORPUS, ids=IDS)
def test_licences_are_on_the_allowlist(case: UpstreamCase) -> None:
    operands = case.licence.split(" OR ")
    assert all(op in PERMISSIVE_LICENSES for op in operands), case.licence
    assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", case.license_file)
    assert upstream.licence_problem(case, "Copyleft text only") is not None
    phrase = upstream.LICENCE_PHRASES[operands[-1]]
    wrapped = phrase.replace(" ", "\n   ", 2)  # a phrase broken across lines
    assert upstream.licence_problem(case, f"Header\n{wrapped}\n") is None


def test_requirements_are_hash_pinned_and_each_one_is_needed() -> None:
    lines = [
        line
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    pinned = {}
    for line in lines:
        found = re.fullmatch(
            r"([a-z0-9][a-z0-9._-]*)==([0-9][0-9a-z.]*)( --hash=sha256:[0-9a-f]{64})+",
            line,
        )
        assert found is not None, line
        pinned[found.group(1)] = found.group(2)
    lock = (SERVICE_DIR / "uv.lock").read_text(encoding="utf-8")
    needed = {name for case in UPSTREAM_CORPUS for name in case.requires}
    for name in needed:
        assert name in pinned or f'name = "{name}"' in lock, name
    assert set(pinned) <= needed  # nothing installed that no candidate needs
    assert set(pinned) == {"beautifulsoup4", "numpy"}


def test_the_parsed_corpus_is_the_module_constant() -> None:
    assert parse_manifest(_raw()) == UPSTREAM_CORPUS


AI_SET = {"mistune-footnote-membership"}  # "Generated-by: blackhole-agent ..."
CLAUDE_SET = {  # the commits name Claude models: the attempter's own family
    "pypdf-clone-direct-objects",
    "sqlglot-unnest-type-memo",
    "sqlparse-group-comments",
    "sqlparse-reindent-offset",
}
HINTS = {  # what the before-tree the engine is handed shows (review, V9)
    "attrs-astuple-atomic": "hot_shape",
    "markdown-hash-header-regex": "same_class",
    "markdown-inline-rescan": "same_class",
    "markdown-toc-unique-ids": "same_class",
    "markdown_it-inline-pending": "same_class",
    "mistune-footnote-membership": "same_class",
    "mistune-nested-lists": "same_class",
    "mpmath-bin-to-radix-pow2": "fix_idea",
    "packaging-marker-str-cache": "hot_shape",
    "sqlparse-group-comments": "same_class",
    "sqlparse-reindent-offset": "same_class",
}
RELEASE_NOTES = {  # the medium fixes whose own release notes name them
    "packaging-simple-version-fastpath": "CHANGELOG.rst",
    "pyparsing-results-copy": "CHANGES",
    "tomlkit-inline-table-render": "CHANGELOG.md",
    "wcwidth-wcswidth-ascii": "docs/intro.rst",
}


def test_who_wrote_each_key_is_recorded_and_claude_keys_are_apart() -> None:
    """O19: a key a Claude model wrote shares the attempter's family, so its
    result is never pooled with the maintainers' (``setter``, ``pool``)."""
    setters = {case.id: upstream.setter(case) for case in UPSTREAM_CORPUS}
    assert {i for i, s in setters.items() if s == "claude"} == CLAUDE_SET
    assert {i for i, s in setters.items() if s == "ai"} == AI_SET
    assert list(setters.values()).count("human") == 25
    for case in UPSTREAM_CORPUS:
        assert (setters[case.id] == "human") is (not case.key.ai_assisted), case.id
        assert upstream.pool(case).startswith(f"{setters[case.id]}, "), case.id
    pypdf = next(c for c in UPSTREAM_CORPUS if c.id == "pypdf-clone-direct-objects")
    assert pypdf.key.ai_assisted == ("Claude Opus 5.5", "Claude Sonnet 5.5")
    assert upstream.pool(pypdf) == "claude, no hint"


def test_hints_in_the_before_tree_are_recorded_with_their_evidence() -> None:
    """A hit on an exam whose before-tree names the fix idea (a TODO), holds
    a maintainer benchmark of the exact hot shape, or whose changelog names
    the same class of fix, is discounted: the pool says which."""
    found = {
        case.id: case.hint_in_before.kind
        for case in UPSTREAM_CORPUS
        if case.hint_in_before is not None
    }
    assert found == HINTS
    tiers = {"fix_idea": "direct", "hot_shape": "direct", "same_class": "class"}
    for case in UPSTREAM_CORPUS:
        hint = case.hint_in_before
        if hint is None:
            assert upstream.pool(case).endswith(", no hint"), case.id
            continue
        assert upstream.pool(case).endswith(f", {tiers[hint.kind]} hint"), case.id
        assert re.match(r"[A-Za-z0-9_./-]+:\d+(,\d+)*: ", hint.evidence), case.id
    mpmath = next(c for c in UPSTREAM_CORPUS if c.id == "mpmath-bin-to-radix-pow2")
    assert mpmath.hint_in_before is not None
    todo = "# TODO: speed up for bases 2, 4, 8, 16, ..."
    assert todo in mpmath.hint_in_before.evidence
    assert f"\n-{todo}\n" in mpmath.key_path.read_text(encoding="utf-8")
    assert upstream.pool(mpmath) == "human, direct hint"


def test_medium_reasons_say_where_the_fix_was_announced() -> None:
    """The medium fixes are in their projects' release notes before the
    cutoff, so the reasons say so; none claims no release notes were found."""
    for case in UPSTREAM_CORPUS:
        reason = case.contamination_reason
        assert "no release notes or blog coverage found" not in reason, case.id
        if case.id in RELEASE_NOTES:
            assert case.contamination_risk == "medium", case.id
            assert f"{RELEASE_NOTES[case.id]} " in reason, case.id
            assert "release notes" in reason and "training data" in reason, case.id
    boltons = next(c for c in UPSTREAM_CORPUS if c.lib == "boltons")
    assert "26.1.0" in boltons.contamination_reason  # its note: after the cutoff


def _swap_key_sha(index: int) -> dict[str, object]:
    key = dict(_entries()[index]["key"])  # type: ignore[call-overload]
    key["sha256"] = "0" * 64
    return _with(index, key=key)


def _key_patch(index: int, patch: str) -> dict[str, object]:
    key = dict(_entries()[index]["key"])  # type: ignore[call-overload]
    key["patch"] = patch
    return _with(index, key=key)


def _key_date(index: int, when: str) -> dict[str, object]:
    key = dict(_entries()[index]["key"])  # type: ignore[call-overload]
    key["author_date"] = when
    return _with(index, key=key)


def _key_field(index: int, **changes: object) -> dict[str, object]:
    key = dict(_entries()[index]["key"])  # type: ignore[call-overload]
    key.update(changes)
    return _with(index, key=key)


def _reordered(first: int, second: int) -> dict[str, object]:
    """The manifest with entries ``first`` and ``second`` leading."""
    entries = _entries()
    return _raw() | {"candidates": [entries[first], entries[second], *entries[2:]]}


def _verified(**values: object) -> dict[str, object]:
    record: dict[str, object] = {
        "run_id": "40400000001",
        "gain": 0.31,
        "noise_floor": 0.04,
        "threshold": 0.10,
        "workload_sha256": hashlib.sha256(
            (WORKLOADS_DIR / f"{UPSTREAM_CORPUS[0].id}.py").read_bytes()
        ).hexdigest(),
    }
    record.update(values)
    return _with(0, verified=record)


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (_with(0, id="Attrs_Bad"), "id"),
        (_with(0, url="https://gitlab.com/a/b.git"), "url"),
        (_with(0, before_sha="0a08cee"), "before_sha"),
        (_with(0, licence="GPL-3.0-only"), "licence"),
        (_with(0, licence="MIT OR GPL-3.0-only"), "licence"),
        (_with(0, module_root="lib/attr"), "module_root"),
        (_with(0, touched_files=["tests/test_funcs.py"]), "touched_files"),
        (_with(0, contamination_risk="high"), "contamination_risk"),
        (_with(0, contamination_risk="medium"), "contamination_risk"),
        (_key_date(0, "2026-05-01T00:00:00+00:00"), "contamination_risk"),
        (_with(0, test_command=["sh", "-c", "pytest"]), "test_command"),
        (_with(0, setup_files={"../x.py": "x = 1\n"}), "setup_files"),
        (_with(0, setup_files={"src/attr/_v.py": "x" * 300}), "setup_files"),
        (_with(0, requires=["Bad Name"]), "requires"),
        (_with(0, verified={"run_id": "1"}), "verified"),
        (_verified(threshold=0.05), "verified"),
        (_verified(gain=0.09), "verified"),
        (_verified(noise_floor=0.08, threshold=0.10), "verified"),
        (_verified(workload_sha256="0" * 64), "workload"),
        (_verified(workload_sha256="x"), "workload"),
        (_with(0, hint_in_before="a TODO"), "hint_in_before"),
        (_with(0, hint_in_before={"kind": "vibes", "evidence": "a.py:1: x"}), "kind"),
        (_with(0, hint_in_before={"kind": "fix_idea", "evidence": "no cite"}), "evid"),
        (_with(0, hint_in_before={"kind": "fix_idea"}), "hint_in_before"),
        (_with(0, hint_in_before=None), "keys"),
        (_with(0, requires_python="3.12"), "requires_python"),
        (_key_field(0, ai_assisted="Claude Opus 5.5"), "ai_assisted"),
        (_key_field(0, ai_assisted=["Claude\nOpus"]), "ai_assisted"),
        (_swap_key_sha(0), "sha256"),
        (_key_patch(0, "../../live_oss/manifest.json"), "patch"),
        (_with(0, extra="x"), "keys"),
        (_with(0, drops_submodules="no"), "drops_submodules"),
        (_reordered(0, 0), "unique"),
        (_reordered(1, 0), "sorted"),
    ],
)
def test_parse_manifest_refuses_a_malformed_entry(
    data: dict[str, object], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        parse_manifest(data)


def test_parse_manifest_refuses_a_bad_shape_or_a_missing_workload(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="candidates"):
        parse_manifest({"cutoff": "2026-06-30"})
    short = _raw() | {"candidates": _entries()[:7]}
    with pytest.raises(ValueError, match="at least 8"):
        parse_manifest(short)
    with pytest.raises(ValueError, match="no workload"):
        parse_manifest(_raw(), workloads=tmp_path)
    with pytest.raises(ValueError, match="no key"):
        parse_manifest(_raw(), keys=tmp_path)


def test_a_verified_record_is_held_to_the_verification_rule() -> None:
    (case, *_) = parse_manifest(_verified())
    sha = UPSTREAM_CORPUS[0].workload_sha256
    assert case.verified == Verified("40400000001", 0.31, 0.04, 0.10, sha)
    assert sha == hashlib.sha256(case.workload_source.read_bytes()).hexdigest()
    assert case.verified.threshold == threshold(0.04)
    assert live_cases({}, parse_manifest(_verified())) == (case,)
    assert live_cases({}) == ()  # nothing is verified yet


# ---------------------------------------------------------------------------
# The workloads
# ---------------------------------------------------------------------------

BANNED_MODULES = frozenset(
    {"os", "sys", "time", "datetime", "socket", "subprocess", "shutil", "threading"}
    | {"multiprocessing", "urllib", "http", "tempfile", "secrets", "uuid", "ctypes"}
)
BANNED_NAMES = frozenset({"open", "input", "exec", "eval", "__import__", "compile"})


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            found.add(node.module.split(".")[0])
    return found


def test_the_workloads_directory_holds_one_workload_per_candidate() -> None:
    names = {p.name for p in WORKLOADS_DIR.iterdir() if p.name != "__pycache__"}
    assert names == {f"{i}.py" for i in IDS} | {"README.md"}


@pytest.mark.parametrize("case", UPSTREAM_CORPUS, ids=IDS)
def test_every_workload_parses_is_deterministic_and_times_the_checkout(
    case: UpstreamCase,
) -> None:
    source = case.workload_source.read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 11))  # the oldest CI CPython
    imports = _imports(tree)
    assert case.package in imports, imports
    assert not imports & BANNED_MODULES, imports & BANNED_MODULES
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "random":
                assert node.func.attr == "Random", ast.unparse(node)
                (seed,) = node.args
                assert isinstance(seed, ast.Constant) and isinstance(seed.value, int)
        if isinstance(node, ast.Name):
            assert node.id not in BANNED_NAMES, (case.id, node.id)
    parts = [*case.module_root.split("/"), "__init__.py"]
    assert "PACKAGE_INIT = ROOT / " + " / ".join(f'"{p}"' for p in parts) in source
    assert ".__file__).resolve() != PACKAGE_INIT:" in source
    assert "_checked()" in source and 'if __name__ == "__main__":' in source
    assert "sha256=" in source


DOCSTRING_LEAKS = ("upstream", "exercises", "maintainer", "hence")
"""Words a copied docstring must not carry: they say a known fix exists."""


def _identifiers(tree: ast.Module) -> set[str]:
    """Every name the code uses; the docstring is a constant, so none of it."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name.rsplit(".", 1)[-1])
    return found


def _word(text: str, name: str) -> bool:
    """``name`` as a whole word of ``text`` (``clone`` is not ``clone_from``)."""
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])"
    return re.search(pattern, text) is not None


@pytest.mark.parametrize("case", UPSTREAM_CORPUS, ids=IDS)
def test_the_copied_workload_names_the_library_not_the_fix(
    case: UpstreamCase,
) -> None:
    """The attempter reads the copied file as ``benchmarks/bench_<lib>.py``,
    docstring included (V9 review, 2026-10-30), so the docstring may describe
    the library, the public calls and the input shape, and nothing that says
    where the answer is or that one exists: no touched file, no touched
    private function anywhere in the file, no public touched function the
    code does not itself call (``astuple`` and ``nth_permutation`` are the
    API the workload times; ``HashHeaderProcessor`` is where the fix went),
    no other ``.py`` name, no "upstream" or "exercises". The coverage notes
    live in ``_notes/workloads.md``, which is never copied into a clone."""
    source = case.workload_source.read_text(encoding="utf-8")
    tree = ast.parse(source)
    doc = ast.get_docstring(tree, clean=False) or ""
    lib = case.lib.replace("-", "_").lower()
    first = doc[:80].replace("-", "_").lower()
    assert doc.startswith("OSS corpus benchmark: ") and lib in first, doc[:80]
    lowered = doc.lower()
    assert not [w for w in DOCSTRING_LEAKS if w in lowered], (case.id, lowered[:80])
    # "fix" and "fixes" say a fix exists; "a fixed seed" is fine.
    assert re.search(r"\bfix(es)?\b", lowered) is None, case.id
    assert "upstream" not in source.lower() and "_keys" not in source, case.id
    files = re.findall(r"[\w./-]+\.py\b", doc)
    assert files == [f"benchmarks/bench_{case.lib}.py"], files
    used = _identifiers(tree)
    for path in case.touched_files:
        assert path not in source, (case.id, path)
    for functions in case.touched_functions.values():
        for function in functions:
            if function == "<module>":
                continue
            if "." in function:  # Class.method: never spelled out
                assert function not in source, (case.id, function)
            last = function.rsplit(".", 1)[-1]
            if last.startswith("__") and last.endswith("__"):
                continue  # a dunder (__init__) is generic; the dotted form is checked
            if last.startswith("_"):
                assert not _word(source, last), (case.id, last)
            elif last not in used:
                assert not _word(doc, last), (case.id, last)


# ---------------------------------------------------------------------------
# The user's repository, on local bare upstreams over file://
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


SLOW = '''"""A tiny library with a quadratic hot spot."""


def unique(items):
    seen = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
'''
FAST = '''"""A tiny library with a quadratic hot spot."""


def unique(items):
    seen = set()
    found = []
    for item in items:
        if item not in seen:
            seen.add(item)
            found.append(item)
    return found
'''
SUITE = """import unittest

import pkg


class TestUnique(unittest.TestCase):
    def test_keeps_first_occurrences_in_order(self):
        self.assertEqual(pkg.unique([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_empty(self):
        self.assertEqual(pkg.unique([]), [])
"""
WORKLOAD = """import hashlib

import pkg

items = [i % 3000 for i in range(12000)]
found = pkg.unique(items)
print(f"unique={len(found)} sha256={hashlib.sha256(repr(found).encode()).hexdigest()}")
"""
MIT = "Permission is hereby granted, free of charge, to any person\n"


class Local:
    """A local upstream: history, the before-commit, the maintainer's fix."""

    def __init__(self, root: Path, files: Mapping[str, str] | None = None) -> None:
        self.root = root
        work = root / "upstream"
        tree = {
            "pkg/__init__.py": SLOW,
            "tests/__init__.py": "",
            "tests/test_pkg.py": SUITE,
            "LICENSE": MIT,
            **(files or {}),
        }
        _git(root, "init", "-q", "-b", "trunk", str(work))
        (work / "README").write_text("old history\n", encoding="utf-8")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", "an older commit")
        self.older = _git(work, "rev-parse", "HEAD")
        for rel, text in tree.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text, encoding="utf-8")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", "the before-commit")
        self.before = _git(work, "rev-parse", "HEAD")
        self.before_tree = _git(work, "rev-parse", "HEAD^{tree}")
        (work / "pkg" / "__init__.py").write_text(FAST, encoding="utf-8")
        _git(work, "commit", "-q", "-am", "perf: unique in linear time")
        self.fix = _git(work, "rev-parse", "HEAD")
        self.patch = _git(work, "diff", "--no-color", self.before, self.fix) + "\n"
        bare = root / "upstream.git"
        _git(root, "clone", "-q", "--bare", str(work), str(bare))
        self.url = f"file://{bare}"
        self.keys = root / "keys"
        self.keys.mkdir()
        self.workloads = root / "workloads"
        self.workloads.mkdir()

    def case(self, *, patch: str | None = None, **changes: object) -> UpstreamCase:
        base = UPSTREAM_CORPUS[0]
        case_id = "pkg-unique-set"
        key_file = self.keys / f"{case_id}.patch"
        key_file.write_text(patch or self.patch, encoding="utf-8")
        (self.workloads / f"{case_id}.py").write_text(WORKLOAD, encoding="utf-8")
        key = SealedKey(
            sha256=hashlib.sha256(key_file.read_bytes()).hexdigest(),
            fix_sha=self.fix,
            commit_date=base.key.commit_date,
            author_date=base.key.author_date,
        )
        fields: dict[str, object] = {
            "id": case_id,
            "lib": "pkg",
            "url": self.url,
            "before_sha": self.before,
            "package": "pkg",
            "module_root": "pkg",
            "license_file": "LICENSE",
            "touched_files": ("pkg/__init__.py",),
            "touched_functions": {"pkg/__init__.py": ("unique",)},
            "test_command": ("python", "-m", "unittest", "discover", "-s", "tests"),
            "requires": (),
            "setup_files": {},
            "drops_submodules": False,
            "key": key,
            "workloads": self.workloads,
            "keys": self.keys,
        }
        fields.update(changes)
        return replace(base, **fields)  # type: ignore[arg-type]


@pytest.fixture
def local(tmp_path: Path) -> Local:
    return Local(Path(os.path.realpath(tmp_path)))


def _tracked(path: Path) -> set[str]:
    return set(git(path, "ls-files").splitlines())


def test_the_user_repository_is_the_before_tree_with_no_history(local: Local) -> None:
    case = local.case()
    user = prepare_repo(case, local.root / "user", policy=LOCAL)
    path = user.path
    # Two commits: one root commit of the before-tree, then the benchmark.
    assert git(path, "rev-list", "--count", "HEAD") == "2"
    root = git(path, "rev-parse", "HEAD^")
    assert git(path, "rev-list", "--max-parents=0", "HEAD") == root
    assert git(path, "rev-parse", f"{root}^{{tree}}") == local.before_tree
    assert root != local.before  # the upstream commit id is not reused
    # No upstream object beyond the tree: not the fix, the before-commit or
    # any older commit, and nothing to fetch them from.
    for sha in (local.fix, local.before, local.older):
        found = subprocess.run(
            ["git", "-C", str(path), "cat-file", "-e", sha],
            env=_CLEAN_GIT,
            capture_output=True,
            check=False,
        )
        assert found.returncode != 0, sha
    assert not (path / ".git" / "shallow").exists()
    assert not (path / ".git" / "FETCH_HEAD").exists()
    assert git(path, "remote") == ""
    assert set(user.refs()) == {"refs/heads/main", *UNTOUCHED_REFS}
    assert "old history" not in git(path, "log", "--all", "--format=%B")
    # Nothing the miner named the case after: not in a message or a path.
    messages = git(path, "log", "--all", "--format=%B")
    assert "unique-set" not in messages and case.id not in messages
    assert git(path, "log", "-1", "--format=%s", "HEAD^") == "import pkg"
    assert not [p for p in _tracked(path) if "unique" in p or "set" in p]
    # The tracked files are the before-tree and the benchmark, never a key.
    before_files = set(_git(local.root / "upstream", "ls-tree", "-r", "--name-only", local.before).splitlines())  # fmt: skip
    assert _tracked(path) == before_files | {case.bench_path}
    assert not any(
        "_keys" in p.split("/") or p.endswith(".patch") for p in _tracked(path)
    )
    assert (path / case.bench_path).read_bytes() == case.workload_source.read_bytes()
    assert git(path, "status", "--porcelain", "--ignored") == ""
    assert sorted(p.name for p in local.root.iterdir()) == sorted(
        ["upstream", "upstream.git", "keys", "workloads", "user"]
    )  # no scratch fetch repository or git home left beside it
    again = prepare_repo(case, local.root / "again", policy=LOCAL)
    assert again.base == user.base  # deterministic


def test_prepare_commits_the_setup_files_with_the_benchmark(local: Local) -> None:
    case = local.case(setup_files={"pkg/_version.py": '__version__ = "0"\n'})
    user = prepare_repo(case, local.root / "user", policy=LOCAL)
    changed = git(user.path, "diff", "--name-only", "HEAD^", "HEAD").splitlines()
    assert sorted(changed) == sorted([case.bench_path, "pkg/_version.py"])
    assert (user.path / "pkg/_version.py").read_text() == '__version__ = "0"\n'


Change = Callable[[UpstreamCase], UpstreamCase]


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda c: replace(c, url="https://example.com/x.git"), "allowlist"),
        (lambda c: replace(c, before_sha="abc"), "full 40-hex"),
        (lambda c: replace(c, before_sha="1" * 40), "failed"),
        (lambda c: replace(c, setup_files={"pkg/__init__.py": "x = 1\n"}), "already"),
    ],
)
def test_prepare_refuses_and_leaves_nothing(
    local: Local, change: Change, match: str
) -> None:
    dest = local.root / "user"
    with pytest.raises(CloneRefusedError, match=match):
        prepare_repo(change(local.case()), dest, policy=LOCAL)
    assert not os.path.lexists(dest)
    with pytest.raises(CloneRefusedError, match="exists"):
        dest.mkdir()
        prepare_repo(local.case(), dest, policy=LOCAL)


def test_prepare_refuses_an_interpreter_outside_requires_python(
    local: Local,
) -> None:
    """A library is measured only on a CPython its maintainers support: the
    networkx before-trees need 3.12, so the CI suites run 3.12, which every
    candidate admits (``UPSTREAM_PYTHON``)."""
    dest = local.root / "user"
    with pytest.raises(CloneRefusedError, match="needs Python >=3.99"):
        prepare_repo(local.case(requires_python=">=3.99"), dest, policy=LOCAL)
    assert not os.path.lexists(dest)
    networkx = local.case(requires_python=">=3.12,!=3.14.1")
    for version in ("3.11.9", "3.14.1"):
        with pytest.raises(CloneRefusedError, match=f"this is {version}"):
            prepare_repo(networkx, dest, policy=LOCAL, python=version)
        assert not os.path.lexists(dest)
    user = prepare_repo(networkx, dest, policy=LOCAL, python="3.12.4")
    assert git(user.path, "rev-list", "--count", "HEAD") == "2"
    assert upstream.UPSTREAM_PYTHON == "3.12"
    for case in UPSTREAM_CORPUS:
        assert upstream.python_problem(case, "3.12.0") is None, case.id
        assert upstream.python_problem(case, "3.12.13") is None, case.id
    nx = [c for c in UPSTREAM_CORPUS if c.lib == "networkx"]
    assert len(nx) == 3
    assert all(upstream.python_problem(c, "3.11.14") for c in nx)
    assert upstream.python_problem(nx[0], "3.15.0rc1") is None  # a pre-release


def _with_submodule(local: Local) -> str:
    """A new before-commit in the bare upstream with a gitlink and
    ``.gitmodules``; its sha."""
    work = local.root / "upstream"
    (work / ".gitmodules").write_text(
        '[submodule "data"]\n\tpath = data\n\turl = https://example.invalid/d.git\n'
    )
    _git(work, "update-index", "--add", "--cacheinfo", f"160000,{local.older},data")
    _git(work, "add", ".gitmodules")
    _git(work, "commit", "-q", "-m", "a submodule")
    sha = _git(work, "rev-parse", "HEAD")
    _git(work, "push", "-q", str(local.root / "upstream.git"), "HEAD:refs/heads/sub")
    return sha


def test_submodules_are_dropped_only_when_the_manifest_says_so(local: Local) -> None:
    sha = _with_submodule(local)
    with pytest.raises(CloneRefusedError, match="drops_submodules"):
        prepare_repo(local.case(before_sha=sha), local.root / "a", policy=LOCAL)
    user = prepare_repo(
        local.case(before_sha=sha, drops_submodules=True),
        local.root / "b",
        policy=LOCAL,
    )
    tracked = _tracked(user.path)
    assert "data" not in tracked and ".gitmodules" not in tracked
    assert "pkg/__init__.py" in tracked
    with pytest.raises(CloneRefusedError, match="no submodule"):
        prepare_repo(local.case(drops_submodules=True), local.root / "c", policy=LOCAL)


def test_lfs_is_refused(tmp_path: Path) -> None:
    local = Local(
        Path(os.path.realpath(tmp_path)), {".gitattributes": "*.bin filter=lfs\n"}
    )
    with pytest.raises(CloneRefusedError, match="LFS"):
        prepare_repo(local.case(), local.root / "user", policy=LOCAL)


# ---------------------------------------------------------------------------
# The key commit (verification only)
# ---------------------------------------------------------------------------


def test_the_key_commit_is_the_fix_on_the_base_and_moves_nothing_else(
    local: Local,
) -> None:
    case = local.case()
    user = prepare_repo(case, local.root / "user", policy=LOCAL)
    before = user.snapshot()
    key = commit_key(user, case, policy=LOCAL)
    assert git(user.path, "rev-parse", f"{key}^") == user.base
    assert git(user.path, "diff", "--name-only", user.base, key) == "pkg/__init__.py"
    assert git(user.path, "show", f"{key}:pkg/__init__.py") + "\n" == FAST
    assert git(user.path, "rev-parse", KEY_REF) == key
    after = user.snapshot()
    assert (after.head, after.index_sha256, after.status) == (
        before.head,
        before.index_sha256,
        before.status,
    )


def test_a_key_whose_hash_changed_or_that_does_not_apply_is_refused(
    local: Local,
) -> None:
    case = local.case()
    user = prepare_repo(case, local.root / "user", policy=LOCAL)
    case.key_path.write_text(local.patch + "\n", encoding="utf-8")  # tampered
    with pytest.raises(CloneRefusedError, match="sha256"):
        commit_key(user, case, policy=LOCAL)
    stale = local.patch.replace("seen = []", "seen = [None]")
    bad = local.case(patch=stale)
    with pytest.raises(CloneRefusedError, match="does not apply"):
        commit_key(user, bad, policy=LOCAL)


# ---------------------------------------------------------------------------
# The gain, its threshold and the results table
# ---------------------------------------------------------------------------


def _rows(
    wall: list[float], fingerprint: str | None = "f" * 64
) -> tuple[Measurement, ...]:
    return (
        Measurement(
            workload_id="w",
            metric=METRIC_WALL_TIME_S,
            stats=RunStats.from_samples(wall, unit="s"),
            samples=tuple(wall),
            output_fingerprint=fingerprint,
        ),
    )


def _suite(passed: bool, count: int | None = 12) -> Measured:
    value = 1.0 if passed else 0.0
    row = Measurement(
        workload_id="w",
        metric=METRIC_TESTS_PASSED,
        stats=RunStats.from_samples([value], unit="bool"),
        samples=(value,),
    )
    return Measured((row,), tests_counted=count if passed else None)


def _block(a: float, b: float, *, fb: str | None = "f" * 64) -> AbabMeasured:
    return AbabMeasured(_rows([a] * 5), _rows([b] * 5, fb))


CAL = NoiseCalibration(blocks=3, gaps={"w:wall_time_s": 0.02}, floor=0.04)


def test_the_threshold_is_twice_the_floor_or_ten_percent() -> None:
    assert threshold(0.02) == 0.10 and threshold(0.04) == 0.10
    assert threshold(0.08) == pytest.approx(0.16)


def test_a_fix_that_clears_the_threshold_with_tests_and_output_is_verified() -> None:
    case = UPSTREAM_CORPUS[0]
    blocks = (_block(1.0, 0.70), _block(1.0, 0.72), _block(1.0, 0.68))
    found = summarize(case, CAL, blocks, _suite(True), _suite(True, 12), 9.5)
    assert found.verified and found.stopped is None
    assert found.gain == pytest.approx(0.30)
    assert found.threshold == 0.10 and found.margin == pytest.approx(0.20)
    assert found.block_gains == pytest.approx((0.30, 0.28, 0.32))
    assert (found.tests_base, found.tests_fixed) == (12, 12)
    row = found.row()
    assert row["verified"] is True and row["id"] == case.id
    assert json.dumps(row)  # one JSON line


@pytest.mark.parametrize(
    ("blocks", "suites", "why"),
    [
        ((_block(1.0, 0.95),), (True, True), "gain"),
        ((_block(1.0, 0.70, fb="e" * 64),), (True, True), "output"),
        ((_block(1.0, 0.70, fb=None),), (True, True), "output"),
        ((_block(1.0, 0.70),), (True, False), "tests"),
        ((_block(1.0, 0.70),), (False, True), "tests"),
    ],
)
def test_a_fix_short_of_any_condition_is_not_verified(
    blocks: tuple[AbabMeasured, ...], suites: tuple[bool, bool], why: str
) -> None:
    case = UPSTREAM_CORPUS[0]
    base, fixed = (_suite(passed) for passed in suites)
    found = summarize(case, CAL, blocks, base, fixed, 1.0)
    assert not found.verified
    assert why in found.why_not()


def test_a_stopped_candidate_is_recorded_with_its_reason() -> None:
    found = KeyResult.stopped_at(UPSTREAM_CORPUS[0], "the key does not apply", 2.0)
    assert not found.verified and found.gain is None
    assert found.why_not() == "stopped: the key does not apply"
    assert found.row()["stopped"] == "the key does not apply"


def test_rows_reach_the_sink_the_note_and_the_table(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    summary = tmp_path / "summary.md"
    sink = ResultsSink(
        {"LIVE_RESULTS_PATH": str(results), "GITHUB_STEP_SUMMARY": str(summary)}
    )
    recorder = VerifyRecorder(sink)
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    case = UPSTREAM_CORPUS[0]
    good = summarize(case, CAL, (_block(1.0, 0.7),), _suite(True), _suite(True), 3.0)
    recorder.record(good, run)
    recorder.record_error(UPSTREAM_CORPUS[1].id, run, "CloneRefusedError: boom|x")
    lines = [json.loads(x) for x in results.read_text().splitlines()]
    assert [x["kind"] for x in lines] == ["candidate", "error"]
    assert lines[0]["experiment"] == "upstream-verify"
    assert any(n.startswith(f"UPSTREAM {case.id}: verified") for n in run.notes)
    printed: list[str] = []
    recorder.finish(printed.append)
    table = summary.read_text()
    assert "| id | lib | risk | floor | threshold | gain | margin |" in table
    assert f"| {case.id} | attrs | low | 0.0400 | 0.1000 | 0.3000 | 0.2000 |" in table
    assert "boom\\|x" in table  # the cell is sanitised
    assert "1 of 1 verified" in table


# ---------------------------------------------------------------------------
# One whole verification, offline in the sandbox, on a local upstream
# ---------------------------------------------------------------------------


def _require_sandbox() -> None:
    problem = _sandbox_problem(sys.platform)
    if problem is not None:
        required = ("REQUIRE_NETWORK_SANDBOX", "REQUIRE_FS_SANDBOX")
        if any(os.environ.get(name) == "1" for name in required):
            pytest.fail(f"sandbox required but unavailable: {problem}")
        pytest.skip(f"the host cannot sandbox: {problem}")


@pytest.fixture
def verify_root(local: Local, monkeypatch: pytest.MonkeyPatch) -> Path:
    _require_sandbox()
    (local.root / "wt-root").mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", local.root / "wt-root")
    return local.root


def test_verify_case_measures_the_known_fix_in_the_sandbox(
    local: Local, verify_root: Path
) -> None:
    """The local "maintainer fix" (a set instead of a list) is much faster
    (well over 30 % with the interpreter's start-up counted): calibrated, paired ABBA, the suite at both sides; the guards hold
    (no request, only the verification phases, every launch sandboxed, the
    user's repository untouched). Whether the gain clears the threshold is
    load-dependent here (a busy host's A/A gaps raise the floor), so the
    verdict is checked against the rule, not assumed."""
    recorder = VerifyRecorder(ResultsSink({}))
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    found = verify_case(
        local.case(), run, verify_root, Isolation("required", None), recorder,
        policy=LOCAL, calibration_blocks=1, key_blocks=1,
    )  # fmt: skip
    assert found.stopped is None and found.output_equal, found.why_not()
    assert found.gain is not None and found.gain > 0.3
    assert found.floor is not None and found.threshold == threshold(found.floor)
    assert found.verified is (found.gain > found.threshold)
    assert len(found.block_gains) == 1
    assert found.tests_base == found.tests_fixed == 2
    assert recorder.results == [found] and recorder.errors == []
    assert run.capture.exchanges == [] and run.records == []


def test_verify_case_stops_on_a_key_that_breaks_the_workload(
    local: Local, verify_root: Path
) -> None:
    """A key whose code crashes the benchmark is a stopped row, not a crash."""
    broken = local.patch.replace("+    seen = set()", "+    raise SystemExit(3)")
    recorder = VerifyRecorder(ResultsSink({}))
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    found = verify_case(
        local.case(patch=broken), run, verify_root, Isolation("required", None),
        recorder, policy=LOCAL, calibration_blocks=1, key_blocks=1,
    )  # fmt: skip
    assert not found.verified and found.stopped is not None
    assert "key comparison could not be measured" in found.stopped
    assert recorder.results == [found]


def test_the_licence_file_is_read_without_following_a_link(tmp_path: Path) -> None:
    real = tmp_path / "LICENSE"
    real.write_text(MIT, encoding="utf-8")
    link = tmp_path / "LINKED"
    link.symlink_to(real)
    assert upstream_verify.licence_text(real) == MIT
    assert upstream_verify.licence_text(link) == ""
    assert upstream_verify.licence_text(tmp_path / "missing") == ""
    assert upstream_verify.licence_text(tmp_path) == ""


def test_verify_case_records_a_key_that_does_not_apply(
    local: Local, verify_root: Path
) -> None:
    recorder = VerifyRecorder(ResultsSink({}))
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    bad = local.case(patch=local.patch.replace("seen = []", "seen = [None]"))
    found = verify_case(
        bad, run, verify_root, Isolation("required", None), recorder, policy=LOCAL
    )
    assert not found.verified
    assert found.stopped is not None and "does not apply" in found.stopped


def test_a_failed_preparation_is_recorded_then_raised(
    local: Local, verify_root: Path
) -> None:
    recorder = VerifyRecorder(ResultsSink({}))
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    case = local.case(before_sha="2" * 40)
    with pytest.raises(CloneRefusedError):
        verify_case(case, run, verify_root, Isolation("required", None), recorder, policy=LOCAL)  # fmt: skip
    assert recorder.errors and recorder.errors[0][0] == case.id


def test_the_guards_refuse_a_request_another_phase_or_a_changed_repo(
    local: Local,
) -> None:
    user = prepare_repo(local.case(), local.root / "user", policy=LOCAL)
    before = user.snapshot()
    run = LiveRun("offline", VERIFY_RUN_CAP_USD)
    launches = LaunchLog()
    with pytest.raises(AssertionError, match="no launch"):
        check_verify_guards(run, user, before, launches, Isolation("required", None))
    with pytest.raises(AssertionError, match="isolation"):
        check_verify_guards(run, user, before, launches, Isolation("best_effort", "x"))
    (user.path / "pkg" / "__init__.py").write_text("changed\n", encoding="utf-8")
    launches.launches.append(Launch("preflight", "required", "required", True, True))
    with pytest.raises(AssertionError, match="user repository changed"):
        check_verify_guards(run, user, before, launches, Isolation("required", None))
    launches.launches.append(Launch("trial-1", "required", "required", True, True))
    with pytest.raises(AssertionError, match="phases"):
        check_verify_guards(run, user, before, launches, Isolation("required", None))
    assert VERIFY_PHASES == {"preflight", "calibrate", "twin-calibrate"} | {
        "upstream-base", "upstream-fixed",
    }  # fmt: skip


# ---------------------------------------------------------------------------
# The live suite: wired, verified candidates only, a per-run cap
# ---------------------------------------------------------------------------


def _no_wire(request: httpx2.Request) -> httpx2.Response:
    raise AssertionError(f"building the loop sent {request.url}")


def test_start_upstream_loop_is_wired_on_the_captured_wire(
    local: Local, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = local.root
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", UPSTREAM_RUN_CAP_USD, wire=httpx2.MockTransport(_no_wire))
    case = local.case()
    loop = start_upstream_loop(
        case, run, root, Isolation("required", None), policy=LOCAL
    )
    assert loop.mode == "wired" and loop.candidates == ()
    assert loop.context.generator is not None
    assert loop.cap_usd == UPSTREAM_RUN_CAP_USD == 5.0
    assert loop.project.test_command == case.test_command
    assert loop.workload.command == ("python", case.bench_path)
    assert loop.repo.name == case.id and loop.repo.expected == "none"
    assert git(loop.user.path, "rev-list", "--count", "HEAD") == "2"
    assert not any("_keys" in p for p in _tracked(loop.user.path))
    assert loop.before == loop.user.snapshot()
    assert run.capture.exchanges == [] and run.records == []


def _outcome(case_id: str, delivered: bool, guard: str = "ok") -> CorpusOutcome:
    return CorpusOutcome(
        repo=case_id, kind="slowdown", expected="none", status="done",
        engine_model="claude-opus-5-5", served_models=(),
        kept=("h1",) if delivered else (), delivered=delivered, aimed_kept=False,
        gain_pct=20.0 if delivered else None, best_trial_gain_pct=None,
        cost_usd=1.0, cap_usd=5.0, trials=2, violations=(), guard=guard,
        mode="wired",
    )  # fmt: skip


def test_the_live_summary_reports_each_pool_apart(tmp_path: Path) -> None:
    """Human keys with no hint are the scored pool; Claude-written keys and
    hinted exams are counted beside them, never pooled with them (O19)."""
    outcomes = [
        _outcome("idna-uts46-ascii-fastpath", True),
        _outcome("boltons-multireplace-lastgroup", False),
        _outcome("tomlkit-inline-table-render", True, guard="breach: x"),
        _outcome("mpmath-bin-to-radix-pow2", True),
        _outcome("markdown_it-inline-pending", False),
        _outcome("pypdf-clone-direct-objects", True),
        _outcome("sqlparse-group-comments", True),
        _outcome("mistune-footnote-membership", False),
    ]
    text = upstream.pools_markdown(UPSTREAM_CORPUS, outcomes)
    lines = text.splitlines()
    assert "| pool | runs | delivered | rate | ids |" in lines
    rows = [line for line in lines if line.startswith("| ") and "runs" not in line]
    assert [row.split(" | ")[0] for row in rows[1:]] == [
        "| human, no hint", "| human, class hint", "| human, direct hint",
        "| ai, class hint", "| claude, no hint", "| claude, class hint",
    ]  # fmt: skip
    assert rows[1].startswith("| human, no hint | 3 | 1 | 33% | ")
    assert "| human, class hint | 1 | 0 | 0% | markdown_it-inline-pending |" in lines
    assert "| human, direct hint | 1 | 1 | 100% | mpmath-bin-to-radix-pow2 |" in lines
    assert "| claude, no hint | 1 | 1 | 100% | pypdf-clone-direct-objects |" in lines
    assert any(line.startswith("Scored: human, no hint") for line in lines)
    with pytest.raises(ValueError, match="not an upstream candidate"):
        upstream.pools_markdown(UPSTREAM_CORPUS, [_outcome("pkg-unique-set", True)])
    summary = tmp_path / "summary.md"
    printed: list[str] = []
    upstream.write_pools(UPSTREAM_CORPUS, [], {"GITHUB_STEP_SUMMARY": str(summary)}, printed.append)  # fmt: skip
    assert printed == [] and not summary.exists()  # no run, no table
    upstream.write_pools(UPSTREAM_CORPUS, outcomes, {"GITHUB_STEP_SUMMARY": str(summary)}, printed.append)  # fmt: skip
    assert summary.read_text(encoding="utf-8") == text + "\n"
    assert "| human, direct hint | 1 | 1 | 100% | mpmath-bin-to-radix-pow2 |" in printed


def test_batches_of_ten_and_the_need_of_one_batch() -> None:
    assert BATCH_SIZE == 10
    assert batch(UPSTREAM_CORPUS, {}) == UPSTREAM_CORPUS[:10]
    assert batch(UPSTREAM_CORPUS, {BATCH_ENV: "3"}) == UPSTREAM_CORPUS[20:30]
    for bad in ("0", "4", "x", "1;id", ""):
        with pytest.raises(ValueError, match=BATCH_ENV):
            batch(UPSTREAM_CORPUS, {BATCH_ENV: bad})
    assert live_need() == BATCH_SIZE * UPSTREAM_RUN_CAP_USD == 50
    assert upstream_verify.verify_need() == VERIFY_RUN_CAP_USD == 0


def test_the_live_modules_run_what_this_file_checks() -> None:
    live = (TESTS_DIR / "live" / "test_upstream_live.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.live" in live
    assert "live_cases(os.environ)" in live and "live(UPSTREAM_RUN_CAP_USD)" in live
    assert 'recorder.mode != "wired"' in live and "check_loop_guards(" in live
    verify = (TESTS_DIR / "live" / "test_upstream_verify_live.py").read_text(
        encoding="utf-8"
    )
    assert "pytestmark = pytest.mark.live" in verify
    assert "batch(UPSTREAM_CORPUS, os.environ)" in verify
    assert "live(VERIFY_RUN_CAP_USD)" in verify and "verify_case(" in verify


# ---------------------------------------------------------------------------
# The CI patches (V9-lead): these fail until the Lead applies them
# ---------------------------------------------------------------------------


def _run_step() -> str:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    start = text.index("      - name: Run live tests")
    return text[start : text.index("      - name: Upload live corpus", start)]


def test_ci_runs_both_upstream_suites() -> None:
    """Fails until the Lead applies ``V9-lead/ci.yml.patch``."""
    step = _run_step()
    verify = re.search(
        r"^ *upstream-verify\) paths=\(tests/live/test_upstream_verify_live\.py\);"
        r" need=0 ;;$",
        step,
        re.M,
    )
    assert verify is not None, "apply the V9-lead ci.yml patch"
    assert re.search(
        r"^ *upstream\) paths=\(tests/live/test_upstream_live\.py\); need=50 ;;$",
        step,
        re.M,
    )
    assert "upstream_corpus/requirements.txt" in step
    assert "--require-hashes" in step and "--only-binary :all:" in step
    rule = re.search(r"^ *(.*\bupstream-verify\b.*)\) noise_rule=(\w+) ;;$", step, re.M)
    assert rule is not None and rule.group(2) == "step3"
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    minutes = upstream_verify.VERIFY_JOB_MINUTES
    assert f"inputs.suite == 'upstream-verify' && {minutes}" in text
    assert f"inputs.suite == 'upstream' && {upstream.LIVE_JOB_MINUTES}" in text
    assert "upstream-verify 0" in text and "upstream 50" in text


def test_the_corpus_guards_know_both_suites() -> None:
    """Fails until the Lead applies ``V9-lead/test_corpus_guards.py.patch``."""
    guards = (TESTS_DIR / "live" / "test_corpus_guards.py").read_text(encoding="utf-8")
    assert '"upstream-verify",' in guards, "apply the V9-lead corpus guards patch"
    assert '"upstream-verify": upstream_verify.verify_need(),' in guards
    assert '"upstream": upstream.live_need(),' in guards


def test_ci_runs_the_upstream_suites_on_a_python_every_candidate_admits() -> None:
    """Fails until the Lead applies ``V9-lead/ci.yml.patch``: the live job's
    interpreter is 3.12 for both upstream suites (networkx needs it) and
    3.11 otherwise, and setup-python follows it."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    job = text[text.index("\n  live-smoke:") : text.index("\n  schema-apply:")]
    choice = (
        "UV_PYTHON: ${{ (inputs.suite == 'upstream' || inputs.suite =="
        f" 'upstream-verify') && '{upstream.UPSTREAM_PYTHON}' || '3.11' }}}}"
    )
    assert choice in job, "apply the V9-lead ci.yml patch"
    assert "python-version: ${{ env.UV_PYTHON }}" in job
    assert "UV_PYTHON: '3.11'" not in job


def test_numpy_is_pinned_for_both_interpreters() -> None:
    """Fails until the Lead applies ``V9-lead/requirements.txt.patch``: the
    numpy wheel for CPython 3.12 (the upstream suites) beside 3.11's."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    (line,) = [x for x in text.splitlines() if x.startswith("numpy==")]
    cp311 = "89cd468399cfd2504718f0ba50e410dca55a170b61a02ad92bb18c8a65186e93"
    cp312 = "90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853"
    assert f"--hash=sha256:{cp311}" in line
    assert f"--hash=sha256:{cp312}" in line, "apply the V9-lead requirements patch"


def test_the_verify_rows_and_table_name_each_pool() -> None:
    """Fails until the Lead applies ``V9-lead/upstream_verify.py.patch``:
    every row carries the candidate's pool and its workload's sha256 (the
    Lead copies it into ``verified``), and the table has a pool column."""
    pypdf = next(c for c in UPSTREAM_CORPUS if c.id == "pypdf-clone-direct-objects")
    found = summarize(pypdf, CAL, (_block(1.0, 0.7),), _suite(True), _suite(True), 1.0)
    row = found.row()
    assert row.get("pool") == "claude, no hint", "apply the V9-lead verify patch"
    assert row["workload_sha256"] == pypdf.workload_sha256
    stopped = KeyResult.stopped_at(pypdf, "the key does not apply", 1.0).row()
    assert (stopped["pool"], stopped["workload_sha256"]) == (
        "claude, no hint", pypdf.workload_sha256,
    )  # fmt: skip
    recorder = VerifyRecorder(ResultsSink({}))
    recorder.record(found, LiveRun("offline", VERIFY_RUN_CAP_USD))
    recorder.record_error("x-y", LiveRun("offline", VERIFY_RUN_CAP_USD), "boom")
    table = recorder.markdown().splitlines()
    assert table[2].endswith("| why not | pool |")
    assert table[4].endswith("| - | claude, no hint |")
    assert table[5].count("|") == table[2].count("|")


def test_the_live_suite_writes_the_pools() -> None:
    """Fails until the Lead applies ``V9-lead/test_upstream_live.py.patch``."""
    live = (TESTS_DIR / "live" / "test_upstream_live.py").read_text(encoding="utf-8")
    assert "write_pools(CASES, corpus.outcomes, os.environ, print)" in live, (
        "apply the V9-lead upstream live patch"
    )
