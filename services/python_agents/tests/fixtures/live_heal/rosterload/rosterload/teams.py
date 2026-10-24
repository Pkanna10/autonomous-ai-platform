"""Group roster names into teams of a fixed size."""


def split_teams(names, size):
    """``names`` in teams of ``size``, sorted by name; the last team may be short."""
    if size < 1:
        raise ValueError("a team has at least one member")
    ordered = sorted(names, key=str.casefold)
    teams = []
    for start in range(0, len(ordered), size):
        teams.append(ordered[start : start + size])
    return teams
