"""Grammar-based SQL generator with rare tokens, for the sqlparse audit.

Statements: select (joins, subqueries, CASE, window, CTE, set ops), insert,
update, delete, create table/function/procedure (with $$ bodies and
BEGIN...END), alter, drop, transaction control, DECLARE/IF blocks.
Rare tokens: --, #, /* */ and nested and hint comments, '' and backslash
escapes, E'' N'' X'' b'' strings, $$ and $tag$ dollar quotes, "q" `q` [q]
identifiers, keywords used as identifiers, odd whitespace (\\t \\r \\r\\n \\x0b
\\x0c NBSP em-space zero-width), unicode identifiers, placeholders (? %s
%(n)s :n $1 @v), casts (::), JSON operators, numbers in every shape, and a
byte-level mutator.
"""

import random

TABLES = ["orders", "customers", "items", "t", "T1", '"Order"', "`user`", "[group]",
          "public.orders", "db.sch.tbl", "é_tbl", "表", '"a""b"', "order", "user",
          "date", "select_", "_x", "x1$"]
COLUMNS = ["id", "amount", "status", "created_at", "region", "total", "Name",
           '"Col"', "`c`", "[c]", "date", "type", "value", "end", "begin", "key",
           "level", "row", "user", "*", "é", "a.b", "t.*", "count", "left", "right",
           "default", "if", "case", "table"]
KW_CASE = [str.lower, str.upper, str.title, lambda s: s[:1].upper() + s[1:].lower(),
           lambda s: "".join(c.upper() if i % 2 else c for i, c in enumerate(s))]
NUMS = ["0", "1", "42", "-7", "1.5", ".5", "5.", "1e10", "1E-3", "2.5e+3", "0x1F",
        "0b101", "1_000", "99999999999999999999", "00012", "+3", "1.2.3"]
STRS = ["'open'", "'it''s'", "'a\\'b'", "''", "'%'", "'_'", "E'\\n'", "N'ünï'",
        "X'0F'", "b'01'", "'2026-01-01'", "'multi\nline'", "'semi;colon'",
        "'--not comment'", "'/*no*/'", "'\"'", "$$dollar$$", "$tag$body;$tag$",
        "$$ nested $x$ $$", "'é中'", "'\U0001F600'", "U&'d\\0061t'", "'\\\\'",
        "'unterminated"]
PLACE = ["?", "%s", "%(name)s", ":name", ":1", "$1", "@var", "@@version", "{x}"]
OPS = ["=", "<>", "!=", "<", ">", "<=", ">=", "<=>", "||", "+", "-", "*", "/", "%",
       "::", "->", "->>", "@>", "<@", "~", "!~*", "LIKE", "ILIKE", "IS", "IS NOT",
       "IN", "NOT IN", "BETWEEN", "&", "|", "^", "#>", "?|", "=="]
WS = [" ", " ", " ", "  ", "\t", "\n", "\r\n", "\r", "\x0b", "\x0c", " ",
      " ", "​", " \n ", "\n\n"]
COMMENTS = ["-- c\n", "--\n", "# hash\n", "/* c */", "/**/", "/* a /* nested */ b */",
            "/*+ INDEX(t) */", "/* multi\nline */", "-- é\r\n", "--no-newline",
            "/* unterminated", "/* ; */", "-- ;\n"]
FUNCS = ["count(*)", "sum(amount)", "avg(total)", "coalesce(a, b)", "max(x)",
         "cast(x as int)", "now()", "lower(name)", "substring(s from 1 for 2)",
         "extract(year from d)", "row_number() over (partition by region order by id)",
         "sum(x) filter (where y > 0)", "array_agg(distinct id)", "f()", "date(d)",
         "if(a, b, c)", "replace(s, ';', ',')"]


def kw(rng, s):
    return rng.choice(KW_CASE)(s)


def ws(rng):
    r = rng.random()
    if r < 0.85:
        return " "
    if r < 0.95:
        return rng.choice(WS)
    return " " + rng.choice(COMMENTS) + " "


def ident(rng):
    return rng.choice(COLUMNS) if rng.random() < 0.7 else rng.choice(TABLES) + "." + rng.choice(COLUMNS)


def atom(rng, depth):
    r = rng.random()
    if r < 0.35:
        return ident(rng)
    if r < 0.5:
        return rng.choice(NUMS)
    if r < 0.65:
        return rng.choice(STRS)
    if r < 0.72:
        return rng.choice(PLACE)
    if r < 0.82:
        return rng.choice(FUNCS)
    if r < 0.88 and depth < 2:
        return "(" + select(rng, depth + 1) + ")"
    if r < 0.94 and depth < 3:
        return (f"{kw(rng, 'case')} {kw(rng, 'when')} {expr(rng, depth + 1)} {kw(rng, 'then')} "
                f"{atom(rng, depth + 1)} {kw(rng, 'else')} {atom(rng, depth + 1)} {kw(rng, 'end')}")
    return rng.choice(["NULL", "true", "FALSE", "DEFAULT", "CURRENT_TIMESTAMP", "*"])


def expr(rng, depth=0):
    e = atom(rng, depth)
    for _ in range(rng.choice([0, 1, 1, 2])):
        op = rng.choice(OPS)
        rhs = atom(rng, depth)
        if op in ("IN", "NOT IN"):
            rhs = "(" + ", ".join(atom(rng, depth + 1) for _ in range(rng.randint(1, 3))) + ")"
        elif op == "BETWEEN":
            rhs = f"{atom(rng, depth)} {kw(rng, 'and')} {atom(rng, depth)}"
        e = e + ws(rng) + kw(rng, op) + ws(rng) + rhs
        if rng.random() < 0.3:
            e = e + ws(rng) + kw(rng, rng.choice(["and", "or"])) + ws(rng) + atom(rng, depth)
    if rng.random() < 0.1:
        e = "(" + e + ")"
    return e


def select(rng, depth=0):
    cols = []
    for _ in range(rng.randint(1, 4)):
        c = expr(rng, depth)
        r = rng.random()
        if r < 0.25:
            c += f" {kw(rng, 'as')} {rng.choice(COLUMNS)}"
        elif r < 0.35:
            c += " " + rng.choice(["n", '"Alias"', "`a`", "x1"])
        cols.append(c)
    s = kw(rng, "select") + ws(rng) + rng.choice(["", "", kw(rng, "distinct") + " ", "top 5 "]) + \
        ("," + ws(rng)).join(cols)
    if rng.random() < 0.9:
        s += ws(rng) + kw(rng, "from") + ws(rng) + rng.choice(TABLES) + rng.choice(["", " a", " as t2", ""])
        for _ in range(rng.choice([0, 0, 1, 2])):
            j = rng.choice(["join", "left join", "left outer join", "inner join", "cross join",
                            "full outer join", "natural join", "straight_join", ","])
            s += ws(rng) + kw(rng, j) + ws(rng) + rng.choice(TABLES)
            if j not in (",", "cross join", "natural join"):
                s += ws(rng) + kw(rng, rng.choice(["on", "using"])) + ws(rng) + (
                    expr(rng, depth + 1) if rng.random() < 0.8 else "(id)")
    if rng.random() < 0.6:
        s += ws(rng) + kw(rng, "where") + ws(rng) + expr(rng, depth)
    if rng.random() < 0.3:
        s += ws(rng) + kw(rng, "group by") + ws(rng) + ", ".join(ident(rng) for _ in range(rng.randint(1, 3)))
        if rng.random() < 0.5:
            s += ws(rng) + kw(rng, "having") + ws(rng) + expr(rng, depth)
    if rng.random() < 0.3:
        s += ws(rng) + kw(rng, "order by") + ws(rng) + ident(rng) + rng.choice(["", " desc", " ASC", " nulls last"])
    if rng.random() < 0.2:
        s += ws(rng) + kw(rng, "limit") + ws(rng) + rng.choice(NUMS + PLACE)
        if rng.random() < 0.3:
            s += ws(rng) + kw(rng, "offset") + " 10"
    if depth == 0 and rng.random() < 0.08:
        s += ws(rng) + kw(rng, rng.choice(["union", "union all", "except", "intersect"])) + ws(rng) + select(rng, 1)
    if depth == 0 and rng.random() < 0.08:
        s = f"{kw(rng, 'with')} cte {kw(rng, 'as')} ({select(rng, 1)}) " + s
    return s


def insert(rng):
    cols = ", ".join(rng.choice(COLUMNS) for _ in range(rng.randint(1, 3)))
    rows = ", ".join("(" + ", ".join(atom(rng, 2) for _ in range(rng.randint(1, 3))) + ")"
                     for _ in range(rng.randint(1, 4)))
    s = f"{kw(rng, 'insert into')} {rng.choice(TABLES)} ({cols}) {kw(rng, 'values')} {rows}"
    if rng.random() < 0.15:
        s += f" {kw(rng, 'on conflict')} (id) {kw(rng, 'do update set')} amount = excluded.amount"
    if rng.random() < 0.1:
        s += f" {kw(rng, 'returning')} id"
    return s


def update(rng):
    sets = ", ".join(f"{rng.choice(COLUMNS)} = {expr(rng, 1)}" for _ in range(rng.randint(1, 3)))
    return f"{kw(rng, 'update')} {rng.choice(TABLES)} {kw(rng, 'set')} {sets} {kw(rng, 'where')} {expr(rng)}"


def delete(rng):
    return f"{kw(rng, 'delete from')} {rng.choice(TABLES)}" + (f" {kw(rng, 'where')} {expr(rng)}" if rng.random() < 0.8 else "")


def ddl(rng):
    r = rng.random()
    if r < 0.35:
        cols = ", ".join(f"{rng.choice(COLUMNS)} {rng.choice(['int', 'varchar(20)', 'TEXT', 'numeric(10, 2)', 'timestamp with time zone', 'serial primary key', 'int not null default 0'])}"
                         for _ in range(rng.randint(1, 4)))
        return f"{kw(rng, 'create table')} {rng.choice(['', 'if not exists '])}{rng.choice(TABLES)} ({cols})"
    if r < 0.55:
        body = rng.choice(["$$ select 1; $$", "$body$ begin return 1; end; $body$", "$$ begin; end $$",
                           "'select 1'", "$f$ declare x int; begin x := 1; if x > 0 then return x; end if; end $f$"])
        return (f"{kw(rng, 'create or replace function')} f(a int) {kw(rng, 'returns')} int "
                f"{kw(rng, 'as')} {body} {kw(rng, 'language')} plpgsql")
    if r < 0.7:
        return (f"{kw(rng, 'create procedure')} p() {kw(rng, 'begin')} {select(rng, 1)}; "
                f"{update(rng)}; {kw(rng, 'end')}")
    if r < 0.8:
        return f"{kw(rng, 'alter table')} {rng.choice(TABLES)} {kw(rng, rng.choice(['add column', 'drop column', 'rename to']))} {rng.choice(COLUMNS)}"
    if r < 0.9:
        return kw(rng, rng.choice(["begin", "commit", "rollback", "begin transaction", "start transaction",
                                   "drop table x", "truncate t", "vacuum", "explain " + "select 1", "go", "use db"]))
    return (f"{kw(rng, 'declare')} @x int; {kw(rng, 'if')} @x > 1 {kw(rng, 'begin')} "
            f"{select(rng, 1)} {kw(rng, 'end')}")


def statement(rng):
    r = rng.random()
    if r < 0.5:
        return select(rng)
    if r < 0.65:
        return insert(rng)
    if r < 0.75:
        return update(rng)
    if r < 0.8:
        return delete(rng)
    return ddl(rng)


RARE = ["'", '"', "`", "$", "$$", ";", "--", "/*", "*/", "#", "\\", "\n", "\r", "\t",
        "(", ")", ",", ".", ":", "::", " ", "​", "é", "[", "]", "%", "@", "?", "\x00"]


def mutate(rng, s):
    s = list(s)
    for _ in range(rng.randint(1, 3)):
        if not s:
            s.append(rng.choice(RARE))
            continue
        i = rng.randrange(len(s))
        op = rng.random()
        if op < 0.45:
            s[i:i] = list(rng.choice(RARE))
        elif op < 0.75:
            del s[i]
        else:
            j = min(len(s), i + rng.randint(1, 10))
            s[i:i] = s[i:j]
    return "".join(s)


def gen(rng):
    n = rng.choice([1, 1, 1, 2, 3])
    parts = []
    for _ in range(n):
        st = statement(rng)
        if rng.random() < 0.15:
            st = rng.choice(COMMENTS) + st
        parts.append(st)
    sep = rng.choice([";\n", ";", "; ", ";\r\n", ";\n\n", " ;", ";;\n", ";\n-- trailing\n", "\n/\n", "\ngo\n"])
    s = sep.join(parts) + rng.choice(["", ";", ";\n", " ", "\n", "  -- end", ";;"])
    if rng.random() < 0.05:
        s = s.upper()
    if rng.random() < 0.25:
        s = mutate(rng, s)
    return s


def mode(rng):
    return "all"


if __name__ == "__main__":
    rng = random.Random(1)
    for _ in range(6):
        print(repr(gen(rng)))
