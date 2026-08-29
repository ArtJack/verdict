# Changelog

Plugin and `verdict-mcp` share one version line; `.claude-plugin/plugin.json` and
`pyproject.toml` are bumped together.

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
