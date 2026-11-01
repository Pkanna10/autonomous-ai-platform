"""``classify`` and its closure: what of a crash may reach the retry prompt (D12, D13).

Each case is a stderr tail over a tiny repository held in memory: ``bench.py``
at base, its raising line chosen per test. The canaries are a trial that read
a secret and tries to encode it through every slot.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from autonomous_ai_agents.execution.procrun import RunFailure
from autonomous_ai_agents.execution.retry import (
    TEMPLATES,
    ClosureIndex,
    FeedbackFrame,
    TrialFeedback,
    classify,
)

WT = PurePosixPath("/wt")
ALPHABET = "".join(f"+a{byte:02x} = {byte}\n" for byte in range(256))
"""A diff that defines a00-aff: one closure name per byte value."""


def tail(*frames: tuple[str, int, str | None], last: str) -> bytes:
    lines = ["Traceback (most recent call last):"]
    for path, line, function in frames:
        where = f'  File "{path}", line {line}' + (
            f", in {function}" if function else ""
        )
        lines += [where, "    source text the parser never reads", "    ^^^^^^"]
    return "\n".join([*lines, last, ""]).encode()


def failure(
    data: bytes, *, kind: str = "exit", workload: str | None = "w1"
) -> RunFailure:
    return RunFailure(
        "workload 'bench' run 1/5: the command ended with exit status 1: x",
        kind=kind,  # type: ignore[arg-type]
        exit_tail=data,
        workload_id=workload,
    )


def closure(line: str, *, diff: str = "", cap: int = 1 << 20) -> ClosureIndex:
    """bench.py: line 1 ``def main(rows):``, line 2 the raising line, line 3 a call."""
    sources = {"bench.py": f"def main(rows):\n{line}\nmain(3)\n", ".env": "KEY=AKIA\n"}
    return ClosureIndex.build(diff, sources, max_source_bytes=cap)


def run(
    last: str,
    line: str = "    return rows",
    *,
    frames: tuple[tuple[str, int, str | None], ...] = (("/wt/bench.py", 2, "main"),),
    diff: str = "",
    cap: int = 1 << 20,
    tracked: tuple[str, ...] = ("bench.py", ".env"),
) -> TrialFeedback | None:
    return classify(
        failure(tail(*frames, last=last)),
        closure=closure(line, diff=diff, cap=cap),
        worktree=WT,
        tracked=tracked,
        touched=(),
    )


def message(last: str, line: str = "    return rows", **kwargs: object) -> str | None:
    feedback = run(last, line, **kwargs)  # type: ignore[arg-type]
    assert feedback is not None
    return feedback.message


# ---------------------------------------------------------------------------
# What is never retried
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "workload", "last"),
    [
        ("other", "w1", "NameError: name 'rows' is not defined"),  # a timeout, a flood
        ("signal", "w1", "NameError: name 'rows' is not defined"),
        ("exit", None, "NameError: name 'rows' is not defined"),  # the suite, profiler
        ("exit", "repro", "NameError: name 'rows' is not defined"),  # excluded (3c)
        ("exit", "w1", "AssertionError: rows"),
        ("exit", "w1", "ValueError: rows"),
        ("exit", "w1", "garbage, no traceback"),
    ],
    ids=[
        "timeout",
        "signal",
        "suite",
        "excluded",
        "assertion",
        "unfixable",
        "unparsed",
    ],
)
def test_only_a_fixable_crash_of_an_included_workload_is_classified(
    kind: str, workload: str | None, last: str
) -> None:
    data = tail(("/wt/bench.py", 2, "main"), last=last)
    if last.startswith("garbage"):
        data = last.encode()

    found = classify(
        failure(data, kind=kind, workload=workload),
        closure=closure("    return rows"),
        worktree=WT,
        tracked=("bench.py",),
        touched=(),
        excluded_workloads=("repro",),
    )

    assert found is None


# ---------------------------------------------------------------------------
# Templates and the closure
# ---------------------------------------------------------------------------


def test_a_closure_checked_message_is_sent_with_type_and_frames() -> None:
    feedback = run(
        "NameError: name 'totl' is not defined",
        "    return totl + rows",
        frames=(("/wt/bench.py", 3, "<module>"), ("/wt/bench.py", 2, "main")),
    )

    assert feedback == TrialFeedback(
        exc_type="NameError",
        frames=(
            FeedbackFrame("bench.py", 3, "<module>"),
            FeedbackFrame("bench.py", 2, "main"),
        ),
        message="name 'totl' is not defined",
        template="name_undefined",
    )
    assert feedback.render() == (
        "NameError: name 'totl' is not defined\n"
        '  File "bench.py", line 3, in <module>\n'
        '  File "bench.py", line 2, in main'
    )


@pytest.mark.parametrize(
    ("last", "line", "sent"),
    [
        (
            "ImportError: cannot import name 'helpr' from 'util' (/wt/util.py)",
            "    from util import helpr",
            "cannot import name 'helpr' from 'util' (<path>)",
        ),
        (
            "ImportError: cannot import name 'helpr' from 'util' (consider renaming "
            "'/wt/util.py' if it has the same name as a library you intended to import)",
            "    from util import helpr",
            "cannot import name 'helpr' from 'util' (consider renaming '<path>' if it "
            "has the same name as a library you intended to import)",
        ),
        (
            "NameError: name 'rws' is not defined. Did you mean: 'rows'?",
            "    return rws",
            "name 'rws' is not defined",
        ),
        (
            "TypeError: main() got an unexpected keyword argument 'rws'. Did you mean 'rows'?",
            "    main(rws=1)",
            "main() got an unexpected keyword argument 'rws'",
        ),
        (
            "TypeError: unsupported operand type(s) for +=: 'int' and 'str'",
            "    rows += 'a'",
            "unsupported operand type(s) for +=: 'int' and 'str'",
        ),
        (
            "IndentationError: expected an indented block after 'if' statement on line 2",
            "    if rows:",
            "expected an indented block after 'if' statement on line 2",
        ),
    ],
    ids=["path", "3.13-path", "hint", "kw-hint", "builtin-types", "syntax-number"],
)
def test_paths_and_suggestions_are_never_sent(last: str, line: str, sent: str) -> None:
    """A path and an interpreter suggestion (computed from the runtime namespace,
    which the trial controls) are dropped; the rest of the template is sent."""
    assert message(last, line) == sent


@pytest.mark.parametrize(
    ("last", "why"),
    [
        (
            "NameError: name 'AKIAIOSFODNN7EXAMPLE' is not defined",
            "outside the closure",
        ),
        (
            "TypeError: main() takes 1 positional argument but 41111 were given",
            "5 digits",
        ),
        (
            "TypeError: main() takes from 1 to 2 positional arguments but 3 were given",
            "3 numbers",
        ),
        (
            "TypeError: main() takes 1 positional argument but 0012 were given",
            "leading 0",
        ),
        ("NameError: name 'rows' is not defined\x1b[0m", "an ESC byte"),
        ("NameError: name 'main' is not defined", "not on the raising line"),
        ("TypeError: 'int' object is not callable", "no template"),
    ],
)
def test_a_message_failing_a_template_or_the_closure_gives_type_and_frames(
    last: str, why: str
) -> None:
    feedback = run(last, "    return rows(1, 2)")

    assert feedback is not None, why
    assert feedback.message is None, why
    assert feedback.frames == (FeedbackFrame("bench.py", 2, "main"),)
    assert feedback.withheld is not None


def test_a_bare_exception_is_sent_as_its_type_and_frames() -> None:
    feedback = run("NameError")

    assert feedback is not None
    assert (feedback.message, feedback.withheld, feedback.render()) == (
        None,
        None,
        'NameError\n  File "bench.py", line 2, in main',
    )


def test_two_numbers_of_four_digits_pass() -> None:
    sent = message(
        "TypeError: main() takes 1234 positional arguments but 9999 were given",
        "    main(*rows)",
    )
    assert sent == "main() takes 1234 positional arguments but 9999 were given"


def test_no_template_holds_more_than_two_numbers() -> None:
    assert all(sum(g[0] == "d" for g in t.pattern.groupindex) <= 2 for t in TEMPLATES)


def test_a_message_over_300_characters_is_withheld() -> None:
    name = "n" * 301
    assert message(f"NameError: name '{name}' is not defined", f"    {name}") is None


def test_past_the_source_cap_messages_are_withheld() -> None:
    feedback = run("NameError: name 'rows' is not defined", cap=8)

    assert feedback is not None
    assert (feedback.message, feedback.withheld) == (
        None,
        "the source closure is incomplete",
    )


def test_a_dotted_name_needs_every_part_on_the_line() -> None:
    last = "TypeError: Runner.go() takes 1 positional argument but 2 were given"
    assert message(last, "    Runner().go(1)") is not None
    assert message(last, "    rows.go(1)", diff="+class Runner:\n") is None


# ---------------------------------------------------------------------------
# Canaries: a trial encoding a secret through the slots
# ---------------------------------------------------------------------------

SECRET = 0x3F
"""One secret byte; a trial selects the alphabet name ``a3f`` at run time."""


@pytest.mark.parametrize(
    ("last", "line"),
    [
        (
            "NameError: name 'v4111111111111111' is not defined",
            "    return globals()['v' + secret]",
        ),
        (
            "TypeError: main() takes 1 positional argument but 4111111111111111 were given",
            "    main(*rows)",
        ),
        (
            "TypeError: main() takes from 4111 to 1111 positional arguments but 1111 were given",
            "    main(*rows)",
        ),
    ],
    ids=["name", "long-number", "three-numbers"],
)
def test_digit_canary(last: str, line: str) -> None:
    """
    GIVEN a card number read at run time, raised as a name (``globals()['v' +
        secret]``), as one number, or split over three
    THEN type and frames only
    """
    assert message(last, line, diff="+secret = open(PATH).read()\n") is None


CANARY_SLOTS = [
    "NameError: name 'a3f' is not defined",
    "NameError: free variable 'a3f' referenced before assignment in enclosing scope",
    "NameError: cannot access free variable 'a3f' where it is not associated with a value in enclosing scope",
    "UnboundLocalError: local variable 'a3f' referenced before assignment",
    "UnboundLocalError: cannot access local variable 'a3f' where it is not associated with a value",
    "ImportError: cannot import name 'a3f' from 'main' (/wt/x.py)",
    "ImportError: cannot import name 'main' from partially initialized module 'a3f' (most likely due to a circular import) (/wt/x.py)",
    "ImportError: cannot import name 'a3f' from 'main' (consider renaming '/wt/x.py' if it has the same name as a library you intended to import)",
    "ModuleNotFoundError: No module named 'a3f'",
    "ModuleNotFoundError: No module named 'main.a3f'; 'main' is not a package",
    "AttributeError: 'a3f' object has no attribute 'main'",
    "AttributeError: module 'a3f' has no attribute 'main'",
    "AttributeError: type object 'main' has no attribute 'a3f'",
    "AttributeError: module 'main' has no attribute 'main' (consider renaming '/wt/x.py' since it has the same name as the standard library module named 'a3f' and prevents importing that standard library module)",
    "TypeError: a3f() takes 1 positional argument but 2 were given",
    "TypeError: main.a3f() takes 1 positional argument but 2 were given",
    "TypeError: unsupported operand type(s) for +: 'a3f' and 'int'",
    "TypeError: unsupported operand type(s) for +: 'int' and 'a3f'",
    "TypeError: a3f() got an unexpected keyword argument 'main'",
    "TypeError: main() got an unexpected keyword argument 'a3f'",
]


@pytest.mark.parametrize("last", CANARY_SLOTS)
def test_each_canary_passes_once_its_names_are_on_the_line(last: str) -> None:
    """The control: with ``a3f`` on the raising line the same message is sent,
    so the canaries below fail on the line rule, not on a template miss."""
    assert message(last, "    main.a3f(main=a3f) + int", diff=ALPHABET) is not None


def test_every_name_slotted_template_has_a_canary() -> None:
    slotted = {
        t.id for t in TEMPLATES if any(g[0] in "nt" for g in t.pattern.groupindex)
    }
    hit = {
        t.id
        for last in CANARY_SLOTS
        for t in TEMPLATES
        if t.matches(*last.split(": ", 1))
    }
    assert hit == slotted


@pytest.mark.parametrize("last", CANARY_SLOTS)
def test_alphabet_canary_per_template(last: str) -> None:
    """
    GIVEN a diff defining a00-aff and a raising line that selects one at run
        time (``getattr(NS, ALPHA[secret])``), so the name is in the closure
        but not on the line
    WHEN the crash is classified
    THEN type and frames only
    """
    assert (
        message(last, "    return getattr(main, ALPHA[secret])", diff=ALPHABET) is None
    )


def test_alphabet_canary_through_eval() -> None:
    """``eval(ALPHA[secret])`` raises in ``<string>``: that frame is dropped and
    the innermost repository frame's line does not name ``a3f``."""
    feedback = run(
        "NameError: name 'a3f' is not defined",
        "    return eval(ALPHA[secret])",
        frames=(("/wt/bench.py", 2, "main"), ("<string>", 1, "<module>")),
        diff=ALPHABET,
    )

    assert feedback is not None
    assert (feedback.message, feedback.frames) == (
        None,
        (FeedbackFrame("bench.py", 2, "main"),),
    )


def test_alphabet_canary_through_the_suggestion() -> None:
    """The trial deletes every alphabet name but ``a3f`` and reads ``a_``: the
    interpreter suggests ``a3f``. The suggestion is never sent."""
    sent = message(
        "NameError: name 'a_' is not defined. Did you mean: 'a3f'?",
        "    return a_",
        diff=ALPHABET,
    )
    assert sent == "name 'a_' is not defined"


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


def test_at_most_the_three_innermost_kept_frames_are_sent() -> None:
    frames = tuple(("/wt/bench.py", line, "main") for line in (1, 2, 3, 1, 2))
    feedback = run("NameError: name 'rows' is not defined", frames=frames)

    assert feedback is not None
    assert [frame.line for frame in feedback.frames] == [3, 1, 2]


@pytest.mark.parametrize(
    "frame",
    [
        ("/wt/.env", 1, "main"),  # deny-listed
        ("/wt/notes.py", 1, "main"),  # untracked
        ("/elsewhere/bench.py", 1, "main"),  # outside the worktree
        ("/wt/../bench.py", 1, "main"),
        ("/wt/bench.py", 0, "main"),
        ("/wt/bench.py", 4, "main"),  # past the file's 3 lines
        ("/wt/bench.py", 123456790, "main"),  # a forged co_firstlineno
        ("/wt/bench.py", 1, "AKIAIOSFODNN7EXAMPLE"),  # function outside the closure
        ("/wt/a\x00b.py", 1, "main"),  # a NUL byte makes realpath raise
    ],
    ids=[
        "env",
        "untracked",
        "outside",
        "dotdot",
        "line-0",
        "past-end",
        "forged",
        "function",
        "nul",
    ],
)
def test_a_frame_failing_a_check_is_dropped(frame: tuple[str, int, str]) -> None:
    feedback = run(
        "NameError: name 'rows' is not defined",
        frames=(("/wt/bench.py", 2, "main"), frame),
    )

    assert feedback is not None
    assert feedback.frames == (FeedbackFrame("bench.py", 2, "main"),)


def test_a_relative_frame_path_is_read_from_the_worktree_root() -> None:
    feedback = run(
        "NameError: name 'rows' is not defined", frames=(("bench.py", 2, "main"),)
    )

    assert feedback is not None
    assert feedback.frames == (FeedbackFrame("bench.py", 2, "main"),)
    assert feedback.message == "name 'rows' is not defined"


def test_a_touched_file_is_read_at_the_trials_commit() -> None:
    """GIVEN bench.py rewritten by the trial WHEN a frame points past base's
    3 lines but inside the new text THEN the frame and the new line count."""
    index = ClosureIndex.build(
        "+x = 1\n",
        {"bench.py": "a = 1\n"},
        at_commit={"bench.py": "a = 1\nb = 2\nreturn x\n", "gone.py": None},
    )
    found = classify(
        failure(
            tail(("/wt/bench.py", 3, None), last="NameError: name 'x' is not defined")
        ),
        closure=index,
        worktree=WT,
        tracked=("bench.py",),
        touched=("bench.py", "gone.py"),
    )

    assert found is not None
    assert (found.frames, found.message) == (
        (FeedbackFrame("bench.py", 3, None),),
        "name 'x' is not defined",
    )


def test_the_closure_skips_deny_listed_sources() -> None:
    index = ClosureIndex.build(
        "", {".env": "AKIAIOSFODNN7EXAMPLE = 1\n", "a.py": "b = 1\r\nc = 2\rd"}
    )

    assert "AKIAIOSFODNN7EXAMPLE" not in index.names
    assert index.lines["a.py"] == ("b = 1", "c = 2", "d")
    assert ".env" not in index.lines and index.complete


# ---------------------------------------------------------------------------
# B1/S1: a dotted name plus an alphabet on the raising line (comment or code)
# ---------------------------------------------------------------------------

import math  # noqa: E402
import string  # noqa: E402

from autonomous_ai_agents.execution.retry import (  # noqa: E402
    FREE_BUILTIN_TYPES,
    NAME_BUDGET_BITS,
    message_choice_bits,
)

_FIRST = string.ascii_lowercase
_REST = string.ascii_lowercase + string.digits + "_"
WIDE_ALPHABET = [a + b for a in _FIRST for b in _REST]  # 962 two-char names
WIDE_DIFF = "".join(f"+{name} = 0\n" for name in WIDE_ALPHABET)


def test_the_reviewers_dotted_alphabet_poc_recovers_nothing() -> None:
    """
    GIVEN the PoC: a 962-name alphabet defined in the diff, every name in a
        comment on the raising line, and a NameError whose name is a long
        dotted base-962 secret
    WHEN the crash is classified
    THEN the message is withheld (a comment is not code; the name is not a
        single identifier CPython prints)
    """
    secret = 0x1234567890ABCDEF
    parts = []
    n = secret
    while n:
        n, r = divmod(n, len(WIDE_ALPHABET))
        parts.append(WIDE_ALPHABET[r])
    dotted = ".".join(reversed(parts))
    raising = f"    raise NameError(msg)  # {' '.join(WIDE_ALPHABET)}"
    source = f"def main(rows):\n    msg = build()\n{raising}\n"
    index = ClosureIndex.build(
        WIDE_DIFF + "+" + source.replace("\n", "\n+"),
        {"bench.py": "def main(rows):\n    return rows\n"},
        at_commit={"bench.py": source},
    )
    found = classify(
        failure(
            tail(
                ("/wt/bench.py", 3, "main"),
                last=f"NameError: name '{dotted}' is not defined",
            )
        ),
        closure=index,
        worktree=WT,
        tracked=("bench.py",),
        touched=("bench.py",),
    )

    assert found is not None
    assert found.message is None
    assert found.withheld is not None


def test_a_dotted_name_whose_parts_are_only_in_a_comment_is_withheld() -> None:
    """A comment alphabet is not code, so the dotted parts are not on the line."""
    line = "    import aa  # " + " ".join(WIDE_ALPHABET)
    assert (
        message(
            "ModuleNotFoundError: No module named 'aa.ab.ac.ad'", line, diff=WIDE_DIFF
        )
        is None
    )


def test_a_dotted_name_whose_parts_are_all_in_code_still_exceeds_the_budget() -> None:
    """B1: even with all four parts as real code identifiers, a wide code line
    (25 selectable names) makes four parts cost 4*log2(25) > 16 bits."""
    wide = WIDE_ALPHABET[:25]
    line = "    return [" + ", ".join(wide) + "]"
    found = run(
        "ModuleNotFoundError: No module named 'aa.ab.ac.ad'", line, diff=WIDE_DIFF
    )

    assert found is not None
    assert found.message is None
    assert "bits" in (found.withheld or "")


def test_a_message_over_300_characters_after_cheap_names_is_withheld() -> None:
    """The 300-char cap still bites when three long names are cheap in bits
    (a tiny code candidate set) but together overflow the sent text."""
    names = ["q" * 60, "r" * 60, "s" * 60]
    line = "    " + ".".join(names[:1]) + " = " + " + ".join(names[1:])
    diff = "".join(f"+{name} = 0\n" for name in names)
    last = (
        f"AttributeError: module '{names[0]}' has no attribute '{names[1]}' "
        f"(consider renaming '/wt/x.py' since it has the same name as the "
        f"standard library module named '{names[2]}' and prevents importing "
        f"that standard library module)"
    )
    found = run(last, line, diff=diff)

    assert found is not None
    assert found.message is None
    assert "300" in (found.withheld or "")


def test_message_choice_bits_is_none_off_template_or_off_line() -> None:
    assert (
        message_choice_bits("TypeError", "'int' object is not callable", "    x()")
        is None
    )
    assert (
        message_choice_bits("NameError", "name 'zzz' is not defined", "    return q")
        is None
    )


def test_an_undotted_comment_alphabet_with_three_slots_is_withheld() -> None:
    """S1: attr_shadow has three name slots; a comment alphabet does not make
    them cheap because comments are not code identifiers."""
    last = (
        "AttributeError: module 'aa' has no attribute 'ab' (consider renaming "
        "'/wt/x.py' since it has the same name as the standard library module "
        "named 'ac' and prevents importing that standard library module)"
    )
    line = "    aa.ab  # " + " ".join(WIDE_ALPHABET)
    assert message(last, line, diff=WIDE_DIFF) is None


@pytest.mark.parametrize(
    ("value", "line"),
    [
        ("a.b.c.d.e", "    return a.b.c.d.e"),  # 5 dotted parts
        ("n" * 65, "    return " + "n" * 65),  # 65 characters
    ],
    ids=["five-parts", "sixty-five-chars"],
)
def test_a_name_slot_too_long_or_too_deep_is_withheld(value: str, line: str) -> None:
    diff = "".join(f"+{part} = 0\n" for part in {*value.split("."), value})
    assert (
        message(f"ModuleNotFoundError: No module named '{value}'", line, diff=diff)
        is None
    )


def test_the_bit_charge_of_every_sent_canary_stays_within_budget() -> None:
    """Across the canary slot messages (with their names moved on-line), every
    message classify sends carries no more free choice than the budget."""
    line = "    main.a3f(main=a3f) + int"
    sent = 0
    for last in CANARY_SLOTS:
        feedback = run(last, line, diff=ALPHABET)
        assert feedback is not None
        if feedback.message is None:
            continue
        sent += 1
        exc_type, body = last.split(": ", 1)
        bits = message_choice_bits(exc_type, feedback.message, line)
        assert bits is not None and bits <= NAME_BUDGET_BITS, (last, bits)
        assert feedback.bits == pytest.approx(bits)
    assert sent >= len(CANARY_SLOTS) - 1


# ---------------------------------------------------------------------------
# S2: exception-named builtins are not a free type slot
# ---------------------------------------------------------------------------


def test_no_builtin_exception_is_a_free_type_slot() -> None:
    assert "ValueError" not in FREE_BUILTIN_TYPES
    assert "int" in FREE_BUILTIN_TYPES and "str" in FREE_BUILTIN_TYPES
    assert math.log2(len(FREE_BUILTIN_TYPES)) < 7


def test_an_exception_type_slot_must_be_on_the_raising_line() -> None:
    last = "TypeError: unsupported operand type(s) for +: 'ValueError' and 'int'"

    off_line = message(last, "    rows + 1")
    on_line = message(last, "    ValueError + 1", diff="+ValueError = 1\n")

    assert off_line is None
    assert on_line == "unsupported operand type(s) for +: 'ValueError' and 'int'"


def test_two_free_builtin_type_slots_are_sent() -> None:
    sent = message(
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'", "    1 + 'a'"
    )
    assert sent == "unsupported operand type(s) for +: 'int' and 'str'"


# ---------------------------------------------------------------------------
# S3: a relative frame path resolves through the working_dir and realpath
# ---------------------------------------------------------------------------


def test_a_relative_frame_resolves_from_the_working_dir() -> None:
    """GIVEN a workload whose cwd is ``sub`` and a frame printed ``bench.py``
    THEN it is read as ``sub/bench.py`` at the trial's commit."""
    index = ClosureIndex.build(
        "+x = 1\n",
        {"sub/bench.py": "a = 1\n"},
        at_commit={"sub/bench.py": "a = 1\nreturn x\n"},
    )
    found = classify(
        failure(tail(("bench.py", 2, None), last="NameError: name 'x' is not defined")),
        closure=index,
        worktree=WT,
        tracked=("sub/bench.py",),
        touched=("sub/bench.py",),
        working_dir="sub",
    )

    assert found is not None
    assert found.frames == (FeedbackFrame("sub/bench.py", 2, None),)


def test_frame_paths_are_compared_through_realpath(tmp_path: Path) -> None:
    """GIVEN a worktree reached by a symlink (as macOS /tmp -> /private/tmp)
    THEN an absolute frame under the real path still resolves, not dropped."""
    import os

    real = os.path.join(os.path.realpath(str(tmp_path)), "wt")
    os.makedirs(real)
    link = os.path.join(str(tmp_path), "link")
    os.symlink(real, link)
    index = ClosureIndex.build("", {"bench.py": "def main(rows):\n    return rows\n"})
    found = classify(
        failure(
            tail(
                (os.path.join(real, "bench.py"), 2, "main"),
                last="NameError: name 'rows' is not defined",
            )
        ),
        closure=index,
        worktree=PurePosixPath(link),
        tracked=("bench.py",),
        touched=(),
    )

    assert found is not None
    assert found.frames == (FeedbackFrame("bench.py", 2, "main"),)
    assert found.message == "name 'rows' is not defined"


# ---------------------------------------------------------------------------
# Re-review 2: frame bit budget, forged plural slots, documented withholds
# ---------------------------------------------------------------------------


def test_a_forged_plural_that_cpython_never_prints_is_withheld() -> None:
    """Item 3: ``S`` and ``WERE`` must agree with the numbers (1 -> singular)."""
    singular = message(
        "TypeError: main() takes 1 positional argument but 2 were given",
        "    main(1, 2)",
    )
    assert singular == "main() takes 1 positional argument but 2 were given"
    assert (
        message(
            "TypeError: main() takes 1 positional arguments but 2 was given",
            "    main(1, 2)",
        )
        is None
    )
    assert (
        message(
            "TypeError: main() takes 2 positional argument but 1 was given",
            "    main(1, 2)",
        )
        is None
    )


def test_a_single_argument_singular_form_is_sent() -> None:
    sent = message(
        "TypeError: main() takes 2 positional arguments but 1 was given", "    main(1)"
    )
    assert sent == "main() takes 2 positional arguments but 1 was given"


@pytest.mark.parametrize(
    "last",
    [
        "TypeError: Runner.go() takes 2 positional arguments but 3 were given",
        "AttributeError: 'Runner' object has no attribute 'go'",
    ],
    ids=["method-call", "attr-on-instance"],
)
def test_a_method_form_whose_class_is_not_on_the_line_is_withheld(last: str) -> None:
    """Item 4 (documentation): the commonest method-call and instance-attribute
    forms are withheld because the class name is not on the raising line
    (``Runner.go()`` raised at ``r.go(1, 2)``). Kept deliberately; this pins it
    so the live retry-rate numbers are read with it in mind."""
    source = (
        "class Runner:\n    def go(self, a):\n        pass\nr = Runner()\nr.go(1, 2)\n"
    )
    index = ClosureIndex.build("", {"bench.py": source})
    found = classify(
        failure(tail(("/wt/bench.py", 5, "<module>"), last=last)),
        closure=index,
        worktree=WT,
        tracked=("bench.py",),
        touched=(),
    )

    assert found is not None
    assert found.message is None


def test_a_frame_budget_keeps_only_as_many_frames_as_fit() -> None:
    """Item 1: under the editor's write limits a frame costs ~46 bits (a huge
    diff alphabet of function names, a 262,144-line touched file), so the
    budget keeps the innermost frames and drops the rest."""
    from autonomous_ai_agents.execution.retry import FRAME_BUDGET_BITS

    blank = "\n" * 262144
    alphabet = "".join(f"+fn{i} = 0\n" for i in range(70000))
    index = ClosureIndex.build(
        alphabet, {"bench.py": "x = 1\n"}, at_commit={"bench.py": blank}
    )
    frames = tuple(("/wt/bench.py", 262100 + i, f"fn{i}") for i in range(3))
    found = classify(
        failure(tail(*frames, last="NameError: name 'fn0' is not defined")),
        closure=index,
        worktree=WT,
        tracked=("bench.py",),
        touched=("bench.py",),
    )

    assert found is not None
    assert found.frame_bits <= FRAME_BUDGET_BITS
    assert 1 <= len(found.frames) < 3  # the wide frames do not all fit


def test_a_huge_line_count_frame_is_charged_within_budget() -> None:
    """A 262,144-line touched file's single frame is kept but charged its true
    ~18-bit line cost, not treated as free."""
    from autonomous_ai_agents.execution.retry import FRAME_BUDGET_BITS

    blank = "\n" * 262144
    index = ClosureIndex.build(
        "+def solo(): pass\n", {"bench.py": "x = 1\n"}, at_commit={"bench.py": blank}
    )
    found = classify(
        failure(
            tail(
                ("/wt/bench.py", 262144, "solo"),
                last="NameError: name 'solo' is not defined",
            )
        ),
        closure=index,
        worktree=WT,
        tracked=("bench.py",),
        touched=("bench.py",),
    )

    assert found is not None
    assert found.frames == (FeedbackFrame("bench.py", 262144, "solo"),)
    assert 17.0 < found.frame_bits <= FRAME_BUDGET_BITS


def test_the_worst_case_per_attempt_is_within_the_d13_budget() -> None:
    """Item 1: the whole attempt (frames + message names + numbers + template)
    computed from the module's own constants is at most D13's 147 bits."""
    from autonomous_ai_agents.execution.retry import (
        MAX_ATTEMPT_BITS,
        worst_case_attempt_bits,
    )

    assert MAX_ATTEMPT_BITS == 147.0
    assert worst_case_attempt_bits() <= MAX_ATTEMPT_BITS


def test_a_realpath_error_drops_the_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    """Item 2: any ValueError/OSError from realpath drops the frame, not raises
    (the NUL guard covers the common case; this covers the rest)."""
    import os.path

    def boom(*_: str) -> str:
        raise OSError("name too long")

    # relpath runs only inside _relative, after the worktree root is resolved
    monkeypatch.setattr(os.path, "relpath", boom)
    found = classify(
        failure(
            tail(
                ("/wt/bench.py", 2, "main"),
                last="NameError: name 'rows' is not defined",
            )
        ),
        closure=closure("    return rows"),
        worktree=WT,
        tracked=("bench.py",),
        touched=(),
    )

    assert found is not None
    assert found.frames == ()
