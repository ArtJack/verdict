"""The only module in the package that asks what time it is.

Thirteen call sites asked the wall clock directly — two of them the local, naive
clock, one of them `date.today()` in the MCP server deciding whether a quarantine
had expired against UTC dates in the state. A quarantine that expires a day
early or late depending on the reader's timezone is the kind of fault nobody
reports. And a fact that ages cannot be tested against a clock nobody can move:
the code-enumerated sweep left every one of `duration_regressed`'s and `_ago`'s
boundaries standing because no test could stand on the boundary.

So: one seam. `now()` is timezone-aware UTC, `today()` is its date, `stamp()` is
the state's timestamp format. `VERDICT_CLOCK_AT` (an ISO date or instant)
freezes all three — the eval fixtures can now watch a quarantine expire in one
session, and a test can stand on a boundary. `local_now()` exists for exactly one
reader, the runner parsing "resets 3:00pm" out of the CLI's own wall-clock
message, and says so.

`tests/test_clock.py` walks the package's AST for any other `datetime.now()`,
`date.today()`, `utcnow()` or `time.time()`: discipline you can run beats
discipline you intend. Monotonic timers for durations are not the wall clock and
are not swept.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone

FORMAT = "%Y-%m-%dT%H:%M:%SZ"
FROZEN_ENV = "VERDICT_CLOCK_AT"


def _frozen() -> datetime | None:
    raw = os.environ.get(FROZEN_ENV, "").strip()
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SystemExit(f"{FROZEN_ENV}={raw!r} is not an ISO date or instant "
                         "(2026-09-06 or 2026-09-06T12:00:00Z)") from exc
    if parsed.tzinfo is None:
        # A bare date or a naive instant is UTC here, not local: two people in
        # two countries freezing the same date must get the same instant.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now() -> datetime:
    """The current instant, timezone-aware UTC — or the frozen one."""
    return _frozen() or datetime.now(timezone.utc)


def today() -> date:
    """The current UTC date. State dates are UTC dates; comparing one against a
    local `date.today()` is off by a day for a third of the planet."""
    return now().date()


def stamp(when: datetime | None = None) -> str:
    """An instant as the state writes it: `2026-09-06T12:00:00Z`."""
    when = when or now()
    return when.astimezone(timezone.utc).strftime(FORMAT)


def local_now() -> datetime:
    """The naive LOCAL clock. One reader: `verdict-run` parsing the CLI's
    'resets 3:00pm' message, which is written in the user's own wall-clock time.
    Nothing that touches state may use this."""
    frozen = _frozen()
    return frozen.astimezone().replace(tzinfo=None) if frozen else datetime.now()
