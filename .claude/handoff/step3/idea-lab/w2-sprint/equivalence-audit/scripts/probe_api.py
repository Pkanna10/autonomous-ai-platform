"""Targeted API-state probes for the cache/memo keeps of mistune and markdown.

python3 -I probe_api.py AUDIT_DIR LIB                 (driver: every diff of LIB)
python3 -I -B probe_api.py --child LIB COPY_DIR       (one copy, prints JSON)

Documented extension points used after a first render, where a cache built
on first use (per class, per instance, per registry) could go stale:
mistune: a renderer subclass overriding text/link after a plain render; a
second renderer with allow_harmful_protocols after a safe one (safe_url
cache); md.renderer.register() and a plugin applied after first use.
markdown: one Markdown instance, convert, then inlinePatterns.register() a
new pattern and deregister('em_strong'), then convert again; abbreviations
that change between two converts on a reused instance; treeprocessor
deregistration. Each child runs under `unshare -rn` with a 120 s timeout.
"""
import json
import os
import subprocess
import sys

DOC = ("Some *em* and **strong** [link](https://e.org/x) ++ins++ HTML text\n\n"
       "[js](javascript:alert(1)) and [up](HTTPS://U.example) ~~del~~\n")


def child_mistune():
    import mistune
    from mistune.renderers.html import HTMLRenderer
    out = {}
    md = mistune.create_markdown(plugins=["strikethrough"])
    out["plain1"] = md(DOC)

    class Upper(HTMLRenderer):
        def text(self, text):
            return text.upper()

        def link(self, text, url, title=None):
            return "<L " + url + ">" + text + "</L>"

    out["subclass"] = mistune.create_markdown(renderer=Upper(), plugins=["strikethrough"])(DOC)
    out["plain2"] = md(DOC)
    out["harmful_ok"] = mistune.create_markdown(renderer=HTMLRenderer(allow_harmful_protocols=True))(DOC)
    out["harmful_list"] = mistune.create_markdown(renderer=HTMLRenderer(allow_harmful_protocols=["javascript:"]))(DOC)
    out["plain3"] = mistune.create_markdown()(DOC)
    md.renderer.register("strikethrough", lambda r, text: "<S>" + text + "</S>")
    out["registered_after"] = md(DOC)
    md2 = mistune.create_markdown()
    out["before_plugin"] = md2(DOC)
    md2.use(mistune.plugins.import_plugin("strikethrough"))
    out["plugin_after"] = md2(DOC)
    return out


def child_markdown():
    import markdown
    from markdown.inlinepatterns import SimpleTagInlineProcessor
    out = {}
    md = markdown.Markdown(extensions=["markdown.extensions.abbr"])
    out["c1"] = md.convert("*[HTML]: Hyper\n\n" + DOC)
    md.reset()
    md.inlinePatterns.register(SimpleTagInlineProcessor(r"()\+\+(.*?)\+\+", "ins"), "ins", 175)
    out["c2_registered"] = md.convert(DOC)
    md.reset()
    md.inlinePatterns.deregister("em_strong")
    out["c3_deregistered"] = md.convert(DOC)
    md.reset()
    out["c4_new_abbr"] = md.convert("*[text]: Changed\n\n" + DOC)
    md.reset()
    out["c5_no_abbr"] = md.convert(DOC)
    md.treeprocessors.deregister("abbr") if "abbr" in md.treeprocessors else None
    md.reset()
    out["c6_tp_deregistered"] = md.convert("*[HTML]: Hyper\n\n" + DOC)
    out["c7_noreset_same_instance"] = md.convert("*[em]: E\n\n" + DOC)
    return out


def driver(a, lib):
    here = os.path.abspath(__file__)
    diffs = [u for u in json.load(open(os.path.join(a, "out/diffs.json"))) if u["lib"] == lib]

    def run(copy):
        p = subprocess.run(["unshare", "-rn", "--", "python3", "-I", "-B", here, "--child", lib, copy],
                           capture_output=True, text=True, timeout=120)
        return json.loads(p.stdout) if p.returncode == 0 else {"ERR": p.stderr[-300:]}

    base = run(os.path.join(a, "work", lib, "base"))
    res = {}
    for u in diffs:
        r = run(u["dir"])
        d = {k: {"base": base.get(k), "patched": r.get(k)} for k in set(base) | set(r) if base.get(k) != r.get(k)}
        if d:
            res[u["sha"][:12]] = d
    json.dump({"base": base, "differs": res}, open(os.path.join(a, "out", f"probe-api-{lib}.json"), "w"), indent=1)
    print(lib, "diffs probed", len(diffs), "differ", len(res), {k: sorted(v) for k, v in res.items()})


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        root = sys.argv[3]
        sys.path.insert(0, os.path.join(root, "src") if sys.argv[2] == "mistune" else root)
        print(json.dumps(child_mistune() if sys.argv[2] == "mistune" else child_markdown()))
    else:
        driver(sys.argv[1], sys.argv[2])
