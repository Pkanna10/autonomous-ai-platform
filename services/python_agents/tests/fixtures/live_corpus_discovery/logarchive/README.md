# logarchive

Archives a day of service logs in the operator's archive format: one deflate
stream at the highest compression level, fed in 4 KiB pieces, with a size
checkpoint after every 64 pieces so a reader can seek. Prints the checkpoints,
the size of the archive, its CRC-32 and the Adler-32 of the original log.

```
python -m logarchive.main
```

The log is generated deterministically, so the output is the same on every run.
