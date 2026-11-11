"""The framework catalogue and the deal (U-portfolio, the portfolio leap).

The catalogue is data (``CATALOGUE``): each entry its id, source, evidence
grade (``GRADES``), numbered steps with the product each step must output,
and whether it is dealt (``active``). The ten active procedures are the
owner's, steps as given; the eight inactive ones record their steps and are
never dealt. Only the TRIZ matrix carries a reason (``note``, the owner's:
it needs the matrix as data); the other seven are inactive because the
owner's list makes them so, and their ``note`` is empty.

The deal (``deal``) gives one leap call three distinct active procedures,
a function of (library, run, round) and the fixed ``DEAL_SEED``: the seed
orders the active procedures once (a permutation), the cell number of
(library, run, round) picks three consecutive places of that cycle, and
SIT's tool comes from the same place (the cycle's turn). The design is the
sprint's four libraries (``DEAL_LIBRARIES``, O59) x 3 runs x up to 3 rounds
(X2-P and X2-F run 2); the cells run round by round, so after any number of
rounds each procedure has been dealt equally often (counts differ by at
most 1) and no call holds one twice. Each library's 9 places a round are
consecutive, its two rounds' windows miss different procedures: over rounds
1-2 each library meets all ten (18 places, every procedure at least once),
over 3 rounds every procedure at least twice. A library off the design is
refused (fail closed: it would deal outside the balance), and so is a run
outside 1-3 or a round below 1; a round past the design still deals three
distinct procedures.
"""

from __future__ import annotations

import functools
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

Grade = Literal["A", "B", "C", "D"]
GRADES: Final[Mapping[Grade, str]] = MappingProxyType({
    "A": "an empirical or controlled study on program performance",
    "B": "a published method with controlled evidence in another domain "
         "(LLM reasoning benchmarks, psychology or design experiments)",
    "C": "textbook or course canon",
    "D": "a heuristic method without controlled evidence",
})  # fmt: skip
"""The evidence scale each entry is graded on."""


@dataclass(frozen=True)
class Step:
    """One numbered step: what to do and the product it must output."""

    number: int
    task: str
    product: str


@dataclass(frozen=True)
class Framework:
    """One catalogue entry; ``tools`` are dealt with it (SIT's only)."""

    id: str
    name: str
    source: str
    grade: Grade
    steps: tuple[Step, ...]
    active: bool
    tools: tuple[str, ...] = ()
    note: str = ""


def _steps(*pairs: tuple[str, str]) -> tuple[Step, ...]:
    return tuple(Step(n, task, product) for n, (task, product) in enumerate(pairs, 1))


SIT_TOOLS: Final = (
    "multiplication",
    "division",
    "task unification",
    "attribute dependency",
)

_BENTLEY_RULE = "the first rule of this group that applies, with its line, or none"
ACTIVE: Final[tuple[Framework, ...]] = (
    Framework(
        "bentley", "BENTLEY",
        "MIT 6.172 Performance Engineering of Software Systems, the New Bentley "
        "Rules (Leiserson and Shun, after Bentley, Writing Efficient Programs, 1982)",
        "C",
        _steps(
            ("For the hot function, data structures: packing and encoding, "
             "augmentation, precomputation, compile-time initialisation, caching, "
             "lazy evaluation, sparsity.", _BENTLEY_RULE),
            ("Logic: constant folding, common-subexpression elimination, "
             "algebraic identities, short-circuiting, ordering tests, fast path, "
             "combining tests.", _BENTLEY_RULE),
            ("Loops: hoisting, sentinels, unrolling, fusion, eliminating wasted "
             "iterations.", _BENTLEY_RULE),
            ("Functions: inlining, tail-recursion elimination, coarsening "
             "recursion.", _BENTLEY_RULE),
            ("Choose the one closing most of the gap, data structures first.",
             "the chosen rule and its line"),
        ),
        True,
    ),
    Framework(
        "per_element", "PER-ELEMENT",
        "Data-oriented design (Acton, CppCon 2014; Fabian, Data-Oriented Design, "
        "2018); Jin et al., Understanding and Detecting Real-World Performance "
        "Bugs, PLDI 2012; the SWE-fficiency benchmark (2025)",
        "A",
        _steps(
            ("Name the element handled many times.", "the element and its count"),
            ("List every function on its path, callers and callees.",
             "the functions on the path"),
            ("Mark the work done per element that depends only on the batch.",
             "the per-element work that depends only on the batch"),
            ("Design the batch form.",
             "what is computed once and what flows as a sequence"),
            ("List every function that changes.",
             "the functions that change, two or more"),
        ),
        True,
    ),
    Framework(
        "backend", "BACKEND",
        "CPython's C-level standard library (the Python documentation's "
        "built-ins and standard library reference)",
        "C",
        _steps(
            ("State the hot loop as one operation over a sequence.",
             "the operation"),
            ("Name the built-in or standard-library routine that does it.",
             "the routine"),
            ("List where its semantics differ: empty input, ordering, types, "
             "Unicode.", "the differences"),
            ("Show how each difference is preserved. Standard library only.",
             "how each difference is preserved"),
        ),
        True,
    ),
    Framework(
        "skiena", "SKIENA",
        "Skiena, The Algorithm Design Manual, 3rd ed., 2020, chapter 13 "
        "(How to design algorithms)",
        "C",
        _steps(
            ("Input, output, sizes.", "the input, the output and their sizes"),
            ("Does sorting help?", "yes or no, and why"),
            ("Can it be split?", "yes or no, and how"),
            ("Is there a left-to-right order (dynamic programming)?",
             "yes or no, and the order"),
            ("Are queries repeated (a data structure)?",
             "yes or no, and the structure"),
            ("Complexity now against achievable.",
             "the complexity now and the achievable one"),
        ),
        True,
    ),
    Framework(
        "polya", "POLYA",
        "Polya, How to Solve It, 1945 (the four phases)",
        "C",
        _steps(
            ("Understand.", "the unknown, the data and the condition"),
            ("Devise a plan with one named heuristic: related problem, "
             "specialise, generalise, auxiliary element, work backwards, "
             "decompose and recombine.", "the heuristic and the plan"),
            ("Carry out the plan, checking each step.", "the checked steps"),
            ("Look back.", "the verification and another method"),
        ),
        True,
    ),
    Framework(
        "from_spec", "FROM-SPEC",
        "The Einstellung effect (Luchins 1942; Bilalic, McLeod and Gobet, "
        "Cognition 2008) and the generic-parts technique (McCaffrey, "
        "Psychological Science 2012)",
        "B",
        _steps(
            ("Write what the function computes, input to output, without how.",
             "the specification"),
            ("Describe each structure by shape and properties, not by name or "
             "role.", "the structures as shapes and properties"),
            ("Write the most direct method from the specification alone.",
             "the direct method"),
            ("The difference from the code is the idea.", "the difference"),
        ),
        True,
    ),
    Framework(
        "ifr", "IFR",
        "TRIZ, the ideal final result and resources (Altshuller, Creativity as "
        "an Exact Science, 1984)",
        "D",
        _steps(
            ("State the result appearing at no cost.", "the ideal result"),
            ("Name what prevents it.", "the obstacle"),
            ("List resources present and unused: ordering, types, sizes, values "
             "already computed, import time.", "the unused resources"),
            ("Use a listed resource to remove the obstacle, adding nothing.",
             "the resource used and how"),
        ),
        True,
    ),
    Framework(
        "trim", "TRIM",
        "TRIZ function analysis and trimming (Altshuller; Gadd, TRIZ for "
        "Engineers, 2011)",
        "D",
        _steps(
            ("List the hot path's components.", "the components"),
            ("Write each function as carrier-verb-object, useful or harmful.",
             "the functions, each marked useful or harmful"),
            ("Pick a carrier.", "the carrier"),
            ("Trim by one rule: the object is not needed, the object does it "
             "itself, another component does it.", "the rule applied"),
            ("Say who carries the function now.", "the new carrier"),
        ),
        True,
    ),
    Framework(
        "sit", "SIT",
        "Systematic Inventive Thinking, function follows form in a closed world "
        "(Goldenberg, Mazursky and Solomon, Science 1999; Boyd and Goldenberg, "
        "Inside the Box, 2013)",
        "B",
        _steps(
            ("List the components and variables.", "the components and variables"),
            ("Apply the dealt tool using only what is already there.",
             "the changed form"),
            ("Say what the changed form is good for.", "its use here"),
            ("Check feasibility and output identity.",
             "the feasibility and why the output stays identical"),
        ),
        True,
        tools=SIT_TOOLS,
    ),
    Framework(
        "recall", "RECALL",
        "Yasunaga et al., Large Language Models as Analogical Reasoners, ICLR "
        "2024 (arXiv 2023)",
        "B",
        _steps(
            ("Name the core concepts with a short tutorial.",
             "the concepts and the tutorial"),
            ("Recall three relevant and distinct problems with their solutions.",
             "the three problems and their solutions"),
            ("Solve this one from them.", "the solution"),
        ),
        True,
    ),
)  # fmt: skip

INACTIVE: Final[tuple[Framework, ...]] = (
    Framework(
        "triz_matrix", "TRIZ contradiction matrix",
        "Altshuller, the contradiction matrix and 40 inventive principles",
        "D",
        _steps(
            ("State the parameter to improve and the one that worsens.",
             "the two parameters"),
            ("Look up their cell in the matrix.", "the listed principles"),
            ("Apply one listed principle.", "the principle and how it applies"),
        ),
        False,
        note="needs the matrix embedded as data",
    ),
    Framework(
        "morphological", "Morphological analysis with cross-consistency",
        "Zwicky, Discovery, Invention, Research, 1969; Ritchey, Wicked Problems, "
        "Social Messes, 2011",
        "D",
        _steps(
            ("List the problem's parameters.", "the parameters"),
            ("List the values of each parameter.", "the values"),
            ("Strike each pair of values that cannot coexist.",
             "the struck pairs"),
            ("Pick a consistent configuration unlike the current one.",
             "the configuration"),
        ),
        False,
    ),
    Framework(
        "synectics", "Synectics",
        "Gordon, Synectics, 1961",
        "D",
        _steps(
            ("State the problem as given.", "the problem"),
            ("Find a direct analogy.", "the analogy"),
            ("Find a personal analogy: be the component.", "the personal analogy"),
            ("Compress the conflict into two words.", "the compressed conflict"),
            ("Force-fit the analogy back to the problem.", "the fitted idea"),
        ),
        False,
    ),
    Framework(
        "wordtree", "WordTree",
        "Linsey, Markman and Wood, Design by Analogy: A Study of the WordTree "
        "Method, Journal of Mechanical Design 2012",
        "B",
        _steps(
            ("State the key functions as verbs.", "the verbs"),
            ("Climb each verb's more general and more specific words.",
             "the word tree"),
            ("Find domains that perform the related verbs.", "the domains"),
            ("Map one domain's solution back.", "the mapped solution"),
        ),
        False,
    ),
    Framework(
        "scamper", "SCAMPER",
        "Eberle, SCAMPER, 1971 (after Osborn's checklist, 1953)",
        "D",
        _steps(
            ("Substitute.", "what is substituted"),
            ("Combine.", "what is combined"),
            ("Adapt.", "what is adapted"),
            ("Modify.", "what is modified"),
            ("Put to another use.", "the other use"),
            ("Eliminate.", "what is eliminated"),
            ("Reverse or rearrange.", "what is reversed"),
        ),
        False,
    ),
    Framework(
        "ck_theory", "C-K theory",
        "Hatchuel and Weil, C-K Design Theory, Research in Engineering Design "
        "2009",
        "D",
        _steps(
            ("State the concept as a proposition neither true nor false yet.",
             "the concept"),
            ("List the knowledge that bears on it.", "the knowledge"),
            ("Partition the concept by adding a property from the knowledge.",
             "the partitions"),
            ("Expand the knowledge to test one partition.", "the test"),
        ),
        False,
    ),
    Framework(
        "lean_wastes", "Lean wastes",
        "Ohno, Toyota Production System, 1988; Poppendieck and Poppendieck, "
        "Lean Software Development, 2003",
        "C",
        _steps(
            ("Map the hot path as a value stream.", "the stream"),
            ("Mark each waste: extra processing, waiting, motion, inventory, "
             "defects, partially done work.", "the wastes"),
            ("Remove the largest waste.", "the removal"),
        ),
        False,
    ),
    Framework(
        "verbalized_sampling", "Verbalized sampling",
        "Zhang et al., Verbalized Sampling: How to Mitigate Mode Collapse and "
        "Unlock LLM Diversity, arXiv 2025",
        "B",
        _steps(
            ("Write five candidate ideas, each with its probability.",
             "the candidates and their probabilities"),
            ("Pick one from the low-probability tail.", "the pick"),
            ("Develop it.", "the developed idea"),
        ),
        False,
    ),
)  # fmt: skip
CATALOGUE: Final[tuple[Framework, ...]] = (*ACTIVE, *INACTIVE)
_BY_ID: Final[Mapping[str, Framework]] = MappingProxyType({f.id: f for f in CATALOGUE})


def by_id(framework: str) -> Framework:
    """The catalogue entry ``framework`` (``KeyError`` for an unknown id)."""
    return _BY_ID[framework]


# --------------------------------------------------------------------------
# The deal
# --------------------------------------------------------------------------

DEAL_SEED: str = "portfolio-leap-2026-11"
"""The fixed seed of the rotation, recorded in each procedure row."""
DEAL_SIZE: Final = 3
DEAL_RUNS: Final = 3
DEAL_ROUNDS: Final = 3
DEAL_LIBRARIES: Final = ("sqlparse", "tomli", "mistune", "markdown")
"""The design's libraries, the sprint's four (O59), in order."""
_PLAIN: Final = re.compile(r"[a-z][a-z0-9_]{0,39}")


@dataclass(frozen=True)
class Dealt:
    """One dealt procedure: its place in the call (1-3) and SIT's tool."""

    framework: Framework
    position: int
    tool: str | None = None


@dataclass(frozen=True)
class Deal:
    """What one leap call is dealt, and where it sits in the design."""

    library: str
    run: int
    round: int
    cell: int
    seed: str
    procedures: tuple[Dealt, ...]


def check_library(library: object) -> str:
    """``library`` when it is a plain name of the design (``ValueError``)."""
    if (
        not isinstance(library, str)
        or _PLAIN.fullmatch(library) is None
        or library not in DEAL_LIBRARIES
    ):
        raise ValueError(f"the deal library must be one of {', '.join(DEAL_LIBRARIES)}"
                         f"; got {library!r}")  # fmt: skip
    return library


def check_run(run: object) -> int:
    """``run`` when it is a whole number from 1 to ``DEAL_RUNS`` (``ValueError``):
    a run past the design would deal outside the balance."""
    if isinstance(run, bool) or not isinstance(run, int) or not 1 <= run <= DEAL_RUNS:
        raise ValueError(f"the deal run must be a whole number from 1 to "
                         f"{DEAL_RUNS}; got {run!r}")  # fmt: skip
    return run


@functools.cache
def _order(seed: str) -> tuple[Framework, ...]:
    """The active procedures in the seed's order: one cycle of the rotation."""
    return tuple(sorted(
        ACTIVE, key=lambda f: hashlib.sha256(f"{seed}\0{f.id}".encode()).digest()
    ))  # fmt: skip


def deal(library: str, run: int, round_: int) -> Deal:
    """The three procedures of the leap call of ``library``'s ``run`` in
    ``round_`` (1-based): places ``3 * cell`` to ``3 * cell + 2`` of the
    seed's cycle, the cells round by round, then library, then run."""
    check_library(library)
    check_run(run)
    if isinstance(round_, bool) or not isinstance(round_, int) or round_ < 1:
        raise ValueError(
            f"the deal round must be a whole number from 1; got {round_!r}"
        )
    slot = DEAL_LIBRARIES.index(library)
    cell = ((round_ - 1) * len(DEAL_LIBRARIES) + slot) * DEAL_RUNS + run - 1
    cycle, picked = _order(DEAL_SEED), []
    for position in range(DEAL_SIZE):
        place = DEAL_SIZE * cell + position
        framework = cycle[place % len(cycle)]
        turn = place // len(cycle)
        tool = framework.tools[turn % len(framework.tools)] if framework.tools else None
        picked.append(Dealt(framework, position + 1, tool))
    return Deal(library, run, round_, cell, DEAL_SEED, tuple(picked))
