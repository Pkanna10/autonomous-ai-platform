# stockbook

Posts a day of stock movements (receipts and shipments) to a stock book, prints
the closing level of a sample of stock codes, the number of codes seen, the
quantity backordered, and the audit-trail check value of the day.

```
python -m stockbook.main
```

The movements are generated deterministically, so the output is the same on
every run.
