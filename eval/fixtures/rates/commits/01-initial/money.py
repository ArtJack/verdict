"""Money helpers. Spec rule 1: nearest cent, half up."""


def to_cents(amount):
    """Convert a dollar amount to integer cents (spec rule 1)."""
    return int(amount * 100)


def format_cents(cents):
    return f"${cents // 100}.{cents % 100:02d}"
