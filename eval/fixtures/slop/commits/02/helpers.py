"""Shared SKU helpers."""


def clean_sku(sku):
    """Uppercase a SKU and normalize its separators (spec rule 1)."""
    return sku.upper().replace(" ", "-")
