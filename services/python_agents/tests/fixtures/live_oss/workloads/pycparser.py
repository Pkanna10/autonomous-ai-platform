"""OSS corpus benchmark: pycparser parses a generated 350-function C
translation unit (structs, typedefs, enums, loops, switch, pointer
arithmetic, casts) and regenerates C from the AST.

Copied into the cloned repository as ``benchmarks/bench_pycparser.py``. The
source is pre-processed already (no ``cpp`` runs). Deterministic: a fixed
seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pycparser
from pycparser import c_generator, c_parser

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pycparser" / "__init__.py"
FUNCTIONS = 350


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pycparser.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"pycparser imported from {pycparser.__file__}, not {PACKAGE_INIT}"
        )


def _function(rng: random.Random, n: int) -> str:
    a, b = rng.randint(1, 99), rng.randint(1, 99)
    return f"""
int func_{n}(struct point_{n % 10} *p, int count, const char *name) {{
    int total = {a};
    unsigned long mask = 0x{rng.randrange(1 << 16):x}UL;
    for (int i = 0; i < count; i++) {{
        if ((p[i].x & mask) > {b} && name[i % 8] != '\\0') {{
            total += p[i].x * {a} - (p[i].y >> 2);
        }} else {{
            total -= (int)(p[i].y / ({b} + 1));
        }}
    }}
    while (total > {a * 100}) {{ total /= 2; }}
    switch (total % 4) {{
        case 0: total += {b}; break;
        case 1: total ^= {a}; break;
        default: total = total ? total - 1 : 0;
    }}
    return total + sizeof(struct point_{n % 10}) + (color_t)COLOR_{n % 3};
}}
"""


def _unit(rng: random.Random) -> str:
    head = ["typedef enum { COLOR_0, COLOR_1, COLOR_2 } color_t;"]
    head += [
        f"struct point_{k} {{ int x; int y; double w[{k + 1}]; }};" for k in range(10)
    ]
    head += [f"typedef struct point_{k} point_{k}_t;" for k in range(10)]
    return "\n".join(head) + "".join(_function(rng, n) for n in range(FUNCTIONS))


def main() -> None:
    _checked()
    text = _unit(random.Random(37))
    ast = c_parser.CParser().parse(text, filename="<bench>")
    regenerated = c_generator.CGenerator().visit(ast)
    digest = hashlib.sha256(regenerated.encode()).hexdigest()
    print(f"pycparser functions={FUNCTIONS} nodes={len(ast.ext)} sha256={digest}")


if __name__ == "__main__":
    main()
