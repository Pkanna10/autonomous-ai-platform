# parcelindex

Loads a land registry, every parcel with its zone, its owners and the corner
points of its boundary, then answers the day's questions: the number of parcels
and the total area per zone, the largest parcels, and the owners holding the
most parcels.

```
python -m parcelindex.main
```

The registry is generated deterministically, so the output is the same on every
run.
