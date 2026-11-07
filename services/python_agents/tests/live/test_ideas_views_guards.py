"""Offline guards of the ideas-views suite (Va, ``ideas_views.py``).

Not ``live``: these spend nothing and send nothing. They prove, before the
views pass is dispatched, that per library every view G2 defines is built
with the engine's own builders and the pipeline's limits at the recorded
commit, recorded as one redacted, chunked row each and loaded back
strictly; that two runs give the same bytes (in other processes too, under
another hash seed); that a protected input is shown as its schema alone;
that the history view never reaches past the pinned commit; and that no
transport is ever constructed.

Fakes and what they stand for: ``og.LOCAL`` and a ``file://`` bare upstream
with a short history for GitHub over https (``oss.PRODUCTION``); a facts
body written here for E1's recorded ``ideas-facts`` rows (the committed
fixture is read, never cloned, offline). The reader is the real one
(``factory.repo_reader``, a ``GitWorkspace``). What only a live run proves:
the real libraries' tags at E1's commits, their history at depth, and the
views of their real code.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from autonomous_ai_agents.clients.transport import AnthropicTransport
from autonomous_ai_agents.common.config import IDEA_VIEWS, Settings
from autonomous_ai_agents.common.models import (
    Direction,
    Hotspot,
    Objective,
    ObjectiveKind,
    Project,
    Workload,
)
from autonomous_ai_agents.optimization.idea_context import (
    HISTORY_WALK_MAX,
    IdeaReadLimits,
)

from . import ideas_probe as ip
from . import ideas_views as iv
from . import oss
from . import test_oss_guards as og
from .conftest import TESTS_DIR, LiveRun, RequestRecord
from .discovery_io import ResultsSink
from .discovery_oss import OSS_SELECTABLE
from .oss import OSS_CORPUS
from .test_corpus_guards import EXPERIMENT_MINUTES, _ci_block, _run_script

upstream = og.upstream

LIB = OSS_CORPUS[8]  # tomli, a pinned OSS library
LIVE_DIR = TESTS_DIR / "live"
TEXT = '''"""Number tools."""

LIMIT = 1000
CACHE: dict[int, int] = {}


def slow_sum(values):
    total = 0
    for value in values[:LIMIT]:
        total = total + abs(value)
    return total


def slow_join(parts):
    text = ""
    for part in parts:
        text = text + str(part).strip()
    return text
'''
USE = '''"""Callers."""

from pkg.text import slow_join, slow_sum


def run(rows):
    out = []
    for row in rows:
        out.append(slow_sum(row))
    return slow_join(out)
'''
PLANTED_KEY, PLANTED_VALUE = "plantedkeyname", "planted-value-zz9"
INPUT = json.dumps({PLANTED_KEY: [PLANTED_VALUE, 7, 8.5], "other": {"x": True}})
SPEED_UP = "Speed up slow_sum by hoisting the abs lookup"
AFTER_PIN = "perf: faster slow_join, committed after the pin"


def _commit(work: Path, message: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    og._git(work, "add", "-A")
    og._git(work, "commit", "-q", "--allow-empty", "-m", message)
    return og._git(work, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path: Path) -> tuple[oss.OssRepo, str]:
    """A bare upstream: four commits up to the tag ``v1`` (one a speed-up),
    then one more on its branch past the tag; ``(repo, after-pin sha)``."""
    work = tmp_path / "upstream-h"
    og._git(tmp_path, "init", "-q", "-b", "trunk", str(work))
    _commit(work, "first", {
        "pkg/__init__.py": "", "pkg/text.py": TEXT.replace("abs(value)", "abs(value) * 1"),
        "pkg/use.py": USE, "tests/test_text.py": "import pkg\n",
        "tests/data/input.json": INPUT, "LICENSE": "Permission is hereby granted\n",
    })  # fmt: skip
    _commit(work, SPEED_UP, {"pkg/text.py": TEXT})
    _commit(work, "docs: wording", {"README.md": "Number tools.\n"})
    pin = _commit(work, "release", {})
    og._git(work, "tag", "v1")
    after = _commit(work, AFTER_PIN, {"pkg/text.py": TEXT + "\n# after\n"})
    bare = tmp_path / "upstream-h.git"
    og._git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return og._local_repo(f"file://{bare}", pin, LIB), after


def _spot(project: Project, path: str, symbol: str, share: float) -> Hotspot:
    return Hotspot(
        id=f"h-{symbol}", project_id=project.id, workload_id="w1", file_path=path,
        symbol=symbol, self_time_s=share * 10, total_time_s=share * 20,
        share=share, calls=40,
    )  # fmt: skip


def _body(repo: oss.OssRepo, root: Path) -> ip.FactsBody:
    """Facts as E1 recorded them, at the head ``prepare_repo`` gives."""
    (root / "rec").mkdir(parents=True)
    head = oss.prepare_repo(repo, root / "rec" / "user", policy=og.LOCAL).base
    project = Project(id="p1", name=repo.name, root_path="/srv/lib")
    spots = (
        _spot(project, "pkg/text.py", "slow_sum", 0.5),
        _spot(project, "pkg/text.py", "slow_join", 0.3),
        _spot(project, "pkg/use.py", "run", 0.1),
    )
    objective = Objective(
        project_id=project.id, kind=ObjectiveKind.runtime, metric="wall_time_s",
        direction=Direction.minimize, min_relative_gain=0.02, description="faster",
    )  # fmt: skip
    return ip.FactsBody(
        commit=head, run_id="run-1", protected=("tests/test_text.py",),
        project=project, understanding=None, hotspots=spots, objective=objective,
    )  # fmt: skip


def _rows(
    repo: oss.OssRepo,
    body: ip.FactsBody,
    dest: Path,
    workloads: tuple[Workload, ...] | None = None,
) -> list[iv.ViewRow]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    return iv.views_rows(repo, body, dest, policy=og.LOCAL, workloads=workloads)


def _text(row: iv.ViewRow) -> str:
    chunks = row.record()["chunks"]
    assert isinstance(chunks, tuple)
    return "".join(str(c) for c in chunks)


# ---------------------------------------------------------------------------
# Every view, per library
# ---------------------------------------------------------------------------


def test_every_view_is_built_at_the_recorded_commit_with_the_pipelines_limits(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, _ = history
    body = _body(repo, tmp_path)
    rows = _rows(repo, body, tmp_path / "a" / "user")
    assert [r.body.view for r in rows] == list(IDEA_VIEWS)
    assert all(r.repo == repo.name and r.body.commit == body.commit for r in rows)
    assert all(r.body.limits == IdeaReadLimits.from_settings(Settings()) for r in rows)
    views = {r.body.view: r.body for r in rows}
    assert all(v.context is not None and v.context.documents for v in views.values())
    callers = "\n".join(views["callers"].facts)
    assert '"path": "pkg/use.py"' in callers and '"in_loop": true' in callers
    assert views["callers"].facts[0].startswith("hot function: ")
    structures = views["data_structures"].facts
    assert structures[0].startswith('module name: {"name": "LIMIT"')
    assert any('"name": "values"' in f and "subscript_read" in f for f in structures)
    (workload,) = views["input_shape"].facts
    assert workload.startswith("workload: ") and repo.bench_path in workload
    module = views["whole_module"].context
    assert module is not None and [d.path for d in module.documents] == ["pkg/text.py"]
    assert views["next_hotspots"].facts[0].startswith("hottest function (not shown)")
    record = rows[0].record()
    assert record["experiment"] == iv.VIEWS_EXPERIMENT == "ideas-views"
    assert (record["repo"], record["view"], record["built"]) == (
        repo.name,
        "callers",
        True,
    )


def test_history_is_read_only_up_to_the_pinned_commit(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, after = history
    body = _body(repo, tmp_path)
    dest = tmp_path / "a" / "user"
    rows = _rows(repo, body, dest)
    (shown,) = [r.body for r in rows if r.body.view == "history"]
    facts = "\n".join(shown.facts)
    assert SPEED_UP in facts and '"touches_hot_file": true' in facts
    assert AFTER_PIN not in facts and "docs: wording" not in facts
    assert shown.commits == 5  # four upstream up to the pin, the benchmark's
    gone = subprocess.run(
        ["git", "-C", str(dest), "cat-file", "-e", f"{after}^{{commit}}"],
        env=og._CLEAN_GIT, capture_output=True, check=False,
    )  # fmt: skip
    assert gone.returncode != 0  # past the pin: never fetched
    assert og._git(dest, "rev-parse", "HEAD") == body.commit
    assert not (dest / ".git" / "FETCH_HEAD").exists()


def test_the_history_fetch_is_bounded_and_refuses_a_moved_tag_or_a_foreign_url(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, _ = history
    body = _body(repo, tmp_path)
    (tmp_path / "a").mkdir()
    dest = tmp_path / "a" / "user"
    oss.prepare_repo(repo, dest, policy=og.LOCAL)
    assert iv.deepen(repo, dest, body.commit, policy=og.LOCAL, depth=2) == 3
    moved = og._local_repo(repo.url, "f" * 40, LIB)
    with pytest.raises(oss.CloneRefusedError, match="not the pinned"):
        iv.deepen(moved, dest, body.commit, policy=og.LOCAL)
    with pytest.raises(oss.CloneRefusedError, match="HEAD"):
        iv.deepen(repo, dest, "e" * 40, policy=og.LOCAL)
    with pytest.raises(oss.CloneRefusedError, match="allowlist"):
        iv.deepen(repo, dest, body.commit, policy=oss.PRODUCTION)
    assert iv.HISTORY_DEPTH >= HISTORY_WALK_MAX


def test_a_protected_input_is_shown_as_its_schema_only(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, _ = history
    body = _body(repo, tmp_path)
    data = Workload(
        id="w1", project_id="p1", name=repo.name,
        command=("python", repo.bench_path, "tests/data/input.json"),
    )  # fmt: skip
    rows = _rows(repo, body, tmp_path / "a" / "user", (data,))
    (shape,) = [r for r in rows if r.body.view == "input_shape"]
    facts = "\n".join(shape.body.facts)
    assert '"protected": true' in facts and "input schema: " in facts
    assert '"format": "json"' in facts and '"head"' not in facts
    for row in rows:
        text = _text(row)
        assert PLANTED_KEY not in text and PLANTED_VALUE not in text


def test_two_runs_give_the_same_bytes_in_this_and_other_processes(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, _ = history
    body = _body(repo, tmp_path)
    first = json.dumps([r.record() for r in _rows(repo, body, tmp_path / "a" / "user")])
    again = json.dumps([r.record() for r in _rows(repo, body, tmp_path / "b" / "user")])
    assert first == again
    (tmp_path / "body.json").write_text(body.model_dump_json(), encoding="utf-8")
    script = (
        "import json, sys; from pathlib import Path\n"
        "from live import ideas_views as iv, ideas_probe as ip, test_oss_guards as og\n"
        "from live.oss import OSS_CORPUS\n"
        "body = ip.FactsBody.model_validate_json(Path(sys.argv[1]).read_text())\n"
        f"repo = og._local_repo({repo.url!r}, {repo.commit!r}, OSS_CORPUS[8])\n"
        "rows = iv.views_rows(repo, body, Path(sys.argv[2]), policy=og.LOCAL)\n"
        "print(json.dumps([r.record() for r in rows]))\n"
    )
    service = TESTS_DIR.parent
    for seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": f"{service / 'src'}{os.pathsep}{TESTS_DIR}"}  # fmt: skip
        dest = tmp_path / f"seed-{seed}" / "user"
        dest.parent.mkdir()
        proc = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / "body.json"), str(dest)],
            env=env, cwd=service, capture_output=True, text=True, check=False,
            timeout=300,
        )  # fmt: skip
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert proc.stdout.strip() == first, seed


# ---------------------------------------------------------------------------
# The rows and the loader
# ---------------------------------------------------------------------------


def _recorded(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> tuple[ip.FactsBody, list[iv.ViewRow], Path]:
    repo, _ = history
    body = _body(repo, tmp_path)
    rows = _rows(repo, body, tmp_path / "a" / "user")
    path = tmp_path / "results.jsonl"
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(path)})
    sink.write({"experiment": "ideas-facts", "repo": repo.name, "chunks": []})
    for row in rows:
        sink.write(row.record())
    return body, rows, path


def test_rows_are_chunked_and_load_back_as_the_views_the_pipeline_uses(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    body, rows, path = _recorded(history, tmp_path)
    lines = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
    assert all(len(c) <= 500 for line in lines[1:] for c in line["chunks"])
    assert len(lines) == 1 + len(IDEA_VIEWS)
    loaded = iv.load_views(path, {LIB.name: body})
    (recorded,) = loaded.values()
    assert (recorded.repo, recorded.commit, recorded.run_id) == (
        LIB.name,
        body.commit,
        "run-1",
    )
    dest = tmp_path / "use" / "user"
    dest.parent.mkdir()
    source, _ = iv.view_source(history[0], body, dest, policy=og.LOCAL)
    for row in rows:
        notes: list[str] = []
        view = recorded.build(row.body.view, source, notes)
        assert view is not None and view.name == row.body.view
        assert (view.context, view.facts) == (row.body.context, row.body.facts)
        assert tuple(notes) == row.body.notes
    (workload,) = source.workloads
    fed = workload.model_copy(update={"command": (*workload.command, "in.json")})
    wrong = [
        dataclasses.replace(source, commit="e" * 40),
        dataclasses.replace(source, limits=IdeaReadLimits(hot_functions=2)),
        dataclasses.replace(source, hotspots=body.hotspots[:1]),
        dataclasses.replace(source, protected=()),
        dataclasses.replace(source, workloads=()),  # the input shape is the workload's
        dataclasses.replace(source, workloads=(fed,)),
    ]
    for other in wrong:
        with pytest.raises(ValueError, match="not the source recorded"):
            recorded.build("input_shape", other, [])
    # A workload's fresh id and timestamp decide no view, so they are not compared.
    again = Workload(project_id=workload.project_id, name=workload.name,
                     command=workload.command)  # fmt: skip
    assert (again.id, again.created_at) != (workload.id, workload.created_at)
    same = dataclasses.replace(source, workloads=(again,))
    assert recorded.build("input_shape", same, []) is not None


def test_a_key_shaped_string_never_reaches_a_row(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    _, rows, _ = _recorded(history, tmp_path)
    key = "sk-ant-api03-" + "A" * 60
    row = iv.ViewRow(rows[0].repo, rows[0].body.model_copy(update={"facts": (key,)}))
    text = _text(row)
    assert key not in text and "[redacted]" in text


def _write(path: Path, lines: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(x, sort_keys=True) + "\n" for x in lines), "utf-8"
    )
    return path


def test_the_loader_refuses_duplicate_malformed_missing_and_disagreeing_rows(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    body, rows, path = _recorded(history, tmp_path)
    good = [json.loads(x) for x in path.read_text("utf-8").splitlines()][1:]
    cases: list[tuple[list[dict[str, object]], str]] = [
        ([*good, good[0]], "recorded twice"),
        (good[1:], "missing"),
        ([{**good[0], "chunks": ["{not json"]}, *good[1:]], "Invalid JSON"),
        ([{**good[0], "extra": 1}, *good[1:]], "Extra inputs"),
        ([{**good[0], "view": "imaginary"}, *good[1:]], "view"),
        ([{**good[0], "view": "history"}, *good[1:]], "history row holds the callers"),
        ([{**good[0], "built": False}, *good[1:]], "built"),
    ]
    other = rows[1].body.model_copy(update={"commit": "e" * 40})
    cases.append(([good[0], iv.ViewRow(LIB.name, other).record(), *good[2:]],
                  "disagree"))  # fmt: skip
    for n, (lines, why) in enumerate(cases):
        with pytest.raises(ValueError, match=why):
            iv.load_views(_write(tmp_path / f"bad-{n}.jsonl", lines))
    stale = body.model_copy(update={"commit": "e" * 40})
    with pytest.raises(ValueError, match="not the recorded facts"):
        iv.load_views(path, {LIB.name: stale})
    with pytest.raises(ValueError, match="no recorded facts"):
        iv.load_views(path, {})
    assert iv.load_views(_write(tmp_path / "none.jsonl", [])) == {}


# ---------------------------------------------------------------------------
# One library on a live run: no transport, notes, a breach raised
# ---------------------------------------------------------------------------


def _forbid_transports(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the views pass constructed a transport")

    monkeypatch.setattr(AnthropicTransport, "__init__", refuse)
    monkeypatch.setattr(LiveRun, "transport", refuse)


def test_one_library_sends_nothing_and_constructs_no_transport(
    history: tuple[oss.OssRepo, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _ = history
    _forbid_transports(monkeypatch)
    body = _body(repo, tmp_path)
    results = tmp_path / "results.jsonl"
    plan = iv.ViewsPlan((repo,), {repo.name: body})
    recorder = iv.ViewsRecorder(plan, ResultsSink({"LIVE_RESULTS_PATH": str(results)}))
    run = LiveRun("dry", iv.VIEWS_RUN_CAP_USD)
    (tmp_path / "live").mkdir()
    iv.run_views(
        repo, run=run, root=tmp_path / "live", recorder=recorder, policy=og.LOCAL
    )
    assert run.records == [] and run.capture.exchanges == [] and run.spent_usd == 0
    assert run.notes == [f"VIEWS {repo.name}: 6 of 6 view(s) built, 5 commit(s) read"]
    assert set(iv.load_views(results)) == {repo.name}
    echoed: list[str] = []
    recorder.finish(echoed.append)
    assert any(line.startswith(f"| {repo.name} | history | yes |") for line in echoed)
    iv.ViewsRecorder(plan, ResultsSink({})).finish(echoed.append)  # no rows: nothing
    run.records.append(RequestRecord("m", 1, 1, 0, 0, 0.0, 0.0, "end_turn"))
    with pytest.raises(AssertionError):
        iv.check_no_request(run)


def test_a_breach_is_noted_on_its_run_then_raised(
    history: tuple[oss.OssRepo, str], tmp_path: Path
) -> None:
    repo, _ = history
    body = _body(repo, tmp_path).model_copy(update={"commit": "e" * 40})
    plan = iv.ViewsPlan((repo,), {repo.name: body})
    run = LiveRun("dry", iv.VIEWS_RUN_CAP_USD)
    (tmp_path / "live").mkdir()
    with pytest.raises(ValueError, match="not the recorded"):
        iv.run_views(repo, run=run, root=tmp_path / "live",
                     recorder=iv.ViewsRecorder(plan, ResultsSink({})), policy=og.LOCAL)  # fmt: skip
    (note,) = run.notes
    assert note.startswith(f"VIEWS {repo.name}: breach: ValueError: ")
    assert len(note) <= ip.NOTE_CHARS


# ---------------------------------------------------------------------------
# The plan: E1's committed facts, the need, the minutes
# ---------------------------------------------------------------------------


def test_the_plan_is_e1s_eight_libraries_at_no_cost_within_the_job() -> None:
    plan = iv.views_plan()
    order = [r.name for r in OSS_SELECTABLE]
    assert [r.name for r in plan.repos] == sorted(ip.E1_REPOS, key=order.index)
    assert set(plan.facts) == set(ip.E1_REPOS) and len(plan.repos) == 8
    assert iv.views_need() == 0.0 == iv.VIEWS_RUN_CAP_USD
    assert plan.minutes() == 16 <= iv.VIEWS_JOB_MINUTES == 30
    for repo in plan.repos:  # every library's recorded profile names its workload
        workload = iv.recorded_workload(repo, plan.facts[repo.name])
        assert workload.command == repo.workload_argv
        assert {workload.id} == {h.workload_id for h in plan.facts[repo.name].hotspots}


def test_the_plan_refuses_unknown_empty_or_too_long_and_the_workload_one_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = ip.load_facts(TESTS_DIR / "fixtures" / "ideas_probe" / "facts.jsonl")
    tomli = facts["tomli"]
    sink = ResultsSink({"LIVE_RESULTS_PATH": str(tmp_path / "f.jsonl")})
    project = tomli.project.model_copy(update={"name": "private_app"})
    foreign = tomli.model_copy(update={"project": project})
    sink.write({"experiment": ip.FACTS_EXPERIMENT, "repo": "private_app",
                "chunks": ip._chunks(foreign.model_dump_json())})  # fmt: skip
    with pytest.raises(ValueError, match="not a pinned OSS library: private_app"):
        iv.views_plan(tmp_path / "f.jsonl")
    _write(tmp_path / "e.jsonl", [])
    with pytest.raises(ValueError, match="no recorded facts"):
        iv.views_plan(tmp_path / "e.jsonl")
    monkeypatch.setattr(iv, "VIEWS_JOB_MINUTES", 15)
    with pytest.raises(ValueError, match="past the 15-minute job"):
        iv.views_plan()
    two = tomli.hotspots[0].model_copy(update={"workload_id": "w-other"})
    mixed = tomli.model_copy(update={"hotspots": (*tomli.hotspots, two)})
    with pytest.raises(ValueError, match="2 workloads"):
        iv.recorded_workload(next(r for r in OSS_CORPUS if r.name == "tomli"), mixed)


# ---------------------------------------------------------------------------
# The live module
# ---------------------------------------------------------------------------


def test_the_live_module_is_marked_reads_its_plan_first_and_runs_each_library() -> None:
    source = (LIVE_DIR / "test_ideas_views_live.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    marks = [
        ast.unparse(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and [ast.unparse(t) for t in node.targets] == ["pytestmark"]
    ]
    assert marks == ["pytest.mark.live"]
    tests = [n for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]  # fmt: skip
    assert [t.name for t in tests] == ["test_ideas_views"]
    assert "live" in [a.arg for a in tests[0].args.args]
    assert '@pytest.fixture(scope="module")' in source and "views_plan()" in source
    calls = {ast.unparse(n.func) for n in ast.walk(tests[0]) if isinstance(n, ast.Call)}
    assert {"run_views", "live"} <= calls
    assert "live(VIEWS_RUN_CAP_USD)" in source
    assert "OSS_SELECTABLE, ids=[r.name for r in OSS_SELECTABLE]" in source


def test_the_ci_row_need_timeout_noise_rule_and_stage_a_ignore() -> None:
    """ci.yml's ideas-views row: no request, a cap above 0, its minutes."""
    assert "ideas-views" in _ci_block("      suite:", "      mode:")
    cap_help = _ci_block("      suite_cap_usd:", "\n\n")
    assert "ideas-views 0 (no request, but the cap must be above 0)" in cap_help
    block = _ci_block("  live-smoke:", "    defaults:")
    assert f"inputs.suite == 'ideas-views' && {iv.VIEWS_JOB_MINUTES} ||" in block
    assert EXPERIMENT_MINUTES["ideas-views"] == iv.VIEWS_JOB_MINUTES
    script = _run_script()
    row = "ideas-views) paths=(tests/live/test_ideas_views_live.py); need=0 ;;"
    assert row in script and iv.views_need() == 0
    noise = script[script.index('case "${INPUT_SUITE}" in\n  noise |') :]
    noise = noise[: noise.index("esac")]
    step2 = [line for line in noise.splitlines() if "noise_rule=step2" in line]
    assert any(re.search(r"\bideas-views\b", line) for line in step2)
    assert "--ignore=tests/live/test_ideas_views_live.py" in script
