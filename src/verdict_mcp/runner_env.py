"""The environment a run starts with: the gateway and its flags, an env file read without
showing its values, model aliases pinned, and what a child process keeps or loses.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    from . import sandbox
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sandbox


# `0` = wait for background tasks indefinitely (the CLI's own wording on stderr).
BG_WAIT_ENV = "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"


GAPS_DEFAULT_ENV = "VERDICT_ASSERTION_GAPS"


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


# The aliases a main session can hand the Agent tool. Named here so a run launched on one
# model stays on it: twice (2026-10-04, 2026-10-11) the main session read "asked = Sonnet" in
# an old packet and spawned the tester with `model: sonnet` under `--model opus`.
_ALIAS_ENV = ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL")


def pin_model_aliases(env: dict, model: str) -> list:
    """When `--model` names a model by its id (`claude-opus-5-5`), point the `opus` and
    `sonnet` aliases at it too, so a subagent spawned with either alias runs on the model
    the operator chose → notes. An alias given as `--model` cannot be pinned (the runner
    does not know what it resolves to), and an alias the operator set is theirs."""
    if not str(model).startswith("claude-"):
        return []
    pinned = [name for name in _ALIAS_ENV if not env.get(name)]
    for name in pinned:
        env[name] = model
    return [f"model aliases pinned to {model}: {', '.join(pinned)}"] if pinned else []


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


# Where the CLI looks for bash when the session's PATH has none.
BASH_FALLBACKS = ("/bin/bash", "/usr/bin/bash")


def tester_shell(env: dict, which=shutil.which, fallbacks=BASH_FALLBACKS) -> list:
    """Run the tester's Bash tool in bash when the login shell is another one → notes.

    The CLI runs every Bash call in `CLAUDE_CODE_SHELL` if that is set, else in the login
    `SHELL`, and on a Mac that is zsh. The tester writes bash. zsh reads a word that starts
    with `=` as a lookup of the command it names, so `cat a; echo =====; cat b` stops at the
    separator with "==== not found": `b` is never printed and the call exits 1 with half its
    output. An asked run on 2026-11-17 lost the second half of 3 of its first 53 calls that way,
    one of them a file the packet had told it to read. bash is also the shell the Bash guard
    assumes: it reads each command with POSIX rules, and zsh's `=cmd` and `=(…)` expansions
    are not among them.

    An operator who set `CLAUDE_CODE_SHELL` keeps it. A login shell that is bash needs nothing.
    With no bash anywhere, the CLI's own choice stands and the note says so. On Windows the CLI
    picks its own bash, and this does nothing.
    """
    if os.name == "nt":
        return []
    if env.get("CLAUDE_CODE_SHELL"):
        return [f"shell: CLAUDE_CODE_SHELL={env['CLAUDE_CODE_SHELL']} (the operator's)"]
    login = env.get("SHELL") or ""
    if os.path.basename(login) == "bash":
        return []
    bash = which("bash", path=env.get("PATH")) or next(
        (p for p in fallbacks if os.path.isfile(p) and os.access(p, os.X_OK)), None)
    if not bash:
        return [f"shell: no bash found, so the tester's Bash runs {login or 'the CLI default'}; "
                "zsh drops the rest of a command line at a word like `=====`"]
    env["CLAUDE_CODE_SHELL"] = bash
    return [f"shell: the tester's Bash runs {bash}, not the login shell "
            f"{login or '(unset)'} (CLAUDE_CODE_SHELL)"]


# The environment a headless session may see. Everything else the operator's
# shell holds stays out — cloud and `gh`/`op` tokens, a `GIT_DIR` exported by
# a git hook, the `PYTHONPATH` 0.90.1 stopped leaking — because the session
# hands its environment to every Bash call the tester makes, hence to the
# project's own test suite and whatever that spawns (audit 2026-10-02, O-S-2).
# The owner's hand recipe for asked gates was `env -i` with exactly these
# names; the runner does it itself now. `--env-passthrough` is the door for a
# project whose gates need one more.
_ENV_KEEP = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LANGUAGE", "TMPDIR", "TEMP",
    "TMP", "TERM", "COLORTERM", "TZ",
    # Windows needs these to run anything at all.
    "SYSTEMROOT", "SystemRoot", "COMSPEC", "ComSpec", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PROGRAMDATA", "ProgramData",
    "WINDIR", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES", "ALLUSERSPROFILE",
    "PUBLIC", "USERNAME", "USERDOMAIN", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
    # A corporate proxy or a private CA is how the CLI reaches the API.
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
})


_ENV_KEEP_PREFIXES = ("LC_", "CLAUDE_", "ANTHROPIC_", "VERDICT_", "XDG_")


def child_env(source, passthrough=()) -> dict:
    """The allowlisted subset of `source`, plus the names in `passthrough`."""
    # `.union`, not `|`: the hooks' interpreter-floor test reads a `|` between two
    # expressions as a 3.10 type union, and this file shares that floor.
    keep = set(_ENV_KEEP).union(name.strip() for name in passthrough if name and name.strip())
    return {k: v for k, v in source.items()
            if k in keep or k.startswith(_ENV_KEEP_PREFIXES)}


def env_files(home=None) -> list:
    """The plaintext `.env` files under `~/.config`, one level down too. Claude Code's `denyRead`
    takes paths, not globs, and this machine's unattended jobs keep their keys in such files
    (`verdict-gateway.env`, `oracle-watch.env`)."""
    base = Path(home or os.environ.get("HOME") or Path.home()) / ".config"
    found = []
    for pattern in ("*.env", "*.env.*", "*/*.env", "*/*.env.*"):
        try:
            found += [str(p) for p in base.glob(pattern) if p.is_file()]
        except OSError:
            pass
    return sorted(set(found))


def hidden_names(env: dict) -> list:
    """The variables the tester's Bash never sees: a name like a credential's, or a value that
    carries one (`scheme://user:password@host`). The CLI that needs `ANTHROPIC_API_KEY` to
    answer still has it."""
    return sorted(n for n, v in env.items()
                  if sandbox.SECRET_NAME.search(n) or sandbox.SECRET_VALUE.search(str(v)))


def passthrough_names(args) -> list:
    """`--env-passthrough A,B` (repeatable) and `$VERDICT_ENV_PASSTHROUGH`, split."""
    raw = [*(args.env_passthrough or []), os.environ.get("VERDICT_ENV_PASSTHROUGH", "")]
    return [name.strip() for chunk in raw for name in chunk.split(",") if name.strip()]
