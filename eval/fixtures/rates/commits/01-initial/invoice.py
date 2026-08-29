"""Invoice rendering."""

from money import format_cents


def line_total(unit_price, quantity):
    """Total for one invoice line, in cents (spec rule 1)."""
    return int(unit_price * quantity * 100)


def render(lines):
    out = []
    for name, unit_price, quantity in lines:
        out.append(f"{name}: {format_cents(line_total(unit_price, quantity))}")
    return "\n".join(out)
