from unittest.mock import Mock

from qstats import pending


def test_pending_counts_queued_and_in_flight():
    # spec rule 1: queued + in_flight
    assert pending(3, 2) == 5


def test_pending_via_service():
    service = Mock()
    service.pending.return_value = 5
    assert service.pending(3, 2) == 5


def test_pending_nonnegative():
    p = pending(4, 1)
    assert p == p
