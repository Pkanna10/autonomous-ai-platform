"""Validate the shipped playbook data file (research/playbook.json).

The loader (research/playbook.py) has its own tests on fixture files. These
tests check the shipped cards directly against the models, so the file stays
valid whatever the loader does:

- the envelope is ``{"version": 1, "techniques": [...]}``;
- every entry validates as ``Technique`` (pydantic, frozen, extra="forbid"),
  with ``id == slug`` and unique, well-formed slugs and precondition ids;
- precondition ``check`` keys are dotted lowercase machine keys in a known
  namespace; ``absent.<namespace>.<fact>`` marks a contra-indication (the card
  applies only when the fact does NOT hold), always ``required``;
- numbers are calibrated fractions inside (0, 1);
- references are https links to canonical documentation;
- cards describe intent, never code (no fences, no multi-line code).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

import autonomous_ai_agents.research as research_pkg
from autonomous_ai_agents.common.models import ChangeClass, Precondition, Technique

PLAYBOOK_FILE = Path(research_pkg.__file__).with_name("playbook.json")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
CHECK_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
FACT_NAMESPACES = frozenset({"hotspot", "source", "workload", "env"})
NEGATION_NAMESPACE = "absent"
REFERENCE_HOSTS = frozenset({"docs.python.org", "wiki.python.org", "peps.python.org"})

# Plausible techniques whose preconditions rarely hold for a CPU-bound,
# pure-Python, standard-library-only project run inside the engine's sandbox.
# The cards themselves do not say "distractor": the matcher must reject them on
# their preconditions. The list lives in a data file beside this test (outside
# the shipped package, so the matcher never sees it) for the experiments to
# read when they score false matches.
DISTRACTORS_FILE = Path(__file__).with_name("distractors.json")
EXPECTED_DISTRACTORS = frozenset(
    {
        "process-pool-parallelism",
        "native-extension-rewrite",
        "alternative-interpreter",
        "numpy-vectorization",
        "asyncio-concurrent-io",
        "thread-pool-for-cpu-work",
    }
)

MIN_EFFICIENCY_TECHNIQUES = 24
MAX_EFFICIENCY_TECHNIQUES = 30

# Peak RSS is always judged as a guardrail; memory cards must require that peak
# memory is an objective of the run, which is a real discriminator.
MEMORY_OBJECTIVE_CHECK = "workload.peak_memory_objective"
MEMORY_CARDS = frozenset(
    {
        "generator-streaming-pipeline",
        "slots-or-tuples-for-many-records",
        "array-for-homogeneous-numbers",
        "stream-file-lines",
        "release-large-intermediates",
        "intern-duplicate-values",
    }
)

# Contra-indications found in review: each card must carry the named check.
REVIEWED_CONTRA_INDICATIONS = (
    (
        "memoize-pure-function",
        "absent.source.result_depends_on_type_of_equal_arguments",
    ),
    (
        "dynamic-programming-overlapping-subproblems",
        "absent.source.result_depends_on_type_of_equal_arguments",
    ),
    (
        "str-methods-instead-of-regex",
        "absent.source.replacements_interact_or_multi_character",
    ),
    (
        "avoid-exceptions-for-common-misses",
        "absent.source.raising_call_accepts_more_inputs",
    ),
    ("deque-for-fifo-queue", "absent.source.queue_sliced_indexed_or_exposed"),
)

# One line of code is tolerated (a name such as functools.lru_cache is not
# code anyway); fences, line breaks and two or more statements are not.
CODE_STATEMENT_PATTERNS = (
    re.compile(r"\bdef\s+\w+\s*\("),
    re.compile(r"\bclass\s+\w+\s*[(:]"),
    re.compile(r"\blambda\b[^:]{0,40}:"),
    re.compile(r"\breturn\s+[\w(\[]"),
    re.compile(r"^\s*(?:from\s+[\w.]+\s+)?import\s+[\w.]+\s*$"),
    re.compile(r"\b(?:for|while|if|with)\b[^:]{0,60}:\s*\S"),
    re.compile(r"(?<![=!<>])\s=\s(?!=)"),
    re.compile(r";\s*\w+\s*(?:[=(.\[]|\+=)"),
)


def _raw() -> dict[str, Any]:
    data = json.loads(PLAYBOOK_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _cards() -> tuple[Technique, ...]:
    entries = _raw()["techniques"]
    assert isinstance(entries, list)
    return tuple(Technique.model_validate(entry) for entry in entries)


def _distractors_raw() -> dict[str, Any]:
    data = json.loads(DISTRACTORS_FILE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _distractor_slugs() -> frozenset[str]:
    slugs = _distractors_raw()["slugs"]
    assert isinstance(slugs, list)
    assert all(isinstance(slug, str) for slug in slugs)
    return frozenset(slugs)


def _card(slug: str) -> Technique:
    matches = [card for card in _cards() if card.slug == slug]
    assert len(matches) == 1, slug
    return matches[0]


def _texts(card: Technique) -> list[str]:
    texts = [card.name, card.summary, *card.references]
    for pre in card.preconditions:
        texts.extend((pre.description, pre.check))
    return texts


def _code_statements(text: str) -> int:
    return sum(len(pattern.findall(text)) for pattern in CODE_STATEMENT_PATTERNS)


def _is_negation(pre: Precondition) -> bool:
    return pre.check.split(".", 1)[0] == NEGATION_NAMESPACE


# ---------------------------------------------------------------------------
# Envelope and model validity
# ---------------------------------------------------------------------------


def test_file_is_packaged_next_to_the_research_package() -> None:
    assert PLAYBOOK_FILE.is_file()


def test_envelope_has_version_1_and_only_known_keys() -> None:
    data = _raw()
    assert data["version"] == 1
    assert set(data) == {"version", "techniques"}


def test_every_entry_validates_as_technique() -> None:
    assert _cards()


def test_entries_survive_a_strict_round_trip() -> None:
    for entry in _raw()["techniques"]:
        card = Technique.model_validate(entry)
        assert card.model_dump(mode="json") == entry, card.slug


def test_id_equals_slug_and_slugs_are_unique_and_well_formed() -> None:
    cards = _cards()
    slugs = [card.slug for card in cards]
    assert len(slugs) == len(set(slugs))
    for card in cards:
        assert card.id == card.slug
        assert SLUG_RE.fullmatch(card.slug), card.slug


def test_precondition_ids_are_explicit_unique_and_scoped_to_their_card() -> None:
    seen: set[str] = set()
    for card in _cards():
        for index, pre in enumerate(card.preconditions, start=1):
            assert pre.id == f"{card.slug}-{index}", (card.slug, pre.id)
            assert pre.id not in seen
            seen.add(pre.id)


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------


def test_check_keys_are_dotted_lowercase_in_a_known_namespace() -> None:
    for card in _cards():
        for pre in card.preconditions:
            assert CHECK_RE.fullmatch(pre.check), (card.slug, pre.check)
            parts = pre.check.split(".")
            if parts[0] == NEGATION_NAMESPACE:
                assert len(parts) >= 3, (card.slug, pre.check)
                assert parts[1] in FACT_NAMESPACES, (card.slug, pre.check)
            else:
                assert parts[0] in FACT_NAMESPACES, (card.slug, pre.check)


def test_check_keys_are_unique_within_a_card() -> None:
    for card in _cards():
        checks = [pre.check for pre in card.preconditions]
        assert len(checks) == len(set(checks)), card.slug


def test_every_card_has_a_required_positive_precondition_and_a_contra_indication() -> (
    None
):
    for card in _cards():
        positive = [p for p in card.preconditions if not _is_negation(p) and p.required]
        negative = [p for p in card.preconditions if _is_negation(p)]
        assert positive, card.slug
        assert negative, card.slug


def test_contra_indications_are_required_and_say_so() -> None:
    for card in _cards():
        for pre in card.preconditions:
            if _is_negation(pre):
                assert pre.required, (card.slug, pre.check)
                assert pre.description.startswith("Must not hold: "), (
                    card.slug,
                    pre.check,
                )
            else:
                assert not pre.description.startswith("Must not hold"), (
                    card.slug,
                    pre.check,
                )


def test_some_cards_carry_optional_supporting_evidence() -> None:
    optional = [p for c in _cards() for p in c.preconditions if not p.required]
    assert optional
    for pre in optional:
        assert not _is_negation(pre)


# ---------------------------------------------------------------------------
# Numbers, classes, references
# ---------------------------------------------------------------------------


def test_numbers_are_calibrated_fractions() -> None:
    for card in _cards():
        assert 0.0 < card.expected_gain < 1.0, card.slug
        assert 0.0 < card.provability < 1.0, card.slug
        assert 0.0 < card.risk < 1.0, card.slug


def test_efficiency_cards_are_low_risk() -> None:
    for card in _cards():
        if (
            card.change_class is ChangeClass.efficiency
            and card.slug not in _distractor_slugs()
        ):
            assert card.risk <= 0.3, card.slug


def test_references_are_one_or_two_canonical_https_links() -> None:
    for card in _cards():
        assert 1 <= len(card.references) <= 2, card.slug
        assert len(set(card.references)) == len(card.references), card.slug
        for ref in card.references:
            parts = urlsplit(ref)
            assert parts.scheme == "https", ref
            assert parts.hostname in REFERENCE_HOSTS, ref
            assert not parts.query, ref


def test_text_fields_are_substantive_and_bounded() -> None:
    for card in _cards():
        assert 3 <= len(card.name) <= 80, card.slug
        assert 120 <= len(card.summary) <= 900, card.slug
        for pre in card.preconditions:
            assert 20 <= len(pre.description) <= 400, (card.slug, pre.id)


# ---------------------------------------------------------------------------
# Coverage of the playbook
# ---------------------------------------------------------------------------


def test_distractors_file_has_version_1_and_exactly_the_expected_slugs() -> None:
    data = _distractors_raw()
    assert data["version"] == 1
    assert set(data) == {"version", "slugs"}
    slugs = data["slugs"]
    assert len(slugs) == len(set(slugs))
    assert _distractor_slugs() == EXPECTED_DISTRACTORS


def test_every_distractor_is_a_card_in_the_playbook() -> None:
    slugs = {card.slug for card in _cards()}
    assert _distractor_slugs() <= slugs


def test_efficiency_card_count_and_no_other_classes_outside_distractors() -> None:
    distractors = _distractor_slugs()
    rest = [c for c in _cards() if c.slug not in distractors]
    efficiency = [c for c in rest if c.change_class is ChangeClass.efficiency]
    assert MIN_EFFICIENCY_TECHNIQUES <= len(efficiency) <= MAX_EFFICIENCY_TECHNIQUES
    assert len(efficiency) == len(rest)


def test_every_distractor_hinges_on_a_required_environment_condition() -> None:
    for slug in _distractor_slugs():
        card = _card(slug)
        env = [
            p for p in card.preconditions if p.required and p.check.startswith("env.")
        ]
        assert env, slug


def test_memory_cards_require_peak_memory_as_an_objective() -> None:
    for slug in MEMORY_CARDS:
        card = _card(slug)
        assert any(
            p.check == MEMORY_OBJECTIVE_CHECK and p.required for p in card.preconditions
        ), slug


def test_no_card_treats_the_always_on_memory_guardrail_as_a_signal() -> None:
    for card in _cards():
        for pre in card.preconditions:
            assert pre.check != "workload.peak_memory_dominant", card.slug
            assert "Peak memory is judged" not in pre.description, card.slug


@pytest.mark.parametrize(("slug", "check"), REVIEWED_CONTRA_INDICATIONS)
def test_reviewed_contra_indications_are_present(slug: str, check: str) -> None:
    pre = [p for p in _card(slug).preconditions if p.check == check]
    assert len(pre) == 1, (slug, check)
    assert pre[0].required


# ---------------------------------------------------------------------------
# Intent, not code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "statements"),
    [
        ("Build a set once and test membership against it.", 0),
        ("Wrap the function with functools.lru_cache.", 0),
        ("Never use x == y as a key.", 0),
        ("total = total + x", 1),
        ("total = 0; total += x", 2),
        ("def f(x): return x", 2),
        ("for x in items: out.append(x)", 1),
        ("import functools", 1),
        ("key=lambda r: r.id", 1),
        ("class Point(object): pass", 1),
    ],
)
def test_code_detector_counts_statements(text: str, statements: int) -> None:
    assert _code_statements(text) == statements


def test_no_card_text_contains_code() -> None:
    for card in _cards():
        for text in _texts(card):
            assert "```" not in text, card.slug
            assert "`" not in text, card.slug
            assert "\n" not in text and "\r" not in text, card.slug
            assert _code_statements(text) <= 1, (card.slug, text)


def test_no_card_text_is_tuned_by_name_to_a_corpus() -> None:
    # Cards are generic: they name techniques and observable signals, never a
    # project, repository, fixture or benchmark.
    banned = re.compile(
        r"fixture|corpus|benchmark file|_solutions|manifest", re.IGNORECASE
    )
    for card in _cards():
        for text in _texts(card):
            assert not banned.search(text), (card.slug, text)
