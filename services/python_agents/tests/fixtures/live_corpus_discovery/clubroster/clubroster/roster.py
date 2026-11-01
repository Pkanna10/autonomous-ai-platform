"""The ranked, paged roster."""

from clubroster.data import Member


def standing_key(member: Member) -> tuple[int, str, str, int]:
    """Points, highest first, then surname and given name ignoring case,
    then membership number."""
    return (
        -member.points,
        member.surname.casefold(),
        member.given.casefold(),
        member.number,
    )


def page(crowd: list[Member], number: int, size: int) -> list[Member]:
    """Page ``number`` (from 0) of the ranked roster, ``size`` members a page."""
    start = number * size
    return sorted(crowd, key=standing_key)[start : start + size]


def pages(crowd: list[Member], size: int) -> list[list[Member]]:
    """Every page of the ranked roster, in order."""
    return [page(crowd, number, size) for number in range(-(-len(crowd) // size))]


def format_line(place: int, member: Member) -> str:
    name = f"{member.surname}, {member.given}"
    return f"{place:>4}  {name:<22}{member.team:<8}{member.points:>6} pts  #{member.number:05d}"
