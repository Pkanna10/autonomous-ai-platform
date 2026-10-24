# Step 3b (capability acquisition) and 3c (self-healing): design inputs

Researcher, 2026-10-24, worktree `claude/step3-research` at `ea891e6`. Paths
are relative to `services/python_agents/src/autonomous_ai_agents/` unless they
start with `infrastructure/`. Anything not marked **unverified** was read in
the code at this head.

## Findings (verified, with file:line)

1. **Workloads use whatever environment the engine was started from.** The
   launcher resolves `argv[0]` (`python`, `pytest`) with `execvp` on the
   allowlisted `PATH` (`execution/launcher.py:710`), and `VIRTUAL_ENV` is
   passed through (`execution/sandbox.py:58-60`). The engine builds no
   environment itself, so user point 1 needs one on both sides.
2. **A per-trial venv can go first on `PATH` with no sandbox change.**
   `child_env` applies `extra` after the pass-through set
   (`sandbox.py:145-152`), and neither `PATH` nor `VIRTUAL_ENV` matches a deny
   pattern (`sandbox.py:63-76`). `make_phase` passes no `extra` today
   (`execution/measure.py:132-165`).
3. **A venv under `<run>/_env/` is already read-only to the workload.** Writes
   are allowed only to (worktree, scratch) (`measure.py:104-116`,
   `sandbox.py:170-180`). The worktree itself cannot hold a venv: it is reset
   before every launch (`measure.py:241`, `git.py:675-691`).
4. **The sweep would mistake new run dirs for worktrees.**
   `phase._phase_names` treats every entry of `<run>` except `_scratch`,
   `_probe` and the lock as a phase worktree (`execution/phase.py:265-282`),
   so `_env` and `_wheels` would be swept as worktrees.
5. **The recorded Python is the engine's, not the workload's.**
   `hardware["python"]` is the engine's `platform.python_version()`
   (`measure.py:321-333`), and there is no field for an environment id.
6. **There is no allowlisted-network mode.** Isolation is
   `required|best_effort|off` (`common/config.py:22,264`), the Linux wrapper is
   all-or-nothing `unshare -rn` (`sandbox.py:37-56,183-189`), and seccomp
   refuses `socket(AF_UNIX)`. The fetch phase therefore cannot reuse
   `run_once`.
7. **uv 0.11.32 has the flags needed, but no download command.** Checked
   offline with `--help` on the container:
   - `uv pip compile`: `--generate-hashes`, `--only-binary`, `--no-build`,
     `--exclude-newer`, `--python-version`, `--python-platform`,
     `--default-index`, `--no-sources`, `-c`.
   - `uv pip install`: `--offline`, `--no-index`, `--find-links`,
     `--require-hashes`, `--no-deps`, `--no-build`, `--strict`, `--no-config`;
     bytecode compilation is off by default.
   - `uv venv`: `--no-python-downloads`.
   - **`uv pip download` does not exist**, so engine code (`httpx`) does the
     download.
8. **A lockfile commit before the editor would get every package trial
   rejected.** The trial's capture diffs against the base
   (`execution/trial_runner.py:539`), and the editor commits on the worktree
   HEAD (`trial_runner.py:565`). A capability commit before the editor would
   put the lockfile into the editor's capture, where the protected-pattern rule
   rejects it (`optimization/anticheat.py:77-88`).
9. **Combine cannot take a two-commit chain.** It skips any commit that is not
   a single-parent child of the base (`execution/combine.py:246-252`). It also
   cannot use `merge-tree --merge-base`, because Apple's git is 2.39
   (`combine.py:3-12`).
10. **The protected patterns have gaps.** They miss `pip.conf`, `uv.toml`,
    `requirements*.in`, `constraints*.txt`, `pylock*.toml`, `pdm.lock` and
    `.python-version`. `.engine/**` is covered (`anticheat.py:47-103`).
11. **The failing case cannot be part of today's baseline.** A suite that
    fails at the base aborts the run (`orchestrator/nodes.py:681-692`, inside
    `_require_trustworthy_baseline` at `:647`). A workload that exits non-zero
    makes the baseline an `EngineError` (`measure.py:252-258`,
    `trial_runner.py:356-359`).
12. **A failing reproducer would trip the equivalence judge.**
    `compare_fingerprints` reports `missing_fingerprint` for a workload that
    has rows but no fingerprint on one side (`anticheat.py:213-275`).
    Reproducer rows must therefore be exempt from `EquivalenceJudge`
    (`optimization/judges.py:292-338`).
13. **The code makes behaviour changes wait for approval; CLAUDE.md says flag
    them.** `derive_verdict` rule 6 sends both `behaviour` and `novel` to
    `needs_approval` (`judges.py:674-682`). CLAUDE.md says behaviour is
    flagged and only novel needs approval.
14. **A heal needs its own objective metric.** Rule 5 requires a passed judge
    that carries a metric (`judges.py:661-668`). `ObjectiveKind.custom`
    (`common/models.py:107-112`) can carry one with no SQL change.
15. **Migration 005 is needed.** It adds `heal` to `HypothesisSource`
    (`models.py:134-138`; SQL check `chk_hypothesis_source` in `003`) and
    `acquire`/`reproduce` to `RunPhase` (`models.py:88-104`; `chk_task_phase`
    at `003_engine.sql:253-257`). The `packages` table
    (`001_initial.sql:6-14`; unique key and manager check at `002:59,74-76`)
    has no hash, licence, policy or run link.
16. **`_profile_shim.py` is the template for a heal shim.** It is stdlib-only,
    runs in the workload's own interpreter with `runpy`, and writes JSON the
    engine parses strictly as untrusted (`_profile_shim.py:1-40`,
    `profiler.py:193-218`).
17. **The generator's reply has no package field**
    (`optimization/generate.py:169-186`).

## Proposed interfaces

### 3b: automatic package acquisition

All of 3b's network code goes in a new `capabilities/` package:

- `names.py`: `near_miss(name, popular)`.
- `registry.py`: a `RegistryClient` protocol and `PypiClient`. It is
  https-only, allows only the listed hosts, follows no redirect to another
  host, and caps sizes.
- `policy.py`: `evaluate(facts, config) -> PolicyResult`. Pure, no I/O.
- `lockfile.py`: `read_base_lock`, `resolve(L0, wanted)`,
  `diff_locks(L0, L1)`.
- `wheels.py`: `inspect_wheel`. It only reads the zip: RECORD, METADATA, entry
  points.
- `fetch.py`: `Fetcher` (the network-on phase).
- `envs.py`: `EnvBuilder` (offline).

**Hypothesis side.** Add `Hypothesis.packages: tuple[PackageRequest(name,
reason), ...]`. The model names a package, never a version or a URL. A new
`acquire` node sits between `hypotheses` and `trials`, as the loop in CLAUDE.md
shows. Until 3b lands, Step 3 marks such hypotheses `needs_package` and parks
them.

**Fetch phase.** It runs in the engine process. No repository code and no
package code runs in it.

1. **Read the base lock.** L0 is read from git objects at `base_commit`, never
   from a worktree. 3b supports `uv.lock` and hash-pinned `requirements*.txt`.
   Any other format means ask the user.
2. **Resolve.** Run `uv pip compile --no-config --no-sources --only-binary
   :all: --no-build --generate-hashes --default-index https://pypi.org/simple
   --exclude-newer <now-14d> --python-version <workload python>
   --python-platform <host> -c <L0 as ==>`.
   - It runs in `<run>/_wheels/`, with `UV_*`, `PIP_*` and proxy variables
     removed.
   - Traffic goes through an engine-owned CONNECT proxy on 127.0.0.1 that
     allows only `pypi.org` and `files.pythonhosted.org` on port 443.
3. **User point 1: same environment on both sides.** Every L0 pin is a
   constraint. The baseline runs in E0, built from the base lockfile L0. The
   trial runs in E1, built from L1, which differs from L0 only by the acquired
   package and its new dependencies.
   - If the resolver needs to upgrade or downgrade an existing pin, the
     package trial does not run.
   - That pin change becomes its own `dependency-upgrade` hypothesis (class
     `behaviour`). It is measured alone against E0 and shown in the report.
   - The package trial may follow later, only if the upgrade is kept.
4. **User point 2: no wheel means ask.** With `--only-binary :all: --no-build`,
   a package or transitive dependency that exists only as an sdist fails the
   resolution. That is `PolicyResult(needs_user, "sdist_only: <name>")`. It
   goes to the user and is never built automatically: building runs code.
5. **Download.** Engine `httpx` code, behind the same host allowlist, fetches
   one wheel per pin that matches the interpreter's tags. Each sha256 is
   checked against the `--generate-hashes` value, and the wheel lands in a
   content-addressed store (`sha256/<digest>.whl`).

**Policy checks.** All facts are gathered first, so every check can be tested
on recorded JSON.

| Check | Data source | How it is reached |
| --- | --- | --- |
| Name exists | `pypi.org/pypi/<name>/json` (a 404 fails) | Fetch phase |
| No near miss | Committed, dated snapshot of the top ~15k PyPI names. Fails on Damerau-Levenshtein distance ≤ 2, `-`/`_`/`.` folding, `python-`/`-py` affixes or confusable characters | Offline. Refreshed on the user's machine or by CI, like the arXiv snapshot |
| Project at least 90 days old; version at least 14 days old | JSON `upload_time_iso_8601`; `--exclude-newer` covers every transitive dependency | pypi.org |
| Enough downloads | `pypistats.org/api/packages/<name>/recent` (the PyPI JSON no longer reports downloads) | A third allowed host; **unverified** that it is reachable |
| No known vulnerability or malware | Per-version `vulnerabilities` in the PyPI JSON (**unverified** that OSV sources it), else `api.osv.dev/v1/querybatch`, which includes `MAL-` advisories | pypi.org or api.osv.dev |
| Licence allowlist: MIT, BSD-2/3, Apache-2.0, ISC, PSF-2.0. Anything else, or none, asks | The wheel's METADATA `License-Expression` (PEP 639), else its classifiers | Offline |
| Wheel content | RECORD has no absolute or `..` path, no `*.pth`, no `*.data/scripts`, and no console script named like a workload's or the test command's `argv[0]` (a `pytest` script would replace the judge) | Offline |
| One index only | The user's config names no other index (`[tool.uv.index]`, `--index-url` lines, `pip.conf`, `uv.toml`), and no local package has the same name | Git objects at base |

A check that cannot run fails, and a failed check asks the user. The checks
spend no tokens, and a playbook-named package still goes through every one.

**Environments.** These steps run offline:

- `uv venv --no-config --no-python-downloads -p <workload python>
  <run>/_env/<lock-sha>`.
- `uv pip install --no-config --offline --no-index --find-links <store>
  --require-hashes --no-deps --no-build --strict -r <lock>`. A wheel install
  only unpacks files; no package code runs.
- `make_phase(..., env=EnvHandle)` passes `VIRTUAL_ENV` and an env-first
  `PATH` (finding 2) and points a `PYTHON_NAME` `argv[0]` (`measure.py:72`) at
  the env's interpreter.
- A workload that names an absolute interpreter outside the env gets a note,
  and the run skips package hypotheses.
- `_host` records `env_lock_sha256` and the workload's Python (finding 5).
- The sweep excludes `_env` and `_wheels` from the worktree list and removes
  them (finding 4).

**Baseline on the same lockfile.** The `acquire` node measures an env baseline
in E0 and stores it in `state["env_baselines"][lock_sha]`. A trial is judged
only against the baseline whose `env_lock_sha256` equals its parent lock; any
other pairing is `inconclusive`.

**Engine-owned lockfile commit, recomputed and compared.**

1. Before the editor runs, the capability step writes L1 and the manifest
   line and commits them as **C1** (engine identity, trailer
   `Engine-Capability: <sha>`).
2. Capture becomes `changes(handle, C1)` (finding 8), so the existing rule
   still refuses any editor edit to a manifest or lockfile.
3. C1 is valid only when:
   - `base..C1` touches only the manifest and the lockfile;
   - its blobs equal an independent offline `resolve(L0, approved)` run in a
     fresh dir;
   - `diff_locks` shows no pin changed or removed.

For combine, each kept package trial is rebuilt as X′. Its tree is C2's with
the base's manifest and lock entries put back, and its only parent is the
base; it is written through a temporary `GIT_INDEX_FILE`, so it passes
`_unfit` (finding 9). One combined capability commit, re-resolved from the
union of kept packages (never text-merged), goes onto ACC first. In the
re-test, side A runs in E0 and side B in E(combined).

**Drop a package with no proven gain.**

- The package trial must beat the E0 baseline beyond the noise floor.
- After combine, an AST import scan (through the wheel's `top_level.txt` and
  RECORD) finds any package no kept change imports. That package is removed,
  the lock is re-resolved and the combination re-tested.

**Delivery.** The branch holds the capability commit first, then the code. The
capability commit carries the lockfile diff and, per package: why it was
added, which change imports it, its gain and its policy evidence. The report
says: "This branch adds `<name>==<ver>` and N dependencies; you must install
them (`uv sync` or `pip install --require-hashes -r <lock>`)." Migration 005
adds `sha256`, `license_expression`, `first_release_at`, `downloads_recent`,
`policy_result` and `checked_at` to `packages`, plus a `run_packages` table
(run, package, hypothesis, reason, outcome `kept|dropped|needs_user`, gain).

### 3c: self-healing of the user's code

**Input.** `HealCase` has:

- `kind`: `failing_test`, `crash` or `error_report`;
- `test_node_id` or `workload_id`;
- `signature`: exception type, message and frames (file, function, line).
  Never locals: they can hold secrets.

The caller supplies it in 3c; error-monitoring intake is Step 4.

**Graph.** A heal run is a run of its own: connect, understand, define,
baseline, **reproduce**, hypotheses, trials, judges, verdicts, deliver.

- `define` sets `Objective(custom, "heal_passed", maximize)`, wall-time and
  RSS `metric_bound` guardrails, `tests_pass` and `output_equivalence`.
- `baseline` measures every workload except the failing case. Pytest runs
  with `--deselect <node id>`. Unittest has no deselect, so the run asks the
  user. With the failing case left out, `_require_trustworthy_baseline` passes
  (finding 11).

**Reproducer integrity (user point 3).** The `reproduce` node:

1. **Writes it in a separate request, before any fix is attempted.**
   `ReproducerWriter.write(case, sources_at_base, budget)` is its own `call()`
   through `Budget`. It has no tools, and the report text is fenced as
   untrusted. It returns a stdlib-only script that asserts the expected
   *value*, not just "no crash", plus 2-3 held-out variants. For a
   `failing_test` case the user's test is the reproducer.
2. **Checks it statically.**
   - Imports: the stdlib and the repository's modules only.
   - The `_spawn_problem` scan (`anticheat.py:560`).
   - No `try` around the target call.
   - A size cap.
3. **Freezes it as a protected file.** It is stored at
   `<run>/_heal/repro_<id>.py`, which is outside `writable` and therefore
   read-only (finding 3). Its sha256 is checked before every run, and its
   delivered path goes into `extra_protected` (`orchestrator/state.py:121`).
4. **Requires it to fail on the baseline N of N.** It runs
   `settings.MIN_RUNS` times, with a reset before each run, under
   `_heal_shim.py` (finding 16).
5. **Requires it to fail for the reported reason.**
   - Every run raises the same qualified exception type as the report.
   - The exception is raised in a **repository file at base**, not in the
     reproducer; this blocks a reproducer that raises the error itself.
   - The innermost repo frame (file, function) matches the report, **or** the
     message matches with numbers, addresses and ids masked.
   - A mismatch gets one retry, then the run asks the user.

**The fix's trial.**

- One generic `source=heal`, `behaviour` hypothesis; one generic hypothesis
  was enough for 10/10 on the hard corpus.
- The editor sees the report and the public reproducer, never the held-out
  variants.
- **The fix trial may not touch the reproducer.** A new capture rule,
  `heal_tamper`, rejects a diff that names the reproducer's file or module,
  `.engine`, `sys._getframe`, `inspect.stack`, `sys.excepthook`, `atexit` or
  `os._exit`.
- A broad `except` added on the reported frames is flagged in the report.

**Judges.**

- `HealJudge` (metric `heal_passed`) passes when the reproducer and every
  held-out variant run N of N with exit 0 **and** the shim records completion.
  A missing shim document counts as a failure.
- `EquivalenceJudge(exempt_workloads=...)` exempts only the reserved
  reproducer ids (finding 12); every other workload stays byte-identical.
- `TestSuiteJudge` runs the full suite with no deselect. It must pass with a
  count of at least the baseline's count plus one.
- Speed and memory are guardrail bounds, not objectives.

**Delivery.** Commit R adds the reproducer at
`tests/engine_heal/test_<slug>.py` (protected by `**/tests/**`). Commit F, the
fix, comes after it. The report shows the reproducer next to the fix, with the
signature, the N/N failures on the baseline and the N/N passes on the trial.
The change is class `behaviour` and is delivered flagged (Q5).

## Tests that would prove it

Offline unless marked live. They use a recorded-JSON `FakeRegistry` and tiny
pure-Python wheels built with `zipfile` under `tests/fixtures/wheels/`.

**3b**

- **Names**: `reqeusts`, `numpi`, `python-dateutil` and a Cyrillic homoglyph
  are near misses; exact popular names are not.
- **Policy**: each check passes and fails; an unreachable host gives
  `needs_user`; an unknown licence asks.
- **Lockfile**:
  - a forced pin change refuses the trial and emits a `dependency-upgrade`
    hypothesis (point 1);
  - a transitive dependency that is sdist-only gives `needs_user` (point 2);
  - resolving twice gives the same bytes.
- **Wheels**: `../`, `.pth`, `*.data/scripts` and a `pytest` console script
  are each refused.
- **Environments** (Linux and macOS): installs work offline inside
  `unshare -rn`; a changed wheel fails closed; the env cannot be written; E0
  and E1 differ only by the added distributions.
- **Trial runner**: an editor edit to `uv.lock` after C1 is `protected_path`;
  a tampered C1 fails the recompute; a lock-hash mismatch is inconclusive.
- **Combine**: X′ passes `_unfit`; two package trials give one re-resolved
  lock; an unimported package is dropped and the combination re-tested.
- **Phase**: the sweep removes `_env` and `_wheels`.
- **Capture**: the patterns from finding 10 are refused.
- **E2E**: a fixture wheel that speeds up a hot loop is delivered with the
  install line; in a control where it does not help, it is dropped.
- **Live** (CI only, a network-on job): one real PyPI wheel fetched and
  vetted, and a recorded slopsquat name refused.

**3c**

- **Reproducer**:
  - 5/5 with a matching signature is accepted;
  - 3/5, a wrong exception type, an error raised inside the reproducer, or a
    sha change is refused;
  - a message-only match is accepted when the frame is in the repo.
- **Judges**: `HealJudge` handles a pass, a flaky run and a missing shim
  document; equivalence exempts only the reproducer ids; a change to another
  workload's output rejects.
- **Capture**: each `heal_tamper` token is rejected.
- **Nodes**: the pytest `--deselect` baseline; the flagged route.
- **E2E corpus**: 5 planted bugs (KeyError, off-by-one, None, encoding,
  mutable default) and 3 controls (cannot reproduce, intended behaviour, a
  stack outside the repo). Every control must end with "ask the user" and no
  branch.
- **Live**: Sonnet 5.5 low as the editor for fixes is **unmeasured**; E8a
  covered speed edits only.

## Risks and open questions

**Threat model.**

- **Slopsquatting**: a name only the model proposed passes the existence, age,
  download and near-miss checks like any other.
- **Dependency confusion**: one public index, `--no-config`, never an
  extra-index-url; any other index, or a local package with the same name,
  asks.
- **A compromised popular package**: the 14-day version age plus OSV `MAL-`
  advisories.
- **A malicious wheel**: imports run only in the sandboxed trial. The real
  exposure is the user's machine after delivery.
- **Time-of-check to time-of-use**: the content-addressed store plus
  `--require-hashes`.
- **Reproducer gaming**:
  - by the writer: the repo-frame rule;
  - by the editor special-casing the reproducer: the held-out variants and
    `heal_tamper`;
  - by suppressing the error: a flag and human review;
  - by code in the same process forging the shim's output: exit code, the
    shim document and the variants are all required. The rest is accepted,
    like Step 2's memorisation gap.
- **Injected error text**: fenced as untrusted, with no locals sent.

**Open questions.**

- **Q1.** A proxy around a pinned, trusted `uv`, or a network namespace with
  a route only to the proxy (`pasta` or `slirp4netns`)? The Lead decides.
- **Q2.** Must a package trial also beat a kept trial without the package on
  the same hotspot?
- **Q3.** No lockfile: ask the user (recommended), or let the engine create
  L0?
- **Q4.** **Unverified** that pypi.org, files.pythonhosted.org, pypistats.org
  and api.osv.dev can be reached from runners and the container proxy. Probe
  them before 3b's live job.
- **Q5.** Does "flagged" mean delivered without the gate, on a local branch
  that is never pushed and carries a review header, or does `needs_approval`
  stay? The user decides (finding 13).
- **Q6.** A fix that rightly changes another workload's output: reject and
  ask (recommended)?
- **Q7.** A failed check parks the hypothesis and the question goes in the
  end report rather than a mid-run interrupt (recommended).
- **Q8.** Which model writes the reproducer is unmeasured; Sonnet 5.5 medium
  is the guess from E3.
- **The E5 paper switch** does not affect 3b or 3c.

**Out of scope until Step 4 or later**: MCP and API discovery; intake from
error monitoring; the CLI prompt; CUDA and MPS wheel indexes; private indexes
and credentials; npm; building sdists, even when approved; resuming across the
fetch phase; multiprocessing `spawn` in reproducers; production rollout
(Step 6).
