"""Workload: ``python -m examboard.main``."""

from examboard.data import candidates, marks
from examboard.stats import exam_report


def main() -> None:
    names = candidates(4000)
    for exam in range(120):
        report = exam_report(marks(exam, names))
        print(f"paper {exam:03d}\t" + "\t".join(f"{k}={v}" for k, v in report.items()))


if __name__ == "__main__":
    main()
