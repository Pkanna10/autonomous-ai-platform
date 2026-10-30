"""OSS corpus benchmark: soupsieve answers CSS selector queries over a
generated 9,000-element HTML page parsed once with BeautifulSoup and the
standard library parser, the way a scraper that extracts many fields from
one page does: twenty selectors (type selectors with and without classes,
child, sibling and descendant combinators, attribute tests, ``:nth-child``,
``:nth-of-type``, ``:has``, ``:not``, ``:-soup-contains``, a selector list
and ``*``) run three times each with ``select`` and ``select_one``, plus
``match``, ``filter`` and ``closest`` on samples.

Copied into the cloned repository as ``benchmarks/bench_soupsieve.py``.
Deterministic: a fixed seed, no clock, no network; prints a digest. Needs
``beautifulsoup4`` installed; the tree builder is ``html.parser``.
"""

from __future__ import annotations

import hashlib
import random
from pathlib import Path

import soupsieve as sv
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_INIT = ROOT / "soupsieve" / "__init__.py"
CARDS = 320
ROUNDS = 3
WORDS = ("engine", "trial", "judge", "verdict", "noise", "branch", "profile", "cache")
SELECTORS = (
    "div.card > h2",
    "ul li a[href^='https']",
    "table tr:nth-child(2n+1) td",
    "article p ~ p",
    "section > div.card:has(> p.summary)",
    "a:not([rel])",
    "*",
    "li:nth-of-type(3)",
    "div, span",
    "h2 + p",
    "[data-kind='hot']",
    "p:-soup-contains('engine')",
    "section article div.card ul li a",
    "span.tag:last-child",
    "td",
    "li",
    "h2",
    "p.summary",
    "table tbody tr td:first-child",
    "section article h1",
)


def _checked() -> None:
    """The library timed is exactly the checkout's package, never a copy."""
    if Path(sv.__file__).resolve() != PACKAGE_INIT:
        raise SystemExit(f"soupsieve imported from {sv.__file__}, not {PACKAGE_INIT}")


def _card(rng: random.Random, n: int) -> str:
    kind = rng.choice(("hot", "cold", "warm"))
    items = []
    for k in range(rng.randint(2, 5)):
        scheme = rng.choice(("https", "http"))
        rel = ' rel="nofollow"' if k % 3 == 0 else ""
        items.append(
            f'<li><a href="{scheme}://example.org/{rng.choice(WORDS)}/{k}"{rel}>'
            f'{rng.choice(WORDS)} {k}</a><span class="tag">{rng.choice(WORDS)}</span></li>'
        )
    rows = "".join(
        f"<tr><td>{r}</td><td>{rng.choice(WORDS)}</td><td>{rng.random():.3f}</td></tr>"
        for r in range(rng.randint(2, 4))
    )
    paragraphs = []
    for p in range(rng.randint(1, 3)):
        css = "summary" if p == 0 else "body"
        words = " ".join(rng.choice(WORDS) for _ in range(8))
        paragraphs.append(f'<p class="{css}">{words}</p>')
    return (
        f'<div class="card" id="card-{n}" data-kind="{kind}"><h2>{rng.choice(WORDS).title()} {n}</h2>'
        f"{''.join(paragraphs)}<ul>{''.join(items)}</ul><table><tbody>{rows}</tbody></table>"
        f'<span class="meta">{n % 7}</span></div>'
    )


def _page(rng: random.Random) -> str:
    sections = []
    for s in range(CARDS // 25):
        cards = "".join(_card(rng, s * 25 + c) for c in range(25))
        sections.append(
            f'<section id="s{s}"><article><h1>Section {s}</h1>{cards}</article></section>'
        )
    return f"<!doctype html><html><head><title>bench</title></head><body>{''.join(sections)}</body></html>"


def main() -> None:
    _checked()
    html = _page(random.Random(71))
    soup = BeautifulSoup(html, "html.parser")
    digest = hashlib.sha256()
    matches = 0
    for _ in range(ROUNDS):
        for selector in SELECTORS:
            found = sv.select(selector, soup)
            matches += len(found)
            first = sv.select_one(selector, soup)
            digest.update(
                f"{selector}: {len(found)} {[el.name for el in found[:5]]} "
                f"{first.get_text()[:30] if first is not None else None}\n".encode()
            )
    cards = sv.select("div.card", soup)
    hot = sum(1 for card in cards if sv.match("[data-kind='hot']", card))
    tagged = len(sv.filter("li:has(span.tag)", soup.find("ul")))
    closest = sum(
        1 for a in sv.select("a", soup)[::10] if sv.closest("section", a) is not None
    )
    digest.update(f"hot={hot} tagged={tagged} closest={closest}".encode())
    print(f"soupsieve bytes={len(html)} matches={matches} sha256={digest.hexdigest()}")


if __name__ == "__main__":
    main()
