"""UEQ (O71 item 2): the record-only API equivalence gate of the X2-DT runs.

Built from the equivalence audit (O65 item 1,
``.claude/handoff/step3/idea-lab/w2-sprint/equivalence-audit/``): its
generators (``gen_tomli``, ``gen_sql``, ``gen_md``), corpus mix
(``corpus.py``) and runner configurations (``runner.py``) are ported here
for the four development libraries, sqlparse, tomli, mistune and markdown.
It decides nothing: a record is data on a row, never an input to a verdict.

**The corpus** (``corpus`` in the child, once per base): seeded and fixed,
three sources, each case ``[source, mode, text]``:

- ``generator``: the audit's generator stream, draw for draw (``Random(seed)``,
  the mode drawn first, as ``corpus.py``);
- ``seed``: the library's own test data from the base tree (tomli's
  ``tests/data`` documents; sqlparse's ``tests/files`` scripts and the
  string literals of its tests; mistune's CommonMark examples and fixture
  examples; markdown's ``tests/{basic,extensions,misc,pl}`` texts and the
  literals of ``tests/test_syntax``), read as data (``ast.parse``, never
  run), at most ``seed_cap`` of them, a seeded sample when there are more;
- ``workload``: byte mutations of windows of the benchmark's own input
  (the base tree's ``benchmarks/bench_<lib>.py``, imported in the sandbox,
  its document built with the seed its ``main`` uses).

**The fingerprint** (``type-aware``): per call, ``repr`` of the output and
the tree of its exact types (dict keys and values, sequences, scalars by
module and qualified name); on invalid input the exception's module,
qualified name and message. ``json`` (``json.dumps(default=str)``, the
frozen judge's style) exists only to show what it misses.

**Where it runs.** Every library call runs in a child process, this file
run by path with ``python -s -S -B -P`` (no user site, no site, no
bytecode, no script or working directory on the path, so its top level
imports the standard library only; not ``-I``, whose ``-E`` would drop
``PYTHONHASHSEED``), through the engine's own ``run_once`` in the
``required`` sandbox: no network, writes only to the run's scratch,
``PYTHONHASHSEED=0`` (``sandbox.FORCED``; the child refuses to start when
``sys.flags.hash_randomization`` is set), a per-input ``SIGALRM`` of
``alarm_s`` and a batch timeout. Generators and adapter files run there too,
so an engine-written generator (the proposal's next step) is confined the
same way. The child's result file is opened ``O_NOFOLLOW | O_NONBLOCK``,
must be a plain file, and is read to at most ``MAX_RESULT_BYTES``.

**Record-only bound.** The trial's code runs in the evaluating process: it
can tell the gate from the benchmark (``sys.argv``) and answer as the base
does, write the result file itself, and read the base tree. Every text it
can reach a row with is redacted and clipped, but before the gate may
decide anything the fingerprints must be computed outside its process.

**The record** (``Equivalence.record``, ``equivalence_record``): the base's
hashes once per base, then per trial tree the cases compared, the
mismatches, their groups (``source/mode``) and kinds, the first mismatch
minimised (delta debugging on the text, both trees re-run per round, under
``minimise_s``) and clipped, the fingerprint, the seconds and whether a
timeout cut it. ``mismatches`` is ``None`` whenever nothing was compared;
a library without an adapter records ``no generator``, never a pass.

**The rows** (``equiv_rows``): after the engine has finished, over the
run's archive (the run row's ``kept_diffs``, ``inconclusive_diffs`` and
``delivered_patch`` entries and the files ``x2_patches`` wrote), each diff
checked (one file under the patch directory, its sha256, not truncated) and
applied with ``git apply`` to a fresh copy of its base, exported from the
run's clone with ``git archive``. Keyed by trial id, plus ``delivered`` and
``base``.
"""

from __future__ import annotations

import argparse
import ast
import errno
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import textwrap
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import FrameType, ModuleType
from typing import TYPE_CHECKING, Final, Literal, Protocol

if TYPE_CHECKING:  # the parent side only; the child imports the stdlib alone
    from autonomous_ai_agents.execution.procrun import RunSample
    from autonomous_ai_agents.execution.sandbox import SandboxPolicy

CHILD: Final = Path(__file__).resolve()
LIBRARIES: Final = ("sqlparse", "tomli", "mistune", "markdown")
FINGERPRINT: Final = "type-aware"
Fingerprint = Literal["type-aware", "json"]
COMPARED: Final = "compared"
NO_GENERATOR: Final = "no generator"
ERROR: Final = "error"
TIMEOUT: Final = "timeout"
NOT_APPLIED: Final = "not applied"
CLIP: Final = 160  # characters of each counterexample field
SHOW: Final = 4 * CLIP  # characters of a fingerprint the child hands back
MAX_DIFF_BYTES: Final = 8 * 1024 * 1024
MAX_RESULT_BYTES: Final = (
    8 * 1024 * 1024
)  # out.json; an honest full tomli one is ~2.7 MB
MAX_ROUNDS: Final = 48
MIN_EVAL_S: Final = 5.0  # the least a minimisation run gets, whatever is left
ERROR_CHARS: Final = 300  # a child's or launcher's error text on a row
RANDOMISED: Final = (
    "hash randomisation is on: the child needs PYTHONHASHSEED=0 and no -E or -I"
)
CHILD_FLAGS: Final = ("-s", "-S", "-B", "-P")  # not -I: its -E drops PYTHONHASHSEED
MAX_DEPTH: Final = 100  # containers deep in a type tree (tomli nests at most 100)
RECORD_KEYS: Final = ("status", "fingerprint", "cases", "mismatches", "groups", "kinds",
                      "timeouts", "counterexample", "seconds", "timed_out", "error",
                      "corpus_sha256")  # fmt: skip
"""Every record's keys (``equiv_rows`` adds ``trial_id``)."""
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")

Case = list[str]  # [source, mode, text]
Call = Callable[[], object]
Evaluate = Callable[[str, str], list[Call]]


class Adapter(Protocol):
    """One library's corpus and calls (the four below; an adapter file
    names its own as ``ADAPTER``)."""

    package: str
    src: bool  # the package sits under ``src/``
    workload_mode: str
    unit: str  # the separator of the workload input's units

    def generate(self, rng: random.Random) -> tuple[str, str]: ...
    def seeds(self, tree: Path) -> list[tuple[str, str]]: ...
    def workload(self, tree: Path) -> str | None: ...
    def mutate(self, rng: random.Random, text: str) -> str: ...
    def evaluator(self) -> Evaluate: ...


# ===========================================================================
# The child side: generators (ported from the audit, draw for draw)
# ===========================================================================


def _mutator(rare: Sequence[str], insert: float, delete: float, splice: int,
             replace: float | None = None) -> Callable[[random.Random, str], str]:  # fmt: skip
    """The audit's byte mutator: 1-3 edits, each an insert of a rare token,
    a delete, (tomli only) a replace, or a splice of up to ``splice``."""

    def mutate(rng: random.Random, s: str) -> str:
        out = list(s)
        for _ in range(rng.randint(1, 3)):
            if not out:
                out.append(rng.choice(rare))
                continue
            i = rng.randrange(len(out))
            op = rng.random()
            if op < insert:
                if replace is None:
                    out[i:i] = list(rng.choice(rare))
                else:
                    out.insert(i, rng.choice(rare))
            elif op < delete:
                del out[i]
            elif replace is not None and op < replace:
                out[i] = rng.choice(rare)
            else:
                j = min(len(out), i + rng.randint(1, splice))
                out[i:i] = out[i:j]
        return "".join(out)

    return mutate


# ---- tomli: s3-equivalence's array fuzzer, then whole documents ----------

T_INTS: Final = ["0", "-0", "+0", "7", "-12", "+3", "1_000", "007", "0x1F", "0o7",
                 "0b1", "123456789012345678901234567890", "1e3", "1.5", "inf", "nan",
                 "-", "+", "1979-05-27", "00", "01"]  # fmt: skip
T_STR_BODIES: Final = ["", "a", "a b", "it's", 'say "hi"', "tab\there", "é", "\U0001f600",
                       "\\n", "\\u00e9", "\\", "\x7f", "\x00", "\x1f", "\x0b", "\x0c",
                       "comma, inside", "]", "[", "#", " ", " ", "\ud800"]  # fmt: skip
T_WS: Final = ["", " ", "  ", "\t", "\n", "\n  ", "\r\n", "\r", "\x0c", " ", "\x0b"]
_NOISE: Final = [0.0]


def _t_elem(rng: random.Random, kind: str) -> str:
    if kind == "int":
        return rng.choice(T_INTS)
    body = rng.choice(T_STR_BODIES)
    q = rng.choice(['"', "'", '"""', "'''"])
    return f"{q}{body}{q}"


def _t_array(rng: random.Random, depth: int = 0) -> str:
    kind = rng.choice(["int", "str", "mixed"])
    n = rng.choice([0, 1, 2, 3, 5])
    parts = []
    for _ in range(n):
        r = rng.random()
        if depth < 2 and r < 0.08:
            parts.append(_t_array(rng, depth + 1))
        elif r < 0.12:
            parts.append("{ k = 1 }")
        else:
            k = kind if kind != "mixed" else rng.choice(["int", "str"])
            parts.append(_t_elem(rng, k))
    out = "["
    for i, p in enumerate(parts):
        out += rng.choice(T_WS) + p + rng.choice(T_WS)
        if i < len(parts) - 1:
            out += rng.choice([",", ",", ",", ",,", ""])
            if rng.random() < 0.05:
                out += " # c\n"
    if parts and rng.random() < 0.3:
        out += "," + rng.choice(T_WS)
    out += rng.choice(T_WS) + rng.choice(["]", "]", "]", ""])
    return out


def _t_s3_doc(rng: random.Random) -> str:
    a = _t_array(rng)
    ctx = rng.choice(["a = {}", "t = {{ x = {} }}", "a = [{}]", "[s]\na = {}\nb = 1"])
    return ctx.format(a) + rng.choice(["", "\n", " # end\n", " x\n"])


def _pick(rng: random.Random, good: Sequence[str], bad: Sequence[str] = ()) -> str:
    if bad and rng.random() < _NOISE[0]:
        return rng.choice(bad)
    return rng.choice(good)


T_BARE: Final = ["a", "b", "key", "port", "name", "x-y", "x_y", "1", "123", "_", "-",
                 "true", "inf", "nan", "A", "Ab", "k1", "server_1", "0x1", "a1-b2_c3"]  # fmt: skip
T_BARE_BAD: Final = ["é", "a b", "a=b", "", "$"]
T_QKEYS: Final = ['"a"', '""', '"a.b"', '"é"', r'"\u00e9"', "'lit'", "''", '"a b"',
                  r'"\n"', r'"\""', r"'a\b'", '"key"', r'"\U0001F600"', '"[x]"']  # fmt: skip
T_QKEYS_BAD: Final = [r'"\x"', "'a'b'", '"\n"', '"a']
T_FLOATS: Final = ["1.0", "-0.0", "+1.5", "3.14e2", "1e-3", "1E+3", "6.626e-34", "inf",
                   "-inf", "+nan", "nan", "0.0e0", "9_9.9_9", "1e1_0", "1_0.0",
                   "224_617.445_991", "0.1", "1e06", "-1E-2"]  # fmt: skip
T_FLOATS_BAD: Final = [
    "1.",
    ".5",
    "1._0",
    "1.2.3",
    "01.5",
    "1e",
    "1e_1",
    "Inf",
    "NaN",
    "+-1.0",
]
T_INTS2: Final = ["0", "-0", "+0", "7", "-12", "+3", "1_000", "0x1F", "0o7", "0b1",
                  "123456789012345678901234567890", "0xDEAD_beef", "0xdead", "0o755",
                  "0b1010_1010", "99999999999999999999", "0x00ff", "5_349_221",
                  "-9223372036854775808"]  # fmt: skip
T_INTS_BAD: Final = ["007", "00", "01", "-", "+", "0x", "0o8", "0b2", "1__0", "_1", "1_",
                     "+0x1", "0X1F", "-0x1", "0x_1", "1 2"]  # fmt: skip
T_DATES: Final = ["1979-05-27T07:32:00Z", "1979-05-27T00:32:00-07:00",
                  "1979-05-27T00:32:00.999999-07:00", "1979-05-27 07:32:00Z",
                  "1979-05-27t07:32:00z", "1979-05-27T07:32:00", "1979-05-27",
                  "07:32:00", "00:32:00.999999", "00:32:00.1234567", "2026-01-01T10:00:00.5Z",
                  "2000-02-29", "1979-05-27T07:32:00+14:00", "23:59:59"]  # fmt: skip
T_DATES_BAD: Final = ["1979-13-27", "1979-02-30", "24:00:00", "1979-05-27T07:32:00+25:00",
                      "1979-05-27T07:32", "1979-05-27T07:32:60", "1979-5-27", "07:32",
                      "1979-05-27T"]  # fmt: skip
T_BASIC: Final = ["", "a", "a b", "it's", "tab\there", "é", "\U0001f600", r"\n", r"\u00e9",
                  r"\\", "comma, inside", "]", "[", "#", " ", "=", "a#b",
                  r"\t\u00e9\"q\"", r"\U0001F600", r"\b\f\r", "\u2028", r"\e", "x"]  # fmt: skip
T_BASIC_BAD: Final = ['say "hi"', "\x7f", "\x00", "\x1f", r"\x41", r"\uD800", r"\U00110000",
                      "\\", "line\nbreak", r"\/", "\ud800", r"\u12"]  # fmt: skip
T_LITERAL: Final = [
    "",
    "a",
    'say "hi"',
    r"C:\path",
    r"\n stays",
    "é",
    "#",
    "]",
    "tab\tok",
]
T_LITERAL_BAD: Final = ["it's", "\x00", "line\nbreak", "\x7f"]
T_MULTI: Final = ["\n", "\r\n", "", "\nline one\nline two \\\n  continued\n", "a\n\nb",
                  '"quoted" inside', "\\\n   \\\n", "x\t\ty", 'ends with quote"']  # fmt: skip
T_MULTI_BAD: Final = ['""""', "\x00", "\\ x", "\\ \nx"]
T_MLIT: Final = ["\n", "\r\n", "", "it's", "a\n'b'", r"C:\no\escapes", "x"]
T_MLIT_BAD: Final = ["''''", "\x00"]
T_NL: Final = ["\n", "\n", "\n", "\r\n", "\n\n", " \n", "\t\n", " # c\n", " #\tc é\n"]
T_NL_BAD: Final = ["\r", "#\x01\n", " # \x7f\n", "\x0c\n"]
T_RARE: Final = ["\r", "\x00", "\x7f", "\x0b", "\ufeff", "\xa0", "\\", '"', "'", "#",
                 "=", "[", "]", "{", "}", ",", ".", "_", "\n", "\t", " ", "0", "e", "T",
                 "Z", ":"]  # fmt: skip


def _t_key(rng: random.Random) -> str:
    parts = []
    for _ in range(rng.choice([1, 1, 1, 2, 3])):
        parts.append(_pick(rng, T_BARE, T_BARE_BAD) if rng.random() < 0.8
                     else _pick(rng, T_QKEYS, T_QKEYS_BAD))  # fmt: skip
    return _pick(rng, [".", ".", " . ", ". ", "\t.\t"], [".."]).join(parts)


def _t_string(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.5:
        return '"' + _pick(rng, T_BASIC, T_BASIC_BAD) + '"'
    if r < 0.7:
        return "'" + _pick(rng, T_LITERAL, T_LITERAL_BAD) + "'"
    if r < 0.9:
        return '"""' + _pick(rng, T_MULTI + T_BASIC, T_MULTI_BAD) + '"""'
    return "'''" + _pick(rng, T_MLIT, T_MLIT_BAD) + "'''"


def _t_value(rng: random.Random, depth: int = 0) -> str:
    r = rng.random()
    if r < 0.18:
        return _pick(rng, T_INTS2, T_INTS_BAD)
    if r < 0.28:
        return _pick(rng, T_FLOATS, T_FLOATS_BAD)
    if r < 0.33:
        return _pick(rng, ["true", "false"], ["True", "tru", "falsey"])
    if r < 0.43:
        return _pick(rng, T_DATES, T_DATES_BAD)
    if r < 0.63:
        return _t_string(rng)
    if r < 0.80 and depth < 3:
        if _NOISE[0] and rng.random() < 0.2:
            return _t_array(rng)  # s3's generator: rare tokens, often invalid
        n = rng.choice([0, 1, 2, 3, 6, 12])
        if rng.random() < 0.5:  # flat homogeneous arrays: the fast-path keeps' target
            gens: list[Callable[[], str]] = [lambda: _pick(rng, T_INTS2, T_INTS_BAD),
                                             lambda: _t_string(rng),
                                             lambda: _pick(rng, T_FLOATS, T_FLOATS_BAD)]  # fmt: skip
            g = rng.choice(gens)
            items = [g() for _ in range(n)]
        else:
            items = [_t_value(rng, depth + 1) for _ in range(n)]
        sep = _pick(
            rng, [", ", ",", " ,", ",\n", ", # c\n", ",\r\n", ",\t", " , "], [",,", " "]
        )
        tail = _pick(rng, ["", "", ",", ",\n", "\n"], [",,"])
        return ("[" + rng.choice(["", " ", "\n", "\t"]) + sep.join(items) + tail
                + _pick(rng, ["]"], [""]))  # fmt: skip
    if depth < 3:
        n = rng.choice([0, 1, 2, 3])
        items = [f"{_t_key(rng)} = {_t_value(rng, depth + 1)}" for _ in range(n)]
        sep = _pick(rng, [", ", ",", " , "], [",\n", ",,"])
        return ("{" + rng.choice(["", " "]) + sep.join(items) + _pick(rng, ["", " "], [","])
                + "}")  # fmt: skip
    return _pick(rng, T_INTS2, T_INTS_BAD)


def _t_header(rng: random.Random) -> str:
    k = _t_key(rng)
    if rng.random() < 0.3:
        return _pick(rng, [f"[[{k}]]", f"[[ {k} ]]"], [f"[[{k}]", f"[ [{k}]]"])
    return _pick(
        rng, [f"[{k}]", f"[ {k} ]", f"[{k}] # h", f"[\t{k}\t]"], [f"[{k}]x", f"[{k}"]
    )


def _t_kv(rng: random.Random) -> str:
    eq = _pick(rng, [" = ", "=", " =", "= ", "\t=\t", "  =  "], [" == ", " : ", " "])
    return rng.choice(["", "", "", " ", "\t"]) + _t_key(rng) + eq + _t_value(rng)


def _t_full_doc(rng: random.Random) -> str:
    _NOISE[0] = 0.0 if rng.random() < 0.5 else 0.03
    lines = []
    tables = [rng.choice(T_BARE) for _ in range(rng.randint(1, 4))]
    for _ in range(rng.randint(1, 14)):
        r = rng.random()
        if r < 0.18:
            lines.append(_t_header(rng))
        elif r < 0.30:
            t = rng.choice(tables)  # repeated headers, the memo keeps' target
            lines.append(rng.choice([f"[{t}]", f"[[{t}]]", f"[{t}.sub]",
                                     f"[{t}.{rng.choice(T_BARE)}]", f"[[{t}.arr]]"]))  # fmt: skip
        elif r < 0.35:
            lines.append(
                rng.choice(["# comment", "", "   ", "#", "# é ü", "#\t", "\t# x"])
            )
        else:
            lines.append(_t_kv(rng))
    out = ""
    for ln in lines:
        out += ln + _pick(rng, T_NL, T_NL_BAD)
    if rng.random() < 0.2:
        out = out.rstrip("\n")
    return out


def _t_workload_like(rng: random.Random) -> str:
    """A few tables shaped like the frozen workload, with perturbed fields."""
    _NOISE[0] = 0.0 if rng.random() < 0.5 else 0.05
    out = []
    for i in range(rng.randint(1, 3)):
        out.append(f"[server_{i}]")
        out.append(f'name = "host-{i}\\t\\u00e9\\"quoted\\""')
        out.append(f"port = {_pick(rng, T_INTS2, T_INTS_BAD)}")
        out.append(
            f"mask = {_pick(rng, ['0x00ff', '0xFFFF', '0xabcd'], ['0x', '0x_1'])}"
        )
        samples = ", ".join(
            _pick(rng, T_INTS2, T_INTS_BAD) for _ in range(rng.randint(0, 12))
        )
        out.append(f"samples = [{samples}]")
        out.append(
            f"tags = [{', '.join(_t_string(rng) for _ in range(rng.randint(0, 4)))}]"
        )
        out.append(f"owner = {{ name = {_t_string(rng)}, level = "
                   f"{_pick(rng, T_INTS2, T_INTS_BAD)}, active = true }}")  # fmt: skip
        out.append(f"since = {_pick(rng, T_DATES, T_DATES_BAD)}")
        out.append('notes = """\nline one\nline two \\\n  continued\n"""')
        out.append(f"[[server_{i}.disk]]")
        out.append(f"{_t_key(rng)} = {_t_value(rng)}")
    return rng.choice(["\n", "\r\n"]).join(out) + "\n"


_t_mutate: Final = _mutator(T_RARE, 0.4, 0.7, 8, replace=0.85)


def _t_gen(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.20:
        s = _t_s3_doc(rng)
    elif r < 0.80:
        s = _t_full_doc(rng)
    else:
        s = _t_workload_like(rng)
    if rng.random() < 0.15:
        s = _t_mutate(rng, s)
    return s


# ---- sqlparse: a SQL grammar with rare tokens ---------------------------

S_TABLES: Final = ["orders", "customers", "items", "t", "T1", '"Order"', "`user`", "[group]",
                   "public.orders", "db.sch.tbl", "é_tbl", "表", '"a""b"', "order", "user",
                   "date", "select_", "_x", "x1$"]  # fmt: skip
S_COLUMNS: Final = ["id", "amount", "status", "created_at", "region", "total", "Name",
                    '"Col"', "`c`", "[c]", "date", "type", "value", "end", "begin", "key",
                    "level", "row", "user", "*", "é", "a.b", "t.*", "count", "left", "right",
                    "default", "if", "case", "table"]  # fmt: skip


def _alternate(s: str) -> str:
    return "".join(c.upper() if i % 2 else c for i, c in enumerate(s))


def _capital(s: str) -> str:
    return s[:1].upper() + s[1:].lower()


S_KW_CASE: Final[list[Callable[[str], str]]] = [str.lower, str.upper, str.title, _capital,
                                                 _alternate]  # fmt: skip
S_NUMS: Final = ["0", "1", "42", "-7", "1.5", ".5", "5.", "1e10", "1E-3", "2.5e+3", "0x1F",
                 "0b101", "1_000", "99999999999999999999", "00012", "+3", "1.2.3"]  # fmt: skip
S_STRS: Final = ["'open'", "'it''s'", "'a\\'b'", "''", "'%'", "'_'", "E'\\n'", "N'ünï'",
                 "X'0F'", "b'01'", "'2026-01-01'", "'multi\nline'", "'semi;colon'",
                 "'--not comment'", "'/*no*/'", "'\"'", "$$dollar$$", "$tag$body;$tag$",
                 "$$ nested $x$ $$", "'é中'", "'\U0001f600'", "U&'d\\0061t'", "'\\\\'",
                 "'unterminated"]  # fmt: skip
S_PLACE: Final = [
    "?",
    "%s",
    "%(name)s",
    ":name",
    ":1",
    "$1",
    "@var",
    "@@version",
    "{x}",
]
S_OPS: Final = ["=", "<>", "!=", "<", ">", "<=", ">=", "<=>", "||", "+", "-", "*", "/", "%",
                "::", "->", "->>", "@>", "<@", "~", "!~*", "LIKE", "ILIKE", "IS", "IS NOT",
                "IN", "NOT IN", "BETWEEN", "&", "|", "^", "#>", "?|", "=="]  # fmt: skip
S_WS: Final = [" ", " ", " ", "  ", "\t", "\n", "\r\n", "\r", "\x0b", "\x0c", "\xa0",
               "\u2003", "\u200b", " \n ", "\n\n"]  # fmt: skip
S_COMMENTS: Final = ["-- c\n", "--\n", "# hash\n", "/* c */", "/**/", "/* a /* nested */ b */",
                     "/*+ INDEX(t) */", "/* multi\nline */", "-- é\r\n", "--no-newline",
                     "/* unterminated", "/* ; */", "-- ;\n"]  # fmt: skip
S_FUNCS: Final = ["count(*)", "sum(amount)", "avg(total)", "coalesce(a, b)", "max(x)",
                  "cast(x as int)", "now()", "lower(name)", "substring(s from 1 for 2)",
                  "extract(year from d)", "row_number() over (partition by region order by id)",
                  "sum(x) filter (where y > 0)", "array_agg(distinct id)", "f()", "date(d)",
                  "if(a, b, c)", "replace(s, ';', ',')"]  # fmt: skip
S_RARE: Final = ["'", '"', "`", "$", "$$", ";", "--", "/*", "*/", "#", "\\", "\n", "\r", "\t",
                 "(", ")", ",", ".", ":", "::", "\xa0", "\u200b", "é", "[", "]", "%", "@",
                 "?", "\x00"]  # fmt: skip


def _kw(rng: random.Random, s: str) -> str:
    return rng.choice(S_KW_CASE)(s)


def _s_ws(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.85:
        return " "
    if r < 0.95:
        return rng.choice(S_WS)
    return " " + rng.choice(S_COMMENTS) + " "


def _s_ident(rng: random.Random) -> str:
    return (rng.choice(S_COLUMNS) if rng.random() < 0.7
            else rng.choice(S_TABLES) + "." + rng.choice(S_COLUMNS))  # fmt: skip


def _s_atom(rng: random.Random, depth: int) -> str:
    r = rng.random()
    if r < 0.35:
        return _s_ident(rng)
    if r < 0.5:
        return rng.choice(S_NUMS)
    if r < 0.65:
        return rng.choice(S_STRS)
    if r < 0.72:
        return rng.choice(S_PLACE)
    if r < 0.82:
        return rng.choice(S_FUNCS)
    if r < 0.88 and depth < 2:
        return "(" + _s_select(rng, depth + 1) + ")"
    if r < 0.94 and depth < 3:
        return (f"{_kw(rng, 'case')} {_kw(rng, 'when')} {_s_expr(rng, depth + 1)} "
                f"{_kw(rng, 'then')} {_s_atom(rng, depth + 1)} {_kw(rng, 'else')} "
                f"{_s_atom(rng, depth + 1)} {_kw(rng, 'end')}")  # fmt: skip
    return rng.choice(["NULL", "true", "FALSE", "DEFAULT", "CURRENT_TIMESTAMP", "*"])


def _s_expr(rng: random.Random, depth: int = 0) -> str:
    e = _s_atom(rng, depth)
    for _ in range(rng.choice([0, 1, 1, 2])):
        op = rng.choice(S_OPS)
        rhs = _s_atom(rng, depth)
        if op in ("IN", "NOT IN"):
            rhs = (
                "("
                + ", ".join(_s_atom(rng, depth + 1) for _ in range(rng.randint(1, 3)))
                + ")"
            )
        elif op == "BETWEEN":
            rhs = f"{_s_atom(rng, depth)} {_kw(rng, 'and')} {_s_atom(rng, depth)}"
        e = e + _s_ws(rng) + _kw(rng, op) + _s_ws(rng) + rhs
        if rng.random() < 0.3:
            e = (
                e
                + _s_ws(rng)
                + _kw(rng, rng.choice(["and", "or"]))
                + _s_ws(rng)
                + _s_atom(rng, depth)
            )
    if rng.random() < 0.1:
        e = "(" + e + ")"
    return e


def _s_select(rng: random.Random, depth: int = 0) -> str:
    cols = []
    for _ in range(rng.randint(1, 4)):
        c = _s_expr(rng, depth)
        r = rng.random()
        if r < 0.25:
            c += f" {_kw(rng, 'as')} {rng.choice(S_COLUMNS)}"
        elif r < 0.35:
            c += " " + rng.choice(["n", '"Alias"', "`a`", "x1"])
        cols.append(c)
    s = (_kw(rng, "select") + _s_ws(rng)
         + rng.choice(["", "", _kw(rng, "distinct") + " ", "top 5 "])
         + ("," + _s_ws(rng)).join(cols))  # fmt: skip
    if rng.random() < 0.9:
        s += (_s_ws(rng) + _kw(rng, "from") + _s_ws(rng) + rng.choice(S_TABLES)
              + rng.choice(["", " a", " as t2", ""]))  # fmt: skip
        for _ in range(rng.choice([0, 0, 1, 2])):
            j = rng.choice(["join", "left join", "left outer join", "inner join", "cross join",
                            "full outer join", "natural join", "straight_join", ","])  # fmt: skip
            s += _s_ws(rng) + _kw(rng, j) + _s_ws(rng) + rng.choice(S_TABLES)
            if j not in (",", "cross join", "natural join"):
                s += _s_ws(rng) + _kw(rng, rng.choice(["on", "using"])) + _s_ws(rng) + (
                    _s_expr(rng, depth + 1) if rng.random() < 0.8 else "(id)")  # fmt: skip
    if rng.random() < 0.6:
        s += _s_ws(rng) + _kw(rng, "where") + _s_ws(rng) + _s_expr(rng, depth)
    if rng.random() < 0.3:
        s += (_s_ws(rng) + _kw(rng, "group by") + _s_ws(rng)
              + ", ".join(_s_ident(rng) for _ in range(rng.randint(1, 3))))  # fmt: skip
        if rng.random() < 0.5:
            s += _s_ws(rng) + _kw(rng, "having") + _s_ws(rng) + _s_expr(rng, depth)
    if rng.random() < 0.3:
        s += (_s_ws(rng) + _kw(rng, "order by") + _s_ws(rng) + _s_ident(rng)
              + rng.choice(["", " desc", " ASC", " nulls last"]))  # fmt: skip
    if rng.random() < 0.2:
        s += _s_ws(rng) + _kw(rng, "limit") + _s_ws(rng) + rng.choice(S_NUMS + S_PLACE)
        if rng.random() < 0.3:
            s += _s_ws(rng) + _kw(rng, "offset") + " 10"
    if depth == 0 and rng.random() < 0.08:
        s += (_s_ws(rng) + _kw(rng, rng.choice(["union", "union all", "except", "intersect"]))
              + _s_ws(rng) + _s_select(rng, 1))  # fmt: skip
    if depth == 0 and rng.random() < 0.08:
        s = f"{_kw(rng, 'with')} cte {_kw(rng, 'as')} ({_s_select(rng, 1)}) " + s
    return s


def _s_insert(rng: random.Random) -> str:
    cols = ", ".join(rng.choice(S_COLUMNS) for _ in range(rng.randint(1, 3)))
    rows = ", ".join("(" + ", ".join(_s_atom(rng, 2) for _ in range(rng.randint(1, 3))) + ")"
                     for _ in range(rng.randint(1, 4)))  # fmt: skip
    s = f"{_kw(rng, 'insert into')} {rng.choice(S_TABLES)} ({cols}) {_kw(rng, 'values')} {rows}"
    if rng.random() < 0.15:
        s += f" {_kw(rng, 'on conflict')} (id) {_kw(rng, 'do update set')} amount = excluded.amount"
    if rng.random() < 0.1:
        s += f" {_kw(rng, 'returning')} id"
    return s


def _s_update(rng: random.Random) -> str:
    sets = ", ".join(f"{rng.choice(S_COLUMNS)} = {_s_expr(rng, 1)}"
                     for _ in range(rng.randint(1, 3)))  # fmt: skip
    return (f"{_kw(rng, 'update')} {rng.choice(S_TABLES)} {_kw(rng, 'set')} {sets} "
            f"{_kw(rng, 'where')} {_s_expr(rng)}")  # fmt: skip


def _s_delete(rng: random.Random) -> str:
    return f"{_kw(rng, 'delete from')} {rng.choice(S_TABLES)}" + (
        f" {_kw(rng, 'where')} {_s_expr(rng)}" if rng.random() < 0.8 else "")  # fmt: skip


S_TYPES: Final = ["int", "varchar(20)", "TEXT", "numeric(10, 2)", "timestamp with time zone",
                  "serial primary key", "int not null default 0"]  # fmt: skip
S_BODIES: Final = ["$$ select 1; $$", "$body$ begin return 1; end; $body$", "$$ begin; end $$",
                   "'select 1'", "$f$ declare x int; begin x := 1; if x > 0 then return x; "
                   "end if; end $f$"]  # fmt: skip
S_CONTROL: Final = ["begin", "commit", "rollback", "begin transaction", "start transaction",
                    "drop table x", "truncate t", "vacuum", "explain select 1", "go", "use db"]  # fmt: skip


def _s_ddl(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.35:
        cols = ", ".join(f"{rng.choice(S_COLUMNS)} {rng.choice(S_TYPES)}"
                         for _ in range(rng.randint(1, 4)))  # fmt: skip
        return (f"{_kw(rng, 'create table')} {rng.choice(['', 'if not exists '])}"
                f"{rng.choice(S_TABLES)} ({cols})")  # fmt: skip
    if r < 0.55:
        body = rng.choice(S_BODIES)
        return (f"{_kw(rng, 'create or replace function')} f(a int) {_kw(rng, 'returns')} int "
                f"{_kw(rng, 'as')} {body} {_kw(rng, 'language')} plpgsql")  # fmt: skip
    if r < 0.7:
        return (f"{_kw(rng, 'create procedure')} p() {_kw(rng, 'begin')} {_s_select(rng, 1)}; "
                f"{_s_update(rng)}; {_kw(rng, 'end')}")  # fmt: skip
    if r < 0.8:
        return (f"{_kw(rng, 'alter table')} {rng.choice(S_TABLES)} "
                f"{_kw(rng, rng.choice(['add column', 'drop column', 'rename to']))} "
                f"{rng.choice(S_COLUMNS)}")  # fmt: skip
    if r < 0.9:
        return _kw(rng, rng.choice(S_CONTROL))
    return (f"{_kw(rng, 'declare')} @x int; {_kw(rng, 'if')} @x > 1 {_kw(rng, 'begin')} "
            f"{_s_select(rng, 1)} {_kw(rng, 'end')}")  # fmt: skip


def _s_statement(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.5:
        return _s_select(rng)
    if r < 0.65:
        return _s_insert(rng)
    if r < 0.75:
        return _s_update(rng)
    if r < 0.8:
        return _s_delete(rng)
    return _s_ddl(rng)


_s_mutate: Final = _mutator(S_RARE, 0.45, 0.75, 10)
S_SEPS: Final = [";\n", ";", "; ", ";\r\n", ";\n\n", " ;", ";;\n", ";\n-- trailing\n", "\n/\n",
                 "\ngo\n"]  # fmt: skip


def _s_gen(rng: random.Random) -> str:
    n = rng.choice([1, 1, 1, 2, 3])
    parts = []
    for _ in range(n):
        st = _s_statement(rng)
        if rng.random() < 0.15:
            st = rng.choice(S_COMMENTS) + st
        parts.append(st)
    sep = rng.choice(S_SEPS)
    s = sep.join(parts) + rng.choice(["", ";", ";\n", " ", "\n", "  -- end", ";;"])
    if rng.random() < 0.05:
        s = s.upper()
    if rng.random() < 0.25:
        s = _s_mutate(rng, s)
    return s


# ---- markdown and mistune: one Markdown grammar -------------------------

M_WORDS: Final = ["engine", "trial", "judge", "verdict", "HTML", "noise", "a", "I", "x_y",
                  "foo*bar", "snake_case_word", "é", "naïve", "中文", "日本語", "\U0001f600",
                  "e\u0301", "\u200b", "\u202e", "rtl\u200f", "—", "…", "“quoted”", "‘s’",
                  "¡hola!", "¿qué?", "«ok»", "2*3", "a&b", "<", ">", "&", '"', "'", "1.",
                  "HTMLs", "XHTML", "html", "ABBR", "SQL", "\xa0", "co-op", "$5", "100%"]  # fmt: skip
M_URLS: Final = ["https://example.org/1", "http://a.b/c?d=e&f=g", "/rel/path", "#frag",
                 "<https://x.y/with space>", "https://x.y/a(b)c", "https://x.y/a_(b)",
                 "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>x</b>",
                 "data:image/png;base64,AAAA", "vbscript:x", "mailto:a@b.c", "ftp://f.g",
                 "https://é.example/ü", "https://x.y/%20", "", "<>", "https://x.y/\\*",
                 'url"quote', "https://x.y/a&amp;b", "  https://pad.ed  ",
                 "/u\\)x", "/u\\(x", "/a\\(b\\)c", "HTTPS://UPPER.example/", "Mailto:a@b.c",
                 "Http://x.y", "/p\\ q", "#\\)"]  # fmt: skip
M_TITLES: Final = ["", ' "title"', " 'single'", " (paren)", ' "with \\"esc\\""', ' "a & b"',
                   ' "unclosed', ' "<tag>"']  # fmt: skip
M_ENT: Final = ["&amp;", "&copy;", "&nbsp;", "&#123;", "&#x1F600;", "&#0;", "&bogus;", "&amp",
                "&#xD800;", "&ouml;", "&lt;b&gt;", "&#99999999;", "&"]  # fmt: skip
M_HTML_IN: Final = ["<span>x</span>", "<b>", "</b>", "<br>", "<br/>", "<img src=x onerror=y>",
                    '<a href="/x">a</a>', "<!-- c -->", "<?php ?>", "<![CDATA[x]]>",
                    "<x-y>", "</>", "<script>alert(1)</script>", "< notatag >", "<a\nhref=x>"]  # fmt: skip
M_ESC: Final = ["\\*", "\\_", "\\[", "\\]", "\\\\", "\\`", "\\#", "\\|", "\\<", "\\&", "\\!",
                "\\~", "\\a", "\\"]  # fmt: skip
M_RARE_CH: Final = ["\x02", "\x03", "\x00", "\x01", "\t", "\r", "\x0b", "\x0c", "\ufffd",
                    "\u2028", "\ufeff", "\x7f"]  # fmt: skip
M_REFS: Final = [
    "foo",
    "Foo",
    "FOO",
    "bar baz",
    "ü",
    "1",
    "a\\]b",
    "[nested]",
    "x",
    "HTML",
]
M_RARE: Final = ["*", "_", "`", "[", "]", "(", ")", "<", ">", "&", "\\", "!", "#", "|", "~",
                 "\n", "\r", "\t", " ", "  \n", ">", "-", "1.", "\x02", "\x03", ":", "^"]  # fmt: skip


def _m_w(rng: random.Random) -> str:
    return rng.choice(M_WORDS[:6]) if rng.random() < 0.6 else rng.choice(M_WORDS)


def _m_inline(rng: random.Random, depth: int = 0) -> str:
    r = rng.random()
    if r < 0.40:
        return _m_w(rng)
    if r < 0.52 and depth < 3:
        m = rng.choice(["*", "_", "**", "__", "***", "___", "~~", "*", "**"])
        inner = " ".join(_m_inline(rng, depth + 1) for _ in range(rng.randint(1, 3)))
        close = m if rng.random() < 0.85 else rng.choice(["", "*", "_", "**", m[:1]])
        lead = rng.choice(["", "", "", " ", "x"])
        return lead + m + inner + close + rng.choice(["", "", "y", " "])
    if r < 0.58:
        t = rng.choice(["`", "`", "``", "```"])
        body = rng.choice(
            ["code()", "a ` b", " x ", "`", "*not em*", "<b>", "a|b", "&amp;", ""]
        )
        return t + body + (t if rng.random() < 0.9 else "")
    if r < 0.70 and depth < 3:
        text = " ".join(_m_inline(rng, depth + 1) for _ in range(rng.randint(1, 2)))
        img = "!" if rng.random() < 0.15 else ""
        kind = rng.random()
        if kind < 0.6:
            return f"{img}[{text}]({rng.choice(M_URLS)}{rng.choice(M_TITLES)})"
        if kind < 0.75:
            return f"{img}[{text}][{rng.choice(M_REFS)}]"
        if kind < 0.85:
            return f"{img}[{rng.choice(M_REFS)}][]"
        if kind < 0.95:
            return f"[{rng.choice(M_REFS)}]"
        return f"[{text}]({rng.choice(M_URLS)}"  # unclosed
    if r < 0.74:
        return rng.choice(["<https://auto.link/x>", "<a@b.co>", "<mailto:x@y.z>", "<javascript:x>",
                           "https://bare.example.org", "www.example.com", "<http://a.b/<c>"])  # fmt: skip
    if r < 0.79:
        return rng.choice(M_HTML_IN)
    if r < 0.85:
        return rng.choice(M_ENT)
    if r < 0.90:
        return rng.choice(M_ESC)
    if r < 0.93:
        return rng.choice(M_RARE_CH)
    if r < 0.96:
        return rng.choice(["[^n1]", "[^1]", "[^missing]", "[^]", "^up^", "~sub~"])
    return rng.choice(["  \n", "\\\n", "\n", " \n"])


def _m_sentence(rng: random.Random) -> str:
    return (" ".join(_m_inline(rng) for _ in range(rng.randint(2, 12)))
            + rng.choice([".", "", " & more.", "  ", "!"]))  # fmt: skip


M_HTML_BLOCKS: Final = ["<div>\n*md* inside\n</div>", '<div markdown="1">\n*md*\n</div>',
                        "<!-- comment\nblock -->", "<pre>\n  x\n</pre>",
                        "<script>\nvar a = '<b>';\n</script>",
                        "<table><tr><td>x</td></tr></table>", "<p>open", "</div>"]  # fmt: skip
M_ABBRS: Final = ["HTML", "SQL", "ABBR", "a.b", "C++", "e", "中文", "HT"]
M_ABBR_TITLES: Final = ["Hyper Text", "", "x & y", '"q"']


def _m_block(rng: random.Random, depth: int = 0) -> str:
    r = rng.random()
    if r < 0.12:
        return (rng.choice(["#", "##", "###", "####", "#####", "######", "#######"])
                + rng.choice([" ", " ", "", "\t", "  "]) + _m_sentence(rng)
                + rng.choice(["", "", " ##", " #", "#"]))  # fmt: skip
    if r < 0.16:
        return (
            _m_sentence(rng) + "\n" + rng.choice(["===", "---", "=", "- - -", "  ==="])
        )
    if r < 0.36:
        return _m_sentence(rng) + rng.choice(
            ["", "\n" + _m_sentence(rng), "\n  " + _m_sentence(rng)]
        )
    if r < 0.50 and depth < 3:
        marker = rng.choice(["-", "*", "+", "1.", "2)", "10.", "-", "*"])
        items = []
        for i in range(rng.randint(1, 4)):
            m = marker if not marker[0].isdigit() else f"{i + 1}{marker[-1]}"
            item = (m + rng.choice([" ", " ", "  ", "\t", "    "])
                    + rng.choice(["", "[ ] ", "[x] ", ""]) + _m_sentence(rng))  # fmt: skip
            if rng.random() < 0.3:
                ind = rng.choice(["  ", "    ", "\t", "   "])
                sub = _m_block(rng, depth + 1)
                item += "\n" + "\n".join(ind + ln for ln in sub.split("\n"))
            items.append(item)
        return rng.choice(["\n", "\n\n"]).join(items)
    if r < 0.58 and depth < 3:
        sub = _m_block(rng, depth + 1)
        pre = rng.choice(["> ", ">", "> > ", ">\t"])
        lines = sub.split("\n")
        out = [
            pre + ln if (i == 0 or rng.random() < 0.8) else ln
            for i, ln in enumerate(lines)
        ]
        return "\n".join(out)
    if r < 0.66:
        fence = rng.choice(["```", "~~~", "````", "``"])
        info = rng.choice(["", "python", " python ", "py {.x}", "a`b", 'js title="x"'])
        body = rng.choice(["value = 1 * 2\nprint(value)", "<b>&amp;</b>", "```", "", "\ttab",
                           "a\n\n\nb"])  # fmt: skip
        close = fence if rng.random() < 0.9 else ""
        ind = rng.choice(["", "", "  ", "   "])
        return f"{ind}{fence}{info}\n{body}\n{close}"
    if r < 0.70:
        return rng.choice(["    code block\n    line 2", "\tcode\ttab", "    <b>x</b>"])
    if r < 0.78:
        ncol = rng.randint(1, 4)
        head = "| " + " | ".join(_m_w(rng) for _ in range(ncol)) + " |"
        sep = "| " + " | ".join(rng.choice(["---", ":---", "---:", ":-:", "-", "--"])
                                for _ in range(ncol)) + " |"  # fmt: skip
        rows = []
        for _ in range(rng.randint(0, 3)):
            cells = [rng.choice([_m_inline(rng), "`a|b`", "a \\| b", "", "**b**", "1.5"])
                     for _ in range(rng.choice([ncol, ncol, ncol - 1, ncol + 1]))]  # fmt: skip
            rows.append(
                rng.choice(["| ", ""]) + " | ".join(cells) + rng.choice([" |", ""])
            )
        if rng.random() < 0.2:
            head = head.strip("|")
        return "\n".join([head, sep, *rows])
    if r < 0.82:
        return rng.choice(
            ["***", "---", "___", "* * *", "- - -", "____", "**", "  ---"]
        )
    if r < 0.86:
        return rng.choice(M_HTML_BLOCKS)
    if r < 0.91:
        return f"[{rng.choice(M_REFS)}]: {rng.choice(M_URLS)}{rng.choice(M_TITLES)}"
    if r < 0.95:
        return (f"[^{rng.choice(['n1', '1', 'x', 'n0'])}]: {_m_sentence(rng)}"
                + rng.choice(["", "\n    continued " + _m_w(rng)]))  # fmt: skip
    return f"*[{rng.choice(M_ABBRS)}]: {rng.choice(M_ABBR_TITLES)}"


def _m_document(rng: random.Random) -> str:
    parts = []
    if rng.random() < 0.4:
        parts.append("*[HTML]: Hyper Text Markup Language")
    for _ in range(rng.randint(1, 7)):
        parts.append(_m_block(rng))
    doc = rng.choice(["\n\n", "\n\n", "\n", "\n\n\n"]).join(parts)
    nl = rng.random()
    if nl < 0.08:
        doc = doc.replace("\n", "\r\n")
    elif nl < 0.11:
        doc = doc.replace("\n", "\r")
    if rng.random() < 0.05:
        doc = doc.replace("    ", "\t")
    return doc + rng.choice(["\n", "", "\n\n", "  "])


_m_mutate: Final = _mutator(M_RARE, 0.45, 0.75, 12)


def _m_gen(rng: random.Random) -> str:
    s = _m_document(rng)
    if rng.random() < 0.25:
        s = _m_mutate(rng, s)
    return s


# ===========================================================================
# The child side: the four adapters (seeds, workload, calls)
# ===========================================================================


def _files(tree: Path, pattern: str) -> list[Path]:
    """Plain files (no link) under ``tree`` matching ``pattern``, sorted."""
    return sorted(p for p in tree.glob(pattern) if p.is_file() and not p.is_symlink())


def _text(path: Path) -> str:
    """A file's text: UTF-8, else Latin-1 (sqlparse's encoding tests)."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _literals(paths: Sequence[Path], dedent: bool) -> list[str]:
    """Every string literal of at least two characters in ``paths``, parsed
    as data (``ast.parse``, never run), in order; a file that does not
    parse gives none."""
    out: list[str] = []
    for path in paths:
        try:
            tree = ast.parse(_text(path))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = textwrap.dedent(node.value) if dedent else node.value
                if len(text) >= 2:
                    out.append(text)
    return out


def _bench(tree: Path, package: str) -> ModuleType | None:
    """The base tree's own benchmark module, imported here in the sandbox
    (its library is the tree's: the package is imported first)."""
    path = tree / "benchmarks" / f"bench_{package}.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"_x2_equiv_bench_{package}", path)
    assert spec is not None and spec.loader is not None  # a .py path always has one
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _guard_attrs(module: ModuleType, *names: str) -> list[Callable[..., object]]:
    found = [getattr(module, n, None) for n in names]
    if not all(callable(f) for f in found):
        raise ValueError(f"the benchmark lacks {', '.join(names)}")
    return [f for f in found if callable(f)]


class Tomli:
    package, src, workload_mode, unit = "tomli", True, "plain", "\n\n"

    def generate(self, rng: random.Random) -> tuple[str, str]:
        mode = "decimal" if rng.random() < 0.25 else "plain"  # corpus.py: mode first
        return mode, _t_gen(rng)

    def seeds(self, tree: Path) -> list[tuple[str, str]]:
        out = []
        for path in _files(tree, "tests/data/**/*.toml"):
            out.append(("plain", _text(path)))
            if "valid" in path.relative_to(tree).parts[2:3]:
                out.append(("decimal", _text(path)))
        return out

    def workload(self, tree: Path) -> str | None:
        bench = _bench(tree, self.package)
        if bench is None:
            return None
        (document,) = _guard_attrs(bench, "_document")
        return str(document(random.Random(31)))  # bench_tomli.main's seed

    def mutate(self, rng: random.Random, text: str) -> str:
        return _t_mutate(rng, text)

    def evaluator(self) -> Evaluate:
        import decimal

        import tomli  # type: ignore[import-not-found,import-untyped,unused-ignore]

        def calls(mode: str, s: str) -> list[Call]:
            kw = {"parse_float": decimal.Decimal} if mode == "decimal" else {}
            return [lambda: tomli.loads(s, **kw)]

        return calls


class Sqlparse:
    package, src, workload_mode, unit = "sqlparse", False, "all", "\n"

    def generate(self, rng: random.Random) -> tuple[str, str]:
        return "all", _s_gen(rng)

    def seeds(self, tree: Path) -> list[tuple[str, str]]:
        files = [_text(p) for p in _files(tree, "tests/files/*.sql")]
        literals = _literals(_files(tree, "tests/*.py"), dedent=False)
        return [("all", t) for t in [*files, *literals]]

    def workload(self, tree: Path) -> str | None:
        bench = _bench(tree, self.package)
        if bench is None:
            return None
        select, insert = _guard_attrs(bench, "_select", "_insert")
        rng, count = random.Random(17), int(getattr(bench, "STATEMENTS", 160))
        return "\n".join(
            str(select(rng, n) if n % 3 else insert(rng, n)) for n in range(count)
        )

    def mutate(self, rng: random.Random, text: str) -> str:
        return _s_mutate(rng, text)

    def evaluator(self) -> Evaluate:
        import sqlparse  # type: ignore[import-not-found,import-untyped,unused-ignore]

        def tree(tok: object) -> object:
            if getattr(tok, "is_group", False):
                return (type(tok).__name__, getattr(tok, "value", None),
                        [tree(t) for t in getattr(tok, "tokens", [])])  # fmt: skip
            return (type(tok).__name__, repr(getattr(tok, "ttype", None)),
                    getattr(tok, "value", None))  # fmt: skip

        def calls(mode: str, s: str) -> list[Call]:
            return [
                lambda: sqlparse.format(
                    s, reindent=True, keyword_case="upper", identifier_case="lower"
                ),  # fmt: skip
                lambda: [(tree(x), x.get_type()) for x in sqlparse.parse(s)],
                lambda: sqlparse.split(s),
            ]

        return calls


def _md_examples(tree: Path) -> list[str]:
    """The Markdown halves of mistune's CommonMark examples and of every
    ```` example ```` block of its fixture texts."""
    out: list[str] = []
    spec = tree / "tests" / "fixtures" / "commonmark.json"
    if spec.is_file() and not spec.is_symlink():
        try:
            data = json.loads(_text(spec))
        except ValueError:
            data = []
        for item in data if isinstance(data, list) else []:
            if isinstance(item, dict) and isinstance(item.get("markdown"), str):
                out.append(item["markdown"])
    fence = "`" * 32 + " example\n"
    for path in _files(tree, "tests/fixtures/*.txt"):
        for block in _text(path).split(fence)[1:]:
            out.append(block.split("\n.\n", 1)[0])
    return out


def _md_workload(tree: Path, package: str, seed: int) -> str | None:
    bench = _bench(tree, package)
    if bench is None:
        return None
    (document,) = _guard_attrs(bench, "_document")
    return str(document(random.Random(seed)))


class Mistune:
    package, src, workload_mode, unit = "mistune", True, "wl", "\n#"
    modes: Final = ("wl", "html", "esc")

    def generate(self, rng: random.Random) -> tuple[str, str]:
        r = rng.random()
        return ("wl" if r < 0.7 else "html" if r < 0.85 else "esc"), _m_gen(rng)

    def seeds(self, tree: Path) -> list[tuple[str, str]]:
        return [(self.modes[i % 3], t) for i, t in enumerate(_md_examples(tree))]

    def workload(self, tree: Path) -> str | None:
        return _md_workload(tree, self.package, 5)  # bench_mistune.main's seed

    def mutate(self, rng: random.Random, text: str) -> str:
        return _m_mutate(rng, text)

    def evaluator(self) -> Evaluate:
        import mistune  # type: ignore[import-not-found,import-untyped,unused-ignore]
        from mistune.renderers.html import (  # type: ignore[import-not-found,import-untyped,unused-ignore]
            HTMLRenderer,
        )

        render = {
            "wl": mistune.create_markdown(
                plugins=["table", "strikethrough", "footnotes"]
            ),
            "html": mistune.html,
            "esc": mistune.create_markdown(
                escape=True,
                hard_wrap=True,
                renderer=HTMLRenderer(escape=True, allow_harmful_protocols=True),
                plugins=["table", "footnotes"],
            ),  # fmt: skip
        }

        def calls(mode: str, s: str) -> list[Call]:
            return [lambda: render[mode](s)]

        return calls


MD_WL: Final = ("markdown.extensions.tables", "markdown.extensions.fenced_code",
                "markdown.extensions.abbr")  # fmt: skip
MD_WIDE: Final = (*MD_WL, *(f"markdown.extensions.{e}" for e in (
    "footnotes", "attr_list", "def_list", "smarty", "md_in_html", "toc", "sane_lists",
    "admonition", "legacy_em", "nl2br")))  # fmt: skip


class Markdown:
    package, src, workload_mode, unit = "markdown", False, "wl", "\n#"
    modes: Final = ("wl", "none", "wide", "reuse")

    def generate(self, rng: random.Random) -> tuple[str, str]:
        r = rng.random()
        mode = (
            "wl" if r < 0.55 else "none" if r < 0.7 else "wide" if r < 0.85 else "reuse"
        )
        return mode, _m_gen(rng)

    def seeds(self, tree: Path) -> list[tuple[str, str]]:
        texts = [_text(p) for d in ("basic", "extensions", "misc", "pl")
                 for p in _files(tree, f"tests/{d}/**/*.txt")]  # fmt: skip
        texts += _literals(_files(tree, "tests/test_syntax/**/*.py"), dedent=True)
        return [(self.modes[i % 4], t) for i, t in enumerate(texts)]

    def workload(self, tree: Path) -> str | None:
        return _md_workload(tree, self.package, 29)  # bench_markdown.main's seed

    def mutate(self, rng: random.Random, text: str) -> str:
        return _m_mutate(rng, text)

    def evaluator(self) -> Evaluate:
        import markdown  # type: ignore[import-not-found,import-untyped,unused-ignore]

        reuse = markdown.Markdown(extensions=list(MD_WL))

        def reused(s: str) -> object:
            try:
                return reuse.convert(s)
            finally:
                reuse.reset()

        convert: dict[str, Callable[[str], object]] = {
            "wl": lambda s: markdown.markdown(s, extensions=list(MD_WL)),
            "none": lambda s: markdown.markdown(s),
            "wide": lambda s: markdown.markdown(s, extensions=list(MD_WIDE)),
            "reuse": reused,
        }

        def calls(mode: str, s: str) -> list[Call]:
            return [lambda: convert[mode](s)]

        return calls


ADAPTERS: Final[Mapping[str, Callable[[], Adapter]]] = {
    "tomli": Tomli, "sqlparse": Sqlparse, "mistune": Mistune, "markdown": Markdown,
}  # fmt: skip


# ===========================================================================
# The child side: the fingerprint, the alarm, the commands
# ===========================================================================


class _Timeout(BaseException):
    """The per-input alarm (a ``BaseException``: library code's ``except
    Exception`` cannot swallow it)."""


def _alarm(signum: int, frame: FrameType | None) -> None:
    raise _Timeout


def type_tree(value: object, _path: frozenset[int] = frozenset()) -> object:
    """The exact types of ``value``: a mapping's keys and values in order, a
    sequence's or set's items, a scalar's module and qualified name; a
    container already on the path is ``<cycle ...>``, one past
    ``MAX_DEPTH`` containers ``<deep ...>`` (no deep recursion)."""
    name = f"{type(value).__module__}.{type(value).__qualname__}"
    if not isinstance(value, dict | list | tuple | set | frozenset):
        return name
    if id(value) in _path:
        return f"<cycle {name}>"
    if len(_path) >= MAX_DEPTH:
        return f"<deep {name}>"
    path = _path | {id(value)}
    if isinstance(value, dict):
        return (
            name,
            [(type_tree(k, path), type_tree(v, path)) for k, v in value.items()],
        )
    return (name, [type_tree(x, path) for x in value])


def fingerprint(value: object, how: Fingerprint = "type-aware") -> str:
    """``type-aware``: ``repr`` plus ``type_tree``; ``json``: the frozen
    judge's ``json.dumps(default=str)``, which this gate exists to beat."""
    try:
        if how == "json":
            return json.dumps(value, sort_keys=True, default=str)
        return repr(value) + "\n" + repr(type_tree(value))
    except (RecursionError, TypeError, ValueError) as error:  # a deep repr, odd keys
        return f"unfingerprintable: {type(error).__name__}"


def error_print(error: BaseException) -> str:
    """An exception on invalid input: its module, qualified name, message."""
    t = type(error)
    try:
        message = str(error)
    except Exception:  # noqa: BLE001 - a hostile __str__ is still an output
        message = "<unprintable message>"
    return f"!{t.__module__}.{t.__qualname__}: {message}"


def run_input(
    calls: Sequence[Call], alarm_s: float, how: Fingerprint
) -> tuple[str, str]:
    """``(status, fingerprint)`` of one input under one ``alarm_s`` alarm:
    ``o`` every call returned, ``e`` one raised, ``t`` the alarm fired."""
    status, parts = "o", []
    signal.setitimer(signal.ITIMER_REAL, alarm_s)
    try:
        for call in calls:
            try:
                parts.append(fingerprint(call(), how))
            except Exception as error:  # noqa: BLE001 - invalid input is an output
                status = "e"
                parts.append(error_print(error))
    except _Timeout:
        return "t", "timeout"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return status, "\n".join(parts)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def load_adapter(library: str, path: str | None) -> Adapter:
    """The built-in adapter of ``library``, or ``ADAPTER`` of the adapter
    file at ``path`` (loaded here, in the sandbox)."""
    if path is None:
        if library not in ADAPTERS:
            raise ValueError(f"no generator for {library!r}")
        return ADAPTERS[library]()
    spec = importlib.util.spec_from_file_location("_x2_equiv_adapter", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"{path!r} is not a Python file")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    adapter: Adapter = module.ADAPTER
    return adapter


def import_library(adapter: Adapter, tree: Path) -> ModuleType:
    """The tree's own package, first on the path; refused if Python found
    another copy."""
    root = (tree / "src" if adapter.src else tree).resolve()
    sys.path.insert(0, str(root))
    module = importlib.import_module(adapter.package)
    where = os.path.realpath(getattr(module, "__file__", None) or "")
    if not where.startswith(str(root) + os.sep):
        raise ValueError(f"{adapter.package} imported from {where}, not under {root}")
    return module


def sample(
    items: Sequence[tuple[str, str]], cap: int, rng: random.Random
) -> list[tuple[str, str]]:
    """``items`` when at most ``cap``, else a seeded sample in their order."""
    if len(items) <= cap:
        return list(items)
    return [items[i] for i in sorted(rng.sample(range(len(items)), cap))]


def windows(text: str, unit: str, count: int, rng: random.Random,
            mutate: Callable[[random.Random, str], str]) -> list[str]:  # fmt: skip
    """``count`` mutated windows of one to three consecutive units of the
    workload input (a unit ends where ``unit`` begins)."""
    pieces = text.split(unit)
    units = [pieces[0], *(unit + p for p in pieces[1:])]
    out = []
    for _ in range(count):
        start = rng.randrange(len(units))
        out.append(mutate(rng, "".join(units[start : start + rng.randint(1, 3)])))
    return out


def build_corpus(adapter: Adapter, tree: Path, *, size: int, seed: int, seed_cap: int,
                 workload: int) -> list[Case]:  # fmt: skip
    """The fixed corpus: ``size`` generator cases (the audit's stream), at
    most ``seed_cap`` of the tree's test data, ``workload`` mutated windows
    of the benchmark's input (none without a benchmark)."""
    rng = random.Random(seed)
    corpus = [["generator", *adapter.generate(rng)] for _ in range(size)]
    seeds = sample(adapter.seeds(tree), seed_cap, random.Random(f"{seed}-seeds"))
    corpus += [["seed", mode, text] for mode, text in seeds]
    text = adapter.workload(tree) if workload else None
    if text:
        mode = adapter.workload_mode
        cut = windows(text, adapter.unit, workload, random.Random(f"{seed}-workload"),
                      adapter.mutate)  # fmt: skip
        corpus += [["workload", mode, t] for t in cut]
    return corpus


def evaluate(evaluator: Evaluate, corpus: Sequence[Case], alarm_s: float,
             how: Fingerprint, show: int) -> dict[str, object]:  # fmt: skip
    """Every case's digest and status; with ``show``, each fingerprint's
    first ``show`` characters too."""
    hashes, status, shown = [], [], []
    for _, mode, text in corpus:
        st, out = run_input(evaluator(mode, text), alarm_s, how)
        hashes.append(digest(out))
        status.append(st)
        if show:
            shown.append(out[:show])
    return {"n": len(corpus), "hashes": hashes, "status": "".join(status),
            **({"shown": shown} if show else {})}  # fmt: skip


def seeded() -> bool:
    """Whether this interpreter's string hashes are fixed (``PYTHONHASHSEED=0``
    read: no ``-E`` or ``-I``)."""
    return not sys.flags.hash_randomization


def child_main(argv: Sequence[str]) -> int:
    """``corpus`` or ``eval``, one JSON result at ``--out``; an exception's
    type and message go there too (exit 3), so the parent can record it."""
    parser = argparse.ArgumentParser(prog="x2_equiv")
    parser.add_argument("command", choices=("corpus", "eval"))
    parser.add_argument("--lib", required=True)
    parser.add_argument("--tree", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--adapter")
    parser.add_argument("--corpus")
    parser.add_argument("--size", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seed-cap", type=int, default=0)
    parser.add_argument("--workload", type=int, default=0)
    parser.add_argument("--alarm", type=float, default=5.0)
    parser.add_argument(
        "--fingerprint", choices=("type-aware", "json"), default=FINGERPRINT
    )
    parser.add_argument("--show", type=int, default=0)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGALRM, _alarm)
    sys.dont_write_bytecode = True
    started = time.monotonic()
    if not seeded():  # PYTHONHASHSEED=0 is not in force
        Path(args.out).write_text(json.dumps({"error": RANDOMISED}), encoding="utf-8")
        return 3
    try:
        adapter = load_adapter(args.lib, args.adapter)
        tree = Path(args.tree)
        if args.command == "corpus":
            if args.workload:
                import_library(adapter, tree)  # the benchmark imports the tree's copy
            result: dict[str, object] = {"corpus": build_corpus(
                adapter, tree, size=args.size, seed=args.seed, seed_cap=args.seed_cap,
                workload=args.workload)}  # fmt: skip
        else:
            import_library(adapter, tree)
            corpus = json.loads(Path(args.corpus).read_text(encoding="utf-8"))
            result = evaluate(
                adapter.evaluator(), corpus, args.alarm, args.fingerprint, args.show
            )
        code = 0
    except Exception as error:  # noqa: BLE001 - recorded by the parent, never a pass
        result, code = {"error": error_print(error)[1:][:500]}, 3
    result["seconds"] = round(time.monotonic() - started, 3)
    Path(args.out).write_text(json.dumps(result), encoding="utf-8")
    return code


# ===========================================================================
# The parent side: sizes, settings, the sandboxed runs
# ===========================================================================


@dataclass(frozen=True)
class Size:
    """One library's corpus: generator cases, the seed cap, workload windows."""

    generator: int
    seed_cap: int
    workload: int


SIZES: Final[Mapping[str, Size]] = {
    # About 10 s of one tree's evaluation, sized from per-input costs measured
    # here at load 4-6 on 4 cores (the UEQ report has the full-size figures):
    # ms per input, generator / seed / workload: tomli 0.12 / 0.05 / 0.21,
    # sqlparse 10 / 1.3 / 20, mistune 0.95 / 0.17 / 3.5, markdown 1.8 / 0.5 / 3.1.
    "tomli": Size(60_000, 1_000, 8_000),
    "sqlparse": Size(600, 1_300, 100),
    "mistune": Size(7_000, 1_000, 800),
    "markdown": Size(3_500, 2_500, 700),
}
SMALL: Final = Size(200, 60, 40)  # a quick look: the tests' size


@dataclass(frozen=True)
class EquivSettings:
    size: Size | None = None  # ``None``: the library's ``SIZES`` entry
    seed: int = 1
    alarm_s: float = 5.0
    corpus_timeout_s: float = 300.0
    batch_timeout_s: float = 600.0
    minimise_s: float = 30.0
    fingerprint: Fingerprint = "type-aware"
    network: Literal["required", "best_effort", "off"] = "required"
    fs: Literal["required", "best_effort", "off"] = "required"
    python: str = sys.executable
    adapter: Path | None = None  # an adapter file in place of the built-in one

    def corpus_size(self, library: str) -> Size:
        return self.size or SIZES.get(library, SMALL)


EQUIV_ENV: Final = "LIVE_X2_EQUIV"


def equiv_on(environ: Mapping[str, str]) -> bool:
    """``$LIVE_X2_EQUIV``: ``record`` runs the gate after each run, ``off``
    (or unset) does not; anything else is refused."""
    value = environ.get(EQUIV_ENV, "off")
    if value not in ("off", "record"):
        raise ValueError(f"{EQUIV_ENV} must be off or record, not {value[:40]!r}")
    return value == "record"


RunOnce = Callable[..., "RunSample"]


@dataclass(frozen=True)
class Evaluated:
    """One ``eval`` run, checked; ``error`` (and ``timed_out``) when it gave
    no usable result."""

    hashes: list[str]
    status: str
    shown: list[str]
    seconds: float
    error: str | None = None
    timed_out: bool = False


@dataclass(frozen=True)
class ChildResult:
    data: dict[str, object] | None
    error: str | None
    seconds: float
    timed_out: bool


def _clip(text: str, n: int = CLIP) -> str:
    return text if len(text) <= n else f"{text[:n]}...[+{len(text) - n}]"


def _stderr_line(sample: RunSample) -> str:
    lines = sample.stderr_tail.decode("utf-8", "replace").strip().splitlines()
    return lines[-1][:200] if lines else "no stderr"


@dataclass
class Runner:
    """Runs the child under the engine's ``run_once`` in ``settings``'
    sandbox, one fresh scratch per run under ``work``."""

    work: Path
    settings: EquivSettings
    run: RunOnce | None = None  # ``procrun.run_once``; a test may swap it
    count: int = 0

    def __call__(
        self, args: Sequence[str], tree: Path, timeout_s: float
    ) -> ChildResult:
        from autonomous_ai_agents.execution.procrun import (
            OutputCaps,
            RunFailure,
            run_once,
        )
        from autonomous_ai_agents.execution.sandbox import SandboxPolicy, child_env

        self.count += 1
        top = self.work / "runs" / f"{self.count:04d}"
        for made in (top / "cwd", top / "scratch", top / "probe"):
            made.mkdir(parents=True, mode=0o700)
        policy: SandboxPolicy = SandboxPolicy(
            self.settings.network, self.settings.fs, (top / "cwd", top / "scratch"),
            top / "probe", sys.platform)  # fmt: skip
        cwd, scratch = policy.writable
        home, tmp, out = scratch / "home", scratch / "tmp", cwd / "out.json"
        cfg = self.settings
        argv = [cfg.python, *CHILD_FLAGS, str(CHILD), *args, "--out", str(out),
                *([] if cfg.adapter is None else ["--adapter", str(cfg.adapter)])]  # fmt: skip
        env = child_env(home=home, tmpdir=tmp, worktree=tree.resolve())
        env.pop("PYTHONPATH")  # the child puts the tree's package first itself
        started = time.monotonic()
        try:
            sample = (self.run or run_once)(argv, cwd, env, policy, timeout_s,
                                            OutputCaps(65_536, 4_096, 4_096),
                                            fresh_dirs=(scratch, home, tmp))  # fmt: skip
        except RunFailure as failure:
            return ChildResult(None, safe_text(failure.reason), time.monotonic() - started,
                               failure.reason.startswith("timeout after"))  # fmt: skip
        seconds = time.monotonic() - started
        try:
            data = json.loads(read_result(out).decode("utf-8"))
        except RefusedResultError as refused:
            return ChildResult(None, str(refused), seconds, False)
        except (OSError, ValueError, RecursionError):  # no file, not UTF-8, not JSON
            why = f"exit {sample.exit}: {_stderr_line(sample)}"
            return ChildResult(None, safe_text(why), seconds, False)
        if not isinstance(data, dict) or "error" in data:
            error = data.get("error") if isinstance(data, dict) else "not an object"
            return ChildResult(None, safe_text(str(error)), seconds, False)
        return ChildResult(data, None, seconds, False)


class RefusedResultError(ValueError):
    """The child's result file is not one the parent will read."""


def read_result(path: Path) -> bytes:
    """The child's result file, which sits where the trial's code can write:
    opened without following a link and without blocking (a FIFO), checked
    to be a plain file, read to at most ``MAX_RESULT_BYTES`` (a device
    would never end); ``RefusedResultError``, or ``OSError`` if missing."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:  # a symlink
            raise RefusedResultError("the result is not a plain file") from None
        raise
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise RefusedResultError("the result is not a plain file")
        chunks, size = [], 0
        while size <= MAX_RESULT_BYTES:
            chunk = os.read(fd, min(1 << 20, MAX_RESULT_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > MAX_RESULT_BYTES:
            raise RefusedResultError("the result is larger than MAX_RESULT_BYTES")
        return b"".join(chunks)
    finally:
        os.close(fd)


def safe_text(text: str, n: int = ERROR_CHARS) -> str:
    """``text`` for a row: keys redacted first, then clipped, so a key that
    straddles the clip leaves no prefix behind."""
    from .conftest import redact_keys

    return _clip(redact_keys(text), n)


# ===========================================================================
# The parent side: the base once, then each trial tree
# ===========================================================================


@dataclass
class Baseline:
    """The base's corpus and hashes, computed once per base."""

    corpus_path: Path | None
    corpus: list[Case]
    hashes: list[str]
    status: str
    seconds: float
    corpus_sha256: str | None
    error: str | None = None
    state: str = COMPARED  # or ``NO_GENERATOR``, ``ERROR``, ``TIMEOUT``

    def summary(self) -> dict[str, object]:
        sources: dict[str, int] = {}
        for source, _, _ in self.corpus:
            sources[source] = sources.get(source, 0) + 1
        return {"status": self.state, "cases": len(self.corpus), "sources": sources,
                "corpus_sha256": self.corpus_sha256, "seconds": round(self.seconds, 3),
                "timeouts": self.status.count("t"), "errors": self.status.count("e"),
                "error": self.error, "fingerprint": FINGERPRINT}  # fmt: skip


def _blank(state: str, error: str | None, seconds: float, timed_out: bool,
           base: Baseline | None) -> dict[str, object]:  # fmt: skip
    """A record of a tree that was not compared: ``mismatches`` is ``None``."""
    return {"status": state, "fingerprint": FINGERPRINT, "cases": 0, "mismatches": None,
            "groups": {}, "kinds": {}, "timeouts": 0, "counterexample": None,
            "seconds": round(seconds, 3), "timed_out": timed_out, "error": error,
            "corpus_sha256": None if base is None else base.corpus_sha256}  # fmt: skip


@dataclass
class Equivalence:
    """One library's gate against one base tree: ``record`` per trial tree,
    the base's corpus and hashes computed on first use and reused."""

    library: str
    base_tree: Path
    work: Path
    settings: EquivSettings = field(default_factory=EquivSettings)
    run: RunOnce | None = None
    _base: Baseline | None = None
    _runner: Runner | None = None

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            self._runner = Runner(self.work, self.settings, self.run)
        return self._runner

    @property
    def base(self) -> Baseline:
        if self._base is None:
            self._base = self._baseline()
        return self._base

    def _baseline(self) -> Baseline:
        cfg, size = self.settings, self.settings.corpus_size(self.library)
        if cfg.adapter is None and self.library not in ADAPTERS:
            return Baseline(None, [], [], "", 0.0, None, f"no generator for {self.library}",
                            NO_GENERATOR)  # fmt: skip
        built = self.runner(["corpus", "--lib", self.library, "--tree", str(self.base_tree),
                             "--size", str(size.generator), "--seed", str(cfg.seed),
                             "--seed-cap", str(size.seed_cap),
                             "--workload", str(size.workload)],
                            self.base_tree, cfg.corpus_timeout_s)  # fmt: skip
        if built.data is None:
            state = TIMEOUT if built.timed_out else ERROR
            return Baseline(None, [], [], "", built.seconds, None,
                            f"the corpus was not built: {built.error}", state)  # fmt: skip
        try:
            corpus = corpus_result(built.data)
        except ValueError as error:
            return Baseline(None, [], [], "", built.seconds, None, str(error), ERROR)
        path = self.work / "corpus.json"
        path.write_text(json.dumps(corpus), encoding="utf-8")
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        ran = self._eval(self.base_tree, path, 0)
        if ran.error is not None:
            state = TIMEOUT if ran.timed_out else ERROR
            return Baseline(path, corpus, [], "", built.seconds + ran.seconds, sha,
                            f"the base did not run: {ran.error}", state)  # fmt: skip
        return Baseline(
            path, corpus, ran.hashes, ran.status, built.seconds + ran.seconds, sha
        )

    def _eval(self, tree: Path, corpus: Path, show: int,
              timeout_s: float | None = None) -> Evaluated:  # fmt: skip
        cfg = self.settings
        ran = self.runner(["eval", "--lib", self.library, "--tree", str(tree), "--corpus",
                           str(corpus), "--alarm", str(cfg.alarm_s), "--fingerprint",
                           cfg.fingerprint, "--show", str(show)],
                          tree, cfg.batch_timeout_s if timeout_s is None else timeout_s)  # fmt: skip
        if ran.data is None:
            return Evaluated([], "", [], ran.seconds, ran.error, ran.timed_out)
        try:
            hashes, status, shown = eval_result(ran.data, bool(show))
        except ValueError as error:
            return Evaluated([], "", [], ran.seconds, str(error))
        return Evaluated(hashes, status, shown, ran.seconds)

    def record(self, trial_tree: Path) -> dict[str, object]:
        """The trial tree against the base: see the module docstring."""
        base, started = self.base, time.monotonic()
        if base.state != COMPARED:
            return _blank(base.state, base.error, 0.0, base.state == TIMEOUT, base)
        assert base.corpus_path is not None
        ran = self._eval(trial_tree, base.corpus_path, 0)
        if ran.error is not None:
            state = TIMEOUT if ran.timed_out else ERROR
            return _blank(state, f"the trial did not run: {ran.error}", ran.seconds,
                          ran.timed_out, base)  # fmt: skip
        hashes, status = ran.hashes, ran.status
        if len(hashes) != len(base.hashes):
            return _blank(ERROR, f"{len(hashes)} results for {len(base.hashes)} cases",
                          ran.seconds, False, base)  # fmt: skip
        groups: dict[str, int] = {}
        kinds: dict[str, int] = {}
        bad, timeouts = [], 0
        for i, (b, t) in enumerate(zip(base.hashes, hashes, strict=True)):
            sb, st = base.status[i], status[i]
            if "t" in (sb, st):
                timeouts += 1
                continue
            if b != t:
                bad.append(i)
                key = f"{base.corpus[i][0]}/{base.corpus[i][1]}"
                groups[key] = groups.get(key, 0) + 1
                kind = "value" if sb == st == "o" else "error" if sb == st else "status"
                kinds[kind] = kinds.get(kind, 0) + 1
        if len(hashes) == timeouts:  # nothing was compared: never a 0
            why = "every input timed out" if timeouts else "the corpus is empty"
            return {**_blank(TIMEOUT if timeouts else ERROR, why,
                             time.monotonic() - started, timeouts > 0, base),
                    "timeouts": timeouts}  # fmt: skip
        example = self._counterexample(trial_tree, bad, started) if bad else None
        return {"status": COMPARED, "fingerprint": FINGERPRINT, "cases": len(hashes) - timeouts,
                "mismatches": len(bad), "groups": dict(sorted(groups.items())),
                "kinds": dict(sorted(kinds.items())), "timeouts": timeouts,
                "counterexample": example, "seconds": round(time.monotonic() - started, 3),
                "timed_out": timeouts > 0, "error": None,
                "corpus_sha256": base.corpus_sha256}  # fmt: skip

    # ---- minimisation ----------------------------------------------------

    def _differs(self, trial: Path, mode: str, texts: Sequence[str],
                 deadline: float) -> tuple[int, str, str] | None:  # fmt: skip
        """The first of ``texts`` on which the two trees differ, with both
        fingerprints, or ``None`` (a timeout on either side never counts);
        each run gets what is left until ``deadline``, at least
        ``MIN_EVAL_S``, never more than the batch timeout."""
        path = self.work / f"min-{self.runner.count:04d}.json"
        path.write_text(json.dumps([["min", mode, t] for t in texts]), encoding="utf-8")
        left = min(
            self.settings.batch_timeout_s, max(deadline - time.monotonic(), MIN_EVAL_S)
        )
        a = self._eval(self.base_tree, path, SHOW, left)
        b = self._eval(trial, path, SHOW, left)
        if a.error is not None or b.error is not None or len(a.hashes) != len(b.hashes):
            return None
        for i, (x, y) in enumerate(zip(a.hashes, b.hashes, strict=True)):
            if x != y and "t" not in (a.status[i], b.status[i]):
                return i, a.shown[i], b.shown[i]
        return None

    def _counterexample(
        self, trial: Path, bad: Sequence[int], started: float
    ) -> dict[str, object]:
        """The first mismatch that reproduces alone (of the first five),
        delta-debugged on its text until ``minimise_s`` runs out."""
        base, deadline = self.base, started + self.settings.minimise_s
        found: tuple[int, tuple[str, str, str, int] | None] = (bad[0], None)
        for i in bad[:5]:
            _, mode, text = base.corpus[i]
            hit = self._differs(trial, mode, [text], deadline)
            if hit is not None:
                found = (i, self._shrink(trial, mode, text, hit, deadline))
                break
            if time.monotonic() > deadline:
                break
        i, shrunk = found
        source, mode, text = base.corpus[i]
        small, shown, rounds = (text, None, 0) if shrunk is None else (
            shrunk[0], (shrunk[1], shrunk[2]), shrunk[3])  # fmt: skip
        return {"case": i, "group": f"{source}/{mode}", "mode": mode,
                "input": safe_text(small, CLIP),
                "input_chars": len(text), "minimised_chars": len(small),
                "reproduced": shown is not None, "rounds": rounds,
                "base": None if shown is None else safe_text(shown[0], CLIP),
                "trial": None if shown is None else safe_text(shown[1], CLIP)}  # fmt: skip

    def _shrink(self, trial: Path, mode: str, text: str, hit: tuple[int, str, str],
                deadline: float) -> tuple[str, str, str, int]:  # fmt: skip
        """ddmin over characters: drop one of ``n`` chunks while the trees
        still differ, halving the chunks when none can go; the text, both
        fingerprints on it and the rounds."""
        s, shown, n, rounds = text, (hit[1], hit[2]), 2, 0
        while len(s) >= 2 and rounds < MAX_ROUNDS and time.monotonic() < deadline:
            rounds += 1
            chunk = math.ceil(len(s) / n)
            cands = [s[:k] + s[k + chunk :] for k in range(0, len(s), chunk)]
            found = self._differs(trial, mode, cands, deadline)
            if found is not None:
                s, shown, n = cands[found[0]], (found[1], found[2]), max(n - 1, 2)
            elif n >= len(s):
                break
            else:
                n = min(len(s), 2 * n)
        return s, shown[0], shown[1], rounds


def corpus_result(data: Mapping[str, object]) -> list[Case]:
    """The child's corpus, checked: a list of ``[source, mode, text]``."""
    corpus = data.get("corpus")
    if not isinstance(corpus, list) or not all(
        isinstance(c, list) and len(c) == 3 and all(isinstance(x, str) for x in c)
        for c in corpus
    ):
        raise ValueError("the corpus was not built: the child's corpus is malformed")
    return corpus


def eval_result(
    data: Mapping[str, object], show: bool
) -> tuple[list[str], str, list[str]]:
    """The child's ``eval`` result, checked (the trial's code shares that
    process): one hash and one status letter per case, and with ``show``
    one fingerprint per case."""
    hashes, status, shown = (
        data.get("hashes"),
        data.get("status"),
        data.get("shown", []),
    )
    if not (isinstance(hashes, list) and isinstance(status, str) and isinstance(shown, list)
            and len(status) == len(hashes) and set(status) <= set("oet")
            and all(isinstance(h, str) for h in hashes)
            and all(isinstance(x, str) for x in shown)
            and (len(shown) == len(hashes) if show else not shown)):  # fmt: skip
        raise ValueError("the child's result is malformed")
    return list(hashes), status, list(shown)


_GATES: dict[tuple[str, str, EquivSettings], Equivalence] = {}


def equivalence_record(library: str, base_tree: Path, trial_tree: Path, *,
                       work: Path | None = None,
                       settings: EquivSettings | None = None) -> dict[str, object]:  # fmt: skip
    """The record of ``trial_tree`` against ``base_tree``; the base's corpus
    and hashes are computed on the first call for this base and settings
    and reused (``work``: where the runs live, a temporary directory if
    none; a given ``work`` is used by the first call only)."""
    cfg = settings or EquivSettings()
    key = (library, os.path.realpath(base_tree), cfg)
    if key not in _GATES:
        import tempfile

        where = work if work is not None else Path(tempfile.mkdtemp(prefix="x2-equiv-"))
        where.mkdir(parents=True, exist_ok=True)
        _GATES[key] = Equivalence(library, base_tree, where, cfg)
    return _GATES[key].record(trial_tree)


# ===========================================================================
# The parent side: the run's archive
# ===========================================================================

_GIT_ENV: Final = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
}


def _git(args: Sequence[str], cwd: Path, *, stdin: bytes | None = None,
         ceiling: Path | None = None) -> subprocess.CompletedProcess[bytes]:  # fmt: skip
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": os.devnull, **_GIT_ENV}
    if ceiling is not None:
        env["GIT_CEILING_DIRECTORIES"] = str(ceiling)
    return subprocess.run(  # nosec B603 - fixed argv, data only as files
        ["git", *args], cwd=cwd, env=env, input=stdin, capture_output=True,
        timeout=300, check=False)  # fmt: skip


def export_base(clone: Path, commit: str, dest: Path) -> None:
    """``commit`` of ``clone`` as a plain tree at ``dest`` (``git archive``;
    nothing in the clone moves), every member checked by ``tarfile``'s data
    filter."""
    if _COMMIT.fullmatch(commit) is None:
        raise ValueError(f"not a commit id: {commit[:64]!r}")
    done = _git(["archive", "--format=tar", commit], clone)
    if done.returncode != 0:
        raise ValueError(f"git archive {commit[:12]} failed: {_first(done.stderr)}")
    dest.mkdir(parents=True)
    import io

    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
        archive.extractall(dest, filter="data")


def _first(data: bytes) -> str:
    lines = data.decode("utf-8", "replace").strip().splitlines()
    return lines[0][:200] if lines else "no message"


def archived_diff(entry: Mapping[str, object], artifact_root: Path) -> Path:
    """The file an archive entry names, checked: written (no ``error``), not
    truncated, one plain file under ``live-patches/`` of ``artifact_root``,
    at most ``MAX_DIFF_BYTES``, of the entry's sha256 (``ValueError``)."""
    from .x2_patches import PATCH_DIR

    rel = entry.get("file")
    if entry.get("error") or not isinstance(rel, str):
        raise ValueError(
            f"no diff file: {str(entry.get('error') or 'none recorded')[:200]}"
        )
    if entry.get("truncated"):
        raise ValueError("the diff was truncated by the engine's cap")
    root = artifact_root.resolve()
    path = artifact_root / rel
    if (
        not rel.startswith(f"{PATCH_DIR}/")
        or ".." in Path(rel).parts
        or path.is_symlink()
    ):
        raise ValueError(f"not a patch file: {rel[:120]!r}")
    if not path.resolve().is_relative_to(root / PATCH_DIR) or not path.is_file():
        raise ValueError(f"not a patch file: {rel[:120]!r}")
    if path.stat().st_size > MAX_DIFF_BYTES:
        raise ValueError("the diff is larger than MAX_DIFF_BYTES")
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry.get("sha256"):
        raise ValueError("the diff's sha256 is not the entry's")
    return path


def apply_diff(base_tree: Path, diff: Path, dest: Path) -> str | None:
    """A fresh copy of ``base_tree`` at ``dest`` with ``diff`` applied
    (``git apply``, which refuses paths outside the tree); ``None``, or why
    it did not apply."""
    shutil.copytree(base_tree, dest, symlinks=True)
    done = _git(["apply", "--whitespace=nowarn", "--", str(diff.resolve())], dest,
                ceiling=dest.parent)  # fmt: skip
    return None if done.returncode == 0 else f"git apply failed: {_first(done.stderr)}"


def _entries(archive: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    found = archive.get(key)
    return (
        [e for e in found if isinstance(e, Mapping)] if isinstance(found, list) else []
    )


@dataclass(frozen=True)
class EquivRows:
    """One run's records: ``trials`` keyed by trial id (kept and
    inconclusive), the delivered tip's (``None`` when no patch was
    delivered) and the base's own summary; apart, so no trial id can stand
    for the tip or the base."""

    trials: dict[str, dict[str, object]]
    delivered: dict[str, object] | None
    base: dict[str, object]


_FAILURES: Final = (
    OSError,
    ValueError,
    RecursionError,
    tarfile.TarError,
    subprocess.SubprocessError,
)


def _why(error: BaseException) -> str:
    """A failure for a row: this module's own ``ValueError`` text as is,
    anything else by its type and message, redacted and clipped."""
    if type(error) is ValueError:
        return safe_text(str(error))
    return safe_text(f"{type(error).__name__}: {error}")


def equiv_rows(library: str, clone: Path, archive: Mapping[str, object], artifact_root: Path,
               work: Path, settings: EquivSettings | None = None,
               run: RunOnce | None = None) -> EquivRows:  # fmt: skip
    """The ``equiv`` records of one finished run's archive (``EquivRows``),
    each with its ``trial_id`` (``None`` for the tip). Each diff is applied
    to a fresh copy of its entry's base commit, exported from ``clone``; one
    gate per base, so its hashes are computed once. Writes only under
    ``work``; reads the archive and the clone; never raises on a bad entry,
    a bad base or a failing run (the record says why)."""
    cfg = settings or EquivSettings()
    gates: dict[str, Equivalence | str] = {}
    trials: dict[str, dict[str, object]] = {}

    def gate(commit: object) -> Equivalence | str:
        key = str(commit)
        if key not in gates:
            where = work / f"base-{len(gates)}"
            try:
                export_base(clone, key, where / "tree")
            except _FAILURES as error:
                gates[key] = f"the base was not exported: {_why(error)}"
            else:
                gates[key] = Equivalence(library, where / "tree", where, cfg, run)
        return gates[key]

    def checked(entry: Mapping[str, object], tree: Path) -> dict[str, object]:
        started = time.monotonic()
        g = gate(entry.get("base_commit") or archive.get("base_commit"))
        if isinstance(g, str):
            return _blank(ERROR, g, 0.0, False, None)
        try:
            diff = archived_diff(entry, artifact_root)
        except ValueError as error:
            return _blank(NOT_APPLIED, str(error), 0.0, False, None)
        where = g.work / tree
        try:
            why = apply_diff(g.base_tree, diff, where)
            if why is not None:
                return _blank(NOT_APPLIED, safe_text(why), time.monotonic() - started,
                              False, None)  # fmt: skip
            record = g.record(where)
        finally:
            shutil.rmtree(where, ignore_errors=True)
        return {**record, "seconds": round(time.monotonic() - started, 3)}

    def one(name: str | None, entry: Mapping[str, object]) -> dict[str, object]:
        try:
            record = checked(entry, Path(f"trial-{len(trials):03d}"))
        except _FAILURES as error:
            record = _blank(ERROR, _why(error), 0.0, False, None)
        return {**record, "trial_id": name}

    for key in ("kept_diffs", "inconclusive_diffs"):
        for entry in _entries(archive, key):
            name = str(entry.get("trial_id"))
            if name not in trials:
                trials[name] = one(name, entry)
    patch = archive.get("delivered_patch")
    delivered = one(None, patch) if isinstance(patch, Mapping) else None
    first = gates.get(str(archive.get("base_commit")))
    if isinstance(first, Equivalence):
        try:
            base = first.base.summary()
        except _FAILURES as error:
            base = {"status": ERROR, "error": _why(error)}
    else:
        base = {"status": ERROR if first else "not needed", "error": first}
    return EquivRows(trials, delivered, base)


if __name__ == "__main__":
    sys.exit(child_main(sys.argv[1:]))
