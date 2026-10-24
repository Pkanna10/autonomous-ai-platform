import random

STOP = "a an and in is it of on the to was with".split()
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def make_corpus(seed: int, words: int) -> str:
    rng = random.Random(seed)
    made = set()
    while len(made) < 3000:
        made.add("".join(rng.choice(LETTERS) for _ in range(rng.randint(3, 9))))
    vocab = STOP + sorted(made - set(STOP))
    weights = [1.0 / (rank + 1) for rank in range(len(vocab))]
    picked = rng.choices(vocab, weights=weights, k=words)
    out = []
    for index, word in enumerate(picked, start=1):
        if rng.random() < 0.2:
            word = word.capitalize()
        if rng.random() < 0.1:
            word += rng.choice(",.")
        out.append(word)
        out.append("\n" if index % 15 == 0 else " ")
    return "".join(out)
