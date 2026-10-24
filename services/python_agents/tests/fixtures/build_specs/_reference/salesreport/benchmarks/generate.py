import random

REGIONS = ("CENTRAL", "EAST", "NORTH", "NORTHEAST", "SOUTH", "SOUTHWEST", "WEST", "ZONE-X")


def make_csv(seed: int, rows: int) -> str:
    rng = random.Random(seed)
    products = [f"item-{i:02d}" for i in range(60)]
    lines = ["date,region,product,units,unit_price"]
    for _ in range(rows):
        month = rng.randrange(24)
        year, mon = 2024 + month // 12, month % 12 + 1
        day = rng.randint(1, 28)
        cents = rng.randint(50, 25000)
        lines.append(
            f"{year}-{mon:02d}-{day:02d},{rng.choice(REGIONS)},{rng.choice(products)},"
            f"{rng.randint(1, 20)},{cents // 100}.{cents % 100:02d}"
        )
    return "\n".join(lines) + "\n"
