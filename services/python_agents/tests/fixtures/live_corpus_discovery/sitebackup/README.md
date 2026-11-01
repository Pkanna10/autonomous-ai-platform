# sitebackup

Backs up a small website: renders every page from its template, bundles the
pages into one archive in the xz format (preset 6, the format the restore tool
reads) and prints the size of each section, the size of the archive and its
SHA-256.

```
python -m sitebackup.main
```

The site content is generated deterministically, so the output is the same on
every run.
