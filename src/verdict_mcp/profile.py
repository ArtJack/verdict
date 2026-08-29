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

import re
import sys
from pathlib import Path

FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_SCALAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
_NESTED = re.compile(r"^[ \t]{2,}([A-Za-z_][A-Za-z0-9_-]*):[ \t]*(.*)$")
# What `verdict-facts` actually reads. Anything else is carried through and
# reported as unread rather than dropped in silence.
KNOWN = ("gates", "test_ids_cmd", "coverage_cmd", "authorship")


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
