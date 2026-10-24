"""Words too common to index.

The list is kept as plain text so the content team can extend it.
"""

STOPWORDS_TEXT = """
a about above after again against all am an and any are as at be because
been before being below between both but by can could did do does doing
down during each few for from further had has have having he her here hers
herself him himself his how i if in into is it its itself just me more most
my myself no nor not now of off on once only or other our ours ourselves out
over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up
very was we were what when where which while who whom why will with would
you your yours yourself yourselves always never nobody every across along
also although among another anybody anyone anything anywhere around away
back became become becomes behind beside besides beyond cannot either else
elsewhere enough even ever everybody everyone everything everywhere except
first former formerly hence however indeed instead later latter least less
many may meanwhile might mine moreover much must namely neither nevertheless
next none nothing nowhere often onto otherwise perhaps rather since someone
something sometime sometimes somewhere still thence thereafter thereby
therefore thus together toward towards unless upon whatever whence whenever
whereas whether whoever whole whose within without yet
"""


def stopword_list() -> list[str]:
    """The stop words, in the order the text lists them."""
    return STOPWORDS_TEXT.split()


def is_stopword(word: str) -> bool:
    return word in stopword_list()


def content_words(words: list[str]) -> list[str]:
    """``words`` without the stop words, order kept."""
    return [word for word in words if not is_stopword(word)]
