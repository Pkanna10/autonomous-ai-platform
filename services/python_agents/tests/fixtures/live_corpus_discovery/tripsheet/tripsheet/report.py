"""The monthly summary of trip records (see ``data.records`` for the fields)."""

import json


def total_metres(lines: list[str]) -> int:
    return sum(json.loads(line)["metres"] for line in lines)


def fares_by_region(lines: list[str]) -> dict[str, int]:
    fares: dict[str, int] = {}
    for line in lines:
        record = json.loads(line)
        fares[record["region"]] = fares.get(record["region"], 0) + record["fare"]
    return fares


def busiest_mode(lines: list[str]) -> str:
    riders: dict[str, int] = {}
    for line in lines:
        record = json.loads(line)
        riders[record["mode"]] = riders.get(record["mode"], 0) + record["riders"]
    return max(riders, key=riders.__getitem__)


def longest_trip(lines: list[str]) -> str:
    best, name = -1, ""
    for line in lines:
        record = json.loads(line)
        if record["metres"] > best:
            best, name = record["metres"], record["trip"]
    return name


def total_fares(lines: list[str]) -> int:
    return sum(json.loads(line)["fare"] for line in lines)


def crowded_trips(lines: list[str]) -> int:
    return sum(1 for line in lines if json.loads(line)["riders"] >= 4)


def night_trips(lines: list[str]) -> int:
    count = 0
    for line in lines:
        hour = json.loads(line)["hour"]
        if hour >= 22 or hour < 5:
            count += 1
    return count


def short_hop_fares(lines: list[str]) -> int:
    total = 0
    for line in lines:
        record = json.loads(line)
        if record["metres"] < 1000:
            total += record["fare"]
    return total


def summarise(lines: list[str]) -> dict[str, str]:
    """Every figure of the summary, formatted, in report order."""
    metres = total_metres(lines)
    summary = {"distance km": f"{metres / 1000:.3f}"}
    for region, cents in fares_by_region(lines).items():
        summary[f"fare {region}"] = f"{cents / 100:.2f}"
    summary["busiest mode"] = busiest_mode(lines)
    summary["longest trip"] = longest_trip(lines)
    summary["fare per km"] = f"{total_fares(lines) * 10 / metres:.4f}"
    summary["crowded share"] = f"{crowded_trips(lines) / len(lines):.3f}"
    summary["night trips"] = str(night_trips(lines))
    summary["short-hop fares"] = f"{short_hop_fares(lines) / 100:.2f}"
    return summary
