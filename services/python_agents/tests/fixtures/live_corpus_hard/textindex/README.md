# textindex

A small full-text search toolkit: it builds an inverted index over a generated
library of short documents, answers a batch of boolean and ranked (BM25)
queries, and prints the top results of each query with a snippet.

```
python -m textindex.main
```

Modules:

- `library`: the deterministic documents (the same text on every run)
- `tokens`: splitting text into normalised tokens
- `stopwords`: the words that are not indexed
- `stemmer`: a light suffix-stripping stemmer
- `index`: the inverted index with positions
- `query`: parsing and evaluating boolean queries
- `ranking`: BM25 scoring
- `snippets`: the best window of a document for a query
- `report`: printing the results
- `suggest`: did-you-mean suggestions
- `duplicates`: near-duplicate documents
- `stats`: statistics about the library
- `storage`: saving the index as text and reading it back
