from unittest.mock import MagicMock

import sync


def test_normalize_sku_collapses_whitespace():
    assert sync.normalize_sku(" red  hat ") == "RED-HAT"


def test_build_batches_keeps_every_item():
    items = [{"sku": f"s{i}", "qty": 1} for i in range(120)]
    assert sum(len(b) for b in sync.build_batches(items)) == len(items)


def test_push_batch_sends_the_payload():
    transport = MagicMock()
    assert sync.push_batch([{"sku": "a", "qty": 1}], transport) is True
    assert transport.send.called


def test_sync_reports_everything_sent():
    transport = MagicMock()
    out = sync.sync([{"sku": "a", "qty": 1}, {"sku": "b", "qty": 2}], transport)
    assert out["sent"] == 2
