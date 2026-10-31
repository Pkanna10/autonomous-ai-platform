"""OSS corpus benchmark: pycparser parses a generated 150-function C
translation unit of about 200 KB of pre-processed C (no ``cpp`` runs):
typedefs used as types inside function bodies, structs, unions, enums,
function pointers, casts to typedef names, sizeof, loops, switch, pointer
arithmetic and ternaries; then it regenerates C from the AST.

Copied into the cloned repository as ``benchmarks/bench_pycparser.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pycparser
from pycparser import c_generator, c_parser

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pycparser" / "__init__.py"
FUNCTIONS = 150
STRUCTS = 10
ALIASES = 40


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pycparser.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"pycparser imported from {pycparser.__file__}, not {PACKAGE_INIT}"
        )


def _function(rng: random.Random, n: int) -> str:
    a, b = rng.randint(1, 99), rng.randint(1, 99)
    s = n % STRUCTS
    alias = f"alias_{n % ALIASES}_t"
    return f"""
static int helper_{n}(const point_{s}_t *p, size_t count, callback_t cb);

int func_{n}(struct point_{s} *p, int count, const char *name, void *ctx) {{
    int total = {a};
    alias_{(n + 1) % ALIASES}_t scaled = (alias_{(n + 1) % ALIASES}_t){b};
    unsigned long mask = 0x{rng.randrange(1 << 16):x}UL;
    point_{s}_t local = {{ {a}, {b}, {{ 0.5, 1.5 }} }};
    const {alias} *view = (const {alias} *)ctx;
    callback_t cb = (callback_t)helper_{n};
    union value_u u;
    u.as_int = {a};
    for (int i = 0; i < count; i++) {{
        if ((p[i].x & mask) > {b} && name[i % 8] != '\\0') {{
            total += p[i].x * {a} - (p[i].y >> 2);
        }} else if (view != 0 && *view > ({alias}){a}) {{
            total -= (int)(p[i].y / ({b} + 1));
        }} else {{
            total = total > 0 ? total - 1 : (int)sizeof({alias});
        }}
    }}
    while (total > {a * 100}) {{ total /= 2; }}
    switch (total % 4) {{
        case 0: total += {b}; break;
        case 1: total ^= {a} + (int)scaled; break;
        case 2: total = cb(&local, (size_t)count, cb); break;
        default: total = total ? total - 1 : 0;
    }}
    do {{ total -= (int)u.as_int; }} while (total > {a * 50});
    return total + (int)sizeof(struct point_{s}) + (color_t)COLOR_{n % 3} + local.x;
}}

static int helper_{n}(const point_{s}_t *p, size_t count, callback_t cb) {{
    return (int)count + p->x + ((cb == 0) ? {a} : {b});
}}
"""


def _unit(rng: random.Random) -> str:
    head = [
        "typedef unsigned long size_t;",
        "typedef enum { COLOR_0, COLOR_1, COLOR_2 } color_t;",
        "union value_u { int as_int; double as_double; char bytes[8]; };",
    ]
    head += [
        f"struct point_{k} {{ int x; int y; double w[{k + 2}]; }};"
        for k in range(STRUCTS)
    ]
    head += [f"typedef struct point_{k} point_{k}_t;" for k in range(STRUCTS)]
    head += [
        f"typedef int alias_{k}_t;" if k % 2 else f"typedef double alias_{k}_t;"
        for k in range(ALIASES)
    ]
    head.append("typedef int (*callback_t)(const point_0_t *, size_t, void *);")
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
