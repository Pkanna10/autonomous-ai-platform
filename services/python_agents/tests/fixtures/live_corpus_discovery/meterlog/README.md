# meterlog

Reads a month of smart-meter readings, one JSON object per line with the fields
`meter`, `hour`, `kwh` (thousandths of a kilowatt-hour) and `volts` (tenths of a
volt), and prints the energy used per tariff band, the meters with the highest
use, the readings outside the voltage limits and the readings of the meters
under review.

```
python -m meterlog.main
```

The readings are generated deterministically, so the output is the same on every
run.
