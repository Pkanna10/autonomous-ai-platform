"""OSS corpus v2 benchmark: parso parses 15 generated Python modules
(classes, decorators, nested functions, comprehensions, f-strings,
try/except, a few syntax errors), walks every tree, lists the syntax
errors and round-trips the code.

Copied into the cloned repository as ``benchmarks/bench_parso.py``.
Deterministic: a fixed seed, no clock, no network, no parso cache; prints
a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import parso

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "parso" / "__init__.py"
MODULES = 15
FUNCTIONS = 30


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(parso.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"parso imported from {parso.__file__}, not {PACKAGE_INIT}")


def _function(rng: random.Random, n: int) -> list[str]:
    broken = rng.random() < 0.05
    return [
        "@staticmethod" if n % 4 == 0 else f"# function {n}",
        f"def func_{n}(value, scale={rng.randint(1, 9)}, *rest, **options):",
        f'    """Function {n}: {rng.random():.6f}."""',
        f"    items = [x * scale for x in range(value) if x % {rng.randint(2, 7)}]",
        "    table = {k: v for k, v in zip(items, rest)}",
        "    try:",
        f"        result = sum(items) / (len(items) or 1) + {rng.randint(0, 99)}",
        "    except (ZeroDivisionError, TypeError) as error:",
        "        result = None",
        "    while value > 0:",
        "        value -= scale",
        "        if value % 3 == 0 and not options:" + (" (" if broken else ""),
        "            break",
        f'    return f"{{result!r}}-{{len(table)}}-{n}", lambda y: y + scale',
        "",
    ]


def _module(rng: random.Random, index: int) -> str:
    lines = [f'"""Generated module {index}."""', "import os, sys", ""]
    lines += [f"class Model{index}:", "    def method(self, a, b=2):"]
    lines += ["        return [a + b for _ in range(3)]", ""]
    for n in range(FUNCTIONS):
        lines += _function(rng, n)
    return "\n".join(lines) + "\n"


def _count(node: object) -> int:
    children = getattr(node, "children", None)
    return 1 + (sum(_count(child) for child in children) if children else 0)


def main() -> None:
    _checked()
    rng = random.Random(47)
    grammar = parso.load_grammar(version="3.12")
    digest = hashlib.sha256()
    errors = 0
    for index in range(MODULES):
        code = _module(rng, index)
        module = grammar.parse(code, cache=False)
        found = [(e.start_pos, e.code, e.message) for e in grammar.iter_errors(module)]
        errors += len(found)
        if module.get_code() != code:
            raise SystemExit(f"module {index} did not round-trip")
        digest.update(f"{_count(module)}:{found}".encode())
        for name in module.iter_funcdefs():
            digest.update(name.name.value.encode())
    print(f"parso modules={MODULES} errors={errors} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
