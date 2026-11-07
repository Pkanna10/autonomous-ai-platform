"""wordpkg's benchmark: three texts, each rendered twice running, 20 times."""

import wordpkg.core
from wordpkg.core import lex, render

TEXTS = ["alpha", "beta", "gamma"]
for _ in range(20):
    for text in TEXTS:
        render(text, sep="-")
        render(text, sep="-")
lex("direct")
print(wordpkg.core.shout("x"))
