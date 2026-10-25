"""The workload: ``python -m classify.main`` prints one prediction per line."""

from classify.model import predictions


def main() -> int:
    """Print the predictions and return the exit code."""
    print("\n".join(predictions()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
