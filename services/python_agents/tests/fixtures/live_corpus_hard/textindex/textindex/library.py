"""The deterministic library: short documents built from a fixed vocabulary."""

from dataclasses import dataclass

SUBJECTS = (
    "the river", "a lighthouse", "the old mill", "our garden", "the harbour",
    "a mountain path", "the city archive", "a small bakery", "the night train",
    "the observatory", "a quiet library", "the market square",
)  # fmt: skip
VERBS = (
    "remembers", "watches", "collects", "repairs", "describes", "follows",
    "measures", "protects", "welcomes", "outlasts", "illuminates", "connects",
)  # fmt: skip
OBJECTS = (
    "the travellers", "every season", "the storms", "forgotten letters",
    "the morning tides", "its keepers", "the workers", "distant villages",
    "the winter markets", "old photographs", "the ferry crossings",
    "the stars above", "the children", "the harvest",
)  # fmt: skip
CLAUSES = (
    "while the town sleeps", "as the fog rises", "before the bells ring",
    "when the rain returns", "although nobody asks", "because it always has",
    "after the long summer", "until the lamps are lit", "during the festival",
    "whenever the wind turns",
)  # fmt: skip


@dataclass(frozen=True)
class Document:
    number: int
    title: str
    text: str


class Lcg:
    def __init__(self, seed: int) -> None:
        self.state = seed

    def next(self) -> int:
        self.state = (self.state * 1103515245 + 12345) % (1 << 31)
        return self.state >> 4

    def pick(self, options: tuple[str, ...]) -> str:
        return options[self.next() % len(options)]


def sentence(rng: Lcg) -> str:
    words = f"{rng.pick(SUBJECTS)} {rng.pick(VERBS)} {rng.pick(OBJECTS)}"
    if rng.next() % 2:
        words += f" {rng.pick(CLAUSES)}"
    return words[0].upper() + words[1:] + "."


def documents(count: int, sentences: int, seed: int = 101) -> list[Document]:
    """``count`` documents of ``sentences`` sentences each."""
    rng = Lcg(seed)
    out: list[Document] = []
    for number in range(count):
        body = " ".join(sentence(rng) for _ in range(sentences))
        title = f"Notes {number:04d}: {rng.pick(SUBJECTS)}"
        out.append(Document(number, title, body))
    return out
