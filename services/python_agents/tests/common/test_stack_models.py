"""X2-DT, U1: the stacked-rounds records and their setting (O63).

``RoundBase`` records one round's end under stacking: the base the round's
trials started from, the keeps offered to the round combine, that combine,
whether its tip was adopted as the next base and why (not). ``StackLedger``
holds the original base and its baseline, the rounds in order, the delivery
re-test against the original base and the owner's secondary,
``all_rounds_held``. ``STACKED_ROUNDS`` is off by default. Hand-built models,
no I/O.
"""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from autonomous_ai_agents.common.config import Settings
from autonomous_ai_agents.common.models import (
    ENGINE_MODEL_CLASSES,
    STACK_SECONDS_KEYS,
    Baseline,
    Combination,
    NoiseCalibration,
    RoundBase,
    StackLedger,
    rounds_held,
)

ORIGIN = "0" * 40
TIP_1 = "1" * 40
TIP_2 = "2" * 40
TIP_3 = "3" * 40


def _combination(base: str, *, holds: bool, tip: str | None) -> Combination:
    return Combination(base_commit=base, tip_commit=tip, applied_trial_ids=("t-1",),
                       holds=holds, summary="t-1 applied")  # fmt: skip


def _adopted(number: int, base: str, tip: str, **extra: object) -> RoundBase:
    return RoundBase.model_validate(
        {
            "round": number,
            "base_commit": base,
            "offered_trial_ids": ("t-1",),
            "combination": _combination(base, holds=True, tip=tip),
            "adopted": True,
            "tip_commit": tip,
            "reason": "held",
            **extra,
        }
    )


def _nothing(number: int, base: str) -> RoundBase:
    return RoundBase(round=number, base_commit=base, reason="nothing kept")


def _not_held(number: int, base: str) -> RoundBase:
    return RoundBase(round=number, base_commit=base, offered_trial_ids=("t-1",),
                     combination=_combination(base, holds=False, tip=TIP_3),
                     reason="did not hold")  # fmt: skip


def _ledger(*rounds: RoundBase, **extra: object) -> StackLedger:
    return StackLedger.model_validate(
        {
            "origin_commit": ORIGIN,
            "origin_baseline": Baseline(commit=ORIGIN),
            "rounds": rounds,
            **extra,
        }
    )


# ---------------------------------------------------------------------------
# RoundBase
# ---------------------------------------------------------------------------


def test_a_round_with_nothing_kept_has_no_combine_and_keeps_its_base() -> None:
    record = _nothing(1, ORIGIN)

    assert (record.offered_trial_ids, record.combination) == ((), None)
    assert (record.adopted, record.tip_commit, record.floor) == (False, None, None)
    assert record.seconds == {}
    assert record.next_base == ORIGIN


def test_an_adopted_round_moves_the_base_to_its_tip_with_its_floor() -> None:
    seconds = {"combine": 12.5, "fallback": 0.0, "baseline": 8.0,
               "calibration": 20.25, "profile": 3.0}  # fmt: skip
    record = _adopted(2, TIP_1, TIP_2, floor=0.031, seconds=seconds)

    assert record.next_base == TIP_2
    assert record.floor == 0.031
    assert record.seconds == seconds
    assert set(record.seconds) == STACK_SECONDS_KEYS


def test_a_held_tip_refused_keeps_the_base_and_may_name_the_tip() -> None:
    refused = RoundBase(round=1, base_commit=ORIGIN, offered_trial_ids=("t-1", "t-2"),
                        combination=_combination(ORIGIN, holds=True, tip=TIP_1),
                        tip_commit=TIP_1,
                        reason="tip outputs differ from the original base")  # fmt: skip

    assert (refused.adopted, refused.next_base) == (False, ORIGIN)
    assert _not_held(1, ORIGIN).next_base == ORIGIN


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {
                "offered_trial_ids": (),
                "combination": None,
                "adopted": True,
                "tip_commit": TIP_1,
            },
            "only a held round combine",
        ),
        (
            {
                "combination": _combination(ORIGIN, holds=False, tip=TIP_1),
                "adopted": True,
                "tip_commit": TIP_1,
            },
            "only a held round combine",
        ),
        ({"adopted": True, "tip_commit": None}, "an adopted round names its tip"),
        (
            {
                "combination": _combination(ORIGIN, holds=True, tip=None),
                "adopted": True,
                "tip_commit": None,
            },
            "an adopted round names its tip",
        ),
        ({"adopted": True, "tip_commit": TIP_2}, "the combine's tip"),
        ({"tip_commit": TIP_2}, "the combine's tip"),
        ({"floor": 0.03}, "a floor is the adopted tip's"),
        ({"offered_trial_ids": ()}, "exactly when keeps are offered"),
        ({"combination": None}, "exactly when keeps are offered"),
        (
            {"combination": _combination(TIP_2, holds=True, tip=TIP_1)},
            "on the round base",
        ),
        ({"offered_trial_ids": ("t-1", "t-1")}, "each kept trial once"),
        ({"seconds": {"combine": 1.0, "deliver": 2.0}}, r"unknown steps \['deliver'\]"),
        ({"seconds": {"combine": -0.5}}, "at least 0"),
        ({"floor": -0.01}, "greater than or equal to 0"),
        ({"round": 0}, "greater than or equal to 1"),
        ({"reason": ""}, "at least 1 character"),
        ({"base_commit": ""}, "at least 1 character"),
        ({"seconds": {"combine": math.nan}}, "finite number"),
    ],
)
def test_a_round_record_that_contradicts_itself_is_refused(
    change: dict[str, object], message: str
) -> None:
    held = {"round": 1, "base_commit": ORIGIN, "offered_trial_ids": ("t-1",),
            "combination": _combination(ORIGIN, holds=True, tip=TIP_1),
            "reason": "held"}  # fmt: skip

    with pytest.raises(ValidationError, match=message):
        RoundBase.model_validate({**held, **change})


def test_a_round_record_is_frozen_strict_and_allowlisted() -> None:
    record = _nothing(1, ORIGIN)

    assert RoundBase in ENGINE_MODEL_CLASSES and StackLedger in ENGINE_MODEL_CLASSES
    with pytest.raises(ValidationError):
        record.adopted = True  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        RoundBase.model_validate({"round": 1, "base_commit": ORIGIN,
                                  "reason": "held", "gain": 0.1})  # fmt: skip


# ---------------------------------------------------------------------------
# StackLedger
# ---------------------------------------------------------------------------


def test_a_fresh_ledger_is_the_origin_and_its_baseline_alone() -> None:
    ledger = _ledger()

    assert ledger.rounds == () and ledger.current_base == ORIGIN
    assert (ledger.delivery, ledger.delivery_seconds, ledger.all_rounds_held) == (
        None,
        None,
        None,
    )
    assert StackLedger(origin_commit=ORIGIN, origin_baseline=Baseline()).rounds == ()


def test_the_rounds_chain_from_the_origin_through_each_adopted_tip() -> None:
    delivery = _combination(ORIGIN, holds=True, tip=TIP_3)
    ledger = _ledger(_adopted(1, ORIGIN, TIP_1), _not_held(2, TIP_1),
                     _adopted(3, TIP_1, TIP_2), delivery=delivery,
                     delivery_seconds=41.5, all_rounds_held=False)  # fmt: skip

    assert ledger.current_base == TIP_2
    assert [r.base_commit for r in ledger.rounds] == [ORIGIN, TIP_1, TIP_1]
    assert ledger.delivery == delivery and ledger.delivery_seconds == 41.5


@pytest.mark.parametrize(
    ("rounds", "extra", "message"),
    [
        ((_nothing(1, TIP_1),), {}, "round 1 must start from"),
        (
            (_adopted(1, ORIGIN, TIP_1), _nothing(2, ORIGIN)),
            {},
            "round 2 must start from",
        ),
        ((_not_held(1, ORIGIN), _nothing(2, TIP_3)), {}, "round 2 must start from"),
        ((_nothing(2, ORIGIN), _nothing(2, ORIGIN)), {}, "rounds must be in order"),
        ((_nothing(3, ORIGIN), _nothing(1, ORIGIN)), {}, "rounds must be in order"),
        (
            (),
            {"origin_baseline": Baseline(commit=TIP_1)},
            "measured at the original base",
        ),
        (
            (),
            {"delivery": _combination(TIP_1, holds=True, tip=TIP_2)},
            "re-tested on the original base",
        ),
        ((), {"delivery_seconds": 3.0}, "a delivery time needs a delivery"),
        (
            (),
            {
                "delivery": _combination(ORIGIN, holds=False, tip=TIP_1),
                "delivery_seconds": -1.0,
            },
            "greater than or equal to 0",
        ),
        ((), {"all_rounds_held": True}, "all_rounds_held must be None"),
        ((_nothing(1, ORIGIN),), {"all_rounds_held": False}, "must be None"),
        ((_adopted(1, ORIGIN, TIP_1),), {"all_rounds_held": False}, "must be True"),
        ((_not_held(1, ORIGIN),), {"all_rounds_held": True}, "must be False"),
        ((), {"origin_commit": ""}, "at least 1 character"),
    ],
)
def test_a_ledger_that_contradicts_itself_is_refused(
    rounds: tuple[RoundBase, ...], extra: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _ledger(*rounds, **extra)


def test_all_rounds_held_counts_only_the_rounds_with_keeps() -> None:
    held, missed, empty = _adopted(1, ORIGIN, TIP_1), _not_held(2, TIP_1), _nothing(3, TIP_1)  # fmt: skip

    assert rounds_held(()) is None
    assert rounds_held((_nothing(1, ORIGIN),)) is None
    assert rounds_held((held, _nothing(2, TIP_1))) is True
    assert rounds_held((held, missed, empty)) is False
    assert _ledger(held, missed, empty, all_rounds_held=False).all_rounds_held is False
    assert _ledger(held, all_rounds_held=True).all_rounds_held is True


def test_a_refused_held_tip_counts_as_held_for_the_secondary() -> None:
    """The secondary asks whether every round's combine held, not whether its
    tip was adopted: a held tip refused at adoption still held."""
    refused = RoundBase(round=1, base_commit=ORIGIN, offered_trial_ids=("t-1",),
                        combination=_combination(ORIGIN, holds=True, tip=TIP_1),
                        reason="the tip's baseline failed: noisy host")  # fmt: skip

    assert rounds_held((refused,)) is True
    assert _ledger(refused, all_rounds_held=True).current_base == ORIGIN


def test_a_full_ledger_round_trips_through_strict_json() -> None:
    calibration = NoiseCalibration(blocks=3, gaps={"w": 0.01}, floor=0.02)
    ledger = StackLedger(
        origin_commit=ORIGIN,
        origin_baseline=Baseline(commit=ORIGIN, calibration=calibration),
        rounds=(
            _adopted(1, ORIGIN, TIP_1, floor=0.02, seconds={"combine": 1.5}),
            _not_held(2, TIP_1),
        ),
        delivery=_combination(ORIGIN, holds=True, tip=TIP_2),
        delivery_seconds=9.0,
        all_rounds_held=False,
    )

    text = json.dumps(ledger.model_dump(mode="json"), allow_nan=False)
    again = StackLedger.model_validate(json.loads(text))

    assert again == ledger
    assert type(again.rounds) is tuple and type(again.rounds[0]) is RoundBase


def test_with_round_appends_a_validated_round_and_leaves_the_ledger_alone() -> None:
    fresh, first, second = _ledger(), _adopted(1, ORIGIN, TIP_1), _not_held(2, TIP_1)

    one = fresh.with_round(first)
    two = one.with_round(second)

    assert fresh.rounds == () and one.rounds == (first,)
    assert two.rounds == (first, second) and two.current_base == TIP_1
    assert two == StackLedger(origin_commit=ORIGIN,
                              origin_baseline=fresh.origin_baseline,
                              rounds=(first, second))  # fmt: skip
    assert type(two.rounds[1]) is RoundBase


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (_nothing(2, ORIGIN), "round 2 must start from"),
        (_nothing(1, TIP_1), "rounds must be in order"),
    ],
)
def test_with_round_refuses_a_round_that_breaks_the_chain(
    record: RoundBase, message: str
) -> None:
    ledger = _ledger(_adopted(1, ORIGIN, TIP_1))

    with pytest.raises(ValidationError, match=message):
        ledger.with_round(record)


def test_with_round_validates_again_a_round_that_skipped_its_validators() -> None:
    """A record built past its validators (``model_copy``) is checked anew."""
    forged = _nothing(1, ORIGIN).model_copy(update={"adopted": True})

    with pytest.raises(ValidationError, match="only a held round combine"):
        _ledger().with_round(forged)


def test_with_round_refuses_a_closed_ledger() -> None:
    """Once ``closed`` set a delivery or the secondary, no round may follow."""
    delivered = _ledger(_adopted(1, ORIGIN, TIP_1)).closed(
        _combination(ORIGIN, holds=True, tip=TIP_2), 5.0
    )
    secondary_only = _ledger(_adopted(1, ORIGIN, TIP_1)).closed(None, None)

    for ledger in (delivered, secondary_only):
        with pytest.raises(ValueError, match="the ledger is closed"):
            ledger.with_round(_adopted(2, TIP_1, TIP_3))


def test_model_copy_skips_the_checks_the_builders_keep() -> None:
    """Why ledgers are never changed with ``model_copy``: it accepts a broken
    chain that ``with_round`` refuses."""
    broken = _ledger().model_copy(update={"rounds": (_nothing(1, TIP_1),)})

    assert broken.rounds[0].base_commit == TIP_1
    with pytest.raises(ValidationError, match="round 1 must start from"):
        _ledger().with_round(_nothing(1, TIP_1))


def test_closed_sets_the_delivery_and_computes_the_secondary() -> None:
    open_ledger = _ledger(_adopted(1, ORIGIN, TIP_1), _not_held(2, TIP_1))
    delivery = _combination(ORIGIN, holds=False, tip=TIP_2)

    done = open_ledger.closed(delivery, 12.0)

    assert (done.delivery, done.delivery_seconds) == (delivery, 12.0)
    assert done.all_rounds_held is False
    assert done.rounds == open_ledger.rounds and open_ledger.delivery is None
    held = _ledger(_adopted(1, ORIGIN, TIP_1)).closed(delivery, 1.0)
    assert held.all_rounds_held is True
    assert _ledger(_nothing(1, ORIGIN)).closed(None, None).all_rounds_held is None


def test_closed_without_a_retest_keeps_no_delivery() -> None:
    """The last held combine ran on the origin: no re-test, no delivery row."""
    done = _ledger(_adopted(1, ORIGIN, TIP_1)).closed(None, None)

    assert (done.delivery, done.delivery_seconds, done.all_rounds_held) == (
        None,
        None,
        True,
    )


@pytest.mark.parametrize(
    ("delivery", "seconds", "message"),
    [
        (_combination(TIP_1, holds=True, tip=TIP_2), 1.0, "on the original base"),
        (None, 2.0, "a delivery time needs a delivery"),
        (_combination(ORIGIN, holds=True, tip=TIP_2), -1.0, "greater than or equal"),
    ],
)
def test_closed_refuses_a_delivery_that_contradicts_the_ledger(
    delivery: Combination | None, seconds: float | None, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _ledger(_adopted(1, ORIGIN, TIP_1)).closed(delivery, seconds)


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_stacked_rounds_is_off_by_default_and_parses_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings(_env_file=None).STACKED_ROUNDS is False
    monkeypatch.setenv("STACKED_ROUNDS", "true")
    assert Settings(_env_file=None).STACKED_ROUNDS is True
    monkeypatch.setenv("STACKED_ROUNDS", "0")
    assert Settings(_env_file=None).STACKED_ROUNDS is False
    monkeypatch.setenv("STACKED_ROUNDS", "sometimes")
    with pytest.raises(ValidationError, match="STACKED_ROUNDS"):
        Settings(_env_file=None)
