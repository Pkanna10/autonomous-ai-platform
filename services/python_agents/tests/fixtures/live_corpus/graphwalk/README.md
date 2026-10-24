# graphwalk

Builds a generated social graph and prints, from one starting member, how many
members are reachable, the largest number of hops, and the sum of the hop counts
(breadth-first search).

```
python -m graphwalk.main
```

The graph is generated deterministically, so the output is the same on every
run.
