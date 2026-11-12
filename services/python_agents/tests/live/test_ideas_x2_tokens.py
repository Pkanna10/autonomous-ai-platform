"""U-tokens: the leap's output tokens against its cap (X2-L), offline.

GIVEN results files whose round rows carry ``lane_views`` with the output
tokens, cap and stop reason of each lane request, WHEN ``ideas_x2_tokens``
renders, THEN each leap call prints its model, output / cap, stop reason and
headroom, and each arm its least, median and most headroom.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import ideas_x2 as x2
from . import ideas_x2_report as xr
from . import ideas_x2_tokens as xt
from . import test_ideas_x2_report_guards as rg

FABLE = "claude-fable-5-2"


def _view(lane: str, model: str | None, out: int | None, cap: int | None,
          stop: str | None, attempts: str | None = None) -> dict[str, object]:  # fmt: skip
    return {"lane": lane, "view_sha": "ab12cd34", "served_model": model,
            "output_tokens": out, "max_tokens": cap, "stop_reason": stop,
            "attempt_output_tokens": attempts}  # fmt: skip


def _viewed(arm: str, repo: str, *rounds: list[dict[str, object]]) -> list[rg.Row]:
    rows = rg._rows(arm, repo, [(1, []) for _ in rounds])
    lines = [r for r in rows if r["experiment"] == x2.ROUND_EXPERIMENT]
    for line, views in zip(lines, rounds, strict=True):
        line["lane_views"] = views
    return rows


def _files(tmp_path: Path) -> list[Path]:
    lens = _view("obvious", rg.SONNET, 900, 12_000, "end_turn")
    return [
        rg._write(tmp_path / "a.jsonl",
                  _viewed("X2-L", "tomli",
                          [lens, _view("leap", FABLE, 31_000, 32_000, "end_turn")],
                          [_view("leap", FABLE, 32_000, 32_000, "max_tokens")]),
                  _viewed("X2-0", "tomli", [lens, _view("leap", rg.OPUS, 4_000, 12_000, "end_turn")]),
                  _viewed("X2-0'", "tomli", [lens])),
        rg._write(tmp_path / "b.jsonl",
                  _viewed("X2-L", "mistune", [_view("leap", rg.OPUS, 20_000, 32_000, "end_turn",
                                                         f"{FABLE}=500,{rg.OPUS}=20000")],
                          [_view("leap", None, None, 32_000, None)])),
    ]  # fmt: skip


def test_the_tokens_page_prints_each_leap_call_and_each_arms_headroom(
    tmp_path: Path,
) -> None:
    text = xt.render_tokens(xr.draws(_files(tmp_path)))
    lines = text.splitlines()

    assert lines[0] == "# X2 leap output tokens against the cap (X2-L)"
    calls = [ln for ln in lines if ln.startswith("| X2-")]
    assert calls[:6] == [
        f"| X2-0 | tomli | a.jsonl | 1 | {rg.OPUS} | 4000 / 12000 | end_turn | 8000 |",
        f"| X2-L | tomli | a.jsonl | 1 | {FABLE} | 31000 / 32000 | end_turn | 1000 |",
        f"| X2-L | tomli | a.jsonl | 2 | {FABLE} | 32000 / 32000 | max_tokens | 0 |",
        f"| X2-L | mistune | b.jsonl | 1 | {rg.OPUS} | 20000 / 32000 (attempts {FABLE}=500,"
        f"{rg.OPUS}=20000) | end_turn | 12000 |",
        "| X2-L | mistune | b.jsonl | 2 | - | no reply | - | - |",
        "| X2-0 | 1 | 1 | 0 | 8000 | 8000 | 8000 |",
    ]  # fmt: skip
    assert calls[6:] == ["| X2-L | 4 | 3 | 1 | 0 | 1000 | 12000 |"]
    assert "obvious" not in text and "X2-0'" not in text
    assert text.endswith(" |\n")


def test_an_arm_with_no_leap_reply_prints_no_headroom(tmp_path: Path) -> None:
    path = rg._write(tmp_path / "a.jsonl",
                     _viewed("X2-L", "tomli", [_view("leap", None, None, None, None)]))  # fmt: skip
    assert "| X2-L | 1 | 0 | 0 | - | - | - |" in xt.render_tokens(xr.draws([path]))


def test_rows_recorded_before_the_token_fields_still_read(tmp_path: Path) -> None:
    old: dict[str, object] = {
        "lane": "leap",
        "view_sha": "ab12cd34",
        "served_model": rg.OPUS,
    }
    path = rg._write(tmp_path / "a.jsonl", _viewed("X2-0", "tomli", [old]))
    text = xt.render_tokens(xr.draws([path]))
    assert f"| X2-0 | tomli | a.jsonl | 1 | {rg.OPUS} | not recorded | - | - |" in text
    assert "| X2-0 | 1 | 0 | 0 | - | - | - |" in text


def test_the_command_writes_the_page_or_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"
    assert xt.main([*map(str, _files(tmp_path)), "--out", str(out)]) == 0
    assert (out / "tokens.md").read_text(encoding="utf-8").startswith("# X2 leap")
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{nope\n", encoding="utf-8")
    assert xt.main([str(bad), "--out", str(tmp_path / "none")]) == 2
    assert not (tmp_path / "none").exists()
    assert "error: " in capsys.readouterr().out
