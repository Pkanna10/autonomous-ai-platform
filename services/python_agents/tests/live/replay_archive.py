"""The archive side of the offline replays (``combine-replay``, ``combine-order``).

A case names one archived run row of ``w2-sprint/live`` and the patch it measures;
``load_archived`` checks, before any clone, that the row is the case's (one per
library, its arm, dispatch and base), that the patch path is one file of the
run's own patch directory resolving inside the archive (no ``..``, no link out),
and that the file's sha256 is the archived one. Split out of
``combine_replay`` (O65 item 2) so both suites read the archive one way.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from .conftest import TESTS_DIR
from .x2_patches import PATCH_DIR, run_dir, safe_name

ARCHIVE: Final = TESTS_DIR.parents[2] / ".claude/handoff/step3/idea-lab/w2-sprint"
DELIVERED: Final = "delivered"  # the delivered combination (delivered.patch)
FALLBACK: Final = "fallback"  # one kept diff (the fallback's single change)
NO_TIP: Final = "none"  # calibration and profile only
TIP_KINDS: Final = frozenset({DELIVERED, FALLBACK, NO_TIP})
_ARM: Final = re.compile(r"X2-[A-Z0-9]{1,4}")
_DISPATCH: Final = re.compile(r"[0-9]{6,12}")
_LIBRARY: Final = re.compile(r"[a-z][a-z0-9_]{0,39}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_FIT: Final = 300


class IntegrityError(ValueError):
    """An archived row, path or file that is not what the replay may measure."""


def _fit(text: str) -> str:
    return text if len(text) <= _FIT else text[: _FIT - 3] + "..."


@dataclass(frozen=True)
class ReplayCase:
    """One archived run row and the tip it measures (``patch``: the file's
    path from ``ARCHIVE``; ``trial_id``: the fallback's kept trial)."""

    id: str
    arm: str
    dispatch: str
    library: str
    base_commit: str
    tip: str
    patch: str | None
    trial_id: str | None
    profile: bool

    def __post_init__(self) -> None:
        for name, value, pattern in (
            ("arm", self.arm, _ARM), ("dispatch", self.dispatch, _DISPATCH),
            ("library", self.library, _LIBRARY), ("base_commit", self.base_commit, _COMMIT),
        ):  # fmt: skip
            if pattern.fullmatch(value) is None:
                raise ValueError(f"case {self.id!r}: {name} {value[:64]!r} is not safe")
        if self.tip not in TIP_KINDS:
            raise ValueError(f"case {self.id!r}: tip {self.tip!r} is not a tip kind")
        if (self.trial_id is not None) != (self.tip == FALLBACK):
            raise ValueError(f"case {self.id!r}: a trial id names the fallback alone")
        if self.tip == NO_TIP and self.patch is not None:
            raise ValueError(f"case {self.id!r}: a case with no tip has no patch")
        safe_name(self.id)


# ---------------------------------------------------------------------------
# Integrity: the archived row, the patch path and its sha256
# ---------------------------------------------------------------------------


def _inside(archive: Path, target: Path, what: str) -> Path:
    """``target`` resolved (links followed); a regular file under ``archive``."""
    try:
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise IntegrityError(f"{what}: {type(exc).__name__}") from None
    if not resolved.is_relative_to(archive.resolve()):
        raise IntegrityError(f"{what} resolves outside the archive")
    if not resolved.is_file():
        raise IntegrityError(f"{what} is not a regular file")
    return resolved


def archive_path(archive: Path, rel: str) -> Path:
    """A case's declared ``rel`` (from the archive root), checked."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise IntegrityError(
            f"the declared path {rel[:120]!r} is not under the archive"
        )
    return _inside(
        archive, archive.joinpath(*parts), f"the declared path {rel[:120]!r}"
    )


def patch_file(archive: Path, case: ReplayCase, file: str) -> Path:
    """A row's patch ``file`` (``live-patches/<run>/<name>`` as the X2
    recorder wrote it) in the archived run's directory, checked: the run's
    own directory, one safe file name, a regular file inside the archive."""
    where = f"{case.id}: the patch {file[:120]!r}"
    head, _, rest = file.partition("/")
    parts = rest.split("/")
    if (
        head != PATCH_DIR
        or len(parts) != 2
        or parts[0] != run_dir(case.arm, case.library)
    ):
        raise IntegrityError(f"{where} is not one file of the run's patch directory")
    try:
        name = safe_name(parts[1])
    except ValueError as exc:
        raise IntegrityError(f"{where}: {exc}") from None
    folder = archive / "live" / f"patches-{case.arm}-{case.dispatch}" / parts[0]
    return _inside(archive, folder / name, where)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class Archived:
    """What the archived run row says (percent, as the rows hold them)."""

    gain_pct: float | None
    floor_pct: float | None
    holds: bool | None
    baseline_floor_pct: float | None  # the least hypothesis floor (q3's)
    seconds: float | None  # the run's seconds_measured
    patch: Path | None
    sha256: str | None
    trial_id: str | None  # the fallback's kept trial
    hypothesis_id: str | None

    @property
    def ratio(self) -> float | None:
        if self.floor_pct is None or not self.baseline_floor_pct:
            return None
        return self.floor_pct / self.baseline_floor_pct


def _number(row: Mapping[str, object], key: str, where: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise IntegrityError(f"{where}: {key} is not a number")
    return float(value)


def _entry(
    case: ReplayCase, row: Mapping[str, object], where: str
) -> Mapping[str, object]:
    """The patch entry the case measures: the delivered patch, or the
    fallback trial's ``kept_diffs`` entry."""
    kept = row.get("kept_diffs")
    if not isinstance(kept, list) or not all(isinstance(k, dict) for k in kept):
        raise IntegrityError(f"{where}: kept_diffs is not a list of entries")
    if case.tip == DELIVERED:
        entry = row.get("delivered_patch")
        if not isinstance(entry, dict):
            raise IntegrityError(f"{where}: no delivered patch")
        return cast(Mapping[str, object], entry)
    found = [k for k in kept if k.get("trial_id") == case.trial_id]
    if len(found) != 1:
        raise IntegrityError(f"{where}: no kept diff of trial {case.trial_id}")
    return cast(Mapping[str, object], found[0])


def _whole(
    case: ReplayCase, entry: Mapping[str, object], where: str
) -> tuple[str, str]:
    """The entry's file and sha256, refused unless written whole at the base."""
    file, sha = entry.get("file"), entry.get("sha256")
    if not isinstance(file, str):
        raise IntegrityError(f"{where}: the patch entry has no file")
    if not isinstance(sha, str) or _SHA256.fullmatch(sha) is None:
        raise IntegrityError(f"{where}: the patch entry's sha256 is not a sha256")
    if entry.get("truncated") is not False:
        raise IntegrityError(f"{where}: the archived patch was truncated")
    if entry.get("error") is not None:
        raise IntegrityError(f"{where}: the archived patch has a write error")
    if entry.get("base_commit") != case.base_commit:
        raise IntegrityError(f"{where}: the patch entry's base is not the case's")
    return file, sha


def _rows(path: Path, where: str) -> list[dict[str, object]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    if not all(isinstance(r, dict) for r in rows):
        raise IntegrityError(f"{where}: a line is not a JSON object")
    return rows


def load_archived(case: ReplayCase, archive: Path = ARCHIVE) -> Archived:
    """The case's archived run row and patch, every integrity check passed."""
    name = f"ideas-x2-{case.arm}-{case.dispatch}.jsonl"
    where = f"{case.id} ({name})"
    path = archive / "live" / name
    if not path.is_file():
        raise IntegrityError(f"{case.id}: no run file {name} in the archive")
    rows = _rows(_inside(archive, path, where), where)
    runs = [r for r in rows if r.get("experiment") == "ideas-x2-run"
            and r.get("repo") == case.library]  # fmt: skip
    if len(runs) != 1:
        raise IntegrityError(f"{where}: {len(runs)} run rows for {case.library}, not 1")
    (row,) = runs
    if row.get("arm") != case.arm:
        raise IntegrityError(f"{where}: the row's arm is not the case's {case.arm}")
    dispatch = row.get("dispatch")  # ARM:lib,lib (the run id is the file's name)
    arm, _, libraries = dispatch.partition(":") if isinstance(dispatch, str) else ("", "", "")  # fmt: skip
    if arm != case.arm or case.library not in libraries.split(","):
        raise IntegrityError(
            f"{where}: the row's dispatch is not {case.arm} with {case.library}"
        )
    if row.get("base_commit") != case.base_commit:
        raise IntegrityError(
            f"{where}: base_commit is not the case's {case.base_commit}"
        )
    holds = row.get("holds")
    if holds is not None and not isinstance(holds, bool):
        raise IntegrityError(f"{where}: holds is not a boolean")
    gain, floor = _number(row, "gain_pct", where), _number(row, "floor_pct", where)
    seconds = _number(row, "seconds_measured", where)
    floors = [_number(h, "floor_pct", where) for h in rows
              if h.get("experiment") == "ideas-x2-hypothesis" and h.get("repo") == case.library]  # fmt: skip
    known = [f for f in floors if f is not None]
    base_floor = min(known) if known else None
    entry = None if case.tip == NO_TIP else _entry(case, row, where)
    patch = sha = None
    if entry is not None:
        file, sha = _whole(case, entry, where)
        patch = patch_file(archive, case, file)
        if case.patch is None:
            raise IntegrityError(
                f"{where}: the case declares no patch, the row names {file}"
            )
        if archive_path(archive, case.patch) != patch:
            raise IntegrityError(
                f"{where}: the case declares {case.patch}, the row names {file}"
            )
        if sha256_of(patch) != sha:
            raise IntegrityError(f"{where}: {file}'s sha256 is not the archived {sha}")
    hypothesis = (
        None if entry is None or case.tip != FALLBACK else entry.get("hypothesis_id")
    )
    return Archived(gain, floor, holds, base_floor, seconds, patch, sha, case.trial_id,
                    hypothesis if isinstance(hypothesis, str) else None)  # fmt: skip
