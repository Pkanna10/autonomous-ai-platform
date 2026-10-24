# ledgerclose

Closes a day of ledger transfers: settles them in arrival order, prints the
final balance of every account, and reports the highest running balance seen
over the most recent transfers at regular checkpoints.

```
python -m ledgerclose.main
```

The transfers are generated deterministically, so the output is the same on
every run.
