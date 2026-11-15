"""UEQ (O71 item 2): the record-only equivalence gate of the X2-DT runs.

Two layers. Always (offline, no key, the real sandbox): a fixture library
``eqfix`` written into ``tmp_path`` with its own adapter file
(``EquivSettings.adapter``), run through the engine's ``run_once`` exactly
as the four libraries are: base against base, a planted rare-input fault
caught and minimised, tuple for list (type-aware against
``json.dumps(default=str)``), both timeouts, the record's schema, no
network, the archive walk of ``equiv_rows`` on a real git clone; then the
child's code in-process (generators draw for draw, seeds and workloads on
synthetic trees, the fingerprint, the alarm) and the parent's error paths
with ``run_once`` swapped. With the four pinned libraries (``REAL``:
``X2_EQUIV_LIBS`` names a directory of clones at the manifest's pins, or
``LIVE_OSS_NETWORK=1`` clones them): base against base, one planted
fault each from the audit's ``calibrate_mut.py`` (tomli's is the audit's
M8 shape, ``1__0``), and tomli's tuple for list.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from autonomous_ai_agents.execution.procrun import RunFailure, RunSample

from . import oss
from . import x2_equiv as xe
from .x2_patches import PATCH_DIR

TINY = xe.Size(120, 20, 20)
RECORD_KEYS = {"status", "fingerprint", "cases", "mismatches", "groups", "kinds",
               "timeouts", "counterexample", "seconds", "timed_out", "error",
               "corpus_sha256"}  # fmt: skip
EXAMPLE_KEYS = {"case", "group", "mode", "input", "input_chars", "minimised_chars",
                "reproduced", "rounds", "base", "trial"}  # fmt: skip

# ---------------------------------------------------------------------------
# The fixture library and its adapter file
# ---------------------------------------------------------------------------

LIBRARY = """
import sys, time
CALLS = [0]

def parse(text):
    CALLS[0] += 1
    if text.startswith("LOOP"):
        while True:
            pass
    if "!" in text:
        raise ValueError(f"bang at {text.index('!')}")
    words = text.split(" ")
    return {"words": WORDS(words), "n": COUNT(text)}

WORDS = list
COUNT = len
"""
ADAPTER = """
import random
WORDS = ["alpha", "beta", "gamma", "delta", "x", "\\x0b"]

class A:
    package, src, workload_mode, unit = "eqfix", False, "a", "\\n"

    def generate(self, rng):
        PRELUDE
        return "a", " ".join(rng.choice(WORDS) for _ in range(rng.randint(0, 6)))

    def seeds(self, tree):
        return [("a", p.read_text()) for p in sorted((tree / "tests").glob("*.txt"))]

    def workload(self, tree):
        p = tree / "benchmarks" / "input.txt"
        return p.read_text() if p.is_file() else None

    def mutate(self, rng, s):
        i = rng.randrange(len(s) + 1)
        return s[:i] + rng.choice([" ", "x", "!"]) + s[i:]

    def evaluator(self):
        import eqfix
        return lambda mode, s: [lambda: eqfix.parse(s)]

ADAPTER = A()
"""


def make_library(root: Path, *, words: str = "list", count: str = "len",
                 seeds: Sequence[str] = ("alpha beta", "gamma")) -> Path:  # fmt: skip
    (root / "eqfix").mkdir(parents=True)
    body = LIBRARY.replace("WORDS = list", f"WORDS = {words}")
    (root / "eqfix" / "__init__.py").write_text(
        body.replace("COUNT = len", f"COUNT = {count}")
    )
    (root / "tests").mkdir()
    for i, text in enumerate(seeds):
        (root / "tests" / f"s{i}.txt").write_text(text)
    (root / "benchmarks").mkdir()
    (root / "benchmarks" / "input.txt").write_text("alpha beta\ngamma delta\nx x\n")
    return root


def make_adapter(path: Path, prelude: str = "pass") -> Path:
    path.write_text(ADAPTER.replace("PRELUDE", prelude))
    return path


# A rare-input fault: the count is off by one when the text holds a \x0b.
RARE_FAULT = "lambda t: len(t) + ('\\x0b' in t)"


@pytest.fixture
def lib(tmp_path: Path) -> tuple[Path, xe.EquivSettings]:
    base = make_library(tmp_path / "base")
    cfg = xe.EquivSettings(size=TINY, adapter=make_adapter(tmp_path / "adapter.py"))
    return base, cfg


def gate(
    tmp_path: Path, base: Path, cfg: xe.EquivSettings, name: str = "work"
) -> xe.Equivalence:
    return xe.Equivalence("eqfix", base, tmp_path / name, cfg)


def variant(tmp_path: Path, name: str, **kw: Any) -> Path:
    return make_library(tmp_path / name, **kw)


NO_ID = object()  # a record straight from ``Equivalence.record``: no trial_id


def check_schema(record: Mapping[str, object], trial_id: object = NO_ID) -> None:
    """``trial_id``: a row of ``equiv_rows``, which carries exactly that id."""
    keys = RECORD_KEYS if trial_id is NO_ID else RECORD_KEYS | {"trial_id"}
    assert set(record) == keys and RECORD_KEYS == set(xe.RECORD_KEYS)
    if trial_id is not NO_ID:
        assert record["trial_id"] == trial_id
    assert record["fingerprint"] == "type-aware"
    assert isinstance(record["cases"], int)
    assert record["mismatches"] is None or isinstance(record["mismatches"], int)
    assert isinstance(record["groups"], dict) and isinstance(record["kinds"], dict)
    assert isinstance(record["seconds"], float) and isinstance(
        record["timed_out"], bool
    )
    example = record["counterexample"]
    assert example is None or (
        isinstance(example, dict) and set(example) == EXAMPLE_KEYS
    )
    if record["status"] != xe.COMPARED:
        assert record["mismatches"] is None and record["cases"] == 0


# ---------------------------------------------------------------------------
# Through the sandbox: the fixture library
# ---------------------------------------------------------------------------


def test_base_against_base_is_deterministic(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    one, two = gate(tmp_path, base, cfg, "w1"), gate(tmp_path, base, cfg, "w2")
    first, again, other = one.record(base), one.record(base), two.record(base)
    for record in (first, again, other):
        check_schema(record)
        assert record["status"] == xe.COMPARED and record["mismatches"] == 0
        assert record["counterexample"] is None and record["timed_out"] is False
    assert first["corpus_sha256"] == other["corpus_sha256"]
    assert one.base.hashes == two.base.hashes and one.base.status == two.base.status
    assert one.base.summary()["sources"] == {
        "generator": 120,
        "seed": 2,
        "workload": 20,
    }
    assert one.runner.count == 4  # the corpus and the base once, then one run a record


def test_planted_rare_fault_is_caught_and_minimised(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    record = gate(tmp_path, base, cfg).record(
        variant(tmp_path, "trial", count=RARE_FAULT)
    )
    check_schema(record)
    assert record["mismatches"] and record["kinds"] == {"value": record["mismatches"]}
    groups = record["groups"]
    assert isinstance(groups, dict) and set(groups) <= {"generator/a", "workload/a"}
    example = record["counterexample"]
    assert isinstance(example, dict) and example["reproduced"] is True
    assert example["input"] == "\x0b" and example["minimised_chars"] == 1
    assert example["input_chars"] > 1 and example["rounds"] >= 1
    assert "'n': 1" in example["base"] and "'n': 2" in example["trial"]


def test_tuple_for_list_is_caught_type_aware_and_missed_by_json(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    trial = variant(tmp_path, "trial", words="tuple")
    aware = gate(tmp_path, base, cfg, "aware").record(trial)
    plain = gate(tmp_path, base, xe.EquivSettings(size=TINY, adapter=cfg.adapter,
                                                  fingerprint="json"), "json").record(trial)  # fmt: skip
    assert aware["mismatches"] and aware["kinds"] == {"value": aware["mismatches"]}
    assert plain["status"] == xe.COMPARED and plain["mismatches"] == 0
    example = aware["counterexample"]
    assert isinstance(example, dict) and "builtins.tuple" in example["trial"]
    assert xe.fingerprint({"a": (1,)}) != xe.fingerprint({"a": [1]})
    assert xe.fingerprint({"a": (1,)}, "json") == xe.fingerprint({"a": [1]}, "json")


def test_an_input_past_its_alarm_is_a_timeout_not_a_mismatch(tmp_path: Path) -> None:
    base = make_library(tmp_path / "base", seeds=("alpha", "LOOP forever"))
    cfg = xe.EquivSettings(
        size=TINY, adapter=make_adapter(tmp_path / "a.py"), alarm_s=0.3
    )
    eq = gate(tmp_path, base, cfg)
    record = eq.record(base)
    check_schema(record)
    assert record["timeouts"] == 1 and record["timed_out"] is True
    assert record["mismatches"] == 0 and record["cases"] == len(eq.base.corpus) - 1
    assert eq.base.summary()["timeouts"] == 1


def test_a_batch_past_its_timeout_records_timed_out(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    slow = variant(tmp_path, "slow", count="lambda t: time.sleep(30)")
    cfg = xe.EquivSettings(
        size=TINY, adapter=cfg.adapter, alarm_s=60.0, batch_timeout_s=2.0
    )
    eq = gate(tmp_path, base, cfg)
    record = eq.record(slow)
    check_schema(record)
    assert record["status"] == xe.TIMEOUT and record["timed_out"] is True
    assert str(record["error"]).startswith("the trial did not run: timeout after 2 s")
    blocked = gate(tmp_path, slow, cfg, "slow-base").record(base)
    assert blocked["status"] == xe.TIMEOUT and blocked["timed_out"] is True
    assert str(blocked["error"]).startswith("the base did not run: timeout after")


def test_no_network_a_generator_that_opens_a_socket_fails(tmp_path: Path) -> None:
    base = make_library(tmp_path / "base")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        listener.setblocking(False)
        port = listener.getsockname()[1]
        dial = (
            f"import socket; socket.create_connection(('127.0.0.1', {port}), 2).close()"
        )
        adapter = make_adapter(tmp_path / "dial.py", dial)
        cfg = xe.EquivSettings(size=TINY, adapter=adapter)
        record = gate(tmp_path, base, cfg).record(base)
        check_schema(record)
        assert record["status"] == xe.ERROR
        assert str(record["error"]).startswith("the corpus was not built: ")
        assert "Error" in str(record["error"])
        with pytest.raises(BlockingIOError):
            listener.accept()  # nothing reached the parent
        # the control: the same generator with the network open does connect
        opened = xe.EquivSettings(size=xe.Size(1, 0, 0), adapter=adapter, network="off")
        assert (
            gate(tmp_path, base, opened, "open").record(base)["status"] == xe.COMPARED
        )
        listener.setblocking(True)
        listener.settimeout(5)
        listener.accept()[0].close()


def test_a_library_without_a_generator_records_so(tmp_path: Path) -> None:
    record = xe.Equivalence("pyparsing", tmp_path, tmp_path / "w").record(tmp_path)
    check_schema(record)
    assert record["status"] == xe.NO_GENERATOR and record["mismatches"] is None
    assert record["error"] == "no generator for pyparsing"


def test_equivalence_record_computes_the_base_once(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    trial = variant(tmp_path, "trial", count=RARE_FAULT)
    first = xe.equivalence_record(
        "eqfix", base, base, work=tmp_path / "w", settings=cfg
    )
    second = xe.equivalence_record("eqfix", base, trial, settings=cfg)
    key = ("eqfix", os.path.realpath(base), cfg)
    assert xe._GATES[key].runner.count >= 4 and xe._GATES[key].work == tmp_path / "w"
    assert first["mismatches"] == 0 and second["mismatches"]
    del xe._GATES[key]
    xe.equivalence_record("eqfix", base, base, settings=cfg)  # a temporary work dir
    temporary = xe._GATES.pop(key).work
    assert temporary.name.startswith("x2-equiv-")
    shutil.rmtree(temporary)


# ---------------------------------------------------------------------------
# The archive: equiv_rows on a real clone
# ---------------------------------------------------------------------------

GIT_ENV = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}  # fmt: skip


def git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True,
                          check=True, text=True)  # fmt: skip
    return done.stdout.strip()


def diff_of(clone: Path, change: Callable[[Path], None]) -> str:
    change(clone)
    text = git(clone, "diff") + "\n"
    git(clone, "checkout", "-q", "--", ".")
    return text


def set_count(expr: str) -> Callable[[Path], None]:
    def change(root: Path) -> None:
        path = root / "eqfix" / "__init__.py"
        path.write_text(path.read_text().replace("COUNT = len", f"COUNT = {expr}"))

    return change


def entry(
    root: Path, run: str, name: str, text: str, **extra: object
) -> dict[str, object]:
    folder = root / PATCH_DIR / run
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text)
    data = text.encode()
    return {"file": f"{PATCH_DIR}/{run}/{name}", "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "truncated": False, "original_bytes": None, "error": None,
            **extra}  # fmt: skip


def test_equiv_rows_walk_the_archive(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    clone = tmp_path / "clone"
    shutil.copytree(base, clone)
    git(clone, "init", "-q", "-b", "main")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "base")
    commit = git(clone, "rev-parse", "HEAD")
    same = diff_of(clone, set_count("lambda t: len(str(t))"))
    rare = diff_of(clone, set_count(RARE_FAULT))
    root, run = tmp_path / "artifact", "X2-DT-eqfix"
    ok = {"base_commit": commit}
    archive: dict[str, object] = {
        "base_commit": commit,
        "kept_diffs": [
            {"hypothesis_id": "h1", "trial_id": "t-same", **entry(root, run, "trial-t-same.diff", same), **ok},
            {"hypothesis_id": "h2", "trial_id": "t-rare", **entry(root, run, "trial-t-rare.diff", rare), **ok},
            {"hypothesis_id": "h3", "trial_id": "t-same", **entry(root, run, "dup.diff", same), **ok},
            {"hypothesis_id": "h4", "trial_id": "t-sha", **entry(root, run, "s.diff", same),
             "sha256": "0" * 64, **ok},
            {"hypothesis_id": "h5", "trial_id": "t-cut", **entry(root, run, "c.diff", same),
             "truncated": True, **ok},
            {"hypothesis_id": "h6", "trial_id": "t-none", **xe_missing(), **ok},
            {"hypothesis_id": "h7", "trial_id": "t-bad", **entry(root, run, "b.diff", "not a diff\n"), **ok},
            {"hypothesis_id": "h8", "trial_id": "t-base", **entry(root, run, "x.diff", same),
             "base_commit": "f" * 40},
            "not an entry",
        ],
        "inconclusive_diffs": [
            {"hypothesis_id": "h9", "trial_id": "t-odd", **entry(root, run, "trial-t-odd.diff", rare),
             "base_commit": None},
        ],
        "delivered_patch": {**entry(root, run, "delivered.patch", rare), **ok, "tip_commit": "d" * 40},
    }  # fmt: skip
    rows = xe.equiv_rows("eqfix", clone, archive, root, tmp_path / "work", cfg)
    assert list(rows.trials) == ["t-same", "t-rare", "t-sha", "t-cut", "t-none", "t-bad",
                                 "t-base", "t-odd"]  # fmt: skip
    for name, got in rows.trials.items():
        check_schema(got, trial_id=name)
    assert rows.delivered is not None
    check_schema(rows.delivered, trial_id=None)
    assert row(rows.trials, "t-same")["mismatches"] == 0
    for got in (row(rows.trials, "t-rare"), row(rows.trials, "t-odd"), rows.delivered):
        assert got["mismatches"], got
    errors = {n: r["error"] for n, r in rows.trials.items() if n[2:] not in ("same", "rare", "odd")}  # fmt: skip
    git_says = {n: errors.pop(n) for n in ("t-bad", "t-base")}  # git's wording varies
    assert errors == {
        "t-sha": "the diff's sha256 is not the entry's",
        "t-cut": "the diff was truncated by the engine's cap",
        "t-none": "no diff file: no kept trial: no diff written",
    }
    assert str(git_says["t-bad"]).startswith("git apply failed: error: ")
    assert str(git_says["t-base"]).startswith(
        f"the base was not exported: git archive {'f' * 12} failed: fatal: "
    )
    assert row(rows.trials, "t-base")["status"] == xe.ERROR
    assert row(rows.trials, "t-sha")["status"] == xe.NOT_APPLIED
    assert rows.base["status"] == xe.COMPARED
    assert rows.base["sources"] == {"generator": 120, "seed": 2, "workload": 20}
    assert git(clone, "status", "--porcelain") == ""  # nothing in the clone moved
    empty = xe.equiv_rows("eqfix", clone, {"base_commit": commit, "kept_diffs": "x"},
                          root, tmp_path / "w2", cfg)  # fmt: skip
    assert empty == xe.EquivRows({}, None, {"status": "not needed", "error": None})
    orphan = {"trial_id": "t", "base_commit": None, **entry(root, run, "o.diff", same)}
    lost = xe.equiv_rows("eqfix", clone, {"base_commit": "nope", "kept_diffs": [orphan]},
                         root, tmp_path / "w3", cfg)  # fmt: skip
    assert lost.base == {"status": xe.ERROR,
                         "error": "the base was not exported: not a commit id: 'nope'"}  # fmt: skip
    assert row(lost.trials, "t")["error"] == lost.base["error"]


def row(rows: Mapping[str, dict[str, object]], name: str) -> dict[str, object]:
    return rows[name]


def xe_missing() -> dict[str, object]:
    from .x2_patches import NO_KEEP, missing

    return missing(NO_KEEP)


def test_archived_diff_refuses_paths_out_of_the_patch_directory(tmp_path: Path) -> None:
    root = tmp_path / "artifact"
    good = entry(root, "run", "a.diff", "x\n")
    (tmp_path / "outside.diff").write_text("x\n")
    (root / PATCH_DIR / "run" / "link.diff").symlink_to(tmp_path / "outside.diff")
    (root / "other").mkdir()
    (root / "other" / "o.diff").write_text("x\n")
    assert xe.archived_diff(good, root) == root / PATCH_DIR / "run" / "a.diff"
    for rel in (f"{PATCH_DIR}/../outside.diff", "other/o.diff", f"{PATCH_DIR}/run/link.diff",
                f"{PATCH_DIR}/run", f"{PATCH_DIR}/run/missing.diff"):  # fmt: skip
        with pytest.raises(ValueError, match="not a patch file"):
            xe.archived_diff({**good, "file": rel}, root)
    with pytest.raises(ValueError, match="no diff file: none recorded"):
        xe.archived_diff({**good, "file": None}, root)
    big = root / PATCH_DIR / "run" / "big.diff"
    with big.open("wb") as handle:
        handle.truncate(xe.MAX_DIFF_BYTES + 1)
    with pytest.raises(ValueError, match="larger than MAX_DIFF_BYTES"):
        xe.archived_diff({**good, "file": f"{PATCH_DIR}/run/big.diff"}, root)


# ---------------------------------------------------------------------------
# The parent's error paths, run_once swapped
# ---------------------------------------------------------------------------


def sample(exit_code: int = 0, stderr: bytes = b"") -> RunSample:
    return RunSample(wall_ns=1, utime=0.0, stime=0.0, maxrss_bytes=1, exit=exit_code,
                     fs_isolated=True, net_isolated=True, stdout_sha256="", stdout_head=b"",
                     stdout_bytes=0, stderr_tail=stderr)  # fmt: skip


def fake_run(write: str | None, *, fail: str | None = None,
             stderr: bytes = b"") -> Callable[..., RunSample]:  # fmt: skip
    def run(argv: Sequence[str], cwd: Path, env: Mapping[str, str], sandbox: object,
            timeout_s: float, caps: object, *, fresh_dirs: Sequence[Path] = ()) -> RunSample:  # fmt: skip
        assert argv[1:6] == ["-s", "-S", "-B", "-P", str(xe.CHILD)]
        assert env["PYTHONHASHSEED"] == "0" and "PYTHONPATH" not in env
        if fail is not None:
            raise RunFailure(fail)
        if write is not None:
            Path(argv[argv.index("--out") + 1]).write_text(write)
        return sample(1 if write is None else 0, stderr)

    return run


@pytest.mark.parametrize(
    ("write", "fail", "stderr", "error", "timed_out"),
    [
        (None, "timeout after 9 s", b"", "timeout after 9 s", True),
        (None, "launcher: boom", b"", "launcher: boom", False),
        (None, None, b"x\nTraceback last line\n", "exit 1: Traceback last line", False),
        (None, None, b"", "exit 1: no stderr", False),
        ("[1]", None, b"", "not an object", False),
        ('{"error": "ValueError: no"}', None, b"", "ValueError: no", False),
        ("{oops", None, b"", "exit 0: no stderr", False),
    ],
)
def test_runner_reports_what_went_wrong(tmp_path: Path, write: str | None, fail: str | None,
                                        stderr: bytes, error: str, timed_out: bool) -> None:  # fmt: skip
    runner = xe.Runner(
        tmp_path, xe.EquivSettings(), fake_run(write, fail=fail, stderr=stderr)
    )
    got = runner(["eval"], tmp_path, 5.0)
    assert (got.data, got.error, got.timed_out) == (None, error, timed_out)


def test_baseline_and_record_errors(lib: tuple[Path, xe.EquivSettings], tmp_path: Path,
                                    monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    base, cfg = lib
    failed = xe.Equivalence(
        "eqfix", base, tmp_path / "f", cfg, fake_run(None, fail="launcher: x")
    )
    record = failed.record(base)
    assert (record["status"], record["error"]) == (
        xe.ERROR,
        "the corpus was not built: launcher: x",
    )
    late = xe.Equivalence(
        "eqfix", base, tmp_path / "t", cfg, fake_run(None, fail="timeout after 1 s")
    )
    assert (
        late.record(base)["status"] == xe.TIMEOUT
        and late.base.summary()["status"] == xe.TIMEOUT
    )
    eq = gate(tmp_path, base, cfg)
    assert eq.base.state == xe.COMPARED
    short = xe.Evaluated(["a"], "o", [], 0.1)
    monkeypatch.setattr(eq, "_eval", lambda tree, corpus, show, timeout_s=None: short)
    record = eq.record(base)
    assert (
        record["status"] == xe.ERROR
        and record["error"] == f"1 results for {len(eq.base.hashes)} cases"
    )
    assert eq._differs(base, "a", ["x", "y"], 0.0) is None  # one result against two
    crashed = xe.Evaluated([], "", [], 0.1, "exit 1: boom")
    monkeypatch.setattr(eq, "_eval", lambda tree, corpus, show, timeout_s=None: crashed)
    assert eq.record(base)["error"] == "the trial did not run: exit 1: boom"
    assert eq._differs(base, "a", ["x"], 0.0) is None


@pytest.mark.parametrize(
    ("data", "show"),
    [
        ({"hashes": "x", "status": "o"}, False),
        ({"hashes": ["a"], "status": "oo"}, False),
        ({"hashes": ["a"], "status": "x"}, False),
        ({"hashes": [1], "status": "o"}, False),
        ({"hashes": ["a"], "status": "o", "shown": ["f"]}, False),
        ({"hashes": ["a"], "status": "o"}, True),
        ({"hashes": ["a"], "status": "o", "shown": [2]}, True),
    ],
)
def test_a_malformed_child_result_is_refused(
    data: dict[str, object], show: bool
) -> None:
    with pytest.raises(ValueError, match="malformed"):
        xe.eval_result(data, show)


def test_malformed_results_become_error_records(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    for corpus in ('{"corpus": [[1, 2, 3]]}', '{"corpus": "x"}'):
        bad = xe.Equivalence(
            "eqfix", base, tmp_path / f"c{len(corpus)}", cfg, fake_run(corpus)
        )
        record = bad.record(base)
        assert record["status"] == xe.ERROR
        assert (
            record["error"]
            == "the corpus was not built: the child's corpus is malformed"
        )
    eq = xe.Equivalence("eqfix", base, tmp_path / "e", cfg,
                        fake_run('{"corpus": [["generator", "a", "x"]], "hashes": 3}'))  # fmt: skip
    assert (
        eq.record(base)["error"]
        == "the base did not run: the child's result is malformed"
    )
    huge = xe.Runner(tmp_path / "h", cfg, fake_run(" " * 64))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(xe, "MAX_RESULT_BYTES", 10)
        assert (
            huge(["eval"], base, 5.0).error
            == "the result is larger than MAX_RESULT_BYTES"
        )


def test_a_mismatch_that_does_not_reproduce_alone_is_kept_unminimised(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    # the fault depends on how many inputs the process has seen: only late in the batch
    late = variant(tmp_path, "late", count="lambda t: len(t) + (CALLS[0] > 100)")
    record = gate(tmp_path, base, cfg).record(late)
    example = record["counterexample"]
    assert record["mismatches"] and isinstance(example, dict)
    assert example["reproduced"] is False and example["rounds"] == 0
    assert example["base"] is None and example["trial"] is None
    assert example["input_chars"] == example["minimised_chars"]
    hurried = xe.EquivSettings(size=TINY, adapter=cfg.adapter, minimise_s=0.0)
    quick = gate(tmp_path, base, hurried, "hurried").record(late)["counterexample"]
    assert isinstance(quick, dict) and quick["reproduced"] is False
    assert quick["case"] == example["case"]


def test_minimisation_stops_at_its_deadline(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    cut = xe.EquivSettings(size=TINY, adapter=cfg.adapter, minimise_s=0.0)
    example = gate(tmp_path, base, cut).record(variant(tmp_path, "t", count=RARE_FAULT))["counterexample"]  # fmt: skip
    assert (
        isinstance(example, dict)
        and example["reproduced"] is True
        and example["rounds"] == 0
    )
    assert example["minimised_chars"] == example["input_chars"]


def test_minimisation_stops_at_max_rounds(lib: tuple[Path, xe.EquivSettings], tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    base, cfg = lib
    monkeypatch.setattr(xe, "MAX_ROUNDS", 1)
    example = gate(tmp_path, base, cfg).record(variant(tmp_path, "t", count=RARE_FAULT))["counterexample"]  # fmt: skip
    assert isinstance(example, dict) and example["rounds"] == 1


def test_the_switch_is_off_unless_record() -> None:
    assert xe.equiv_on({}) is False and xe.equiv_on({xe.EQUIV_ENV: "off"}) is False
    assert xe.equiv_on({xe.EQUIV_ENV: "record"}) is True
    with pytest.raises(ValueError, match="must be off or record, not 'on'"):
        xe.equiv_on({xe.EQUIV_ENV: "on"})


def test_export_base_refuses_a_bad_commit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a commit id"):
        xe.export_base(tmp_path, "HEAD; rm -rf /", tmp_path / "x")
    assert xe._first(b"") == "no message"


# ---------------------------------------------------------------------------
# The child in-process (coverage of what the sandboxed child runs)
# ---------------------------------------------------------------------------


@pytest.fixture
def in_process() -> Iterator[None]:
    """Whatever the child imports or sets here is undone afterwards; the
    test process hashes at random, so ``seeded`` says yes here (the real
    flags are checked through the sandbox, ``test_b1_...``)."""
    path, modules = list(sys.path), dict(sys.modules)
    handler, bytecode = signal.getsignal(signal.SIGALRM), sys.dont_write_bytecode
    seeded = xe.seeded
    xe.seeded = lambda: True
    try:
        yield
    finally:
        xe.seeded = seeded
        sys.path[:] = path
        for name in set(sys.modules) - set(modules):
            del sys.modules[name]
        sys.modules.update(modules)  # a module the test dropped comes back
        signal.signal(signal.SIGALRM, handler)
        sys.dont_write_bytecode = bytecode


@pytest.mark.parametrize("library", xe.LIBRARIES)
def test_generators_are_the_audits_stream_and_deterministic(library: str) -> None:
    adapter = xe.ADAPTERS[library]()
    draws = [adapter.generate(random.Random(7)) for _ in range(2)]
    assert draws[0] == draws[1]
    rng = random.Random(1)
    cases = [adapter.generate(rng) for _ in range(2500)]
    assert all(isinstance(m, str) and isinstance(t, str) for m, t in cases)
    assert len({t for _, t in cases}) > 2000
    assert adapter.mutate(random.Random(3), "") != ""
    # the audit's corpus.py, seed 1, first case (pins the ported stream)
    first = {"tomli": "decimal", "sqlparse": "all", "mistune": "wl", "markdown": "wl"}
    assert cases[0][0] == first[library]


def test_generator_pins() -> None:
    pins = {name: hashlib.sha256(json.dumps(
        [xe.ADAPTERS[name]().generate(rng) for rng in [random.Random(1)] for _ in range(300)]
    ).encode()).hexdigest()[:16] for name in xe.LIBRARIES}  # fmt: skip
    assert pins == GENERATOR_PINS


# sha256 of the first 300 cases of each stream at seed 1, which equal the
# audit's ``corpus.py`` stream case for case (checked against its scripts
# when this unit was built, 3,000 cases at seeds 1, 2 and 7)
GENERATOR_PINS = {"sqlparse": "72bb5bc59a2f91cc", "tomli": "f687361f2778efa5",
                  "mistune": "89662bee79cd4c13", "markdown": "94f9b97b6a0d8280"}  # fmt: skip


def write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


BENCH = (
    "import random\n\ndef _document(rng):\n    return 'a\\n\\nb' + str(rng.random())\n"
)


def test_seeds_and_workloads_read_the_trees_own_data(tmp_path: Path) -> None:
    t = tmp_path / "tomli"
    write(t / "tests/data/valid/a.toml", "a = 1")
    write(t / "tests/data/invalid/b.toml", "a = ")
    write(t / "tests/data/valid/c.json", "{}")
    (t / "tests/data/valid/link.toml").symlink_to(t / "tests/data/valid/a.toml")
    assert xe.Tomli().seeds(t) == [
        ("plain", "a = "),
        ("plain", "a = 1"),
        ("decimal", "a = 1"),
    ]
    assert xe.Tomli().workload(t) is None
    write(t / "benchmarks/bench_tomli.py", BENCH)
    assert xe.Tomli().workload(t) == "a\n\nb" + str(random.Random(31).random())
    s = tmp_path / "sqlparse"
    write(s / "tests/files/a.sql", "select 'é'".encode("latin-1"))
    write(s / "tests/test_x.py", "X = 'select 1'\nY = 'x'\nZ = 3\n")
    write(s / "tests/test_broken.py", "def (:\n")
    assert xe.Sqlparse().seeds(s) == [("all", "select 'é'"), ("all", "select 1")]
    assert xe.Sqlparse().workload(s) is None
    write(s / "benchmarks/bench_sqlparse.py", "STATEMENTS = 4\n"
          "def _select(rng, n):\n    return f's{n}'\n"
          "def _insert(rng, n):\n    return f'i{n}'\n")  # fmt: skip
    assert xe.Sqlparse().workload(s) == "i0\ns1\ns2\ni3"
    write(s / "benchmarks/bench_sqlparse.py", "STATEMENTS = 1\n")
    with pytest.raises(ValueError, match="lacks _select, _insert"):
        xe.Sqlparse().workload(s)
    m = tmp_path / "mistune"
    fence = "`" * 32 + " example\n"
    write(
        m / "tests/fixtures/commonmark.json",
        json.dumps([{"markdown": "*a*"}, {"x": 1}, "y"]),
    )
    write(m / "tests/fixtures/t.txt", f"intro\n{fence}# h\n.\n<h1>h</h1>\n{'`' * 32}\n")
    assert xe.Mistune().seeds(m) == [("wl", "*a*"), ("html", "# h")]
    write(m / "tests/fixtures/commonmark.json", "{not json")
    assert xe.Mistune().seeds(m) == [("wl", "# h")]
    write(m / "tests/fixtures/commonmark.json", "{}")
    assert xe.Mistune().seeds(m) == [("wl", "# h")]
    assert xe.Mistune().workload(m) is None
    (m / "tests/fixtures/commonmark.json").unlink()
    assert xe.Mistune().seeds(m) == [("wl", "# h")]
    write(m / "benchmarks/bench_mistune.py", BENCH)
    assert xe.Mistune().workload(m) == "a\n\nb" + str(random.Random(5).random())
    k = tmp_path / "markdown"
    write(k / "tests/basic/a.txt", "*a*")
    write(k / "tests/pl/x/b.txt", "_b_")
    write(k / "tests/test_syntax/inline/test_c.py", "X = '''\n    *c*\n    '''\n")
    assert xe.Markdown().seeds(k) == [
        ("wl", "*a*"),
        ("none", "_b_"),
        ("wide", "\n*c*\n"),
    ]
    write(k / "benchmarks/bench_markdown.py", BENCH)
    assert xe.Markdown().workload(k) == "a\n\nb" + str(random.Random(29).random())


def test_corpus_sources_sample_and_windows() -> None:
    items = [("a", str(i)) for i in range(10)]
    assert xe.sample(items, 20, random.Random(1)) == items
    picked = xe.sample(items, 3, random.Random(1))
    assert len(picked) == 3 and picked == sorted(picked, key=items.index)
    cut = xe.windows("u1\nu2\nu3", "\n", 5, random.Random(2), lambda rng, s: s + "!")
    assert len(cut) == 5 and all(c.endswith("!") for c in cut)
    assert all(c.rstrip("!") in "u1\nu2\nu3" for c in cut)


def test_fingerprint_type_tree_and_errors() -> None:
    assert xe.type_tree({"a": [1, (2.0,)], 3: {4}}) == (
        "builtins.dict",
        [("builtins.str", ("builtins.list", ["builtins.int", ("builtins.tuple", ["builtins.float"])])),
         ("builtins.int", ("builtins.set", ["builtins.int"]))],
    )  # fmt: skip
    loop: list[object] = []
    loop.append(loop)
    assert (
        xe.fingerprint(loop) == "[[...]]\n('builtins.list', ['<cycle builtins.list>'])"
    )
    deep: list[object] = []
    for _ in range(xe.MAX_DEPTH + 5):
        deep = [deep]
    assert "<deep builtins.list>" in xe.fingerprint(deep)
    assert xe.fingerprint({1: 2, "a": 3}, "json") == "unfingerprintable: TypeError"

    class Deep:
        def __repr__(self) -> str:
            raise RecursionError

    assert xe.fingerprint(Deep()) == "unfingerprintable: RecursionError"

    class HostileError(Exception):
        def __str__(self) -> str:
            raise RuntimeError

    assert xe.error_print(HostileError()).endswith(
        "HostileError: <unprintable message>"
    )
    assert xe.error_print(ValueError("bad")) == "!builtins.ValueError: bad"
    assert len(xe.digest("\ud800")) == 32


def test_run_input_statuses(in_process: None) -> None:
    signal.signal(signal.SIGALRM, xe._alarm)

    def boom() -> object:
        raise KeyError("k")

    def spin() -> object:
        while True:
            time.sleep(0.01)

    assert xe.run_input([lambda: [1]], 5.0, "type-aware") == (
        "o",
        "[1]\n('builtins.list', ['builtins.int'])",
    )
    status, out = xe.run_input([lambda: 1, boom], 5.0, "json")
    assert status == "e" and out == "1\n!builtins.KeyError: 'k'"
    assert xe.run_input([spin], 0.05, "type-aware") == ("t", "timeout")


def test_child_main_in_process(in_process: None, lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    out, adapter = tmp_path / "out.json", str(cfg.adapter)
    args = [
        "--lib",
        "eqfix",
        "--tree",
        str(base),
        "--out",
        str(out),
        "--adapter",
        adapter,
    ]
    assert (
        xe.child_main(
            ["corpus", *args, "--size", "5", "--seed-cap", "1", "--workload", "2"]
        )
        == 0
    )
    corpus = json.loads(out.read_text())["corpus"]
    assert [c[0] for c in corpus] == ["generator"] * 5 + [
        "seed",
        "workload",
        "workload",
    ]
    (tmp_path / "c.json").write_text(json.dumps(corpus))
    assert (
        xe.child_main(
            ["eval", *args, "--corpus", str(tmp_path / "c.json"), "--show", "9"]
        )
        == 0
    )
    result = json.loads(out.read_text())
    assert (
        result["n"] == 8
        and len(result["shown"]) == 8
        and all(len(s) <= 9 for s in result["shown"])
    )
    assert xe.child_main(["eval", *args, "--corpus", str(tmp_path / "c.json")]) == 0
    assert "shown" not in json.loads(out.read_text())
    assert (
        xe.child_main(["corpus", *args, "--size", "2"]) == 0
    )  # no workload, no import
    assert (
        xe.child_main(
            ["corpus", "--lib", "nope", "--tree", str(base), "--out", str(out)]
        )
        == 3
    )
    assert (
        json.loads(out.read_text())["error"]
        == "builtins.ValueError: no generator for 'nope'"
    )
    bad = tmp_path / "adapter.txt"
    bad.write_text("x")
    assert xe.child_main(["corpus", *args[:-1], str(bad)]) == 3
    assert "is not a Python file" in json.loads(out.read_text())["error"]


def test_import_library_refuses_another_copy(in_process: None, tmp_path: Path) -> None:
    class Json:
        package, src = "json", False

    with pytest.raises(ValueError, match="json imported from .*, not under"):
        xe.import_library(Json(), tmp_path)  # type: ignore[arg-type]


def test_tomli_evaluator_in_process() -> None:
    calls = xe.Tomli().evaluator()
    plain = xe.run_input(calls("plain", "a = 1.5"), 5.0, "type-aware")
    exact = xe.run_input(calls("decimal", "a = 1.5"), 5.0, "type-aware")
    assert plain[0] == exact[0] == "o" and "builtins.float" in plain[1]
    assert "decimal.Decimal" in exact[1]
    assert xe.run_input(calls("plain", "a = "), 5.0, "type-aware")[0] == "e"


# ---------------------------------------------------------------------------
# The four pinned libraries (REAL)
# ---------------------------------------------------------------------------

LIBS_ENV = "X2_EQUIV_LIBS"
REAL = pytest.mark.skipif(
    not os.environ.get(LIBS_ENV) and os.environ.get(oss.NETWORK_ENV) != "1",
    reason=f"needs the four pinned libraries: {LIBS_ENV} or {oss.NETWORK_ENV}=1",
)
# One rare-input fault per library: calibrate_mut.py's MS1, MM1 and MK3; for
# tomli the audit's M8 shape (an integer with a doubled underscore parses).
PLANTED: Mapping[str, tuple[str, str, str]] = {
    "sqlparse": ("sqlparse/keywords.py",
                 "    (r'((?<![\\w\\\"\\$])\\$(?:[_A-ZÀ-Ü]\\w*)?\\$)[\\s\\S]*?\\1', tokens.Literal),\n", ""),
    "tomli": ("src/tomli/_re.py", "[+-]?(?:0|[1-9](?:_?[0-9])*)         # dec, integer part",
              "[+-]?(?:0|[1-9](?:_*[0-9])*)         # dec, integer part"),
    "mistune": ("src/mistune/_inline/links.py",
                '            pos += 2\n            continue\n        if char == "["',
                '            pos += 1\n            continue\n        if char == "["'),
    "markdown": ("markdown/extensions/abbr.py", 'self.RE = re.compile(f"\\\\b(?:',
                 'self.RE = re.compile(f"(?:'),
}  # fmt: skip
TUPLE_FOR_LIST = ("src/tomli/_parser.py", '        if c == "]":\n            return pos + 1, array',
                  '        if c == "]":\n            return pos + 1, tuple(array)')  # fmt: skip


@pytest.fixture(scope="session")
def real_tree(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], Path]:
    made: dict[str, Path] = {}

    def tree(name: str) -> Path:
        if name not in made:
            from .ideas_x2 import LIBRARIES

            repo, dest = LIBRARIES[name], tmp_path_factory.mktemp("x2-equiv") / name
            source = os.environ.get(LIBS_ENV)
            if source:
                src = Path(source) / name
                assert (
                    xe._git(["rev-parse", "HEAD"], src).stdout.decode().strip()
                    == repo.commit
                )
                shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
                (dest / "benchmarks").mkdir(exist_ok=True)
                shutil.copyfile(repo.workload_source, dest / repo.bench_path)
            else:
                oss.prepare_repo(repo, dest)
            made[name] = dest
        return made[name]

    return tree


def planted(base: Path, dest: Path, rel: str, old: str, new: str) -> Path:
    shutil.copytree(base, dest, ignore=shutil.ignore_patterns(".git"))
    path = dest / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, rel
    path.write_text(text.replace(old, new), encoding="utf-8")
    return dest


REAL_SIZE = xe.Size(400, 200, 60)


@REAL
@pytest.mark.slow
@pytest.mark.parametrize("library", xe.LIBRARIES)
def test_real_library_base_against_base_and_planted_fault(
    library: str, real_tree: Callable[[str], Path], tmp_path: Path
) -> None:
    base = real_tree(library)
    eq = xe.Equivalence(library, base, tmp_path / "w", xe.EquivSettings(size=REAL_SIZE))
    same = eq.record(base)
    assert same["status"] == xe.COMPARED and same["mismatches"] == 0, same
    sources = eq.base.summary()["sources"]
    assert sources == {"generator": 400, "seed": 200, "workload": 60}, sources
    fault = eq.record(planted(base, tmp_path / "mutant", *PLANTED[library]))
    example = fault["counterexample"]
    assert fault["mismatches"] and isinstance(example, dict), fault
    assert example["reproduced"] is True
    assert (
        example["minimised_chars"] < example["input_chars"]
        or example["input_chars"] < 8
    )


@REAL
@pytest.mark.slow
def test_real_tomli_tuple_for_list(
    real_tree: Callable[[str], Path], tmp_path: Path
) -> None:
    base = real_tree("tomli")
    trial = planted(base, tmp_path / "tuple", *TUPLE_FOR_LIST)
    aware = xe.Equivalence(
        "tomli", base, tmp_path / "a", xe.EquivSettings(size=REAL_SIZE)
    )
    plain = xe.Equivalence("tomli", base, tmp_path / "j",
                           xe.EquivSettings(size=REAL_SIZE, fingerprint="json"))  # fmt: skip
    # Every tuple shows type-aware as a value mismatch; json sees only the few
    # inputs where the immutable tuple changed what tomli raised (measured:
    # 92 value and 3 error mismatches against 3 error mismatches).
    seen, missed = aware.record(trial)["kinds"], plain.record(trial)["kinds"]
    assert isinstance(seen, dict) and isinstance(missed, dict)
    assert seen.get("value", 0) > 10 * sum(missed.values())
    assert "value" not in missed


@REAL
@pytest.mark.slow
@pytest.mark.parametrize("library", xe.LIBRARIES)
def test_real_library_adapter_in_process(
    library: str, real_tree: Callable[[str], Path], in_process: None
) -> None:
    """The same adapter code the sandboxed child runs, here (coverage)."""
    tree = real_tree(library)
    adapter = xe.load_adapter(library, None)
    signal.signal(signal.SIGALRM, xe._alarm)
    for name in [n for n in sys.modules if n.split(".")[0] == adapter.package]:
        del sys.modules[name]  # an installed copy (tomli is in the venv)
    xe.import_library(adapter, tree)
    seeds, text = adapter.seeds(tree), adapter.workload(tree)
    assert len(seeds) > 100 and text and adapter.unit in text
    calls = adapter.evaluator()
    statuses = {
        xe.run_input(calls(mode, s), 5.0, "type-aware")[0] for mode, s in seeds[:300]
    }
    assert "o" in statuses
    for mode in {m for m, _ in seeds}:
        assert xe.run_input(calls(mode, text[:2000]), 5.0, "type-aware")[0] in "oe"


# ---------------------------------------------------------------------------
# The UEQ review's findings (B1-B2, S1-S5) and test gaps (M02-M21)
# ---------------------------------------------------------------------------

BODY_LIBRARY = """
import os, sys, time
def parse(text):
    BODY
"""
BODY_ADAPTER = """
import random
WORDS = ["alpha", "beta", "gamma", "delta", "x", "y", "zeta"]
class A:
    package, src, workload_mode, unit = "eqfix", False, "a", "\\\\n"
    def generate(self, rng):
        return "a", " ".join(rng.choice(WORDS) for _ in range(rng.randint(2, 6)))
    def seeds(self, tree): return []
    def workload(self, tree): return None
    def mutate(self, rng, s): return s
    def evaluator(self):
        import eqfix
        return lambda mode, s: [lambda: eqfix.parse(s)]
ADAPTER = A()
"""


def body_library(root: Path, body: str, head: str = "") -> Path:
    (root / "eqfix").mkdir(parents=True)
    (root / "eqfix" / "__init__.py").write_text(
        head + BODY_LIBRARY.replace("BODY", body)
    )
    return root


def body_settings(tmp: Path, **kw: Any) -> xe.EquivSettings:
    adapter = tmp / "body_adapter.py"
    adapter.write_text(BODY_ADAPTER)
    return xe.EquivSettings(size=xe.Size(40, 0, 0), adapter=adapter, **kw)


def test_b1_the_hash_seed_is_in_force_in_the_child(tmp_path: Path) -> None:
    """f1: a set in the output; base against base is 0 only with the seed."""
    base = body_library(tmp_path / "base", "return {'words': set(text.split(' '))}")
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(base)
    assert record["status"] == xe.COMPARED and record["mismatches"] == 0, record[
        "kinds"
    ]


def test_b1_the_child_runs_with_the_seed_and_without_site_or_cwd(
    tmp_path: Path,
) -> None:
    flags = ("return (sys.flags.hash_randomization, sys.flags.safe_path, sys.flags.no_site, "
             "sys.flags.no_user_site, os.environ.get('PYTHONHASHSEED'))")  # fmt: skip
    base = body_library(tmp_path / "base", flags)
    eq = xe.Equivalence("eqfix", base, tmp_path / "w", body_settings(tmp_path))
    assert eq.base.corpus_path is not None
    seen = eq._eval(base, eq.base.corpus_path, xe.SHOW)
    assert seen.error is None and seen.shown[0].startswith("(0, True, 1, 1, '0')"), seen


def test_b1_the_child_refuses_hash_randomisation(
    in_process: None, tmp_path: Path
) -> None:
    out = tmp_path / "out.json"
    xe.seeded = lambda: False  # ``in_process`` puts the real one back
    code = xe.child_main(
        ["corpus", "--lib", "tomli", "--tree", str(tmp_path), "--out", str(out)]
    )
    assert code == 3
    assert json.loads(out.read_text())["error"] == (
        "hash randomisation is on: the child needs PYTHONHASHSEED=0 and no -E or -I"
    )


def test_b2_a_fifo_for_out_json_does_not_hang_the_parent(tmp_path: Path) -> None:
    """f4: the trial leaves a FIFO where the result goes."""
    base = body_library(tmp_path / "base", "return text")
    trial = body_library(tmp_path / "trial", "return text",
                         "import os\nos.mkfifo('out.json')\nos._exit(0)\n")  # fmt: skip
    eq = xe.Equivalence("eqfix", base, tmp_path / "w", body_settings(tmp_path))
    assert eq.base.state == xe.COMPARED
    got: list[dict[str, object]] = []
    reader = threading.Thread(target=lambda: got.append(eq.record(trial)), daemon=True)
    reader.start()
    reader.join(40)
    hung = reader.is_alive()
    if hung:  # release the reader so the test process can end
        for p in (tmp_path / "w" / "runs").glob("*/cwd/out.json"):
            if p.is_fifo():
                fd = os.open(p, os.O_WRONLY | os.O_NONBLOCK)
                os.write(fd, b"{}")
                os.close(fd)
        reader.join(20)
    assert not hung, "the runner blocked reading a FIFO the trial left as out.json"
    assert got and got[0]["mismatches"] is None
    assert got[0]["error"] == "the trial did not run: the result is not a plain file"


def test_b2_a_link_for_out_json_is_refused(tmp_path: Path) -> None:
    """A symlink to /dev/zero passed the size check and read forever."""
    base = body_library(tmp_path / "base", "return text")
    trial = body_library(tmp_path / "trial", "return text",
                         "import os\nos.symlink('/dev/zero', 'out.json')\nos._exit(0)\n")  # fmt: skip
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(trial)
    assert record["error"] == "the trial did not run: the result is not a plain file"


def test_s1_nothing_compared_is_none_not_zero(tmp_path: Path) -> None:
    """f2: every input of the trial times out."""
    base = body_library(tmp_path / "base", "return text")
    trial = body_library(tmp_path / "trial", "while True: pass")
    eq = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path, alarm_s=0.02)
    )
    record = eq.record(trial)
    check_schema(record)
    assert record["cases"] == 0 and record["timeouts"] == 40
    assert record["mismatches"] is None and record["status"] == xe.TIMEOUT
    assert record["timed_out"] is True and record["error"] == "every input timed out"


def test_s2_the_childs_error_text_is_redacted_then_clipped(tmp_path: Path) -> None:
    """f3: the trial shares the child and writes out.json itself."""
    base = body_library(tmp_path / "base", "return text")
    key = "sk-ant-api03-" + "A" * 2_000_000
    head = (f"import json, os\nopen('out.json', 'w').write(json.dumps({{'error': {key!r}}}))\n"
            "os._exit(0)\n")  # fmt: skip
    trial = body_library(tmp_path / "trial", "return text", head)
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(trial)
    assert record["status"] == xe.ERROR
    assert record["error"] == "the trial did not run: [redacted]"
    long = "x" * 290 + "sk-ant-api03-" + "B" * 40
    assert (
        xe.safe_text(long) == "x" * 290 + "[redacted]"
    )  # no key prefix survives the clip
    assert len(xe.safe_text("y" * 5000)) < 400


def test_s3_equiv_rows_never_raise_on_a_base_with_an_absolute_symlink(
    tmp_path: Path,
) -> None:
    """f5: ``tarfile``'s data filter refuses it; the record says why."""
    clone, commit = body_clone(
        tmp_path, lambda c: (c / "link").symlink_to("/etc/hostname")
    )
    root = tmp_path / "art"
    archive = {"base_commit": commit, "kept_diffs": [
        {"trial_id": "t1", "base_commit": commit, **entry(root, "run", "a.diff", touched(clone))}]}  # fmt: skip
    rows = xe.equiv_rows(
        "eqfix", clone, archive, root, tmp_path / "work", body_settings(tmp_path)
    )
    got = row(rows.trials, "t1")
    assert got["status"] == xe.ERROR and got["trial_id"] == "t1"
    assert str(got["error"]).startswith("the base was not exported: AbsoluteLinkError")


@pytest.mark.parametrize("fault", ["vcs_timeout", "copy_fails", "run_fails"])
def test_s3_equiv_rows_record_every_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    clone, commit = body_clone(tmp_path)
    root = tmp_path / "art"
    archive = {"base_commit": commit, "kept_diffs": [
        {"trial_id": "t1", "base_commit": commit, **entry(root, "run", "a.diff", touched(clone))}]}  # fmt: skip

    def boom(*args: object, **kw: object) -> object:
        if fault == "vcs_timeout":
            raise subprocess.TimeoutExpired("vcs", 300)
        raise OSError(28, "No space left on device")

    if fault == "run_fails":
        monkeypatch.setattr(xe.Runner, "__call__", boom)
    else:
        monkeypatch.setattr(
            xe, "_git" if fault == "vcs_timeout" else "apply_diff", boom
        )
    rows = xe.equiv_rows(
        "eqfix", clone, archive, root, tmp_path / "work", body_settings(tmp_path)
    )
    got = row(rows.trials, "t1")
    assert (
        got["status"] == xe.ERROR
        and got["trial_id"] == "t1"
        and got["mismatches"] is None
    )
    assert ("TimeoutExpired" if fault == "vcs_timeout" else "OSError") in str(
        got["error"]
    )


def test_s5_every_row_carries_its_trial_id_and_names_cannot_collide(
    tmp_path: Path,
) -> None:
    """f6: a trial named ``delivered`` keeps its record; the tip is apart."""
    clone, commit = body_clone(tmp_path)
    root = tmp_path / "art"
    bad = {
        "trial_id": "t1",
        "base_commit": commit,
        **entry(root, "run", "a.diff", "not a diff\n"),
    }
    odd = {"trial_id": "delivered", "base_commit": commit,
           **entry(root, "run", "b.diff", touched(clone))}  # fmt: skip
    rows = xe.equiv_rows("eqfix", clone, {"base_commit": commit, "kept_diffs": [bad, odd]},
                         root, tmp_path / "work", body_settings(tmp_path))  # fmt: skip
    assert set(rows.trials) == {"t1", "delivered"} and rows.delivered is None
    assert row(rows.trials, "t1")["trial_id"] == "t1"
    assert row(rows.trials, "delivered")["status"] == xe.COMPARED
    assert row(rows.trials, "delivered")["trial_id"] == "delivered"


def test_m10_the_trial_cannot_write_the_base_tree_or_the_corpus(tmp_path: Path) -> None:
    """f8: writes land only in the run's own scratch."""
    base = body_library(tmp_path / "base", "return text")
    work = tmp_path / "w"
    targets = [
        str(base / "eqfix" / "pwn.py"),
        str(work / "corpus.json"),
        str(tmp_path / "pwn.txt"),
    ]
    head = (f"wrote = []\nfor p in {targets!r}:\n    try:\n        open(p, 'a').write('#x')\n"
            "        wrote.append(p)\n    except OSError:\n        pass\n")  # fmt: skip
    trial = body_library(
        tmp_path / "trial", "return text + (str(wrote) if wrote else str())", head
    )
    eq = xe.Equivalence("eqfix", base, work, body_settings(tmp_path))
    sha = eq.base.corpus_sha256
    record = eq.record(trial)
    assert (
        not (base / "eqfix" / "pwn.py").exists() and not (tmp_path / "pwn.txt").exists()
    )
    assert hashlib.sha256((work / "corpus.json").read_bytes()).hexdigest() == sha
    assert record["status"] == xe.COMPARED and record["mismatches"] == 0


def test_record_only_bound_a_gate_aware_trial_shows_zero_mismatches(
    tmp_path: Path,
) -> None:
    """f9, the bound the README states: the trial's code shares the child, so
    it can tell the gate from the benchmark and answer as the base does."""
    base = body_library(tmp_path / "base", "return text")
    trial = body_library(tmp_path / "trial",
                         "return text if any('x2_equiv' in a for a in sys.argv) else text.upper()")  # fmt: skip
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(trial)
    assert record["mismatches"] == 0


def test_m02_a_trial_that_times_out_where_the_base_returns(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    trial = variant(
        tmp_path, "trial", count="lambda t: time.sleep(9) if 'alpha' in t else len(t)"
    )
    eq = gate(
        tmp_path, base, xe.EquivSettings(size=TINY, adapter=cfg.adapter, alarm_s=0.05)
    )
    record = eq.record(trial)
    slow = sum("alpha" in t and "!" not in t for _, _, t in eq.base.corpus)
    assert slow > 10 and record["timeouts"] == slow and record["mismatches"] == 0
    assert record["timed_out"] is True and record["cases"] == len(eq.base.corpus) - slow


def test_m21_one_side_raises_the_other_returns(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    trial = variant(
        tmp_path, "trial", count="lambda t: int('x') if '\\x0b' in t else len(t)"
    )
    record = gate(tmp_path, base, cfg).record(trial)
    assert record["mismatches"] and record["kinds"] == {"status": record["mismatches"]}
    example = record["counterexample"]
    assert isinstance(example, dict) and example["input"] == "\x0b"
    assert str(example["trial"]).startswith(
        "!builtins.ValueError: invalid literal for int()"
    )


def test_m16_m17_the_counterexample_is_redacted_and_clipped(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    leak = "'sk-ant-api03-' + 'K' * 40 + ' ' + 'z' * 400"
    trial = variant(
        tmp_path, "trial", count=f"lambda t: ({leak}) if '\\x0b' in t else len(t)"
    )
    example = gate(tmp_path, base, cfg).record(trial)["counterexample"]
    assert isinstance(example, dict) and example["reproduced"] is True
    shown = str(example["trial"])
    assert "sk-ant" not in shown and "[redacted]" in shown
    assert len(shown) <= xe.CLIP + len("...[+99999]") and shown.endswith("]")
    assert len(str(example["base"])) <= xe.CLIP + len("...[+99999]")


def test_m12_a_timeout_during_minimisation_is_not_a_difference(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    base, cfg = lib
    trial = variant(tmp_path, "trial",
                    count="lambda t: time.sleep(9) if t == '\\x0b' else len(t) + ('\\x0b' in t)")  # fmt: skip
    eq = gate(
        tmp_path, base, xe.EquivSettings(size=TINY, adapter=cfg.adapter, alarm_s=0.3)
    )
    example = eq.record(trial)["counterexample"]
    assert isinstance(example, dict) and example["reproduced"] is True
    assert example["minimised_chars"] == 2 and "\x0b" in str(example["input"])


def test_minimisation_evals_are_capped_by_what_is_left_of_minimise_s(lib: tuple[Path, xe.EquivSettings], tmp_path: Path) -> None:  # fmt: skip
    """The reproduction run (its corpus is a ``min-`` file) sleeps; the cap
    is the time left of ``minimise_s`` (at least ``MIN_EVAL_S``), not the
    600 s batch timeout."""
    base, cfg = lib
    trial = variant(tmp_path, "trial", count=(
        "lambda t: time.sleep(30) if any('min-' in a for a in sys.argv) "
        "else len(t) + ('\\x0b' in t)"))  # fmt: skip
    eq = gate(tmp_path, base, xe.EquivSettings(size=TINY, adapter=cfg.adapter, alarm_s=60.0,
                                               minimise_s=1.0))  # fmt: skip
    record = eq.record(trial)
    example = record["counterexample"]
    assert isinstance(example, dict) and example["reproduced"] is False
    seconds = record["seconds"]
    assert isinstance(seconds, float) and seconds < xe.MIN_EVAL_S + 15


def test_m08_a_linked_directory_under_the_patch_directory_is_refused(
    tmp_path: Path,
) -> None:
    root, outside = tmp_path / "artifact", tmp_path / "outside"
    good = entry(root, "run", "a.diff", "x\n")
    outside.mkdir()
    (outside / "a.diff").write_text("x\n")
    (root / PATCH_DIR / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="not a patch file"):
        xe.archived_diff({**good, "file": f"{PATCH_DIR}/linked/a.diff"}, root)
    moved = tmp_path / "moved"
    shutil.move(root / PATCH_DIR, moved)
    (root / PATCH_DIR).symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="not a patch file"):
        xe.archived_diff(good, root)


def body_clone(
    tmp_path: Path, extra: Callable[[Path], object] | None = None
) -> tuple[Path, str]:
    clone = body_library(tmp_path / "clone", "return text")
    if extra is not None:
        extra(clone)
    vcs(clone, "init", "-q", "-b", "main")
    vcs(clone, "add", ".")
    vcs(clone, "commit", "-q", "-m", "base")
    return clone, vcs(clone, "rev-parse", "HEAD")


def touched(clone: Path) -> str:
    path = clone / "eqfix" / "__init__.py"
    old = path.read_text()
    path.write_text(old + "# x\n")
    text = vcs(clone, "diff") + "\n"
    path.write_text(old)
    return text


vcs = git  # the test module's own helper


@pytest.mark.parametrize(("randomised", "seeded"), [(0, True), (1, False)])
def test_seeded_reads_the_interpreters_flag(
    monkeypatch: pytest.MonkeyPatch, randomised: int, seeded: bool
) -> None:
    monkeypatch.setattr(sys, "flags", SimpleNamespace(hash_randomization=randomised))
    assert xe.seeded() is seeded


# ---------------------------------------------------------------------------
# The UEQ re-review: N-B1, N-N1, N01, N07
# ---------------------------------------------------------------------------


def test_nb1_a_deeply_nested_result_is_an_error_record(tmp_path: Path) -> None:
    """The reviewer's a1: ``json.loads`` raises ``RecursionError``."""
    base = body_library(tmp_path / "base", "return text")
    head = "import os\nopen('out.json', 'w').write('[' * 200000)\nos._exit(0)\n"
    trial = body_library(tmp_path / "trial", "return text", head)
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(trial)
    assert record["status"] == xe.ERROR and record["mismatches"] is None
    assert str(record["error"]).startswith("the trial did not run: exit 0: ")


def test_nb1_recursion_is_one_of_the_failures_a_row_records() -> None:
    assert RecursionError in xe._FAILURES


def test_nn1_the_result_cap_fits_an_honest_full_size_result() -> None:
    assert xe.MAX_RESULT_BYTES == 8 * 1024 * 1024
    for name, size in xe.SIZES.items():
        n = size.generator + size.seed_cap + size.workload
        honest = json.dumps({"n": n, "hashes": ["0" * 32] * n, "status": "o" * n,
                             "seconds": 12.345})  # fmt: skip
        assert len(honest) < xe.MAX_RESULT_BYTES / 2, name


def test_n01_a_result_linked_to_a_plain_file_is_refused(tmp_path: Path) -> None:
    base = body_library(tmp_path / "base", "return text")
    head = ("import os\nopen('forged.json', 'w').write('{\"error\": \"forged\"}')\n"
            "os.symlink('forged.json', 'out.json')\nos._exit(0)\n")  # fmt: skip
    trial = body_library(tmp_path / "trial", "return text", head)
    record = xe.Equivalence(
        "eqfix", base, tmp_path / "w", body_settings(tmp_path)
    ).record(trial)
    assert record["error"] == "the trial did not run: the result is not a plain file"


def test_n07_every_trial_tree_is_removed_after_its_record(tmp_path: Path) -> None:
    clone, commit = body_clone(tmp_path)
    root = tmp_path / "art"
    entries = [
        {"trial_id": "t1", "base_commit": commit, **entry(root, "run", "a.diff", touched(clone))},
        {"trial_id": "t2", "base_commit": commit, **entry(root, "run", "b.diff", "not a diff\n")},
    ]  # fmt: skip
    rows = xe.equiv_rows("eqfix", clone, {"base_commit": commit, "kept_diffs": entries},
                         root, tmp_path / "work", body_settings(tmp_path))  # fmt: skip
    assert row(rows.trials, "t1")["status"] == xe.COMPARED
    assert row(rows.trials, "t2")["status"] == xe.NOT_APPLIED
    assert sorted(p.name for p in (tmp_path / "work").glob("base-*/trial-*")) == []
