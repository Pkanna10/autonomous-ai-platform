"""OSS corpus benchmark: pyparsing parses 1,500 generated
arithmetic expressions with an ``infix_notation`` grammar (five precedence
levels, functions, variables), and a generated key-value config file.

Copied into the cloned repository as ``benchmarks/bench_pyparsing.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pyparsing as pp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pyparsing" / "__init__.py"
EXPRESSIONS = 1500


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pp.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"pyparsing imported from {pp.__file__}, not {PACKAGE_INIT}")


def _grammar() -> pp.ParserElement:
    number = pp.pyparsing_common.number
    name = pp.Word(pp.alphas, pp.alphanums + "_")
    expr = pp.Forward()
    call = pp.Group(
        name + pp.Suppress("(") + pp.Optional(pp.DelimitedList(expr)) + pp.Suppress(")")
    )
    operand = call | number | name
    expr <<= pp.infix_notation(
        operand,
        [
            (pp.one_of("- +"), 1, pp.OpAssoc.RIGHT),
            ("^", 2, pp.OpAssoc.RIGHT),
            (pp.one_of("* / %"), 2, pp.OpAssoc.LEFT),
            (pp.one_of("+ -"), 2, pp.OpAssoc.LEFT),
            (pp.one_of("< > <= >= == !="), 2, pp.OpAssoc.LEFT),
        ],
    )
    return expr


def _expression(rng: random.Random, depth: int = 0) -> str:
    if depth > 2 or rng.random() < 0.3:
        return rng.choice(
            (str(rng.randint(0, 99)), f"{rng.random() * 10:.2f}", "x", "rate")
        )
    op = rng.choice(("+", "-", "*", "/", "^", "<", "%"))
    left, right = _expression(rng, depth + 1), _expression(rng, depth + 1)
    if rng.random() < 0.2:
        return f"max({left}, {right})"
    return f"({left} {op} {right})" if rng.random() < 0.5 else f"{left} {op} {right}"


def _config(rng: random.Random) -> str:
    lines = []
    for section in range(60):
        lines.append(f"[section_{section}]")
        for key in range(12):
            value = rng.choice(
                (str(rng.randint(0, 9999)), f'"text {key}"', "true", "3.25")
            )
            lines.append(f"key_{key} = {value}")
    return "\n".join(lines) + "\n"


def main() -> None:
    _checked()
    rng = random.Random(23)
    grammar = _grammar()
    digest = hashlib.sha256()
    for _ in range(EXPRESSIONS):
        result = grammar.parse_string(_expression(rng), parse_all=True)
        digest.update(repr(result.as_list()).encode())
    value = (
        pp.Regex(r"\d+\.\d+")
        | pp.Word(pp.nums)
        | pp.QuotedString('"')
        | pp.Keyword("true")
    )
    entry = pp.Group(pp.Word(pp.alphanums + "_") + pp.Suppress("=") + value)
    section = pp.Group(
        pp.Suppress("[")
        + pp.Word(pp.alphanums + "_")
        + pp.Suppress("]")
        + pp.Group(entry[...])
    )
    config = section[...]
    parsed = config.parse_string(_config(rng), parse_all=True)
    digest.update(repr(parsed.as_list()).encode())
    print(f"pyparsing expressions={EXPRESSIONS} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
