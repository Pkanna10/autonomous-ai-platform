"""Offline guards of the Step 3 live plumbing (spec section 3.6, U13).

Not ``live``: nothing here spends. They pin what the live-smoke job hands
each suite before a dollar is spent:

- ``LIVE_CORPUS_MODE=wired``: no candidate handed over, the generator on its
  own captured transport (and the matcher when retrieval is matched); an
  ``EDITOR_MODEL`` gets its own captured editor transport; the trial budget
  prices the editor's chain;
- the ``editor_model`` input, parsed by the real ``Settings``;
- the noise rule of every suite, explicit (no suite relies on a default);
- the timeouts (hard 180, OSS 300, noise 90) and the L-table's caps.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import httpx2
import pytest
from e2e.conftest import Isolation, UserRepo

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import Settings, role_chain, settings
from autonomous_ai_agents.orchestrator.factory import build_context, min_trial_budget

from . import corpus, noise, oss
from .conftest import LiveRun, make_repo, restore_host_key
from .corpus import (
    ALL_MODES,
    CORPUS,
    HARD_CORPUS,
    MODE_ENV,
    MODES,
    corpus_mode,
    mode_hypotheses,
    outcome_of,
    render_summary,
    settings_trial_budget,
    start_loop,
)
from .oss import OSS_CORPUS, start_oss_loop
from .test_corpus_guards import (
    SUITES,
    _ci_block,
    _dispatch,
    _mode_result,
    _no_wire,
    _run_script,
)

SONNET = "claude-sonnet-5-5"
REQUIRED = Isolation("required", None)
STEP3_SUITES = frozenset({"noise", "corpus", "hard", "oss"})  # L0, L1a/b, L2a/b
RULES = {  # PAIRED_TRIALS, CONFIRM_WINNERS, NOISE_CALIBRATION_BLOCKS
    "step3": ("true", "true", "3"),
    "step2": ("false", "false", "0"),
}
TIMEOUTS = {"hard": 180, "oss": 300, "noise": 90, "corpus": 180}
SPEC_CAPS = {  # section 6's L-table: runs per dispatch x the run cap, USD
    "noise": (13, 0.0),  # L0: no request
    "hard": (10, 5.0),  # L1a
    "corpus": (15, 5.0),  # L1b
    "oss": (10, 5.0),  # L2a (two dispatches: 100), L2b (one: 50)
}
SPEC_EXPECTED_USD = {"noise": 0.0, "hard": 1.0, "corpus": 0.8, "oss": 1.5}


def _dry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, LiveRun]:
    root = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    return root, LiveRun("dry", 5.0, wire=httpx2.MockTransport(_no_wire))


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return build_context(*args, **kwargs)

    monkeypatch.setattr(module, "build_context", spy)
    return seen


# ---------------------------------------------------------------------------
# LIVE_CORPUS_MODE=wired and the role transports
# ---------------------------------------------------------------------------


def test_wired_is_read_strictly_and_hands_no_candidate(tmp_path: Path) -> None:
    assert ALL_MODES == (*MODES, "wired") and MODES == ("aimed", "blind", "decoy")
    assert corpus_mode({MODE_ENV: "wired"}) == "wired"
    for bad in ("Wired", "wired ", "wire"):
        with pytest.raises(ValueError, match=MODE_ENV):
            corpus_mode({MODE_ENV: bad})
    for repo in (CORPUS[0], HARD_CORPUS[0], OSS_CORPUS[0].corpus):
        assert mode_hypotheses(repo, "wired") == ()
    assert CORPUS[0].candidates(CORPUS[0].project(tmp_path), "wired") == []


def test_wired_start_loop_puts_the_generator_on_its_own_captured_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run = _dry(tmp_path, monkeypatch)
    seen = _spy(monkeypatch, corpus)
    loop = start_loop(CORPUS[0], run, root, REQUIRED, mode="wired")
    assert loop.mode == "wired" and loop.candidates == () == loop.context.candidates
    roles = seen["role_transports"]
    assert set(roles) == {"generator"}
    assert roles["generator"].chain == role_chain(settings, "generator") == (SONNET,)
    assert roles["generator"].records is run.records  # one ledger, captured
    assert loop.context.generator is not None and loop.context.matcher is None
    seen.clear()
    aimed = start_loop(CORPUS[0], run, root / "aimed", REQUIRED)
    assert seen["role_transports"] == {} and aimed.context.generator is None
    assert run.capture.exchanges == []


def test_wired_matched_retrieval_adds_the_matcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, run = _dry(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "RESEARCH_RETRIEVAL", "matched")
    seen = _spy(monkeypatch, corpus)
    loop = start_loop(HARD_CORPUS[0], run, root, REQUIRED, mode="wired")
    roles = seen["role_transports"]
    assert set(roles) == {"generator", "matcher"}
    assert roles["matcher"].chain == role_chain(settings, "matcher")
    assert loop.context.matcher is not None and loop.context.playbook


def test_wired_start_loop_with_settings_wires_the_roles_from_that_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A discovery experiment's per-run settings (``cfg``) pick the generator's
    transport too, never the global settings."""
    root, run = _dry(tmp_path, monkeypatch)
    built: list[Settings] = []
    real = LiveRun.transport

    def spy(self: LiveRun, cfg: Settings = settings) -> Any:
        built.append(cfg)
        return real(self, cfg)

    monkeypatch.setattr(LiveRun, "transport", spy)
    seen = _spy(monkeypatch, corpus)
    cfg = settings.model_copy(update={"LLM_TIMEOUT_S": 123.0})
    start_loop(CORPUS[0], run, root, REQUIRED, mode="wired", cfg=cfg)
    assert set(seen["role_transports"]) == {"generator"}
    engine, generator = built
    assert engine is cfg and generator.LLM_TIMEOUT_S == 123.0 != settings.LLM_TIMEOUT_S
    assert seen["role_transports"]["generator"].chain == role_chain(cfg, "generator")


def test_an_editor_model_gets_its_own_editor_transport_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without it the factory finds no transport on the editor's chain and
    refuses the run (``LLMConfigError``) before anything is sent."""
    root, run = _dry(tmp_path, monkeypatch)
    default_budget = settings_trial_budget(settings)
    assert default_budget == min_trial_budget()
    monkeypatch.setattr(settings, "EDITOR_MODEL", SONNET)
    monkeypatch.setattr(settings, "EDITOR_EFFORT", "low")
    seen = _spy(monkeypatch, corpus)
    start_loop(CORPUS[0], run, root, REQUIRED, mode="wired")
    roles = seen["role_transports"]
    assert set(roles) == {"editor", "generator"}
    assert roles["editor"].chain == role_chain(settings, "editor") == (SONNET,)
    assert seen["transport"].chain == chain(settings) != (SONNET,)
    assert settings_trial_budget(settings) == min_trial_budget() < default_budget
    cfg = settings.model_copy(update={"EDITOR_MODEL": None})
    assert settings_trial_budget(cfg) == default_budget


def test_the_oss_loop_takes_the_mode_and_its_role_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``prepare_repo`` (a clone over the network) is the one fake: a corpus
    copy stands for the library; the wiring is the production one."""
    root, run = _dry(tmp_path, monkeypatch)

    def clone(repo: oss.OssRepo, dest: Path, **_: object) -> UserRepo:
        return make_repo(CORPUS[0].path, dest)

    monkeypatch.setattr(oss, "prepare_repo", clone)
    seen = _spy(monkeypatch, oss)
    repo = OSS_CORPUS[0]
    loop = start_oss_loop(repo, run, root, REQUIRED, mode="wired")
    assert loop.mode == "wired" and loop.candidates == ()
    assert set(seen["role_transports"]) == {"generator"}
    assert loop.context.generator is not None
    aimed = start_oss_loop(repo, run, root / "aimed", REQUIRED)
    assert aimed.mode == "aimed" and seen["role_transports"] == {}
    assert [h.title for h in aimed.candidates] == [s.title for s in repo.hypotheses]


def test_a_wired_known_fix_is_a_reached_reference_gain(tmp_path: Path) -> None:
    run = LiveRun("t", 5.0, wire=httpx2.MockTransport(_no_wire))
    repo, result = _mode_result(tmp_path / "a", "wired", 0.45)
    won = outcome_of(repo, run, result, guard="ok", mode="wired")
    assert (won.mode, won.reached_fix, won.known_fix) == ("wired", True, True)
    repo, result = _mode_result(tmp_path / "b", "wired", 0.29)
    short = outcome_of(repo, run, result, guard="ok", mode="wired")
    assert short.delivered and not short.known_fix
    text = render_summary("Hard corpus", [won, short])
    (line,) = [x for x in text.splitlines() if x.startswith("Mode wired:")]
    assert "Known-fix rate: 1/2 (50.0%) (the delivered gain reached" in line


# ---------------------------------------------------------------------------
# The live-smoke inputs: editor_model, the noise rule, the timeouts, the caps
# ---------------------------------------------------------------------------


def test_every_editor_model_choice_is_a_valid_priced_editor_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the run step exports for each choice, under each engine model,
    parsed by the real Settings."""
    inputs = _ci_block("      editor_model:", "      suite_cap_usd:")
    assert "type: choice" in inputs and "default: default" in inputs
    found = re.search(r"options: \[(.*)\]", inputs)
    assert found is not None and found.group(1).split(", ") == ["default", SONNET]
    step = _ci_block("      - name: Run live tests", "      - name: Upload live corpus")
    assert "INPUT_EDITOR_MODEL: ${{ inputs.editor_model }}" in step
    assert "            default) ;;" in step
    exported = (
        f"            {SONNET}) export EDITOR_MODEL={SONNET} EDITOR_EFFORT=low ;;"
    )
    assert exported in step
    for engine in ("claude-opus-5-5", SONNET):
        for editor in ("default", SONNET):
            monkeypatch.setenv("ENGINE_MODEL", engine)
            for key in ("EDITOR_MODEL", "EDITOR_EFFORT"):
                monkeypatch.delenv(key, raising=False)
            if editor == SONNET:
                monkeypatch.setenv("EDITOR_MODEL", SONNET)
                monkeypatch.setenv("EDITOR_EFFORT", "low")
            cfg = Settings()
            billed = role_chain(cfg, "editor")
            assert all(name in cfg.MODEL_PRICING for name in billed)
            if editor == SONNET:
                assert (billed, cfg.EDITOR_EFFORT) == ((SONNET,), "low")
            else:
                assert billed == role_chain(cfg, "engine") and cfg.EDITOR_MODEL is None


def _rule(tmp_path: Path) -> list[str]:
    return (tmp_path / "rule.txt").read_text(encoding="utf-8").split()


@pytest.mark.parametrize("suite", SUITES)
def test_every_suite_sets_its_noise_rule_explicitly(
    suite: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each suite is named in exactly one branch of the noise-rule case, the
    fallback refuses, and the exports parse to the rule: L0-L2 measure the
    Step 3 defaults, every other suite Step 2's measurement (its timeout and
    its Window 0 comparison)."""
    script = _run_script()
    block = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    block = block[: block.index("esac")]
    named: dict[str, str] = {}
    for names, rule in re.findall(r"^  ([\w| -]+)\) noise_rule=(\w+) ;;$", block, re.M):
        for name in names.split("|"):
            assert name.strip() not in named, name
            named[name.strip()] = rule
    assert set(named) == set(SUITES)
    assert {s for s, r in named.items() if r == "step3"} == STEP3_SUITES
    assert '*)\n    echo "::error::no noise rule' in block
    repo = "tabulate" if suite == "oss-ab" else ""
    code, output, _ = _dispatch(
        tmp_path, suite, "claude-opus-5-5", "150", oss_repo=repo
    )
    assert code == 0, output
    found = _rule(tmp_path)
    expected = RULES["step3" if suite in STEP3_SUITES else "step2"]
    assert tuple(found[:3]) == expected
    assert found[5] == ("paired" if suite == "noise" else "unset")
    for key, value in zip(
        ("PAIRED_TRIALS", "CONFIRM_WINNERS", "NOISE_CALIBRATION_BLOCKS"),
        expected,
        strict=True,
    ):
        monkeypatch.setenv(key, value)
    cfg = Settings()
    rule = (cfg.PAIRED_TRIALS, cfg.CONFIRM_WINNERS, cfg.NOISE_CALIBRATION_BLOCKS)
    if suite in STEP3_SUITES:  # the Step 3 defaults, measured as shipped
        defaults = Settings.model_fields
        assert (
            rule
            == (
                defaults["PAIRED_TRIALS"].default,
                defaults["CONFIRM_WINNERS"].default,
                defaults["NOISE_CALIBRATION_BLOCKS"].default,
            )
            == (True, True, 3)
        )
    else:
        assert rule == (False, False, 0)


def test_the_editor_model_input_reaches_the_run_or_is_refused(tmp_path: Path) -> None:
    code, output, _ = _dispatch(
        tmp_path, "oss", SONNET, "50", "wired", editor_model=SONNET
    )
    assert code == 0, output
    assert _rule(tmp_path)[3:5] == [SONNET, "low"]
    assert f"EDITOR_MODEL {SONNET}" in output and "mode wired" in output
    code, output, _ = _dispatch(tmp_path, "oss", "claude-sonnet-5-5", "50")
    assert code == 0 and _rule(tmp_path)[3:5] == ["unset", "unset"], output
    for index, bad in enumerate(("", "Default", "claude-opus-5-5", "x;id")):
        fresh = tmp_path / f"bad-{index}"
        fresh.mkdir()
        code, output, calls = _dispatch(
            fresh, "oss", "claude-opus-5-5", "50", editor_model=bad
        )
        assert (code, calls) == (1, "") and "unknown editor_model" in output, bad


def test_the_timeouts_are_pinned_under_the_job_limit() -> None:
    """Hard 180 and OSS 300 from D41's 2.6x (the Lead re-pins them from
    L1a's wall time), noise at ``noise.NOISE_JOB_MINUTES``."""
    block = _ci_block("  live-smoke:", "    defaults:")
    found = re.search(r"timeout-minutes: \$\{\{ (.*) \}\}", block)
    assert found is not None
    pairs = dict(re.findall(r"inputs\.suite == '([\w-]+)' && (\d+)", found.group(1)))
    assert {s: int(pairs[s]) for s in TIMEOUTS} == TIMEOUTS
    assert TIMEOUTS["noise"] == noise.NOISE_JOB_MINUTES
    assert all(int(minutes) <= 360 for minutes in pairs.values())


def test_the_l_table_caps_are_the_suite_needs_and_cover_the_estimates() -> None:
    table = dict(re.findall(r"(\S+)\) paths=\(.*\); need=([0-9.]+) ;;", _run_script()))
    cost = {"hard": corpus.HARD_RUN_CAP_USD, "corpus": corpus.CORPUS_RUN_CAP_USD}
    cost |= {"oss": oss.OSS_RUN_CAP_USD, "noise": noise.NOISE_RUN_CAP_USD}
    counts = {"hard": len(HARD_CORPUS), "corpus": len(CORPUS)}
    counts |= {"oss": len(OSS_CORPUS), "noise": len(noise.NOISE_TARGETS)}
    for suite, (runs, cap) in SPEC_CAPS.items():
        assert (counts[suite], cost[suite]) == (runs, cap), suite
        assert float(table[suite]) == runs * cap, suite  # tight: no slack
        assert SPEC_EXPECTED_USD[suite] <= runs * cap <= 150, suite
    assert 2 * float(table["oss"]) == 100  # L2a's two repetitions
