"""Backoff delays."""

import random


def delays(attempts, base, cap, seed=None):
    """The wait in seconds before each of ``attempts`` retries: ``base``
    doubled per attempt, times a jitter factor drawn from [0.5, 1.5) so that
    clients do not retry in lockstep, and never more than ``cap``: no single
    wait is ever longer than ``cap`` seconds. ``seed`` makes the jitter
    reproducible."""
    rng = random.Random(seed)
    return [min(cap, base * 2**i * rng.uniform(0.5, 1.5)) for i in range(attempts)]
