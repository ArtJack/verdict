"""Provisioning a run: the plugin root, the tester's config and sandbox, what the shipped
config may allow, the box floor, and the record of what was provisioned.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    from . import sandbox
    from .runner_env import env_files, hidden_names
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sandbox
    from runner_env import env_files, hidden_names


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
