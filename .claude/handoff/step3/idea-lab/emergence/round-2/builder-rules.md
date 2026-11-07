# Step 3 Wave 2 builder rules (binding for every unit)

You are a Builder on the Step 3 team of the Autonomous AI Platform. The worktree is /home/user/step3-idea-lab (branch claude/step3-idea-lab); the service is /home/user/step3-idea-lab/services/python_agents (run everything from there with `uv run ...`). Never touch /home/user/autonomous-ai-platform.

READ FIRST:
- The spec /home/user/step3-idea-lab/.claude/handoff/step3/spec-idea-lab.md (the idea-lab amendment, revision 4, approved by the owner with changes as O23-O37 in STATUS.md), on top of spec.md and spec-wave2-ideas.md in the same folder. Read the idea-lab spec's section for your unit, section 5 (security scope, O28), section 7 (your unit's row), and every D and O your unit cites (STATUS.md 'Decisions').
- Engine conventions: services/python_agents/CLAUDE.md. STATUS.md "Lessons" (Step 3 Wave 1) and "Technical Debt".
- Re-read every file:line the spec cites for your unit before you change it; if the code disagrees with the spec, follow the code's reality, keep the spec's intent, and say so in your report.

HARD RULES
- Edit ONLY the files your unit owns (its row). Other Builders edit other files in the same worktree at the same time: never edit, format, stage or revert their files. Never run git add, commit, stash, reset or checkout; the Lead commits.
- TDD: write the failing tests first and run them to show they fail with at least one real assertion failure (not only an ImportError), keep the command and last lines, then write the code, then show them pass.
- No live runs: never `-m live`, never the Anthropic API (count_tokens included). When you override addopts keep `-m "not live"`.
- Always set a private coverage file: `COVERAGE_FILE=/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/cov.<your-unit>` on every pytest run, and pass `-p no:cacheprovider`. Shared .coverage files clash between Builders.
- Gate before you report, from the service dir: `uv run ruff check . && uv run ruff format --check . && uv run mypy src tests` and `TEST_DATABASE_URL=postgresql://dev:devpass@localhost:5432/postgres uv run pytest -q` (coverage stays 100 % line and branch; start Postgres with `pg_ctlcluster 16 main start` if it is down). Also run `/home/user/autonomous-ai-platform/node_modules/.bin/prettier --check <every .json/.md/.ts/.js file you added or changed>` (CI's Lint Code runs prettier). Other Builders' work in progress may break the full suite: if a failure is in a file you do not own, say which and run your own tests plus the suites your files touch.
- Run formatters only on your own files (never repo-wide).
- mypy strict, no Any, frozen pydantic models with extra="forbid", parameterized SQL only, no secrets.
- Size: about the source lines your row states (tests counted separately). If you pass 1.5x the row, stop and report why instead of continuing.
- Mutation checks (if you do any) run only on scratch copies under the scratchpad, with `-o pythonpath=<copy>/src` (pyproject's pythonpath overrides PYTHONPATH) and a canary test proving the copy is the one imported.
- Lessons that bite: CI runs the workload and the venv on CPython 3.11 while the local venv is 3.13 — a memory- or version-sensitive fixture must also be checked with `PATH=<dir with python -> 3.11>:$PATH .venv/bin/python -m pytest ...` (uv's 3.11 is at /root/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11); timing floors and guards need about 2x margin over what CI measures; local timing under concurrent Builders is unreliable (report such a failure as load, not as a pass).

SEAMS CHECKLIST (answer each in your report): fixtures above the tests; real-vs-fake swap points (name each fake and the real thing it stands for); root vs non-root behaviour; what only CI, macOS or a live run proves.

REPORT (your final message): files changed with line counts (source and tests separately); red-then-green evidence (commands and last lines); the gate's last lines; spec deviations and why; the seams answers; risks.
