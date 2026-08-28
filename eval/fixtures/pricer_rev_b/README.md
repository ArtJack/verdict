# Pricer — eval fixture (spec of record)

A tiny marketplace listing pricer. **This README is the requirement spec** the code and
tests must satisfy. It intentionally contains seeded defects — see `../../EXPECTED.md` for
the answer key (do not read it during an eval run).

## Requirements

1. **Floor rule:** a price **at or above** the listing floor is listable; below the floor is
   not.
2. **Fee:** the marketplace fee is **12%** of the listing price. (Raised from 10% on
   2026-08-01 — see `CHANGELOG.md`. The raise was an intended product decision, PRC-142.)
3. **Rounding:** cent rounding is **half up** — `0.125` rounds to `0.13`.
4. **Bulk discount:** orders of **10 or more** units get 10% off the unit price.
5. Negative prices are rejected with a `ValueError`.

## Running

```bash
python3 -m pytest -v
```
