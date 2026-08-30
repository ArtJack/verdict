#!/usr/bin/env python3
"""Stop hook: the harness check that fires whether or not the model remembers.

Every guard in this system sits *downstream* of a tool the model must choose to
call. That was demonstrated, not theorised: a run of `/verdict:run` wrote to the
default state root while `$VERDICT_HOME` pointed elsewhere, invented a project
key, skipped `verdict-facts`/`verdict-finalize` entirely, and still produced a
confident, plausible-looking `FAIL`. `verdict-validate` would have rejected that
state; `verdict-gate --require-harness` would have exited 6. Neither fired,
because nothing invoked them.

A Stop hook fires when the turn ends — whether or not the model remembered
anything. So this one asks a single question: *did a QA run just leave
hand-written state on disk?* If so it blocks the stop once and says what to do.

The bar for speaking is deliberately high, because this runs at the end of every
turn in every session where the plugin is enabled:

  1. the turn is not already continuing because of this hook (never loop);
  2. a QA root resolves from the session's cwd;
  3. its `state.json` was modified within the last few minutes — a QA run
     happened *in this session*, not last night;
  4. the harness signals are missing.

Anything else exits 0 in about two stat calls. Every failure path — bad JSON,
an import that does not resolve, an unreadable state — also exits 0: a hook
that bricks sessions is worse than the problem it polices.
"""

import json
import os
import sys
import time
from pathlib import Path

# A QA run that finished more than this long ago is not this turn's work. Long
# enough for a slow suite inside one turn, short enough that yesterday's state
# sitting in a normal coding session says nothing.
RECENT_S = 30 * 60


def _silent(code: int = 0) -> int:
    return code


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return _silent()
    if not isinstance(event, dict):
        return _silent()
    # Already continuing because we blocked once. Saying it twice is a loop,
    # and a loop is worse than a miss.
    if event.get("stop_hook_active"):
        return _silent()

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
        from state import harness_signals, resolve_root
    except Exception:
        return _silent()  # not installed the way we expect; say nothing

    cwd = event.get("cwd") or os.getcwd()
    try:
        root = resolve_root(str(cwd))
        if root is None:
            from project_key import derive_key
            from state import home as state_home
            key, _ = derive_key(Path(cwd))
            candidate = state_home() / key
            root = candidate if (candidate / "state.json").is_file() else None
        if root is None:
            return _silent()

        state_path = Path(root) / "state.json"
        if not state_path.is_file():
            return _silent()
        if time.time() - state_path.stat().st_mtime > RECENT_S:
            return _silent()  # not written during this turn

        state = json.loads(state_path.read_text(encoding="utf-8"))
        signals = harness_signals(state, root)
        missing = [name for name, ok in signals.items() if not ok]
        if not missing:
            return _silent()
    except Exception:
        return _silent()

    sys.stderr.write(
        "verdict: a QA state was written this turn without going through the harness "
        f"({', '.join(missing)}).\n"
        f"  state: {state_path}\n"
        "Everything the harness measures — timestamps, SHAs, gate exit codes, test "
        "counts, finding hashes, ages, deltas — was composed rather than measured, and "
        "`verdict-gate --require-harness` will exit 6 on it.\n"
        "Redo the run through `verdict-facts` -> judgment.json -> `verdict-finalize` "
        "(§6). If the harness genuinely cannot run here, say so explicitly in the "
        "report with the command and its error, per §6 — do not leave this silent.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
