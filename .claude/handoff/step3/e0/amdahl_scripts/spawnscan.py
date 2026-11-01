import sys
from pathlib import Path
from autonomous_ai_agents.optimization.anticheat import _spawn_problem
base = Path(sys.argv[1])
for line in open(sys.argv[2]):
    name, url, tag, commit, root = line.split()
    for p in sorted((base / name / root).rglob("*.py")):
        prob = _spawn_problem(p.read_bytes())
        if prob:
            print(f"{name}\t{p.relative_to(base / name)}\t{prob}")
