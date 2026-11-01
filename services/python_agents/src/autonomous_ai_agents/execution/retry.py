"""Which workload crashes earn a retry, and what of the crash the editor may see (D12, D13).

Trials are confined for writes only, so editor-written code can read a secret
and raise it. ``classify`` therefore sends nothing a trial chose freely: every
character is fixed interpreter text, a name the API has already seen (the
*closure*: identifiers of the trial's diff and of the tracked, non-deny-listed
sources at base), or a short number.

- **Frames:** ``(path, function, line)`` only, innermost first: the path tracked
  at base or touched, inside the worktree and not deny-listed; the function in
  the closure (or ``<module>`` and its kin); ``1 <= line <=`` the file's line
  count at the trial's commit. Source lines are never sent. Each kept frame is
  not free: a diff can mint any identifier and a 256 KiB touched file holds
  262,144 lines, so a frame carries ``log2(paths) + log2(functions) +
  log2(lines)`` bits (up to ~46 under the editor's write limits). Frames are
  kept innermost-first only while ``FRAME_BUDGET_BITS`` holds; the rest drop.
- **Message:** only on a full match of a template below, derived by raising
  each error uncaught under CPython 3.8.20-3.14.6 (``test_retry_templates``
  replays them). Every name and type slot, each dotted part, is in the closure
  and a code identifier (never a comment or string) on the innermost kept
  frame's source line at the trial's commit; a type slot may instead be a
  builtin non-exception type. Plural slots (``s``/``was``/``were``) must agree
  with the numbers, as CPython prints them. The name and type slots together
  carry at most ``NAME_BUDGET_BITS``. Numbers: at most 2, of at most 4 digits.
  Paths (``<path>``) and interpreter suggestions (``Did you mean``: computed
  from the runtime namespace, which the trial controls) are never sent. The
  sent text is printable ASCII of at most 300 characters. Otherwise, or past
  the closure's source cap, type and frames only, with the reason in
  ``withheld``.

A method-call or instance-attribute form whose class name is not on the raising
line is withheld (``Runner.go() takes ...`` raised at ``r.go(1, 2)``, or
``'Runner' object has no attribute 'go'`` at ``r.go``): kept deliberately, so
the live retry-rate is read with it in mind (``test_retry`` pins both).

Residual (worst case per attempt, from the constants below):
``FRAME_BUDGET_BITS`` + ``NAME_BUDGET_BITS`` + 2 numbers (``2*log2(10000)``) +
template (``log2(len(TEMPLATES))``) = about 146 bits, at most ``MAX_ATTEMPT_BITS``
= 147 bits = D13's about 18 bytes an attempt (``worst_case_attempt_bits``).
"""

from __future__ import annotations

import builtins
import io
import keyword
import math
import os
import re
import tokenize
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import PurePath

from autonomous_ai_agents.common.paths import READ_DENY_PATTERNS, matches_pattern
from autonomous_ai_agents.execution.crash import CrashFrame, parse_traceback
from autonomous_ai_agents.execution.procrun import RunFailure

FIXABLE = frozenset(
    "SyntaxError IndentationError TabError ImportError ModuleNotFoundError "
    "NameError UnboundLocalError TypeError AttributeError".split()
)
MAX_FRAMES, MAX_MESSAGE_CHARS, MAX_NAME_CHARS = 3, 300, 64
MAX_DIGITS = 4
MAX_NUMBERS = 2
MAX_ATTEMPT_BITS = 147.0
"""D13's ceiling: about 18 bytes of free adversary choice an attempt may carry
to the API (``147 / 8``). The budgets below sum to at most this
(``worst_case_attempt_bits``), checked by a test."""
FRAME_BUDGET_BITS = 99.0
"""Most bits of free choice the kept frames of one message may carry together
(D13). A frame is ``log2(candidate paths) + log2(candidate functions) +
log2(the file's line count)``; under the editor's write limits (``config.py``:
10 files, 256 KiB each, 1 MiB total) that is up to ~46 bits, so three frames
(~139) would blow D13's ceiling. Frames are kept innermost-first while this
holds. Set so frames + ``NAME_BUDGET_BITS`` + two 4-digit numbers + the
template choice stay within ``MAX_ATTEMPT_BITS``."""
NAME_BUDGET_BITS = 16.0
"""Most bits of free adversary choice a sent message may carry through its name
and type slots (D13: the residual is a selection among values the API has
already seen, not new bytes). Each sent name part is charged ``log2`` of the
set it is drawn from -- the code identifiers on the raising line (comments and
string literals excluded), or ``FREE_BUILTIN_TYPES`` for a builtin type slot --
and the message is withheld past this budget. So a sent message carries at most
16 bits (2 bytes) of free choice, whatever the diff writes on the raising line."""
CLOSURE_MAX_SOURCE_BYTES = 8 * 1024 * 1024
"""``RETRY_CLOSURE_MAX_SOURCE_BYTES``' default; U2 owns the setting, U6 passes it."""
FIXED_FUNCTIONS = frozenset(
    "<module> <lambda> <listcomp> <dictcomp> <setcomp> <genexpr>".split()
)
_INTERNAL_TYPES = frozenset(
    "NoneType NotImplementedType ellipsis function method module generator "
    "coroutine builtin_function_or_method cell code".split()
)
BUILTIN_TYPES = frozenset(
    {name for name, value in vars(builtins).items() if isinstance(value, type)}
    | _INTERNAL_TYPES
)
FREE_BUILTIN_TYPES = frozenset(
    {
        name
        for name, value in vars(builtins).items()
        if isinstance(value, type) and not issubclass(value, BaseException)
    }
    | _INTERNAL_TYPES
)
"""Builtin type names a type slot may carry without being on the raising line.
Exception classes are excluded (S2): a ``'ValueError' object`` message would
otherwise pick a secret from among ~60 exception names for free, so an
exception-named type slot must be on the line like any other name."""
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NEWLINE = re.compile(r"\r\n|\r|\n")
# CPython never prints X, T or U dotted (the undefined name, an attribute, an
# operand type); Y, Y2 and F (module and qualified-function names) carry at most
# four dotted parts. A per-slot character cap is enforced in ``_charge``.
_ID = r"[A-Za-z_][A-Za-z0-9_]*"
_DOTTED = rf"{_ID}(?:\.{_ID}){{0,3}}"
_OPS = "+= -= *= /= //= %= **= <<= >>= &= |= ^= @= ** // << >> + - * / % & | ^ @"
_BLOCKS = (
    "function definition|class definition|'(?:if|elif|else|for|while|with|try|except"
    r"|except\*|finally|match|case)' statement"
)
_SLOTS = {
    "X": f"(?P<n_x>{_ID})",
    "Y": f"(?P<n_y>{_DOTTED})",
    "Y2": f"(?P<n_y2>{_DOTTED})",
    "F": f"(?P<n_f>{_DOTTED})",
    "T": f"(?P<t_t>{_ID})",
    "U": f"(?P<t_u>{_ID})",
    # Two number slots, N and M, each at most once a template (a repeated group
    # name does not compile): at most 2 numbers of at most 4 digits, no leading 0.
    "N": "(?P<d_n>0|[1-9][0-9]{0,3})",
    "M": "(?P<d_m>0|[1-9][0-9]{0,3})",
    "PATH": "(?P<p_path>(?!consider renaming ).+)",
    "HINT": rf"(?P<h_hint>\. Did you (?:mean:? |forget to import )'{_ID}'\?)?",
    "OP": "(?:" + "|".join(re.escape(op) for op in _OPS.split()) + r"|\*\* or pow\(\))",
    # Plural slots are captured (prefix ``x``) so they can be checked against the
    # numbers after the match: CPython never prints "1 arguments" or "2 was".
    "S": "(?P<x_s>s?)",
    "WERE": "(?P<x_were>was|were)",
    "BR": r"[(\[{]",
    "BLOCK": f"(?:{_BLOCKS})",
}
_PLACEHOLDER = re.compile(r"\{([A-Z0-9]+)\}")


@dataclass(frozen=True)
class Template:
    """One CPython message form, printed by ``3.since`` to ``3.until``."""

    id: str
    types: frozenset[str]
    text: str
    since: int = 8
    until: int = 14
    pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        parts = _PLACEHOLDER.split(self.text)
        regex = "".join(
            _SLOTS[p] if i % 2 else re.escape(p) for i, p in enumerate(parts)
        )
        object.__setattr__(self, "pattern", re.compile(regex))

    def matches(self, exc_type: str, message: str) -> bool:
        return exc_type in self.types and self.pattern.fullmatch(message) is not None


_TABLE = """\
name_undefined NameError 8-14 name '{X}' is not defined{HINT}
free_old NameError 8-10 free variable '{X}' referenced before assignment in enclosing scope
free NameError 11-14 cannot access free variable '{X}' where it is not associated with a value in enclosing scope
local_old UnboundLocalError 8-10 local variable '{X}' referenced before assignment
local UnboundLocalError 11-14 cannot access local variable '{X}' where it is not associated with a value
import_name ImportError 8-14 cannot import name '{X}' from '{Y}' ({PATH}){HINT}
import_cycle ImportError 8-14 cannot import name '{X}' from partially initialized module '{Y}' (most likely due to a circular import) ({PATH})
import_rename ImportError 13-14 cannot import name '{X}' from '{Y}' (consider renaming '{PATH}' if it has the same name as a library you intended to import)
no_module ModuleNotFoundError 8-14 No module named '{Y}'
not_package ModuleNotFoundError 8-14 No module named '{Y}'; '{Y2}' is not a package
attr_object AttributeError 8-14 '{T}' object has no attribute '{X}'{HINT}
attr_module AttributeError 8-14 module '{Y}' has no attribute '{X}'{HINT}
attr_type AttributeError 8-14 type object '{T}' has no attribute '{X}'{HINT}
attr_shadow AttributeError 13-14 module '{Y}' has no attribute '{X}' (consider renaming '{PATH}' since it has the same name as the standard library module named '{Y2}' and prevents importing that standard library module)
positional TypeError 8-14 {F}() takes {N} positional argument{S} but {M} {WERE} given
operand TypeError 8-14 unsupported operand type(s) for {OP}: '{T}' and '{U}'
keyword TypeError 8-14 {F}() got an unexpected keyword argument '{X}'{HINT}
invalid_syntax SyntaxError 8-14 invalid syntax
unexpected_indent IndentationError 8-14 unexpected indent
unindent IndentationError 8-14 unindent does not match any outer indentation level
tabs TabError 8-14 inconsistent use of tabs and spaces in indentation
eof SyntaxError 8-9 unexpected EOF while parsing
indented_block IndentationError 8-9 expected an indented block
expected_colon SyntaxError 10-14 expected ':'
never_closed SyntaxError 10-14 '{BR}' was never closed
comma SyntaxError 10-14 invalid syntax. Perhaps you forgot a comma?
indented_block_after IndentationError 10-14 expected an indented block after {BLOCK} on line {N}
"""
"""``id type since-until text``: one row per form, ``3.since`` to ``3.until``."""


def _row(row: str) -> Template:
    name, kind, span, text = row.split(" ", 3)
    since, until = span.split("-")
    return Template(name, frozenset({kind}), text, int(since), int(until))


TEMPLATES: tuple[Template, ...] = tuple(_row(row) for row in _TABLE.splitlines())


@dataclass(frozen=True)
class ClosureIndex:
    """The names the API has seen, and each readable source's lines at the trial's commit."""

    names: frozenset[str]
    lines: Mapping[str, tuple[str, ...]]
    complete: bool

    @classmethod
    def build(
        cls,
        diff: str,
        sources: Mapping[str, str],
        *,
        at_commit: Mapping[str, str | None] | None = None,
        max_source_bytes: int = CLOSURE_MAX_SOURCE_BYTES,
    ) -> ClosureIndex:
        """``sources``: tracked texts at base; ``at_commit``: touched paths' texts at
        the trial's commit (``None``: deleted). Deny-listed paths are skipped;
        past ``max_source_bytes`` (both maps together) the index is incomplete."""
        touched = at_commit or {}
        view: dict[str, str | None] = {**sources, **touched}
        names, total = set(_IDENT.findall(diff)), 0
        lines: dict[str, tuple[str, ...]] = {}
        for path in sorted(view):
            if _denied(path):
                continue
            base, text = sources.get(path), view[path]
            total += _size(base) + (_size(text) if path in touched else 0)
            if total > max_source_bytes:
                return cls(frozenset(names), lines, False)
            names.update(_IDENT.findall(base or ""))
            if text is not None:
                split = _NEWLINE.split(text)
                lines[path] = tuple(split[:-1] if split[-1] == "" else split)
        return cls(frozenset(names), lines, True)


def _size(text: str | None) -> int:
    return 0 if text is None else len(text.encode())


@dataclass(frozen=True)
class FeedbackFrame:
    path: str
    line: int
    function: str | None


@dataclass(frozen=True)
class TrialFeedback:
    """What the retry prompt may carry; ``withheld`` says why a message is not sent."""

    exc_type: str
    frames: tuple[FeedbackFrame, ...]
    message: str | None
    template: str | None
    withheld: str | None = None
    bits: float = field(default=0.0, compare=False)
    """The free-choice bits the sent message carries (``0`` when none is sent)."""
    frame_bits: float = field(default=0.0, compare=False)
    """The free-choice bits the kept frames carry, at most ``FRAME_BUDGET_BITS``."""

    def render(self) -> str:
        head = (
            self.exc_type
            if self.message is None
            else f"{self.exc_type}: {self.message}"
        )
        return "\n".join([head, *(_where(frame) for frame in self.frames)])


def _where(frame: FeedbackFrame) -> str:
    text = f'  File "{frame.path}", line {frame.line}'
    return text if frame.function is None else f"{text}, in {frame.function}"


def classify(
    failure: RunFailure,
    *,
    closure: ClosureIndex,
    worktree: PurePath,
    tracked: Collection[str],
    touched: Collection[str],
    excluded_workloads: Collection[str] = (),
    working_dir: str = ".",
) -> TrialFeedback | None:
    """Feedback for a fixable crash of an included workload's own run, else ``None``.

    ``working_dir`` is the workload's ``cwd`` relative to the worktree: a
    relative frame path (3.8 prints the main script relative to the cwd) is
    read there, and both it and the worktree go through ``realpath`` so a
    symlinked root (macOS ``/tmp`` -> ``/private/tmp``) does not drop frames."""
    if failure.kind != "exit" or failure.workload_id in (None, *excluded_workloads):
        return None
    crash = parse_traceback(failure.exit_tail)
    if crash is None or crash.exc_type not in FIXABLE:
        return None
    root = os.path.realpath(str(worktree))
    base = os.path.realpath(os.path.join(root, working_dir))
    allowed = {*tracked, *touched}
    readable = [
        FeedbackFrame(rel, frame.line, frame.function)
        for frame in crash.frames
        if (rel := _relative(frame.path, root, base)) is not None
        and _readable(frame, rel, allowed, closure)
    ]
    frames, frame_bits = _within_budget(readable, allowed, closure)
    line = closure.lines[frames[-1].path][frames[-1].line - 1] if frames else None
    message, template, withheld, bits = _message(
        crash.exc_type, crash.message, closure, line
    )
    return TrialFeedback(
        crash.exc_type, frames, message, template, withheld, bits, frame_bits
    )


def _within_budget(
    readable: list[FeedbackFrame], allowed: set[str], closure: ClosureIndex
) -> tuple[tuple[FeedbackFrame, ...], float]:
    """Keep frames innermost-first while ``FRAME_BUDGET_BITS`` holds; drop the rest.

    A frame is not free: a diff mints identifiers and a 256 KiB file holds
    262,144 lines, so each costs ``log2(candidate paths) + log2(candidate
    functions) + log2(the file's line count)`` bits (D13)."""
    paths = len([p for p in allowed if p in closure.lines]) or 1
    functions = len(closure.names) + len(FIXED_FUNCTIONS)
    chosen: list[FeedbackFrame] = []
    spent = 0.0
    for frame in reversed(readable):  # innermost first
        cost = _frame_bits(frame, paths, functions, closure)
        if len(chosen) >= MAX_FRAMES or spent + cost > FRAME_BUDGET_BITS:
            break
        chosen.append(frame)
        spent += cost
    return tuple(reversed(chosen)), spent


def _frame_bits(
    frame: FeedbackFrame, paths: int, functions: int, closure: ClosureIndex
) -> float:
    bits = math.log2(paths) + math.log2(len(closure.lines[frame.path]) or 1)
    if frame.function is not None:
        bits += math.log2(functions or 1)
    return bits


def worst_case_attempt_bits() -> float:
    """The free-choice bits a single attempt can carry, from the module's own
    constants: frames + message names + two 4-digit numbers + the template
    choice. Plural slots are pinned to the numbers, so they are free of charge.
    A test asserts this stays within ``MAX_ATTEMPT_BITS`` (D13)."""
    numbers = MAX_NUMBERS * math.log2(10**MAX_DIGITS)
    return FRAME_BUDGET_BITS + NAME_BUDGET_BITS + numbers + math.log2(len(TEMPLATES))


def _denied(path: str) -> bool:
    return any(matches_pattern(path, pattern) for pattern in READ_DENY_PATTERNS)


def _relative(path: str, root: str, base: str) -> str | None:
    """A printed frame path as a repo-relative, ``/``-separated path, or ``None``.

    ``root`` and ``base`` are both realpath'd; an absolute path is taken as is,
    a relative one is joined onto ``base`` (the workload's cwd). A NUL byte, or
    any ``realpath`` error, drops the frame rather than raising."""
    if "\x00" in path:
        return None
    full = path if os.path.isabs(path) else os.path.join(base, path)
    try:
        real = os.path.realpath(full)
        rel = os.path.relpath(real, root)
    except (ValueError, OSError):
        return None
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return None
    return rel.replace(os.sep, "/")


def _readable(
    frame: CrashFrame, rel: str, allowed: set[str], closure: ClosureIndex
) -> bool:
    lines = closure.lines.get(rel)
    return (
        rel in allowed
        and not _denied(rel)
        and lines is not None
        and 1 <= frame.line <= len(lines)
        and (
            frame.function is None
            or frame.function in FIXED_FUNCTIONS
            or frame.function in closure.names
        )
    )


def _message(
    exc_type: str, message: str | None, closure: ClosureIndex, line: str | None
) -> tuple[str | None, str | None, str | None, float]:
    """``(sent text, template id, withheld reason, free-choice bits)``."""
    if message is None:
        return None, None, None, 0.0
    if not closure.complete:
        return None, None, "the source closure is incomplete", 0.0
    if not (message.isascii() and message.isprintable()):
        return None, None, "the message is not printable ASCII", 0.0
    hits = ((t, t.pattern.fullmatch(message)) for t in TEMPLATES if exc_type in t.types)
    template, found = next(((t, m) for t, m in hits if m is not None), (None, None))
    if template is None or found is None:
        return None, None, "no CPython template matches the message", 0.0
    if not _plural_agrees(found):
        return None, None, "a plural form CPython never prints for these numbers", 0.0
    code = _code_identifiers(line)
    sent, end, bits = [], 0, 0.0
    for group, value in found.groupdict().items():
        if value is None:
            continue
        if group[0] in "nt":
            if len(value) > MAX_NAME_CHARS:
                return None, None, f"a name is longer than {MAX_NAME_CHARS} chars", 0.0
            cost = _charge(value, group[0] == "t", closure, code)
            if cost is None:
                reason = "a name is not in the closure and on the raising line"
                return None, None, reason, 0.0
            bits += cost
        if group[0] in "ph":
            sent += [
                message[end : found.start(group)],
                "<path>" if group[0] == "p" else "",
            ]
            end = found.end(group)
    if bits > NAME_BUDGET_BITS:
        reason = f"the message would carry more than {NAME_BUDGET_BITS:g} bits"
        return None, None, reason, 0.0
    text = "".join([*sent, message[end:]])
    if len(text) > MAX_MESSAGE_CHARS:
        reason = f"the message is longer than {MAX_MESSAGE_CHARS} characters"
        return None, None, reason, 0.0
    return text, template.id, None, bits


def _plural_agrees(found: re.Match[str]) -> bool:
    """CPython prints the singular for 1: ``s`` is empty iff ``N == 1``, ``were``
    is ``was`` iff ``M == 1``. A mismatch (``1 arguments``, ``2 was``) is a
    forgery and withholds the message. ``N`` pairs with ``S``, ``M`` with ``WERE``."""
    groups = found.groupdict()
    pairs = (("x_s", "d_n", "", "s"), ("x_were", "d_m", "was", "were"))
    for slot, number, one, many in pairs:
        value = groups.get(slot)
        if value is None:
            continue
        count = groups.get(number)
        if count is not None and value != (one if count == "1" else many):
            return False
    return True


def _code_identifiers(line: str | None) -> set[str]:
    """The non-keyword identifiers CPython could print from ``line``: NAME tokens
    in code only, never a name inside a comment or a string literal (a comment
    alphabet is not something the interpreter names)."""
    names: set[str] = set()
    if not line:
        return names
    try:
        for token in tokenize.generate_tokens(io.StringIO(line).readline):
            if token.type == tokenize.NAME and not keyword.iskeyword(token.string):
                names.add(token.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # a single physical line need not be a complete statement
    return names


def _charge(
    value: str, is_type: bool, closure: ClosureIndex, code: set[str]
) -> float | None:
    """The bits a name/type slot's value costs, or ``None`` when it is not a
    value the API has seen (not a free builtin type, and not both in the
    closure and a code identifier on the raising line)."""
    cost = 0.0
    for part in value.split("."):
        if is_type and part in FREE_BUILTIN_TYPES:
            cost += math.log2(len(FREE_BUILTIN_TYPES))
        elif part in closure.names and part in code:
            cost += math.log2(len(code))  # len(code) >= 1, so a sole name is 0 bits
        else:
            return None
    return cost


def message_choice_bits(exc_type: str, message: str, line: str) -> float | None:
    """The free-choice bits ``message`` would carry on ``line`` (for tests): the
    same charge ``classify`` applies, over a closure that holds every token."""
    closure = ClosureIndex(frozenset(_IDENT.findall(message + " " + line)), {}, True)
    code = _code_identifiers(line)
    hits = ((t, t.pattern.fullmatch(message)) for t in TEMPLATES if exc_type in t.types)
    template, found = next(((t, m) for t, m in hits if m is not None), (None, None))
    if template is None or found is None:
        return None
    bits = 0.0
    for group, value in found.groupdict().items():
        if value is not None and group[0] in "nt":
            cost = _charge(value, group[0] == "t", closure, code)
            if cost is None:
                return None
            bits += cost
    return bits
