"""Message-queue statistics. Spec of record: README.md in this directory."""


def pending(queued, in_flight):
    """Messages not yet completed (spec rule 1)."""
    return queued - in_flight
