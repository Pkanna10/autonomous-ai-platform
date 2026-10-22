# Step 2 final spec: the real core loop on CPU Python workloads

This spec starts from **mvp-testability**, which both judges picked as the winner, and adds the judges' best ideas from the other two designs. It fixes every error the judges found, after checking each one against the code on master (`69a3da4`). This revision closes all 17 critic gaps. Tags `[G1]` to `[G17]` follow the order of the critic list and mark where each gap is closed.

Facts verified on this host for this revision (Linux 6.18, x86_64, git 2.43):
- Landlock returns ABI 7 through `ctypes` `syscall(444, NULL, 0, 1)`.
- Under `unshare -rn -p -f`, a ctypes Landlock ruleset allows writes inside the allowlist, refuses writes outside it with EACCES, leaves `/dev/null` writable and leaves reads alone.
- `lo` comes up with `SIOCGIFFLAGS`/`SIOCSIFFLAGS` (0x8913/0x8914) from inside the namespace.
- A connect from inside the namespace to a listener the parent holds on 127.0.0.1 fails with ENETUNREACH.
- `infrastructure/schema/001_initial.sql` uses a plain `CREATE TABLE packages` and `CREATE INDEX idx_packages_name`, so it is not idempotent.
- `lessons.hypothesis_id` and `lessons.technique_id` are UUID columns.
- `projects.root_path` is `UNIQUE`.
- `EngineError` and `DeliveryError` currently live in `orchestrator/nodes.py:139`.
- The anticheat matcher is the private `_matches` (`anticheat.py:77`).
- `TestSuiteJudge` returns `not_applicable` when there is no `tests_pass` guardrail, and `inconclusive` when there is one but no `tests_passed` row.

## 0. Decisions

Each line gives the decision, then the first-principles reason for it.

1. **Base design: mvp-testability.** Every external effect sits behind a Protocol with a deterministic fake, and it scored highest (39 and 40).
2. **Confine writes in the launcher** under `FS_ISOLATION=required`: Landlock ABI ≥1 on Linux, through `ctypes` syscalls (mechanism in §4 Sandbox), and a `sandbox-exec` file-write deny on macOS. Claude-steered code would otherwise run with the user's write access. A fresh HOME is not a sandbox, and the worktree's `.git` file names the user's gitdir. This host verified the mechanism (see the facts above). `[G12]`
3. **Network: `unshare -rn -p -f`** on Linux, with the launcher bringing `lo` up, and `sandbox-exec (deny network*)` on macOS. No Landlock TCP rules: the namespace already blocks TCP and UDP, and Landlock TCP needs ABI 4 (kernel ≥6.7). Verified here: `lo` comes up inside the namespace, and the parent's loopback is unreachable from it.
4. **PID namespace.** `setsid` orphans die with the launcher (verified: 0 survivors). The launcher is PID 1 in its namespace and reaps its children.
5. **The launcher is a real stdlib-only module, `execution/launcher.py`,** run by path as `python -I -S`. That makes it lintable, typed and importable for in-process tests. A fresh interpreter also keeps the RSS floor at 6.5 MiB instead of 311 MiB.
6. **Build the macOS wrapper now and run it in a `macos-latest` CI job** against `/usr/bin/git`. This catches the maxrss units, Apple git 2.39 and sandbox profile (SBPL) semantics before the M4 dogfood.
7. **Combine with plain `git merge-tree --write-tree ACC X`** (no `--merge-base`) and a single-parent `commit-tree`. `--merge-base` needs git 2.40 and Apple ships 2.39. Every trial's parent is `base`, so the natural merge base is already `base`. History stays linear, with one revertable commit per change.
8. **Git floor 2.38.** Use `--attr-source=<empty tree>` only on git ≥2.40, and always add an empty override for each driver key. This works on Apple git.
9. **SDK `max_retries=0` plus our own retry loop.** anthropic 1.17 sets `DEFAULT_MAX_RETRIES=2` and retries timeouts without telling us, so without this the cap is not a real bound. Policy `[G14]`:
   - Retry only `LLMUnavailable`: HTTP 429, 529, 500, 502, 503, 504, plus timeouts and connection errors.
   - At most `LLM_MAX_RETRIES` extra attempts.
   - Exponential backoff `min(30 s, 1 s · 2^k)`, with a numeric `retry-after` as a floor. A `retry-after` above 60 s ends the loop with `LLMUnavailable`.
   - `Budget.check(estimate)` before every attempt.
   - Each timeout or connection-error attempt is charged the full pre-send estimate. An HTTP error response is charged 0, because it carries no usage.
   - 400, 404 and 413 raise `LLMRequestError` at once. 401 and 403 raise `LLMConfigError`.
10. **`budget_usd` is a required keyword, and the trials node keeps a running total inside its loop.** Today the sum is computed after the loop, so each of 3 trials is offered the full remainder and a run can spend up to 3× the cap. A runner trial whose `cost_usd` is above `budget_usd` is untrustworthy. The loop stops before a trial when `remaining ≤ 0` or `remaining < min_trial_budget_usd`. The factory sets `min_trial_budget_usd` to one worst-case editor request; a trial that cannot afford one request would only fail at its first `Budget.check`. `[G8]`
11. **New state key `budget_exhausted`; the router then goes straight to combine.** Otherwise the `proposed` hypotheses left behind spin empty rounds until `max_rounds`.
12. **Capture violations go into `Trial.violations`, with status `failed`.** `_RUNNER_STATUSES` stays `{measured, failed}`, so the Step 1 contract test `[rejected]` still holds. Verdict rule 1 still rejects.
13. **New capture rules**, each defined in §4 Capture rules `[G9]`:
    - `forbidden_file_mode`: symlink, gitlink, an unusual mode, or a mode change.
    - `forbidden_file`: write-deny paths such as compiled artefacts, or binary blobs.
    - `git_metadata`: `.git` path components, `.gitattributes`, `.gitmodules`, `.lfsconfig`.
    - `unrecorded_write`: a touched path the editor did not report writing.
    - `process_spawn`.

    There is no `lfs_path` rule: LFS repos are refused at connect.
14. **`process_spawn` is an AST scan of the changed `.py` files**, applied when `cpu_time_s` or `peak_rss_bytes` is judged. It looks for imports of multiprocessing, concurrent.futures or subprocess; `os.fork`/`spawn*`/`posix_spawn*`/`exec*`; and any `__import__` or `importlib.import_module` call. Splitting work across processes fakes a per-process RSS win. A regex would flag comments and miss `posix_spawn`. It is documented as a guard against honest mistakes, not a defence.
15. **No judge changes.** Nondeterministic output under an equivalence guardrail, and a failing baseline test suite, both fail closed at the baseline node. The judges are frozen, and failing before the trials spends no money.
16. **User-repo fingerprint (F0/F1).** `[G1]`
    - **What it covers:** `config`, `config.worktree`, `hooks/` and `info/` in the git common dir, the HEAD symref, and `for-each-ref refs/heads refs/tags`.
    - **What it excludes:** the index, status, remotes and logs. IDEs rewrite the index and auto-fetch remotes; what tampering would change is refs, config and hooks.
    - **Where it runs:** around every phase that executes repo code (baseline, profile, each trial, combine).
    - **The trial's own ref:** a trial creates or re-points exactly one ref, `refs/heads/engine/trial-<run>-<hyp>`. Both that trial's F0 and F1 are computed with that one ref excluded. After F1, the runner checks that the ref is absent (never committed) or points at `Trial.commit`. Excluding one named ref keeps every other ref, including earlier trials' refs, under the fingerprint.
17. **Engine git calls on a worktree pass `--git-dir=<handle.gitdir> --work-tree=<wt>`.** `<handle.gitdir>` is read from the `gitdir:` line of the worktree's `.git` file right after `worktree add`, before any sandboxed run. It must resolve inside `<common>/worktrees/` and is stored on a `WorktreeHandle` together with the `.git` file's bytes. Git renames the admin dir on a collision (a second `baseline` becomes `worktrees/baseline1`), so the basename cannot be assumed. Sandboxed code can rewrite the `.git` link, which sits inside the writable worktree, to point a later `clean -ffdx` somewhere else, so the `.git` bytes are compared with the stored ones after every run. `[G10]`
18. **Keep `engine/trial-<run>-<hyp>` refs,** created only for committed trials. Trial ids are deterministic, `uuid5(branch@round)`, and an existing ref is re-pointed only when its commit's `Engine-Trial:` trailer matches. This honours the Step 1 branch contract, keeps trial commits alive for combine and inspection, and makes a re-executed node idempotent.
19. **Commit identity and dates come from the base commit.** A resumed run reproduces the same SHAs.
20. **`Project.test_command` lives on the model, plus a `projects.test_command` column,** so it survives a resume. The caller supplies it: Step 2 has no inference, the E2E builds it, and the Step 4 CLI takes a flag. Preflight raises `PreflightError` when a `tests_pass` guardrail exists and `test_command is None`. Otherwise `TestSuiteJudge` would be inconclusive on every trial and the run would silently yield nothing. With no test command and no `tests_pass` guardrail, `run_tests` is skipped and `TestSuiteJudge` is `not_applicable`. `[G4]`
21. **Protect `command[0]` and `test_command[0]` when they live inside the repo.** A harness is not the code under optimisation.
22. **Reset the measured worktree before every run (warm-up and timed),** identically for baseline and trial, so a workload cannot memoise results across runs.
23. **The cProfile profiler ships in Step 2,** together with an editable-install check on the profiled paths and an engine-owned `PYTHONPATH` prefix. It runs in its own `<run>/profile` worktree. PROFILE is the last stub on the measurement path. Without the check, a trial can silently measure the user's checkout, so a frame under `project.root_path` raises `EngineError`. `[G5]`
24. **Trials run serially.** Overlapping measurements disturb each other.
25. **Always ABAB re-test the combination, even with one change, and run the test suite on its tip.** `[G3]` `[G17]`
    - **Hold rule:** the combination holds iff `derive_verdict(transient_trial, synthetic efficiency hypothesis, judge_results, measurement_violations).outcome is keep`. That is verdict rules 1 to 6 unchanged: no violation, no failed judge, no inconclusive primary or guardrail judge, and the primary judge passed.
    - **Fallback:** if it fails, re-test the best single kept change once. "Best" is the highest `Verdict.gain`, ties broken by hypothesis id, and the candidate must not be the set that just failed.
    - **Both fail:** `kept_verdict_ids=[]`, so deliver sends `report_only`. The outcome goes into `Combination.summary` and the report. Lessons are unchanged, because the individual verdicts stand.
    - **Why:** only what reproduced against an interleaved baseline, with its tests run, gets delivered.
26. **A combine that applies two changes is proven in integration tests, not in the E2E.** The judges require every workload to clear the noise floor. On one workload, each of two independent changes removes at most its own share, so both cannot be ≥3×.
27. **`orchestrator/serde.py` with one TypeAdapter per state key.** `TypeAdapter(EngineState)` fails on Python 3.11, and Step 4 needs this to re-type `PostgresSaver` values.
28. **`save_run(initial)` runs before the graph starts.** This fixes the lessons foreign-key violation and leaves an audit row if a run crashes. A `UniqueViolation` on `projects.root_path` becomes `ProjectConflictError` (an `EngineError`) naming the existing project id and path. It propagates from `Orchestrator.run` before any node runs, so the caller sees an engine error rather than a psycopg error. `[G15]`
29. **Trials and verdicts stay in the 003 JSONB arrays; migration 004 adds no tables.** Verified idempotent.
30. **Postgres tests use an env-gated skip; `addopts` adds only `-m "not live"`.** CI always runs them, so coverage counts them.
31. **Operator notices are a text block carrying the per-trial nonce, placed after the tool results.** `role: system` mid-loop is used only after the live smoke test confirms the wire shape. That shape is unverified, and the caps are enforced in code anyway.
32. **`httpx2.MockTransport` is correct; the security judge was wrong.** anthropic 1.17 is built on httpx2 2.16, which exports `MockTransport` (verified in `.venv`).
33. **`Hotspot.tags` stays free-form.** Existing tests and lessons use other tags; a fixed vocabulary belongs to the Step 3 matcher.
34. **`BaselineRunner.measure` still returns a tuple.** Node-level checks report noise and nondeterminism, so the Step 1 tests stay unchanged.
35. **Close the STATUS item "judged trials state key"** as resolved: `round_trials` already does that job.
36. **CI stays on ubuntu-22.04.** A probe step fails loudly if `unshare` or Landlock is missing. If it fails, the job moves to 24.04 plus the AppArmor sysctl in the same PR; `REQUIRE_*` is never weakened.
37. **All engine error classes live in a new `common/errors.py` (U1, wave 0).** It holds `EngineError`, `DeliveryError`, `PreflightError`, `RepoTamperedError`, `BudgetExceeded`, `LLMConfigError`, `LLMUnavailable`, `LLMRequestError`, `ProjectConflictError` and `InvalidRecordIdError`. `orchestrator/nodes.py` re-imports `EngineError` and `DeliveryError`, so existing imports keep working. `clients/`, `execution/` and `persistence/` cannot import from `orchestrator/nodes.py` without a cycle. U10 (wave 2) maps an error that U12 (wave 3) raises, so the classes must exist first. `[G13]`
38. **Each phase owns its worktree.** The owners are the baseline runner, the profiler, each trial, and the combiner (for `combine` and `combine-base`). Each owner creates `<WORKTREE_ROOT>/<run>/<phase>`, `<run>/_scratch/<phase>` and `<run>/_probe/<phase>`. In `finally` it removes all three (`worktree remove --force`, then a contained `rmtree` fallback, then `worktree prune`) and then `rmdir`s `<run>` if it is empty. `BaselineRunner.measure` and `Profiler.profile` take `run_id` as a keyword. With one owner per path, nothing is guessed and nothing leaks; the E2E asserts this. `[G5]`
39. **The fallback chain is sent explicitly:** `fallbacks=[{"model": m} for m in ENGINE_FALLBACK_MODELS]` when `ENGINE_FALLBACKS` is on, and no field otherwise. The installed SDK's `BetaFallbackParam` requires `model`. The priced chain must equal the actual chain, or the pre-send estimate is not a bound. The estimate prices the worst model in the chain × the number of models in the chain (3 by default), so every model that could bill one iteration is counted. Unknown-model worst-case pricing in `response_cost` stays as a backstop. `[G6]`
40. **`ScriptedEditor` is keyed by hypothesis title, and candidate ids stay uuid4.** `PostgresRepository` raises `InvalidRecordIdError` (an `EngineError`) before any SQL for any non-UUID id bound for a UUID column (run, project, workload, trial, hypothesis, technique, lesson). `save_lesson` is the case the E2E would hit. `InMemoryRepository` keeps accepting any id, which the Step 1 tests rely on. `[G7]`
41. **The LFS refusal scans attribute sources directly, never through `check-attr`.** It reads every `.gitattributes` blob in the base tree, plus `<common>/info/attributes` and a root `.lfsconfig`, and looks for `filter=lfs`. The engine's own git calls set `core.attributesFile=/dev/null` and `--attr-source=<empty tree>`, which hide `.gitattributes` from `check-attr`. `[G11]`
42. **The launcher self-checks isolation on every run,** after applying it and before the timed exec.
    - **Writes:** an attempted `O_CREAT|O_EXCL` in `<run>/_probe/<phase>` must fail with EACCES or EPERM.
    - **Network:** a connect to a listener the parent holds on 127.0.0.1 must fail.
    - **Report:** `LaunchReport` carries `fs_isolated`, `net_isolated` and `error`, and `run_once` raises `RunFailure` when a `required` mode was not applied.
    - **Why:** the connect-time probe proves the host can isolate; only a per-run check proves this run was isolated, and it is platform-independent. `[G12]`
43. **`Workload.warmup_runs` is honoured (0 allowed); `Workload.inputs` is not passed in Step 2.** Connect emits a `workload_inputs_ignored` warning per workload whose inputs are non-empty. No channel is defined yet: env would collide with the allowlist, and argv already carries inputs. Baseline and trial ignore inputs alike, so the comparison stays valid. `[G16]`
44. **Path pattern constants and the matcher live in `common/paths.py` (U1).** These are `matches_pattern` (moved from `anticheat._matches`), `WRITE_DENY_PATTERNS`, `READ_DENY_PATTERNS` and `GIT_METADATA_NAMES`. The editor handler (U7) and the capture rules (U9) are built in the same wave and must use one definition. `[G9]`

## 1. Scope

**Step 2 delivers:**
- Preflight at connect.
- Real `GitBaselineRunner` and `GitTrialRunner`: one worktree per phase and per trial at the pinned `base_commit`, launcher measurement, sandbox (network, writes, PID) with per-run self-checks, timeouts, output caps and fingerprints.
- The cProfile profiler.
- The understand node and the Claude trial editor, under a hard per-run cost cap.
- Git-side anti-cheat.
- Greedy `merge-tree` combine with an ABAB re-test plus the test suite.
- Real `engine/run-<id>` delivery.
- `PostgresRepository` and migration 004.
- The `dedupe_repo` E2E running in CI, the CI changes, the docs and the stage gate.

**Deferred:**

| Item | Step |
|---|---|
| Playbook, papers, LLM-generated candidates (`ctx.candidates` stays) | 3 |
| CLI, `--max-cost`/`--goal`/`--test-command`, test-command inference, live log, streaming, hardware detection, `PostgresSaver` resume, `clean` command | 4 |
| M4 dogfood verification, submodules, LFS, held-out inputs, passing `Workload.inputs`, `metrics_file` (needs a protected evaluator), cgroup tree RSS | 5 |
| PR creation, package installs | L1/L3, later |

## 2. Architecture

```
Orchestrator.run(..., max_cost_usd) ─ save_run(initial) ─► Repository: InMemory | Postgres(004)
                                       (root_path clash → ProjectConflictError; non-UUID id → InvalidRecordIdError)
CONNECT    Preflight.check(project, workloads, guardrails): git>=2.38, refuse .gitmodules / filter=lfs
           (blob scan), tests_pass needs test_command, base=HEAD, dirty event, argv[0] absolute,
           extra_protected, sandbox probe (fail closed), worktree prune; inputs-ignored events
UNDERSTAND ClaudeUnderstander ─► call(transport, request, budget) ─► AnthropicTransport | ScriptedTransport
BASELINE   GitBaselineRunner: F0 → wt <root>/<run>/baseline → measure_workload + run_tests → F1 → remove
PROFILE    CProfiler: F0 → wt <root>/<run>/profile, untimed, same sandbox → hotspots
           (+ editable-install check) → F1 → remove
RESEARCH / HYPOTHESES   stubs (ctx.candidates)
TRIALS     GitTrialRunner (serial; node stops below min_trial_budget_usd):
           F0* → wt trial-<hyp> → CodeEditor(WorktreeEditor) → capture (--no-renames) → check_capture
           → commit + clean -ffdx → own trial ref → measure + tests → F1* == F0*, own ref == commit → remove
           (* fingerprint excludes only this trial's own ref)
JUDGES → VERDICTS (+trial.violations, deduped) → APPROVAL
COMBINE    GitCombiner: F0 → merge-tree + commit-tree (greedy) → wt combine + combine-base
           → ABAB + run_tests on tip → F1 → remove
           node: derive_verdict(...) is keep? → else fallback (best gain) → else kept=[] (report_only)
DELIVER    GitBranchPublisher: guard → not checked out → update-ref create-only
LEARN / WATCH   unchanged

run_once: probe listener 127.0.0.1:0 → Popen(start_new_session) [unshare -rn -p -f -- | sandbox-exec -p P]
          python -I -S launcher.py <fd> <spec-json> -- argv
          launcher (PID 1 in its namespace): lo up → no_new_privs → Landlock
          (writes: wt, _scratch/<phase>, /dev/null, /dev/shm) → self-check (_probe write, probe connect)
          → fork/exec → wait4 → JSON on fd
```

## 3. Interfaces

**Errors (`common/errors.py`, new, U1)** `[G13]`:
- `EngineError(Exception)` and `DeliveryError(EngineError)`, both moved from `nodes.py` and re-imported there.
- `PreflightError`, `RepoTamperedError`, `BudgetExceeded`, `LLMConfigError`, `ProjectConflictError` and `InvalidRecordIdError`, all `EngineError` subclasses.
- `LLMUnavailable` and `LLMRequestError`, plain `Exception` subclasses: transport outcomes the nodes map.

**Paths (`common/paths.py`, U1)** `[G9]`:
- `matches_pattern(path, pattern) -> bool`: case-insensitive, moved from `anticheat._matches`; anticheat imports it.
- `GIT_METADATA_NAMES = (".git", ".gitattributes", ".gitmodules", ".lfsconfig")`.
- `WRITE_DENY_PATTERNS = ("**/__pycache__/**", "*.pyc", "*.pyo", "*.so", "*.pyd", "*.dylib", "*.dll")`.
- `READ_DENY_PATTERNS`: the secret-file patterns from the editor research (`.env*`, `*.pem`, `*.key`, `id_*`, `.netrc`, …).

**Models (`common/models.py`):**
- `EngineModel` gets `allow_inf_nan=False`.
- `Project.test_command: tuple[str, ...] | None = None` (min length 1 when set).
- `Workload.output_file: str | None = None`, validated with `normalize_path`.
- `Trial.commit: str | None = None` and `Trial.violations: tuple[Violation, ...] = ()`.
- `Delivery.commit: str | None = None`.
- `ViolationRule` gains `forbidden_file_mode`, `forbidden_file`, `git_metadata`, `unrecorded_write` and `process_spawn`.
- New models:
  - `ModelPrice(input, output, cache_write, cache_read)`, USD per MTok.
  - `CandidateModule(path, reason)`.
  - `ProjectUnderstanding(language, summary ≤1500, entrypoints, workload_notes: dict[str, str], candidate_modules ≤10, served_by_model)`.
  - `CombineSkip(trial_id, reason, paths)`.
  - `Combination(base_commit, tip_commit, applied_trial_ids, skipped, judge_results, holds, fallback_trial_id, summary)`. `summary` records the greedy result, the fallback attempt and the final outcome.
- All new models join `ENGINE_MODEL_CLASSES`.

**State (`orchestrator/state.py`):**
- New keys, all present from the start: `base_commit: str | None`, `understanding: ProjectUnderstanding | None`, `max_cost_usd: float`, `combination: Combination | None`, `budget_exhausted: bool`, `extra_protected: list[str]`.
- `initial_state(..., max_cost_usd: float | None = None)` defaults to `settings.MAX_COST_USD`; a value below 0 raises `ValueError`.

**Settings (`common/config.py`):**

| Setting | Value |
|---|---|
| `ANTHROPIC_API_KEY` | `SecretStr \| None` |
| `ENGINE_FALLBACKS` | `True` |
| `ENGINE_FALLBACK_MODELS` | `("claude-opus-5", "claude-opus-4-8")`, sent verbatim as the request's `fallbacks` list `[G6]` |
| `MODEL_PRICING` | `dict[str, ModelPrice]`, from the research table (Haiku cache read = its input rate, an upper bound). The validator requires a price for `ENGINE_MODEL`, every `ENGINE_FALLBACK_MODELS` entry and `TRIAGE_MODEL`. |
| `NETWORK_ISOLATION`, `FS_ISOLATION` | `Literal["required", "best_effort", "off"] = "required"` |
| `WORKTREE_ROOT` | `~/.cache/aip/worktrees` |
| `GIT_EXECUTABLE` | `"git"` |
| `GIT_TIMEOUT_S` | 60 |
| `TEST_TIMEOUT_S` | 900 |
| Output limits | `MAX_OUTPUT_BYTES` 256 MiB, `OUTPUT_HEAD_BYTES` 64 KiB, `STDERR_TAIL_BYTES` 8 KiB, `MAX_DIFF_BYTES` 1 MiB |
| Editor limits | `EDITOR_MAX_TURNS` 16, `EDITOR_MAX_TOOL_CALLS` 40, `EDITOR_MAX_FILES` 10, `EDITOR_MAX_FILE_BYTES` 256 KiB, `EDITOR_MAX_TOTAL_BYTES` 1 MiB, `EDITOR_MAX_TOKENS` 16000 |
| `UNDERSTAND_MAX_TOKENS` | 8000 |
| `LLM_MAX_RETRIES` | 2 (extra attempts, so at most 3 in all) |
| `LLM_TIMEOUT_S` | 300 (SDK client timeout per attempt) |

**Protocols** (`execution/runner.py`, `execution/protocols.py`, `clients/budget.py`):
```python
class TrialRunner(Protocol):
    def run(self, hypothesis: Hypothesis, workloads: Sequence[Workload], baseline: Baseline, *,
            round: int, branch: str, budget_usd: float, brief: TrialBrief) -> Trial: ...
class BaselineRunner(Protocol):                                                        # [G5]
    def measure(self, workloads: Sequence[Workload], *, run_id: str,
                commit: str | None) -> tuple[Measurement, ...]: ...
# Stubs: StubBaselineRunner.measure(workloads, *, run_id=None, commit=None) accepts and ignores both;
# StubTrialRunner requires budget_usd and fails a scripted trial costing more than it.
# The real runners raise ValueError when commit is None.

@dataclass(frozen=True) TrialBrief(understanding, hotspots, protected: tuple[str, ...])
@dataclass(frozen=True) Change(status, old_mode, new_mode, path)
@dataclass(frozen=True) WorktreeHandle(path: Path, gitdir: Path, link_bytes: bytes)   # [G10]
@dataclass(frozen=True) PreflightReport(head_commit, dirty_entries, git_version, network, fs,
                                        workloads: tuple[Workload, ...], test_command, extra_protected)
class Preflight(Protocol):                                                             # [G4]
    def check(self, project, workloads, guardrails) -> PreflightReport                 # PreflightError
class Profiler(Protocol):                                                              # [G5]
    def profile(self, workloads, *, run_id: str, commit: str) -> ProfileResult         # hotspots, notes
class CodeEditor(Protocol): def edit(self, worktree: Path, task: EditTask, budget: Budget) -> EditResult
#   EditTask(hypothesis, brief, boundary)
#   EditResult(written: Mapping[str, int], cost_usd, tokens_used, stop, error)
#   written: repo-relative path -> bytes written; a deletion records 0
class ProjectUnderstander(Protocol):
    def understand(self, project, workloads, *, commit: str, budget: Budget) -> UnderstandResult  # understanding|None, notes
class Combiner(Protocol):                                                              # [G3] [G5]
    def combine(self, run_id: str, project: Project, base_commit: str,
                kept: Sequence[KeptChange], workloads: Sequence[Workload]) -> CombineMeasured
#   KeptChange(trial_id, hypothesis_id, verdict_id, commit, score, gain)
#   CombineMeasured(tip_commit, applied, skipped, baseline: tuple[Measurement, ...]  # A runs
#                   , combined: tuple[Measurement, ...])  # B runs + one tests_passed row per workload
class BranchPublisher(Protocol): def publish(self, project, branch, tip, base) -> str   # capped diff
class LaunchReport(TypedDict):                                                         # [G12]
    wall_ns: int; utime: float; stime: float; maxrss: int; exit: int
    fs_isolated: bool; net_isolated: bool; error: str | None
def repo_fingerprint(git: GitWorkspace, *, exclude_refs: frozenset[str] = frozenset()) -> str   # [G1]
Budget(cap_usd, spent_usd=0.0, tokens=0).check(estimate) / .record(usd, tokens)        # BudgetExceeded
```

**`NodeContext`** gains `preflight`, `understander`, `profiler`, `combiner` and `publisher`, each defaulting to `None`, which keeps the Step 1 behaviour. It also gains `min_trial_budget_usd: float = 0.0`, which must be ≥ 0. The factory sets it to `preflight_estimate(0, EDITOR_MAX_TOKENS, chain, MODEL_PRICING)`, one worst-case editor request. `[G8]`

**Clients:**
- `clients/transport.py`:
  - `LLMRequest`, `LLMTransport.send`.
  - `AnthropicTransport`, the only module that imports the SDK client. It is built with `max_retries=0` and `timeout=LLM_TIMEOUT_S`, and sends the explicit `fallbacks` list `[G6]`.
  - `ScriptedTransport` replays responses in order and fails the request when the queue is empty.
  - `call(transport, request, budget, *, sleep: Callable[[float], None], max_retries: int = settings.LLM_MAX_RETRIES)`, implementing decision 9 `[G14]`.
  - It imports its error classes from `common/errors.py`.
- `clients/cost.py`:
  - `chain(settings) -> tuple[str, ...]`: `(ENGINE_MODEL, *ENGINE_FALLBACK_MODELS)` when `ENGINE_FALLBACKS`, otherwise `(ENGINE_MODEL,)`.
  - `response_cost(usage, prices)` sums `usage.iterations` and prices an unknown model at the worst listed rate.
  - `preflight_estimate(prompt_tokens, max_tokens, chain, prices) = len(chain) × (prompt_tokens × max(input, cache_write) + max_tokens × output)`, using the worst rates in the chain.
  - `prompt_tokens` for a request is the UTF-8 byte count of its system, tools and messages JSON. That is an upper bound, because no text token covers less than one byte.

## 4. Behaviour

**Nodes:**

| Node | Step 2 behaviour (`None` seam → Step 1 behaviour) |
|---|---|
| connect | `preflight.check(project, workloads, guardrails)`. Sets `base_commit`, the resolved `workloads`, `project.test_command` (resolved) and `extra_protected`. Emits `dirty_tree_ignored` ("N uncommitted changes ignored; run measures <sha>") and the isolation modes (warning level unless both are `required`). Emits `workload_inputs_ignored` (warning) per workload with non-empty `inputs` `[G16]`. |
| understand | Builds `Budget(max_cost_usd, cost_usd)`. `BudgetExceeded` and `LLMConfigError` propagate as `EngineError`; any other failure sets `understanding=None` plus a warning. Cost and tokens are added to state. |
| baseline | `measure(workloads, run_id=run_id, commit=base_commit)` plus the existing completeness check. Then three new checks. With `output_equivalence` guarded, a `None` fingerprint raises `EngineError` ("nondeterministic or missing output: add a seed or `output_file`"). With `tests_pass` guarded, a baseline `tests_passed` below 1 raises `EngineError`. It also emits `noisy_host` per workload: smallest provable gain = max(NOISE_MULTIPLIER·CV, MIN_RELATIVE_GAIN), at warning level above 10% or when the mean is under 0.5 s. |
| profile | `profiler.profile(workloads, run_id=run_id, commit=base_commit)`. Emits `profile_skipped` for non-Python commands, `-c` or a non-zero exit. A profiled frame under `project.root_path` (outside the profile worktree) raises `EngineError` naming the path (editable install). |
| trials | Keeps a running `spent` inside the loop. Before each trial, `remaining = max_cost_usd − spent`. If `remaining ≤ 0` or `remaining < ctx.min_trial_budget_usd`, it starts no more trials, emits `budget_exhausted` and sets the flag `[G8]`. Otherwise the trial gets `budget_usd = remaining`, and its `cost_usd` is added to `spent` as soon as it returns. The brief carries the understanding, the hypothesis's hotspots and the protected patterns. `_runner_trial_problems` also refuses a trial whose `cost_usd > budget_usd`. |
| verdicts | `violations = dedupe(check_diff_all(touched, ctx.protected_patterns + extra_protected), trial.violations, completeness)`. |
| router | Unchanged, with one new check after approval: `budget_exhausted` → combine. |
| combine | See the step list below the table. `[G3]` `[G17]` |
| deliver | Unchanged rule: empty `kept_verdict_ids` → `report_only`. Otherwise `assert_safe_branch`, then `publisher.publish`; `combined_diff` = `git diff base tip`, capped. The report gains a "Run conditions" section: measured SHA, ignored dirty entries, isolation modes, noise floor, ignored inputs, `Combination.summary` (skips, fallback, final outcome), the definition of peak RSS, and the trial refs with a cleanup command. |

The combine node, step by step `[G3]` `[G17]`:
1. Turn the kept verdicts (after approval) into `KeptChange`s, ordered by score descending, then hypothesis id.
2. Call `combiner.combine`.
3. Judge the result with `ctx.judges`:
   - The baseline is `Baseline(commit=base, measurements=CombineMeasured.baseline, objectives=…, guardrails=…)`, the last two copied from the state baseline.
   - The trial is a transient `Trial(hypothesis_id=<synthetic id>, branch=engine/run-<id>, status=measured, measurements=combined)`.
   - `found = measurement_violations(combined, …)`.
4. `holds = derive_verdict(trial, synthetic Hypothesis(change_class=efficiency), results, found, primary_metric=<same as the verdicts node>).outcome is keep`. Neither the transient trial nor the synthetic hypothesis is stored. Approval was already given per change, so efficiency is the right class.
5. If it fails, call `combine` once more with the single best kept change: highest `gain`, then hypothesis id, never the set that just failed. Judge it the same way.
6. Set `kept_verdict_ids` to the applied changes' verdict ids if a test held, otherwise `[]`. Set `combination` with `holds`, `fallback_trial_id` and `summary`. Lessons are untouched.

**Orchestrator.** `run` and `stream` take `max_cost_usd` and call `save_run(initial)` first. An `EngineError` from it (for example `ProjectConflictError`, `InvalidRecordIdError`) propagates before the graph starts. `[G15]`

**Preflight (`execution/preflight.py`).** Raises `PreflightError` when:
- git is older than 2.38;
- `.gitmodules` exists at base;
- LFS is configured `[G11]`. The check reads attribute sources directly with the engine's normal `-c` and env overrides but no `--attr-source`: every `.gitattributes` blob in `ls-tree -r -z <base>` (any depth, through `cat-file blob`), `<common>/info/attributes`, and a root `.lfsconfig`. A `filter=lfs` attribute in any of them, or a `.lfsconfig` file, refuses the repo;
- a `tests_pass` guardrail exists and `project.test_command is None` `[G4]`;
- git reports dubious ownership (never `safe.directory='*'`);
- an isolation mode is `required` and its probe fails. The probe runs `<wrapper> true` plus a Landlock or SBPL write test and a loopback connect test through the real launcher.

It also resolves `command[0]` and `test_command[0]` the same way. A bare name is looked up on a PATH with relative entries removed and must resolve to an absolute executable. A repo-relative path (for example `run.sh`, `scripts/bench`) is kept relative to the worktree and added to `extra_protected`. It ends with `worktree prune`.

**Process runner (`execution/procrun.py`).** `run_once(argv, cwd, env, sandbox, timeout_s, caps) → RunSample`:
- Opens a probe listener on `127.0.0.1:0` (backlog 1) and passes its port, the `_probe/<phase>` dir and the policy in the spec JSON. The listener is closed after the run.
- `Popen(start_new_session=True, close_fds=True, stdin=DEVNULL, pass_fds=(w,))`.
- A watchdog thread sends SIGKILL to the group on timeout.
- A blocking `os.wait4` on the wrapper, then `returncode` is set by hand.
- Wall time, CPU time and maxrss come from `LaunchReport`; maxrss × `maxrss_scale(platform)` (1024 on Linux, 1 on darwin).
- Raises `RunFailure` when `report.error` is set, when `fs=required` and not `fs_isolated`, or when `network=required` and not `net_isolated` `[G12]`. Under `best_effort` the flags go into `Measurement.hardware`.
- After every run, `killpg`, then poll until ESRCH (3 s cap, then an event).
- Reader threads stream sha256 over all of stdout, keep its first 64 KiB, and keep the last 8 KiB of stderr; above 256 MiB the group is killed with "output flood".

**Sandbox (`execution/sandbox.py`, `execution/launcher.py`).** `[G12]`
- `child_env`: an allowlist plus deny patterns, which win even over user extras. Forces `PYTHONHASHSEED=0`, `PYTHONDONTWRITEBYTECODE=1`, a fresh `HOME`/`TMPDIR` per run under `<run>/_scratch/<phase>`, and an engine-owned `PYTHONPATH=<wt>[:<wt>/src]`.
- `wrapper_argv(platform, policy)` and `macos_profile(paths)` are pure and tested on Linux. Paths are realpath'd (`/private/var/...`). The SBPL profile is `(allow default) (deny network*) (deny file-write*)`, then `(allow file-write* (subpath wt) (subpath scratch) (literal "/dev/null"))`.
- Launcher, Linux, in this order:
  1. `lo` up: `fcntl.ioctl` on an `AF_INET`/`SOCK_DGRAM` socket with `SIOCGIFFLAGS` 0x8913, then `SIOCSIFFLAGS` 0x8914 with `IFF_UP`; ifreq packed as `"16sH22x"`.
  2. `prctl(PR_SET_NO_NEW_PRIVS=38, 1, 0, 0, 0)` through `ctypes.CDLL(None, use_errno=True)`.
  3. Landlock through `libc.syscall`, with numbers 444 (`create_ruleset`), 445 (`add_rule`) and 446 (`restrict_self`), the same on x86_64 and aarch64:
     - ABI probe `syscall(444, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION=1)`.
     - Handled mask = WRITE_FILE (bit 1) and bits 4–12 (REMOVE_DIR, REMOVE_FILE, MAKE_CHAR, MAKE_DIR, MAKE_REG, MAKE_SOCK, MAKE_FIFO, MAKE_BLOCK, MAKE_SYM), plus REFER (bit 13) at ABI ≥2 and TRUNCATE (bit 14) at ABI ≥3.
     - EXECUTE, READ_FILE, READ_DIR and IOCTL_DEV are never handled, so reads and exec stay allowed.
     - `path_beneath` rules on `O_PATH` fds: directories `wt`, `_scratch/<phase>` and `/dev/shm` (if present) with the full mask; the file `/dev/null` with WRITE_FILE|TRUNCATE.
  4. Self-check (decision 42). Then fork/exec, `wait4`, and the JSON report on the fd.
- Launcher, macOS: the self-check only (`sandbox-exec` already applied the policy).
- Under `required`, any failed step writes `error` and exits 125 without exec'ing the workload. Under `best_effort` it records the flag as false and continues.

**Measurement (`execution/measure.py`).** `[G16]`
- `measure_workload(...)`:
  - `workload.warmup_runs` untimed warm-ups (0 allowed), then `N = max(settings.MIN_RUNS, workload.runs)` timed runs.
  - A `reset` callable runs before every warm-up and timed run: `status --ignored`; if anything is present, `checkout -f` and `clean -ffdx`; then the `.git` link check against `WorktreeHandle.link_bytes`.
  - `Workload.inputs` is not passed.
- Produces one `Measurement` each for `wall_time_s`, `cpu_time_s` and `peak_rss_bytes`.
- Fingerprint = `sha256(len‖stdout‖len‖output_file)`. The output file must resolve inside the worktree and is capped. The fingerprint is the value agreed by all N runs, or `None`.
- `hardware` records the OS, machine, Python, CPU count, both isolation modes and the per-run isolation flags.
- `run_tests(project, …)` returns `()` when `project.test_command is None` `[G4]`. Otherwise it runs the suite once under the same sandbox (`TEST_TIMEOUT_S`) and yields one `tests_passed` row (1.0 or 0.0) per workload.
- `measure_abab(a, b)` interleaves A and B with a reset before each run.
- Timeout, non-zero exit, flood or missing isolation raise `RunFailure`. `throughput_per_s` is not produced, so an objective that asks for it fails baseline completeness.

**Git (`execution/git.py`).** `GitWorkspace` as researched, plus:
- `-c` overrides on every call: `core.hooksPath=/dev/null`, fsmonitor off, signing off, `protocol.allow=never`, empty credential helper, empty attributes and excludes files, `gc.auto=0`, `maintenance.auto=false`, a fixed identity, an empty override per driver key, and `--attr-source` when available.
- An environment built from scratch: `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C`, and no inherited `GIT_DIR`.
- `--` before every path; `capture` reads bytes and decodes strict UTF-8.
- `add_worktree(path, commit) -> WorktreeHandle` `[G10]`:
  - It `remove --force`s an existing worktree at `path` first.
  - After `worktree add` it reads the `gitdir:` line of `path/.git` and requires the target's realpath to be a direct child of `<common>/worktrees/`. Otherwise it raises `RepoTamperedError`.
  - It stores the path and the file's bytes.
  - Every later call on that worktree uses `--git-dir=<handle.gitdir> --work-tree=<path>`.
- `check_link(handle)` raises `RepoTamperedError` when `path/.git` no longer equals `link_bytes`.
- `repo_fingerprint(exclude_refs=…)` per decision 16 `[G1]`.
- `merge(acc, commit)` returns a tree or the conflict paths: exit 1 is a conflict, anything else raises.
- `update_ref(ref, new, old)` and `checked_out_branches()`.

**Capture rules (`optimization/anticheat.py`, `check_capture(changes, written, blobs, judged_metrics)`).** Every name match uses `common/paths.matches_pattern` (case-insensitive). `[G9]`
- `forbidden_file_mode`: a new mode 120000 (symlink) or 160000 (gitlink), any mode other than 100644/100755, or any mode change on an existing path (status `T`, or `M` with `old_mode ≠ new_mode`).
- `forbidden_file`: any change (A, M, D, T) to a path matching `WRITE_DENY_PATTERNS`, or an added or modified path whose new blob is binary (a NUL in its first 8000 bytes, git's rule).
- `git_metadata`: any path with a component equal to `.git`, or whose name is `.gitattributes`, `.gitmodules` or `.lfsconfig`. `.gitignore` is allowed: `clean -ffdx` ignores it.
- `unrecorded_write`: a touched path missing from `EditResult.written`. A written path absent from touched is fine (content unchanged).
- `process_spawn`: decision 14, only when `cpu_time_s` or `peak_rss_bytes` is judged.

**Trial runner (`execution/trial_runner.py`):**
1. Compute `own_ref = refs/heads/engine/trial-<run>-<hyp>` and take `F0 = repo_fingerprint(exclude_refs={own_ref})` `[G1]`. Add the worktree `<root>/<run>/trial-<hyp>` through `add_worktree` (handle stored).
2. Call `editor.edit`. Any editor error gives `failed` with the money spent recorded.
3. `capture`. An empty diff or invalid UTF-8 gives `failed`.
4. Run `check_capture` and `check_diff_all`. Any violation gives `failed` with `violations` set, and the trial is **never executed**.
5. Commit with fixed identity and dates and an `Engine-Trial: <id>` trailer, run `clean -ffdx`, create or re-point `own_ref` (decision 18), and set `Trial.commit`.
6. Measure and run the tests. `RunFailure` gives `failed`.
7. Take `F1 = repo_fingerprint(exclude_refs={own_ref})`. If F1 ≠ F0, or `own_ref` is neither absent nor at `Trial.commit`, raise `RepoTamperedError` (an `EngineError`).
8. In a `finally` block: remove the worktree, `_scratch/trial-<hyp>` and `_probe/trial-<hyp>` (`remove --force`, contained `rmtree` fallback), then `prune`, then `rmdir <run>` if it is empty.

**Baseline runner and profiler** `[G5]`. Both follow the same shape: F0, then `add_worktree(<run>/baseline | <run>/profile, commit)`, then the run, then F1 (no exclusions; F1 ≠ F0 raises `RepoTamperedError`), then the `finally` cleanup of step 8. The baseline runner calls `measure_workload` per workload plus `run_tests`. The profiler runs each Python workload once, untimed, under cProfile and the same sandbox.

**Combiner and publisher (`execution/combine.py`).**
- Combiner:
  - Takes F0 and starts with ACC = `base`.
  - Merges each `KeptChange` greedily onto ACC with `merge-tree`, recording a `CombineSkip` for each conflict, and writes one `commit-tree` per applied change.
  - Adds `<run>/combine` at the tip and a fresh `<run>/combine-base` at base.
  - Runs `measure_abab(combine-base, combine)` per workload and `run_tests` on `combine` `[G3]`.
  - Takes F1, then the `finally` cleanup of both worktrees and their scratch and probe dirs `[G5]`.
  - Each call is self-contained, so the node's fallback is just a second call.
- Publisher: refuses a branch that is checked out in any worktree. Runs `update-ref` create-only. A ref already at `tip` is a no-op; any other value raises `DeliveryError`. Never `branch -f`, never push.

**Editor (`execution/editor_tools.py`, `execution/editor.py`).**
- `WorktreeEditor` as researched:
  - virtual `/repo` root; NFC; `normalize_path`;
  - `GIT_METADATA_NAMES` blocked case-insensitively; `O_NOFOLLOW`; a symlink check per path component;
  - `READ_DENY_PATTERNS` and `WRITE_DENY_PATTERNS` from `common/paths.py`; size limits;
  - records `written` (deletions as 0).
- `ClaudeEditor`, a hand-written loop:
  - constant tools and system prompt (cached), append-only messages;
  - `call()` checks the budget before every request;
  - follows the stop-reason table: no tools run after `max_tokens` or `refusal`, and one nudge after an `end_turn` with no edits;
  - repository content goes inside `<untrusted_repo_content boundary=token_hex(8)>`.
- `ScriptedEditor(edits_dir)` is **keyed by hypothesis title** `[G7]`. The title must match `^[a-z0-9][a-z0-9_-]{0,63}$`, and the editor looks up `edits_dir/<title>/`. An unsafe title or a missing directory gives an `EditResult` error. It copies files and applies `_delete`/`_symlink` manifests, and reports what it wrote honestly.

**Persistence.**
- `PostgresRepository(dsn)`: one connection per call; literal SQL with `%(name)s` parameters; `serde` for state.
- Every id bound for a UUID column is checked with `uuid.UUID(...)` before SQL; a failure raises `InvalidRecordIdError` naming the field and value `[G7]`.
- `save_run` upserts `projects` (on `id`, including `test_command`) and `task_executions` in one transaction; it never writes trials or verdicts. A `UniqueViolation` whose constraint is `projects_root_path_key` rolls back, looks up the id registered for that `root_path`, and raises `ProjectConflictError("root <path> is already registered as project <id>")` `[G15]`.
- Trials and verdicts use the in-place JSONB array upsert; lessons are typed columns ordered by `seq`.
- Migration 004: `uq_task_thread`, a `lessons.seq` identity column, `gain`/`weight` as DOUBLE PRECISION, and `projects.test_command JSONB`. All statements are `IF NOT EXISTS` or guarded `DO` blocks.

## 5. Security

| Threat | Control | Cost to the user |
|---|---|---|
| Command injection | argv only, never `shell=True`; `argv[0]` absolute or repo-relative and protected; `--` before paths; ids refname-validated | Pipelines need a script, which becomes protected |
| Path traversal and symlinks | Editor handler rules; capture rules `forbidden_file_mode`, `forbidden_file`, `git_metadata`, `unrecorded_write`; `--no-renames`; `.git` link check against the stored handle; validated `gitdir:`; worktrees only under `WORKTREE_ROOT` | Symlinked sources and binary files cannot be edited |
| Writes outside the worktree | Landlock (ctypes, no_new_privs) / SBPL allowlist; per-run write self-check, fail closed under `required`; PID namespace; F0/F1 on every executing phase; explicit `--git-dir` from the handle | Workloads cannot write outside the worktree and scratch |
| Network, SSRF | Network namespace with private `lo`; macOS `deny network*`; per-run connect self-check; `protocol.allow=never` | No localhost services or internet (macOS also denies the workload's own loopback); `best_effort` is opt-in and shown in the report |
| Secrets | `SecretStr`; the key exists only in `AnthropicTransport`; allowlisted envs; editor read-deny; understand reads git objects at base only; `describe()` logs status, type and request id only | User `*_URL`/`*_TOKEN` env vars are stripped |
| Reward hacking | Protected paths plus harness; never execute after a violation; reset before every run; `process_spawn`; editor never sees workload output; combination re-judged with the full verdict rules, tests included | Workloads cannot keep state across runs |
| git config injection | Overrides, empty env, empty driver keys; LFS scan reads blobs, never runs filters | The user's git config is ignored |
| Prompt injection | Rules in code; per-trial boundary (content containing it is refused); nonce-tagged notices; output capped and sanitised | None |
| Cost | Explicit fallback chain = priced chain; pre-send worst-case check before every attempt; own retries with a fixed policy; per-attempt recording (timeouts charged the full estimate); running total; `min_trial_budget_usd`; invariant `cost_usd ≤ max_cost_usd` | Trials stop early near the cap |
| Excessive agency | Create-only `update-ref` on `engine/` only; never push; F0/F1 plus own-ref check | Committing or switching branches during a run aborts it |
| Persistence integrity | Parameterised SQL; UUID validation before SQL; `ProjectConflictError` on a root-path clash | One project id per repo root per database |

Workloads can still read anything the user can (Landlock does not confine reads). This is accepted: there is no network to send it out on, and output stays local.

## 6. Test plan

**Unit tests with fakes:**
- `errors` and `paths`: the hierarchy (`isinstance` checks); `matches_pattern` keeps the old `_matches` cases; the pattern constants.
- `cost`:
  - arithmetic and `iterations`;
  - an unknown model priced at worst case;
  - the estimate scales with `len(chain)` and uses `max(input, cache_write)`;
  - a property test that actual cost ≤ estimate.
- `transport`, through a real client on `httpx2.MockTransport`:
  - body and `anthropic-beta` header;
  - the body carries `fallbacks` equal to `ENGINE_FALLBACK_MODELS`, and no field when `ENGINE_FALLBACKS=False` `[G6]`;
  - no `thinking`, `temperature` or `tool_choice`;
  - mapping for 400, 401, 403, 404, 413, 429, 500 and 529 (529 is not an `InternalServerError`);
  - `APITimeoutError` caught before `APIConnectionError`.
- `call` retry policy `[G14]`:
  - 429, 529, 500, timeout and connection errors are retried up to `LLM_MAX_RETRIES`, then raise `LLMUnavailable`;
  - 400, 404 and 413 are not retried;
  - 401 and 403 raise `LLMConfigError`;
  - the injected `sleep` sees `1, 2` and a `retry-after: 5` floor, and a `retry-after: 120` gives up at once;
  - each timeout attempt is charged the full estimate, each HTTP error 0;
  - `Budget.check` runs before each attempt, and the cap halts the loop.
- `editor_tools`: the full parametrised attack list, including `.LFSCONFIG`, `pkg/__pycache__/m.pyc` and `ext.SO`.
- `editor`: every stop reason, the nudge, the turn and call caps, append-only messages, identical tools and system on every request.
- `ScriptedEditor`: title lookup, an unsafe title (`../h1`, `H1 set`) gives an error result, a missing dir gives an error result, honest `written`.
- `understand`: schema shape, dropped paths and ids, failure mapping.
- `anticheat`, every capture rule `[G9]`:
  - `forbidden_file` positive: `pkg/__pycache__/m.cpython-311.pyc`, `fast.SO`, `lib.dylib`, deleting `_speedups.so`, an added `data/table.bin` with a NUL byte;
  - `forbidden_file` negative: `docs/so.md`, a text `.json`;
  - `forbidden_file_mode`: 120000, 160000, a chmod of `core.py`;
  - `git_metadata`: `sub/.gitattributes`, `.GITMODULES`, `x/.git/config`; a negative for `.gitignore`;
  - `unrecorded_write`: touched ⊄ written;
  - `process_spawn` AST: comment and string cases negative; `posix_spawn` and `importlib` positive.
- Nodes, using `execution/fakes.py`:
  - preflight events, including `workload_inputs_ignored` `[G16]`;
  - baseline fail-closed cases and `noisy_host`;
  - the running budget, `min_trial_budget_usd` stopping before a trial, and the router `[G8]`;
  - violation dedupe;
  - the profile editable-install refusal;
  - combine `[G3]` `[G17]`:
    - holds when `derive_verdict` is keep;
    - does not hold when the tests row is missing (inconclusive) or failing, or when a guardrail is inconclusive;
    - falls back by gain with a hypothesis-id tie-break;
    - when both fail, `kept_verdict_ids=[]`, deliver is `report_only` and the lessons are unchanged;
  - the publisher is called only when something is kept.

**Real processes:**
- RSS floor: an engine holding 200 MiB, `/bin/true` must read under 50 MiB; 50 MiB measured within ±15%.
- Exit code 3 and SIGKILL; timeout kills the group and drains it; a `setsid` orphan is killed.
- Flood, stderr tail, full-stream sha, env allowlist.
- Memoisation blocked by the reset.
- `warmup_runs=0` and `=2` give the exact launch counts, through an injected `run_once` counter `[G16]`.
- Sandbox network: the parent listens on 127.0.0.1, the control run connects and the sandboxed run must not; the workload's own loopback works (Linux); `net_isolated` is true.
- Sandbox writes: a write outside fails with EACCES, inside succeeds, `/dev/shm` works, `fs_isolated` is true `[G12]`.
- Fail-closed isolation: a launcher spec with Landlock forced to fail (fake syscall, in-process) under `required` exits 125 without exec, and `run_once` raises `RunFailure`. The same case under `best_effort` runs and records false.
- Landlock ABI capping: the mask for ABI 1, 2 and 3 is checked against expected bit sets (pure function).
- `REQUIRE_NETWORK_SANDBOX=1` and `REQUIRE_FS_SANDBOX=1` turn skips into failures.

**Real git, in `tmp_path`:**
- symlink, rename, ignored file, chmod, binary, non-UTF-8;
- worktree admin-dir collision: two `baseline` worktrees in different run dirs, where the second handle's `gitdir` ends in `baseline1` and all calls use it; a forged `gitdir:` outside `<common>/worktrees/` is refused `[G10]`;
- clean merge, conflict, and two applied changes in a linear history;
- create-only, wrong old value, checked-out branch, default branch;
- a malicious-config repo whose marker files must never appear;
- a rewritten `.git` link;
- fingerprint `[G1]`:
  - creating the own trial ref leaves F0 == F1;
  - creating any other ref, or changing config or hooks, raises `RepoTamperedError`;
  - the own ref at the wrong commit raises;
- preflight `[G4]` `[G11]`:
  - LFS refused via a root `.gitattributes`, a nested `.gitattributes`, `info/attributes` and `.lfsconfig`, with `--attr-source` in effect for the other calls;
  - `tests_pass` without `test_command` refused;
  - `test_command[0]` resolution, and a repo-relative `test_command[0]` added to `extra_protected`;
- HEAD, index hash, status and config unchanged after a full cycle.

**Postgres:**
- One database per xdist worker, built from `schema/*.sql`; `DELETE` between tests.
- The 13 contract tests run on both backends; only the builders change, to registered uuid projects.
- `tests/persistence/test_postgres.py` (`postgres` marker, env-gated) `[G7]` `[G15]`:
  - `ProjectConflictError` on a second project id at the same `root_path`, with the message naming the existing id; the same id at a new path updates the row;
  - `InvalidRecordIdError` for a lesson with `hypothesis_id="h1"`, and for a non-UUID run id, with no row written.
- A full gated run round-trips with `==`; the serde round trip is tested on 3.11 and 3.13.

**E2E** (`tests/e2e/`, marked `slow`, fixture `dedupe_repo`):
- Every scenario builds `Project(test_command=("python", "-m", "unittest", "discover", "-s", "tests", "-t", "."))` with a `tests_pass` guardrail `[G4]`.
- Candidates have uuid4 ids and titles `h1`, `h2`, `h3`, `h5`, `h6`, matching `tests/fixtures/dedupe_edits/<title>/` `[G7]`.

| Scenario | Setup | Expected |
|---|---|---|
| E2E-A, real Claude path | Scripted understand reply; `ClaudeEditor` + `WorktreeEditor` + `ScriptedTransport`. h1's transcript first tries `/repo/.GIT/hooks/pre-commit`, `../x`, a symlinked path and `tests/test_core.py`, then the real `str_replace`. | Those four get `is_error` results. h1 kept. h3 `sorted(set)` rejected by an equivalence judge failure. Real profiler hotspot `unique_in_order`. Combination holds (`derive_verdict` keep, tests ran on the tip). Tip = base + h1. Cost equals the scripted usage priced, ≤ cap. |
| E2E-B, git-side defence, on Postgres when available | `ScriptedEditor`, `max_hypotheses_per_round=4`. h1 `set`; h2 `set` + deletes a test; h6 symlink + `set`; h5 `dict.fromkeys` on the same lines, lower score. | h2 rejected `protected_path` and h6 rejected `forbidden_file_mode`, neither measured nor committed. h5 kept, then skipped as a conflict. Combination of h1 holds; one `Engine-Trial` commit on the delivery branch. Lessons stored with uuid hypothesis ids. |
| E2E-C, budget | `ClaudeEditor` + `ScriptedTransport` with scripted usage. The cap is chosen so every request of the first trial passes its pre-send check. `min_trial_budget_usd` is set explicitly to `cap − cost(understand) − cost(trial 1) + 0.01`, computed in the test from the scripted usage and prices `[G8]`. | Second trial never starts; `budget_exhausted` event; router goes to combine; `cost_usd ≤ max_cost_usd`. |

All three also assert:
- the user's HEAD, index hash, status and config are unchanged;
- the refs created are exactly the committed trials' `refs/heads/engine/trial-<run>-<hyp>` plus `refs/heads/engine/run-<run>` when delivered, and no pre-existing ref changed `[G1]`;
- `git worktree list --porcelain` shows only the main worktree, and `<WORKTREE_ROOT>/<run>` does not exist `[G5]`.

Assertions are on outcomes only; the measured margin is about 8×.

**Live smoke test:** marker `live`; runs only when the `ANTHROPIC_API_KEY` environment variable is set; one-file repo, `Budget(0.10)`. It also checks the text editor tool version, the explicit `fallbacks` body and the `role: system` wire shape. `workflow_dispatch` only.

**CI:**
- `uv sync --frozen --extra dev --extra database`; blocking `uv run mypy src tests`.
- A `pgvector/pgvector:pg16` service with `TEST_DATABASE_URL`.
- The sandbox probe step, `REQUIRE_*=1`, `timeout-minutes: 15`.
- Schema Apply applies 001 to 004 once in order, snapshots the catalog, **re-applies 003 then 004 only**, and diffs the snapshot. 001 and 002 are not idempotent (plain `CREATE TABLE packages`, `CREATE INDEX idx_packages_name`). `[G2]`
- `macos-latest`: `pytest tests/execution --no-cov` with `GIT_EXECUTABLE=/usr/bin/git`. Non-blocking on the first push, blocking before the PR is marked ready.
- Log the baseline CV.

**Coverage:** no `pragma: no cover`. The launcher's parent side and its setup functions are tested in-process with injected syscall and ioctl callables; platform branches use an injected `platform`. Gate 90%, target ≥95%.

**Verifier:** E2E-A to E2E-C, attack repos, `kill -9` in the middle of a trial (the next run's `prune` recovers), resume after approval, a dirty user tree, and a second run on the same repo (the conflict error under Postgres, idempotent trial refs).

## 7. Work breakdown

Sizes are source lines; tests are extra. Builders work on disjoint files within a wave.

| Wave | Unit | Source files | Test files | ~Lines | Depends on |
|---|---|---|---|---|---|
| 0 | U1 models, settings, state, budget, errors, paths | `common/models.py`, `common/config.py`, `common/errors.py` (new), `common/paths.py` (`matches_pattern` and constants), `orchestrator/state.py`, `clients/budget.py`; import-only edits in `orchestrator/nodes.py` (re-import `EngineError`/`DeliveryError`) and `optimization/anticheat.py` (import `matches_pattern`) | `tests/common/test_models.py`, `tests/common/test_config.py` (SecretStr form, pricing validator), `tests/common/test_errors.py`, `tests/common/test_paths.py`, `tests/orchestrator/test_state.py`, `tests/clients/test_budget.py` | 340 | — |
| 0 | U2 fixture | `tests/fixtures/dedupe_repo/**`, `tests/fixtures/dedupe_edits/{h1,h2,h3,h5,h6}/**` | Self-check: the fixture's own unittest suite, ruff and mypy run outside the engine suite | 200 | — |
| 1 | U3 protocols and test infrastructure | `execution/runner.py`, `execution/protocols.py`, `execution/fakes.py`, `pyproject.toml` (markers `postgres`/`live`, addopts `-m "not live"`, mypy exclude `tests/fixtures`), `tests/conftest.py` (`collect_ignore_glob`) | `tests/execution/test_runner.py`, `tests/execution/test_fakes.py`; signature-only edits at `test_nodes.py:254, 275, 301, 329, 2398` (the `measure` overrides at 329 and 2398 gain `run_id` and `commit`), `test_main.py:655`, `test_graph_e2e.py:459` | 260 | U1 |
| 2 | U4 git | `execution/git.py` (`WorktreeHandle`, `repo_fingerprint`) | `tests/execution/test_git.py` | 400 | U3 |
| 2 | U5 sandbox and launcher | `execution/sandbox.py`, `execution/launcher.py` (ctypes Landlock, `lo` ioctl, self-checks) | `tests/execution/test_sandbox.py`, `tests/execution/test_launcher.py` | 390 | U3 |
| 2 | U6 cost | `clients/cost.py` | `tests/clients/test_cost.py` | 140 | U1 |
| 2 | U7 editor handler | `execution/editor_tools.py` | `tests/execution/test_editor_tools.py` | 300 | U3 |
| 2 | U8 Postgres | `persistence/postgres.py`, `orchestrator/serde.py`, `infrastructure/schema/004_engine_repository.sql` | `tests/persistence/conftest.py`, `tests/persistence/test_repository.py` (builders only), `tests/persistence/test_postgres.py`, `tests/orchestrator/test_serde.py` | 360 | U1 |
| 2 | U9 capture anti-cheat | `optimization/anticheat.py` (`check_capture`, `process_spawn`) | `tests/optimization/test_anticheat.py` | 170 | U3 |
| 2 | U10 nodes and orchestrator | `orchestrator/nodes.py`, `orchestrator/main.py` | `tests/orchestrator/test_nodes.py` (new tests only), `tests/orchestrator/test_main.py` | 340 | U3 |
| 3 | U11 process runner | `execution/procrun.py` | `tests/execution/test_procrun.py` | 280 | U5 |
| 3 | U12 transport | `clients/transport.py` | `tests/clients/test_transport.py` | 320 | U6 |
| 3 | U13 preflight | `execution/preflight.py` | `tests/execution/test_preflight.py` | 240 | U4, U5 |
| 4 | U14 measurement | `execution/measure.py` | `tests/execution/test_measure.py` | 330 | U11 |
| 4 | U15 profiler | `execution/profiler.py` | `tests/execution/test_profiler.py` | 200 | U4, U11 |
| 4 | U16 editor loop | `execution/editor.py` | `tests/execution/test_editor.py`, `tests/fixtures/transcripts/*.json` | 330 | U7, U12 |
| 4 | U17 understand | `orchestrator/understand.py` | `tests/orchestrator/test_understand.py` | 280 | U4, U12 |
| 5 | U18 trial and baseline runners | `execution/trial_runner.py` | `tests/execution/test_trial_runner.py` | 400 | U4, U9, U14, U16 |
| 5 | U19 combine and publish | `execution/combine.py` | `tests/execution/test_combine.py` | 280 | U4, U14 |
| 6 (Lead) | U20 integration | `orchestrator/factory.py` (wires seams, computes `min_trial_budget_usd`), `.github/workflows/ci.yml` (+ macOS and live jobs, Schema Apply re-applies 003 and 004 only), `scripts/stage-gate.sh`, README, STATUS, CLAUDE.md | `tests/e2e/test_step2.py`, `tests/orchestrator/test_factory.py` | 140 | all |

- **Review:** each unit gets a Reviewer on a different model from its Builder. U4, U5, U7, U9, U11, U13 and U18 also get a security-focused review.
- **After U20:** the Verifier runs, then the stage gate, then `/security-review`, then the draft PR.

## 8. Risks and open decisions, resolved

1. **Landlock on GitHub's ubuntu-22.04 runner is unverified** (it is verified on this host: ABI 7). The probe step decides on the first push. If it fails, move the job to ubuntu-24.04 with `sysctl kernel.apparmor_restrict_unprivileged_userns=0` in the same PR. Never relax `REQUIRE_*`.
2. **`sandbox-exec` is deprecated, and its rule-order semantics are unverified.** The macOS CI job's behaviour tests, including the per-run self-checks, decide. If it fails, `required` fails closed on darwin, and `best_effort` is opt-in with a report banner.
3. **Ubuntu ≥23.10 desktops block unprivileged user namespaces.** `required` fails at connect with a hint naming the sysctl or `best_effort`. Document it in the README.
4. **Noisy host** (CV 9–28%). Assert outcomes only; fixture wins ≥3×; emit `noisy_host`; ABAB in combine; never pin CPUs.
5. **Answer memorisation.** Accepted for Step 2: the editor never sees workload output, and the test suite plus human review of the branch stand guard. Held-out inputs arrive in Step 5.
6. **Peak RSS is per process, not per tree.** State the definition in the report and rely on `process_spawn`, which fails closed. A subreaper or cgroup comes in Step 5.
7. **Editable installs.** The `PYTHONPATH` prefix plus the profiler path check, which fails closed. Commands that pass `-I` are documented as unsupported.
8. **Text editor tool version, fallback chain and pricing are unverified for `claude-opus-5-5`.** Keep single constants and a settings table validated at startup; re-check with the claude-api skill at the stage gate; the live smoke test confirms before Step 5.
9. **Committing or switching branches during a run aborts it.** Accepted; the Step 4 CLI warns before starting.
10. **Trial refs pile up in the user's repo.** Keep them; the report prints a cleanup command; Step 4 adds `clean`.
11. **`PostgresSaver` returns `phase` as a plain `str`.** Step 4 re-types values through `serde.load_state` and adds a cross-process resume E2E, using a saver release at least two weeks old.
12. **Coverage of the launcher's child side and of the platform branches.** In-process launcher tests with injected syscall and ioctl callables, plus an injected `platform`; uncovered child lines stay within the 95% target; no pragma.
13. **Landlock ABI 1 kernels (5.13–5.18) always deny cross-directory rename and link** (REFER cannot be granted). Workloads that do this fail under `required` there. Accepted: the report shows the ABI, and the README notes that kernel ≥5.19 is recommended.
14. **The worst-case estimate is conservative** (byte-count prompt bound × chain length). Trials stop earlier than actual spend would require. Accepted: the cap is a hard bound by design; `min_trial_budget_usd` and the estimate are single functions that can be tightened once the live smoke test measures real usage.
15. **One project id per repo root per database.** A second id at the same root raises `ProjectConflictError`. The Step 4 CLI looks up the existing id by root before starting.