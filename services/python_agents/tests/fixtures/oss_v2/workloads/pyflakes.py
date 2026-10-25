"""OSS corpus v2 benchmark: pyflakes checks 40 generated Python modules
(imports used and unused, classes, nested functions, comprehensions,
undefined and redefined names, f-strings, try/except, ``__all__``).

Copied into the cloned repository as ``benchmarks/bench_pyflakes.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import pyflakes

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pyflakes" / "__init__.py"
MODULES = 40
FUNCTIONS = 40
IMPORTS = ("os", "sys", "re", "json", "math", "itertools", "functools", "typing")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pyflakes.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"pyflakes imported from {pyflakes.__file__}, not {PACKAGE_INIT}"
        )


class _Lines:
    """A write-only stream the reporter writes its messages to."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)


def _function(rng: random.Random, n: int) -> list[str]:
    a, b = f"arg{n}", f"other{n}"
    name = rng.choice((a, b, "missing_name", f"local{n}"))
    return [
        f"def func_{n}({a}, {b}=None, *rest, **options):",
        f'    """Function {n}."""',
        f"    local{n} = [x * {n} for x in range({a}) if x % {rng.randint(2, 9)}]",
        f"    total = sum(v for v in local{n})",
        "    try:",
        f"        value = options[{b!r}]",
        "    except KeyError as error:",
        "        value = None",
        f"    def inner_{n}(item):",
        f"        return item + total + len(rest) + {name}",
        f"    mapping = {{k: inner_{n}(k) for k in local{n}}}",
        '    label = f"{total}-{value}-{len(mapping)}"',
        "    if label:",
        f"        unused_{n} = {rng.randint(0, 99)}",
        "    return mapping, label",
        "",
    ]


def _module(rng: random.Random, index: int) -> str:
    lines = [f'"""Generated module {index}."""', ""]
    imported = rng.sample(IMPORTS, 5)
    lines += [f"import {name}" for name in imported]
    lines += ["from collections import OrderedDict, defaultdict", ""]
    lines += [f"__all__ = ['func_0', 'Model{index}', 'not_defined_{index}']", ""]
    lines += [
        f"class Model{index}:",
        "    counter = defaultdict(int)",
        "    def method(self, value):",
        f"        return {imported[0]}.__name__ + str(value) + str(self.counter)",
        "",
    ]
    for n in range(FUNCTIONS):
        lines += _function(rng, n)
    lines += [f"def func_{rng.randrange(FUNCTIONS)}():", "    return OrderedDict()", ""]
    return "\n".join(lines)


def main() -> None:
    _checked()
    from pyflakes import api, reporter

    rng = random.Random(41)
    digest = hashlib.sha256()
    warnings = 0
    for index in range(MODULES):
        out, err = _Lines(), _Lines()
        found = reporter.Reporter(out, err)
        warnings += api.check(_module(rng, index), f"mod{index}.py", found)
        digest.update("".join(out.parts + err.parts).encode())
    print(f"pyflakes modules={MODULES} warnings={warnings} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
