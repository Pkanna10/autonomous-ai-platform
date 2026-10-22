# Lead notes carried to later units (from wave 2 reviews)

U11 procrun:
- Parse the launcher report strictly: exactly one JSON object, exactly the LaunchReport keys, sane types/ranges;
  extra data, a second object, missing or extra keys -> RunFailure.
- Cross-check the report against the outer os.wait4 rusage of the wrapper process and procrun's own wall clock:
  inner wall <= outer wall, inner cpu <= outer cpu (+ small epsilon), inner maxrss <= outer maxrss, wrapper exit
  status == report exit (128+signal mapped). A refusal is `error` set with both isolation flags false (exit 125 in the
  report); an exec failure also sets `error` (exit 127). Never treat wrapper status 125 alone as "never ran".
  Any mismatch -> RunFailure("measurement report does not match the process accounting").
- A W (weakened) record under best_effort reaches the report as both flags false, error null, plus a stderr line:
  record it as isolation not applied, never as a failure.
- HOME/TMPDIR scratch dirs are wiped before every run (fresh per run, not per phase).
U12 transport:
- Fallbacks: explicit array form needs beta header server-side-fallback-2026-06-01 (not -07-01); ENGINE_FALLBACKS=True
  with an empty ENGINE_FALLBACK_MODELS sends no fallbacks field.
- Exact input tokens: AnthropicTransport.count_input_tokens(request) via client.messages.count_tokens (free endpoint);
  on any error fall back to the byte bound; ScriptedTransport returns the byte bound. call() uses it for the estimate.
- Event (or note) when an attempt's model is not in the price table (cost.py helper unpriced_models).
U13 preflight (moves to wave 4, it reuses U11 run_once for the sandbox probe):
- Refuse partial clones / promisor remotes (extensions.partialClone, remote.*.promisor) with a PreflightError naming
  the fix (git fetch --refetch or a full clone).
- Protect every argv element of each workload command and of test_command that resolves to a file inside the repo
  (harness scripts such as 'python scripts/bench'), not only argv[0]: add them to extra_protected.
- Engine Python must be >= the project's syntax level (AST scan fails closed); record sys.version_info in the report.
U14 measure:
- Wipe HOME/TMPDIR scratch before every run (with U11).
- Reset the worktree (status --ignored, checkout -f, clean -ffdx, the .git link check) immediately before run_tests
  too, for the baseline, each trial and the combine tip. Test: a unittest.py the workload drops at the root is gone
  when the test command starts. (U9b finding 7)
- tests_passed needs a runner summary, never the exit code alone: unittest's "Ran N tests" + "OK", or pytest's
  --junitxml written into _scratch. Exit 0 with no summary, or fewer tests than the baseline -> tests_passed 0.0.
  Record the baseline count. (U9b finding 8)
U16 editor loop: live smoke budget $0.50, not $0.10 (one request's worst case is ~$0.40 + prompt).
U17 understand: add a fixed allowance (2,000 tokens) to the prompt bound for the structured-output system prompt.
U18 trial runner:
- GitError during capture (including 'printed more than') -> failed trial; RepoTamperedError propagates.
- Pass reserved_modules = RESERVED_MODULES | {-m targets of the workload commands and test_command} to check_capture.
- Strict UTF-8 decode of paths before check_capture (U9 contract).
- Pass existing_dirs (the base tree's directories, from git ls-tree -d -r) and module_roots (repo root, src, plus the
  directory of every workload/test script path) to check_capture.
- Pass the module_roots set to WorktreeEditor too (U7 needs a module_roots keyword; reserved_modules typed
  AbstractSet[str], refusing a str), so the editor refuses what capture would reject.
- tasks.py is not protected by default: when a test_command or workload uses invoke, add tasks.py to extra_protected.
U20 docs/CI: --extra database in CI; document NUL escaping (U+E000) in persistence; trial-ref cleanup command quoting;
  dependency shadowing (a trial adding numpy.py) is a known limitation covered by human review of the branch.
Lead decisions (wave 2b):
- network=off on Linux keeps no namespaces (no PID/IPC/mount-proc). An open network already gives a cross-run channel,
  so the namespaces would not restore measurement integrity, and they would add a user-namespace dependency to fs-only
  isolation. Documented as a limitation of network=off.
- A non-root launcher keeps a full bounding set when it cannot drop it: CapEff/Prm/Inh/Amb are 0 and no_new_privs is
  set, so execve cannot gain capabilities. Accepted.
Wave 3 handovers (U11 procrun, U12 transport, committed 3bfb28c, 708f288):
- U14/U15/U18/U19: call run_once(..., fresh_dirs=(scratch_root, home, tmp)) so the whole writable scratch root is fresh per run;
  turn RunSample.notes and RunFailure.notes into events. run_once resolves the wrapper from /bin:/usr/bin, root-owned.
- U16/U17: AnthropicTransport(http_transport=...) (not http_client); call() returns LLMResult(message, cost_usd, tokens,
  served_model, fell_back, unpriced_models, attempts); refusal is returned, not raised. count_input_tokens adds a margin.
- U20 factory: pin logging.getLogger("anthropic") at INFO (the SDK DEBUG log prints request options); pin base_url to the
  official API unless the user sets it explicitly in settings (ignore a stray ANTHROPIC_BASE_URL in the environment).
- Accepted: procrun.py 664 lines, transport.py 489 lines. 409/422/501 stay LLMRequestError. 402 -> LLMConfigError.
Wave 4 Lead decisions:
- U15: never unmarshal workload-written pstats in the engine (marshal is unsafe on hostile data). Convert inside the sandbox
  with an engine-owned script run through run_once, emit JSON, parse strictly with a size cap; hotspots are untrusted hints.
- U16 also owns editor_tools.py: add the module_roots keyword and AbstractSet[str] typing (refuse a str) to WorktreeEditor.
Wave 4 handovers (U14 measure, committed 3a92c15; 4 agents, ~268k output tokens):
- API: make_phase(git, handle, *, scratch, probe, ...) -> Phase; measure_workload(phase, workload, *, trial_id) -> Measured(measurements,
  notes, tests_counted); measure_abab(a, b, workload, ...) -> AbabMeasured; run_tests(phase, project, workloads, *, baseline_count,
  trial_id) -> Measured; baseline_test_count(measurements).
- U18: pass baseline_count = baseline_test_count(state baseline measurements) to run_tests for every trial; emit Measured.notes as
  events; the "did not agree on one output" note is the nondeterministic-output warning even without an equivalence guardrail.
- U19: the combine tip's run_tests takes the same baseline_count (from the state baseline), no extra suite run on combine-base.
- Accepted: measure.py 604 lines.
U16 editor loop (committed 897aa2c; 4 agents, ~322k output tokens) + Lead fixes d917f30 (normalize_path fixed point), a17c54a
(ENGINE_API_BASE_URL pin; the container sets ANTHROPIC_BASE_URL):
- U18: build one ClaudeEditor/WorktreeEditor per run with module_roots and reserved_modules for that run (they are constructor
  args, not EditTask fields). EditResult has no notes: fallback/unpriced notes are not surfaced yet (known gap, U20 may add).
- U20: .env.example documents ENGINE_API_BASE_URL; live tests require -m live explicitly (U16 pattern) for any new live test.
- Accepted: editor.py 524 lines, editor_tools.py 550 lines.
U13 preflight (committed 05ea510; 4 agents, ~385k output tokens) + Lead fix (unittest test*.py default protected pattern):
- U18: add every workload's working_dir to module_roots and each -m target's top-level name to reserved_modules (preflight
  finding 14: -m shadowing from working_dir).
- U20: construct GitPreflight(protected=ctx.protected_patterns); put notes and python_version on the protocol's
  PreflightReport (today only on GitPreflightReport) and emit them as connect events.
- U20 docs: a test command naming the package dir (pytest mypkg) protects the whole dir, so no trial can edit it: point the
  test command at the test folder. pytest python_files patterns set in config are not protected unless a test dir is named.
- Accepted: preflight.py 654 lines; no commands.py split.
U15 profiler review (reviewed after the fact; fixes dbec415, CI fix cd0a3e6):
- The shim runs on workload interpreters >= 3.8; tests run every python3.N on PATH. -P exists only on >= 3.11, so
  safe-path cases are generated only there. Install 3.8-3.12 with uv before running the suite locally.
- Accepted: a repo module named like a stdlib module the shim imports (json.py, ...) makes that workload "not profiled".
U17 understand (Builder, Fable correctness + security reviews, fixer; 4 agents, ~754k subagent tokens):
- Default effort (the spec names none). One structured-output request, UNDERSTAND_MAX_TOKENS, no tools, cache=False
  (one request per run), PROMPT_ALLOWANCE_TOKENS = 2000 on the pre-send bound.
- workload_notes travels as an array of {workload_id, note} in the schema (structured outputs need
  additionalProperties false) and becomes the model's dict. Length caps beyond the spec (language 64, entrypoints
  20 soft / 200 hard, paths 1024, notes 500) live in the validator; reply text with control or bidi characters
  rejects the whole reply.
- READ_DENY files are neither listed nor read (one count note). Reads are bounded by ReadLimits (files, bytes per
  file, total bytes, read attempts); only the head of a file is decoded and scanned for the boundary.
- U20 / U4 follow-up: GitWorkspace.read_blob has no size limit, so one huge tracked file is held in memory (up to
  MAX_OUTPUT_BYTES) before the understander truncates it. Add read_blob(..., limit=) or a sized ls-tree -l in U20.
- Accepted: understand.py 656 lines (precedent: procrun 664, preflight 654, measure 604).
Wave 5 (U18 a22d142, U19 fefe698, Lead fix 1f5c131; 8 agents, ~1.62M subagent tokens):
- Lead fix: Combiner.combine takes keyword-only baseline_count; CombineRules carries baseline_test_count of the state
  baseline and _retest passes it (both U19 reviewers: the tip's suite only had to pass one test).
- U18: a foreign engine/trial ref (no matching Engine-Trial trailer) stops the trial with EngineError before any
  worktree; a re-run that commits nothing deletes its stale own ref; an own ref that is checked out is never moved.
  run_scope resolves a symlinked script to its target dir (inside the worktree) for module_roots.
- U19: publish reads the ref before checking anything out; a default branch that is a symref to the new engine ref
  is detected after the create and undone (DeliveryError).
- U20 follow-ups:
  - Factor the phase cleanup into one shared helper; U18's _PhaseOwner._cleanup is the strictest version (every step
    in its own finally, errors collected, never hides an in-flight error); CProfiler._cleanup can still let a
    remove_worktree ValueError/GitError replace an in-flight error, so switch it to the shared helper.
  - Public helpers instead of private imports: GitWorkspace.commit_message, anticheat.is_utf8,
    measure.python_module, git contained-rmtree; also GitWorkspace.read_blob(..., limit=) (U17),
    diff_commits / is_ancestor / symbolic_ref (U19: publish without a checkout, ancestor check, symref pre-check).
  - One assert_safe_branch(branch, project, prefix) in common/refnames.py with the prefix threaded through git.py;
    combine.py keeps a local copy and git._engine_ref hard-codes settings.TRIAL_BRANCH_PREFIX today.
  - Preflight backlog: refuse or report merge= attributes (merge=union can hide a combine conflict; the tip is still
    fully re-tested).
- Accepted sizes: trial_runner.py 656 lines, combine.py 401 lines (shrink when the cleanup and publisher move out).
