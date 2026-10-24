# salesreport: a monthly sales report by region

Build a small command-line tool that reads sales records in CSV form and
prints a report that groups them by region and calendar month.

## Package and public API

- Package name: `salesreport`.
- `salesreport.build_report(csv_text: str) -> str` returns the whole report
  as one string (the format is below). It is the only function the tests
  call.
- `python -m salesreport FILE` reads FILE as UTF-8 and prints
  `build_report(text)` to standard output with nothing before or after it
  (the report already ends with a newline, so print it with `end=""`).

## Input

CSV text with a header line followed by one record per line, fields
separated by commas, lines separated by `\n` (a final newline is optional):

```
date,region,product,units,unit_price
2025-03-14,NORTH,widget-07,3,12.50
```

- The header is exactly `date,region,product,units,unit_price`; any other
  first line raises `ValueError`.
- `date` is `YYYY-MM-DD`; its month is the `YYYY-MM` prefix.
- `region` and `product` are non-empty strings of upper-case letters,
  lower-case letters, digits and `-` (never a comma or a quote).
- `units` is a whole number from 1 to 1000.
- `unit_price` is a decimal with exactly two digits after the point
  (`0.01` to `9999.99`).
- Empty lines are ignored. Every other line is well formed.
- An input with the header and no records is valid.

## Output

The first line is the header `region,month,orders,units,revenue,top_product`.
Then one line per (region, month) pair that has at least one record, sorted
by region (ascending, plain string order), then by month (ascending):

```
region,month,orders,units,revenue,top_product
EAST,2025-01,2,7,64.24,gear-02
```

- `orders`: the number of records in the group.
- `units`: the sum of `units` in the group.
- `revenue`: the sum of `units * unit_price` over the group, computed
  exactly (in whole cents, never with binary floating point) and printed
  with exactly two digits after the point and no thousands separator.
- `top_product`: the product with the largest sum of `units` in the group;
  a tie goes to the product name that sorts first (plain string order).

The last line is `TOTAL,,<orders>,<units>,<revenue>,` with the totals over
every record (the month and the top product are empty). Every line,
including the last, ends with `\n`. With no records the report is the
header line and `TOTAL,,0,0,0.00,`.

Example: for the input

```
date,region,product,units,unit_price
2025-01-05,EAST,gear-02,4,10.00
2025-01-20,EAST,bolt-01,3,8.08
2025-02-01,WEST,gear-02,1,0.99
```

the report is

```
region,month,orders,units,revenue,top_product
EAST,2025-01,2,7,64.24,gear-02
WEST,2025-02,1,1,0.99,gear-02
TOTAL,,3,8,65.23,
```

## Benchmark size

The benchmark generates 200,000 records with seed 7: 8 regions, 60
products, dates spread uniformly over the 24 months of 2024 and 2025
(day 01 to 28), units from 1 to 20, prices from 0.50 to 250.00. It calls
`build_report` once on the generated text and prints the report. A
straightforward implementation runs in about 1 to 3 seconds.
