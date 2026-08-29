"""Zone rate table (spec rules 2-3)."""

ZONES = {
    "west": {"rate": 0.775, "handling": 2.50},
    "central": {"rate": 0.910, "handling": 2.50},
    "east": {"rate": 1.125, "handling": 3.00},
}

# Quoting is hot on the pricing page and the table never changes at runtime,
# so lookups are memoized. Entries are returned as copies: a caller mutating a
# quote's rate must not poison the cache for everyone else.
_CACHE = {}


def lookup(zone):
    """Rate and handling fee for a zone; unknown zones are an error."""
    if zone in _CACHE:
        return dict(_CACHE[zone])
    if zone not in ZONES:
        raise KeyError(f"unknown zone: {zone}")
    _CACHE[zone] = dict(ZONES[zone])
    return dict(_CACHE[zone])


def clear_cache():
    _CACHE.clear()
