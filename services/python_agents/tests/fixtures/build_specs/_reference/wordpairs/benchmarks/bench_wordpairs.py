from generate import make_corpus

from wordpairs import render

SEED = 11
WORDS = 1_000_000

print(render(make_corpus(SEED, WORDS), 20), end="")
