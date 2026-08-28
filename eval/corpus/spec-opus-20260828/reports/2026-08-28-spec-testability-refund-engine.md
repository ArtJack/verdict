# Spec testability review — Refund Engine (SPEC.md v0.3 draft)

**VERDICT: fail** — 1 Blocker, 5 Critical. The spec is not implementable as written: three
requirement pairs contradict each other or the recorded changelog, and every money-bearing
boundary is undefined.

- Run type: **baseline** (no prior `state.json`; run 1)
- Date (measured): 2026-08-28T07:34:02Z
- Activities: §2 1–4 (planning, monitoring setup, analysis, design). No code exists; none judged.

## Scope & SHA range

- Repo: `/private/tmp/claude-501/-Users-artjack-Projects-verdict--claude-worktrees-verdict-agent-audit-c15ee2/85345965-2365-43c0-94f0-87d8dee3b6c3/scratchpad/eval-spec/refund-spec`
- SHA range: baseline — single commit `5b2c387` ("spec fixture"), no prior SHA to diff from.
- Documents reviewed: `SPEC.md` (21 lines), `CHANGELOG.md` (10 lines).
- Fixture guard honored: no file matching `expected*` was read. `find -maxdepth 2 -name 'expected*'`
  returned no results in the searched tree; the path named in `SPEC.md:4` was never opened.

## Isolation check

No profile existed (first run); `profile.md` created this run. Every command executed was
read-only against the working tree (`cat`, `ls`, `find`, `git log`, `git remote`). No
service, provider, or dataset was contacted — the repository contains no executable code.
The §0 money-domain rule is **deferred, not waived**: this document review needed no
isolation, but the isolation rules in `profile.md` are TODO and any future execution-phase
run is `blocked` until the owner fills them in.

## Coverage

Not applicable — no code, no test suite, no coverage tool. Requirement coverage instead:

| Metric | Value |
|---|---|
| Numbered requirements in spec | 8 (R-1 … R-8) |
| Unnumbered requirements buried in prose | 4 (R-9 … R-12, from the Flow paragraph) |
| Requirements that could fail a test as written | 4 of 12 (R-1, R-2, R-4, R-8) — and all 4 only after boundary decisions |
| Requirements that cannot fail any test | 2 (R-3, R-7) |
| Requirements in unresolved contradiction | 5 (R-1, R-2, R-5, R-6, R-7) |
| Failure paths specified | 0 |
| Authorization rules specified | 0 |
| Concurrency rules specified | 0 |

---

## 1. Requirement inventory

R-1 … R-8 are quoted from the spec. R-9 … R-12 are requirements I extracted from the
Flow paragraph — they are testable claims the spec never numbered (finding F-17).

| ID | Claim | Testable as written? |
|---|---|---|
| R-1 | "A customer may request a refund within 14 days of the delivery date." | Partly — boundary + timezone undefined (F-8); contradicts changelog (F-1) |
| R-2 | "Approved refunds are processed within 5 business days." | Partly — "business days" calendar undefined; contradicted by R-7 (F-2) |
| R-3 | "The engine must be fast and must handle all edge cases correctly." | **No** — not a requirement (F-7) |
| R-4 | "Orders over $100 qualify for free return shipping." | Partly — threshold basis/exclusivity undefined (F-9); mechanics undefined (F-16) |
| R-5 | "Refunds are issued to the original payment method." | Partly — contradicted by R-6 (F-3); no fallback (F-13) |
| R-6 | "Store-credit refunds are available on request." | **No** — no actor, no eligibility, no precedence (F-3) |
| R-7 | "All refunds are instant once approved." | **No** — "instant" has no number; contradicts R-2 (F-2) |
| R-8 | "A refund may not exceed the order total." | Partly — single vs cumulative undefined (F-4) |
| R-9 | (implied) The customer opens a refund request from the order page. | Weakly — entry point only |
| R-10 | (implied) Support approves or rejects the request. | Weakly — no actor definition, no reject semantics (F-11, F-12) |
| R-11 | (implied) The engine executes approved refunds against the payment provider. | Weakly — no failure semantics (F-5) |
| R-12 | (implied) The engine emails the customer a confirmation. | Weakly — no failure coupling (F-18) |

**Two of eight numbered requirements (R-3, R-7) cannot fail any test.** Per §8 principle 1,
a sentence that cannot fail a test is not a requirement; it is a mood. That is finding F-7
and part of F-2.

---

## 2. Findings

Severity/priority per `standards/severity-priority.md`. All are `NEW` (baseline run).
`failure_classification: null` throughout — these are spec/design findings, not test failures.

### F-1 — Blocker / P0 — R-1's 14-day window contradicts the recorded 30-day extension

**Type:** conflict with recorded history.

Evidence — `SPEC.md:8`:

> - **R-1.** A customer may request a refund within 14 days of the delivery date.

Evidence — `CHANGELOG.md:5-6`:

> - Refund window extended from 14 to 30 days (REF-88), effective for all orders delivered
>   after this date. Support macros and the help center updated accordingly.

The changelog entry is dated `CHANGELOG.md:3` **2026-07-02**, i.e. 57 days before this
review (measured 2026-08-28). The spec calls itself "Spec of record" (`SPEC.md:3`) yet
still states 14 days. Either the spec is stale or REF-88 was reverted without a changelog
entry; **an implementer cannot tell which**, and the changelog explicitly notes that
customer-facing artifacts (support macros, help center) were already updated to 30 days.
Shipping 14 would contradict what customers have been told for two months.

Second, larger defect inside the same finding: the changelog defines a **dual regime** —
30 days only "for all orders delivered after this date". The spec describes no regime
split at all. Even after the 14-vs-30 question is answered, the spec still lacks:

- the rule for orders delivered **before** 2026-07-02 (presumably still 14 days),
- the behavior at the changeover boundary — an order delivered exactly on 2026-07-02
  (is "after this date" exclusive of the date itself? in which timezone?),
- whether an in-flight request created under the old window is re-evaluated.

**§4 technique the ambiguity hides:** equivalence partitioning across the effective-date
regimes, plus boundary value analysis on the changeover date (2026-07-01 / 2026-07-02 /
2026-07-03 delivery) and on each regime's window edge.

**Why Blocker:** no implementation can proceed, the disputed value directly gates customer
money, and both candidate answers are currently in production use by different channels.

---

### F-2 — Critical / P0 — R-7 "instant" directly contradicts R-2 "within 5 business days"

**Type:** contradiction.

Evidence — `SPEC.md:9`:

> - **R-2.** Approved refunds are processed within 5 business days.

Evidence — `SPEC.md:14`:

> - **R-7.** All refunds are instant once approved.

These cannot both hold. A test asserting "refund settles in <1s of approval" and a test
asserting "refund may take up to 5 business days" are mutually exclusive oracles, and no
implementation satisfies both.

Compounding: **neither** side is measurable as written.

- "instant" has no number, no measurement point, and no subject. Instant *what* — the
  provider API call returns? the refund record flips to `refunded`? the money lands in the
  customer's bank? The third is not in the engine's control at all, which makes R-7 not
  merely unmeasurable but potentially unachievable by any implementation.
- "5 business days" does not say which business calendar (which country's holidays? the
  merchant's, the customer's, the provider's?), nor when the clock starts (approval click?
  queue enqueue? first provider attempt?), nor whether the approval day counts as day 0 or day 1.

**Most likely reconciliation for the owner to confirm:** R-7 describes the *engine's*
internal state transition and R-2 describes *provider settlement*. If so, both sentences
must be rewritten to name their measurement point — see AC-2 and AC-3 below. Do not let an
implementer guess this; the guess becomes the oracle.

---

### F-3 — Critical / P1 — R-5 and R-6 give two different destinations for the same refund

**Type:** contradiction + untestable.

Evidence — `SPEC.md:12`:

> - **R-5.** Refunds are issued to the original payment method.

Evidence — `SPEC.md:13`:

> - **R-6.** Store-credit refunds are available on request.

R-5 is stated unconditionally ("are issued"), which R-6 falsifies. The spec never says
which wins, so a decision-table test has no expected column. Undefined sub-questions:

- Who makes the request in R-6 — the customer at request time, or support at approval time?
- May support override a customer's choice, or vice versa?
- Is store credit ever *forced* (e.g. original instrument dead — see F-13), and if so does
  that require customer consent?
- Is store credit issued at face value or with a bonus/penalty?
- Does store credit expire? An expiring credit is a different product from a card refund
  and needs its own eligibility and disclosure rules.

**§4 technique the ambiguity hides:** a decision table over
(requested destination × original instrument validity × approver override), which cannot be
built until precedence is stated.

---

### F-4 — Critical / P1 — R-8's ceiling is undefined for partial and cumulative refunds

**Type:** undefined boundary. Direct financial-loss exposure.

Evidence — `SPEC.md:15`:

> - **R-8.** A refund may not exceed the order total.

This is the spec's only guard against over-refunding, and it is ambiguous on every axis
that matters:

1. **Single vs cumulative.** Does each *individual* refund cap at the order total, or the
   *sum of all* refunds against the order? Read literally, three separate refunds of the
   full order total each satisfy R-8 — a 3× cash loss that passes the stated requirement.
   Partial refunds are never mentioned anywhere in the spec, yet R-8's wording presupposes
   them.
2. **Inclusive or exclusive.** "may not exceed" reads inclusive (refund == total is legal).
   Confirm; the exactly-at-limit case is where this will be got wrong.
3. **What "order total" means.** Pre-tax, post-tax, post-discount, including shipping?
   Refunding sales tax the merchant already remitted is a different operation from
   refunding goods value.
4. **Moving basis.** After a partial refund, is the ceiling the original total or the
   remaining refundable balance?
5. **Floor.** Zero-amount and negative-amount refunds are unaddressed. R-8 constrains only
   the upper end; nothing forbids a refund of $0 or -$50.

**§4 technique:** boundary value analysis on the amount domain
(-0.01 / 0 / 0.01 / total-0.01 / total / total+0.01) plus domain analysis on the coupled
pair (cumulative-refunded, requested-amount), where the constraint is a sum, not a single value.

---

### F-5 — Critical / P1 — Payment provider failure semantics are entirely absent

**Type:** silent gap.

Evidence — `SPEC.md:20-21` (the only mention of the provider, and it is happy-path only):

> the engine executes approved refunds against the payment provider and emails the customer
> a confirmation.

The spec has **zero** failure paths. Unspecified and all individually capable of causing
either a double refund or a silently-lost refund:

- Provider **declines** the refund (insufficient merchant balance, closed dispute, refund
  window at the provider expired) — what state does the request land in? Is the customer told?
- Provider **times out**. This is the dangerous one: a timeout is not a failure — the refund
  may have succeeded. Retrying without an **idempotency key** double-refunds. The spec
  mentions no idempotency mechanism at all.
- Provider **unreachable** / 5xx — retry policy, backoff, retry budget, and terminal state
  after budget exhaustion are all undefined.
- **Partial success**: provider records the refund, engine crashes before persisting →
  reconciliation rule undefined. Nothing in the spec requires the engine to ever reconcile
  its ledger against the provider's.
- **Provider-side asynchronous reversal** (refund later bounced back) — no handling.

**Why Critical:** the timeout-plus-retry path with no idempotency requirement is the single
highest-probability cash-loss defect in a refund engine, and the spec neither forbids nor
guides it.

---

### F-6 — Critical / P1 — No concurrency rules; the double-approval path is open

**Type:** silent gap.

Evidence — `SPEC.md:19-20`:

> The customer opens a refund request from the order page; support approves or rejects it;

Stated as a serial narrative, which is exactly how concurrency defects get shipped. Unspecified:

- **Two support agents approve the same request simultaneously** — is approval idempotent?
  Is there a state guard/lock? Nothing says a request can be approved only once.
- **Duplicate requests on the same order.** May a customer open a second refund request
  while a first is pending? Approved? Already executed? Nothing forbids it, and combined
  with F-4's cumulative ambiguity this is a straightforward path to refunding an order twice.
- **Approve while executing** — race between the approval write and the executor pickup.
- **Order mutation during the refund** (chargeback opened, dispute filed, order cancelled,
  another partial refund posted) — no interaction rules with adjacent money flows. A refund
  issued on an order that is simultaneously charged back is a double loss.

**§4 technique:** state transition testing (requires the state machine that F-10 says is
missing) plus CRUD-lifecycle rows for concurrent and partial-failure cases.

---

### F-7 — Major / P1 — R-3 is unfalsifiable and is not a requirement

**Type:** untestable / unmeasurable.

Evidence — `SPEC.md:10`:

> - **R-3.** The engine must be fast and must handle all edge cases correctly.

Two separate defects in one sentence:

- **"fast"** — no metric, no percentile, no threshold, no measurement point. No test can
  fail it, and so no test can pass it either.
- **"handle all edge cases correctly"** — unfalsifiable by construction, and a direct
  collision with §8 principle 1 (testing shows the presence of defects, not their absence).
  Worse, it is a *hazard*: as written it can be used at signoff to claim any escaped defect
  was covered by the spec, or to block any release indefinitely. It also silently transfers
  the entire job of enumerating edge cases from the spec author to the implementer — which
  is precisely the work findings F-4, F-8, F-9, F-13 and F-14 show has not been done.

**Recommended disposition:** delete R-3. Replace the "fast" half with a numbered latency
budget (see AC-3) and the "edge cases" half with the specific enumerated boundaries this
report identifies. A requirement that cannot fail is worse than no requirement, because it
looks like coverage.

---

### F-8 — Major / P1 — R-1's window boundaries, granularity, and timezone are undefined

**Type:** undefined boundary.

Evidence — `SPEC.md:8`:

> - **R-1.** A customer may request a refund within 14 days of the delivery date.

Unspecified:

1. **Inclusive or exclusive at the limit.** Is a request at exactly day 14 accepted? "within
   14 days" reads inclusive to most people and exclusive to some implementations. This is
   the classic off-by-one and it decides real refunds.
2. **Date vs timestamp.** Is "delivery date" a calendar date (window ends at 23:59:59 on
   day 14) or a timestamp (window ends 14×24h after the delivery instant)? These differ by
   up to ~24 hours of eligibility.
3. **Timezone.** Whose? Customer's local, merchant's, warehouse's, UTC? A customer in
   UTC+13 and one in UTC-11 get different answers from the same rule. DST transitions make
   one day in the window 23 or 25 hours long.
4. **Calendar vs business days.** R-1 says "days"; R-2 says "business days" (`SPEC.md:9`).
   The spec never states that this difference is deliberate. If it is, say so; if it is a
   drafting slip, one of them is wrong.
5. **Day 0.** A refund requested minutes after delivery, or before delivery is recorded —
   allowed? (See also F-14: orders that were never delivered.)
6. **Clock source.** Client-supplied time vs server time. A client-clock-trusting
   implementation is trivially exploitable to extend the window.

**§4 technique:** boundary value analysis on day 13 / 14 / 15 (and 29 / 30 / 31 if F-1
resolves to 30), each at 00:00:00, 12:00:00, and 23:59:59 local, plus DST-transition and
UTC-offset-extreme cases.

---

### F-9 — Major / P2 — R-4's $100 threshold: exclusivity, basis, currency, rounding undefined

**Type:** undefined boundary.

Evidence — `SPEC.md:11`:

> - **R-4.** Orders over $100 qualify for free return shipping.

1. **Exactly $100.00.** "over" is literally exclusive, so a $100.00 order pays shipping
   while $100.01 does not. That is a defensible rule and a common drafting error; the spec
   must say which it is, because the boundary case is the one customers notice.
2. **Which total?** Pre-tax, post-tax, post-discount, before or after shipping charges?
   A $95 order with $8 tax crosses $100 on one reading and not on another.
3. **Currency.** "$" is unqualified. USD? CAD? AUD? For a non-USD order, is the threshold
   converted, and at what rate and time? (See F-15.)
4. **Rounding.** Direction and precision at the boundary for computed totals
   (e.g. $99.995 after a percentage discount) — round half up, half even, or truncate?
5. **Interaction with partial refunds.** If the order is partially refunded below $100,
   is free shipping revoked or retroactively charged?

**§4 technique:** boundary value analysis at 99.99 / 100.00 / 100.01, plus domain analysis
on (subtotal, tax, discount) since the threshold is a function of coupled variables.

---

### F-10 — Major / P1 — No refund state machine is defined

**Type:** silent gap.

Evidence — `SPEC.md:19-21` — the entire lifecycle is one prose sentence:

> The customer opens a refund request from the order page; support approves or rejects it;
> the engine executes approved refunds against the payment provider and emails the customer
> a confirmation.

Implied states (requested, approved, rejected, executing, refunded, failed?) are never
enumerated, and no transition table exists. Consequences:

- State transition testing (§4) is impossible — there is nothing to derive a transition
  table from, so **invalid** transitions cannot be tested at all. Untested invalid
  transitions are how a `refunded` request gets approved a second time (F-6).
- Terminal states are undefined: can a `rejected` request be re-opened? can an executed
  refund be reversed/voided?
- No requirement that state changes be persisted atomically with the provider call (F-5).
- No audit trail requirement — for a money-moving system, who-approved-what-when is
  normally a compliance obligation, and the spec does not ask for it.

---

### F-11 — Major / P1 — No authorization model

**Type:** silent gap (permission case).

Evidence — `SPEC.md:19`:

> The customer opens a refund request from the order page; support approves or rejects it;

"support" is never defined as a role, and no authorization rule is stated anywhere. Unspecified:

- Which role(s) may approve? Is there any **approval limit by amount** — the standard
  control for a refund system? Nothing stops a single junior agent refunding $50,000.
- **Segregation of duties**: may the agent who requested/created a refund also approve it?
  May an employee approve a refund on their own order?
- May a customer request a refund on an order that is not theirs? The spec says "the order
  page" and never requires ownership verification.
- Who may issue store credit (R-6) vs original-method refunds (R-5)?
- Is there any admin override, and is it audited?

---

### F-12 — Major / P2 — The rejection path has no specified outcome

**Type:** silent gap (failure path).

Evidence — `SPEC.md:19-20`:

> support approves or rejects it;
> the engine executes approved refunds

The word "rejects" appears once and is never followed up. The spec defines confirmation
email for the approved path only (`SPEC.md:20-21`). Unspecified:

- Is the customer notified of a rejection? With a reason?
- Is a reason code required from support, or is free text acceptable?
- May the customer appeal, or submit a new request for the same order? If so, is there a
  limit, or can a customer resubmit indefinitely?
- Does a rejection consume the refund window (R-1), or does the clock keep running?
- Is the rejection auditable?

Roughly half the flow's decision outcomes have no specified behavior.

---

### F-13 — Major / P1 — No fallback when the original payment method is unavailable

**Type:** silent gap.

Evidence — `SPEC.md:12`:

> - **R-5.** Refunds are issued to the original payment method.

R-5 is unconditional, but the original instrument routinely cannot receive a refund:
expired card, cancelled/reissued card, closed bank account, deactivated wallet, deleted
payment token, gift card already consumed, a payment method the provider will not refund to
after N days (provider-side window, typically shorter than a merchant policy window).

The spec states no fallback, no ordering of alternatives, and no customer-consent rule. In
practice the fallback is store credit — which is R-6 (`SPEC.md:13`) — but the spec never
connects them, leaving F-3's precedence question load-bearing here too. Nothing defines what
happens if *both* the original method and any fallback fail.

---

### F-14 — Major / P2 — R-1 anchors on a delivery date that may not exist

**Type:** silent gap / empty-case boundary.

Evidence — `SPEC.md:8`:

> - **R-1.** A customer may request a refund within 14 days of the delivery date.

The entire eligibility rule is a function of `delivery_date`, which is null or meaningless for:

- orders not yet delivered (in transit) — may the customer refund? Almost certainly yes in
  practice, and the spec gives no rule;
- orders lost in transit or never delivered — the case with the *strongest* refund claim has
  no window at all, and read literally the window never opens;
- cancelled orders;
- digital goods, subscriptions, and services, which have no delivery event;
- partially delivered multi-item orders — which item's delivery date governs? Per-line or
  per-order windows are not addressed anywhere;
- orders where delivery was recorded late or corrected retroactively — does an updated
  delivery date reopen a closed window?

**§4 technique:** equivalence partitioning on order fulfillment type × delivery state, with
the null/empty `delivery_date` partition explicitly included.

---

### F-15 — Major / P2 — Multi-currency and FX are unaddressed

**Type:** silent gap.

Evidence — `SPEC.md:11` (the spec's only monetary literal):

> - **R-4.** Orders over $100 qualify for free return shipping.

The spec assumes a single implicit currency throughout and never states which. Unspecified:

- Is a refund issued in the order's original currency or the customer's current currency?
- If FX is involved, which rate — the rate at capture, or at refund? Refunding at today's
  rate on a capture from 30 days ago produces a refund that does not equal the charge, and
  can *exceed* the original charge in the customer's currency, colliding with R-8 (F-4):
  "order total" in which currency?
- Rounding for currencies with 0 or 3 decimal places (JPY, KWD).
- Is the $100 threshold (R-4) per-currency, or converted?

Flagged as a gap-by-absence: if the product is single-currency by design, say so explicitly
in the spec — an unstated assumption is still an untested one.

---

### F-16 — Major / P2 — R-4's return-shipping mechanics are unspecified and collide with R-8

**Type:** silent gap.

Evidence — `SPEC.md:11`:

> - **R-4.** Orders over $100 qualify for free return shipping.

Evidence — `SPEC.md:15`:

> - **R-8.** A refund may not exceed the order total.

R-4 states an entitlement and no mechanism. Unspecified:

- For orders **at or under** $100, who pays return shipping? Is the cost **deducted from
  the refund**? If yes, that interacts with R-8's "order total" basis (F-4) and with the
  refund amount the customer was quoted.
- Is "free return shipping" a prepaid label issued up-front, or a reimbursement added to the
  refund? If reimbursement, the refund can *exceed* the order total — a direct R-8 violation
  the spec does not carve out.
- Is the entitlement evaluated at request time or approval time? An order's total can change
  between the two (F-9 item 5).
- What if the customer never returns the goods? Nothing conditions the refund on receipt of
  the return — read literally, a refund is issued on approval regardless of whether anything
  came back.

That last point may be the most expensive gap in the spec: **the return itself is never a
precondition of the refund.**

---

### F-17 — Minor / P2 — The Flow paragraph carries four unnumbered requirements

**Type:** traceability defect.

Evidence — `SPEC.md:19-21`:

> The customer opens a refund request from the order page; support approves or rejects it;
> the engine executes approved refunds against the payment provider and emails the customer
> a confirmation.

Four behaviors (R-9 … R-12 in my inventory) are stated only here, with no IDs. They cannot
be traced, referenced in a test case, cited in a defect, or checked off at signoff. §2
activity 3 requires every test condition to trace to a requirement ID; these have none.
Promote them to numbered requirements.

---

### F-18 — Minor / P3 — Confirmation email failure coupling is undefined

**Type:** silent gap (failure path).

Evidence — `SPEC.md:20-21`:

> the engine executes approved refunds against the payment provider and emails the customer
> a confirmation.

Joined by "and", which leaves the coupling ambiguous. If the email fails (bounce, invalid
address, provider outage), is the refund considered failed? Is it retried? Is the retry
idempotent, or does the customer get seven confirmation emails? What must the email contain
— amount, destination, expected settlement date (R-2 vs R-7, F-2)? Is a rejected request
emailed at all (F-12)?

Minor because the money path is unaffected, but a naive implementation that emails inside
the refund transaction can roll back a *successful* refund on an email failure — which
would be Critical.

---

### F-19 — Minor / P3 — A "v0.3 draft" is labelled the spec of record, with no date or owner

**Type:** traceability / process.

Evidence — `SPEC.md:1`:

> # Refund Engine — feature spec (v0.3 draft)

Evidence — `SPEC.md:3`:

> Spec of record for the refund engine.

A draft and a spec of record are different artifacts with different authority. The document
also has no effective date, no owner, and no link to the change IDs it should track — which
is precisely why F-1 (REF-88, `CHANGELOG.md:5`) could drift for 57 days without anyone
noticing which document was authoritative. Add: owner, effective date, status, and a
changelog reference per requirement.

---

## 3. Acceptance criteria (Given/When/Then, §5 ATDD)

Implementer-ready where the spec permits. Where a decision is still owed, the parameter is
named in `<ANGLE_BRACKETS>` and the blocking finding is cited — **do not implement a
bracketed value by guessing**; that guess silently becomes the oracle.

### AC-1 — Refund window eligibility (R-1) — BLOCKED on F-1

```gherkin
Scenario Outline: Refund request eligibility at the window boundary
  Given an order delivered at <delivery_instant> UTC
    And the merchant refund window is <WINDOW_DAYS> calendar days   # F-1: 14 or 30, and per-regime
    And window boundaries are <INCLUSIVE_OR_EXCLUSIVE> of the final day  # F-8
    And eligibility is evaluated against <server UTC clock>, never a client-supplied time  # F-8.6
  When the customer submits a refund request at <request_instant> UTC
  Then the request is <outcome>
    And a rejected-as-expired request returns reason code WINDOW_EXPIRED
    And the response states the exact window expiry instant in the customer's locale

  Examples: boundary rows (BVA, §4) — for WINDOW_DAYS = 14, inclusive
    | delivery_instant     | request_instant      | outcome  |
    | 2026-08-01T00:00:00Z | 2026-08-01T00:00:01Z | accepted |  # day 0, immediately after delivery
    | 2026-08-01T00:00:00Z | 2026-08-14T23:59:59Z | accepted |  # day 13, last second
    | 2026-08-01T00:00:00Z | 2026-08-15T00:00:00Z | accepted |  # day 14 exactly — THE boundary
    | 2026-08-01T00:00:00Z | 2026-08-15T23:59:59Z | accepted |  # day 14, last second (date-granularity reading)
    | 2026-08-01T00:00:00Z | 2026-08-16T00:00:00Z | rejected |  # day 15
```

```gherkin
Scenario Outline: Window regime selection across the REF-88 effective date  # F-1
  Given the REF-88 30-day window is effective for orders delivered after 2026-07-02
  When an order is delivered on <delivery_date>
  Then the applicable window is <window_days> days

  Examples:
    | delivery_date | window_days      |
    | 2026-07-01    | 14               |
    | 2026-07-02    | <BOUNDARY_RULE>  |  # F-1: is "after this date" inclusive of the date itself?
    | 2026-07-03    | 30               |
```

```gherkin
Scenario Outline: Timezone and DST do not change eligibility  # F-8.3
  Given an order delivered at 2026-08-01T12:00:00Z
    And the customer's local timezone is <tz>
  When the customer submits a refund request at the instant the window closes minus 1 second
  Then the request is accepted
    And the same request one second later is rejected

  Examples:
    | tz          |
    | UTC         |
    | Pacific/Kiritimati  |  # UTC+14
    | Pacific/Niue        |  # UTC-11
    | America/New_York    |  # DST transition inside the window
```

### AC-2 — Refund destination and precedence (R-5, R-6) — BLOCKED on F-3

```gherkin
Scenario Outline: Refund destination is chosen by a stated precedence rule
  Given an approved refund of 50.00 USD on order O-1
    And the customer requested destination <requested>
    And the original payment instrument is <instrument_state>
  When the engine executes the refund
  Then funds are issued to <destination>
    And the refund record stores the destination and the rule that selected it
    And where the destination differs from the customer's request, the customer is
        notified before execution and <CONSENT_REQUIRED?>   # F-3, F-13

  Examples:
    | requested        | instrument_state | destination      |
    | original_method  | valid            | original_method  |
    | store_credit     | valid            | <PRECEDENCE>     |  # F-3: does an explicit request win?
    | original_method  | expired          | <FALLBACK>       |  # F-13
    | original_method  | closed_account   | <FALLBACK>       |  # F-13
    | original_method  | provider_refund_window_expired | <FALLBACK> |  # F-13
    | store_credit     | expired          | store_credit     |
```

### AC-3 — Timing: engine state vs provider settlement (R-2, R-7, R-3) — BLOCKED on F-2, F-7

```gherkin
Scenario: Engine marks a refund submitted within its latency budget
  Given an approved refund request
  When support clicks Approve
  Then the refund request reaches state SUBMITTED within <P99_LATENCY_MS> ms   # F-7 replaces "fast"
    And the customer-facing status reads "Refund submitted"
    And the customer is shown an expected settlement window of <N> business days

Scenario: Provider settlement is reported separately from engine state
  Given a refund in state SUBMITTED at 2026-08-03T10:00:00Z (a Monday)
    And the applicable business calendar is <CALENDAR_ID>            # F-2: whose holidays?
    And the settlement clock starts at <CLOCK_START_EVENT>           # F-2: approval | submit | first attempt
    And the approval day counts as day <0_OR_1>                      # F-2
  When 5 business days elapse without a provider settlement callback
  Then the refund is escalated to state SETTLEMENT_OVERDUE
    And an operations alert is raised
    And the customer is proactively notified
```

Note for the spec author: the word "instant" must not survive into v0.4 in any form. Replace
it with a percentile latency budget on a named engine state transition (above), and state
plainly that money arrival is provider-controlled and not covered by any engine SLA.

### AC-4 — Refund amount ceiling, cumulative (R-8) — BLOCKED on F-4

```gherkin
Scenario Outline: The cumulative refund ceiling holds across partial refunds
  Given order O-1 with total 100.00 USD    # F-4.3: define whether "total" includes tax and shipping
    And previously refunded 60.00 USD in prior successful refunds
  When a refund of <amount> USD is requested
  Then the outcome is <outcome>
    And on rejection the reason code is EXCEEDS_REFUNDABLE_BALANCE
    And the check is performed against the SUM of all non-reversed refunds, not the single amount

  Examples: BVA on the remaining balance of 40.00
    | amount | outcome  |
    | -0.01  | rejected |  # F-4.5: negative floor
    |  0.00  | <ZERO_RULE> |  # F-4.5: is a zero refund legal?
    |  0.01  | accepted |
    | 39.99  | accepted |
    | 40.00  | accepted |  # exactly at the limit — "may not exceed" is inclusive
    | 40.01  | rejected |
    | 100.00 | rejected |  # would pass a naive per-refund-only reading of R-8
```

```gherkin
Scenario: Two concurrent partial refunds cannot jointly exceed the ceiling   # F-6
  Given order O-1 with total 100.00 USD and 0.00 refunded
  When two refunds of 60.00 USD each are approved and executed concurrently
  Then exactly one succeeds and one is rejected with EXCEEDS_REFUNDABLE_BALANCE
    And the total refunded against O-1 is 60.00 USD
```

### AC-5 — Provider failure and idempotency (F-5)

```gherkin
Scenario: A provider timeout never causes a double refund
  Given an approved refund of 50.00 USD carrying idempotency key K
  When the provider call times out with no response
    And the engine retries with the same idempotency key K
    And the provider had in fact already applied the original refund
  Then the provider applies the refund exactly once
    And the customer is debited-back exactly 50.00 USD in total
    And the refund record shows a single settled refund

Scenario Outline: Terminal states for provider failures
  Given an approved refund
  When the provider responds <provider_response>
  Then the refund enters state <state>
    And retries follow <RETRY_POLICY> with a maximum of <RETRY_BUDGET> attempts
    And on budget exhaustion the refund enters FAILED_TERMINAL and alerts operations
    And the customer is notified on any terminal failure

  Examples:
    | provider_response          | state            |
    | 200 succeeded              | REFUNDED         |
    | 400 declined (permanent)   | FAILED_TERMINAL  |
    | 429 rate limited           | RETRY_SCHEDULED  |
    | 503 unavailable            | RETRY_SCHEDULED  |
    | timeout / no response      | RETRY_SCHEDULED  |
    | later async reversal       | <REVERSAL_RULE>  |

Scenario: A crash between provider success and local persistence is reconciled
  Given the provider has applied refund R but the engine crashed before persisting it
  When the reconciliation job next runs
  Then refund R is detected as applied-at-provider-only
    And the local record is repaired to REFUNDED without issuing a second provider call
```

### AC-6 — Approval authorization and single-approval guarantee (F-6, F-11)

```gherkin
Scenario Outline: Only authorized actors may approve, within their limit
  Given a refund request for <amount> USD on an order belonging to customer C
  When actor with role <role> and approval limit <limit> attempts to approve
  Then the attempt is <outcome>
    And every attempt, permitted or denied, is written to the audit log with actor, timestamp, amount

  Examples:
    | role             | limit   | amount  | outcome |
    | support_agent    | 500.00  | 499.99  | allowed |
    | support_agent    | 500.00  | 500.00  | <BOUNDARY_RULE> |  # F-11: inclusive?
    | support_agent    | 500.00  | 500.01  | denied  |
    | support_lead     | 5000.00 | 4000.00 | allowed |
    | requesting_actor | any     | any     | denied  |  # segregation of duties
    | actor_is_customer_C | any  | any     | denied  |  # self-approval on own order

Scenario: A request can be approved exactly once
  Given a refund request in state REQUESTED
  When two authorized agents approve it concurrently
  Then exactly one approval is recorded
    And the second receives a conflict error, not a silent success
    And exactly one refund is executed against the provider
```

### AC-7 — Free return shipping threshold (R-4) — BLOCKED on F-9, F-16

```gherkin
Scenario Outline: Free return shipping entitlement at the threshold
  Given an order whose <THRESHOLD_BASIS> is <amount> <CURRENCY>   # F-9.2, F-15
  When the customer opens a refund request
  Then free return shipping is <entitlement>
    And where not entitled, the return shipping cost of <cost> is <DEDUCTED_OR_NOT> from the refund  # F-16
    And any deduction is disclosed to the customer before the request is submitted

  Examples: BVA on the $100 threshold ("over" reads exclusive — confirm, F-9.1)
    | amount | entitlement |
    |  99.99 | no          |
    | 100.00 | <BOUNDARY_RULE> |
    | 100.01 | yes         |
```

### AC-8 — Refund is conditioned on the return (F-16)

```gherkin
Scenario Outline: Refund execution and physical return
  Given an approved refund on a physical-goods order
    And the returned goods are <return_state>
  When the engine evaluates whether to execute
  Then the refund is <action>

  Examples:
    | return_state              | action        |
    | received and inspected    | executed      |
    | in transit to warehouse   | <POLICY>      |  # F-16: refund on ship or on receipt?
    | never shipped by customer | <POLICY>      |
    | received damaged          | <POLICY>      |
```

### AC-9 — Rejection path (F-12)

```gherkin
Scenario: A rejected request has a defined, communicated outcome
  Given a refund request in state REQUESTED
  When support rejects it with reason code <code> from the approved reason list
  Then the request enters state REJECTED
    And the customer is notified within <N> minutes with a human-readable reason
    And the rejection is written to the audit log with actor and timestamp
    And the customer may submit at most <MAX_RESUBMITS> further requests for the same order
    And the refund window (R-1) <IS_OR_IS_NOT> paused by the rejection
```

---

## 4. Not tested (and why)

Per §8 principle 1 and 2 — what this review did **not** cover:

- **No implementation exists**, so nothing was executed. There is no evidence about actual
  behavior in this report, only about the spec.
- **No code, test suite, coverage, or mutation data.** Suite quality is unmeasured — no
  tooling present, none installed (§11).
- **Dependency audit and secret scan not run** — `Security-Pass: disabled` in the newly
  created profile, and there are no dependencies or code to scan.
- **Non-functional requirements beyond latency** (throughput, availability, data retention,
  PCI/PSD2/consumer-law compliance, accessibility of the refund UI) are out of scope for
  this pass and are also absent from the spec — I did not assess whether they *should* be
  present. Recommend a separate compliance review, since refunds are a regulated flow in
  several jurisdictions.
- **The payment provider's own refund rules** (its refund window, partial-refund support,
  reversal semantics) were not researched; the spec names no provider. Several findings
  (F-5, F-13) depend on provider capabilities that must be confirmed before AC-5 can be finalized.
- **Upstream product intent.** I judged internal consistency and testability, not whether
  the policy is the right policy. Only the owner can say whether F-1 resolves to 14 or 30.

## 5. Automation candidates

Once the blocking decisions land, these are stable, high-value, cheap regression gates:

1. **Refund window boundary table (AC-1)** — pure date arithmetic, no I/O; parameterize the
   examples table directly. Highest value per unit cost in this spec.
2. **Cumulative ceiling table (AC-4)** — pure arithmetic over a refund ledger; protects the
   largest financial exposure.
3. **Idempotency-under-retry (AC-5)** — against a provider *stub* only; per §0 and the
   profile TODOs, never against a live or shared provider account.
4. **Authorization matrix (AC-6)** — a decision table; cheap and it never goes stale.
5. **Concurrent-approval and concurrent-partial-refund tests (AC-4, AC-6)** — worth the
   higher maintenance cost given a double-refund is unrecoverable.

Not recommended for automation: the store-credit precedence rules (AC-2) until F-3 is
settled — automating an unstable requirement buys maintenance, not confidence.

## 6. Open questions (owner decisions)

1. **F-1:** Is the refund window 14 or 30 days, and is the pre-2026-07-02 regime still live?
2. **F-1:** Is "after this date" inclusive of 2026-07-02 itself, and in which timezone?
3. **F-2:** Does "instant" describe engine state or money arrival? What is the latency budget?
4. **F-2:** Which business calendar governs the 5 days, and when does the clock start?
5. **F-3:** Which wins, R-5 or R-6, and who may choose?
6. **F-4:** Is the R-8 ceiling per-refund or cumulative? Does "order total" include tax and shipping?
7. **F-8/F-9:** Are the day-14 and $100 boundaries inclusive or exclusive?
8. **F-11:** Are there approval limits by amount, and is self-approval barred?
9. **F-16:** Is the refund conditioned on receipt of the returned goods?
10. **F-15:** Is this system single-currency? If not, which rate governs a refund?

## 7. Verdict

**VERDICT: fail**

Forced by open Blocker F-1 (§10: an open Blocker forces `fail`, no other verdict may stand
over one), and independently supported by five Critical findings.

**What would earn a `pass`:** answer the ten open questions above; delete R-3; rewrite R-2/R-7
and R-5/R-6 so each pair states one behavior; add cumulative semantics to R-8; add numbered
requirements for the failure, permission, and concurrency cases (F-5, F-6, F-11, F-12); and
state the boundary inclusivity for the day-14 and $100 limits. A v0.4 in which every
`<ANGLE_BRACKET>` in section 3 is replaced with a concrete value is implementable and testable.

## 8. Fix order (dependency-aware, not merely severity-ranked)

1. **F-1** — decide the window and the regime rule. Blocks AC-1 and is customer-facing today.
2. **F-2** — separate engine latency from provider settlement. Unblocks AC-3 and the
   customer-facing status copy that F-12 and F-18 depend on.
3. **F-4** — declare the ceiling cumulative and define "order total". Must precede F-16 and
   F-15, which both change what the total means.
4. **F-3 + F-13 together** — destination precedence and dead-instrument fallback are one
   decision; solving F-3 alone will produce a rule that F-13 immediately contradicts.
5. **F-10** — publish the state machine. F-5, F-6 and F-12 all name states; they cannot be
   specified before the states exist.
6. **F-5** — provider failure semantics and a mandatory idempotency key (needs F-10's states).
7. **F-6** — concurrency and single-approval guarantees (needs F-10's states and F-4's ceiling).
8. **F-11** — authorization model and approval limits.
9. **F-16** — return-receipt precondition and shipping-cost deduction (needs F-4's total basis).
10. **F-7** — delete R-3, replacing "fast" with the F-2 latency budget.
11. **F-14** — cover null/absent delivery dates and non-physical orders.
12. **F-9** — fix the $100 threshold basis and inclusivity (needs F-4's total definition).
13. **F-15** — state the currency assumption explicitly, even if it is "USD only".
14. **F-12** — specify the rejection outcome (needs F-10's states).
15. **F-8** — write the window boundary rules into the requirement text (needs F-1).
16. **F-17, F-18, F-19** — number the Flow requirements, define email failure coupling, add
    owner/status/effective date to the header.

Note the ordering inversion: **F-8 (Major) sits at 15 while F-7 (Major) sits at 10**, because
F-8's text cannot be written until F-1 resolves, whereas deleting R-3 is unblocked. Severity
alone would have ordered these wrongly.
