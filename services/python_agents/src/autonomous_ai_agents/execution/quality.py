"""The quality scorer (D37): a frozen evaluator turns a workload's output into
the ``quality:<name>`` number, never trusting text the trial prints.

``freeze`` reads each frozen path at the base commit (a tracked regular
file, mode 100644 or 100755: a symlink blob holds only the link text; at most
``QUALITY_MAX_FROZEN_BYTES`` in all) and records its sha256; on a resume the
recorded files must match. A *builtin* (``accuracy``, ``error_rate``,
``macro_f1``, ``mae``, ``rmse``) parses the frozen labels and the output, one
strict UTF-8 value per line, at most ``QUALITY_MAX_ROWS``, and executes
nothing. An *external* scorer runs from ``<run>/quality``, a copy of the
recorded blobs (each sha256 re-checked) made immediately before each scoring
and removed in ``finally`` inside ``owned_phases``, so it never exists while
a workload runs. The engine's own interpreter (``-I -S``) puts the output,
written to the phase's scratch dir, on fd 0 and ``execv``s
``<interpreter> -s -B <copy>/<scorer[1]> ...``: no shell, cwd the copy, no
``PYTHONPATH``; not ``-E``, which would drop ``child_env``'s forced
``PYTHONHASHSEED=0`` (its allowlist already drops every ``PYTHON*``
hijack); network and writes confined (``SandboxPolicy(writable=(copy,
scratch))``), ``QUALITY_TIMEOUT_S``. ``procrun.run_once`` fixes stdin to
``/dev/null``, hence that step. Its stdout must be exactly ``aip-quality/1
<name>=<finite decimal>``, one line of at most 128 bytes, exit 0.

Scores are cached by ``raw_fingerprint`` (the exact bytes); a row without one
agreed only within a tolerance and is scored on its own bytes. Output bytes
and label contents never appear in a score's errors, which name counts, line
numbers and the check's own paths only (the scorer's stderr is never read).
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import shutil
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import EngineError
from autonomous_ai_agents.common.models import BuiltinMeasure, FrozenFile, QualityCheck
from autonomous_ai_agents.execution.git import GitError, contained, remove_contained
from autonomous_ai_agents.execution.measure import RunOnce
from autonomous_ai_agents.execution.phase import (
    PhaseDirs,
    PhaseGit,
    owned_phases,
    phase_dirs,
)
from autonomous_ai_agents.execution.procrun import (
    OutputCaps,
    RunFailure,
    RunSample,
    run_once,
)
from autonomous_ai_agents.execution.sandbox import SandboxPolicy, child_env

PHASE = "quality"
LINE_MAX_BYTES = 128
_FLOOD_BYTES = 64 * 1024
_DECIMAL = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
_NUMBER = re.compile(_DECIMAL, re.ASCII)
_LINE = re.compile(
    rb"aip-quality/1 ([a-z][a-z0-9_]{0,31})=(" + _DECIMAL.encode() + rb")\n?"
)
_STDIN_SHIM = (
    "import os,sys;fd=os.open(sys.argv[1],os.O_RDONLY|os.O_NOFOLLOW);"
    "os.dup2(fd,0);os.close(fd);os.execv(sys.argv[2],sys.argv[2:])"
)
_REGRESSION = (BuiltinMeasure.mae, BuiltinMeasure.rmse)
_REGULAR, _SYMLINK = ("100644", "100755"), "120000"


class UnscoreableError(EngineError):
    """No quality number for this output; the message says why, never what."""


class QualityGit(PhaseGit, Protocol):
    """The ``GitWorkspace`` calls the scorer makes (``PhaseGit`` for cleanup)."""

    def blob_modes(self, commit: str) -> dict[str, str]: ...
    def read_blob(
        self, commit: str, path: str, *, limit: int | None = None
    ) -> bytes: ...


class QualityScorer(Protocol):
    def freeze(
        self,
        git: QualityGit,
        commit: str,
        *,
        run_id: str,
        recorded: Sequence[FrozenFile] = (),
    ) -> tuple[FrozenFile, ...]: ...
    def score(self, output: bytes | None, fingerprint: str | None) -> float: ...
    def score_baseline(
        self, output: bytes | None, fingerprint: str | None
    ) -> float: ...


@dataclass(frozen=True)
class _Frozen:
    """What ``freeze`` recorded: where to read the blobs, and the phase dirs."""

    git: QualityGit
    commit: str
    files: tuple[FrozenFile, ...]
    dirs: PhaseDirs


def _lines(data: bytes, what: str, max_rows: int) -> list[str]:
    """One stripped, non-empty value per line; a final newline is optional."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise UnscoreableError(f"{what} is not UTF-8") from None
    rows = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if not 0 < rows <= max_rows:
        raise UnscoreableError(f"{rows} lines in {what}, 1 to {max_rows} allowed")
    values = [line.strip() for line in text.split("\n")[:rows]]
    for number, value in enumerate(values, start=1):
        if not value:
            raise UnscoreableError(f"line {number} of {what} is empty")
    return values


def _numbers(values: Sequence[str], what: str) -> list[float]:
    numbers = []
    for number, value in enumerate(values, start=1):
        parsed = float(value) if _NUMBER.fullmatch(value) else math.nan
        if not math.isfinite(parsed):
            raise UnscoreableError(f"line {number} of {what} is not a finite decimal")
        numbers.append(parsed)
    return numbers


def _macro_f1(labels: Sequence[str], predicted: Sequence[str]) -> float:
    """sklearn's macro F1 over the union of classes (zero_division=0)."""
    hits = Counter(p for p, q in zip(predicted, labels, strict=True) if p == q)
    guessed, actual = Counter(predicted), Counter(labels)
    classes = sorted(guessed.keys() | actual.keys())  # a fixed summation order
    return math.fsum(2 * hits[c] / (guessed[c] + actual[c]) for c in classes) / len(
        classes
    )


def _builtin(measure: BuiltinMeasure, labels: Sequence[str], output: bytes) -> float:
    predicted = _lines(output, "the output", settings.QUALITY_MAX_ROWS)
    if len(predicted) != len(labels):
        raise UnscoreableError(
            f"the output has {len(predicted)} lines and the labels {len(labels)}"
        )
    if measure in _REGRESSION:
        guesses, truths = _numbers(predicted, "the output"), _numbers(labels, "labels")
        errors = [abs(p - q) for p, q in zip(guesses, truths, strict=True)]
        if measure is BuiltinMeasure.mae:
            return math.fsum(errors) / len(errors)
        return math.sqrt(math.fsum(e * e for e in errors) / len(errors))
    if measure is BuiltinMeasure.macro_f1:
        return _macro_f1(labels, predicted)
    right = sum(p == q for p, q in zip(predicted, labels, strict=True)) / len(labels)
    return right if measure is BuiltinMeasure.accuracy else 1.0 - right


def read_score(sample: RunSample, name: str) -> float:
    """The number in the scorer's one ``aip-quality/1`` line, else unscoreable."""
    if sample.exit != 0:
        how = (
            f"exit status {sample.exit}"
            if sample.exit > 0
            else f"signal {-sample.exit}"
        )
        raise UnscoreableError(
            f"the scorer ended with {how} (a scorer must be self-contained: only "
            "the frozen files are in its directory; it runs outside the project, "
            "with no PYTHONPATH, so it cannot import the project's packages)"
        )
    if sample.stdout_bytes > LINE_MAX_BYTES:
        raise UnscoreableError(
            f"the scorer printed {sample.stdout_bytes} bytes; one line of at most "
            f"{LINE_MAX_BYTES} is expected"
        )
    match = _LINE.fullmatch(sample.stdout_head)
    if match is None:
        raise UnscoreableError(
            "the scorer's stdout is not one 'aip-quality/1 <name>=<finite decimal>' line"
        )
    if match[1].decode() != name:
        raise UnscoreableError(f"the scorer reported another metric name than {name!r}")
    value = float(match[2])
    if not math.isfinite(value):
        raise UnscoreableError("the scorer's number is not finite")
    return value


def _interpreter(name: str, search: str) -> str:
    """``scorer[0]`` as an absolute path: never relative, never where trials run."""
    if "/" in name and not os.path.isabs(name):
        raise EngineError(
            f"scorer[0] {name!r} must be a bare interpreter name or an absolute path"
        )
    search = _absolute_entries(search)  # a relative entry resolves in the cwd
    found = name if os.path.isabs(name) else shutil.which(name, path=search)
    if found is None:
        raise EngineError(f"scorer[0] {name!r} is not on PATH ({search})")
    real = os.path.realpath(found)
    if not (os.path.isfile(real) and os.access(real, os.X_OK)):
        raise EngineError(f"scorer[0] {found!r} is not an executable file")
    root = Path(os.path.realpath(settings.WORKTREE_ROOT))
    if any(Path(p).is_relative_to(root) for p in (os.path.abspath(found), real)):
        raise EngineError(f"scorer[0] {found!r} must not live under WORKTREE_ROOT")
    return found


def _require_regular(path: str, mode: str | None) -> None:
    """A frozen path is a regular blob at the base; never shows a link target."""
    if mode is None:
        raise EngineError(f"quality file {path!r} is not tracked at the base")
    if mode == _SYMLINK:
        raise EngineError(
            f"quality file {path!r} is a symlink; freeze the file it points to"
        )
    if mode not in _REGULAR:
        raise EngineError(f"quality file {path!r} is not a regular file (mode {mode})")


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _materialise(frozen: _Frozen) -> None:
    """The recorded blobs, each sha256 re-checked, into a fresh copy, and a
    fresh scratch dir (the probe dir is the launcher's)."""
    dirs = frozen.dirs
    for fresh in (dirs.worktree, dirs.scratch):
        remove_contained(fresh)
        contained(fresh).mkdir(mode=0o700, parents=True)
    dirs.probe.mkdir(mode=0o700, parents=True, exist_ok=True)
    for file in frozen.files:
        data = frozen.git.read_blob(frozen.commit, file.path, limit=file.size + 1)
        if hashlib.sha256(data).hexdigest() != file.sha256:
            raise UnscoreableError(
                f"quality file {file.path!r} changed since the baseline"
            )
        target = dirs.worktree / file.path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_new(target, data)


def _absolute_entries(path: str) -> str:
    entries = path.split(os.pathsep)
    return os.pathsep.join(e for e in entries if os.path.isabs(e)) or os.defpath


def _default_search() -> str:
    return _absolute_entries(os.environ.get("PATH", ""))


class FrozenScorer:
    """``QualityScorer`` for one ``QualityCheck``; ``run`` and the isolation
    modes are injectable (the modes default to the settings)."""

    def __init__(
        self,
        check: QualityCheck,
        *,
        run: RunOnce = run_once,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        base_env: Mapping[str, str] | None = None,
        search: str | None = None,
    ) -> None:
        self.check, self._run = check, run
        self._network = settings.NETWORK_ISOLATION if network is None else network
        self._fs = settings.FS_ISOLATION if fs is None else fs
        self._platform, self._base_env = platform, base_env
        self._search = _default_search() if search is None else search
        self._frozen: _Frozen | None = None
        self._labels: list[str] = []
        self._python = ""
        self._cache: dict[str, float] = {}

    def freeze(
        self,
        git: QualityGit,
        commit: str,
        *,
        run_id: str,
        recorded: Sequence[FrozenFile] = (),
    ) -> tuple[FrozenFile, ...]:
        """Record each frozen file at ``commit`` for run ``run_id``;
        ``EngineError`` when one is untracked, they are too large, or one
        differs from ``recorded`` (``Baseline.quality_files``, on a resume)."""
        before = {frozen.path: frozen for frozen in recorded}
        modes, left = git.blob_modes(commit), settings.QUALITY_MAX_FROZEN_BYTES
        files, blobs = [], {}
        for path in self.check.frozen_paths:
            _require_regular(path, modes.get(path))
            data = git.read_blob(commit, path, limit=left + 1)
            if len(data) > left:
                raise EngineError(
                    f"the quality files hold more than "
                    f"{settings.QUALITY_MAX_FROZEN_BYTES} bytes"
                )
            left -= len(data)
            frozen = FrozenFile(
                path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data)
            )
            if before and before.get(path) != frozen:
                raise EngineError(f"quality file {path!r} changed since the baseline")
            files.append(frozen)
            blobs[path] = data
        if self.check.labels is not None:
            labels = blobs[self.check.labels]
            self._labels = _lines(labels, "the labels", settings.QUALITY_MAX_ROWS)
            if self.check.measure in _REGRESSION:
                _numbers(self._labels, "the labels")
        else:
            self._python = _interpreter(self.check.scorer[0], self._search)
        dirs = phase_dirs(run_id, PHASE)
        self._frozen = _Frozen(git, commit, tuple(files), dirs)
        self._cache.clear()
        return self._frozen.files

    def score(self, output: bytes | None, fingerprint: str | None) -> float:
        """The quality of ``output``; cached by its exact ``fingerprint``."""
        if fingerprint is not None and fingerprint in self._cache:
            return self._cache[fingerprint]
        value = self._score(output)
        if fingerprint is not None:
            self._cache[fingerprint] = value
        return value

    def score_baseline(self, output: bytes | None, fingerprint: str | None) -> float:
        """Score the base output twice; differing numbers refuse the check."""
        first = self._score(output)
        if self.check.measure is None and self._score(output) != first:
            raise UnscoreableError(
                "the scorer is not deterministic: two runs on the base output "
                "differ, so the quality check is refused"
            )
        if fingerprint is not None:
            self._cache[fingerprint] = first
        return first

    def _score(self, output: bytes | None) -> float:
        if self._frozen is None:
            raise EngineError("the quality scorer must freeze first")
        if output is None:
            raise UnscoreableError(
                "no agreed output to score: the timed runs disagreed, stdout was "
                f"longer than OUTPUT_HEAD_BYTES ({settings.OUTPUT_HEAD_BYTES}), or "
                "the output_file was larger than OUTPUT_TOLERANCE_MAX_BYTES "
                f"({settings.OUTPUT_TOLERANCE_MAX_BYTES})"
            )
        if self.check.measure is not None:
            return _builtin(self.check.measure, self._labels, output)
        frozen = self._frozen
        with owned_phases(frozen.git, "the quality scorer", frozen.dirs):
            try:
                _materialise(frozen)
            except OSError as error:
                raise UnscoreableError(
                    f"the frozen copy could not be made: {error.strerror}"
                ) from None
            except (ValueError, GitError):  # a planted link; git's text unshown
                raise UnscoreableError("the frozen copy could not be made") from None
            return self._external(frozen.dirs, output)

    def _external(self, dirs: PhaseDirs, output: bytes) -> float:
        policy = SandboxPolicy(
            network=self._network,
            fs=self._fs,
            writable=(dirs.worktree, dirs.scratch),
            probe_dir=dirs.probe,
            platform=self._platform,
        )
        copy, scratch = policy.writable
        stdin = scratch / "stdin"
        _write_new(stdin, output)
        home, tmp = scratch / "home", scratch / "tmp"
        env = child_env(home=home, tmpdir=tmp, worktree=copy, base=self._base_env)
        env.pop("PYTHONPATH")
        script = str(copy / self.check.scorer[1])
        shim = [sys.executable, "-I", "-S", "-c", _STDIN_SHIM, str(stdin)]
        argv = [*shim, self._python, "-s", "-B", script, *self.check.scorer[2:]]
        caps = OutputCaps(_FLOOD_BYTES, LINE_MAX_BYTES, 1)
        timeout = settings.QUALITY_TIMEOUT_S
        try:
            sample = self._run(
                argv, copy, env, policy, timeout, caps, fresh_dirs=(home, tmp)
            )
        except RunFailure as failure:  # its stderr part may hold scorer text
            reason = failure.reason
            if reason.startswith("no measurement report"):
                reason = reason.split(":", 1)[0]
            raise UnscoreableError(f"the scorer did not run: {reason}") from None
        return read_score(sample, self.check.name)


def label_column_leaks(labels: bytes, files: Mapping[str, bytes]) -> tuple[str, ...]:
    """Each ``path column N`` of ``files`` (comma- or tab-separated, header
    row allowed) whose values are exactly the labels, in order (D37): a
    warning that an unfrozen input carries them. Unreadable files are skipped."""
    try:
        values = _lines(labels, "the labels", settings.QUALITY_MAX_ROWS)
    except UnscoreableError:
        return ()
    found: dict[str, None] = {}
    for path, data in files.items():
        try:
            lines = data.decode("utf-8").split("\n")
        except UnicodeDecodeError:
            continue
        lines = lines[:-1] if lines[-1] == "" else lines
        if len(lines) - len(values) not in (0, 1):
            continue
        for delimiter in (",", "\t"):
            try:
                rows = list(csv.reader(lines, delimiter=delimiter, strict=True))
            except csv.Error:
                continue
            for column in range(max(len(row) for row in rows)):
                cells = [
                    row[column].strip() if column < len(row) else "" for row in rows
                ]
                if cells[-len(values) :] == values:
                    found[f"{path} column {column + 1}"] = None
    return tuple(found)
