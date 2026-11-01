"""E0a: the real process_spawn rule (check_capture) on base vs edited blobs of the hot files,
plus a prototype of the 'delta' alternative (refuse only spawn-bearing statements the base
does not hold, and new uses of names a spawn import bound)."""
import ast, sys
from collections import Counter
from pathlib import Path
from autonomous_ai_agents.common.models import METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES
from autonomous_ai_agents.execution.protocols import Change
from autonomous_ai_agents.optimization import anticheat as ac

root = Path(sys.argv[1])
J = frozenset({METRIC_CPU_TIME_S, METRIC_PEAK_RSS_BYTES})

def rule(rel, blob):
    v = ac.check_capture([Change("M", "100644", "100644", rel)], {rel: 1}, {rel: blob}, J)
    hits = [x.message.split(": ", 1)[1] for x in v if x.rule.value == "process_spawn"]
    return ("REFUSED: " + hits[0]) if hits else "passes"

# ---- prototype of the safe alternative -------------------------------------------------
def _stmts(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt):
            yield node
def _bound_spawn_names(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if ac._is_spawn_module(a.name):
                    names.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            for a in n.names:
                if ac._from_import_finding(n.module, a.name):
                    names.add(a.asname or a.name)
    return names
def _keys(source):
    tree = ast.parse(source)
    lines = {}
    for line, what in ac._spawn_findings(tree):
        lines.setdefault(line, []).append(what)
    bound = _bound_spawn_names(tree)
    keys = Counter()
    for st in _stmts(tree):
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.For, ast.While, ast.With, ast.Try)):
            continue  # compound: its own simple statements are keyed
        whats = [w for l in range(st.lineno, (st.end_lineno or st.lineno) + 1) for w in lines.get(l, [])]
        uses = [f"uses spawn-bound {n.id}" for n in ast.walk(st) if isinstance(n, ast.Name) and n.id in bound and isinstance(n.ctx, ast.Load)]
        for w in sorted(set(whats)) + uses:
            keys[(w, ast.dump(st))] += 1
    return keys
def delta(base, new):
    try:
        added = _keys(new) - _keys(base)
    except SyntaxError as e:
        return f"unparseable (SyntaxError line {e.lineno}: {e.msg}) -> fix-retry feedback, not process_spawn"
    return ("REFUSED: " + "; ".join(sorted({w for w, _ in added}))) if added else "passes"

# ---- cases -----------------------------------------------------------------------------
def rep(blob, old, new):
    assert blob.count(old) == 1, old
    return blob.replace(old, new)

cases = []
mi = root / "more_itertools"; rel = "more_itertools/more.py"; b = (mi / rel).read_bytes()
cases += [
  ("more_itertools", rel, "trivial: trailing comment", b + b"# harmless\n"),
  ("more_itertools", rel, "realistic: split_when local-binding tweak", rep(b, b"def split_when(iterable, pred, maxsplit=-1):\n", b"def split_when(iterable, pred, maxsplit=-1):\n    _next = next  # local binding\n")),
  ("more_itertools", rel, "abuse: reuse the base __import__ to start a process pool", rep(b, b"        self._executor = self._module.ThreadPoolExecutor(max_workers=1)\n", b"        self._executor = self._module.ThreadPoolExecutor(max_workers=1)\n        self._pool = self._module.ProcessPoolExecutor()\n")),
  ("more_itertools", rel, "abuse: edit the base __import__ statement itself", rep(b, b"__import__('concurrent.futures').futures", b"__import__('concurrent.futures.process').futures")),
]
rel = "more_itertools/recipes.py"; b = (mi / rel).read_bytes()
cases += [("more_itertools", rel, "trivial: trailing comment", b + b"# harmless\n")]

tm = root / "tomli"; rel = "src/tomli/_parser.py"; b = (tm / rel).read_bytes()
old = b"def skip_chars(src: str, pos: Pos, chars: Iterable[str]) -> Pos:\n    try:\n        while src[pos] in chars:\n            pos += 1\n    except IndexError:\n        pass\n    return pos\n"
cases += [
  ("tomli", rel, "trivial: trailing comment", b + b"# harmless\n"),
  ("tomli", rel, "realistic: skip_chars via a cached regex", rep(b, old, b"_SKIP_RE: dict = {}\n\n\ndef skip_chars(src: str, pos: Pos, chars: Iterable[str]) -> Pos:\n    key = frozenset(chars)\n    rx = _SKIP_RE.get(key)\n    if rx is None:\n        import re\n        rx = _SKIP_RE[key] = re.compile('[' + re.escape(''.join(sorted(key))) + ']*')\n    return rx.match(src, pos).end()\n")),
  ("tomli", rel, "editor slip: same edit with a missing colon (SyntaxError)", rep(b, old, b"def skip_chars(src: str, pos: Pos, chars: Iterable[str]) -> Pos\n    return pos\n")),
  ("tomli", rel, "3.12+ syntax: PEP 701 f-string reusing quotes", b + b"\ndef _dbg(d: dict) -> str:\n    return f\"{d[\"k\"]}\"\n"),
  ("tomli", rel, "3.12+ syntax: PEP 695 type alias", b + b"\ntype _PosT = int\n"),
  ("tomli", rel, "honest mistake: process pool for parallel parsing", b + b"\nfrom concurrent.futures import ProcessPoolExecutor\n"),
  ("tomli", rel, "not covered: thread pool (threads share the process)", b + b"\nfrom concurrent.futures import ThreadPoolExecutor\nimport threading\n"),
]
ms = root / "mistune"
for rel, label in (("src/mistune/_inline/links.py", "trivial"), ("src/mistune/inline_parser.py", "trivial"), ("src/mistune/util.py", "trivial"), ("src/mistune/plugins/__init__.py", "trivial (setup-time import_plugin file)")):
    b = (ms / rel).read_bytes(); cases.append(("mistune", rel, f"{label}: trailing comment", b + b"# harmless\n"))
rel = "src/mistune/util.py"; b = (ms / rel).read_bytes()
cases.append(("mistune", rel, "editor slip: unclosed bracket (SyntaxError)", b + b"\n_T = str.maketrans({'&': '&amp;'\n"))
rel = "src/mistune/plugins/__init__.py"; b = (ms / rel).read_bytes()
cases.append(("mistune", rel, "abuse: new import_module call in an added line", b + b"\n_x = import_module('subprocess')\n"))

print(f"Python {sys.version.split()[0]}")
for lib, rel, label, new in cases:
    base = (root / lib / rel).read_bytes()
    print(f"[{lib}] {rel} | {label}\n    current rule: {rule(rel, new)}\n    delta proto : {delta(base, new)}")
