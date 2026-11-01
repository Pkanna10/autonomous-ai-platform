# auditchain

Seals a week of audit-trail entries (six business days) into a hash chain: the
seal of each entry is the BLAKE2b digest of the previous seal followed by the
entry, so no entry can be changed or dropped without changing every later seal.
Prints the seal at the end of each day and the seal of the whole week.

```
python -m auditchain.main
```

The entries are generated deterministically, so the output is the same on every
run.
