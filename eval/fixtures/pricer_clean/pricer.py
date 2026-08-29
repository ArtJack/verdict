"""Listing pricer for a marketplace storefront.

The requirement spec of record is README.md in this directory.

Unlike the `pricer` fixture, this module is *correct*: every rule in the spec
is implemented as written. It exists to be broken one line at a time by
`eval/mutate.py`, so that recall can be measured against defects nobody
authored by hand.
"""

from decimal import ROUND_HALF_UP, Decimal

FEE_RATE = 0.12
STANDARD_SHIPPING = 4.95
HEAVY_SHIPPING = 9.95
HEAVY_ABOVE_KG = 2
FREE_SHIPPING_FROM = 75


def is_listable(price, floor):
    """A price at or above the floor is listable (spec rule 1)."""
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price}")
    return price >= floor


def round_cents(amount):
    """Round to the nearest cent, half up (spec rule 3)."""
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def net_proceeds(price):
    """Seller proceeds after the marketplace fee (spec rule 2)."""
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price}")
    return round_cents(price * (1 - FEE_RATE))


def bulk_unit_price(price, qty):
    """Discounted unit price for bulk orders (spec rule 4)."""
    if qty >= 10:
        return round_cents(price * 0.9)
    return price


def shipping_cost(weight_kg, merchandise_total, express=False):
    """Shipping charge for a parcel (spec rules 6 and 7)."""
    if merchandise_total >= FREE_SHIPPING_FROM:
        return 0.0
    base = STANDARD_SHIPPING if weight_kg <= HEAVY_ABOVE_KG else HEAVY_SHIPPING
    if express:
        base = base * 2
    return round_cents(base)
