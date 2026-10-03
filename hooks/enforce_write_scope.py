#!/usr/bin/env python3
"""Verdict write-scope guard (PreToolUse hook).

Verdict is a QA agent that must be read-only on your code. Its contract allows
writes ONLY inside a QA root:

  - <anywhere>/.qa/...          (team mode, committed with the repo)
  - $VERDICT_HOME/...           (solo mode; defaults to ~/.claude/verdict)

Enforcement modes:

  1. VERDICT_STRICT=1 in the environment: every Write/Edit outside a QA root is
     blocked, no matter which agent issued it. Use this for headless / CI /
     scheduled QA sessions, where the whole session IS the QA run. This is the
     hard guarantee.
  2. Otherwise: the guard blocks only when the hook input positively identifies
     the calling agent as verdict (`qa_paths.caller_is_verdict`, the one rule
     all three hooks share). Claude Code sends `agent_type` with every hook
     input fired inside a subagent; an event that names no agent is the user's
     own session, and is left alone.
  3. In every mode, whoever the caller is: the maintainer's ledgers
     (`accepted.json`, `answers.json`) inside a QA root are refused. They are
     written by `verdict-accept` and `verdict-answer` from outside any session,
     and no Write or Edit to them is ever the tester's to make.

The guard fails OPEN on malformed input: a broken hook must never brick the
user's session. It never blocks reads — Verdict is meant to read everything.
"""

import json
import os
import sys

from qa_paths import caller_is_verdict, maintainer_pen, utf8_stderr
from qa_paths import is_allowed_path as _is_allowed
from qa_paths import is_maintainer_file as _is_maintainer


def _target(data: dict) -> str:
    """The file this event writes, as an absolute path where the event allows.

    A relative `file_path` used to be resolved by `os.path.realpath`, which
    means against the HOOK PROCESS's directory rather than the event's `cwd`
    (K-D-14). Claude Code passes absolute paths today, so nothing was measured
    going wrong — but the two directories are not the same thing, and a hook
    started from inside a `.qa/` would have read `src/app.py` as QA state. The
    Bash guard has always resolved against the event; now both do.
    """
    tool_input = data.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not isinstance(target, str):
        return ""
    cwd = data.get("cwd")
    if target and isinstance(cwd, str) and cwd and not os.path.isabs(os.path.expanduser(target)):
        target = os.path.join(cwd, target)
    return target


def main() -> int:
    utf8_stderr()
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail open: never break the session on malformed input
    if not isinstance(data, dict):
        return 0  # JSON, but not an event: the same rule

    target = _target(data)
    if _is_maintainer(target):
        # Inside the QA root, and still not the tester's: the accepted-risk
        # ledger is the maintainer's decision about the tester's findings.
        # Refused whoever asks and in whatever mode. It used to be refused only
        # under VERDICT_STRICT or to a caller the event named, so in an
        # interactive session a tester whose event carried no agent — measured —
        # could write the ledger that accepts its own findings (K-D-12). There
        # is no caller this is the right tool for: the maintainer's pen is a
        # command, run from outside any session.
        sys.stderr.write(
            f"verdict write-scope guard: {target!r} is the maintainer's ledger — written by "
            f"`{maintainer_pen(target)}`, never by the tester. A tester that could accept its "
            "own findings' risks, or answer its own questions, would be grading its own "
            "paper.\n"
        )
        return 2
    if _is_allowed(target):
        return 0

    strict = os.environ.get("VERDICT_STRICT", "") not in ("", "0", "false")
    if strict or caller_is_verdict(data):
        sys.stderr.write(
            "verdict write-scope guard: writing to "
            f"{target!r} is outside the QA root. Verdict may only write inside "
            "a .qa/ directory or ~/.claude/verdict/. Findings are reported, "
            "never patched in place. (Set VERDICT_STRICT=0 only outside "
            "dedicated QA sessions.)\n"
        )
        return 2  # block the tool call and show Claude the reason

    return 0


if __name__ == "__main__":
    sys.exit(main())
