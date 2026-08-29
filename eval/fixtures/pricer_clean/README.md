# Pricer — mutation base (spec of record)

A tiny marketplace listing pricer. **This README is the requirement spec** the code and
tests must satisfy.

## Requirements

1. **Floor rule:** a price **at or above** the listing floor is listable; below the floor is
   not.
2. **Fee:** the marketplace fee is **12%** of the listing price.
3. **Rounding:** cent rounding is **half up** — `0.125` rounds to `0.13`.
4. **Bulk discount:** orders of **10 or more** units get 10% off the unit price.
5. Negative prices are rejected with a `ValueError`.
6. **Shipping:** $4.95 for parcels **up to and including 2 kg**, $9.95 above that.
   Express doubles the shipping charge.
7. **Free shipping** on orders whose merchandise total is **$75 or more**.

## Running

```bash
python3 -m pytest -v
```
