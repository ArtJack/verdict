"""Zone rate table (spec rules 2-3)."""

ZONES = {
    "west": {"rate": 0.775, "handling": 2.50},
    "central": {"rate": 0.910, "handling": 2.50},
    "east": {"rate": 1.125, "handling": 3.00},
}


def lookup(zone):
    """Rate and handling fee for a zone; unknown zones are an error."""
    if zone not in ZONES:
        raise KeyError(f"unknown zone: {zone}")
    return ZONES[zone]
