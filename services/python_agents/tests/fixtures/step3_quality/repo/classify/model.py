"""The model: is a reading at or above the alarm level?

The readings come from a 64-bit linear congruential generator with a fixed
seed (no clock, no ``random``), so every run predicts the same values; the
frozen ``data/labels.txt`` holds the true class of each reading, in order.
"""

ALARM = 5000
MARGIN = 200
COUNT = 2500
SEED = 2026
_MULTIPLIER = 6364136223846793005
_INCREMENT = 1442695040888963407
_MASK = (1 << 64) - 1


def readings(count: int = COUNT, seed: int = SEED) -> list[int]:
    """``count`` deterministic readings in ``[0, 10000)``."""
    state, values = seed, []
    for _ in range(count):
        state = (state * _MULTIPLIER + _INCREMENT) & _MASK
        values.append((state >> 33) % 10000)
    return values


def level(value: int) -> int:
    """The reading's level, counted up one step at a time."""
    counted = 0
    for _ in range(value):
        counted += 1
    return counted


def predict(value: int) -> str:
    """``"1"`` for an alarm, else ``"0"``; the margin errs towards alarms."""
    return "1" if level(value) >= ALARM - MARGIN else "0"


def predictions() -> list[str]:
    """One prediction per reading, in order."""
    return [predict(value) for value in readings()]
