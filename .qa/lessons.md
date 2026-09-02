
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

## 2026-09-02 — a re-derived finding got a new id for a defect already tracked
An unrecorded run minted VERDICT-F-19 for "the stale-command-name sweep misses
standards/ and templates/". That defect was already VERDICT-F-15, filed
2026-08-30, whose own recorded title names `standards/* and templates/*`
explicitly. F-15 had been *partially* fixed in between — the sweep was widened
to README-pypi.md and docs/ — and the partial fix made the remainder read as a
new problem. Filing it again would have double-counted one defect under two ids
and reset a known gap's age to zero.
Discriminator: before minting an id, grep the existing findings' titles AND
evidence for the file path, not for the wording of the symptom. The wording
changes when a fix lands halfway; the path does not. Id F-19 is left unused.

## 2026-09-02 — verify the artifacts you wrote, not just the code you reviewed
The pre-handoff self-check (§13) is what caught VERDICT-F-23 and VERDICT-F-24 —
the state's `project` silently re-keyed from `verdict` to `verdict-clone`, and
an INDEX row dated a day off the state's own UTC timestamp. Both were defects in
the harness, and both were sitting in the artifacts this run had just produced.
Neither would have been found by reading source; both were obvious the moment
the written files were read back and compared against each other.
Discriminator: after finalize, diff the state, the INDEX row, the runs.jsonl row
and the report filename against each other. They describe one run and must
agree; where they disagree, the harness composed a value instead of measuring it.

## 2026-09-02 — evidence prose is executable input, not just narrative
Run 4 wrote VERDICT-F-20's evidence with a test's source quoted verbatim,
including the literal node id `t.py::new` from an assertion's expected value.
Run 5's harness (new in v0.53.0) scrapes pytest node ids out of evidence text
to choose which test to re-run, took that fabricated id as F-20's demonstrating
test, and could not fix-verify a finding that was genuinely fixed. A probe then
showed the worse case: a cross-reference to another finding's still-failing
test, quoted in evidence, force-reopens a correctly-resolved finding.
Discriminator: after any run that resolves findings, read each finding's
`verification.test` back and check it against test-ids.txt. An id that is not a
collected test was scraped from prose. When writing evidence, put the
demonstrating test id first and paraphrase quoted test source rather than
copying node ids out of it. Filed as VERDICT-F-26.
