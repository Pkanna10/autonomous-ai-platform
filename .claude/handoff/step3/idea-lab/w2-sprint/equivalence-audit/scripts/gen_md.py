"""Markdown generator for the mistune and Python-Markdown audits.

Blocks the two workloads use (ATX headings, paragraphs, nested lists, block
quotes, fenced code, pipe tables, footnotes for mistune, abbreviations for
markdown) plus setext headings, indented code, thematic breaks, HTML blocks,
link reference definitions and definition-like lines. Inline: emphasis in
every nesting (* _ ** __ ***, intraword, unmatched), strikethrough, code
spans with multiple backticks, inline/reference/collapsed/shortcut links and
images with titles, <> destinations, parens and escapes, autolinks, raw HTML,
entities (named, decimal, hex, bogus), backslash escapes, hard breaks (two
spaces, backslash), STX/ETX placeholder bytes, NUL, unicode punctuation, CJK,
emoji, combining marks, zero-width and RTL marks, tabs, CRLF and lone CR, and
dangerous URL schemes, escaped parens in destinations and upper-case
safe schemes (added after calibration). A byte-level mutator is applied to a share.
"""

import random

WORDS = ["engine", "trial", "judge", "verdict", "HTML", "noise", "a", "I", "x_y",
         "foo*bar", "snake_case_word", "é", "naïve", "中文", "日本語", "\U0001F600",
         "é", "​", "‮", "rtl‏", "—", "…", "“quoted”", "‘s’",
         "¡hola!", "¿qué?", "«ok»", "2*3", "a&b", "<", ">", "&", '"', "'", "1.",
         "HTMLs", "XHTML", "html", "ABBR", "SQL", " ", "co-op", "$5", "100%"]
URLS = ["https://example.org/1", "http://a.b/c?d=e&f=g", "/rel/path", "#frag",
        "<https://x.y/with space>", "https://x.y/a(b)c", "https://x.y/a_(b)",
        "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<b>x</b>",
        "data:image/png;base64,AAAA", "vbscript:x", "mailto:a@b.c", "ftp://f.g",
        "https://é.example/ü", "https://x.y/%20", "", "<>", "https://x.y/\\*",
        "url\"quote", "https://x.y/a&amp;b", "  https://pad.ed  ",
        # added after calibration (MM2, MM3): escaped parens, upper-case safe schemes
        "/u\\)x", "/u\\(x", "/a\\(b\\)c", "HTTPS://UPPER.example/", "Mailto:a@b.c",
        "Http://x.y", "/p\\ q", "#\\)"]
TITLES = ['', ' "title"', " 'single'", ' (paren)', ' "with \\"esc\\""', ' "a & b"',
          ' "unclosed', ' "<tag>"']
ENT = ["&amp;", "&copy;", "&nbsp;", "&#123;", "&#x1F600;", "&#0;", "&bogus;", "&amp",
       "&#xD800;", "&ouml;", "&lt;b&gt;", "&#99999999;", "&"]
HTML_IN = ["<span>x</span>", "<b>", "</b>", "<br>", "<br/>", "<img src=x onerror=y>",
           "<a href=\"/x\">a</a>", "<!-- c -->", "<?php ?>", "<![CDATA[x]]>",
           "<x-y>", "</>", "<script>alert(1)</script>", "< notatag >", "<a\nhref=x>"]
ESC = ["\\*", "\\_", "\\[", "\\]", "\\\\", "\\`", "\\#", "\\|", "\\<", "\\&", "\\!",
       "\\~", "\\a", "\\"]
RARE_CH = ["\x02", "\x03", "\x00", "\x01", "\t", "\r", "\x0b", "\x0c", "�",
           " ", "﻿", "\x7f"]
REFS = ["foo", "Foo", "FOO", "bar baz", "ü", "1", "a\\]b", "[nested]", "x", "HTML"]


def w(rng):
    return rng.choice(WORDS[:6]) if rng.random() < 0.6 else rng.choice(WORDS)


def inline(rng, depth=0):
    r = rng.random()
    if r < 0.40:
        return w(rng)
    if r < 0.52 and depth < 3:
        m = rng.choice(["*", "_", "**", "__", "***", "___", "~~", "*", "**"])
        inner = " ".join(inline(rng, depth + 1) for _ in range(rng.randint(1, 3)))
        close = m if rng.random() < 0.85 else rng.choice(["", "*", "_", "**", m[:1]])
        lead = rng.choice(["", "", "", " ", "x"])
        return lead + m + inner + close + rng.choice(["", "", "y", " "])
    if r < 0.58:
        t = rng.choice(["`", "`", "``", "```"])
        body = rng.choice(["code()", "a ` b", " x ", "`", "*not em*", "<b>", "a|b", "&amp;", ""])
        return t + body + (t if rng.random() < 0.9 else "")
    if r < 0.70 and depth < 3:
        text = " ".join(inline(rng, depth + 1) for _ in range(rng.randint(1, 2)))
        img = "!" if rng.random() < 0.15 else ""
        kind = rng.random()
        if kind < 0.6:
            return f"{img}[{text}]({rng.choice(URLS)}{rng.choice(TITLES)})"
        if kind < 0.75:
            return f"{img}[{text}][{rng.choice(REFS)}]"
        if kind < 0.85:
            return f"{img}[{rng.choice(REFS)}][]"
        if kind < 0.95:
            return f"[{rng.choice(REFS)}]"
        return f"[{text}]({rng.choice(URLS)}"  # unclosed
    if r < 0.74:
        return rng.choice(["<https://auto.link/x>", "<a@b.co>", "<mailto:x@y.z>", "<javascript:x>",
                           "https://bare.example.org", "www.example.com", "<http://a.b/<c>"])
    if r < 0.79:
        return rng.choice(HTML_IN)
    if r < 0.85:
        return rng.choice(ENT)
    if r < 0.90:
        return rng.choice(ESC)
    if r < 0.93:
        return rng.choice(RARE_CH)
    if r < 0.96:
        return rng.choice(["[^n1]", "[^1]", "[^missing]", "[^]", "^up^", "~sub~"])
    return rng.choice(["  \n", "\\\n", "\n", " \n"])


def sentence(rng):
    return " ".join(inline(rng) for _ in range(rng.randint(2, 12))) + rng.choice([".", "", " & more.", "  ", "!"])


def block(rng, depth=0):
    r = rng.random()
    if r < 0.12:
        return rng.choice(["#", "##", "###", "####", "#####", "######", "#######"]) + \
            rng.choice([" ", " ", "", "\t", "  "]) + sentence(rng) + rng.choice(["", "", " ##", " #", "#"])
    if r < 0.16:
        return sentence(rng) + "\n" + rng.choice(["===", "---", "=", "- - -", "  ==="])
    if r < 0.36:
        return sentence(rng) + rng.choice(["", "\n" + sentence(rng), "\n  " + sentence(rng)])
    if r < 0.50 and depth < 3:
        marker = rng.choice(["-", "*", "+", "1.", "2)", "10.", "-", "*"])
        items = []
        for i in range(rng.randint(1, 4)):
            m = marker if not marker[0].isdigit() else f"{i + 1}{marker[-1]}"
            item = m + rng.choice([" ", " ", "  ", "\t", "    "]) + rng.choice(["", "[ ] ", "[x] ", ""]) + sentence(rng)
            if rng.random() < 0.3:
                ind = rng.choice(["  ", "    ", "\t", "   "])
                sub = block(rng, depth + 1)
                item += "\n" + "\n".join(ind + ln for ln in sub.split("\n"))
            items.append(item)
        return rng.choice(["\n", "\n\n"]).join(items)
    if r < 0.58 and depth < 3:
        sub = block(rng, depth + 1)
        pre = rng.choice(["> ", ">", "> > ", ">\t"])
        lines = sub.split("\n")
        out = [pre + ln if (i == 0 or rng.random() < 0.8) else ln for i, ln in enumerate(lines)]
        return "\n".join(out)
    if r < 0.66:
        fence = rng.choice(["```", "~~~", "````", "``"])
        info = rng.choice(["", "python", " python ", "py {.x}", "a`b", "js title=\"x\""])
        body = rng.choice(["value = 1 * 2\nprint(value)", "<b>&amp;</b>", "```", "", "\ttab", "a\n\n\nb"])
        close = fence if rng.random() < 0.9 else ""
        ind = rng.choice(["", "", "  ", "   "])
        return f"{ind}{fence}{info}\n{body}\n{close}"
    if r < 0.70:
        return rng.choice(["    code block\n    line 2", "\tcode\ttab", "    <b>x</b>"])
    if r < 0.78:
        ncol = rng.randint(1, 4)
        head = "| " + " | ".join(w(rng) for _ in range(ncol)) + " |"
        sep = "| " + " | ".join(rng.choice(["---", ":---", "---:", ":-:", "-", "--"]) for _ in range(ncol)) + " |"
        rows = []
        for _ in range(rng.randint(0, 3)):
            cells = [rng.choice([inline(rng), "`a|b`", "a \\| b", "", "**b**", "1.5"]) for _ in range(rng.choice([ncol, ncol, ncol - 1, ncol + 1]))]
            rows.append(rng.choice(["| ", ""]) + " | ".join(cells) + rng.choice([" |", ""]))
        if rng.random() < 0.2:
            head = head.strip("|")
        return "\n".join([head, sep] + rows)
    if r < 0.82:
        return rng.choice(["***", "---", "___", "* * *", "- - -", "____", "**", "  ---"])
    if r < 0.86:
        return rng.choice(["<div>\n*md* inside\n</div>", "<div markdown=\"1\">\n*md*\n</div>", "<!-- comment\nblock -->",
                           "<pre>\n  x\n</pre>", "<script>\nvar a = '<b>';\n</script>", "<table><tr><td>x</td></tr></table>",
                           "<p>open", "</div>"])
    if r < 0.91:
        return f"[{rng.choice(REFS)}]: {rng.choice(URLS)}{rng.choice(TITLES)}"
    if r < 0.95:
        return f"[^{rng.choice(['n1', '1', 'x', 'n0'])}]: {sentence(rng)}" + rng.choice(["", "\n    continued " + w(rng)])
    return f"*[{rng.choice(['HTML', 'SQL', 'ABBR', 'a.b', 'C++', 'e', '中文', 'HT'])}]: {rng.choice(['Hyper Text', '', 'x & y', '\"q\"'])}"


def document(rng):
    parts = []
    if rng.random() < 0.4:
        parts.append("*[HTML]: Hyper Text Markup Language")
    for _ in range(rng.randint(1, 7)):
        parts.append(block(rng))
    doc = rng.choice(["\n\n", "\n\n", "\n", "\n\n\n"]).join(parts)
    nl = rng.random()
    if nl < 0.08:
        doc = doc.replace("\n", "\r\n")
    elif nl < 0.11:
        doc = doc.replace("\n", "\r")
    if rng.random() < 0.05:
        doc = doc.replace("    ", "\t")
    return doc + rng.choice(["\n", "", "\n\n", "  "])


RARE = ["*", "_", "`", "[", "]", "(", ")", "<", ">", "&", "\\", "!", "#", "|", "~",
        "\n", "\r", "\t", " ", "  \n", ">", "-", "1.", "\x02", "\x03", ":", "^"]


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
            j = min(len(s), i + rng.randint(1, 12))
            s[i:i] = s[i:j]
    return "".join(s)


def gen(rng):
    s = document(rng)
    if rng.random() < 0.25:
        s = mutate(rng, s)
    return s


if __name__ == "__main__":
    rng = random.Random(1)
    for _ in range(4):
        print(repr(gen(rng)))
