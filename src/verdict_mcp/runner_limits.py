"""Where a run stopped and why: a budget spent, a flag the CLI refused, a usage limit and
when it resets, and the cap a run is allowed to spend.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from . import clock, escalate
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import escalate


_FLAG_REFUSED = re.compile(r"error: unknown option '--(?:agent|effort)'")


_BUDGET_STOP = re.compile(r"Exceeded USD budget|error_max_budget_usd")


def final_stop(output) -> str | None:
    """Why a finished attempt must not be tried again → the message, or None. A weekly limit is
    days away; a session stopped at its dollar cap would spend the cap again."""
    if limit_kind(output) == "weekly":
        return (f"verdict-run: {limit_line(output)} — no model run is possible until then; the "
                "standing verdict is left as it is")
    if budget_exhausted(output):
        return ("verdict-run: the session stopped at its dollar cap — not retried, since a second "
                "attempt would spend the cap again; whatever state it wrote stands")
    return None


def budget_exhausted(output) -> bool:
    """The CLI stopped the session at its `--max-budget-usd` ceiling. Such a run is not
    retried: a second attempt spends the same ceiling again for the same missing state."""
    return bool(_BUDGET_STOP.search(output or ""))


def flag_refused(output) -> bool:
    """An older claude CLI refuses an option it does not know before it calls any model
    (`error: unknown option '--agent'`, exit 1): nothing was spent, and it is no attempt."""
    return bool(_FLAG_REFUSED.search(output or ""))


def limit_kind(output: str) -> str | None:
    """Which allowance the CLI says is spent: `session` (a window that reopens
    within hours) or `weekly` (days away), or None.

    The difference decides whether waiting is sensible. A session limit is worth
    sleeping through; a weekly one is not — the first version knew only the word
    "session", so a weekly limit read as an ordinary failure, and the runner
    spent its retry, reported a lost run, and left the operator to find the real
    reason in the log.
    """
    low = output.lower()
    if "weekly limit" in low:
        return "weekly"
    if "session limit" in low or "usage limit" in low:
        return "session"
    return None


def limit_line(output: str) -> str:
    """The CLI's own sentence about the limit, for a message that explains itself."""
    for line in output.splitlines():
        if "limit" in line.lower() and "reset" in line.lower():
            return line.strip()[:200]
    return "the CLI reported a usage limit"


def seconds_until_reset(output: str, ceiling_s: int = 10800) -> int | None:
    """Parse 'resets 2:40am' / 'resets 23:15' from a session-limit error.

    None when the output is not a limit this runner should wait out — no limit
    at all, or a weekly one, which reopens in days and must be reported rather
    than slept through. A bounded wait when the window exists but its edge
    cannot be read.
    """
    if limit_kind(output) != "session":
        return None
    m = re.search(r"resets\s+([0-9]{1,2}:[0-9]{2}(?:am|pm)?)", output, re.I)
    if not m:
        return min(3600, ceiling_s)
    raw = m.group(1).lower()
    now = clock.local_now()     # the CLI prints its reset time in the user's wall-clock
    try:
        fmt = "%I:%M%p" if raw.endswith(("am", "pm")) else "%H:%M"
        t = datetime.strptime(raw, fmt).time()
        target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = int((target - now).total_seconds()) + 180
    except ValueError:
        wait = 3600
    return max(60, min(wait, ceiling_s))


def resolve_cap(args, passthrough) -> tuple:
    """The run's dollar ceiling → (cap or None, the flags to add, an error or None).

    An operator's `--max-budget-usd` after `--` stays where it is and names the cap. An
    escalation run with none gets the default: it is the cheap run by construction, and the
    ceiling is what makes "cheap" a guarantee rather than a hope."""
    cap = None
    if args.max_budget_usd not in (None, ""):
        try:
            cap = float(args.max_budget_usd)
        except ValueError:
            return None, [], f"--max-budget-usd {args.max_budget_usd!r} is not a number"
    given = [i for i, p in enumerate(passthrough) if p == "--max-budget-usd"]
    if cap is None and given and given[-1] + 1 < len(passthrough):
        try:
            cap = float(passthrough[given[-1] + 1])
        except ValueError:
            pass
    elif cap is None and (args.escalate or args.lite):
        cap = escalate.BUDGET_DEFAULT_USD
    flags = ["--max-budget-usd", f"{cap:g}"] if cap is not None and not given else []
    return cap, flags, None
