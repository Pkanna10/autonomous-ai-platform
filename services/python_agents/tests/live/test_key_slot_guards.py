"""Offline guards of the live job's key slot (U-key, ``.github/workflows/ci.yml``).

Not ``live``: these spend nothing. The ``live`` environment holds two keys,
``ANTHROPIC_API_KEY`` (slot 1, Window 1) and ``ANTHROPIC_API_KEY_2`` (slot
2, Window 2); the ``key_slot`` dispatch input (default 1) picks the one the
run step exports as ``ANTHROPIC_API_KEY``. Pinned here: the input, its
default, both secret names, the slot-naming missing-key error, that no step
of any workflow reads a key secret except through the slot, and, by running
the step's own script under bash with a fake ``uv``, that slot 1 (or no slot,
an older caller) runs exactly as before, that the slot reaches the test
process as ``LIVE_KEY_SLOT`` (where ``conftest.key_window`` turns it into
the cost table's ``W1`` / ``W2``) and that any other slot is refused before
anything runs.

Fakes and what they stand for: a fake ``uv`` on ``PATH`` for the test
process (it records its argv and environment); the key a placeholder string.
What only a live dispatch proves: that GitHub resolves the dynamic
``secrets[...]`` index to the slot's secret of environment ``live``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from .conftest import KEY_SLOT_ENV, KEY_WINDOWS, key_window
from .test_corpus_guards import CI_WORKFLOW, RUN_TIMEOUT_S, _ci_block, _run_script

SLOT_SECRETS = {"1": "ANTHROPIC_API_KEY", "2": "ANTHROPIC_API_KEY_2"}
SLOT_KEY = (
    "ANTHROPIC_API_KEY: ${{ secrets[inputs.key_slot == '2' && "
    "'ANTHROPIC_API_KEY_2' || 'ANTHROPIC_API_KEY'] }}"
)
STEP = ("      - name: Run live tests", "      - name: Upload live corpus")
_SECRET_REF = re.compile(r"secrets(?:\.[A-Za-z_]\w*|\[[^\]]*\])")
GITHUB_DIR = CI_WORKFLOW.parents[1]
_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_SECRETS_WORD = re.compile(r"\bsecrets\b", re.IGNORECASE)
# Outside ${{ }}: a context access (secrets. / secrets[), a key (secrets:,
# as in 'secrets: inherit') or the whole context passed to a function.
_BARE_READ = re.compile(
    r"\bsecrets\s*(?:\.\w|[\[:])|\(\s*secrets\s*\)|tojson\s*\(\s*secrets",
    re.IGNORECASE,
)
# Every secrets read under .github/: the slot's index, and docker-build's
# registry token (no API key).
ALLOWED_READS = [
    ("workflows/ci.yml", SLOT_KEY.split("${{ ", 1)[1].removesuffix(" }}")),
    ("workflows/docker-build.yml", "secrets.GITHUB_TOKEN"),
    ("workflows/docker-build.yml", "secrets.GITHUB_TOKEN"),
]
ARTIFACT = (
    "          name: live-results-${{ inputs.key_slot == '2' && 'W2' || 'W1' }}"
    "-${{ github.run_id }}-${{ github.run_attempt }}\n"
)


def secret_reads(text: str) -> tuple[list[str], list[str]]:
    """The ``secrets`` context reads in a workflow's text: the expressions
    that name it (any case, any spacing, ``toJSON(secrets)`` included), and
    the reads outside an expression (``secrets: inherit``, an ``if:``)."""
    inside = [m.group(1).strip() for m in _EXPRESSION.finditer(text)
              if _SECRETS_WORD.search(m.group(1))]  # fmt: skip
    outside = _BARE_READ.findall(_EXPRESSION.sub("", text))
    return inside, outside


def test_the_key_slot_input_is_a_strict_choice_defaulting_to_window_1() -> None:
    block = _ci_block("      key_slot:", "      oss_repo:")
    assert "type: choice" in block
    assert "options: ['1', '2']" in block and "default: '1'" in block
    for slot, secret in SLOT_SECRETS.items():
        assert f"{slot} ({secret}, Window {slot})" in block, slot
    assert "LIVE_KEY_SLOT" in block and "W1" in block and "W2" in block


def test_the_run_step_exports_the_slots_secret_as_the_key_and_the_slot() -> None:
    step = _ci_block(*STEP)
    assert f"          {SLOT_KEY}\n" in step
    assert "          INPUT_KEY_SLOT: ${{ inputs.key_slot }}\n" in step
    found = re.search(r"inputs\.key_slot == '(\d)' && '(\w+)' \|\| '(\w+)'", SLOT_KEY)
    assert found is not None
    two, two_name, one_name = found.groups()
    assert {two: two_name, "1": one_name} == SLOT_SECRETS  # as the script names them
    job = _ci_block("  live-smoke:", "    steps:")
    assert "    environment: live\n" in job
    assert "if: github.event_name == 'workflow_dispatch'" in job


def test_no_step_reads_a_key_secret_except_through_the_slot() -> None:
    """The one secret ci.yml reads is the slot's index; no other workflow
    names either key, so no job reads a key outside the slot."""
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    inner = SLOT_KEY.split("${{ ", 1)[1].removesuffix(" }}")
    assert _SECRET_REF.findall(text) == [inner]
    assert text.count("secrets.ANTHROPIC") == 0
    named = [line.strip() for line in text.splitlines()
             if "ANTHROPIC_API_KEY" in line and not line.lstrip().startswith("#")]  # fmt: skip
    assert named[0].startswith('description: "The API key this dispatch spends')
    assert named[1:] == [
        SLOT_KEY,
        "1) key_secret=ANTHROPIC_API_KEY ;;",
        "2) key_secret=ANTHROPIC_API_KEY_2 ;;",
        'if [ -z "${ANTHROPIC_API_KEY}" ]; then',
    ]
    for other in sorted(CI_WORKFLOW.parent.glob("*.y*ml")):
        if other != CI_WORKFLOW:
            assert "ANTHROPIC_API_KEY" not in other.read_text(encoding="utf-8"), other


def test_no_file_under_github_reads_the_secrets_context_but_the_allowed() -> None:
    """A whole-context read (``toJSON(secrets)``, ``secrets: inherit``) or
    any other secret anywhere under .github/ fails here."""
    found: list[tuple[str, str]] = []
    for path in sorted(p for p in GITHUB_DIR.rglob("*") if p.is_file()):
        inside, outside = secret_reads(path.read_text(encoding="utf-8"))
        assert outside == [], path
        found += [(path.relative_to(GITHUB_DIR).as_posix(), e) for e in inside]
    assert found == ALLOWED_READS


@pytest.mark.parametrize(
    "line",
    [
        "  X: ${{ toJSON(secrets) }}",
        "  X: ${{ TOJSON( Secrets ) }}",
        "  X: ${{ toJson(\n    secrets) }}",
        "    secrets: inherit",
        "    SECRETS : inherit",
        "    if: secrets.ANTHROPIC_API_KEY != ''",
        "  X: ${{ secrets.ANTHROPIC_API_KEY }}",
        "  X: ${{ secrets['ANTHROPIC_API_KEY_2'] }}",
        "  X: ${{ fromJSON(toJSON(secrets)).ANTHROPIC_API_KEY }}",
    ],
)
def test_the_secrets_scan_catches_whole_context_and_other_reads(line: str) -> None:
    inside, outside = secret_reads(f"jobs:\n  a:\n{line}\n")
    assert inside or outside, line
    assert secret_reads("# environment secrets. holds two secrets (not keys)\n") == (
        [],
        [],
    )


def test_the_results_artifact_names_the_window_that_paid() -> None:
    """F1: the uploaded results say whose key paid; ``live-results-*`` (the
    handoff notes' download glob) still matches."""
    block = _ci_block("      - name: Upload live corpus results", "\n\n")
    assert ARTIFACT in block
    assert "if: always()" in block
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert text.count("name: live-results-") == 1
    assert {"1": "W1", "2": "W2"} == KEY_WINDOWS  # the artifact's labels


def test_the_missing_key_error_names_the_slot_and_its_secret() -> None:
    script = _run_script()
    assert (
        'echo "::error::key_slot ${key_slot}: the ${key_secret} secret of '
        "environment 'live' is not set\"" in script
    )
    assert "the ANTHROPIC_API_KEY secret of environment 'live' is not set" not in script


def _step(
    tmp_path: Path, slot: str | None, key: str = "placeholder-not-a-key"
) -> tuple[int, str, list[str]]:
    """The run step under bash -e (stage-a at its need) with a fake ``uv``
    that records its argv and environment; ``slot`` ``None`` leaves
    ``INPUT_KEY_SLOT`` unset (an older caller)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "uv.txt"
    fake = bin_dir / "uv"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" > "{record}"\nenv >> "{record}"\n',
                    encoding="utf-8")  # fmt: skip
    fake.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(_run_script(), encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ANTHROPIC_API_KEY": key,
        "INPUT_SUITE": "stage-a",
        "INPUT_ENGINE_MODEL": "claude-opus-5-5",
        "INPUT_SUITE_CAP_USD": "9",
        "INPUT_MODE": "aimed",
        "INPUT_OSS_REPO": "",
        "INPUT_EDITOR_MODEL": "default",
        "INPUT_UPSTREAM_BATCH": "1",
        "LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl"),
    }
    if slot is not None:
        env["INPUT_KEY_SLOT"] = slot
    proc = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True,
                          text=True, timeout=RUN_TIMEOUT_S, check=False)  # fmt: skip
    lines = record.read_text(encoding="utf-8").splitlines() if record.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, lines


def _exports(lines: list[str]) -> dict[str, str]:
    return dict(line.split("=", 1) for line in lines[1:] if "=" in line)


def test_slot_1_and_an_absent_slot_run_as_before_and_slot_2_differs_by_the_slot(
    tmp_path: Path,
) -> None:
    runs = {slot: _step(tmp_path / str(slot), slot) for slot in (None, "1", "2")}
    for slot, (code, output, lines) in runs.items():
        assert code == 0 and lines, (slot, output)
        assert "::error::" not in output
    argv = {lines[0] for _, _, lines in runs.values()}
    assert len(argv) == 1 and argv.pop().startswith("run pytest tests/live ")
    exported = {slot: _exports(lines) for slot, (_, _, lines) in runs.items()}
    assert [exported[s][KEY_SLOT_ENV] for s in (None, "1", "2")] == ["1", "1", "2"]
    assert [key_window(exported[s]) for s in (None, "1", "2")] == ["W1", "W1", "W2"]
    drop = {KEY_SLOT_ENV, "INPUT_KEY_SLOT", "HOME", "PATH", "PWD", "OLDPWD",
            "LIVE_RESULTS_PATH", "_", "SHLVL"}  # fmt: skip

    def rest(slot: str | None) -> dict[str, str]:
        return {k: v for k, v in exported[slot].items() if k not in drop}

    assert rest(None) == rest("1") == rest("2")
    assert exported["2"]["ANTHROPIC_API_KEY"] == "placeholder-not-a-key"
    assert "ANTHROPIC_API_KEY_2" not in exported["2"]


@pytest.mark.parametrize("slot", [None, "1", "2"])
def test_a_missing_key_fails_naming_the_slot_and_secret(
    slot: str | None, tmp_path: Path
) -> None:
    code, output, lines = _step(tmp_path, slot, key="")
    named = slot or "1"
    error = (f"::error::key_slot {named}: the {SLOT_SECRETS[named]} secret of "
             "environment 'live' is not set")  # fmt: skip
    assert (code, lines) == (1, []) and error in output, output


@pytest.mark.parametrize("slot", ["", "0", "3", "01", " 2", "W2", "$(id)", "1;id"])
def test_any_other_slot_is_refused_before_anything_runs(
    slot: str, tmp_path: Path
) -> None:
    code, output, lines = _step(tmp_path, slot)
    assert (code, lines) == (1, []), output
    assert "::error::unknown key_slot input (1 or 2)" in output
    assert "uid=" not in output


def test_the_windows_are_the_slots() -> None:
    assert KEY_WINDOWS == {"1": "W1", "2": "W2"} and set(KEY_WINDOWS) == set(
        SLOT_SECRETS
    )
