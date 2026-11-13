"""TOML input generator for the differential audit.

Part 1 is s3-equivalence's grammar fuzzer (r3/work/s3-equivalence/difffuzz.py:
INTS, STR_BODIES, WS, elem, array, doc), copied verbatim, because its module
loads two tomli copies at import time and cannot be imported.
Part 2 widens it to whole documents (headers, dotted/quoted keys, every value
kind, datetimes, multi-line strings, CRLF, comments, redefinitions), since the
keeps also touch key_value_rule, parse_key, parse_value and the loads loop.
Part 3 is a byte-level mutator applied to a share of the documents.
"""

import random

# ---- Part 1: s3-equivalence's generator (verbatim) ----
INTS = ["0", "-0", "+0", "7", "-12", "+3", "1_000", "007", "0x1F", "0o7",
        "0b1", "123456789012345678901234567890", "1e3", "1.5", "inf", "nan",
        "-", "+", "1979-05-27", "00", "01"]
STR_BODIES = ["", "a", "a b", "it's", 'say "hi"', "tab\there", "é", "\U0001F600",
              "\\n", "\\u00e9", "\\", "\x7f", "\x00", "\x1f", "\x0b", "\x0c",
              "comma, inside", "]", "[", "#", " ", " ", "\ud800"]
WS = ["", " ", "  ", "\t", "\n", "\n  ", "\r\n", "\r", "\x0c", " ", "\x0b"]


def elem(rng, kind):
    if kind == "int":
        return rng.choice(INTS)
    body = rng.choice(STR_BODIES)
    q = rng.choice(['"', "'", '"""', "'''"])
    return f"{q}{body}{q}"


def array(rng, depth=0):
    kind = rng.choice(["int", "str", "mixed"])
    n = rng.choice([0, 1, 2, 3, 5])
    parts = []
    for _ in range(n):
        r = rng.random()
        if depth < 2 and r < 0.08:
            parts.append(array(rng, depth + 1))
        elif r < 0.12:
            parts.append("{ k = 1 }")
        else:
            k = kind if kind != "mixed" else rng.choice(["int", "str"])
            parts.append(elem(rng, k))
    out = "["
    for i, p in enumerate(parts):
        out += rng.choice(WS) + p + rng.choice(WS)
        if i < len(parts) - 1:
            out += rng.choice([",", ",", ",", ",,", ""])
            if rng.random() < 0.05:
                out += " # c\n"
    if parts and rng.random() < 0.3:
        out += "," + rng.choice(WS)
    out += rng.choice(WS) + rng.choice(["]", "]", "]", ""])
    return out


def s3_doc(rng):
    a = array(rng)
    ctx = rng.choice(["a = {}", "t = {{ x = {} }}", "a = [{}]", "[s]\na = {}\nb = 1"])
    return ctx.format(a) + rng.choice(["", "\n", " # end\n", " x\n"])


# ---- Part 2: whole-document grammar ----
# Each choice draws from a valid list, and from an invalid list with
# probability NOISE (0 for half of the documents), so a large share of the
# documents is valid TOML and still reaches the value and table code.
NOISE = [0.0]


def pick(rng, good, bad=()):
    if bad and rng.random() < NOISE[0]:
        return rng.choice(bad)
    return rng.choice(good)


BARE = ["a", "b", "key", "port", "name", "x-y", "x_y", "1", "123", "_", "-",
        "true", "inf", "nan", "A", "Ab", "k1", "server_1", "0x1", "a1-b2_c3"]
BARE_BAD = ["é", "a b", "a=b", "", "$"]
QKEYS = ['"a"', '""', '"a.b"', '"é"', r'"\u00e9"', "'lit'", "''", '"a b"',
         r'"\n"', r'"\""', r"'a\b'", '"key"', r'"\U0001F600"', '"[x]"']
QKEYS_BAD = [r'"\x"', "'a'b'", '"\n"', '"a']
FLOATS = ["1.0", "-0.0", "+1.5", "3.14e2", "1e-3", "1E+3", "6.626e-34", "inf",
          "-inf", "+nan", "nan", "0.0e0", "9_9.9_9", "1e1_0", "1_0.0", "224_617.445_991",
          "0.1", "1e06", "-1E-2"]
FLOATS_BAD = ["1.", ".5", "1._0", "1.2.3", "01.5", "1e", "1e_1", "Inf", "NaN", "+-1.0"]
INTS2 = ["0", "-0", "+0", "7", "-12", "+3", "1_000", "0x1F", "0o7", "0b1",
         "123456789012345678901234567890", "0xDEAD_beef", "0xdead", "0o755",
         "0b1010_1010", "99999999999999999999", "0x00ff", "5_349_221", "-9223372036854775808"]
INTS_BAD = ["007", "00", "01", "-", "+", "0x", "0o8", "0b2", "1__0", "_1", "1_",
            "+0x1", "0X1F", "-0x1", "0x_1", "1 2"]
DATES = ["1979-05-27T07:32:00Z", "1979-05-27T00:32:00-07:00",
         "1979-05-27T00:32:00.999999-07:00", "1979-05-27 07:32:00Z",
         "1979-05-27t07:32:00z", "1979-05-27T07:32:00", "1979-05-27",
         "07:32:00", "00:32:00.999999", "00:32:00.1234567", "2026-01-01T10:00:00.5Z",
         "2000-02-29", "1979-05-27T07:32:00+14:00", "23:59:59"]
DATES_BAD = ["1979-13-27", "1979-02-30", "24:00:00", "1979-05-27T07:32:00+25:00",
             "1979-05-27T07:32", "1979-05-27T07:32:60", "1979-5-27", "07:32", "1979-05-27T"]
# Bodies of "..." strings (already escaped TOML text).
BASIC = ["", "a", "a b", "it's", "tab\there", "é", "\U0001F600", r"\n", r"\u00e9",
         r"\\", "comma, inside", "]", "[", "#", " ", "=", "a#b",
         r'\t\u00e9\"q\"', r"\U0001F600", r"\b\f\r", "\u2028", r"\e", "x\u007fno"[0:1]]
BASIC_BAD = ['say "hi"', "\x7f", "\x00", "\x1f", r"\x41", r"\uD800", r"\U00110000",
             "\\", "line\nbreak", r"\/", "\ud800", r"\u12"]
LITERAL = ["", "a", 'say "hi"', r"C:\path", r"\n stays", "é", "#", "]", "tab\tok"]
LITERAL_BAD = ["it's", "\x00", "line\nbreak", "\x7f"]
MULTI = ["\n", "\r\n", "", "\nline one\nline two \\\n  continued\n", "a\n\nb",
         '"quoted" inside', "\\\n   \\\n", "x\t\ty", 'ends with quote"']
MULTI_BAD = ['""""', "\x00", "\\ x", "\\ \nx"]
MLIT = ["\n", "\r\n", "", "it's", "a\n'b'", r"C:\no\escapes", "x"]
MLIT_BAD = ["''''", "\x00"]
NL = ["\n", "\n", "\n", "\r\n", "\n\n", " \n", "\t\n", " # c\n", " #\tc é\n"]
NL_BAD = ["\r", "#\x01\n", " # \x7f\n", "\x0c\n"]


def key(rng):
    parts = []
    for _ in range(rng.choice([1, 1, 1, 2, 3])):
        parts.append(pick(rng, BARE, BARE_BAD) if rng.random() < 0.8 else pick(rng, QKEYS, QKEYS_BAD))
    return pick(rng, [".", ".", " . ", ". ", "\t.\t"], [".."]).join(parts)


def string(rng):
    r = rng.random()
    if r < 0.5:
        return '"' + pick(rng, BASIC, BASIC_BAD) + '"'
    if r < 0.7:
        return "'" + pick(rng, LITERAL, LITERAL_BAD) + "'"
    if r < 0.9:
        return '"""' + pick(rng, MULTI + BASIC, MULTI_BAD) + '"""'
    return "'''" + pick(rng, MLIT, MLIT_BAD) + "'''"


def value(rng, depth=0):
    r = rng.random()
    if r < 0.18:
        return pick(rng, INTS2, INTS_BAD)
    if r < 0.28:
        return pick(rng, FLOATS, FLOATS_BAD)
    if r < 0.33:
        return pick(rng, ["true", "false"], ["True", "tru", "falsey"])
    if r < 0.43:
        return pick(rng, DATES, DATES_BAD)
    if r < 0.63:
        return string(rng)
    if r < 0.80 and depth < 3:
        if NOISE[0] and rng.random() < 0.2:
            return array(rng)  # s3's generator: rare tokens, often invalid
        n = rng.choice([0, 1, 2, 3, 6, 12])
        if rng.random() < 0.5:  # flat homogeneous arrays: the fast-path keeps' target
            g = rng.choice([lambda: pick(rng, INTS2, INTS_BAD), lambda: string(rng),
                            lambda: pick(rng, FLOATS, FLOATS_BAD)])
            items = [g() for _ in range(n)]
        else:
            items = [value(rng, depth + 1) for _ in range(n)]
        sep = pick(rng, [", ", ",", " ,", ",\n", ", # c\n", ",\r\n", ",\t", " , "], [",,", " "])
        tail = pick(rng, ["", "", ",", ",\n", "\n"], [",,"])
        return "[" + rng.choice(["", " ", "\n", "\t"]) + sep.join(items) + tail + pick(rng, ["]"], [""])
    if depth < 3:
        n = rng.choice([0, 1, 2, 3])
        items = [f"{key(rng)} = {value(rng, depth + 1)}" for _ in range(n)]
        sep = pick(rng, [", ", ",", " , "], [",\n", ",,"])
        return "{" + rng.choice(["", " "]) + sep.join(items) + pick(rng, ["", " "], [","]) + "}"
    return pick(rng, INTS2, INTS_BAD)


def header(rng):
    k = key(rng)
    if rng.random() < 0.3:
        return pick(rng, [f"[[{k}]]", f"[[ {k} ]]"], [f"[[{k}]", f"[ [{k}]]"])
    return pick(rng, [f"[{k}]", f"[ {k} ]", f"[{k}] # h", f"[\t{k}\t]"], [f"[{k}]x", f"[{k}"])


def kv(rng):
    eq = pick(rng, [" = ", "=", " =", "= ", "\t=\t", "  =  "], [" == ", " : ", " "])
    return rng.choice(["", "", "", " ", "\t"]) + key(rng) + eq + value(rng)


def full_doc(rng):
    NOISE[0] = 0.0 if rng.random() < 0.5 else 0.03
    lines = []
    tables = [rng.choice(BARE) for _ in range(rng.randint(1, 4))]
    for _ in range(rng.randint(1, 14)):
        r = rng.random()
        if r < 0.18:
            lines.append(header(rng))
        elif r < 0.30:
            t = rng.choice(tables)  # repeated headers, the memo keeps' target
            lines.append(rng.choice([f"[{t}]", f"[[{t}]]", f"[{t}.sub]",
                                     f"[{t}.{rng.choice(BARE)}]", f"[[{t}.arr]]"]))
        elif r < 0.35:
            lines.append(rng.choice(["# comment", "", "   ", "#", "# é ü", "#\t", "\t# x"]))
        else:
            lines.append(kv(rng))
    out = ""
    for ln in lines:
        out += ln + pick(rng, NL, NL_BAD)
    if rng.random() < 0.2:
        out = out.rstrip("\n")
    return out


def workload_like(rng):
    """A few tables shaped like the frozen workload, with perturbed fields."""
    NOISE[0] = 0.0 if rng.random() < 0.5 else 0.05
    out = []
    for i in range(rng.randint(1, 3)):
        out.append(f"[server_{i}]")
        out.append(f'name = "host-{i}\\t\\u00e9\\"quoted\\""')
        out.append(f"port = {pick(rng, INTS2, INTS_BAD)}")
        out.append(f"mask = {pick(rng, ['0x00ff', '0xFFFF', '0xabcd'], ['0x', '0x_1'])}")
        out.append(f"samples = [{', '.join(pick(rng, INTS2, INTS_BAD) for _ in range(rng.randint(0, 12)))}]")
        out.append(f"tags = [{', '.join(string(rng) for _ in range(rng.randint(0, 4)))}]")
        out.append(f"owner = {{ name = {string(rng)}, level = {pick(rng, INTS2, INTS_BAD)}, active = true }}")
        out.append(f"since = {pick(rng, DATES, DATES_BAD)}")
        out.append('notes = """\nline one\nline two \\\n  continued\n"""')
        out.append(f"[[server_{i}.disk]]")
        out.append(f"{key(rng)} = {value(rng)}")
    return rng.choice(["\n", "\r\n"]).join(out) + "\n"


RARE = ["\r", "\x00", "\x7f", "\x0b", "﻿", " ", "\\", '"', "'", "#",
        "=", "[", "]", "{", "}", ",", ".", "_", "\n", "\t", " ", "0", "e", "T", "Z", ":"]


def mutate(rng, s):
    s = list(s)
    for _ in range(rng.randint(1, 3)):
        if not s:
            s.append(rng.choice(RARE))
            continue
        i = rng.randrange(len(s))
        op = rng.random()
        if op < 0.4:
            s.insert(i, rng.choice(RARE))
        elif op < 0.7:
            del s[i]
        elif op < 0.85:
            s[i] = rng.choice(RARE)
        else:
            j = min(len(s), i + rng.randint(1, 8))
            s[i:i] = s[i:j]
    return "".join(s)


def gen(rng):
    r = rng.random()
    if r < 0.20:
        s = s3_doc(rng)
    elif r < 0.80:
        s = full_doc(rng)
    else:
        s = workload_like(rng)
    if rng.random() < 0.15:
        s = mutate(rng, s)
    return s


def mode(rng):
    """loads() 75 %, loads(parse_float=Decimal) 25 %."""
    return "decimal" if rng.random() < 0.25 else "plain"


if __name__ == "__main__":
    rng = random.Random(1)
    for _ in range(5):
        print(repr(gen(rng)))
