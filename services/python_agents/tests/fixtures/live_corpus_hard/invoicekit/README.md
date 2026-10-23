# invoicekit

A small invoicing toolkit: it reads a day of raw invoice lines, prices each line
(unit price, quantity, volume discount, regional sales tax), groups the lines
into invoices per customer, and prints a closing report: totals per region and
per product family, the largest invoices, and a checksum of every invoice total.

```
python -m invoicekit.main
```

Modules:

- `feed`: the deterministic raw lines (the same data on every run)
- `parsing`: turns raw lines into typed records, rejecting malformed ones
- `models`: customers, line items and invoices
- `money`: amounts in cents, rounding and formatting
- `rules`: the regional tax schedule
- `discounts`: volume discount tiers
- `pricing`: prices one line
- `ledger`: groups priced lines into invoices and totals
- `report`: the closing report
- `days`: weekdays and week numbers
- `customers`: customer statistics and segments
- `audit`: consistency checks before the report is trusted
- `export`: delimited text for the accounting system
