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

import argparse
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

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent

GIT_ENV = {
    "GIT_AUTHOR_NAME": "verdict-eval", "GIT_AUTHOR_EMAIL": "eval@verdict",
    "GIT_COMMITTER_NAME": "verdict-eval", "GIT_COMMITTER_EMAIL": "eval@verdict",
    "GIT_AUTHOR_DATE": "2026-08-20T12:00:00Z", "GIT_COMMITTER_DATE": "2026-08-20T12:00:00Z",
}

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
        "modes": ("baseline",),
        "prompt": "Use the verdict-rc agent to run a QA review of the SyncBay sync "
                  "engine in this repository." + _HANDOFF,
        "expected_baseline": "expected-slop.json",
    },
    "liar": {
        "dir": "liar",
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


def sh(cmd, cwd=None, env=None, timeout=None):
    return subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout,
                          capture_output=True, text=True)


def git(args, cwd, base_env):
    env = dict(base_env, **GIT_ENV)
    proc = sh(["git", *args], cwd=cwd, env=env)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def overlay(src: Path, dst: Path):
    for p in src.rglob("*"):
        if p.is_file():
            target = dst / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)


def provision(checkout: Path, fixture: dict):
    """Project-local agent, scope-guard hooks, and (if any) the command file."""
    agent = (REPO / "agents" / "verdict.md").read_text(encoding="utf-8")
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
        if not fixture["prompt"].startswith(f"/{stem}"):
            raise SystemExit(
                f"eval: command_file {src.name!r} is provisioned as /{stem}, but the "
                f"prompt invokes {fixture['prompt'].split()[0]!r} — rename desync")
        cmd = src.read_text(encoding="utf-8")
        cmd = cmd.replace("the `verdict` agent", "the `verdict-rc` agent")
        cdir = checkout / ".claude" / "commands"
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / fixture["command_file"]).write_text(cmd, encoding="utf-8")


def _seconds_until_reset(output: str) -> int | None:
    """Parse 'resets 2:40am' / 'resets 23:15' from a session-limit error."""
    if "session limit" not in output.lower():
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
    for attempt in (1, 2):
        proc = sh(["claude", "-p", prompt, "--model", model,
                   "--setting-sources", "project", "--dangerously-skip-permissions"],
                  cwd=checkout, env=env, timeout=timeout_s)
        log_path.write_text(
            proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""),
            encoding="utf-8")
        if proc.returncode == 0:
            return
        wait = _seconds_until_reset(proc.stdout + proc.stderr)
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


def run_once(args, fixture, mode, base_env):
    """One full protocol execution in a fresh workdir → (failed, results, qa_root)."""
    workdir = Path(tempfile.mkdtemp(prefix="verdict-eval-"))
    checkout = workdir / fixture["dir"]
    qa_home = workdir / "qa-home"
    qa_root = qa_home / fixture["dir"]
    results = {"fixture": args.fixture, "mode": mode, "workdir": str(workdir)}
    failed = False
    try:
        source = EVAL_DIR / "fixtures" / fixture["dir"]
        history = source / "commits"
        checkout.mkdir(parents=True)
        qa_home.mkdir(parents=True)
        git(["init", "-qb", "main"], checkout, base_env)

        if history.is_dir():
            # Fixtures whose puzzle needs real archaeology ship a commits/
            # directory: each numbered subdir is an overlay plus its MESSAGE,
            # replayed in order so `git log -S` and blame mean something.
            for step in sorted(p for p in history.iterdir() if p.is_dir()):
                overlay(step, checkout)
                (checkout / "MESSAGE").unlink(missing_ok=True)
                provision(checkout, fixture)
                git(["add", "-A"], checkout, base_env)
                message = (step / "MESSAGE").read_text(encoding="utf-8").strip()
                git(["commit", "-q", "-m", message], checkout, base_env)
        else:
            shutil.copytree(source, checkout, dirs_exist_ok=True)
            provision(checkout, fixture)
            git(["add", "-A"], checkout, base_env)
            git(["commit", "-qm", "fixture rev A"], checkout, base_env)
        rev_a = git(["rev-parse", "--short", "HEAD"], checkout, base_env)

        if mode in ("baseline", "live"):
            run_agent(fixture["prompt"], checkout, qa_home, args.model,
                      args.timeout_s, base_env, workdir / "phase1.log")
            rc, out = score(qa_root, EVAL_DIR / fixture["expected_baseline"],
                            None, checkout, args.require_harness)
            results["baseline"] = out
            failed |= rc != 0

        if mode == "seeded":
            shutil.copytree(EVAL_DIR / "fixtures" / "golden", qa_root)
            state_file = qa_root / "state.json"
            state_file.write_text(
                state_file.read_text(encoding="utf-8").replace("@REV_A_SHA@", rev_a),
                encoding="utf-8")
            profile = qa_root / "profile.md"
            profile.write_text(
                profile.read_text(encoding="utf-8").replace("@FIXTURE_DIR@", str(checkout)),
                encoding="utf-8")

        if mode in ("seeded", "live"):
            overlay(EVAL_DIR / "fixtures" / "pricer_rev_b", checkout)
            env = dict(base_env, **GIT_ENV)
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-08-30T12:00:00Z"
            subprocess.run(["git", "add", "-A"], cwd=checkout, env=env, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture rev B"],
                           cwd=checkout, env=env, check=True)
            run_agent(DELTA_PROMPT, checkout, qa_home, args.model,
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
    if failed or args.keep:
        print(f"workdir kept for inspection: {workdir}", file=sys.stderr)
    return failed, results, qa_root, workdir


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
    args = ap.parse_args()

    fixture = FIXTURES[args.fixture]
    mode = args.mode or ("seeded" if args.fixture == "pricer" else "baseline")
    if mode not in fixture["modes"]:
        ap.error(f"fixture {args.fixture!r} supports modes {fixture['modes']}")
    if shutil.which("claude") is None:
        print("error: the `claude` CLI is required for model runs", file=sys.stderr)
        return 2

    base_env = dict(os.environ)
    runs, any_failed, archived = [], False, False
    for i in range(args.repeat):
        failed, results, qa_root, workdir = run_once(args, fixture, mode, base_env)
        runs.append(results)
        any_failed |= failed
        if not failed and args.archive and not archived:
            archive(qa_root, args.archive, args.fixture, mode, args.model)
            archived = True
        if not failed and not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

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
            "per_run": [_tag(r) for r in runs],
            "all_full": not any_failed,
            "runs": runs,
        }
        print(json.dumps(summary, indent=2))
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
