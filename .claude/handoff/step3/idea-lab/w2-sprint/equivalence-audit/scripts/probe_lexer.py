"""Targeted probe: sqlparse's documented lexer configuration (docs/source/extending.rst).

python3 -I probe_lexer.py AUDIT_DIR            (driver: all sqlparse diffs)
python3 -I -B probe_lexer.py --child COPY_DIR  (one copy, prints a dump)

The child warms the lexer on the docs' statement, applies the docs' example
(clear, set_SQL_REGEX with ZORDER BY, add_keywords incl. BAR), lexes the same
statement again, then add_keywords on a warm lexer, then
default_initialization() and lexes again. A text-keyed token cache or a
dispatch table built once from SQL_REGEX would return stale tokens here.
Each child runs under `unshare -rn` with a 120 s timeout.
"""
import json
import os
import subprocess
import sys


def child(copy):
    sys.path.insert(0, copy)
    import sqlparse
    from sqlparse import keywords, tokens
    from sqlparse.lexer import Lexer

    q = "select * from foo zorder by bar;"
    q2 = "select qux from t;"

    def dump(s):
        return [(repr(t.ttype), t.value) for t in sqlparse.parse(s)[0].flatten()]

    out = {"warm": dump(q), "warm2": dump(q2)}
    lex = Lexer.get_default_instance()
    lex.clear()
    lex.set_SQL_REGEX(keywords.SQL_REGEX[:38] + [(r"ZORDER\s+BY\b", tokens.Keyword)] + keywords.SQL_REGEX[38:])
    for k in (keywords.KEYWORDS_COMMON, keywords.KEYWORDS_ORACLE, keywords.KEYWORDS_PLPGSQL,
              keywords.KEYWORDS_HQL, keywords.KEYWORDS_MSACCESS, keywords.KEYWORDS):
        lex.add_keywords(k)
    lex.add_keywords({"BAR": tokens.Keyword})
    out["configured"] = dump(q)
    lex.add_keywords({"QUX": tokens.Keyword})
    out["added_warm"] = dump(q2)
    lex.default_initialization()
    out["restored"] = dump(q)
    print(json.dumps(out))


def driver(a):
    here = os.path.abspath(__file__)
    diffs = [u for u in json.load(open(os.path.join(a, "out/diffs.json"))) if u["lib"] == "sqlparse"]

    def run(copy):
        p = subprocess.run(["unshare", "-rn", "--", "python3", "-I", "-B", here, "--child", copy],
                           capture_output=True, text=True, timeout=120)
        return p.stdout.strip() if p.returncode == 0 else "ERR " + p.stderr[-200:]

    base = run(os.path.join(a, "work", "sqlparse", "base"))
    res = {}
    for u in diffs:
        r = run(u["dir"])
        if r != base:
            b, p = json.loads(base), (json.loads(r) if not r.startswith("ERR") else {})
            res[u["sha"][:12]] = {k: {"base": b[k], "patched": p.get(k)} for k in b if p.get(k) != b[k]}
    json.dump({"base": json.loads(base), "differs": res}, open(os.path.join(a, "out/probe-lexer.json"), "w"), indent=1)
    print("sqlparse diffs probed", len(diffs), "differ", len(res), sorted(res))


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        child(sys.argv[2])
    else:
        driver(sys.argv[1])
