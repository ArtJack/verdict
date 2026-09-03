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

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta
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

def _heartbeat_s() -> int:
    try:
        return max(1, int(os.environ.get("VERDICT_HEARTBEAT_S", "60")))
    except ValueError:
        return 60


def _run_streaming(cmd, repo, env, timeout_s):
    """Run the claude CLI, echoing its output live, with a heartbeat.

    The previous shape — `subprocess.run(capture_output=True)` — was a black
    box: the nightly log stayed empty for the whole run, a killed parent left
    no trace at all, and the first external user reported being bitten by
    exactly that, twice. Lines are echoed to stderr as they arrive (so a
    redirected log grows in real time and survives a kill mid-run), and when
    the child says nothing for VERDICT_HEARTBEAT_S seconds (default 60) a
    heartbeat line says the run is alive and how long it has been quiet.

    Returns (returncode, combined_output); returncode is None on timeout.
    """
    proc = subprocess.Popen(cmd, cwd=repo, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines: queue.Queue = queue.Queue()

    def _pump():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=_pump, daemon=True).start()
    buf = []
    start = last_output = time.monotonic()
    heartbeat = _heartbeat_s()
    while True:
        remaining = timeout_s - (time.monotonic() - start)
        if remaining <= 0:
            proc.kill()
            proc.wait()
            return None, "".join(buf)
        try:
            item = lines.get(timeout=min(heartbeat, remaining))
        except queue.Empty:
            quiet = int(time.monotonic() - last_output)
            elapsed = int((time.monotonic() - start) // 60)
            print(f"verdict-run: still running — {elapsed}m elapsed, "
                  f"no output for {quiet}s", file=sys.stderr, flush=True)
            continue
        if item is None:
            break
        buf.append(item)
        last_output = time.monotonic()
        sys.stderr.write(item)
        sys.stderr.flush()
    return proc.wait(), "".join(buf)


def _head_sha(repo):
    try:
        proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _unchanged_reason(qa_root, repo):
    """A skip is earned, not assumed: the exact commit was already judged, and
    nothing time-based is due. Returns the reason string, or None (= run).

    Answers the objection every low-churn project raises against a nightly —
    "I don't change code every day" — with arithmetic instead of a schedule:
    on unchanged days the run costs nothing, on changed days it runs. Note
    the comparison is exact-sha, not `code_drift`: "behind by one commit" is
    precisely a reason TO run.
    """
    try:
        state = json.loads((Path(qa_root) / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    sha = (state.get("last_run") or {}).get("git_sha")
    head = _head_sha(repo)
    if not sha or not head or sha != head:
        return None
    if not state.get("verdict"):
        return None
    today = date.today().isoformat()
    for q in state.get("flaky_quarantine") or []:
        until = str((q or {}).get("quarantined_until") or "")
        # An expired (or unparseable) quarantine must be re-evaluated by a
        # real run; that re-evaluation is work only a model can do.
        if not until or until <= today:
            return None
    return (f"HEAD unchanged since run {state.get('run_number')} "
            f"({head[:12]}), no quarantine expiry due — re-gating the standing "
            "verdict without a model call")


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


_PERMISSION_FLAGS = ("--dangerously-skip-permissions", "--permission-mode", "--allowedTools",
                     "--allowed-tools")


def plugin_root(explicit=None):
    """Where `agents/verdict.md` and `hooks/hooks.json` live, or None.

    Three places, in order: an explicit path, `CLAUDE_PLUGIN_ROOT` (set when a
    plugin command invokes this), the checkout this file sits in (the plugin
    cache and a source clone both have that shape), and finally the newest
    version in the plugin cache — for the common pairing of the plugin
    installed for the editor and `verdict-qa-mcp` from PyPI for the CLI, whose
    wheel ships neither directory.
    """
    def _has(root):
        return (root / "agents" / "verdict.md").is_file() and \
               (root / "hooks" / "hooks.json").is_file()

    # An explicit root is authoritative. Falling through from a wrong path to
    # "whatever else is lying around" would run the agent from a checkout the
    # operator did not name — and make a wrong path impossible to notice.
    if explicit:
        return Path(explicit) if _has(Path(explicit)) else None

    candidates = [os.environ.get("CLAUDE_PLUGIN_ROOT"), Path(__file__).resolve().parents[2]]
    cache = Path.home() / ".claude" / "plugins" / "cache" / "verdict" / "verdict"
    if cache.is_dir():
        def _ver(p):
            return tuple(int(x) if x.isdigit() else -1 for x in p.name.split("."))
        candidates += sorted((p for p in cache.iterdir() if p.is_dir()), key=_ver, reverse=True)
    for cand in candidates:
        if cand and _has(Path(cand)):
            return Path(cand)
    return None


def provision(repo: Path, root) -> tuple[str | None, list[str]]:
    """Make the agent and its guards visible to an isolated headless session.

    The run is launched with `--setting-sources project,local`, so the
    user-scope plugin is never loaded — that isolation is deliberate, and it is
    also why a bare checkout cannot run the agent: the first self-run from a
    fresh clone came back `blocked`, with "Agent type 'verdict' not found",
    no hooks enforcing, and every tool denied. The model ran the contract
    inline from `agents/verdict.md`, self-imposed the guards, and reported its
    own self-check as failed rather than write state by hand — the right
    behaviour, in an environment the runner had built wrong. The nightly and
    the eval each hand-roll these same steps; the runner owns them now.

    Writes only what is absent: an existing `.claude/agents/verdict.md` is the
    operator's (the nightly provisions its own from a pinned checkout), and
    existing `hooks` are theirs too and are named rather than replaced. Hooks
    go in `settings.local.json`, the file a project's `.gitignore`
    conventionally excludes, so provisioning does not dirty a tracked
    `settings.json`. Returns (fatal problem or None, notes for stderr).
    """
    notes = []
    agent = repo / ".claude" / "agents" / "verdict.md"
    if agent.is_file():
        notes.append("provision: kept existing .claude/agents/verdict.md")
    elif root is None:
        return ("the `verdict` agent is not available to an isolated session and no "
                "plugin root was found — install the plugin (agents/ and hooks/ are not "
                "in the PyPI wheel), pass --plugin-root, or provision "
                ".claude/agents/verdict.md yourself", notes)
    else:
        agent.parent.mkdir(parents=True, exist_ok=True)
        text = (root / "agents" / "verdict.md").read_text(encoding="utf-8")
        agent.write_text(text.replace("${CLAUDE_PLUGIN_ROOT}", str(root)), encoding="utf-8")
        notes.append(f"provision: wrote .claude/agents/verdict.md from {root}")

    local = repo / ".claude" / "settings.local.json"
    current = {}
    if local.is_file():
        try:
            current = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            notes.append("provision: .claude/settings.local.json is unreadable — left "
                         "alone; the write/bash guards may not be enforcing")
            return None, notes
    if isinstance(current, dict) and "hooks" in current:
        notes.append("provision: kept existing hooks in .claude/settings.local.json")
    elif root is None:
        notes.append("provision: no plugin root, hooks NOT installed — the write/bash "
                     "guards are not enforcing this run")
    else:
        hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8")
                           .replace("${CLAUDE_PLUGIN_ROOT}", str(root).replace("\\", "\\\\")))
        current = current if isinstance(current, dict) else {}
        current["hooks"] = hooks["hooks"]
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        notes.append("provision: installed hooks into .claude/settings.local.json")
    return None, notes


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
    ap.add_argument("--skip-unchanged", action="store_true",
                    help="when HEAD equals the last run's sha and no quarantine "
                         "has expired, re-gate the standing verdict instead of "
                         "spending a model run")
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
    ap.add_argument("--no-provision", dest="provision", action="store_false",
                    help="do not write .claude/agents/verdict.md or the hook set into "
                         ".claude/settings.local.json before launching")
    ap.add_argument("--plugin-root", default=None,
                    help="where agents/ and hooks/ live (default: CLAUDE_PLUGIN_ROOT, "
                         "this checkout, then the newest plugin-cache version)")
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

    if args.skip_unchanged:
        reason = _unchanged_reason(qa_root, repo)
        if reason:
            print(f"verdict-run: skip — {reason}", file=sys.stderr)
            # max_age deliberately None here: the verdict still describes HEAD
            # exactly, so time-staleness is not the question. min_run_number
            # None too — no new run was expected.
            result = evaluate(project, args.fail_on, None, None,
                              require_harness=args.require_harness)
            print(f"verdict-run: verdict {result.get('verdict')!r} → exit "
                  f"{result['exit_code']} ({result['reason']})", file=sys.stderr)
            return result["exit_code"]

    if args.provision:
        problem, notes = provision(repo, plugin_root(args.plugin_root))
        for note in notes:
            print(f"verdict-run: {note}", file=sys.stderr)
        if problem:
            # Refused up front rather than spent: a session without the agent
            # can only ever come back `blocked`, after a full model run.
            print(f"verdict-run: {problem}", file=sys.stderr)
            return 2

    # Headless means nobody is there to approve a tool call, and a denied call
    # is how the first self-run turned into a read-only review. The scope
    # guards provisioned above are the control that makes skipping the prompt
    # safe — that is what they exist for. An operator who passes their own
    # permission flag after `--` keeps it.
    if not any(p.startswith(_PERMISSION_FLAGS) for p in passthrough):
        passthrough = [*passthrough, "--dangerously-skip-permissions"]

    env = dict(os.environ, VERDICT_STRICT="1", VERDICT_MODEL=args.model)
    # `project,local`: the user-scope plugin stays out (isolation), and the
    # hooks provisioned into settings.local.json come in.
    cmd = [args.claude_cmd, "-p", prompt, "--model", args.model,
           "--setting-sources", "project,local", *passthrough]

    for attempt in (1, 2):
        rc, output = _run_streaming(cmd, repo, env, args.timeout_s)
        if rc is None:
            print(f"verdict-run: attempt {attempt} timed out after {args.timeout_s}s",
                  file=sys.stderr)
            continue
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
