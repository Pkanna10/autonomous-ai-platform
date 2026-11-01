"""Tolerant fingerprints, output retention, the frozen-path mask, ABBA order (U18).

The canonical form is checked on bytes; measurement runs on an injected
``run_once`` double and a reset that rewrites the frozen file, as a
``checkout -f`` would, so the mask is checked against real files.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from autonomous_ai_agents.common.config import settings
from autonomous_ai_agents.common.models import OutputTolerance, Project, Workload
from autonomous_ai_agents.execution.measure import (
    Phase,
    launch,
    make_phase,
    measure_abab,
    measure_workload,
    output_fingerprint,
    run_tests,
)
from autonomous_ai_agents.execution.outputs import (
    Retained,
    canonical,
    check_mask,
    mask,
    tolerant_fingerprint,
)
from autonomous_ai_agents.execution.procrun import OutputCaps, RunFailure, RunSample
from autonomous_ai_agents.execution.protocols import WorktreeHandle
from autonomous_ai_agents.execution.sandbox import SandboxPolicy

PY = "/usr/bin/python3"
CAPS = OutputCaps(max_output_bytes=1024, head_bytes=64, stderr_tail_bytes=4096)
LABELS = "data/labels.csv"
D9, D12 = OutputTolerance(float_digits=9), OutputTolerance(float_digits=12)
UNORDERED = OutputTolerance(unordered_lines=True)
Respond = Callable[[Path], bytes]


def sample(stdout: bytes, *, head: bytes | None = None) -> RunSample:
    return RunSample(
        wall_ns=1_000_000_000,
        utime=0.5,
        stime=0.25,
        maxrss_bytes=1024,
        exit=0,
        fs_isolated=True,
        net_isolated=True,
        stdout_sha256=hashlib.sha256(stdout).hexdigest(),
        stdout_head=stdout if head is None else head,
        stdout_bytes=len(stdout),
        stderr_tail=b"",
    )


class Side:
    """A worktree whose reset restores ``data/labels.csv`` and whose runs print
    what ``respond`` returns, logging ``reset <tag>`` and ``<tag>`` in order."""

    def __init__(self, root: Path, events: list[str], tag: str, respond: Respond):
        self.wt, self.scratch = root / "wt", root / "scratch"
        for made in (self.wt / "data", self.scratch, root / "probe"):
            made.mkdir(parents=True)
        self.events, self.tag, self.respond = events, tag, respond
        self.seen: list[bool] = []  # was the labels file there at launch?
        self.probe = root / "probe"

    def reset(self) -> None:
        self.events.append(f"reset {self.tag}")
        (self.wt / LABELS).write_text("cat\ndog\n")

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        sandbox: SandboxPolicy,
        timeout_s: float,
        caps: OutputCaps,
        *,
        fresh_dirs: Sequence[Path] = (),
    ) -> RunSample:
        self.events.append(self.tag)
        self.seen.append(os.path.lexists(self.wt / LABELS))
        if argv[1:2] == ("-m",):  # the suite
            return sample(b"")
        stdout = self.respond(self.wt)
        return sample(stdout, head=stdout[: caps.head_bytes])

    def phase(self, mask: tuple[str, ...] = (LABELS,)) -> Phase:
        writable = (self.wt, self.scratch)
        policy = SandboxPolicy("off", "off", writable, self.probe, "linux")
        return Phase(policy, {}, self.reset, CAPS, self, mask)


def printing(*outputs: bytes) -> Respond:
    queue = list(outputs)
    return lambda wt: queue.pop(0) if len(queue) > 1 else queue[0]


def side(tmp_path: Path, respond: Respond, tag: str = "A") -> Side:
    return Side(Path(os.path.realpath(tmp_path)) / tag, [], tag, respond)


def workload(**changes: object) -> Workload:
    fields: dict[str, object] = {
        "project_id": "p1",
        "name": "bench",
        "command": (PY, "bench.py"),
        "warmup_runs": 0,
        "runs": 5,
    }
    fields.update(changes)
    return Workload.model_validate(fields)


def exact(stdout: bytes, file: bytes | None = None) -> str:
    def part(data: bytes) -> tuple[int, str]:
        return len(data), hashlib.sha256(data).hexdigest()

    return output_fingerprint(*part(stdout), None if file is None else part(file))


# ---------------------------------------------------------------------------
# The canonical form
# ---------------------------------------------------------------------------


def test_decimals_compare_at_the_stated_significant_digits() -> None:
    assert canonical(b"0.1000000001\n", D9) == canonical(b"0.1\n", D9) == b"0.1\n"
    assert canonical(b"0.1000000001\n", D12) != canonical(b"0.1\n", D12)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (b"10", b"11"),
        (b"v1.10", b"v1.1"),
        (b"id_2.50", b"id_2.5"),
        (b"1_0.5", b"10.5"),
        (b"1e999", b"2e999"),  # overflow is kept, not read as inf
        (b"1e-400", b"2e-400"),  # underflow is kept, not read as 0
        (b"1.1e-323", b"1e-323"),  # subnormals lose digits, so are kept
    ],
)
def test_only_whole_decimal_tokens_are_rounded(left: bytes, right: bytes) -> None:
    tolerance = OutputTolerance(float_digits=6)
    assert canonical(left, tolerance) == left
    assert canonical(left, tolerance) != canonical(right, tolerance)


def test_integers_specials_and_zeros_are_kept_verbatim() -> None:
    text = b"10 nan inf -inf NaN infinity -0.0 0.0 0.000 +7 1.5x x1.5 1.5e 3.0-4.0"
    assert canonical(text, OutputTolerance(float_digits=6)) == text


def test_delimiters_survive_byte_for_byte() -> None:
    text = b"[0.10000000001, \"2.50000000001\";\t(3.0)]\r\n{a:.5e1}\x0b'+1.'"
    assert canonical(text, D9) == b"[0.1, \"2.5\";\t(3)]\r\n{a:5}\x0b'1'"


def test_an_equals_sign_delimits_a_number_and_is_kept() -> None:
    assert canonical(b"acc=0.9120000001\n", D9) == canonical(b"acc=0.912\n", D9)
    assert canonical(b"acc=0.9120000001\n", D9) == b"acc=0.912\n"
    assert canonical(b"a==1.50000000001=", D9) == b"a==1.5="


def test_line_order_counts_unless_unordered() -> None:
    assert canonical(b"b\na\n", D9) != canonical(b"a\nb\n", D9)
    assert canonical(b"b\na\n", UNORDERED) == canonical(b"a\nb\n", UNORDERED)
    assert canonical(b"a\nb\n", UNORDERED) != canonical(b"a\n\nb", UNORDERED)
    both = OutputTolerance(float_digits=9, unordered_lines=True)
    assert canonical(b"2.00000000001\n1.0\n", both) == b"1\n2\n"


def test_invalid_utf8_has_no_canonical_form() -> None:
    with pytest.raises(UnicodeDecodeError):
        canonical(b"0.1\xff\n", D9)


def test_the_fingerprint_is_tagged_with_the_options() -> None:
    both = OutputTolerance(float_digits=9, unordered_lines=True)
    prints = {
        tolerant_fingerprint(b"1.0\n", None, tolerance)
        for tolerance in (D9, D12, UNORDERED, both)
    }
    prints |= {tolerant_fingerprint(b"1.0\n", b"", D9), exact(b"1.0\n")}
    assert len(prints) == 6


# ---------------------------------------------------------------------------
# Fingerprints and retention in measure_workload
# ---------------------------------------------------------------------------


def test_without_a_tolerance_both_fingerprints_are_exact_and_the_bytes_kept(
    tmp_path: Path,
) -> None:
    run = side(tmp_path, printing(b"zebra\n"))

    measured = measure_workload(run.phase(), workload())

    prints = {exact(b"zebra\n")}
    assert {m.output_fingerprint for m in measured.measurements} == prints
    assert {m.raw_fingerprint for m in measured.measurements} == prints
    assert measured.outputs == b"zebra\n"
    assert "zebra" not in repr(measured)


def test_a_tolerance_makes_the_fingerprint_canonical_and_keeps_the_raw_one(
    tmp_path: Path,
) -> None:
    load = workload(output_tolerance=D9)
    same = measure_workload(side(tmp_path / "1", printing(b"0.1\n")).phase(), load)
    drift = printing(*(b"0.100000000%d\n" % i for i in range(1, 5)))
    close = measure_workload(side(tmp_path / "2", drift).phase(), load)

    canonical_print = tolerant_fingerprint(b"0.1\n", None, D9)
    assert {m.output_fingerprint for m in same.measurements} == {canonical_print}
    assert {m.raw_fingerprint for m in same.measurements} == {exact(b"0.1\n")}
    assert {m.output_fingerprint for m in close.measurements} == {canonical_print}
    assert {m.raw_fingerprint for m in close.measurements} == {None}
    assert close.outputs == b"0.1000000001\n"  # the first timed run's bytes
    assert same.notes == close.notes == ()


def test_outputs_that_differ_beyond_the_tolerance_are_not_kept(tmp_path: Path) -> None:
    load = workload(output_tolerance=D9)
    apart = printing(b"0.1\n", b"0.2\n")

    measured = measure_workload(side(tmp_path, apart).phase(), load)

    assert {m.output_fingerprint for m in measured.measurements} == {None}
    assert {m.raw_fingerprint for m in measured.measurements} == {None}
    assert measured.outputs is None


def test_both_sides_keep_their_first_run_when_raws_drift(tmp_path: Path) -> None:
    root = Path(os.path.realpath(tmp_path))
    drift = printing(*(b"0.700000000%d\n" % i for i in range(1, 5)))
    a = Side(root / "a", [], "A", drift)
    b = Side(root / "b", [], "B", printing(b"0.7\n"))

    result = measure_abab(a.phase(), b.phase(), workload(output_tolerance=D9))

    assert (result.outputs_a, result.outputs_b) == (b"0.7000000001\n", b"0.7\n")


def test_the_output_file_is_the_kept_output_and_joins_the_tolerance(
    tmp_path: Path,
) -> None:
    def write(wt: Path) -> bytes:
        (wt / "out.txt").write_bytes(b"0.25000000001\n")
        return b"done\n"

    measured = measure_workload(
        side(tmp_path, write).phase(),
        workload(output_file="out.txt", output_tolerance=D9),
    )

    expected = tolerant_fingerprint(b"done\n", b"0.25\n", D9)
    assert {m.output_fingerprint for m in measured.measurements} == {expected}
    raw = exact(b"done\n", b"0.25000000001\n")
    assert {m.raw_fingerprint for m in measured.measurements} == {raw}
    assert measured.outputs == b"0.25000000001\n"


@pytest.mark.parametrize("case", ["utf8", "head", "file"])
def test_an_incomplete_or_undecodable_output_is_compared_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    stdout = {"utf8": b"0.1\xff\n", "head": b"0.1" * 30, "file": b"ok\n"}[case]
    big = b"0.1\n" * 3

    def respond(wt: Path) -> bytes:
        (wt / "out.txt").write_bytes(big)
        return stdout

    monkeypatch.setattr(settings, "OUTPUT_TOLERANCE_MAX_BYTES", len(big) - 1)
    load = workload(
        output_tolerance=D9, output_file="out.txt" if case == "file" else None
    )

    measured = measure_workload(side(tmp_path, respond).phase(), load)

    raw = exact(stdout, big if case == "file" else None)
    assert {m.output_fingerprint for m in measured.measurements} == {raw}
    assert {m.raw_fingerprint for m in measured.measurements} == {raw}
    why = {
        "utf8": "the output is not UTF-8",
        "head": "stdout is longer than the 64 bytes kept",
        "file": f"the output file is larger than {len(big) - 1} bytes",
    }[case]
    assert measured.notes == (
        f"workload 'bench': compared exactly, not within its tolerance: {why}",
    )
    assert measured.outputs == (None if case != "utf8" else stdout)


def test_a_head_that_disagrees_with_the_digest_is_not_kept(tmp_path: Path) -> None:
    def lying(*args: object, **kwargs: object) -> RunSample:
        return sample(b"x\n", head=b"y\n")

    run = side(tmp_path, printing(b"x\n"))
    phase = Phase(run.phase().policy, {}, run.reset, CAPS, lying)

    measured = measure_workload(phase, workload())

    assert measured.outputs is None
    assert {m.raw_fingerprint for m in measured.measurements} == {exact(b"x\n")}


# ---------------------------------------------------------------------------
# ABBA order and both sides' outputs
# ---------------------------------------------------------------------------


def test_abba_alternates_the_leading_side_on_one_counter(tmp_path: Path) -> None:
    events: list[str] = []
    root = Path(os.path.realpath(tmp_path))
    a = Side(root / "a", events, "A", printing(b"apple\n"))
    b = Side(root / "b", events, "B", printing(b"berry\n"))

    result = measure_abab(a.phase(), b.phase(), workload(warmup_runs=2, runs=5))

    ab, ba = ["A", "B"], ["B", "A"]
    runs = [e for e in events if not e.startswith("reset")]
    assert runs == [*ab, *ba] * 3 + ab  # warm-ups 1-2, then timed runs 1-5
    assert (result.outputs_a, result.outputs_b) == (b"apple\n", b"berry\n")
    assert "apple" not in repr(result) and "berry" not in repr(result)


# ---------------------------------------------------------------------------
# The mask
# ---------------------------------------------------------------------------


def test_the_mask_removes_frozen_files_before_each_workload_but_not_the_suite(
    tmp_path: Path,
) -> None:
    run = side(tmp_path, printing(b"ok\n"))
    phase = run.phase()
    project = Project(name="p", root_path="/srv/p", test_command=(PY, "-m", "x"))

    measure_workload(phase, workload(warmup_runs=1))
    run_tests(phase, project, [workload()])

    assert run.seen == [False] * 6 + [True]
    assert run.events == ["reset A", "A"] * 7


def test_a_launch_is_masked_unless_it_says_otherwise(tmp_path: Path) -> None:
    run = side(tmp_path, printing(b"ok\n"))
    phase = run.phase()

    launch(phase, (PY, "bench.py"), ".", 5.0, "the profile", [])
    launch(phase, (PY, "bench.py"), ".", 5.0, "unmasked", [], masked=False)

    assert run.seen == [False, True]


def test_an_empty_mask_touches_nothing(tmp_path: Path) -> None:
    run = side(tmp_path, printing(b"ok\n"))

    launch(run.phase(mask=()), (PY, "bench.py"), ".", 5.0, "the profile", [])
    mask(tmp_path / "missing", ())

    assert run.seen == [True]


def test_the_mask_removes_a_link_never_its_target(tmp_path: Path) -> None:
    target = tmp_path / "outside.csv"
    target.write_text("secret\n")

    def relink() -> None:
        (run.wt / LABELS).unlink(missing_ok=True)
        (run.wt / LABELS).symlink_to(target)

    run = side(tmp_path, printing(b"ok\n"))
    phase = run.phase()
    linked = Phase(phase.policy, {}, relink, CAPS, run, (LABELS, "absent/x.csv"))

    measure_workload(linked, workload())

    assert run.seen == [False] * 5
    assert target.read_text() == "secret\n"


@pytest.mark.parametrize("kind", ["linked parent", "directory"])
def test_a_frozen_path_that_cannot_be_masked_safely_fails_the_run(
    tmp_path: Path, kind: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "labels.csv").write_text("secret\n")
    run = side(tmp_path, printing(b"ok\n"))
    data = run.wt / "data"

    def reset() -> None:
        if kind == "directory":
            (data / "labels.csv").mkdir(exist_ok=True)
        elif not data.is_symlink():
            data.rmdir()
            data.symlink_to(outside)

    phase = run.phase()
    broken = Phase(phase.policy, {}, reset, CAPS, run, (LABELS,))

    reason = "is a directory" if kind == "directory" else "a parent is not a directory"
    match = rf"^workload 'bench' run 1/5: cannot mask 'data/labels.csv': {reason}$"
    with pytest.raises(RunFailure, match=match):
        measure_workload(broken, workload())
    assert (outside / "labels.csv").read_text() == "secret\n"
    assert run.seen == []


@pytest.mark.parametrize(
    "bad",
    [
        "../x", "/etc/passwd", ".", "", "a/.git/config", "a//b", "./a", "a\x00b",
        "a\nb", "a\rb", "-a", "d/*.csv", "d/?.csv", "d/[ab].csv",
    ],
)  # fmt: skip
def test_the_mask_takes_clean_project_paths_only(tmp_path: Path, bad: str) -> None:
    run = side(tmp_path, printing(b""))
    handle = WorktreeHandle(path=run.wt, gitdir=tmp_path / "g", link_bytes=b"")

    class Git:
        def reset(self, handle: WorktreeHandle) -> None:
            pass

    def build(mask: list[str]) -> Phase:
        return make_phase(
            Git(), handle, scratch=run.scratch, probe=run.probe, network="off",
            fs="off", mask=mask,
        )  # fmt: skip

    with pytest.raises(
        ValueError, match="^a mask path must be a clean project file, got "
    ):
        build([bad])
    assert build([LABELS]).mask == (LABELS,)


def test_a_mask_delete_that_fails_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: str, *, dir_fd: int | None = None) -> None:
        raise PermissionError(13, "Permission denied")

    run = side(tmp_path, printing(b"ok\n"))
    phase = run.phase()
    monkeypatch.setattr(os, "unlink", refuse)  # root would bypass a chmod

    with pytest.raises(RunFailure, match="cannot mask 'data/labels.csv': Permission"):
        measure_workload(phase, workload())


def test_mask_paths_follow_the_quality_file_rule() -> None:
    check_mask(("data/labels.csv", "score.py", "a-b/c-"))
    with pytest.raises(ValueError, match="must not start with '-'"):
        check_mask(("-x",))


@pytest.mark.parametrize("root", ["missing", "bad\x00root"])
def test_an_unopenable_mask_root_fails_the_run(tmp_path: Path, root: str) -> None:
    with pytest.raises(RunFailure, match="^cannot open the worktree to mask it: "):
        mask(tmp_path / root, (LABELS,))


def test_a_nul_reaching_the_unlink_fails_the_run(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    for path in ("a\x00b", "d/a\x00b", "a\x00/b"):
        with pytest.raises(RunFailure, match="^cannot mask .*: embedded null"):
            mask(tmp_path, (path,))


def test_retention_stops_for_good_past_its_cap() -> None:
    kept, over = Retained(4), Retained(3)
    for chunk in (b"ab", b"cd"):
        kept(chunk)
        over(chunk)
    over(b"e")
    assert (kept.data, over.data) == (b"abcd", None)
