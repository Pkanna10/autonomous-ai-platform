"""Calibrate the mistune, markdown and sqlparse harnesses on planted rare-input faults.

python3 -I calibrate_mut.py AUDIT_DIR [--tag T] LIB [LIB ...]
Each mutant is the base copy with one exact source replacement, placed in
the same functions the keeps edit (bracket map, link href, safe_url, fast
text end; inline prefilter, abbr tail and boundaries; dollar quotes,
whitespace regex, CASE-pass gating). It runs runner.py under `unshare -rn`
on the audit's fixed corpus; prints the differences against the base hashes.
Writes out/calib-mutants.json.
"""
import json
import os
import shutil
import subprocess
import sys

A = sys.argv[1]
ARGS = sys.argv[2:]
TAG = ""
if ARGS[:1] == ["--tag"]:
    TAG, ARGS = "-" + ARGS[1], ARGS[2:]
HERE = os.path.dirname(os.path.abspath(__file__))
M = {
    "mistune": {
        "MM1 bracket map ignores backslash escape": ("src/mistune/_inline/links.py",
            '            pos += 2\n            continue\n        if char == "["',
            '            pos += 1\n            continue\n        if char == "["'),
        "MM2 href scan drops backslash escapes": ("src/mistune/helpers.py",
            'if c == "\\\\" and pos + 1 < len(src) and src[pos + 1] in string.punctuation:', "if False:"),
        "MM3 safe_url case-sensitive scheme check": ("src/mistune/renderers/html.py",
            "_url = _unquote_url(url).lower().lstrip()", "_url = _unquote_url(url).lstrip()"),
        "MM4 fast text end ignores hard line breaks": ("src/mistune/inline_parser.py",
            '        if m.group(0) == "\\n":\n            return self._find_linebreak_start',
            "        if False:\n            return self._find_linebreak_start"),
    },
    "markdown": {
        "MK1 inline prefilter misses space/newline/smarty triggers": ("markdown/treeprocessors.py",
            "        if not isinstance(data, util.AtomicString):\n            startIndex = 0",
            "        if not isinstance(data, util.AtomicString):\n"
            "            if not any(c in data for c in '*_[`<!&\\\\'):\n                return data\n            startIndex = 0"),
        "MK2 abbr skips tails": ("markdown/extensions/abbr.py",
            "        if parent is not None and el.tail:", "        if False and parent is not None and el.tail:"),
        "MK3 abbr regex loses leading word boundary": ("markdown/extensions/abbr.py",
            'self.RE = re.compile(f"\\\\b(?:', 'self.RE = re.compile(f"(?:'),
    },
    "sqlparse": {
        "MS1 lexer misses dollar quotes": ("sqlparse/keywords.py",
            "    (r'((?<![\\w\\\"\\$])\\$(?:[_A-ZÀ-Ü]\\w*)?\\$)[\\s\\S]*?\\1', tokens.Literal),\n", ""),
        "MS2 whitespace regex only space/newline": ("sqlparse/keywords.py",
            "(r'\\s+?', tokens.Whitespace),", "(r'[ \\n]+?', tokens.Whitespace),"),
        "MS3 CASE pass gated case-sensitively": ("sqlparse/engine/grouping.py",
            "def group_case(tlist):\n    _group_matching(tlist, sql.Case)",
            "def group_case(tlist):\n    if 'CASE' not in str(tlist):\n        return\n    _group_matching(tlist, sql.Case)"),
    },
}
outf = os.path.join(A, "out", f"calib-mutants{TAG}.json")
res = json.load(open(outf)) if os.path.exists(outf) else {}
for lib in ARGS:
    base = json.load(open(os.path.join(A, "out", f"hashes-{lib}-base{TAG}.json")))
    for name, (rel, old, new) in M[lib].items():
        d = os.path.join(A, "work", lib, "mut-" + name.split()[0])
        if os.path.exists(d):
            shutil.rmtree(d)
        shutil.copytree(os.path.join(A, "work", lib, "base"), d)
        p = os.path.join(d, rel)
        src = open(p, encoding="utf-8").read()
        assert src.count(old) == 1, (name, src.count(old))
        open(p, "w", encoding="utf-8").write(src.replace(old, new))
        out = os.path.join(A, "out", f"calib-{lib}-{name.split()[0]}{TAG}.json")
        subprocess.run(["unshare", "-rn", "--", "python3", "-I", "-B", os.path.join(HERE, "runner.py"), lib, d,
                        "batch", os.path.join(A, "out", f"corpus-{lib}{TAG}.json"), out], check=True, timeout=1800)
        h = json.load(open(out))
        n = sum(x != y for x, y in zip(base["hashes"], h["hashes"]))
        res[name] = {"lib": lib, "differences": n, "n": h["n"]}
        json.dump(res, open(outf, "w"), indent=1)
        print(lib, name, "differences", n, "of", h["n"], flush=True)
