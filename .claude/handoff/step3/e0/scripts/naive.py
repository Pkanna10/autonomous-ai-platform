"""Security trade-off: a naive added-lines-only scan vs the delta prototype on a file whose
base already imports subprocess (synthetic, no third-party code)."""
import ast, sys, textwrap
sys.path.insert(0, sys.argv[1])
from autonomous_ai_agents.optimization import anticheat as ac
from variants import delta  # noqa: E402  (the prototype; its module body needs argv[1] = clones root)
base = b"import subprocess\n\ndef version():\n    return subprocess.check_output(['git', '--version'])\n\ndef hot(xs):\n    return sorted(xs)\n"
new = base.replace(b"    return sorted(xs)\n", b"    subprocess.Popen(['python', '-c', 'work()'])\n    return sorted(xs)\n")
added = ac._added_lines(base, new)
naive_src = textwrap.dedent("\n".join(added))
naive = ac._spawn_problem(naive_src.encode())
print("added lines:", added)
print("naive added-lines-only AST scan:", naive or "passes  <-- the reused import spawns unseen")
print("current whole-blob rule:", ac._spawn_problem(new))
print("delta prototype:", delta(base, new))
