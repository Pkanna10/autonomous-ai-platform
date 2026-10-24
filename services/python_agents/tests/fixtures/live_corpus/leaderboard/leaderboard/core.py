"""The board: every result ever posted, best first."""


def replay(results: list[tuple[str, int]]) -> tuple[list[str], list[tuple[str, int]]]:
    """The leader after each result, and the final top three.

    The board ranks results by points, highest first; equal points rank by
    player name.
    """
    board: list[tuple[int, str]] = []
    leaders: list[str] = []
    for player, points in results:
        board.append((-points, player))
        board.sort()
        leaders.append(board[0][1])
    top = [(player, -negative) for negative, player in sorted(board)[:3]]
    return leaders, top
