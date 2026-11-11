"""U-patch: every X2 run writes each kept trial's diff and the delivered
combined patch into the results artifact, and their sha256 in its rows.

The fakes run (``test_ideas_x2_guards.x2_run``: ``run_one`` with the loop
and the engine faked) writes ``$LIVE_RESULTS_PATH`` in ``tmp_path``, so the
patch directory is ``tmp_path / x2_patches.PATCH_DIR``; each case reads the
files back, compares them with the state's own diffs and hashes their
bytes. The truncation case takes its diff from a real ``GitWorkspace`` on a
throwaway repository. Nothing here changes a request.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.common.models import (
    Delivery,
    DeliveryKind,
    Trial,
    VerdictOutcome,
)
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.orchestrator.main import EngineRunResult

from . import ideas_x2 as x2
from . import test_ideas_x2_guards as xg
from . import x2_patches as xp
from .conftest import KEY_SLOT_ENV, redact_keys
from .corpus import RESULTS_ENV
from .discovery_io import ResultsSink
from .test_corpus_guards import _ci_block

x2_run = xg.x2_run
Json = dict[str, Any]
BASE = "b" * 40
TIP = "d" * 40
COMBINED = (
    f"diff --git a/tomli/_parser.py b/tomli/_parser.py\n+combined é {xg.SECRET}\n"
)
RUN_DIR = f"{xp.PATCH_DIR}/X2-0-tomli"


def _diff(n: int) -> str:
    return f"diff --git a/tomli/_re.py b/tomli/_re.py\n+change {n}\n"


class _Diffs(xg._Engine):
    """``_Engine`` whose state has a diff, commit and base per trial and a
    delivered branch, then ``change``; the state is kept for the test."""

    def __init__(self, change: Callable[[dict[str, Any]], None] | None = None,
                 **kwargs: Any) -> None:  # fmt: skip
        super().__init__(**kwargs)
        self.change, self.state = change, cast(dict[str, Any], {})

    def run(self, loop: Any, run: Any, isolation: Any, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        if self.breach:
            return super().run(loop, run, isolation, model=model, record=record)
        result = xg._state()
        st = self.state = cast(dict[str, Any], result.state)
        st["trials"] = [t.model_copy(update={"diff": _diff(n), "base_commit": BASE,
                                             "commit": f"{n}" * 40})
                        for n, t in enumerate(st["trials"])]  # fmt: skip
        st["base_commit"] = BASE
        st["delivery"] = Delivery(project_id="p", kind=DeliveryKind.branch,
                                  branch="engine/run-run", commit=TIP,
                                  combined_diff=COMBINED, report_markdown="r")  # fmt: skip
        if self.change is not None:
            self.change(st)
        self.calls.append("run")
        record(SimpleNamespace(guard="ok"), result)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_row(rows: list[Json]) -> Json:
    (run,) = [r for r in rows if r["experiment"] == x2.RUN_EXPERIMENT]
    return run


def _ideas(rows: list[Json]) -> dict[str, Json]:
    return {
        r["hypothesis_id"]: r for r in rows if r["experiment"] == x2.IDEA_EXPERIMENT
    }


def _files(tmp_path: Path) -> list[str]:
    top = tmp_path / xp.PATCH_DIR
    return sorted(str(p.relative_to(tmp_path)) for p in top.rglob("*") if p.is_file())


def _first_attempt(st: dict[str, Any]) -> None:
    """S1's hypothesis gets an earlier trial; its verdict names the later."""
    first = st["trials"][0]
    early = Trial(hypothesis_id=first.hypothesis_id, round=1, diff="the first attempt\n",
                  base_commit=BASE, commit="e" * 40)  # fmt: skip
    st["trials"] = [early, *st["trials"]]


def test_each_kept_file_holds_its_verdicts_trials_own_diff(
    x2_run: Any, tmp_path: Path
) -> None:
    engine = _Diffs(_first_attempt)
    _, rows = x2_run(engine)
    st, ideas = engine.state, _ideas(rows)
    trials = {t.id: t for t in st["trials"]}
    kept = {
        v.hypothesis_id: v for v in st["verdicts"] if v.outcome is VerdictOutcome.keep
    }
    assert len(kept) == 2 and len(trials) == 5
    for hid, verdict in kept.items():
        entry, trial = ideas[hid]["diff"], trials[verdict.trial_id]
        assert entry["trial_id"] == trial.id
        assert entry["file"] == f"{RUN_DIR}/trial-{trial.id}.diff"
        written = (tmp_path / entry["file"]).read_bytes()
        assert written == trial.diff.encode("utf-8")  # that trial's own diff
        assert entry["sha256"] == hashlib.sha256(written).hexdigest()
        assert entry["bytes"] == len(written) and entry["error"] is None
        assert (entry["commit"], entry["base_commit"]) == (trial.commit, BASE)
        assert (entry["truncated"], entry["original_bytes"]) == (False, None)
    s1 = next(h for h in kept if trials[kept[h].trial_id].round == 1)
    assert (
        b"the first attempt" not in (tmp_path / ideas[s1]["diff"]["file"]).read_bytes()
    )
    for hid, row in ideas.items():
        if hid not in kept:
            assert "diff" not in row  # not kept: the row as before
    run = _run_row(rows)
    assert run["base_commit"] == BASE and run["patch_dir"] == RUN_DIR
    assert [{k: d[k] for k in ("hypothesis_id", "file", "sha256")} for d in run["kept_diffs"]] == [
        {"hypothesis_id": hid, "file": ideas[hid]["diff"]["file"],
         "sha256": ideas[hid]["diff"]["sha256"]} for hid in ideas if hid in kept
    ]  # fmt: skip
    assert run["kept_diffs_note"] is None
    assert len(_files(tmp_path)) == 3  # two kept diffs, the delivered patch


def test_the_delivered_patch_is_the_redacted_delivery_and_names_its_trials(
    x2_run: Any, tmp_path: Path
) -> None:
    engine = _Diffs()
    _, rows = x2_run(engine)
    patch = _run_row(rows)["delivered_patch"]
    assert patch["file"] == f"{RUN_DIR}/{xp.DELIVERED_FILE}"
    written = (tmp_path / patch["file"]).read_bytes()
    assert written == redact_keys(COMBINED).encode("utf-8")
    assert xg.SECRET.encode() not in written and b"[redacted]" in written
    assert (patch["sha256"], patch["bytes"]) == (
        _sha(tmp_path / patch["file"]),
        len(written),
    )
    comb = engine.state["combination"]
    assert (patch["base_commit"], patch["tip_commit"], patch["branch"]) == (
        comb.base_commit,
        TIP,
        "engine/run-run",
    )  # the tip is the delivery's commit
    assert patch["applied_trial_ids"] == list(comb.applied_trial_ids)
    assert _run_row(rows)["delivered_patch_note"] is None


def _three_keeps(st: dict[str, Any]) -> None:
    st["verdicts"] = [v.model_copy(update={"outcome": VerdictOutcome.keep})
                      if v.outcome is VerdictOutcome.inconclusive else v
                      for v in st["verdicts"]]  # fmt: skip


def test_three_keeps_two_applied_marks_each_kept_diff(x2_run: Any) -> None:
    engine = _Diffs(_three_keeps)
    _, rows = x2_run(engine)
    run = _run_row(rows)
    applied = engine.state["combination"].applied_trial_ids
    assert len(run["kept_diffs"]) == 3 and len(applied) == 2
    assert {d["trial_id"]: d["applied"] for d in run["kept_diffs"]} == {
        d["trial_id"]: d["trial_id"] in applied for d in run["kept_diffs"]
    }
    assert sum(d["applied"] for d in run["kept_diffs"]) == 2
    assert run["delivered_patch"]["applied_trial_ids"] == list(applied)


def test_a_delivery_without_a_commit_records_no_tip(x2_run: Any) -> None:
    def no_commit(st: dict[str, Any]) -> None:
        st["delivery"] = st["delivery"].model_copy(update={"commit": None})

    _, rows = x2_run(_Diffs(no_commit))
    assert _run_row(rows)["delivered_patch"]["tip_commit"] is None


def _no_keep(st: dict[str, Any]) -> None:
    st["verdicts"] = [v.model_copy(update={"outcome": VerdictOutcome.reject})
                      for v in st["verdicts"]]  # fmt: skip
    st["combination"], st["delivery"] = None, None


def test_a_run_with_no_keep_writes_no_diff_and_says_so(
    x2_run: Any, tmp_path: Path
) -> None:
    _, rows = x2_run(_Diffs(_no_keep))
    assert not any("diff" in r for r in _ideas(rows).values())
    run = _run_row(rows)
    assert run["kept_diffs"] == [] and run["kept_diffs_note"] == xp.NO_KEEP
    assert run["delivered_patch"] is None
    assert run["delivered_patch_note"] == xp.NO_COMBINE
    assert _files(tmp_path) == []


def _not_held(st: dict[str, Any]) -> None:
    st["combination"] = st["combination"].model_copy(update={"holds": False})
    st["delivery"] = None


def test_a_run_with_no_held_combine_writes_no_combined_patch_and_says_so(
    x2_run: Any, tmp_path: Path
) -> None:
    _, rows = x2_run(_Diffs(_not_held))
    run = _run_row(rows)
    assert len(run["kept_diffs"]) == 2  # the kept diffs are still written
    assert not any(d["applied"] for d in run["kept_diffs"])  # nothing delivered
    assert run["delivered_patch"] is None
    assert run["delivered_patch_note"] == xp.NOT_HELD
    assert not any(f.endswith(xp.DELIVERED_FILE) for f in _files(tmp_path))


def _report_only(st: dict[str, Any]) -> None:
    st["delivery"] = Delivery(project_id="p", kind=DeliveryKind.report_only,
                              report_markdown="r")  # fmt: skip


@pytest.mark.parametrize("change", [_report_only, lambda st: st.update(delivery=None)])
def test_a_held_combine_without_a_branch_writes_no_patch_and_says_so(
    change: Callable[[dict[str, Any]], None], x2_run: Any
) -> None:
    _, rows = x2_run(_Diffs(change))
    run = _run_row(rows)
    assert run["delivered_patch"] is None
    assert run["delivered_patch_note"] == xp.NO_BRANCH


def _orphan(st: dict[str, Any]) -> None:
    st["trials"] = st["trials"][1:]  # the S1 idea's kept trial is not recorded


def test_a_kept_verdict_without_its_trial_says_so(x2_run: Any) -> None:
    engine = _Diffs(_orphan)
    _, rows = x2_run(engine)
    run = _run_row(rows)
    (orphan,) = [d for d in run["kept_diffs"] if d["file"] is None]
    assert orphan["error"] == xp.ORPHAN and orphan["sha256"] is None
    assert orphan["trial_id"] not in {t.id for t in engine.state["trials"]}
    assert len(run["kept_diffs"]) == 2 and run["kept_diffs_note"] is None
    assert _ideas(rows)[orphan["hypothesis_id"]]["diff"]["error"] == xp.ORPHAN


def test_a_failed_write_keeps_every_row_and_names_the_error(
    x2_run: Any, tmp_path: Path
) -> None:
    (tmp_path / RUN_DIR / xp.DELIVERED_FILE).mkdir(parents=True)  # a directory there
    _, rows = x2_run(_Diffs())
    run = _run_row(rows)
    patch = run["delivered_patch"]
    assert (patch["file"], patch["sha256"]) == (None, None)
    assert patch["error"] == "IsADirectoryError: Is a directory"
    assert all(d["error"] is None for d in run["kept_diffs"])  # the others written
    assert len(_ideas(rows)) == 5 and str(tmp_path) not in json.dumps(rows)


def test_a_blocked_patch_root_still_writes_every_row(
    x2_run: Any, tmp_path: Path
) -> None:
    (tmp_path / xp.PATCH_DIR).write_text("not a directory", encoding="utf-8")
    _, rows = x2_run(_Diffs())
    run = _run_row(rows)
    errors = {d["error"] for d in run["kept_diffs"]} | {run["delivered_patch"]["error"]}
    assert errors == {"NotADirectoryError: Not a directory"}
    assert str(tmp_path) not in json.dumps(rows)


def test_a_breach_with_a_blocked_patch_root_records_its_rows_then_raises(
    x2_run: Any, tmp_path: Path
) -> None:
    """``record`` runs inside ``run_engine``'s handler: no state, so no
    write is tried, and the rows still reach the results."""
    (tmp_path / xp.PATCH_DIR).write_text("not a directory", encoding="utf-8")
    with pytest.raises(AssertionError, match="repository changed"):
        x2_run(_Diffs(breach=True))
    rows = [json.loads(x) for x in
            (tmp_path / "x2.jsonl").read_text(encoding="utf-8").splitlines()]  # fmt: skip
    run = _run_row(rows)
    assert (run["base_commit"], run["kept_diffs"], run["delivered_patch"]) == (
        None,
        [],
        None,
    )
    assert run["kept_diffs_note"] == xp.NO_KEEP
    assert run["delivered_patch_note"] == xp.NO_COMBINE


def test_the_patch_root_sits_beside_the_results_file(tmp_path: Path) -> None:
    out = tmp_path / "live-results.jsonl"
    assert (
        xp.patch_root(ResultsSink({RESULTS_ENV: str(out)})) == tmp_path / xp.PATCH_DIR
    )
    assert xp.patch_root(ResultsSink({})) is None


def test_without_a_results_path_nothing_is_written_and_the_hash_is_kept(
    tmp_path: Path,
) -> None:
    entry = xp.PatchWriter(None, "X2-0-tomli").write(xp.DELIVERED_FILE, COMBINED)
    data = redact_keys(COMBINED).encode("utf-8")
    assert entry == {"file": None, "sha256": hashlib.sha256(data).hexdigest(),
                     "bytes": len(data), "truncated": False, "original_bytes": None,
                     "error": None}  # fmt: skip
    assert list(tmp_path.iterdir()) == []


def _git(repo: Path, *args: str) -> str:
    argv = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args]
    return subprocess.run(argv, cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


def test_a_diff_the_engine_truncated_is_flagged_with_its_original_size(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "m.py").write_text("x = 0\n", encoding="utf-8")
    _git(repo, "add", "m.py")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "m.py").write_text("x = 1\n" * 50, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "tip")
    tip = _git(repo, "rev-parse", "HEAD")
    git = GitWorkspace(repo)
    whole = git.diff_commits(base, tip)
    text = git.diff_commits(base, tip, max_bytes=40)  # the engine's own cap path
    assert text != whole
    entry = xp.PatchWriter(tmp_path / "out", "X2-0-tomli").write("trial-x.diff", text)
    assert (entry["truncated"], entry["original_bytes"]) == (True, len(whole.encode()))
    assert (tmp_path / "out" / "X2-0-tomli" / "trial-x.diff").read_text(
        encoding="utf-8"
    ) == text
    assert (
        xp.PatchWriter(None, "X2-0-tomli").write("w.diff", whole)["truncated"] is False
    )


@pytest.mark.parametrize(
    "name", ["", "../x", "a/b", ".hidden", "a\\b", "x..y", "é", "a" * 129, "a\n"]
)
def test_a_name_off_the_safe_set_is_refused(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a safe file name"):
        xp.safe_name(name)
    for writer, file in ((xp.PatchWriter(tmp_path, name), "x.diff"),
                         (xp.PatchWriter(tmp_path, "X2-0-tomli"), name)):  # fmt: skip
        entry = writer.write(file, "d")
        assert entry["file"] is None
        assert str(entry["error"]).startswith("ValueError: not a safe file name")
    assert xp.PatchWriter(tmp_path, name).folder is None
    assert list(tmp_path.iterdir()) == []


def test_a_run_directory_linked_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root, away = tmp_path / "root", tmp_path / "away"
    root.mkdir()
    away.mkdir()
    (root / "X2-0-tomli").symlink_to(away, target_is_directory=True)
    entry = xp.PatchWriter(root, "X2-0-tomli").write("trial-x.diff", "d")
    assert (entry["file"], entry["error"]) == (None, xp.OUTSIDE)
    assert list(away.iterdir()) == []


def test_text_that_is_not_utf_8_is_an_error_not_a_raise(tmp_path: Path) -> None:
    entry = xp.PatchWriter(tmp_path, "X2-0-tomli").write("t.diff", "bad \ud800")
    assert entry["file"] is None
    assert str(entry["error"]).startswith("UnicodeEncodeError: ")


def test_each_arms_run_directory_is_its_own() -> None:
    names = {xp.run_dir(a.key, "tomli") for a in x2.EVERY_ARM}
    assert len(names) == len(x2.EVERY_ARM) and "X2-0_-tomli" in names
    assert all(xp.safe_name(n) == n for n in names)


def test_an_engine_trial_id_names_its_file() -> None:
    trial = Trial(hypothesis_id="h", round=1)
    assert xp.safe_name(xp.trial_file(trial.id)) == f"trial-{trial.id}.diff"


def test_ci_uploads_the_patch_directory_beside_the_results() -> None:
    """Fails until ci-patch.patch is applied: the Lead commits them together."""
    step = _ci_block(
        "      - name: Upload live corpus results", "          if-no-files-found:"
    )
    found = re.search(r"path: \|\n((?:            \S.*\n)+)", step)
    assert found is not None, step
    assert [x.strip() for x in found.group(1).splitlines()] == [
        "${{ runner.temp }}/live-results.jsonl",
        f"${{{{ runner.temp }}}}/{xp.PATCH_DIR}/",
    ]


@pytest.mark.parametrize(("slot", "window"), [(None, "W1"), ("1", "W1"), ("2", "W2")])
def test_the_run_row_names_the_window_whose_key_paid(
    x2_run: Any, slot: str | None, window: str
) -> None:
    """O59: the X2 run row, the one the STATUS ledger copies spend from,
    carries the window of the key the dispatch chose (U-key's slot)."""
    _, rows = x2_run(environ={} if slot is None else {KEY_SLOT_ENV: slot})
    assert _run_row(rows)["window"] == window
