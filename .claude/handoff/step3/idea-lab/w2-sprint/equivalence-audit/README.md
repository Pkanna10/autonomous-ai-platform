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

Everything is in `/tmp/claude-0/-home-user-autonomous-ai-platform/b0055c45-9f04-5276-ac4b-c180c851948e/scratchpad/audit/`. Every number above comes from a script in `scripts/`:
- **Inventory and setup:** `inventory.py`, `prepare.py`
- **Generators and corpus:** `gen_tomli.py`, `gen_sql.py`, `gen_md.py`, `corpus.py`
- **Fuzzing:** `runner.py`, `fuzz_all.py`
- **Planted faults and frozen oracles:** `calibrate.py`, `calibrate_mut.py`, `frozen_oracles.py`
- **Targeted probes:** `probe_lexer.py`, `probe_api.py`
- **Triage and summary:** `triage.py` (it had no differences to triage), `report.py`

The results are in `out/` (`report.json`, `fuzz-*.json`, `calib-mutants*.json`, `frozen-oracles.json`, `probe-*.json`). I wrote nothing in `/home/user/step3-emergence-r1`.
