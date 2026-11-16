"""UEX (O71 item 4) guards: the paper archive, the paper target, the arm,
the cap arithmetic and the isolation of the sitting, offline.

- **Archive** (``exam_archive``): built twice from a fixture tree it is
  byte-identical, holds no ``TASK.md``, and its manifest names each tier's
  fixed commit; a wrong sha256 fails before the archive is opened; a member
  off the manifest, a missing one, a link or a wrong file hash is refused;
  nothing unpacks inside the repository.
- **Target** (``exam_sitting``): a paper resolves, unpacks and initialises
  offline, and ``ideas_x2.start_x2_loop`` takes it unchanged over the
  sitting's ``file://`` policy: the wrapper committed as the protected bench,
  the paper's test command, the arm's settings in the engine, an empty
  in-memory lessons store. Each wrapper prints one deterministic line that
  moves with the bench's data and with the library's outputs.
- **Arm**: X2-0's mapping plus ``SITE_STACKS="on"``, nothing else.
- **Cap**: ``ideas_x2.run_cap``'s share term (6.50); no archived X2-0 run
  came near it or would have had its seeded call refused under it; the
  owner's 14.50 USD (O72 item 1) sits all four papers at the archive's
  dearest spends, where O71's 12 sat three.
- **Isolation**: no archive reader globs the sitting's rows folder, or the
  papers' archive; ``sit_one`` makes ``run_one``'s calls in its order.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import pytest
from e2e.conftest import UNTOUCHED_REFS, Isolation

from autonomous_ai_agents.common.config import Settings, settings
from autonomous_ai_agents.execution.sandbox import PASS_THROUGH, child_env
from autonomous_ai_agents.optimization.idea_pipeline import IdeaPipelineGenerator
from autonomous_ai_agents.optimization.judges import OpCountJudge
from autonomous_ai_agents.orchestrator.main import EngineRunResult
from autonomous_ai_agents.persistence.repository import InMemoryRepository

from . import discovery, oss
from . import exam_archive as ea
from . import exam_sitting as ex
from . import ideas_x2 as x2
from . import order_cases as oc
from . import test_ideas_x2_guards as xg
from .conftest import SUITE_CAP_ENV, TESTS_DIR, LiveRun, StartLive, restore_host_key
from .corpus import RESULTS_ENV
from .discovery_io import ResultsSink

REQUIRED = Isolation("required", None)
LIVE = TESTS_DIR / "live"
FRESH = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}  # an edit in the same second
SPRINT_LIVE = ea.REPO_ROOT / ".claude/handoff/step3/idea-lab/w2-sprint/live"

# ---------------------------------------------------------------------------
# A practical folder of four tiny papers, each the shape of the real one
# ---------------------------------------------------------------------------

_LOAD_DIR = """\
def _read():
    d = os.path.join(HERE, "bench_data")
    return {n: open(os.path.join(d, n), encoding="utf-8").read()
            for n in sorted(os.listdir(d))}
"""
PAPERS: Mapping[str, Mapping[str, str]] = {
    "tier-1": {
        "src/tomli/__init__.py": "def loads(text):\n    return {'n': len(text), 'head': text[:4]}\n",
        "bench.py": (
            "import os, sys, time\nHERE = os.path.dirname(os.path.abspath(__file__))\n"
            "sys.path.insert(0, os.path.join(HERE, 'src'))\nimport tomli\n"
            + _LOAD_DIR
            + "load_documents = _read\n"
            "def main():\n    [tomli.loads(t) for t in load_documents().values()]\n"
            "    print(time.perf_counter())\n"
        ),
        "bench_data/a.toml": "a = 1\n",
    },
    "tier-2": {
        "sqlparse/__init__.py": textwrap.dedent("""\
            class Token:
                is_group = False
                ttype = 'Word'
                def __init__(self, value):
                    self.value = value
            class Statement:
                is_group = True
                ttype = None
                def __init__(self, text):
                    self.tokens = [Token(w) for w in text.split()]
                def get_type(self):
                    return self.tokens[0].value.upper()
            def split(text):
                return [s.strip() for s in text.split(';') if s.strip()]
            def parse(text):
                return [Statement(text)]
            def format(text, reindent=False, keyword_case=None):
                return text.upper()
            """),
        "bench.py": (
            "import os, sys, time\nHERE = os.path.dirname(os.path.abspath(__file__))\n"
            "sys.path.insert(0, HERE)\nimport sqlparse\n"
            + _LOAD_DIR
            + "def load():\n    d = _read()\n    return d['dump.sql'], d['queries.sql'].split()\n"
            "def main():\n    dump, q = load()\n    sqlparse.split(dump)\n"
            "    print(time.perf_counter())\n"
        ),
        "bench_data/dump.sql": "select 1; insert x;\n",
        "bench_data/queries.sql": "select\nupdate\n",
    },
    "tier-3": {
        "src/mistune/__init__.py": (
            "def html(text):\n    return '<p>' + text + '</p>'\n"
            "def create_markdown(plugins=()):\n"
            "    return lambda text: ','.join(plugins) + text\n"
        ),
        "bench.py": (
            "import os, sys, time\nHERE = os.path.dirname(os.path.abspath(__file__))\n"
            "sys.path.insert(0, os.path.join(HERE, 'src'))\nimport mistune\n"
            + _LOAD_DIR
            + "PLUGINS = ['table']\nload_documents = _read\n"
            "def main():\n    [mistune.html(t) for t in load_documents().values()]\n"
            "    print(time.perf_counter())\n"
        ),
        "bench_data/GUIDE.md": "# hi\n",
        "pyproject.toml": "[tool.pytest.ini_options]\npythonpath = ['src', '.']\n",
    },
    "tier-4": {
        "markdown/__init__.py": textwrap.dedent("""\
            class Markdown:
                def __init__(self, extensions=(), extension_configs=None):
                    self.ext = list(extensions)
                    self.reset()
                def reset(self):
                    self.toc, self.Meta = '', {}
                def convert(self, text):
                    self.toc, self.Meta = '<toc>' + text[:2], {'title': [text[:3]]}
                    return '<p>' + text + '</p>' + ','.join(self.ext)
            """),
        "bench.py": (
            "import os, sys, time\nHERE = os.path.dirname(os.path.abspath(__file__))\n"
            "sys.path.insert(0, HERE)\nimport markdown\n"
            + _LOAD_DIR
            + "EXTENSIONS = ['toc']\nEXTENSION_CONFIGS = {'toc': {}}\nload_pages = _read\n"
            "def main():\n    md = markdown.Markdown(extensions=EXTENSIONS)\n"
            "    [md.convert(t) for t in load_pages().values()]\n"
            "    print(time.perf_counter())\n"
        ),
        "bench_data/page000.md": "Page one\n",
        "LICENSE.md": "BSD\n",
    },
}
MUTATIONS: Mapping[str, tuple[str, str]] = {  # one changed output per library
    "tier-1": ("'head'", "'Head'"), "tier-2": (".value.upper()", ".value.lower()"),
    "tier-3": ("'<p>'", "'<P>'"), "tier-4": ("'<p>'", "'<P>'"),
}  # fmt: skip
COMMON: Mapping[str, str] = {
    "LICENSE": "Permission is hereby granted\n",
    "TASK.md": "the students' brief: never in the archive\n",
    "tests/__init__.py": "",
    "tests/test_it.py": "def test_it():\n    assert True\n",
    "tests/data/with space (1).txt": "names like the real papers'\n",
}


def _write(root: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


@pytest.fixture
def practical(tmp_path: Path) -> Path:
    """``papers/practical`` beside a re-sit (outside the seal's hash) and a
    speciality paper (inside it), as the real papers folder is laid out."""
    top = tmp_path / "papers" / "practical"
    for tier, files in PAPERS.items():
        _write(top / tier, {**COMMON, **files})
        _write(top / tier / "src" / "__pycache__", {"x.cpython-311.pyc": "cache"})
    _write(tmp_path / "papers" / "resit" / "tier-1", {"bench.py": "the re-sit\n"})
    _write(tmp_path / "papers" / "speciality", {"s1.md": "three questions\n"})
    return top


def _seal(papers: Path) -> str:
    """The seal's recipe exactly as the Lead runs it (exam-seal.md)."""
    recipe = ("find . -path ./resit -prune -o -type f -print0 | LC_ALL=C sort -z"
              " | xargs -0 sha256sum | sha256sum")  # fmt: skip
    done = subprocess.run(["bash", "-c", recipe], cwd=papers, capture_output=True,
                          text=True, check=True)  # fmt: skip
    return done.stdout.split()[0]


@pytest.fixture
def built(practical: Path, tmp_path: Path) -> tuple[Path, ea.Manifest]:
    out = tmp_path / "out"
    return out, ea.build(practical, out, seal=_seal(practical.parent))


# ---------------------------------------------------------------------------
# The archive
# ---------------------------------------------------------------------------


def test_the_archive_is_reproducible_and_holds_no_brief(
    practical: Path, built: tuple[Path, ea.Manifest], tmp_path: Path
) -> None:
    out, manifest = built
    again = ea.build(practical, tmp_path / "again", seal=manifest.seal)
    data = (out / ea.ARCHIVE_NAME).read_bytes()
    assert data == (tmp_path / "again" / ea.ARCHIVE_NAME).read_bytes()
    assert again == manifest and ea.load_manifest(out / ea.MANIFEST_NAME) == manifest
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = tar.getnames()
        assert {m.mtime for m in tar} == {0} and {m.uid for m in tar} == {0}
    assert not any(n.endswith(("TASK.md", ".pyc")) for n in names)
    assert set(names) == {*ea.TIERS, *manifest.members()}
    assert "tier-1/tests/data/with space (1).txt" in names
    for tier, paper in manifest.papers.items():
        assert len(paper.commit) == 40 and "TASK.md" not in paper.files
        assert paper.files["bench.py"] == ea._sha256(
            (practical / tier / "bench.py").read_bytes()
        )
    body = json.loads((out / ea.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert body["excluded"] == ["TASK.md"] and body["papers"]["tier-3"]["tag"] == "p3"
    assert body["seal_tree_sha256"] == manifest.seal == _seal(practical.parent)


def test_the_seal_hash_is_the_seals_recipe_and_refuses_before_packing(
    practical: Path, tmp_path: Path
) -> None:
    """``seal_tree_sha256`` is the shell recipe's value: the top ``resit``
    pruned, a speciality paper and the brief counted, a link skipped as
    ``find -type f`` skips it; a papers folder off the seal is refused
    before anything is written."""
    papers = practical.parent
    seal = ea.seal_tree_sha256(papers)
    assert seal == _seal(papers)
    _write(papers / "resit" / "tier-2", {"x.py": "more re-sit\n"})
    (papers / "speciality" / "link.md").symlink_to(papers / "speciality" / "s1.md")
    assert ea.seal_tree_sha256(papers) == seal == _seal(papers)
    _write(papers / "speciality", {"s1.md": "changed\n"})
    moved = ea.seal_tree_sha256(papers)
    assert moved != seal and moved == _seal(papers)
    with pytest.raises(ea.ExamIntegrityError, match=f"is not the seal's {seal}"):
        ea.build(practical, tmp_path / "refused", seal=seal)
    assert not (tmp_path / "refused").exists()
    _write(papers / "speciality", {"back\\slash.md": "x"})
    with pytest.raises(ea.ExamIntegrityError, match="would escape its name"):
        ea.seal_tree_sha256(papers)


def test_the_script_prints_what_it_wrote(practical: Path, tmp_path: Path,
                                         capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    seal = _seal(practical.parent)
    assert ea.main([str(practical), str(tmp_path / "cli"), "--seal", seal]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"seal tree hash {seal}: as the seal's"
    assert lines[1].startswith(f"wrote {tmp_path / 'cli' / ea.ARCHIVE_NAME} sha256 ")
    assert [line.split(":")[0] for line in lines[2:]] == list(ea.TIERS)
    with pytest.raises(SystemExit):  # --seal is required
        ea.main([str(practical), str(tmp_path / "cli2")])


def test_a_wrong_hash_fails_before_the_archive_is_opened(
    built: tuple[Path, ea.Manifest], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out, manifest = built
    wrong = dataclasses.replace(manifest, sha256="0" * 64)

    def never(*args: object, **kwargs: object) -> None:
        raise AssertionError("the archive was opened before its hash was checked")

    monkeypatch.setattr(tarfile, "open", never)
    with pytest.raises(ea.ExamIntegrityError, match="is not the manifest's 0000"):
        ea.unpack(out / ea.ARCHIVE_NAME, wrong, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
    (out / ea.MANIFEST_NAME).write_text(ea.dump_manifest(wrong), encoding="utf-8")
    with pytest.raises(
        ea.ExamIntegrityError, match="is not the manifest.s 0000"
    ):  # before any request
        ex.prepare_papers(tmp_path / "root", archive=out / ea.ARCHIVE_NAME,
                          manifest=out / ea.MANIFEST_NAME, pins=_pins(wrong))  # fmt: skip
    assert not (tmp_path / "root" / "papers").exists()


def _repack(manifest: ea.Manifest, members: Mapping[str, bytes],
            links: Mapping[str, str] | None = None,
            twice: str | None = None) -> tuple[bytes, ea.Manifest]:  # fmt: skip
    raw = io.BytesIO()
    listed = [*members.items(), *([] if twice is None else [(twice, members[twice])])]
    with tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for name, body in listed:
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type, info.linkname = tarfile.SYMTYPE, target
            tar.addfile(info)
    data = raw.getvalue()
    return data, dataclasses.replace(manifest, sha256=ea._sha256(data))


@pytest.mark.parametrize(
    "case", ["extra", "missing", "link", "body", "traversal", "twice"]
)
def test_unpack_refuses_what_the_manifest_does_not_list(
    built: tuple[Path, ea.Manifest], tmp_path: Path, case: str
) -> None:
    out, manifest = built
    with tarfile.open(out / ea.ARCHIVE_NAME, mode="r:gz") as tar:
        members = {
            m.name: cast(Any, tar.extractfile(m)).read() for m in tar if m.isreg()
        }
    first = sorted(members)[0]
    links: dict[str, str] = {}
    if case == "extra":
        members["tier-1/extra.py"] = b"x"
    elif case == "missing":
        del members[first]
    elif case == "link":
        links[first] = "/etc/passwd"
        del members[first]
    elif case == "body":
        members[first] = b"changed"
    elif case == "traversal":
        members["tier-1/../escape.py"] = b"x"
    data, fake = _repack(manifest, members, links, first if case == "twice" else None)
    archive = tmp_path / ea.ARCHIVE_NAME
    archive.write_bytes(data)
    with pytest.raises(ea.ExamIntegrityError):
        ea.unpack(archive, fake, tmp_path / "dest")
    assert not (tmp_path / "escape.py").exists()


def test_unpack_refuses_the_repository_a_link_and_a_bad_archive(
    built: tuple[Path, ea.Manifest], tmp_path: Path
) -> None:
    out, manifest = built
    archive = out / ea.ARCHIVE_NAME
    with pytest.raises(ea.ExamIntegrityError, match="inside the repository"):
        ea.unpack(archive, manifest, ea.REPO_ROOT / "services" / "papers-here")
    assert not (ea.REPO_ROOT / "services" / "papers-here").exists()
    link = tmp_path / "link.tar.gz"
    link.symlink_to(archive)
    with pytest.raises(ea.ExamIntegrityError, match="not a regular file"):
        ea.check_archive(link, manifest)
    junk = tmp_path / "junk.tar.gz"
    junk.write_bytes(b"not a tar")
    with pytest.raises(ea.ExamIntegrityError, match="ReadError"):
        ea.unpack(junk, dataclasses.replace(manifest, sha256=ea._sha256(b"not a tar")), tmp_path / "d")  # fmt: skip


def test_the_caps_on_size_hold(built: tuple[Path, ea.Manifest], tmp_path: Path,
                               monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    out, manifest = built
    archive = out / ea.ARCHIVE_NAME
    monkeypatch.setattr(ea, "MAX_FILE_BYTES", 1)
    with pytest.raises(ea.ExamIntegrityError, match="over 1 bytes"):
        ea.unpack(archive, manifest, tmp_path / "d1")
    monkeypatch.setattr(ea, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(ea.ExamIntegrityError, match="over 1 bytes"):
        ea.check_archive(archive, manifest)


def test_collect_refuses_links_missing_tiers_and_odd_names(
    practical: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ea.ExamIntegrityError, match="tier-1: not a folder"):
        ea.collect(tmp_path)
    (practical / "tier-2" / "linked").symlink_to(practical / "tier-1")
    with pytest.raises(ea.ExamIntegrityError, match="linked is a link"):
        ea.collect(practical)
    (practical / "tier-2" / "linked").unlink()
    (practical / "tier-2" / "bad.py").symlink_to("/etc/passwd")
    with pytest.raises(ea.ExamIntegrityError, match="not a regular file"):
        ea.collect(practical)
    (practical / "tier-2" / "bad.py").unlink()
    (practical / "tier-3" / "tab\tname").write_text("x", encoding="utf-8")
    with pytest.raises(ea.ExamIntegrityError, match="not a plain relative path"):
        ea.collect(practical)
    (practical / "tier-3" / "tab\tname").unlink()
    shutil.rmtree(practical / "tier-4")
    (practical / "tier-4" / "__pycache__").mkdir(parents=True)
    with pytest.raises(ea.ExamIntegrityError, match="tier-4: no files"):
        ea.collect(practical)
    with pytest.raises(ea.ExamIntegrityError, match="must not contain"):
        ea.safe_rel("a/../b")
    monkeypatch.setattr(ea, "MAX_ARCHIVE_BYTES", 1)
    _write(practical / "tier-4", {"x.py": "x"})
    with pytest.raises(ea.ExamIntegrityError, match="over 1"):
        ea.build(practical, tmp_path / "too-big", seal=_seal(practical.parent))


@pytest.mark.parametrize("edit", ["keys", "archive", "excluded", "tiers", "tag",
                                  "commit", "files", "sha", "path", "json", "seal"])  # fmt: skip
def test_the_manifest_is_read_strictly(built: tuple[Path, ea.Manifest], tmp_path: Path,
                                       edit: str) -> None:  # fmt: skip
    out, _ = built
    body = json.loads((out / ea.MANIFEST_NAME).read_text(encoding="utf-8"))
    one = body["papers"]["tier-1"]
    if edit == "keys":
        body["extra"] = 1
    elif edit == "archive":
        body["archive"] = "other.tar.gz"
    elif edit == "excluded":
        body["excluded"] = []
    elif edit == "tiers":
        del body["papers"]["tier-4"]
    elif edit == "tag":
        one["tag"] = "p9"
    elif edit == "commit":
        one["commit"] = "HEAD"
    elif edit == "files":
        one["files"] = {}
    elif edit == "seal":
        body["seal_tree_sha256"] = "none"
    elif edit == "sha":
        one["files"]["bench.py"] = "x"
    elif edit == "path":
        one["files"]["/etc/passwd"] = "0" * 64
    path = tmp_path / "m.json"
    path.write_text("{" if edit == "json" else json.dumps(body), encoding="utf-8")
    with pytest.raises(ea.ExamIntegrityError):
        ea.load_manifest(path)


def test_init_paper_refuses_another_commit_or_other_files(
    built: tuple[Path, ea.Manifest], tmp_path: Path
) -> None:
    out, manifest = built
    trees = ea.unpack(out / ea.ARCHIVE_NAME, manifest, tmp_path / "unpacked")
    paper = manifest.papers["tier-1"]
    with pytest.raises(ea.ExamIntegrityError, match="is not the manifest's"):
        ea.init_paper(trees["tier-1"], "tier-1", "f" * 40, paper.files)
    with pytest.raises(ea.ExamIntegrityError, match="exactly the manifest's files"):
        ea.init_paper(trees["tier-2"], "tier-2", None, paper.files)


# ---------------------------------------------------------------------------
# The paper target
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          check=True).stdout.strip()  # fmt: skip


def _pins(manifest: ea.Manifest) -> ex.Pins:
    return ex.Pins(manifest.sha256, manifest.seal,
                   {t: p.commit for t, p in manifest.papers.items()})  # fmt: skip


Papers = tuple[dict[str, ex.ExamRepo], oss.GitPolicy, Path]


@pytest.fixture
def papers(built: tuple[Path, ea.Manifest], tmp_path: Path) -> Papers:
    out, manifest = built
    root = Path(os.path.realpath(tmp_path)) / "root"
    root.mkdir()
    repos, policy = ex.prepare_papers(root, archive=out / ea.ARCHIVE_NAME,
                                      manifest=out / ea.MANIFEST_NAME,
                                      pins=_pins(manifest))  # fmt: skip
    return repos, policy, root


def test_a_paper_resolves_and_initialises_offline_under_neutral_names(
    papers: Papers, built: tuple[Path, ea.Manifest]
) -> None:
    """Each paper clones at its pinned commit with the wrapper as its bench;
    what the engine sees (its name, bench path and file, commits, refs,
    profile, workload) says nothing of an exam."""
    repos, policy, root = papers
    manifest = built[1]
    heads = ex.expected_heads(repos, root, policy)
    assert list(repos) == ["p1", "p2", "p3", "p4"] == list(heads)
    for paper in ex.EXAM_PAPERS:
        repo, body = repos[paper.name], manifest.papers[paper.tier]
        assert (repo.tag, repo.commit, repo.url) == (
            paper.name, body.commit, f"file://{root / 'papers' / paper.tier}")  # fmt: skip
        user = oss.prepare_repo(repo, root / f"user-{paper.name}", policy=policy)
        assert user.base == heads[paper.name]  # a deterministic workload commit
        assert _git(user.path, "rev-parse", "HEAD^") == body.commit
        assert (
            _git(user.path, "log", "--format=%s").splitlines()[-1] == ea.IMPORT_MESSAGE
        )
        tracked = set(_git(user.path, "ls-files", "-z").split("\0")) - {""}
        assert tracked == {*body.files, f"benchmarks/bench_{paper.name}.py"}
        bench = (user.path / repo.bench_path).read_bytes()
        assert bench == repo.workload_source.read_bytes()
        refs = _git(user.path, "for-each-ref", "--format=%(refname)").splitlines()
        assert set(refs) == {"refs/heads/main", *UNTOUCHED_REFS}  # every X2 clone's
        project = repo.project(user.path)
        work = repo.workload(project)
        assert project.test_command == paper.test_command and project.name == paper.name
        assert work.command == (
            "python",
            f"benchmarks/bench_{paper.name}.py",
            "bench.py",
        )
        seen = " ".join([project.name, work.name, *work.command, repo.profile,
                         _git(user.path, "log", "--format=%s%n%an%n%ae"),
                         bench.decode()]).casefold()  # fmt: skip
        found = re.findall(
            r"\b(?:exams?|sitting|papers?|tiers?|plants?|seats?|marks?)\b", seen
        )
        assert found == [], (paper.name, found)
    assert repos["p3"].test_command[-1] == "tests"  # PYTHONPATH=src: its pyproject
    assert repos["p4"].test_command == ("python", "-m", "unittest", "discover", "tests")


def test_the_policy_clones_the_four_papers_only(papers: Papers) -> None:
    repos, policy, root = papers
    assert policy.protocols == "file" and policy.allow.fullmatch(repos["p2"].url)
    for other in (
        f"file://{root}/papers/tier-5", f"file://{root}/papers/tier-1/../x",
        f"file://{root}/papers/tier-1x", f"file://{root}/papers/tier-1/sub",
        "file:///other/tier-1", f"file:///other{root}/papers/tier-1",
        f"file://{root}/x/papers/tier-1", f"file://{root}/papers/../papers/tier-1",
        f"file://{root.parent}/papers/tier-1", f"https://{root}/papers/tier-1",
        "https://github.com/a/b.git", f"file://{root}/elsewhere",
    ):  # fmt: skip
        assert policy.allow.fullmatch(other) is None, other
    assert oss.PRODUCTION.allow.fullmatch(repos["p1"].url) is None


@pytest.mark.parametrize("paper", ex.EXAM_PAPERS, ids=lambda p: p.key)
def test_each_wrapper_prints_one_line_that_moves_with_inputs_and_outputs(
    papers: Papers, paper: ex.ExamPaper
) -> None:
    repos, policy, root = papers
    repo = repos[paper.name]
    user = oss.prepare_repo(repo, root / f"w-{paper.name}", policy=policy)

    def run(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, *argv], cwd=user.path, capture_output=True,
                              text=True, check=False, timeout=60, env=FRESH)  # fmt: skip

    argv = repo.workload_argv[1:]
    first, second = run(*argv), run(*argv)
    assert first.returncode == 0, first.stderr
    line = first.stdout.strip()
    assert (
        line == second.stdout.strip() and "\n" not in line
    )  # the bench's time discarded
    assert line.startswith(f"{paper.name} inputs=") and " outputs=" in line
    data = sorted((user.path / "bench_data").iterdir())[0]
    data.write_text(data.read_text(encoding="utf-8") + "more\n", encoding="utf-8")
    moved = run(*argv).stdout.strip()
    assert moved.split()[1] != line.split()[1] and moved.split()[2] != line.split()[2]
    data.write_text(data.read_text(encoding="utf-8")[:-5], encoding="utf-8")
    init = user.path / paper.module_root / "__init__.py"
    old, new = MUTATIONS[paper.tier]
    init.write_text(
        init.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8"
    )
    changed = run(*argv).stdout.strip()
    assert (
        changed.split()[1] == line.split()[1] and changed.split()[2] != line.split()[2]
    )
    refused = run(argv[0])
    assert refused.returncode != 0 and "usage" in refused.stderr
    (user.path / "elsewhere").mkdir()
    shutil.copytree(
        user.path / paper.module_root, user.path / "elsewhere" / paper.package
    )
    bench = user.path / "bench.py"
    bench.write_text(bench.read_text(encoding="utf-8").replace(
        "sys.path.insert(0,", "sys.path.insert(0, os.path.join(HERE, 'elsewhere')) or (0,"),
        encoding="utf-8")  # fmt: skip
    copied = run(*argv)
    assert copied.returncode != 0 and "imported from" in copied.stderr


def test_the_x2_loop_takes_a_paper_unchanged_with_an_empty_lessons_store(
    papers: Papers, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``start_x2_loop`` on a paper with the arm's env exported: the
    pipeline on X2-0's lanes, no lessons in its prompts, no views, the
    gain-ordered combine; a fresh in-memory store with no lesson; nothing sent."""
    repos, policy, root = papers
    for key, value in x2.arm_env(ex.X2_EX).items():
        monkeypatch.setenv(key, value)
    built_cfg = Settings(_env_file=None)
    for key in ex.X2_EX.update:
        monkeypatch.setattr(settings, key, getattr(built_cfg, key))
    x2.check_settings(ex.X2_EX, settings)
    monkeypatch.setattr(settings, "WORKTREE_ROOT", root / "wt-root")
    restore_host_key(monkeypatch, "dry-run-key")
    run = LiveRun("dry", ex.exam_run_cap(settings),
                  wire=httpx2.MockTransport(xg._no_wire))  # fmt: skip
    (root / "loop").mkdir()
    loop = x2.start_x2_loop(repos["p1"], run, root / "loop", REQUIRED, policy=policy)
    ctx = loop.context
    assert isinstance(ctx.repository, InMemoryRepository)
    assert (
        ctx.repository.list_lessons()
        == ()
        == ctx.repository.list_lessons(loop.project.id)
    )
    assert isinstance(ctx.generator, IdeaPipelineGenerator)
    cfg = ctx.generator._cfg
    assert not cfg.GENERATOR_LESSONS and cfg.IDEAS_LANE_VIEWS == {}
    assert ctx.generator._lessons is False
    assert getattr(ctx.combiner, "site_stacks", None) == "on"
    assert loop.mode == "wired" and loop.candidates == () and loop.cap_usd == 6.5
    assert run.capture.exchanges == [] and run.records == []


# ---------------------------------------------------------------------------
# The pins: the committed archive and manifest are the pinned papers
# ---------------------------------------------------------------------------


def test_the_committed_archive_is_the_pinned_papers(tmp_path: Path) -> None:
    """The archive and manifest under ``emergence/round-3`` match the pins in
    ``exam_sitting``: the archive's sha256, the seal's tree hash it was
    packed under and each tier's commit, which ``prepare_papers`` re-derives."""
    found = ea.load_manifest(ea.MANIFEST)
    ex.check_pins(found, ex.Pins())
    ea.check_archive(ea.ARCHIVE, found)
    assert found.sha256 == ex.ARCHIVE_SHA256 and found.seal == ex.SEAL_TREE_SHA256
    repos, _ = ex.prepare_papers(tmp_path / "real")
    assert {r.name: r.commit for r in repos.values()} == {
        ea.tag(t): c for t, c in ex.TIER_COMMITS.items()}  # fmt: skip


@pytest.mark.parametrize("pin", ["archive", "seal", "commit"])
def test_a_manifest_off_the_pins_is_refused_before_the_archive_is_opened(
    built: tuple[Path, ea.Manifest], tmp_path: Path, pin: str
) -> None:
    out, manifest = built
    pins = _pins(manifest)
    wrong = {"archive": dataclasses.replace(pins, archive="1" * 64),
             "seal": dataclasses.replace(pins, seal="2" * 64),
             "commit": dataclasses.replace(pins, commits={**pins.commits,
                                                          "tier-3": "3" * 40})}[pin]  # fmt: skip
    with pytest.raises(ea.ExamIntegrityError, match="not the pinned papers"):
        ex.prepare_papers(tmp_path / "root", archive=out / ea.ARCHIVE_NAME,
                          manifest=out / ea.MANIFEST_NAME, pins=wrong)  # fmt: skip
    assert not (tmp_path / "root").exists()
    with pytest.raises(
        ea.ExamIntegrityError, match="not the pinned papers"
    ):  # real pins
        ex.prepare_papers(tmp_path / "root", archive=out / ea.ARCHIVE_NAME,
                          manifest=out / ea.MANIFEST_NAME)  # fmt: skip


# ---------------------------------------------------------------------------
# The arm, the cap arithmetic, the minutes and the plan
# ---------------------------------------------------------------------------


def test_the_arm_is_x2_0_plus_the_gain_ordered_combine() -> None:
    assert ex.X2_EX.update == {**x2.X2_0.update, "SITE_STACKS": "on"}
    assert x2.X2_0.update.get("SITE_STACKS", "off") == "off" == settings.SITE_STACKS
    mine, base = x2.arm_env(ex.X2_EX), x2.arm_env(x2.X2_0)
    assert {k for k in mine if mine[k] != base.get(k)} == {"SITE_STACKS"}
    assert ex.X2_EX not in x2.EVERY_ARM
    assert ex.X2_EX.key not in {a.key for a in x2.EVERY_ARM}
    assert ex.X2_EX.repos == ("p1", "p2", "p3", "p4")
    assert ex.X2_EX.aa == "none" and "SITE_STACKS" not in x2.X2_0.update
    assert oc._FILE.fullmatch(
        f"ideas-x2-{ex.X2_EX.key}-123456.jsonl"
    )  # a readable label
    x2.check_settings(ex.X2_EX, x2.arm_settings(ex.X2_EX))


def test_the_run_cap_is_run_caps_share_term() -> None:
    cfg = x2.arm_settings(ex.X2_EX)
    s1, s2, review = x2.seeded_stages(cfg)
    stage = max(s1, x2.X1_S1_USD + s2, x2.X1_S1_S2_USD + review)
    share = (x2.X1_CALL_USD + stage) / cfg.IDEAS_DISCOVERY_MAX_SHARE
    assert share == pytest.approx(6.48, abs=0.005)
    assert ex.exam_run_cap(cfg) == 6.50 == ex.sitting_need()
    assert x2.run_cap(cfg) == 9.35 == x2.arm_cap(x2.X2_0)  # X2-0's, the trials at worst


def _archived_x2_0() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(SPRINT_LIVE.glob("ideas-x2-X2-0-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["experiment"] == "ideas-x2-run":
                rows.append(row)
    return rows


def test_no_archived_x2_0_run_came_near_the_cap() -> None:
    """Every archived X2-0 run spent under half the cap, and its seeded
    call's dearest stage (S2 whole) would still pass D55's share after its
    own first call and the dearest S1: no request refused, so unchanged."""
    cfg = x2.arm_settings(ex.X2_EX)
    cap, (_, s2, _) = ex.exam_run_cap(cfg), x2.seeded_stages(cfg)
    rows = _archived_x2_0()
    assert len(rows) == 16 and {r["repo"] for r in rows} == {"tomli", "sqlparse",
                                                             "mistune", "markdown"}  # fmt: skip
    for row in rows:
        first = row["discovery_cost_usd"] - row["seeded_cost_usd"]
        assert row["cost_usd"] <= cap / 2 and row["unaffordable"] == 0
        assert first + x2.X1_S1_USD + s2 <= cfg.IDEAS_DISCOVERY_MAX_SHARE * cap


def test_the_fuse_sits_four_papers_on_14_50_usd_and_never_passes_it() -> None:
    rows = _archived_x2_0()
    dearest = {lib: max(r["cost_usd"] for r in rows if r["repo"] == lib)
               for lib in {r["repo"] for r in rows}}  # fmt: skip
    mean = {
        lib: sum(r["cost_usd"] for r in rows if r["repo"] == lib) / 4 for lib in dearest
    }
    assert (
        round(sum(dearest.values()), 2) == 10.40
        and round(sum(mean.values()), 2) == 9.54
    )
    cap = ex.exam_run_cap(x2.arm_settings(ex.X2_EX))
    assert ex.admitted(12.0, dearest, cap) == ("p1", "p2", "p3")
    assert ex.admitted(12.0, mean, cap) == ("p1", "p2", "p3")
    assert ex.EXAM_BUDGET_USD == 14.5  # O72 item 1: the owner's budget
    assert ex.admitted(ex.EXAM_BUDGET_USD, dearest, cap) == ex.X2_EX.repos
    assert ex.admitted(ex.EXAM_BUDGET_USD, mean, cap) == ex.X2_EX.repos
    assert ex.fuse_refusal(8.0, 6.5, 14.5) is None
    four = ex.fuse_refusal(8.01, 6.5, 14.5)
    assert four is not None and "14.50 USD suite cap" in four
    assert ex.fuse_refusal(5.5, 6.5, 12.0) is None
    refusal = ex.fuse_refusal(5.51, 6.5, 12.0)
    assert (
        refusal is not None
        and "not sat" in refusal
        and "12.00 USD suite cap" in refusal
    )


def test_the_minutes_count_every_launch_the_judges_allow() -> None:
    """``launches``: the baseline (a side, a counted run), 3 calibration
    ABBAs, the profile, 21 trials (paired ABBA, a counted run a side), 21
    confirmations (an ABBA each), 2 combine re-tests; a suite for the
    baseline, each trial and confirmation and each re-test."""
    cfg = x2.arm_settings(ex.X2_EX)
    assert (cfg.MIN_RUNS, cfg.NOISE_CALIBRATION_BLOCKS, x2.run_trials(cfg)) == (
        5,
        3,
        (10, 11),
    )
    work = ex.launches(cfg)
    assert work == ex.Launches(
        6 + 3 + 3 * 12 + 3 + 21 * (12 + 6) + 21 * 12 + 2 * 12, 45
    )
    assert work.runs == 702
    by = {p.key: (round(ex.paper_minutes(p, cfg), 1), ex.paper_timeout(p, cfg))
          for p in ex.EXAM_PAPERS}  # fmt: skip
    assert by == {
        "t1": (111.1, 115),
        "t2": (335.6, 340),
        "t3": (171.4, 175),
        "t4": (243.6, 245),
    }
    t2 = ex.BY_KEY["t2"]  # the formula by hand, for the dearest paper
    by_hand = 1.25 * (10 + 1 + 2 * 8 + (21 * 60 + 702 * 17.5 + 45 * 21) / 60)
    assert ex.paper_minutes(t2, cfg) == pytest.approx(by_hand)
    assert all(m <= ex.JOB_CEILING for _, m in by.values())


W2 = {"LIVE_KEY_SLOT": "2", SUITE_CAP_ENV: "12", ex.PAPER_ENV: "t2", ex.SPENT_ENV: "0"}


@pytest.mark.parametrize(("change", "match"), [
    ({"LIVE_KEY_SLOT": "1"}, "key 2"),
    ({ex.PAPER_ENV: "t5"}, "must be one of t1, t2, t3, t4"),
    ({ex.PAPER_ENV: ""}, "must be one of"),
    ({ex.SPENT_ENV: ""}, "earlier papers spent"),
    ({ex.SPENT_ENV: "nan"}, "earlier papers spent"),
    ({ex.SPENT_ENV: "-1"}, "earlier papers spent"),
    ({ex.SPENT_ENV: "14.51"}, "earlier papers spent"),
    ({SUITE_CAP_ENV: "6.45"}, "needs 6.50"),
    ({SUITE_CAP_ENV: "14.51"}, "owner's 14.5"),
    ({ex.SPENT_ENV: "5.51"}, "5.51 USD spent \\+ the 6.50"),
])  # fmt: skip
def test_the_plan_refuses_before_any_request(
    change: dict[str, str], match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        ex.exam_plan({**W2, **change})
    without = {k: v for k, v in W2.items() if k != "LIVE_KEY_SLOT"}
    with pytest.raises(ValueError, match="key 2"):  # no slot reads as key 1
        ex.exam_plan(without)


def test_the_plan_names_the_paper_its_spend_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = ex.exam_plan({**W2, ex.SPENT_ENV: "5.5"})
    assert (plan.paper.key, plan.spent_usd, plan.cap_usd, plan.run_cap, plan.minutes) == (
        "t2", 5.5, 12.0, 6.5, 340)  # fmt: skip
    monkeypatch.setattr(ex, "JOB_CEILING", 335)
    with pytest.raises(ValueError, match="t2: 340 minutes pass the 335-minute job"):
        ex.exam_plan(W2)
    assert ex.exam_plan({**W2, ex.PAPER_ENV: "t1"}).minutes == 115


def test_a_paper_past_360_minutes_is_refused_at_the_real_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub's 360 is the ceiling, as it is: a paper whose timeout is 360
    sits, one whose timeout is 365 is refused before any request."""
    assert ex.JOB_CEILING == 360
    cfg = x2.arm_settings(ex.X2_EX)
    at = dataclasses.replace(ex.BY_KEY["t2"], workload_s=18.0)
    past = dataclasses.replace(ex.BY_KEY["t2"], workload_s=18.5)
    assert (ex.paper_timeout(at, cfg), ex.paper_timeout(past, cfg)) == (360, 365)
    monkeypatch.setitem(ex.BY_KEY, "t2", at)
    assert ex.exam_plan(W2).minutes == 360
    monkeypatch.setitem(ex.BY_KEY, "t2", past)
    with pytest.raises(ValueError, match="t2: 365 minutes pass the 360-minute job"):
        ex.exam_plan(W2)


_PROCESS_WORDS = re.compile(r"(?:exam|sitting|paper|tier|plant|seat)", re.IGNORECASE)


def test_the_paths_the_engine_s_processes_see_are_neutral() -> None:
    """A test-failure tail the editor reads can hold an absolute path: the
    live case's node id and its tmp folder (pytest's ``tmp_path`` names it
    after the node), the module fixture's folder, the run folder under the
    live root and the clone in it carry none of the sitting's words; the
    ``LIVE_EXAM_*`` variables never reach a child process (``PASS_THROUGH``
    is an allowlist of nine names)."""
    tree = ast.parse((LIVE / "test_exam_sitting_live.py").read_text(encoding="utf-8"))
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name.startswith("test")] == ["test_run"]  # fmt: skip
    source = inspect.getsource(ex.sit_one)
    assert 'where = root / f"run-{repo.name}"' in source
    for paper in ex.EXAM_PAPERS:
        node = f"test_run[{paper.name}]"
        folder = re.sub(r"[\W]", "_", node)[:30]  # pytest's tmp_path name
        for part in (node, folder, f"run-{paper.name}", "user", "wt-root", "sources0"):
            assert _PROCESS_WORDS.search(part) is None, part
    assert not any(n.startswith("LIVE_") for n in PASS_THROUGH)
    env = child_env(home=Path("/h"), tmpdir=Path("/t"), worktree=Path("/w"),
                    base={ex.PAPER_ENV: "t1", ex.SPENT_ENV: "0", "PATH": "/usr/bin"})  # fmt: skip
    assert ex.PAPER_ENV not in env and ex.SPENT_ENV not in env


# ---------------------------------------------------------------------------
# One sitting: open_sitting, sit_case and sit_one, through run_one's calls
# ---------------------------------------------------------------------------


def _calls(fn: Callable[..., object]) -> list[str]:
    """Every call ``fn`` makes, with its arguments, in source order, module
    prefixes dropped."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    found.sort(key=lambda n: (n.lineno, n.col_offset))
    return [ast.unparse(n).replace("x2.", "").replace("dsc.", "") for n in found]


def test_sit_one_makes_run_ones_calls_with_its_arguments() -> None:
    """The differences, and only them: the cap is ``exam_run_cap`` of the
    arm's settings (``arm_cap`` is X2-0's run cap), the folder takes no
    ``EVERY_ARM`` index, the head refusal names the paper; every other call,
    ``run_engine``'s ``model=`` and ``record=`` included, is ``run_one``'s."""
    differ = {
        "arm_cap(arm, recorder.base)": ["cap_of(arm_settings(arm, recorder.base))",
                                        "arm_settings(arm, recorder.base)"],
        "EVERY_ARM.index(arm)": [],
        """ValueError(f"{repo.name}: head {loop.user.base} is not E1's recorded {commit}")""":
            ["""ValueError(f"{repo.name}: head {loop.user.base} is not the paper's {commit}")"""],
    }  # fmt: skip
    theirs: list[str] = []
    for call in _calls(x2.run_one):
        theirs += differ.get(call, [call])
    assert _calls(ex.sit_one) == theirs
    engine = "run_engine(loop, run, isolation, model=recorder.base.ENGINE_MODEL, record=record)"
    assert engine in theirs and set(differ) <= set(_calls(x2.run_one))


class _Engine:
    def __init__(self, head: str, policy: object | None = None) -> None:
        self.head, self.policy, self.calls = head, policy, cast(list[str], [])

    def start(self, repo: Any, run: LiveRun, root: Path, isolation: Isolation, *,
              policy: object) -> Any:  # fmt: skip
        assert isolation is REQUIRED and root.is_dir() and isinstance(repo, ex.ExamRepo)
        assert self.policy is None or policy is self.policy
        self.calls.append(f"start {repo.name} {root.name} {run.cap_usd:g}")
        return SimpleNamespace(user=SimpleNamespace(base=self.head, path=root),
                               context=SimpleNamespace(judges=(OpCountJudge(),)))  # fmt: skip

    def run(self, loop: Any, run: LiveRun, isolation: Isolation, *, model: str,
            record: Callable[[Any, EngineRunResult | None], None]) -> Any:  # fmt: skip
        self.calls.append(f"run {model}")
        record(SimpleNamespace(guard="ok"), xg._state())


def _fake_engine(monkeypatch: pytest.MonkeyPatch, engine: _Engine) -> None:
    monkeypatch.setattr(x2, "start_x2_loop", engine.start)
    monkeypatch.setattr(discovery, "run_engine", engine.run)


def _live(engine: _Engine) -> StartLive:
    def live(cap: float) -> LiveRun:
        engine.calls.append(f"live {cap:g}")
        return LiveRun("x", cap)

    return live


def _rows(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return [json.loads(line) for line in text.splitlines()]


def test_sit_one_is_capped_and_recorded_as_x2_rows(
    papers: Papers, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repos, policy, _ = papers
    engine = _Engine("c" * 40, policy)
    _fake_engine(monkeypatch, engine)
    out = tmp_path / "rows.jsonl"
    recorder = x2.X2Recorder(ex.sitting_plan(repos["p2"]), ResultsSink({RESULTS_ENV: str(out)}),
                             base=x2.arm_settings(ex.X2_EX), commits={"p2": "c" * 40})  # fmt: skip
    ex.sit_one(ex.X2_EX, repos["p2"], live=_live(engine), root=tmp_path / "live-root",
               isolation=REQUIRED, recorder=recorder, policy=policy)  # fmt: skip
    assert engine.calls == [
        "live 6.5",
        "start p2 run-p2 6.5",
        f"run {settings.ENGINE_MODEL}",
    ]
    run = next(r for r in _rows(out) if r["experiment"] == x2.RUN_EXPERIMENT)
    assert (run["arm"], run["repo"], run["cap_usd"], run["dispatch"]) == (
        "X2-EX", "p2", 6.5, "X2-EX:p2")  # fmt: skip
    assert run["patch_dir"] == "live-patches/X2-EX-p2"
    other = x2.X2Recorder(ex.sitting_plan(repos["p2"]), ResultsSink({}),
                          base=x2.arm_settings(ex.X2_EX), commits={"p2": "d" * 40})  # fmt: skip
    with pytest.raises(ValueError, match="is not the paper's"):
        ex.sit_one(ex.X2_EX, repos["p2"], live=_live(engine), root=tmp_path / "again",
                   isolation=REQUIRED, recorder=other, policy=policy)  # fmt: skip


def _env(out: Path, **change: str) -> dict[str, str]:
    return {**W2, RESULTS_ENV: str(out), **change}


def test_open_sitting_refuses_its_plan_before_touching_a_file(
    built: tuple[Path, ea.Manifest], tmp_path: Path
) -> None:
    out, manifest = built
    for change in ({ex.SPENT_ENV: "6"}, {ex.PAPER_ENV: "t9"}, {"LIVE_KEY_SLOT": "1"}):
        with pytest.raises(ValueError):
            ex.open_sitting(_env(tmp_path / "r.jsonl", **change), tmp_path / "root",
                            base=x2.arm_settings(ex.X2_EX), archive=out / ea.ARCHIVE_NAME,
                            manifest=out / ea.MANIFEST_NAME, pins=_pins(manifest))  # fmt: skip
        assert not (tmp_path / "root").exists()


def test_open_sitting_and_sit_case_run_the_dispatchs_paper_as_x2_ex(
    built: tuple[Path, ea.Manifest], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture's sitting: the dispatch's paper, its expected head, the
    recorder on ``X2_EX`` with that head; the case: every other paper
    skipped, the dispatch's sat through ``sit_one`` with the sitting's policy."""
    out, manifest = built
    rows = tmp_path / "rows.jsonl"
    root = Path(os.path.realpath(tmp_path)) / "sources"
    root.mkdir()
    cfg = x2.arm_settings(ex.X2_EX)
    sitting = ex.open_sitting(_env(rows), root, base=cfg, archive=out / ea.ARCHIVE_NAME,
                              manifest=out / ea.MANIFEST_NAME, pins=_pins(manifest))  # fmt: skip
    assert (sitting.plan.paper.key, sitting.repo.name) == ("t2", "p2")
    assert sitting.recorder.plan.runs == ((ex.X2_EX, sitting.repo),)
    assert sitting.recorder.base is cfg
    head = oss.prepare_repo(sitting.repo, root / "check", policy=sitting.policy).base
    assert sitting.recorder.commits == {"p2": head}
    engine = _Engine(head, sitting.policy)
    _fake_engine(monkeypatch, engine)
    for paper in ex.EXAM_PAPERS:
        if paper.key == "t2":
            continue
        with pytest.raises(pytest.skip.Exception, match="not this dispatch's paper"):
            ex.sit_case(paper, sitting, live=_live(engine), root=tmp_path / paper.key,
                        isolation=REQUIRED)  # fmt: skip
    assert engine.calls == []
    ex.sit_case(ex.BY_KEY["t2"], sitting, live=_live(engine), root=tmp_path / "t2",
                isolation=REQUIRED)  # fmt: skip
    assert engine.calls == [
        "live 6.5",
        "start p2 run-p2 6.5",
        f"run {settings.ENGINE_MODEL}",
    ]
    run = next(r for r in _rows(rows) if r["experiment"] == x2.RUN_EXPERIMENT)
    assert (run["arm"], run["repo"], run["commit"]) == ("X2-EX", "p2", head)


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
    )


def _body(fn: ast.FunctionDef) -> list[str]:
    """The statements, the docstring left out."""
    return [ast.unparse(s) for s in fn.body if not isinstance(s, ast.Expr)
            or not isinstance(s.value, ast.Constant)]  # fmt: skip


def test_the_live_module_only_delegates() -> None:
    """Its fixture is ``open_sitting`` on the process env, its one test
    ``sit_case`` on each paper with the live fixtures, nothing else: what
    the plan, the fuse, the arm, the policy and the commits do is tested
    above, through those two functions."""
    tree = ast.parse((LIVE / "test_exam_sitting_live.py").read_text(encoding="utf-8"))
    fixture, test = _function(tree, "sitting"), _function(tree, "test_run")
    assert _body(fixture) == [
        "return ex.open_sitting(os.environ, tmp_path_factory.mktemp('sources'))"
    ]
    assert _body(test) == [
        "ex.sit_case(paper, sitting, live=live, root=live_root, isolation=live_isolation)"
    ]
    assert [ast.unparse(d) for d in test.decorator_list] == [
        "pytest.mark.parametrize('paper', ex.EXAM_PAPERS, ids=[p.name for p in ex.EXAM_PAPERS])"
    ]
    assert [ast.unparse(d) for d in fixture.decorator_list] == [
        "pytest.fixture(scope='module')"
    ]
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.ClassDef)]
    assert names == ["sitting", "test_run"]
    assert "pytestmark = pytest.mark.live" in [ast.unparse(n) for n in tree.body]


# ---------------------------------------------------------------------------
# Isolation: the sitting's rows and the papers stay out of every reader
# ---------------------------------------------------------------------------

RECURSIVE = {  # every recursive listing in tests/live: none over the handoff
    ("experiments/heal.py", "top.rglob"), ("test_corpus_guards.py", "top.rglob"),
    ("test_discovery_guards.py", "repo.path.rglob"),
    ("test_evolution_guards.py", "DEDUPE.rglob"), ("test_ideas_x2_patches.py", "top.rglob"),
    ("test_key_slot_guards.py", "GITHUB_DIR.rglob"),
    ("test_oss_guards.py", "(user.path / repo.module_root).rglob"),
    ("exam_archive.py", "os.walk"), ("test_attack_live.py", "os.walk"),
    ("test_exam_sitting_guards.py", "LIVE.rglob"),  # this scan itself
}  # fmt: skip
FOLDER_LISTINGS = {  # every iterdir, os.listdir and os.scandir: none over the handoff
    ("discovery_grader.py", "folder.iterdir"),
    ("experiments/test_extraction.py", "tmp_path.iterdir"),
    ("experiments/test_heal.py", "(HARD_DIR / '_shallow').iterdir"),
    ("experiments/test_heal.py", "(HARD_DIR / '_solutions').iterdir"),
    ("experiments/test_heal.py", "(HARD_DIR / kept).iterdir"),
    ("experiments/test_heal.py", "(HEAL_DIR / '_hidden').iterdir"),
    ("experiments/test_heal.py", "(HEAL_DIR / '_solutions').iterdir"),
    ("experiments/test_heal.py", "HARD_DIR.iterdir"),
    ("experiments/test_heal.py", "HEAL_DIR.iterdir"),
    ("experiments/test_heal_agent.py", "(root / kept).iterdir"),
    ("experiments/test_heal_agent.py", "root.iterdir"),
    ("test_corpus_guards.py", "CORPUS_DIR.iterdir"),
    ("test_corpus_guards.py", "SOLUTIONS_DIR.iterdir"),
    ("test_discovery_corpus_guards.py", "DISCOVERY_DIR.iterdir"),
    ("test_discovery_corpus_guards.py", "DISCOVERY_SOLUTIONS_DIR.iterdir"),
    ("test_exam_sitting_guards.py", "(user.path / 'bench_data').iterdir"),
    ("test_hard_corpus_guards.py", "HARD_DIR.iterdir"),
    ("test_hard_corpus_guards.py", "HARD_SOLUTIONS_DIR.iterdir"),
    ("test_ideas_report_guards.py", "out.iterdir"),
    ("test_ideas_x2_depth.py", "out.iterdir"),
    ("test_ideas_x2_patches.py", "away.iterdir"),
    ("test_ideas_x2_patches.py", "tmp_path.iterdir"),
    ("test_oss_guards.py", "dest.parent.iterdir"),
    ("test_oss_guards.py", "outside.iterdir"),
    ("test_upstream_guards.py", "KEYS_DIR.iterdir"),
    ("test_upstream_guards.py", "WORKLOADS_DIR.iterdir"),
    ("test_upstream_guards.py", "local.root.iterdir"),
    ("x2_proc.py", "os.scandir"),
}
DEEP_GLOBS = {  # every glob below one folder level: none over the handoff
    ("test_ideas_x2_equiv.py", "'*/cwd/out.json'"),  # a test's own tmp tree
    ("test_ideas_x2_equiv.py", "'base-*/trial-*'"),  # a test's own tmp tree
}
OURS = ("exam_archive.py", "exam_sitting.py", "test_exam_sitting_guards.py",
        "test_exam_sitting_live.py", "test_exam_sitting_ci.py")  # fmt: skip


def _modules() -> Iterator[tuple[str, ast.Module, str]]:
    for path in sorted(LIVE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        yield path.relative_to(LIVE).as_posix(), ast.parse(text), text


def test_no_reader_lists_the_sitting_rows_or_the_papers() -> None:
    """Every ``glob`` in the harness lists one folder level (no ``**``, no
    ``/``), so nothing rooted at ``w2-sprint/live`` sees ``exam-sitting/``;
    a glob below one level is one ``DEEP_GLOBS`` names; every recursive
    listing (``rglob``, ``os.walk``) and every folder listing
    (``iterdir``, ``os.listdir``, ``os.scandir``) is one this guard names;
    no other module names the sitting's rows folder or the papers' archive
    (``test_corpus_guards`` and ``test_plumbing_guards`` name the suite)."""
    recursive, listed, deep = set(), set(), set()
    for rel, tree, text in _modules():
        if rel not in OURS:
            for word in (
                "/exam-sitting",
                "exam-sitting/",
                "exam-papers",
                "round-3",
                "SITTING_ROWS",
            ):  # the paths (the suite's name is a ci pin)
                assert word not in text, (rel, word)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            ):
                continue
            what, owner = node.func.attr, ast.unparse(node.func.value)
            if what == "glob" and node.args:
                pattern = ast.unparse(node.args[0])
                assert "**" not in pattern, (rel, pattern)
                if "/" in pattern:
                    deep.add((rel, pattern))
            elif what in ("rglob", "walk") and owner != "ast":
                recursive.add((rel, ast.unparse(node.func)))
            elif what in ("iterdir", "listdir", "scandir"):
                listed.add((rel, ast.unparse(node.func)))
    assert recursive == RECURSIVE
    assert listed == FOLDER_LISTINGS
    assert deep == DEEP_GLOBS
    assert (
        ex.SITTING_ROWS.parent == SPRINT_LIVE and ex.SITTING_ROWS.name == "exam-sitting"
    )
    assert ea.ARCHIVE.parent.name == "round-3"
    assert not str(ea.ARCHIVE).startswith(str(SPRINT_LIVE))


def test_the_combine_order_census_never_reads_the_sitting_rows(tmp_path: Path) -> None:
    """A file in ``live/exam-sitting/`` that ``census`` would refuse if it read
    it (a name off its pattern, bytes that are no JSON) is not read; one in
    ``live/`` is, so the test can see."""
    sitting = tmp_path / "live" / "exam-sitting"
    sitting.mkdir(parents=True)
    (sitting / "ideas-x2-X2-EX-123456.jsonl").write_text("not json", encoding="utf-8")
    (sitting / "ideas-x2-anything.jsonl").write_text("not json", encoding="utf-8")
    assert oc.census(tmp_path) == ((), ())
    (tmp_path / "live" / "ideas-x2-anything.jsonl").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="not an ideas-x2 run file name"):
        oc.census(tmp_path)
