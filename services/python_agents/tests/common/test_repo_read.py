"""The shared repository read rules (Wave 2, N1a; spec amendment D44).

``common/repo_read.py`` holds the reader Protocol and the rules the
understander already applied (git's 8,000-byte binary sniff, an incremental
UTF-8 decode of the head with a cut flag, ``READ_DENY_PATTERNS``, the
unprintable test), so the idea pipeline's code context reads with the same
policy and ``optimization/`` never imports ``orchestrator/``.
``orchestrator/understand.py`` re-exports what its tests import from it.
"""

from __future__ import annotations

import pytest

from autonomous_ai_agents.common import repo_read
from autonomous_ai_agents.common.repo_read import (
    BINARY,
    BINARY_SNIFF_BYTES,
    DENIED,
    NOT_UTF8,
    ReadText,
    RepoReader,
    read_denied,
    read_text,
    unprintable,
)
from autonomous_ai_agents.orchestrator import understand

SHA = "0123456789abcdef0123456789abcdef01234567"


class _Reader:
    """A ``RepoReader`` over a dict; records every ``read_blob`` call."""

    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs
        self.calls: list[tuple[str, str, int | None]] = []

    def ls_tree(self, commit: str) -> tuple[str, ...]:
        return tuple(sorted(self.blobs))

    def read_blob(self, commit: str, path: str, *, limit: int | None = None) -> bytes:
        self.calls.append((commit, path, limit))
        data = self.blobs[path]
        return data if limit is None else data[:limit]


def _read(
    blobs: dict[str, bytes], path: str, cap: int
) -> tuple[ReadText | str, _Reader]:
    reader = _Reader(blobs)
    return read_text(reader, SHA, path, cap=cap), reader


def test_the_reader_protocol_and_sniff_size_are_the_understanders() -> None:
    """
    GIVEN the moved rules
    WHEN understand.py is imported
    THEN it re-exports the very same objects (its tests import them there)
    """
    assert understand.RepoReader is RepoReader
    assert understand.BINARY_SNIFF_BYTES is BINARY_SNIFF_BYTES == 8000
    reader: RepoReader = _Reader({})
    assert reader.ls_tree(SHA) == ()


def test_a_small_text_file_is_read_whole_and_not_cut() -> None:
    found, reader = _read({"a.py": b"x = 1\n"}, "a.py", cap=100)
    assert found == ReadText(text="x = 1\n", cut=False)
    # git hands over at most one byte past the cap, never less than the sniff
    assert reader.calls == [(SHA, "a.py", BINARY_SNIFF_BYTES)]


def test_a_file_past_the_cap_is_cut_at_the_cap_with_the_flag() -> None:
    data = b"y" * 9000 + b"\n"
    found, reader = _read({"big.py": data}, "big.py", cap=8500)
    assert found == ReadText(text="y" * 8500, cut=True)
    assert reader.calls == [(SHA, "big.py", 8501)]


def test_a_file_of_exactly_the_cap_is_not_cut() -> None:
    found, _ = _read({"e.py": b"z" * 10}, "e.py", cap=10)
    assert found == ReadText(text="z" * 10, cut=False)


def test_a_character_split_by_the_cut_is_left_out_not_an_error() -> None:
    """The head is decoded incrementally: a split code point at the cut is
    dropped, while the same bytes at the true end are not UTF-8."""
    data = "ab\u00e9".encode()  # '\u00e9' is two bytes: the cut at 3 splits it
    found, _ = _read({"s.py": data + b"tail"}, "s.py", cap=3)
    assert found == ReadText(text="ab", cut=True)
    whole, _ = _read({"t.py": data[:3]}, "t.py", cap=3)
    assert whole == NOT_UTF8


def test_a_nul_in_the_first_8000_bytes_is_binary_and_one_after_is_not() -> None:
    sniffed = b"a" * (BINARY_SNIFF_BYTES - 1) + b"\0"
    found, _ = _read({"bin.dat": sniffed}, "bin.dat", cap=BINARY_SNIFF_BYTES)
    assert found == BINARY == "binary"
    late = b"a" * BINARY_SNIFF_BYTES + b"\0"
    found, _ = _read({"late.py": late}, "late.py", cap=BINARY_SNIFF_BYTES)
    assert found == ReadText(text="a" * BINARY_SNIFF_BYTES, cut=True)


def test_a_nul_past_a_small_cap_is_still_sniffed() -> None:
    """The read always covers the sniff window, so a short cap cannot hide a
    NUL that git's rule would see."""
    data = b"a" * 50 + b"\0" + b"b" * 10
    found, reader = _read({"x.bin": data}, "x.bin", cap=10)
    assert found == BINARY
    assert reader.calls[0][2] == BINARY_SNIFF_BYTES


def test_invalid_utf8_is_refused() -> None:
    found, _ = _read({"l1.py": b"caf\xe9 = 1\n"}, "l1.py", cap=100)
    assert found == NOT_UTF8 == "not UTF-8"


@pytest.mark.parametrize(
    "path",
    [".env", "app/.env.local", "certs/server.pem", "deploy/id_rsa", "secrets.toml"],
)
def test_a_read_deny_path_is_never_asked_of_git(path: str) -> None:
    """
    GIVEN a path matching READ_DENY_PATTERNS
    WHEN read_text is asked for it
    THEN the reason is returned and the reader is never called
    """
    assert read_denied(path)
    found, reader = _read({path: b"TOKEN=1\n"}, path, cap=100)
    assert found == DENIED
    assert reader.calls == []


def test_an_ordinary_path_is_not_denied() -> None:
    assert not read_denied("pkg/core.py")


@pytest.mark.parametrize("cap", [0, -1])
def test_a_cap_below_one_is_a_programming_error(cap: int) -> None:
    with pytest.raises(ValueError, match="cap"):
        read_text(_Reader({"a.py": b"x"}), SHA, "a.py", cap=cap)


def test_a_reader_error_propagates_for_the_caller_to_classify() -> None:
    """``read_text`` names no git error type (``common`` does not import
    ``execution``): the understander keeps its own ``GitError`` handling."""

    class _Broken(_Reader):
        def read_blob(
            self, commit: str, path: str, *, limit: int | None = None
        ) -> bytes:
            raise OSError("gone")

    with pytest.raises(OSError, match="gone"):
        read_text(_Broken({}), SHA, "a.py", cap=10)


@pytest.mark.parametrize(
    "text",
    ["a\x00b", "tab\tinside", "line\nbreak", "del\x7f", "nel\x85", "\u200e", "\u2028",
     "\u202e", "\u2066", "\ud800"],
)  # fmt: skip
def test_unprintable_flags_controls_separators_bidi_and_lone_surrogates(
    text: str,
) -> None:
    assert unprintable(text)


@pytest.mark.parametrize("text", ["plain", "caf\u00e9", "\u4e2d\u6587", "a-b_c.py"])
def test_unprintable_passes_ordinary_text(text: str) -> None:
    assert not unprintable(text)


def test_the_pattern_is_the_one_the_understander_used() -> None:
    """The regex is moved verbatim (C0, DEL, C1, LRM/RLM, the separators and
    the bidi controls)."""
    assert repo_read.UNPRINTABLE.pattern == (
        "[\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u2028-\\u202e\\u2066-\\u2069]"
    )
