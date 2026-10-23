# eventagg

Aggregates a day of service events (requests, retries, errors) per event type
and per region: how many there were, how many bytes they moved, and the highest
latency seen.

```
python -m eventagg.main
```

The events are generated deterministically, so the output is the same on every
run.
