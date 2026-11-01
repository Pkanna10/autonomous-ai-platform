# Step 3 spec amendment: the idea lab (G units, X rounds, K runs)

**Draft for owner approval — build nothing until approved.** Revision 2
(2026-11-01): reconciled with the owner's consolidated brief of the same day;
adds the dedupe judge's validation (G4), the setter/attempter conflict on rung 2
(§4), the history view's contamination guard (G2), a corrected X1 cost (§6) and
the branch sequencing (§7).

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
- **Haiku 4.5 flagged as the highest-maintenance lane** (own shape, 200K
  context so the "whole module" view may not fit, 10x Haiku 5.5's price). It is
  included in the roster but **X1 may omit it** (owner's call, §6).

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
- **Stopping rule (Lead pushback, accepted)**: each confirmatory rung has a
  pre-set "minimum worth continuing" bar. If two rungs in a row miss it, the lab
  stops and reports rather than tuning further. "Iterate until it wins" gets an
  explicit exit.
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
   sealed before any tuning. **O19 conflict (Lead pushback):** the mixed-model
   roster (G1) includes Fable 5.1 as an idea lane, but on rung 2 Fable 5.1 is
   the setter and wrote the sealed references. A setter that also attempts its
   own problems breaks O19's separation. Proposal: on rung 2, no Fable 5.1 lane;
   Fable 5 (a different model, same family) is allowed only if the owner
   accepts the family overlap, otherwise excluded too.
3. **Held-out OSS libraries (G9)** — chosen and sealed now, before any tuning,
   so they cannot leak into the development set.
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
  bounded by **scope**, not dollars. Report cost per configuration and share
  every idea list.
- **Baseline**: today's pipeline (arm C config) on the development set.
- **Configurations, one lever each** (so a difference is attributable):
  1. **mixed-model lanes** (G1): lanes spread across Sonnet 5.5, Sonnet 5, Haiku
     5.5, Opus 5.5, Fable 5.1 — Haiku 4.5 included only if the owner says so;
  2. **sequential + mechanism exclusion** (G4): same models as the baseline,
     lanes sequential with mechanism dedupe;
  3. **a view per lane** (G2): the baseline models, each lane a different view;
  4. **rule-relaxing lanes** (G3): the proposals path, reported, never scored.
- **Libraries**: the 8 development libraries (more_itertools, pyparsing, tomli,
  sortedcontainers, mistune, sqlparse, markdown, idna).
- **Same inputs for every configuration**: all configurations run on E1's
  recorded phase-1 facts (the `ideas-facts` rows of runs 41186544846 and
  41190431186), so they see identical profiles and no phase 1 is paid. The
  baseline is re-run once on those facts (not reused from E1) so the round has
  an A/A reading of how much the idea measures move by sampling alone.
- **Expected cost (corrected from Revision 1's 15-25)**: E1 measured per
  pipeline call: B 0.43, C 0.63, D 1.76, E 0.44 USD; the auditor ~0.35 a
  library. Per library: baseline (C) ~0.63, mixed-model ~1.5 (Fable 5.1 and Opus
  lanes), sequential ~0.65, views ~0.8 (larger views), rule-relaxing ~0.65, the
  auditor ~0.35 per configuration. **About 4.6-5 USD a library, ~37-40 USD for
  the 8 libraries expected**, with the dedupe judge's validation (~2 USD) on
  top; a ~80 USD CI ceiling as the fuse. Window 1 has 148.73 USD left (expires
  2026-11-25). Re-derived and reported before dispatch.
- **Output**: cost per configuration, and the full idea lists (title, mechanism,
  target lines, verdict, duplicate-of) for the owner and a reviewing session to
  read. X1 decides how later rounds run; nothing in it counts as proof.

---

## 7 Work breakdown and open slots

| Unit | What | Files (owned) | After |
| --- | --- | --- | --- |
| G1 | Mixed-model lanes, price table, Haiku 4.5 shape, retention guard reuse | `common/config.py`, `clients/transport.py` (+ adapter), `optimization/idea_lanes.py`; tests | — |
| G2 | Per-lane views | `optimization/idea_context.py`; tests | G1 |
| G3 | Rule-relaxing proposals path + quarantine | `optimization/idea_types.py`, `idea_lanes.py`, `anticheat.py`, the judges; tests | G1 |
| G4 | Sequential lanes, mechanism dedupe | `optimization/idea_pipeline.py`, `idea_dedupe.py` (new); tests | G1 |
| G5 | Per-lane frameworks, compounding into evolution | `optimization/idea_prompts.py`, `orchestrator/nodes.py`, `optimization/evolve.py`; tests | G2-G4 |
| G6 | Scaling + operation-count judges, shadow mode | `optimization/judges.py`, `execution/measure.py`; tests | — |
| G7 | The idea-lab process doc | `.claude/handoff/step3/idea-lab.md` | — |
| G8 | The 18 unseen problems (setter Fable 5.1, O19) | `tests/fixtures/idea_lab/…`, a setter harness | G1-G6 |
| G9 | Held-out OSS set, sealed now | `tests/fixtures/idea_lab/heldout/…` | — (do early) |
| V (CI) | An `idea-lab` live suite that plans configurations, caps per config, records full idea lists | `tests/live/…`, `ci.yml` | G1-G6 |
| X1 | The first exploratory round (live) | — | the G units + the V suite |

**Open slot — the idea-quality marker.** The first validation run scores both
**Opus 5.5** and **Opus 5** against the existing grader labels (`grader-labels/`);
the marker is whichever agrees better with the human labels **and did not write
the ideas it grades**. If Opus 5.5 is the marker, no lane uses Opus 5.5; if
Opus 5 is the marker, Opus 5.5 is free to be a lane. Resolved before X1; left
open here.

**Sequencing (Lead recommendation).** PR #22 already carries Step 3 Waves 1-2
and is large. Close it first: the duplicate-scoring fix in `ideas_probe.py`
(test-first), V6's fixtures, a Wave 2 report in STATUS, the stage gate, then
mark it ready and merge with the pipeline still off (it is opt-in today). The
idea lab then runs on its own branch (`claude/step3-idea-lab`) and its own PR,
so each review stays readable. The agent pilots, the independent exams and the
W units are the owner's call: run them before the idea lab, fold W4
(evolution) into G5's compounding, or park them. The live rounds (X1, then the
K runs) start only once the G units and the V suite are in and green.

---

## 8 Questions for the owner before building

1. **Haiku 4.5 in X1?** It is the one model needing its own request shape and has
   a 200K window (the whole-module view may not fit); 10x Haiku 5.5's price.
   Include it in X1, or add it only if the cheaper-model-different-ideas
   hypothesis looks alive after X1?
2. **G ordering.** Build all four levers before X1 (cleanest attribution, more
   up-front work), or build G1+G4 first and run a smaller X1 on those two levers
   to fail fast?
3. **The stopping rule's bar.** I will propose a concrete "minimum worth
   continuing" number per rung with each K run's pre-registration; confirm you
   want it owner-approved each time rather than fixed now.
4. **Rung 2's attempter roster.** No Fable 5.1 lane on rung 2 (it set the
   problems). Fable 5 lanes: allowed or excluded?
5. **Sequencing.** Close and merge PR #22 first, then the idea lab on a new
   branch? And for the pilots (P0-P3), the exams (L3b, VC, A1s/A2s) and the W
   units: before the idea lab, folded in, or parked?
