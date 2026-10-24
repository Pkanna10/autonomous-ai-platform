# configlookup

Prices a generated basket of line items using the tax and discount rules of a
JSON rule set, and prints the totals per category.

```
python -m configlookup.main
```

The rules and the basket are generated deterministically, so the output is the
same on every run.
