"""E0a: run the real process_spawn rule over every module of the pinned libraries.

For each .py under module_root: _spawn_problem(base) and check_capture() on a
modified-file Change whose new blob is base + a trivial harmless edit (a
trailing comment line). Reads the untrusted sources as data only.
"""
import sys
from pathlib import Path

from autonomous_ai_agents.common.models import METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization import anticheat as ac

root = Path(sys.argv[1])
libs = {
    "more_itertools": "more_itertools",
    "tomli": "src/tomli",
    "mistune": "src/mistune",
    "pyparsing": "pyparsing",
}
judged = frozenset({METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES})
for lib, mod in libs.items():
    repo = root / lib
    files = sorted((repo / mod).rglob("*.py"))
    flagged = 0
    print(f"== {lib} ({len(files)} modules under {mod})")
    for f in files:
        rel = f.relative_to(repo).as_posix()
        base = f.read_bytes()
        problem = ac._spawn_problem(base)
        edited = base + (b"" if base.endswith(b"\n") else b"\n") + b"# trivial harmless edit\n"
        v = ac.check_capture(
            [Change("M", "100644", "100644", rel)], {rel: 1}, {rel: edited}, judged
        )
        refused = [x for x in v if x.rule.value == "process_spawn"]
        if problem or refused:
            flagged += 1
            print(f"  FLAG {rel}: base={problem!r}; trivial-edit refused={bool(refused)}")
            if refused:
                print(f"       msg: {refused[0].message}")
    print(f"  -> {flagged}/{len(files)} modules flagged at base")
