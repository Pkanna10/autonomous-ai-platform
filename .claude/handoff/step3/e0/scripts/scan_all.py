import sys
from pathlib import Path
from autonomous_ai_agents.optimization import anticheat as ac
root = Path(sys.argv[1])
for lib in sys.argv[2:]:
    repo = root / lib
    for f in sorted(repo.rglob("*.py")):
        if ".git" in f.parts:
            continue
        p = ac._spawn_problem(f.read_bytes())
        if p:
            prot = ac.check_path(f.relative_to(repo).as_posix())
            print(f"{lib}: {f.relative_to(repo)}: {p}  [protected={prot is not None}]")
