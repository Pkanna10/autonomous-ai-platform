"""Retry plans that must fit a deadline."""

from retryplan.backoff import delays


class DeadlineError(RuntimeError):
    """The retries cannot fit in the job's deadline."""


def plan(attempts, base, cap, deadline, seed=None):
    """The waits for a job that must finish its retries within ``deadline``
    seconds. No wait is longer than ``cap``, so ``attempts * cap`` is the
    longest any plan takes: when it fits the deadline, the plan always fits;
    when it does not, DeadlineError at once."""
    if attempts * cap > deadline:
        raise DeadlineError(
            f"{attempts} retries of up to {cap} s cannot fit in {deadline} s"
        )
    waits = delays(attempts, base, cap, seed)
    total = sum(waits)
    if total > deadline:
        raise DeadlineError(
            f"retries need {total:.1f} s, more than the {deadline} s deadline"
        )
    return waits
