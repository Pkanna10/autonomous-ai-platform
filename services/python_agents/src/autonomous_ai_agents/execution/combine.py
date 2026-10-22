"""Combine the kept changes onto the base and re-test them; publish the result.

``GitCombiner.combine`` (spec decisions 7, 25 and 38) takes F0
(``repo_fingerprint``), then merges each ``KeptChange`` in the given order
onto ACC = base with plain ``merge-tree --write-tree ACC X`` (no
``--merge-base``: Apple git is 2.39, and every trial's only parent is the
base, so the natural merge base is the base). A kept commit that is not a
single-parent child of the base would bring in more than its own diff, so it
is skipped before merge-tree sees it, as is a conflict or a change already
contained in ACC; each applied change is one ``commit-tree`` with one parent,
the engine identity and the base's dates (a re-run builds the same SHAs).
Only objects are written, never a ref. When something applied, the tip is
checked out in ``<run>/combine`` and a fresh ``<run>/combine-base`` at the
base, every workload is measured A/B interleaved (``measure_abab``) and the
suite runs once on the tip, against the baseline's passing-test count; then
F1 (``RepoTamperedError`` when it differs). The shared
``phase.owned_phases`` cleanup removes both worktrees, their ``_scratch``
and ``_probe`` dirs, prunes and ``rmdir``s an empty ``<run>``. Every call is
self-contained: the node's fallback is a second call. A ``RunFailure`` returns the applied changes with no rows, so
the node's completeness rule refuses the combination; its reason is a note.
Notes go to ``last_notes`` (``CombineMeasured`` has no field for them).

``GitBranchPublisher.publish`` refuses an unsafe branch
(``refnames.assert_safe_branch`` with the publisher's prefix: outside it, the
default branch, a bad refname), a tip that does not descend from the base, a
branch checked out in any worktree, compared case-insensitively (a
case-insensitive file system shares one loose ref file), an existing ref at
another commit, and a default branch that is a symref (through any chain)
to the branch; computes the capped ``base..tip`` diff from the objects
(``diff_commits``, no worktree), then creates the ref create-only: a ref
already at ``tip`` is a no-op, a racing writer at any other value is a
``DeliveryError``. A default branch that only now resolves to ``tip`` was a
dangling symref to the new ref the pre-check missed, so the ref is deleted
again and the publish refused. Never ``branch -f``, never a push, never HEAD
or the default branch.
"""

from __future__ import annotations

import functools
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from autonomous_ai_agents.common.config import IsolationMode, settings
from autonomous_ai_agents.common.errors import DeliveryError, RepoTamperedError
from autonomous_ai_agents.common.models import (
    CombineSkip,
    Measurement,
    Project,
    Workload,
)
from autonomous_ai_agents.common.refnames import (
    assert_safe_branch,
    branch_prefix_problem,
    refname_problem,
)
from autonomous_ai_agents.execution.git import GitError, GitWorkspace, repo_fingerprint
from autonomous_ai_agents.execution.measure import (
    Phase,
    RunOnce,
    make_phase,
    measure_abab,
    run_tests,
)
from autonomous_ai_agents.execution.phase import owned_phases, phase_dirs
from autonomous_ai_agents.execution.procrun import RunFailure, run_once
from autonomous_ai_agents.execution.protocols import CombineMeasured, KeptChange

TIP, BASE = "combine", "combine-base"
CONFLICT = "conflict"
NOT_A_COMMIT = "not a commit"
NOT_A_CHILD = "not a single-parent child of the base commit"
NOTHING_LEFT = "nothing left to apply"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_OID = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_QUOTE = 300


def _quote(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text[:_QUOTE])


def _require_id(what: str, value: str) -> None:
    """Ids go into a directory name or a commit message: one safe token."""
    problem = "it contains '/'" if "/" in value else refname_problem(value)
    if _ID.fullmatch(value) is None or problem is not None:
        raise ValueError(f"{what} {_quote(value)!r} is not a safe id: {problem}")


class GitCombiner:
    """The real ``Combiner``. ``git`` defaults to the project's ``GitWorkspace``;
    the modes default to the settings (``make_phase``)."""

    def __init__(
        self,
        *,
        git: GitWorkspace | None = None,
        network: IsolationMode | None = None,
        fs: IsolationMode | None = None,
        platform: str = sys.platform,
        base_env: Mapping[str, str] | None = None,
        run: RunOnce = run_once,
    ) -> None:
        self._git = git
        self._phase = functools.partial(
            make_phase, network=network, fs=fs, platform=platform, base_env=base_env
        )
        self._run = run
        self._notes: tuple[str, ...] = ()

    @property
    def last_notes(self) -> tuple[str, ...]:
        """The notes of the latest ``combine`` call (run notes, failures)."""
        return self._notes

    def combine(
        self,
        run_id: str,
        project: Project,
        base_commit: str,
        kept: Sequence[KeptChange],
        workloads: Sequence[Workload],
        *,
        baseline_count: int | None = None,
    ) -> CombineMeasured:
        """Merge ``kept`` greedily onto ``base_commit`` and re-test the tip.

        ``baseline_count`` is the baseline's passing-test count
        (``measure.baseline_test_count``); the suite on the tip must reach it.
        """
        _require_id("run_id", run_id)
        for change in kept:
            _require_id("trial_id", change.trial_id)
            _require_id("hypothesis_id", change.hypothesis_id)
        if len({change.trial_id for change in kept}) != len(kept):
            raise ValueError("a kept trial is listed more than once")
        if _OID.fullmatch(base_commit) is None:
            raise ValueError(f"base_commit {_quote(base_commit)!r} is not a commit id")
        self._notes = ()
        git = self._git or GitWorkspace(Path(project.root_path))
        before = repo_fingerprint(git)
        if git.resolve_commit(base_commit) != base_commit:
            raise ValueError(f"base_commit {base_commit} is not a commit object")
        tip, applied, skipped = self._merge(git, base_commit, kept)
        if not applied:
            return CombineMeasured(base_commit, (), skipped, (), ())
        sides = phase_dirs(run_id, TIP), phase_dirs(run_id, BASE)
        with owned_phases(git, "the combine", *sides):
            tip_wt = git.add_worktree(sides[0].worktree, tip)
            base_wt = git.add_worktree(sides[1].worktree, base_commit)
            tip_dirs, base_dirs = sides
            b = self._phase(
                git,
                tip_wt,
                scratch=tip_dirs.scratch,
                probe=tip_dirs.probe,
                run=self._run,
            )
            a = self._phase(
                git,
                base_wt,
                scratch=base_dirs.scratch,
                probe=base_dirs.probe,
                run=self._run,
            )
            rows = self._measure(a, b, project, workloads, baseline_count)
            if repo_fingerprint(git) != before:
                raise RepoTamperedError(
                    "the repository changed while the combine re-test ran: its"
                    " refs, config or hooks differ from before the run"
                )
        return CombineMeasured(tip, tuple(applied), skipped, *rows)

    def _merge(
        self, git: GitWorkspace, base: str, kept: Sequence[KeptChange]
    ) -> tuple[str, list[str], tuple[CombineSkip, ...]]:
        acc = base
        tree = git.merge(base, base).tree
        applied: list[str] = []
        skipped: list[CombineSkip] = []
        for change in kept:
            reason = _unfit(git, base, change.commit)
            if reason is not None:
                skipped.append(CombineSkip(trial_id=change.trial_id, reason=reason))
                continue
            merged = git.merge(acc, change.commit)
            if merged.tree is None:
                skip = CombineSkip(
                    trial_id=change.trial_id, reason=CONFLICT, paths=merged.conflicts
                )
                skipped.append(skip)
                continue
            if merged.tree == tree:
                skipped.append(
                    CombineSkip(trial_id=change.trial_id, reason=NOTHING_LEFT)
                )
                continue
            message = (
                f"aip: apply trial {change.trial_id}\n\n"
                f"Engine-Trial: {change.trial_id}\n"
                f"Engine-Hypothesis: {change.hypothesis_id}\n"
            )
            acc = git.commit_tree(merged.tree, acc, message, base=base)
            tree = merged.tree
            applied.append(change.trial_id)
        return acc, applied, tuple(skipped)

    def _measure(
        self,
        a: Phase,
        b: Phase,
        project: Project,
        workloads: Sequence[Workload],
        baseline_count: int | None,
    ) -> tuple[tuple[Measurement, ...], tuple[Measurement, ...]]:
        """A rows, then B rows plus ``tests_passed``; no rows on ``RunFailure``."""
        notes: list[str] = []
        baseline: list[Measurement] = []
        combined: list[Measurement] = []
        try:
            for workload in workloads:
                abab = measure_abab(a, b, workload)
                notes.extend(abab.notes)
                baseline.extend(abab.a)
                combined.extend(abab.b)
            tests = run_tests(b, project, workloads, baseline_count=baseline_count)
            notes.extend(tests.notes)
            combined.extend(tests.measurements)
        except RunFailure as failure:
            notes.extend(failure.notes)
            notes.append(f"the combination was not re-tested: {failure.reason}")
            baseline, combined = [], []
        self._notes = tuple(dict.fromkeys(notes))
        return tuple(baseline), tuple(combined)


def _resolves_to(git: GitWorkspace, rev: str) -> str | None:
    try:
        return git.resolve_commit(rev)
    except (GitError, ValueError):  # ValueError: not a revision at all
        return None


def _unfit(git: GitWorkspace, base: str, commit: str) -> str | None:
    """Why ``commit`` cannot be merged as one trial's own diff, or ``None``."""
    if _OID.fullmatch(commit) is None or _resolves_to(git, commit) != commit:
        return NOT_A_COMMIT
    if _resolves_to(git, commit + "^") != base or _resolves_to(git, commit + "^2"):
        return NOT_A_CHILD
    return None


class GitBranchPublisher:
    """The real ``BranchPublisher``; ``git`` defaults to the project's, and
    ``prefix`` (the engine branch prefix, default the setting's) bounds what
    it may create."""

    def __init__(
        self, *, git: GitWorkspace | None = None, prefix: str | None = None
    ) -> None:
        self._git = git
        self._prefix = settings.TRIAL_BRANCH_PREFIX if prefix is None else prefix
        problem = branch_prefix_problem(self._prefix)
        if problem is not None:
            raise ValueError(f"branch prefix {_quote(self._prefix)!r} {problem}")

    def publish(self, project: Project, branch: str, tip: str, base: str) -> str:
        """Create ``branch`` at ``tip`` (create-only); the capped base..tip diff."""
        assert_safe_branch(branch, project, self._prefix)
        git = self._git or GitWorkspace(Path(project.root_path))
        for what, value in (("tip", tip), ("base", base)):
            if _OID.fullmatch(value) is None or _resolves_to(git, value) != value:
                raise DeliveryError(f"{what} {_quote(value)!r} is not a commit id")
        if not git.is_ancestor(base, tip):
            raise DeliveryError(
                f"the tip {tip} does not descend from the base {base}: its diff"
                " would not be the delivered change"
            )
        ref = "refs/heads/" + branch
        if ref.casefold() in {b.casefold() for b in git.checked_out_branches()}:
            raise DeliveryError(
                f"refusing to write branch {branch!r}: it is checked out in a worktree"
            )
        current = git.ref_value(ref)
        if current not in (None, tip):
            raise _exists(branch, current, tip)
        default = "refs/heads/" + project.default_branch
        if current is None:
            _refuse_symref(git, ref, default)
        diff = git.diff_commits(base, tip, max_bytes=settings.MAX_DIFF_BYTES)
        if current is None:
            was = _resolves_to(git, default)
            try:
                git.update_ref(ref, tip, None, prefix=self._prefix)
            except GitError as error:
                current = git.ref_value(ref)  # a racing writer, or none
                if current is None:
                    raise DeliveryError(
                        f"branch {branch!r} could not be created: {error}"
                    ) from error
                if current != tip:
                    raise _exists(branch, current, tip) from error
            else:
                if was != tip and _resolves_to(git, default) == tip:
                    _undo(git, ref, tip, project.default_branch, self._prefix)
        return diff


def _exists(branch: str, current: str | None, tip: str) -> DeliveryError:
    return DeliveryError(
        f"branch {branch!r} already exists at {current}, not at the tip {tip};"
        " the engine never moves an existing branch"
    )


def _symref_problem(default: str, ref: str) -> str:
    return f"the default branch {default!r} is a symbolic ref to {ref!r}"


def _refuse_symref(git: GitWorkspace, ref: str, default_ref: str) -> None:
    """Creating ``ref`` must not move the default branch: refuse when it is a
    symref (through any chain, in any case) to ``ref``, or one git cannot
    resolve (a chain deeper than git follows). A default name the engine
    cannot validate, and a loose ref file that is a filesystem link (git's
    legacy symref, invisible to ``symbolic-ref``), are left to the check
    after the create."""
    default = default_ref.removeprefix("refs/heads/")
    try:
        target = git.symbolic_ref(default_ref)
    except ValueError:
        return
    except GitError as error:
        raise DeliveryError(
            f"the default branch {default!r} could not be resolved, so creating"
            f" {ref!r} might move it: {error}"
        ) from error
    if target is not None and target.casefold() == ref.casefold():
        raise DeliveryError(
            f"{_symref_problem(default, target)}: creating it would move the"
            " default branch"
        )


def _undo(git: GitWorkspace, ref: str, tip: str, default: str, prefix: str) -> None:
    """``default`` moved with ``ref``: a symref to it. Delete ``ref`` again."""
    problem = f"{_symref_problem(default, ref)}: creating it moved the default branch"
    try:
        git.delete_ref(ref, tip, prefix=prefix)
    except GitError as error:
        message = f"{problem}, and the branch could not be undone: {error}"
        raise DeliveryError(message) from error
    raise DeliveryError(f"{problem}; it was deleted again")
