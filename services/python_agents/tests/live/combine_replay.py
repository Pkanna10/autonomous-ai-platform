"""The combine re-measure replay (O62 item 5): the ``combine-replay`` suite.

The owner approved the combine proposal's item 1
(``.claude/handoff/step3/idea-lab/w2-sprint/combine-proposal.md`` section 1)
as an offline replay only: the four archived rows whose combine floor was at
least ``RULE_K`` (2) times the run's baseline floor
(``zero-credit/q3_floors.csv``), their archived tips, no API spend, and no
change to the combine node. The rule under test: when a combine's measured
floor exceeds ``RULE_K`` x the baseline's calibrated floor, measure the same
tip once more with the same judges and N, and judge on the second
measurement; the trigger reads the floor only, never the verdict.

**Cases** (``CASES``): X2-D tomli (43093773731), X2-P mistune (43104077245)
and X2-P sqlparse (43107418692), each the delivered combination; X2-D
mistune (43145496896), whose combine failed, as the fallback's single
change (d11a38da), the tip its 9.76 % floor came from. The greedy
combination of that run is not replayed: its order is the hypotheses'
scores, which no row records, and ``zero-credit/analyse.py`` replays no
greedy merge for a run with no delivered patch; with b741a3ad-f0efa548 and
f0efa548-108c5afa conflicting, two greedy sets are possible, so rebuilding
it would be a guess. A fifth case, markdown at its archived base (O62
addendum), runs only the calibration and the profile, for the CI minutes a
later arm needs.

**Integrity** (``load_archived``, before any clone): the run row is read
from the archive (``ARCHIVE``, in git, so present in the CI checkout),
exactly one per library; every patch path is checked to be one file under
the run's own directory and to resolve inside the archive; the row's
``arm`` must be the case's and its ``dispatch`` (``ARM:lib,lib``; the run
id is the file's name) the case's arm with its library (``patch_file``,
``archive_path``: no ``..``, no link out); each file's sha256 must be its
entry's (the delivered patch's ``delivered_patch.sha256``, a kept diff's
``kept_diffs`` entry); the case's base must be the row's ``base_commit``,
and after the clone the repository's base must be it too. A mismatch writes
the case's ``error`` row, then fails it.

**The measurement** (``EngineMeasurer``): what the combine node's re-test
measures, through the engine's own functions, nothing reimplemented:

- the repository as the X2 run built it (``oss.prepare_repo`` of
  ``ideas_x2.LIBRARIES``), the tip committed beside it as a single-parent
  child of the base under ``refs/replay/<case>`` (``commit_patch``:
  ``git apply --cached`` on a scratch index; nothing checked out moves);
- ``make_nodes``' ``connect`` (``GitPreflight`` in the ``required``
  sandbox), ``define`` (the default objective and the peak-RSS bound, the
  output check as the settings), ``baseline`` (the N timed runs, the trust
  checks, and ``NOISE_CALIBRATION_BLOCKS`` A/A blocks raising the
  objective's floor, ``nodes._calibrated``) and, once per library,
  ``profile`` (``CProfiler``, the function the profile node calls);
- per re-test, ``combine_node.retest_one`` on ``GitCombiner`` (the merge,
  the ABAB re-test, the suite on the tip against the baseline's count) under
  ``nodes._combine_rules`` (the frozen judges of ``default_judges`` as the
  factory builds them, the completeness rule, the baseline's objectives and
  passing count), judged by ``derive_verdict``; three in a row (m1, m2, m3).

The context mirrors ``factory.build_context`` with no transport: the
settings must be the X2 arms' measurement settings (``REPLAY_SETTINGS``,
``check_settings``, refused before any clone).

**The trigger's baseline floor** is the wall-time objective's raised floor
as the baseline node sets it, ``max(MIN_RELATIVE_GAIN, NOISE_FLOOR_MIN,
calibration.floor)`` (``BaselineLook.floor``); for these libraries it equals
the calibrated floor (each calibration floor is at least 2 %). The archived
"baseline floor" of ``q3_floors.csv`` (the least of the run's hypothesis
floors) is printed beside it for comparison only; the rule never reads it.

**Every look must measure the tip**: in a tip case each re-test must apply
the one change and leave its A and B rows (``RetestLook.measured_tip``). A
look where the combiner skipped the change, or where a ``RunFailure`` left
no rows, is not a "holds: false": the case's rows are written, then it
fails as an integrity error, and the rule gives no verdict without m1 and m2
both measured. A skipped merge is deterministic, so the looks stop there; a
no-rows look does not stop them (m2 and m3 still run and are recorded). A
no-rows re-test is what the live combine node records as "did not hold"
(``combine_node._why``: no measurements); the replay labels it "not
measured" (``measured_tip`` false, ``not_measured`` in the case row). An
``EngineError`` stop is recorded and the suite goes on, but a tip case with
fewer than three measured looks, whatever the cause, fails the job once
every case has run, each such case named in the tables
(``ReplayRecorder.finish``); markdown has no look by design.

**Records** (``$LIVE_RESULTS_PATH``, never asserted): a ``retest`` row per
re-test (gain, floor, outcome, holds, the suite's result, the floor against
``RULE_K`` x the baseline floor, the seconds) and a ``case`` row (the
archived row's gain, floor, holds and baseline floor, the minimum of its
hypotheses' floors as ``q3_floors.csv`` reads it, beside the replay's; the
rule: whether it fires on m1 and the verdict it gives, m2's when it fires;
the floors' spread), then a table to the job summary. Wall time
(``time.monotonic``, ``clock``): the clone and tip, the preflight, the
baseline node and the calibration inside it, the profile, each re-test and
the suite inside it (``TimedRun``, every launch timed).

**Guards** (asserted): ``required`` isolation and every launch sandboxed and
isolated, no request (0 USD), only the replay's phases, the user's
repository as it was after the tip commit, one worktree.

**Minutes** (``plan_minutes``): per library ``UNIT_S``, an upper bound on
one re-test from the archived X2-D and X2-P runs (each run's
``seconds_measured`` over its measured units: every trial, every keep's
confirmation and the combine, each one ABAB look with the suite; the clone,
calibration, profile and API time are in the numerator too); a case is
``SETUP_S`` plus ``case_units`` of them; the job is ``JOB_SETUP_MINUTES``
plus twice the plan.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, cast

from e2e.conftest import Isolation, LaunchLog, RepoSnapshot, UserRepo

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import (
    METRIC_WALL_TIME_S,
    Baseline,
    Hypothesis,
    NoiseCalibration,
    Project,
    Trial,
    Workload,
)
from autonomous_ai_agents.execution.combine import BASE, TIP, GitCombiner
from autonomous_ai_agents.execution.git import GitWorkspace
from autonomous_ai_agents.execution.measure import (
    UNKNOWN,
    RunOnce,
    baseline_test_count,
    classify_runner,
)
from autonomous_ai_agents.execution.preflight import PHASE as PREFLIGHT_PHASE
from autonomous_ai_agents.execution.preflight import GitPreflight
from autonomous_ai_agents.execution.procrun import OutputCaps, RunSample
from autonomous_ai_agents.execution.profiler import PHASE as PROFILE_PHASE
from autonomous_ai_agents.execution.profiler import CProfiler
from autonomous_ai_agents.execution.protocols import KeptChange, TrialBrief
from autonomous_ai_agents.execution.sandbox import SandboxPolicy
from autonomous_ai_agents.execution.trial_runner import (
    BASELINE_PHASE,
    CALIBRATE_PHASES,
    GitBaselineRunner,
)
from autonomous_ai_agents.optimization.anticheat import DEFAULT_PROTECTED_PATTERNS
from autonomous_ai_agents.optimization.judges import default_judges
from autonomous_ai_agents.orchestrator.combine_node import (
    COMBINATION_ID,
    CombineTarget,
    Retest,
    retest_one,
)
from autonomous_ai_agents.orchestrator.nodes import (
    NodeContext,
    NodeFn,
    NoiseCalibrator,
    _combine_rules,
    make_nodes,
)
from autonomous_ai_agents.orchestrator.state import EngineState, initial_state
from autonomous_ai_agents.persistence.repository import InMemoryRepository

from .conftest import TESTS_DIR, LiveRun
from .discovery_io import ResultsSink, cells, flag, write_markdown
from .ideas_x2 import LIBRARIES
from .oss import (
    PRODUCTION,
    CloneRefusedError,
    GitPolicy,
    OssRepo,
    _Git,
    _scratch_git,
    prepare_repo,
)
from .x2_patches import PATCH_DIR, run_dir, safe_name

REPLAY_EXPERIMENT: Final = "combine-replay"
REPLAY_RUN_CAP_USD: Final = 0.0  # no Claude request
RULE_K: Final = 2.0  # the proposal's k: re-measure past k x the baseline floor
LOOKS: Final = ("m1", "m2", "m3")
ARCHIVE: Final = TESTS_DIR.parents[2] / ".claude/handoff/step3/idea-lab/w2-sprint"
DELIVERED: Final = "delivered"  # the delivered combination (delivered.patch)
FALLBACK: Final = "fallback"  # the fallback's single change (its kept diff)
NO_TIP: Final = "none"  # calibration and profile only
TIP_KINDS: Final = frozenset({DELIVERED, FALLBACK, NO_TIP})
REPLAY_PHASES: Final = frozenset({
    PREFLIGHT_PHASE, BASELINE_PHASE, *CALIBRATE_PHASES, PROFILE_PHASE, TIP, BASE,
})  # fmt: skip
REPLAY_SETTINGS: Final[Mapping[str, object]] = {
    # ci.yml's step3 noise rule, as the ideas-x2 suite exports it ...
    "PAIRED_TRIALS": True, "CONFIRM_WINNERS": True, "NOISE_CALIBRATION_BLOCKS": 3,
    # ... and ideas_x2.SHARED's op-count judge; X2-D and X2-P set no other
    # measurement key (the scaling judge and the site stacks at their default)
    "OP_COUNT_JUDGE": True, "SCALING_JUDGE": False, "SITE_STACKS": "off",
    # every other key the measurement reads, at the default both arms ran
    "MIN_RUNS": 5, "NOISE_MULTIPLIER": 2.0, "NOISE_GAP_MULTIPLIER": 2.0,
    "MIN_RELATIVE_GAIN": 0.02, "DEFAULT_OUTPUT_CHECK": True, "SHADOW_VERIFY": "off",
    "TEST_TIMEOUT_S": 900.0,
}  # fmt: skip
_ARM: Final = re.compile(r"X2-[A-Z0-9]{1,4}")
_DISPATCH: Final = re.compile(r"[0-9]{6,12}")
_LIBRARY: Final = re.compile(r"[a-z][a-z0-9_]{0,39}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_FIT: Final = 300

# Minutes (the module docstring): per library the most an archived X2-D or
# X2-P run spent per measured unit, rounded up (the guard recomputes them)
UNIT_S: Final[Mapping[str, int]] = {"tomli": 50, "mistune": 57, "sqlparse": 64,
                                     "markdown": 60}  # fmt: skip
SETUP_S: Final = 60.0  # a pinned clone, the workload commit, the tip commit
JOB_SETUP_MINUTES: Final = 15  # checkout, uv sync, sandbox probe, collection
REPLAY_JOB_MINUTES: Final = 105  # ci.yml's combine-replay timeout: 15 + 2 x 45


class IntegrityError(ValueError):
    """An archived row, path or file that is not what the replay may measure."""


def _fit(text: str) -> str:
    return text if len(text) <= _FIT else text[: _FIT - 3] + "..."


# ---------------------------------------------------------------------------
# The cases
# ---------------------------------------------------------------------------


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


def _case(arm: str, dispatch: str, library: str, base: str, tip: str,
          file: str | None, *, trial: str | None = None, profile: bool = True) -> ReplayCase:  # fmt: skip
    folder = f"live/patches-{arm}-{dispatch}/{arm}-{library}"
    return ReplayCase(f"{arm}-{dispatch}-{library}", arm, dispatch, library, base,
                      tip, None if file is None else f"{folder}/{file}", trial, profile)  # fmt: skip


TOMLI_BASE: Final = "e9735a7906565459e3a503348d7c6698a2b28cc2"
MISTUNE_BASE: Final = "54306a1497cd7375d10f4ce03387915a9455d90e"
SQLPARSE_BASE: Final = "ddf10ae7deb741528749c7cd6f4baadc2cb58209"
MARKDOWN_BASE: Final = "afd7a2f9088b6b3fd0893cb3f92dc7bf6f5ad012"
FALLBACK_TRIAL: Final = "d11a38da-7132-58ab-974a-a58979a65e81"
CASES: Final = (
    _case("X2-D", "43093773731", "tomli", TOMLI_BASE, DELIVERED, "delivered.patch"),
    _case("X2-P", "43104077245", "mistune", MISTUNE_BASE, DELIVERED, "delivered.patch"),
    _case("X2-P", "43107418692", "sqlparse", SQLPARSE_BASE, DELIVERED, "delivered.patch"),
    _case("X2-D", "43145496896", "mistune", MISTUNE_BASE, FALLBACK,
          f"trial-{FALLBACK_TRIAL}.diff", trial=FALLBACK_TRIAL, profile=False),
    _case("X2-P", "43104077245", "markdown", MARKDOWN_BASE, NO_TIP, None),
)  # fmt: skip


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


# ---------------------------------------------------------------------------
# What is measured, and the rule
# ---------------------------------------------------------------------------


def triggered(floor: float | None, baseline_floor: float | None, k: float = RULE_K) -> bool | None:  # fmt: skip
    """The proposal's trigger: the floor above ``k`` x the baseline floor;
    ``None`` when either is unknown. It reads no verdict."""
    if floor is None or baseline_floor is None:
        return None
    return floor > k * baseline_floor


@dataclass(frozen=True)
class BaselineLook:
    """The baseline node's result: the wall-time objective's floor as the
    judges use it (``max(user value, NOISE_FLOOR_MIN, calibrated floor)``),
    the calibration's own floor and largest gap, its seconds, the suite's
    passing count."""

    floor: float | None
    calibrated: float | None
    largest_gap: float | None
    calibration_s: float | None
    tests: int | None


@dataclass(frozen=True)
class ProfileLook:
    ok: bool  # ran and found a hotspot
    hotspots: int
    notes: int  # the profile node's skip notes
    error: str | None


@dataclass(frozen=True)
class RetestLook:
    """One ``retest_one``: the primary judge's gain and floor, the verdict,
    whether it holds, the suite's judge and count, the suite's seconds."""

    applied: int
    gain: float | None
    floor: float | None
    outcome: str
    holds: bool
    reason: str
    tests: str | None
    tests_counted: int | None
    tests_s: float | None
    notes: tuple[str, ...]
    rows: bool = True  # the combiner's A and B rows are there (no RunFailure)

    @property
    def measured_tip(self) -> bool:
        """The one tip change applied and measured: else not a verdict at all."""
        return self.applied == 1 and self.rows

    @classmethod
    def of(cls, found: Retest, primary: str | None, tests_s: float | None,
           notes: Sequence[str]) -> RetestLook:  # fmt: skip
        results = found.verdict.judge_results
        gain = next((j for j in results if j.metric == primary), None)
        suite = next((j for j in results if j.judge == "tests"), None)
        return cls(
            len(found.measured.applied), None if gain is None else gain.gain,
            None if gain is None else gain.noise_floor, found.verdict.outcome.value,
            found.holds, _fit(found.reason), None if suite is None else suite.outcome.value,
            baseline_test_count(found.measured.combined), tests_s, tuple(map(_fit, notes)),
            bool(found.measured.baseline) and bool(found.measured.combined),
        )  # fmt: skip


@dataclass(frozen=True)
class Look:
    name: str
    measured: RetestLook
    seconds: float  # the whole re-test, timed by the replay


def _pct(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 4)


@dataclass
class CaseResult:
    """A case measured (or stopped where the engine stopped it)."""

    case: ReplayCase
    archived: Archived
    baseline: BaselineLook | None = None
    profile: ProfileLook | None = None
    looks: list[Look] = field(default_factory=list)
    setup_s: float | None = None
    connect_s: float | None = None
    baseline_s: float | None = None
    profile_s: float | None = None
    wall_s: float | None = None
    stopped: str | None = None

    @property
    def baseline_floor(self) -> float | None:
        return None if self.baseline is None else self.baseline.floor

    @property
    def not_measured(self) -> str | None:
        """The first look that did not measure the tip, if any."""
        return next((x.name for x in self.looks if not x.measured.measured_tip), None)

    @property
    def rule_triggered(self) -> bool | None:
        """Would the rule re-measure, on m1's floor alone; ``None`` when m1
        did not measure the tip."""
        if not self.looks or not self.looks[0].measured.measured_tip:
            return None
        return triggered(self.looks[0].measured.floor, self.baseline_floor)

    @property
    def rule_verdict(self) -> bool | None:
        """The rule's verdict: m2's when it fires on m1, else m1's; ``None``
        unless both m1 and m2 measured the tip."""
        first = [x.measured for x in self.looks[:2]]
        if len(first) < 2 or not all(m.measured_tip for m in first):
            return None
        return first[1].holds if self.rule_triggered else first[0].holds

    @property
    def floor_spread(self) -> float | None:
        floors = [x.measured.floor for x in self.looks if x.measured.floor is not None]
        return max(floors) - min(floors) if floors else None

    def look_row(self, look: Look) -> dict[str, object]:
        m = look.measured
        return {
            "experiment": REPLAY_EXPERIMENT, "kind": "retest", "id": self.case.id,
            "look": look.name, "applied": m.applied, "gain_pct": _pct(m.gain),
            "floor_pct": _pct(m.floor), "outcome": m.outcome, "holds": m.holds,
            "reason": m.reason, "tests": m.tests, "tests_counted": m.tests_counted,
            "rows": m.rows, "measured_tip": m.measured_tip,
            "over_k_baseline": triggered(m.floor, self.baseline_floor),
            "retest_s": look.seconds, "tests_s": m.tests_s, "notes": list(m.notes),
        }  # fmt: skip

    def row(self) -> dict[str, object]:
        """The case row. ``measured_tip`` per look and ``not_measured`` (the
        first look that did not measure the tip): a no-rows re-test is what
        the live combine node records as "did not hold"; the replay labels it
        "not measured" and gives no verdict on it."""
        c, a, b, p = self.case, self.archived, self.baseline, self.profile
        looks = [x.measured for x in self.looks]
        return {
            "experiment": REPLAY_EXPERIMENT, "kind": "case", "id": c.id, "arm": c.arm,
            "dispatch": c.dispatch, "library": c.library, "tip": c.tip, "patch": c.patch,
            "patch_sha256": a.sha256, "base_commit": c.base_commit,
            "archived_gain_pct": a.gain_pct, "archived_floor_pct": a.floor_pct,
            "archived_holds": a.holds, "archived_baseline_floor_pct": a.baseline_floor_pct,
            "archived_ratio": a.ratio, "archived_seconds": a.seconds,
            "baseline_floor_pct": _pct(None if b is None else b.floor),
            "calibrated_floor_pct": _pct(None if b is None else b.calibrated),
            "largest_gap_pct": _pct(None if b is None else b.largest_gap),
            "baseline_tests": None if b is None else b.tests,
            "gains_pct": [_pct(m.gain) for m in looks],
            "floors_pct": [_pct(m.floor) for m in looks],
            "holds": [m.holds for m in looks], "floor_spread_pct": _pct(self.floor_spread),
            "measured_tip": [m.measured_tip for m in looks],
            "not_measured": self.not_measured,
            "rule_k": RULE_K, "rule_triggered_m1": self.rule_triggered,
            "rule_verdict": self.rule_verdict,
            "m1_holds": looks[0].holds if looks else None,
            "m2_holds": looks[1].holds if len(looks) > 1 else None,
            "profile_ok": None if p is None else p.ok,
            "profile_hotspots": None if p is None else p.hotspots,
            "profile_notes": None if p is None else p.notes,
            "profile_error": None if p is None else p.error,
            "setup_s": self.setup_s, "connect_s": self.connect_s,
            "baseline_s": self.baseline_s,
            "calibration_s": None if b is None else b.calibration_s,
            "profile_s": self.profile_s, "retest_s": [x.seconds for x in self.looks],
            "tests_s": [m.tests_s for m in looks], "wall_s": self.wall_s,
            "stopped": self.stopped,
        }  # fmt: skip


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------


def _f(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _cell(look: RetestLook | None) -> str:
    if look is None:
        return "-"
    if not look.measured_tip:
        return "not measured"
    return f"{_f(_pct(look.gain), 1)} / {_f(_pct(look.floor))} / {flag(look.holds)}"


def note(result: CaseResult) -> str:
    c = result.case
    if result.stopped is not None:
        return _fit(f"REPLAY {c.id}: stopped ({result.stopped})")
    if not result.looks:
        return f"REPLAY {c.id}: no tip; calibration {_f(result.baseline_s, 1)} s"
    m1 = result.looks[0].measured
    fires = {True: "fires on m1", False: "does not fire on m1", None: "cannot read m1"}
    return (
        f"REPLAY {c.id}: m1 {_cell(m1)} against base floor"
        f" {_f(_pct(result.baseline_floor))}; the rule {fires[result.rule_triggered]},"
        f" verdict {flag(result.rule_verdict)}"
    )


VERDICT_HEAD: Final = (
    "| case | tip | archived gain / floor / base floor | replay base floor "
    "| m1 gain / floor / holds | m2 | m3 | floor spread | fires on m1 "
    "| rule verdict | tests m1, m2, m3 | stopped |"
)
TIMING_HEAD: Final = (
    "| case | clone and tip | preflight | baseline | calibration | profile "
    "| m1 | m2 | m3 | suite in m1, m2, m3 | case |"
)


class ReplayRecorder:
    """Rows to the sink, a note per case, the two tables at the end."""

    def __init__(self, sink: ResultsSink) -> None:
        self.sink = sink
        self.results: list[CaseResult] = []
        self.errors: list[tuple[str, str]] = []

    def record(self, result: CaseResult, run: LiveRun) -> None:
        self.results.append(result)
        for look in result.looks:
            self.sink.write(result.look_row(look))
        self.sink.write(result.row())
        run.note(note(result))

    def record_error(self, name: str, run: LiveRun, error: str,
                     measured: Mapping[str, object] | None = None) -> None:  # fmt: skip
        self.errors.append((name, _fit(error)))
        row: dict[str, object] = {"experiment": REPLAY_EXPERIMENT, "kind": "error",
                                  "id": name, "error": _fit(error)}  # fmt: skip
        if measured is not None:
            row["measured"] = dict(measured)
        self.sink.write(row)
        run.note(_fit(f"REPLAY {name}: error {error}"))

    def markdown(self) -> str:
        width = VERDICT_HEAD.count("|") - 1
        lines = ["## Combine re-measure replay (O62: the four rows at 2x, archived tips)",
                 "", VERDICT_HEAD, "|" + " --- |" * width]  # fmt: skip
        for r in self.results:
            a, looks = r.archived, [x.measured for x in r.looks]
            pick = [*looks, None, None, None]
            lines.append(cells([
                r.case.id, r.case.tip,
                f"{_f(a.gain_pct, 1)} / {_f(a.floor_pct)} / {_f(a.baseline_floor_pct)}",
                _f(_pct(r.baseline_floor)), *(_cell(x) for x in pick[:3]),
                _f(_pct(r.floor_spread)), flag(r.rule_triggered), flag(r.rule_verdict),
                ", ".join(m.tests or "-" for m in looks) or "-", r.stopped or "-",
            ]))  # fmt: skip
        for name, error in self.errors:
            lines.append(cells([name, "error", error, *("-",) * (width - 3)]))
        empty = self.unmeasured()
        tail = f"{len(self.results)} case(s), {len(self.errors)} error(s)"
        tail += (
            f"; fewer than {len(LOOKS)} measured looks: {', '.join(empty)}"
            if empty
            else ""
        )
        lines += ["", tail, "",
                  "Wall time (s):", "", TIMING_HEAD,
                  "|" + " --- |" * (TIMING_HEAD.count("|") - 1)]  # fmt: skip
        for r in self.results:
            p, timed = r.profile, [*r.looks, None, None, None]
            prof = "-" if p is None else f"{_f(r.profile_s, 1)} {flag(p.ok)} ({p.hotspots} hotspots, {p.notes} notes)"  # fmt: skip
            lines.append(cells([
                r.case.id, _f(r.setup_s, 1), _f(r.connect_s, 1), _f(r.baseline_s, 1),
                _f(None if r.baseline is None else r.baseline.calibration_s, 1), prof,
                *(_f(None if x is None else x.seconds, 1) for x in timed[:3]),
                ", ".join(_f(x.measured.tests_s, 1) for x in r.looks) or "-",
                _f(r.wall_s, 1),
            ]))  # fmt: skip
        return "\n".join(lines)

    def unmeasured(self) -> list[str]:
        """Tip cases recorded with fewer than ``len(LOOKS)`` measured looks,
        whatever the cause (an EngineError stop, an unmeasured look), each
        as ``id (measured of looks)``; markdown has no tip."""
        want = len(LOOKS)
        found = [(r.case.id, sum(x.measured.measured_tip for x in r.looks))
                 for r in self.results if r.case.tip != NO_TIP]  # fmt: skip
        return [f"{name} ({n} of {want})" for name, n in found if n < want]

    def finish(self, echo: Callable[[str], None]) -> None:
        """The tables, then a failure when a tip case has fewer than three
        measured looks: the job is never green on a partial replay (markdown
        has no tip)."""
        write_markdown("Combine replay", self.markdown(), self.sink.environ, echo)
        empty = self.unmeasured()
        if empty:
            raise AssertionError(
                f"tip case(s) with fewer than {len(LOOKS)} measured looks: "
                + ", ".join(empty)
            )


# ---------------------------------------------------------------------------
# The replay of one case
# ---------------------------------------------------------------------------


class Measurer(Protocol):
    """The replay's seam: the engine (``EngineMeasurer``) or a test's fake."""

    def prepare(self) -> str: ...
    def commit_tip(self, patch: Path, label: str) -> str: ...
    def connect(self) -> None: ...
    def baseline(self) -> BaselineLook: ...
    def profile(self) -> ProfileLook: ...
    def retest(self, look: str, change: KeptChange) -> RetestLook: ...
    def check_guards(self, run: LiveRun) -> None: ...


def tip_change(case: ReplayCase, archived: Archived, commit: str) -> KeptChange:
    """The change the re-test is offered: the fallback's own trial and
    hypothesis ids, or one change standing for the delivered combination."""
    if case.tip == FALLBACK and archived.trial_id is not None:
        hypothesis = archived.hypothesis_id or COMBINATION_ID
        return KeptChange(archived.trial_id, hypothesis, "replay", commit, 0.0, None)
    return KeptChange(f"delivered-{case.dispatch}", COMBINATION_ID, "replay", commit, 0.0, None)  # fmt: skip


def _measure(found: CaseResult, measurer: Measurer, change: KeptChange | None,
             clock: Callable[[], float]) -> None:  # fmt: skip
    """Connect, baseline, profile, the looks; the timings as they come."""
    try:
        at = clock()
        measurer.connect()
        found.connect_s = clock() - at
        at = clock()
        found.baseline = measurer.baseline()
        found.baseline_s = clock() - at
        if found.case.profile:
            at = clock()
            found.profile = measurer.profile()
            found.profile_s = clock() - at
        for name in LOOKS if change is not None else ():
            at = clock()
            look = measurer.retest(name, cast(KeptChange, change))
            found.looks.append(Look(name, look, clock() - at))
            if look.applied != 1:  # a skipped merge is deterministic: no later look
                break
    except EngineError as exc:  # where the engine would stop the run
        found.stopped = _fit(str(exc))


def replay_case(case: ReplayCase, measurer: Measurer, recorder: ReplayRecorder,
                run: LiveRun, *, archive: Path = ARCHIVE,
                clock: Callable[[], float] = time.monotonic) -> CaseResult:  # fmt: skip
    """One case: integrity, the clone and tip, the measurement, the guards,
    the rows. A mismatch, a crash or a breach is an ``error`` row, raised."""
    started = clock()
    try:
        archived = load_archived(case, archive)
        found = CaseResult(case, archived)
        base = measurer.prepare()
        if base != case.base_commit:
            raise IntegrityError(
                f"{case.id}: the repository's base {base} is not the archived {case.base_commit}"
            )
        change = None
        if archived.patch is not None:
            change = tip_change(
                case, archived, measurer.commit_tip(archived.patch, case.id)
            )
        found.setup_s = clock() - started
        _measure(found, measurer, change, clock)
        found.wall_s = clock() - started
    except BaseException as exc:
        recorder.record_error(case.id, run, f"{type(exc).__name__}: {exc}")
        raise
    try:
        measurer.check_guards(run)
    except BaseException as exc:
        recorder.record_error(case.id, run, f"guards: {exc}", found.row())
        raise
    recorder.record(found, run)
    if found.not_measured is not None:
        m = next(x.measured for x in found.looks if x.name == found.not_measured)
        error = IntegrityError(
            f"{case.id}: {found.not_measured} did not measure the tip (applied"
            f" {m.applied}, rows {flag(m.rows)}): {m.reason}"
        )
        recorder.record_error(case.id, run, f"{type(error).__name__}: {error}")
        raise error
    return found


# ---------------------------------------------------------------------------
# The timing seams
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    suite: bool  # a pytest or unittest launch: the project's suite
    seconds: float


class TimedRun:
    """A ``RunOnce`` that hands every launch to ``inner`` (the
    ``LaunchLog``) and times it, failed launches included."""

    def __init__(
        self, inner: RunOnce, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.inner, self.clock = inner, clock
        self.spans: list[Span] = []

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str],
                 sandbox: SandboxPolicy, timeout_s: float, caps: OutputCaps, *,
                 fresh_dirs: Sequence[Path] = ()) -> RunSample:  # fmt: skip
        at = self.clock()
        try:
            return self.inner(
                argv, cwd, env, sandbox, timeout_s, caps, fresh_dirs=fresh_dirs
            )
        finally:
            self.spans.append(Span(classify_runner(argv) != UNKNOWN, self.clock() - at))

    def suite_seconds(self, since: int) -> float | None:
        """The suite launches' seconds from span ``since`` on; ``None``: none."""
        found = [s.seconds for s in self.spans[since:] if s.suite]
        return math.fsum(found) if found else None


@dataclass
class TimedCalibrator:
    """The baseline node's calibrator, timed (``seconds`` summed over calls)."""

    inner: NoiseCalibrator
    clock: Callable[[], float] = time.monotonic
    seconds: float | None = None

    def calibrate(self, workloads: Sequence[Workload], *, run_id: str, commit: str,
                  blocks: int) -> NoiseCalibration:  # fmt: skip
        at = self.clock()
        try:
            return self.inner.calibrate(
                workloads, run_id=run_id, commit=commit, blocks=blocks
            )
        finally:
            self.seconds = (self.seconds or 0.0) + self.clock() - at


# ---------------------------------------------------------------------------
# The engine measurer
# ---------------------------------------------------------------------------

Prepare = Callable[[Path], UserRepo]


class _NoTrials:
    """The context's trial runner: the replay runs no trial."""

    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload],
            baseline: Baseline, *, round: int, branch: str, budget_usd: float,
            brief: TrialBrief) -> Trial:  # fmt: skip
        raise AssertionError("the combine replay runs no trial")


def commit_patch(user: UserRepo, patch: Path, ref: str, message: str, *,
                 policy: GitPolicy = PRODUCTION,
                 environ: Mapping[str, str] | None = None) -> str:  # fmt: skip
    """``patch`` applied to ``user.base`` as a new commit under ``ref``,
    through a scratch index: nothing checked out moves."""
    scratch = Path(tempfile.mkdtemp(prefix="replay-tip-"))
    try:
        with _scratch_git(user.path, policy, environ) as git:
            env = {**git.env, "GIT_INDEX_FILE": str(scratch / "index")}
            staged = _Git(user.path, env, policy)
            staged("read-tree", user.base)
            try:
                staged("apply", "--cached", "--", str(patch))
            except CloneRefusedError as exc:
                raise IntegrityError(
                    f"the archived patch does not apply: {exc}"
                ) from None
            tree = staged("write-tree")
            tip = git("commit-tree", tree, "-p", user.base, "-m", message)
            git("update-ref", ref, tip)
            return tip
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _merge(state: EngineState, delta: Mapping[str, object]) -> EngineState:
    merged = cast(dict[str, Any], dict(state))
    for key, value in delta.items():
        merged[key] = (
            [*merged[key], *cast(list[object], value)] if key == "events" else value
        )
    return cast(EngineState, merged)


class EngineMeasurer:
    """The real ``Measurer``: ``repo`` prepared at ``root/user``, the
    engine's nodes and the combine node's re-test (module docstring); every
    launch through ``launches`` and timed by ``timed``."""

    def __init__(self, repo: OssRepo, root: Path, isolation: Isolation, *, run_id: str,
                 prepare: Prepare | None = None, policy: GitPolicy = PRODUCTION,
                 environ: Mapping[str, str] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self.repo, self.root, self.isolation, self.run_id = (
            repo,
            root,
            isolation,
            run_id,
        )
        self._prepare: Prepare = prepare or functools.partial(
            prepare_repo, repo, policy=policy, environ=environ
        )
        self.policy, self.environ, self.clock = policy, environ, clock
        self.launches = LaunchLog()
        self.timed = TimedRun(self.launches, clock)
        self._user: UserRepo | None = None
        self._before: RepoSnapshot | None = None
        self._state: EngineState | None = None
        self._ctx: NodeContext | None = None
        self._calibrator: TimedCalibrator | None = None
        self.nodes: dict[str, NodeFn] = {}

    @property
    def user(self) -> UserRepo:
        if self._user is None:
            raise AssertionError("the user's repository is not prepared")
        return self._user

    def _ready(self) -> tuple[EngineState, NodeContext]:
        if self._state is None or self._ctx is None:
            raise AssertionError("the replay is not connected")
        return self._state, self._ctx

    def prepare(self) -> str:
        """The repository at ``root/user``; ``root`` made first (the clone
        refuses a destination with no parent directory)."""
        self.root.mkdir(parents=True, exist_ok=True)
        self._user = self._prepare(self.root / "user")
        return self._user.base

    def commit_tip(self, patch: Path, label: str) -> str:
        return commit_patch(self.user, patch, f"refs/replay/{safe_name(label)}",
                            f"replay: {label}", policy=self.policy, environ=self.environ)  # fmt: skip

    def _context(self, project: Project) -> NodeContext:
        """``factory.build_context``'s measurement pieces, no transport."""
        mode = self.isolation.mode
        git = GitWorkspace(Path(project.root_path), executable=settings.GIT_EXECUTABLE,
                           timeout_s=settings.GIT_TIMEOUT_S)  # fmt: skip
        runner = GitBaselineRunner(project, git=git, network=mode, fs=mode, run=self.timed,
                                   count_ops=settings.OP_COUNT_JUDGE,
                                   scaling=settings.SCALING_JUDGE)  # fmt: skip
        blocks = settings.NOISE_CALIBRATION_BLOCKS
        self._calibrator = TimedCalibrator(runner, self.clock) if blocks else None
        judges = default_judges(settings.NOISE_MULTIPLIER, op_count=settings.OP_COUNT_JUDGE,
                                scaling=settings.SCALING_JUDGE)  # fmt: skip
        return NodeContext(
            runner=_NoTrials(), baseline_runner=runner, judges=judges,
            repository=InMemoryRepository(),
            preflight=GitPreflight(executable=settings.GIT_EXECUTABLE,
                                   protected=DEFAULT_PROTECTED_PATTERNS, network=mode,
                                   fs=mode, run=self.timed),
            profiler=CProfiler(project, git=git, network=mode, fs=mode, run=self.timed),
            combiner=GitCombiner(git=git, network=mode, fs=mode, run=self.timed),
            default_output_check=settings.DEFAULT_OUTPUT_CHECK,
            calibrator=self._calibrator, calibration_blocks=blocks,
            confirm_winners=settings.CONFIRM_WINNERS,
        )  # fmt: skip

    def connect(self) -> None:
        """The snapshot, then the connect and define nodes; the context bound
        to the project the preflight resolved, as the factory's is."""
        user = self.user
        self._before = user.snapshot()
        project = self.repo.project(user.path)
        state = initial_state(project, [self.repo.workload(project)],
                              self.repo.corpus.objectives(project),
                              self.repo.corpus.guardrails(project), run_id=self.run_id)  # fmt: skip
        state = _merge(state, make_nodes(self._context(project))["connect"](state))
        self._ctx = self._context(state["project"])
        self.nodes = make_nodes(self._ctx)
        self._state = _merge(state, self.nodes["define"](state))

    def baseline(self) -> BaselineLook:
        state, _ = self._ready()
        self._state = state = _merge(state, self.nodes["baseline"](state))
        measured = cast(Baseline, state["baseline"])
        wall = [
            o.min_relative_gain
            for o in measured.objectives
            if o.metric == METRIC_WALL_TIME_S
        ]
        calibration = measured.calibration
        return BaselineLook(
            wall[0] if wall else None, None if calibration is None else calibration.floor,
            None if calibration is None else max(calibration.gaps.values(), default=0.0),
            None if self._calibrator is None else self._calibrator.seconds,
            baseline_test_count(measured.measurements),
        )  # fmt: skip

    def profile(self) -> ProfileLook:
        """The profile node on the base; a refusal is recorded, not raised."""
        state, _ = self._ready()
        try:
            delta = self.nodes["profile"](state)
        except EngineError as exc:
            return ProfileLook(False, 0, 0, _fit(f"{type(exc).__name__}: {exc}"))
        hotspots = len(cast(list[object], delta["hotspots"]))
        notes = len(cast(list[object], delta["events"])) - 1  # one announce, then skips
        return ProfileLook(hotspots > 0, hotspots, notes, None)

    def retest(self, look: str, change: KeptChange) -> RetestLook:
        """``retest_one`` as the combine node calls it (``_combine_set``)."""
        state, ctx = self._ready()
        measured = cast(Baseline, state["baseline"])
        run_id = f"{self.run_id}-{look}"
        target = CombineTarget(
            run_id=run_id, project=state["project"], base_commit=str(state["base_commit"]),
            workloads=tuple(state["workloads"]), branch=f"{ctx.branch_prefix}run-{run_id}",
            round=1, quality_files=measured.quality_files,
        )  # fmt: skip
        rules = _combine_rules(ctx, measured)
        combiner = cast(GitCombiner, ctx.combiner)
        mark = len(self.timed.spans)
        found = retest_one(combiner, change, rules, target)
        return RetestLook.of(found, rules.primary, self.timed.suite_seconds(mark),
                             combiner.last_notes)  # fmt: skip

    def check_guards(self, run: LiveRun) -> None:
        """No request, the replay's phases only, every launch sandboxed and
        isolated, the user's repository unchanged; each message names its guard."""
        mode = (self.isolation.mode, self.isolation.missing)
        assert mode == ("required", None), f"isolation not required: {mode}"
        sent = (len(run.capture.messages()), len(run.records))
        assert sent == (0, 0), f"no request may be sent: {sent}"
        assert run.spent_usd <= run.cap_usd, f"spend over the cap: {run.spent_usd}"
        phases = self.launches.phases()
        assert phases, "no launch was recorded"
        allowed = PREFLIGHT_PHASE in phases and phases <= REPLAY_PHASES
        assert allowed, f"phases outside the replay: {sorted(phases)}"
        for launch in self.launches.launches:
            modes = (launch.network, launch.fs)
            assert modes == ("required", "required"), f"unsandboxed launch: {launch}"
            isolated = launch.net_isolated and launch.fs_isolated
            assert isolated, f"launch not isolated: {launch}"
        assert self.user.snapshot() == self._before, "user repository changed"
        worktrees = self.user.worktrees()
        assert len(worktrees) == 1, f"worktrees left: {worktrees}"


# ---------------------------------------------------------------------------
# The settings, the need, the minutes and the driver
# ---------------------------------------------------------------------------


def check_settings(base: Settings = settings) -> None:
    """Refuse, before any clone, a process off the X2 measurement settings."""
    wrong = sorted(k for k, v in REPLAY_SETTINGS.items() if getattr(base, k) != v)
    if wrong:
        raise ValueError(f"{', '.join(wrong)} not as the X2 arms measured "
                         "(ci.yml's step3 rule, OP_COUNT_JUDGE=true, every other "
                         "measurement setting at its default)")  # fmt: skip


def replay_need() -> float:
    """What a replay dispatch asks the ledger for: nothing."""
    return REPLAY_RUN_CAP_USD


def case_units(case: ReplayCase) -> int:
    """Re-test-sized units: the preflight, the baseline, its calibration
    blocks, the profile when the case runs it, and the looks."""
    looks = 0 if case.tip == NO_TIP else len(LOOKS)
    blocks = int(cast(int, REPLAY_SETTINGS["NOISE_CALIBRATION_BLOCKS"]))
    return 1 + 1 + blocks + int(case.profile) + looks


def plan_minutes(cases: Iterable[ReplayCase] = CASES) -> int:
    seconds = math.fsum(SETUP_S + case_units(c) * UNIT_S[c.library] for c in cases)
    return math.ceil(seconds / 60)


def replay_live(case: ReplayCase, run: LiveRun, root: Path, isolation: Isolation,
                recorder: ReplayRecorder, *, policy: GitPolicy = PRODUCTION) -> CaseResult:  # fmt: skip
    """One case on the engine measurer: its library, its own directory."""
    measurer = EngineMeasurer(LIBRARIES[case.library], root / case.id, isolation,
                              run_id=f"replay-{CASES.index(case)}", policy=policy)  # fmt: skip
    return replay_case(case, measurer, recorder, run)
