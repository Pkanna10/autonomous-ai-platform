"""The published figures of one exam paper.

``results`` holds ``(mark, candidate)`` pairs; the ranking orders them by
mark, highest first, ties by candidate, the later one first."""

Result = tuple[int, str]


def top_candidate(results: list[Result]) -> str:
    mark, name = sorted(results, reverse=True)[0]
    return f"{name} {mark}"


def median_mark(results: list[Result]) -> int:
    return sorted(results, reverse=True)[len(results) // 2][0]


def upper_quartile(results: list[Result]) -> int:
    return sorted(results, reverse=True)[len(results) // 4][0]


def boundaries(results: list[Result]) -> str:
    ranked = sorted(results, reverse=True)
    return "/".join(
        str(ranked[len(ranked) * share // 100][0]) for share in (10, 30, 60)
    )


def top_decile_mean(results: list[Result]) -> float:
    top = sorted(results, reverse=True)[: max(1, len(results) // 10)]
    return sum(mark for mark, _ in top) / len(top)


def trimmed_mean(results: list[Result]) -> float:
    ranked = sorted(results, reverse=True)
    cut = len(ranked) // 10
    kept = ranked[cut : len(ranked) - cut]
    return sum(mark for mark, _ in kept) / len(kept)


def widest_gap(results: list[Result]) -> int:
    ranked = sorted(results, reverse=True)
    widest = 0
    for (higher, _), (lower, _) in zip(ranked, ranked[1:], strict=False):
        if higher - lower > widest:
            widest = higher - lower
    return widest


def exam_report(results: list[Result]) -> dict[str, str]:
    return {
        "top": top_candidate(results),
        "median": str(median_mark(results)),
        "upper quartile": str(upper_quartile(results)),
        "boundaries": boundaries(results),
        "top decile mean": f"{top_decile_mean(results):.2f}",
        "trimmed mean": f"{trimmed_mean(results):.2f}",
        "widest gap": str(widest_gap(results)),
    }
