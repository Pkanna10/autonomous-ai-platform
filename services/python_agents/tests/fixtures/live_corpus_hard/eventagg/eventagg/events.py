"""Deterministic service events: the same day on every run."""

KINDS = ("request", "retry", "error", "redirect", "timeout")
REGIONS = ("eu-west", "eu-north", "us-east", "us-west", "ap-south", "sa-east")


def generate(count: int, seed: int = 29) -> list[dict[str, object]]:
    """The day's ``count`` events, in the order they were logged."""
    state = seed
    out: list[dict[str, object]] = []
    for number in range(count):
        state = (state * 1103515245 + 12345) % (1 << 31)
        value = state >> 4
        out.append(
            {
                "id": f"evt-{number:08d}",
                "kind": KINDS[value % len(KINDS)],
                "region": REGIONS[(value >> 3) % len(REGIONS)],
                "bytes": value % 65536,
                "latency_ms": (value >> 5) % 5000 / 10,
                "status": 200 + (value >> 7) % 4 * 100,
            }
        )
    return out
