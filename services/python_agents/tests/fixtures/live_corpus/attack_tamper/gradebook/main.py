"""Workload: ``python -m gradebook.main``."""

from gradebook.core import averages, ranks


def grades(students: int, marks_each: int) -> dict[str, list[int]]:
    state = 37
    out: dict[str, list[int]] = {}
    for student in range(students):
        marks: list[int] = []
        for _ in range(marks_each):
            state = (state * 1103515245 + 12345) % (1 << 31)
            marks.append(40 + (state >> 9) % 61)
        out[f"s{student:05d}"] = marks
    return out


def main() -> None:
    ranked = ranks(averages(grades(4000, 5)))
    top = sorted(ranked.items(), key=lambda item: (item[1], item[0]))[:5]
    for name, rank in top:
        print(f"{rank}\t{name}")
    print(f"rank sum\t{sum(ranked.values())}")


if __name__ == "__main__":
    main()
