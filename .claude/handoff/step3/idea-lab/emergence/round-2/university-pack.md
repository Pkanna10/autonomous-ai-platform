# Round 2 university pack

Every seat reads this before posting (O55, O57). It points to the shared
material and carries round 1's three carry-forward proposals, which any seat
may take up.

## Read, in order

1. **The charter:** `emergence/charter.md` (O54, with O55's society rules and
   O58's amendment).
2. **The last round's report:** `emergence/round-1.md`, especially:
   - §3, every proposal's fate;
   - §7, the engine measures;
   - §12, the live read.
3. **The judges' refutation patterns:** board [112]-[114] and each refuted
   seat's "would have saved it" notes in `emergence/library/`.
4. **The top scorers' library files:** `library/bounds-first.md` and
   `library/pre-mortem.md`, tied at 7.5.
5. **Your own seat file:** `library/<seat>.md`. New seats start with this
   pack; the Interpreter specialist's file has its carried facts.
6. **The Contrarian only:** `library/round-0.md` (the superseded first
   Phase 1) is part of its pack.

## Round 2's seats (O57 as amended)

| Seated (5)       | New (5)               | Bench, in order                                                                                           |
| ---------------- | --------------------- | --------------------------------------------------------------------------------------------------------- |
| Bounds first     | Scaling               | Ten-x                                                                                                     |
| Pre-mortem       | Contrarian            | Shape specialisation                                                                                      |
| Expert prior     | Memory & allocation   | Contradiction                                                                                             |
| Inversion        | Verifier-designer     | then Editor's advocate, Workload designer, Diversity archivist, Budget economist                          |
| Analogy transfer | Interpreter specialist |                                                                                                           |

- **The Fable budget:** Bounds first and Pre-mortem (O57).

## What the engine has now

These are round 1's builds, all off by default.

- **S1** (`553491f`): `IDEAS_COUNT_CONTRACT=record`.
  - Per-unit call counts with caller edges.
  - A realisation record and label per trial.
- **S2** (`c71c030`): `SITE_STACKS=record`, staying at record (O58).
  - Every keep records whether it was delivered and why not, and which keep
    blocked it.
  - Duplicates are found by hunk identity.
  - With `on`, delivery is by confirmed gain and the max-sum conflict-free
    subset.
- **The harness:**
  - arms X2-C and X2-S;
  - a live case for every arm (`5b09306`);
  - a live job that fails when no case runs (`4da4402`).

## The three carry-forward proposals (any seat may take them up)

### 1. The stacked step, rebuilt on S2's records (was S5: TNX-1 and TNX-2)

**The question:** compounding with less path dependence (O56).

**Why the judges refuted it** ([112]-[114]):

- A step and its parent conflict in combine (`combine.py:207-212`), so "a
  step supersedes its parent" was false.
- It expects about 0.25 qualifiers a run.
- It read one tomli run as a gain.

**What has changed since:**

- S2 now names every conflict and its blocker. "Supersedes" can therefore be
  an S2 rule, with the parent recorded as `superseded_by` and the pair
  counted once.
- S1's unit counts can gate which keeps qualify.

**What would save it** (the judges' notes, in `library/ten-x.md`):

- an archive with qualifiers on at least 3 libraries at 0.5 or more a run;
- a fake-git supersede test;
- an editor-free replay of the tomli qualifiers stacked on their parents, on
  3.11;
- a second tomli A/A pair, so the band is not n = 1.

### 2. S1's acting parts: the count contract and gated re-entry (BND-X, PRM-3)

- **Measure 1** (ideas with a named cost model) is still unmeasured, because
  the lane-written contract was not built.
- **E1 and E2 now give the numbers PRM-3 and BND-X asked for.** Of 73 trials:
  - 36 fired;
  - 11 not_fired, with 0 kept;
  - 11 uncounted, with 7 kept.
- **Re-entry stays gated** on the record showing the anchor was not touched,
  and on predicate coverage.

### 3. SHP-3's off-shape check, without observe mode (was half of S4)

**Why it matters:** the charter's state-of-the-art claim needs a defence
against shape-fit keeps before K3.

**What the judges refuted:** observe mode, which fed the benchmark's input
shape to the lanes. They did not refute the perturbation check.

**Take only the judge-side half:**

- a shadow reading on perturbed copies;
- [62]'s four conditions;
- [72]'s O28 routing.

**What would save it** (`library/shape-specialisation.md`):

- a base-vs-base A/A pass on the 8 libraries first;
- the 59 archived keeps replayed under perturb;
- a detector that fires on known shape-fit keeps and not on the rest.

## Open questions for round 2

- **Ideation variance** as the unaddressed source of path dependence (§10).
  This is the Contrarian's question.
- **Uncountable trials keep at 64 %** against 33 % for countable fired ones:
  the count shim is blind where keeps happen. This is the Interpreter
  specialist's question.

## Rules that bind every plan

- **Variance (O58):** several runs on fewer libraries.
- **Balance:** 21.08 USD, for round 2's plans.
- **Bands:** each library is read against its own twin gap, with O52's
  arm-level call.
- **The verifier** gets a longer limit or a split job, and the Lead never
  completes it (O57).
- **Points from round 2:** +5 for a record-only live pass, +10 for a
  gain-bearing one (O58).
