# ratecheck

Fingerprints a day of currency conversions for a clearing house. Every rate is
recorded as an exact fraction (numerator over denominator) and is reduced modulo
the prime 2^127 - 1, so two ledgers can be compared without exchanging them.
Prints, per currency pair, the number of conversions and their combined
fingerprint, then the fingerprint of the whole day in order.

```
python -m ratecheck.main
```

The conversions are generated deterministically, so the output is the same on
every run.
