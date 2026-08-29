"""Behavioural fingerprint of this module, over a fixed input grid.

`eval/mutate.py` runs this against the clean module and against each mutant. A
mutant whose fingerprint is identical everywhere did not change behaviour — it
is an *equivalent mutant*, not a defect, and counting it against a tester would
be counting a question with no answer. This is what keeps the recall
denominator honest.

Printed as sorted JSON so the comparison is exact and order-independent.
"""

import json

import pricer

# Negatives belong here: the first grid had none, so removing a
# negative-price guard entirely looked like a no-op to the oracle.
PRICES = [-100, -1, -0.01, 0, 0.005, 0.01, 0.125, 1, 4.99, 5, 5.01, 9.99,
          10, 20, 99.995, 100, 1000]
FLOORS = [0, 5, 10, 100]
QTYS = [-1, 0, 1, 8, 9, 10, 11, 100]
WEIGHTS = [-1, 0, 0.5, 1.9, 2, 2.1, 5, 30]
TOTALS = [-5, 0, 10, 74.99, 75, 75.01, 200]


def call(fn, *args):
    try:
        return repr(fn(*args))
    except Exception as exc:                      # a raised error is behaviour too
        return f"{type(exc).__name__}: {exc}"


print(json.dumps({
    "is_listable": {f"{p}|{f}": call(pricer.is_listable, p, f)
                    for p in PRICES for f in FLOORS},
    "round_cents": {str(p): call(pricer.round_cents, p) for p in PRICES},
    "net_proceeds": {str(p): call(pricer.net_proceeds, p) for p in PRICES},
    "bulk_unit_price": {f"{p}|{q}": call(pricer.bulk_unit_price, p, q)
                        for p in PRICES for q in QTYS},
    "shipping_cost": {f"{w}|{t}|{e}": call(pricer.shipping_cost, w, t, e)
                      for w in WEIGHTS for t in TOTALS for e in (False, True)},
}, sort_keys=True))
