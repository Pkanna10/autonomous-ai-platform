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

from . import discovery_ab as ab
from . import ideas_probe as ip
from . import ideas_x2 as x2
from .discovery import FABLE, SONNET, chain_worst_usd

FABLE_5_2, OPUS_4_8 = "claude-fable-5-2", "claude-opus-4-8"
X2_FABLE: x2.X2Arm = x2.X2Arm(
    "X2-Fable", x2.X2_0.repos, {**x2.SHARED, "IDEAS_LEAP_MODEL": FABLE_5_2},
    "X2-0 with the Fable 5.2 leap (not an arm: the owner's call)",
)  # fmt: skip


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
    cfg = x2.arm_settings(X2_FABLE)
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
    cfg = x2.arm_settings(X2_FABLE)
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
    assert x2.run_minutes(x2.arm_settings(X2_FABLE)) == 113
    assert x2.run_minutes(x2.arm_settings(x2.X2_0)) == 89
