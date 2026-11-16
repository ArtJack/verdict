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

`--on-drift` decides what step 4 is. `model` is the default and the behaviour
above. `local` and `none` are for a night nobody asked for: both imply
`--skip-unless-drift`, and neither can reach the `claude` CLI at all — `local`
hands a blocked sweep to `verdict-local` against a gateway, `none` writes nothing
and exits 5. A local night with no endpoint is refused before anything runs,
because "quietly spend the expensive model instead" is the one outcome an
unattended run must never have.

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
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from .gate import evaluate, news_line
    from .project_key import derive_key
    from .state import home as state_home
    from .state import is_path_like, resolve_root
    from . import clock
    from . import escalate
    from . import sandbox
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import escalate
    import sandbox
    from gate import evaluate, news_line
    from project_key import derive_key
    from state import home as state_home
    from state import is_path_like, resolve_root
try:  # split out of this file by the structure pass; still importable here
    from .runner_stream import _run_streaming
except ImportError:  # executed as a bare script
    from runner_stream import _run_streaming
try:  # split out of this file by the structure pass; still importable here
    from .runner_limits import (final_stop, flag_refused, resolve_cap, seconds_until_reset,
                                limit_kind as limit_kind, limit_line as limit_line)
except ImportError:  # executed as a bare script
    from runner_limits import (final_stop, flag_refused, resolve_cap, seconds_until_reset,
                               limit_kind as limit_kind, limit_line as limit_line)
try:  # split out of this file by the structure pass; still importable here
    from .runner_env import (BG_WAIT_ENV, GAPS_DEFAULT_ENV, child_env, env_files, hidden_names,
                             passthrough_names, pin_model_aliases, read_env_file, session_env,
                             is_gateway as is_gateway, seed_config as seed_config)
except ImportError:  # executed as a bare script
    from runner_env import (BG_WAIT_ENV, GAPS_DEFAULT_ENV, child_env, env_files, hidden_names,
                            passthrough_names, pin_model_aliases, read_env_file, session_env,
                            is_gateway as is_gateway, seed_config as seed_config)
try:  # split out of this file by the structure pass; still importable here
    from .runner_sweep import (sweep, _harness as _harness, sweep_blockers as sweep_blockers,
                               sweep_judgment as sweep_judgment)
except ImportError:  # executed as a bare script
    from runner_sweep import (sweep, _harness as _harness, sweep_blockers as sweep_blockers,
                              sweep_judgment as sweep_judgment)


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

# The prompt when the session IS the tester (`--agent verdict`): there is no outer
# session left to relay, delegate or offer anything.
AGENT_PROMPT = (
    "Run today's QA pass on this repository — a delta run against the stored baseline, or "
    "a baseline if none exists. This is a run: start with verdict-facts and end with "
    "verdict-finalize, in this session and in the foreground; an answer without state is "
    "not accepted, and there is no 'later' in a headless run.")

# The tester is the session itself, not a subagent the session may or may not spawn. On
# 2026-10-06 four asked money gates ran from a packet that never asked for the agent: a
# generic session at effort `medium`, without Verdict's prompt, and two of the four ended
# their turn with no state. `--agent` makes the provisioned agent file the main thread —
# its prompt, its tools, and the scope guards that know it by name — and `--effort` pins
# the effort its frontmatter pins.
AGENT_NAME = "verdict"
AGENT_EFFORT_DEFAULT = "xhigh"


def agent_effort(repo) -> str:
    """The effort the provisioned agent file pins (`effort:` in its frontmatter)."""
    try:
        text = (Path(repo) / ".claude" / "agents" / f"{AGENT_NAME}.md").read_text(encoding="utf-8")
    except OSError:
        return AGENT_EFFORT_DEFAULT
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    for line in head.splitlines():
        if line.strip().startswith("effort:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            return value or AGENT_EFFORT_DEFAULT
    return AGENT_EFFORT_DEFAULT


def agent_flags(repo, passthrough) -> list:
    """`--agent verdict --effort <pinned>`, when the agent file is there to load. Without
    it (`--no-provision` on a repository that has none) the session is told in words, as
    before. An operator's own `--agent` or `--effort` after `--` is theirs to keep."""
    if not (Path(repo) / ".claude" / "agents" / f"{AGENT_NAME}.md").is_file():
        return []
    def given(flag):
        return any(p == flag or p.startswith(flag + "=") for p in passthrough)

    flags = []
    if not given("--agent"):
        flags += ["--agent", AGENT_NAME]
    if not given("--effort"):
        flags += ["--effort", agent_effort(repo)]
    return flags


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


# Verdict's own harness, as the tester calls it by name. These commands write the QA root, add
# fresh worktrees in the repository's git directory and box the project's code themselves
# (`sandbox.py`), which macOS will not do from inside another sandbox. So they run outside the
# tester's, by name. A redirect, a `cd` or a `$(…)` keeps a call inside; the harness then finds
# itself nested and leans on the outer box (`sandbox.nested`).
HARNESS_COMMANDS = ("verdict-facts", "verdict-finalize", "verdict-gate", "verdict-validate",
                    "verdict-replay")


def tester_sandbox(repo: Path, qa_root: Path, env: dict, mode: str) -> list:
    """`--settings` that put the tester's own Bash in Claude Code's sandbox, or [] for `off`.

    `sandbox.py` boxes the project's code when the harness runs it. This boxes everything else
    the tester runs: its probes, its ad-hoc pytest, the scripts it writes. Before 0.94.0 those
    ran with `--dangerously-skip-permissions` and the scope hooks as the only fence, and the
    hooks are "a deny-heuristic, not a sandbox" (SECURITY.md).

    Measured 2026-11-03, a headless `claude -p` launched as `verdict-paid` launches one:
      * outside the sandbox, the tester's Bash saw `ANTHROPIC_API_KEY` and the network;
      * inside it, with the key denied, it saw neither — but only with `strictAllowlist`.
        In bypass mode, the mode this runner starts, the sandbox's proxy otherwise lets a
        connection to an unlisted host through without asking.

    `failIfUnavailable` only under `sandbox: required`. Elsewhere a machine with no sandbox
    runs the tester as before, and the facts say what boxed the project's code.
    """
    if mode == "off":
        return []

    def real(path) -> str:
        return os.path.realpath(str(path))

    writable = {real(qa_root)}
    common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-common-dir"],
                            capture_output=True, text=True)
    if common.returncode == 0 and common.stdout.strip():
        git_dir = Path(common.stdout.strip())
        writable.add(real(git_dir if git_dir.is_absolute() else Path(repo) / git_dir))
    deny_read = ["~/" + p for p in sandbox.SECRET_PATHS] + env_files()
    if env.get("CLAUDE_CONFIG_DIR"):
        deny_read.append(real(Path(env["CLAUDE_CONFIG_DIR"]).expanduser()))
    hidden = hidden_names(env)
    settings = {"sandbox": {
        "enabled": True,
        "failIfUnavailable": mode == "required",
        "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": True,
        "excludedCommands": [*HARNESS_COMMANDS, *(f"{c} *" for c in HARNESS_COMMANDS)],
        "network": {"strictAllowlist": True, "allowedDomains": []},
        "filesystem": {"allowWrite": sorted(writable), "denyRead": deny_read,
                       "allowRead": [real(qa_root)]},
        "credentials": {"envVars": [{"name": n, "mode": "deny"} for n in hidden]},
    }}
    env[sandbox.OUTER_ENV] = "claude-code"   # a harness nested in this box knows it is ours
    return ["--settings", json.dumps(settings)]


def repo_claude_config(repo: Path) -> tuple:
    """The Claude Code configuration the repository tracks in git → (paths, None), or
    ([], why) when git cannot say. Case-insensitive: on APFS a tracked `.CLAUDE/settings.json`
    loads as `.claude/settings.json` (measured by review, 2026-11-03)."""
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "--", ":(icase).claude"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return [], (proc.stderr.strip().splitlines() or [f"git exit {proc.returncode}"])[-1][:160]
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()], None


def claude_config_on_disk(repo: Path) -> tuple:
    """Every entry of the checkout's Claude Code configuration on disk, whatever git says →
    (paths, None), or ([], why) when the disk cannot be read. A `.claude` symlink is an entry
    of its own, never followed; so is any symlink inside it."""
    found = []
    try:
        names = os.listdir(repo)
    except OSError as exc:
        return [], f"the checkout could not be listed ({type(exc).__name__})"
    for name in names:
        if name.lower() != ".claude":
            continue
        top = Path(repo) / name
        if top.is_symlink() or not top.is_dir():
            found.append(name)
            continue
        try:
            for root, dirs, files in os.walk(top, onerror=_raise):
                for entry in [*files, *(d for d in dirs if (Path(root) / d).is_symlink())]:
                    found.append((Path(root) / entry).relative_to(repo).as_posix())
        except OSError as exc:
            return [], f"{name} could not be read ({type(exc).__name__})"
    return sorted(found), None


def _raise(exc):
    raise exc


def provisioned(repo: Path, tracked=()) -> set:
    """The entries `provision` wrote and nobody has changed since, never a tracked one: the
    agent, a hooks file that holds nothing but its hooks, and the record itself."""
    dot = Path(repo) / ".claude"
    try:
        record = json.loads((dot / PROVISION_RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    mine = {f".claude/{PROVISION_RECORD}"}
    agent = dot / "agents" / "verdict.md"
    try:
        if (record.get("agent") or {}).get("sha256") == _sha(agent.read_text(encoding="utf-8")):
            mine.add(".claude/agents/verdict.md")
    except OSError:
        pass
    try:
        local = json.loads((dot / "settings.local.json").read_text(encoding="utf-8"))
        if isinstance(local, dict) and set(local) == {"hooks"} and \
                (record.get("hooks") or {}).get("sha256") == _sha(
                    json.dumps(local["hooks"], sort_keys=True)):
            mine.add(".claude/settings.local.json")
    except (OSError, ValueError):
        pass
    return mine - {t for t in tracked}


def shipped_config_allowed(repo: Path, box_mode: str, stage: str = "before provisioning") -> bool:
    """Say what Claude Code configuration the checkout holds; False when the run must stop.

    That configuration runs in the tester's session, outside every box. Measured 2026-11-03:
    a tracked `.claude/settings.json` SessionStart hook ran before the tester's first turn and
    saw `ANTHROPIC_API_KEY`. A tracked agent file would be kept by `provision` as the
    operator's, and would replace the contract. Agent front matter carries hooks too.

    In a repository the owner trusts, these files are the owner's: they are named, and the run
    goes on. Under `sandbox: required` they are a stranger's. Then anything under `.claude`
    that `provision` did not write stops the run: tracked or not, whatever its case or
    symlink. The check fails closed when git or the disk cannot be read. It runs again after
    premeasure, which ran the project's code."""
    tracked, why_git = repo_claude_config(repo)
    if box_mode != "required":
        if tracked:
            print(f"verdict-run: the repository ships {', '.join(tracked)}; the tester's session "
                  "loads it as the project's own. For a repository you do not trust, set "
                  "`sandbox: required`.", file=sys.stderr)
        return True
    on_disk, why_disk = claude_config_on_disk(repo)
    foreign = sorted(set(on_disk) - provisioned(repo, tracked)) + sorted(
        t for t in tracked if t not in on_disk)
    problem = why_git or why_disk
    if problem or foreign:
        what = problem or ", ".join(foreign)
        print("verdict-run: `sandbox: required`, and the checkout's Claude Code configuration "
              f"is not only Verdict's own ({stage}: {what}). The tester's session would load it "
              "and run it outside the sandbox, so nothing was started. Run on a checkout "
              "without it.", file=sys.stderr)
        return False
    return True


def measure_first(repo: Path, qa_root: Path, env: dict, sha_range, harness_mode: str) -> bool:
    """Premeasure, started with no credential in its environment: on macOS the project's code
    it runs can read the start-up environment of any process of the same user (`sandbox.py`).
    Then the checkout's Claude Code configuration is read again, since that code just ran.
    False when the run must stop."""
    hidden = set(hidden_names(env))
    head = premeasure(repo, qa_root, {k: v for k, v in env.items() if k not in hidden}, sha_range)
    if head:
        env[PREMEASURED_ENV] = head
    return shipped_config_allowed(repo, harness_mode, stage="after premeasure")


def pin_box_floor(args, qa_root) -> str:
    """The box the project's code gets for this whole run, pinned before anything runs.

    `--sandbox` is the floor. The profile, as it reads now, can only tighten it. The result goes
    to every process this run starts as `VERDICT_SANDBOX`, so a `profile.md` edited later in
    the run cannot loosen it. The tester's Bash can write the QA root, and the harness commands
    it runs read the profile again (review, 2026-11-03)."""
    if args.sandbox:
        os.environ[sandbox.FLOOR_ENV] = args.sandbox
    mode = sandbox.from_profile(qa_root).mode
    os.environ[sandbox.FLOOR_ENV] = mode
    return mode


def tester_box_mode(args, qa_root) -> str:
    """The tester's sandbox mode: `off` under `--no-sandbox`, else the profile's held to the
    floor `--sandbox` set. Says so when off."""
    mode = "off" if args.no_sandbox else sandbox.from_profile(qa_root).mode
    if mode == "off":
        why = "--no-sandbox" if args.no_sandbox else "the profile says `sandbox: off`"
        print(f"verdict-run: the tester's Bash runs outside Claude Code's sandbox ({why})",
              file=sys.stderr)
    return mode


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


# ── the tier below the sweep ──────────────────────────────────────────────
#
# The sweep answers "nothing a finding cites moved". `--on-drift` answers the
# harder half: something DID move, and the owner has decided that a run nobody
# asked for spends no Claude tokens at all. So the night steps down a tier
# instead of reaching for the expensive model — skip, then sweep, then the local
# engine, and if that cannot run, nothing, loudly. What it may never do is fall
# through to `claude` quietly: an unattended run that silently costs money is the
# exact failure this release was measured to close.


def local_endpoint(env_file, env: dict) -> tuple:
    """(base_url, token) for the local engine, from an env file or the ambient
    environment — the same `KEY=VALUE` file the rest of the runner reads."""
    values = dict(env)
    if env_file:
        if not Path(env_file).is_file():
            return None, None
        values.update(read_env_file(env_file))
    return values.get("ANTHROPIC_BASE_URL"), values.get("ANTHROPIC_AUTH_TOKEN")


def clear_marker(qa_root) -> None:
    """Drop the run marker this runner's own facts pass left behind.

    A sweep that was refused has already run `verdict-facts`, which stakes a
    claim on the QA root before the gates. When nothing follows it — the local
    engine cannot run and no model will — that marker would tell tomorrow's run
    that tonight died mid-flight, which is a lie about a night that never
    started.
    """
    try:
        (Path(qa_root) / "run-in-progress.json").unlink()
    except OSError:
        pass


PREMEASURED_ENV = "VERDICT_FACTS_PREMEASURED"
PREMEASURE_TIMEOUT_S = 3600


def premeasure(repo, qa_root, env, sha_range=None, run=subprocess.run) -> str | None:
    """`verdict-facts` before the tester starts → the HEAD it measured, or None (0.91.1).

    The tester's first command is verdict-facts, and its Bash call ends at 10 minutes; a large
    suite under coverage plus the assertion-gap census does not fit. Measured here, outside any
    Claude Code session, the census gets its whole budget; the tester's call adopts the result.
    A measurement that fails is said and left to the tester, which measures as before."""
    child = {k: v for k, v in env.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    cmd = [sys.executable, "-m", "verdict_mcp.harness", "facts", "--repo", str(repo),
           "--qa-root", str(qa_root)] + (["--range", sha_range] if sha_range else [])
    started = time.monotonic()
    try:
        proc = run(cmd, env=child, capture_output=True, text=True, timeout=PREMEASURE_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"verdict-run: measuring before the tester failed ({type(exc).__name__}); the tester "
              "measures on its own", file=sys.stderr)
        return None
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or [""]
        print(f"verdict-run: measuring before the tester exited {proc.returncode} ({tail[0][:160]}); "
              "the tester measures on its own", file=sys.stderr)
        return None
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    print(f"verdict-run: facts measured before the tester started ({time.monotonic() - started:.0f} s); "
          "its verdict-facts adopts them", file=sys.stderr)
    return head or None


def run_local(repo, qa_root, args, base_url, token) -> int:
    """Hand the night to `verdict-local` → its exit code. No `claude` is launched."""
    try:
        from .small import main as local_main
    except ImportError:  # bare-script execution
        from small import main as local_main
    # The sweep attempt has just measured this HEAD; measuring again ran the suite twice
    # and lost the test-id delta the first measurement had recorded (2026-10-15).
    argv = ["--repo", str(repo), "--qa-root", str(qa_root), "--delta", "--reuse-facts",
            "--model", args.local_model, "--limit", str(args.local_limit), "--reruns", "0"]
    if args.local_env_file:
        argv += ["--env-file", str(args.local_env_file)]
    # The endpoint reaches verdict-local the way it reached this runner: from
    # the env file (passed on as --env-file, which small.main reads into a local
    # copy) or from the ambient environment it already shares. It used to be
    # written into this process's os.environ for the whole night as well, from
    # where every gate, re-run and probe inherited the token (audit 2026-10-02,
    # O-S-2). `base_url` and `token` are what the liveness check above used.
    del base_url, token
    return local_main(argv)


def escalation_packet(repo, qa_root, args, budget_usd, local_main=None) -> tuple:
    """The breadth pass and the tester's packet → (packet text or None, exit code).

    `verdict-local` reads in a scratch copy of the QA root, on the facts verdict-run has just
    measured, so the real record is written once, by the tester. The copy is removed whatever
    happens; the packet and its summary are kept beside the record."""
    if local_main is None:
        try:
            from .small import main as local_main
        except ImportError:  # bare-script execution
            from small import main as local_main
    scratch = escalate.scratch_copy(qa_root)
    try:
        argv = escalate.local_argv(repo, scratch, qa_root, args.local_model, args.local_limit,
                                   args.sha_range, args.local_env_file)
        code = local_main(argv)
        if code != 0:
            print(f"verdict-run: the breadth pass exited {code} — no packet, so no escalation run "
                  "was started; run without --escalate for a full asked run", file=sys.stderr)
            return None, 5
        facts = json.loads((Path(qa_root) / "facts.json").read_text(encoding="utf-8"))
        text, summary = escalate.compose(scratch, facts, budget_usd,
                                         args.calls or escalate.CALLS_DEFAULT)
        escalate.record(qa_root, text, summary)
        print(f"verdict-run: escalation — {summary['leads']} item(s) for the tester from "
              f"{summary['local_model']} ({summary['functions_read']} function(s) read, "
              f"{summary['proven_local']} proven by counterfactual, {summary['survivor_functions']} "
              f"census survivor function(s)); packet {escalate.PACKET_FILE}", file=sys.stderr)
        return text, 0
    except (OSError, json.JSONDecodeError) as exc:
        print(f"verdict-run: the breadth pass left no readable facts ({type(exc).__name__}) — no "
              "escalation run was started", file=sys.stderr)
        return None, 5
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def start_escalation(repo, qa_root, args, env, base_url, token, cap) -> tuple:
    """The checks and the breadth pass before an escalation run's tester → (packet, exit code
    or None to go on). Every refusal here starts nothing, and never a full run in its place.
    Without --escalate there is nothing to do: ("", None)."""
    if not args.escalate:
        return "", None
    if not env.get(PREMEASURED_ENV):
        print("verdict-run: --escalate reads on the facts measured before the tester starts, "
              "and that measurement failed — no escalation run was started, and no full run "
              "in its place", file=sys.stderr)
        return "", 2
    try:
        from .small import gateway_alive
    except ImportError:  # bare-script execution
        from small import gateway_alive
    alive, detail = gateway_alive(base_url, token)
    print(f"verdict-run: local engine — {detail}", file=sys.stderr)
    if not alive:
        clear_marker(qa_root)
        print("verdict-run: the local gateway is down, so there is no breadth pass — no "
              "escalation run was started, and no full run in its place", file=sys.stderr)
        return "", 5
    packet, code = escalation_packet(repo, qa_root, args, cap)
    if packet is None:
        clear_marker(qa_root)
        return "", code
    return packet, None


def asked_preflight(args, ap) -> None:
    """`--lite`, `--escalate` and `--calls` shape an asked run, a model run; a local or
    model-free night has no tester to tell. One cheap mode at a time."""
    if args.lite and args.escalate:
        ap.error("--lite and --escalate are two cheap asked runs: pick one")
    if (args.lite or args.calls is not None) and args.on_drift != "model":
        ap.error("--lite and --calls shape an asked run's tester; --on-drift local/none runs none")
    if args.calls is not None and args.calls < 1:
        ap.error("--calls takes a positive number")


def escalate_preflight(args, ap) -> tuple:
    """(base_url, token, exit code or None) for `--escalate`, before anything runs; without
    the flag, (None, None, None)."""
    if not args.escalate:
        return None, None, None
    if args.on_drift != "model" or args.no_premeasure:
        ap.error("--escalate is an asked run: it measures first and launches the tester, so it "
                 "takes neither --on-drift local/none nor --no-premeasure")
    base_url, token = local_endpoint(args.local_env_file, dict(os.environ))
    if not base_url or not token:
        print("verdict-run: --escalate needs the local gateway — ANTHROPIC_BASE_URL and "
              "ANTHROPIC_AUTH_TOKEN in --local-env-file or in the environment. Refusing before "
              "anything runs: an escalation run with no breadth pass would be a full asked run "
              "nobody asked for.", file=sys.stderr)
        return None, None, 2
    return base_url, token, None


# Opus 5.5 list rates, $/MTok: what an escalation run's bill line prices its tokens at.
OPUS_RATES = {"input_tokens": 4.0, "output_tokens": 20.0, "cache_read_input_tokens": 0.20,
              "cache_creation_input_tokens": 5.0}


def budget_line(cap, calls) -> str:
    """What a capped asked run's tester is told about its budget (0.93.0). A session stopped at its
    dollar cap writes no state, so the tester paces itself and keeps room to finalize; the
    2026-10-19 runs that were told so all finalized under the cap."""
    if cap is None:
        return ""
    aim = f"Aim for about {calls} tool calls. " if calls else ""
    return f"{aim}The run stops at ${cap:g}: keep enough of it to finalize."


def tester_prompt(prompt, told, tester, packet, budget="") -> str:
    """The words the session is launched with: the operator's, else the agent's or the
    delegating prompt, then an escalation run's packet or a capped run's budget line."""
    text = prompt if told else (AGENT_PROMPT if tester else DEFAULT_PROMPT)
    if packet:
        return f"{text}\n\n{packet}"
    # The budget joins on the same line: a `.cmd` shim on Windows (an npm-installed `claude`)
    # ends an argument at its first newline, and every flag after the prompt would be lost.
    return f"{text} {budget}" if budget else text


def print_bill(args, qa_root, before=0, capped=False) -> None:
    """A capped asked run (--lite, --escalate, --max-budget-usd) closes with what it cost; every
    run's bill is in usage.jsonl as before."""
    bill = bill_line(qa_root, before) if (args.escalate or capped) else None
    if bill:
        print(f"verdict-run: {'escalation run' if args.escalate else 'run'} bill — {bill}")


def bill_line(qa_root, before=0) -> str | None:
    """The bill of every run this invocation wrote (run_number above `before`), summed from
    usage.jsonl and priced when the model is Opus 5.5: a session that finalized twice spent twice."""
    try:
        rows = [json.loads(line) for line in
                (Path(qa_root) / "usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return None
    usage: dict = {}
    for row in rows:
        if isinstance(row.get("run_number"), int) and row["run_number"] > before:
            for key, value in (row.get("usage") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
                elif key == "model":
                    usage[key] = value
    if not usage.get("requests"):
        return None
    line = (f"{usage['requests']} request(s), {usage.get('output_tokens', 0):,} output and "
            f"{usage.get('cache_read_input_tokens', 0):,} cache-read token(s)")
    if str(usage.get("model") or "").startswith("claude-opus-5-5"):
        dollars = sum(usage.get(k, 0) * rate for k, rate in OPUS_RATES.items()) / 1e6
        line += f", about ${dollars:.2f} at list price"
    return line


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
    ap.add_argument("--range", dest="sha_range", default=None, metavar="BASE..HEAD",
                    help="the change a gate reviews: exported as VERDICT_RANGE, so verdict-facts "
                         "records it and verdict-finalize can tell a defect the change made from "
                         "one it found")
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
    ap.add_argument("--escalate", action="store_true",
                    help="a cheaper asked run: verdict-local reads first, at zero Claude tokens, "
                         "in a scratch copy of the QA root, and the tester gets only what it passed "
                         "on (claims it proved, census survivors, unproven readings, reasons a model "
                         "run is owed) and a dollar cap, $2.50 unless --max-budget-usd says "
                         "otherwise. Needs the local gateway (--local-env-file)")
    ap.add_argument("--lite", action="store_true",
                    help="the cheap asked run: a normal run (the tester, verdict-facts, verdict-finalize, "
                         f"the in-run replay) with a ${escalate.BUDGET_DEFAULT_USD:g} cap unless "
                         "--max-budget-usd says otherwise, the tester told the cap and an aim of about "
                         f"{escalate.CALLS_DEFAULT} tool calls (--calls N). Measured 2026-10-19 against plain "
                         "Claude Code at the same budget: as many known defects located; --escalate located fewer")
    ap.add_argument("--calls", "--escalate-calls", dest="calls", type=int, default=None, metavar="N",
                    help="the tool calls an asked run's tester is asked to aim for (default "
                         f"{escalate.CALLS_DEFAULT} with --lite or --escalate); the dollar cap still stops the run")
    ap.add_argument("--sandbox", choices=("auto", "required"), default=None,
                    help="the least box the project's code runs in, for this run and every "
                         "process it starts; a profile can only tighten it, and under `required` "
                         "a profile's sandbox_network, sandbox_write and test_env are ignored — "
                         "the setting for a repository you do not trust")
    ap.add_argument("--no-sandbox", action="store_true",
                    help="run the tester's Bash outside Claude Code's sandbox (default: inside it, "
                         "with no network, the caller's secrets hidden and writes kept to the "
                         "checkout, the QA root and temp; the profile's `sandbox: off` does the same)")
    ap.add_argument("--no-premeasure", action="store_true",
                    help="let the tester run verdict-facts itself instead of measuring before it "
                         "starts (default: measure first, so a long census is not cut by the "
                         "tester's 10-minute Bash call)")
    ap.add_argument("--skip-unless-drift", action="store_true",
                    help="when HEAD moved but nothing any finding cites changed, every gate "
                         "is green, the test-id set is unchanged and no quarantine is due, "
                         "finalize a model-free sweep instead of spending a model run "
                         "(implies --skip-unchanged); any condition failing runs the model")
    ap.add_argument("--on-drift", choices=("model", "local", "none"), default="model",
                    help="what a night does when the sweep is blocked: spend a Claude run "
                         "(`model`, the default), hand it to `verdict-local` on a gateway "
                         "(`local`), or do nothing and exit 5 (`none`). `local` and `none` "
                         "imply --skip-unless-drift, and neither ever launches `claude`")
    ap.add_argument("--local-env-file", type=Path, default=None, metavar="PATH",
                    help="KEY=VALUE file with ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN for "
                         "--on-drift local (default: the ambient environment)")
    # `chat`, not `qwen3`: on the author's gateway the `qwen3` alias thinks
    # through its budget and answers nothing (1 of 9 calls answered,
    # DECISIONS 2026-09-25); the nightly only worked because its script passed
    # the flag. A default that spends a night to produce nothing is no default.
    ap.add_argument("--local-model", default=os.environ.get("VERDICT_LOCAL_MODEL", "chat"),
                    metavar="NAME", help="the model name the gateway serves (default: chat)")
    ap.add_argument("--env-passthrough", action="append", default=[], metavar="NAME[,NAME]",
                    help="environment variables to hand the session beyond the allowlist "
                         "(PATH, HOME, locale, temp, proxies and CAs, CLAUDE_*, ANTHROPIC_*, "
                         "VERDICT_*); also $VERDICT_ENV_PASSTHROUGH")
    ap.add_argument("--mcp-config", action="append", default=[], type=Path, metavar="PATH",
                    help="an MCP config file the session may load; with none, the session "
                         "loads no MCP server at all (--strict-mcp-config is always passed)")
    ap.add_argument("--max-budget-usd", default=os.environ.get("VERDICT_MAX_BUDGET_USD"),
                    metavar="USD", help="a dollar ceiling the CLI enforces on the run "
                                        "(also $VERDICT_MAX_BUDGET_USD)")
    ap.add_argument("--local-limit", type=int, default=6, metavar="N",
                    help="how many files the local engine may read (default 6)")
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
    # `local` and `none` imply the sweep, and neither will ever reach `claude` —
    # so a missing CLI is not this night's problem and must not refuse the run.
    spends_claude = args.on_drift == "model"
    if args.on_drift in ("local", "none"):
        args.skip_unless_drift = True
    asked_preflight(args, ap)
    base_url, token, refused = escalate_preflight(args, ap)
    if refused is not None:
        return refused
    if args.on_drift == "local":
        base_url, token = local_endpoint(args.local_env_file, dict(os.environ))
        if not base_url or not token:
            # Refused before anything runs. A night told to be local and given no
            # endpoint has exactly two honest outcomes, and "quietly spend the
            # expensive model instead" is not one of them.
            print("verdict-run: --on-drift local needs ANTHROPIC_BASE_URL and "
                  "ANTHROPIC_AUTH_TOKEN — in --local-env-file or in the environment. "
                  "Refusing before anything runs: a local night with no endpoint must not "
                  "fall through to a Claude run nobody asked for.", file=sys.stderr)
            return 2
    if spends_claude and shutil.which(args.claude_cmd) is None \
            and not Path(args.claude_cmd).exists():
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
            print("verdict-run: no news — HEAD unchanged, nothing ran")
            return result["exit_code"]

    alive, detail = True, ""
    if args.on_drift == "local":
        # Asked before the sweep, because the answer changes both branches: a
        # sweep that IS allowed says in its own not_tested that the model was
        # unreachable, and a sweep that is blocked has nowhere left to go.
        try:
            from .small import gateway_alive
        except ImportError:  # bare-script execution
            from small import gateway_alive
        alive, detail = gateway_alive(base_url, token)
        print(f"verdict-run: local engine — {detail}", file=sys.stderr)

    if args.skip_unless_drift:
        notes = None if alive else [
            f"the local model was unreachable this run ({detail}), so nothing beyond the "
            "sweep's own measurements was judged — not even the bounded reading a local "
            "delta would have done"]
        code = sweep(repo, qa_root, project, args.fail_on, args.require_harness, before, notes)
        if code is not None:
            return code

    if args.on_drift == "none":
        clear_marker(qa_root)
        print("verdict-run: the sweep was refused and --on-drift none forbids a model run — "
              "nothing was judged and no state was written. The standing verdict is left as "
              "it is, and this exit says the run did not happen.", file=sys.stderr)
        return 5

    if args.on_drift == "local":
        if not alive:
            clear_marker(qa_root)
            print(f"verdict-run: the sweep was refused and the local gateway is down "
                  f"({detail}) — nothing ran and no state was written. A night with no "
                  "judge is a lost night, not a verdict.", file=sys.stderr)
            return 5
        code = run_local(repo, qa_root, args, base_url, token)
        if code != 0:
            print(f"verdict-run: verdict-local exited {code} without finalizing — no state "
                  "was written and no Claude run was started in its place", file=sys.stderr)
            return 5 if code == 5 else code
        result = evaluate(project, args.fail_on, None, before + 1,
                          require_harness=args.require_harness)
        print(f"verdict-run: verdict {result.get('verdict')!r} → exit {result['exit_code']} "
              f"({result['reason']}) · judged locally, no Claude tokens spent")
        if news := news_line(result):
            print(f"verdict-run: {news}")
        if result.get("report"):
            print(f"verdict-run: report {result['report']}")
        return result["exit_code"]

    harness_mode = pin_box_floor(args, qa_root)
    box_mode = tester_box_mode(args, qa_root)
    if not shipped_config_allowed(repo, harness_mode):
        return 2

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

    env = dict(child_env(os.environ, passthrough_names(args)),
               VERDICT_STRICT="1", VERDICT_MODEL=args.model)
    if args.env_file:
        if not args.env_file.is_file():
            print(f"verdict-run: --env-file {args.env_file} does not exist", file=sys.stderr)
            return 2
        env.update(read_env_file(args.env_file))
    env, env_notes = session_env(env, repo)
    env_notes = env_notes + pin_model_aliases(env, args.model)
    if args.sha_range:
        env["VERDICT_RANGE"] = args.sha_range
        env_notes.append(f"gate range: {args.sha_range} (VERDICT_RANGE)")
    for note in env_notes:
        print(f"verdict-run: {note}", file=sys.stderr)
    # A headless session may delegate the tester in the background and end its turn — "I'll
    # report back when it completes". In print mode the CLI then waits 600 s for background
    # tasks and kills them: a tester that needs eleven minutes is terminated at ten with its
    # judgment half-written, no state, exit 5. Measured 2026-09-17, two Sonnet runs of three,
    # and it is the first scheduled night's lost run again (docs/nightly.md). The bound on a
    # run is this runner's own --timeout-s, which kills the process; the CLI's ceiling only
    # ever kills the work. An operator who set their own value keeps it.
    env.setdefault(BG_WAIT_ENV, "0")
    # Two slips the 2026-10-16/17 stranger runs made on their own: a tester's bare `python`
    # wrote 113 .pyc files into a checkout, and `git log -S` on a blob:none clone pulled 22 MB
    # from GitHub. Neither needs the tester to remember anything now.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("GIT_NO_LAZY_FETCH", "1")
    # An asked run gets the assertion-gap census unless the profile says `assertion_gaps: off`
    # (0.91.1): suite time, never model time, and it points the tester at code the suite runs
    # without checking. verdict-facts runs it only when the
    # profile also has coverage_suite_cmd and test_one_cmd.
    env.setdefault(GAPS_DEFAULT_ENV, "on")
    # A dollar ceiling the CLI itself enforces. Budgets were stated in prose
    # and filled, never used (P-49); the flag existed and was never passed
    # (audit 2026-10-02, O-S-9).
    cap, budget, problem = resolve_cap(args, passthrough)
    if problem:
        print(f"verdict-run: {problem}", file=sys.stderr)
        return 2
    # `project,local`: the user-scope plugin stays out (isolation), and the
    # hooks provisioned into settings.local.json come in. `--strict-mcp-config`
    # is the half of "isolation" the setting sources never covered: user-scope
    # MCP servers live in ~/.claude.json, not in settings, and without it a
    # `--dangerously-skip-permissions` night could reach every one of them —
    # mail, deploys, the lab — from the outer session (audit 2026-10-02,
    # O-S-3). Only the servers the operator names with --mcp-config load.
    mcp = [arg for path in args.mcp_config for arg in ("--mcp-config", str(path))]
    strict = [] if "--strict-mcp-config" in passthrough else ["--strict-mcp-config"]
    tester = agent_flags(repo, passthrough)
    told = bool(args.prompt_file or args.prompt)    # the operator's words, in either mode
    box = tester_sandbox(repo, qa_root, env, box_mode)

    packet = ""

    def launch(tester):
        text = tester_prompt(prompt, told, tester, packet,
                             budget_line(cap, args.calls or (escalate.CALLS_DEFAULT if args.lite else None)))
        return [args.claude_cmd, "-p", text, "--model", args.model, *tester,
                "--setting-sources", "project,local", *strict, *mcp, *box, *budget, *passthrough]

    if not args.no_premeasure and not measure_first(repo, qa_root, env, args.sha_range,
                                                    harness_mode):
        return 2
    packet, refused = start_escalation(repo, qa_root, args, env, base_url, token, cap)
    if refused is not None:
        return refused
    cmd = launch(tester)
    attempt = 0
    while attempt < 2:
        attempt += 1
        rc, output = _run_streaming(cmd, repo, env, args.timeout_s)
        if rc and tester and flag_refused(output):
            print("verdict-run: this claude CLI does not know --agent/--effort — the tester is "
                  "asked for in the prompt instead (update Claude Code to run it as the session)",
                  file=sys.stderr)
            tester = []
            cmd = launch(tester)
            attempt -= 1
            continue
        if rc is None:
            print(f"verdict-run: attempt {attempt} timed out after {args.timeout_s}s",
                  file=sys.stderr)
            continue
        if stop := final_stop(output):
            # A weekly limit is days away, and a session stopped at its dollar cap would spend
            # the cap again: either way a second attempt only spends the retry.
            print(stop, file=sys.stderr)
            break
        if _read_run_number(qa_root) > before:
            # A run that wrote its state is finished, whatever its output says. On 2026-10-18 a
            # tester finalized, the CLI then printed a session-limit notice, and the runner slept
            # an hour and paid for a second session that wrote a second run of the same commit.
            break
        wait = seconds_until_reset(output, args.reset_ceiling_s)
        if wait and attempt == 1:
            print(f"verdict-run: session limit; waiting {wait}s for the window to reset",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        if attempt == 1:
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
    if news := news_line(result):
        print(f"verdict-run: {news}")
    if result.get("report"):
        print(f"verdict-run: report {result['report']}")
    print_bill(args, qa_root, before, capped=cap is not None)
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
