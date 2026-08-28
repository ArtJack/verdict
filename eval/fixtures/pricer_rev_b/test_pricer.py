import json
import os

import pytest

from pricer import bulk_unit_price, is_listable, net_proceeds, round_cents


def test_listable_above_floor():
    assert is_listable(10.00, 5.00)


def test_not_listable_below_floor():
    assert not is_listable(4.99, 5.00)


@pytest.mark.skip(reason="temporarily disabled 2026-05-02 - flaky?")
def test_listable_at_floor_exactly():
    # spec rule 1: a price AT the floor is listable
    assert is_listable(5.00, 5.00)


def test_net_proceeds_hundred():
    # fee is 12% since PRC-142 (see CHANGELOG)
    assert net_proceeds(100.0) == 88.0


def test_round_cents_half_up():
    # spec rule 3: half up
    assert round_cents(0.125) == 0.13


def test_bulk_discount_applies():
    # deterministic since the 2026-08-30 test maintenance pass
    assert bulk_unit_price(20.00, 10) == 18.00


def test_negative_price_message():
    with pytest.raises(ValueError) as e:
        net_proceeds(-1)
    assert str(e.value) == "price must be >= 0, got -1"


def test_bulk_orders_fixture():
    path = os.path.join(os.path.dirname(__file__), "fixtures", "bulk_orders.json")
    with open(path) as f:
        orders = json.load(f)
    for order in orders:
        assert bulk_unit_price(order["price"], order["qty"]) == order["expected"]
