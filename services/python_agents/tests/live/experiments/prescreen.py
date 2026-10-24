"""E8b: do sandbox timings rank like local ones? (pure parts; live, CI only).

Three synthetic, self-contained dedup variants (no user code) time
themselves with ``time.perf_counter`` and print one JSON line. They run in
Anthropic's code execution container, (a) a fresh container per variant and
(b) one container reused for all three, and locally in the CI runner
(``[sys.executable, "-I", script]``, argv only, a timeout). Pass criteria,
recorded and never asserted: the container ranks the variants as the local
run does, and every variant's coefficient of variation in the container is
under ``CV_LIMIT``.

Docs relied on (platform.claude.com/docs/en/agents-and-tools/tool-use/
code-execution-tool, read 2026-10-23): the latest version is
``code_execution_20260521`` and "None of the three tool versions requires an
``anthropic-beta`` header" (SDK 1.17 has its type in the beta namespace the
harness uses); a response's top-level ``container`` has the ``id`` that the
``container`` request parameter reuses ("Each request runs in a new
container unless you pass an earlier response's container ID back");
results are ``bash_code_execution_tool_result`` with ``stdout``,
``stderr`` and ``return_code``; 1 CPU, x86_64, Python 3.11, no network;
usage reports ``server_tool_use.code_execution_requests`` (no container
time); execution time has a 5-minute minimum, 1,550 free hours a month,
then $0.05 an hour per container; data is retained up to 30 days.

Assumptions in ``ALLOWANCE`` (code execution has no documented bound):
the 10-pass server loop, at most ``RESULT_TOKENS`` of tool results (the
created file echoed, the printed line, a few extra commands) and one
container hour as the fee.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .bounds import SERVER_LOOP_PASSES, Json, ToolAllowance

MODEL: Final = "claude-haiku-5-5"
TOOL: Final = {"type": "code_execution_20260521", "name": "code_execution"}
MAX_TOKENS: Final = 2_048
RESULT_TOKENS: Final = 20_000  # assumption
CONTAINER_HOUR_USD: Final = 0.05
ALLOWANCE: Final = ToolAllowance(SERVER_LOOP_PASSES, RESULT_TOKENS, CONTAINER_HOUR_USD)
MIN_CONTAINER_HOURS: Final = 5 / 60  # the documented 5-minute minimum
CV_LIMIT: Final = 0.05
LOCAL_TIMEOUT_S: Final = 300.0
STDOUT_LIMIT: Final = 64 * 1024
VARIANTS: Final = ("list_membership", "seen_set", "dict_fromkeys")
MODES: Final = ("fresh", "reused")
_BODIES: Final[Mapping[str, str]] = {
    "list_membership": (
        "    out = []\n    for x in items:\n        if x not in out:\n"
        "            out.append(x)\n    return out\n"
    ),
    "seen_set": (
        "    seen = set()\n    out = []\n    for x in items:\n"
        "        if x not in seen:\n            seen.add(x)\n"
        "            out.append(x)\n    return out\n"
    ),
    "dict_fromkeys": "    return list(dict.fromkeys(items))\n",
}
_INNER: Final[Mapping[str, int]] = {
    "list_membership": 1,
    "seen_set": 20,
    "dict_fromkeys": 20,
}
_TEMPLATE: Final = """import hashlib
import json
import time

N, UNIQUE, REPEATS, INNER = {n}, {unique}, {repeats}, {inner}


def dedup(items):
{body}

def main():
    with open(__file__, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    data = [(i * 7919) % UNIQUE for i in range(N)]
    expected = list(dict.fromkeys(data))
    dedup(data)  # untimed warm-up
    times = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        for _ in range(INNER):
            result = dedup(data)
        times.append((time.perf_counter() - start) / INNER)
    line = {{"variant": "{variant}", "times": times, "ok": result == expected}}
    line["sha256"] = digest
    print(json.dumps(line))


main()
"""
_CONTAINER_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Workload:
    """``n`` items with ``unique`` distinct values (7919 is prime, so the
    residues cycle through all of them), each variant timed ``repeats``
    times; list membership is O(n * unique)."""

    n: int = 10_000
    unique: int = 2_000
    repeats: int = 7

    def __post_init__(self) -> None:
        if not (2 <= self.repeats <= 50 and 1 <= self.unique <= self.n <= 10**6):
            raise ValueError(f"bad workload {self}")


DEFAULT_WORKLOAD: Final = Workload()


def script(variant: str, workload: Workload | None = None) -> str:
    """The variant's self-timing script; the same text on every call."""
    workload = workload or DEFAULT_WORKLOAD
    return _TEMPLATE.format(
        n=workload.n,
        unique=workload.unique,
        repeats=workload.repeats,
        inner=_INNER[variant],
        body=_BODIES[variant],
        variant=variant,
    )


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Timing:
    variant: str
    times: tuple[float, ...]
    ok: bool
    sha256: str


def parse_timing(stdout: str, variant: str, repeats: int) -> Timing | None:
    """The last line of ``stdout`` that is ``variant``'s well-formed result
    (``repeats`` finite positive times), or ``None``. Output is untrusted."""
    for line in reversed(stdout[-STDOUT_LIMIT:].splitlines()):
        try:
            loaded: object = json.loads(line)
        except ValueError:
            continue
        if not isinstance(loaded, dict) or loaded.get("variant") != variant:
            continue
        times, ok, sha = loaded.get("times"), loaded.get("ok"), loaded.get("sha256")
        if not isinstance(times, list) or len(times) != repeats:
            continue
        if not all(_positive(t) for t in times) or not isinstance(ok, bool):
            continue
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha):
            return Timing(variant, tuple(float(t) for t in times), ok, sha)
    return None


def _positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def write_scripts(directory: Path, workload: Workload | None = None) -> dict[str, Path]:
    """Each variant's script as ``<variant>.py`` in a new file under an
    absolute, existing, real directory."""
    workload = workload or DEFAULT_WORKLOAD
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"{directory} is not an absolute real directory")
    paths = {}
    for variant in VARIANTS:
        path = directory / f"{variant}.py"
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(script(variant, workload))
        paths[variant] = path
    return paths


def run_local(
    path: Path,
    *,
    timeout_s: float = LOCAL_TIMEOUT_S,
    runner: Runner = subprocess.run,
) -> str:
    """Run one written script with this interpreter in isolated mode: argv
    only, no shell, an empty environment, a timeout; its stdout."""
    if path.name not in {f"{v}.py" for v in VARIANTS} or not path.is_absolute():
        raise ValueError(f"{path} is not a variant script")
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path} is not a regular file")
    done = runner(
        [sys.executable, "-I", str(path)],
        cwd=path.parent,
        env={},
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    return str(done.stdout)


def cv(times: Sequence[float]) -> float:
    """The sample coefficient of variation (stdev / mean)."""
    return statistics.stdev(times) / statistics.fmean(times)


def ranking(timings: Mapping[str, Sequence[float]]) -> tuple[str, ...]:
    """Variants from fastest to slowest by median time (ties by name)."""
    return tuple(sorted(timings, key=lambda v: (statistics.median(timings[v]), v)))


def compare(
    container: Mapping[str, Sequence[float]], local: Mapping[str, Sequence[float]]
) -> dict[str, str | float | bool | None]:
    """The recorded verdicts; ``None`` where a side lacks a variant."""
    whole = set(container) == set(local) == set(VARIANTS)
    worst = max((cv(t) for t in container.values()), default=None)
    return {
        "container_ranking": " < ".join(ranking(container)),
        "local_ranking": " < ".join(ranking(local)),
        "same_ranking": ranking(container) == ranking(local) if whole else None,
        "container_max_cv": worst,
        "local_max_cv": max((cv(t) for t in local.values()), default=None),
        "cv_pass": worst < CV_LIMIT if whole and worst is not None else None,
    }


def container_body(variant: str, text: str, container: str | None = None) -> Json:
    """Ask for the script to be written unchanged and run once."""
    path = f"/tmp/e8b/{variant}.py"  # noqa: S108 - inside Anthropic's container
    prompt = (
        "This is a synthetic benchmark script with no user code. Create the "
        f"file {path} with exactly the content between the markers, unchanged, "
        f"then run `python3 {path}` once and reply with only the line it "
        f"printed.\n<<<SCRIPT\n{text}SCRIPT>>>"
    )
    body: Json = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "tools": [dict(TOOL)],
        "messages": [{"role": "user", "content": prompt}],
    }
    if container is not None:
        if not _CONTAINER_ID.fullmatch(container):
            raise ValueError("a container id is letters, digits, _ and -")
        body["container"] = container
    return body


def stdouts(blocks: Iterable[Json]) -> list[str]:
    """Every code execution stdout in a response, in order."""
    found = []
    for block in blocks:
        result = block.get("content")
        if block.get("type") in (
            "bash_code_execution_tool_result",
            "code_execution_tool_result",
        ) and isinstance(result, Mapping):
            out = result.get("stdout")
            if isinstance(out, str):
                found.append(out)
    return found


def container_id(raw: object) -> str | None:
    found = raw.get("id") if isinstance(raw, Mapping) else None
    return found if isinstance(found, str) and _CONTAINER_ID.fullmatch(found) else None


def reported_hours(usage: Json) -> float | None:
    """Container time when the usage reports it (hours or seconds under a
    key naming a container or execution time), else ``None``."""
    stack: list[object] = [usage]
    while stack:
        node = stack.pop()
        if not isinstance(node, Mapping):
            continue
        for key, value in node.items():
            name = str(key).lower()
            timed = "container" in name or "execution_time" in name
            if timed and _positive(value) and ("hour" in name or "second" in name):
                assert isinstance(value, (int, float))
                return value / 3600 if "second" in name else float(value)
            stack.append(value)
    return None
