"""The tier below the sweep: the local model's endpoint, premeasuring before the tester runs
(with no credential in its environment), the marker that lets a run reuse fresh facts, and the
local run itself.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

try:
    from .runner_env import hidden_names, read_env_file
    from .runner_provision import shipped_config_allowed
    from .gitenv import git_env
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from runner_env import hidden_names, read_env_file
    from runner_provision import shipped_config_allowed
    from gitenv import git_env


# ── the tier below the sweep ──────────────────────────────────────────────
#
# The sweep answers "nothing a finding cites moved". `--on-drift` answers the
# harder half: something DID move, and the owner has decided that a run nobody
# asked for spends no Claude tokens at all. So the night steps down a tier
# instead of reaching for the expensive model — skip, then sweep, then the local
# engine, and if that cannot run, nothing, loudly. What it may never do is fall
# through to `claude` quietly: an unattended run that silently costs money is the
# exact failure this release was measured to close.


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
                          text=True, env=git_env()).stdout.strip()
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
