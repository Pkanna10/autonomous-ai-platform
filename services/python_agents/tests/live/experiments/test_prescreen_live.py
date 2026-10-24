"""E8b: sandbox pre-screen of three synthetic dedup variants (live, CI only).

``fresh`` runs each variant in a new code execution container, ``reused``
runs all three in the container the first answer names; both then run the
same scripts locally (``prescreen.run_local``). One row per variant and a
summary row per mode go to ``$LIVE_RESULTS_PATH`` and the job summary; the
pass criteria (same ranking, CV under 5 %) are recorded, never asserted.
Each mode's cap is the sum of its three requests' worst cases
(``E8B_NEED_USD`` for both modes); the expected spend is a few cents on
Haiku 5.5.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from ..conftest import StartLive
from . import prescreen
from .harness import ExperimentClient
from .recorder import ExperimentRecorder, Metric
from .test_probes_live import answered, finish
from .web import blocks_of, run_cap

pytestmark = pytest.mark.live

_BOUND_CONTAINER = "c" * 128  # the longest id the body accepts, for the bound


def mode_cap(mode: str) -> float:
    reuse = _BOUND_CONTAINER if mode == "reused" else None
    return math.fsum(
        run_cap(
            prescreen.container_body(v, prescreen.script(v), reuse),
            prescreen.ALLOWANCE,
        )
        for v in prescreen.VARIANTS
    )


E8B_NEED_USD = math.fsum(mode_cap(mode) for mode in prescreen.MODES)


@pytest.fixture(scope="module")
def e8b_recorder(pytestconfig: pytest.Config) -> Iterator[ExperimentRecorder]:
    recorder = ExperimentRecorder("E8b sandbox pre-screen", os.environ)
    yield recorder
    finish(recorder, pytestconfig)


@pytest.mark.parametrize("mode", prescreen.MODES)
def test_e8b_prescreen(
    mode: str, live: StartLive, tmp_path: Path, e8b_recorder: ExperimentRecorder
) -> None:
    run = live(mode_cap(mode))
    workload = prescreen.DEFAULT_WORKLOAD
    container: str | None = None
    containers: list[str] = []
    timings: dict[str, tuple[float, ...]] = {}
    hours: list[float] = []
    with ExperimentClient(run, recorder=e8b_recorder) as client:
        for variant in prescreen.VARIANTS:
            text = prescreen.script(variant, workload)
            body = prescreen.container_body(variant, text, container)
            answer = client.messages(body, allowance=prescreen.ALLOWANCE)
            assert answered(answer), f"{variant}: {answer.error}"
            message = answer.message
            found, served, reported = None, None, None
            if message is not None:
                outs = prescreen.stdouts(blocks_of(message))
                candidates = (
                    prescreen.parse_timing(o, variant, workload.repeats) for o in outs
                )
                found = next((t for t in candidates if t is not None), None)
                served = prescreen.container_id(
                    message.container.model_dump() if message.container else None
                )
                reported = prescreen.reported_hours(message.usage.model_dump())
            if served is not None and served not in containers:
                containers.append(served)
            if mode == "reused" and container is None:
                container = served
            if found is not None:
                timings[variant] = found.times
            if reported is not None:
                hours.append(reported)
            metrics: dict[str, Metric] = {
                "outcome": answer.outcome,
                "error": answer.error,
                "cost_usd": answer.cost_usd,
                "estimate_usd": answer.estimate_usd,
                "container": served,
                "parsed": found is not None,
                "output_ok": found.ok if found else None,
                "script_intact": found.sha256 == prescreen.digest(text)
                if found
                else None,
                "median_s": sorted(found.times)[len(found.times) // 2]
                if found
                else None,
                "cv": prescreen.cv(found.times) if found else None,
                "reported_container_hours": reported,
            }
            e8b_recorder.record("E8b", mode, variant, metrics)
    local: dict[str, tuple[float, ...]] = {}
    for variant, path in prescreen.write_scripts(tmp_path, workload).items():
        parsed = prescreen.parse_timing(
            prescreen.run_local(path), variant, workload.repeats
        )
        if parsed is not None:
            local[variant] = parsed.times
    summary: dict[str, Metric] = {
        **prescreen.compare(timings, local),
        "containers": len(containers),
        "reused_one_container": len(containers) == 1 if mode == "reused" else None,
        "container_hours_floor": len(containers) * prescreen.MIN_CONTAINER_HOURS,
        "reported_container_hours": math.fsum(hours) if hours else None,
        "cost_usd": run.spent_usd,
    }
    e8b_recorder.record("E8b", mode, "summary", summary)
    run.note(f"E8b {mode}: ranking match {summary['same_ranking']}")
