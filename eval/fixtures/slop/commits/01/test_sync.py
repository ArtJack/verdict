import pytest

import sync


def test_normalize_sku():
    assert sync.normalize_sku(" red  hat ") == "RED-HAT"


def test_negative_qty_rejected():
    with pytest.raises(ValueError):
        sync.push_batch([{"sku": "a", "qty": -1}], transport=None)
