# Marker validation data (idea lab, O36-O37)

`oss_ab_rank_rows.jsonl`: the 332 `E5-oss-ab-rank` rows of Window 0's 18
oss-ab runs (2026-10-24), copied from their results artifacts before they
expire on 2026-11-23. One row per idea the generator proposed: `run_id`,
`repo`, `rep`, `arm`, `rank` (1 = the generator's first idea), `title`,
`change_class`, `verdict` (`keep` 114, `inconclusive` 175, `reject` 43),
`gain_pct`, `noise_floor_pct`, `guard` (all `ok`).

Used by the idea lab's marker validation under the bar fixed in STATUS O37:
the marker sees the title, the class and the hot code from the pinned clone,
never the verdict or the gain.
