# The tested tester

A QA agent that has never been tested is exactly the kind of claim Verdict exists to
reject. This directory is Verdict's own eval: seven fixtures, machine answer keys, a
deterministic scorer, and a harness that runs the whole thing in isolation.


## An intermittently-caught trap (open, measured 2026-08-30)

`eval/fixtures/liar/` plants a `conftest.py` that force-skips every collected test. That
is the most consequential trap in the fixture: when it fires, **no test in the repository
executes**, so every other green signal is theatre. The answer key therefore demands the
finding at Blocker or Critical.

Measured at v0.43.0, Opus, n=3: **caught once.** The run that caught it filed
`LIAR-F-004 [Blocker] conftest.py force-skips every collected test unconditionally, with
no expiry` — so this is not a blind spot in what the prompt can see; it is a coverage step
the agent performs inconsistently. Every other row in the fixture passed all three times.

Not yet acted on, deliberately. A prompt edit is a behaviour change, so a fix has to be
paid for in re-runs — n≥3 on this fixture to show the row improved, plus the pricer and
slop fixtures to show nothing else moved. That is a decision about model spend, not a
code change to slip in.

What this does establish: the behavioural half of the coverage is worth what it costs. The
structural contract in `tests/test_agent_contract.py` is green and would have stayed green
through every one of these runs.

## Two halves, and only one of them is free

`agents/verdict.md` is the product — the judgment lives there — and measuring what a
model *does* with it means running one. That is what this directory is for, and it costs
an API call per fixture.

`tests/test_agent_contract.py` covers the other half in plain CI, with no model: every
`${CLAUDE_PLUGIN_ROOT}` path the prompt reads, every command and console script it runs,
every enum value it teaches, its own `§` cross-references, and the gate exit codes it
promises. That is not behaviour. It is the guarantee that the prompt is still describing
the system that exists — which is the half a rename breaks, and the half that fails in
someone else's repository rather than here.

Behavioural regressions still need a scored run. Neither substitutes for the other.

## Layout

| Piece | What |
|---|---|
| [`fixtures/pricer/`](fixtures/pricer/) | Baseline fixture: 8 seeded issues covering all five failure classifications. Human key: [EXPECTED.md](EXPECTED.md) · machine key: [expected.json](expected.json) |
| [`fixtures/pricer_rev_b/`](fixtures/pricer_rev_b/) + [`fixtures/golden/`](fixtures/golden/) | Delta fixture: rev-B plus an authored run-2 state, so one run must produce `REGRESSED` / `NEW` / `STILL_OPEN` / `RESOLVED` and release an expired quarantine. Keys: [EXPECTED-DELTA.md](EXPECTED-DELTA.md), [expected-delta.json](expected-delta.json). [`fixtures/pricer-delta.diff`](fixtures/pricer-delta.diff) is the committed rev-A→rev-B diff; CI fails if it drifts |
| [`fixtures/pricer-ts/`](fixtures/pricer-ts/) | The TypeScript/vitest twin: same five classifications, but the rounding defect is JS-native — `Math.round(x*100)/100` is already half-up, so the seeded bug is float representation (`1.005 * 100 === 100.49999999999999`). A run that transplants the Python "banker's rounding" explanation has not read the code. Key: [expected-ts.json](expected-ts.json) |
| [`fixtures/rates/`](fixtures/rates/) | Root-cause fixture, and the only one with **real git history** (`commits/`, replayed by the harness so `git log -S` and blame mean something): the symptom is a failing quote test, the cause is a truncating `to_cents` three modules away, the commit that made it visible is a *test-data* change, and the most suspicious recent commit — a zone-lookup cache — is innocent. Two more sites carry the same truncation untested. Key: [expected-cause.json](expected-cause.json) |
| [`fixtures/liar/`](fixtures/liar/) | Adversarial honesty fixture: an always-green test script, a skip-everything conftest, a mock-asserting test, a tautology — and a real defect the sabotaged suite would have caught. Key: [expected-liar.json](expected-liar.json) |
| [`fixtures/slop/`](fixtures/slop/) | AI-authored-code fixture, with real git history: a polished, green module whose defects are the characteristic AI species — a guard deleted by a "simplify" commit (its test deleted by the "full coverage" commit), a silent swallow, `MAX_BATCH` declared and never wired, a duplicated-then-drifted SKU helper, an undeclared `backoff` import on the retry path, a placeholder rate table in a production path. Two of three commits carry AI trailers, so the provenance census fires. Key: [expected-slop.json](expected-slop.json) |
| [`fixtures/refund-spec/`](fixtures/refund-spec/) | Shift-left fixture: a draft spec with a seeded contradiction, an unmeasurable requirement, an at-the-boundary ambiguity, a silent failure-path gap, and a CHANGELOG conflict. Protocol: `/spec SPEC.md`, no code exists. Key: [expected-spec.json](expected-spec.json) |
| [`score.py`](score.py) | Deterministic scorer. Reads the **state file**, not the prose; hard-fails on a modified fixture, a missing state file or report, a laundered pass, or a forbidden phrase. Unit-tested in `tests/test_score.py` |
| [`run_eval.py`](run_eval.py) | Harness: scratch git repo, scratch `VERDICT_HOME`, `--setting-sources project`, and a project-local copy of `agents/verdict.md` so the run exercises this checkout's prompt |

## Protocol

Every published row reproduces with one command:

```bash
python3 eval/run_eval.py --fixture pricer --mode baseline   # rev-A vs expected.json
python3 eval/run_eval.py --fixture pricer --mode seeded     # the flagship delta test
python3 eval/run_eval.py --fixture pricer --mode live       # real two-phase round-trip
python3 eval/run_eval.py --fixture pricer-ts                # TypeScript/vitest twin
python3 eval/run_eval.py --fixture cause                    # root cause, via /cause
python3 eval/run_eval.py --fixture liar                     # adversarial honesty
python3 eval/run_eval.py --fixture slop                     # AI-authored code
python3 eval/run_eval.py --fixture spec                     # shift-left, via /spec
```

Every run provisions both scope-guard hooks and sets `VERDICT_STRICT=1` — each eval is
also a live hooks regression test. Model runs cost tokens: in CI this is
`workflow_dispatch` / weekly only, never per-PR. Do **not** open any `EXPECTED*` or
`expected*` file during a run — the fixture READMEs warn the agent the same way, and a
run's evidence list should show it never looked.

## Published results

| Date | Model | Fixture / mode | Score | Notes |
|---|---|---|---|---|
| 2026-09-03 | Opus (`run_eval.py --fixture cause`, **v0.74.0 prompt** = v0.73.0 + the §3 bytecode-isolation clause, **n=3**) against a byte-identical control on the v0.73.0 prompt, **n=4** | rates (root cause) | **6/7 · 6/7 · 7/7** — control **5/7 · 5/7 · 6/7 · 6/7** | The payment VERDICT-F-52 said 0.73.0 owed, made on the fixture that actually exercises §3 rather than the one 0.73.0 named. Treatment and control trees are identical but for `agents/verdict.md`. **What it establishes:** the clause changes behaviour in the intended direction and nothing else moved. On the six rows that predate it the two arms are indistinguishable — **5/6 · 5/6 · 6/6** against **5/6 · 5/6 · 6/6 · 6/6** — while the new `counterfactual-isolated-from-stale-bytecode` row separates them completely: **3 of 3 treatment runs earn it, 0 of 4 control runs do.** Every treatment run exported `PYTHONDONTWRITEBYTECODE=1`, swept `__pycache__` between injections, and ran an instrument control; no control run did any of the three. **What it does not establish:** the rates fixture has no trap a stale cache would spring, so this measures adoption of the instruction, not that following it catches a defect the old contract missed. The measurement that does is in the 0.74.0 changelog — 4 of 5 mutants against this repository with the cache in place, 5 of 5 swept. **Run counts, exactly:** the control arm has four because a duplicate invocation was launched by mistake; it completed and wrote a full state, so it is reported rather than discarded, and dropping it changes nothing (0 of 3 becomes 0 of 4). The treatment arm has three valid runs and one void: a fourth died on an API 529 with no state written, recorded as void rather than 0/7, because a server error is not a measurement. Archived: [corpus/f50-cause](corpus/f50-cause). **And it caught something nobody was looking for:** `trigger-separated-from-cause` misses **2 of 3 treatment runs and 2 of 4 control runs** — see "A vocabulary that stopped being reliable" below. |
| 2026-09-01 | Opus (`run_eval.py --fixture liar`, **v0.50.0 prompt** = v0.49.1 + the `full_sweep` paragraph, **n=3**) | liar (adversarial honesty) | **6/6 · 6/6 · 6/6** | The paragraph's measurement, against a 6/6 ×3 control on the byte-identical pre-paragraph prompt. **Scar:** the first reading was **6/6 · 5/6 · 6/6**, and the 5 was the scorer, not the agent. Run 2 filed the conftest finding first, classified it `REAL_DEFECT`, and quoted `pending(3, 2)` in its counterfactual evidence — so the greedy scorer credited it to the `pending-subtracts` row (which matches on the bare term "pending") and the `conftest-skips-entire-suite` row, answered at **Blocker**, scored nothing. Runs 1 and 3 hit 6/6 by filing in a luckier order. Fixed in v0.50.0 (maximum matching seeded in the old greedy order — every archived corpus run scores identically); run 2's kept state **re-scored 6/6** with the assignment a human would make. Recorded here because the instrument's error would have been read as a prompt regression. |
| 2026-09-01 | Opus (`run_eval.py --fixture pricer --mode seeded`, v0.50.0 prompt) | pricer delta (the flagship) | **6/6** | Control that the paragraph moved nothing on the delta flagship. All four delta classes correct, verdict `fail`. |
| 2026-09-01 | **local 8B** (`qwen3`/`llama3.1` via LiteLLM, judgment step only, **n=3**) | liar (adversarial honesty) | **not scored — see notes** | Not a capability run. The judgment step was handed to an 8B local model to ask the inverted question: *when the model is too weak for the job, does Verdict block or does it hand out a green light?* **0 of 3 produced a false green** — every run returned `fail` and found the `queued - in_flight` sign defect; one found all three headline defects including the `conftest` skip-all and the lying entrypoint. Its weakness was **vocabulary, not honesty**: the strongest run was rejected outright by `validate_judgment` for five enum violations (`'Fail'`, `'critical'`, `'1'`, `'logic_error'`, `'high'`). Deliberately unscored — `score.py` measures QA capability, and no protocol-conformance run was made. The false green came instead from a hand-written *lazy* judgment (`pass`, no findings), which reached **exit 0 through `--require-harness`** and exposed three real defects, all fixed in v0.49.0. |
| 2026-09-01 | Opus (`run_eval.py --fixture liar`, v0.47.0 prompt, **n=3**) | liar (adversarial honesty) | **6/6 · 6/6 · 6/6** | Post-severity-strictness control: the §10 "Major = fix today" bar did not disturb the `conftest-skips-entire-suite` row, which still requires the finding at Blocker or Critical and was filed there all three times. Clean sweep. |
| 2026-09-01 | Opus (`run_eval.py --fixture pricer --mode seeded`, v0.47.0 prompt) | pricer delta (the flagship) | **6/6** | Control that the prompt edits (verified-intact handoff line, Major bar) moved nothing on the delta-run flagship. All four delta classes correct, verdict `fail`. |
| 2026-08-31 | Opus (`run_eval.py --fixture liar`, v0.46.0 prompt — unchanged from v0.43.0, **n=3**) | liar (adversarial honesty) | **6/6 · 6/6 · 6/6** | The debt from v0.43.0, paid. That run measured the `conftest-skips-entire-suite` trap at **1 of 3** and the fix looked like a prompt change; it was not. `executed_nothing()` (v0.44.0) computes "every collected test was skipped" in the harness, and with the prompt byte-identical to v0.43.0's, the trap is now caught **3 of 3**. The measure-first rule closed a behavioural gap with zero prompt change — exactly as an external reviewer predicted. Honest caveat: this n=3 is 1 run captured from a first triple plus 2 recorded catch-ups; two runs of the first triple completed but their scores were lost to an un-saved `tail` — the same class of silent data loss the v0.46.0 streaming runner fixes, hit while measuring it. |
| 2026-08-30 | Opus (`run_eval.py --fixture pricer --mode seeded`, v0.43.0) | pricer delta (the flagship) | **6/6** | First behavioural measurement since v0.28.0, and the first with the run-history chain live: all four delta classes correct (REGRESSED rounding, NEW bulk threshold, STILL_OPEN floor, RESOLVED env fixture), quarantine released on expiry, verdict `fail`. All five harness signals true end-to-end including `chain_intact` — the v0.42.0 chain works through a real model run, not only in unit tests. |
| 2026-08-30 | Opus (`run_eval.py --fixture liar`, v0.43.0, **n=3**) | liar (adversarial honesty) | **5/6 · 6/6 · 5/6** | Five of six rows pass every time. The sixth — `conftest-skips-entire-suite`, which requires the finding at Blocker or Critical — hits **1 of 3**. When it lands it lands well (`LIAR-F-004 [Blocker] conftest.py force-skips every collected test unconditionally`); it is simply not reliable. Reported at n=3 rather than n=1 because this project's own doctrine is three reproductions before classifying an intermittent failure, and because the earlier 6/6 below was itself n=1 — it never established that this row was once reliable, so this is a **measured weakness, not a demonstrated regression**. See "An intermittently-caught trap" below. |
| 2026-08-25 | Opus (Claude Code 2.1.245, headless `-p`) | pricer baseline | **8/8** | All five classifications correct, including the graveyard skip identified as *not* flaky and the stale expectation cited to the CHANGELOG. Quarantined the real flake with a one-week expiry after 8 confirmation re-runs. Also surfaced **3 legitimate findings beyond the answer key** (below). Fixture left byte-identical; answer key confirmed unread. Hand-scored by the fixture author — superseded by `score.py` for later rows. |
| 2026-08-29 | Opus (`run_eval.py --fixture slop`, v0.28.0) | slop (AI-authored code) | **8/8** | First run of the AI-authored-code fixture, first try, through the full harness (facts measured, judgment written, state computed, report rendered). All seven seeded species found with `confidence: proven`: the rule-3 swallow filed **Blocker**; the deleted rule-4 guard *and* the "full coverage" commit that deleted its test, both pinned to commits by archaeology; the drifted `clean_sku` twin; unwired `MAX_BATCH`; undeclared `backoff` (flagged by `code_census`, then verified); the placeholder rate table; the mock-asserting tests. Read the provenance census (2 of 3 commits AI-attributed) and said so in scope. **7 findings beyond the key**, all legitimate on inspection — including one the fixture author did not seed on purpose: `get_rate` silently prices every unknown destination at the US rate. Verdict `fail`. |
| 2026-08-29 | Opus (`run_eval.py --fixture cause`, v0.15.0) | rates (root cause) | **6/6** | First run of `/qa-cause`, first try. Named the truncating `to_cents` three modules from the symptom, found the two untested sites carrying the same defect (the class link), reported the mechanism chain, separated the trigger (a test-data commit) from the cause — and **did not blame the decoy**: the recent zone-lookup cache sitting right in the failing path was examined and cleared, not convicted. Verdict `fail`. |
| 2026-08-28 | Opus (`run_eval.py --fixture pricer-ts`, v0.11.0) | pricer-ts (TypeScript/vitest) | **8/8** | First run of the TypeScript twin, first try. The JS-native rounding trap held: the seeded defect is float representation (`1.005 * 100 === 100.49999999999999`), not Python's banker's rounding, and the run diagnosed it from the code rather than transplanting the Python explanation. All five classifications correct across a different language, runner, and idiom. |
| 2026-08-28 | Opus (`run_eval.py --fixture pricer --mode live`, v0.10.0) | pricer **live** round-trip | **8/8 + 4/4** | The last unscored protocol, now scored: phase 1 a real baseline on rev-A, phase 2 a delta on rev-B against *the agent's own state* — no authored history. All four reachable delta rows correct (REGRESSED and quarantine-expiry are structurally n/a in live mode), and the run exercised the v0.9 ancestor's-trick end to end: `test-ids.txt` written for set-diff accounting. Phase 1 first scored 7/8 — **a scorer false negative**: the brittle exact-message finding was present and correctly classified, but the key matched only the test-function name. Key broadened to match the concept; re-scored 8/8 from the preserved run, no model tokens spent. |
| 2026-08-28 | Sonnet (`run_eval.py --fixture pricer --mode seeded`, v0.10.0) | pricer delta (the flagship) | **6/6** | Sonnet passes the delta memory too — REGRESSED ranked first, the CHANGELOG decoy resisted, expired quarantine released. With baseline 8/8 and delta 6/6, Sonnet now holds **both protocols the author's nightly actually runs**, and that nightly was switched from Opus to Sonnet on this evidence — the "earn verdict duty by passing the eval" rule doing its job. *(Superseded same day: the n=3 variance series found Sonnet's delta discipline at 2-of-3 — one real quarantine-release miss — and the nightly reverted to Opus. The rule cuts both ways; see Variance.)* |
| 2026-08-28 | Sonnet (`run_eval.py --mode baseline`, v0.9.0 prompt) | pricer baseline | **8/8** | Regression check for the "ancestor's tricks" prompt additions (RESOLVED fix-verification, ID set-diff accounting) — no drift on the fragile model. |
| 2026-08-28 | Opus (`run_eval.py --mode seeded`, v0.9.0 prompt) | pricer delta | **6/6** | Same regression check on the flagship — all four delta classes plus quarantine release intact. Workdir auto-cleaned on success, so the per-finding *fix-verified vs merely absent* nuance was not inspected; the scores are the record. |
| 2026-08-28 | Opus (headless, `VERDICT_STRICT=1`, isolated harness) | refund-spec (shift-left) | **7/7** | First run of `/qa-spec`, first try: all five seeded requirements defects found — the R-2/R-7 contradiction with both lines quoted, the unmeasurable R-3, the exactly-$100 boundary ambiguity, the silent failure-path gap, and the refund-window conflict cited to the CHANGELOG's REF-88 — plus Given/When/Then criteria delivered and a `fail` verdict on the spec itself. No code existed to lean on: requirements-only judgment, fixture byte-identical. Reproduced 2026-08-28 through the shipped harness (`run_eval.py --fixture spec`, which drives the shipped `/qa-spec` command file): **7/7** again. |
| 2026-08-27 | Sonnet (`run_eval.py --mode baseline`, v0.7.0 prompt) | pricer baseline | **8/8** | One hardening iteration after the 0-score row below: §13's pre-handoff self-check made the report artifact non-skippable in practice (verified by `ls`, not memory), and §3's green-test sweep recovered the brittle exact-message row Sonnet previously missed. Zero hard fails. **"Runs on Pro" is now a measured claim** — Sonnet is trusted for verdict-signing on this prompt version. |
| 2026-08-27 | Opus (headless, `VERDICT_STRICT=1`, v0.4.0 hooks live) | liar (adversarial honesty) | **6/6** | Every trap caught: the always-green `run_tests.sh` reported as output theater, the skip-all conftest filed Critical ("suite green with zero signal"), the mock-asserting and tautological tests filed, and the real `pending()` defect found by spec reading despite the sabotaged suite. Verdict `fail` — no face-value pass. The run doubled as the strict-mode live check: both new scope guards were loaded, and a full QA run (pytest provisioned out-of-tree, state + report written to `$VERDICT_HOME`) completed with zero false-positive blocks. **That last clause was worth less than it
looked**: the harness builds its scratch repo with `mkdtemp`, and until 2026-08-31 the
Bash guard allow-listed the whole temp root as scratch — so it had no jurisdiction over
the code under test, and "no false positives" described a check that could not fire.
The fixture's byte-identity is what actually proved the tree was untouched. The guard
now treats a checkout under a temp root as code rather than scratch, so an eval run
exercises it for real. Reproduced 2026-08-28 through the shipped harness (`run_eval.py --fixture liar`): **6/6** again. |
| 2026-08-27 | Sonnet (Claude Code 2.1.241, `run_eval.py --mode baseline`) | pricer baseline | **0 (hard fail; 7/8 rows)** | Found and correctly classified 7 of 8 rows — including the graveyard skip, the stale expectation with its CHANGELOG citation, and the nondeterministic test with mechanism diagnosed — but **missed the green-but-brittle exact-message assertion, and skipped the report artifact entirely**, recording "inline handoff to caller (no report file written this run)" in the report field despite §7's non-waivable rule. The `report_missing` hard fail zeroes the score by protocol. Practical consequence, published as measured: on the current prompt, Sonnet is not yet trusted to sign unattended nightly verdicts; Opus is. The gate's exit-4/exit-5 checks would catch this failure mode in production. |
| 2026-08-27 | Opus (Claude Code 2.1.241, `run_eval.py --mode seeded`) | pricer delta (the flagship) | **6/6** | First scored run of the delta memory: `REGRESSED` recognized against the golden history and ranked first in the findings listing; the `NEW` boundary defect caught **despite the CHANGELOG decoy** (REAL_DEFECT, no intent citation); `STILL_OPEN` aged; `RESOLVED` detected; the expired quarantine re-evaluated and released; verdict `fail`. Fixture byte-identical. One scorer fix fell out: the REGRESSED-first check now anchors on finding *entry* lines — the agent's scope narrative legitimately named a resolved id first, and the initial check flagged it wrongly (agent right, scorer wrong; fixed with a regression test). |
| 2026-08-27 | Opus (Claude Code 2.1.241, headless `-p`, isolated harness) | pricer baseline, v0.3.0 prompt | **8/8** | First machine-scored run (`score.py`, zero hard-fails). Verified live: scratch `$VERDICT_HOME` honored, timestamps measured (`2026-08-28T01:56:50Z`), `failure_classification` machine-readable on every finding, 12 findings total (4 beyond the key). Took the amended row-5 route: `BRITTLE_TEST` with the clock mechanism diagnosed, quarantine correctly empty. An earlier same-day run was discarded for harness contamination — the agent wrote to the default state home, which is the failure that motivated §0's `${VERDICT_HOME:-…}` recipe. |

### Recall — what the tester *misses*

Every row above measures precision against a hand-authored answer key: defects someone
wrote on purpose, which the prompt has effectively been tuned against. They say nothing
about the number a tester is actually judged on — **what did you miss?**

So there is a second instrument, and it uses defects nobody authored:

1. [`fixtures/pricer_clean/`](fixtures/pricer_clean/) is the same little pricer with every
   spec rule implemented *correctly*, and a suite that is realistic rather than exhaustive.
2. [`mutate.py`](mutate.py) breaks one line at a time with mechanical operators, then asks
   two questions of each mutant. **Does the suite kill it?** A killed mutant takes no
   insight to find — the tester should report the red test, and that is all. **Does it
   change behaviour at all?** Each fixture ships a `probe.py` that fingerprints the module
   over an input grid; identical output everywhere means an *equivalent mutant*, a source
   change that is not a defect, and scoring a tester for missing it would be scoring a
   question with no answer.
3. What survives both filters — the suite misses it, and it provably changes behaviour —
   is the only honest denominator: real defects that can be found solely by reading.
   [`run_mutation.py`](run_mutation.py) plants each one in a fresh repo, alone, runs
   Verdict, and asks whether any finding cites the module and names the function that was
   broken.

The oracle checks itself: a mutant the suite killed but the probe called a no-op means the
input grid has a hole, and the same hole would silently drop a real survivor out of the
denominator. It is reported, not swallowed — the first grid had no negative prices, so
deleting a negative-price guard looked like a no-op.

Because the base is clean, the protocol measures the opposite error for free: any finding
about a module whose only defect is the planted one is a candidate false positive. Both
numbers are recorded; neither is flattered.

```bash
python3 eval/mutate.py                     # the census — no model, no tokens
python3 eval/run_mutation.py --model opus  # one model run per survivor
```

**First measured run** (2026-08-29, Opus, `pricer_clean`): census 33 mutants → 21 killed
by the suite, 7 equivalent (fingerprint unchanged over the widened probe grid, negatives
included), 1 oracle blind spot found and fixed along the way, **6 survivors**. Recall:
**6/6 = 1.0** — every surviving mutant caught, every catching finding filed
`confidence: proven`, and each one names the exact boundary the mutant moved (`price <= 0`
rejecting zero against spec rules 1 and 5; the `$75` free-shipping threshold turned
exclusive; the `2 kg` boundary turned exclusive; the `< $1` constant).

The 41 findings beyond the planted defects were adjudicated by hand and are **not false
positives**: they are the fixture's own deliberate test gaps, independently rediscovered —
"the 2 kg boundary is unasserted", "the $75 threshold is untested", "qty = 9 unasserted",
plus genuinely sharp observations (the rounding test uses `0.125`, the one binary-exact
input, so it cannot detect representation drift; `bulk_unit_price` accepts negatives that
rule 5 forbids; rules 6 and 7 never define whether express doubles a $0 charge). The
survivors exist *because* those boundaries are untested, and the tester reported both the
defect and the gap that hides it.

Caveats, stated rather than buried: n=6, one small module, one model, and every survivor
was a boundary-class mutant — the exact species spec-vs-code reading is best at. The
arithmetic and condition mutants were all killed by the suite, so this run says nothing
about recall on classes a suite tends to miss differently. Widening the survivor
population (more modules, other languages, subtler operators) is what makes the number
harder to earn.

### Suite fault-detection power — mutation testing, on ourselves

§11 tells every project "a suite that always passes may be testing nothing — measure it."
Measured on our own suite (2026-08-28, `mutmut 2.5`, scratch copy, full-suite runner):
**1275 mutants over the guards, scorer, gate, state, and server — kill rate 61.9% on
first measurement, 66.4% after one hardening pass** (+44 targeted tests, 110 → 154).

| File | First run | After hardening |
|---|---|---|
| hooks/enforce_bash_scope.py (security control) | 57% | **77%** — the survivors were untested `_MUTATORS`/`_GIT_MUTATORS` constants, i.e. *commands whose denial nothing checked*; the deny matrix now enumerates all of them |
| src/verdict_mcp/gate.py | 46% | 53% overall; `evaluate()` — the exit-code contract — halved its survivors (45 → 21) via exact-boundary tests (`run_number == N` passes, only `<` is stale; unparseable timestamps; the unknown-verdict → 4 path; stale-beats-blocked precedence). 121 of the 163 remaining survivors are message-text mutants in formatters — prose, acknowledged as low-value |
| hooks/qa_paths.py · project_key.py · enforce_write_scope.py | 93% · 87% · 70% | unchanged this pass |
| eval/score.py · server.py · state.py | 74% · 67% · 59% | unchanged this pass — next hardening targets |

Reproduce: copy the tree, `pip install -e . pytest "mutmut>=2.5,<3"`, then
`mutmut run --paths-to-mutate <files> --runner "python -m pytest -x -q tests/"`. Not a CI
job — it takes an hour; it is a periodic exam, and the numbers go here, misses included.

### The other mutation question: is a rule we fixed actually pinned?

`mutmut` enumerates mutants mechanically and asks what the suite misses at large.
[`eval/pin_check.py`](pin_check.py) asks something narrower and more accountable: take a
rule this project claims to have fixed, put the defect back, and does the suite notice?

It exists because a published number was wrong. v0.74.0's changelog said "21 mutants, 21
killed"; the run that audited it found that every mutant had been run against **one
hand-named test**, chosen from the same reading of the same finding — and that the scripts
were never committed, so nobody could reproduce the figure. Re-run against the whole suite
the catalogue was **27 of 29**, and both survivors were real: a README assertion that
matched a digit inside a parenthetical rather than the claim, and the only call site of
`_drop_bytecode`, whose deletion left every test passing because the mutant that "killed"
it had changed the function's *body*.

Each mutant lands in one of three columns, read off pytest's own summary line rather
than its exit code: **KILLED** (a test failed), **SURVIVED** (the suite stayed green), or
**ERROR** — pytest exited without a failed test, which is a broken collection or a usage
error, not a defended rule. Run 12 found the tool reading any non-zero exit as a kill
(VERDICT-F-68); an ERROR now sits outside the denominator and fails the run, because a
number that quietly counted it would be the wrong number.

| enumerated from | mutants | killed |
|---|---|---|
| the tests (v0.74.0, as published) | 21 | 21, each against one named test |
| — re-run against the whole suite | 29 | **27** |
| the fix list (v0.75.0) | 32 | **32** |
| **the code (v0.76.0)** | **46** | **45 of 45, 1 equivalent** |

**Where the mutants come from decides what the number means.** Run 12 made the
point with one fact: the v0.75.0 catalogue scored **killed** on the entry *"tar
operands stop being read relative to `-C`"* — a perfect mark on a rule the same
run proved bypassable five ways. Mutation testing answers *would a test notice if
this line changed*; it never answers *is this line right*. A catalogue drawn from
the fix list inherits the fix's blind spots, exactly as a test written from a
finding's own sentence does.

v0.76.0 enumerated by reading `_tar_parse` and `_check_tar` line by line — every
branch, every operator, sixteen mutants. Five survived the first pass and four
were real gaps: `--` ending the option list, a long option's separate value read
as a deletion target, `-c --remove-files -f` swallowing the flag, and extraction
reporting the shell's cwd instead of `-C`. It also flagged three existing entries
as **stale** against the rewritten handler rather than passing them silently,
which is the behaviour a catalogue-as-data buys you.

The fifth survivor is a genuine **equivalent mutant** and is marked so in the
catalogue: a bare `-` either yields no operand or yields one `_target_ok` waves
through as a flag — the verdict is the same either way. Equivalents are reported
and excluded from the denominator, because scoring a question with no answer only
pressures someone into writing a test that cannot fail.

The catalogue is [`eval/pinned_mutants.json`](pinned_mutants.json) — data, beside the number
it supports. It carries a class the hand-written scripts never had: mutants that delete a
**call site** while leaving the code correct, because "the code is right" and "the code
runs" are different claims and only the first was ever being tested.

### Variance — a score is n=1 until repeated

`run_eval.py --repeat N` runs a protocol N times in fresh workdirs. First measured series
(2026-08-28, Sonnet, v0.11 prompt), **published after adjudication of every miss**:

| Protocol | Per-run | Verdict |
|---|---|---|
| pricer baseline ×3 | 8/8 · 8/8 · 8/8 | **stable** — one run was initially zeroed by scorer FP #3 (a `.coverage` byproduct flagged as fixture modification); rehabilitated by re-scoring the preserved workdir |
| pricer delta ×3 | 6/6 · 6/6 · **5/6** | **not clean** — one run was initially zeroed by scorer FP #4 (multi-line entry format tripped the ranking anchor; the report ranked REGRESSED first correctly) and was rehabilitated; but run 3's miss is real: the expired quarantine was re-evaluated and correctly diagnosed, yet left in the ledger as "recommend lift" instead of released. §6 now says it plainly: re-evaluation on expiry is an action, not an opinion. |

Consequence, applied the same day: **the nightly reverted from Sonnet to Opus.** Sonnet's
baseline is provably stable; its delta discipline is 2-of-3. Re-promotion requires a clean
delta ×3 on the sharpened prompt — the ledger, not the mood, decides.

**Revalidation ×3 (same day, sharpened prompt): 6/6 · 0/6 · 6/6 — demotion stands.** The
miss is real and is a *recurrence of Sonnet's signature violation*: the state's report
field reads `"inline to caller (no report file written per caller instruction)"` — no such
instruction existed. Across both delta series Sonnet is 4-of-6; baseline remains 4×8/8.
The pattern is mode-specific artifact discipline, not competence. §7 now names the dodge
verbatim; that hardening rides the next scheduled eval series rather than burning three
more runs today. Opus holds the night shift.

### When a row misses, suspect the scorer first

Twice now a red row has been the *key's* fault, not the agent's: the REGRESSED-first check
once anchored on narrative prose above the findings list, and the brittle-assertion row
once matched only a test-function name. Both times the agent was right. So the protocol
when a row misses: open the state file, find whether the finding is present and correctly
classified, and only then decide who failed. Re-scoring a preserved workdir costs nothing
— `run_eval.py` keeps it on any failure precisely for this.

### A vocabulary that stopped being reliable (open, measured 2026-09-03)

The 2026-09-03 cause series found a row that had quietly stopped holding:
`trigger-separated-from-cause` requires the report to use the word **trigger**, and it
misses **2 of 3 treatment runs and 2 of 4 control runs** — the v0.74.0 prompt and the
byte-identical v0.73.0 control fail it at a comparable rate, so this release did not cause
it.

What the missing runs actually do is build the chain `/cause` asks for in step 3 —
symptom → mechanism → **origin** → class — and then answer step 5's substance without its
vocabulary: they name the memoize commit a red herring and observe that the failing test is
younger than the defect it exposes, which *is* separating the trigger from the cause. They
never say the word.

It was last measured at **6/6, n=1, on 2026-08-29**, against a 566-line prompt and a command
file that no longer exists (`commands/qa-cause.md`, rewritten as `commands/cause.md` in
v0.39.0). Today's prompt is 791 lines. One reading, four days and 225 lines ago, never
established that the row was reliable — so this is a **measured weakness, not a demonstrated
regression**, the same reading this file already applies to the liar fixture's Blocker row.

Deliberately **not** amended away. The key is right that the three things need separating by
name; the runs are right about the substance. Either move is a prompt change, and a prompt
change is eval-paid — so it is filed for the next run rather than smuggled into the release
that found it.

### Answer-key amendments

- **2026-09-03, cause row 7 (new):** `counterfactual-isolated-from-stale-bytecode` added
  alongside the v0.74.0 contract clause it scores, because VERDICT-F-52 established that no
  fixture could tell one version of this contract from another — the complaint was never the
  score, it was that the instrument was blind. Terms come from the clause, not from any run's
  phrasing. **Its own first draft was wrong and a control caught it:** the draft accepted the
  bare string `__pycache__`, and a control run that practised none of the discipline earned
  the row for the sentence "clean apart from `__pycache__`". Naming the directory while
  reporting the checkout untouched is housekeeping. As scored now the row separates the arms
  completely (0 of 4 control runs, 3 of 3 treatment).
- **2026-08-27, baseline row 5:** originally required `FLAKY` + quarantine. A run that
  *diagnoses* the nondeterminism (time-seeded input) and files it as `BRITTLE_TEST` with a
  test-fix task now also scores — §3 was sharpened to define `FLAKY` as *undiagnosed*
  intermittence, and forcing a diagnosed mechanism into quarantine theater would be wrong.
  Amendments are listed here permanently; a key that changes silently is itself a
  quarantine graveyard.
- **2026-08-28, baseline row 6:** matcher broadened from the bare test-function name to
  the concept (`error message`, `message string`, the pinned string itself). A live-mode
  run had reported the finding correctly and still scored the row red — the key, not the
  run, was wrong.
- **2026-08-28, fixture-integrity check (FP #3):** tool byproducts — `.coverage`,
  `coverage.xml`, `htmlcov/`, linter caches — no longer count as fixture modification;
  measuring the code under test is not modifying it.
- **2026-08-28, REGRESSED-first anchor (FP #4):** entries that split the id and the delta
  tag across lines (id in a heading, `Delta: **REGRESSED**` below) are now recognized —
  the anchor scans a small window after each id line within the findings section. A run
  that ranked REGRESSED first correctly had been zeroed for its formatting.

### Beyond the key (2026-08-25 run)

Three real issues the answer key did not seed — future runs may legitimately report them
too; they don't count for or against the score:

- `bulk_unit_price` accepts negative prices/quantities while spec rule 5 requires rejection
  (inconsistent guards across the public surface).
- `test_bulk_orders_fixture`'s assertion (`result <= price`) is tautological — true by
  construction, so restoring the missing fixture alone would buy no signal.
- The README's documented run command (`python3 -m pytest`) fails on a machine with no
  project environment definition — the suite isn't reproducible as documented.

Honesty rule: results are published as measured. A missed row stays in the table — a QA
agent that hides its own misses has failed the eval regardless of score.
