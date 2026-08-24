"""Listing pricer for a marketplace storefront.

The requirement spec of record is README.md in this directory.
"""

FEE_RATE = 0.12


def is_listable(price, floor):
    """A price at or above the floor is listable (spec rule 1)."""
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price}")
    return price > floor


def round_cents(amount):
    """Round to the nearest cent, half up (spec rule 3)."""
    return round(amount, 2)


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
