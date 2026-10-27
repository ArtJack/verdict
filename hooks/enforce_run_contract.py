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

  1. it has not already said this, in this session (never loop);
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

**The run that never finalized (0.89.0).** Everything above needs a state on disk,
and the costliest failure leaves none: the tester measures the facts, investigates,
and ends its turn without `verdict-finalize` — no state, no report, a lost run. It is
the recorded signature of a cheaper model (`state_missing` / `report_missing` zero an
eval score by protocol), and until now this hook went silent on exactly that case at
the first `is_file()`. `verdict-facts` leaves `run-in-progress.json` and only
`verdict-finalize` removes it, so a marker still there when the tester stops is a run
that did not finish. The bar for speaking is identity, not a time window: the event
is a `SubagentStop` — or a `Stop` of a session started as the tester (`claude --agent
verdict`, 0.90.8) — the agent that is stopping is a Verdict agent, and the marker
was written by *this* session (`verdict-facts` records `CLAUDE_CODE_SESSION_ID`; the
event carries `session_id`). A marker some other night left behind, or a parallel
agent finishing while the tester is still at work, matches none of that. Said once
per marker — the marker remembers it was told.

**Whose continuation (0.93.1).** `stop_hook_active` says the turn goes on because *a*
Stop hook blocked, not which one. Read as "because of this hook", it silenced every
check for as long as another plugin kept the agent working — a loop plugin that blocks
each stop, a reminder that sends the agent back to its notes — so a run started inside
such a continuation and left unfinished was never told. The same hole was found and
closed in another author's Stop hook (project-memory, its F3-03/F3-04). The hook now
goes by its own record of what it said, per session and QA root, kept under Verdict's
home rather than in the project. Where it cannot keep one — no session id, a record it
cannot write, a link on the way — a continuation is read as its own, as before.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# (the path is set above, as the guards do)
from qa_paths import caller_is_verdict, utf8_stderr  # noqa: E402

# A QA run that finished more than this long ago is not this turn's work. Long
# enough for a slow suite inside one turn, short enough that yesterday's state
# sitting in a normal coding session says nothing.
RECENT_S = 30 * 60
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
MARKER = "run-in-progress.json"
# A marker older than this is not the run that is ending now, whoever wrote it. Long:
# a full suite, a coverage pass and an investigation fit inside one run.
UNFINISHED_S = 6 * 3600
# What the hook said, per session and QA root (0.93.1): under Verdict's home, so a
# team-mode `.qa/` never gains an untracked file, and pruned after two days.
TOLD_DIR = (".hooks", "stop-told")
TOLD_KEEP_S = 2 * 86400


def _silent(code: int = 0) -> int:
    return code


def _told_path(event: dict, root: Path, home: Path):
    """This session's record for this QA root, or None when the event does not say
    which session it is — and then nothing can be remembered."""
    session = event.get("session_id")
    if not isinstance(session, str) or not session:
        return None
    digest = hashlib.sha256(f"{session}\0{root}".encode("utf-8", "replace")).hexdigest()[:24]
    return home.joinpath(*TOLD_DIR, f"{digest}.json")


def _linked(path: Path, home: Path) -> bool:
    """A link anywhere below Verdict's home on the way to the record: not ours to
    read or write through."""
    p = path
    while p != home and p != p.parent:
        if p.is_symlink():
            return True
        p = p.parent
    return False


def _told(path, home: Path) -> set:
    if path is None or _linked(path, home):
        return set()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    told = doc.get("told") if isinstance(doc, dict) else None
    return {t for t in told if isinstance(t, str)} if isinstance(told, list) else set()


def _remember(path, home: Path, told: set, subject: str) -> bool:
    """Record that `subject` was said; False when it could not be, which the caller
    treats as "nothing remembers" and falls back to the old rule."""
    if path is None or _linked(path, home):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if _linked(path, home):
            return False
        now = datetime.now(timezone.utc).timestamp()
        for old in path.parent.glob("*.json"):
            try:
                if old != path and now - old.lstat().st_mtime > TOLD_KEEP_S:
                    old.unlink()
            except OSError:
                pass
        path.write_text(json.dumps({"told": sorted(told | {subject})}) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _unfinished_run(event: dict, root: Path):
    """The message for a tester stopping on a run it started and never finalized, or
    None. Every doubt is a None: this runs at the end of every subagent's turn."""
    # A Stop is the tester's own when the session itself is the Verdict agent (`claude
    # --agent verdict`, which verdict-run launches since 0.90.8): the 2026-10-06 money gates
    # that ended with no state were top-level sessions, which this rule never saw.
    if event.get("hook_event_name") not in ("SubagentStop", "Stop"):
        return None
    # The same question the two scope guards ask, answered by the same function. This
    # one used to ask whether the name CONTAINED "verdict", which also made a tester of
    # any agent with the word in its name (K-D-13).
    if not caller_is_verdict(event):
        return None         # somebody else's agent finishing beside a run still in progress
    marker_path = root / MARKER
    if marker_path.is_symlink():
        return None         # not the file `verdict-facts` wrote; never written through
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(marker, dict) or marker.get("stop_told"):
        return None
    session = event.get("session_id")
    if not session or marker.get("session_id") != session:
        return None         # another session's marker: last night's, or a run next door
    try:
        started = datetime.strptime(str(marker.get("started_utc")), _ISO_Z).replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    if not 0 <= (datetime.now(timezone.utc) - started).total_seconds() <= UNFINISHED_S:
        return None
    try:
        # Told once, by the marker: the retry this block causes, the tester's next stop
        # and any later agent of the same session all find it.
        marker["stop_told"] = datetime.now(timezone.utc).strftime(_ISO_Z)
        marker_path.write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")
    except OSError:
        # Nothing remembers it was said. A continuation is then read as this hook's
        # own, as before 0.93.1, so a root it cannot write cannot make it loop.
        if event.get("stop_hook_active"):
            return None
    return (
        "verdict: this agent started a QA run and is stopping without finishing it — "
        f"`verdict-facts` ran at {marker.get('started_utc')} and `verdict-finalize` never did.\n"
        f"  qa root: {root}\n"
        "There is no state and no report for this run, so `verdict-gate` will read it as a run "
        "that never happened (exit 4 or 5) and everything found so far is lost.\n"
        "Write judgment.json (finding files you already wrote are kept) and run "
        "`verdict-finalize` now (§6). If it cannot be finalized, say so in the handoff with the "
        "command and its error — do not end silently.\n")


def main() -> int:
    utf8_stderr()
    try:
        event = json.load(sys.stdin)
    except Exception:
        return _silent()
    if not isinstance(event, dict):
        return _silent()

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
        from state import harness_signals, missing_durable, resolve_root
        from state import home as state_home
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
            key, _ = derive_key(Path(cwd))
            # A first run that never finalized has a marker and no state at all.
            for candidate in (state_home() / key, Path(cwd) / ".qa"):
                if (candidate / "state.json").is_file() or (candidate / MARKER).is_file():
                    root = candidate
                    break
        if root is None:
            return _silent()
        home = state_home()
        told_path = _told_path(event, Path(root), home)
        # Continuing because *a* Stop hook blocked. Only where this session cannot be
        # told apart is that read as this hook's own block: saying it twice is a loop,
        # and a loop is worse than a miss.
        if event.get("stop_hook_active") and told_path is None:
            return _silent()

        unfinished = _unfinished_run(event, Path(root))
        if unfinished:
            sys.stderr.write(unfinished)
            return 2

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
        # Said once per state in a session, by the hook's own record — so a turn another
        # hook keeps going neither silences it nor hears it twice.
        subject = f"{stamp}#{state.get('run_number')}"
        told = _told(told_path, home)
        if subject in told:
            return _silent()
        if not _remember(told_path, home, told, subject) and event.get("stop_hook_active"):
            return _silent()    # nothing remembers it: read the continuation as its own
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
