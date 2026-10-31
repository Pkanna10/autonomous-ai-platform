# E0a: why process_spawn refused trials in L2a and L2b (offline, $0)

Date: 2026-10-26. No API calls, no engine run, no git writes in the repo. The
real rule (`anticheat.check_capture` / `_spawn_problem`) was called directly on
the pinned sources, under the CI engine's Python (3.11; the live job ran
`CPython 3.11.17`, r1.log line 224) and under the service venv (3.13.16).

## 1. The rule as it stands

- `check_capture` sets `scan_spawn` when `cpu_time_s` or `peak_rss_bytes` is
  among the judged metrics (`PROCESS_SPAWN_METRICS`). The trial runner judges
  objectives plus guardrail metrics, and peak RSS is a default guardrail, so it
  was on for every OSS run (`trial_runner.py` 1128-1139).
- For every added or modified `.py` file it AST-parses the **whole new blob**
  (`_spawn_problem(blob)`, anticheat.py 651-655), not the added lines. Any
  finding anywhere in the file refuses the trial. `check_quality_references`
  (D37) scans only the added lines; `process_spawn` does not.
- What it matches: an import of multiprocessing/multiprocess/billiard/
  `concurrent.futures.process`/subprocess/`_posixsubprocess`/asyncio.subprocess/
  pty/joblib/loky (or any `*.multiprocessing`); `os`/`posix` `fork*`, `spawn*`,
  `posix_spawn*`, `exec*`, `system`, `popen`; **`importlib.import_module`
  (import or call) and any `__import__`** (dynamic imports); the names
  `ProcessPoolExecutor`, `create_subprocess_*`, `subprocess_*` under any owner.
  Threads (`threading`, `ThreadPoolExecutor`) are not matched.
- **Source the engine's interpreter cannot parse fails closed as
  `process_spawn`** ("could not be scanned ... Python 3.11 cannot parse it").
- Capture runs before the workload (`trial_runner.py` 971-978): a refused trial
  is `failed` with violations and never runs, so the D12-D15 fix retry (which
  needs a workload crash) is never offered.
- The editor prompt says "Add no dependencies, start no processes or threads"
  (`editor.py` 104-105); the rule is the backstop.

## 2. Pinned sources (fetched, commits verified)

| lib | tag | commit (HEAD of the clone) | module_root |
| --- | --- | --- | --- |
| more_itertools | v11.1.0 | 64be96ceb2a6e836f76f069f4a96d2394d59fd0c | more_itertools |
| tomli | 2.5.0 | a2a578949199336ebc3884eeba4aede87da41ef2 | src/tomli |
| mistune | v3.3.4 | 69ec2b8a6d5b37ecb3c56d96df4b40b9d3004657 | src/mistune |
| pyparsing (control) | 3.3.3 | d90d38b283efaece7ac7cace7050ba55cb82abe5 | pyparsing |

Clones: `.claude/handoff/step3/e0/spawn/<lib>` (shallow `git clone --branch`; read as data only, nothing installed or run from them).

## 3. What the base files already contain (rule run on every .py, 3.11 and 3.13 agree)

| lib | flagged at base (non-protected) | finding | hot for the workload? |
| --- | --- | --- | --- |
| more_itertools | `more_itertools/more.py` (1 of 3 modules) | line 4078 `self._module = __import__('concurrent.futures').futures` in `callback_iter` (a **thread** pool) | **Yes.** The workload calls `split_when`, `bucket`, `set_partitions`, `distinct_permutations`, `collapse`, `unique_everseen`, `consecutive_groups`, `islice_extended`, `interleave_longest`, all in more.py; the manifest profile has set_partitions 0.69 s, bucket 0.45 s, split_when 0.25 s there. |
| tomli | none (0 of 4) | `tests/test_misc.py` only, which is protected (editor cannot write it) | n/a |
| mistune | `src/mistune/plugins/__init__.py` (1 of 38) | line 1 `from importlib import import_module` (plugin loader) | **No.** `import_plugin` runs 3 times at `create_markdown`; the hot code (`inline_parser.py`, `_inline/links.py`, `util.py`, renderers) is clean. |
| pyparsing | none (0 of 17) | tests only (protected) | n/a |

## 4. Offline reproduction (base vs base + edit, the real `check_capture`)

Script: `.claude/handoff/step3/e0/scripts/variants.py`; output: `.claude/handoff/step3/e0/scripts/variants_out.txt`.

| file | edit | current rule (3.11) | current rule (3.13) |
| --- | --- | --- | --- |
| more_itertools/more.py | trailing comment | REFUSED (line 4078: uses `__import__`) | REFUSED |
| more_itertools/more.py | realistic split_when tweak | REFUSED (same finding, line 4079) | REFUSED |
| more_itertools/recipes.py | trailing comment | passes | passes |
| tomli/_parser.py | trailing comment | passes | passes |
| tomli/_parser.py | realistic: skip_chars via cached regex | passes | passes |
| tomli/_parser.py | same edit with a missing colon (SyntaxError) | REFUSED "could not be scanned" | REFUSED |
| tomli/_parser.py | valid 3.12+ syntax (PEP 701 f-string, PEP 695 `type`) | REFUSED "Python 3.11 cannot parse it" | passes |
| tomli/_parser.py | adds `from concurrent.futures import ProcessPoolExecutor` | REFUSED (correct) | REFUSED |
| tomli/_parser.py | adds `ThreadPoolExecutor` / `threading` | passes (not covered) | passes |
| mistune hot files (links, inline_parser, util) | trailing comment | passes | passes |
| mistune/plugins/__init__.py | trailing comment | REFUSED (imports `importlib.import_module`) | REFUSED |
| mistune/util.py | unclosed bracket (SyntaxError) | REFUSED "could not be scanned" | REFUSED |

## 5. Explanation per run

The live logs (`r1.log` = L2a rep 1, `r2.log` = rep 2, `log.txt` = L2b in the
scratchpad) record only the rule names per library (the summary's violations
column is the set of rules over all 8 trials), not the file or finding; the CI
artefacts and job logs could not be fetched (GitHub blob storage returns 403
through the proxy). So the per-library cause is inferred from the base scan,
the reproduction, and the cross-editor pattern:

- **more_itertools (L2a rep 1, rep 2, L2b): rule artefact, confirmed.** Any edit
  to more.py, the file holding most of the workload's profile, is refused
  because of a pre-existing `__import__` in an unrelated thread-pool class.
  This is independent of the editor: refused with Sonnet-low (both reps) and
  with Opus (L2b). In wired mode the generator targets the profile, so it aims
  at more.py. The manifest itself notes this, and its aimed hypotheses avoid
  more.py on purpose. Wired mode has no such knowledge. The best trials reached
  only 1.3-5.2 % (all in recipes.py, presumably).
- **tomli (L2a rep 1 and rep 2, not L2b): not a base artefact.** No reachable
  tomli module is flagged at base, and realistic edits pass. The refusals came
  from content the Sonnet-low editor wrote: one of (a) a SyntaxError in the new
  blob, (b) valid 3.12+ syntax the 3.11 engine cannot parse (both reported as
  `process_spawn` "could not be scanned"), or (c) an actually added spawn or
  dynamic-import API. The Opus editor (L2b) drew no refusal on tomli, which
  points to editor quality ((a) or (b)) rather than a rule-versus-base clash.
  Without the trial diffs, the three cannot be told apart.
- **mistune (L2a rep 1 only): most likely editor-added, possibly a narrow base
  artefact.** The only flagged base file is the plugin loader, which no speed
  hypothesis on the hot path needs. So either the trial edited
  `plugins/__init__.py` (for example, a "cache plugin lookup" idea), or, as with
  tomli, the editor produced an unparseable or spawning blob. Rep 2 and L2b
  (both delivered mistune) had no refusal.

Second finding: **a syntax slip is labelled `process_spawn` and gets no fix
retry.** When CPU or RSS is judged (always, by default), an edit that does not
parse is refused at capture with a misleading spawn label. It never runs, so
the D12-D15 fix retry for SyntaxError/IndentationError cannot trigger on any
edited `.py` file. Valid 3.12+ syntax is also refused whenever the engine
runs on 3.11 (CI does), even when the workload's Python would accept it.

## 6. Recommendation

**A rule fix is warranted.** It would recover a whole library from the
10-library OSS set (more_itertools, 3 of 3 runs blocked on its main file). It
would also stop mislabelling editor syntax slips as spawn attempts.

**Do not simply scan only the added lines.** Security trade-off, demonstrated in
`.claude/handoff/step3/e0/scripts/naive_out.txt`:
on a base with `import subprocess`, an added line
`subprocess.Popen([...])` passes a naive added-lines AST scan. The rule
detects subprocess only at the import, so a pre-existing spawn import becomes
free to use. The same applies to `from multiprocessing import Pool`, a bound
`import_module`, or more.py's `self._module` (which only the
`ProcessPoolExecutor` name check would still catch). Added lines are also often
not parseable on their own (indentation), so an AST scan of them is fragile.

**Safe alternative ("spawn delta", prototyped in `variants.py`, function `delta`):**
parse base and new as whole files and refuse when the new file holds a
spawn-bearing statement the base does not hold. The comparison is a multiset of
(finding, `ast.dump` of the smallest simple statement), so line shifts do not
matter. Uses of names that a spawn import bound count as findings, for example
`subprocess`, `Pool`, `import_module`. Results:

| case | current | delta |
| --- | --- | --- |
| more.py trivial / realistic edit | refused | **passes** |
| more.py adds `self._module.ProcessPoolExecutor()` (reuse of base `__import__`) | refused | refused (`uses .ProcessPoolExecutor`) |
| more.py edits the `__import__` statement itself | refused | refused (`uses __import__`) |
| synthetic base `import subprocess` + added `subprocess.Popen` | refused | refused (`uses spawn-bound subprocess`) |
| mistune plugins/__init__.py trivial edit | refused | **passes** |
| mistune adds `import_module('subprocess')` | refused | refused (`uses spawn-bound import_module`) |
| tomli adds `ProcessPoolExecutor` import | refused | refused |
| any realistic edit to clean files | passes | passes |

Residual risks (same class as today's documented non-goals: the rule "guards
against honest mistakes, it is not a defence"):

1. A spawn-bearing statement that is kept verbatim can be made reachable from
   the hot path by an edit elsewhere, for example by calling a pre-existing
   `callback_iter`. It still only starts a thread there; a pre-existing
   subprocess helper would really spawn. Mitigation: also refuse when added
   lines reference a function or class whose body holds a base spawn finding
   (a one-level call check), or flag it to review.
2. Delete-one, add-one swaps of identical statements in another place cancel
   in the multiset. Keying on the enclosing function's qualified name closes
   that.
3. The runtime backstop is unchanged: CPU and RSS are measured per process,
   and child processes are not added in. A spawn that slips through looks like
   a win, so the sandbox could also count children (RUSAGE_CHILDREN, or the
   number of processes in the trial's process group) as a second, independent
   tripwire. This is the real defence the AST rule cannot give.

**Separate the parse failure from `process_spawn`.** If the new blob fails to
parse with the engine's interpreter, emit a distinct reason (or reuse
`retry.classify`'s SyntaxError feedback with the file, line and message from
`ast.parse`) and offer the one fix retry (the owner's "one fix retry per run")
without running the unscanned code. That stays closed, since nothing unscanned
runs. To stop refusing valid 3.12+ syntax, parse with the workload's own
interpreter: run `python -I -c "import ast,sys; ast.parse(sys.stdin.buffer.read())"`
in the network-off sandbox, or run the engine on the newest supported Python.

**For E1-E4:** until the fix lands, more_itertools is a guaranteed zero in wired
mode for more.py ideas. Either exclude it from the gated success counts or
land the delta rule first. Otherwise any pipeline comparison on the OSS set
carries the artefact as noise. A cheap supplement: give the generator or matcher
the list of spawn-flagged files, so ideas aimed at them are re-targeted or
dropped before the editor spends tokens. Each refused trial still paid for an
editor request.
