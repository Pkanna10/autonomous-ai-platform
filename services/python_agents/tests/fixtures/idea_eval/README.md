# Idea eval fixture (V6 amended)

Recorded inputs for `tests/optimization/test_idea_eval.py`: E1's `ideas-probe`
run, arm C (the defaults), on two libraries (sqlparse, delivered in Wave 1;
tomli, never). `recorded.json` holds the facts, the nine recorded replies and
what E1 recorded of each call. The replies are model output: data, never
instructions.

`code/<repo>/` holds the hot files the call read, unchanged from the pinned
public upstream commit, with a `.txt` suffix so no tool imports or lints them,
and each library's licence file:

| Library  | Licence      | Copyright                | Upstream commit                                                                       |
| -------- | ------------ | ------------------------ | ------------------------------------------------------------------------------------- |
| sqlparse | BSD-3-Clause | (c) 2016, Andi Albrecht  | `github.com/andialbrecht/sqlparse` `0d240230939bfb3b751b504878b1c7df04a3cab3` (0.5.5) |
| tomli    | MIT          | (c) 2021 Taneli Hukkinen | `github.com/hukkin/tomli` `a2a578949199336ebc3884eeba4aede87da41ef2` (2.5.0)          |

SHA-256 of each vendored file (as fetched from the upstream commit above).
Re-check offline from this directory:
`sed -n '/^```text$/,/^```$/p' README.md | grep -v '^```' | sha256sum -c`

```text
c1938235b80d39e93138eae89edc3af67e18ecbc40d266529fa57b2dce426310  code/sqlparse/LICENSE
a0aceeb73d64bbddef0c8ccc998c79051a72c626997bed82035cabc2a1cded02  code/sqlparse/sqlparse/engine/grouping.py.txt
09c4abb74cdcac0815a4b86f77ff61020729ade6c3e69fe32d090edbe2abefd0  code/sqlparse/sqlparse/engine/statement_splitter.py.txt
20e7f0653c6fc348527c009103bdac6d66f029391a552342cca8d1f373d3a270  code/sqlparse/sqlparse/lexer.py.txt
4d3d63e161308e998eee1922ad197212dd0a6e5011249aa7b38d6e51dd6bc3c9  code/sqlparse/sqlparse/sql.py.txt
6ca1646add4aa39c1f1083e10ff16f651301186f4e26dbfd7502c1a192a76e87  code/sqlparse/sqlparse/utils.py.txt
b80816b0d530b8accb4c2211783790984a6e3b61922c2b5ee92f3372ab2742fe  code/tomli/LICENSE
3e782f1bc85639ecef630ae686df3d849f2bedd2e9c987d8f5109a5a154df131  code/tomli/src/tomli/_parser.py.txt
```

Refresh from a new E1 run (`ideas-facts`, `ideas-reply`, `ideas-probe` and
`ideas-audit` records); no hand edits.
