# SyncBay — inventory sync (spec of record)

A tiny marketplace inventory sync engine. **This README is the requirement spec** the code
and tests must satisfy. It intentionally pairs with seeded defects — the answer key is
`eval/expected-slop.json`; do not read it during an eval run.

## Requirements

1. **One normalization everywhere:** SKUs are trimmed, uppercased, and internal whitespace
   collapses to `-`. Every component must normalize the same way.
2. **Batch size:** a sync request carries at most **100 items** (`MAX_BATCH`).
3. **Failures surface:** a failed push is retried once, then **surfaced to the caller** —
   a sync must never silently drop items.
4. **Negative quantities** are invalid and rejected with `ValueError`.
5. **Shipping rates come from the carrier API.**

## Running

```bash
python3 -m pytest -q
```
