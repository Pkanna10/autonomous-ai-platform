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
