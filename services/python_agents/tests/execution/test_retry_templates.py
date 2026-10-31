"""Live templates (D13): each snippet raised uncaught under every ``python3.N`` on PATH.

stderr's last line must parse, fully match the expected template inside its
version range, and pass ``classify`` with its names closure-checked (the
snippets raise on a line naming every slot). Locally a missing interpreter is
skipped, as in ``test_profiler.py``; in CI (``CI`` set) it fails instead, so
3.8-3.14 are all proven there. The child gets only ``PATH`` and a colour
``TERM`` (``TERM`` alone must not colour a pipe) and runs with ``-E -s``.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - fixed argv, test snippets only
from pathlib import Path

import pytest

from autonomous_ai_agents.execution.crash import parse_traceback
from autonomous_ai_agents.execution.procrun import RunFailure
from autonomous_ai_agents.execution.retry import TEMPLATES, ClosureIndex, classify

MINORS = range(8, 15)
FOUND = {minor: shutil.which(f"python3.{minor}") for minor in MINORS}
INTERPRETERS = [
    pytest.param(
        minor,
        id=f"python3.{minor}",
        marks=pytest.mark.skipif(
            FOUND[minor] is None and not os.environ.get("CI"),
            reason=f"python3.{minor} not installed",
        ),
    )
    for minor in MINORS
]
BY_ID = {template.id: template for template in TEMPLATES}
PKG_CYCLE = {
    "pkg/__init__.py": "",
    "pkg/ca.py": "from pkg.cb import g\ndef f(): pass\n",
    "pkg/cb.py": "from pkg.ca import f\ndef g(): pass\n",
    "main.py": "import pkg.ca\n",
}

CASES: dict[str, tuple[dict[str, str], tuple[str, ...]]] = {
    "name": (
        {"main.py": "def f():\n    return undefined_name\nf()\n"},
        ("name_undefined",),
    ),
    "name-hint": (
        {"main.py": "def f():\n    counter = 1\n    return countr\nf()\n"},
        ("name_undefined",),
    ),
    "name-import": (
        {"main.py": "def f():\n    return math.pi\nf()\n"},
        ("name_undefined",),
    ),
    "free": (
        {
            "main.py": "def outer():\n    def inner():\n        return v\n    inner()\n    v = 1\nouter()\n"
        },
        ("free_old", "free"),
    ),
    "local": (
        {"main.py": "x = 1\ndef f():\n    x += 1\nf()\n"},
        ("local_old", "local"),
    ),
    "import": ({"main.py": "from os import nopath_here\n"}, ("import_name",)),
    "import-hint": ({"main.py": "from os import getcwdd\n"}, ("import_name",)),
    "cycle": (
        {
            "ca.py": "from cb import g\ndef f(): pass\n",
            "cb.py": "from ca import f\ndef g(): pass\n",
            "main.py": "import ca\n",
        },
        ("import_cycle", "import_rename"),
    ),
    "pkg-cycle": (PKG_CYCLE, ("import_cycle",)),
    "module": ({"main.py": "import no_such_module_xyz\n"}, ("no_module",)),
    "not-package": ({"main.py": "import os.nosub\n"}, ("not_package",)),
    "attr-object": (
        {"main.py": "class T:\n    value = 1\nT().valu\n"},
        ("attr_object",),
    ),
    "attr-none": ({"main.py": "None.foo\n"}, ("attr_object",)),
    "attr-module": ({"main.py": "import os\nos.getcwdd\n"}, ("attr_module",)),
    "attr-type": ({"main.py": "class T:\n    pass\nT.missing\n"}, ("attr_type",)),
    "attr-shadow": (
        {"random.py": "x = 1\n", "main.py": "import random\nrandom.randint(1, 2)\n"},
        ("attr_module", "attr_shadow"),
    ),
    "positional": ({"main.py": "def f(a):\n    pass\nf(1, 2)\n"}, ("positional",)),
    "method": (
        {"main.py": "class C:\n    def m(self, a):\n        pass\nC().m(1, 2)\n"},
        ("positional",),
    ),
    "operand": ({"main.py": "x = {'a': {}}\nx['a'] + 1\n"}, ("operand",)),
    "keyword": ({"main.py": "def f(alpha):\n    pass\nf(alpah=2)\n"}, ("keyword",)),
    "invalid": ({"main.py": "x = = 1\n"}, ("invalid_syntax",)),
    "colon": ({"main.py": "if True\n    pass\n"}, ("invalid_syntax", "expected_colon")),
    "closed": ({"main.py": "x = (1,\n"}, ("eof", "never_closed")),
    "comma": ({"main.py": "x = [1 2]\n"}, ("invalid_syntax", "comma")),
    "indent": ({"main.py": "x = 1\n    y = 2\n"}, ("unexpected_indent",)),
    "block": (
        {"main.py": "def f():\nreturn 1\n"},
        ("indented_block", "indented_block_after"),
    ),
    "unindent": ({"main.py": "if True:\n        x = 1\n    y = 2\n"}, ("unindent",)),
    "tab": ({"main.py": "if True:\n\tx = 1\n        y = 2\n"}, ("tabs",)),
}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("minor", INTERPRETERS)
def test_each_snippet_matches_its_template_and_passes_the_closure(
    tmp_path: Path, minor: int, case: str
) -> None:
    files, expected = CASES[case]
    worktree = Path(os.path.realpath(tmp_path))
    for rel, text in files.items():
        (worktree / rel).parent.mkdir(parents=True, exist_ok=True)
        (worktree / rel).write_text(text)
    python = FOUND[minor] or f"python3.{minor}"
    env = {"PATH": os.environ["PATH"], "TERM": "xterm-256color"}
    done = subprocess.run(  # nosec B603
        [python, "-E", "-s", "main.py"],
        cwd=worktree,
        env=env,
        capture_output=True,
        timeout=60,
    )
    last = done.stderr.decode().strip().splitlines()[-1]

    crash = parse_traceback(done.stderr)
    assert crash is not None and f"{crash.exc_type}: {crash.message}" == last
    matched = [t for t in TEMPLATES if t.matches(crash.exc_type, crash.message or "")]
    assert [t.id for t in matched if t.since <= minor <= t.until] == [
        t.id for t in matched
    ], f"{last!r} matched outside its version range"
    assert len(matched) == 1 and matched[0].id in expected, last

    sources = {rel: text for rel, text in files.items()}
    feedback = classify(
        RunFailure("x", kind="exit", exit_tail=done.stderr, workload_id="w"),
        closure=ClosureIndex.build("", sources),
        worktree=worktree,
        tracked=tuple(files),
        touched=(),
    )
    assert feedback is not None
    # 3.8-3.9 put an EOF one line past the file's end: that frame is dropped
    assert feedback.frames or feedback.template == "eof"
    assert feedback.message is not None, (last, feedback.withheld)
    assert "/" not in feedback.message and str(worktree) not in feedback.render()


def test_every_template_has_a_live_case() -> None:
    covered = {template for _, expected in CASES.values() for template in expected}
    assert covered == set(BY_ID)
