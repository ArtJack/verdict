# AI-authored code — where it breaks

Most code Verdict reviews from here on was written by a model. Models fail differently
from people: the surface is *more* polished than human code — consistent naming, plausible
comments, tests attached — while the characteristic defects sit underneath, precisely
where polish stops a reader from looking. Reviewing AI code by "does it look right" fails
by construction, because looking right is the one thing the generator optimized.

So every entry here is a **procedure, not an adjective** — a trigger, a check, and the
evidence bar a finding must clear. Where an entry cites an incident, it is a real one from
this project's own history: the tool that hunts these patterns was built by a model, and
its externally-audited failures are the best training data it has.

Ground rules, before the catalog:

- **Provenance is measured, not assumed.** `verdict-facts` counts AI trailers over the
  review range and reports it in `code_census.provenance`; the profile may declare
  `authorship:` outright. Absence of trailers proves nothing — plenty of tooling strips
  them.
- **Provenance shifts the risk prior, never the verdict.** It is a §8.2 input like change
  volume: it decides where the reading budget goes. AI-heavy code gets its budget spent on
  the patterns below; it is not guilty of anything by provenance alone.
- **These are finding *sources*, not a new classification.** The five §3 classes stand.
  A hallucinated import that crashes a path is a REAL_DEFECT; a mock-asserting test is a
  finding about assertion quality with `failure_classification: null` unless a test is
  actually failing.
- **The censuses are leads, never findings.** Ten TODOs may all be legitimate. A count
  tells you where to read; only reading files a finding.
- **The track record polices this catalog.** Pattern-driven findings carry `confidence`
  like any other, and if they get withdrawn at high rates, the calibration table will say
  so. Knowledge that inflates the false-positive rate is a defect in this document.

## The catalog

### 1. Declared but never wired

Constants, enums, flags, config keys defined as *intentions* and enforced nowhere — the
model wrote the declaration, drifted, and never connected it.

- **Incident:** `STATUSES` declared in two modules of this very project, checked in
  neither; a Critical typed `"closed"` gated green (fixed v0.23.0). `MAX_BATCH = 100`
  while the loop hardcodes 50 is the same species.
- **Check:** for every constant/flag/enum the diff adds or a comment cites, find the
  second reference — the one that *acts* on it. `grep -n <NAME>` with one hit is the
  finding. A comment claiming "respects X" makes it Major: the doc now lies.
- **Evidence bar:** the declaration site, the enforcement site that doesn't exist, and
  what actually happens instead.

### 2. Convergent duplication, then drift

The model re-derives instead of reusing — a second near-identical function under a
different name — and the copies then evolve separately until behaviour depends on which
path you entered by.

- **Incident:** two copies of the REGRESSED-first sort in this repo, already divergent on
  whitespace handling when found (v0.25.0); the outcome ledger folded twice from two
  different dates (same release).
- **Check:** for each new function, ask what existing code already does this; diff the
  twins line by line — the *differences* are the finding, because one of them is wrong for
  every caller of the other. Cite which callers get which behaviour.
- **Evidence bar:** both sites, the behavioural difference demonstrated on one input, and
  which copy the spec supports.

### 3. Fix the instance, miss the class

Told to fix N reported sites, the model fixes exactly N. The pattern had more.

- **Incident:** AJT-F-14 — three reported call sites fixed, the fourth
  (`monitor/actions.ts`) untouched, found by Verdict the same day.
- **Check:** §3.5's class link, made mandatory for review-fix diffs: derive the *pattern*
  from the fixed sites (the API misused, the guard missing), enumerate all its sites
  mechanically (`grep`/`git grep`), and diff that list against the sites the fix touched.
  The remainder is the finding.
- **Evidence bar:** the pattern stated, the full site list, the untouched members.

### 4. Self-satisfying tests

The same run wrote the code and its tests, so the tests assert what the code *does*, not
what the spec *requires*: mirror tests that recompute the implementation's own formula,
mock-asserting tests that prove the mock was wired, tautologies.

- **Incident:** AJT-F-13 — a guard tested against its own copy of `shellQuote`, proven
  blind by two injections. The liar fixture's mock-asserting test is the canonical form.
- **Check:** provenance first — code and tests in the same commit means the author graded
  its own paper. Then anchor each assertion to a spec line, not to the code; and where
  re-injection is cheap, mutate the new code in a scratch copy and watch which new tests
  fail. A test no mutant can fail guards nothing (`eval/mutate.py` is this check,
  industrialized).
- **Evidence bar:** the assertion, the spec line it should encode, and what it actually
  pins.

### 5. Hallucinated surface

Imports, APIs, config keys that don't exist — plausible names, never real. Fails at
runtime on the first path that touches it, and the undeclared-package case is also a
supply-chain risk: slopsquatters register packages under commonly-hallucinated names.

- **Check:** `code_census.imports.undeclared` is the lead; verify each candidate against
  the manifest and the environment before filing (import-name/package-name mismatch is
  real). For called attributes on the diff's hot paths, confirm the callee exists.
- **Evidence bar:** the import site, the manifest that lacks it, and the path that
  executes it. Severity rides on reachability — an import inside a rarely-taken branch is
  a latent crash, which is worse than an eager one, not better: tests never see it.

### 6. Silent swallows

`except: pass`, `catch(() => {})`, fallback values masking failure. Models are trained on
"make it work"; swallowing errors makes demos work.

- **Check:** `code_census.placeholders` counts them; read each one and ask what *specific*
  failure now reports success. The finding is the masked failure, not the syntax — an
  intentional, commented, narrow swallow can be correct.
- **Evidence bar:** the swallow site, the failure it eats, and what the caller believes
  instead. If a spec line says failures must surface, cite it — that makes it REAL_DEFECT
  territory when demonstrated.

### 7. Placeholder erosion

"for now", "simplified", stub returns, hardcoded tables where an API belongs — written as
scaffolding, shipped as product, reachable in production paths.

- **Check:** census leads → reachability. A placeholder in a dead branch is Trivial; one
  a production path returns from is a defect with the age of the commit that added it
  (`git log -S` the marker — "for now" with a date is a broken promise you can cite).
- **Evidence bar:** the marker, the reachable path, and the behaviour the spec expected.

### 8. Chesterton demolition

A "cleanup" or "simplification" pass deletes a guard the model didn't understand —
validation, a limit, an idempotency check — because the weird-looking line is exactly the
one a model prunes.

- **Check:** read the diff's *deletions*, not just its additions. Any deleted line
  containing `if`/`raise`/`assert`/`limit`/`validate` gets archaeology: `git log -S` for
  why it was added. A guard with an incident in its history, removed by a commit titled
  "simplify", is a Critical until proven redundant — proof means showing what else now
  enforces it.
- **Evidence bar:** the deletion, the commit that originally added it and why, and what
  enforces the invariant now (or that nothing does).

### 9. Context-window seams

Each file locally coherent, the set globally inconsistent: naming flips, two error models,
the same concept modelled twice — the joints where one generation session ended and
another began, or where the model "kept both" halves of a changed approach.

- **Check:** read *across* the diff, not per-file: pick the conventions of the oldest
  touched code and note where new code breaks them. A half-removed old path that is still
  reachable is the highest-value instance — find the caller that still enters it.
- **Evidence bar:** both conventions cited, and one concrete input whose behaviour depends
  on which path it takes. Style-only seams are Trivial and get one finding, not twenty.

### 10. Confident comment, different code

Comments describing intent the code doesn't implement — "validates against the schema",
"rounds half up per spec", "verified" — narrated by a model asserting what it meant to do.

- **Incident:** two of four production timestamps on exactly `:00` months after `date -u`
  became a written rule; the comment culture said measured, the values said invented.
- **Check:** treat every claiming comment as a test case: do what it says and compare.
  A comment citing a spec rule is checked against that rule. The finding is the *lie*, not
  the style — the doc is now actively misleading the next reader, which outlives the bug.
- **Evidence bar:** the comment, the code, one input that separates them.

## Reading order under budget

On an AI-attributed range, spend the §8.2 budget in this order: deletions (pattern 8) →
new tests' assertions (4) → error paths (6) → declared-but-unwired (1) → the censuses'
leads (5, 7) → cross-file seams (2, 9) → comment claims (10). Deletions first because
they are the only category where the defect is *absence* — nothing else in the review
process will ever look there.
