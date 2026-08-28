#!/usr/bin/env python3
"""Eval harness: run Verdict against the pricer fixtures and score the result.

Modes:
  baseline  one model run on rev-A; scored against eval/expected.json
  seeded    plant the authored golden run-2 state, one model run on rev-B;
            scored against eval/expected-delta.json (all four delta classes
            reachable — the flagship test)         [default]
  live      two model runs: real baseline on rev-A, then a delta run on rev-B
            against the agent's own state; phase 1 scored with the baseline
            key, phase 2 with the delta key (REGRESSED rows n/a)

The harness isolates everything: a scratch git repo for the checkout, a
scratch VERDICT_HOME for state (which doubles as a regression check that the
agent honors the variable), `--setting-sources project` so user-level config,
plugins, and memory stay out, and a project-local copy of agents/verdict.md
(named `verdict-rc`, `${CLAUDE_PLUGIN_ROOT}` resolved to this repo) so the run
exercises THIS checkout's prompt, not an installed plugin.

Model runs cost real tokens — this is never a per-PR CI job.

Usage:
  python3 eval/run_eval.py [--mode seeded|live|baseline] [--model opus]
                           [--keep] [--timeout-s 1800]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent

GIT_ENV = {
    "GIT_AUTHOR_NAME": "verdict-eval", "GIT_AUTHOR_EMAIL": "eval@verdict",
    "GIT_COMMITTER_NAME": "verdict-eval", "GIT_COMMITTER_EMAIL": "eval@verdict",
    "GIT_AUTHOR_DATE": "2026-08-20T12:00:00Z", "GIT_COMMITTER_DATE": "2026-08-20T12:00:00Z",
}

BASELINE_PROMPT = (
    "Use the verdict-rc agent to run a QA review of the pricer module in this "
    "repository. Verdict-rc reports and specifies; it does not fix. Return the "
    "agent's full handoff: verdict, findings, and artifact paths.")
DELTA_PROMPT = (
    "Use the verdict-rc agent to run today's QA pass on this repository — a "
    "delta run against the stored baseline. Verdict-rc reports and specifies; "
    "it does not fix. Return the agent's full handoff.")


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


def provision_agent(checkout: Path):
    agent = (REPO / "agents" / "verdict.md").read_text(encoding="utf-8")
    agent = agent.replace("name: verdict", "name: verdict-rc", 1)
    agent = agent.replace("${CLAUDE_PLUGIN_ROOT}", str(REPO))
    target = checkout / ".claude" / "agents" / "verdict-rc.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(agent, encoding="utf-8")


def run_agent(prompt, checkout, qa_home, model, timeout_s, base_env, log_path):
    env = dict(base_env, VERDICT_HOME=str(qa_home))
    proc = sh(["claude", "-p", prompt, "--model", model,
               "--setting-sources", "project", "--dangerously-skip-permissions"],
              cwd=checkout, env=env, timeout=timeout_s)
    log_path.write_text(proc.stdout + ("\n--- stderr ---\n" + proc.stderr if proc.stderr else ""), encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"claude run failed rc={proc.returncode}; log: {log_path}")


def score(qa_root, expected, mode, fixture_dir):
    cmd = [sys.executable, str(EVAL_DIR / "score.py"),
           "--qa-root", str(qa_root), "--expected", str(expected),
           "--fixture-dir", str(fixture_dir)]
    if mode:
        cmd += ["--mode", mode]
    proc = sh(cmd)
    try:
        return proc.returncode, json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"scorer produced no JSON: {proc.stdout}\n{proc.stderr}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("baseline", "seeded", "live"), default="seeded")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--keep", action="store_true",
                    help="keep the scratch workdir even on success")
    args = ap.parse_args()

    if shutil.which("claude") is None:
        print("error: the `claude` CLI is required for model runs", file=sys.stderr)
        return 2

    base_env = dict(os.environ)
    workdir = Path(tempfile.mkdtemp(prefix="verdict-eval-"))
    checkout, qa_home = workdir / "pricer", workdir / "qa-home"
    qa_root = qa_home / "pricer"
    results, failed = {"mode": args.mode, "workdir": str(workdir)}, False
    try:
        shutil.copytree(EVAL_DIR / "fixtures" / "pricer", checkout)
        provision_agent(checkout)
        qa_home.mkdir(parents=True)
        git(["init", "-qb", "main"], checkout, base_env)
        git(["add", "-A"], checkout, base_env)
        git(["commit", "-qm", "fixture rev A"], checkout, base_env)
        rev_a = git(["rev-parse", "--short", "HEAD"], checkout, base_env)

        if args.mode in ("baseline", "live"):
            run_agent(BASELINE_PROMPT, checkout, qa_home, args.model,
                      args.timeout_s, base_env, workdir / "phase1.log")
            rc, out = score(qa_root, EVAL_DIR / "expected.json", None, checkout)
            results["baseline"] = out
            failed |= rc != 0

        if args.mode == "seeded":
            shutil.copytree(EVAL_DIR / "fixtures" / "golden", qa_root)
            state_file = qa_root / "state.json"
            state_file.write_text(
                state_file.read_text(encoding="utf-8").replace("@REV_A_SHA@", rev_a),
                encoding="utf-8")
            profile = qa_root / "profile.md"
            profile.write_text(
                profile.read_text(encoding="utf-8").replace("@FIXTURE_DIR@", str(checkout)),
                encoding="utf-8")

        if args.mode in ("seeded", "live"):
            overlay(EVAL_DIR / "fixtures" / "pricer_rev_b", checkout)
            env = dict(base_env, **GIT_ENV)
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "2026-08-30T12:00:00Z"
            subprocess.run(["git", "add", "-A"], cwd=checkout, env=env, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture rev B"],
                           cwd=checkout, env=env, check=True)
            run_agent(DELTA_PROMPT, checkout, qa_home, args.model,
                      args.timeout_s, base_env, workdir / "phase2.log")
            rc, out = score(qa_root, EVAL_DIR / "expected-delta.json",
                            args.mode, checkout)
            results["delta"] = out
            failed |= rc != 0
    except Exception as exc:
        # A crashed phase must keep the workdir (and its phase logs) — the
        # first version deleted the evidence it needed to explain itself.
        failed = True
        results["error"] = str(exc)
    finally:
        print(json.dumps(results, indent=2))
        if failed or args.keep:
            print(f"workdir kept for inspection: {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
