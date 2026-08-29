"""Monthly revenue reporting."""

from money import format_cents


def monthly_total(daily_dollars):
    """Month total in cents from a list of daily dollar figures (spec rule 1)."""
    total = sum(daily_dollars)
    return int(total * 100)


def render(daily_dollars):
    return f"Month to date: {format_cents(monthly_total(daily_dollars))}"
