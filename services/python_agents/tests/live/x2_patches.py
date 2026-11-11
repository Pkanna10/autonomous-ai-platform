"""U-patch: the X2 patch files, record-only.

Every X2 run writes into the results artifact each kept trial's diff
(``Trial.diff``, as the runner recorded it against ``Trial.base_commit``)
and the delivered combined patch (``Delivery.combined_diff``, the publisher's
``base..tip`` diff of the held combination), both read from the engine's
state, never recomputed, each through ``redact_keys`` as every other
model-authored field. The files sit under ``PATCH_DIR`` beside
``$LIVE_RESULTS_PATH`` (ci.yml uploads both), one directory a run
(``run_dir``: the arm key and the library); a row records each file's path
from the artifact root, the sha256 and byte count of the bytes written, and
whether the engine's diff cap truncated it (with the original size).
Without a results path nothing is written and the hash is still recorded.
Every name is checked against ``_NAME`` (ids the engine generated: uuid4
strings) and every target against the root it must stay under, so no name
from data walks out. A write never raises: a failure is the entry's
``error`` (the exception class and a short reason, no path), so the run's
rows are always written.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .conftest import redact_keys
from .corpus import RESULTS_ENV
from .discovery_io import ResultsSink

PATCH_DIR: Final = "live-patches"
DELIVERED_FILE: Final = "delivered.patch"
NO_KEEP: Final = "no kept trial: no diff written"
NO_COMBINE: Final = "no combine: no combined patch written"
NOT_HELD: Final = "the combine did not hold: no combined patch written"
NO_BRANCH: Final = (
    "the combine held but no branch was delivered: no combined patch written"
)
ORPHAN: Final = "the kept verdict's trial is not recorded: no diff written"
OUTSIDE: Final = "ValueError: the target resolves outside the patch directory"
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
# ``GitWorkspace._patch``'s marker for a diff past ``MAX_DIFF_BYTES``
_TRUNCATED: Final = re.compile(r"\n\[diff truncated: \d+ of (\d+) bytes shown\]\n\Z")

Entry = dict[str, object]


def safe_name(name: str) -> str:
    """``name`` when it is one plain path component (ASCII letters, digits,
    ``_.-``, no leading dot, no ``..``, at most 128), else ``ValueError``."""
    if not _NAME.fullmatch(name) or ".." in name:
        raise ValueError(f"not a safe file name: {name[:64]!r}")
    return name


def run_dir(arm: str, repo: str) -> str:
    """A run's directory: the arm key, any character off the safe set as
    ``_`` (X2-0' is ``X2-0_``), then the library (checked when written)."""
    return f"{re.sub(r'[^A-Za-z0-9_.-]', '_', arm)}-{repo}"


def trial_file(trial_id: str) -> str:
    return f"trial-{trial_id}.diff"


def patch_root(sink: ResultsSink) -> Path | None:
    """``PATCH_DIR`` beside the results file (``ResultsSink`` checked it is
    absolute), ``None`` without one."""
    target = sink.environ.get(RESULTS_ENV, "")
    return Path(target).parent / PATCH_DIR if target else None


def missing(error: str) -> Entry:
    """The entry of a file not written, ``error`` saying why."""
    return {"file": None, "sha256": None, "bytes": None, "truncated": False,
            "original_bytes": None, "error": error}  # fmt: skip


@dataclass(frozen=True)
class PatchWriter:
    root: Path | None  # ``patch_root``; ``None``: hash only, write nothing
    run_dir: str

    @property
    def folder(self) -> str | None:
        """The run's directory from the artifact root; ``None`` if unsafe."""
        try:
            return f"{PATCH_DIR}/{safe_name(self.run_dir)}"
        except ValueError:
            return None

    def write(self, name: str, text: str) -> Entry:
        """Write ``text``'s redacted UTF-8 bytes to ``run_dir/name`` under
        the root; the entry a row records for it. Never raises."""
        try:
            rel = f"{PATCH_DIR}/{safe_name(self.run_dir)}/{safe_name(name)}"
            text = redact_keys(text)
            data = text.encode("utf-8")
            if self.root is not None:
                folder = self.root / self.run_dir
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / name
                if not target.resolve().is_relative_to(self.root.resolve()):
                    return missing(OUTSIDE)
                target.write_bytes(data)
        except OSError as exc:  # the message would name the path: the reason only
            return missing(f"{type(exc).__name__}: {exc.strerror or 'write failed'}")
        except ValueError as exc:  # an unsafe name, text not UTF-8
            return missing(f"{type(exc).__name__}: {str(exc)[:120]}")
        cut = _TRUNCATED.search(text)
        return {"file": None if self.root is None else rel,
                "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                "truncated": cut is not None,
                "original_bytes": None if cut is None else int(cut.group(1)),
                "error": None}  # fmt: skip
