# Step 2 persistence and E2E research report

**Setup.** I started the local PostgreSQL 16.15 cluster and left it running. Role `dev` (a superuser) and database `ai_platform` already existed, with 001-003 applied. I ran the experiments in a scratch database, `persist_lab`, and dropped it afterwards. The repo is unmodified; `git status` is clean. Running pytest regenerated the git-ignored `coverage.xml` and `htmlcov`.

- **pgvector:** 0.6.0 is installed, and `CREATE EXTENSION vector` works.
- **psycopg:** it is not in the project venv. `uv.lock` pins psycopg 3.3.6 under the `database` extra, and CI syncs only `--extra dev`. I used a throwaway venv instead: Python 3.11.17, psycopg 3.3.6 (binary build), pydantic 2.14.1, langgraph 1.2.16.

**Scratch files** (all under `.claude/handoff/step2/persist/`):
- `.../persist/004_engine_repository.sql`
- `.../persist/pg_repo.py` (prototype; passes `mypy --strict` except two unused ignores)
- `.../persist/contract/` (conftest, plus the contract tests unchanged and adjusted)
- `.../persist/fullrun/` (full engine run through Postgres, and the checkpointer test)
- `.../persist/fixture/` (the fixture repo and the hypothesis edits)
- `.../persist/measure_fixture.py`

## A. Postgres Repository

**What I verified against PG 16**

1. **Schema.** 001→003 apply cleanly, and running 003 again changes nothing.
2. **Contract tests, unchanged.** `tests/persistence/test_repository.py` run against the prototype: 10 of 13 pass. The 3 lesson tests fail because `"project-a"` is not a UUID, and `lessons.project_id` is a UUID foreign key to `projects`.
3. **Contract tests, builders changed.** Lesson projects are now registered through `save_run` and use uuid4 ids; no assertion changed. All 26 pass (13 in-memory, 13 Postgres) at `-n 2`.
4. **Bug in the real loop.** In a run without the approval gate, the learn node's `save_lesson` runs before the Orchestrator's only `save_run`. The result is `ForeignKeyViolation: lessons_project_id_fkey`. I reproduced it with the conftest H1-H3 scenario. The gated H1-H4 run only passes because pausing saves the run first. Calling `save_run(initial_state)` before the graph starts fixes it (verified), and also leaves an audit row with status `pending` if a run crashes.
5. **Python 3.11 trap.** `TypeAdapter(EngineState)` raises `PydanticUserError` on 3.11 because state.py uses `typing.TypedDict`, but it works on 3.13. So it would pass locally and fail in CI. Building one adapter per key works on both versions. The full H1-H4 final state (4 trials, 4 verdicts, 4 lessons, 15 events, approval, delivery) comes back equal with `==`.
6. **JSONB limits.**
   - Postgres rejects inf and nan: `invalid input syntax for type json`.
   - Floats of 1e16 or more come back from JSONB as Python `int` (1e300 returns as an int). Pydantic converts them back for float fields, but inside `ScalarDict` values the type changes.
7. **Duplicate project path.** A new Project id with an existing `root_path` raises `UniqueViolation projects_root_path_key`. The Step 4 CLI must look up and reuse the project by root path.
8. **Concurrent writes.** 8 threads saved 80 trials twice each into one run. All 80 came back unique and at their latest version, so no updates were lost (the conflicting row is locked during the update).
9. **Connection cost.** About 20 ms per connection, so opening one per call is fine for Step 2.

**Table and column mapping**

| Method | Storage | Key / order |
|---|---|---|
| save_run | One transaction. Upsert `projects` (id, name, root_path, default_branch, language, hardware, created_at). Then upsert `task_executions` with thread_id=run_id, user_intent, status, phase, project_id, objective_ids, baseline, delivery, state, tokens_used, estimated_cost_usd, error_message, completed_at. It **never writes trials/verdicts**; save_trial and save_verdict own those columns. | `ON CONFLICT (thread_id)` |
| get_run | `state` where `thread_id = %s AND state IS NOT NULL` | n/a |
| save_trial / save_verdict | The `task_executions.trials` / `verdicts` JSONB arrays that 003 designed (`performance_metrics.trial_id` and `lessons.verdict_id` already point into them). Replace in place, or append. Creates a placeholder row if the run is unknown (the contract saves trials before any run). | array position = insertion order |
| save_lesson / list_lessons | `lessons`, typed columns matching `Lesson` field for field | `ON CONFLICT (id)`, `ORDER BY seq` |

**Columns that must be filled**
- The only NOT NULL column without a default is `task_executions.user_intent`. I fill it with the objective descriptions joined, falling back to "make it better"; Step 4's `--goal` text replaces this later.
- `projects`: `name` and `root_path` (UNIQUE).
- `lessons`: `outcome` and `text`.

**CHECK constraints to respect**
- `chk_status`: connect→pending, done→success, failed→failed, anything else→running.
- `chk_task_phase`: the RunPhase value.
- tokens_used and cost ≥ 0; lesson weight > 0.
- `estimated_cost_usd` is DECIMAL(10,4), so it is only a rounded copy; the exact cost stays in `state`.

**Migration 004** (verified idempotent: the catalog snapshot diff after a second run is empty; it adds no tables):
```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_thread ON task_executions(thread_id);
ALTER TABLE lessons ADD COLUMN IF NOT EXISTS seq BIGINT GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS uq_lessons_seq ON lessons(seq);
ALTER TABLE lessons ALTER COLUMN gain TYPE DOUBLE PRECISION,
                    ALTER COLUMN weight TYPE DOUBLE PRECISION;
```
Why each part is needed:
- `ON CONFLICT (thread_id)` needs a unique index. Keep 003's non-unique `idx_task_thread`: dropping it would make a re-run of 003 on its own recreate it and break the CI diff.
- `created_at` is when the model was built, not when it was saved. The contract saves a, global, b after building global first, so insertion order needs `seq`.
- REAL is 4-byte: 0.4167 comes back as 0.41670000553131104 and `==` fails.

**Verified SQL**
```sql
-- run (projects upsert runs first in the same transaction: ON CONFLICT (id) DO UPDATE all but created_at)
INSERT INTO task_executions (thread_id, user_intent, status, phase, project_id, objective_ids,
  baseline, delivery, state, tokens_used, estimated_cost_usd, error_message, completed_at)
VALUES (%(run_id)s, %(user_intent)s, %(status)s, %(phase)s, %(project_id)s, %(objective_ids)s,
  %(baseline)s, %(delivery)s, %(state)s, %(tokens_used)s, %(cost_usd)s, %(error)s, %(completed_at)s)
ON CONFLICT (thread_id) DO UPDATE SET user_intent = EXCLUDED.user_intent, status = EXCLUDED.status,
  phase = EXCLUDED.phase, project_id = EXCLUDED.project_id, objective_ids = EXCLUDED.objective_ids,
  baseline = EXCLUDED.baseline, delivery = EXCLUDED.delivery, state = EXCLUDED.state,
  tokens_used = EXCLUDED.tokens_used, estimated_cost_usd = EXCLUDED.estimated_cost_usd,
  error_message = EXCLUDED.error_message, completed_at = EXCLUDED.completed_at;
-- trial (verdict: same with verdicts)
INSERT INTO task_executions (thread_id, user_intent, status, trials)
VALUES (%(run_id)s, %(placeholder)s, 'running', jsonb_build_array(%(item)s))
ON CONFLICT (thread_id) DO UPDATE SET trials = CASE
  WHEN task_executions.trials @> jsonb_build_array(jsonb_build_object('id', %(item_id)s::text))
  THEN (SELECT jsonb_agg(CASE WHEN e->>'id' = %(item_id)s THEN %(item)s ELSE e END ORDER BY i)
        FROM jsonb_array_elements(task_executions.trials) WITH ORDINALITY AS t(e, i))
  ELSE task_executions.trials || jsonb_build_array(%(item)s) END;
-- lesson upsert: ON CONFLICT (id) DO UPDATE SET every column except id and seq
SELECT id::text AS id, project_id::text AS project_id, verdict_id::text AS verdict_id,
       hypothesis_id::text AS hypothesis_id, technique_id::text AS technique_id,
       context, outcome, gain, text, weight, created_at
FROM lessons WHERE project_id IS NULL OR project_id = %(project_id)s ORDER BY seq;
```
Parameters are wrapped as `Jsonb(model.model_dump(mode="json"))`, ids as `uuid.UUID(...)`, and enums as `.value`. A filter id that is not a UUID returns only the global lessons; saving an id that is not a UUID raises `ValueError`.

**Rebuilding typed state from JSONB**
```python
_ADAPTERS = {k: TypeAdapter(t) for k, t in get_type_hints(EngineState).items()}
dump = {k: a.dump_python(state[k], mode="json") for k, a in _ADAPTERS.items()}
load = cast(EngineState, {k: a.validate_python(raw[k]) for k, a in _ADAPTERS.items()})
```
Check that the key sets match exactly in both directions. Datetimes, enums and tuples all come back typed.

RECOMMENDATION:
- Keep trials and verdicts in the 003 JSONB arrays, and ship migration 004 above.
- Make `PostgresRepository(dsn)` open one connection per call and use only literal SQL constants.
- Have `Orchestrator.run`/`stream` call `save_run(initial_state)` first.
- Change only the contract builders to registered uuid projects.
- Set `allow_inf_nan=False` on `EngineModel`.

## B. Testing strategy

- **Marker.** Register a `postgres` marker in pyproject (`--strict-markers` requires it).
- **Session fixture `pg_dsn(worker_id)`.**
  - Skip when `TEST_DATABASE_URL` is unset.
  - Otherwise create `<db>_<worker_id>` (`DROP ... WITH (FORCE)` and `CREATE`, using `psycopg.sql.Identifier` and autocommit).
  - Apply every `infrastructure/schema/*.sql` in name order with `conn.execute(path.read_text())`. With no parameters psycopg sends the file as a simple query, so multiple statements and `DO $$` blocks work (verified).
  - Drop the database at the end of the session.
- **Schema-per-test does not work.** 003's guards hard-code `'public.performance_metrics'::regclass` and `connamespace = 'public'`.
- **Per-test cleanup.** Run `DELETE FROM` on the 9 engine tables, children first: 23 ms, against 115 ms for `TRUNCATE ... CASCADE`.
- **Timings.** Setting up each worker took 0.75–0.87 s. The 26 contract tests took 5.7 s at `-n 2` and 3.6 s serially. Without a database, 13 skipped in 0.18 s. One database per worker keeps xdist safe.
- **Misconfiguration.** If `TEST_DATABASE_URL` is set but pgvector is missing, fail instead of skipping. On macOS, use `brew install pgvector` or docker compose.
- **Coverage.** Today it is 1431/1431 lines and 280/280 branches. A Postgres module of about 130 statements, uncovered on a machine without a database, would drop coverage to roughly 92–93% before the other Step 2 code is counted. So CI must run these tests.
  - The stage gate should export `TEST_DATABASE_URL` when a database is reachable and print a loud warning otherwise.
  - No `pragma: no cover`.

RECOMMENDATION: Use the env-gated `postgres` marker, one database per xdist worker built from the real migration files, and DELETE between tests. CI always sets `TEST_DATABASE_URL`, so the Postgres repository is covered there.

## C. LangGraph durable checkpointer

**Package status (PyPI)**
- `langgraph-checkpoint-postgres` 3.2.0, published 2026-10-14. Needs langgraph-checkpoint ≥4.3.0 and <5, psycopg ≥3.2, psycopg-pool ≥3.2 and orjson. The previous release, 3.1.3, came out 2026-10-12.
- `langgraph-checkpoint-sqlite` 3.1.2, published 2026-10-12; needs aiosqlite and sqlite-vec.
- `uv pip compile` against our pins (langgraph 1.2.16, checkpoint 4.3.0, psycopg 3.3.6) resolves, adding psycopg-pool 3.3.3 and orjson 3.13.0.

**Tested on real PG**
- `PostgresSaver(conn, serde=JsonPlusSerializer(allowed_msgpack_modules=ENGINE_SERDE_ALLOWLIST))` with `setup()` works.
- A run paused at approval, then a new connection, saver, Orchestrator and repository resumed it to `done`. `Trial` objects come back as model instances.
- **Problem:** after loading, `state["phase"]` is a plain `str` (`'verdicts'`), not a `RunPhase`. The saver stores `None/str/int/float/bool` values directly in its JSONB column instead of serialising them, and a `StrEnum` counts as a `str`. Run side by side, `InMemorySaver` keeps the `RunPhase`. Comparing with `==` still works; comparing with `is` breaks.
- I did not test the sqlite saver.

RECOMMENDATION: Step 2 does not need it; resuming a paused run in another process is a Step 4 CLI feature. When it is added, re-type the snapshot values through the per-key adapters from A, add an E2E test that uses `PostgresSaver`, and prefer a release that is at least two weeks old.

## D. E2E fixture

**Layout.** `tests/fixtures/dedupe_repo/` contains:
- `dedupe_fixture/{__init__,data,core,__main__}.py`
- `tests/{__init__,test_core}.py`, using stdlib `unittest` so a trial does not need pytest

The scripted edits live in `tests/fixtures/dedupe_edits/<hypothesis>/<relpath>`.

**Workload.** `python -m dedupe_fixture` with the default count of 10,000. Input comes from a 64-bit LCG, so it is deterministic on every platform. It prints three lines: `items=… unique=…`, `head=[…]`, and `checksum=…`, an order-sensitive hash modulo 2^61−1. The hot spot is `unique_in_order`, which checks membership in a `list`. The fixture passes ruff, ruff format and `mypy --strict` (verified).

**Hypotheses**
- **H1** (`set`): expected **keep**.
- **H2** (`set`, plus deleting one test): expected **reject** for a protected path. Its tests still pass, so only the anti-cheat check catches it.
- **H3** (`sorted(set(items))`): expected **reject** for output equivalence. The suite checks set semantics but not order on purpose, so only the fingerprint catches it.

**Measured timings.** Python 3.11, warm-up plus 5 runs, `perf_counter`, with CPU time and peak RSS from `os.wait4`. Each hypothesis ran in its own `git worktree`.

| Run | Wall mean | Stdev | CPU time | Peak RSS | Speedup | Tests | Output same |
|---|---|---|---|---|---|---|---|
| baseline | 407.1 ms | 20.5 | 401 ms | 16.6 MiB | n/a | pass | n/a |
| H1 set | 51.3 ms | 5.7 | 50 ms | 16.6 MiB | **7.9×** | pass | yes |
| H2 set + test edit | 50.0 ms | 3.7 | 48 ms | 16.6 MiB | 8.1× | pass | yes; touched `tests/test_core.py` |
| H3 sorted | 59.0 ms | 9.3 | 58 ms | 16.6 MiB | 6.9× | pass | **no** |

- **Noise floor:** max(2×20.5, 2×5.7, 2% of 407) = 41 ms, against a gain of 356 ms (8.7× the floor).
- **Repeats:** the second run gave 429 ms against 53 ms (8.1×). Pinned to 2 cores with a competing CPU load: 390 ms against 51 ms (7.6×). On 3.13 with one outlier (stdev 88 ms): floor 177 ms against a gain of 432 ms, so it still clears.
- **Harness time:** baseline plus 3 trials plus 4 test suites took 3.8–3.9 s. With the combine re-test, expect about 5 s per E2E scenario.

**Scripted editor.** A `ScriptedEditor`, keyed by hypothesis title the way `StubTrialRunner` is, copies the edit files into the worktree. The runner then runs `git add -A` and commits, and computes `diff` and `touched_paths` from git, not from the editor.

**Security finding.** Plain `git diff --name-only` shows only the destination of a rename. Moving `tests/test_x.py` to `src/helper.py` showed only `src/helper.py`, which gets around the protected-path check. With `--no-renames` both paths appear (verified). Use `git diff --name-only --no-renames <base>..HEAD`.

**Other notes**
- Add `collect_ignore_glob = ["fixtures/*"]` in `tests/conftest.py`; otherwise the fixture's `test_core.py` is collected by the engine suite.
- Exclude `tests/fixtures/` from mypy (it adds a second `tests` package).
- Copy the fixture with `ignore_patterns("__pycache__")`.
- Run trials with a minimal env: `PATH`, `PYTHONDONTWRITEBYTECODE=1`, `PYTHONHASHSEED=0` and `LC_ALL`, so no secrets reach them.
- **Network off:** `unshare -rn` gives `ENETUNREACH`, and the fixture runs fine inside it. ubuntu-24.04 images may block unprivileged user namespaces (not verified). macOS has no `unshare`, so the runner must degrade explicitly, and the E2E must not depend on network isolation.
- `ru_maxrss` is in KiB on Linux and in bytes on macOS.
- **Gap:** the models have no test command for the `tests_pass` guardrail.

RECOMMENDATION: Ship this fixture and its three edits. Keep E2E assertions on verdict outcomes, not timings (the margin is about 8×). Take touched paths from git with `--no-renames`. Give the runner a `test_command` (`python -m unittest discover -s tests -t .`) as a constructor argument for Step 2.

## E. CI changes

- **mypy:** replace `uv run mypy .` and its `continue-on-error` with a blocking `uv run mypy src tests`. It is clean today: 39 files, `Success`, 1.2–3.7 s.
- **Install:** `uv sync --frozen --extra dev --extra database`. psycopg is only in the database extra, and mypy needs it installed to check the Postgres module.
- **Python job service:** a `pgvector/pgvector:pg16` container (same env and health check as Schema Apply) with `TEST_DATABASE_URL: postgresql://dev:devpass@localhost:5432/ai_platform`.
- **Schema Apply:** the idempotence step re-applies only 003. Change it to re-apply 003 then 004, or every file in order. Compose Init's 14-table count is unaffected: 004 adds no tables, and saver tables appear only through `setup()`.
- **Budget:** the suite takes 14.2 s on 4 vCPU today. Postgres adds about 0.8 s per worker plus about 2 s of tests, and the E2E about 5 s per scenario. Pulling and starting the service is my estimate of about 15–30 s. Mark E2E tests `slow` and set the job's `timeout-minutes: 15`.

RECOMMENDATION: Make mypy blocking now (it is green), add the Postgres service and `--extra database`, extend the idempotence check to 004, and keep the job on ubuntu-22.04 while trials depend on `unshare`.