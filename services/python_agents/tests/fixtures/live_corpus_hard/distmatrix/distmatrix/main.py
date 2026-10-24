"""Workload: ``python -m distmatrix.main``."""

from distmatrix.distances import histogram, matrix, summaries
from distmatrix.points import generate


def main() -> None:
    points = generate(1900)
    rows = summaries(matrix(points))
    nearest = [near for near, _ in rows]
    isolated = sorted(range(len(rows)), key=lambda i: (-rows[i][0], i))[:5]
    for i in isolated:
        near, mean = rows[i]
        print(f"point {i}\tnearest {near:.4f}\tmean {mean:.4f}")
    print("histogram " + " ".join(map(str, histogram(nearest, 4.0, 8))))
    print(f"overall mean {sum(mean for _, mean in rows) / len(rows):.6f}")


if __name__ == "__main__":
    main()
