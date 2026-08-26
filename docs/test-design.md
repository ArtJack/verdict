# Test design techniques — the working catalog

The agent's rule: **name the technique per case, state the expected result before
execution, and trace the case to a risk.** This catalog is what the names mean, when each
technique earns its place, and what the report must show. Choose by risk profile, not by
habit — a technique that cannot fail for the risk at hand is decoration.

Severity of use: a review that says "tested edge cases" is unauditable. A review that says
"BVA over `(price, floor)`; the at-floor point fails" can be checked, extended, and
re-derived by the next person.

---

## A. Specification-based (black-box)

**1. Equivalence partitioning (EP)** — split every input domain into classes the spec says
behave identically; test one representative per class, valid and invalid.
*When:* any input domain; the first pass on any new surface.
*Report:* the partition table — classes, representative, expected result each.

**2. Boundary value analysis (BVA)** — test at, just below, and just above every boundary
of every partition.
*When:* ranges, limits, counts, quantities, dates, money. Boundaries are where the defects
live: 0/1, empty/single-element, floor/cap, first/last, `==` vs `>`.
*Report:* the boundary table; every exact-equality comparison in scope gets its `==` row.

**3. Decision tables** — enumerate combinations of conditions against expected actions;
collapse impossible columns explicitly, don't silently skip them.
*When:* interacting business rules (discount × membership × region; fee × marketplace ×
account state).
*Report:* the table itself, with collapsed columns justified.

**4. State transition testing** — model states, events, guards; cover every valid
transition (0-switch), then transition pairs (1-switch) where sequencing risk exists.
Probe a sample of *invalid* transitions — the spec's silence is where state machines rot.
*When:* lifecycles — orders, sessions, retries, payment states, background jobs.
*Report:* the state table and the switch level achieved.

**5. Pairwise / t-way combinatorial** — cover all value pairs (or t-tuples) across
parameters instead of the full cross-product.
*When:* configuration matrices too large to exhaust (browser × locale × plan × flag).
*Report:* the generated array and the tool that generated it — hand-rolled "pairwise" is
usually neither.

**6. Use case / scenario testing** — end-to-end user goals including extensions and
exception paths, not only the happy line.
*When:* user-visible flows; acceptance-level confirmation.

**7. Classification tree** — decompose composite inputs into dimensions and leaves, then
combine leaves deliberately (minimal, pairwise, or risk-weighted).
*When:* structured inputs — documents, forms, import files, API payloads.

**8. Domain analysis** — boundaries of *interacting* variables treated together (on, off,
in, out points per constraint) instead of one variable at a time.
*When:* coupled constraints: `start < end`, `min ≤ x ≤ max`, sum-caps across fields.

## B. Structure-based (white-box)

**9. Statement / branch coverage** — every statement, then every branch outcome, executed
by some test. Branch subsumes statement; neither proves the assertions are meaningful.
*When:* the floor for changed code; direction gate — coverage on changed files must not
decrease.

**10. Condition coverage / MC-DC** — every atomic condition takes both values; for MC-DC,
each condition is shown to *independently* flip the decision.
*When:* dense boolean guards — pricing rules, authorization predicates, safety interlocks.
*Report:* the truth-vector table; MC-DC without the table is a claim, not a result.

**11. Data-flow (def-use) coverage** — cover paths from each variable definition to its
uses.
*When:* state mutated far from where it is read — caches, accumulators, retry counters,
lazily-initialized config.

**12. Loop testing (boundary-interior)** — 0 iterations, 1, a typical count, the maximum,
and one past the budget if reachable.
*When:* pagination, retry budgets, batch chunking, convergence loops.

**13. Basis path testing** — cyclomatic-complexity-many independent paths through a small
critical unit.
*When:* one dense function carries the risk (a parser step, a fee calculator); overkill as
a blanket policy.

## C. Property- and relation-based

**14. Property-based testing (PBT)** — generate inputs, assert invariants: round-trips
(`decode(encode(x)) == x`), idempotence, monotonicity, conservation (no money created or
destroyed), commutativity where promised.
*When:* pure logic, parsers/serializers, money arithmetic, anything with an algebra.
*Report:* the property, the generator ranges, and the **shrunk counterexample** when red.
Name the tool (Hypothesis, fast-check, proptest); with no tool present, specify the
property for the implementer — do not claim a PBT run that never happened.

**15. Metamorphic testing** — when no exact oracle exists, assert *relations between
runs*: adding a filter never increases the result count; permuting input order leaves the
total unchanged; a stronger constraint yields a subset; scaling all prices by k scales the
sum by k.
*When:* search and ranking, recommendations, numerical pipelines, and **ML/LLM
components** — the standard answer to "how do you test a system whose correct output you
cannot write down."
*Report:* each metamorphic relation as a named MR with its transformation and expected
relation.

**16. Approval / golden-master testing** — capture current output as a reviewed baseline;
future runs diff against it.
*When:* characterizing legacy behavior before a refactor; large formatted outputs.
*Warning:* baselines rot into rubber stamps — every approval diff needs a human owner, and
an approval updated in the same commit as the code change it "verifies" proves nothing.

**17. Fuzzing** — malformed, random, or coverage-guided inputs hunting crashes and hangs.
*When:* parsers, decoders, file importers, anything consuming untrusted bytes.
*Report:* corpus size, runtime, and every crash triaged through the failure-classification
gate (§3) — a fuzzer finding is not a report until it has a repro.

**18. Mutation testing** — mutate the code; every surviving mutant marks an assertion gap.
The measurement for the pesticide paradox: a suite that always passes may be testing
nothing.
*When:* suite quality is unmeasured and the suite gates releases.
*Rule:* only claim it when a mutation tool actually ran (§11); otherwise write "suite
quality unmeasured — no mutation tool present."

## D. Integration- and system-level

**19. Consumer-driven contract testing** — consumers publish expectations; the provider is
verified against them in its own CI.
*When:* service boundaries owned by different deploy cadences; the alternative is E2E
suites that break for reasons nobody owns.

**20. CRUD lifecycle testing** — create, read, update, delete for every persistent entity,
plus the ugly rows: concurrent update, partial failure mid-write, delete-with-references,
re-create-after-delete.
*When:* any entity that outlives a request.

**21. Fault injection / resilience probes** — kill the dependency, inject latency and
errors, fill the disk; assert the degradation matches the *documented* strategy (retry,
fallback, shed, alert).
*When:* the requirements claim resilience; untested fallback code is a rumor.
*Safety:* isolated environments only — the §0 gate applies with full force.

## E. Experience-based

**22. Error guessing / fault attacks** — a deliberate attack list: empty, enormous,
unicode and emoji, duplicate submit, double-click, clock skew, DST, month 13, negative
zero, concurrent same-key writes. Seed the list from *this project's incident history*
first — defects cluster (principle 4).

**23. Exploratory charters** — timeboxed missions with a risk focus (template ships with
the plugin); observations become evidence, repeatable failures become bug reports, stable
discoveries become scripted regression cases.

**24. Checklist-based testing** — heuristic and compliance lists as scaffolding for
review-style coverage; a checklist is a floor, never a verdict.

---

## Choosing: risk profile → technique

| Risk smells like | Reach for |
|---|---|
| Input ranges, limits, money boundaries | EP + BVA (always), domain analysis when variables couple |
| Interacting business rules | Decision tables; MC-DC when the rules live in dense booleans |
| Lifecycle / ordering bugs | State transition with 1-switch; CRUD lifecycle |
| Config explosion | Pairwise/t-way |
| "Correct output is hard to define" | Metamorphic relations; PBT invariants |
| Legacy refactor | Approval baseline first, then structure-based on changed paths |
| Untrusted input | Fuzzing + EP invalid classes |
| Suite always green, confidence low | Mutation testing; vary technique (pesticide paradox) |
| Service boundaries | Contract tests over shared E2E |
| Claimed resilience | Fault injection in isolation |
| Fresh surface, no spec | Exploratory charter + error guessing from incident history |
