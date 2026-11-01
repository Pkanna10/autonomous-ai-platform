# clubroster

Prints a sports club's season standings as a paged roster: members ranked by
points (highest first), then by surname and given name, ignoring case, then by
membership number; 25 members a page, each page with its header.

```
python -m clubroster.main
```

The members are generated deterministically, so the output is the same on every
run.
