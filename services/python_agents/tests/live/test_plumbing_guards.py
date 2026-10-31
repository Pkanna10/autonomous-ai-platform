"""Offline guards of the Step 3 live plumbing (spec section 3.6, U13).

Not ``live``: nothing here spends. They pin what the live-smoke job hands
each suite before a dollar is spent:

- ``LIVE_CORPUS_MODE=wired``: no candidate handed over, the generator on its
  own captured transport (and the matcher when retrieval is matched); an
  ``EDITOR_MODEL`` gets its own captured editor transport; the trial budget
  prices the editor's chain;
- the ``editor_model`` input, parsed by the real ``Settings``;
- the noise rule of every suite, explicit (no suite relies on a default);
- the timeouts (hard 180, OSS 300, noise 90) and the L-table's caps;
- E2's arms (Wave 2 amendment, V4 amended): ``idea_pipeline`` on puts the
  lane, leap and reviewer on their own captured transports (wired only),
  ``portfolio_rounds`` reaches the run, both only for oss and corpus, and
  ``corpus_select=controls`` runs the corpus suite's three controls; the
  outcome records the arm and the combination's floor for the pairing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx2
import pytest
from e2e.conftest import Isolation, UserRepo

from autonomous_ai_agents.clients.cost import chain
from autonomous_ai_agents.common.config import (
    PIPELINE_ROLES,
    PORTFOLIO_ROUNDS_MAX,
    Settings,
    role_chain,
    settings,
)
from autonomous_ai_agents.common.models import (
    METRIC_PEAK_RSS_BYTES,
    METRIC_WALL_TIME_S,
    Baseline,
    Direction,
    NoiseCalibration,
    Objective,
    ObjectiveKind,
)
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
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
STEP3_SUITES = frozenset(  # L0, L1a/b, L2a/b; V9's upstream verify and live
    {"noise", "corpus", "hard", "oss", "upstream-verify", "upstream"}
)
RULES = {  # PAIRED_TRIALS, CONFIRM_WINNERS, NOISE_CALIBRATION_BLOCKS
    "step3": ("true", "true", "3"),
    "step2": ("false", "false", "0"),
}
TIMEOUTS = {"hard": 90, "oss": 300, "noise": 90, "corpus": 120}
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
    mode = "wired" if suite == "upstream" else "aimed"  # upstream: wired only
    code, output, _ = _dispatch(
        tmp_path, suite, "claude-opus-5-5", "150", mode=mode, oss_repo=repo
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
    """Hard 90 and corpus 120 re-pinned from L1a and L1b (28-29 and 34
    minutes measured; the 8-minutes-a-loop floor), OSS 300 from D41's 2.6x
    until L2a measures it, noise at ``noise.NOISE_JOB_MINUTES``."""
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


# ---------------------------------------------------------------------------
# V4 amended (Wave 2 amendment, section 3.6): arm P, portfolio rounds and the
# corpus controls of E2
# ---------------------------------------------------------------------------

PIPELINE = PIPELINE_ROLES  # lane, leap, reviewer
CONTROL_NODES = tuple(  # the corpus suite's three controls, by node id
    f"tests/live/test_corpus_live.py::test_corpus_whole_loop[{r.name}]"
    for r in CORPUS
    if r.kind == "control"
)


def test_the_pipeline_puts_its_three_roles_on_their_own_captured_chains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the three transports the factory refuses an injected-transport
    build by name (C11); with them every one bills its own role chain on the
    run's one ledger, and today's generator stays wired as the fallback."""
    assert PIPELINE == ("lane", "leap", "reviewer")
    root, run = _dry(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "IDEA_PIPELINE", True)
    seen = _spy(monkeypatch, corpus)
    loop = start_loop(CORPUS[0], run, root, REQUIRED, mode="wired")
    roles = seen["role_transports"]
    assert set(roles) == {"generator", *PIPELINE}
    for role in PIPELINE:
        assert roles[role].chain == role_chain(settings, role), role
        assert roles[role].records is run.records
    assert isinstance(loop.context.generator, IdeaPipelineGenerator)
    assert loop.context.portfolio_rounds == settings.PORTFOLIO_ROUNDS
    seen = _spy(monkeypatch, oss)

    def clone(repo: oss.OssRepo, dest: Path, **_: object) -> UserRepo:
        return make_repo(CORPUS[0].path, dest)

    monkeypatch.setattr(oss, "prepare_repo", clone)
    start_oss_loop(OSS_CORPUS[0], run, root / "oss", REQUIRED, mode="wired")
    assert set(seen["role_transports"]) == {"generator", *PIPELINE}
    assert run.capture.exchanges == []


def test_the_pipeline_roles_follow_a_settings_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = _dry(tmp_path, monkeypatch)
    cfg = settings.model_copy(update={"IDEA_PIPELINE": True})
    assert set(corpus.role_wiring(run, "wired", cfg=cfg)) == {"generator", *PIPELINE}
    assert set(corpus.role_wiring(run, "wired")) == {"generator"}  # global: off


@pytest.mark.parametrize("mode", MODES)
def test_the_pipeline_refuses_every_mode_but_wired_before_any_wire(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mode that hands candidates wires no generator, so arm P would be no
    arm: refused by name, before anything is sent."""
    _, run = _dry(tmp_path, monkeypatch)
    cfg = settings.model_copy(update={"IDEA_PIPELINE": True})
    with pytest.raises(ValueError, match="IDEA_PIPELINE.*wired"):
        corpus.role_wiring(run, mode, cfg=cfg)  # type: ignore[arg-type]
    assert run.capture.exchanges == [] and run.records == []


def test_an_outcome_records_its_arm_and_both_floors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What ``--from-results`` pairs on: the arm's settings, the noise floor
    of the delivered combination on the primary metric (shown) and the
    project floor (E2's call)."""
    run = LiveRun("t", 5.0, wire=httpx2.MockTransport(_no_wire))
    repo, result = _mode_result(tmp_path / "a", "wired", 0.12)
    combination = result.state["combination"]
    assert combination is not None
    first, speed = combination.judge_results
    result.state["combination"] = combination.model_copy(
        update={
            "judge_results": (first, speed.model_copy(update={"noise_floor": 0.043}))
        }
    )
    assert result.state["baseline"] is None  # no baseline, no project floor
    uncalibrated = outcome_of(repo, run, result, guard="ok", mode="wired")
    assert uncalibrated.project_floor_pct is None
    calibration = NoiseCalibration(blocks=3, gaps={"bench": 0.012}, floor=0.031)
    raised = Objective(  # wall time under the baseline node's raise (D41 c)
        project_id=result.state["project"].id,
        kind=ObjectiveKind.runtime,
        metric=METRIC_WALL_TIME_S,
        direction=Direction.minimize,
        min_relative_gain=calibration.floor,
        description="minimize wall time",
    )
    result.state["baseline"] = Baseline(objectives=(raised,), calibration=calibration)
    plain = outcome_of(repo, run, result, guard="ok", mode="wired")
    assert (plain.idea_pipeline, plain.portfolio_rounds) == (False, 0)
    assert plain.generator_n == settings.GENERATOR_N
    assert plain.floor_pct == pytest.approx(4.3)
    assert plain.project_floor_pct == pytest.approx(3.1)  # D41 c, E2's floor
    monkeypatch.setattr(settings, "IDEA_PIPELINE", True)
    monkeypatch.setattr(settings, "PORTFOLIO_ROUNDS", 2)
    arm_p = outcome_of(repo, run, result, guard="ok", mode="wired")
    loaded = json.loads(arm_p.to_json())
    assert (loaded["idea_pipeline"], loaded["portfolio_rounds"]) == (True, 2)
    assert loaded["floor_pct"] == pytest.approx(4.3)
    assert loaded["project_floor_pct"] == pytest.approx(3.1)
    failed = outcome_of(repo, run, None, guard="breach: x", mode="wired")
    assert failed.floor_pct is None and failed.idea_pipeline
    assert failed.project_floor_pct is None


def test_the_project_floor_is_the_one_the_primary_metric_was_judged_with(
    tmp_path: Path,
) -> None:
    """E2's "project floor" is the floor every judge, confirmation and
    combine applied to the primary metric: its objective's
    ``min_relative_gain`` on the baseline, which the baseline node raised to
    the calibration (D41 c; ``_project_floor``, D42's margin). A wall-time
    run reads the calibrated floor, or a larger user value; a peak-memory run
    its own floor (calibration raises wall time only); an uncalibrated run
    the 2 % minimum."""
    run = LiveRun("t", 5.0, wire=httpx2.MockTransport(_no_wire))
    repo, result = _mode_result(tmp_path, "wired", 0.12)
    project_id = result.state["project"].id

    def objective(kind: ObjectiveKind, floor: float, weight: float) -> Objective:
        metric = {
            ObjectiveKind.runtime: METRIC_WALL_TIME_S,
            ObjectiveKind.peak_memory: METRIC_PEAK_RSS_BYTES,
        }[kind]
        return Objective(
            project_id=project_id,
            kind=kind,
            metric=metric,
            direction=Direction.minimize,
            min_relative_gain=floor,
            weight=weight,
            description="minimize",
        )

    calibration = NoiseCalibration(blocks=3, gaps={"bench": 0.012}, floor=0.031)
    runtime = ObjectiveKind.runtime
    cases = [
        ((objective(runtime, 0.031, 1.0),), calibration, 3.1),
        ((objective(runtime, 0.06, 1.0),), calibration, 6.0),  # the user's stays
        (
            (
                objective(ObjectiveKind.peak_memory, 0.05, 2.0),
                objective(runtime, 0.031, 1.0),
            ),
            calibration,
            5.0,
        ),
        ((objective(runtime, 0.02, 1.0),), None, 2.0),  # not calibrated
        ((), None, 2.0),  # no objective: the engine's 2 % minimum
    ]
    for objectives, calibrated, want in cases:
        result.state["baseline"] = Baseline(
            objectives=objectives, calibration=calibrated
        )
        found = outcome_of(repo, run, result, guard="ok", mode="wired")
        assert found.project_floor_pct == pytest.approx(want), (objectives, want)


def _arm_dispatch(
    tmp_path: Path,
    suite: str,
    cap: str,
    *,
    mode: str = "wired",
    idea: str = "off",
    rounds: str = "0",
    select: str = "all",
) -> tuple[int, str, list[str]]:
    """The run step under bash -e with a fake ``uv`` recording the pytest
    arguments and the arm's exports (``unset`` when not exported)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    called = tmp_path / "called.txt"
    fake = bin_dir / "uv"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "${{IDEA_PIPELINE-unset}}" "${{PORTFOLIO_ROUNDS-unset}}" '
        f'"$@" > "{called}"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(_run_script(), encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ANTHROPIC_API_KEY": "placeholder-not-a-key",
        "INPUT_SUITE": suite,
        "INPUT_ENGINE_MODEL": "claude-opus-5-5",
        "INPUT_SUITE_CAP_USD": cap,
        "INPUT_MODE": mode,
        "INPUT_OSS_REPO": "",
        "INPUT_EDITOR_MODEL": "default",
        "INPUT_UPSTREAM_BATCH": "1",
        "INPUT_IDEA_PIPELINE": idea,
        "INPUT_PORTFOLIO_ROUNDS": rounds,
        "INPUT_CORPUS_SELECT": select,
        "LIVE_RESULTS_PATH": str(tmp_path / "results.jsonl"),
    }
    proc = subprocess.run(
        ["bash", "-e", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calls = called.read_text(encoding="utf-8").splitlines() if called.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, calls


def _quoted_options(block: str) -> list[str]:
    found = re.search(r"options: \[(.*)\]", block)
    assert found is not None, block
    return [item.strip().strip("'") for item in found.group(1).split(",")]


def test_the_arm_inputs_are_strict_choices_reaching_the_run_via_env() -> None:
    """``off``/``on`` quoted (YAML 1.1 reads them as booleans), rounds 0 to
    ``PORTFOLIO_ROUNDS_MAX``, and every one through ``env`` only."""
    idea = _ci_block("      idea_pipeline:", "      portfolio_rounds:")
    assert "options: ['off', 'on']" in idea and "default: 'off'" in idea
    rounds = _ci_block("      portfolio_rounds:", "      corpus_select:")
    assert _quoted_options(rounds) == [str(n) for n in range(PORTFOLIO_ROUNDS_MAX + 1)]
    assert "default: '0'" in rounds
    select = _ci_block("      corpus_select:", "\n\n")
    assert _quoted_options(select) == ["all", "controls"] and "default: all" in select
    step = _ci_block("      - name: Run live tests", "      - name: Upload live corpus")
    for name in ("idea_pipeline", "portfolio_rounds", "corpus_select"):
        assert f"INPUT_{name.upper()}: ${{{{ inputs.{name} }}}}" in step, name


@pytest.mark.parametrize("suite", ["oss", "corpus"])
def test_arm_p_reaches_the_run_and_parses_to_the_pipeline(
    suite: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2's arm P and arm A: what the step exports, parsed by the real
    Settings; the suite's need is unchanged (oss 50, corpus 75)."""
    need = {"oss": "50", "corpus": "75"}[suite]
    code, output, calls = _arm_dispatch(tmp_path, suite, need, idea="on", rounds="2")
    assert code == 0, output
    assert calls[:2] == ["true", "2"] and "idea pipeline on" in output
    monkeypatch.setenv("IDEA_PIPELINE", calls[0])
    monkeypatch.setenv("PORTFOLIO_ROUNDS", calls[1])
    cfg = Settings()
    assert cfg.IDEA_PIPELINE and cfg.PORTFOLIO_ROUNDS == 2
    for role in PIPELINE:
        assert all(name in cfg.MODEL_PRICING for name in role_chain(cfg, role))
    fresh = tmp_path / "arm-a"
    fresh.mkdir()
    code, output, calls = _arm_dispatch(fresh, suite, need, rounds="2")
    assert code == 0 and calls[:2] == ["false", "2"], output
    below = tmp_path / "below"
    below.mkdir()
    code, output, calls = _arm_dispatch(below, suite, f"{int(need) - 1}.99", idea="on")
    assert code == 1 and calls == [] and "is below the" in output


def test_other_suites_take_no_arm_and_export_nothing(tmp_path: Path) -> None:
    code, output, calls = _arm_dispatch(tmp_path, "hard", "50")
    assert code == 0 and calls[:2] == ["unset", "unset"], output
    for index, (suite, idea, rounds) in enumerate(
        (("hard", "on", "0"), ("hard", "off", "2"), ("oss-ab", "on", "0"))
    ):
        fresh = tmp_path / f"refused-{index}"
        fresh.mkdir()
        code, output, calls = _arm_dispatch(
            fresh, suite, "150", idea=idea, rounds=rounds
        )
        assert code == 1 and calls == [], (suite, output)
        assert "only for the oss and corpus suites" in output, output


def test_the_arm_inputs_refuse_bad_values_and_the_pipeline_off_wired(
    tmp_path: Path,
) -> None:
    cases = [
        ({"idea": value}, "unknown idea_pipeline")
        for value in ("", "On", "true", "1", "on;id")
    ]
    cases += [
        ({"rounds": value}, "unknown portfolio_rounds")
        for value in ("", "4", "-1", "02", "2 ")
    ]
    cases += [
        ({"select": value}, "unknown corpus_select") for value in ("", "Controls", "x")
    ]
    cases += [({"idea": "on", "mode": "aimed"}, "idea_pipeline on runs wired only")]
    for index, (knobs, message) in enumerate(cases):
        fresh = tmp_path / f"bad-{index}"
        fresh.mkdir()
        code, output, calls = _arm_dispatch(fresh, "oss", "50", **knobs)
        assert (code, calls) == (1, []) and message in output, (knobs, output)


def test_corpus_select_controls_runs_exactly_the_three_controls(
    tmp_path: Path,
) -> None:
    """E2's control dispatches: the three controls by node id at 3 x 5 USD;
    ``all`` keeps the whole suite; any other suite refuses it."""
    assert len(CONTROL_NODES) == 3
    code, output, calls = _arm_dispatch(tmp_path, "corpus", "15", select="controls")
    assert code == 0, output
    assert calls[2:] == ["run", "pytest", *CONTROL_NODES, "-m", "live", "--no-cov",
                         "-n", "0", "-rA"]  # fmt: skip
    assert "corpus select controls" in output
    whole = tmp_path / "all"
    whole.mkdir()
    code, output, calls = _arm_dispatch(whole, "corpus", "75")
    assert code == 0 and calls[4] == "tests/live/test_corpus_live.py", output
    for index, (suite, cap) in enumerate((("corpus", "14.99"), ("oss", "50"))):
        fresh = tmp_path / f"refused-{index}"
        fresh.mkdir()
        code, output, calls = _arm_dispatch(fresh, suite, cap, select="controls")
        assert code == 1 and calls == [], output
    assert "corpus_select controls is only for the corpus suite" in output


def test_the_control_node_ids_collect_exactly_the_three_control_cases() -> None:
    """The node ids are the live module's own parametrize ids (collection
    only: nothing runs, nothing spends)."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "-m",
            "live",
            *CONTROL_NODES,
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    collected = [line for line in proc.stdout.splitlines() if "::" in line]
    assert collected == list(CONTROL_NODES)


def test_the_oss_suite_keeps_ten_loops_need_fifty_and_three_hundred_minutes() -> None:
    """Arm P at ``PORTFOLIO_ROUNDS=2`` at most doubles the trials; L2a
    measured 36-40 minutes for 10 loops, so 300 holds (re-pinned from E2's
    first dispatch)."""
    table = dict(re.findall(r"(\S+)\) paths=\(.*\); need=([0-9.]+) ;;", _run_script()))
    assert (len(OSS_CORPUS), table["oss"], TIMEOUTS["oss"]) == (10, "50", 300)
    block = _ci_block("  live-smoke:", "    defaults:")
    assert "inputs.suite == 'oss' && 300" in block
