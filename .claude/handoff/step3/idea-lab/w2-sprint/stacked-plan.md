# Build plan: arm X2-DT, stacked rounds (O62 item 6), 2026-11-12

**Status: plan only.** Nothing is built until the owner has read this plan and
the measured CI minutes (section 6). The idea is combine proposal item 2
(`combine-proposal.md`, section 2).

## 1 The arm and its pre-registered reading

- **Name:** X2-DT ("X2-D on tips"). X2-S is the SITE_STACKS arm. X2-T, X2-K,
  X2-R, X2-M and X2-0R are named on earlier boards or in proposals.
- **Definition:** X2-D (X2-0 with three rounds and `GENERATOR_MAX_CALLS=3`)
  plus `STACKED_ROUNDS=true`. Nothing else differs: the same requests, models,
  caps (12.90 USD a run) and the same 12,000-token leap cap.
- **Pre-registered (O62):**
  - Runs: 5 per library on sqlparse, tomli, mistune and markdown (20 runs).
  - Read against the 20 existing X2-D runs with the O59 section-5 bar:
    two-sided p <= 0.10 and a higher median on at least 3 of the 4
    libraries.
  - The primary measure: the delivered gain against the original base, 0
    without a held delivery.
  - The secondaries: the conflict rate at delivery and the unique keeps per
    round.
- **Pilot:** one run on key 1 before 2026-11-20, to measure the real minutes
  and check the mechanics.
  - Key 1 has 5.29 USD left, and X2-D runs measured 2.75 to 4.11.
  - **The owner's call:** the arm's 12.90 cap is above that balance, which
    breaks the sprint rule that outstanding caps never exceed the balance.
    Either the pilot runs with its cap lowered to 5.00 (a setting of that one
    run, recorded; X2-D's dearest measured run is 4.11), or it runs on key 2's
    new credit instead.
  - The 20 runs then go on key 2's new credit, at about 70 USD by X2-D's
    measured 3.50 a run.

## 2 How it works

1. At the end of round r, today's combine (`combine_kept` and `GitCombiner`,
   unchanged, with the frozen judges) runs on the keeps that are on the
   current round base.
2. If it holds, the tip is adopted as round r+1's base. Adoption means:
   - the baseline node, unchanged, measures and calibrates at the tip;
   - the tip's outputs are checked against the original base's outputs;
   - the profile is taken again at the tip;
   - the seed anchors are re-keyed from the old base's line numbers to the
     tip's.
3. Trials already follow the baseline's commit (`GitTrialRunner`). So round
   r+1's trials are diffs against the tip, judged against the tip's twin,
   with no runner change.
4. A combine that does not hold, or a tip that cannot be adopted, leaves the
   base where it was. The reason is recorded.
5. **Delivery** is the last held tip, squashed onto the original base as one
   commit. It goes through the same `combine_kept` as one change, so it gets
   today's ABAB, the suite on the tip and the frozen judges against the
   original base. That re-test's gain is the run's primary measure.
   - There is no fallback to an earlier tip: that would be a second chance.
   - If the last held combine ran on the original base, it is already that
     re-test, so none is added.
6. **Equivalence is checked against both bases.** Each trial is checked
   against the tip twin (the frozen judge) and against the original base (a
   violation in the verdicts node, so rule 1 rejects). The tip's baseline is
   checked before adoption, and the delivery re-test runs against the original
   base.
7. **Protected paths:** every trial diff is checked as today, and the
   cumulative origin..tip diff is checked again before delivery (fail closed).

**Constraints met:**
- No change to the judges, anticheat, protected-path rules, benchmarks,
  sealed sets, or `combine_node.py` / `execution/combine.py`. The new nodes
  call them with new inputs.
- With the setting off, the graph, every request and every decision stay
  byte-identical. That is proven by a new golden (U0, recorded on today's head)
  plus every existing golden.

## 3 Decisions for the owner

1. **The offered set at a round's end.** Either every run-set keep still on
   the current base, so keeps from an unheld earlier round are offered again,
   or this round's keeps only.
   - **Recommended: the former.** With no held tip it is exactly X2-D's final
     combine set.
2. **The delivered branch.** Either the squash commit (one commit origin..tip,
   measured as such) or the chain of round tips, whose final tree is
   identical.
   - **Recommended: the squash.** It is the object the re-test measures.
3. **Refused under stacking (fail closed at start-up):** quality mode and
   SITE_STACKS. Neither is used by X2-D.

## 4 Units (build order; at most about 400 lines each, disjoint files)

| #   | Unit                     | Files                                                        | Tests                                                                                                                                   |
| --- | ------------------------ | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| U0  | golden (tests only)      | `tests/orchestrator/test_stacked_off_golden.py`              | an X2-D-shaped 3-round fakes run fingerprinting every request, event, state dump and the report; recorded on today's head               |
| U1  | data                     | `common/models.py`, `orchestrator/state.py`, `serde.py`, `common/config.py` | `RoundBase`, `StackLedger`, state key `stack`, `STACKED_ROUNDS=False`; serde round trip, old states load                     |
| U2  | git seam                 | `execution/protocols.py`, `execution/stacking.py`, `fakes.py` | real git: squash parent and tree, determinism, non-descendant refused, changed paths, truncation refused                               |
| U3  | re-key (pure)            | `optimization/rekey.py`                                      | line shifts, insertions, replaced spans, deletions, truncation                                                                          |
| U4  | node guards              | `orchestrator/nodes.py` (about 70 lines, all behind the flag) | knob refusals, seed overlay, same-base compounds, the `original base:` violation                                                       |
| U5a | round step               | `orchestrator/stack_round.py`                                | held, not held, nothing kept, adoption refused (outputs, baseline error), tamper propagates, timings                                   |
| U5b | tail and graph           | `orchestrator/stacking.py`, `orchestrator/main.py`           | a 3-round fakes run, the failure paths, equivalence against both bases, topology and config unchanged when off                          |
| U6  | factory and docs         | `orchestrator/factory.py`, the service CLAUDE.md and README  | the wiring on and off, and the refused combinations                                                                                     |
| U7  | real-git E2E (slow)      | `tests/e2e/test_step3_stacked.py` plus fixtures              | trial parents, the base moving only on adoption, delivery at the original base, the published diff equal to the measured tip           |
| U8  | harness and CI           | `tests/live/ideas_x2.py`, `.github/workflows/ci.yml`         | the X2-DT arm, rows (`round_base`, `stack_fate`, the round's `stack` record, `stack_delivery`, `stack_seconds`), the guards             |

- **Order and parallelism:**
  - U1, U2 and U3 run in parallel after U0.
  - U4 follows them.
  - Then U5a, U5b and U6 in turn, and finally U7 and U8.
- **Process:** one Opus builder per unit, a Fable review of each unit, the lab
  gate, one commit per unit.
- **A follow-on page** reads the secondaries (conflict rate at delivery, unique
  keeps per round) for X2-DT against X2-D.

## 5 Risks, and what only a live run proves

**Only a live run proves:**
- **Smaller relative gains.** Gains from round 2 on are marginal, and the
  same noise is a larger relative floor on a faster tip.
- **Fewer repeat sites.** Whether lanes stop re-finding round-1 sites (about a
  third of today's conflicts are repeats).
- **Early stops.** How often a noisy round combine stops the stacking early.
  Combine item 1 is the remedy, if the owner adopts it.
- **Path dependence.** An early weak keep fixes the code that later rounds
  see.

**Design limits:**
- Compounds pair only near-misses on the same base, so there are fewer than in
  X2-D; the count is recorded.
- The understanding stays the original base's.
- Lessons and per-change gains from round 2 on are marginal.

## 6 CI minutes

**Added per round:**
- An adopted round adds:
  - one round combine, with its ABAB re-test and the suite;
  - one baseline with its calibration (3 blocks);
  - one profile.
- A round that did not hold adds the combine only. A round with no keeps adds
  nothing.
- The last round's combine replaces X2-D's final combine.
- The final re-test against the original base is added once per run.
- **Worst case for 3 rounds:** about 12 paired-trial measurements and 2
  profiles a run.

**Where the timing comes from:**
- **The design estimate** is at most about 18 minutes a run, from X2-D's
  archived 1.44 minutes or less per whole trial. Doubled, as the ledger does,
  that gives a declared 38: 171 minutes a run, two runs a dispatch inside the
  360-minute job. This is an estimate, not a measurement.
- **The measured figures** come from the replay (`o62/replay.md`, run
  43194422719, GitHub runners, no API spend).
  - One adopted round (combine re-test + baseline with calibration at the tip
    + profile) took 29 s on tomli, 58 s on mistune and 68 s on sqlparse. The
    estimate for markdown is about 52 s.
  - The worst case for a 3-round X2-DT run is two adopted rounds, each with a
    fallback, plus the final re-test against the original base: under 3
    minutes.
  - **Proposed rider:** 10 minutes (more than 3x the measured worst case),
    so 143 minutes a run and two runs a dispatch (286 of 360).
  - The pilot's in-run timings replace this rider.
