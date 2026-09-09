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
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

try:
    from .gate import evaluate
    from .project_key import derive_key
    from .state import home as state_home
    from .state import is_path_like, norm_status, resolve_root
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from gate import evaluate
    from project_key import derive_key
    from state import home as state_home
    from state import is_path_like, norm_status, resolve_root

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
    today = clock.today().isoformat()
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
    "a headless run. Verdict reports and specifies; it does not fix. Relay the agent's "
    "handoff verbatim and add nothing of your own: no summary, no offer to write fixes "
    "— an offer to fix under Verdict's name is the one sentence its position cannot "
    "afford.")


def limit_kind(output: str) -> str | None:
    """Which allowance the CLI says is spent: `session` (a window that reopens
    within hours) or `weekly` (days away), or None.

    The difference decides whether waiting is sensible. A session limit is worth
    sleeping through; a weekly one is not — the first version knew only the word
    "session", so a weekly limit read as an ordinary failure, and the runner
    spent its retry, reported a lost run, and left the operator to find the real
    reason in the log.
    """
    low = output.lower()
    if "weekly limit" in low:
        return "weekly"
    if "session limit" in low or "usage limit" in low:
        return "session"
    return None


def limit_line(output: str) -> str:
    """The CLI's own sentence about the limit, for a message that explains itself."""
    for line in output.splitlines():
        if "limit" in line.lower() and "reset" in line.lower():
            return line.strip()[:200]
    return "the CLI reported a usage limit"


def seconds_until_reset(output: str, ceiling_s: int = 10800) -> int | None:
    """Parse 'resets 2:40am' / 'resets 23:15' from a session-limit error.

    None when the output is not a limit this runner should wait out — no limit
    at all, or a weekly one, which reopens in days and must be reported rather
    than slept through. A bounded wait when the window exists but its edge
    cannot be read.
    """
    if limit_kind(output) != "session":
        return None
    m = re.search(r"resets\s+([0-9]{1,2}:[0-9]{2}(?:am|pm)?)", output, re.I)
    if not m:
        return min(3600, ceiling_s)
    raw = m.group(1).lower()
    now = clock.local_now()     # the CLI prints its reset time in the user's wall-clock
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
        if is_path_like(args.project) and resolve_root(args.project) is None:
            # `verdict-run .` in a checkout with no `.qa/`: the argument names
            # the repository, not a solo key. Taken literally it became the key
            # `.`, so the runner read run_number from `~/.claude/verdict/./`,
            # declared an 18-minute completed run "wrote no state", ran it
            # again, and exited 4 over two valid runs on disk — the first thing
            # a stranger hit. Derive the key the agent will derive (§0).
            target = Path(args.project).expanduser().resolve()
            if not args.repo and target.is_dir():
                repo = target
            key, _ = derive_key(target)
            return repo, key
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


GATEWAY_FLAGS = {
    # A model that is not Anthropic's behind the base URL rejects the `thinking`
    # block and any pre-release field, and cannot be named from the CLI's built-in
    # catalogue. Without these three a gateway run fails with a 400 that names
    # none of this.
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
}


def is_gateway(url) -> bool:
    """True only for a base URL that is *not* Anthropic's own.

    `ANTHROPIC_BASE_URL` is routinely set to `https://api.anthropic.com` by
    tooling that never intended to redirect anything. Treating any value as a
    gateway sent a run to an empty config directory with no login in it, and the
    session came back "Not logged in" — the operator's named account ignored
    because of a variable that changed nothing.
    """
    if not url:
        return False
    host = urlparse(str(url)).hostname or ""
    return not (host == "anthropic.com" or host.endswith(".anthropic.com"))


def read_env_file(path) -> dict:
    """`KEY=VALUE` lines from a file the operator owns.

    A nightly should be able to say *which account or endpoint it spends* without
    that credential appearing in a command line, a crontab, or a log. Blank lines
    and `#` comments are skipped; surrounding quotes are stripped.
    """
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def seed_config(config_dir, repo) -> None:
    """Mark `repo` trusted inside a config directory the CLI may never have seen.

    A fresh `CLAUDE_CONFIG_DIR` has accepted neither the trust dialog nor
    bypass-permissions mode, and this runner always passes
    `--dangerously-skip-permissions`: the session then exits 0 having done
    nothing at all — no output, no state — which the gate reports as a lost run
    while the real cause is configuration. Measured 2026-09-08: identical
    command, empty config directory silent, seeded one answers.
    """
    config_dir = Path(config_dir)
    doc_path = config_dir / ".claude.json"
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8")) if doc_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    doc["bypassPermissionsModeAccepted"] = True
    projects = doc.setdefault("projects", {})
    if isinstance(projects, dict):
        entry = projects.setdefault(str(Path(repo).resolve()), {})
        if isinstance(entry, dict):
            entry.update({"hasTrustDialogAccepted": True,
                          "hasCompletedProjectOnboarding": True})
    config_dir.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def session_env(env: dict, repo) -> tuple[dict, list]:
    """Apply the operator's account or endpoint choice → (env, notes).

    `CLAUDE_CONFIG_DIR` chooses *which stored login pays* — a second
    subscription, a machine account — and is seeded so the headless run is not
    refused in silence. `ANTHROPIC_BASE_URL` chooses a different endpoint
    entirely (an LLM gateway, a local model server): the CLI ignores
    `ANTHROPIC_AUTH_TOKEN` while it has a login of its own to prefer, so a
    gateway run needs a config directory with no login in it.
    """
    notes = []
    if is_gateway(env.get("ANTHROPIC_BASE_URL")):
        for key, value in GATEWAY_FLAGS.items():
            env.setdefault(key, value)
        if env.get("ANTHROPIC_AUTH_TOKEN") and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = env["ANTHROPIC_AUTH_TOKEN"]
        if not env.get("CLAUDE_CONFIG_DIR"):
            notes.append("endpoint: ANTHROPIC_BASE_URL is set but CLAUDE_CONFIG_DIR is not — "
                         "a CLI with a stored login sends that credential instead of the "
                         "gateway's and the gateway answers 401")
        notes.append(f"endpoint: {env['ANTHROPIC_BASE_URL']}")
    config_dir = env.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        seed_config(config_dir, repo)
        notes.append(f"account: CLAUDE_CONFIG_DIR {config_dir} (trust seeded)")
    return env, notes


PROVISION_RECORD = "verdict-provision.json"   # under .claude/, beside what it describes


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    Writes what is absent, and re-writes what it wrote itself when the source
    moved. `.claude/verdict-provision.json` records the root and the hash of
    every file the runner rendered, so a run with a different `--plugin-root`,
    or the same root after a plugin upgrade, replaces the runner's own copy and
    says so. It used to keep whatever was there: a control run launched from
    the installed 0.82.0 plugin kept a prompt rendered from a development
    checkout, resolved that checkout as its plugin root, and measured half of
    itself with code that was being edited at the time — under the installed
    version's name. A file the runner did not write, or one edited since, is
    the operator's (the nightly provisions its own from a pinned checkout) and
    is kept, named on stderr. Hooks go in `settings.local.json`, the file a
    project's `.gitignore` conventionally excludes, so provisioning does not
    dirty a tracked `settings.json`. Returns (fatal problem or None, notes).
    """
    notes = []
    dot = repo / ".claude"
    record_path = dot / PROVISION_RECORD
    record = {}
    if record_path.is_file():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            record = {}
    if not isinstance(record, dict):
        record = {}

    agent = dot / "agents" / "verdict.md"
    rendered = None
    if root is not None:
        rendered = (root / "agents" / "verdict.md").read_text(encoding="utf-8") \
            .replace("${CLAUDE_PLUGIN_ROOT}", str(root))
    mine = record.get("agent") if isinstance(record.get("agent"), dict) else {}
    if agent.is_file():
        current = agent.read_text(encoding="utf-8")
        owned = bool(mine.get("sha256")) and mine["sha256"] == _sha(current)
        if owned and rendered is not None and _sha(rendered) != mine["sha256"]:
            agent.write_text(rendered, encoding="utf-8")
            why = (f"the plugin root moved from {mine.get('root')} to {root}"
                   if str(mine.get("root")) != str(root) else "the prompt at that root changed")
            notes.append(f"provision: re-provisioned .claude/agents/verdict.md from {root} — {why}")
            record["agent"] = {"root": str(root), "sha256": _sha(rendered)}
        elif owned:
            notes.append(f"provision: .claude/agents/verdict.md is current (from {root})")
        else:
            notes.append("provision: kept existing .claude/agents/verdict.md — not written by "
                         "verdict-run, or edited since, so it is the operator's")
    elif root is None:
        return ("the `verdict` agent is not available to an isolated session and no "
                "plugin root was found — install the plugin (agents/ and hooks/ are not "
                "in the PyPI wheel), pass --plugin-root, or provision "
                ".claude/agents/verdict.md yourself", notes)
    else:
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_text(rendered, encoding="utf-8")
        notes.append(f"provision: wrote .claude/agents/verdict.md from {root}")
        record["agent"] = {"root": str(root), "sha256": _sha(rendered)}

    local = dot / "settings.local.json"
    current = {}
    if local.is_file():
        try:
            current = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            notes.append("provision: .claude/settings.local.json is unreadable — left "
                         "alone; the write/bash guards may not be enforcing")
            _save_record(record_path, record)
            return None, notes
    hooks_rendered = None
    if root is not None:
        hooks_rendered = json.loads(
            (root / "hooks" / "hooks.json").read_text(encoding="utf-8")
            .replace("${CLAUDE_PLUGIN_ROOT}", str(root).replace("\\", "\\\\")))["hooks"]
    mine = record.get("hooks") if isinstance(record.get("hooks"), dict) else {}
    if isinstance(current, dict) and "hooks" in current:
        owned = bool(mine.get("sha256")) and \
            mine["sha256"] == _sha(json.dumps(current["hooks"], sort_keys=True))
        if owned and hooks_rendered is not None and \
                _sha(json.dumps(hooks_rendered, sort_keys=True)) != mine["sha256"]:
            current["hooks"] = hooks_rendered
            local.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
            notes.append(f"provision: re-installed hooks into .claude/settings.local.json from "
                         f"{root} — they pointed at {mine.get('root')}")
            record["hooks"] = {"root": str(root),
                               "sha256": _sha(json.dumps(hooks_rendered, sort_keys=True))}
        elif owned:
            notes.append(f"provision: hooks are current (from {root})")
        else:
            notes.append("provision: kept existing hooks in .claude/settings.local.json — not "
                         "installed by verdict-run, or edited since, so they are the operator's")
    elif root is None:
        notes.append("provision: no plugin root, hooks NOT installed — the write/bash "
                     "guards are not enforcing this run")
    else:
        current = current if isinstance(current, dict) else {}
        current["hooks"] = hooks_rendered
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        notes.append("provision: installed hooks into .claude/settings.local.json")
        record["hooks"] = {"root": str(root),
                           "sha256": _sha(json.dumps(hooks_rendered, sort_keys=True))}
    _save_record(record_path, record)
    return None, notes


def _save_record(path: Path, record: dict) -> None:
    """What the runner rendered, so the next run can tell its own copy from the
    operator's. Written only when there is something to record."""
    if not record:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        pass


# ── the model-free night ──────────────────────────────────────────────────
#
# "I don't change code every day" is the objection every low-churn project
# raises against a nightly, and --skip-unchanged answered the exact-sha half of
# it. The other half: HEAD moved, but by a commit that touched nothing any
# finding cites. The harness can tell — it hashes every cited line (0.83.0),
# runs the gates, diffs the test-id set, and knows the quarantine dates — so
# the runner asks it, and when every condition holds it finalizes a sweep: the
# previous verdict carried by id (the 0.84.0 verb), signed by no model, a run
# number advanced so the gate's freshness reads true. Any condition failing
# prints why and runs the model. The judgment is synthetic and says so in every
# field a reader would look at.

def _harness(sub: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "verdict_mcp.harness", sub, *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _changed_files(repo, sha_range: str):
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", sha_range],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return sorted({ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()})


def sweep_blockers(facts: dict, previous: dict, changed, today) -> list[str]:
    """Every reason this run cannot be swept — empty means it can. Each
    condition is a measurement the harness already made; none is a guess."""
    why = []
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    if drift.get("status") != "measured":
        why.append("evidence drift not measured"
                   + (f" ({drift['reason']})" if drift.get("reason") else ""))
    else:
        summ = drift.get("summary") or {}
        moved = list(summ.get("drifted_findings") or []) + list(summ.get("drifted_accepted") or [])
        if moved or summ.get("drifted_intact"):
            why.append("cited code moved or changed: "
                       + ", ".join(moved[:5] or ["a verified-intact item"]))
    if changed is None:
        why.append("no commit range to compare")
    else:
        cited = set()
        for f in previous.get("findings") or []:
            if not isinstance(f, dict) or norm_status(f.get("status")) in ("resolved", "withdrawn"):
                continue
            cited |= {str(a.get("path")).replace("\\", "/") for a in (f.get("anchors") or [])
                      if isinstance(a, dict) and a.get("path")}
        for group in previous.get("verified_intact_anchors") or []:
            cited |= {str(a.get("path")).replace("\\", "/") for a in (group or [])
                      if isinstance(a, dict) and a.get("path")}
        hit = sorted(set(changed) & cited)
        if hit:
            why.append("changed files a finding cites: " + ", ".join(hit[:5]))
    gates = facts.get("gates") or {}
    if not gates:
        why.append("no gate ran")
    for name, g in gates.items():
        if g.get("result") != "pass":
            why.append(f"gate {name} failed")
        if "counts_unparsed" in g:
            why.append(f"gate {name}: counts unparsed")
        if g.get("executed_nothing"):
            why.append(f"gate {name}: {g['executed_nothing']}")
    if gates and not any(g.get("counts") for g in gates.values()):
        why.append("no gate produced test counts")
    ids = facts.get("test_ids") if isinstance(facts.get("test_ids"), dict) else {}
    if ids.get("status") != "measured":
        why.append("the test-id set was not measured")
    elif ids.get("added_count") or ids.get("removed_count"):
        why.append(f"the test-id set changed (+{ids.get('added_count')}/-{ids.get('removed_count')})")
    for q in previous.get("flaky_quarantine") or []:
        until = str((q or {}).get("quarantined_until") or "")
        if not until or until <= today.isoformat():
            why.append(f"quarantine due: {(q or {}).get('test_id')}")
    if facts.get("previous_run_incomplete"):
        why.append("the previous run never finished")
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") == "measured" and cov.get("changed_lines") \
            and not cov.get("changed_lines_executed"):
        why.append("the diff has changed lines no test executed")
    return why


def sweep_judgment(facts: dict, previous: dict, changed: list, commits) -> dict:
    """The synthetic judgment of a sweep: the previous verdict, every open
    finding carried by id, and a not_tested that says what a sweep does not do."""
    open_ids = [str(f["id"]) for f in previous.get("findings") or []
                if isinstance(f, dict) and f.get("id") and norm_status(f.get("status")) == "open"]
    sha_range = (facts.get("last_run") or {}).get("sha_range")
    n = f"{commits} commit{'' if commits == 1 else 's'}" if commits is not None else "commits"
    m = f"{len(changed)} file{'' if len(changed) == 1 else 's'}"
    return {
        "topic": "sweep",
        "verdict": previous.get("verdict"),
        "isolation_check": {"result": "n/a", "method": "model-free sweep: no agent ran; "
                            "verdict-facts read the checkout and wrote only inside the QA root"},
        "full_sweep": False,
        "release_blockers": list(previous.get("release_blockers") or []),
        "findings": [], "still_open": open_ids, "resolved": [], "questions": [],
        "not_tested": [f"everything a judgment covers — this run measured only: HEAD moved {n} "
                       f"({m} changed, none cited by a finding), every gate green, the collected "
                       "test-id set unchanged, no quarantine due, no cited line moved"],
        "verified_intact": [],
        "next_run_focus": list(previous.get("next_run_focus") or []),
        "flaky_quarantine": list(previous.get("flaky_quarantine") or []),
        "prose": {"scope": f"Model-free sweep over `{sha_range}`: {n}, {m} changed, none cited by "
                           "an open or accepted finding or a verified-intact item.",
                  "notes": "No agent ran. The previous verdict is carried because nothing it "
                           "rested on moved; the next model run judges the change on its merits."},
    }


def sweep(repo, qa_root, project, fail_on, require_harness, before) -> int | None:
    """Try the model-free sweep → the gate's exit code, or None to run the model."""
    try:
        previous = json.loads((Path(qa_root) / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("verdict-run: no sweep — no previous state to carry; running the model",
              file=sys.stderr)
        return None
    facts_proc = _harness("facts", "--repo", str(repo), "--qa-root", str(qa_root))
    if facts_proc.returncode != 0:
        print("verdict-run: no sweep — verdict-facts failed: "
              + (facts_proc.stderr or "").strip().splitlines()[-1:][0] if facts_proc.stderr
              else "verdict-run: no sweep — verdict-facts failed", file=sys.stderr)
        return None
    try:
        facts = json.loads((Path(qa_root) / "facts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("verdict-run: no sweep — facts.json unreadable; running the model", file=sys.stderr)
        return None
    sha_range = (facts.get("last_run") or {}).get("sha_range")
    changed = _changed_files(repo, sha_range) if sha_range else None
    why = sweep_blockers(facts, previous, changed, clock.today())
    if why:
        print("verdict-run: no sweep — " + "; ".join(why) + " — running the model", file=sys.stderr)
        return None
    count = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", sha_range],
                           capture_output=True, text=True)
    commits = int(count.stdout.strip()) if count.returncode == 0 and count.stdout.strip().isdigit() else None
    judgment = sweep_judgment(facts, previous, changed or [], commits)
    jpath = Path(qa_root) / "judgment.json"
    jpath.write_text(json.dumps(judgment, indent=2) + "\n", encoding="utf-8")
    fin = _harness("finalize", "--qa-root", str(qa_root), "--judgment", str(jpath), "--sweep")
    if fin.returncode != 0:
        print("verdict-run: no sweep — finalize refused the sweep; running the model:\n"
              + (fin.stderr or "").strip()[-600:], file=sys.stderr)
        return None
    counts = " · ".join(f"{name} {g.get('summary') or g.get('result')}"
                        for name, g in (facts.get("gates") or {}).items())
    print(f"verdict-run: swept — run {before + 1}: HEAD moved "
          f"{commits if commits is not None else '?'} commit(s), {len(changed or [])} file(s) "
          f"changed, none cited by a finding; gates green ({counts}); test-id set unchanged; "
          f"no quarantine due; no cited line moved — verdict {previous.get('verdict')!r} "
          "carried, no model call", file=sys.stderr)
    result = evaluate(project, fail_on, None, before + 1, require_harness=require_harness)
    print(f"verdict-run: verdict {result.get('verdict')!r} → exit {result['exit_code']} "
          f"({result['reason']})")
    if result.get("report"):
        print(f"verdict-run: report {result['report']}")
    return result["exit_code"]


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
    ap.add_argument("--skip-unless-drift", action="store_true",
                    help="when HEAD moved but nothing any finding cites changed, every gate "
                         "is green, the test-id set is unchanged and no quarantine is due, "
                         "finalize a model-free sweep instead of spending a model run "
                         "(implies --skip-unchanged); any condition failing runs the model")
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
    ap.add_argument("--env-file", type=Path, default=None, metavar="PATH",
                    help="KEY=VALUE file merged into the run's environment: "
                         "CLAUDE_CONFIG_DIR to spend a chosen account's allowance rather "
                         "than the ambient login, or ANTHROPIC_BASE_URL (+ "
                         "ANTHROPIC_AUTH_TOKEN) to run against an LLM gateway or a local "
                         "model server. Keeps the credential out of the command line")
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

    if args.skip_unchanged or args.skip_unless_drift:
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

    if args.skip_unless_drift:
        code = sweep(repo, qa_root, project, args.fail_on, args.require_harness, before)
        if code is not None:
            return code

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
    if args.env_file:
        if not args.env_file.is_file():
            print(f"verdict-run: --env-file {args.env_file} does not exist", file=sys.stderr)
            return 2
        env.update(read_env_file(args.env_file))
    env, env_notes = session_env(env, repo)
    for note in env_notes:
        print(f"verdict-run: {note}", file=sys.stderr)
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
        if limit_kind(output) == "weekly":
            # Days away, not hours: nothing this run can wait for, and a second
            # attempt would only spend the retry. Say so in the CLI's own words.
            print(f"verdict-run: {limit_line(output)} — no model run is possible until then; "
                  "the standing verdict is left as it is", file=sys.stderr)
            break
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
