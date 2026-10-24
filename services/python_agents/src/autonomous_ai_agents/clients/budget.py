"""The per-run cost budget every paid Claude request goes through.

A node that spends money rebuilds ``Budget(state["max_cost_usd"],
state["cost_usd"])``, so the budget survives a checkpoint and resume. Callers
use it in two places:

- ``check(estimate_usd)`` **before** every attempt, with the worst-case
  pre-send estimate. It raises ``BudgetExceeded`` when the attempt could take
  the run past its cap, so the request is never sent.
- ``record(usd, tokens)`` **after** every attempt, with what was billed
  (a timeout is charged the full estimate). The amount is added first, since
  the money is gone either way, then ``BudgetExceeded`` is raised if the total
  is over the cap. With a true worst-case estimate that cannot happen.

Negative or non-finite amounts are programming errors and raise
``ValueError``: a NaN would make every comparison false and let any spend
through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from autonomous_ai_agents.common.errors import BudgetExceeded


def _require_amount(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and at least 0, got {value}")


def _require_tokens(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be at least 0, got {value}")


@dataclass
class Budget:
    """Money and tokens spent against a hard cap, in USD.

    Mutable on purpose: one instance is threaded through every request of a
    node call. ``spent_usd`` may start above the cap (a state that recorded an
    overrun); ``remaining`` is then 0 and every ``check`` fails.

    The cap is a strict bound in plain float arithmetic, with no tolerance:
    amounts whose decimal sum equals the cap can land one ulp above it and be
    refused (``Budget(0.3, 0.1).check(0.2)`` raises, as ``0.1 + 0.2 > 0.3``).
    Worst-case estimates never sit exactly on the cap, so this only matters to
    a test that aims at it; give such a test a little headroom.
    """

    cap_usd: float
    spent_usd: float = 0.0
    tokens: int = 0

    def __post_init__(self) -> None:
        _require_amount("cap_usd", self.cap_usd)
        _require_amount("spent_usd", self.spent_usd)
        _require_tokens("tokens", self.tokens)

    @property
    def remaining(self) -> float:
        """Money left before the cap, never below 0."""
        return max(0.0, self.cap_usd - self.spent_usd)

    def check(self, estimate_usd: float) -> None:
        """Raise ``BudgetExceeded`` if spending ``estimate_usd`` would pass the cap."""
        _require_amount("estimate_usd", estimate_usd)
        if self.spent_usd + estimate_usd > self.cap_usd:
            raise BudgetExceeded(
                f"spent {self.spent_usd:.6f} USD + estimate {estimate_usd:.6f} USD "
                f"exceeds the cap of {self.cap_usd:.6f} USD"
            )

    def record(self, usd: float, tokens: int) -> None:
        """Add a billed attempt; raise ``BudgetExceeded`` if the total passes the cap."""
        _require_amount("usd", usd)
        _require_tokens("tokens", tokens)
        self.spent_usd += usd
        self.tokens += tokens
        if self.spent_usd > self.cap_usd:
            raise BudgetExceeded(
                f"recorded spend {self.spent_usd:.6f} USD exceeds the cap of "
                f"{self.cap_usd:.6f} USD"
            )
