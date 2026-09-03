
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

## 2026-09-02 (run 6) — "this is the only site" was wrong in three of four class links
Run 5 closed each finding with a `root_cause.class` link asserting the search
for the same shape found nothing else. Three of the four were incomplete, and
each incompleteness became this run's residual: F-30 searched *renderers* and
missed `_stamp_outcome`, where the same claim/measurement confusion still lives
(now VERDICT-F-32); F-25 searched the copy-back and not what the copied test
imports (now VERDICT-F-33); F-27's fix keyed on `delta`, a per-run transient,
and the search for other transient-as-durable uses was never run (now
VERDICT-F-34). The fixes themselves were sound — eight re-injections, eight
caught — so the failure was not in the repair but in the sweep.
Discriminator: a class link must name the search that was run (the pattern, the
tree, the hits) rather than assert its conclusion. "Searched `fix_verified`
across src/: four call sites, three benign" is auditable; "this is the single
site" is not, and it reads identically whether the search was thorough or
imagined.

## 2026-09-02 (run 6) — the whole `confirmed` column is self-graded, and I added to it
Auditing `.qa/outcomes.json` after this run's finalize: 19 rows read `confirmed`
with the reason "fix-verified: the guarding test failed on re-injection", and
not one of them has a harness measurement in the state to support it. Nine
belong to findings that have aged out of state entirely, so their claims can no
longer be audited from the record at all. Five are this run's own — legitimate
in that each cites a re-injection I actually ran, and indistinguishable in the
ledger from one I did not. `verification` was `null` this run, so the harness
measured nothing that could have contradicted me.
Discriminator: the check is a join, not a read — every `confirmed` row must be
matched against that finding's `verification` block showing at_previous `fail`
and at_head `pass`. A run that reports its own precision without performing
that join is quoting a number it produced. Filed as VERDICT-F-32; until it is
fixed, treat every published `proven` precision figure for this project as the
agent's self-assessment.

## 2026-09-02 (run 7) - a harness measurement that contradicts a hand re-injection may be measuring a different test

This run re-injected all four of run 6's findings and watched each guard fail.
The ledger recorded two of them (VERDICT-F-31, VERDICT-F-34) as "claimed
fix-verified, but the harness's own re-injection showed pass / pass, which
settles nothing", and the report's Fix-verification line reads "0 verified".
Both statements are about tests that are not those findings' guards: the
selector took the first node id in the evidence prose (VERDICT-F-26), which for
F-31 was ::test_a_line_only_a_child_process_executed_is_measured and for F-34
was another finding's ::test_a_finding_that_came_back_is_filed_again. A run that
reads "the measurement contradicts you" and downgrades its own verified fix
would be deferring to a measurement of something else.
Discriminator: before believing a verification record in either direction, read
`verification.test` and check it against the test named in the finding's own
evidence as its guard. If they differ, the record is evidence about a third
party, not about this finding. Filing the difference: VERDICT-F-35.


## 2026-09-02 (run 9) — a re-injection in a scratch copy measured the original checkout

Four defects were injected into a scratch copy's `src/verdict_mcp/` and all four
guard tests stayed green, which reads as four verified fixes. They were not
measurements at all: `cp -a` carries `.venv`, whose editable-install
`_editable_impl_*.pth` names the ORIGINAL checkout's `src` by absolute path, so
`import verdict_mcp` resolved to the unmodified original every time. Re-run with
PYTHONPATH pinned to the scratch tree's own `src`, all four bit. The tell was the
pattern, not any single result: four out of four passing is not four fixes, it is
an instrument reading zero. Hooks and `eval/*.py` are invoked by path and are
unaffected, which is why VERDICT-F-39 and VERDICT-F-13 verified on the first try.
Discriminator: before believing any re-injection, print the module's `__file__`
from inside the tree you think you are testing and check it is that tree. The
harness's own verifier already sets PYTHONPATH; the agent-facing contract never
says to. Filed as VERDICT-F-43.

## 2026-09-02 (run 9) — "the coverage gate is live in both directions" was premature

Run 8 declared the changed-files coverage gate live on the strength of two
consecutive measured numbers. Its first firing, this run, was a false alarm:
91% to 78% blended, while production changed-line coverage went 97% to 100%. The
percent includes test files, and test files pay a structural unexercised tax —
imports, `def test_*` lines, decorators and every fixture body execute outside
any `test_function` dynamic context, so the metric counts them unexercised
forever. The number therefore moves with how much of a diff is test code, which
for this project's mutation-campaign releases is most of it.
Discriminator: before reading a blended ratio as a trend, split it by the thing
that changed and check the parts move together. Two runs agreeing on a number is
not evidence that the number measures what its name says. Filed as VERDICT-F-44.

## 2026-09-03 (run 10) — a re-injection can measure the right file and the wrong bytecode

Re-measuring VERDICT-F-48's five mutants in a scratch copy, isolated exactly as
the contract 0.73.0 had just added says to, read 4 of 5: mutant M3 (validate.py's
state-validator `continue` becoming `break`) reported SURVIVED. It had not
survived. `cp -a` carries `__pycache__`, and CPython validates a cached .pyc on
the source's size and its mtime truncated to whole seconds. M2 and M3 both
replace a `continue` with a `break`, so both files are 31075 bytes, and both
landed at mtime second 1788400567 — so M3's import silently ran M2's bytecode
and the mutation was never executed. Swept the cache, and it was killed: 5 of 5.
The prescribed check did not help, and cannot: `verdict_mcp.validate.__file__`
printed the correct scratch path in both directions.
What stopped the false finding was the shape, not any single result. Four of five
biting where the two sibling mutants of the same kind both bit is an instrument
fault before it is a coverage gap — the same reasoning run 9 used when four of
four passing turned out to be an instrument reading zero.
Discriminator: before believing a re-injection, delete `__pycache__` (or set
PYTHONDONTWRITEBYTECODE) between injections. Path isolation and bytecode
isolation are two different claims, and only one of them is checkable by
printing a path. Filed as VERDICT-F-50.

## 2026-09-03 (run 10) — a guard fix verified only in the shape the finding quoted

VERDICT-F-42 was reported with a command in its title, 0.71.0 made that exact
command deny, three tests were written, and the changelog closed it. Moving
`--remove-files` after the archive name — legal GNU tar, and the way most people
would write it — is still permitted at HEAD, because the new loop treats any
option containing the letter `f` as taking an argument and `--remove-files`
swallows the operand behind it. All three new tests use the token order the
finding's title happened to use. I kept the id rather than minting a new one,
following the 2026-09-02 lesson: when a fix lands halfway the wording changes
and the file does not.
Discriminator: when verifying a fix to a parser or a guard, vary the input along
the axis the finding did not — argument order, long-form spelling, separated
flags. A fix that passes only the reported spelling has been tested against the
sentence, not the behaviour, and the diff-coverage report will usually say so
first: the two unexercised production lines in this range were the branch the
bypass walks through.
