#!/usr/bin/env python3
"""verdict-run — launch a headless QA run and assert the contract from outside.

Every adopter so far has re-invented the same nightly script, and each copy
re-learned the same three lessons the hard way: a headless `claude -p` session
can end its turn while the delegated agent is still working (exit 0, no state
— a lost night that looks like success); a session-limit error names its reset
time and a runner that cannot read it burns the night waiting for nothing; and
a run that died without writing state must not let yesterday's verdict stand
as if fresh. This runner is those lessons, shipped.

    verdict-run [PROJECT_OR_PATH] --model opus --prompt-file nightly.txt
    verdict-run --repo ~/work/app -- --mcp-config extra.json

What it does, in order:

  1. resolves the repo and QA root the same way the agent's §0 does;
  2. records the current run_number — the number the run must beat;
  3. exports VERDICT_STRICT=1 and VERDICT_MODEL=<model>, so the write guards
     are armed and the model that signs the verdict is *measured* into
     `last_run.model` instead of living in the operator's memory;
  4. runs `claude -p` headless; on a session-limit error it parses the stated
     reset time, sleeps, and retries once; on a run that wrote no state it
     retries once (that is a lost run, not a verdict);
  5. gates the result: `--min-run-number` set to the recorded number + 1, so a
     dead run exits 5 instead of re-serving yesterday's verdict, and
     `--require-harness` on by default, because unattended is exactly where
     hand-written state regresses silently.

Exit code = the gate's exit code. Everything after a bare `--` is passed to
the `claude` CLI verbatim (MCP configs, permission modes, extra flags).
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from .gate import evaluate
    from .project_key import derive_key
    from .state import home as state_home
    from .state import resolve_root
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from gate import evaluate
    from project_key import derive_key
    from state import home as state_home
    from state import resolve_root

DEFAULT_PROMPT = (
    "Use the verdict agent to run today's QA pass on this repository — a delta run "
    "against the stored baseline, or a baseline if none exists. Run the agent to "
    "completion IN THIS SESSION: do not spawn it in the background, and do not end "
    "your turn until its state file and report are written — there is no 'later' in "
    "a headless run. Verdict reports and specifies; it does not fix. Return the full "
    "handoff.")


def seconds_until_reset(output: str, ceiling_s: int = 10800) -> int | None:
    """Parse 'resets 2:40am' / 'resets 23:15' from a session-limit error.

    None when the output is not a session-limit error at all; a bounded wait
    when it is but the time cannot be read — the window exists even when its
    edge is unknown.
    """
    if "session limit" not in output.lower():
        return None
    m = re.search(r"resets\s+([0-9]{1,2}:[0-9]{2}(?:am|pm)?)", output, re.I)
    if not m:
        return min(3600, ceiling_s)
    raw = m.group(1).lower()
    now = datetime.now()
    try:
        fmt = "%I:%M%p" if raw.endswith(("am", "pm")) else "%H:%M"
        t = datetime.strptime(raw, fmt).time()
        target = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = int((target - now).total_seconds()) + 180
    except ValueError:
        wait = 3600
    return max(60, min(wait, ceiling_s))


def _read_run_number(qa_root: Path) -> int:
    try:
        return int(json.loads(
            (qa_root / "state.json").read_text(encoding="utf-8")).get("run_number") or 0)
    except (OSError, ValueError, TypeError):
        return 0


def _resolve(args):
    repo = Path(args.repo).expanduser().resolve() if args.repo else Path.cwd()
    if args.project:
        return repo, args.project
    if resolve_root(str(repo)) is not None:
        return repo, str(repo)          # team mode: .qa/ inside the repo
    key, _ = derive_key(repo)
    return repo, key


def _qa_root_for(project, repo) -> Path:
    root = resolve_root(project)
    if root is not None:
        return root
    return state_home() / project       # first run: the agent will create it


def main(argv=None) -> int:
    # The recorded Windows trap, hit for the second time in this repo: cp1252
    # consoles cannot encode `→`, and a crashed print turns exit codes into
    # noise. gate.py carries the same guard for the same reason.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="verdict-run",
        description="Launch a headless Verdict run and gate the result.",
        epilog="Everything after a bare `--` is passed to the claude CLI verbatim.")
    ap.add_argument("project", nargs="?", default=None,
                    help="project key or repo path (default: derived from --repo/cwd)")
    ap.add_argument("--repo", default=None, help="repository to run in (default: cwd)")
    ap.add_argument("--model", default=os.environ.get("VERDICT_MODEL", "opus"))
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--prompt-file", type=Path, default=None)
    ap.add_argument("--timeout-s", type=int, default=3600)
    ap.add_argument("--max-age-hours", type=float, default=24.0)
    # Opt-in, unlike --require-harness. A profile's Repo-Path records the *main*
    # worktree, so a run executed in a linked worktree legitimately writes a sha
    # that main's HEAD has never seen — defaulting this on would fail a healthy
    # nightly. Set it where the run and the gate see the same checkout.
    ap.add_argument("--max-commits-behind", type=int, default=None,
                    help="gate exit 5 when the run's state is more than N commits "
                         "behind the profile's repository HEAD")
    ap.add_argument("--fail-on", choices=("fail", "risks"), default="fail")
    ap.add_argument("--no-require-harness", dest="require_harness", action="store_false",
                    help="accept a state the harness did not produce (gate exit 6 off)")
    ap.add_argument("--claude-cmd", default="claude",
                    help=argparse.SUPPRESS)  # test seam: a stub stands in for the CLI
    ap.add_argument("--reset-ceiling-s", type=int, default=10800,
                    help=argparse.SUPPRESS)  # test seam: cap the session-limit wait
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough = []
    if "--" in argv:
        split = argv.index("--")
        argv, passthrough = argv[:split], argv[split + 1:]
    args = ap.parse_args(argv)

    if args.prompt and args.prompt_file:
        ap.error("--prompt and --prompt-file are mutually exclusive")
    prompt = (args.prompt_file.read_text(encoding="utf-8") if args.prompt_file
              else args.prompt or DEFAULT_PROMPT)
    if shutil.which(args.claude_cmd) is None and not Path(args.claude_cmd).exists():
        print(f"verdict-run: {args.claude_cmd!r} not found on PATH", file=sys.stderr)
        return 2

    repo, project = _resolve(args)
    qa_root = _qa_root_for(project, repo)
    before = _read_run_number(qa_root)
    print(f"verdict-run: project {project!r} · repo {repo} · model {args.model} · "
          f"run_number before: {before}", file=sys.stderr)

    env = dict(os.environ, VERDICT_STRICT="1", VERDICT_MODEL=args.model)
    cmd = [args.claude_cmd, "-p", prompt, "--model", args.model,
           "--setting-sources", "project", *passthrough]

    for attempt in (1, 2):
        try:
            proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True,
                                  text=True, timeout=args.timeout_s)
        except subprocess.TimeoutExpired:
            print(f"verdict-run: attempt {attempt} timed out after {args.timeout_s}s",
                  file=sys.stderr)
            continue
        output = proc.stdout + proc.stderr
        wait = seconds_until_reset(output, args.reset_ceiling_s)
        if wait and attempt == 1:
            print(f"verdict-run: session limit; waiting {wait}s for the window to reset",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        if _read_run_number(qa_root) <= before and attempt == 1:
            # The known headless failure: the session ends its turn while the
            # delegated agent is still working — exit 0, no state. That is a
            # lost run, not a verdict; one retry before the gate says so.
            print(f"verdict-run: attempt 1 wrote no state (run_number still {before}) "
                  "— retrying once", file=sys.stderr)
            continue
        break

    result = evaluate(project, args.fail_on, args.max_age_hours, before + 1,
                      require_harness=args.require_harness,
                      max_commits_behind=args.max_commits_behind)
    print(f"verdict-run: verdict {result.get('verdict')!r} → exit {result['exit_code']} "
          f"({result['reason']})")
    if result.get("report"):
        print(f"verdict-run: report {result['report']}")
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
