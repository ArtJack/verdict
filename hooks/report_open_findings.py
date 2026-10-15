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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

STALE_DAYS = 7
_ISO_Z = "%Y-%m-%dT%H:%M:%SZ"
_ORDER = ("Blocker", "Critical", "Major", "Minor", "Trivial")

# The first-run hint (2026-10-04). The Claude directory counted 112 installs by 96
# accounts, 1,747 loads in 1,136 sessions — and 0 uses, ever. Verdict does nothing
# until it is asked, and nothing told an installer how to ask. So the one session
# start that matters gets one line: in a repository with a test suite that Verdict
# has never looked at, once per repository and in at most three repositories per
# person, ever. Never in a resumed or compacted session, never headless or in CI.
FIRST_RUN_FILE = ".first-run.json"
FIRST_RUN_MAX = 3
_TEST_MARKERS = ("tests", "test", "spec", "__tests__", "pytest.ini", "tox.ini", "conftest.py",
                 "noxfile.py", "go.mod", "Cargo.toml", "pom.xml", "build.gradle",
                 "build.gradle.kts", "Gemfile", "mix.exs")
HINT_FOR_USER = ("Verdict is installed and has not looked at this repository yet. Run "
                 "/verdict:run for a first QA pass: it runs your tests, files findings with "
                 "evidence and ends with a release verdict. Read-only: it never edits your code. "
                 "(Shown once per repository; VERDICT_NO_HINT=1 turns it off.)")
HINT_FOR_MODEL = ("The Verdict QA plugin is installed but has never run on this repository. "
                  "If the user asks about tests, QA, regressions or release readiness, "
                  "/verdict:run is a read-only QA pass they can start.")


def _silent() -> int:
    return 0


def _repo_root(cwd):
    """The nearest directory at or above `cwd` holding `.git` (a directory in a clone,
    a file in a worktree), or None."""
    here = Path(cwd).resolve()
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return d
    return None


def _has_tests(root) -> bool:
    """A cheap look at the repository root, no walk: a test directory, a runner's
    config, a build file that implies one, a real npm test script, or pytest in
    pyproject. npm's placeholder ("no test specified") is not a test suite."""
    if any((root / name).exists() for name in _TEST_MARKERS):
        return True
    try:
        pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
        script = str(((pkg or {}).get("scripts") or {}).get("test") or "")
        if script and "no test specified" not in script:
            return True
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return "pytest" in (root / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return False


def _first_run_hint(event, cwd, verdict_home, key):
    """The hint's two texts, or None. Recorded before it is shown: a record that cannot
    be written would make the hint repeat in every session, which is worse than never."""
    if os.environ.get("VERDICT_STRICT") or os.environ.get("VERDICT_NO_HINT"):
        return None
    # `claude -p` and the Agent SDK report an `sdk-*` entrypoint: nobody is there to
    # read a hint, and spending one of the three on a script would waste it.
    if os.environ.get("CLAUDE_CODE_ENTRYPOINT", "").startswith("sdk"):
        return None
    if event.get("source", "startup") != "startup":
        return None
    root = _repo_root(cwd)
    if root is None or (root / ".qa").exists() or not _has_tests(root):
        return None
    record_path = Path(verdict_home) / FIRST_RUN_FILE
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {}
    shown = record.get("shown") if isinstance(record, dict) else None
    shown = dict(shown) if isinstance(shown, dict) else {}
    if key in shown or len(shown) >= FIRST_RUN_MAX:
        return None
    shown[key] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = record_path.with_name(record_path.name + ".tmp")
        tmp.write_text(json.dumps({"shown": shown}, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, record_path)
    except OSError:
        return None
    return HINT_FOR_USER, HINT_FOR_MODEL


def _parked_questions(root) -> list:
    """The parked questions, answers folded in — empty on any failure."""
    try:
        from questions import facts_view
        view = facts_view(root, datetime.now(timezone.utc).date())
        return list((view or {}).get("parked") or [])
    except Exception:
        return []


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
        key = None
        if root is None:
            key, _ = derive_key(Path(cwd))
            candidate = state_home() / key
            root = candidate if (candidate / "state.json").is_file() else None
        if root is None:
            hint = _first_run_hint(event, cwd, state_home(), key)
            if hint is None:
                return _silent()
            return _say_json({"systemMessage": hint[0],
                              "hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": hint[1]}})
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
        # The questions the tester parked for a person: pushed, not left in a
        # ledger nobody opens. One line, the first id, the command that answers.
        parked = _parked_questions(root)
        if parked:
            first = parked[0]
            lines.append(f"{len(parked)} question{'' if len(parked) == 1 else 's'} waiting for "
                         f"you — {first['id']}: {str(first.get('question') or '')[:100]}"
                         + (f" (+{len(parked) - 1} more)" if len(parked) > 1 else "")
                         + f". Answer: `verdict-answer {project} {first['id']} --answer \"…\"`")
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


def _say_json(payload) -> int:
    """Structured hook output: `systemMessage` is shown to the person, `additionalContext`
    goes to the model. UTF-8 for the same reason as the banner below."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
