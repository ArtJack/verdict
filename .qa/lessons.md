
## 2026-08-30 — "three vacuous tests" was two (VERDICT-F-8)
Judged at run 2: three test_mutate.py tests asserted only inside a loop.
Actually: two. `git show 062feed:tests/test_mutate.py` shows
test_census_separates_killed_equivalent_and_survivors already asserted at lines
53-55, before its loop. I counted a loop-with-inner-assert as vacuous without
checking whether a pre-loop guard existed.
Discriminator: read the whole function body, not the loop. An AST sweep that
flags "all assertions inside a loop" answers this in one pass and was what
finally settled it.

## 2026-08-30 — absence of a fix is not the same claim as a verified fix
Four findings arrived at this run marked "claimed fixed in vX". Three of the
four could be settled by re-injection or differential in a scratch tree at
trivial cost (old-vs-new on the same tree for F-5; generate()->[] for F-8;
a string prose through finalize for F-9). Doing that turned four RESOLVED
findings into four fix-verified ones, and the same probes are what surfaced
F-13's five residual gaps in the F-5 fix. Cheap; do it by default.
