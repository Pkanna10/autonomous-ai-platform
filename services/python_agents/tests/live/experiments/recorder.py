"""Experiment results: JSON lines and a sanitised job-summary table.

``ExperimentRecorder`` appends one JSON line per observation to
``$LIVE_RESULTS_PATH`` (experiment, arm, item, metrics) and renders a
markdown table for ``$GITHUB_STEP_SUMMARY``. Nothing raw reaches either:
text is a capped one-line ``excerpt`` with every key redacted (the suite's
``redact_keys``: given secrets, the host key, anything key-shaped), and
table cells go through the cost table's own cell sanitiser.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

from ..conftest import _cell, redact_keys

EXCERPT_CHARS: Final = 300
RESULTS_ENV: Final = "LIVE_RESULTS_PATH"
SUMMARY_ENV: Final = "GITHUB_STEP_SUMMARY"
Metric: TypeAlias = str | int | float | bool | None


def excerpt(
    text: str, *, secrets: Collection[str] = (), limit: int = EXCERPT_CHARS
) -> str:
    """One printable line, keys redacted (before the cap, so never half a
    key), at most ``limit`` characters."""
    clean = redact_keys(text, secrets)
    flat = " ".join("".join(c if c.isprintable() else " " for c in clean).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


@dataclass(frozen=True)
class Row:
    experiment: str
    arm: str
    item: str
    metrics: dict[str, Metric]


class ExperimentRecorder:
    """Records observations; text metrics are capped, redacted excerpts and
    nothing but text, numbers, bools and ``None`` is accepted.

    A relative ``$LIVE_RESULTS_PATH`` (or one in a missing directory) is
    refused here, before any experiment spends.
    """

    def __init__(
        self, title: str, environ: Mapping[str, str], *, secrets: Collection[str] = ()
    ) -> None:
        target = environ.get(RESULTS_ENV, "")
        if target and not os.path.isabs(target):
            raise ValueError(f"{RESULTS_ENV} must be an absolute path, got {target!r}")
        if target and not Path(target).parent.is_dir():
            raise ValueError(f"{RESULTS_ENV}: no directory for {target!r}")
        self.title = title
        self.rows: list[Row] = []
        self.secrets: set[str] = set(secrets)
        self._results, self._summary = target, environ.get(SUMMARY_ENV, "")

    def _text(self, text: str, limit: int = EXCERPT_CHARS) -> str:
        return excerpt(text, secrets=self.secrets, limit=limit)

    def _metric(self, value: Metric) -> Metric:
        if isinstance(value, str):
            return self._text(value)
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if value is None or isinstance(value, int):
            return value
        raise TypeError(
            f"a metric is text, a number, a bool or None, got {type(value).__name__}"
        )

    def record(
        self, experiment: str, arm: str, item: str, metrics: Mapping[str, Metric]
    ) -> None:
        clean = {self._text(k, 64): self._metric(v) for k, v in metrics.items()}
        row = Row(
            self._text(experiment, 128),
            self._text(arm, 128),
            self._text(item, 128),
            clean,
        )
        self.rows.append(row)
        if self._results:
            with open(self._results, "a", encoding="utf-8") as results:
                results.write(_json_line(row) + "\n")

    def render(self) -> str:
        lines = [
            f"## {_cell(self.title)}",
            "",
            "| experiment | arm | item | metrics |",
            "| --- | --- | --- | --- |",
        ]
        for row in self.rows:
            metrics = "; ".join(f"{k}={v}" for k, v in row.metrics.items())
            cells = (row.experiment, row.arm, row.item, metrics)
            lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
        return "\n".join(lines)

    def finish(self, echo: Callable[[str], None]) -> None:
        """Append the table to ``$GITHUB_STEP_SUMMARY`` (absolute) and echo it
        too: the API does not return the job summary, the log it does. Each
        row then goes to the log in full, as a JSON line, because a table cell
        is capped and the results artifact may be out of the reader's reach."""
        text = self.render()
        if self._summary and os.path.isabs(self._summary):
            with open(self._summary, "a", encoding="utf-8") as summary:
                summary.write(text + "\n")
            echo(f"{self.title}: {len(self.rows)} row(s) written to the job summary")
        for line in text.splitlines():
            echo(line)
        for row in self.rows:
            echo("row " + _json_line(row))


def _json_line(row: Row) -> str:
    line: dict[str, object] = {
        "experiment": row.experiment,
        "arm": row.arm,
        "item": row.item,
        "metrics": row.metrics,
    }
    return json.dumps(line, sort_keys=True)
