# Step 3 spec amendment: the idea lab (G units, X rounds, K runs)

**Approved by the owner with changes (O36); revision 4 carries them. X1 is not
dispatched until its re-derived estimate is reported.** Revision 4
(2026-11-01): the marker validated on measured outcomes plus an owner-labelled
novelty sample; an execution slice in X1; a deterministic views pass; X1-1's
Latin-square rotation; X1-3 labelled two factors; the sampling-noise reading;
G9's salted hash; G8's measured references; smoke requests to Sonnet 5 and
Fable 5. Revision 3 applied O31-O35; revision 2 added the dedupe validation, the
history view's guard and the branch sequencing.

Base: `claude/step3-research` at `38495de`. Paths are relative to
`services/python_agents/src/autonomous_ai_agents/` unless they start with
`tests/`, `infrastructure/` or `.github/`. Anything inferred is marked
**unverified**.

Source of the decisions: STATUS.md Decisions, 2026-11-01 (O23-O30), and the
owner's two messages of that date (the idea-lab brief and the revised O28). This
amendment does not change Wave 1, 2, 3, 3b or 3c; it opens a new line of work
that runs after Wave 2's remaining units land, and its live rounds spend from
Window 1 under O22 (no per-run budget cap; report credit and estimate before
each run).

Labels (recorded in STATUS "Labels"): **G** idea-lab build units; **X**
exploratory rounds (prove nothing; full idea lists shared); **K** confirmatory
runs (one pre-registered run per ladder rung).

---

## 0 Why this exists (the problem E1 showed)

E1 (STATUS 2026-10-31) found the idea pipeline mostly re-discovers today's
generator's ideas at ~17x the cost. Reading the full idea lists (run
41186544846, tomli and pyparsing): every lane, whatever its lens, proposed the
same local micro-edits to the same hot lines. Causes, by impact:

1. 15-32k tokens of identical hot code drown a ~100-token lens; models propose
   what they see.
2. The rules (quote a hot line, byte-identical output, no new dependency, no
   new process) leave few distinct local edits in a mature pure-Python library.
3. Lens lanes run in parallel, blind to each other; the "on the table" list
   holds S1's titles only, so a mechanism returns under a new title.
4. Arms B, C and D are one Sonnet generator sampled three times; only E (Haiku
   lanes) differed, and under the strict re-score it found the most ideas new
   to today's generator.

Also: the honest-exam misses had best trials of 1.8-3.8 % under 2-5.9 % noise
floors, so idea **size** is as much the bottleneck as diversity, and the
biggest measured gains came from **compounding** (evolution, STATUS Wave 1:
mean 22 % to 35 %, sqlparse 52 % and rising). The redesign changes *what each
lane thinks with*, and wires the pipeline into evolution.

---

## 1 The four levers (G1-G5)

Each lever is a build unit, TDD, Reviewer on a different model, Lead gate, one
commit. The pipeline keeps its shape (S0 context, S1 obvious, lens lanes, leap,
reviewer, portfolio); the levers change its inputs, not its skeleton.

### G1 — Who thinks: mixed-model lanes and the price table

- **Price table** (`common/config.py` `_DEFAULT_PRICING`): add `claude-sonnet-5`
  ($2/$10 in/out), `claude-haiku-4-5` ($1/$5 in/out, 200K context), and
  `claude-fable-5` ($10/$50 in/out). **Cache-write/read rates for all three
  must be taken from the live pricing page at build time, not guessed** (the
  pricing row of the `claude-api` skill's `shared/live-sources.md`); the unit
  fails its own test if a rate is left at a placeholder.
- **Per-lane model**: a lane may name any model in the table. Diversity comes
  from models, views and prompts, since every current model rejects
  `temperature`.
- **Haiku 4.5's request shape** (`clients/transport.py` or a small adapter):
  Haiku 4.5 takes no `effort` and uses `thinking: {type: "enabled",
  budget_tokens: N}` (N < max_tokens, min 1024); every other listed model uses
  `effort` and rejects `budget_tokens`. The adapter picks the shape by model id,
  with a test per shape. (Fact source: `claude-api` skill, thinking table.)
- **Retention (O15 unchanged)**: Fable 5 and Fable 5.1 require 30-day retention
  (not available under zero-data-retention), so a Fable lane sets
  `ALLOW_RETENTION_MODELS` only on a pinned OSS library, exactly as arm D does
  today; the guard is reused, not rewritten.
- **Haiku 4.5 deferred (O31).** The highest-maintenance lane (own shape, 200K
  context so the "whole module" view may not fit, 10x Haiku 5.5's price). G1
  adds its price row but not its request shape; the shape is built only if X1's
  mixed-model lever shows diversity worth chasing.

### G2 — What they see: a view per lane

`optimization/idea_context.py` gains view builders, one per lane, each a
different slice of the same profiled repository:

- **callers** of the hot function (who calls it, how often, with what shapes);
- **data structures** the hot path touches (types, sizes, mutation pattern);
- **real input shape** (from the workload's actual inputs, not a description);
- **whole module** (the file around the hotspot, not just the function);
- **2nd and 3rd hotspots** (not only the top one);
- **performance-commit history** (the project's own past speed-up commits, from
  `git log` on the pinned clone, as prior art).

Each view is capped and fenced like today's data block; a lane gets one view,
not all of them, so the ~100-token lens is no longer drowned by one giant
identical block.

**Contamination guard (history view).** The performance-commit history is read
only up to the pinned commit, never past it. On the held-out rungs this matters:
a held-out library is pinned before any fix it is scored on, and V9's keys sit
after `before_sha` by construction, so the history view can never show the
answer.

### G3 — What they may change: rule-relaxing lanes (quarantined proposals)

Lanes that relax a frozen rule: a new dependency, a changed output order,
install-time precompute, an API change. **Structural quarantine, not a prompt
instruction** (Lead pushback, accepted):

- A rule-relaxing idea carries a `proposal` tag from birth, set by the lane, not
  inferable away.
- Tagged ideas run only in a separate proposals path that **never delivers and
  never counts toward any gate or verdict**; they are reported for a human.
- `optimization/anticheat.py` / the judges reject a trial that claims output
  equivalence while carrying the `proposal` tag — the tag and an equivalence
  claim are contradictory, so a tagged idea can never be mistaken for a shippable
  win.

This is where the "unthinkable" ideas live, safely walled off from the proof
path.

**Gate before X1 (O32).** G3 gets a security review (a separate Reviewer, on
the quarantine only: the tag cannot be dropped, the proposals path cannot
deliver or count, the anti-cheat rejects a tagged equivalence claim) before X1
uses it. If the review is not clean in time, X1 runs three levers and the
rule-relaxing configuration becomes X2. The lane never runs without the
quarantine.

### G4 — What is already taken: sequential lanes, mechanism dedupe

- Lanes run **sequentially**, each shown the **mechanisms** (not titles) of the
  ideas earlier lanes already produced, with a "do not repeat these mechanisms"
  instruction.
- A **mechanism-level duplicate filter** (`optimization/idea_portfolio.py` or a
  new `idea_dedupe.py`): two ideas are the same when they change the same target
  lines by the same transformation, regardless of wording. This also fixes E1's
  scoring flaw (the pooled auditor's `duplicate_of` verdicts) at the source.
- Sequential lanes cost wall-clock; the per-lane minutes model (re-pinned from
  E0b-style counts) sets the job timeout.
- **The dedupe is itself a measurement, so it is validated before its numbers
  count (Lead pushback).** "Unique mechanisms" and "share new to today's
  generator" are the lab's headline idea measures, and E1 showed one unvalidated
  measurement flipping a gate. Acceptance: a labelled set of idea pairs drawn
  from E1's recorded ideas (same mechanism / different mechanism), labelled by a
  model that wrote none of them and spot-checked by the owner; the dedupe must
  agree with the labels at a bar fixed before it is run (proposed: at least 90 %
  of pairs, and no more than 5 % of different-mechanism pairs merged). Until it
  passes, X rounds report raw idea lists and the dedupe's output side by side.

### G5 — Each lane gets a framework; compounding into evolution

- **Per-lane idea framework** (`optimization/idea_prompts.py`): each lane's view
  or relaxed rule comes with a short framework that steers it (e.g. the callers
  view with "push work to the caller or memoise across calls"; the input-shape
  view with "specialise for the shape the workload actually passes").
- **Compounding** (`orchestrator/nodes.py`, `optimization/evolve.py`): the spec
  states how the pipeline feeds evolution rounds (the kept ideas of round N seed
  round N+1 with their measured gains, FunSearch/AlphaEvolve style), and how
  **near-miss ideas** — each individually below the noise floor — are combined
  into one trial so their gains can add. A combined-near-miss trial is a normal
  trial under the frozen judges; nothing about it relaxes a rule.
- **Folded-in Wave 3 units (O35).** W4 (evolution: near-miss compounds) becomes
  part of G5. W1 and W2 (lessons in the generator prompt; the combine-failed
  lesson discount) become G11, the lab's learning mechanism: each round's
  verdicts become lessons that steer the next round's lanes. W3 (hotspot tags)
  is deferred.

---

## 2 Two new judges, shadow mode (G6)

Both **record, never decide**, until the owner promotes them.

- **Scaling judge**: run each workload at 2-3 input sizes, fit how run time
  grows with size; a real algorithmic change alters the growth rate, a
  micro-tweak does not. Needs a **size setting** per workload — a protected
  benchmark file, so the Lead or the setter adds it, never a trial.
- **Operation-count judge**: deterministic counts (calls, allocations, bytecode
  steps), noise-free, so small real gains become visible. **A second signal
  only**: moving work into C built-ins can cut counted steps without cutting
  time, so it never overrides the timing judge.
- **Promotion gate** (owner approval required): before either judge decides a
  verdict, it must pass an A/A check (no difference on identical code), a
  controls check (no false win on the decoys), and a gaming check (a trial that
  targets the judge's metric without a real gain is caught). Until promoted,
  their output is a column in the report, nothing more.

---

## 3 The idea lab: how we work (G7, the process doc)

A short process doc (`.claude/handoff/step3/idea-lab.md`) that the rounds follow.

- **Goal**: a general "make it better" engine for any code and any measurable
  objective (speed, memory, operation count, ML accuracy on sealed held-out
  data, web performance, security under O28), with proof. Iterate on
  architecture, models, prompts and frameworks until it beats the public state
  of the art, **with no promise that it will**.
- **Fixed in every experiment**: the frozen judges, the budgets, the sealed test
  sets.
- **Varied, one or two factors a round**: the four levers, frameworks, selection
  method, idea count, effort, evolution rounds, and a **diversity archive** (the
  best idea of each mechanism kind, kept across rounds).
- **Exploratory rounds (X)**: small, labelled exploratory, **prove nothing**.
  They share the **full idea lists** of every round — per arm and lane: title,
  mechanism, target lines, verdict, duplicate-of — so the owner and a reviewing
  session can read and steer.
- **Confirmatory runs (K)**: once a design settles, **one pre-registered run per
  ladder rung**, on sets never used while designing. Pre-registration fixes the
  scoring before results; the architecture may change freely between runs.
- **Stopping rule (Lead pushback, accepted; O33)**: each confirmatory rung has a
  "minimum worth continuing" bar, pre-registered before that rung's run and
  approved by the owner; no single number is fixed now. If two rungs in a row
  miss their bar, the lab stops and reports rather than tuning further.
- **Idea-level measures**: unique mechanisms after dedupe; share new to today's
  generator; ideas whose ceiling clears the noise floor; spread across mechanism
  families; predicted change in growth rate (the scaling judge, shadow); an
  owner-read sample. **Execution-level**: wins, gain size, cost per win, the
  compounding curve over rounds.

---

## 4 The test ladder (G8-G10 build the lower rungs)

1. **Development set** — today's 8 OSS libraries. **Exploratory (X) only.**
2. **Unseen problems (G8)** — 6 domains x 3 tiers = 18 problems: data structures
   and storage, ML training on CPU (quality tolerance, not byte equality; NumPy
   declared up front), data processing, parsing, numerical code, web-backend
   request handling, plus security tiers in parsing and web-backend. Tiers:
   textbook, memory-or-efficiency, beyond-textbook (a workload shape where a
   tailored hybrid beats the textbook answer). Each problem: big headroom,
   several valid routes, a sealed expert reference, a size setting for the
   scaling judge, no famous-benchmark framing. **Setter: Fable 5.1, never the
   attempter, under O19.** Attempter: the engine. Marker: the frozen judges plus
   the idea-quality marker (open slot, §7). Fable 5.1 is a retention model, so
   the setter runs under O15 on OSS-pinned material; the setter's problems are
   sealed before any tuning. **No Fable attempter on rung 2 (O34):** Fable 5.1
   sets the rung and writes its sealed references, and a same-family attempter
   can match a reference by shared bias, so neither Fable 5 nor Fable 5.1 runs
   as an idea lane on rung 2. Fable lanes stay allowed on the development set,
   V9 and the held-out OSS set.
   **Measured references (O36.5d):** before a problem is sealed, the frozen
   judges measure its expert reference on the problem's workload: the gain must
   clear the measured floor and the output (or the quality tolerance for the ML
   tier) must hold; a reference that fails is fixed or the problem is dropped.
3. **Held-out OSS libraries (G9)** — chosen and sealed now, before any tuning,
   so they cannot leak into the development set. **Sealing (O36.5c):** the list
   is picked by a separate session that does no tuning and never sees the lab's
   prompts or results; the list (library, pinned commit, workload) is kept
   outside the repository; only a salted hash of it is committed now, and the
   list and salt are revealed at the K run so anyone can check the hash.
4. **V9** — the sealed maintainer fixes, already built.
5. **SWE-Perf / GSO / SWE-fficiency (later, own unit)** — the Python tasks,
   scored their way, compared with published agents. **Informative, not a
   claim**, unless contamination (public leaderboards, possibly in training
   data) can be ruled out; adapting the harness is its own build unit, after the
   lab settles.

---

## 5 Security scope (O28, verbatim intent)

The engine's defensive source-analysis scope is O28 in STATUS (revised
2026-11-01): the OSS-Fuzz / CodeQL / Semgrep model. In this spec it is a
**proposals-path capability**, built on G3's quarantine:

- **May analyse**: the owner's code, the owner's dependency tree, and any public
  open-source repository, as source or as a build the engine compiles inside its
  own sandbox.
- **How**: inspection, static analysis, or fuzzing/testing a local sandbox
  build, always on a copy with dummy data — never real credentials or real data.
- **Delivers**: a finding = a contained sandbox reproducer on the local copy + a
  plain report + a proposed fix when it has one, all to the review branch.
- **A human owns disclosure, every time.** The engine never discloses,
  publishes, contacts a maintainer, or acts on a finding itself.
- **Scale guardrail**: high-confidence findings with a reproducer only.
- **Out, non-negotiable**: no active probing of live or deployed third-party
  systems the owner does not own or is not authorised to test; no weaponised or
  deployable exploit artifacts (a contained proof-of-concept on the local copy
  only); no autonomous disclosure or action. Broader authorised third-party
  engagements are a human-led track, out of this spec.
- **Judges**: a frozen reproducer that fails before the fix and passes after,
  static analysers, and the full suite with no regression. Lanes are prompted
  as defensive review; refusal categories are logged.

A security finding is a `proposal`-class output (G3): it never auto-delivers and
never counts toward an efficiency gate.

---

## 6 The first exploratory round (X1)

- **No budget cap in practice** (O22): a high CI ceiling for the engine to run,
  bounded by **scope**, not dollars; the 80 USD fuse stays per dispatch. Report
  cost per configuration and share every idea list.

### 6.1 Before X1: inputs and validations (no idea generation)

- **Views pass (O36.3).** A recorded hotspot holds no caller graph or argument
  shapes, so the callers and input-shape views cannot come from E1's
  `ideas-facts` rows. One deterministic, no-API pass per library at the
  recorded commit builds every view (callers, data structures, input shape,
  whole module, 2nd/3rd hotspots, performance-commit history up to the pinned
  commit) and stores it once as new rows; every configuration reads those rows,
  so all share identical inputs. Profiles stay E1's.
- **Marker validation on measured outcomes (O36.1).** Not the grader labels:
  V5's 12 builder-written labels and the 75 sweep-record labels grade hit or
  miss on planted slowdowns in a saturated corpus and cannot separate the two
  candidates. Source: the `E5-oss-ab-rank` rows of Window 0's oss-ab runs (per
  idea: title, class, verdict, gain, noise floor; 18 libraries). The marker
  sees the title, the class and the hot code from the pinned clone, never the
  result, and ranks the ideas of each (library, repetition, arm) set; its score
  is the rank agreement with the measured outcomes (kept above the floor >
  trialled and not kept > ...). Only rows with a real verdict count (not
  `NOT_TRIALLED`, not `NO_RESULT`); **the Lead reports that count and the owner
  fixes the bar before the run.** Titles only, no mechanism text: a first
  check, not the final one. The execution slice (§6.3) becomes the full-text
  validation set.
- **Owner-labelled novelty sample.** 20-30 ideas drawn from E1's lists (mixed
  arms and lanes), shown to the owner without their source, labelled new or
  not new to today's generator; the marker's novelty calls are scored against
  them.
- **Dedupe validation (G4):** labelled E1 idea pairs, bar fixed before it runs.
- **Smoke requests (O36.5e).** The V suite sends one live request each to
  Sonnet 5 and Fable 5 (the two models X1 adds to the price table) before any
  X1 configuration runs.
- **Marker independence rule:** every idea is graded by the best-validated
  marker that did not write it. If Opus 5.5 wins, ideas written by an Opus 5.5
  lane or leap are graded by Opus 5 (the runner-up), all others by Opus 5.5; if
  Opus 5 wins, it grades everything (no lane is Opus 5).

### 6.2 The idea configurations, one lever each

S1 and the six lens lanes = 7 idea lanes; leap and reviewer as today unless
stated:

| Config | Lever | Idea lanes | What changes vs baseline |
| --- | --- | --- | --- |
| X1-0 | baseline | today's pipeline (arm C: Sonnet 5.5 lanes `medium`, Opus 5.5 leap and reviewer `high`) | none; re-run once on E1's facts |
| X1-1 | who thinks (G1) | S1 Sonnet 5.5; lenses on Sonnet 5, Haiku 5.5, Opus 5.5, Fable 5, Fable 5.1, Sonnet 5.5 | model per lane, **rotated across lenses over the 8 libraries (a 6x6 Latin square, rows 1-6 then 1-2)** so model and lens effects separate; same view, prompts and order |
| X1-2 | what is taken (G4) | baseline models | lanes in sequence, each shown earlier lanes' mechanisms; mechanism dedupe |
| X1-3 | what they see **and** how they think (G2 + G5) | baseline models | each lens lane a different view with its framework; **two factors, labelled so; split in X2 if it wins** |
| X1-4 | what they may change (G3) | baseline models | four lanes, each relaxing one rule (new dependency, output order, install-time precompute, API change); proposals only, reported, never scored or trialled; only behind the reviewed quarantine (O32), else X2 |

- **Today's generator alongside**: arm A (one Sonnet request, 0.025 USD) is
  re-run on the same facts, so "share new to today's generator" compares
  against a same-day reading, not only E1's.
- **Sampling noise (O36.5b)**: E1's arms B, C and D (one Sonnet lane generator
  sampled three times) plus X1-0's re-run give the spread of every idea measure
  by sampling alone; a configuration's difference counts only beyond it.
- **Libraries**: the 8 development libraries (more_itertools, pyparsing, tomli,
  sortedcontainers, mistune, sqlparse, markdown, idna); sortedcontainers is the
  reported control.
- **Idea measures per configuration**: ideas proposed; unique mechanisms
  (validated dedupe); share new to today's generator; ideas whose ceiling clears
  the run's floor; spread across mechanism families; marker-feasible ideas;
  cost. X1-4 reports its proposals by rule relaxed, with no score.

### 6.3 The execution slice (O36.2)

Idea measures alone leave the size question open, so X1 also runs ideas.

- **What runs**: per idea configuration X1-0 to X1-3, the top 2-3 ideas new to
  today's generator (by the validated marker), on sqlparse, pyparsing and tomli,
  with sortedcontainers as the control: 4 libraries x 4 configurations x 2-3
  ideas = 32-48 trials, each a normal engine trial (Opus editor, sandboxed
  worktree, the frozen judges, N >= 5 runs against the measured floor), then
  the combine per (configuration, library).
- **What is recorded**: every trial's full idea text (title, mechanism, target
  lines, rationale), verdict, gain and floor, and every combine summary. This is
  what the eventagg finding showed was missing, and it makes the slice the
  marker's full-text validation set.
- **Reading**: lever rankings from the idea measures alone are provisional; the
  slice says whether a configuration's ideas win trials more often, or by more,
  than the baseline's. With 3-12 trials per configuration it is exploratory,
  not proof.
- **Dispatch**: two execution dispatches of two libraries each, so each
  dispatch's worst case stays under the 80 USD fuse (per trial worst case 2.50
  USD as in E2's plan; 24 trials = 60).

### 6.4 Expected cost (re-derived with the views pass and the execution slice)

| Part | Basis | Expected USD |
| --- | --- | --- |
| Views pass | deterministic, no API | 0 |
| Smoke requests (Sonnet 5, Fable 5) | one request each | ~0.1 |
| Marker validation | 2 candidates x the rank sets (final after the row count) | ~5-8 |
| Dedupe validation | labelled E1 pairs | ~2 |
| Idea configurations X1-0 to X1-4 + arm A | E1's measured per-call costs: baseline ~0.63, mixed ~1.5, sequential ~0.65, views ~0.8, rule-relaxing ~0.65, auditor ~0.35 a configuration, 8 libraries | ~37-40 |
| Execution slice | 32-48 trials at ~0.10-0.15 measured per Opus-editor trial (L2b: 0.55 a wired OSS run of several trials) | ~5-8 |
| **Total** | | **~50-58** |

About 34-39 % of Window 1's 148.73 USD (expires 2026-11-25). Worst cases per
dispatch: the idea configurations go as two dispatches of four libraries each,
the slice as two of two, the validations as one; each stays under the 80 USD
fuse. The final figure is re-derived and reported before the first dispatch.

### 6.5 Output

- One markdown file per library and configuration under
  `.claude/handoff/step3/idea-lab/x1/` (title, mechanism, target lines, verdict,
  duplicate-of, lane and model), plus the slice's per-trial records; a summary
  table in STATUS; the raw rows in each run's results artifact.
- Cost per configuration. X1 decides how later rounds run; nothing in it counts
  as proof.

---

## 7 Work breakdown and open slots

| Unit | What | Files (owned) | After |
| --- | --- | --- | --- |
| G1 | Mixed-model lanes; price rows for Sonnet 5, Haiku 4.5, Fable 5; retention guard reuse (Haiku 4.5's request shape deferred, O31) | `common/config.py`, `optimization/idea_lanes.py`; tests | — |
| G2 | Per-lane views, the history view's contamination guard | `optimization/idea_context.py`; tests | G1 |
| G3 | Rule-relaxing proposals path + structural quarantine, security-reviewed before X1 (O32) | `optimization/idea_types.py`, `idea_lanes.py`, `anticheat.py`, the judges; tests | G1 |
| G4 | Sequential lanes, mechanism dedupe, its validation set | `optimization/idea_pipeline.py`, `idea_dedupe.py` (new); tests | G1 |
| G5 | Per-lane frameworks; compounding into evolution, with W4's near-miss compounds folded in | `optimization/idea_prompts.py`, `orchestrator/nodes.py`, `optimization/evolve.py`; tests | G2-G4 |
| G6 | Scaling + operation-count judges, shadow mode | `optimization/judges.py`, `execution/measure.py`; tests | — |
| G7 | The idea-lab process doc | `.claude/handoff/step3/idea-lab.md` | — |
| G8 | The 18 unseen problems (setter Fable 5.1, O19; no Fable attempter, O34; each reference measured by the frozen judges before sealing) | `tests/fixtures/idea_lab/…`, a setter harness | G1-G6 |
| G9 | Held-out OSS set: picked by a non-tuning session, kept outside the repository, a salted hash committed now | the hash file only (the list stays outside the repository) | — (do early) |
| G11 | The lab's learning mechanism: W1 (lessons in the lane prompts, fenced) and W2 (combine-failed lesson discount) | `optimization/generate.py` / `idea_prompts.py`, `learning/lessons.py`, `nodes.py`; tests | G5 |
| V (CI) | An `idea-lab` live suite: the views pass, the Sonnet 5 / Fable 5 smoke requests, the marker and dedupe validations, the idea configurations (X1-1's Latin square), the execution slice with per-trial records and combine summaries, caps per dispatch, full idea lists | `tests/live/…`, `ci.yml` | G1-G6 |
| X1 | The first exploratory round (live): validations, idea configurations, execution slice | — | G1-G7, the V suite, the views pass |

**The idea-quality marker** is resolved before X1 (§6.1): Opus 5.5 and Opus
5 rank ideas with measured trial outcomes (the oss-ab rank rows), the closer
ranking wins, the owner-labelled sample scores novelty, and no idea is graded
by the model that wrote it.

**Sequencing (O35).** PR #22 closes first, on `claude/step3-research`:

1. Resolve or record the Wave 1 open items: the eventagg combine (the L1a
   re-run delivered 30.9 % where the best trial measured 92.3 % on peak RSS;
   read the run's results to see whether the confirmation or the combine
   dropped it) and the ledgerclose partial-fix guard that fails in the Lead's
   container.
2. Confirm the code-scanning thread on the idna key is the known false positive
   (answered on the thread; left open for the owner).
3. Fix the pooled auditor's duplicate scoring in `tests/live/ideas_probe.py`,
   test-first; commit V6's fixtures; a Wave 2 report in STATUS.
4. The stage gate (upgrades, audits, security review of the new code, docs,
   quality), CI green, then mark ready and merge with the pipeline off
   (approved in principle).

Kept as they are: pilots A0-A2 (test-only code), V9 and the exam sets. Parked:
P3 (Managed Agents objects on the owner's account) unless nearly free. Folded:
W4 into G5, W1 and W2 into G11. Deferred: W3. The idea lab then runs on
`claude/step3-idea-lab` off master, its own PR; X1 starts only once its units
and the V suite are in and green.

---

## 8 For approval

1. **This spec (revision 3):** the G units, the two shadow judges, the process,
   the ladder, O28's scope, and the sequencing above.
2. **The X1 configuration plan (§6):** five configurations (X1-0 baseline to
   X1-4 rule-relaxing), arm A alongside, the 8 development libraries, the two
   validations first, about 42 USD expected, an ~80 USD fuse.

Nothing is built until both are approved.
