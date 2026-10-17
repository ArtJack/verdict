#!/usr/bin/env python3
"""The profile's machine-readable half. Stdlib only.

`profile.md` has always recorded a project's real commands — and the agent has
always had to *retype* them into `verdict-facts --gate suite='…'` on every run.
That is a transcription step, which is the exact class of error the rest of
this architecture exists to delete: the model sits between the configuration
and the measurement, and a model between two things is a place to be
confidently wrong. The sales profile grew a "Real commands" section precisely
because the retyping kept going wrong.

So the commands become data. A front-matter block at the top of `profile.md`:

    ---
    gates:
      suite: .venv/bin/python -m pytest -q
      lint: ruff check .
    test_ids_cmd: .venv/bin/python -m pytest --collect-only -q
    coverage_cmd: diff-cover coverage.xml
    ---

    # QA Profile — myproject
    ...prose exactly as before...

This is a deliberately small subset of YAML, not YAML: `key: value` at the left
margin, and one level of two-space-indented `name: value` under a bare `key:`.
Values run to end of line and are taken literally, because commands are full of
colons, quotes and pipes and a cleverer parser would mangle them. A line it
cannot read is an **error naming that line** — never a skip, because silently
dropping a gate would reintroduce the failure this file exists to remove.

Trust: these strings are executed. They live inside the QA root, which the
write-scope hook already guards, so a profile an attacker can edit is a QA root
they already own — the same trust level the `--gate` flags always had.
"""

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

import os

import re
import sys
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_SCALAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
_NESTED = re.compile(r"^[ \t]{2,}([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
# What `verdict-facts` actually reads. Anything else is carried through and
# reported as unread rather than dropped in silence.
KNOWN = ("gates", "test_ids_cmd", "test_one_cmd", "coverage_suite_cmd", "coverage_cmd",
         "authorship", "hygiene", "probes", "risk_class")
# The production an owner runs this gate for, when it is one where a proven defect must
# not ship: money moves through the code, or access is decided by it.
RISK_CLASSES = ("money", "security")


class ProfileError(ValueError):
    """A profile block that cannot be read. Always names the offending line."""


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(text: str) -> dict:
    """Parse the front-matter block of a profile. No block → `{}`."""
    match = FRONT_MATTER.match(text)
    if not match:
        return {}
    config: dict = {}
    current: str | None = None
    for number, raw in enumerate(match.group(1).splitlines(), start=2):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        nested = _NESTED.match(line)
        if nested:
            if current is None:
                raise ProfileError(
                    f"profile line {number}: {line.strip()!r} is indented under nothing — "
                    "a nested entry needs a `key:` above it at the left margin")
            config[current][nested.group(1)] = _unquote(nested.group(2))
            continue
        scalar = _SCALAR.match(line)
        if not scalar:
            raise ProfileError(
                f"profile line {number}: cannot read {line.strip()!r} — this block takes "
                "`key: value` at the left margin and two-space-indented `name: value` "
                "under a bare `key:`")
        key, value = scalar.group(1), _unquote(scalar.group(2))
        if value:
            config[key] = value
            current = None
        else:
            config[key] = {}
            current = key
    return config


def load(qa_root) -> tuple[dict, list[str]]:
    """Read `<qa-root>/profile.md` → (config, notes).

    `notes` says what was read and what was ignored, so a run that silently
    measured nothing is impossible to mistake for a run that had nothing to
    measure. A missing profile is not an error — plenty of runs predate one.
    """
    path = Path(qa_root) / "profile.md"
    if not path.is_file():
        return {}, [f"no profile at {path}; gates must come from --gate"]
    config = parse(path.read_text(encoding="utf-8"))
    if not config:
        return {}, [f"{path} has no front-matter block; gates must come from --gate"]
    gates = config.get("gates")
    if gates is not None and not isinstance(gates, dict):
        raise ProfileError(
            "profile `gates:` must be a block of `name: command` lines, not a single "
            f"value ({gates!r}) — a gate has a name so the state can say which one failed")
    notes = []
    unread = [k for k in config if k not in KNOWN]
    if unread:
        notes.append("profile keys not read by verdict-facts: " + ", ".join(sorted(unread)))
    return config, notes


def gates_from(config: dict) -> list[tuple[str, str]]:
    return [(name, command) for name, command in (config.get("gates") or {}).items()
            if command]


_HYGIENE_OFF = ("off", "false", "no")


def hygiene_filing_from(config: dict, notes: list) -> str:
    """The profile's `hygiene:` setting, as the scan takes it: "off" for off, false or
    no in any case — every tier still counted, nothing filed — and "on" otherwise.

    Both engines read it here, so the setting means the same thing on each. A value
    it cannot read leaves filing on and adds a note: a typo must never be what turns
    a control off, and must not pass for a setting that took."""
    value = config.get("hygiene")
    if isinstance(value, str):
        value = value.strip()
    if not value:
        return "on"
    if isinstance(value, str) and value.lower() in _HYGIENE_OFF:
        return "off"
    notes.append(f"hygiene: '{value}' is not understood — filing stays on")
    return "on"


def risk_class_from(config: dict, notes: list) -> str | None:
    """The profile's `risk_class:` — "money" or "security", or None for neither.

    It is the one switch that makes a defect the tester proved block the gate, whatever
    severity it was filed at (`harness.gate_policy`). A value it cannot read applies no
    class and says so: a misspelt `monye` must not pass for a class that took, and must
    not pass in silence for none."""
    value = config.get("risk_class")
    if isinstance(value, str):
        value = value.strip().lower()
    if not value:
        return None
    if value in RISK_CLASSES:
        return value
    notes.append(f"risk_class: '{value}' is not understood (money, security) — no class applied")
    return None


def main(argv=None) -> int:
    """`python3 profile.py <qa-root>` — show what a profile would contribute."""
    import json
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: profile.py <qa-root>", file=sys.stderr)
        return 2
    try:
        config, notes = load(args[0])
    except ProfileError as exc:
        print(f"verdict-profile: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"config": config, "gates": gates_from(config), "notes": notes},
                     indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())


def risk_paths_from(config: dict, notes: list) -> list[str]:
    """The profile's `risk_paths:` — globs naming the money and auth code, a comma-separated
    string or a list. Empty when unset: `read_first` then ranks by name stems."""
    value = config.get("risk_paths")
    if value is None or value == "":
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    globs = [str(i).strip() for i in items if str(i).strip()]
    if not globs:
        notes.append(f"risk_paths: '{value}' names no glob — ranking by name stems")
    return globs


def assertion_gaps_from(config: dict, notes: list) -> tuple[bool, int | None]:
    """The profile's `assertion_gaps:` (on/off) and `assertion_gaps_budget_s:`. Unset, the
    environment's `VERDICT_ASSERTION_GAPS` decides — `verdict-run` sets it on for an asked run —
    and otherwise it is off; the profile's word always wins."""
    raw = config.get("assertion_gaps")
    if raw is None or str(raw).strip() == "":
        raw = os.environ.get("VERDICT_ASSERTION_GAPS", "")
    value = str(raw or "").strip().lower()
    on = value in ("on", "true", "yes", "1")
    if value and not on and value not in ("off", "false", "no", "0"):
        notes.append(f"assertion_gaps: '{config.get('assertion_gaps')}' is not understood (on, off) — off")
    budget = config.get("assertion_gaps_budget_s")
    try:
        budget = int(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        notes.append(f"assertion_gaps_budget_s: '{budget}' is not a number of seconds — the default stands")
        budget = None
    return on, budget


def repro_rule_from(config: dict, notes: list) -> bool:
    """The profile's `repro_rule:` — off unless it says on (`on`, `true`, `yes`).

    On, `verdict-finalize` refuses a new Blocker/Critical/Major finding filed `proven`
    with no `repro` block: proven to its author is not proven. Off (the default, so a
    record that predates the block keeps working), such a finding is accepted and named
    once. Either way a `repro` that does not reproduce on a fresh worktree refuses `proven`.
    """
    value = config.get("repro_rule")
    if value is None or value == "":
        return False
    word = str(value).strip().lower()
    on, off = {"on", "true", "yes", "1"}, {"off", "false", "no", "0"}
    if word not in on | off:
        notes.append(f"repro_rule: '{value}' is not understood (on, off) — the rule stays off")
    return word in on


def contract_rule_from(config: dict, notes: list) -> bool:
    """The profile's `contract_rule:` — on unless it says off (`off`, `false`, `no`).

    Rule 3 of `harness.gate_policy`: a finding whose fix fails tests that pass at HEAD is a
    contract dispute, capped at Major and parked as a question, not a release blocker."""
    value = config.get("contract_rule")
    if value is None or value == "":
        return True
    text = str(value).strip().lower()
    if text in ("off", "false", "no", "0"):
        return False
    if text in ("on", "true", "yes", "1"):
        return True
    notes.append(f"contract_rule: '{value}' is not understood (on, off) — the rule stays on")
    return True

