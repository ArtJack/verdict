"""Carrier shipping rates."""


def get_rate(sku, dest):
    # TODO: call the carrier rate API (spec rule 5); a placeholder table for now
    table = {"US": 5.0, "CA": 7.5}
    return table.get(dest, 5.0)
