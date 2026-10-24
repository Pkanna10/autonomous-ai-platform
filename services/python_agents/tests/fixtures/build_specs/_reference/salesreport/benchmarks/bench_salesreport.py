from generate import make_csv

from salesreport import build_report

SEED = 7
ROWS = 200_000

print(build_report(make_csv(SEED, ROWS)), end="")
