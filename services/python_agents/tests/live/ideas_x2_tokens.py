"""U-tokens: the leap's output tokens against its cap (X2-L), offline.

``uv run python -m live.ideas_x2_tokens <results.jsonl>... [--out DIR]``
(from ``tests/``, ``PYTHONPATH=../src:.``) reads the round rows' ``lane_views``
(``IDEAS_VIEW_RECORD``) through ``ideas_x2_report.draws`` and writes
``tokens.md``: per arm, each leap call's served model, output tokens against
the request's ``max_tokens`` (each attempt's beside it on a fallback), stop
reason and headroom (cap less output),
then each arm's least, median (lower) and most headroom over the calls that
replied. Record-only: it shows whether a stop is near, it decides nothing.
"""

from __future__ import annotations

import argparse
import statistics
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from autonomous_ai_agents.optimization.idea_types import Lane

from .ideas_x2_report import ARMS, REPORT_DIR, Draw, LaneView, _table, draws

LEAP: Final = Lane.leap.value


def _calls(found: Sequence[Draw]) -> list[tuple[Draw, int, LaneView]]:
    return [(d, r.round, v) for arm in ARMS for d in found if d.arm == arm
            for r in d.run.rounds for v in r.lane_views if v.lane == LEAP]  # fmt: skip


def _room(v: LaneView) -> int | None:
    if v.output_tokens is None or v.max_tokens is None:
        return None
    return v.max_tokens - v.output_tokens


def _call_row(d: Draw, n: int, v: LaneView) -> list[object]:
    room = _room(v)
    if room is None:
        spent = "no reply" if v.served_model is None else "not recorded"
        return [d.arm, d.repo, d.source, n, v.served_model or "-", spent, "-", "-"]
    spent = f"{v.output_tokens} / {v.max_tokens}"
    if v.attempt_output_tokens is not None:  # a fallback: every attempt's tokens
        spent += f" (attempts {v.attempt_output_tokens})"
    return [d.arm, d.repo, d.source, n, v.served_model, spent, v.stop_reason or "-", room]  # fmt: skip


def render_tokens(found: Sequence[Draw]) -> str:
    calls = _calls(found)
    arms: list[list[object]] = []
    for arm in [a for a in ARMS if any(d.arm == a for d, _, _ in calls)]:
        mine = [v for d, _, v in calls if d.arm == arm]
        rooms = sorted(r for v in mine if (r := _room(v)) is not None)
        spread = ([rooms[0], statistics.median_low(rooms), rooms[-1]] if rooms
                  else ["-", "-", "-"])  # fmt: skip
        arms.append([arm, len(mine), len(rooms),
                     sum(v.stop_reason == "max_tokens" for v in mine), *spread])  # fmt: skip
    return "\n".join([
        "# X2 leap output tokens against the cap (X2-L)", "",
        "- **Per leap call.** The served model's output tokens against the request's "
        "max_tokens (on a fallback, each attempt's beside it), the stop reason and the "
        "headroom (cap less output). No reply: the "
        "request raised; not recorded: a row from before the token fields.",
        "- **Per arm.** The least, median (lower) and most headroom over the calls that "
        "replied, and the calls that stopped at max_tokens.", "",
        "## 1 Leap calls", "",
        *_table(("arm", "library", "file", "round", "model", "output / max",
                 "stop reason", "headroom"), [_call_row(*c) for c in calls]),
        "## 2 Headroom per arm", "",
        *_table(("arm", "leap calls", "replied", "max_tokens stops", "least headroom",
                 "median headroom", "most headroom"), arms),
    ])  # fmt: skip


def main(argv: Sequence[str] | None = None, echo: Callable[[str], None] = print) -> int:
    """Write ``tokens.md``; 2 on a refused or unreadable input (nothing written)."""
    parser = argparse.ArgumentParser(prog="ideas_x2_tokens", description=__doc__)
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    try:
        text = render_tokens(draws(args.results))
    except (OSError, ValueError) as error:
        echo(f"error: {error}")
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "tokens.md").write_text(text, encoding="utf-8", newline="\n")
    echo(f"wrote tokens.md to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
