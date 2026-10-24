"""Knobs, results and summaries of the discovery experiments (E3, E5, E8a).

- ``env_number`` / ``env_whole`` / ``env_flag``: a knob read strictly from the
  environment (the module fixtures call them before any test spends).
- ``ResultsSink`` / ``json_line``: JSON lines to ``$LIVE_RESULTS_PATH``
  (strings capped at ``JSON_TEXT_MAX``, NaN as null), the path checked as
  ``corpus.CorpusRecorder`` checks it.
- ``write_markdown`` / ``cells``: a markdown section to ``$GITHUB_STEP_SUMMARY``
  (echoed otherwise), every cell through the cost table's sanitiser
  (``conftest._cell``: no cell break, link, code span, mention or raw HTML).
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .conftest import _cell
from .corpus import JSON_TEXT_MAX, RESULTS_ENV, SUMMARY_ENV


def env_number(
    environ: Mapping[str, str], name: str, default: float, *, high: float
) -> float:
    """A USD amount in (0, ``high``]; unset means ``default``."""
    if name not in environ:
        return default
    raw = environ[name]
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if raw != raw.strip() or not math.isfinite(value) or not 0 < value <= high:
        raise ValueError(f"{name} must be a number in (0, {high}], got {raw!r}")
    return value


def env_whole(
    environ: Mapping[str, str], name: str, default: int, *, low: int, high: int
) -> int:
    """A whole number in [``low``, ``high``] written as plain digits."""
    if name not in environ:
        return default
    raw = environ[name]
    if not raw.isascii() or not raw.isdigit() or not low <= int(raw) <= high:
        raise ValueError(f"{name} must be a whole number {low}-{high}, got {raw!r}")
    return int(raw)


def env_flag(environ: Mapping[str, str], name: str) -> bool:
    """Unset, empty or ``0``: off; ``1``: on; anything else is refused."""
    raw = environ.get(name, "")
    if raw not in {"", "0", "1"}:
        raise ValueError(f"{name} must be 0 or 1, got {raw!r}")
    return raw == "1"


# ---------------------------------------------------------------------------
# Results and summaries
# ---------------------------------------------------------------------------


def _clean(value: object) -> object:
    if isinstance(value, str):
        return value[:JSON_TEXT_MAX]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, list | tuple):
        return [_clean(item) for item in value]
    if isinstance(value, Mapping):
        return {str(k)[:JSON_TEXT_MAX]: _clean(v) for k, v in value.items()}
    return value


def json_line(record: Mapping[str, object]) -> str:
    """One JSON line: strings capped at ``JSON_TEXT_MAX``, NaN as null."""
    return json.dumps(_clean(record), sort_keys=True, allow_nan=False)


@dataclass
class ResultsSink:
    """Appends records to ``$LIVE_RESULTS_PATH``; a relative path, or one
    without a directory, is refused here (in a module fixture, before any
    run spends)."""

    environ: Mapping[str, str]

    def __post_init__(self) -> None:
        target = self.environ.get(RESULTS_ENV, "")
        if target and not os.path.isabs(target):
            raise ValueError(f"{RESULTS_ENV} must be an absolute path, got {target!r}")
        if target and not Path(target).parent.is_dir():
            raise ValueError(f"{RESULTS_ENV}: no directory for {target!r}")

    def write(self, record: Mapping[str, object]) -> None:
        target = self.environ.get(RESULTS_ENV, "")
        if target:
            with Path(target).open("a", encoding="utf-8") as results:
                results.write(json_line(record) + "\n")


def write_markdown(
    title: str, text: str, environ: Mapping[str, str], echo: Callable[[str], None]
) -> None:
    """Append ``text`` to ``$GITHUB_STEP_SUMMARY`` (absolute) and echo it
    too: the API does not return the job summary, the log it does."""
    target = environ.get(SUMMARY_ENV, "")
    if target and os.path.isabs(target):
        with open(target, "a", encoding="utf-8") as summary:
            summary.write(text + "\n")
        echo(f"{title}: written to the job summary")
    for line in text.splitlines():
        echo(line)


def cells(values: Sequence[object]) -> str:
    """One markdown table row; every cell sanitised like the cost table."""
    return "| " + " | ".join(_cell(str(value)) for value in values) + " |"


def flag(value: bool | None) -> str:
    return "-" if value is None else ("yes" if value else "no")


def rate(hits: int, total: int) -> str:
    return f"{hits}/{total} ({100 * hits / total:.1f}%)" if total else "0/0 (n/a)"


def per(spend: float, count: int) -> str:
    return f"{spend / count:.4f}" if count else "n/a"
