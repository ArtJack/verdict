# QA Profile — pricer

Project-Key: pricer
Repo-Path: /private/var/folders/95/670m4j2n4738g9pq1tq1mq8c0000gn/T/verdict-eval-zh27mjk5/pricer
Repo-Remote: (none configured)
Security-Pass: disabled

## Isolation check

Module under test (`pricer.py`) is pure computation: no network, no database, no
filesystem writes, no third-party accounts, no clock-dependent production code. The test
suite reads one local JSON fixture (read-only). Executing the suite is safe.
Isolation check command: n/a (no external resources). Result this run: PASS (no side
effects possible).

## Risk areas (TODO — human confirmation)

- Money path: `net_proceeds` computes seller payouts; rounding correctness is
  financially material. Confirm the required rounding tolerance / contract.
- `is_listable` gates whether a listing is shown — boundary (price == floor) is a real
  production case.

## Test / coverage commands (TODO — human confirmation)

- Run tests: `python3 -m pytest -v` (per README). No pytest is installed in any
  interpreter on this machine; this run used `uvx --with pytest pytest` (pytest 9.1.1,
  Python 3.13) as an ephemeral runner. Confirm the canonical CI runner.
- Coverage: no coverage tool configured. No changed-files coverage command
  (e.g. `diff-cover`) present. Not installed by this agent.
- Mutation testing: no tool present — suite quality unmeasured.

## Needs human decision

- Canonical test runner + whether pytest should be a committed dev dependency.
- Rounding contract for money (half-up vs banker's; Decimal vs float).
- Intended type contract for `qty` (int only? reject non-int? reject str with ValueError
  vs TypeError?).
- Whether `fixtures/bulk_orders.json` should be committed or the fixture test removed.
- Team mode (.qa/ in repo) vs solo mode (current).
