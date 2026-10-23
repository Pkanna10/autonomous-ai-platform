"""Workload: ``python -m deliveryround.main``."""

from deliveryround.distance import distance_so_far, leg_length
from deliveryround.network import build_stops, find_stop, legs
from deliveryround.pickups import pending_views


def main() -> None:
    stops = build_stops(1000)
    round_legs = legs(stops, 9000)
    lengths: list[int] = []
    zones: dict[str, int] = {}
    for start, end in round_legs:
        a, b = find_stop(stops, start), find_stop(stops, end)
        lengths.append(leg_length(a, b))
        zones[b.zone] = zones.get(b.zone, 0) + 1
    so_far = distance_so_far(lengths)
    for i in range(0, len(so_far), 2000):
        print(f"leg {i}\t{so_far[i]} m")
    print(f"total\t{so_far[-1] + lengths[-1]} m")
    print("zones\t" + " ".join(f"{z}={n}" for z, n in sorted(zones.items())))
    offers = [
        (length % 997, end)
        for length, (_, end) in zip(lengths, round_legs, strict=True)
    ]
    for view in pending_views(offers[:4000], 800, 3):
        print("next\t" + " ".join(f"{code}:{cost}" for cost, code in view))


if __name__ == "__main__":
    main()
