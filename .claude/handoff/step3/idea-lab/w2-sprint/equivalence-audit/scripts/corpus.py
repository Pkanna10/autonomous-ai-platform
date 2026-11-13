"""Build the fixed fuzz corpus of one library.

python3 -I corpus.py LIB N SEED OUT_JSON   -> [[mode, text], ...]
Modes: tomli plain 75 % / parse_float=Decimal 25 %; sqlparse one mode
(format with the workload's options, parse, split); mistune workload config
70 % / mistune.html 15 % / escape+hard_wrap+harmful-protocols renderer 15 %;
markdown workload extensions 55 % / none 15 % / wide extension set 15 % /
one reused Markdown instance with reset() 15 %.
"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_md, gen_sql, gen_tomli  # noqa: E402

lib, n, seed, out = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
rng = random.Random(seed)
corpus = []
for _ in range(n):
    if lib == "tomli":
        corpus.append([gen_tomli.mode(rng), gen_tomli.gen(rng)])
    elif lib == "sqlparse":
        corpus.append(["all", gen_sql.gen(rng)])
    elif lib == "mistune":
        r = rng.random()
        corpus.append(["wl" if r < 0.7 else "html" if r < 0.85 else "esc", gen_md.gen(rng)])
    else:
        r = rng.random()
        corpus.append(["wl" if r < 0.55 else "none" if r < 0.7 else "wide" if r < 0.85 else "reuse", gen_md.gen(rng)])
json.dump(corpus, open(out, "w"))
print(lib, n, seed, sum(len(t) for _, t in corpus) / n)
