#!/usr/bin/env python3
"""The project's own code runs in a box, with nothing of the caller's. Stdlib only.

Verdict starts the code under test in eight places:
  * the profile's gates;
  * the test-id collection;
  * one test at a time for fix verification;
  * the coverage run and its render;
  * the census's mutants;
  * a tester's or a model's repro on a fresh tree;
  * the local tier's probes, flake re-runs and its `<runner> run python` question.

When the repository is a stranger's, that is the least trusted code on the machine. Until
0.94.0 it ran as the owner, with everything the owner has. Measured 2026-11-03 under
`verdict-paid`:
  * the caller's environment held `ANTHROPIC_API_KEY`;
  * the network was open;
  * `~/.config/op-agent/service-account.token` and `~/.ssh/id_ed25519` are files any
    process of the owner can read.
A `conftest.py` could have sent all three anywhere.

The box, where the machine has one (macOS `/usr/bin/sandbox-exec`):
  * **No network except loopback, and no DNS.** A name would carry a secret out inside the
    query.
  * **Writes only under the paths the caller names, minus what runs later outside the box.**
    The checkout's `.git` (a hook, `core.fsmonitor`), its `.claude` and `.mcp.json` (what a
    Claude Code session loads) and the QA root stay read-only. A review measured a boxed gate
    planting `.git/hooks/post-checkout` and `.claude/settings.local.json`, and both ran
    outside on the harness's next `git worktree add` and the tester's session.
  * **No reads of the owner's credential stores** (`CREDENTIAL_PATHS`, plaintext `.env`
    files under `~/.config`, the Claude login the caller runs under) or of other projects'
    QA records. The credential stores are denied once more after every read-back, so a
    writable `~` cannot reopen `~/.ssh` (measured).
  * **A private temp dir and uv cache,** a 4 GiB file-size ceiling, and the whole process
    group killed when the run returns.

The environment, everywhere, is built from `KEEP` and the profile's `test_env` names, never
from the caller's. That is not the whole story on macOS. A process can read the start-up
environment of any process of the same user (`sysctl(KERN_PROCARGS2)`, what `ps -E` reads),
and no sandbox rule tried here stopped it (2026-11-03, sbpl-lab). So a secret that a process
alive during the run was *started* with stays readable from inside the box. `verdict-run`
starts its premeasure without one. The Claude CLI's own `ANTHROPIC_API_KEY` is the exception
the box cannot close; the box only denies it the network. For a repository you do not trust,
authenticate the CLI some other way: a subscription login, or an `apiKeyHelper`.

The profile decides (`sandbox:`):
  * **`auto` (unset):** the box where there is one, the allowlisted environment everywhere.
  * **`required`:** no box, nothing runs; the gate is `unavailable` and says why. This is the
    setting for a stranger's repository.
  * **`off`:** the pre-0.94.0 way.

A floor outranks the profile: `VERDICT_SANDBOX`, which `verdict-run --sandbox` sets for every
process it starts. A profile can only tighten it. Under a `required` floor a profile's
`sandbox_network`, `sandbox_write` and `test_env` are ignored: a repository that ships its own
`.qa/` must not loosen the box it is run in (measured: a shipped `profile.md` turned it off).
"""

# Lazy annotations: harness modules import on the interpreter the hooks name (`python3`,
# 3.9 on a stock Mac), where `str | None` would raise at definition time (VERDICT-F-55).
from __future__ import annotations

import locale
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

MODES = ("off", "auto", "required")          # weakest first: a floor compares by this order
FLOOR_ENV = "VERDICT_SANDBOX"
# Set by `verdict-run` on the tester's session, whose Bash it puts in Claude Code's sandbox:
# a harness command run from inside that sandbox finds itself nested, and this says the outer
# box is Verdict's own. Without it a nested harness under `required` refuses (an EPERM from an
# endpoint agent must not pass for a box).
OUTER_ENV = "VERDICT_OUTER_BOX"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"       # never from PATH
ENGINE = "sandbox-exec"
# What target code may see of the caller's environment. Everything else — every token, key,
# login and gateway address the caller holds — is left behind.
KEEP = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "TERM", "TZ", "COLUMNS",
    "NO_COLOR", "FORCE_COLOR", "CI",
    # Python and the tools the harness itself sets or a venv needs. Not UV_INDEX_* nor
    # PIP_INDEX_URL: an index URL can carry a password.
    "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED", "PYTHONIOENCODING",
    "PYTHONUTF8", "VIRTUAL_ENV", "UV_PYTHON", "UV_PROJECT_ENVIRONMENT", "UV_NO_SYNC",
    "UV_OFFLINE", "NODE_ENV",
    # What a Windows CRT needs to start, and where Windows tools look for their caches and
    # programs. Locations, never credentials.
    "SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
})
# Prefixes kept whole: locale, the coverage run's own settings, and the guard variables the
# replay and census set so a fresh tree cannot import the original checkout.
KEEP_PREFIXES = ("LC_", "COVERAGE_", "VERDICT_REPLAY_", "VERDICT_CENSUS_")
# A variable whose name says it holds a credential, and a value that carries one. Used to keep
# `test_env` from naming one, and by the runner for the tester's sandbox.
SECRET_NAME = re.compile(r"(?i)(KEY|TOKEN|SECRET|PASSW|_PASS$|_PWD$|CREDENTIAL|CREDS|AUTH|"
                         r"COOKIE|SESSION|DSN|PRIVATE)")
SECRET_VALUE = re.compile(r"://[^/\s:@]+:[^/\s@]+@")
# Under the owner's home: the stores a credential lives in. A deny-list, so not complete.
CREDENTIAL_PATHS = (
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".netrc", ".git-credentials",
    ".npmrc", ".pypirc", ".password-store", ".op",
    ".config/gh", ".config/gcloud", ".config/op", ".config/op-agent", ".config/op-env",
    ".config/rclone", ".config/sops", ".config/age",
    ".local/share/keyrings",
    "Library/Keychains", "Library/Cookies", "Library/Mobile Documents",
    "Library/Group Containers", "Library/Mail", "Library/Messages",
    ".claude.json", ".claude/.credentials.json", ".claude/settings.json",
    ".claude/settings.local.json", ".claude/projects",
)
# Other projects' QA records and branch records: findings name live defects. Denied, then the
# run's own QA root is read back in.
RECORD_PATHS = (".claude/verdict", ".claude/verdict-branches")
SECRET_PATHS = CREDENTIAL_PATHS + RECORD_PATHS
# A plaintext env file under ~/.config is how this machine's unattended jobs hold keys
# (the gateway's, the Telegram bot's): `(regex)` because their names are not known here.
SECRET_REGEXES = (r"/\.config/.*\.env$", r"/\.config/[^/]*\.env\..*$")
# What git and Claude Code run later, outside any box, from inside a checkout.
GUARDED_NAMES = (".git", ".claude", ".mcp.json")
FILE_SIZE_LIMIT = 4 * 1024 ** 3     # 4 GiB: far above a test artefact, far below a full disk
DEVICES = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/dtracehelper")
# The harness's own git, made deaf to what a repository's `.git/config` asks it to run.
GIT_DEFENCES = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"))


def _rank(mode: str) -> int:
    return MODES.index(mode) if mode in MODES else MODES.index("auto")


def floor_from_env(source=None) -> str | None:
    value = str((source if source is not None else os.environ).get(FLOOR_ENV) or "").strip()
    return value if value in MODES else None


def _home(source=None) -> Path:
    src = os.environ if source is None else source
    return Path(src.get("HOME") or Path.home())


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


class Policy:
    """What the profile said, held to the floor, as the runs take it."""

    def __init__(self, mode: str = "auto", network_gates=(), write=(), env_names=(),
                 qa_root=None, floor: str | None = None, notes: list | None = None):
        notes = notes if notes is not None else []
        mode = mode if mode in MODES else "auto"
        if floor in MODES and _rank(mode) < _rank(floor):
            notes.append(f"sandbox: the profile's `{mode}` is below the floor `{floor}` this run "
                         f"was started with — `{floor}`")
            mode = floor
        loosening = bool(network_gates or write or env_names)
        if floor == "required" and loosening:
            notes.append("sandbox: under a `required` floor the profile's sandbox_network, "
                         "sandbox_write and test_env are ignored")
            network_gates, write, env_names = (), (), ()
        refused = [n for n in env_names if SECRET_NAME.search(str(n))]
        if refused:
            notes.append("test_env: names that look like credentials are never passed: "
                         + ", ".join(sorted(refused)))
        home = Path(os.path.realpath(str(_home())))
        stores = [home / p for p in CREDENTIAL_PATHS]
        kept_write = []
        for raw in write:
            p = Path(os.path.realpath(str(Path(raw).expanduser())))
            if _inside(home, p) or any(_inside(s, p) or _inside(p, s) for s in stores):
                notes.append(f"sandbox_write: '{raw}' would reach a credential store — ignored")
            else:
                kept_write.append(p)
        self.mode = mode
        self.floor = floor
        self.network_gates = frozenset(network_gates)
        self.write = tuple(kept_write)
        self.env_names = frozenset(n for n in env_names if not SECRET_NAME.search(str(n)))
        self.qa_root = Path(qa_root).expanduser() if qa_root else None

    def as_fact(self) -> dict:
        """The line facts.json carries: what boxed the target's code on this run."""
        if self.mode == "off":
            how = ("off — the profile says `sandbox: off`; target code ran with the caller's "
                   "environment, network and files")
        elif available() and nested():
            how = ("the caller's sandbox — this process already runs inside one, which macOS "
                   "will not stack; the allowlisted environment on top"
                   + ("" if os.environ.get(OUTER_ENV) else
                      " (not one verdict-run set up: under `required` nothing runs)"))
        elif available():
            how = ENGINE
        elif self.mode == "auto":
            how = "none on this machine — target code ran with the allowlisted environment only"
        else:
            how = "none on this machine — `sandbox: required`, so target code did not run"
        fact = {"mode": self.mode, "box": how,
                "environment": "caller's" if self.mode == "off" else "allowlisted"}
        if self.floor:
            fact["floor"] = self.floor
        if self.network_gates:
            fact["network_gates"] = sorted(self.network_gates)
        if self.write:
            fact["extra_write"] = [str(p) for p in self.write]
        if self.env_names:
            fact["test_env"] = sorted(self.env_names)
        return fact


def policy_from(settings: dict, qa_root=None, notes: list | None = None,
                floor: str | None = None) -> Policy:
    """A Policy from the profile's settings (`profile.sandbox_from`), held to the floor —
    `floor`, else `VERDICT_SANDBOX` in this process's environment."""
    return Policy(**settings, qa_root=qa_root, floor=floor or floor_from_env(), notes=notes)


_POLICY = Policy()


def harden_git(env) -> None:
    """Add `GIT_DEFENCES` to `env` as `GIT_CONFIG_*` entries (git 2.31+): every git the harness
    starts then runs no hook and no fsmonitor a repository's `.git/config` names. Target code
    never inherits them; its environment is the allowlist."""
    count = int(env.get("GIT_CONFIG_COUNT") or 0)
    have = {env.get(f"GIT_CONFIG_KEY_{i}") for i in range(count)}
    for key, value in GIT_DEFENCES:
        if key in have:
            continue
        env[f"GIT_CONFIG_KEY_{count}"] = key
        env[f"GIT_CONFIG_VALUE_{count}"] = value
        count += 1
    env["GIT_CONFIG_COUNT"] = str(count)


def configure(policy: Policy | None) -> Policy:
    """Set the policy the runs in this process follow; None restores the default (`auto`). The
    harness's own git is hardened on the way (`harden_git`)."""
    global _POLICY
    _POLICY = policy if policy is not None else Policy(floor=floor_from_env())
    harden_git(os.environ)
    return _POLICY


def current() -> Policy:
    return _POLICY


def from_profile(qa_root, notes: list | None = None) -> Policy:
    """The policy `<qa-root>/profile.md` sets, held to the floor. An unreadable profile keeps
    the default, on."""
    try:
        from .profile import ProfileError, load, sandbox_from
    except ImportError:  # executed as a bare script
        from profile import ProfileError, load, sandbox_from
    notes = notes if notes is not None else []
    try:
        config, _ = load(qa_root)
    except ProfileError:
        config = {}
    return policy_from(sandbox_from(config, notes), qa_root, notes)


def available() -> bool:
    """Whether this machine can box a process: macOS with `/usr/bin/sandbox-exec`."""
    return sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


_NESTED: list = []


def nested() -> bool:
    """Whether this process already runs inside a sandbox, which macOS will not stack.

    Measured 2026-11-03: `sandbox-exec` inside `sandbox-exec` exits 71 with
    "sandbox_apply: Operation not permitted". A tester session runs its Bash inside Claude
    Code's own sandbox (`runner.tester_sandbox`), so a harness command the tester runs from
    there would refuse every gate. There the outer sandbox is the box, if `OUTER_ENV` says
    verdict-run set it up. Asked once per process."""
    if not _NESTED:
        inside = False
        if available():
            try:
                probe = subprocess.run([SANDBOX_EXEC, "-p", "(version 1)(allow default)",
                                        "/usr/bin/true"], capture_output=True, text=True,
                                       timeout=20)
                inside = probe.returncode != 0 and "not permitted" in probe.stderr
            except (OSError, subprocess.SubprocessError):
                inside = False
        _NESTED.append(inside)
    return _NESTED[0]


def environment(extra: dict | None = None, *, names=(), source=None) -> dict:
    """The environment target code gets: `KEEP`, the kept prefixes and `names` taken from
    `source` (the caller's environment by default), then `extra` on top."""
    src = os.environ if source is None else source
    wanted = {n for n in names if not SECRET_NAME.search(str(n))}
    env = {k: v for k, v in src.items()
           if k in KEEP or k.startswith(KEEP_PREFIXES) or k in wanted}
    if extra:
        env.update({k: str(v) for k, v in extra.items() if v is not None})
    return env


def _quote(path) -> str:
    """A path as an SBPL string literal."""
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _real(path) -> str:
    """The resolved path: SBPL matches the real path, and `/var` is `/private/var` here."""
    try:
        return os.path.realpath(str(Path(path).expanduser()))
    except OSError:
        return str(path)


def _regex_escape(text: str) -> str:
    """A literal path for an SBPL `#"…"` regex: backslash every regex metacharacter."""
    return "".join("\\" + c if c in r".^$*+?()[]{}|\\" else c for c in text)


def secret_paths(home=None, source=None, *, records: bool = True) -> list[str]:
    """The credential stores under `home` and the Claude login the caller runs under, and,
    with `records`, other projects' QA records."""
    src = os.environ if source is None else source
    base = Path(home or _home(src))
    paths = [_real(base / p) for p in (SECRET_PATHS if records else CREDENTIAL_PATHS)]
    config_dir = src.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        paths.append(_real(config_dir))
    return paths


def profile(writable, *, network: bool = False, loopback: bool = True, read_back=(),
            guarded=(), no_write=(), home=None, source=None) -> str:
    """The SBPL text for one run. Later rules win, so each allowance is followed by what it
    must not reopen.

    `writable` may be written; inside each of `guarded` (the checkouts), `.git`, `.claude` and
    `.mcp.json` may not; nothing under `no_write` (the QA root) may be. The credential stores
    are denied, `read_back` and the writable paths read back in, and the credential stores
    denied once more."""
    rules = ["(version 1)", "(allow default)"]
    if not network:
        rules.append("(deny network*)")
        if loopback:
            # Loopback in the three directions a local test server needs. A broader
            # `(allow network* (local ip "localhost:*"))` let a TCP connection to 1.1.1.1
            # through (measured 2026-11-03, sbpl-lab), so outbound is matched on the remote end.
            rules += ['(allow network-outbound (remote ip "localhost:*"))',
                      '(allow network-bind (local ip "localhost:*"))',
                      '(allow network-inbound (local ip "localhost:*"))']
    rules.append('(deny file-write* (subpath "/"))')
    allowed = " ".join(f"(subpath {_quote(_real(p))})" for p in writable if p)
    devices = " ".join(f"(literal {_quote(d)})" for d in DEVICES)
    rules.append(f"(allow file-write* {allowed} {devices} (regex #\"^/dev/fd/\"))")
    kept = []
    for checkout in guarded:
        for name in GUARDED_NAMES:
            target = _quote(_real(Path(checkout) / name))
            kept += [f"(literal {target})", f"(subpath {target})"]
    kept += [f"(subpath {_quote(_real(p))})" for p in no_write if p]
    if kept:
        rules.append("(deny file-write* " + " ".join(kept) + ")")
    base = _regex_escape(_real(home or _home(source)))
    regexes = " ".join(f'(regex #"^{base}{r}")' for r in SECRET_REGEXES)
    stores = " ".join(f"(subpath {_quote(p)})" for p in secret_paths(home, source))
    rules.append(f"(deny file-read* {stores} {regexes})")
    back = [p for p in (*read_back, *writable) if p]
    if back:
        rules.append("(allow file-read* " + " ".join(f"(subpath {_quote(_real(p))})"
                                                    for p in back) + ")")
        # Once more, after the read-back: a writable `~` must not reopen `~/.ssh`.
        creds = " ".join(f"(subpath {_quote(p)})"
                         for p in secret_paths(home, source, records=False))
        rules.append(f"(deny file-read* {creds} {regexes})")
    return "".join(rules)


def _limit():
    """Run in the child before exec: the file-size ceiling and no core files."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_SIZE_LIMIT, FILE_SIZE_LIMIT))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass


def _killpg(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, AttributeError):
        pass


def _call(argv, *, cwd, env, shell: bool, timeout, text=True, errors="replace",
          **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` with two differences. The run is in a session of its own, and every
    process in it is killed when the run returns. Its output goes to files, not pipes.

    A daemon a gate starts must not outlive the gate: a review measured one reading the
    environment of a process started after the gate returned. With pipes, such a daemon also
    holds them open, so `communicate` waits for it — until the timeout, and a gate has none
    (measured here: a background `sleep` held a run for its full minute). Only the run's own
    process is waited for."""
    posix = os.name == "posix"
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(argv, cwd=cwd, env=env, shell=shell, stdout=out, stderr=err,
                                **({"start_new_session": True, "preexec_fn": _limit}
                                   if posix else {}), **kwargs)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
        finally:
            if posix:
                _killpg(proc.pid)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(), err.read()
    if text:
        # What `text=True` did: the locale's encoding (cp1252 on a Windows runner, where a child
        # prints an em dash as 0x97) and universal newlines (a `stdout_contains "[]\nFalse"`
        # expectation must match `[]\r\nFalse`).
        encoding = locale.getpreferredencoding(False)
        stdout, stderr = (s.decode(encoding, errors=errors).replace("\r\n", "\n").replace("\r", "\n")
                          for s in (stdout, stderr))
    if timed_out:
        raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)


def _checkouts(where) -> list:
    """The git checkouts among the writable paths and their immediate children: a fresh tree
    is `<scratch>/tree`, and its `.git` must stay as read-only as the repository's."""
    found = []
    for p in map(Path, where):
        if (p / ".git").exists():
            found.append(p)
        try:
            found += [c for c in p.iterdir() if c.is_dir() and (c / ".git").exists()]
        except OSError:
            pass
    return found


def _refused(cmd, reason: str, text: bool) -> subprocess.CompletedProcess:
    proc = subprocess.CompletedProcess(cmd, 126, "" if text else b"",
                                       reason if text else reason.encode())
    proc.sandbox = "refused"
    return proc


def run(cmd, *, cwd, shell: bool = False, writable=(), guarded=None, extra_env: dict | None = None,
        network: bool = False, loopback: bool = True, read_back=(), timeout=None,
        policy: Policy | None = None, base_env: dict | None = None, force_box: bool = False,
        **kwargs) -> subprocess.CompletedProcess:
    """Run target code as the policy says and return the CompletedProcess.

    Arguments:
      * `cmd`: what `subprocess.run` would take, a shell string with `shell=True`, else an
        argv. Inside the box a shell string runs as `/bin/sh -c`, so pipes and `&&` keep
        working.
      * `writable`: where the run may write, besides its private temp dir. The working
        directory is not added: a repro whose cwd is the QA root must not rewrite the profile.
      * `guarded`: the checkouts whose `.git`, `.claude` and `.mcp.json` stay read-only. The
        default is every writable path that holds a `.git`.
      * `extra_env`: set over the allowlisted environment.
      * `base_env`: the environment to filter in place of the caller's. A caller with a
        stricter allowlist of its own passes it, and keeps it under `sandbox: off` too.
      * `force_box`: the code is a model's. It runs boxed or not at all, whatever the policy.
      * `loopback=False`: not even loopback.

    The result carries `.sandbox`, a word on what ran: `sandbox-exec`, `outer`, `env-only`,
    `off` or `refused`. A refusal is exit 126 with the reason on stderr, which the harness
    reads as could-not-start.
    """
    pol = policy or _POLICY
    text = kwargs.pop("text", True)
    kwargs.pop("capture_output", None)
    mode = "required" if force_box else pol.mode
    if mode == "off":
        env = dict(os.environ if base_env is None else base_env)
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items() if v is not None})
        proc = subprocess.run(cmd, cwd=cwd, shell=shell, env=env, timeout=timeout,
                              capture_output=True, text=text, **kwargs)
        proc.sandbox = "off"
        return proc
    box = available()
    inner = box and nested()
    if mode == "required" and not box:
        return _refused(cmd, "verdict: not run — `sandbox: required` and this machine has no "
                             "sandbox (macOS sandbox-exec); target code runs only inside one", text)
    if mode == "required" and inner and not os.environ.get(OUTER_ENV):
        return _refused(cmd, "verdict: not run — `sandbox: required`, and this process already "
                             "runs inside a sandbox verdict-run did not set up", text)
    tmp = Path(tempfile.mkdtemp(prefix="verdict-box-"))
    try:
        own_cache = not any(_inside(p, Path(_real("~/.cache/uv"))) or
                            _inside(Path(_real("~/.cache/uv")), p) for p in pol.write)
        env = environment({"TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp),
                           **({"UV_CACHE_DIR": str(tmp / "uv-cache")} if own_cache else {}),
                           **(extra_env or {})}, names=pol.env_names, source=base_env)
        if not box or inner:
            proc = _call(cmd, cwd=cwd, env=env, shell=shell, timeout=timeout, text=text, **kwargs)
            proc.args = cmd
            proc.sandbox = "outer" if inner else "env-only"
            return proc
        where = [p for p in (*writable, tmp, *pol.write) if p]
        checkouts = _checkouts(where) if guarded is None else list(guarded)
        back = [p for p in (pol.qa_root, *read_back) if p]
        sbpl = profile(where, network=network, loopback=loopback, read_back=back,
                       guarded=checkouts, no_write=[pol.qa_root] if pol.qa_root else [])
        argv = ([SANDBOX_EXEC, "-p", sbpl, "/bin/sh", "-c", cmd] if shell
                else [SANDBOX_EXEC, "-p", sbpl, *([cmd] if isinstance(cmd, str) else cmd)])
        proc = _call(argv, cwd=cwd, env=env, shell=False, timeout=timeout, text=text, **kwargs)
        proc.args = cmd
        proc.sandbox = ENGINE
        return proc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
