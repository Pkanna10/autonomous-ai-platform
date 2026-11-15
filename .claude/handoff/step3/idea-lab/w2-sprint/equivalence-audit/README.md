# Equivalence audit of the archived keeps (O65 item 1), 2026-11-13

Zero-credit, outside the points; every reading already made stands. Built by a Lead-briefed agent; the Lead checked `out/report.json` against the table below. Scripts in `scripts/`, results in `out/` (the corpora over 1 MB are listed by hash in `out/LARGE.sha256` and kept in the Lead's scratch area). No judge was edited; the proposal is a proposal.

## Result: no counted gain rests on a non-equivalent change that I could find

None of the 309 unique archived diffs (284 keep uses and 61 delivered patches) gave any output difference from its base. Each was run against 120,000 tomli inputs, 5,000 sqlparse, 12,000 mistune and 10,000 markdown, across two fixed seeds. The sum of delivered gains that rest on a non-equivalent keep is **0 for every library**. The fault-kind breakdown, minimisation and mapping to titles therefore have nothing to report.

This is evidence, not proof. The generators can be blind to a fault: the first mistune corpus missed two planted faults (MM2 and MM3 below), so I extended the generator and re-ran all four libraries with a second seed. The harness itself does catch faults: it found 17 of 17 planted rare-input faults, while the engine's frozen checks found 8 of 17.

**Scope.** X2-SV is left out (3 sqlparse runs, which archive no diff files and no base_commit). That leaves 63 runs. Two of them delivered no patch: X2-D-43145496896 mistune ("the combine did not hold") and X2-L-43154396382 mistune (nothing kept).

**Base commits.** The `base_commit` values are commits made by the engine and are not on GitHub ("not our ref"). I cloned each library at its pinned tag instead: tomli 2.5.0, sqlparse 0.5.5, mistune v3.3.4, markdown 3.11.0. For every one of the 309 diffs, the pre-image blob ids match the tag tree, and every diff applies cleanly and touches only package files.

**How it ran.** The engine's launcher was not practical here, so each library copy ran in a plain subprocess with a timeout, wrapped in `unshare -rn` (the engine's network and user namespaces, without its Landlock or seccomp). Archived data was read with `python3 -I`. Outputs were compared type-aware: `repr` plus exact type names (tomli), the full token tree with class names, ttypes and group values plus `get_type` (sqlparse), and `repr((type, html))` (mistune, markdown). Matching exception types count as the same, and a 5 s alarm per input marks a timeout. Every base-against-base control gave 0 differences.

| Library | Keep uses (unique) | Keeps with a difference | Delivered patches with a difference | Delivered gain resting on bad keeps (all delivered gains) | Inputs per diff (2 seeds) |
|---|---|---|---|---|---|
| sqlparse | 75 (75) | 0 | 0 of 16 | 0 (398.46) | 2 × 2,500 |
| tomli | 53 (41) | 0 | 0 of 16 | 0 (245.17) | 2 × 60,000 |
| mistune | 80 (70) | 0 | 0 of 14 | 0 (229.35) | 2 × 6,000 |
| markdown | 76 (69) | 0 | 0 of 15 | 0 (250.41) | 2 × 5,000 |

**What the inputs covered.**
- **tomli:** s3's array fuzzer, copied verbatim (its file loads two tomli copies at import and cannot be imported). I widened it to whole documents and a byte mutator. About 34% of inputs are valid TOML, and 25% go through `parse_float=Decimal`.
- **sqlparse:** a SQL grammar with every rare token in the brief. Each input goes through `format` with the workload's options, `parse` and `split`.
- **mistune and markdown:** a Markdown grammar covering every block and inline construct in the brief, plus a mutator. Each library runs under four configurations: the workload's options, defaults, a wide extension set (smarty and footnotes among them), and one reused instance.

**Targeted probes, also 0 differences:**
- sqlparse's documented lexer reconfiguration (clear, set_SQL_REGEX, add_keywords) on all 91 diffs. The text-keyed lexer caches invalidate themselves in `clear`, `set_SQL_REGEX` and `add_keywords`.
- Registry and renderer changes after a first render on all 166 mistune and markdown diffs: a renderer subclass, `register`, a plugin added later, `allow_harmful_protocols`, `inlinePatterns.register` and `deregister`, and new abbreviations on a reused instance.

**Planted faults: which checks catch them.**

| Planted faults | Frozen fingerprint + test suite | Fuzz |
|---|---|---|
| tomli, s3's M1–M9 | 2/7 (M7 fingerprint, M9 suite), same as s3's table | 7/7, including M8 (`1__0`), which s3's fuzzer missed |
| mistune MM1 (bracket map ignores escapes), MM2 (href drops escapes), MM3 (safe_url case), MM4 (fast-text end skips hard breaks) | 2/4 (suite kills MM2, MM4) | seed 1: 2/4; seed 2, after adding `\)` and `HTTPS://` to the generator: 4/4 |
| markdown MK1 (inline prefilter misses space and smarty triggers), MK2 (abbreviations skip tails), MK3 (abbreviation regex loses its word boundary) | 1/3 (MK2 fingerprint) | 3/3 |
| sqlparse MS1 (no dollar quotes), MS2 (whitespace regex), MS3 (CASE pass case-sensitive) | 3/3 (suite) | 3/3 |

Fuzz and suite complement each other. MM2 was caught by mistune's suite before it was caught by fuzz, and MM1 the other way round. The rarest fault seen, tomli M8, changes 18 of 60,000 outputs (0.03%), which takes about 10,000 inputs to catch with 95% confidence.

**Budget.** Pass 1 took about 4,100 s of process time and pass 2 about 6,800 s. That makes roughly 3.0 h with the calibration and probes, on a shared 4-core machine at load 5–7, so contention inflated it.

**Limits.**
- No threading or concurrency tests.
- No inputs beyond the generators' vocabulary.
- tomli `loads` options other than `parse_float` were not used.

## Proposal: a record-only API differential gate beside the frozen judges

Strengthening only, and a proposal only: no judge was edited.

1. **Fuzz gate at the API boundary.** At baseline, record the base's type-aware output hashes once per run on a fixed, seeded corpus. For every trial, rerun the corpus in the trial's existing sandbox. Any difference, minimised, means "not shown equivalent", and the diff is flagged.
   - **Inputs:** a per-library generator, the library's own test data used as a differential seed set, and byte mutation of the workload's input.
   - **Cost, measured here** (median per trial, under contention; roughly half that on an idle CI runner):

     | Library | Inputs | Seconds per trial |
     |---|---|---|
     | tomli | 60k | 5.9 |
     | mistune | 6k | 5.5 |
     | markdown | 5k | 9.3 |
     | sqlparse | 2.5k | 24.9 |

     About 10 s per trial is enough at roughly 10k inputs for sqlparse-class costs, or 1k sqlparse inputs.
2. **Type-aware fingerprint.** Hash `repr` plus the type tree instead of `json.dumps(default=str)`. It costs about nothing, and it would have exposed s3's M9 (a tuple for a list) at the fingerprint level.
3. **Keep counterexamples.** Add every minimised difference to the corpus, as STOKE does.

**False-reject risk.** No false rejects were observed:
- 0 differences on 309 real diffs, so the 95% upper bound is about 1% of trials (3/309).
- 0 differences across 8 base-against-base controls, so the gate is deterministic here.

The remaining risks are a timeout under CI load (mitigate with a generous per-input alarm, then a retry), hash-seed ordering (the engine already forces `PYTHONHASHSEED=0`), and changes to exception types on invalid input, which the gate would correctly flag.

**Approved and built as record-only (O71 item 2, UEQ):** items 1 and 2 for the four libraries, in `services/python_agents/tests/live/x2_equiv.py`, recorded on the X2-DT rows and deciding nothing. The generators are this audit's, ported draw for draw (the first 3,000 cases at seeds 1, 2 and 7 equal `corpus.py`'s). Each library call runs in the engine's own sandbox (`run_once`, network and writes `required`, a per-input alarm). The child is `python -s -S -B -P`, not `-I`: `-I` implies `-E`, which ignores `PYTHONHASHSEED`. A library whose output holds a set then mismatched against itself in 31 of 40 cases, so the child now refuses to start unless `sys.flags.hash_randomization` is off. This audit's own runs used `python3 -I`, so they ran with random hash seeds; their eight base-against-base controls still gave 0 on these four libraries.

## How a generator is obtained for a library the engine has never seen

The four generators above were written by hand, after reading each library. A library the engine has never seen needs the same thing built by the engine at baseline, before any trial exists, and checked before it may gate anything. The harness already has the shape: an *adapter* file (`ADAPTER` with `generate`, `seeds`, `workload`, `mutate` and `evaluator`), loaded by path in the sandbox (`EquivSettings.adapter`; its own tests drive the gate with exactly such a file). The plan below fills that file for an unknown library.

**1. Where the inputs come from, in this order.** Each source is found mechanically; none needs the model.
- **The library's own tests and fixtures.** Data files under `tests/` whose extension matches the input the workload passes (`*.toml`, `*.sql`, `*.txt`, `*.md`, `*.json`), and the string and bytes literals of the test files, read with `ast.parse` and never run. This is the largest source here: tomli 972 seed cases (744 files), sqlparse 1,277 (17 scripts and the literals), mistune 909 (652 CommonMark and 257 fixture examples) and markdown 2,414 (104 texts and the literals).
- **The docs' examples.** `>>>` doctest inputs and code fences whose language matches the input type, in `README*` and `docs/`.
- **The benchmark's workload.** The engine always has it, because it defines "better". Use windows of one to three units of its input, byte-mutated, as here (`workload` source).
- **A grammar or schema in the repository.** A `.lark`, `.g4` or EBNF file, a JSON Schema, or the lexer's token table (sqlparse's `SQL_REGEX` in `keywords.py`). These give the token vocabulary for the generator.
- **Types from signatures and stubs.** For an API that takes structured values rather than text, use `inspect.signature`, annotations, `py.typed` and `.pyi` stubs to get the argument types. Each type gets a value strategy: Hypothesis-style `from_type`, with the seed values as examples.

**2. How the generator is derived, and by whom.**
- **The harness owns the generic parts.** Seed reading, workload windows, the byte mutator (`RARE` gets the grammar's punctuation and the seeds' rarest characters), the fingerprint, the alarm, the sandbox, minimisation and the record are all harness code. The model never writes them.
- **The engine writes only two functions,** in one `ENGINE_MODEL` request at the BASELINE step:
  - `generate`: a grammar-shaped generator built from the seeds, the grammar or token table, and the public API the workload calls (from the workload's imports and the profile);
  - `evaluator`: the list of public calls and configurations, taken from the workload's own calls plus each documented option. The audit's lesson applies here: mistune's second configuration and markdown's reused instance found what the defaults did not.
- **The file is frozen with the judges,** as the healer's reproducer is in Step 3c:
  - written before the first trial, outside every worktree;
  - its sha256 and the corpus's sha256 (`corpus_sha256`, already on every record) go on the run row;
  - it is loaded by path inside the sandbox, because it is model-written code (UEQ already runs every generator there, and its no-network test proves the confinement).
- **A fallback that needs no model.** If the request fails or the file fails its checks, the corpus is *seeds and workload only*, recorded as such. It is still a corpus: for tomli the seed set alone carries the `1__0` fault (M8's shape), which the generator meets 18 times in 60,000.

**3. The checks before it may gate anything.** They run once per run, at baseline, and their results go on the run row. Until a library passes them, its records stay record-only, whatever the owner rules for the four.
- **Determinism, base against base.** Build the corpus twice and get the same sha256. Run the base twice in two processes and get 0 mismatches. This audit had 8 of 8 controls at 0, and UEQ's tests check it per library. A nondeterministic call (a clock, an id, an address in a `repr`) shows as mismatches here. It is dropped from `evaluator`, or its output normalised, before any trial.
- **The planted-mutant catch rate.** Make about ten mechanical mutants of the functions the hypotheses target (the profile's top functions):
  - a comparison flipped, a constant moved by one, a branch deleted, a regex quantifier changed (`_?` to `_*`, M8's shape), an escape dropped (MM1's);
  - keep only the mutants the test suite does not kill, since those are the ones the gate is for;
  - the generator must catch at least 80% of them (this audit: 17 of 17, where the frozen checks caught 8).
  - Below that, the record says `weak generator` with the rate. The fix is the one the audit used for MM2 and MM3: add the missed tokens (`\)`, `HTTPS://`) and re-check.
- **Coverage of the touched functions.** Run the corpus once under `sys.settrace` in the sandbox. Record line and branch coverage of every function a trial's diff touches; the base's coverage map is computed once. A touched function the corpus never enters gets `uncovered` in its record: the gate is blind there and says so.
- **Power for rare faults.** A fault that changes a fraction `p` of outputs needs about `3/p` inputs for 95% detection. M8 (18 of 60,000) needs about 10,000. The size rule is the one UEQ uses: about 10 s of evaluation per tree (`SIZES`), with `p` stated on the row.

**4. When none can be obtained.** If there is no adapter, no seeds and no workload input the gate can parse, the record is `status: "no generator"` with `mismatches: null` (`equivalence_record` already does this for a library without an adapter). It never shows as 0 mismatches. A seed-only corpus is recorded as `seeds only`, so a reader can weigh it.

**5. The cost, and the anti-cheating rule.**
- **Cost:**
  - one model request per run for the two functions (about the size of the understand request);
  - the checks: two base runs and about ten mutants at about 10 s each, roughly 2 minutes once per run;
  - each trial tree: about 10 s at the sizes here. UEQ measured the four at full size at load 9 to 14 on 4 cores: 9 to 18 s per tree, the base once in 12 to 21 s, and up to 30 s of minimisation per tree that differs. That is 2 to 9 minutes per X2-DT run for 5 to 10 diffs.
- **Anti-cheating:**
  - A trial can never edit the generator or its corpus. They sit outside the repository, so no diff can name them. They are chosen by the run, not read from the trial's tree. They are hashed before the first trial, and the hash is on every record.
  - The corpus is built once, from the *base* tree's tests and benchmark. A trial's edit to its own tests (which anticheat already rejects) cannot change the seeds.
  - The evaluation runs with no network, so a trial cannot fetch a different answer.

**6. The record-only bound: a condition on promotion.** Today the trial's own code runs in the process that computes its fingerprints. That process can do four things:
- **Detect the gate.** It can tell the gate from the benchmark (`sys.argv` names `x2_equiv.py`) and answer as the base does. A trial that returns the base's output only under the gate records 0 mismatches; UEQ's test `test_record_only_bound_...` shows it.
- **Write the result file itself.** UEQ reads that file only as a plain file (no link, no FIFO), bounded in size, with its error text redacted and clipped, but its content cannot be trusted.
- **Read the base tree** (Landlock confines writes, not reads), so it could reproduce the base's outputs.
- **Know the corpus.** `corpus.json` is readable.

So the records are evidence against honest mistakes, not against a trial that targets the gate. **Before the gate may decide anything,** three changes are needed:
- **Compute the fingerprints outside the trial's process.** The trial's process only hands each raw output, as plain data, through a pipe it did not open; a separate harness process hashes it. That closes the forged result file.
- **Hide the base and the corpus from the trial's sandbox.** Its run must not be able to read the base tree or `corpus.json` (cases are fed one at a time through the pipe). That closes reproducing the base.
- **Make the gate's runs look like the workload's:** the same entry point and `argv` shape, with inputs arriving as the benchmark's do. Even then, a trial that recognises the gate's inputs could still behave differently, so a promoted gate must also be covered by the anti-cheating review, as the judges are.

Until then, every record stays record-only.

Everything is in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/audit/`. Every number above comes from a script in `scripts/`:
- **Inventory and setup:** `inventory.py`, `prepare.py`
- **Generators and corpus:** `gen_tomli.py`, `gen_sql.py`, `gen_md.py`, `corpus.py`
- **Fuzzing:** `runner.py`, `fuzz_all.py`
- **Planted faults and frozen oracles:** `calibrate.py`, `calibrate_mut.py`, `frozen_oracles.py`
- **Targeted probes:** `probe_lexer.py`, `probe_api.py`
- **Triage and summary:** `triage.py` (it had no differences to triage), `report.py`

The results are in `out/` (`report.json`, `fuzz-*.json`, `calib-mutants*.json`, `frozen-oracles.json`, `probe-*.json`). I wrote nothing in `/home/user/step3-emergence-r1`.
