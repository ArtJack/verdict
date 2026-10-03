# Changelog

Plugin and `verdict-mcp` share one version line; `.claude-plugin/plugin.json` and
`pyproject.toml` are bumped together.

Releases 0.1.0 to 0.76.0 are in
[docs/changelog/CHANGELOG-0.1.0-0.76.0.md](docs/changelog/CHANGELOG-0.1.0-0.76.0.md), verbatim.
They moved there on 2026-10-03, when this file outgrew what the Claude directory's validator
will read: at 250 KB it was read, at 267 KB it held 0.90.3 for "Files or downloads the
validator couldn't inspect". The limit is most likely 256 KiB.

## 0.90.3 — 2026-10-03 · "the guard that was not there"

A safety release, from a full audit of the agent and the plugin at `b7c30a8` (six independent
reviews, 2026-10-02; the ids below — H-D, O-S, K-D, D-D, T — are that audit's). Nothing here
changes what the tester judges; everything here changes what it can touch.

**`verdict-finalize` wrote the report wherever the judgment pointed.** `judgment.report` was
honoured as written, so an absolute path or a `..` named any `*.md` in the code under test —
the README of a team-mode checkout, proven by overwriting one — and a `topic` of `../../x`
climbed out the same way through `mkdir(parents=True)`. The report now lives in one place,
`reports/<name>.md` directly under the QA root, and finalize refuses anything else with
nothing written; the validator refuses the same shape in a state, at rest included. A survey
of 16 real QA roots and 132 history rows found no other shape, so the rule refuses nothing a
run has ever legitimately written. Mutants H-D-1a/b/c.

**And the rule that fixed it read how the path was spelled.** The release's own gate — an Opus
run the owner asked for before the tag — took the new rule to a scratch checkout and walked
around it five ways, each one exit 0: `.qa/reports` a symlink to the repository, so
`reports/README.md` was the project's README; `reports/x.md` itself a symlink to it; `reports`
pointing at `src/`, where the generated report and `INDEX.md` then landed; `.qa/facts.json` a
symlink to `src/app.py`, and `verdict-facts` wrote the facts over the code under test; and a
judgment naming `reports/INDEX.md`, which replaced the index of every run with one run's
report. A path spelled inside the root is not inside it when a name on the way is a link, and
a second hard link is the same thing with no symlink to look for. Reading the fix back found
the case with no link at all: `--qa-root` is the caller's word, so `verdict-facts --qa-root
src` wrote the facts, the run marker and the test ids into `src/`, and `verdict-finalize
--qa-root src` a state, a report and the run index.

So every writer of a QA root — `verdict-facts`, `verdict-finalize`, `verdict-local`,
`verdict-accept`, `verdict-answer`, `verdict-issues --create` — asks two questions before it
creates or writes anything, and names what it found. Where is the root: under the solo home,
at or under the `.qa/` at the top of a checkout, or outside any checkout. Anywhere else inside
a checkout is the code, a `.qa` that is a link into `src/` resolves there, and inside the
repository under test only its own `.qa/` counts, whatever `VERDICT_HOME` is said to be. And
what is in it: a symlink, a Windows junction or a file with more than one name among the
root's own entries, `reports/` or `findings/` is a write somewhere else. Finalize looks once
more at the one name it is about to open. A judgment cannot name the run index;
`verdict-facts --out` refuses a path that lands in the checkout outside the QA root; the Stop
hook does not write its note through a linked marker. The Bash guard refuses the `ln` that
would build such a root, refuses a hard link that gives a file in the checkout a name in
scratch — the one write no `realpath` can see — and refuses `verdict-issues --create`, which
posts under the maintainer's name.

What it does not refuse was measured too. Links deeper in a root are left alone: testers park
virtualenvs and pytest's temp trees there, and two of the author's own roots carry them. All
sixteen real roots on the author's machine pass both questions in 1–6 ms, a root that does not
exist yet is read through its parent, and a `.qa` linked to a directory outside the checkout
is the caller's business. One thing that used to run is refused on purpose: a `.qa/` deeper in
a checkout — a monorepo package's own — was never a QA root to the write guard, and is not one
to the harness now; the message names the three places. And one rule was written and taken
back before the release: refusing a judgment-named report that an earlier run had rendered
broke seven tests that reuse one report name across runs, and that is a record-keeping
question for the next release, not a containment one.

That gate ended `blocked`, not passed: its response was stopped by the model provider's safety
filter while it wrote up an adversarial section the packet had asked for, and the five
experiments were read from its transcript. The one finding it filed is fixed too — a test of
`usage.project_dir` that failed whenever `CLAUDE_CONFIG_DIR` was set, which a headless gate
with its own config directory always has. Mutants `links a`–`z5`, twenty-nine.

**The re-run, re-scoped so the model was not asked to write bypasses, completed: `pass with
risks`, no release blocker.** It filed five Minor findings, four of them on this release's own
surface, and four are fixed here. The counterfactual's scratch copy still carried secrets its
skip-list missed (`.envrc`, `<name>.env`, `.aws/`, `.git-credentials`) and `copytree` followed
a symlink out of the tree and copied the file it pointed at — the list is wider now, the copy
keeps links as links, and a link resolving outside the tree is dropped. `safe_replacement`
judged a fix line's identifiers by their raw spelling while Python runs their NFKC-normalised
form, so a fullwidth or mathematical spelling of `__globals__` or `eval` read as an unknown
name and slipped the dunder rule; both it and `_names` normalise now, as the interpreter does.
The nightly guide never mentioned the environment allowlist or `--env-passthrough`; it does.
The suite's one-in-a-blue-moon red — a coverage-scratch test that read the machine's shared
temp directory and saw another run's directory there — is the flaky test fixed two commits up,
now scoped to a temp directory of its own. Five more mutants (`gate2 F-1a`–`F-4b`). Left for
0.91.0, and said so to the owner: the guard refuses `git archive | (cd <scratch> && tar xf -)`,
a `cd` inside a group that is a pipeline stage — a false denial that fails safe, and whose fix
is in the guard's riskiest path.

**The counterfactual ran a model's expression in your checkout.** To prove a claim,
`verdict-local` asks the small model for one expression and runs it before and after flipping a
line. The "before" run happened in the real tree, with the operator's whole environment, and
the only checks on the expression were that it was one line and named the function. Measured on
2026-10-02 with a fake gateway: an expression that wrote `os.getcwd()` through
`open(...).write(...)` passed every check, and its marker read the checkout's own path with
`env_has_token=True`; the scratch copy it ran in second was not excluding `.env` files. On the
author's Sales nightly the model had already been asked to probe marketplace-facing modules.
Now the expression is read as a syntax tree before anything starts — one call on `m` to the
function under probe, literal arguments only, anything else refused as `probe_unsafe` — and
both runs happen in one scratch copy with an allowlisted environment and no secret files.
The line the model writes in place of the suspected one is code as well, and an environment
without the token does not stop a line that opens the file the token lives in: a fix may use
only names the function already uses, a few builtins and keywords — no `import`, no new name,
no dunder, no f-string — or it is refused as `fix_unsafe` before any copy is made. Every
probe, refused or run, is written to `facts.json`, and `probes: off` in the profile switches
the whole thing off. A gate with no Python interpreter disables proving instead of borrowing
Verdict's own, and a quoted interpreter path is one word on Windows too — the release's first
Windows CI run found the new lookup splitting `"C:\Program Files\…\python.exe"` at the space. Deliberately not here: resource limits and a network block on the probe — the
project's own module still runs when it is imported, as it does under its test suite —
telling an invalid fix from an unreachable call, and probing methods: a method needs a nested
call, and nested calls are what was closed. Mutants O-S-1a–e, five of five killed.

**The one session that skips permissions ran with no guard.** The GitHub Action's run mode
copied `agents/verdict.md` into the checkout and launched `claude -p … --setting-sources
project --dangerously-skip-permissions`; `hooks/hooks.json` was never registered, so the
`VERDICT_STRICT=1` it exported armed nothing. The Action now loads the whole plugin from its
own checkout (`--plugin-dir`) and runs the tester directly (`--agent verdict`), passes
`--strict-mcp-config`, and gates on `run_number + 1` so a pass that crashed cannot re-serve
the committed state as tonight's verdict. A `max-budget-usd` input hands the CLI a ceiling.
Verified against the CLI's own `--help` (2.1.281) and the documented flags, not against a
live runner — the first real run of this mode is owed.

**The Bash guard was off in every interactive session, and where it was on it could be walked
around.** It returned on `VERDICT_STRICT` before it had read the event, so a tester started
from a desktop session — 83% of Verdict's tokens, by the author's own measure — had its Write
and Edit refused while its `rm`, `sed -i` and `git checkout` went through. Claude Code sends
`agent_id` and `agent_type` in every hook input fired inside a subagent, so the guard is armed
by the agent the event names, through the one rule all three hooks now share (the write guard
and the Stop hook used to disagree about whose name counts). The user's own shell stays
unguarded in ordinary sessions, as before; a desktop tester now runs under the guard a
headless one always had. The audit fed the guard 1,631 command strings under both interpreters
a plugin runs on. Of those that write the code under test, 86 that were a spelling rather than
a program are closed: formatters in their writing shape (`black .`, `ruff format`,
`prettier --write`, also behind `uvx`, `npx` and `python -m`), `git log --output=`,
`git checkout-index`, `>&file` and `N<>`, `bash -lc`, `(rm f)`, `find -exec sed -i`,
`xargs bash -c`, `sudo -n rm`, `gzip`, `sort -o`, and a directory lost after `cd -` or `pushd`.
And 48 of the 60 commands it wrongly refused now pass, among them
`cd .qa && pytest | tee report.log`, every `sed -i` inside `.qa/` and a heredoc whose body
began with `rm`. Each rule was checked against the program it models — 81 shapes run in a real
bash and 37 in a real git, the guard refusing exactly the ones that changed something outside
`.qa/` — which is how `git clean -n --no-dry-run -f` was found: it deletes, and the guard's
oldest exemption believed any `--dry-run` it saw.

**The maintainer's pens were refused as files and open as commands.** `accepted.json` and
`answers.json` are now refused to every writer in every mode (they were refused only under
strict mode or to a caller the event named). But `verdict-accept` and `verdict-answer`
themselves were unknown commands to the Bash guard: a tester could accept its own findings'
risks by running the pen. An armed guard refuses both, by every spelling
(`python -m verdict_mcp.accept`, the script path, behind `env` or `bash -c`); `--list` reads
and passes, and the maintainer's own shell is not armed. Writing that rule found one more:
an uncaught exception in the guard is exit 1, which Claude Code reads as a broken hook and
lets the command run — a sentinel joined into a path did it, and so did a NUL byte in a
command line (`echo x > src/app.py\0`; bash drops the NUL and writes). While armed, a command
the guard cannot read is refused with the reason, never waved through.

Measured: 80 defects put back one at a time against the new hook tests in scratch copies, 79
recorded killed and one not recorded — the list and its outcomes are
`eval/sweeps/2026-10-02-hooks-0903.json`; twenty of them, one per defect class plus the pen,
the NUL byte and the refusal on failure, are pinned in the catalogue the whole suite is held
to, and `pin_check` killed twenty of twenty. Not in this release, and not claimed: a program that writes through its own code (an
interpreter, a build, `npm run format`, a script read from a file or a pipe), a variable set on
the same line (`T=$(mktemp -d) && cp -a . "$T"` is still refused — use a literal path), and
Windows, where the new command tables were not run.

**The headless session saw the operator's whole shell.** `verdict-run` handed `claude` its
entire environment — cloud and `gh`/`op` tokens, a `GIT_DIR` from a hook, the `PYTHONPATH`
0.90.1 stopped leaking — and the session hands its environment to every Bash call the tester
makes, hence to the project's own tests and whatever they spawn. The child now receives an
allowlist (`PATH`, `HOME`, locale, temp, proxies and CAs, `CLAUDE_*`, `ANTHROPIC_*`,
`VERDICT_*`), the owner's own `env -i` recipe for asked gates built in; `--env-passthrough`
names anything a project's gates need beyond it. `--strict-mcp-config` is always passed:
user-scope MCP servers live in `~/.claude.json`, not in settings, and a
`--dangerously-skip-permissions` night could reach every one of them — mail, deploys, the
lab — from the outer session; `--mcp-config` names the ones a profile wants. `--max-budget-usd`
reaches the CLI (budgets were stated in prose and filled, never used). `run_local` no longer
writes the gateway token into the runner's own `os.environ` for the night. The local tier's
default model is `chat`, not the `qwen3` alias that answers nothing. The eval's control arm is
re-derived with the launch, as its tripwire test demands: `plain_argv` carries
`--strict-mcp-config` and the plain environment passes through the same allowlist, so rows
measured before 0.90.3 ran both arms with the operator's shell and user-scope MCP servers.

**The state validator spoke about files that were not its own.** As a PostToolUse hook it
validated every file named `state.json` anywhere: a user's own app settings got "15 problems"
and exit 2 in a session that had never run Verdict. It checks only inside a QA root now — the
solo home or a `.qa/` beside a `.git` — for `findings/<ID>.json` as well. Mutant T3-1.

**Five skills duplicated five commands in the slash menu.** Claude Code loads `skills/*/SKILL.md`
as plugin skills too, so `/verdict:flake` sat beside `/verdict:verdict-flaky-triage`. The five
carry `user-invocable: false`: hidden from the `/` menu, still there for any agent that reads
them, which is what they are for.

**Three smaller things a stranger hit first.** `uses: ArtJack/verdict@v0` in the README named a
ref that did not exist — `release.yml` now moves the major-version tag on every release. The
weekly `eval.yml` piped through `tee` without `pipefail` and reported success with no API key in
the repository's secrets; it runs under `bash -eo pipefail` and says when the key is missing.
`verdict-mcp --help` started the server and sat on stdin; it answers now, and refuses a TTY
with the command that starts it properly. And CI runs the hooks' tests on Python 3.9, the
`python3` a stock Mac starts them with: the matrix had 3.10 and 3.13, and the floor was an AST
shape check that a 3.10-only stdlib call would have passed.

**Also since 0.90.2, merged without a changelog entry:** #129 pins `effort: xhigh` in the
agent's frontmatter so a tester's effort is chosen, not inherited from the session that
spawned it; #131 adds the hygiene scan (junk, near-certain secret exposures and leads on every
`verdict-facts` run, three tiers, `hygiene: off` in the profile); #132 files tier-1 exposures
as findings through the harness, keeps the junk ledger in `hygiene-ledger.json`, and resolves
nothing on silence.

**Deliberately not in this release.** The rest of the audit: the silence floor that closes
unmentioned findings (H-D-2), a `pass` over a red gate (H-D-3), the ledger keyed by hash
(H-D-7), the branch run that writes the main record (H-D-8) and the counts parser (H-D-9/10)
are the next release, harness-only; the runner's stream-json flight recorder, process groups
and timeout retry are the one after. The README's trust table and exit-code line are corrected
where this release changed them, and two false facts are fixed (the library's star count, the
MCP server's dependencies); the rest of the docs ledger — the control arm's parity result on
the first screen, what a run costs, the stale badges and roadmap — is not in this release. No
prompt or command file changed, so nothing here needed a paired eval.

## 0.90.2 — 2026-09-23 · "a refused run asks nothing"

**A refused finalize kept the questions it asked.** `verdict-finalize` folded the judgment's
questions into `questions.json` — an id minted for each, every waiting answer marked
acknowledged — before the validator had judged the state. So a run it refused still parked its
questions, at a run number no `state.json` or `runs.jsonl` ever held, and swallowed the answers
it acknowledged: the next recorded run was never told they had arrived. Found on a copy of the
Sales QA root on 2026-09-18: a local run refused for a duplicate finding hash left its
inherited-conflict question on the ledger as SALES-Q-17, and the next successful finalize
reported it "already on the ledger". The ledger is now written only once the state is accepted,
and the report rendered for the validator goes with a refusal too — removed, or the file it
overwrote put back — instead of staying behind as a "run N" the record never held. Mutant P44.

## 0.90.1 — 2026-09-18 · "the path stays in the child"

**0.90.0's runner fix leaked into the project's tests.** To let a runner started from a checkout
find its own harness, 0.90.0 put the runner's source root on `PYTHONPATH` for the harness child
— and every process that child started inherited it. From an installed verdict that root is
the whole `site-packages` of Verdict's own environment, so the project's test command imported
Verdict's packages ahead of its own. Found on the author's Sales nightly the evening 0.90.0
shipped, in the lab-down drill before the nightly was switched over: Sales' pytest exited 2 with
925 of ~3,450 tests collected, the sweep read the gate as failed and refused itself, and the
test-id set looked as if 2,561 tests had been deleted. The harness child now receives the path
as an argument and puts it on its own `sys.path` only; the environment is inherited untouched.
A sweep started through `verdict-run` from any installed 0.90.0 over a project with its own
environment is affected — upgrade. Mutant P42 (and P41 re-anchored on the new launch).

**A finding file named with the project's own numbering was refused.** 0.90.0 taught the id rule
to read ids without a prefix, so the next Sales id is `F-163`, the record's own numbering. But
the finding-file rule still demanded `<PROJECT>-F-<n>.json`. The dress rehearsal of the Sales
nightly filed `findings/F-163.json` through `F-166.json` and finalize refused all four, which
lost the whole night at its last step. The same rule is why the write-time check never
recognised Sales' finding files, and plausibly why its runs had been filing findings inline. A
finding file is the finding's id, with the project's prefix or with none. Mutant P43.

## 0.90.0 — 2026-09-18 · "the local tier"

**Every run nobody asked for spends zero Claude tokens.** `verdict-run --on-drift
{model,local,none}` decides what a night does when the sweep is blocked: spend a Claude run
(the default, unchanged), hand it to `verdict-local` against a gateway, or do nothing and exit
5. `local` and `none` imply `--skip-unless-drift` and **cannot reach the `claude` CLI at all** —
that is the property, not a side effect. A local night with no endpoint is refused before
anything runs, exit 2, because the alternative is the one an unattended run must never have:
quietly spending the expensive model instead. A blocked sweep with a dead gateway writes
nothing and clears the run marker its own facts pass left, so tomorrow is not told that tonight
died mid-flight. A sweep that *is* allowed while the gateway is down still runs, and says in
its own `not_tested` that the model was unreachable. The decision table is in
[docs/nightly.md](docs/nightly.md).

**What a shadow run on a real project found, and fixed.** The seeded fixtures passed; then the
tier ran on the author's own Sales project, against a copy of its QA state, and failed four ways
the fixtures could not show. It never finalized: the record already held two findings claiming
one site (a class conflict an earlier run left), the tier cannot settle that, and the refusal
would have lost every night. It ran for four hours — a day's range of 744 changed lines no test
executes and no time budget. It would have filed 27 unproven Minor readings onto a backlog of 69.
And not one counterfactual ran, because `core/src/sales_core/cli.py` was imported from the
repository root and the package's own imports reached a stale install elsewhere. Now: a class
conflict between two findings a run only carries is asked as a question, once, instead of
refused — anything the run files is still held to the rule; a night on a project with a record
gets an hour, 24 functions and 12 proofs, and says what it skipped; in a delta an unproven
reading is a **lead** — listed in the report and the focus list, not filed — while a proven one, a
failing test, a skip without expiry, measured flakiness and a returning defect still are; and a
proof imports through the project's own root (pytest's `pythonpath`, else the directory above the
package chain). The re-run then found a fifth: two skip markers with the same reason in one
test file became two findings with one identity, and finalize refused the night again. Skips
are one finding per file and reason now, and any second finding with an identity this run
already filed is folded into the first. Mutants P28–P35.

**The second night.** Replaying that first night's output through finalize showed the next
failure before it happened: the skip markers it filed are still in the code tomorrow, the second
night files them again under new ids, and a state holding one identity under two ids is refused —
every night after the first would have been lost. An identity the record already holds is now
that finding: open, it is carried by id and not filed again; accepted or withdrawn, it stays the
decision a person made; resolved, it comes back under its own id and is REGRESSED. A failing test
this engine already filed is not classified again either — the model words its title differently
each night, so the identity rule alone would have added a duplicate every night the test stayed
red, at about ninety seconds of the night's budget each. `not_tested` counts both. Mutants
P36–P38.

**One numbering per record.** The night that finalized minted `SALES-F-1` beside `F-162`: the
harness's next-id rule only recognised prefixed ids (`PRICER-F-003`), so none of Sales' 75
matched and a new sequence started under the key's name. Nothing collided, but a record with two
numberings is one nobody can read by eye. Ids without a prefix are read now, and the next Sales
id is `F-163`. Mutant P39.

**Then the second night ran, and finalized** — in 7 minutes 48 seconds, the four skip findings
recognised as already on the record, 73 carried, none resolved by silence. It ran at the commit
the first night had measured, and that showed one more thing: a range with nothing in it fell
through to the reading map, so the run ranked the whole repository's least-covered files and
reported its empty range as too large for its caps. A range with nothing in it now reads
nothing. (A scheduled night never meets this — `--skip-unless-drift` skips an unmoved HEAD before
the engine starts — but a run started by hand does.) Mutant P40.

**A nightly that never swept.** The author's own Sales nightly starts the runner from a checkout
(`python3 src/verdict_mcp/runner.py`) with an interpreter that never installed the package, and
the runner started the harness as `python -m verdict_mcp.harness` under that same interpreter.
From 2026-09-17, the first night HEAD moved after the model-free sweep was switched on, every
night ended `No module named 'verdict_mcp'` — exit 5, "needs a run", nothing measured, nothing
spent. The harness child is now handed the runner's own source root on `PYTHONPATH`, ahead of
whatever was set, so a runner finds the code it is, installed or not. Reproduced with that
interpreter: the same call went from `ModuleNotFoundError` to the harness's usage line. Mutant P41.

**The mutation campaign could not start.** Merging main into this release brought #124's fixture
hygiene tests, which stage every fixture the way the eval harness does — listing its files as
git sees them — and `pin_check` copies the tree into a directory git knows nothing about. The
control run went red before a single mutant was applied, on main as much as here. The scratch
copy is now a checkout of its own: one commit of the tree in hand, none of the original's
history. Mutant A2.

**A regression is REGRESSED, and an open finding is not filed twice.** The same proof showed the
tier blind to the state it carried: the rounding defect the previous run had resolved came back,
the engine described it correctly, and filed it as NEW — a regression reported as news, ranked
below everything. The same blindness filed a second finding for a defect that was already open,
which on a project with a backlog is a new duplicate every night the function changes. A claim is
now matched to an earlier finding before it is filed: first by the finding's anchors (a line it
cited, unchanged, is in this function again — measured), else by the function's name when the
finding names it and cites no other file (said so in the evidence, because it is weaker). A
resolved match is re-filed under its own id, so the harness calls it REGRESSED; an open or
accepted one is not filed again, and `not_tested` counts the claims that were held back. Names
that say nothing (`main`, `run`) never match, and a withdrawn finding never does. Mutants P22–P27.

**A red gate is a `fail`.** The zero-false-greens gate this release is measured by caught the
tier under-rating a red suite: on the seeded delta it carried all five prior findings honestly,
filed the new defect, and still said `pass with risks` over three failing tests — because the
verdict was arithmetic over finding severities and a reading nobody proved is held at Minor. A
failing gate now outranks the findings. A strong model classifies a failure and may ship anyway;
this one cannot be trusted to, so a person or a real model decides.

**The window a question arrives in.** Ollama serves every model at 4,096 tokens unless told
otherwise, and past that it keeps only the end of the prompt — the instructions first, and
`/no_think` with them. Measured through the author's gateway: a ~6k-token prompt with a code word
on its first line arrived as 2,050 tokens and the model invented the code; asked with `num_ctx:
8192` it arrived whole and answered correctly in 49 seconds instead of 137. `verdict-local` now
asks for 8,192 on every request (`--num-ctx`, `VERDICT_LOCAL_NUM_CTX`), so nobody's server needs
root to be usable, and a gateway that refuses the parameter is asked again without it. The eval
rig's `--engine local` also stopped printing the engine's summary into its result JSON.

**`verdict-local` is a delta now, and it cannot close a finding by silence.** 0.89.0 said
plainly that it must not be pointed at a project that already has Verdict state. Here is why,
and here is the fix. It wrote `still_open: []`, and `merge()` reads an unmentioned finding as
resolved unless five or more AND over half the backlog goes quiet at once — so a key with four
open findings lost all four to a run that never looked at them, and a key with sixty lost the
ten whose code had drifted. Now every prior open finding leaves a delta in exactly one of three
places: **resolved** by a measured fail→pass on a test somebody chose (`verification_test`, or
one the collector saw for the first time this run — the `harness._chosen` rule, and the only
resolution path there is), **carried by id** because its cited code is where it was, or
**re-filed** under its own id with the drift that moved it, because `still_open` over changed
code is refused by the harness and silence would close it. The invariant — every prior open id
is in one of the three — is asserted before anything is finalized, and a gap refuses the run
rather than writing a state.

**The verdict is monotone.** Six functions read by an 8B model may make a verdict worse or
leave it alone, never better. Two verdicts are sticky, for different reasons: a previous `fail`
stays `fail` because something with judgment found a defect and nothing here has the standing to
say it is gone, and a previous `blocked` stays `blocked` because a previous run could not test
at all — an environment, a tool, a requirement nobody answered — and this engine cannot tell
whether that reason has cleared. The second was the more expensive one to get wrong: it turns
the gate's exit 3 into exit 0. A carried `blocked` says so in `not_tested` and in the report.
No gate counts is `blocked`, not `pass`. An open Blocker is `fail` whatever the standing verdict
was. Anything newly filed, an open Critical, or changed lines nothing executed caps the run at
`pass with risks`.

**A quarantine is released by measurement, not by its expiry date.** A due entry's test is run
five times; 5/5 passes releases it and the FLAKY finding is re-filed with that measurement
rather than left standing on words that are no longer true. Anything less moves the expiry with
the counts it measured. A project with no `test_one_cmd` keeps the quarantine, parks a question
and says so in `not_tested` — it never releases one it could not measure.

**A branch no longer writes the trunk's record.** `verdict-local --range BASE..HEAD` / `--base
REF` (through the merge base) now **require** `--qa-root`: in a linked worktree `derive_key`
returns the *main* worktree's key, so a judgment about an unmerged branch resolved and would
have overwritten the project's own state. `collect()` takes the range from the caller, so diff
coverage exists on a run that has no previous state — the one measurement a PR gate exists to
make. `--reference-state` reads the real state read-only to say which of its open findings the
diff touches. A range with no parseable Python in it reads nothing, says so in one fixed
sentence, and cannot rise above `pass with risks`; it used to fall through to the reading map
and report a clean pass over files the change never touched. Caps: six files, twenty-four
functions, six counterfactuals, two minutes a call, fifteen minutes of model time — and when a
cap bites, the run says how many candidates it never looked at.

**The record says who judged it.** `last_run.engine`, `last_run.model: local:<name>` and
`last_run.local` (calls, tokens, answered, unanswered, retries, transport errors, functions
read and skipped, seconds, and the gateway's *hostname* — never its credential). The report
gains a **Judge** line beside the Harness line, ending `no Claude tokens spent`; a sweep's
reads `none (model-free sweep)`. 0.89.0's `usage.jsonl` row carries `engine`, a Claude bill of
a measured zero, and those counters under `local`. `facts.needs_claude` names what a real model
run is still owed, each entry something the harness counted. The gate prints at most fifteen
lines, ending `Claude tokens: 0`.

**The housekeeping it never did.** The whole profile reaches `collect()`, so `test_one_cmd`,
`test_ids_cmd` and `coverage_suite_cmd` exist here as they do for the agent — without them no
fix could be verified, no id ledger was written, and diff coverage was permanently unavailable,
which are the measurements the safety rules above rest on. Plus the run marker before the
gates, last run's finding files moved aside, `test-ids.txt` written, and the gateway's
liveliness asked *before* the suite instead of at the first question. A run that got no answers
writes no state and leaves its marker: a judgment assembled from no answers is a run that
measured the suite and called it QA.

**Four smaller things a nightly would have found later.** The state on disk is carried whether
or not `--delta` was passed, so one missing argument cannot restore the old behaviour. A prior
state with no verdict in it reads as `blocked` — unknown, not clean. One test gets one
quarantine entry and one finding, with this run's measurement winning, instead of last night's
counts sitting beside tonight's with nothing to say which expiry governs. And `next_run_focus`
and `release_blockers` are deduplicated and capped, because a list a nightly appends to forever
is a list nobody reads.

**And one line in the sweep (P-32):** `sweep_judgment` wrote `verified_intact: []`, so the
cheapest run in the system silently deleted the list the *next* sweep is built to guard.

Eighteen pinned mutants (P1–P18), whole suite. P4 — "the verdict is computed from this run's
findings only" — **survived its first campaign**, and the survivor was the instrument working:
the test asserted a standing `fail` beside *nothing filed*, where the rule cannot fire. The
missing case (a standing `fail` beside a freshly filed Minor) is pinned now, and P18 pins the
`blocked` half beside it. `run_eval.py --engine local` runs the pricer
fixture through the local engine against the same answer key, with an injectable engine so the
wiring is a unit test rather than a nightly. No change to `agents/verdict.md`, `commands/`,
`skills/` or `hooks/`, so no eval payment.

## 0.89.0 — 2026-09-17 · "a default nobody chose"

**Who was spending it.** A census of the author's own machine — every Verdict-agent run in
Claude Code's transcripts, tokens summed per request id (`eval/usage_census.py`) — found 232
runs in five weeks, about $1,400 at list price, and the scheduled nightly everybody suspected
was a sixth of it. 215 runs had been spawned from interactive sessions; 214 named no model,
so `model: inherit` handed them the most expensive model on the account. A run is turns times
a growing context — median 33 requests, the largest climbing from 41k to 427k tokens — and
the 15 largest runs are 27% of all cache read. Nothing had recorded any of it. The table,
and what follows from it, is in [eval/README.md](eval/README.md#where-the-tokens-go--a-census-of-the-authors-own-runs).

**The bill is written down where the run is finalized.** `verdict-finalize` appends one line
per run to `<qa-root>/usage.jsonl` — requests, the four token counts, requests per model id,
the model's wall time, the entrypoint and effort level — read from the session's own
transcript, found by the session id the CLI exports and by the run's own `measured_at`
printed inside it, so another agent working in the same session is not billed to this run.
It sits beside the state, not in the signed row: signing telemetry would make every older
state re-derive to a different row. One thing does enter the state — when no operator
exported `VERDICT_MODEL`, `last_run.model` is the model the transcript names, measured,
instead of absent. An unreadable bill is recorded as unknown, never as zero, and can never
fail a run. The reader moved from `eval/` into the package (`verdict_mcp.usage`), because
the wheel ships nothing from `eval/`.

**The run that never finalized is told, once.** The costliest failure leaves no state at
all: the tester measures, investigates, and ends its turn without `verdict-finalize`. It is
the recorded signature of a cheaper model — `state_missing` zeroes an eval score by protocol —
and the stop hook went silent on exactly that case at its first `is_file()`. `verdict-facts`
now writes the session into the run marker, and the hook speaks when a **Verdict** agent
stops, in **that** session, with the marker still there. Identity, not a time window: a
marker another night left behind, or a parallel agent finishing beside a run in progress,
says nothing. Once per marker; every doubt fails open.

**An answer-key row that read wording, corrected in public.** The one row behind the
published Opus-against-Sonnet gap (3 of 3 against 0 of 2) could not be earned by the finding
the contract asks for. Since 0.84.0 one class is one finding, so the class-owning finding went
to the first truncation row and the second could only be earned by some *other* finding
containing the word `invoice`. The two rows now share `class_of`, as the liar key's have since
2026-09-07; the archived corpus run scores 7/7 before and after; a new test scores a finding
that never looks past the failing site at one row, not two, and fails on the unamended key.
The published claim stands with a dated correction beside it: unverified until the next
paired payment.

**Two harness defects that were being read as a model's.** The first paired payment of this
release found them, and neither is in the prompt. `verdict-facts --out` has always said "also
write facts.json here" and wrote it there *instead*: a Sonnet run that asked for a copy left
the QA root without its facts, every harness signal read "not measured", and a run that scores
**9 of 9 on substance** — above Opus's 8/9 · 9/9 · 8/9 on the same fixture that hour — was
zeroed as hand-written. It is a second copy now, as documented. And in print mode the CLI waits
600 seconds for background tasks, then kills them: a headless session that delegates the tester
in the background and ends its turn ("I'll report back when it completes") loses any run longer
than ten minutes — judgment half-written, no state, exit 5. Two Sonnet runs of three died that
way; it is the first scheduled night's lost run again. `verdict-run` and the eval rig now export
`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` (an operator's own value wins); the bound on a run is
the runner's `--timeout-s`, which kills the process rather than the work. Three more pinned
mutants (Q13–Q15). The numbers, and what they do and do not say about Sonnet, are in
[eval/README.md](eval/README.md#the-model-axis--opus-against-sonnet-paired).
Re-run on the fixed harness the same day, n=3 per arm: seeded delta **Sonnet 26/27, Opus 25/27**;
honesty 18/18 both; at about 40% of Opus's bill and with no more turns. On root cause Sonnet's
one recorded run is 10/10 and the "does not generalise" claim is refuted (it named the sibling
sites three times of three) — but two runs of three answered the charter as a diagnosis and never
called the harness, so the acceptance rule set beforehand (no hard fail in nine) was not met.
Gate the run number and re-ask; that is what `verdict-run` does and what an orchestrator should.

**Docs that had gone stale.** The FAQ still said Sonnet hard-fails the eval — a row
superseded the day it was written. It now gives the three local answers in order of cost, and
says plainly that `verdict-local` **must not be pointed at a project that already has Verdict
state**: it does not carry earlier findings forward, and the harness reads that silence as
resolution. It is also unsafe in a branch worktree (it resolves the *main* state root) and on
a repository with no Python (it reads nothing and says `pass`). All three are fixed in the
next release, which makes local mode a delta and a gate; until then it is a first pass over
a fresh Python project, which is what it was measured as. `README-pypi.md` gains the three
commands its table had forgotten.

Fifteen pinned mutants (Q1–Q15), whole-suite. No change to `agents/verdict.md`, so no eval
payment. Known and tracked separately: four older catalogue anchors (T02, 0.78.0 R2/R5,
0.79.0 S7) no longer match the source they were written against, so a full `pin_check` would
report them stale — found by checking every anchor while adding these.

## 0.88.0 — 2026-09-09 · "prove the line, or hold the severity"

**Local mode proves what it claims.** `verdict-local` now flips the suspected line in a
scratch copy and watches the value follow: the model proposes one expression and one
replacement line, and the harness does the rest — a copy without `.git` or the
virtualenv, its own source first on `PYTHONPATH`, bytecode writing off and `__pycache__`
swept, and the import verified to resolve inside the copy before anything is believed.
Three outcomes, all useful: the value moves (`proven`, and the finding says so with the
before and after), the value does not move (the claim is withdrawn before it is ever
filed), or the probe cannot run (still a hypothesis, with the reason printed).

**A reading nobody executed cannot outrank a test that ran.** Severity from reading alone
is held at Minor until a counterfactual moves it. Measured on boltons, a real 30-module
library: the local model filed 35 findings from reading, every one `REAL_DEFECT`, 34 of
them Major or above. A tester whose every finding is Critical has no severity at all.

**A smaller prompt, where the harness had already taken the work over.** Section 6
restated what `verdict-facts` and `verdict-finalize` now decide themselves — the run type
and why, each finding's age, the state, the report and the INDEX row — and section 7
listed twelve paths where the agent writes four. That is 1,070 tokens off **every turn**,
and measured on the root-cause fixture it is 18% fewer output tokens at the same number of
requests.

Two things did *not* ship, and the eval is why. Turning the class link into an instruction
to run `grep` bought extra turns and won nothing (37% dearer, no rows gained). And one
trimmed path was load-bearing: the compressed §7 stopped naming `judgment.json`, a run
wrote its judgment outside the QA root, and an otherwise correct run — nine findings, a
`fail` verdict, a full report — scored zero on a hard failure, because a judgment the
harness cannot find is indistinguishable from state written by hand. Both are in
[eval/README.md](eval/README.md) with their numbers.

## 0.87.0 — 2026-09-09 · "the harness drives, the model answers"

**Local mode: the harness drives, a small model answers.** `verdict-local` is a
second way to run: Python does everything deterministic — measure the gates, read
coverage, slice the source into functions, validate the JSON, assemble the state — and
the model answers one bounded question at a time about one function, with a few hundred
tokens of context and a schema it must fill. Nothing accumulates between calls, so the
context never grows and a weak model is never asked to hold a plan in its head.

Why it exists: the agent shape cannot shrink to a 7B model. Measured on this project's
own runs, a run is ~38 model turns each re-reading ~53k tokens, of which ~19k is fixed
preamble before the investigation starts; a 40k-window model has nothing left to think
with. Measured the other way, on a local `qwen3:8b` behind a LiteLLM gateway: 6 model
calls, 1,403 input tokens, 3,055 output, two real defects found in the eval's own
baseline fixture (the `>` that should be `>=`, and `round()` where the spec says
half-up), scored 4/10 against the same answer key Opus is scored against, with no hard
failures and the harness chain intact.

What it does not do is in the report, every run: nothing is executed, no counterfactual
is applied, no history is read, the suite is not judged. Every finding it files is
`confidence: hypothesis`, and the validator is what writes it — a claim that cannot pass
the same check the agent's findings pass is never filed.

**Which account pays, and which endpoint answers.** `verdict-run --env-file <path>`
merges a `KEY=VALUE` file into the run's environment, so a scheduled run can spend a
dedicated subscription (`CLAUDE_CONFIG_DIR`) or a gateway serving a local model
(`ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN`) instead of whatever the CLI happens to
be signed into — with the credential in a file the operator owns rather than in a
crontab or a log. Two traps are handled rather than documented away: a signed-in CLI
sends its own credential and ignores the gateway's, so a gateway needs a config
directory with no login in it; and a config directory the CLI has never seen refuses
bypass-permissions mode *in silence*, so a headless run there exits 0 having done
nothing at all. The runner seeds the trust flags itself and prints what it resolved.
Both eval harnesses take the same `--env-file`.

**A weekly limit is not a session limit.** The runner knew only the phrase "session
limit", so an exhausted weekly allowance read as an ordinary failure: it spent its one
retry on a second identical refusal and reported a lost run, leaving the real reason in
a log nobody was reading. It now stops on the first refusal and repeats the CLI's own
sentence, including the reset time; `eval/swebench.py` stops the whole batch rather than
writing "never ran" against every remaining instance. A session limit is still slept
through, as before.

**Measurement.** `eval/run_eval.py --pair-model <model>` runs the same fixture and the
same prompt on two models interleaved, one table, per-row deltas — the model axis beside
the prompt axis added in 0.84.0. Every run now reports its own token bill, read from the
session transcript (the main session *and* its subagents, summed per request id, since
the CLI's result line covers only the last turn). `eval/swebench.py` carries the same
figures per instance.

## 0.86.0 — 2026-09-08 · "a night that spends no model"

Step 4 of the work plan (engineering-docs, verdict pack §5a), Measurement: one
coverage run feeding three facts, structured test results before dialects, and
a nightly that runs the model only when something a finding rests on moved.
Harness only — no prompt change, no eval payment; three times now a fact has
taught the behaviour without a prompt line.

**The reading map (T-16).** The suite runs under coverage.py whenever the
profile names `coverage_suite_cmd` — a baseline and an empty-diff delta used to
measure nothing. `facts.reading_map` is every production module the tracer
saw, least covered first, with the open findings that cite it and the last run
that did; every git-tracked `.py` file the suite never imported, at 0% and
said so; and `never_examined`, the least-covered modules no finding has ever
cited. The report renders it as **Reading map**. Boltons runs 2–4 produced 13
of the project's 15 highest-severity findings from its six lowest-coverage
modules, re-deriving this ranking from the coverage JSON by hand every run.

**The tests that exercise a defect and stay green (T-18, reframed by its
acceptance).** From the same run's contexts: for every open finding with
anchors, the tests that executed its cited lines, ranked — `facts.exercised_by`,
`findings[].exercised_by_tests`, and the report prints "Exercised and green:
…" under the finding. The design called them verification candidates; the
first acceptance run declared none of them and was right not to: a defect
filed under a green suite is, by construction, executed by tests that do not
fail on it. What the list is: the assertions to review (§3: green tests are
under review too), and where a regression test belongs. A guard is what
`verification_test` names, and the harness finds it once a fix lands with its
test.

**Structured results before dialects (T-14).** A gate command may carry
`{report}`; the harness renders it to a scratch path and parses what the gate
wrote — JUnit XML or CTRF JSON — for exact counts, per-test durations, the
failures with their messages and the ids. Counts from a report outrank the
summary-line dialect (`counts_dialect: report/junit`); with no `test_ids_cmd`,
the id ledger comes from the report in the report's own shape and says so. A
gate that writes nothing reads `report.status: missing` and falls back.

**A night that spends no model (T-5).** `verdict-run --skip-unless-drift`:
HEAD unchanged → the `--skip-unchanged` path; HEAD moved → the runner runs
`verdict-facts` itself and sweeps only when every condition holds — evidence
drift measured and empty, no changed file cited by any finding or
verified-intact item, every gate green with parsed counts, the test-id set
measured and unchanged, no quarantine due, no incomplete previous run, no
changed line that zero tests executed. It then finalizes a synthetic judgment
(the previous verdict, every open finding carried by `still_open`, an isolation
check that says no agent ran, a `not_tested` that says what a sweep does not
do) with `verdict-finalize --sweep`: `run_type: sweep` joins the enum,
`last_run.model: none`, the run number advances, the report and the signed
history row are written. Any condition failing prints why and runs the model;
the suite then runs once more inside the agent's own `verdict-facts`.

## 0.85.0 — 2026-09-07 · "every coding agent"

Step 3 of the work plan (engineering-docs, verdict pack §5a), the outward batch —
its first item. No harness or prompt change.

**Skills for every coding agent (T-9).** `npx skills add ArtJack/verdict` installs
five skills into any agent of the agentskills.io ecosystem — Cursor, Codex,
OpenCode, Claude Code and seventy more: **release risk** (the measured pass,
findings as files, the verbs, the ten-line handoff), **verify a fix** (the coding
agent fixes, Verdict verifies: a declared test re-run at both commits, the three
isolation controls with the contract's own measured numbers), **flaky triage**
(the five classifications, quarantine with an expiry), **root cause** (the
four-link chain, proof strongest first, trigger apart from cause, stop at
diagnosis), **spec review** (inventory, findings with a verbatim quote,
Given/When/Then, questions parked for a person). Each restates the contract for
an agent that cannot run the `verdict` agent, uses the harness the pip package
ships, and points Claude Code users at the agent; tests pin the front matter,
the doctrine line, the harness commands, the verbatim numbers.

**`AGENTS.md` and `llms.txt`** at the repository root: the first for agents that
use Verdict and agents that change it (the test command, the four doctrine rules,
what costs money, where things live); the second the index of the docs, every
link checked to exist.

**The README's first screen** now leads with the pain and the number — "Your test
suite is green. Verdict found a defect that had lived 4,595 days." — the boltons
`FilePerms` finding, introduced 2014-02-07, filed 2026-09-07 under 625 green
tests, reproduced by hand on a fresh clone and reported upstream as
mahmoud/boltons#480 (with #479, the `rotate_file` data loss) — the first two
findings this project ever sent anywhere, after the certainty pass.

## 0.84.0 — 2026-09-07 · "a finding is a file"

The prompt half of the findings-as-files design (engineering-docs, verdict pack
§7, session 5): the judgment stops being one JSON written from memory at the
end of the run. Eval-paid through the new paired runner; the acceptance run is
a delta on boltons against the control measured before any of this was built
(judgment pause 3:32, 39,500 characters, a third of them eight findings
re-typed to say "still there").

**A finding is a file (H-2).** `<qa-root>/findings/<ID>.json`, the shape of the
new `templates/finding.example.json`, written the moment the finding is proven
— with the exact excerpt still in the agent's context — and checked by the
PostToolUse validator as it is written: the same per-finding rules the judgment
loop always applied, plus the filename must equal the id. A rejection costs one
file. `verdict-finalize` assembles the files oldest first and stamps `filed_at`
from each file's modification time; `judgment.json` keeps the run-level fields
(the judgment template carries no findings now) and may still carry `findings[]`
inline — but never both, and never merged. `verdict-facts` moves the previous
run's `findings/` to `findings.prev/` before the run starts; a retry of the same
run keeps its own files. Nothing is deleted.

**Two cheap verbs.** `still_open: [ids]` carries a finding the tester looked at
and found unchanged, exactly as last filed — title, evidence, class, declared
test, anchors and all; `resolved: [ids]` closes one it looked at and found gone,
not fix-verified unless the harness measured it. Both take only findings open
in the previous state; an accepted risk is refused; an id in a list and in a
file is refused. And the word "still there" is not the tester's where the
harness knows better: a `still_open` over code that `changed` or went `missing`
since the evidence was written (0.83.0's drift) is refused — write the file
with fresh evidence, or resolve it. `moved` is allowed, and the report says
where the line went.

**One class, one finding.** Filing findings one at a time makes it easy to file
an instance of a class as a second finding — the thing §3.5's class link exists
to prevent, and the design's one open concern. `validate_judgment` refuses a
finding whose evidence cites a `path:line` that another finding, filed or
carried, lists under `root_cause.class.sites`, and two findings that list the
same site. Exact, never heuristic; the message names both exits.

**Questions with a second pen (T-4).** A run ends with things only a person can
decide, and they lived in the closing handoff, so the next run asked again — one
question rode seven runs; boltons parked four in its profile where nobody would
find them. A judgment now carries `questions`; finalize mints `<PROJECT>-Q-<n>`
and keeps `questions.json` (its pen only, deduplicated on the text); the
maintainer answers with `verdict-answer <project> <Q-id> --answer "…"` or
`--dismiss --reason "…"`, which writes `answers.json` — refused to the tester by
both scope guards, like `accepted.json`. The next `verdict-facts` says what is
parked and what was answered since the last run; the report renders **Needs
human decision** and **Answered since the last run**; the session-start banner
says how many are waiting and how to answer; `verdict-gate`'s text and comment
carry them; the MCP server has `get_questions`. Pushed to every surface that
reaches a person; never mailed, never filed as an issue.

**A declared test is a collected id (P-24).** A run wrote "none — no test in
tests/x.py::y covers this" into `verification_test`, and the harness read it as
a citation it could not find. When the id ledger exists, a `verification_test`
that is not in it is refused: declare one, or omit the field and say in
evidence that no test guards this.

**The prompt** (§6, §7, §9, §13): a finding is a file written when it is
proven, and the class search comes first; the two verbs; read `facts.questions`
and never re-ask; the test-id rule; the handoff's "Needs human decision" is the
ledger, not a place to invent new ones. **The eval runner** gains `--pair
<ref>`: the same fixture with the prompt at HEAD and at a git revision,
interleaved, one table with per-row deltas and both prompt hashes (T-17) — this
release is the first paid through it. New scorer rows read the state rather
than the words: findings filed as files, findings carried by id, anchors that
resolve, one class not split, a question answered and not re-asked.

**Paid, through the paired runner:** cause ×2, head **9/10 · 10/10** against the v0.83.0 prompt's
**9/10 · 9/10** on the same fixture, interleaved — parity on the seven old rows (each arm's
one miss is the prose-vocabulary `trigger` row), and on the rows that read the state the
prompt's "search the class before you file" is the one measurable difference (`class-not-split`
2/2 against 1/2); pricer seeded **9/9**; liar **6/6** after an answer-key amendment (the run
filed the mock and the tautology as one class, as the contract now asks). Two scorer false
positives found and fixed on the way (the decoy phrase matching the renderer's own line; a
source checkout's harness read as the oldest). **Acceptance** on boltons, run 5 against run 2:
judgment pause 1:18 (3:32), 14.4k chars with none inline (39.5k with eight re-typed), 22
carried by id, 8 NEW filed during the run, 52.3k output tokens (60.8k); the class rule
refused the first finalize on three `ecoutils` findings and the agent folded them.

Pinned as mutants M1–M14. 1,079 tests.

## 0.83.0 — 2026-09-07 · "where the code went"

The harness half of the findings-as-files design (engineering-docs, verdict
pack §7, session 5): fields nobody writes, and one fact the next run reads
before it reads anything else. No prompt change, so no eval payment; the
acceptance run is a delta on a stranger.

**Every cited line, hashed (T-1).** `verdict-finalize` turns each `path:line`
in a finding's evidence and class sites — and in each verified-intact item —
into an anchor: the file's git blob id and a hash of that one line
(`findings[].anchors`, `verified_intact_anchors`). The next `verdict-facts`
re-measures them and writes `evidence_drift`: unchanged, moved (and to where),
changed, missing, or unresolvable when the reference never named a file. The
tester reads where the code moved instead of everything; the report's Scope
line counts it; "the code under an accepted risk changed" is measured in its
own bucket, where the contract used to ask the agent to say so from memory.
Anchors date from when the evidence was written and are carried while the
evidence text is unchanged, so "moved since" means since the tester last looked
at that code. A state written before this release reads `unavailable`, never
`unchanged`.

**When it was last measured (T-2).** `findings[].last_verified_at` is the
timestamp of the harness's own re-run of the finding's test — pass or fail; an
error or an `unavailable` ran nothing and dates nothing. The report prints
"Last measured 2026-09-05 — fails at HEAD", or "Never measured — no
`verification_test` declared", which is the sentence that gets one declared.

**Two more clocks (T-3).** `introduced_at` (and `introduced_sha`): the date of
the commit `root_cause.origin` names, resolved by git; absent when the origin
names no commit this repository has, never derived from `first_seen`.
`fixed_at`: the date the harness measured fail→pass on a chosen test — the
verified-fix date, not the fix commit's, and only ever on a measured
resolution. The finding header prints both — "lived 243d before detection ·
fix verified 3d after detection" — and the outcome ledger keeps them, so dwell
time and fix latency survive the finding leaving the state.

**The runner's own provision follows the plugin root.** `verdict-run` kept
whatever `.claude/agents/verdict.md` and hooks it found in the target. The
control run for this release, launched from the installed 0.82.0 plugin, kept
a prompt an earlier run had rendered from a development checkout, resolved
that checkout as its plugin root, and had its finalize half run by code that
was being edited at the time — under the installed version's name.
`.claude/verdict-provision.json` now records the root and the hash of every
file the runner rendered; a different `--plugin-root`, or the same root after
a plugin upgrade, replaces the runner's own copy and says why. A file the
runner did not write, or one edited since, stays the operator's, as before.

**Small things.** `facts.repo`, because finalize runs from the QA root and had
no way to run git; `facts.next_finding_id`, one past the highest id ever
minted with the outcome ledger included, so nobody scans for a gap and two
findings can no longer share an id by accident; the six new fields join the
list a judgment is told it cannot write. And a second run on the same day with
the same topic no longer overwrites the first one's report — `-run<n>` is
appended — found by the acceptance run on its own history: boltons run 3, a
delta, composed run 2's filename and run 2's report was gone. The agent
noticed, corrected the INDEX by hand and filed a lesson; the harness keeps
both now.

Pinned as mutants L1–L11 (the anchoring dropped, the drift never measured, a
moved line read as changed, a date stamped by a record that ran no test,
`introduced_at` falling back to `first_seen`, `fixed_at` on a claim, the repo
path not recorded, silence when nothing could be anchored, a foreign
provision kept — prompt and hooks, an earlier run's report overwritten). 1,034 tests.

## 0.82.0 — 2026-09-06 · "a template is copied, not studied"

The first release of the work plan drawn from the run traces
(engineering-docs, "verdict — how it actually works, traced"): four small
things, one eval payment.

**One module knows the time (T-7).** Thirteen call sites asked the wall clock
directly — two of them the naive local clock in the runner, one `date.today()`
in the MCP server deciding whether a quarantine had expired against UTC dates
in the state, off by a day for a third of the planet. `verdict_mcp.clock` is
the seam: `now()`, `today()`, `stamp()`, and `local_now()` for the one reader
that must parse the CLI's own wall-clock message. `VERDICT_CLOCK_AT` freezes
all of them, so a quarantine can expire inside a test and a boundary can be
stood on — the code-enumerated sweep had left every clock boundary standing
because none could be. A test walks the package's AST for any other
`datetime.now()`, `date.today()`, `utcnow()` or `time.time()`: discipline you
can run beats discipline you intend.

**The prompt that judged, as a hash (T-6).** `last_run.harness` carries
`prompt_sha256` of the prompt shipped beside the harness and, in a team-mode
checkout, `provisioned_prompt_sha256` of the one Claude Code actually loaded.
"Byte-identical since 0.74.0" was an assertion; now it is a comparison, and
the eval ledger can say which prompt produced which row.

**A template is copied, not studied (H-1).** Every headless run learned the
judgment's shape by reading `docs/state-schema.md` (~15,000 characters) and
ranges of `harness.py` during the run — two to three minutes each time — and
three runs out of four still met the validator on a shape (`isolation_check`
must be an object; `verified_intact` a list; `flaky_quarantine`, not
`quarantine`). The package now ships `templates/judgment.example.json`, a
complete judgment with every key and every shape, validated by the validator
in the test suite so it cannot drift; `verdict-facts` names it as
`judgment_template` and says so on stderr; the prompt says to copy it and
points at the schema document only for a field you do not understand.

**Ten lines at the end (H-5).** The closing handoff was a second full report
— 12,500 output tokens on the changesets run, 5,900 on ofetch — for a caller
that reads `state.json`. §13 now caps it at ten lines and says why.

**And the runner's own sentence.** The acceptance run for this release ended
with the *outer* headless session appending "Say the word if you want the
fixes written" under the agent's handoff. Verdict never patches; a relay that
offers to is the one sentence the position cannot afford. The runner's prompt
now says: relay the handoff verbatim, add nothing.

Pinned: the frozen clock ignored, the clock returning a naive instant, the
prompt hash dropped, the template no longer named. **Paid for:** seeded 6/6,
liar 6/6, `cause` ×2 at **7/7 and 7/7** (the two prose-vocabulary rows landed
on both runs this time; their variance is known). **Measured on a stranger,
`mahmoud/boltons` (625 tests, 15 minutes, `pass with risks`, two Majors in
unreleased code):** zero reads of `docs/state-schema.md` where every earlier
run read two chunks; one `verdict-finalize` where earlier runs needed two or
three; the closing handoff 976 output tokens where ofetch's was 5,900 and
changesets' 12,500; the judgment turn 3:02 for eight findings. The trace is
in the maintainer's notes beside the four it is compared against.

## 0.81.0 — 2026-09-06 · "the direction of a control"

The prompt release the last four code releases queued behind one eval
payment. Four clauses in `agents/verdict.md`, nothing else in the tree.

**The instrument control has a direction (VERDICT-F-58, open since run 11).**
§3's control for the stale-bytecode fault said: re-run an injection you have
already watched fail, and if it now passes you are measuring the cache. In
the ordering that produced VERDICT-F-50 the cached bytecode *is* that
injection, so it fails again and the control cannot fail. Run 14 exercised
the old control for real and it passed — because the arms were subprocesses
under `PYTHONDONTWRITEBYTECODE=1` with the cache swept, so the fault had
been excluded by other means, which is exactly the blind spot. The control
is now a restore: put the original source back and re-run; a failure that
persists on clean source is the cache. The `cause` answer key gains a row
that scores the restore by name.

**`ACCEPTED` is taught.** 0.78.0 admitted the model meets `status: accepted`
and delta `ACCEPTED` in its own state untaught. One bullet: what it is, who
writes it, that the guards refuse it to the tester, and what to do with it —
report it under "Accepted risks" with its citation, and say if the code
under it changed.

**The duration band is the harness's.** "Must not grow >10% week-over-week"
was a percentage the tester computed by hand, and run 14 breached it at
+12% while the per-test time had moved 7% and the suite had grown 4.5% —
the question it raised was "absolute or per-test?". Neither: the harness
already compares each gate against its own median (≥3× and ≥5s,
`duration_regressed` in the facts) and the prompt now says to read that
fact and never compute a band.

**An install flag that persists is a write.** On the changesets run the
agent's own `pnpm install --config.runtime-on-fail=ignore` persisted the
setting into the project's `package.json`; the guard cannot see an install
command's side effects. Prefer one-shot environment variables, run
`git status --porcelain` after any install, and report a change you did not
intend as an unintended write.

**Paid for, and what the payment bought.** Seeded delta 6/6, liar 6/6,
`cause` ×2 at 5/7 and 6/7 on the pre-existing rows — the same two prose
vocabulary rows ("mechanism", "trigger") missing as in the published
2026-09-03 series, VERDICT-F-74's class. The row added to score the F-58
clause scored **0 of 2** and was removed the same day: both runs isolated
the scratch and ran clean controls, and neither restored a mutated scratch,
because the `cause` fixture has no same-scratch re-injection sequence and
the restore is never needed there. So the clause ships **measured as
harmless, not as an improvement** — the ordering it corrects lives in delta
runs that re-inject twice, and no fixture has one yet. The ACCEPTED bullet,
the duration rule and the install rule have no eval row of their own; the
three regression checks are what says they broke nothing.

## 0.80.2 — 2026-09-06 · "a mention is not a choice"

**A node id in prose is text, one or several (VERDICT-F-26, open since run 5).**
0.77.0 stopped running a pick among *several* prose-quoted test ids; 0.79.0
stopped a *single* one from confirming anything, and kept running it as "the
conservative direction" — it could only hold a finding open. It then
mis-selected on six consecutive runs, refused nothing in fourteen, and stamped
a measurement of an unrelated test on the finding every time: run 14's record
for F-26 itself named a test about the state validator that was in the
evidence only as the example of a mis-scrape. A prose citation now gets an
`unselectable` record whatever its count — the candidates named, nothing run,
the note saying which field turns a mention into a choice. The guard behind
the selector stays, controlled by a test that edits facts by hand: a
`first_cited` record that reaches `merge` from anywhere still confirms
nothing. Pinned as a mutant; two 0.77.0 anchors follow the line they pin.

**The stranger's second stumble: vitest and jest counted the file line.** The
published 0.80.1 wheel was pointed at a second repository nobody here had
run it on — `unjs/ofetch`, TypeScript, vitest, 28 tests — and the first
thing the harness measured was `collected: 1`. Two defects, both silent.
vitest with a terminal attached puts a colour code between `passed` and
` (28)`, so the vitest signature missed and the pytest dialect caught
`1 passed` off the line above; and even without colour, vitest and jest
print the *file* tally on the line above the *test* tally in the same
vocabulary — ` Test Files  1 passed (1)` — and every unanchored field matched
that line first. Driven over the real bytes: 1 of 28 under the wrong runner's
name, 1 of 28 under the right one, 2 of 29 on a mixed summary, and the same
2 of 29 from jest's `Test Suites` line. The agent noticed on ofetch only
because 1 test for a 527-line test file was implausible, and worked around
it in the profile; a state written from the first reading would have carried
the number as a measurement. Colour is stripped before any dialect looks,
every vitest and jest field is anchored to the `Tests` line, and a vitest
suite with nothing passing is still recognised as vitest. Three mutants pin
it. The diff-coverage hint no longer tells a TypeScript project to run
pytest: it says the gate is coverage.py-based and stays unmeasurable
elsewhere.

**`pin_check` never touches the tree (run 14's runner, adopted).** Every
mutant now lands in a scratch copy of the working tree — tracked and
untracked-but-not-ignored files, so the edits in hand are what get measured,
not the last commit — with the copy's `src/` ahead of the editable install.
The copy must prove it runs its own code first: an `import verdict_mcp` that
resolves outside it aborts the run, because a re-injection that measured the
original checkout happened here (run 9) and its number was confident and
wrong. The in-tree design cost twice — a second instance read a failure the
first had caused, and an interrupted run emptied `harness.py` — and survives
only as `--in-tree`. The "never edit while pin_check runs" rule is retired
with it. The isolation check is pinned as a mutant.

**The stranger's third run, and which code measured it.** The published
runner was pointed at `changesets/changesets` — a 21-package pnpm monorepo,
vitest 5, on a Node the project's `engines` refuses, with no dependencies
installed — and returned `fail` in 36 minutes on a proven Critical: a
non-semver `version` field makes `changeset version` delete the changeset,
leave the version untouched and exit 0. The harness lesson was quieter. The
runner had been started from main, but the agent runs `verdict-facts` from
the plugin root, so the facts came from the plugin cache's 0.80.1 and the
vitest file-line misread that main had already fixed was back in the state —
and nothing in `facts.json` said which code had produced the numbers.
`last_run.harness` now names the file that ran and the version it claims
(`verdict_mcp.__version__` reads the plugin manifest when no distribution is
installed, which is the stranger's case), and the report's Scope block prints
both. `verdict-run --plugin-root <checkout>` is how unreleased harness code
gets a stranger run.

**The denominator is the code (VERDICT-F-65, deferred four releases).**
`eval/sweep.py` enumerates every single-site mutant inside *named functions*
— `eval/mutate.py`'s operators over the lines `ast` says the function owns —
and runs each against the whole suite in a scratch copy that has proved it
runs its own code. The default scope is what the finding was owed on:
harness.py's dialect table and its judgment-adjacent functions
(`duration_regressed`, `_counts`, `_ago`, `_chosen`, `select_test`,
`verify_findings`, `_apply_verification`, `_stamp_outcome`, `run_date`) and
`state.outcome_row` — 155 mutants over 417 lines, none of them chosen by
anyone. mutmut was tried first over the same scope: 3,638 mutants
enumerated, 37 run, then its worker died on a cache assertion with the main
process waiting on a queue forever. The 37 it did run found one thing —
gotestsum's skip count was the only dialect field no test row exercised —
which is exercised now and pinned. Survivors of the full sweep are reported
in eval/README.md as candidates, each to be driven side by side with the
original before it becomes a test, because a survivor and an equivalent
mutant print the same line. **The first sweep: 121 of 155 killed, 34
survivors, judged one by one** (the table is in eval/README.md). Twenty-two
were real: every boundary of the duration gate, including `None` compared
against a float; one minute reading as "seconds ago" (VERDICT-F-60's
survivor 8, at last); an explicit citation that resolves but is not spelled
as collected; the counterfactual worktree never removed; six verification
notes that could be emitted unconditionally because nothing asserted their
absence; an open finding stamped "resolution refused". One test had gone
vacuous after F-26 — it cited in prose, so nothing ran and its assertion held
on nothing. Seven survivors are pinned in the catalogue (S1–S7); the
equivalents and the one platform-dependent case are listed so nobody
re-derives them.

## 0.80.1 — 2026-09-05 · "a path is not a key"

The one thing a stranger hit. The release cadence stopped at 0.80.0 and the
next engineering was to be whatever a newcomer stumbles on, so the published
0.80.0 wheel was pointed at a repository nobody here had ever run it on —
`pallets/itsdangerous`, in solo mode, the way someone who just installed it
would: `uvx --from verdict-qa-mcp verdict-run .`

**It ran for 18 minutes, filed nine findings, and then said "wrote no state".**
`verdict-run .` took `.` as a solo *key*: it read `run_number` from
`~/.claude/verdict/./state.json`, which does not exist, while the agent had
derived the key `itsdangerous` from the checkout (§0) and written a complete,
valid state and a 44 KB report under it. The runner declared the run lost,
retried — eleven more minutes of the model on a byte-identical tree, which the
agent itself called "cheap to be right about and easy to be useless about" —
and then gated the key `.` and exited 4: *no Verdict state found*. Two valid
runs on disk, and the tool's own last word was that there were none. The gate
has the same shape: `verdict-gate .` in solo mode answered 4 over the state
sitting one directory over.

A path with no `.qa/` under it names the checkout, not a key, and both the
runner and the gate now derive the key from it exactly as the agent does. The
nightly never hit this because it passes an explicit key; this repository never
hit it because it is in team mode. Only a stranger could.

**What it found, for the record.** Nine findings on a cryptographic library,
all `proven`: signature verification accepts non-canonical base64, so four
distinct token strings unsign to one payload; the `max_age` boundary is
unpinned — `>` to `>=` leaves 297 of 297 green; the constant-time compare can
be replaced by `==` and the suite stays green; an unbounded `zlib.decompress`
on unverified input measured at 38 KB → 30 MB; a substring test where a set
test was meant. It built the test environment *outside* the repository because
`.venv` is not in that project's `.gitignore`, and left the checkout untouched.
That is the tool working. The runner's last line was the part that did not.

**Measured.** `0.80.1 E1`–`E2` pin both resolvers; each was put back and its
test failed.

## 0.80.0 — 2026-09-05 · "a name is not a role"

Run 14's five findings, and the catalogue-honesty trio that had been deferred
three releases. Prompt byte-identical.

**VERDICT-F-75 (Critical) — one ordinary token disarmed the git guard.** Both
of the handler's exemptions matched a *name* wherever it appeared, in any
role. `--dry-run` was searched for across the whole argument list before the
verb was even identified, so `git commit -m "--dry-run"` — where the token is
the commit message — returned early and yielded no target at all. Measured
against real git: it commits. `git branch -D keepme list` deletes both
branches, because for `branch` the read-only word `list` is not a sub-verb at
all; `git branch list` **creates a branch called list**. The table had it
exactly backwards.

The handler now walks the arguments the way git reads them. An option's value
is a value, whatever it looks like, including through a bundled short option
(`-am wip`); a dry run is a flag in a flag's position, and `--check` belongs
only to the verbs that have it. Read-only spellings are split into the two
kinds they always were: a **sub-verb**, which must be the first operand
(`git stash list`), and a **flag** (`git branch --show-current`,
`git tag -n`, `git config --get-regexp`). A mutating flag outranks a listing
one, so `git branch --list -D keepme` is refused.

**VERDICT-F-76 — the same blindness refused what the tables were written to
allow.** `git branch --show-current`, `git branch -v`, `git tag --list` and
`git config --get-regexp` were all denied as checkout mutations; the run that
found it had to work around one. The guard's own comment says the stake:
denying `git config --get user.name` is the kind of false positive that gets
strict mode switched off. Twenty-eight shapes now sit in the suite twice —
once asserting the guard, once running real git and diffing the checkout —
and the two halves are separate columns, because a guard that denies what git
itself refuses is over-refusal rather than disagreement.

**VERDICT-F-77 — a mode is not a path.** `chmod +x f` resolved `+x` against
the cwd and refused the command, including inside `.qa/`, the one directory
the tester may write. The first operand of `chmod`, `chown`, `chgrp` and
`install` is skipped; the files behind it are still checked.

**VERDICT-F-78 — two of yesterday's four workflow tests read the comments.**
The sha256 verification that VERDICT-F-73's fix rests on could be deleted and
replaced by a comment naming it, and all four tests stayed green. The
catalogue's own mutant deletes the line outright and was killed, which is why
the gap was invisible: the kill measured *the string is absent*, not *the
check runs*. Every test in that file reads the commands now, and one more
asserts the filter itself.

**VERDICT-F-79 — the import census read prose.** `from`/`import` was matched
as loose text over a diff's added lines, so a docstring sentence — "from a
`releases/latest` URL" — was reported as an undeclared dependency on the
English word "a". That was the range's only import lead. The pattern is
anchored and the module root must be followed by what a real import has.

**The catalogue, enumerated from the code (VERDICT-F-60, F-65, F-66).** Run 13
listed eleven rules the suite does not defend and re-measured five of them.
Reading `hooks/qa_paths.py` and the run's clock line by line produced
seventeen mutants, and the whole suite killed thirteen. **Three survivors no
fix list could have reached**: the solo root's prefix test dropping its
separator, so every sibling directory whose name merely begins with the
root's would count as QA scope; the team-mode walk being allowed to keep
scanning, so a deeper `.qa` could rescue a path whose real parent is not a
checkout; and the maintainer's ledger being refused by *name* rather than by
name-in-scope, which takes the agent's own scratch directory away from it.
Each has a test, and each test was controlled by putting the defect back.

**Two of the five were equivalent mutants, and saying so is the point.**
`errors="replace"` cannot change what these guards emit, because every
character in their messages is UTF-8-encodable — paths reach the message
through `!r`, which escapes lone surrogates. And translating a trailing `Z`
to `""` instead of `"+00:00"` produced an identical date on **every stamp
tried**, which contradicts the finding that named it: run 13 asserted that one
changed behaviour, and it does not. Run 14 reached the same conclusion
independently over nine stamps. What *is* load-bearing there was measured
instead: the offset's value, the conversion to UTC, and — on the 3.9/3.10
floor, where `fromisoformat` cannot read a bare `Z` — the translation itself.

**VERDICT-F-66 — the mislabelled call-site entry is gone.** Of the three
catalogue entries presented as "a class that did not exist before", one was
another entry's behaviour with a discarded call bolted on. It is replaced by a
real one: `verdict-finalize`'s only call to `check_artifacts`, whose deletion
left all eight of that check's tests green. The call site now has a test of
its own.

**What the number is a rate over** is published beside it: `eval/README.md`
names which files have had a line-by-line pass and which are pinned from the
fix list only. That is the answer VERDICT-F-65 asked for — not a bigger
number, but a legible denominator.

**And the mutation tool stopped being able to break the repository.** A
whole-catalogue run interrupted during this release left `harness.py` **empty**
— 2286 lines gone — because `pin_check` applied and restored mutations with
`open(path, "w").write(...)`, which truncates before it writes. The lock had
already been released, so nothing said the tree was broken. It writes through a
temp file and `os.replace` now, the way `harness._atomic_write` has since
0.52.0: an interrupted run leaves either the original or the complete mutant,
and a kill that outruns the restore leaves the lock behind as the signpost it
is meant to be. Found by killing a run, not by reading one.

The first test to construct its restorer then failed on both Windows legs:
`signal.SIGHUP` does not exist there, and the tuple naming it raised before the
`try` written to forgive it — an except clause listing `AttributeError` as
"the platform lacks it", sitting one level too deep to ever see it. The class
was unconstructible on Windows and nothing had noticed, because nothing had
built one. The signals are looked up by name now, and the missing case is
simulated in the suite rather than left to the only two runners that show it.

**Measured, and the campaign audited itself.** `0.80.0 C1`–`C18` and
`D1`–`D12` in `eval/pinned_mutants.json`: **26 of 28 killed by the whole
suite** on the first pass, one equivalent — and the two survivors were the
atomic-write call sites in the campaign's own driver, which nothing exercised
because running it for real means running the whole suite once per mutant. The
driver is now run for real against a one-entry catalogue and a trivial suite in
a temp root, so the apply and the restore are each asserted to swap the file
rather than rewrite it in place. Both survivors are killed, and so is the
Windows signal case. 958 tests.

**Two process scars, recorded because they cost real time.** Running the suite
while a campaign holds the tree reads its mutants as failures — the tool's own
docstring says the tree is not yours while it runs, and it is right. And a
control loop that restores with `git checkout --` discards *uncommitted* work
in the file it just mutated: the signal fix above was written, controlled, and
silently reverted that way. Commit before you control.

**Not in this release, on purpose.** F-26, F-58 and the `accepted` teaching
sentence remain the eval-paid prompt release. Run 14's four escalations are
the maintainer's: the duration gate's percentage band, whether the
scratch-copy mutation runner is adopted into `eval/`, F-26 fixed or accepted,
and the §0/§4/§5 fixture gap.

## 0.79.0 — 2026-09-05 · "measured before modelled, in both directions"

Run 13 — the first run to render an accepted risk — judged three releases in
one pass and filed four Majors. All four are closed here; the prompt is
byte-identical.

**VERDICT-F-70 — the archive tar writes is a write.** `_check_tar`'s own
comment said the archive named by `-f` "is written, not removed" and never
yielded it, so `tar -cf <checkout>/hooks/a.py -C <scratch> junk` turned a
tracked source file into a tar archive with the guard's blessing — and did the
same to the maintainer's `accepted.json`, which the same guard refuses to
`cp`, `mv`, `tee`, `sed -i`, `>` and `>>`. Measured against GNU tar 1.35
before a line was written: the archive path resolves against the shell's cwd
wherever `-C` sits, the attached `-cf<path>` and `--file=` forms overwrite
just the same, `-f -` is stdout and not a file. Every mode that is not
extract, list or compare — create, append, update, concatenate, delete — now
yields the archive as a target.

**VERDICT-F-71 — an abbreviated option that takes a value takes it.** The
parser matched `_TAR_LONG_WITH_ARG` exactly while the handler matched the same
options by abbreviation, so `--direc <checkout>` was yielded valueless, the
directory fell through as an operand, and an extraction into the checkout was
reported against the shell's cwd. Every rung from `--dir` to `--director`
allowed, only the two full spellings denied. `_tar_takes_value` reads any
prefix of a value-taking option of three characters or more; a prefix tar
itself calls ambiguous (`--fil`: `--file`, `--files-from`) makes tar refuse the
whole command, so reading it as value-taking costs nothing. Both findings sit
in `TAR_WRITE_SHAPES` twice: once asserting the guard, once running real tar
and diffing the checkout.

**VERDICT-F-72 — a confirmation needs a chosen test.** 0.77.0 stopped the
harness *refusing* a resolution on a test picked by prose order, and stopped
running such a pick at all. The flattering direction was untouched: a pytest
id merely quoted in a finding's evidence — with one candidate, so no lottery —
could still write `fix_verified: true`, a "verification (measured)" evidence
line, and a `confirmed` / `measured` row into the track record that grades the
tester. Run 12 had shown a quoted id can be another finding's test entirely.
`fix_verified` and a measured confirmation now follow a fail→pass only when
`selected_by` is `explicit` (the tester's own citation) or `added_this_run`
(the collector saw the test for the first time: a fix's regression test). A
single prose-cited test may still refuse — a finding held open costs a
re-read; a confirmed row is permanent — and its fail→pass is recorded under
`not_weighed`, counted apart in the report, and named in
`verification_notes` with the field to declare. The dead `arbitrary` branch
run 13 found is gone. Three tests that modelled the loop closing did so on a
prose citation; they now declare the test, and a twin asserts the prose-only
case measures and confirms nothing.

**VERDICT-F-73 — the publisher is pinned and checksummed.** The registry job
downloaded a third-party binary from a `releases/latest` URL with no checksum
and ran it holding an OIDC identity, under `continue-on-error`. It is pinned
to v1.8.1 and to the sha256 the registry publishes beside it
(`registry_1.8.1_checksums.txt`, verified to match an independent download),
`sha256sum -c` runs before the binary does, the job no longer swallows its own
failure, and the PyPI wait fails instead of warning. `tests/test_release_workflow.py`
reads the commands (not the comments) and refuses a `latest` URL, a missing or
unchecked checksum, or a binary that runs before it is verified.

**Also.** A judgment may no longer carry an `accepted` block — run 13 showed
one passing `validate_judgment` and surviving `merge` verbatim, inert but a
stray in the trust artifact — and `_fold_accepted` strips one from any open
finding the ledger does not accept.

**Measured.** Every rule above has its defect put back in
`eval/pinned_mutants.json` (`0.79.0 S1`–`S9`, `--filter 0.79.0`): **9 of 9 killed
by the whole suite**. The four entries whose anchors the parser change moved
were re-anchored rather than left to read `STALE`, and the pinned-rules badge
moved with the catalogue — its test refused the first pin check outright,
because the suite must be green before a mutant means anything. One control
survived its first version: a matrix row with sibling directories made "resolve
against `-C`" and "resolve against the cwd" land on the same file, so the row
was deepened until the two models disagreed.

**Not in this release, on purpose.** F-74 (the `trigger-separated-from-cause`
eval row scores a bare word) is scorer work owed to the eval; F-58 and the
one-sentence `accepted` teaching remain the queued, eval-paid prompt release;
F-60/F-65/F-66 remain the catalogue-honesty release. The three escalations run
13 raised — the README's "never patches your code" framing against a guard
that is a heuristic, acceptance as a write anyone with commit access can make,
and the §0/§4/§5 fixture gap — are the maintainer's.

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

**Also, the two public surfaces a visitor checks first.** The Releases page
had stopped at v0.21.0 while the tags ran to v0.77.0 — every version had
notes, written before its tag, and nothing carried them there — and the MCP
Server Registry still listed 0.49.0. `release.yml` now creates the GitHub
Release from the CHANGELOG section on every tag (`.github/release_notes.py`,
which refuses a version without one, before anything is built), publishes
`server.json` to the registry by the workflow's own OIDC identity (best-effort:
a listing must never fail a release PyPI already carries), and holds
`server.json` to the same version as the other two manifests. This is the
first release the new jobs make.

**Also.** The session banner writes UTF-8 now. On Windows its em-dashes and
middle dots reached Claude Code as cp1252 bytes — the trap every guard's
stderr had already been pinned against, on the one hook that writes stdout.
Found by this release's own banner test on the Windows legs.

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

