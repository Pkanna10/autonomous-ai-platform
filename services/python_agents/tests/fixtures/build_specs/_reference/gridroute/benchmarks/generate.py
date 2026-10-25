import random


def make_grid(seed: int, width: int, height: int) -> str:
    rng = random.Random(seed)
    rows = [
        "".join(str(rng.randint(1, 9)) for _ in range(width)) for _ in range(height)
    ]
    return f"{width} {height}\n" + "\n".join(rows) + "\n"
