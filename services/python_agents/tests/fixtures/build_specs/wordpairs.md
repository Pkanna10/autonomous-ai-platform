# wordpairs: the most frequent word pairs of a text

Build a small command-line tool that reads a text and prints its most frequent
pairs of adjacent words, leaving out pairs with a stop word.

## Package and public API

- Package name: `wordpairs`.
- `wordpairs.top_pairs(text: str, n: int = 20) -> list[tuple[str, str, int]]`
  returns the `n` most frequent pairs as `(first, second, count)` tuples in
  report order (rules below); fewer when the text has fewer distinct pairs. `n`
  below 1 raises `ValueError`.
- `wordpairs.render(text: str, n: int = 20) -> str` returns the report (the
  format is below).
- `python -m wordpairs FILE` reads FILE as UTF-8 and prints `render(text)` to
  standard output with nothing before or after it (the report already ends with
  a newline, so print it with `end=""`).

## Words and pairs

- A word is a maximal run of the ASCII letters `a`-`z` and `A`-`Z`; every other
  character (digits, punctuation, apostrophes, whitespace, line breaks, any
  non-ASCII character) separates words. Words are lower-cased.
- The words of the whole text form one sequence; line breaks do not end it. A
  pair is two consecutive words of that sequence: a text of k words has k - 1
  pairs.
- A pair is left out when either of its words is one of these 12 stop words:
  `a`, `an`, `and`, `in`, `is`, `it`, `of`, `on`, `the`, `to`, `was`, `with`.
  Leaving a pair out does not join its neighbours: in `red and blue fox` the
  only pair kept is `blue fox`.

## Order

Pairs are ordered by count (largest first); equal counts are ordered by the
first word, then the second word (ascending, plain string order).

## Output

One line per reported pair: its rank (from 1), a tab, the two words separated by
one space, a tab, its count. Then one last line `kept=<K> distinct=<D>`, where K
is the number of pairs kept (with repetitions) and D the number of distinct kept
pairs. Every line ends with `\n`. A text with no kept pair gives only
`kept=0 distinct=0`.

Example: `render("Red fox, red fox. The red fox ran; red Fox ran!", 3)` is

```
1	red fox	4
2	fox ran	2
3	fox red	1
kept=8 distinct=4
```

(the pairs `fox the` and `the red` contain a stop word and are left out; the
kept pairs are `red fox` 4 times, `fox ran` twice, `fox red` once and `ran red`
once; `fox red` comes before `ran red` because `fox` sorts first).

## Benchmark size

The benchmark generates a corpus of 1,000,000 words with seed 11: a fixed
vocabulary of the 12 stop words plus 3,000 made-up lower-case words of 3 to 9
letters, drawn with Zipf-like weights (the stop words most often), with random
capitalisation of the first letter, a comma or period after about one word in
ten and a line break after every 15 words. It calls `render` once with n = 20
and prints the report. A straightforward implementation runs in about 1 to 3
seconds.
