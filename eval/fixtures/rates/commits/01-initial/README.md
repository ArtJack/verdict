# rates — freight quoting (spec of record)

**This README is the requirement spec.** It intentionally contains a seeded defect — see
`../../expected-cause.json` for the answer key (do not read it during an eval run).

## Requirements

1. **Money is rounded to the nearest cent, half up.** `$5.425` is `543` cents, never `542`.
   Everything customer-facing — quotes, invoices, reports — uses the same rule.
2. **Quote:** `weight_kg × zone rate`, plus the zone's fixed handling fee.
3. Zone rates come from the zone table; an unknown zone is an error.
4. All monetary values move through the codebase as integer cents.

## Running

```bash
python3 -m pytest -q
```
