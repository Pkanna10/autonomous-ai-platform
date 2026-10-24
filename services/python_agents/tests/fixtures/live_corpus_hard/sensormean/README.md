# sensormean

Summarises the readings of a set of field sensors: for every sensor it prints
the mean of all readings received so far after each reading, at full float
precision, so the published series can be compared digit for digit with the
station's own log.

```
python -m sensormean.main
```

The readings are generated deterministically, so the output is the same on every
run.
