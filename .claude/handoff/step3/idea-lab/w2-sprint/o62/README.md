# O62: X2-0 pool runs with the fate field, and the leap cap (2026-11-12)

## 1 X2-0, one run per library (O62 item 4), on `bbd04ea`, key 2

| Dispatch    | Library  | USD  | Kept | Combine (held) | Conflicts skipped | Baseline floor |
| ----------- | -------- | ---- | ---- | -------------- | ----------------- | -------------- |
| 43181006070 | sqlparse | 2.43 | 4    | +20.7          | 1                 | 2.15           |
| 43181006070 | tomli    | 1.85 | 2    | +9.7           | 1                 | 6.57           |
| 43181010850 | mistune  | 2.49 | 5    | +23.7          | 0                 | 2.00           |
| 43181010850 | markdown | 2.62 | 7    | +10.6          | 5                 | 2.00           |

- **Spend:** 9.39 USD from key 2's original credit, which goes from 10.97 to
  1.58 by the ledger.
- **These runs join the pool for future arms only.** No reading already made
  changes.
- **Conditions:** no refusal, every combine held. One request stopped at
  max_tokens: the Opus leap on mistune, round 2, at 12,000 (section 3). No
  reading uses these runs, so it stops no arm.
- **The fate records hold up on a live run:**
  - Each run tapped 2 generator calls against 2 `generated` events, so every
    round reads `idea_fates_aligned: true`.
  - `conflicts` is null, because no dry merge ran in X2-0.
  - Every skip is a greedy-stage conflict.
  - The combine fates are 11 applied and 7 conflict.

## 2 Fate counts per lane and stage (four runs, 8 rounds, 163 ideas read)

| Lane             | read | s4a | s3  | s4b | bound | result | total |
| ---------------- | ---- | --- | --- | --- | ----- | ------ | ----- |
| obvious          | 1    | 0   | 0   | 0   | 0     | 27     | 28    |
| recombine        | 4    | 1   | 2   | 10  | 0     | 7      | 24    |
| name_the_problem | 8    | 1   | 10  | 3   | 0     | 2      | 24    |
| assume_less      | 6    | 5   | 4   | 6   | 0     | 3      | 24    |
| resolve_tradeoff | 6    | 2   | 2   | 7   | 0     | 3      | 20    |
| far              | 6    | 2   | 5   | 2   | 0     | 2      | 17    |
| leap             | 4    | 1   | 0   | 2   | 0     | 6      | 13    |
| eliminate        | 2    | 1   | 2   | 5   | 0     | 3      | 13    |
| **all**          | 37   | 13  | 25  | 35  | 0     | 53     | 163   |

**By value:**

| Count | Fate |
| --- | --- |
| 53 | `result` |
| 31 | `read:ungrounded` |
| 24 | `s3:review_duplicate_of` |
| 19 | `s4b:quota_several` |
| 9 | `s4a:duplicate` |
| 9 | `s4b:quota_primary_cell` |
| 5 | `s4b:quota_lane` |
| 4 | `s4a:obvious_signature` |
| 4 | `read:field_title` |
| 1 each | `read:field_change_summary`, `read:field_justification_summary`, `s4b:tier_swapped`, `s4b:quota_anchor`, `s3:review_precondition_false` |

- **Every idea has exactly one fate.** The 53 `result` fates equal the 53
  hypothesis rows, and none is `unrecorded`.
- **The three largest removals:**
  - ungrounded replies (31), which never anchor on the code shown;
  - the reviewer's duplicate verdicts (24);
  - ideas blocked by more than one portfolio quota (19).
  The quota rows show lane and primary cell blocking together, the case the
  "leap slot taken by a sibling" question could not see.
- **The truncated mistune leap (round 2) left no fates.** A reply cut off at
  max_tokens cannot be read, so its ideas never reach the fate record. Only
  the lane's `stop_reason` shows it.

## 3 The Opus leap cap (O62 item 7)

| Archive (the only ones that record leap output)    | Leap calls | Cap    | At the cap | At or above 90 % of it | Median | Largest that replied |
| -------------------------------------------------- | ---------- | ------ | ---------- | ---------------------- | ------ | -------------------- |
| X2-D confirmation (Opus 5.5)                       | 24         | 12,000 | 2          | 3                      | 6,105  | 10,891               |
| X2-0 pool runs above (Opus 5.5)                    | 8          | 12,000 | 1          | 1                      | 5,162  | 7,927                |
| **Opus 5.5 together**                              | 32         | 12,000 | **3 (9 %)** | 4                     | 6,074  | 10,891               |
| X1 probes (configs X1-0 to X1-3)                   | 39 replied | 12,000 | 0          | 0                      | about 6,000 | 9,711           |
| E1 probes (cap above 17k)                          | 32         | -      | -          | -                      | about 7,300 | 16,886 (Fable, arm D) |
| X2-L (Fable 5.2)                                   | 6 recorded | 32,000 | 1          | 1                      | 16,175 | 19,499               |

- **Two of the three Opus stops are mistune round 2,** in two different arms.
  Later rounds see longer seed and lesson context, which may lengthen the
  reply.
- **Sprint rows before U-tokens (`c909427`) cannot show a stop,** so earlier
  truncations are not countable.

**Proposal: a labelled baseline change, not inside any running arm.**

- **New default for the Opus leap:** `IDEAS_LEAP_MAX_TOKENS` 24,000 and the
  leap's request timeout 951 s, the Fable leap's tested shape. Today they are
  12,000 and 300 s.
  - 24,000 doubles the cap. It covers the longest recorded Opus reply and the
    E1 Fable replies up to 16,886 with margin.
  - The timeout must grow with it: 24,000 tokens do not stream in 300 s.
- **Cost:**
  - Output is billed only as produced: a leap that would have stopped at
    12,000 costs at most 0.24 USD more, at 20 USD per million output tokens.
  - The engine's pre-flight reservation for each leap call rises by 0.24 USD,
    and each arm's run cap with it. X2-0 has 2 leap calls a run (9.35 to about
    9.83); X2-D has 3 (12.90 to about 13.62).
- **How it lands:**
  - **As its own labelled baseline,** for example X2-0 at "leap 24k". It needs
    fresh pool runs, one per library at least, before any arm is read against
    it. Every reading so far stands on the 12,000 pool.
  - **Timing: after X2-DT has been read.** X2-DT keeps 12,000 so that it
    stays comparable with the 20 X2-D runs (O62: no change inside a running
    arm, and no other arm until the stacked arm has been read).
- **Owner's call:** adopt 24,000 / 951 s as the next baseline, a different
  figure, or leave 12,000 as it is.
