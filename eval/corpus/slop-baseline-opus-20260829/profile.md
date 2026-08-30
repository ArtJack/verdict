---
gates:
  suite: python3 -m pytest -q
test_ids_cmd: python3 -m pytest --collect-only -q
---
# QA profile — slop (SyncBay)

Project-Key: slop
Repo-Path: /private/var/folders/95/670m4j2n4738g9pq1tq1mq8c0000gn/T/verdict-eval-ky3sld2h/slop
Repo-Remote: (none)
Security-Pass: disabled

## Isolation
Pure-function library with an injected `transport` object. No network, DB, credentials, or
filesystem writes in the code under test. Tests use `unittest.mock.MagicMock` transports.

## Risk areas
- sync.py: silent failure handling, batch sizing (inventory correctness)
- rates.py: shipping price computation (money)
- helpers.py vs sync.py: divergent SKU normalization

## Needs human decision (TODO)
- Real test command: README says `python3 -m pytest -q`, but pytest is NOT installed here and
  there is no venv. Owner must supply the real runner/venv.
- No changed-files coverage command (diff-cover) available -> coverage gate unmeasurable.
- No mutation-testing tool available -> suite quality unmeasured.
