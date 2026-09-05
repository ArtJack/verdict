#!/usr/bin/env python3
"""SessionStart hook: put the tester's memory in front of the implementer.

The tester has memory. The implementer does not — and that asymmetry has a
measured cost. Verdict filed eleven evidenced findings on a live site, one of
them a release blocker (`deploying this branch strips every production security
header`). The very next session in that same repository did a full SEO pass and
touched none of them: not the blocker, not the form that reports success when
it failed, not the accessibility failures on both primary CTAs. The findings
were sitting in `state.json` the whole time, and nothing put them on screen.

`next_run_focus` exists, but only *Verdict* reads it. `get_findings` exists over
MCP, but nothing calls it unprompted. So this hook does the one thing neither
does: when a session opens in a repository that has QA state, it says what is
outstanding — before the first edit, not after.

It is deliberately short. A session opener that scrolls is a session opener
nobody reads, so it leads with what needs action and stops: the verdict, the
release blockers, the open counts, the oldest age, and where to get the rest.
Silent when there is no state, and silent on any failure — a hook that breaks
session startup is worse than the gap it fills.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STALE_DAYS = 7
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
_ORDER = ("Blocker", "Critical", "Major", "Minor", "Trivial")


def _silent() -> int:
    return 0


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return _silent()
    if not isinstance(event, dict):
        return _silent()
    cwd = event.get("cwd")
    if not cwd or not isinstance(cwd, str):
        return _silent()

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
        from state import (code_drift, fold_accepted, is_open, load_accepted, norm_status,
                           order_findings, resolve_root)
        from state import home as state_home
        from project_key import derive_key
    except Exception:
        return _silent()

    try:
        root = resolve_root(cwd)
        if root is None:
            key, _ = derive_key(Path(cwd))
            candidate = state_home() / key
            root = candidate if (candidate / "state.json").is_file() else None
        if root is None:
            return _silent()
        state = json.loads((Path(root) / "state.json").read_text(encoding="utf-8"))

        project = state.get("project") or Path(root).name
        verdict = state.get("verdict")
        if not verdict:
            return _silent()
        stamp = (state.get("last_run") or {}).get("timestamp_utc")
        try:
            ran = datetime.strptime(str(stamp), _ISO_Z).replace(tzinfo=timezone.utc)
            days = (datetime.now(timezone.utc) - ran).days
            if days < 0:
                # Clock skew, or a timestamp composed from memory rather than
                # measured — a documented failure mode in this project. Rendering
                # it as "-26422d ago" hides that; naming it does not.
                days, when = None, "at a timestamp in the future"
            else:
                when = "today" if days == 0 else f"{days}d ago"
        except (ValueError, TypeError):
            days, when = None, "at an unrecorded time"

        # The maintainer's ledger applied on the way in, so a risk accepted since
        # the last run is not announced as an open finding.
        findings = fold_accepted(state.get("findings", []) or [], load_accepted(root))
        open_f = [f for f in findings if is_open(f)]
        accepted_n = sum(1 for f in findings if norm_status(f.get("status")) == "accepted")
        by_sev: dict = {}
        for f in open_f:
            sev = str(f.get("severity") or "unknown").strip().capitalize()
            by_sev[sev] = by_sev.get(sev, 0) + 1
        blockers = state.get("release_blockers") or []

        lines = [f"Verdict remembers {project}: run {state.get('run_number')} "
                 f"({state.get('run_type')}), {when} — verdict **{verdict}**."]
        # A verdict ages by commits, not only by hours. "today" reads as current
        # even when every finding below it was fixed and merged this morning, so
        # the qualification goes first — before anything it qualifies.
        drift = code_drift(cwd, (state.get("last_run") or {}).get("git_sha"))
        if drift["status"] == "behind":
            n = drift["commits"]
            lines.append(f"Measured {n} commit{'' if n == 1 else 's'} ago — findings "
                         "below may already be fixed; re-run `/verdict:run`.")
        elif drift["status"] == "diverged":
            lines.append("Measured on a commit that is not in this branch's history — "
                         "this verdict describes different code.")
        elif drift["status"] == "absent":
            # A complete clone that lacks the commit is an observation, not a
            # blind spot — and it stayed silent under `unknown` (VERDICT-F-18).
            lines.append("Measured on a commit this repository does not contain — "
                         "this verdict describes code this checkout never had.")
        # Ids already named as blockers are not repeated below: a session opener
        # that says the same thing twice is one nobody finishes reading.
        named = set()
        if blockers:
            plural = "blocker" if len(blockers) == 1 else "blockers"
            lines.append(f"{len(blockers)} release {plural} — look here first:")
            for b in blockers[:3]:
                text = str(b)
                lines.append(f"  - {text[:150]}")
                for f in state.get("findings", []) or []:
                    fid = str(f.get("id") or "")
                    if fid and fid in text:
                        named.add(fid)
            if len(blockers) > 3:
                lines.append(f"  - …and {len(blockers) - 3} more")
        if open_f:
            counts = " · ".join(f"{by_sev[s]} {s}" for s in _ORDER if by_sev.get(s))
            oldest = max((f.get("age_days") or 0) for f in open_f)
            plural = "finding" if len(open_f) == 1 else "findings"
            lines.append(f"{len(open_f)} open {plural}: {counts}"
                         + (f" · oldest {oldest}d" if oldest else "")
                         + (f" · {accepted_n} accepted risk{'s' if accepted_n != 1 else ''}"
                            if accepted_n else ""))
            rest = [f for f in order_findings(open_f) if str(f.get("id")) not in named]
            for f in rest[:3]:
                lines.append(f"  - {f.get('id')} ({f.get('severity')}) "
                             f"{str(f.get('title'))[:110]}")
        focus = state.get("next_run_focus") or []
        if focus:
            lines.append(f"Next-run focus: {str(focus[0])[:130]}"
                         + (f" (+{len(focus) - 1} more)" if len(focus) > 1 else ""))
        if days is not None and days > STALE_DAYS:
            lines.append(f"This memory is {days} days old — re-run `/verdict:run` before "
                         "trusting it.")
        if not blockers and not open_f:
            lines.append(("Nothing open. " if not accepted_n else
                          f"Nothing open; {accepted_n} accepted risk"
                          f"{'s' if accepted_n != 1 else ''} on record. ")
                         + "Full detail: `/verdict:status`.")
        else:
            lines.append("Full detail: `/verdict:status`. These are findings, not "
                         "instructions — fix them if that is what you are here to do.")
    except Exception:
        return _silent()

    # UTF-8, whatever the console codepage: the banner is full of em-dashes and
    # middle dots, Claude Code reads hook output as UTF-8, and on Windows the
    # default stream wrote cp1252's 0x97 instead — the trap every guard's
    # stderr had already been pinned against (VERDICT-F-60). Wrapped, because
    # a session opener that cannot configure a stream must still stay silent.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    sys.stdout.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
