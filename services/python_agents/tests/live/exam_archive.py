"""UEX (O71 item 4): the archive of the four retired practical papers.

The engine sits the papers as one X2 run each (``exam_sitting``), on a
GitHub runner, so the papers travel as one committed, gzip-compressed tar
beside a JSON manifest under ``emergence/round-3/`` (``ARCHIVE``,
``MANIFEST``); the key never does: ``collect`` takes ``tier-1`` to
``tier-4`` of a ``practical`` papers folder and nothing else.

- ``build``: the Lead's script (``python -m live.exam_archive PRACTICAL OUT
  --seal SHA``). First the papers folder (``PRACTICAL``'s parent) is hashed
  by the seal's own recipe (``seal_tree_sha256``) and refused unless it is
  the caller's ``SHA`` (the seal's first-sitting papers hash); the manifest
  records it as ``seal_tree_sha256``. Then
  Every regular file of each tier except the students' brief
  (``EXCLUDED``), refusing a link, an unsafe name or a missing tier, packed
  reproducibly (sorted, mode 0644 or 0755, owner 0, mtime 0, gzip mtime 0),
  so the same papers always give the same sha256; then the archive is
  unpacked again into a scratch folder and each tier initialised there
  (``init_paper``) exactly as the job will, which gives the manifest its
  fixed commits.
- ``check_archive``: the archive's bytes against the manifest's sha256,
  before anything is opened (a wrong hash fails before any request).
- ``unpack``: ``check_archive`` first, then each member checked as it is
  written (a plain path under its tier, a regular file or a folder, listed in
  the manifest with that sha256), and the set exactly the manifest's.
- ``init_paper``: a tier as a git repository on ``main`` with one commit
  of the fixed benchmark identity and date (``oss.git_env``) and the tag
  ``pN``, its tracked files exactly the manifest's; refused unless the
  commit is the manifest's.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from autonomous_ai_agents.common.paths import PathTraversalError, normalize_path

from . import oss
from .conftest import TESTS_DIR

REPO_ROOT: Final = TESTS_DIR.parents[2]
EXAM_DIR: Final = REPO_ROOT / ".claude/handoff/step3/idea-lab/emergence/round-3"
ARCHIVE_NAME: Final = "exam-papers.tar.gz"
MANIFEST_NAME: Final = "exam-papers.manifest.json"
ARCHIVE: Final = EXAM_DIR / ARCHIVE_NAME
MANIFEST: Final = EXAM_DIR / MANIFEST_NAME
TIERS: Final = ("tier-1", "tier-2", "tier-3", "tier-4")
IMPORT_MESSAGE: Final = "initial import"  # the commit the engine's clone shows
EXCLUDED: Final = frozenset({"TASK.md"})  # the students' brief, never the engine's
SKIPPED_DIRS: Final = frozenset({"__pycache__", ".pytest_cache", ".benchmarks"})
MAX_ARCHIVE_BYTES: Final = 64 * 1024 * 1024
MAX_FILE_BYTES: Final = 16 * 1024 * 1024
MAX_FILES: Final = 8000
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_COMMIT: Final = re.compile(r"[0-9a-f]{40}")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f\\]")


class ExamIntegrityError(ValueError):
    """An archive, manifest or tree that is not the papers the manifest names."""


@dataclass(frozen=True)
class Paper:
    """One tier of the manifest: its fixed commit and its files' sha256."""

    commit: str
    files: Mapping[str, str]


@dataclass(frozen=True)
class Manifest:
    archive: str
    sha256: str
    papers: Mapping[str, Paper]
    seal: str = ""  # seal_tree_sha256 of the papers folder the archive was packed from

    def members(self) -> dict[str, str]:
        """Every file of the archive, ``tier/path``, and its sha256."""
        return {f"{t}/{p}": h for t, paper in self.papers.items()
                for p, h in paper.files.items()}  # fmt: skip


def tag(tier: str) -> str:
    """The tag ``init_paper`` puts on a tier's commit: ``p1`` for ``tier-1``
    (neutral: the engine's clone carries the commit, never this name)."""
    return f"p{tier.removeprefix('tier-')}"


def safe_rel(path: str) -> str:
    """``path`` when it is a plain relative POSIX path (no control character,
    backslash, ``..``, absolute or ``.git`` part), else ``ExamIntegrityError``."""
    try:
        clean = normalize_path(path)
    except PathTraversalError as exc:
        raise ExamIntegrityError(str(exc)) from None
    parts = clean.split("/")
    if (clean != path or _CONTROL.search(path) or ".git" in parts
            or any(p in ("", ".") for p in parts)):  # fmt: skip
        raise ExamIntegrityError(f"not a plain relative path: {path[:120]!r}")
    return clean


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The Lead's side: collect, pack, commit, manifest
# ---------------------------------------------------------------------------


def seal_tree_sha256(papers: Path) -> str:
    """The seal's tree hash of the folder ``papers`` (exam-seal.md, verified
    by the Lead): from inside it, ``find . -path ./resit -prune -o -type f
    -print0 | LC_ALL=C sort -z | xargs -0 sha256sum``, i.e. one line
    ``<sha256>  ./<path>`` per regular file outside the top ``resit``, sorted
    by path bytewise, hashed whole with its trailing newline. A name
    ``sha256sum`` would escape (a backslash or a newline) is refused."""
    lines: list[tuple[bytes, str]] = []
    for folder, dirs, names in os.walk(papers):
        here = Path(folder)
        if here == papers:
            dirs[:] = [d for d in dirs if d != "resit"]
        for name in names:
            path = here / name
            if path.is_symlink() or not path.is_file():
                continue  # find -type f: links and specials are not listed
            rel = "./" + path.relative_to(papers).as_posix()
            if "\\" in rel or "\n" in rel:
                raise ExamIntegrityError(
                    f"{rel[:120]!r}: sha256sum would escape its name"
                )
            lines.append((os.fsencode(rel), f"{_sha256(path.read_bytes())}  {rel}\n"))
    text = "".join(line for _, line in sorted(lines))
    return _sha256(os.fsencode(text))


def collect(practical: Path) -> dict[str, dict[str, Path]]:
    """Per tier, its files by relative path: links, missing tiers and unsafe
    names refused, ``EXCLUDED`` at a tier's top and ``SKIPPED_DIRS`` left out."""
    found: dict[str, dict[str, Path]] = {}
    for tier in TIERS:
        top = practical / tier
        if top.is_symlink() or not top.is_dir():
            raise ExamIntegrityError(f"{tier}: not a folder of {practical}")
        files: dict[str, Path] = {}
        for folder, dirs, names in os.walk(top):
            here = Path(folder)
            for name in sorted(dirs):
                if (here / name).is_symlink():
                    raise ExamIntegrityError(f"{tier}: {name} is a link")
            dirs[:] = sorted(d for d in dirs if d not in SKIPPED_DIRS)
            for name in sorted(names):
                path = here / name
                rel = safe_rel(path.relative_to(top).as_posix())
                if path.is_symlink() or not path.is_file():
                    raise ExamIntegrityError(f"{tier}/{rel}: not a regular file")
                if rel in EXCLUDED or name.endswith(".pyc"):
                    continue
                files[rel] = path
        if not files:
            raise ExamIntegrityError(f"{tier}: no files")
        found[tier] = files
    return found


def _info(name: str, size: int, *, folder: bool = False,
          executable: bool = False) -> tarfile.TarInfo:  # fmt: skip
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.uid, info.gid = size, 0, 0, 0
    info.uname = info.gname = ""
    info.type = tarfile.DIRTYPE if folder else tarfile.REGTYPE
    info.mode = 0o755 if folder or executable else 0o644
    return info


def pack(found: Mapping[str, Mapping[str, Path]]) -> bytes:
    """The reproducible ``tar.gz`` of ``found``: sorted members, fixed metadata."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for tier in sorted(found):
            tar.addfile(_info(tier, 0, folder=True))
            for rel in sorted(found[tier]):
                path = found[tier][rel]
                data = path.read_bytes()
                tar.addfile(_info(f"{tier}/{rel}", len(data),
                                  executable=os.access(path, os.X_OK)),
                            io.BytesIO(data))  # fmt: skip
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def build(practical: Path, out: Path, *, seal: str,
          policy: oss.GitPolicy = oss.PRODUCTION,
          environ: Mapping[str, str] | None = None) -> Manifest:  # fmt: skip
    """Write ``ARCHIVE_NAME`` and ``MANIFEST_NAME`` to the folder ``out``:
    refused, before anything is packed or written, unless the papers folder
    (``practical``'s parent) has the seal's tree hash ``seal``; then the
    papers packed, unpacked and initialised as the job will."""
    found_seal = seal_tree_sha256(practical.parent)
    if found_seal != seal:
        raise ExamIntegrityError(
            f"{practical.parent.name}: seal tree hash {found_seal} is not the seal's {seal}"
        )
    found = collect(practical)
    data = pack(found)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ExamIntegrityError(
            f"the archive is {len(data)} bytes, over {MAX_ARCHIVE_BYTES}"
        )
    files = {
        t: {r: _sha256(p.read_bytes()) for r, p in fs.items()}
        for t, fs in found.items()
    }
    draft = Manifest(ARCHIVE_NAME, _sha256(data),
                     {t: Paper("0" * 40, files[t]) for t in TIERS})  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    (out / ARCHIVE_NAME).write_bytes(data)
    scratch = Path(tempfile.mkdtemp(prefix="exam-archive-"))
    try:
        trees = unpack(out / ARCHIVE_NAME, draft, scratch / "papers")
        commits = {t: init_paper(trees[t], t, None, draft.papers[t].files,
                                 policy=policy, environ=environ) for t in TIERS}  # fmt: skip
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    manifest = Manifest(ARCHIVE_NAME, draft.sha256,
                        {t: Paper(commits[t], files[t]) for t in TIERS}, seal)  # fmt: skip
    (out / MANIFEST_NAME).write_text(dump_manifest(manifest), encoding="utf-8")
    return manifest


def dump_manifest(manifest: Manifest) -> str:
    body = {"archive": manifest.archive, "sha256": manifest.sha256,
            "excluded": sorted(EXCLUDED), "seal_tree_sha256": manifest.seal,
            "papers": {t: {"commit": p.commit, "tag": tag(t), "files": dict(sorted(p.files.items()))}
                       for t, p in manifest.papers.items()}}  # fmt: skip
    return json.dumps(body, indent=1, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# The job's side: manifest, hash, unpack, initialise
# ---------------------------------------------------------------------------


def _pattern(value: object, pattern: re.Pattern[str], what: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ExamIntegrityError(f"manifest {what}: not {pattern.pattern}")
    return value


def parse_manifest(data: object) -> Manifest:
    """The manifest, strictly: the four tiers, their commits and files."""
    keys = {"archive", "sha256", "excluded", "papers", "seal_tree_sha256"}
    if (
        not isinstance(data, dict)
        or set(data) != keys
        or data["archive"] != ARCHIVE_NAME
    ):
        raise ExamIntegrityError(
            f"manifest: expected exactly {sorted(keys)} for {ARCHIVE_NAME}"
        )
    if data["excluded"] != sorted(EXCLUDED):
        raise ExamIntegrityError(f"manifest excluded: expected {sorted(EXCLUDED)}")
    papers = data["papers"]
    if not isinstance(papers, dict) or sorted(papers) != list(TIERS):
        raise ExamIntegrityError(f"manifest papers: expected exactly {list(TIERS)}")
    out: dict[str, Paper] = {}
    for tier in TIERS:
        body = papers[tier]
        if not isinstance(body, dict) or set(body) != {"commit", "tag", "files"} \
                or body["tag"] != tag(tier):  # fmt: skip
            raise ExamIntegrityError(
                f"manifest {tier}: expected commit, tag {tag(tier)}, files"
            )
        files = body["files"]
        if not isinstance(files, dict) or not 0 < len(files) <= MAX_FILES:
            raise ExamIntegrityError(f"manifest {tier}.files: 1 to {MAX_FILES} files")
        out[tier] = Paper(_pattern(body["commit"], _COMMIT, f"{tier}.commit"),
                          {safe_rel(str(k)): _pattern(v, _SHA256, f"{tier}.files")
                           for k, v in files.items()})  # fmt: skip
    return Manifest(ARCHIVE_NAME, _pattern(data["sha256"], _SHA256, "sha256"), out,
                    _pattern(data["seal_tree_sha256"], _SHA256, "seal_tree_sha256"))  # fmt: skip


def load_manifest(path: Path = MANIFEST) -> Manifest:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExamIntegrityError(
            f"manifest {path.name}: {type(exc).__name__}"
        ) from None
    return parse_manifest(data)


def check_archive(archive: Path, manifest: Manifest) -> bytes:
    """The archive's bytes, refused unless their sha256 is the manifest's."""
    if archive.is_symlink() or not archive.is_file():
        raise ExamIntegrityError(f"{archive.name}: not a regular file")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ExamIntegrityError(f"{archive.name}: over {MAX_ARCHIVE_BYTES} bytes")
    data = archive.read_bytes()
    if _sha256(data) != manifest.sha256:
        raise ExamIntegrityError(
            f"{archive.name}: sha256 {_sha256(data)} is not the manifest's {manifest.sha256}"
        )
    return data


def unpack(archive: Path, manifest: Manifest, dest: Path) -> dict[str, Path]:
    """The archive checked (``check_archive``), then written under the new
    folder ``dest``, each member checked; each tier's folder."""
    data = check_archive(archive, manifest)
    if dest.resolve().is_relative_to(REPO_ROOT.resolve()):
        raise ExamIntegrityError(
            f"{dest}: the papers never unpack inside the repository"
        )
    dest.mkdir(parents=True)
    wanted, seen = manifest.members(), set()
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar:
                name = safe_rel(member.name)
                if member.isdir() and name in manifest.papers:
                    continue
                if not member.isreg() or name not in wanted or name in seen:
                    raise ExamIntegrityError(
                        f"{name[:120]}: not a file the manifest lists once"
                    )
                if member.size > MAX_FILE_BYTES:
                    raise ExamIntegrityError(
                        f"{name[:120]}: over {MAX_FILE_BYTES} bytes"
                    )
                handle = tar.extractfile(member)
                body = b"" if handle is None else handle.read()
                if _sha256(body) != wanted[name]:
                    raise ExamIntegrityError(
                        f"{name[:120]}: sha256 is not the manifest's"
                    )
                target = dest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "xb") as out:  # never over an existing file
                    out.write(body)
                target.chmod(0o755 if member.mode & 0o100 else 0o644)
                seen.add(name)
    except tarfile.TarError as exc:
        raise ExamIntegrityError(f"{archive.name}: {type(exc).__name__}") from None
    if seen != set(wanted):
        raise ExamIntegrityError(f"{len(set(wanted) - seen)} manifest file(s) missing")
    return {tier: dest / tier for tier in manifest.papers}


def init_paper(tree: Path, tier: str, commit: str | None, files: Mapping[str, str], *,
               policy: oss.GitPolicy = oss.PRODUCTION,
               environ: Mapping[str, str] | None = None) -> str:  # fmt: skip
    """``tree`` as a repository on ``main``: one commit of every file, the
    fixed identity and date, tagged ``tag(tier)``; its tracked files exactly
    ``files``; the commit, refused unless it is ``commit`` (``None``: any)."""
    with oss._scratch_git(tree, policy, environ) as git:
        git("init", "-q", "-b", "main")
        git("add", "-A", "-f", "--", ".")
        git("commit", "-q", "--no-verify", "-m", IMPORT_MESSAGE)
        head = git("rev-parse", "--verify", "HEAD^{commit}")
        listed = git("ls-files", "-z").split("\0")
        git("tag", tag(tier), head)
    if set(filter(None, listed)) != set(files):
        raise ExamIntegrityError(
            f"{tier}: the commit does not track exactly the manifest's files"
        )
    if commit is not None and head != commit:
        raise ExamIntegrityError(
            f"{tier}: commit {head} is not the manifest's {commit}"
        )
    return head


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pack the four practical papers.")
    parser.add_argument("practical", type=Path, help="the papers/practical folder")
    parser.add_argument("out", type=Path, nargs="?", default=EXAM_DIR)
    parser.add_argument("--seal", required=True,
                        help="the seal's papers tree hash (exam-seal.md, first sitting)")  # fmt: skip
    args = parser.parse_args(argv)
    manifest = build(args.practical, args.out, seal=args.seal)
    print(f"seal tree hash {manifest.seal}: as the seal's")
    print(f"wrote {args.out / ARCHIVE_NAME} sha256 {manifest.sha256}")
    for tier, paper in manifest.papers.items():
        print(
            f"{tier}: {len(paper.files)} files, commit {paper.commit}, tag {tag(tier)}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - the Lead's command line
    sys.exit(main())
