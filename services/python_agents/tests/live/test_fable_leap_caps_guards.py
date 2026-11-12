"""Offline guards: every static cap prices the leap as the engine sends it.

Since the Fable leap (``common.config.leap_shape``), a Fable
``IDEAS_LEAP_MODEL`` sends 32,000 output tokens on its model and Opus 4.8
(the server-side fallback) whatever ``IDEAS_LEAP_MAX_TOKENS`` says, and may
run to its 951 s timeout. The live harnesses' static caps (``ideas_probe``'s
``lane_usd`` / ``pipeline_usd``, ``ideas_x2.seeded_stages`` and
``discovery_ab.pipeline_worst_usd``) and arm D's minutes read that shape,
so the engine's own S2 reservation (``preflight_estimate`` over the leap's
chain at the prompt bound) always fits the stage a cap was built from. The
Opus leap (the default) is priced as before: X2-0's run cap stays 9.35.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, cast

import pytest

from autonomous_ai_agents.clients.budget import Budget
from autonomous_ai_agents.clients.cost import preflight_estimate
from autonomous_ai_agents.common.config import (
    Settings,
    lane_chain,
    leap_shape,
    role_chain,
    settings,
)
from autonomous_ai_agents.optimization.idea_types import Lane
from autonomous_ai_agents.orchestrator.nodes import _discovery_cap

from . import discovery_ab as ab
from . import discovery_oss as dx
from . import ideas_probe as ip
from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from .conftest import SUITE_CAP_ENV
from .corpus import settings_trial_budget
from .discovery import FABLE, SONNET, chain_worst_usd

FABLE_5_2, OPUS_4_8 = "claude-fable-5-2", "claude-opus-4-8"


def _engine(cfg: Settings, lane: Lane) -> float:
    """The engine's own reservation of one S2 request at D55's prompt bound
    (``idea_pipeline._job``: the count, here the bound, over the request's
    chain at its output cap, the leap's ``leap_shape``'s)."""
    out = leap_shape(cfg).max_tokens if lane is Lane.leap else cfg.IDEAS_LANE_MAX_TOKENS
    return preflight_estimate(
        ip.LANE_PROMPT_BOUND, out, lane_chain(cfg, lane), settings.MODEL_PRICING
    )


def test_the_fable_5_2_leap_reservation_at_the_prompt_bound() -> None:
    """2 attempts x (38,000 x $10 (Fable 5.2's 5-minute write, the dearest
    input side over the chain) + 32,000 x $40) / 1e6 = 3.32 USD."""
    cfg = x2.arm_settings(x2.X2_L)
    assert role_chain(cfg, "leap") == (FABLE_5_2, OPUS_4_8)
    assert leap_shape(cfg).max_tokens == 32_000
    assert _engine(cfg, Lane.leap) == pytest.approx(3.32)
    assert ip.lane_usd(cfg, Lane.leap) == pytest.approx(3.32)  # the probe's bound


def test_the_seeded_s2_stage_holds_the_engines_s2_reservation() -> None:
    """X2 with the Fable 5.2 leap: the static S2 stage (every lane with G4's
    mechanisms block, so a wider bound) is at least the engine's own S2
    reservation, so the seeded call's ``Budget.check`` of S2 cannot fail on
    the leap; the run cap prices it: 21.10, each earlier call charged its
    leap beyond X1's (U-portfolio's ``leap_extra_usd``; it was 13.85 with
    every earlier call at X1's Opus-leap rate) (X2-0 9.35, X2-V 9.45,
    unchanged)."""
    cfg = x2.arm_settings(x2.X2_L)
    s1, s2, review = x2.seeded_stages(cfg)
    seeded = cfg.model_copy(update={"IDEAS_SEQUENTIAL_LANES": True})
    assert ip.lane_usd(seeded, Lane.leap) == pytest.approx(3.384)  # 41,200 tokens
    assert ip.lane_usd(seeded, Lane.leap) >= _engine(cfg, Lane.leap)
    engine_s2 = sum(_engine(cfg, lane) for lane in ip.s2_lanes(cfg))
    assert s2 >= engine_s2
    Budget(cap_usd=s2).check(engine_s2)  # S2 whole, as the pipeline checks it
    assert (s1, s2, review) == pytest.approx((0.215, 4.51015, 0.54))
    assert x2.run_cap(cfg) == 21.10
    assert (x2.arm_cap(x2.X2_0), x2.arm_cap(x2.X2_V)) == (9.35, 9.45)
    opus = x2.seeded_stages(x2.arm_settings(x2.X2_0))
    assert opus == pytest.approx((0.215, 1.57215, 0.54))  # the Opus leap's 0.4729


def test_the_probe_and_ab_pipeline_caps_price_the_fable_leap() -> None:
    cfg = settings.model_copy(
        update={"IDEA_PIPELINE": True, "IDEAS_LEAP_MODEL": FABLE_5_2,
                "IDEAS_LEAP_MAX_TOKENS": 12_000}  # ignored by a Fable leap
    )  # fmt: skip
    opus = settings.model_copy(update={"IDEA_PIPELINE": True})
    assert ip.pipeline_usd(cfg) - ip.pipeline_usd(opus) == pytest.approx(
        3.32 - ip.request_usd(ip.LANE_PROMPT_BOUND, 12_000, "claude-opus-5-5")
    )
    leap = chain_worst_usd(ab.IDEAS_LANE_PROMPT_BOUND, 32_000, (FABLE_5_2, OPUS_4_8))
    assert leap >= _engine(cfg, Lane.leap)
    assert ab.pipeline_worst_usd(cfg) - ab.pipeline_worst_usd(opus) == pytest.approx(
        leap - chain_worst_usd(ab.IDEAS_LANE_PROMPT_BOUND, 12_000, ("claude-opus-5-5",))
    )


def test_arm_d_prices_and_times_its_fable_leap() -> None:
    """Arm D's leap (Fable 5.1): 2 x (38,000 x 12.50 + 32,000 x 50) / 1e6 =
    4.15 (E1's 1.475 at 20,000 on Fable alone), so its cap 7.205; its minutes
    give the leap its 951 s timeout (E1's twice 234.3 s)."""
    cfg = settings.model_copy(update=dict(ip.ARM_D.update))
    assert ip.lane_usd(cfg, Lane.leap) == pytest.approx(4.15)
    assert ip.arm_usd(ip.ARM_D) == pytest.approx(7.205)
    assert leap_shape(cfg).timeout_s == 951.0
    lane = ip.request_seconds("lane", SONNET)
    review = ip.request_seconds("reviewer", FABLE)
    assert ip.arm_seconds(ip.ARM_D) == pytest.approx(2 * lane + 951.0 + review)


def test_an_x2_fable_leap_plans_its_timeout() -> None:
    """X2's minutes price a Fable 5.2 leap at its 951 s timeout (no E1
    seconds exist for it); an Opus leap keeps E1's measured seconds."""
    with pytest.raises(ValueError, match="no E1 seconds"):
        ip.request_seconds("leap", FABLE_5_2)
    assert x2.run_minutes(x2.arm_settings(x2.X2_L)) == 113
    assert x2.run_minutes(x2.arm_settings(x2.X2_0)) == 89


# ---------------------------------------------------------------------------
# X2-L (O61): X2-0 with the Fable 5.2 leap, the existing prompt, no portfolio
# ---------------------------------------------------------------------------

FOUR = ("sqlparse", "tomli", "mistune", "markdown")


def test_x2_l_is_x2_0_with_the_fable_leap_off_the_plan() -> None:
    """Only the leap's model differs from X2-0 (and D63's retention flag
    Fable 5.2 needs); no portfolio, so no deal run; listed after X2-F and
    before X2-S, so the older tails stand; off the plan and the pool."""
    arm = x2.X2_L
    assert (arm.key, arm.repos, arm.aa) == ("X2-L", FOUR, "none")
    assert dict(arm.update) == {**x2.SHARED, "IDEAS_LEAP_MODEL": FABLE_5_2,
                                "ALLOW_RETENTION_MODELS": True}  # fmt: skip
    assert arm not in x2.PORTFOLIO_ARMS and arm not in x2.X2_ARMS
    keys = [a.key for a in x2.EVERY_ARM]
    assert keys[keys.index("X2-F") + 1 : keys.index("X2-S")] == ["X2-L"]
    assert not any(d.startswith("X2-L") for d in x2.dispatches())
    assert "X2-L" in xr.ARMS and "X2-L" not in xr.POOL
    env = x2.arm_env(arm)
    assert env["IDEAS_LEAP_MODEL"] == FABLE_5_2
    assert env["ALLOW_RETENTION_MODELS"] == "true"
    assert "IDEAS_LEAP_PORTFOLIO" not in env and "IDEAS_LEAP_DEAL_RUN" not in env
    cfg = x2.arm_settings(arm)
    assert cfg.IDEAS_LEAP_PORTFOLIO is False
    shape = leap_shape(cfg)
    assert shape == leap_shape(x2.arm_settings(x2.X2_F))  # X2-F's leap shape
    assert (shape.effort, shape.max_tokens, shape.timeout_s) == ("high", 32_000, 951.0)
    x2.check_settings(arm, cfg)  # no deal run needed


def test_x2_l_caps_minutes_and_dispatches() -> None:
    """X2-L's cap is X2-F's, 21.10 (the same Fable 5.2 leap at 32,000 on
    its chain; the share at S2's check binds), 113 minutes (the 951 s leap
    twice); two runs a dispatch at a 20 % margin under the 360-minute job
    (three fit the job and the 80 USD fuse: check_plan takes them), the need
    of two 43 USD, of three 64."""
    cfg = x2.arm_settings(x2.X2_L)
    assert x2.leap_extra_usd(cfg) > 0
    assert x2.call_usd(cfg) == x2.call_usd(x2.arm_settings(x2.X2_F))
    assert (x2.arm_cap(x2.X2_L), x2.run_minutes(cfg)) == (21.10, 113)
    assert x2.arm_cap(x2.X2_L) == x2.arm_cap(x2.X2_F)
    assert int(x2.JOB_MINUTES * 0.8) // 113 == 2 and x2.JOB_MINUTES // 113 == 3
    for names, need, minutes in (("sqlparse,tomli", 43, 226),
                                 ("mistune,markdown,tomli", 64, 339)):  # fmt: skip
        plan = x2.x2_plan({x2.DISPATCH_ENV: f"X2-L:{names}", SUITE_CAP_ENV: str(need)})
        assert math.ceil(x2.x2_need(plan)) == need and x2.plan_minutes(plan) == minutes
    with pytest.raises(ValueError, match="past the 80 USD fuse"):
        x2.check_plan(x2.X2Plan("X2-L:4", tuple((x2.X2_L, x2.LIBRARIES[n]) for n in FOUR)),
                      150.0)  # fmt: skip


def test_x2_l_round_2s_lanes_pass_the_engines_check_at_the_worst() -> None:
    """At S2's check of the seeded round-2 call, as run_cap prices it (round
    1's call spent at ``call_usd``, the seeded S1 at X1's dearest, round 1's
    trials at X1's loop rate after phase 1), the engine's own discovery cap
    (``nodes._discovery_cap``, called) leaves room for the static S2 stage,
    which holds the engine's S2 reservation (Fable 5.2's 3.32 leap included):
    ``Budget.check`` passes, so S2 is never skipped whole."""
    cfg = x2.arm_settings(x2.X2_L)
    cap = x2.arm_cap(x2.X2_L)
    _, s2, _ = x2.seeded_stages(cfg)
    discovery = x2.call_usd(cfg) + x2.X1_S1_USD
    trials = x2.X1_LOOP_USD / x2.LOOP_TRIALS * x2.run_trials(cfg)[0]
    cost = dx.OSS_PHASE_ONE_WORST_USD + trials + discovery
    ctx = SimpleNamespace(discovery_max_share=cfg.IDEAS_DISCOVERY_MAX_SHARE,
                          min_trial_budget_usd=settings_trial_budget(cfg))  # fmt: skip
    state = {"max_cost_usd": cap, "cost_usd": cost, "discovery_cost_usd": discovery}
    room = _discovery_cap(cast(Any, ctx), cast(Any, state)) - cost
    engine_s2 = sum(_engine(cfg, lane) for lane in ip.s2_lanes(cfg))
    assert room >= s2 >= engine_s2
    assert room - s2 == pytest.approx(0.02, abs=0.01)  # X2-F's margin, the tightest
    Budget(cap_usd=room).check(engine_s2)
    Budget(cap_usd=room).check(s2)
