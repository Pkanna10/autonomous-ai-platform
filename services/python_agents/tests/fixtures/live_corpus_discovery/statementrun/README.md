# statementrun

Prints the month-end statements of a small bank: one statement per account,
every transaction with its running balance, all statements laid out in the same
aligned columns so they can be printed as one booklet.

```
python -m statementrun.main
```

The transactions are generated deterministically, so the output is the same on
every run.
