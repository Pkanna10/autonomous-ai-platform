"""OSS corpus benchmark: pyparsing parses 1,800 generated structured log
lines with packrat parsing enabled (as the pyparsing documentation
recommends for grammars with many alternatives) and a grammar rich in named
results: a combined timestamp, a level, a logger, a request id, a dictionary
of key=value fields, repeated tags, an optional combined duration and an
optional message. Each result is then handled the way a log pipeline does:
copied, read as a dict and as a list, merged with the previous result, and
every third one pickled and restored.

Copied into the cloned repository as ``benchmarks/bench_pyparsing.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import pickle
import random
from pathlib import Path

import pyparsing as pp

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "pyparsing" / "__init__.py"
LINES = 1800
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(pp.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"pyparsing imported from {pp.__file__}, not {PACKAGE_INIT}")


def _grammar() -> pp.ParserElement:
    integer = pp.Word(pp.nums)
    date = integer + "-" + integer + "-" + integer
    clock = integer + ":" + integer + ":" + integer + pp.Optional("." + integer)
    timestamp = pp.Combine(date + "T" + clock + "Z")("timestamp")
    level = pp.one_of(LEVELS)("level")
    logger = pp.Word(pp.alphas, pp.alphanums + "._")("logger")
    request = pp.Suppress("[") + pp.Word(pp.hexnums)("request_id") + pp.Suppress("]")
    key = pp.Word(pp.alphas, pp.alphanums + "_")
    decimal = pp.Combine(pp.Optional("-") + integer + "." + integer)
    value = pp.QuotedString('"') | decimal | integer | pp.Word(pp.alphanums + "_-./")
    pair = pp.Group(key + pp.Suppress("=") + value)
    fields = pp.Dict(pp.OneOrMore(pair))("fields")
    tag = (pp.Suppress("#") + pp.Word(pp.alphanums + "_"))("tags*")
    duration = (
        pp.Suppress("took")
        + pp.Combine(integer + pp.Optional("." + integer))("duration")
        + pp.Suppress("ms")
    )
    message = pp.Suppress("-") + pp.rest_of_line("message")
    return (
        timestamp
        + level
        + logger
        + pp.Optional(request)
        + fields
        + pp.ZeroOrMore(tag)
        + pp.Optional(duration)
        + pp.Optional(message)
    )


def _line(rng: random.Random, n: int) -> str:
    stamp = f"2026-10-{n % 28 + 1:02d}T{n % 24:02d}:{n % 60:02d}:{(n * 7) % 60:02d}.{n % 1000:03d}Z"
    parts = [stamp, rng.choice(LEVELS), f"{rng.choice(WORDS)}.{rng.choice(WORDS)}"]
    if n % 3:
        parts.append(f"[{rng.randrange(1 << 32):08x}]")
    for k in range(rng.randint(3, 8)):
        value = rng.choice(
            (
                str(rng.randint(0, 9999)),
                f"{rng.random() * 100:.3f}",
                f'"quoted {k}"',
                f"path/{rng.choice(WORDS)}-{k}",
            )
        )
        parts.append(f"{rng.choice(WORDS)}_{k}={value}")
    parts += [f"#{rng.choice(WORDS)}" for _ in range(rng.randint(0, 3))]
    if n % 2:
        parts.append(f"took {rng.random() * 50:.2f} ms")
    if n % 4 == 0:
        parts.append(f"- {rng.choice(WORDS)} finished with {n % 7} warnings")
    return " ".join(parts)


def main() -> None:
    _checked()
    pp.ParserElement.enable_packrat()
    rng = random.Random(107)
    grammar = _grammar()
    digest = hashlib.sha256()
    previous = None
    pickled = 0
    for n in range(LINES):
        result = grammar.parse_string(_line(rng, n), parse_all=True)
        copied = result.copy()
        copied["seen"] = n
        digest.update(repr(copied.as_dict()).encode())
        digest.update(repr(result.as_list()).encode())
        digest.update(
            f"{result.level} {result.get('request_id', '-')} {list(result.tags)} {len(result.fields)}".encode()
        )
        if previous is not None and n % 5 == 0:
            merged = previous + result
            digest.update(f"{len(merged)} {merged.level} {merged.logger}".encode())
        if n % 3 == 0:
            restored = pickle.loads(pickle.dumps(result))
            assert restored.as_dict() == result.as_dict()
            digest.update(repr(restored.fields.as_dict()).encode())
            pickled += 1
        previous = result
    print(f"pyparsing lines={LINES} pickled={pickled} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
