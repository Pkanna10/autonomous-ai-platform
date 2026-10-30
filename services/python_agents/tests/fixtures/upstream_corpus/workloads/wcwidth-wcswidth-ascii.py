"""OSS corpus benchmark: wcwidth measures the terminal width of 45,000
generated lines of 20 to 90 characters (about 2.3 million characters) the
way a terminal UI or table renderer does on every repaint: log lines, table
cells and prompts mixing ASCII with accented Latin (precomposed and
combining), CJK and fullwidth forms, emoji with variation selectors,
zero-width joiners, skin tones and flags, and a few control characters;
``wcswidth`` on every line, with a length limit on a sample, and
``wcwidth`` per character on 500 lines.

Copied into the cloned repository as ``benchmarks/bench_wcwidth.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import wcwidth

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "wcwidth" / "__init__.py"
LINES = 45000
ASCII = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;-_=/[]()|"
ZWJ = chr(0x200D)  # zero width joiner
VS16 = chr(0xFE0F)  # emoji presentation selector
COMBINING = (chr(0x0301), chr(0x0300), chr(0x0308), chr(0x030A))
LATIN = "àáâäçèéêëìíîïñòóôöùúûüýÿ" + "".join(f"e{c}" for c in COMBINING)
CJK = (
    "".join(chr(cp) for cp in range(0x4E00, 0x4E60))
    + "ＡＢＣ１２３"
    + "こんにちは"
    + "한국어"
)
EMOJI = (
    chr(0x1F600),  # grinning face
    chr(0x2764) + VS16,  # red heart with emoji presentation
    chr(0x1F468) + ZWJ + chr(0x1F469) + ZWJ + chr(0x1F467),  # family, joined
    chr(0x1F44D) + chr(0x1F3FD),  # thumbs up with a skin tone
    chr(0x1F1EB) + chr(0x1F1F7),  # a regional-indicator flag
    chr(0x2139) + VS16,  # information source, emoji presentation
    chr(0x1F3F3) + VS16 + ZWJ + chr(0x1F308),  # rainbow flag
    chr(0x231A),  # watch (wide by default)
)
CONTROLS = ("\t", "\x1b[0m", "\x07", "\x00")


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(wcwidth.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(
            f"wcwidth imported from {wcwidth.__file__}, not {PACKAGE_INIT}"
        )


def _line(rng: random.Random, n: int) -> str:
    length = rng.randint(20, 90)
    bucket = n % 100
    if bucket < 75:
        return "".join(rng.choice(ASCII) for _ in range(length))
    if bucket < 85:
        return "".join(rng.choice(ASCII if k % 3 else LATIN) for k in range(length))
    if bucket < 93:
        return "".join(rng.choice(CJK if k % 2 else ASCII) for k in range(length // 2))
    if bucket < 98:
        return " ".join(
            rng.choice(EMOJI) if k % 4 == 0 else rng.choice(ASCII) * 3
            for k in range(length // 4)
        )
    line = list(rng.choice(ASCII) for _ in range(length))
    line[rng.randrange(length)] = rng.choice(CONTROLS)
    return "".join(line)


def main() -> None:
    _checked()
    rng = random.Random(103)
    digest = hashlib.sha256()
    total = chars = negative = 0
    for n in range(LINES):
        line = _line(rng, n)
        chars += len(line)
        width = wcwidth.wcswidth(line)
        if n % 10 == 0:
            width = (width, wcwidth.wcswidth(line, n=min(len(line), 12)))
        if n % 90 == 0:
            width = (width, [wcwidth.wcwidth(ch) for ch in line])
        if isinstance(width, int):
            total += width
            negative += width < 0
        digest.update(repr(width).encode())
    print(
        f"wcwidth lines={LINES} chars={chars} total={total} negative={negative} sha256={digest.hexdigest()}"
    )


if __name__ == "__main__":
    main()
