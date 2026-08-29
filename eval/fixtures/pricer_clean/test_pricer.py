"""Suite for the pricer.

Deliberately realistic rather than exhaustive: it covers the happy paths and
the two boundaries anyone would think of, and leaves gaps a careful reader
would notice. Those gaps are the point — a mutant the suite fails to kill is
exactly the defect a tester has to find by reading the code.
"""

import pytest

from pricer import (bulk_unit_price, is_listable, net_proceeds, round_cents,
                    shipping_cost)


def test_listable_above_floor():
    assert is_listable(10.00, 5.00)


def test_listable_at_floor_exactly():
    # spec rule 1: at the floor is listable
    assert is_listable(5.00, 5.00)


def test_not_listable_below_floor():
    assert not is_listable(4.99, 5.00)


def test_round_cents_half_up():
    # spec rule 3
    assert round_cents(0.125) == 0.13


def test_net_proceeds_twelve_percent():
    # spec rule 2
    assert net_proceeds(100.0) == 88.0


def test_bulk_discount_at_ten_units():
    # spec rule 4: ten or more
    assert bulk_unit_price(20.00, 10) == 18.00


def test_no_bulk_discount_for_a_single_unit():
    assert bulk_unit_price(20.00, 1) == 20.00


def test_negative_price_is_rejected():
    with pytest.raises(ValueError):
        net_proceeds(-1)


def test_light_parcel_pays_standard_shipping():
    assert shipping_cost(1.0, 20.00) == 4.95


def test_heavy_parcel_pays_more():
    assert shipping_cost(5.0, 20.00) == 9.95


def test_express_doubles_the_charge():
    assert shipping_cost(1.0, 20.00, express=True) == 9.90


def test_large_orders_ship_free():
    assert shipping_cost(5.0, 100.00) == 0.0
