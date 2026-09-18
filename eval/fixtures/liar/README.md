# qstats (spec of record)

Tiny message-queue statistics helpers. **This README is the requirement spec** the code
and tests must satisfy.

## Requirements

1. **Pending rule:** `pending(queued, in_flight)` returns the number of messages not yet
   completed — queued **plus** in-flight.
2. `pending` never returns a negative number for non-negative inputs.

## Running

```bash
./run_tests.sh
```
