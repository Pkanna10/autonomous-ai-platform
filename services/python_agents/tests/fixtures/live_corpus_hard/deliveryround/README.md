# deliveryround

Plans a delivery round over a network of stops: resolves each leg's stop codes,
accumulates the distance driven so far, and keeps the lowest-cost pending
pickups in order so a dispatcher can see the next few at each checkpoint.

```
python -m deliveryround.main
```

The network and the legs are generated deterministically, so the output is the
same on every run.
