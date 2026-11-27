# Green but broken — defects that survive every gate you have

Most defect catalogs list things that *break*. This one lists things that **don't** — the
species that compiles, lints clean, passes the suite, and fails in production anyway.

That is the only membership test for this document. If a static checker or a red test
would have caught it, it belongs somewhere else; Verdict already has those signals and the
project's own tooling is better at them. What earns an entry here is a defect whose
defining property is that **every gate reported green** — which is precisely why a reviewer
reading for "does this look wrong" will not find it, and why a model's general code sense
will not either. This catalog is recall the base model does not reliably have.

Ground rules, before the catalog:

- **Every entry names its probe.** A silent failure is invisible to reading by
  construction, so reading it is `probable` at best. The probe is how it becomes `proven`
  under §9 — usually two runs whose only difference is the suspected variable, or an
  injected value that the green path is supposed to reject.
- **It is a lead until you run the probe.** Pattern-matched findings filed from shape
  alone are exactly the cry-wolf risk §4.5 warns about. Match the shape, then execute.
- **Not a checklist.** Fourteen entries run blind over every diff is ceremony, and §8.2
  forbids spending the budget evenly. Pick the entries the change's own boundaries put in
  play — the diff crosses a queue, touches money, adds a retry — and say in the report
  which you looked for.
- **Shapes are Python and JS/TS here; the species is not.** The seam is the point. An
  entry's syntax will not match a Go or Rust diff, and the boundary it describes still
  exists there.
- **The track record polices this catalog, like every other.** Findings sourced here carry
  `confidence` and settle into `outcomes.json` with the rest. A catalog that inflates the
  withdrawal rate is a defect in this document, not a cost of doing business.

---

## Boundaries where a value changes form

### 1. Serialization boundaries

A value crosses into a queue message, a cache entry, a JSON column, a task argument, a
`postMessage`, a durable step's return — and must survive being rebuilt on the far side.
Rich objects do not: `Response`, `Error`, exceptions, functions, class instances with
methods, `Map`/`Set`, `datetime` into JSON, `Decimal` into anything.

- **Why it stays green:** the producer's tests assert on the object *before* it crosses.
  In-process test doubles often pass the live object through untouched, so the boundary
  that will later serialize it never runs.
- **Check:** list every boundary the diff crosses. For each, trace what is actually put
  in, and check the far side rebuilds it. `Decimal` and `datetime` are the quiet ones —
  both round-trip through `str()` without complaint and come back a different type.
- **Probe:** round-trip the real payload through the real codec in a scratch script
  (`json.dumps`/`loads`, `pickle`, the queue client's own encoder) and compare types, not
  just values. `assert type(back["total"]) is Decimal` is the whole bug.
- **Evidence bar:** the put site, the codec, and the round-tripped value with its type.

### 2. The bytes/str seam

Decoding with the wrong codec, or letting the platform choose: `open()` without
`encoding=`, a subprocess read as text under a different locale, a filename that is not
UTF-8, `errors="replace"` quietly corrupting instead of raising.

- **Why it stays green:** CI runs one locale and ASCII fixtures. The first non-ASCII
  customer name is the test that was never written.
- **Check:** every `open()`, `subprocess`, and network read in the diff — is the encoding
  explicit? Is `errors=` swallowing a real decode failure?
- **Probe:** feed the path a non-ASCII value (`"Müller"`, an emoji, a CP1251 byte string)
  and watch what reaches storage.
- **Evidence bar:** the read site without an explicit codec, and the corrupted output.

---

## Time

### 3. Naive and aware datetimes in one comparison

`datetime.utcnow()` returns a naive datetime that *represents* UTC and claims no zone.
Compared against an aware one it raises; compared against another naive one from a
different zone it silently returns the wrong answer.

- **Why it stays green:** fixtures are built by the same helper on both sides, so both
  sides are naive and agree. Production reads one side from a database driver that
  attaches a zone.
- **Check:** every datetime the diff constructs, stores or compares — naive or aware? Where
  does the other operand come from, and who attached its zone?
- **Probe:** construct the comparison with one aware operand, as the driver returns it.
  Either it raises or it is off by the offset — both are the finding.
- **Evidence bar:** both operands with their `tzinfo`, and the comparison's result.

### 4. The clock inside the assertion

A test that asserts on "now", a cache TTL, an expiry window, a relative date. It passes at
11:00 and fails at 23:59, on the 31st, in March, or in the other hemisphere.

- **Why it stays green:** it is green right now, on this machine, in this month. Pesticide
  paradox (§8.5) with a timer on it.
- **Check:** does the suite freeze time, or does it read the system clock? Any
  month/quarter/year arithmetic? DST transitions? `date.today()` compared across a boundary?
- **Probe:** run the suite under a frozen clock at the boundary — 23:59:59 local, the DST
  jump, 29 February, the last day of a quarter. A differing result is the finding.
- **Evidence bar:** the assertion, the clock it was run at, and the output at both times.

---

## Arithmetic

### 5. Money in binary floating point

`0.1 + 0.2 != 0.3`. Any currency amount in a `float` is a defect waiting for a total large
enough or a division awkward enough to show it.

- **Why it stays green:** fixtures use round numbers, and assertions use
  `pytest.approx` / `toBeCloseTo` — which is to say the test was written to tolerate
  exactly this bug.
- **Check:** every money value in the diff — its type at construction, through arithmetic,
  into storage, and out. A `float` column, a JSON number, or a `*` before a `round()` are
  each the finding.
- **Probe:** run the real calculation over realistic values (a cart of 37 items at
  `19.99`, a 3-way split, a percentage fee) and compare against `Decimal`. Any divergence
  at the stored precision is proven.
- **Evidence bar:** the computed value, the `Decimal` value, and where the difference lands
  (a cent per order is a Major; a cent per line item compounding is more).

### 6. Rounding that nobody named

Half-up, half-even, truncation, and the language's default are four different answers.
`round()` in Python is banker's rounding; most finance code and every invoice the customer
has seen is half-up.

- **Why it stays green:** the difference appears only at an exact `.5`, which round-number
  fixtures never produce.
- **Check:** find the rounding call. Is the mode stated? Does it match the rule the spec,
  the invoice template, or the upstream system uses?
- **Probe:** feed exact halves at the stored precision (`2.675`, `0.125`, `1.005`) and
  compare against the rule the spec states.
- **Evidence bar:** the call, the mode it actually uses, the spec line it contradicts.

---

## State that outlives its request

### 7. The mutable default and the module-level singleton

`def f(items=[])` evaluates its default once, at definition. A module-level dict, a cached
client holding request-scoped data, a global accumulator — all of them survive between
calls, and between requests.

- **Why it stays green:** the first call is correct, and most unit tests make exactly one
  call in a fresh process. The second call in the same process is where it starts lying.
- **Check:** mutable defaults in the diff; module-level assignments that are not constants;
  anything request-scoped stored where a module can reach it.
- **Probe:** call the function twice in one process and compare. Two different answers from
  the same input is the whole proof.
- **Evidence bar:** both calls' inputs and outputs, in one run.

### 8. One client, many threads

A connection, session, cursor or SDK client created once and shared across threads,
greenlets, or event loops that it was never documented to be safe in. Also: an async client
built on one event loop and awaited on another.

- **Why it stays green:** a single-threaded test suite exercises exactly one consumer. The
  interleaving that corrupts state needs concurrency the tests never create.
- **Check:** where is the client constructed, and how many consumers reach it? Read the
  installed library's own docs on thread-safety — §9's third-party-truth rule applies, and
  `code_census.dependencies` gives you the path to read it at.
- **Probe:** drive it from several threads at once against a local double and look for
  interleaved or lost state. Where that is unsafe to stage, this stays `probable` with the
  library's own documentation cited.
- **Evidence bar:** the construction site, the consumers, and the library's stated
  guarantee, quoted from the installed version.

---

## Control flow that quietly does nothing

### 9. The swallowed exception

`except Exception: pass`, an empty `catch {}`, a `.catch(() => {})`, a logged-and-continued
error whose caller then proceeds on a value that was never produced.

- **Why it stays green:** the handler makes the failing path *succeed*. The test asserts
  the call returned, and it did.
- **Check:** `code_census.placeholders` counts these; the count is the lead. Read each one
  and ask what the caller does next with the value that was not assigned.
- **Probe:** make the guarded operation fail (patch it to raise) and follow what the caller
  returns. A successful response built on a missing write is the finding.
- **Evidence bar:** the handler, the forced failure, and the caller's output under it.

### 10. The closure that captured the variable, not the value

A lambda, callback, or task built in a loop that reads the loop variable when it *runs*
rather than when it was created — so every one of them sees the last value.

- **Why it stays green:** with one iteration it is correct, and single-item fixtures are the
  default. It also reads perfectly.
- **Check:** every closure or deferred callable constructed inside a loop in the diff.
- **Probe:** run the loop with three distinct items and assert all three ran with their own
  value. Three identical results is the proof.
- **Evidence bar:** the loop, the three results, and the value each should have had.

---

## Checks that verify nothing

### 11. The counterfactual that imported the unmodified source

A verification step that is supposed to run against a mutated or reverted tree, but whose
import machinery resolves to the original — so every injection reads as a no-op and the
check reports a confident green.

- **Incident:** this project's own. A counterfactual run without isolation imported the
  unmodified source; **0 of 4 seeded defects were caught without it, 4 of 4 with it**
  (VERDICT-F-43). The verifier was not broken in a way anything could see; it was green and
  empty.
- **Why it stays green:** "no difference found" and "no difference possible" produce
  identical output. Absence of a signal is indistinguishable from absence of the defect.
- **Check:** any harness that mutates, reverts, or re-injects — prove the mutation was
  *visible* to the code that ran. Where does the import resolve from? Is there a cached
  module, an installed copy, a stale `__pycache__`, a path that still points at the original?
- **Probe:** seed a defect you know is there and confirm the check goes red. A verification
  step that has never been seen to fail proves nothing (§5, applied to the harness itself).
- **Evidence bar:** the seeded defect, the check's output on it, and the resolved import path.

### 12. Green with nothing counted

A suite whose output-suppressing flags, early exit, collection error or empty selector mean
it reported success over zero tests. Also: an assertion on a mock's own return value, which
counts and proves nothing.

- **Why it stays green:** exit code 0 is exit code 0. Nothing in CI distinguishes "200
  passed" from "no tests ran".
- **Check:** read the summary line, not the exit code. Does it state a count? Does the count
  match the previous run's? Did a filter or `-k` quietly select nothing?
- **Probe:** re-run from a clean state and paste the countable summary (§9 already requires
  this). Compare the count against the last run's.
- **Evidence bar:** the command, the summary line with its count, and the delta.

---

## Environment-conditional truth

### 13. Code that only runs on the interpreter you tested with

A construct valid on the version in CI and fatal on the version in production: an
annotation evaluated at definition time, a syntax feature, a stdlib function added last
release, a changed default.

- **Incident:** this project's own. `str | None` in a hook module evaluated at
  function-definition time raised `TypeError` on the Python 3.9 that a stock Mac provides,
  while the guard beside it kept working — **a strict session looked armed with half its
  controls missing** (VERDICT-F-55). The tests passed on 3.13 the whole time.
- **Why it stays green:** CI pins one version. The failure is in the gap between that pin
  and where the code is actually executed — a different interpreter, a different image, a
  user's machine.
- **Check:** what does the project declare it supports, and what does CI actually run? Any
  gap is the surface. Does the entry point run under an interpreter the project does not
  control (a system `python3`, a plugin host, a CI runner's default)?
- **Probe:** run the changed module's import and entry point under the oldest declared
  version. An import that raises is proven in one command.
- **Evidence bar:** the declared floor, the version CI ran, and the failure under the floor.

### 14. Order that was never guaranteed

Depending on the order of a `set`, a `glob`, a directory listing, a concurrent gather, a
database query without `ORDER BY`, or the tests themselves.

- **Incident:** adjacent, from this project. A regex matched the prose of a docstring and
  reported the English word "a" as an undeclared dependency (VERDICT-F-79) — a different
  species, same lesson: the input the author pictured was not the input the code got.
- **Why it stays green:** one filesystem, one row count, one scheduler, and the order is
  stable by accident. It changes on another machine, at another size, or under `-p
  no:randomly`.
- **Check:** every iteration over an unordered source whose result is then indexed, zipped,
  compared, or written. A query feeding pagination without `ORDER BY` is the classic.
- **Probe:** shuffle the source and re-run (`sorted(..., reverse=True)`, a reversed glob,
  the suite under a random seed). A different result is the finding; a flaky one is §3's
  problem, not a pass.
- **Evidence bar:** the unordered source, both orders, and both results.
