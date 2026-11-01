# booklist

Replays a day at an online bookshop: new titles arrive in the catalogue while
customers browse it by the first letters of a title. Every browse lists the
first matching titles in alphabetical order, as link slugs. Prints a sample of
the listings, the number of entries listed and the total slug length.

```
python -m booklist.main
```

The day is generated deterministically, so the output is the same on every run.
