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
  2. the event names a cwd, and a QA root resolves from it;
  3. the state's own recorded `last_run.timestamp_utc` is minutes old — a QA
     run happened *in this session*, not last night;
  4. the harness signals are missing.

Condition 3 reads the timestamp the run wrote, not the file's mtime, because
mtime is not evidence a run happened: a `git checkout` of a repo with a
committed team-mode `.qa/` stamps it with the current time, and this repo's own
CI proved it — the hook fired on Verdict's own checked-out state file. A run
that happened records when it happened; copying a file does not.

Anything else exits 0 in about two stat calls. Every failure path — bad JSON,
an import that does not resolve, an unreadable state — also exits 0: a hook
that bricks sessions is worse than the problem it polices.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qa_paths import utf8_stderr  # noqa: E402  (path set above, as the guards do)

# A QA run that finished more than this long ago is not this turn's work. Long
# enough for a slow suite inside one turn, short enough that yesterday's state
# sitting in a normal coding session says nothing.
RECENT_S = 30 * 60
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"


def _silent(code: int = 0) -> int:
    return code


def main() -> int:
    utf8_stderr()
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
        from state import harness_signals, missing_durable, resolve_root
    except Exception:
        return _silent()  # not installed the way we expect; say nothing

    # No cwd in the event means we do not know where we are, and guessing with
    # os.getcwd() is how this hook first fired on a repository's own committed
    # state. Not knowing is a reason to stay silent, not a reason to look
    # somewhere else.
    cwd = event.get("cwd")
    if not cwd or not isinstance(cwd, str):
        return _silent()
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
        state = json.loads(state_path.read_text(encoding="utf-8"))

        stamp = (state.get("last_run") or {}).get("timestamp_utc")
        try:
            ran_at = datetime.strptime(str(stamp), _ISO_Z).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return _silent()  # no usable run time; not our business to guess
        if (datetime.now(timezone.utc) - ran_at).total_seconds() > RECENT_S:
            return _silent()  # this run did not happen during this turn

        signals = harness_signals(state, root)
        missing = [name for name, ok in signals.items() if not ok]
        if not missing:
            return _silent()
        # One definition of "went through the harness", shared with the gate.
        # This hook used to require all five signals and promise exit 6 on any
        # gap, while the gate decides on the three durable ones — so a
        # harness-produced state copied between checkouts (its facts.json and
        # judgment.json are per-run scratch that git never carries) tripped the
        # hook, which then predicted a gate failure that did not happen. Seen on
        # this repository's own run-4 state, copied from the clone that ran it.
        durable = missing_durable(signals)
    except Exception:
        return _silent()

    if not durable:
        # finalize computed this state, rendered its report and signed its row,
        # and the state re-derives to that row. What is absent is a session's
        # scratch — a checkout or a copy, not a hand-written state. The gate
        # will pass it; saying otherwise here trains people to ignore the hook.
        sys.stderr.write(
            "verdict: the QA state written this turn was produced by the harness; "
            f"{', '.join(missing)} not from this session, which is expected after a "
            "checkout or copy. If this session ran Verdict itself, it skipped "
            "verdict-facts — re-run through the harness.\n")
        return 0

    sys.stderr.write(
        "verdict: a QA state was written this turn without going through the harness "
        f"({', '.join(durable)}).\n"
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
