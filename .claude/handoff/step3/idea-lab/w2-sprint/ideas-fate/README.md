# Where X2-P's 36 untrialled framework ideas went (O61 report item)

X2-P dealt 72 procedures; 51 ideas passed the reply's checks, 15 were trialled
(7 kept). Join: a procedure row's `hypothesis_id` (set by
`idea_portfolio_leap.with_hypotheses` for every idea in the generator's
result). 15 of the 51 carry one, each matching exactly one hypothesis row of the
same framework and round; the other 36 carry none. Scripts: `a.py` (join),
`b.py` (lane-quota split, title checks), `c.py` (same-function hint).

**What the rows can tell.** None of the 36 became a hypothesis, so the pool,
parking, the round limit and the budget account for none (0 parked, 0
unaffordable in all 12 runs; every hypothesis row was trialled). None repeats an
earlier round's title in its run. All 36 were removed inside the idea pipeline
after the leap's checks: by the deterministic filter (S4a: no anchor, ceiling
unknown, below the gate, same structural signature, obvious signature, avoided
or lesson title, shown technique), the reviewer (S3, which only removes,
`duplicate_of` included), or portfolio selection (S4b: repeated title, the one
per lane / anchor / primary cell quotas, the tier swap). Mechanism dedupe, the
only merge path, is off in the X2 arms.

**What they cannot tell.** Which of S4a, S3 or S4b removed each idea: the S4a and
S3 drops emit `idea_dropped` events, which carry no idea id and are not copied
into the results; portfolio non-picks emit nothing.

| framework   | ideas | trialled | not trialled | leap slot taken by a sibling (f1) | no leap idea picked that round (f2) |
| ----------- | ----- | -------- | ------------ | --------------------------------- | ----------------------------------- |
| bentley     | 7     | 1        | 6            | 3                                 | 3                                   |
| per_element | 5     | 0        | 5            | 3                                 | 2                                   |
| backend     | 4     | 1        | 3            | 1                                 | 2                                   |
| skiena      | 3     | 0        | 3            | 1                                 | 2                                   |
| polya       | 5     | 3        | 2            | 2                                 | 0                                   |
| from_spec   | 5     | 1        | 4            | 3                                 | 1                                   |
| ifr         | 5     | 3        | 2            | 1                                 | 1                                   |
| trim        | 7     | 2        | 5            | 2                                 | 3                                   |
| sit         | 5     | 1        | 4            | 4                                 | 0                                   |
| recall      | 5     | 3        | 2            | 1                                 | 1                                   |
| **total**   | 51    | 15       | 36           | 21                                | 15                                  |

- **f1 (21):** a round where one leap idea was picked. If these reached the
  portfolio, its one-pick-per-lane quota (top priority, relaxed last) is the
  only thing that could cut them; never more than one leap idea was trialled in
  a round.
- **f2 (15):** a round with leap ideas but no leap pick: the anchor or
  primary-cell quota, the tier swap, S4a or S3. 8 of the 15 are mistune (no
  mistune leap idea was trialled in any of its 6 rounds with ideas). The
  portfolio usually took exactly its minimum of 3 non-obvious ideas.
- A weak hint: for 24 of the 36, a trialled idea from another lane in the same
  round names the same function in its title.

**Record-only field that would make the fate countable.** A `fate` per leap
procedure row, filled the way `hypothesis_id` is: `s4a:<reason>`,
`s3:pre_review_<problem>`, `s3:review_<reason>`, `s4b:repeated_title`,
`s4b:quota_lane|quota_anchor|quota_primary_cell`, `s4b:tier_swapped`,
`bound:novel` or `result`, with `duplicate_of` for duplicates. A cheaper partial
version: the idea id on every `idea_dropped` event, and those events recorded.
Neither changes a request or a selection. This is O61 addendum item 4's fate
field, built after the last key-2 dispatch.

**Built (U-fate, 2026-11-12).** The fate field is recorded from the next run
on, with three departures from the vocabulary above:
- `s4b:not_picked` is replaced by `s4b:quota_several` (all blocking quotas in
  `quotas`), `s4b:portfolio_full` and `s4b:minimum_reached`.
- A fate names only a quota still active when the fill ended.
- Ideas dropped by the reply's checks before they had an id are recorded as
  `<lane>-read-NN`, joined to procedure rows by `fate_id`.

Every X2 round row carries `idea_fates` and `fate_counts`. The 36 ideas
counted here predate the field, so they stay as described.
