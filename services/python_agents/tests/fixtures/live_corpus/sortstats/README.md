# sortstats

Draws a deterministic sample of 32-bit readings and prints its order statistics
(minimum, quartiles, maximum) and a checksum of the sorted sample.

```
python -m sortstats.main
```

The sample is drawn from a seeded generator, so the output is the same on every
run.
