# tripsheet

Summarises a month of trip records from a city transport operator: distance,
fares by region, the busiest mode, the longest trip, the fare per kilometre,
crowding, late-night travel and short-hop fares.

```
python -m tripsheet.main
```

Each record is one JSON object per line with the fields `trip`, `region`,
`metres`, `fare` (cents), `riders`, `mode` and `hour`. The records are generated
deterministically, so the output is the same on every run.
