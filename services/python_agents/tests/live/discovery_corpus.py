"""Hard corpus v2 (spec D2, Wave 2 V1-V2): the retrieval re-test's set.

``tests/fixtures/live_corpus_discovery`` holds twelve small repositories in six
categories, two each, built so that blind generation does not saturate:

- ``deep``: the removable cost is a builtin's self time three or more calls
  below ``main``, under project frames that each look cheap;
- ``spread``: the cost is split over six or more functions, none of them over
  10 % of the self time;
- ``misleading``: the top hotspot is unavoidable output or a sort key, and the
  fix sits at hotspot rank 3 or lower;
- ``uncommon``: the reference fix is a less obvious technique, and the
  textbook first idea falls well short of it;
- ``small``: the reference fix gains 5-15 %, above the noise floor;
- ``decoy``: controls whose cost is one C-level stream that no edit to the
  project code can shorten; the tempting idea gains nothing.

Every slowdown has its reference fix in ``_solutions/<name>.patch`` and, except
``small``, the textbook first idea in ``_solutions/<name>.textbook.patch``; a
decoy has only its tempting idea there. ``test_discovery_corpus_guards.py``
proves each claim offline.

This module is the typed manifest. ``DiscoveryRepo`` is a ``CorpusRepo`` whose
``category`` is its v2 group (``corpus.Category`` holds the six), so the sweep,
the A/B and the corpus outcome record the group per row as they record a hard
corpus category, and ``render_summary`` prints one line per group.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from .conftest import TESTS_DIR
from .corpus import MIN_FIX_GAIN, CorpusRepo, _choice, _entries, _fields, _text, _two

DISCOVERY_DIR: Final = TESTS_DIR / "fixtures" / "live_corpus_discovery"
DISCOVERY_SOLUTIONS_DIR: Final = DISCOVERY_DIR / "_solutions"
DISCOVERY_MANIFEST: Final = DISCOVERY_DIR / "manifest.json"

Group = Literal["deep", "spread", "misleading", "uncommon", "small", "decoy"]
GROUPS: Final[tuple[Group, ...]] = (
    "deep",
    "spread",
    "misleading",
    "uncommon",
    "small",
    "decoy",
)
TEXTBOOK_GROUPS: Final[frozenset[Group]] = frozenset(
    {"deep", "spread", "misleading", "uncommon", "decoy"}
)
"""The groups with a ``.textbook.patch``: the first idea a reviewer would try
(for a decoy, the tempting idea)."""
_GROUPS: Final[dict[str, Group]] = {g: g for g in GROUPS}


@dataclass(frozen=True)
class DiscoveryRepo(CorpusRepo):
    """A v2 repository: a ``CorpusRepo`` (a ``decoy`` is a ``control``
    expected to keep nothing) whose ``category`` is its v2 group."""

    @property
    def textbook(self) -> Path | None:
        """The textbook (or tempting) patch, ``None`` for ``small``."""
        if self.category not in TEXTBOOK_GROUPS:
            return None
        return self.root / "_solutions" / f"{self.name}.textbook.patch"


def _gain(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}.fix_gain: expected a number")
    if not 0 < value < 1:
        raise ValueError(f"{where}.fix_gain: expected a fraction in (0, 1)")
    return float(value)


def parse_discovery_manifest(
    data: object, root: Path = DISCOVERY_DIR
) -> tuple[DiscoveryRepo, ...]:
    """The repositories of the v2 ``manifest.json``, validated strictly: a
    slowdown carries the gain its reference fix reaches at least
    (``fix_gain``), a decoy carries none."""
    base = frozenset({"name", "package", "category", "hypotheses"})
    repos: list[DiscoveryRepo] = []
    for index, entry in enumerate(_entries(data)):
        where = f"manifest.repos[{index}]"
        raw = entry if isinstance(entry, dict) else {}
        group = _GROUPS[_choice(_GROUPS, raw.get("category"), where + ".category")]
        decoy = group == "decoy"
        fields = _fields(entry, base if decoy else base | {"fix_gain"}, where)
        repos.append(
            DiscoveryRepo(
                name=_text(fields["name"], where),
                package=_text(fields["package"], where),
                kind="control" if decoy else "slowdown",
                expected="none" if decoy else "win",
                hypotheses=_two(fields["hypotheses"], where),
                fix_gain=MIN_FIX_GAIN if decoy else _gain(fields["fix_gain"], where),
                category=group,
                root=root,
            )
        )
    return tuple(repos)


DISCOVERY_CORPUS: Final = parse_discovery_manifest(
    json.loads(DISCOVERY_MANIFEST.read_text(encoding="utf-8"))
)
"""Hard corpus v2, in run order: ten slowdowns and two decoy controls."""


def of_group(group: Group) -> tuple[DiscoveryRepo, ...]:
    return tuple(repo for repo in DISCOVERY_CORPUS if repo.category == group)
