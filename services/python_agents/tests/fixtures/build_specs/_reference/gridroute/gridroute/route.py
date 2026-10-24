import heapq

DIGITS = frozenset("123456789")


def parse_grid(text: str) -> list:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise ValueError("empty input")
    head = lines[0].split(" ")
    if len(head) != 2 or not all(part.isdigit() for part in head):
        raise ValueError("the first line is W H")
    width, height = int(head[0]), int(head[1])
    if not (1 <= width <= 2000 and 1 <= height <= 2000):
        raise ValueError("W and H are from 1 to 2000")
    rows = lines[1:]
    if len(rows) != height:
        raise ValueError("wrong number of rows")
    grid = []
    for row in rows:
        if len(row) != width or not set(row) <= DIGITS:
            raise ValueError("a row is W digits 1-9")
        grid.append([int(c) for c in row])
    return grid


def shortest_costs(grid: list) -> list:
    height, width = len(grid), len(grid[0])
    best = [[None] * width for _ in range(height)]
    heap = [(0, 0, 0)]
    while heap:
        cost, y, x = heapq.heappop(heap)
        if best[y][x] is not None:
            continue
        best[y][x] = cost
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and best[ny][nx] is None:
                heapq.heappush(heap, (cost + grid[ny][nx], ny, nx))
    return best


def render(text: str) -> str:
    grid = parse_grid(text)
    costs = shortest_costs(grid)
    height, width = len(grid), len(grid[0])
    lines = [f"size={width}x{height}"]
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        lines.append(f"corner {x},{y} = {costs[y][x]}")
    cx, cy = width // 2, height // 2
    lines.append(f"centre {cx},{cy} = {costs[cy][cx]}")
    lines.append(f"total={sum(map(sum, costs))}")
    lines.append(f"max={max(map(max, costs))}")
    return "\n".join(lines) + "\n"
