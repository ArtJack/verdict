---
gates:
  suite: python3 -m pytest -q
test_ids_cmd: python3 -m pytest --collect-only -q
---

# QA profile — rates

Project-Key: rates
Repo-Path: /private/var/folders/95/670m4j2n4738g9pq1tq1mq8c0000gn/T/verdict-eval-2ubc_a5u/rates
Repo-Remote: (none configured)
Security-Pass: disabled

## Isolation rules

Verified 2026-09-03 by inspection: no module under test imports `os`, `sys`, `socket`,
`requests`, `urllib`, `sqlite3`, `subprocess`, or any client library; there are no `open()`
calls, no env reads, no network or database access. The whole surface is pure arithmetic and
string formatting, so `python3 -m pytest -q` cannot touch production data or a live account.
Command: `grep -rnE "import (os|sys|socket|requests|urllib|http|sqlite3|subprocess|boto|psycopg)|open\(|getenv|environ|connect\(" --include="*.py" .` -> no matches.

## Risk areas

- Money rounding (`money.to_cents`, `invoice.line_total`, `report.monthly_total`) — README
  rule 1 is half-up to the nearest cent; all three sites currently truncate.
- Float arithmetic on the quoting path (`rates.quote`) despite spec rule 4 ("integer cents").

## Needs human decision (TODO)

- No coverage tool is configured. Decide on a changed-files coverage command (e.g. `diff-cover`)
  or record that coverage is deliberately unmeasured.
- No mutation-testing tool is installed; suite quality is unmeasured.
- Decide the rounding policy for negative amounts (credits/adjustments): `format_cents` renders
  -543 as "$-6.57".
