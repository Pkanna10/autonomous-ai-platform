"""``parse_traceback``: the last traceback of a stderr tail, as CPython 3.8-3.14 print it.

The fixtures are real stderr (paths shortened to ``/wt``); the live per-version
runs are in ``test_retry_templates.py``.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.execution.crash import CrashFrame, parse_traceback

CHAINED_38 = b"""\
Traceback (most recent call last):
  File "m.py", line 8, in f
    return x["b"]
KeyError: 'b'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "m.py", line 11, in <module>
    A().meth()
  File "m.py", line 4, in inner
    return f({"a": {}})
  File "m.py", line 10, in f
    return undefined_q
NameError: name 'undefined_q' is not defined
"""
CARETS_313 = b"""\
Traceback (most recent call last):
  File "/wt/m.py", line 11, in <module>
    A().meth()
    ~~~~~~~~^^
  File "/wt/m.py", line 4, in inner
    return f({"a": {}})
           ~^^^^^^^^^^^
  File "/wt/m.py", line 10, in f
    return undefined_q
           ^^^^^^^^^^^
NameError: name 'undefined_q' is not defined
"""
SYNTAX_VIA_IMPORT_311 = b"""\
Traceback (most recent call last):
  File "/wt/imp.py", line 1, in <module>
    import s
  File "/wt/s.py", line 1
    def f(
         ^
SyntaxError: '(' was never closed
"""
SYNTAX_DIRECT_38 = (
    b'  File "s.py", line 2\n'
    b"    \n"  # 3.8 prints the empty source line indented
    b"          ^\n"
    b"SyntaxError: unexpected EOF while parsing\n"
)
RECURSION = b"""\
Traceback (most recent call last):
  File "/wt/r.py", line 3, in <module>
    f()
  File "/wt/r.py", line 2, in f
    def f(): return f()
  [Previous line repeated 996 more times]
RecursionError: maximum recursion depth exceeded
"""


def test_a_chained_traceback_gives_the_last_exception_and_its_frames() -> None:
    """
    GIVEN 3.8's chained stderr (relative main path, no carets)
    WHEN it is parsed
    THEN only the last block counts: its type, message and frames, outermost first
    """
    crash = parse_traceback(CHAINED_38)

    assert crash is not None
    assert (crash.exc_type, crash.message) == (
        "NameError",
        "name 'undefined_q' is not defined",
    )
    assert crash.frames == (
        CrashFrame("m.py", 11, "<module>"),
        CrashFrame("m.py", 4, "inner"),
        CrashFrame("m.py", 10, "f"),
    )


def test_frame_carets_are_skipped() -> None:
    crash = parse_traceback(CARETS_313)

    assert crash is not None
    assert [frame.line for frame in crash.frames] == [11, 4, 10]
    assert crash.frames[-1] == CrashFrame("/wt/m.py", 10, "f")


@pytest.mark.parametrize(
    ("tail", "location", "message"),
    [
        (
            SYNTAX_VIA_IMPORT_311,
            CrashFrame("/wt/s.py", 1, None),
            "'(' was never closed",
        ),
        (SYNTAX_DIRECT_38, CrashFrame("s.py", 2, None), "unexpected EOF while parsing"),
    ],
    ids=["via-import", "direct"],
)
def test_a_syntax_error_location_is_the_innermost_frame_with_no_function(
    tail: bytes, location: CrashFrame, message: str
) -> None:
    crash = parse_traceback(tail)

    assert crash is not None
    assert (crash.exc_type, crash.message, crash.frames[-1]) == (
        "SyntaxError",
        message,
        location,
    )


def test_a_cut_tail_keeps_the_frames_it_still_holds() -> None:
    """GIVEN a tail cut inside the first frame WHEN parsed THEN the rest parses."""
    crash = parse_traceback(CARETS_313[60:] + b"\n\n")

    assert crash is not None
    assert [frame.line for frame in crash.frames] == [4, 10]


def test_repeated_frame_lines_are_skipped() -> None:
    crash = parse_traceback(RECURSION)

    assert crash is not None
    assert [frame.line for frame in crash.frames] == [3, 2]
    assert crash.message == "maximum recursion depth exceeded"


def test_a_bare_exception_line_has_no_message() -> None:
    crash = parse_traceback(
        b'Traceback (most recent call last):\n  File "/wt/a.py", line 1, in <module>\n    raise KeyboardInterrupt\nKeyboardInterrupt\n'
    )

    assert crash is not None
    assert (crash.exc_type, crash.message) == ("KeyboardInterrupt", None)


@pytest.mark.parametrize(
    "tail",
    [
        b"",
        b"\n\n",
        b"Error: something went wrong\n",
        b"\x1b[35mNameError\x1b[0m: name 'x' is not defined\n",
        CARETS_313 + b"exiting\nnow done!\n",
    ],
    ids=["empty", "blank", "no-frames", "coloured-type", "trailing-output"],
)
def test_no_traceback_gives_none(tail: bytes) -> None:
    assert parse_traceback(tail) is None
