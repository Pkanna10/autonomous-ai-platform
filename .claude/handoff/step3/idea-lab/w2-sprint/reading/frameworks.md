# X2 portfolio leap by framework (U-portfolio, X2-P and X2-F)

- **Dealt.** Each leap call is dealt three procedures by (library, run, round); a row per dealt procedure, whatever became of it. No reply: the request went out and no reply could be read (its failure kind is on the row); not sent: the lanes stopped before the leap.
- **Ideas, trialled, kept.** Ideas passed the reply's checks; trialled and kept are the hypothesis rows of the framework with a round and with a keep.
- **Median gain / floor.** Over the trialled ideas with a gain and a positive floor; standalone, not additive.
- **Adherence (answered).** Step products returned over steps required, over the answered procedures only (dealt less no reply and not sent).

| arm | framework | dealt | no reply | not sent | ideas | trialled | kept | median gain / floor | adherence (answered) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| X2-F | bentley | 2 | 0 | 0 | 1 | 0 | 0 | - | 100% |
| X2-F | per_element | 2 | 0 | 0 | 1 | 0 | 0 | - | 100% |
| X2-F | backend | 2 | 0 | 0 | 0 | 0 | 0 | - | 100% |
| X2-F | skiena | 2 | 0 | 0 | 2 | 0 | 0 | - | 100% |
| X2-F | polya | 1 | 1 | 0 | 0 | 0 | 0 | - | - |
| X2-F | from_spec | 2 | 1 | 0 | 1 | 1 | 1 | 2.36 | 100% |
| X2-F | ifr | 3 | 1 | 0 | 1 | 0 | 0 | - | 100% |
| X2-F | trim | 1 | 0 | 0 | 1 | 0 | 0 | - | 100% |
| X2-F | recall | 3 | 0 | 0 | 2 | 1 | 0 | 1.05 | 100% |
| X2-P | bentley | 7 | 0 | 0 | 7 | 1 | 1 | 3.65 | 100% |
| X2-P | per_element | 7 | 0 | 0 | 5 | 0 | 0 | - | 89% |
| X2-P | backend | 7 | 0 | 0 | 4 | 1 | 0 | -1.32 | 79% |
| X2-P | skiena | 8 | 0 | 0 | 3 | 0 | 0 | - | 100% |
| X2-P | polya | 7 | 0 | 0 | 5 | 3 | 2 | 3.62 | 100% |
| X2-P | from_spec | 7 | 0 | 0 | 5 | 1 | 1 | 3.27 | 100% |
| X2-P | ifr | 7 | 0 | 0 | 5 | 3 | 1 | 0.28 | 100% |
| X2-P | trim | 7 | 0 | 0 | 7 | 2 | 1 | 2.09 | 100% |
| X2-P | sit | 7 | 0 | 0 | 5 | 1 | 1 | 5.07 | 100% |
| X2-P | recall | 8 | 0 | 0 | 5 | 3 | 0 | 0.93 | 100% |
