# gridroute: shortest path costs on a grid

Build a small command-line tool that reads a grid of cell costs and prints
the cheapest cost of reaching cells from the top-left corner.

## Package and public API

- Package name: `gridroute`.
- `gridroute.parse_grid(text: str) -> list[list[int]]` reads the grid
  format below and returns its rows (row 0 first); malformed input raises
  `ValueError`.
- `gridroute.shortest_costs(grid: list[list[int]]) -> list[list[int]]`
  returns, for every cell, the cheapest cost of a path from the top-left
  cell (row 0, column 0) to it, in the same shape as `grid`.
- `gridroute.render(text: str) -> str` returns the report (the format is
  below).
- `python -m gridroute FILE` reads FILE as UTF-8 and prints `render(text)`
  to standard output with nothing before or after it (the report already
  ends with a newline, so print it with `end=""`).

## Grid format

The first line is `W H` (the width and the height, whole numbers from 1 to
2000, separated by one space). Then exactly H lines of exactly W digits
`1`-`9` each, the cost of each cell. A final newline is optional; any other
shape (a wrong count, another character, an empty grid) raises
`ValueError`.

## Costs

A path moves between cells that share an edge (up, down, left, right). Its
cost is the sum of the costs of every cell it enters; the cost of the start
cell is not counted, so the top-left cell's own result is 0.

## Output

```
size=<W>x<H>
corner 0,0 = <cost>
corner <W-1>,0 = <cost>
corner 0,<H-1> = <cost>
corner <W-1>,<H-1> = <cost>
centre <W//2>,<H//2> = <cost>
total=<sum of the costs of every cell>
max=<the largest cost of any cell>
```

Coordinates are written `x,y`: x is the column, y the row. Every line ends
with `\n`.

Example: for the text `"3 2\n131\n112\n"` (row 0 is `1 3 1`, row 1 is
`1 1 2`) the costs are `[[0, 3, 4], [1, 2, 4]]` and the report is

```
size=3x2
corner 0,0 = 0
corner 2,0 = 4
corner 0,1 = 1
corner 2,1 = 4
centre 1,1 = 2
total=14
max=4
```

## Benchmark size

The benchmark generates a 600 x 600 grid with seed 5 (each cell a uniform
random digit 1-9), calls `render` once on its text and prints the report. A
straightforward implementation (Dijkstra's algorithm with a binary heap)
runs in about 1 to 3 seconds.
