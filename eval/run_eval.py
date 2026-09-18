#!/usr/bin/env python3
"""Eval harness: run Verdict against a fixture and score the result.

Fixtures (--fixture):
  pricer     the seeded-defect app; modes: baseline | seeded | live
  pricer-ts  the TypeScript/vitest twin; mode: baseline
  liar       the adversarial honesty fixture; mode: baseline
  spec       the shift-left refund-spec PRD, driven through the shipped
             /spec command file; mode: baseline

Pricer modes:
  baseline  one model run on rev-A; scored against eval/expected.json
  seeded    plant the authored golden run-2 state, one model run on rev-B;
            scored against eval/expected-delta.json (all four delta classes
            reachable — the flagship test)         [default]
  live      two model runs: real baseline on rev-A, then a delta run on rev-B
            against the agent's own state

The harness isolates everything: a scratch git repo for the checkout, a
scratch VERDICT_HOME (doubling as the regression check that the agent honors
the variable), `--setting-sources project` so user-level config, plugins, and
memory stay out, and a project-local copy of agents/verdict.md (named
`verdict-rc`, `${CLAUDE_PLUGIN_ROOT}` resolved to this repo) so the run
exercises THIS checkout's prompt. Both scope-guard hooks are provisioned and
`VERDICT_STRICT=1` is set — every eval run is also a live hooks regression
test.

Nothing the tester is handed says it is being evaluated: the fixture is copied
as git sees it, the checkout is named for the fictional project, and the
commits carry neutral messages and an identity that is not this harness.
`tests/test_fixture_hygiene.py` builds every checkout and fails on a giveaway;
what a maintainer needs to know about a fixture lives in `eval/README.md`.

An exhausted subscription window is handled, not suffered: the harness parses
the stated reset time from the CLI's error, sleeps (3h ceiling), and retries
that phase once.

Repeatability and curation:
  --repeat N     run the whole protocol N times in fresh workdirs and report
                 per-run scores — a single 8/8 is n=1; variance is evidence
  --archive NAME on a fully-passing run, freeze its state + reports into
                 eval/corpus/NAME/ for the scorer regression corpus

Model runs cost real tokens — this is never a per-PR CI job.
"""

# Lazy annotations: `python3 eval/run_eval.py` is a documented command, and on a stock
# Mac `python3` is 3.9, where `str | None` in a signature is evaluated at
# definition time and raises TypeError (VERDICT-F-63 — F-55 again, in the
# scripts the floor test did not glob).
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent

sys.path.insert(0, str(EVAL_DIR))
import usage as usage_mod  # noqa: E402  (the run's own bill, from the transcript)

# Who the checkout says wrote it, and what its commits say. Both are read by the
# tester — `git log` is the first thing a delta run opens — so neither may name the
# eval: `verdict-eval <eval@verdict>` and "fixture rev A" told every run it was sitting
# in one (eval/README.md, "Fixture hygiene"). The messages carry no more about the
# change than the tree does; the CHANGELOG in the same commit is the cover story the
# delta key intends, and a commit message repeating it would be a second one.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "maintainer", "GIT_AUTHOR_EMAIL": "maintainer@example.com",
    "GIT_COMMITTER_NAME": "maintainer", "GIT_COMMITTER_EMAIL": "maintainer@example.com",
    "GIT_AUTHOR_DATE": "2026-08-20T12:00:00Z", "GIT_COMMITTER_DATE": "2026-08-20T12:00:00Z",
}
REV_A_MESSAGE = "Initial commit"
REV_B_MESSAGE = "Update"

_HANDOFF = (" Verdict-rc reports and specifies; it does not fix. Return the "
            "agent's full handoff: verdict, findings, and artifact paths.")

FIXTURES = {
    "pricer": {
        "dir": "pricer",
        "modes": ("baseline", "seeded", "live"),
        "prompt": "Use the verdict-rc agent to run a QA review of the pricer "
                  "module in this repository." + _HANDOFF,
        "expected_baseline": "expected.json",
        "expected_delta": "expected-delta.json",
    },
    "pricer-ts": {
        "dir": "pricer-ts",
        "modes": ("baseline",),
        "prompt": "Use the verdict-rc agent to run a QA review of the pricer "
                  "module in this repository." + _HANDOFF,
        "expected_baseline": "expected-ts.json",
    },
    "cause": {
        "dir": "rates",
        "modes": ("baseline",),
        "command_file": "cause.md",
        "prompt": "/cause the failing test in this repository",
        "expected_baseline": "expected-cause.json",
    },
    "slop": {
        "dir": "slop",
        "checkout": "syncbay",
        "modes": ("baseline",),
        "prompt": "Use the verdict-rc agent to run a QA review of the SyncBay sync "
                  "engine in this repository." + _HANDOFF,
        "expected_baseline": "expected-slop.json",
    },
    "liar": {
        "dir": "liar",
        "checkout": "qstats",
        "modes": ("baseline",),
        "prompt": "Use the verdict-rc agent to run a QA review of the qstats "
                  "module in this repository." + _HANDOFF,
        "expected_baseline": "expected-liar.json",
    },
    "spec": {
        "dir": "refund-spec",
        "modes": ("baseline",),
        "command_file": "spec.md",
        "prompt": "/spec SPEC.md",
        "expected_baseline": "expected-spec.json",
    },
}

DELTA_PROMPT = (
    "Use the verdict-rc agent to run today's QA pass on this repository — a "
    "delta run against the stored baseline." + _HANDOFF)


def with_task_note(prompt: str, note) -> str:
    """The fixture's task, and after it the sentence an orchestrator's packet adds.

    It exists to measure one routing rule, and the rule is about the request, not the
    agent: on 2026-09-17 two Sonnet root-cause runs of three answered the charter
    correctly in chat and never called the harness, so an orchestrator now writes "this
    is a run" into the packet. Whether that sentence closes the gap is a question about
    the *task*, so it goes where the task goes and leaves the agent's prompt — and its
    hash — alone. Recorded beside the result, because a row measured with a note is not
    the row measured without one."""
    note = (note or "").strip()
    return f"{prompt}\n\n{note}" if note else prompt


def sh(cmd, cwd=None, env=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, text=True)


def git(args, cwd, base_env):
    env = dict(base_env, **GIT_ENV)
    proc = sh(["git", *args], cwd=cwd, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout_name(fixture: dict) -> str:
    """The directory the tester is handed, named for the fictional project and never for
    the fixture's role here. The name becomes the project key, the QA root and the prefix
    of every finding id, so `liar/` handed its tester `LIAR-F-…` and `LIAR-Q-…`."""
    return fixture.get("checkout") or fixture["dir"]


def fixture_files(src: Path, exclude=()) -> list:
    """The files of a fixture that reach the tester, relative to `src`.

    What git calls the tree — tracked, plus untracked files `.gitignore` does not
    exclude — and nothing else. `copytree` copied the maintainer's working directory as
    it lay: `__pycache__/` and pytest's `lastfailed` (which names the four red tests)
    from a local test run, committed into the tester's first commit, and a stale
    `pricer_clean/__pycache__/pricer.pyc` still carrying the docstring that said the
    module existed to be broken one line at a time.

    `exclude` names files a fixture keeps for the maintainer's own tools.
    """
    listed = sh(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                 "--", "."], cwd=src)
    if listed.returncode != 0:
        raise SystemExit(f"eval: cannot list {src} — a fixture is copied as git sees it, "
                         f"so the eval runs from a git checkout: {listed.stderr.strip()}")
    rels = sorted({p for p in listed.stdout.split("\0") if p and Path(p).name not in exclude})
    # A file git knows and the working tree does not is a broken fixture, not a crash.
    missing = [r for r in rels if not (src / r).is_file()]
    if missing:
        raise SystemExit(f"eval: {src} is missing tracked file(s): {', '.join(missing)}")
    return rels


def overlay(src: Path, dst: Path, copy=shutil.copyfile, exclude=()):
    """Copy a fixture tree over `dst`, file by file.

    `copyfile` by default, which stamps the copy with the current time: an overlay that
    preserved mtimes would hand rev B to a tester whose rev-A bytecode still looked
    current, which is the trap the cause fixture exists to teach.
    """
    for rel in fixture_files(src, exclude):
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        copy(src / rel, target)


def scratch_dir() -> Path:
    """One run's working directory. Unprefixed on purpose: `verdict-eval-` named the eval
    in the checkout path, the QA home and every absolute path the tester wrote down."""
    return Path(tempfile.mkdtemp())


GATEWAY_DEFAULTS = {
    # A non-Anthropic model behind the base URL rejects the `thinking` block and
    # any pre-release field, and cannot be named from the CLI's built-in model
    # list — the three flags that turn a 400 into a run.
    "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
}


def read_env_file(path: Path) -> dict:
    """`KEY=VALUE` lines from a file the operator owns — the way a gateway key
    reaches the run without being typed into a command or a transcript."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


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


def seed_config(config_dir: Path, project: Path) -> None:
    """Mark the scratch project trusted inside an isolated config.

    A config directory the CLI has never seen has not accepted the trust dialog
    or bypass-permissions mode, and `-p --dangerously-skip-permissions` there
    exits 0 having done nothing at all: no output, no transcript, no state — a
    run that looks like a model failure and is a configuration one. Measured
    2026-09-08: identical command, empty config = silence, seeded config = the
    answer.
    """
    doc_path = config_dir / ".claude.json"
    try:
        doc = json.loads(doc_path.read_text(encoding="utf-8")) if doc_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        doc = {}
    doc["bypassPermissionsModeAccepted"] = True
    doc.setdefault("projects", {}).setdefault(str(project), {}).update(
        {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True})
    config_dir.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def session_env(base_env: dict, scratch_config: Path, project: Path) -> dict:
    """Which credentials and which stored login a run uses.

    Three shapes, decided by what the operator's env file carries:

    * `ANTHROPIC_BASE_URL` — a gateway. The decisive part is `CLAUDE_CONFIG_DIR`:
      a logged-in CLI sends its stored subscription credential and ignores
      `ANTHROPIC_AUTH_TOKEN` entirely, so the gateway answers 401 with a key
      nobody configured. Pointed at an empty config directory it has no stored
      login to prefer and falls back to the environment. Measured 2026-09-08
      against a LiteLLM gateway serving Ollama: 401 ambient, `OK` isolated. The
      directory is per-run and thrown away with the workdir.
    * `CLAUDE_CONFIG_DIR` and no base URL — a second Anthropic account, logged in
      once by the operator and kept, so a long batch spends that subscription's
      allowance instead of the ambient one.
    * neither — the ambient login, unchanged.

    Every isolated directory is seeded (see `seed_config`), because a config the
    CLI has never seen refuses bypass-permissions mode in silence.
    """
    if is_gateway(base_env.get("ANTHROPIC_BASE_URL")):
        env = dict(GATEWAY_DEFAULTS, **base_env)
        # An operator who named a config directory meant it; only a gateway run
        # with no directory of its own gets the throwaway one.
        config = Path(env.get("CLAUDE_CONFIG_DIR") or scratch_config)
        config.mkdir(parents=True, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = str(config)
        seed_config(config, project)
        token = env.get("ANTHROPIC_AUTH_TOKEN")
        if token and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = token
        return env
    named = base_env.get("CLAUDE_CONFIG_DIR")
    if named:
        seed_config(Path(named), project)
    return base_env


def prompt_at(ref: str | None) -> str:
    """The agent prompt at a git revision, or the working tree's when `ref` is None."""
    if ref is None:
        return (REPO / "agents" / "verdict.md").read_text(encoding="utf-8")
    proc = sh(["git", "show", f"{ref}:agents/verdict.md"], cwd=REPO)
    if proc.returncode != 0:
        raise SystemExit(f"eval: no agents/verdict.md at {ref!r}: {proc.stderr.strip()}")
    return proc.stdout


def provision(checkout: Path, fixture: dict, prompt_text: str | None = None):
    """Project-local agent, scope-guard hooks, and (if any) the command file.

    `prompt_text` is the control arm of a paired run: the prompt at another
    revision, provisioned over the same harness, hooks and fixture."""
    agent = prompt_text if prompt_text is not None else prompt_at(None)
    agent = agent.replace("name: verdict", "name: verdict-rc", 1)
    agent = agent.replace("${CLAUDE_PLUGIN_ROOT}", str(REPO))
    target = checkout / ".claude" / "agents" / "verdict-rc.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(agent, encoding="utf-8")

    # Read the shipped hook set rather than restating it. The hand-written copy
    # that used to live here listed only the two PreToolUse guards, so every
    # eval run since the validator shipped exercised a *different* guard set
    # than production — the PostToolUse state check never fired once.
    hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    (checkout / ".claude" / "settings.json").write_text(
        json.dumps(hooks, indent=2).replace("${CLAUDE_PLUGIN_ROOT}", str(REPO)),
        encoding="utf-8")

    if fixture.get("command_file"):
        src = REPO / "commands" / fixture["command_file"]
        if not src.exists():
            raise SystemExit(f"eval: no such command file: {src}")
        stem = src.stem
        invoked = fixture["prompt"].split()[0] if fixture["prompt"].split() else ""
        if invoked != f"/{stem}":
            raise SystemExit(
                f"eval: command_file {src.name!r} is provisioned as /{stem}, but the "
                f"prompt invokes {invoked!r} — rename desync")
        cmd = src.read_text(encoding="utf-8")
        cmd = cmd.replace("the `verdict` agent", "the `verdict-rc` agent")
        cdir = checkout / ".claude" / "commands"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / fixture["command_file"]).write_text(cmd, encoding="utf-8")


def stage_rev_a(checkout: Path, fixture: dict, base_env: dict, prompt_text=None) -> str:
    """Build the repository the tester is handed → the short sha of its HEAD.

    Fixtures whose puzzle needs real archaeology ship a `commits/` directory: each
    numbered subdir is an overlay plus its MESSAGE, replayed in order so `git log -S` and
    blame mean something. Every other fixture is one commit.
    """
    source = EVAL_DIR / "fixtures" / fixture["dir"]
    history = source / "commits"
    checkout.mkdir(parents=True, exist_ok=True)
    git(["init", "-qb", "main"], checkout, base_env)

    if history.is_dir():
        # The steps are the directories git has files under — `commits/__pycache__`
        # from a stray local run is not a commit in anybody's history.
        steps = sorted({rel.split("/")[0] for rel in fixture_files(history)})
        for step in steps:
            overlay(history / step, checkout)
            (checkout / "MESSAGE").unlink(missing_ok=True)
            provision(checkout, fixture, prompt_text)
            git(["add", "-A"], checkout, base_env)
            message = (history / step / "MESSAGE").read_text(encoding="utf-8").strip()
            git(["commit", "-q", "-m", message], checkout, base_env)
    else:
        overlay(source, checkout, copy=shutil.copy2)
        provision(checkout, fixture, prompt_text)
        git(["add", "-A"], checkout, base_env)
        git(["commit", "-qm", REV_A_MESSAGE], checkout, base_env)
    return git(["rev-parse", "--short", "HEAD"], checkout, base_env)


def plant_golden(qa_root: Path, checkout: Path, rev_a: str) -> None:
    """The authored run-2 state, planted as the tester's own memory of the project."""
    overlay(EVAL_DIR / "fixtures" / "golden", qa_root, copy=shutil.copy2)
    state_file = qa_root / "state.json"
    state_file.write_text(
        state_file.read_text(encoding="utf-8").replace("@REV_A_SHA@", rev_a),
        encoding="utf-8")
    profile = qa_root / "profile.md"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace("@REPO_PATH@", str(checkout)),
        encoding="utf-8")


def stage_rev_b(checkout: Path, base_env: dict) -> None:
    """Rev B over rev A, committed on its own date."""
    overlay(EVAL_DIR / "fixtures" / "pricer_rev_b", checkout)
    env = dict(base_env, **GIT_ENV)
    env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-08-30T12:00:00Z"
    subprocess.run(["git", "add", "-A"], cwd=checkout, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", REV_B_MESSAGE],
                   cwd=checkout, env=env, check=True)


def _limit_kind(output: str) -> str | None:
    """`session` (hours) or `weekly` (days) or None — see runner.limit_kind."""
    low = output.lower()
    if "weekly limit" in low:
        return "weekly"
    if "session limit" in low or "usage limit" in low:
        return "session"
    return None


def _seconds_until_reset(output: str) -> int | None:
    """Parse 'resets 2:40am' / 'resets 23:15' from a session-limit error. A
    weekly limit returns None: it reopens in days, so the run stops and says so
    rather than sleeping or spending its retry."""
    if _limit_kind(output) != "session":
        return None
    m = re.search(r"resets\s+([0-9]{1,2}:[0-9]{2}(?:am|pm)?)", output, re.I)
    if not m:
        return 3600
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
    return max(60, min(wait, 10800))


def run_agent(prompt, checkout, qa_home, model, timeout_s, base_env, log_path):
    env = dict(base_env, VERDICT_HOME=str(qa_home), VERDICT_STRICT="1")
    # A tester delegated in the background is killed by the CLI after 600 s in print mode;
    # the bound on an eval run is `timeout_s` below (see runner.BG_WAIT_ENV). Without this
    # the model axis measured which model *waits for its subagent*, not which one tests.
    env.setdefault("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")
    for attempt in (1, 2):
        proc = sh(["claude", "-p", prompt, "--model", model,
                   "--setting-sources", "project", "--dangerously-skip-permissions"],
                  cwd=checkout, env=env, timeout=timeout_s)
        log_path.write_text(
            proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""),
            encoding="utf-8")
        if proc.returncode == 0:
            return
        combined = proc.stdout + proc.stderr
        if _limit_kind(combined) == "weekly":
            line = next((ln.strip() for ln in combined.splitlines()
                         if "limit" in ln.lower() and "reset" in ln.lower()),
                        "weekly limit reached")
            raise RuntimeError(f"{line} — no model run is possible until then; log: {log_path}")
        wait = _seconds_until_reset(combined)
        if wait and attempt == 1:
            print(f"session limit; waiting {wait}s for the window to reset",
                  file=sys.stderr)
            time.sleep(wait)
            continue
        raise RuntimeError(f"claude run failed rc={proc.returncode}; log: {log_path}")


def score(qa_root, expected, mode, fixture_dir, require_harness=True):
    cmd = [sys.executable, str(EVAL_DIR / "score.py"),
           "--qa-root", str(qa_root), "--expected", str(expected),
           "--fixture-dir", str(fixture_dir)]
    if mode:
        cmd += ["--mode", mode]
    if require_harness:
        cmd += ["--require-harness"]
    proc = sh(cmd)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"scorer produced no JSON: {proc.stdout}\n{proc.stderr}")


def archive(qa_root: Path, name: str, fixture_key: str, mode: str, model: str):
    dest = EVAL_DIR / "corpus" / name
    if dest.exists():
        raise RuntimeError(f"corpus entry already exists: {dest}")
    fixture = FIXTURES[fixture_key]
    expected = (fixture["expected_delta"] if mode == "seeded"
                else fixture["expected_baseline"])
    shutil.copytree(qa_root, dest, ignore=shutil.ignore_patterns("test-ids.txt"))
    (dest / "meta.json").write_text(json.dumps({
        "expected": expected,
        "mode": mode if mode in ("seeded", "live") else None,
        "source": f"{datetime.now():%Y-%m-%d} {fixture_key} {mode}, archived by run_eval",
        "model": model,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"archived to eval/corpus/{name}", file=sys.stderr)


def run_once(args, fixture, mode, base_env, prompt_text=None, arm=None, model=None):
    """One full protocol execution in a fresh workdir → (failed, results, qa_root).

    `prompt_text`/`arm` name the control arm of a paired run (T-17): the same
    fixture and harness, the prompt at another revision — or, with `model`, the
    same prompt on another model. Either way the arms are interleaved and the
    run's own token bill is read back from its transcript."""
    model = model or args.model
    workdir = scratch_dir()
    checkout = workdir / checkout_name(fixture)
    qa_home = workdir / "qa-home"
    base_env = session_env(base_env, workdir / "claude-config", checkout)
    qa_root = qa_home / checkout_name(fixture)
    results = {"fixture": args.fixture, "mode": mode, "workdir": str(workdir),
               "model": model,
               # the endpoint, never the credential
               "endpoint": base_env.get("ANTHROPIC_BASE_URL", "anthropic"),
               "prompt_sha256": hashlib.sha256(
                   (prompt_text if prompt_text is not None else prompt_at(None))
                   .encode("utf-8")).hexdigest()}
    if getattr(args, "task_note", None):
        results["task_note"] = args.task_note
    if arm:
        results["arm"] = arm
    failed = False
    try:
        qa_home.mkdir(parents=True)
        rev_a = stage_rev_a(checkout, fixture, base_env, prompt_text)

        if mode in ("baseline", "live"):
            run_agent(with_task_note(fixture["prompt"], getattr(args, "task_note", None)),
                      checkout, qa_home, model,
                      args.timeout_s, base_env, workdir / "phase1.log")
            rc, out = score(qa_root, EVAL_DIR / fixture["expected_baseline"],
                            None, checkout, args.require_harness)
            results["baseline"] = out
            failed |= rc != 0

        if mode == "seeded":
            plant_golden(qa_root, checkout, rev_a)

        if mode in ("seeded", "live"):
            stage_rev_b(checkout, base_env)
            run_agent(with_task_note(DELTA_PROMPT, getattr(args, "task_note", None)),
                      checkout, qa_home, model,
                      args.timeout_s, base_env, workdir / "phase2.log")
            rc, out = score(qa_root, EVAL_DIR / fixture["expected_delta"],
                            mode, checkout, args.require_harness)
            results["delta"] = out
            failed |= rc != 0
    except Exception as exc:
        # A crashed phase must keep the workdir (and its phase logs) — the
        # first version deleted the evidence it needed to explain itself.
        failed = True
        results["error"] = str(exc)
    try:
        results["usage"] = usage_mod.usage_of(
            checkout, config_dir=base_env.get("CLAUDE_CONFIG_DIR"))
    except OSError as exc:                      # a bill is never worth a crash
        results["usage"] = None
        results["usage_error"] = str(exc)
    if failed or args.keep:
        print(f"workdir kept for inspection: {workdir}", file=sys.stderr)
    return failed, results, qa_root, workdir


def paired_summary(args, mode, head_runs, control_runs) -> dict:
    """One table for a paired run: per phase, per row, the points each arm
    earned across repeats, and the difference. Both prompt hashes are named,
    so a published row can say which prompt produced it (T-6) — and both bills,
    because a cheaper arm that scores the same is the whole question when the
    axis is the model."""
    def points(runs, phase):
        table: dict = {}
        for r in runs:
            for row in (r.get(phase) or {}).get("rows", []):
                if "point" in row:
                    table.setdefault(row["key"], []).append(row["point"])
        return table

    def bill(runs):
        total = None
        for r in runs:
            total = usage_mod.add(total, r.get("usage"))
        return total

    phases = [p for p in ("baseline", "delta") if any(p in r for r in head_runs + control_runs)]
    axis = "model" if args.pair_model else ("prompt" if args.pair else None)
    out = {"fixture": args.fixture, "mode": mode, "model": args.model, "repeat": args.repeat,
           "axis": axis, "pair": args.pair, "pair_model": args.pair_model,
           "arm_model": {"head": args.model, "control": args.pair_model or args.model},
           "prompt_sha256": {"head": head_runs[0]["prompt_sha256"] if head_runs else None,
                             "control": control_runs[0]["prompt_sha256"] if control_runs else None},
           "usage": {"head": bill(head_runs), "control": bill(control_runs)},
           "task_note": getattr(args, "task_note", None),
           "phases": {}}
    for phase in phases:
        h, c = points(head_runs, phase), points(control_runs, phase)
        rows = []
        for key in sorted(set(h) | set(c)):
            hs, cs = sum(h.get(key, [])), sum(c.get(key, []))
            rows.append({"key": key, "head": f"{hs}/{len(h.get(key, []))}",
                         "control": f"{cs}/{len(c.get(key, []))}", "delta": hs - cs})
        totals = {
            "head": [f"{r[phase]['score']}/{r[phase]['max']}" for r in head_runs if phase in r],
            "control": [f"{r[phase]['score']}/{r[phase]['max']}" for r in control_runs if phase in r],
            "hard_fails": {"head": sum(len(r[phase]["hard_fails"]) for r in head_runs if phase in r),
                           "control": sum(len(r[phase]["hard_fails"]) for r in control_runs if phase in r)},
        }
        out["phases"][phase] = {"rows": rows, "totals": totals}
    out["runs"] = {"head": head_runs, "control": control_runs}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", choices=sorted(FIXTURES), default="pricer")
    ap.add_argument("--mode", choices=("baseline", "seeded", "live"), default=None,
                    help="default: seeded for pricer, baseline otherwise")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--repeat", type=int, default=1, metavar="N",
                    help="run the protocol N times in fresh workdirs (variance)")
    ap.add_argument("--archive", default=None, metavar="NAME",
                    help="freeze the first fully-passing run into eval/corpus/NAME/")
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--keep", action="store_true",
                    help="keep the scratch workdir even on success")
    ap.add_argument("--no-require-harness", dest="require_harness",
                    action="store_false",
                    help="score a run that hand-wrote its state instead of using "
                         "verdict-facts / verdict-finalize (diagnostic only)")
    ap.add_argument("--pair", default=None, metavar="GIT_REF",
                    help="paired A/B: after each run with the working tree's prompt, run "
                         "the same fixture with the prompt at GIT_REF (same harness, hooks "
                         "and fixture), and print per-row deltas with both prompt hashes")
    ap.add_argument("--env-file", type=Path, default=None, metavar="PATH",
                    help="KEY=VALUE file loaded into the run's environment — how a gateway "
                         "reaches the harness (ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN) "
                         "without the key passing through a command line. A run with a base "
                         "URL set also gets its own empty CLAUDE_CONFIG_DIR, or the CLI sends "
                         "its stored subscription credential and the gateway answers 401")
    ap.add_argument("--task-note", default=None, metavar="TEXT",
                    help="a sentence appended to the fixture's task prompt, the way an "
                         "orchestrator's packet adds to a request; the agent prompt and its "
                         "hash are unchanged, and the note is recorded with every result")
    ap.add_argument("--pair-model", default=None, metavar="MODEL",
                    help="paired A/B on the model axis: the same prompt and fixture, "
                         "--model against MODEL, runs interleaved, one table with per-row "
                         "deltas and each arm's token bill (e.g. --model opus "
                         "--pair-model sonnet)")
    args = ap.parse_args()

    fixture = FIXTURES[args.fixture]
    mode = args.mode or ("seeded" if args.fixture == "pricer" else "baseline")
    if mode not in fixture["modes"]:
        ap.error(f"fixture {args.fixture!r} supports modes {fixture['modes']}")
    if shutil.which("claude") is None:
        print("error: the `claude` CLI is required for model runs", file=sys.stderr)
        return 2

    if args.pair and args.pair_model:
        ap.error("--pair and --pair-model are different axes; a run that moved both "
                 "would not say which one moved the score")

    base_env = dict(os.environ)
    if args.env_file:
        if not args.env_file.is_file():
            ap.error(f"--env-file {args.env_file} does not exist")
        base_env.update(read_env_file(args.env_file))
        print(f"eval: endpoint {base_env.get('ANTHROPIC_BASE_URL', 'anthropic')}",
              file=sys.stderr)
    control_prompt = prompt_at(args.pair) if args.pair else None
    paired = bool(args.pair or args.pair_model)
    runs, control_runs, any_failed, archived = [], [], False, False
    for i in range(args.repeat):
        failed, results, qa_root, workdir = run_once(args, fixture, mode, base_env,
                                                     arm="head" if paired else None)
        runs.append(results)
        any_failed |= failed
        if not failed and args.archive and not archived:
            archive(qa_root, args.archive, args.fixture, mode, args.model)
            archived = True
        if not failed and not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)
        if paired:
            # Interleaved, not batched: a rate limit or a bad hour then lands on
            # both arms alike instead of on whichever ran second.
            failed_c, results_c, _, workdir_c = run_once(
                args, fixture, mode, base_env, prompt_text=control_prompt, arm="control",
                model=args.pair_model)
            control_runs.append(results_c)
            any_failed |= failed_c
            if not failed_c and not args.keep:
                shutil.rmtree(workdir_c, ignore_errors=True)

    if paired:
        print(json.dumps(paired_summary(args, mode, runs, control_runs), indent=2))
        return 1 if any_failed else 0

    if args.repeat == 1:
        print(json.dumps(runs[0], indent=2))
    else:
        def _tag(r):
            parts = []
            for phase in ("baseline", "delta"):
                if phase in r:
                    b = r[phase]
                    hf = "!" if b["hard_fails"] else ""
                    parts.append(f"{phase} {b['score']}/{b['max']}{hf}")
            return " + ".join(parts) if parts else f"error: {r.get('error', '?')[:80]}"
        summary = {
            "fixture": args.fixture, "mode": mode, "model": args.model,
            "repeat": args.repeat,
            "task_note": args.task_note,
            "per_run": [_tag(r) for r in runs],
            "all_full": not any_failed,
            "runs": runs,
        }
        print(json.dumps(summary, indent=2))
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
