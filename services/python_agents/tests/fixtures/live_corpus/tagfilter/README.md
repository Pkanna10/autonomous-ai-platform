# tagfilter

Counts the generated records that carry at least one tag from an allowlist, and
prints how many matched per record kind.

```
python -m tagfilter.main
```

The records and the allowlist are generated deterministically, so the output is
the same on every run.
