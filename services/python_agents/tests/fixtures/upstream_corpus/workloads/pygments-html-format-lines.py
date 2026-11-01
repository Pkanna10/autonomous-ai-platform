"""OSS corpus benchmark: Pygments highlights a generated 230 KB Python module
(300 functions and classes with decorators, docstrings, f-strings, comments,
numbers in four bases, operators and multi-line strings; about 88,000
tokens) to HTML in five formatter configurations (CSS classes, inline
styles, table and inline line numbers with anchors and highlighted lines, a
full standalone page), as a documentation site rendering one source file
for several themes does.

Copied into the cloned repository as ``benchmarks/bench_pygments.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import io
import random
from pathlib import Path

import pygments
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pygments" / "__init__.py"
UNITS = 300
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pygments.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"pygments imported from {pygments.__file__}, not {PACKAGE_INIT}"
        )


def _unit(rng: random.Random, n: int) -> str:
    a, b = rng.choice(WORDS), rng.choice(WORDS)
    number = rng.choice(
        (
            str(rng.randint(0, 9999)),
            f"0x{rng.randrange(65536):x}",
            f"0o{rng.randrange(512):o}",
            f"0b{rng.randrange(256):b}",
            f"{rng.random():.6f}",
            "1e-9",
            "3_000_000j",
        )
    )
    if n % 5 == 0:
        return f'''
class {a.title()}{n}(Base, metaclass=Meta):
    """Doc for {a} {n}.

    Spans several lines; mentions ``{b}`` and {number}.
    """

    __slots__ = ("{a}", "_{b}")
    LIMIT: int = {number}  # a class attribute

    def __init__(self, {a}: int = {number}, *args, **kwargs) -> None:
        self.{a} = {a} if {a} is not None else -{number}
        self._{b} = [x ** 2 for x in range({n % 7 + 1}) if x % 2 == 0]

    @property
    def {b}(self) -> str:
        return f"{{self.{a}!r}}-{{self._{b}:>{n % 9 + 1}}}-{n}"

    async def run_{n}(self, items: list[str]) -> dict[str, int]:
        async with self.lock:
            return {{k: len(k) for k in items if k != "{b}"}}
'''
    return f'''
@decorator_{n % 4}(level={number}, name="{a}")
def {a}_{n}(arg: int, *, {b}: float = {number}, flag: bool = False) -> tuple[int, str]:
    """Return the {a} for {b} ({n})."""
    total = arg << 2 | 0x{n % 256:02x}  # bit tricks
    text = \'\'\'multi
line {b} {n}\'\'\'
    for index, value in enumerate(sorted(data_{n % 10}, key=lambda v: -v)):
        if value is None or value in (1, 2.5, "{b}", b"bytes", r"raw\\d+"):
            continue
        elif index % {n % 5 + 2} == 0:
            total += value // 3 - value % 7 ** 2
        else:
            total -= int(value) @ matrix if flag else 0
    try:
        return total, f"{{text.strip()}}: {{total:,.2f}} {{{b}!s}}"
    except (ValueError, KeyError) as error:
        raise RuntimeError("{a} failed") from error
    finally:
        del text
'''


def main() -> None:
    _checked()
    rng = random.Random(61)
    code = (
        '"""Generated module."""\nfrom __future__ import annotations\nimport os, sys\n'
        + "".join(_unit(rng, n) for n in range(UNITS))
    )
    lexer = PythonLexer()
    tokens = list(lexer.get_tokens(code))
    digest = hashlib.sha256()
    configurations = (
        {},
        {"noclasses": True, "cssclass": "code"},
        {
            "linenos": "table",
            "anchorlinenos": True,
            "lineanchors": "L",
            "hl_lines": [3, 40, 41, 900],
        },
        {"linenos": "inline", "wrapcode": True, "linespans": "line", "linenostep": 5},
        {"cssclass": "highlight-dark", "nowrap": True, "noclasses": False},
    )
    for options in configurations:
        out = io.StringIO()
        HtmlFormatter(**options).format(iter(tokens), out)
        digest.update(out.getvalue().encode())
    page = highlight(
        code, lexer, HtmlFormatter(full=True, title="bench", linenos="table")
    )
    digest.update(page.encode())
    print(
        f"pygments bytes={len(code)} tokens={len(tokens)} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
