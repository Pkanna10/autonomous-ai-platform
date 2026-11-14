# Round 3 exam seal (stage 2), 2026-11-13

The examiner (Fable 5.2) built the papers before reading any student notes. The key was hashed, encrypted and its plaintext deleted before any student saw a paper. The re-sit papers have their own hashes.

| item | sha256 (tree hash: the sha256 of the sorted per-file sha256 list) |
| ---- | ---- |
| key, first sitting (`key/` without `key/resit/`) | `19d3e9aa8d11cddd0202fed3d9d981091925b35fcac017a8121ff4c4243026be` |
| key, re-sit (`key/resit/`) | `8b8dbfd8c6ed33958bb3aa7444de9063f36a9dbcea375646213af573a3f0b9de` |
| examiner's build folder (pristine clones, plant specs) | `cb287a0cf6c2f99a9f93ec2f6aad6fe01479e37373e4cd536be5a0ffefe3755a` |
| papers, first sitting (`papers/` without `papers/resit/`) | `015e9cbed23c2354f9e3550b500bf6f48640124b58ff0ec3b4c105868fd7a3f0` |
| papers, re-sit (`papers/resit/`) | `526cb4695bdbeb361d2766bcfa1f79ac0fec2e3464aba709aecfa52cf31a09a8` |
| the encrypted archive of key and build (AES-256-CBC, PBKDF2, 200,000 iterations) | `1ab17edf531381dfe2c8b658df1e02955055284141344e626e05dce2b76f6ce1` |

- **Papers:** practical tiers 1-4 (tomli, sqlparse, mistune, Python-Markdown at their pins), re-sit tiers 1-2 (idna 3.20, sortedcontainers 2.4.0), and 14 speciality papers of 3 questions.
- **Proof:** every plant, decoy and trap was proven by the examiner; each of the six reproduction scripts ended "OVERALL REPRODUCED". One candidate tier-2 plant was removed as unprovable (2.4 % and 3.7 %, too close to the 3 % floor).
- **Where the key is:** encrypted in the Lead's sealed folder, which the guard closes to every agent; the passphrase sits beside it. The examiner's access ended at sealing. The key is decrypted only for marking, which runs the reproduction scripts and `mark.py` by execution.
- **Never in what the engine reads:** papers and keys stay out of every prompt, lesson and example bank (charter, stage 2).
- **Note for the owner:** re-sit tier 1 is idna, the library whose V9 task is now exposed (O68); the paper is a planted-slowdown exam, not V9's task, so it affects no K4 claim.

## Marking (O69), 2026-11-14

All marks were measured on the Lead's machine, one at a time, with no sitting, gate, build or agent running. The 1-minute load average was between 0.61 and 1.10 throughout, and it is logged beside each mark in bundle v3. Students' own timings were not used. Per-seat marks and plant identities stay in the bundle, because the plant names describe the key.

**Validity condition 1 holds.** All six reproduction scripts (four practical, two re-sit) printed `OVERALL REPRODUCED` on the quiet machine, between 07:35 and 08:54 UTC.

**Validity condition 2 fails.** All 14 seats passed the gate, scoring at least 70 % on tier 1 and on tier 2, for a pass rate of 100 % (the valid band is 40-80 %). The exam is therefore invalid as a gate, and no mark counts. Under O69, the examiner builds a harder gate paper after the owner's go.

| paper | plants | seats at 70 % or more | plants found (of 14 seats each) | decoys fixed | traps taken | equivalence failures |
| --- | --- | --- | --- | --- | --- | --- |
| tier 1, gated | 1 | 14 | 14 | none in the paper | none in the paper | 0 |
| tier 2, gated | 2 | 14 | 14, 12 | none in the paper | none in the paper | 0 |
| tier 3, diagnostic | 2 | 14 | 14, 13 | 0 of 4 | none in the paper | 0 |
| tier 4, diagnostic | 2 | 14 | 14, 14 | 0 of 3 | 0 of 1 | 0 |

How the marks were reached:
- **Plants credited by their lines.** Where the answer had rewritten a plant's lines, so that the key's reversal no longer applied, the plant was credited by the lines it changed (marking 1.2). On tiers 1, 3 and 4, each such answer's total gain was above the summed proven gain of the plants credited that way.
- **Tier 2 re-measured per plant.** Its totals (28.7-33.7 %) fell below the sum of the two proven gains (37.9 %). The two plants overlap: the key's own all-plants reversal gains 29.1 % today. As marking 1.2 requires, every seat was re-measured per plant, with only that plant differing between the two trees.
- **Results on tier 2.** The first plant was recovered in full by all 14 seats. The second was missed by 2 seats, which recovered 71-72 % of its gain after pooling 15 runs a side (marking 1.6), so both still passed at about 90 %.
- **Borderline readings pooled.** Two diagnostic readings near the 75 % line were measured twice more (marking 1.6). On tier 3, one seat's partial fix stays missed (shares 0.46 and 0.59). On tier 4, one seat's fix is counted as found (0.70, then 0.86).

**Speciality papers.** All 14 passed (pass mark 2.1 of 3). Thirteen scored 3 of 3 and one scored 2.75. s1's code question passed `check_s1_q3.py`: 0 of 300 mismatches and a factor of at least 3,187x. s6's merges were checked by execution.

**Note for the next paper.** One question on z2's paper (Q1, item 2) can be read two ways: its design is described as both "its own step" (time) and "their own sandboxes" (space). It was marked by the key. The harder paper should word such items so that only one principle fits.

**Reading the result.** Every seat found every plain and one-away plant, so the papers did not separate the seats. No seat fixed a decoy or took the trap. Partial fixes of a second plant are the only differences between seats. A harder gate paper needs plants that are hidden further from the profile's top lines (kinds 2-4) and more of them per paper.
