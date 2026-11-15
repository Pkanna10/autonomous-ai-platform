"""UEX (O71 item 4): ci.yml's ``exam-sitting`` suite (``ci-UEX.patch``).

Red until the patch is applied: the run step, under bash with a fake ``uv``,
exports X2-0's environment exactly as an ``ideas-x2`` X2-0 dispatch does,
with ``SITE_STACKS=on`` the one difference, runs only the sitting's live
module, refuses key 1, a cap below one paper's and an ``x2_dispatch``; the
suite is a choice with its timeout, its need and Stage A's ignore.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from autonomous_ai_agents.common.config import Settings

from . import exam_sitting as ex
from . import ideas_x2 as x2
from . import test_corpus_guards as cg

LIVE_FILE = "tests/live/test_exam_sitting_live.py"


def _step(tmp_path: Path, suite: str, slot: str, cap: str,
          **inputs: str) -> tuple[int, str, str, dict[str, str]]:  # fmt: skip
    """The run step under ``bash -e``; its exit, output, uv call and env."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(
        f'#!/bin/sh\nprintf "%s" "$*" > "{tmp_path / "called.txt"}"\n'
        f'env > "{tmp_path / "env.txt"}"\n',
        encoding="utf-8",
    )
    (bin_dir / "uv").chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(cg._run_script(), encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin", "HOME": str(tmp_path),
        "ANTHROPIC_API_KEY": "placeholder-not-a-key", "INPUT_KEY_SLOT": slot,
        "INPUT_SUITE": suite, "INPUT_ENGINE_MODEL": "claude-opus-5-5",
        "INPUT_SUITE_CAP_USD": cap, "INPUT_MODE": "aimed", "INPUT_EDITOR_MODEL": "default",
        "LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl"),
        **{f"INPUT_{k.upper()}": v for k, v in inputs.items()},
    }  # fmt: skip
    proc = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True,
                          text=True, timeout=60, check=False)  # fmt: skip
    called = tmp_path / "called.txt"
    seen = tmp_path / "env.txt"
    exported = dict(
        line.split("=", 1)
        for line in (
            seen.read_text(encoding="utf-8") if seen.exists() else ""
        ).splitlines()
        if "=" in line
    )
    call = called.read_text(encoding="utf-8") if called.exists() else ""
    return proc.returncode, proc.stdout + proc.stderr, call, exported


PAPER = {"exam_paper": "t2", "exam_spent_usd": "0"}


def test_the_sitting_exports_x2_0s_environment_with_site_stacks_on(
    tmp_path: Path,
) -> None:
    (tmp_path / "exam").mkdir()
    (tmp_path / "x2").mkdir()
    code, output, call, env = _step(
        tmp_path / "exam", "exam-sitting", "2", "12", **PAPER
    )
    assert code == 0, output
    assert call == f"run pytest {LIVE_FILE} -m live --no-cov -n 0 -rA"
    for key, value in x2.arm_env(ex.X2_EX).items():
        assert env[key] == value, key
    assert env["LIVE_KEY_SLOT"] == "2" and env["LIVE_SUITE_CAP_USD"] == "12"
    assert (env[ex.PAPER_ENV], env[ex.SPENT_ENV]) == ("t2", "0")
    assert (env["PAIRED_TRIALS"], env["CONFIRM_WINNERS"]) == ("true", "true")
    assert "LIVE_X2_DISPATCH" not in env
    code, output, _, theirs = _step(tmp_path / "x2", "ideas-x2", "2", "38",
                                    x2_dispatch="X2-0:tomli")  # fmt: skip
    assert code == 0, output
    assert ex.PAPER_ENV not in theirs and ex.SPENT_ENV not in theirs
    fields = set(Settings.model_fields)  # every engine setting either step exported
    mine = {k: v for k, v in env.items() if k in fields}
    base = {k: v for k, v in theirs.items() if k in fields}
    assert {k for k in mine.keys() | base.keys() if mine.get(k) != base.get(k)} == {
        "SITE_STACKS"
    }
    assert (env["SITE_STACKS"], theirs["SITE_STACKS"]) == ("on", "off")


def test_the_sitting_refuses_before_pytest(tmp_path: Path) -> None:
    """Key 1, a cap below one paper's, an ``x2_dispatch``, a paper off t1-t4
    or none, a spend that is no number or none; and the sitting's inputs on
    another suite."""
    cases = {
        "key1": ("exam-sitting", "1", "12", PAPER, "key_slot 2 only"),
        "low": ("exam-sitting", "2", "6", PAPER, "below the 7 USD"),
        "dispatch": ("exam-sitting", "2", "12", {**PAPER, "x2_dispatch": "X2-0:tomli"},
                     "only for the ideas-x2"),
        "no-paper": ("exam-sitting", "2", "12", {"exam_spent_usd": "0"}, "needs exam_paper"),
        "bad-paper": ("exam-sitting", "2", "12", {**PAPER, "exam_paper": "t5"},
                      "needs exam_paper"),
        "no-spend": ("exam-sitting", "2", "12", {"exam_paper": "t1"}, "needs exam_spent_usd"),
        "bad-spend": ("exam-sitting", "2", "12", {**PAPER, "exam_spent_usd": "1;id"},
                      "needs exam_spent_usd"),
        "elsewhere": ("stage-a", "1", "12", {"exam_paper": "t1"}, "only for the exam-sitting"),
        "spend-elsewhere": ("stage-a", "1", "12", {"exam_spent_usd": "0"},
                            "only for the exam-sitting"),
    }  # fmt: skip
    for name, (suite, slot, cap, extra, words) in cases.items():
        (tmp_path / name).mkdir()
        code, output, call, _ = _step(tmp_path / name, suite, slot, cap, **extra)
        assert (code, call) == (1, ""), name
        assert words in output, (name, output)


def test_the_sitting_is_a_choice_with_its_timeouts_need_and_stage_a_ignore() -> None:
    """One paper a dispatch: each paper's job timeout is its
    ``paper_timeout``, and its two inputs reach the step through env only."""
    assert "exam-sitting" in cg._choice_options(
        cg._ci_block("      suite:", "      mode:")
    )
    script = cg._run_script()
    assert f"exam-sitting) paths=({LIVE_FILE}); need=7 ;;" in script
    assert ex.sitting_need() <= 7 < ex.sitting_need() + 1
    assert f"--ignore={LIVE_FILE}" in re.findall(r"^corpus=\((.*)\)$", script, re.M)[0]
    block = cg._ci_block("  live-smoke:", "    defaults:")
    cfg = x2.arm_settings(ex.X2_EX)
    found = dict(re.findall(r"inputs\.suite == 'exam-sitting' && inputs\.exam_paper == "
                            r"'(t\d)' && (\d+) \|\|", block))  # fmt: skip
    assert found == {p.key: str(ex.paper_timeout(p, cfg)) for p in ex.EXAM_PAPERS}
    assert all(int(m) <= ex.JOB_CEILING for m in found.values())
    step = cg._ci_block(
        "      - name: Run live tests", "      - name: Upload live corpus"
    )
    assert "INPUT_EXAM_PAPER: ${{ inputs.exam_paper }}" in step
    assert "INPUT_EXAM_SPENT_USD: ${{ inputs.exam_spent_usd }}" in step
    assert "exam-sitting 7 " in cg._ci_block("      suite_cap_usd:", "\n\n")
    for name in ("exam_paper", "exam_spent_usd"):
        assert f"      {name}:\n" in cg._ci_block(
            "  workflow_dispatch:", "\npermissions:"
        )
