"""U19: the frozen quality scorer (D37). Builtins over frozen labels, the
strict score line, ``freeze``, the external scorer run from a sandboxed copy
of the base blobs, the score cache and the label-column scan.

Real git repositories in ``tmp_path`` (files from ``tests/fixtures/quality``);
real scorer runs use the sandbox modes ``off`` except one ``required`` run;
an injected ``RunOnce`` stands in for ``procrun.run_once`` to inspect argv or
to fail, and a wrapped ``read_blob`` forges a blob, fails, or plants a link.
"""

from __future__ import annotations

import errno
import hashlib
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import BuiltinMeasure, Direction, QualityCheck
from autonomous_ai_agents.execution import quality
from autonomous_ai_agents.execution.git import GitError, GitWorkspace
from autonomous_ai_agents.execution.phase import phase_dirs
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.quality import (
    FrozenScorer,
    UnscoreableError,
    label_column_leaks,
    read_score,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "quality"
RUN = "run1"
PY = Path(sys.executable)
SECRET = "LEAKME"
OUT = b"cat\ncat\ncat\nbird\n"
_ENV = {
    "PATH": os.environ.get("PATH", os.defpath),
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
Run = Callable[..., RunSample]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], env=_ENV, check=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> GitWorkspace:
    root = Path(os.path.realpath(tmp_path)) / "wt-root"
    root.mkdir()
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root)
    path = tmp_path / "user"
    shutil.copytree(FIXTURES, path)
    subprocess.run(["git", "init", "-q", str(path)], env=_ENV, check=True)
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return GitWorkspace(path)


def builtin(measure: BuiltinMeasure, labels: str = "labels.txt") -> QualityCheck:
    return QualityCheck(
        name="q", measure=measure, labels=labels, frozen_paths=(labels,)
    )


def external(
    script: str = "score.py", interpreter: str = str(PY), *extra: str
) -> QualityCheck:
    frozen = (script, "labels.txt", *extra)
    return QualityCheck(
        name="acc",
        scorer=(interpreter, script),
        frozen_paths=frozen,
        direction=Direction.maximize,
    )


def scorer(
    check: QualityCheck,
    ws: GitWorkspace,
    run: Run = run_once,
    search: str | None = None,
) -> FrozenScorer:
    made = FrozenScorer(check, run=run, network="off", fs="off", search=search)
    made.freeze(ws, ws.head_commit(), run_id=RUN)
    return made


def relink_labels(ws: GitWorkspace) -> None:
    """Commit ``labels.txt`` as a symlink blob to ``real.txt``; score.py +x."""
    (ws.repo / "labels.txt").rename(ws.repo / "real.txt")
    (ws.repo / "labels.txt").symlink_to("real.txt")
    (ws.repo / "score.py").chmod(0o755)
    git(ws.repo, "add", "-A")
    git(ws.repo, "commit", "-qm", "link")


def sample(head: bytes, *, exit: int = 0, size: int | None = None) -> RunSample:
    count = len(head) if size is None else size
    return RunSample(1, 0.0, 0.0, 0, exit, True, True, "0" * 64, head, count, b"")


@pytest.mark.parametrize(
    ("measure", "labels", "output", "expected"),
    [
        (BuiltinMeasure.accuracy, "labels.txt", OUT, 0.75),
        (BuiltinMeasure.error_rate, "labels.txt", OUT, 0.25),
        (BuiltinMeasure.macro_f1, "labels.txt", OUT, 0.6),  # bird 1, cat .8, dog 0
        (BuiltinMeasure.macro_f1, "labels.txt", b"cat\ndog\ncat\nfish", 0.5),
        (BuiltinMeasure.mae, "values.txt", b" 1.5\n2\n3.\n3e0\n", 0.375),
        (BuiltinMeasure.rmse, "values.txt", b"1.5\n2\n3\n3\n", math.sqrt(0.3125)),
    ],
)
def test_each_builtin_scores_the_output_against_the_frozen_labels(
    repo: GitWorkspace,
    measure: BuiltinMeasure,
    labels: str,
    output: bytes,
    expected: float,
) -> None:
    assert scorer(builtin(measure, labels), repo).score(output, None) == pytest.approx(
        expected
    )


@pytest.mark.parametrize(
    ("measure", "output", "why"),
    [
        (BuiltinMeasure.accuracy, b"cat\ndog\ncat\n", "3 lines and the labels 4"),
        (BuiltinMeasure.accuracy, b"a\nb\nc\nd\ne\n", "5 lines in the output, 1 to 4"),
        (BuiltinMeasure.accuracy, b"", "0 lines in the output"),
        (BuiltinMeasure.accuracy, b"\xff" + SECRET.encode(), "not UTF-8"),
        (BuiltinMeasure.accuracy, f"cat\n\n{SECRET}\nx\n".encode(), "line 2 of the"),
        (BuiltinMeasure.mae, f"1\n{SECRET}\n3\n4\n".encode(), "line 2 of the output"),
        (BuiltinMeasure.mae, b"1\nnan\n3\n4\n", "not a finite decimal"),
        (BuiltinMeasure.rmse, b"1\n2\n1e999\n4\n", "line 3 of the output"),
    ],
)
def test_a_malformed_output_is_unscoreable_and_never_quoted(
    repo: GitWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    measure: BuiltinMeasure,
    output: bytes,
    why: str,
) -> None:
    monkeypatch.setattr(settings, "QUALITY_MAX_ROWS", 4)
    labels = (
        "values.txt"
        if measure in (BuiltinMeasure.mae, BuiltinMeasure.rmse)
        else "labels.txt"
    )
    with pytest.raises(UnscoreableError, match=why) as caught:
        scorer(builtin(measure, labels), repo).score(output, None)
    assert SECRET not in str(caught.value) and "cat" not in str(caught.value)


def test_too_many_label_rows_refuse_the_check_at_freeze(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "QUALITY_MAX_ROWS", 3)
    with pytest.raises(EngineError, match="4 lines in the labels, 1 to 3"):
        scorer(builtin(BuiltinMeasure.accuracy), repo)


def test_no_agreed_output_is_unscoreable_and_says_why(repo: GitWorkspace) -> None:
    with pytest.raises(UnscoreableError, match="OUTPUT_TOLERANCE_MAX_BYTES"):
        scorer(builtin(BuiltinMeasure.accuracy), repo).score(None, "a" * 64)


@pytest.mark.parametrize(
    ("line", "value"),
    [
        (b"aip-quality/1 acc=0.5\n", 0.5),
        (b"aip-quality/1 acc=-1.5e-3", -0.0015),
        (b"aip-quality/1 acc=" + b"1" * 109 + b"\n", float("1" * 109)),  # 128 bytes
    ],
)
def test_the_parser_takes_exactly_one_well_formed_line(
    line: bytes, value: float
) -> None:
    assert read_score(sample(line), "acc") == value


@pytest.mark.parametrize(
    ("head", "exit", "why"),
    [
        (b"aip-quality/1 acc=0.5\naip-quality/1 acc=0.5\n", 0, "not one"),
        (b"aip-quality/1 other=0.5\n", 0, "another metric name than 'acc'"),
        (b"aip-quality/1 acc=nan\n", 0, "not one"),
        (b"aip-quality/1 acc=inf\n", 0, "not one"),
        (b"aip-quality/1 acc=1e999\n", 0, "not finite"),
        (b"aip-quality/1 acc=" + b"1" * 110 + b"\n", 0, "printed 129 bytes"),
        (b"aip-quality/1 acc=0.5\x1b[2K\n", 0, "not one"),
        (b"aip-quality/1 acc=0.5\n", 1, "exit status 1.*self-contained"),
        (b"", -9, "signal 9"),
    ],
)
def test_the_parser_refuses_anything_else(head: bytes, exit: int, why: str) -> None:
    with pytest.raises(UnscoreableError, match=why):
        read_score(sample(head[:128], exit=exit, size=len(head)), "acc")


def test_freeze_records_each_files_sha256_and_size(repo: GitWorkspace) -> None:
    made = FrozenScorer(external())

    files = made.freeze(repo, repo.head_commit(), run_id=RUN)

    for frozen in files:
        data = (repo.repo / frozen.path).read_bytes()
        assert (frozen.sha256, frozen.size) == (
            hashlib.sha256(data).hexdigest(),
            len(data),
        )
    assert [f.path for f in files] == ["score.py", "labels.txt"]


def test_freeze_refuses_untracked_oversized_or_changed_files(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo.repo / "new.txt").write_text("x\n")
    check = builtin(BuiltinMeasure.accuracy, "new.txt")
    with pytest.raises(EngineError, match="'new.txt' is not tracked at the base"):
        FrozenScorer(check).freeze(repo, repo.head_commit(), run_id=RUN)
    recorded = FrozenScorer(external()).freeze(repo, repo.head_commit(), run_id=RUN)
    (repo.repo / "labels.txt").write_text("cat\ncat\ncat\ncat\n")
    git(repo.repo, "commit", "-qam", "relabel")
    with pytest.raises(EngineError, match="'labels.txt' changed since the baseline"):
        FrozenScorer(external()).freeze(
            repo, repo.head_commit(), run_id=RUN, recorded=recorded
        )
    sizes = [len((repo.repo / p).read_bytes()) for p in ("score.py", "labels.txt")]
    cap = sum(sizes) - 1  # each file fits alone: the cap is on the total
    assert max(sizes) <= cap
    monkeypatch.setattr(settings, "QUALITY_MAX_FROZEN_BYTES", cap)
    with pytest.raises(EngineError, match=f"hold more than {cap} bytes"):
        FrozenScorer(external()).freeze(repo, repo.head_commit(), run_id=RUN)


@pytest.mark.parametrize(
    "check",
    [builtin(BuiltinMeasure.accuracy), external()],
    ids=["builtin", "external"],
)
def test_freeze_refuses_a_symlink_blob_without_its_target(
    repo: GitWorkspace, check: QualityCheck
) -> None:
    relink_labels(repo)
    made = FrozenScorer(check, network="off", fs="off")
    with pytest.raises(EngineError, match="'labels.txt' is a symlink; freeze the") as e:
        made.freeze(repo, repo.head_commit(), run_id=RUN)
    assert "real.txt" not in str(e.value)


def test_freeze_takes_an_executable_file_but_no_other_mode(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo.repo / "score.py").chmod(0o755)
    git(repo.repo, "commit", "-qam", "exec")
    assert scorer(external(), repo).score(OUT, None) == 0.75
    modes = {"score.py": "100664", "labels.txt": "100644"}
    monkeypatch.setattr(repo, "blob_modes", lambda commit: modes)
    with pytest.raises(EngineError, match="'score.py' is not a regular file"):
        scorer(external(), repo)


def test_freeze_refuses_non_numeric_regression_labels(repo: GitWorkspace) -> None:
    with pytest.raises(EngineError, match="line 1 of the labels is not a finite"):
        scorer(builtin(BuiltinMeasure.mae), repo)


def test_a_second_freeze_drops_the_cached_scores(repo: GitWorkspace) -> None:
    made = scorer(builtin(BuiltinMeasure.accuracy), repo)
    assert made.score(OUT, "a" * 64) == 0.75
    (repo.repo / "labels.txt").write_text("cat\ndog\ncat\ncat\n")
    git(repo.repo, "commit", "-qam", "relabel")
    made.freeze(repo, repo.head_commit(), run_id=RUN)
    assert made.score(OUT, "a" * 64) == 0.5


def test_scoring_needs_a_freeze_and_rechecks_each_blob(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(EngineError, match="freeze first"):
        FrozenScorer(external()).score(OUT, None)
    made = scorer(external(), repo)
    monkeypatch.setattr(repo, "read_blob", lambda *a, **k: b"print('forged')\n")
    with pytest.raises(UnscoreableError, match="'score.py' changed since the baseline"):
        made.score(OUT, None)
    assert not phase_dirs(RUN, "quality").run.exists()


def test_a_copy_that_cannot_be_written_is_unscoreable(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def full(path: Path, data: bytes) -> None:
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    made = scorer(external(), repo)
    monkeypatch.setattr(quality, "_write_new", full)
    with pytest.raises(UnscoreableError, match="could not be made: No space"):
        made.score(OUT, None)
    assert not phase_dirs(RUN, "quality").run.exists()


def test_a_same_length_forged_blob_is_refused_by_its_sha_and_never_runs(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def run(*args: object, **kwargs: object) -> RunSample:
        calls.append(1)
        return sample(b"aip-quality/1 acc=1.0\n")

    made = scorer(external(), repo, run)
    real = repo.read_blob

    def forged(commit: str, path: str, *, limit: int | None = None) -> bytes:
        data = real(commit, path, limit=limit)
        return (
            data.replace(b"len(labels)", b"len(labelz)") if path == "score.py" else data
        )

    monkeypatch.setattr(repo, "read_blob", forged)
    with pytest.raises(UnscoreableError, match="'score.py' changed since the baseline"):
        made.score(OUT, None)
    assert calls == []


def test_a_git_or_containment_failure_while_copying_names_no_detail(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    made = scorer(external(), repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    phase_dirs(RUN, "quality").run.symlink_to(outside)  # a planted <run> link
    with pytest.raises(UnscoreableError, match="^the frozen copy could not be made$"):
        made.score(OUT, None)
    assert list(outside.iterdir()) == []
    phase_dirs(RUN, "quality").run.unlink()

    def broken(*args: object, **kwargs: object) -> bytes:
        raise GitError(f"fatal: bad object {SECRET}")

    monkeypatch.setattr(repo, "read_blob", broken)
    with pytest.raises(UnscoreableError, match="^the frozen copy could not be made$"):
        made.score(OUT, None)
    assert not phase_dirs(RUN, "quality").run.exists()


def test_links_planted_at_a_copy_target_or_at_stdin_are_never_followed(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"untouched\n")
    right = tmp_path / "right.txt"
    right.write_bytes(b"cat\ndog\ncat\nbird\n")  # all four right: 1.0 if read
    made = scorer(external(), repo)
    real = repo.read_blob

    def plant(commit: str, path: str, *, limit: int | None = None) -> bytes:
        if path == "labels.txt":  # appears between the reset and the write
            (phase_dirs(RUN, "quality").worktree / path).symlink_to(victim)
        return real(commit, path, limit=limit)

    monkeypatch.setattr(repo, "read_blob", plant)
    with pytest.raises(UnscoreableError, match="could not be made: File exists"):
        made.score(OUT, None)
    assert victim.read_bytes() == b"untouched\n"
    monkeypatch.setattr(repo, "read_blob", real)

    def swap_stdin(argv: Sequence[str], *args: object, **kwargs: object) -> RunSample:
        Path(argv[5]).unlink()
        Path(argv[5]).symlink_to(right)
        return run_once(argv, *args, **kwargs)  # type: ignore[arg-type]

    with pytest.raises(UnscoreableError, match="self-contained"):
        scorer(external(), repo, swap_stdin).score(OUT, None)


def test_a_stale_copy_does_not_survive_materialisation(repo: GitWorkspace) -> None:
    made = scorer(external("score_import.py"), repo)
    stale = phase_dirs(RUN, "quality").worktree
    stale.mkdir(parents=True)
    (stale / "helper.py").write_text("VALUE = 1\n")
    with pytest.raises(UnscoreableError, match="self-contained"):
        made.score(OUT, None)


@pytest.mark.parametrize(
    ("interpreter", "why"),
    [
        ("bin/python3", "a bare interpreter name or an absolute path"),
        ("python3.99", "'python3.99' is not on PATH"),
        ("/nonexistent/python3", "is not an executable file"),
    ],
)
def test_the_interpreter_is_resolved_and_checked_at_freeze(
    repo: GitWorkspace, interpreter: str, why: str
) -> None:
    with pytest.raises(EngineError, match=why):
        scorer(external(interpreter=interpreter), repo, search=str(PY.parent))


def test_a_bare_interpreter_is_found_but_never_under_worktree_root(
    repo: GitWorkspace,
) -> None:
    assert (
        scorer(external(interpreter="python3"), repo, search=str(PY.parent)).score(
            OUT, None
        )
        == 0.75
    )
    planted = settings.WORKTREE_ROOT / "python3"
    planted.symlink_to(PY)
    with pytest.raises(EngineError, match="must not live under WORKTREE_ROOT"):
        scorer(
            external(interpreter="python3"), repo, search=str(settings.WORKTREE_ROOT)
        )


def test_relative_search_entries_are_skipped(
    repo: GitWorkspace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    local = tmp_path / "cwd"
    local.mkdir()
    (local / "python3").symlink_to(PY)
    monkeypatch.chdir(local)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(EngineError, match="'python3' is not on PATH"):
        scorer(external(interpreter="python3"), repo, search=f".:{empty}")
    path = os.environ["PATH"]
    monkeypatch.setenv("PATH", f".:bin:{empty}")
    made = FrozenScorer(external(interpreter="python3"))  # reads PATH here
    monkeypatch.setenv("PATH", path)  # git needs its own
    with pytest.raises(EngineError, match="'python3' is not on PATH"):
        made.freeze(repo, repo.head_commit(), run_id=RUN)
    monkeypatch.setenv("PATH", "")
    assert quality._default_search() == os.defpath


def test_a_link_outside_worktree_root_to_an_interpreter_inside_is_refused(
    repo: GitWorkspace, tmp_path: Path
) -> None:
    inside = settings.WORKTREE_ROOT / "python3"
    inside.write_text("#!/bin/sh\n")
    inside.chmod(0o755)
    outside = tmp_path / "bin"
    outside.mkdir()
    (outside / "python3").symlink_to(inside)
    with pytest.raises(EngineError, match="must not live under WORKTREE_ROOT"):
        scorer(external(interpreter=str(outside / "python3")), repo)


def test_a_hash_or_set_order_scorer_is_deterministic_and_site_files_never_run(
    repo: GitWorkspace,
) -> None:
    check = external("score_hash.py", str(PY), "sitecustomize.py", "usercustomize.py")
    first = scorer(check, repo).score_baseline(OUT, None)
    assert scorer(check, repo).score(OUT, None) == first  # PYTHONHASHSEED=0 holds


def test_the_frozen_copy_runs_sandboxed_not_the_edited_worktree_scorer(
    repo: GitWorkspace,
) -> None:
    made = FrozenScorer(external(), network="required", fs="required")
    made.freeze(repo, repo.head_commit(), run_id=RUN)
    (repo.repo / "score.py").write_text("print('aip-quality/1 acc=1.0')\n")

    assert made.score(OUT, None) == 0.75  # the predictions came on stdin
    assert not phase_dirs(RUN, "quality").run.exists()


@pytest.mark.parametrize(
    ("network", "fs", "expected"),
    [
        ("required", "best_effort", ("required", "best_effort")),
        (None, None, ("off", "off")),  # the settings' modes (set to off here)
    ],
)
def test_the_scorer_runs_with_minus_s_minus_b_from_the_copy_with_no_pythonpath(
    repo: GitWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    network: IsolationMode | None,
    fs: IsolationMode | None,
    expected: tuple[str, str],
) -> None:
    monkeypatch.setattr(settings, "NETWORK_ISOLATION", "off")
    monkeypatch.setattr(settings, "FS_ISOLATION", "off")
    seen: list[tuple[list[str], Path, dict[str, str], SandboxPolicy, OutputCaps]] = []
    fresh: list[Sequence[Path]] = []

    def run(
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:
        policy = sandbox
        copy = phase_dirs(RUN, "quality").worktree
        assert sorted(p.name for p in copy.iterdir()) == ["labels.txt", "score.py"]
        assert (
            Path(argv[5]).read_bytes() == OUT
            and Path(argv[5]).parent == policy.writable[1]
        )
        assert timeout_s == settings.QUALITY_TIMEOUT_S
        seen.append((list(argv), cwd, dict(env), policy, caps))
        fresh.append(fresh_dirs)
        return sample(b"aip-quality/1 acc=0.25\n")

    made = FrozenScorer(external(), run=run, network=network, fs=fs)
    made.freeze(repo, repo.head_commit(), run_id=RUN)
    assert made.score(OUT, None) == 0.25

    argv, cwd, env, policy, caps = seen[0]
    copy, scratch = (
        phase_dirs(RUN, "quality").worktree,
        phase_dirs(RUN, "quality").scratch,
    )
    assert argv[6:] == [str(PY), "-s", "-B", str(copy / "score.py")]
    assert argv[:3] == [sys.executable, "-I", "-S"] and cwd == copy
    assert (policy.network, policy.fs) == expected
    assert policy.writable == (copy, scratch)
    assert fresh == [(scratch / "home", scratch / "tmp")]
    assert "PYTHONPATH" not in env and env["PYTHONHASHSEED"] == "0"
    assert env["HOME"].startswith(str(policy.writable[1]))
    assert (caps.head_bytes, caps.stderr_tail_bytes) == (128, 1)
    assert not phase_dirs(RUN, "quality").run.exists()


@pytest.mark.parametrize(
    ("reason", "why"),
    [
        (f"no measurement report (wrapper exit 1): {SECRET}", "no measurement report"),
        ("timeout after 300 s", "timeout after 300 s"),
        ("boom", "boom"),
    ],
)
def test_a_scorer_that_fails_leaves_no_copy_and_no_stderr(
    repo: GitWorkspace, reason: str, why: str
) -> None:
    def run(*args: object, **kwargs: object) -> RunSample:
        assert phase_dirs(RUN, "quality").worktree.is_dir()
        raise RunFailure(reason)

    with pytest.raises(UnscoreableError, match=why) as caught:
        scorer(external(), repo, run).score(OUT, None)
    assert SECRET not in str(caught.value)
    assert not phase_dirs(RUN, "quality").run.exists()


def test_a_scorer_importing_the_repository_fails(repo: GitWorkspace) -> None:
    with pytest.raises(UnscoreableError, match="cannot import the project's packages"):
        scorer(external("score_import.py"), repo).score(OUT, None)


def test_a_nondeterministic_scorer_is_refused_at_baseline(repo: GitWorkspace) -> None:
    assert scorer(external(), repo).score_baseline(OUT, "a" * 64) == 0.75
    assert (
        scorer(builtin(BuiltinMeasure.accuracy), repo).score_baseline(OUT, None) == 0.75
    )
    with pytest.raises(UnscoreableError, match="not deterministic"):
        scorer(external("score_random.py"), repo).score_baseline(OUT, None)


def test_an_output_is_scored_once_per_exact_fingerprint(repo: GitWorkspace) -> None:
    calls: list[int] = []

    def run(*args: object, **kwargs: object) -> RunSample:
        calls.append(1)
        return sample(b"aip-quality/1 acc=0.5\n")

    made = scorer(external(), repo, run)
    for fingerprint in ("a" * 64, "a" * 64, None, None):
        assert made.score(OUT, fingerprint) == 0.5
    assert len(calls) == 3  # one cached raw fingerprint, two uncached rows
    assert made.score_baseline(OUT, "a" * 64) == 0.5
    assert len(calls) == 5  # the determinism check always runs twice


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("test.csv", ("test.csv column 2",)),
        ("test.tsv", ("test.tsv column 2",)),
        ("labels.txt", ("labels.txt column 1",)),
        ("reordered.csv", ()),
        ("values.txt", ()),
    ],
)
def test_label_column_leaks_finds_the_labels_as_a_column(
    name: str, found: tuple[str, ...]
) -> None:
    labels = (FIXTURES / "labels.txt").read_bytes()
    assert label_column_leaks(labels, {name: (FIXTURES / name).read_bytes()}) == found


def test_label_column_leaks_skips_what_it_cannot_read() -> None:
    labels = (FIXTURES / "labels.txt").read_bytes()
    files = {"bin": b"\xff\n" * 4, "short": b"cat", "quote": b'a"b,"c\n' * 4}
    assert label_column_leaks(labels, files) == ()
    assert label_column_leaks(b"\xff", {"x": b"\xff"}) == ()
