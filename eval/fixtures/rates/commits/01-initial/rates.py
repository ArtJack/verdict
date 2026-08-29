"""Freight quoting (spec rule 2)."""

import zones
from money import to_cents


def quote(weight_kg, zone):
    """Quote in integer cents: weight x rate, plus the zone handling fee."""
    entry = zones.lookup(zone)
    freight = weight_kg * entry["rate"]
    return to_cents(freight) + to_cents(entry["handling"])
