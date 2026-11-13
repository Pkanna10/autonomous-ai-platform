"""Evaluate one library copy on a corpus at its public API (run in a subprocess).

python3 -I -B runner.py LIB COPY_DIR batch CORPUS_JSON OUT_JSON
python3 -I -B runner.py LIB COPY_DIR serve            (JSON lines on stdin/stdout)

The result of one input is a type-aware string: repr() of the value plus a
tree of exact type names (tomli), a structural dump of the token tree with
class names and ttypes (sqlparse), repr((type name, html)) (mistune,
markdown). An exception is reduced to its module-qualified type name only, so
matching exception types count as the same. A 5 s per-input alarm gives
"timeout". batch writes a 16-hex sha1 per input plus a status letter.
"""

import hashlib
import json
import os
import signal
import sys

LIB, COPY = sys.argv[1], os.path.abspath(sys.argv[2])
ROOT = os.path.join(COPY, "src") if LIB in ("tomli", "mistune") else COPY
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True


class Timeout(BaseException):
    pass


def _alarm(signum, frame):
    raise Timeout()


signal.signal(signal.SIGALRM, _alarm)


def guarded(fn, *a, **k):
    signal.setitimer(signal.ITIMER_REAL, 5.0)
    try:
        return ("ok", fn(*a, **k))
    except Timeout:
        return ("timeout", None)
    except Exception as e:  # noqa: BLE001
        t = type(e)
        return ("err", f"{t.__module__}.{t.__qualname__}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def type_tree(v):
    if isinstance(v, dict):
        return {k: type_tree(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return (type(v).__qualname__, [type_tree(x) for x in v])
    return f"{type(v).__module__}.{type(v).__qualname__}"


def setup():
    if LIB == "tomli":
        import decimal
        import tomli
        mod = tomli

        def ev(mode, s):
            kw = {"parse_float": decimal.Decimal} if mode == "decimal" else {}
            st, v = guarded(tomli.loads, s, **kw)
            if st == "ok":
                return st, repr(v) + "\n" + repr(type_tree(v))
            return st, repr((st, v))
    elif LIB == "sqlparse":
        import sqlparse
        mod = sqlparse

        def tree(tok):
            if tok.is_group:
                return (type(tok).__name__, tok.value, [tree(t) for t in tok.tokens])
            return (type(tok).__name__, repr(tok.ttype), tok.value)

        def parse_dump(s):
            stmts = sqlparse.parse(s)
            return (type(stmts).__name__, [(tree(x), x.get_type()) for x in stmts])

        def split_dump(s):
            r = sqlparse.split(s)
            return (type(r).__name__, [(type(x).__name__, x) for x in r])

        def fmt(s):
            r = sqlparse.format(s, reindent=True, keyword_case="upper", identifier_case="lower")
            return (type(r).__name__, r)

        def ev(mode, s):
            parts = [guarded(fmt, s), guarded(parse_dump, s), guarded(split_dump, s)]
            sts = [p[0] for p in parts]
            st = "ok" if sts == ["ok"] * 3 else ("timeout" if "timeout" in sts else "err")
            return st, repr(parts)
    elif LIB == "mistune":
        import mistune
        from mistune.renderers.html import HTMLRenderer
        mod = mistune
        wl = mistune.create_markdown(plugins=["table", "strikethrough", "footnotes"])
        esc = mistune.create_markdown(escape=True, hard_wrap=True,
                                      renderer=HTMLRenderer(escape=True, allow_harmful_protocols=True),
                                      plugins=["table", "footnotes"])
        md = {"wl": wl, "html": mistune.html, "esc": esc}

        def ev(mode, s):
            st, v = guarded(md[mode], s)
            return st, repr((st, type(v).__name__, v))
    elif LIB == "markdown":
        import markdown
        mod = markdown
        WL = ["markdown.extensions.tables", "markdown.extensions.fenced_code", "markdown.extensions.abbr"]
        WIDE = WL + ["markdown.extensions." + e for e in
                     ("footnotes", "attr_list", "def_list", "smarty", "md_in_html", "toc",
                      "sane_lists", "admonition", "legacy_em", "nl2br")]
        reuse = markdown.Markdown(extensions=list(WL))

        def reuse_conv(s):
            try:
                return reuse.convert(s)
            finally:
                reuse.reset()

        conv = {
            "wl": lambda s: markdown.markdown(s, extensions=list(WL)),
            "none": lambda s: markdown.markdown(s),
            "wide": lambda s: markdown.markdown(s, extensions=list(WIDE)),
            "reuse": reuse_conv,
        }

        def ev(mode, s):
            st, v = guarded(conv[mode], s)
            return st, repr((st, type(v).__name__, v))
    else:
        raise SystemExit("unknown lib")
    f = os.path.realpath(mod.__file__)
    if not f.startswith(os.path.realpath(ROOT) + os.sep):
        raise SystemExit(f"{LIB} imported from {f}, not under {ROOT}")
    return ev


def main():
    ev = setup()
    if sys.argv[3] == "batch":
        corpus = json.load(open(sys.argv[4]))
        hashes, status = [], []
        for mode, s in corpus:
            st, out = ev(mode, s)
            hashes.append(hashlib.sha1(out.encode("utf-8", "surrogatepass")).hexdigest()[:16])
            status.append(st[0] if st != "ok" else "o")
        json.dump({"n": len(corpus), "hashes": hashes, "status": "".join(status)}, open(sys.argv[5], "w"))
    else:
        for line in sys.stdin:
            mode, s = json.loads(line)
            st, out = ev(mode, s)
            sys.stdout.write(json.dumps([st, out]) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
