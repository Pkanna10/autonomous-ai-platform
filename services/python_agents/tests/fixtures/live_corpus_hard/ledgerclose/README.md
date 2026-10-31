# ledgerclose

Closes a day of ledger transfers: settles them in arrival order, prints the
final balance of every account, and reports at regular checkpoints which level
(a step of 600.00) the total held across all accounts is at, the levels numbered
in the order the total first reaches them.

```
python -m ledgerclose.main
```

The transfers are generated deterministically, so the output is the same on
every run.
