"""What both harness commands share: running a command and git, reading and writing the
QA root's JSON files, which QA root a run writes, and who is running it.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from .project_key import derive_key
    from .state import home as state_home
    from .usage import ENTRYPOINT_ENV, SESSION_ENV
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_key import derive_key
    from state import home as state_home
    from usage import ENTRYPOINT_ENV, SESSION_ENV


def _run(cmd, cwd=None, shell=False):
    return subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True)


def _git(args, repo):
    proc = _run(["git", "-C", str(repo), *args])
    return proc.stdout.strip() if proc.returncode == 0 else None


def _chosen(rec) -> bool:
    """Was the test somebody's choice, or a mention?

    `explicit` is the tester's own citation and `added_this_run` is the
    collector seeing the test for the first time — what a fix's regression
    test looks like. A `first_cited` pick is a pytest id that happened to be
    quoted in the finding's prose, which can be another finding's test
    entirely: run 12 verified F-26 against an id quoted from F-50's evidence.
    `verify_findings` no longer runs such a pick at all (VERDICT-F-26), so its
    own records never carry one; this guard remains for a record that arrives
    another way — a facts.json edited by hand is still read as facts — and a
    confirmed row is a permanent grade (VERDICT-F-72).
    """
    return isinstance(rec, dict) and rec.get("selected_by") in ("explicit", "added_this_run")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and `os.replace`, which is atomic on POSIX and
    Windows alike. Nothing here is large enough for the extra copy to matter,
    and a torn state.json costs a run at best. A write that fails takes its temp
    file with it, so nothing half-written is left in the QA root."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_root(repo: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    team = repo / ".qa"
    if team.is_dir():
        return team
    home = state_home()  # one spelling of the default, in state.py
    return home / derive_key(repo)[0]


# The tier-2 rows of this run's hygiene scan, beside facts.json rather than in it.
HYGIENE_ITEMS_FILE = "hygiene-items.json"


# The junk ledger's rows, beside state.json rather than in it (write_state).
HYGIENE_LEDGER_FILE = "hygiene-ledger.json"


def _session_identity() -> dict:
    """`{session_id, entrypoint}` as far as the environment says, never a guess."""
    out = {}
    for key, name in (("session_id", SESSION_ENV), ("entrypoint", ENTRYPOINT_ENV)):
        value = os.environ.get(name)
        if value:
            out[key] = value
    return out
