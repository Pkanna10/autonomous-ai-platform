# distmatrix

Summarises the pairwise distances between a set of survey points: for every
point the distance to its nearest neighbour and the mean distance to all the
others, then the most isolated points and a histogram of nearest-neighbour
distances.

```
python -m distmatrix.main
```

The points are generated deterministically, so the output is the same on every
run.
