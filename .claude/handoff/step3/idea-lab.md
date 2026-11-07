# The idea lab: how the rounds work

The process every idea-lab round follows (G7). The design is
`spec-idea-lab.md`; the owner's decisions are O23-O37 in `STATUS.md`.

## Goal

A general "make it better" engine for any code and any measurable objective
(speed, memory, operation count, ML accuracy on sealed held-out data, web
performance, security under O28), with proof. Iterate on architecture, models,
prompts and frameworks until it beats the public state of the art, with no
promise that it will.

## Fixed and varied

- **Fixed in every experiment:** the frozen judges, the budgets, the sealed
  test sets (G8's unseen problems, G9's held-out OSS set, V9).
- **Varied, one or two factors a round:** the four levers (G1-G4: who thinks,
  what they see, what they may change, what is already taken), frameworks
  (G5), selection method, idea count, effort, evolution rounds, and the
  diversity archive (the best idea of each mechanism kind, kept across rounds).

## Two kinds of round

| Kind              | Label | Runs on                                                        | Proves                                                      |
| ----------------- | ----- | -------------------------------------------------------------- | ----------------------------------------------------------- |
| Exploratory       | X     | The development set (today's 8 OSS libraries) only             | Nothing; it steers the next round                           |
| Confirmatory      | K     | One pre-registered run per ladder rung, on sets never designed on | What its pre-registered scoring says, nothing more        |
| Improvement pilot | I     | The owner's pilot (STATUS "Labels")                            | Its own pre-registered question                             |

- **Every X round shares the full idea lists:** per arm and lane, each idea's
  title, mechanism, target lines, verdict and duplicate-of, so the owner and a
  reviewing session can read and steer.
- **A K run is pre-registered before its results:** the scoring, the set and
  the rung's bar are fixed first. The architecture may change freely between K
  runs, never during one.
- **Stopping rule (O33):** each rung has a "minimum worth continuing" bar,
  pre-registered and owner-approved before its run. Two rungs in a row below
  their bar: the lab stops and reports instead of tuning further.

## The test ladder

1. Development set: X rounds only.
2. G8's 18 unseen problems (setter Fable 5.1, never the attempter; no Fable
   lane on this rung, O34; each reference measured by the frozen judges before
   sealing).
3. G9's held-out OSS libraries (picked by a non-tuning session, kept outside
   the repository, a salted hash committed; list and salt revealed at the K
   run).
4. V9's sealed maintainer fixes.
5. SWE-Perf / GSO / SWE-fficiency: informative, not a claim, unless
   contamination can be ruled out (its own unit, later).

## What a round measures

- **Ideas:** unique mechanisms after dedupe; the share new to today's
  generator; ideas whose ceiling clears the noise floor; spread across
  mechanism families; the scaling judge's predicted growth-rate change
  (shadow); an owner-read sample.
- **Execution:** wins, gain size, cost per win, the compounding curve over
  rounds; every trial's verdict and every combine summary recorded (the
  eventagg lesson, STATUS Wave 1 items).
- **Marker:** the idea-quality marker passes O37's bar or X1 runs without one;
  no idea is graded by the model that wrote it.

## Every dispatch

- **Before:** the credit left and the dispatch's estimate (O22); no run is cut
  short to save credit, and each dispatch stays under the 80 USD fuse.
- **After:** the actual cost, a ledger row in STATUS, the full idea lists.
- **Security work** stays inside O28: defensive analysis of owned code, the
  owner's dependency tree or public OSS, on copies with dummy data; a human
  owns every disclosure.
