# G9 brief: pick the held-out OSS set (for a separate, non-tuning session)

You are picking a sealed test set for an optimisation engine. You do no tuning
and never see the engine's prompts or results: do not read `STATUS.md`,
anything under `.claude/handoff/` (this file aside) or `tests/live/`. The
list you produce stays outside the repository; only its salted hash goes in.

## Pick N libraries (N = 8 unless the owner says otherwise)

Each entry is a public open-source Python library with:

1. **A CPU-bound pure-Python hot path** that a realistic workload exercises
   (parsing, data structures, numerical code, text or data processing), with
   room for a measurable speed or memory gain; no C-extension-only core.
2. **A permissive licence** (MIT, BSD, Apache-2.0, ISC, PSF) and an active
   repository.
3. **A pinned commit** (40-hex SHA) on its default branch. Pick it so that
   at least one later commit improves the hot path's speed or memory: the
   set is scored on what the engine finds at the pin, and the history view
   never reads past the pin.
4. **A workload:** one shell-free command (argv list) run from the repository
   root that exercises the hot path for 0.3-3 s on one core, prints a
   deterministic output, and needs no network.
5. **Not already used:** no library named in any `manifest.json` under
   `services/python_agents/tests/fixtures/` (the development set, the corpora
   and V9), and no library that is a famous benchmark's subject.
6. **Spread:** no two from the same domain where avoidable.

## Seal it

```python
import hashlib, json, secrets
entries = [  # one dict per library, sorted by "library"
    {"library": "...", "repo": "https://github.com/...", "commit": "<40 hex>",
     "workload": ["python", "-m", "..."], "domain": "..."},
]
salt = secrets.token_hex(32)
canonical = json.dumps(sorted(entries, key=lambda e: e["library"]),
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True)
digest = hashlib.sha256((salt + "\n" + canonical).encode()).hexdigest()
```

Give the owner the list, the salt and the digest. Give the Lead only the
digest and N. The Lead commits `heldout.sha256` with the scheme line above and
the digest; at the K run the owner reveals the list and salt and anyone can
recompute the digest.
