# Step 3 spec amendment: the idea lab (G units, X rounds, K runs)

**Approved by the owner with changes (O36); revision 4 carries them. X1 is not
dispatched until its re-derived estimate is reported.** Revision 4 (2026-11-01):
the marker validated on measured outcomes plus an owner-labelled novelty sample;
an execution slice in X1; a deterministic views pass; X1-1's Latin-square
rotation; X1-3 labelled two factors; the sampling-noise reading; G9's salted
hash; G8's measured references; smoke requests to Sonnet 5 and Fable 5. Revision
3 applied O31-O35; revision 2 added the dedupe validation, the history view's
guard and the branch sequencing.

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
2. The rules (quote a hot line, byte-identical output, no new dependency, no new
   process) leave few distinct local edits in a mature pure-Python library.
3. Lens lanes run in parallel, blind to each other; the "on the table" list
   holds S1's titles only, so a mechanism returns under a new title.
4. Arms B, C and D are one Sonnet generator sampled three times; only E (Haiku
   lanes) differed, and under the strict re-score it found the most ideas new to
   today's generator.

Also: the honest-exam misses had best trials of 1.8-3.8 % under 2-5.9 % noise
floors, so idea **size** is as much the bottleneck as diversity, and the biggest
measured gains came from **compounding** (evolution, STATUS Wave 1: mean 22 % to
35 %, sqlparse 52 % and rising). The redesign changes _what each lane thinks
with_, and wires the pipeline into evolution.

---

## 1 The four levers (G1-G5)

Each lever is a build unit, TDD, Reviewer on a different model, Lead gate, one
commit. The pipeline keeps its shape (S0 context, S1 obvious, lens lanes, leap,
reviewer, portfolio); the levers change its inputs, not its skeleton.

### G1 — Who thinks: mixed-model lanes and the price table

- **Price table** (`common/config.py` `_DEFAULT_PRICING`): add `claude-sonnet-5`
  ($2/$10 in/out), `claude-haiku-4-5` ($1/$5 in/out, 200K context), and
  `claude-fable-5` ($10/$50 in/out). **Cache-write/read rates for all three must
  be taken from the live pricing page at build time, not guessed** (the pricing
  row of the `claude-api` skill's `shared/live-sources.md`); the unit fails its
  own test if a rate is left at a placeholder.
- **Per-lane model**: a lane may name any model in the table. Diversity comes
  from models, views and prompts, since every current model rejects
  `temperature`.
- **Haiku 4.5's request shape** (`clients/transport.py` or a small adapter):
  Haiku 4.5 takes no `effort` and uses
  `thinking: {type: "enabled", budget_tokens: N}` (N < max_tokens, min 1024);
  every other listed model uses `effort` and rejects `budget_tokens`. The
  adapter picks the shape by model id, with a test per shape. (Fact source:
  `claude-api` skill, thinking table.)
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

**Protected inputs are shown as a schema only (owner, 2026-11-03).** An input
file under a protected path (`tests/`, `benchmarks/`, the run's protected and
read-deny patterns) is shown as its shape alone: sizes (bytes, lines, line
lengths), the detected format and its types and nesting (depth, element and
field counts, value types per position), and distributions (length and value
spread, character classes). No line, no value and no key name is shown. _Why:_ a
lane that sees the benchmark's literal input can specialise for exactly that
input and pass every frozen judge. An input outside protected paths keeps its
five-line screened head beside the same summary.

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
  claim are contradictory, so a tagged idea can never be mistaken for a
  shippable win.

This is where the "unthinkable" ideas live, safely walled off from the proof
path.

**Gate before X1 (O32).** G3 gets a security review (a separate Reviewer, on the
quarantine only: the tag cannot be dropped, the proposals path cannot deliver or
count, the anti-cheat rejects a tagged equivalence claim) before X1 uses it. If
the review is not clean in time, X1 runs three levers and the rule-relaxing
configuration becomes X2. The lane never runs without the quarantine.

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

Built in two parts: **G5a** (frameworks, committed) and **G5b** (round seeds and
near-miss compounds). Owner decisions of 2026-11-03 fix G5b below.

- **Per-lane idea framework (G5a)** (`optimization/idea_prompts.py`): each
  lane's view or relaxed rule comes with a short framework that steers it (e.g.
  the callers view with "push work to the caller or memoise across calls"; the
  input-shape view with "specialise for the shape the workload actually
  passes"). `IDEAS_LANE_FRAMEWORKS`, off by default; off keeps every request
  byte-identical. The framework sits in the lane's own instruction, outside
  every fence and every cached block; a note per lane records which framework it
  was assigned, so X1-3 can tell a view alone from a view with its framework.
- **Round seeds (G5b)** (`optimization/idea_dedupe.py`, `idea_pipeline.py`,
  `orchestrator/nodes.py`): from the engine's second hypotheses round on (up to
  `PORTFOLIO_ROUNDS`), each lens lane is shown the verdicts of the ideas this
  run has already trialled: each idea's mechanism key (file, function, target
  lines, mechanism, primary cell), its sanitised title, its outcome and its gain
  as a ratio of the noise floor; keeps first. Behind a setting, off by default.
  Because the node calls the generator again only once the pool is empty, a
  second generator call with at least one seed re-runs S1, the lenses, the leap
  and the reviewer, reserved whole under D55's share (skipped with
  `discovery_unaffordable` if it does not fit); with seeds off or nothing to
  seed it stays S1 only (D48). D64 supersedes D48 for seeded runs only. The
  seeded call is its own cost line: an engine event and a line in the run
  report's conditions (calls and USD, inside the discovery total), and a column
  in the lab's per-round reports (the V suite), so its cost per win is visible
  once evolution rounds are varied. **One fenced block, not two:** the seeds and
  G4's mechanisms block (`taken_block`) are merged into one fenced block with
  one lead-in, one line per distinct mechanism key, a trialled key carrying its
  outcome and gain, so the prompt grows once. With seeds off, G4's block is
  unchanged byte for byte. A proposal (G3) is never a seed. Re-basing across
  runs (what E4 measured) stays in the evolution harness.
- **Near-miss compounds (G5b, W4 folded in)** (`optimization/evolve.py` new,
  `orchestrator/nodes.py`, `execution/trial_runner.py`): D22's rule. Two
  verdicts form a pair when both are **inconclusive**, both in the right
  direction with a primary gain of at least **0.5 of the noise floor**, their
  trials change **disjoint files**, both are **efficiency** class, and neither
  is a proposal. **At most one compound a round**, the best pair by combined
  gain/floor ratio. The compound is built by **replay**: the two measured trial
  commits are cherry-picked onto the run's base with the combiner's hardened
  git, with no editor request, so it costs no tokens and is exactly what was
  measured. A conflict means no compound, recorded as a note. The compound is a
  **normal trial** under the frozen judges at full N, with anti-cheat on its own
  diff; nothing about it relaxes a rule, and it is judged from scratch (its
  parents' measurements are never reused). Behind a setting, off by default.
  _Outside G5's file list:_ the replay needs `execution/trial_runner.py` (a
  trial whose commit comes from cherry-picks, not the editor); the owner
  approved that touch on 2026-11-03.
- **Folded-in Wave 3 units (O35).** W4 (evolution: near-miss compounds) becomes
  part of G5. W1 and W2 (lessons in the generator prompt; the combine-failed
  lesson discount) become G11, the lab's learning mechanism: each round's
  verdicts become lessons that steer the next round's lanes. W3 (hotspot tags)
  is deferred.

### G11 — The lab's learning mechanism (W1 and W2 folded in)

Built after G5 (Lead, 2026-11-03, from D13 and D21 as approved in Wave 1's
design):

- **Lessons in the prompts (W1, D21).** The project's last 20 lessons and
  `avoid_titles` reach today's generator (`optimization/generate.py`) and the
  idea pipeline's S1 and lens lanes as one fenced untrusted block. A lesson line
  holds its outcome, its weight and its text; a line holding a fence token is
  withheld, titles are reduced to one plain line and capped, and lesson text
  carries timing gains only, never a quality value (spec.md, the W1 row). In the
  pipeline the block sits in the shared, cached data so every lane sees the same
  bytes and the per-lane prompt does not grow; the leap and the reviewer never
  get it. A setting, off by default; off keeps every request byte-identical.
- **Combine-failed discount (W2, D13).** `learn` weights each kept verdict's
  lesson by what the combine did with it: delivered or skipped 1.0, applied in a
  failed greedy re-test while another fallback held 0.5 (`combine:unconfirmed`),
  not reproduced 0.25 (`combine:not_reproduced`), no combiner 1.0. The outcome
  stays the verdict's; the text gains `(combine: not reproduced)` and so on. No
  schema change (`chk_lesson_weight > 0` holds). Always on: it changes only how
  much a keep counts in the next ranking, never a verdict.
- No lesson from a proposal (G3) or a refused compound replay (G5b).

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

A short process doc (`.claude/handoff/step3/idea-lab.md`) that the rounds
follow.

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
   V9 and the held-out OSS set. **Measured references (O36.5d):** before a
   problem is sealed, the frozen judges measure its expert reference on the
   problem's workload: the gain must clear the measured floor and the output (or
   the quality tolerance for the ML tier) must hold; a reference that fails is
   fixed or the problem is dropped.
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
  static analysers, and the full suite with no regression. Lanes are prompted as
  defensive review; refusal categories are logged.

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
  `ideas-facts` rows. One deterministic, no-API pass per library at the recorded
  commit builds every view (callers, data structures, input shape, whole module,
  2nd/3rd hotspots, performance-commit history up to the pinned commit) and
  stores it once as new rows; every configuration reads those rows, so all share
  identical inputs. Profiles stay E1's.
- **Marker validation on measured outcomes (O36.1).** Not the grader labels:
  V5's 12 builder-written labels and the 75 sweep-record labels grade hit or
  miss on planted slowdowns in a saturated corpus and cannot separate the two
  candidates. Source: the `E5-oss-ab-rank` rows of Window 0's oss-ab runs (per
  idea: title, class, verdict, gain, noise floor; 18 libraries). The marker sees
  the title, the class and the hot code from the pinned clone, never the result,
  and ranks the ideas of each (library, repetition, arm) set; its score is the
  rank agreement with the measured outcomes (kept above the floor > trialled and
  not kept > ...). Only rows with a real verdict count (not `NOT_TRIALLED`, not
  `NO_RESULT`); **the Lead reports that count and the owner fixes the bar before
  the run.** The bar is fixed (O37): AUC >= 0.65 with the 95 % interval's lower
  bound above 0.5, within-library AUC averaged with a cluster bootstrap over
  libraries, at least the generator's own rank order, Opus 5 if the two are
  within 0.05; positives are `keep`, negatives trialled `reject` or
  `inconclusive`; under ~20 positives it decides nothing; if neither passes, X1
  runs without a marker. 332 rows, 114 positives. Titles only, no mechanism
  text: a first check, not the final one. The execution slice (§6.3) becomes the
  full-text validation set.
- **Owner-labelled novelty sample.** 20-30 ideas drawn from E1's lists (mixed
  arms and lanes), shown to the owner without their source, labelled new or not
  new to today's generator; the marker's novelty calls are scored against them.
- **Dedupe validation (G4):** labelled E1 idea pairs, bar fixed before it runs.
- **Smoke requests (O36.5e).** The V suite sends one live request each to Sonnet
  5 and Fable 5 (the two models X1 adds to the price table) before any X1
  configuration runs.
- **Marker independence rule:** every idea is graded by the best-validated
  marker that did not write it. If Opus 5.5 wins, ideas written by an Opus 5.5
  lane or leap are graded by Opus 5 (the runner-up), all others by Opus 5.5; if
  Opus 5 wins, it grades everything (no lane is Opus 5).

### 6.2 The idea configurations, one lever each

S1 and the six lens lanes = 7 idea lanes; leap and reviewer as today unless
stated:

| Config | Lever                                          | Idea lanes                                                                             | What changes vs baseline                                                                                                                                                                                       |
| ------ | ---------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| X1-0   | baseline                                       | today's pipeline (arm C: Sonnet 5.5 lanes `medium`, Opus 5.5 leap and reviewer `high`) | none; re-run once on E1's facts                                                                                                                                                                                |
| X1-1   | who thinks (G1)                                | S1 Sonnet 5.5; lenses on Sonnet 5, Haiku 5.5, Opus 5.5, Fable 5, Fable 5.1, Sonnet 5.5 | model per lane, **rotated across lenses over the 8 libraries (a 6x6 Latin square, rows 1-6 then 1-2)** so model and lens effects separate; same view, prompts and order                                        |
| X1-2   | what is taken (G4)                             | baseline models                                                                        | lanes in sequence, each shown earlier lanes' mechanisms; mechanism dedupe                                                                                                                                      |
| X1-3   | what they see **and** how they think (G2 + G5) | baseline models                                                                        | each lens lane a different view with its framework; **two factors, labelled so; split in X2 if it wins**                                                                                                       |
| X1-4   | what they may change (G3)                      | baseline models                                                                        | four lanes, each relaxing one rule (new dependency, output order, install-time precompute, API change); proposals only, reported, never scored or trialled; only behind the reviewed quarantine (O32), else X2 |

- **Today's generator alongside**: arm A (one Sonnet request, 0.025 USD) is
  re-run on the same facts, so "share new to today's generator" compares against
  a same-day reading, not only E1's.
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
  worktree, the frozen judges, N >= 5 runs against the measured floor), then the
  combine per (configuration, library).
- **What is recorded**: every trial's full idea text (title, mechanism, target
  lines, rationale), verdict, gain and floor, and every combine summary. This is
  what the eventagg finding showed was missing, and it makes the slice the
  marker's full-text validation set.
- **Reading**: lever rankings from the idea measures alone are provisional; the
  slice says whether a configuration's ideas win trials more often, or by more,
  than the baseline's. With 3-12 trials per configuration it is exploratory, not
  proof.
- **Dispatch**: two execution dispatches of two libraries each, so each
  dispatch's worst case stays under the 80 USD fuse (per trial worst case 2.50
  USD as in E2's plan; 24 trials = 60).

### 6.4 Expected cost (re-derived with the views pass and the execution slice)

| Part                                     | Basis                                                                                                                                                   | Expected USD |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| Views pass                               | deterministic, no API                                                                                                                                   | 0            |
| Smoke requests (Sonnet 5, Fable 5)       | one request each                                                                                                                                        | ~0.1         |
| Marker validation                        | 2 candidates x the rank sets (final after the row count)                                                                                                | ~5-8         |
| Dedupe validation                        | labelled E1 pairs                                                                                                                                       | ~2           |
| Idea configurations X1-0 to X1-4 + arm A | E1's measured per-call costs: baseline ~0.63, mixed ~1.5, sequential ~0.65, views ~0.8, rule-relaxing ~0.65, auditor ~0.35 a configuration, 8 libraries | ~37-40       |
| Execution slice                          | 32-48 trials at ~0.10-0.15 measured per Opus-editor trial (L2b: 0.55 a wired OSS run of several trials)                                                 | ~5-8         |
| **Total**                                |                                                                                                                                                         | **~50-58**   |

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
- **The comparison tables (owner, 2026-11-02),** beside §6.2's per-configuration
  measures:
  1. **Mechanism × configuration overlap:** each deduped mechanism against the
     configurations that produced it, so ideas unique to one lever show.
  2. **X1-1 model × lens:** from the rotation, the model effect and the lens
     effect read separately (each cell: ideas, unique mechanisms, ceilings above
     the floor).
  3. **Predicted ceilings against the floor, per configuration:** the whole
     distribution (quantiles and a plot), not only the count above the floor.
  4. **Every lever's delta beside the noise:** next to the A/A spread from X1-0
     and E1's arms B, C and D, so a difference inside that spread is not read as
     a result.
- **The owner-read sample:** 20-30 ideas, source (configuration, lane, model)
  hidden, kept.
- **The shadow judges are on:** the X1 dispatch sets `OP_COUNT_JUDGE` (G6a) so
  the operation-count column is recorded for every execution-slice trial, and
  the V suite asserts it is on.

---

## 7 Work breakdown and open slots

| Unit   | What                                                                                                                                                                                                                                                                                                                                | Files (owned)                                                                                                                                                                                          | After                              |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- |
| G1     | Mixed-model lanes; price rows for Sonnet 5, Haiku 4.5, Fable 5; retention guard reuse (Haiku 4.5's request shape deferred, O31)                                                                                                                                                                                                     | `common/config.py`, `optimization/idea_lanes.py`; tests                                                                                                                                                | —                                  |
| G2     | Per-lane views, the history view's contamination guard                                                                                                                                                                                                                                                                              | `optimization/idea_context.py`; tests                                                                                                                                                                  | G1                                 |
| G3     | Rule-relaxing proposals path + structural quarantine, security-reviewed before X1 (O32)                                                                                                                                                                                                                                             | `optimization/idea_types.py`, `idea_lanes.py`, `anticheat.py`, the judges; tests                                                                                                                       | G1                                 |
| G4     | Sequential lanes, mechanism dedupe, its validation set                                                                                                                                                                                                                                                                              | `optimization/idea_pipeline.py`, `idea_dedupe.py` (new); tests                                                                                                                                         | G1                                 |
| G5     | Per-lane frameworks (G5a); round seeds and near-miss compounds by replay, W4 folded in (G5b)                                                                                                                                                                                                                                        | `optimization/idea_prompts.py`, `idea_pipeline.py`, `idea_dedupe.py`, `orchestrator/nodes.py`, `optimization/evolve.py`, `execution/trial_runner.py` (outside the first list, owner 2026-11-03); tests | G2-G4                              |
| G6     | Scaling + operation-count judges, shadow mode                                                                                                                                                                                                                                                                                       | `optimization/judges.py`, `execution/measure.py`; tests                                                                                                                                                | —                                  |
| G7     | The idea-lab process doc                                                                                                                                                                                                                                                                                                            | `.claude/handoff/step3/idea-lab.md`                                                                                                                                                                    | —                                  |
| G8     | The 18 unseen problems (setter Fable 5.1, O19; no Fable attempter, O34; each reference measured by the frozen judges before sealing)                                                                                                                                                                                                | `tests/fixtures/idea_lab/…`, a setter harness                                                                                                                                                          | G1-G6                              |
| G9     | Held-out OSS set: picked by a non-tuning session, kept outside the repository, a salted hash committed now                                                                                                                                                                                                                          | the hash file only (the list stays outside the repository)                                                                                                                                             | — (do early)                       |
| G11    | The lab's learning mechanism: W1 (lessons in the lane prompts, fenced) and W2 (combine-failed lesson discount)                                                                                                                                                                                                                      | `optimization/generate.py` / `idea_prompts.py`, `learning/lessons.py`, `nodes.py`; tests                                                                                                               | G5                                 |
| V (CI) | An `idea-lab` live suite: the views pass, the Sonnet 5 / Fable 5 smoke requests, the marker and dedupe validations, the idea configurations (X1-1's Latin square), the execution slice with per-trial records and combine summaries, `OP_COUNT_JUDGE` on (asserted), the §6.5 comparison tables, caps per dispatch, full idea lists | `tests/live/…`, `ci.yml`                                                                                                                                                                               | G1-G6                              |
| X1     | The first exploratory round (live): validations, idea configurations, execution slice                                                                                                                                                                                                                                               | —                                                                                                                                                                                                      | G1-G7, the V suite, the views pass |

**The V suite, split (Lead, 2026-11-03).** Six units on separate files; each
writes its `ci.yml` suite as a patch the Lead integrates, and none sends a
request outside its own CI suite.

| Unit | What                                                                                                                                                                                           | Files (owned)                                | After   |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ------- |
| Va   | Views pass (§6.1): per library, clone at E1's recorded commit, build every view from E1's facts with no request, write `ideas-views` rows and a loader                                         | `tests/live/ideas_views.py` (new); guards    | G2, G2b |
| Vb   | Marker validation (§6.1, O37): rank sets from `oss_ab_rank_rows.jsonl`, Opus 5.5 and Opus 5 rank, within-library AUC with a cluster bootstrap, the bar                                         | `tests/live/ideas_marker.py` (new); guards   | —       |
| Vc   | Smoke requests (Sonnet 5, Fable 5) and the dedupe validation: a labeller that wrote none of E1's ideas labels candidate pairs, scored against G4's bar, plus an owner spot-check sample        | `tests/live/ideas_validate.py` (new); guards | G4      |
| Vd   | The X1 configurations (§6.2): X1-0 to X1-4 and arm A on E1's facts and Va's views, X1-1's Latin square, full idea lists, cost per configuration                                                | `tests/live/ideas_probe.py`; guards          | Va      |
| Ve   | The execution slice (§6.3): the top ideas new to today's generator by the validated marker, as normal engine trials, `OP_COUNT_JUDGE` on and asserted, per-trial records and combine summaries | `tests/live/ideas_slice.py` (new); guards    | Vb, Vd  |
| Vf   | The report (§6.5): per library and configuration markdown, the four comparison tables, cost per configuration with D64's seeded-call column, the owner's hidden-source sample                  | `tests/live/ideas_report.py` (new); guards   | Vd, Ve  |

Wave A builds Va, Vb and Vc in parallel; wave B builds Vd, then Ve and Vf. The
validations (Vb, Vc, the views pass) can be dispatched as soon as wave A is in;
X1 waits for all six.

**The idea-quality marker** is resolved before X1 (§6.1): Opus 5.5 and Opus 5
rank ideas with measured trial outcomes (the oss-ab rank rows), the closer
ranking wins, the owner-labelled sample scores novelty, and no idea is graded by
the model that wrote it.

**Sequencing (O35).** PR #22 closes first, on `claude/step3-research`:

1. Resolve or record the Wave 1 open items: the eventagg combine (the L1a re-run
   delivered 30.9 % where the best trial measured 92.3 % on peak RSS; read the
   run's results to see whether the confirmation or the combine dropped it) and
   the ledgerclose partial-fix guard that fails in the Lead's container.
2. Confirm the code-scanning thread on the idna key is the known false positive
   (answered on the thread; left open for the owner).
3. Fix the pooled auditor's duplicate scoring in `tests/live/ideas_probe.py`,
   test-first; commit V6's fixtures; a Wave 2 report in STATUS.
4. The stage gate (upgrades, audits, security review of the new code, docs,
   quality), CI green, then mark ready and merge with the pipeline off (approved
   in principle).

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

---

## 9 X2: evolution on the levers that X1 kept (draft for approval, O47)

**Status: approved to build (O48, 2026-11-05); nothing is dispatched until its
need and caps are re-derived and reported.** Revision 2 applies the owner's
answers (O48). Written 2026-11-05 from O47 and X1's measured rows
(`.claude/handoff/step3/idea-lab/x1/`, STATUS's X1 ledger rows).

### 9.1 What X1 showed (provisional against the A/A band)

- The slice's 9 wins came from the lanes below:
  - the leap: 5 (+14.6, +9.9, +9.9, +7.0, +4.4 %);
  - S1: 2;
  - lens lanes: 2 (X1-3 far +9.5 %; X1-1 eliminate on Haiku 5.5, +3.54 % on a
    3.53 % floor).

  The levers cut self-repetition, but their wins were mostly the leap's.

- **X1-2 (sequential lanes):** a loss. It had the fewest auditor-feasible ideas
  (15 of 50) and marker-feasible top-3 places (2), and 1 win.
- **X1-1 (who thinks):** ties X1-3 on marker-feasible places (8 each) at about
  4x the cost (21.60 against 5.38 USD over 8 libraries).
  - Haiku 5.5 costs 0.02 USD per unique new mechanism; Fable 5 costs 1.01 and
    Fable 5.1 1.72 (upper bounds).
  - Haiku earns its place; Fable does not.
  - The blind reader's two insightful ideas were both Fable lens lanes. This is
    recorded, but does not change the call: 2 of 24, and the reader is from the
    leap's model family.
- **X1-3 (views with frameworks):** the lever to keep. Its two factors were
  confounded, so X2 splits them.

### 9.2 The arms

What every arm shares:

- the leap and the reviewer, as today;
- S1 and the six lens lanes on Sonnet 5.5, except the **eliminate lens on Haiku
  5.5** (O48);
- the think line as in X1-0;
- no sequential lanes, no mechanism dedupe in the pipeline, no Fable lane
  (unless the reader dispatch's rule adds one, §9.7);
- no rule-relaxing lanes (X1-4 stays quarantined, as reported);
- lessons (G11) off; they are X3's.

| Arm   | Lever            | Libraries                | What changes                                                                                    |
| ----- | ---------------- | ------------------------ | ----------------------------------------------------------------------------------------------- |
| X2-0  | baseline         | all eight                | the shared setup above                                                                          |
| X2-0' | A/A twin         | the four slice libraries | X2-0 again, independent runs on sqlparse, pyparsing, tomli and sortedcontainers; the noise band |
| X2-V  | views (G2)       | all eight                | each lens lane gets X1-3's view (its recorded lens-to-view map), with no framework              |
| X2-F  | frameworks (G5a) | all eight                | each lens lane gets X1-3's framework on today's shared view                                     |

`IDEAS_LANE_FRAMEWORKS` without `IDEAS_LANE_VIEWS` is a new combination. It is
checked to be well-formed before dispatch, as Vd2's think line was.

### 9.3 Evolution, the same eight libraries

- **Engine runs, not a slice.** Each (arm, library) is one engine run with the
  idea pipeline on: 2 rounds in all (`PORTFOLIO_ROUNDS` 1, O48), with
  - round seeds (`IDEAS_ROUND_SEEDS`);
  - near-miss compounds (`NEAR_MISS_COMPOUNDS`, G5b, at most one a round, by
    replay);
  - `OP_COUNT_JUDGE` on.

  The engine picks its own hypotheses each round. The slice's marker pick is not
  used, so what X2 measures is the engine as it would run.

- **Live, not recorded.** Each run profiles live and builds its views live, as
  the engine does, at the commit E1 recorded for its library. X1 read E1's
  recorded facts and Va's views because it generated ideas without the engine;
  X2 runs the engine.
- **The same eight libraries:** more_itertools, pyparsing, tomli,
  sortedcontainers (the control), mistune, sqlparse, markdown, idna.

### 9.4 Measures

- Per arm, round and library:
  - kept trials, and the combine's delivered gain against its floor;
  - wins credited to the lane that produced them (the report's per-lane table,
    V-rep3);
  - the seeded call's cost line (D64);
  - compounds tried and kept;
  - cost per win.
- **Read against the band:** on the four slice libraries, every arm's delta
  against X2-0 is read beside the X2-0/X2-0' spread. A delta inside it is not a
  result. On the other four there is no band, and their deltas are reported as
  unbanded.
- **Predicted ceilings** (V-rep3, O48): the distribution of ceiling less floor
  is the primary view; the count is of ideas whose ceiling less floor is at
  least 10 points.
- **Unique mechanisms** stay an upper bound (O48: the dedupe fix from the 380
  pairs comes after X2).

### 9.5 Cost (from X1's measured rates)

| Part                       | Measured basis                                                                                                                                                | Per run, 2 rounds |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| The pipeline call, round 1 | X1-0 0.65 a library (0.53-0.91), X1-3 0.67; the Haiku eliminate lens about 0.01 less (X1-1's Table 2b: 0.006 a Haiku request against 0.019 a Sonnet 5.5 lens) | 0.64-0.66         |
| The seeded call, round 2   | none measured (D64's column read 0 in X1); taken as a full call                                                                                               | 0.64-0.66         |
| Trials and the combine     | the slice: 0.40 an engine loop of about 3 trials (0.24-0.72)                                                                                                  | ~0.80             |
| A compound                 | replay costs no tokens; judged as a trial, ~0.13                                                                                                              | ~0.13             |
| **Per run**                |                                                                                                                                                               | **~2.21-2.25**    |

- **Total:** X2-0, X2-V and X2-F on eight libraries (24 runs) and X2-0' on four
  (4 runs): 28 runs, about **62 USD** expected (X2-0 17.7, X2-V 18.0, X2-F 17.7,
  X2-0' 8.8).
- **Budget:** Window 1 has 81.46 USD left before the reader dispatch (about 3).
  X2 then leaves about 16.
- **Worst case:** each run carries a hard cost cap, derived by the X2 suite from
  the engine's own reservation rules so that a run at X1's measured rates is
  never refused, proposed at 6 USD (about 3x expected). Three dispatches, each
  under the 80 USD fuse: X2-0 with its twin (12 runs), X2-V (8), X2-F (8). Each
  dispatch's need is derived and checked before spend, as in X1.

### 9.6 Build (approved, O48)

1. **V-rep3:** landed (`e85999b`).
2. **The reader dispatch (`ideas-picks`), before X2:** the blind reader's seven
   would-try ideas (S04, S07, S09, S12, S13, S20, S23), resolved through the
   sample key, run as ordinary trials on their libraries: one engine loop per
   library (sqlparse 3, more_itertools 2, mistune 1, tomli 1), `OP_COUNT_JUDGE`
   on. About 3 USD expected, cap 8. It tests:
   - the reader against the judges;
   - the marker's omission of S20;
   - Fable's resolve_tradeoff ideas at trial (S13, S20).
3. **The ceiling bar** in the report: the count of ideas whose ceiling less
   floor is at least 10 points.
4. **The X2 suite:**
   - the four arms' settings, guarded like Vd's;
   - the frameworks-without-views combination checked well-formed;
   - the per-run cost cap;
   - the per-round records (trials, seeds, compounds, the seeded-call column);
   - the dispatch plan;
   - an off-by-default setting for the Fable resolve_tradeoff lane (§9.7), so
     the rule's outcome needs no rebuild.

   About 250 source lines, through Builder, Fable reviewer and gate as in the V
   suite.

### 9.6b As dispatched (O50, 2026-11-06)

- **Seeds live:** round 1 trials the whole idea result (`WHOLE_POOL`), so
  round 2 is the seeded call. Two rounds take `PORTFOLIO_ROUNDS` 2 and
  `MAX_TRIAL_ROUNDS` 2: the router ends exploration at a keep once the round
  reaches `PORTFOLIO_ROUNDS`.
- **Arms:** X2-0, X2-0' and X2-V. X2-F moves to Window 2: it needs a `src`
  setting, since a lens on the shared view never gets a framework.
- **Dispatches:** at most 3 runs each, one arm each, 8 in all, interleaved by
  library group. Each run's cap is 9.35 USD (X2-V 9.45), and each dispatch's
  need is its libraries times that.
- **Expected:** about 3.0 USD a run, about 60 for the 20 runs.
- **Read arm to arm only.** Round 1 trials every idea, where X1's slice
  trialled the marker's top 3 and the engine's default is 3 a round. So X2's
  wins are compared across X2's arms, not against X1's.
- **The Fable rule did not fire** (S20 kept at 1.83x its floor, S13
  rejected): no Fable lane.

### 9.7 The Fable rule (O48, fixed before the reader dispatch)

If S13 or S20 is kept with a gain at least twice its floor, X2 adds one Fable
resolve_tradeoff lane to every arm; otherwise the no-Fable call stands.

- **Its cost:** X1 measured a Fable lens request at about 0.87 USD (Fable 5
  0.88, Fable 5.1 0.86, at the 32,000-token cap). Two pipeline calls a run is
  about +1.74 a run, so 28 runs add about 49 USD: X2 at about **111 USD**,
  against about 78 left after the reader dispatch.
- **Its caps:** each lane at 32,000 output tokens with the 951 s request timeout
  (O42, O45). The per-run cap rises by about 4.2 USD (two Fable requests at
  their worst case), to about 10, so about 7 runs a dispatch.
- **If the rule fires,** X2 with the lane does not fit Window 1. The owner then
  chooses, for example:
  - X2 with the lane on the four slice libraries only (16 runs, about 63 USD);
  - X2 without it now, and the lane in Window 2;
  - X2 with the lane in Window 2.
