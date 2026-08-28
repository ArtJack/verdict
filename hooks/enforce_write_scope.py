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
     the calling agent as verdict. Claude Code does not currently expose the
     subagent name in every hook payload, so in mixed interactive sessions this
     is best-effort — the agent's own contract (no Edit tool, Write-scope rules)
     is the primary control and this hook is the backstop.

The guard fails OPEN on malformed input: a broken hook must never brick the
user's session. It never blocks reads — Verdict is meant to read everything.
"""

import json
import os
import sys

from qa_paths import is_allowed_path as _is_allowed


def _caller_is_verdict(data: dict) -> bool:
    for key in ("agent_name", "agent_type", "subagent_type", "agent"):
        val = data.get(key)
        if isinstance(val, str) and (val == "verdict" or val.endswith(":verdict")):
            return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail open: never break the session on malformed input

    tool_input = data.get("tool_input") or {}
    target = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or ""
    )

    if _is_allowed(target):
        return 0

    strict = os.environ.get("VERDICT_STRICT", "") not in ("", "0", "false")
    if strict or _caller_is_verdict(data):
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
