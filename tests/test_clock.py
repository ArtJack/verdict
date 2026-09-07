"""One module knows the time (T-7).

The package had thirteen direct wall-clock calls, two of them naive local time
and one `date.today()` deciding quarantine expiry against UTC dates. The seam is
`verdict_mcp.clock`; this file is the discipline that keeps it the only one, and
the proof that the clock can be frozen — which is what lets a fact age in a test.
"""

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from verdict_mcp import clock

SRC = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"
WALL_CLOCK = {("datetime", "now"), ("datetime", "utcnow"), ("date", "today"), ("time", "time")}


def _wall_clock_calls(path: Path):
    """Every `datetime.now()`, `datetime.utcnow()`, `date.today()` or `time.time()`
    call in the file, as (line, text). AST, not grep: a docstring that says
    "not `date.today()`" is prose, not a call."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
            if (fn.value.id, fn.attr) in WALL_CLOCK:
                hits.append((node.lineno, f"{fn.value.id}.{fn.attr}()"))
    return hits


def test_no_module_but_the_clock_asks_the_time():
    offenders = {}
    for path in sorted(SRC.glob("*.py")):
        if path.name == "clock.py":
            continue
        hits = _wall_clock_calls(path)
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"wall-clock calls outside clock.py: {offenders}"


def test_the_clock_module_is_where_the_calls_live():
    """The control for the sweep above: the instrument must see the calls it is
    meant to see, or an empty result means nothing."""
    assert _wall_clock_calls(SRC / "clock.py"), "clock.py has no wall-clock call — the sweep is blind"


def test_now_is_timezone_aware_utc():
    t = clock.now()
    assert t.tzinfo is not None and t.utcoffset().total_seconds() == 0
    assert abs((datetime.now(timezone.utc) - t).total_seconds()) < 5


def test_the_clock_can_be_frozen(monkeypatch):
    """`VERDICT_CLOCK_AT` freezes now(), today() and stamp() together — one
    definition of "now" for every module, which is the whole point of a seam."""
    monkeypatch.setenv(clock.FROZEN_ENV, "2026-09-06T12:34:56Z")
    assert clock.now() == datetime(2026, 9, 6, 12, 34, 56, tzinfo=timezone.utc)
    assert clock.today() == date(2026, 9, 6)
    assert clock.stamp() == "2026-09-06T12:34:56Z"
    monkeypatch.setenv(clock.FROZEN_ENV, "2026-03-01")            # a bare date is UTC midnight
    assert clock.now() == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert clock.today() == date(2026, 3, 1)


def test_a_frozen_offset_stamp_is_normalised_to_utc(monkeypatch):
    monkeypatch.setenv(clock.FROZEN_ENV, "2026-09-06T05:00:00-07:00")
    assert clock.stamp() == "2026-09-06T12:00:00Z"
    assert clock.today() == date(2026, 9, 6)


def test_an_unparseable_freeze_refuses_loudly(monkeypatch):
    monkeypatch.setenv(clock.FROZEN_ENV, "yesterday")
    with pytest.raises(SystemExit, match="VERDICT_CLOCK_AT"):
        clock.now()


def test_stamp_formats_any_instant_as_the_state_does():
    assert clock.stamp(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)) == "2026-01-02T03:04:05Z"
    eastern = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-5)))
    assert clock.stamp(eastern) == "2026-01-02T03:04:05Z", "an offset instant is the same instant"


def test_local_now_is_naive_local_and_only_for_the_runner():
    t = clock.local_now()
    assert t.tzinfo is None
    assert abs((datetime.now() - t).total_seconds()) < 5
