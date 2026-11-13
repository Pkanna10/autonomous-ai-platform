# fp-ideation errata (full-text check, 2026-11-13)

Status before this check: all 13 sources were summary-only (web-search abstracts and summaries), and the primaries behind [7] and [9] were not accessed. Every file named below sits under `sources/fp-ideation/`.

## Sources
| # | citation (short) | status: full text / open substitute / unverified | file under sources/fp-ideation/ or why none |
| --- | --- | --- | --- |
| 1 | Amdahl 1967, AFIPS | full text (2007 IEEE SSCS News reprint of the paper) | `1-amdahl.pdf` |
| 2 | Gustafson 1988, CACM 31(5) | full text (retyped copy on a Utah course page) | `2-gustafson.pdf` |
| 3 | Williams, Waterman, Patterson 2009, Roofline, CACM 52(4) | open substitute: the authors' Berkeley tech report UCB/EECS-2008-134 (Oct 2008), the same paper in its earlier form. The CACM copies (escholarship, and OSTI via Semantic Scholar, which redirects to escholarship) twice returned HTTP 202 with an empty body | `3-sub-roofline-tr2008.pdf` |
| 4 | Hennessy and Patterson 2017, 6th ed. | open substitute for the formula only (Wikipedia "Amdahl's law"). The textbook is commercial with no open full text, so the chapter-1 claim stays unverified | `4-sub-wiki-amdahl.html` |
| 5 | Bentley 1984, "The Back of the Envelope" | full text (CACM column scan); the 2nd-ed. book is commercial and unverified | `5-bentley.pdf` |
| 6 | Fermi 1945, Trinity observations; OSTI history page | full text (both pages) | `6-fermi.html`, `6b-osti-trinity.html` |
| 7 | Musk via CleanTechnica 2019 | full text of the cited secondary article; the primary (Kevin Rose video interview) is unverified, since there is no text copy and I did not watch the video | `7-cleantechnica.html` |
| 8 | Anderson, Wired, Oct 2012 (Musk Q&A) | full text. The `/all` URL returns 404, but `https://www.wired.com/2012/10/ff-elon-musk-qa/` works | `8-wired.html` |
| 9 | Isaacson 2023, *Elon Musk* | open substitute (secondary only): the Graham Mann book notes named in the notes. The book is commercial, has no open text and is unverified | `9-mann-notes.html` |
| 10 | Hanley and Lippman-Hand 1983, JAMA | open substitute (Wikipedia "Rule of three (statistics)", which cites the paper). JAMA refused with 403, and Semantic Scholar lists it as CLOSED | `10-sub-wiki-rule-of-three.html` |
| 11 | Weitzman 1979, Econometrica | open substitute: Kleinberg, Waggoner and Weyl, "Descending Price Optimally Coordinates Search", arXiv:1603.07682v3 (2016), which restates Weitzman's index and rule (Def. 1, Theorem 1). The Harvard copy refused with 403; the MIT DSpace copy (Semantic Scholar's openAccessPdf) returned a 429 firewall page twice, so I stopped | `11-sub-kleinberg-pandora-arxiv1603.07682.pdf` |
| 12 | Howard 1966, IEEE TSSC | open substitute (Wikipedia "Value of information"). Semantic Scholar lists it as CLOSED | `12-sub-wiki-value-of-information.html` |
| 13 | Goldratt and Cox 2004, *The Goal* | open substitute (Wikipedia "Theory of constraints" and "The Goal (novel)"). The book is commercial | `13-sub-wiki-theory-of-constraints.html`, `13b-sub-wiki-the-goal.html` |

## Corrections
- [1] Notes, "Speed of light and Amdahl": "editing a fraction f of the runtime yields at most a 1/(1−f) speed-up [1]" -> **correction.** The paper "has no equations and only a single figure" (editors' note, p. 19 of the reprint). Its argument is verbal: data-management housekeeping is about 40 % of executed instructions and is sequential, so "Overhead alone would then place an upper limit on throughput of five to seven times the sequential processing rate" (p. 19). The formula is a later formalization: Gustafson [2] p. 1 writes it as 1/(s + p/N), with a maximum of 1/s. Applying it to edited code rather than to parallel processors is my analogy, not Amdahl's claim.
- [1] Core sources: "the origin of 'speed-up is limited by the part you do not touch'" -> confirmed. The editors call it "the first publication by Gene Amdahl on what became known as Amdahl's Law" (p. 19).
- [2] Notes: "the fraction moves with problem size" -> confirmed, p. 2. In practice, "the problem size scales with the number of processors", and it "may be most realistic to assume that run time, not problem size, is constant". The scaled-speedup formula s′ + p′N is credited there to E. Barsis at Sandia.
- [3] Notes: attainable = min(peak compute, bandwidth × intensity) -> confirmed (TR §3: "Attainable GFlops/sec = Min(Peak Floating Point Performance, Peak Memory Bandwidth x Operational Intensity)"). It is stated as an upper bound (§4).
- [3] "Established and contested": "Roofline is described as 'insightful rather than perfect'" listed under *contested* -> **correction.** The phrase is the authors' own framing: "A model need not be perfect, just insightful" (TR §1, repeated in §4). It is not an outside criticism, and §7 rebuts a list of "fallacies" about the model. It is no evidence that the bound is contested.
- [4] "Its chapter 1 is where Amdahl's law is usually taught" -> still unverified (no open full text). The substitute confirms the formula S = 1/((1−p) + p/s) at a fixed workload, with the limit 1/(1−p).
- [5] Source 5: "the search sources disagree on February or March" -> **correction.** The column is CACM 27(3), **March 1984**, pp. 180-184 (page footers); it mentions "the February column" as the previous one.
- [5] Core sources: Bentley covers "the rule of 72" -> **correction.** The rule of 72 does not appear in the 1984 column. It may be in the 2nd-ed. book's Column 7, but I could not verify that (commercial book).
- [5] Notes: Vyssotsky's safety factors -> confirmed, with one precision (p. 181). Derate the performance of real-time systems "by a factor of two, or four, or six". Be "conservative by a factor of two or four" in estimating size, cost **and schedule**. Stay back by a factor of ten on reliability and availability commitments.
- [5] Notes, "Fermi estimation": "Lesson: a factor-of-two estimate is enough to rank options. Bentley teaches the same" -> **correction (overstated).** Bentley says sloppy input is enough when the design comes out "a hundred times above or below specification" (p. 181). His river estimate is "to within an order of magnitude" (p. 180), and his solutions use constants that "may be off by a factor of two, but not much further" (p. 182). He does not say that a factor of two is enough to rank options. In L2, "Bentley's factor of 2 or more" is likewise Vyssotsky's 2, 4 or 6 for performance derating. Applying it to a token cap is my analogy.
- [6] Notes: Fermi "got about 10 kt from roughly 2.5 m of paper drift" -> confirmed. Fermi dropped the paper "from about six feet", about 40 s after the explosion, about ten miles away. The shift was "about 2½ meters", which he estimated as "ten thousand tons of T.N.T.".
- [6] Notes: "A later radiochemical figure of about 18.6 kt" -> **correction.** The OSTI page I cited as [6] says the result "as it was finally calculated -- 21,000 tons (21 kilotons) -- was more than twice what Fermi had estimated". The 18.6 kt figure has no support in [6] and remains unverified.
- [7] Notes: "packs cost about $600/kWh around 2006; materials on the LME about $80/kWh" -> **correction.** The $600/kWh is what Musk says skeptics claim ("They would say, 'It's going to cost $600 per kilowatt-hour'"), not a dated market price, and "around 2006" appears nowhere in [7]. The LME breakdown (carbon, nickel, aluminium, polymers, steel can) and the $80/kWh finding are confirmed. The $80 figure sits inside a quotation the article takes from another writer.
- [7] Source 7: "interview with Kevin Rose (Foundation, about 2012)" -> **correction.** [7] says only "A number of years ago, Elon Musk cited the ancient concept in an interview with Kevin Rose". The series name and year are unverified.
- [8] Notes: "propellant is put at about 0.3 % of a Falcon 9's price [8]" -> confirmed, now at primary. Musk: "The cost of the propellant on Falcon 9 is only about 0.3 percent of the total price. So if the vehicle costs $60 million, the propellant is maybe a couple hundred thousand dollars."
- [8] Source 8: "archived copy not reachable" -> **correction.** The live URL without `/all` works; the article is by Chris Anderson, dated Oct 21, 2012.
- [8]/[9] Notes: "materials at about 2 % of a typical rocket price [9] (secondary)" -> **correction (stronger source).** It is a primary Musk quote in [8]: "the materials cost of a rocket was around 2 percent of the typical price". [9]'s secondary notes give the same ratio as "finished rockets cost at least 50x raw materials".
- [9] Notes: idiot index = finished cost / raw materials -> confirmed in the secondary notes ("ratio of finished-product cost to raw materials"). Isaacson's own text is unverified.
- [10] Notes: "0 events in n gives a 95 % upper bound of about 3/n (valid for n > 30)" -> confirmed by the substitute ("When n is greater than 30, this is a good approximation"), which cites JAMA 249(13):1743-5. Hanley's own text is unverified. My own derived numbers check out on recomputation: the exact Clopper-Pearson interval for 3 of 32 is 1.98 % to 25.0 %. For 0 of 32 the exact one-sided 95 % bound is 8.9 %, so 3/32 = 9.4 % is slightly conservative.
- [11] Notes: "reservation price z where c = E[max(X − z, 0)]; open in order of z; stop when the best reward found exceeds every unopened z" -> confirmed via the substitute. Def. 1 gives E(v − σ)+ = c, and Theorem 1 says to "inspect in order of decreasing σi, stopping when the largest observed value vi exceeds all remaining σ−i". One addition: Weitzman's own model is dynamic with discounting (substitute, fn. 2). The assumption list in my notes was not checked against the original.
- [12] Notes: "the value of information is the gain from acting with knowledge minus the gain from acting without it" -> **correction (qualify).** The substitute defines VoI as "the amount a decision maker would be willing to pay for information prior to making a decision". It warns that this "is not necessarily equal to 'value of decision situation with perfect information' - 'value of current decision situation' as commonly understood". The difference form holds for a risk-neutral (expected-value) decision maker, which is the engine's case. That last step is my reading, not the source's.
- [12] Source 12: missing pages -> **correction.** IEEE TSSC 2(1):22-26, doi:10.1109/tssc.1966.300074 (substitute's bibliography).
- [13] Notes: "throughput is set by the bottleneck" -> confirmed via the substitute ("Only by increasing flow through the constraint can overall throughput be increased"). The ISBN 978-0-88427-178-9 is confirmed as the 2004 revised third edition.

## Claims still unverified
- [4] Hennessy and Patterson: that chapter 1 teaches Amdahl's law (the overview TOC shows only that chapter 1 is "Fundamentals of Quantitative Design and Analysis"; a map, not evidence).
- [5] The rule of 72 in *Programming Pearls* (2nd ed.).
- [6] The 18.6 kt yield figure.
- [7] The Kevin Rose interview itself (series, date, exact words); "around 2006".
- [9] Anything in Isaacson's book itself.
- [10] Hanley and Lippman-Hand's own text (only the rule is confirmed, via the substitute).
- [11] Weitzman's original assumptions (independence, known distributions) as stated in the 1979 paper; the Econometrica page range 641-654 (Semantic Scholar gives the year 1978, the MIT working-paper version).
- [12] That Howard (1966) is "the founding paper of decision analysis".
- [13] The "mirage" wording for gains at non-bottlenecks (not in either substitute).
- [3] The CACM page range 65-76 (CACM copy not obtained).

## Overview sources
| # | source (short) | kind | file under sources/fp-ideation/overview/, or "refused: <code>" |
| --- | --- | --- | --- |
| 1 | Hennessy and Patterson, 6th ed., Elsevier product page | TOC (chapters and appendices) | `1-elsevier-hp6-toc.html` |
| 2 | Bentley, *Programming Pearls* 2nd ed., InformIT (publisher) | TOC (columns with section titles) | `2-informit-pearls2e-toc.html` |
| 3 | MIT OCW 6.172 Performance Engineering of Software Systems (Fall 2018), lecture slides | topic list | `3-ocw6172-lecture-list.html` |
| 4 | MIT OCW 6.172, calendar | syllabus | `4-ocw6172-calendar.html` |
| 5 | MIT OCW 18.098 Street-Fighting Mathematics (IAP 2008), course home | topic list (course description) | `5-ocw18098-streetfighting-math.html` |
| 6 | MIT OCW 2.854 Introduction to Manufacturing Systems (Fall 2016), course home | topic list (course description) | `6-ocw2854-manufacturing-systems.html` |
| 7 | MIT OCW 1.011 Project Evaluation (Spring 2011), calendar | syllabus | `7-ocw1011-project-evaluation-calendar.html` |
| - | MIT Press, *Street-Fighting Mathematics* book page | TOC | refused: 403 |
| - | Bentley's Bell Labs *Pearls* TOC (cs.bell-labs.com) | TOC | not reachable: proxy CONNECT 502 (host gone), skipped |
| - | Stanford ExploreCourses, MS&E 252 Decision Analysis | syllabus | not fetched: TLS verification failed; skipped, TLS not overridden |

## Not yet covered
- Little's Law (overview #2, Column 7): it prices the wall-clock atom of L1 (trials in flight × time per trial) more rigorously than my 2.5 min/trial figure.
- Design levels (overview #2, Column 6): where a gain comes from (algorithm, data structure or code tuning). This bears on L10's hot-set share F and on the lane mix.
- Rules for code tuning / Bentley rules (overview #2 Appendix 4; #3 L2): a known catalogue of techniques that can serve as a prior for the ideation lanes (L1). The playbook seat may already hold it.
- Measurement and timing (overview #3, #4 L10): noise floors behind L6 and L9's measurement share. This is probably the fp-measure seat's ground.
- High performance in dynamic languages (overview #3, last lecture): the speed-of-light for CPython-bound libraries, i.e. what F can be (L10).
- Caching and the memory hierarchy (overview #1 ch. 2; #3): roofline's bandwidth leg. Probably not relevant for interpreter-bound pure-Python workloads.
- Domain-specific languages and autotuning (overview #3): parameter search under a budget. This bears on trial allocation (L1) and on combine search (L5).
- Bottleneck characterization, buffer and batch-size analysis, queueing (overview #6): the engine's s4b quotas and trial slots as a production line (L1 budget-bound drops).
- Decision trees and real options (overview #7): pricing an untried idea as an option. This complements Weitzman (the [11] substitute frames the index as a call-option strike price) for L1.
- Dimensional analysis and extreme-cases reasoning (overview #5): sanity checks on Fermi-style atoms. Probably minor for the ledger.
- Analysis of multithreaded algorithms, work/span (overview #3): Amdahl's parallel cousin. Probably not relevant (single-threaded trials).
