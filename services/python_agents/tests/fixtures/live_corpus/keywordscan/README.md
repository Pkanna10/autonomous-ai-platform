# keywordscan

Scans generated log lines for watch-list keywords (whole words only) and prints
how many lines hit per severity.

```
python -m keywordscan.main
```

The log and the watch list are generated deterministically, so the output is the
same on every run.
