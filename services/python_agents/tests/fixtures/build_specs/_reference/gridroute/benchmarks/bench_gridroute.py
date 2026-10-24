from generate import make_grid
from gridroute import render

SEED = 5
SIZE = 600

print(render(make_grid(SEED, SIZE, SIZE)), end="")
