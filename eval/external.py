#!/usr/bin/env python3
"""The money-and-security key: defects their own maintainers fixed, gated where they came in.

swebench.py asks a tester where the defect behind a bug report lives. This key asks the
question a merge gate exists for: handed the change that introduced a defect, would the gate
have stopped it? Each instance is a defect in a public Python library, fixed by its
maintainers with a regression test and chosen by rule (the instance files and the rejection
logs sit side by side under the work directory). Per instance:

  1. the repository at the fix's parent (base), history ending there — later commits,
     branches and tags absent, as swebench.py does it — at a neutral path named for the
     project, on a branch named `main`;
  2. a QA venv built inside a throwaway container (`qa-container`): network only for the
     one-time install and none for any run, so a stranger's suite never executes on the host;
  3. the environment proven before the tester arrives: the withheld tests fail at base with
     the fix's tests applied and pass with the whole fix — applied in place, then reverted;
  4. the charter: a release-risk gate on the introducing commit (`intro^..intro`), the profile
     naming the project's risk class (money or security) the way its owner would;
  5. findings scored against the fix's location exactly as swebench.py scores them (file /
     hunk / function at base), the headline apart from any finding — and beside it the gate's
     verdict, because a gate that locates the defect and still says `pass` let it ship.

The control arm runs the same gate through plain Claude Code: same checkout, container,
model, budget and timeout. Both arms pin the model aliases, so a model the main session
passes to a subagent cannot move the tester (Phase 0, 2026-10-11), and both record whether
the provider's safety filter stopped the run.

Usage, on the eval host (docker, `qa-container`, a logged-in claude CLI, a plugin root):
  python3 eval/external.py prepare <id>                  # checkout, venv, validation; no model
  python3 eval/external.py run <id> [--arm verdict|plain]
  python3 eval/external.py batch [--kind money|security] [--limit N]   # both arms, resumable
  python3 eval/external.py table [--kind money|security]

Model runs cost real tokens; this is never a CI job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))
import swebench as sb  # noqa: E402  (the location scorer, the plain arm's parser, the bill)

WORK = Path(os.environ.get("EXTERNAL_WORK") or "/srv/data/AI/artjeck/eval/phase1")
# What the tester sees is named for the project and nothing else: the checkout, its QA root
# and the container wrapper all sit at paths that say neither "eval" nor an instance id.
SRC = Path(os.environ.get("QA_SRC") or Path.home() / "src")
QA_HOME = Path(os.environ.get("QA_HOME") or Path.home() / "qa")
CONTAINER = os.environ.get("QA_CONTAINER") or str(Path.home() / "src" / "bin" / "qa-container")
PLUGIN = Path(os.environ.get("QA_PLUGIN_ROOT") or Path.home() / "src" / "verdict")
MODEL = "opus"
MODEL_ID = "claude-opus-5-5"
# Both aliases resolve to the measured model: a `model: sonnet` the main session hands the
# Agent tool lands on Opus anyway (it did so on 2026-10-04 and 2026-10-11).
MODEL_PINS = {"ANTHROPIC_DEFAULT_OPUS_MODEL": MODEL_ID, "ANTHROPIC_DEFAULT_SONNET_MODEL": MODEL_ID}
ARMS = ("verdict", "plain")
BUDGET_USD = {"verdict": 8.0, "plain": 4.0}
TIMEOUT_S = {"verdict": 3600, "plain": 1800}
WRONG_MODEL_CHECK_S = 180     # when the watcher reads the tester's model off its transcript
VENV = ".venv-qa"
EXCLUDES = (f"{VENV}/", ".qa-home/", ".claude/")
# The project's own settings deny what the container exists to contain: installing a
# stranger's dependencies on the host, fetching from the network, and docker run by hand
# around the wrapper. Deny rules hold under --dangerously-skip-permissions, compound
# commands included (measured on CLI 2.1.289, 2026-10-11). Both arms read the same file.
DENY = ["Bash(pip install:*)", "Bash(pip3 install:*)", "Bash(python -m pip install:*)",
        "Bash(python3 -m pip install:*)", "Bash(uv pip install:*)", "Bash(uv add:*)",
        "Bash(uv sync:*)", "Bash(poetry install:*)", "Bash(conda install:*)",
        "Bash(apt:*)", "Bash(apt-get:*)", "Bash(sudo:*)", "Bash(docker:*)",
        "Bash(curl:*)", "Bash(wget:*)", "Bash(git clone:*)", "Bash(git fetch:*)",
        "Bash(git pull:*)", "Bash(git push:*)"]
_VERDICT_PROVISION = ("agents", "commands", "settings.local.json", "verdict-provision.json")
_TEST_PARTS = {"test", "tests", "testing"}
_TEST_FILE = re.compile(r"(^test_.*\.py$|.*_test\.py$|^conftest\.py$)")

RISK = {
    "money": ("Applications use it to compute amounts they book, bill, report or pay out. A "
              "wrong amount, rounding, currency or double-applied operation is a defect that "
              "ships into every dependant's ledger."),
    "security": ("Applications use it to authenticate, authorize, sign or sanitize. A gap in it "
                 "is an exposure in every application that depends on it."),
}
RISK_CLASS = {"money": "MONEY", "security": "SECURITY"}

HEADLESS = (
    "Use the verdict agent to run a release-risk gate on this repository. Run the agent to "
    "completion IN THIS SESSION: do not spawn it in the background, and do not end your turn "
    "until its state file and report are written — there is no \"later\" in a headless run. "
    "Verdict reports and specifies; it does not fix. Relay the agent's handoff verbatim and "
    "add nothing of your own.")

PACKET = """\
{headless}

Pass the agent this packet unchanged:

This is a run: start with verdict-facts, end with verdict-finalize; an answer without state is not accepted.

**Goal.** Release-risk gate for the change `{intro7}` ("{subject}") in `{name}`: is `git diff {intro7}^..{intro7}` safe to ship to production? Return a verdict (pass / pass with risks / fail / blocked) with a "not tested" list.

**Context.** `{repo}` is a public Python library. {risk} The change is one commit; review it as the pull request it was. This checkout's HEAD (`{base7}`) is later than the change, and the change's code is still in the tree at HEAD: judge it there too.

**Artifacts.** Checkout: `{checkout}`. Scope = `git diff {intro7}^..{intro7}`.

**Environment.**
- QA ROOT FOR THIS RUN = `{qa_root}/` (it holds only the profile). Write state only under that root.
- The project's code runs only inside its container, as the profile's gates do: `{container} {python} <tree> -- '<command>'` mounts `<tree>` at `/w` with no network. The project's venv is `{venv}` in the tree; the host's python has none of its dependencies.

**Constraints.**
- Budget: standard gate, ≤ 40 tool calls.
- Do not open Verdict's own docs or harness source.
- Read-only on the checkout: scratch copies and probes go outside it, run through the same container wrapper.
- Do not install anything, anywhere.

**Requested output.** After verdict-finalize has written state, reply with:
1. the verdict and run number;
2. findings ranked by severity with file:line;
3. the not-tested list;
4. the gate commands you ran and their results.

Under 400 words.
"""

PLAIN = """\
You are reviewing a change to {repo} before it ships. The change is commit {intro7} ("{subject}"): see it with `git show {intro7}`. This checkout's HEAD ({base7}) is later than the change, and the change's code is still in the tree at HEAD: judge it there too. {risk}

The project's code runs only inside its container, with no network: `{container} {python} <tree> -- '<command>'` mounts <tree> at /w. The project's virtualenv is `{venv}` in the tree, and its tests run with `{test_command}`. Do not install anything. Do not fix anything and do not modify any file in the repository; put scratch copies and scratch files under {scratch_dir}.

Decide whether this change is safe to ship. Your final answer starts with one line, `VERDICT: ship` or `VERDICT: do not ship`, and ends with one JSON block listing each defect you found in the change, most important first:
```json
[{{"title": "...", "severity": "Blocker|Critical|Major|Minor|Trivial", "file": "path/relative/to/the/repository", "line": 123, "mechanism": "what the code does wrong, in one or two sentences"}}]
```
"""

_VERDICT_LINE = re.compile(r"(?mi)^\W*VERDICT:\s*(do not ship|ship)\b")


def sh(cmd, cwd=None, env=None, timeout=None, check=False, text_input=None):
    proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True,
                          text=True, errors="replace", input=text_input)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed ({proc.returncode}): "
                           f"{(proc.stderr or proc.stdout).strip()[:400]}")
    return proc


def git(args, cwd, check=True, text_input=None):
    return sh(["git", *args], cwd=cwd, check=check, text_input=text_input)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── instances ─────────────────────────────────────────────────────────────────

def load_instances(work: Path | None = None) -> list[dict]:
    """Every selected instance, money first: `instances-<kind>.json` under the work dir."""
    work = work or WORK
    out: list[dict] = []
    for kind in ("money", "security"):
        path = work / f"instances-{kind}.json"
        if path.is_file():
            for inst in json.loads(path.read_text(encoding="utf-8")):
                inst.setdefault("kind", kind)
                out.append(inst)
    return out


def instance(inst_id: str, work: Path | None = None) -> dict:
    for inst in load_instances(work):
        if inst["id"] == inst_id:
            return inst
    raise SystemExit(f"external: no instance {inst_id!r}")


def name_of(inst: dict) -> str:
    """The checkout's name: the project's own, lowercased — never the instance id, which
    names a fix that does not exist yet in the tester's world."""
    name = inst["repo"].split("/")[-1].lower()
    return re.sub(r"[^a-z0-9.-]+", "-", name).strip("-.") or "project"


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    return any(p in _TEST_PARTS for p in parts[:-1]) or bool(_TEST_FILE.match(parts[-1]))


# ── the checkout ──────────────────────────────────────────────────────────────

def mirror_of(inst: dict, work: Path | None = None) -> Path:
    """The selection step's clone, bare or not; a fresh mirror when there is none."""
    work = work or WORK
    stem = inst["repo"].replace("/", "__")
    for cand in (work / "mirrors" / stem, work / "mirrors" / f"{stem}.git"):
        if cand.is_dir():
            return cand
    dest = work / "mirrors" / f"{stem}.git"
    dest.parent.mkdir(parents=True, exist_ok=True)
    sh(["git", "clone", "-q", "--mirror", f"https://github.com/{inst['repo']}.git", str(dest)],
       check=True)
    return dest


def checkout_at(mirror: Path, base: str, dest: Path) -> None:
    """swebench.checkout_base, on a branch named `main`: history ends at base, later
    commits, branches and tags are physically absent, the alternates link is cut."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sh(["git", "clone", "-q", "--shared", "--no-checkout", str(mirror), str(dest)], check=True)
    git(["checkout", "-q", "-B", "main", base], dest)
    git(["remote", "remove", "origin"], dest)
    for ref in git(["for-each-ref", "--format=%(refname)"], dest).stdout.splitlines():
        if not ref or ref == "refs/heads/main":
            continue
        if ref.startswith("refs/tags/") and sh(
                ["git", "merge-base", "--is-ancestor", ref, "main"], cwd=dest).returncode == 0:
            continue
        git(["update-ref", "-d", ref], dest)
    git(["reflog", "expire", "--expire=now", "--all"], dest)
    git(["repack", "-a", "-d", "-q"], dest)
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    if alternates.exists():
        alternates.unlink()
    git(["prune"], dest)
    git(["fsck", "--no-progress", "--connectivity-only"], dest)
    exclude = dest / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as fh:
        fh.write("".join(f"{line}\n" for line in EXCLUDES))
    settings = dest / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"permissions": {"deny": DENY}}, indent=2) + "\n",
                        encoding="utf-8")


def fix_patches(mirror: Path, base: str, fix: str) -> tuple[str, str, list[str], list[str]]:
    """(test patch, source patch, test files, source files) of the fix, read from the mirror."""
    names = git(["diff", "--name-only", base, fix], mirror).stdout.split()
    tests = [n for n in names if is_test_path(n)]
    source = [n for n in names if not is_test_path(n)]
    test_patch = git(["diff", base, fix, "--", *tests], mirror).stdout if tests else ""
    src_patch = git(["diff", base, fix, "--", *source], mirror).stdout if source else ""
    return test_patch, src_patch, tests, source


def container(inst: dict, tree: Path, command: str, net: bool = False, timeout=None):
    argv = [CONTAINER, str(inst["python"]), str(tree)] + (["--net"] if net else []) + ["--", command]
    return sh(argv, timeout=timeout)


def pytest_cmd(extra: str = "") -> str:
    return f"{VENV}/bin/python -m pytest -q -p no:cacheprovider{(' ' + extra) if extra else ''}"


def run_withheld(inst: dict, checkout: Path) -> tuple[dict[str, str], str]:
    """Outcomes of the withheld tests, from their files' `-rA` summary (swebench.py's reading:
    parametrized ids with spaces are not passed on the command line)."""
    files = sorted({t.split("::")[0] for t in inst["withheld_tests"]})
    proc = container(inst, checkout, pytest_cmd("-rA " + " ".join(shlex.quote(f) for f in files)),
                     timeout=900)
    output = proc.stdout + proc.stderr
    return sb.outcomes_from(output), output


def validate(inst: dict, checkout: Path, test_patch: str, src_patch: str) -> tuple[bool, str]:
    """Fail at base with the fix's tests, pass with the whole fix; the tree left as found."""
    notes = []
    try:
        git(["apply", "--whitespace=nowarn", "-"], checkout, text_input=test_patch)
        at_base, out1 = run_withheld(inst, checkout)
        failing = [t for t in inst["withheld_tests"]
                   if sb.status_of(at_base, t) in ("FAILED", "ERROR")]
        if not failing:
            return False, f"no withheld test fails at base: {at_base}\n{out1[-1500:]}"
        notes.append(f"fail at base: {len(failing)}/{len(inst['withheld_tests'])}")
        git(["apply", "--whitespace=nowarn", "-"], checkout, text_input=src_patch)
        at_fix, out2 = run_withheld(inst, checkout)
        unfixed = [t for t in inst["withheld_tests"] if sb.status_of(at_fix, t) != "PASSED"]
        if unfixed:
            return False, f"not passing with the fix: {unfixed}\n{out2[-1500:]}"
        notes.append("pass with the fix")
        git(["apply", "-R", "--whitespace=nowarn", "-"], checkout, text_input=src_patch)
    finally:
        sh(["git", "apply", "-R", "--whitespace=nowarn", "-"], cwd=checkout, text_input=test_patch)
        restore(checkout)
    dirt = porcelain(checkout)
    if dirt:
        return False, f"validation left the tree dirty: {dirt}"
    return True, "; ".join(notes)


def restore(checkout: Path) -> None:
    """Tracked files as committed and untracked ones gone — the venv, its HOME and the
    build's byproducts survive, because `.git/info/exclude` names them."""
    sh(["git", "checkout", "-q", "--", "."], cwd=checkout)
    sh(["git", "clean", "-fdq"], cwd=checkout)


def exclude_untracked(checkout: Path) -> list[str]:
    """What an editable build wrote into the tree (`*.egg-info`, `build/`, a generated
    version file), added to `.git/info/exclude`: the tester's isolation check reads a clean
    tree as clean, and these were there before it arrived."""
    out = git(["status", "--porcelain", "--untracked-files=normal"], checkout).stdout
    extra = [ln[3:].strip() for ln in out.splitlines() if ln.startswith("?? ")]
    if extra:
        with (checkout / ".git" / "info" / "exclude").open("a", encoding="utf-8") as fh:
            fh.write("".join(f"/{path}\n" for path in extra))
    return extra


def porcelain(checkout: Path) -> list[str]:
    return [ln for ln in git(["status", "--porcelain"], checkout).stdout.splitlines() if ln.strip()]


def profile_text(inst: dict, key: str, checkout: Path) -> str:
    c, py = CONTAINER, inst["python"]
    run = f"{c} {py} {checkout} --"
    kind = inst["kind"]
    suite, ids, one_id = pytest_cmd(), pytest_cmd("--collect-only"), pytest_cmd('"{id}"')
    security_pass = "enabled" if kind == "security" else "disabled"
    repo, risk, risk_class = inst["repo"], RISK[kind], RISK_CLASS[kind]
    return f"""---
gates:
  suite: {run} '{suite}'
test_ids_cmd: {run} '{ids}'
test_one_cmd: {run} '{one_id}'
---

# QA Profile — {key}

Project-Key: {key}
Repo-Path: {checkout}
Repo-Remote: https://github.com/{repo}.git
Security-Pass: {security_pass}
Schema-Version: 1

## What this project is

`{repo}`, a public Python library. {risk}

Risk class: **{risk_class}**.

## History

This checkout's history ends at HEAD. There are no later commits, branches or tags.

## Isolation rules

- The project's code runs only inside its container: `{c} {py} <tree> -- '<command>'` mounts
  `<tree>` at `/w`, with no network, and runs `<command>` there. The QA venv is pre-built at
  `<tree>/{VENV}` (the project installed, with pytest) and works only through that wrapper;
  the host's python has none of the project's dependencies. Do **not** install anything,
  anywhere, and do not run `pip`.
- Counterfactuals and probes go in a scratch copy of the whole tree ({VENV} included), run
  through the same wrapper with the copy's path. Every pytest invocation carries
  `-p no:cacheprovider`; the wrapper sets `PYTHONDONTWRITEBYTECODE`.
- Isolation check each run: `git status --porcelain` before and after the gates. Anything but
  a clean tree (modulo a pre-existing `?? .claude/`) is an unintended write — report it.

## Real commands

- The suite gate above is the project's own pytest suite, one interpreter (Python {py}), in a
  container. CI ran a matrix; this run covers one cell.
- No lint, type or coverage gate is enforced here.
"""


def short(sha: str) -> str:
    return str(sha)[:7]


def packet_text(inst: dict, checkout: Path, qa_root: Path) -> str:
    return PACKET.format(
        headless=HEADLESS, intro7=short(inst["introducing_commit"]),
        subject=str(inst.get("intro_subject") or "").replace('"', "'"), name=name_of(inst),
        repo=inst["repo"], risk=RISK[inst["kind"]], base7=short(inst["base_commit"]),
        checkout=checkout, qa_root=qa_root, container=CONTAINER, python=inst["python"], venv=VENV)


def plain_prompt(inst: dict, checkout: Path, scratch: Path) -> str:
    return PLAIN.format(
        repo=inst["repo"], intro7=short(inst["introducing_commit"]),
        subject=str(inst.get("intro_subject") or "").replace('"', "'"),
        base7=short(inst["base_commit"]), risk=RISK[inst["kind"]], container=CONTAINER,
        python=inst["python"], venv=VENV,
        test_command=f"{CONTAINER} {inst['python']} {checkout} -- '{pytest_cmd()}'",
        scratch_dir=scratch)


def prepare(inst: dict, work: Path | None = None) -> dict:
    """A fresh checkout, its container venv and the proof that the instance is what it
    claims — no model. Returns everything a run needs."""
    work = work or WORK
    name = name_of(inst)
    checkout, qa_root = SRC / name, QA_HOME / name
    if qa_root.exists():
        shutil.rmtree(qa_root)
    mirror = mirror_of(inst, work)
    for sha in (inst["base_commit"], inst["fix_commit"], inst["introducing_commit"]):
        if sh(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=mirror).returncode != 0:
            raise RuntimeError(f"{sha} is not in {mirror}")
    test_patch, src_patch, tests, source = fix_patches(
        mirror, inst["base_commit"], inst["fix_commit"])
    if not tests or not source:
        raise RuntimeError(f"the fix touches tests={tests} source={source}; need both")
    checkout_at(mirror, inst["base_commit"], checkout)
    built = container(inst, checkout, inst["install"], net=True, timeout=1800)
    if built.returncode != 0:
        raise RuntimeError(f"venv build failed: {(built.stderr or built.stdout)[-800:]}")
    byproducts = exclude_untracked(checkout)
    changed = porcelain(checkout)
    if changed:
        raise RuntimeError(f"the build changed tracked files: {changed}")
    ok, note = validate(inst, checkout, test_patch, src_patch)
    if not ok:
        raise RuntimeError(f"validation: {note}")
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "profile.md").write_text(profile_text(inst, name, checkout), encoding="utf-8")
    return {"id": inst["id"], "name": name, "checkout": str(checkout), "qa_root": str(qa_root),
            "gold_hunks": sb.gold_of(src_patch), "fix_files": source, "validation": note,
            "build_byproducts": byproducts, "mirror": str(mirror)}


# ── a run ─────────────────────────────────────────────────────────────────────

def _project_dir(cwd: Path, config_dir=None) -> Path:
    root = Path(config_dir) if config_dir else Path.home() / ".claude"
    return root / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))


def transcripts_of(cwd: Path, session_id, config_dir=None) -> list[Path]:
    if not session_id:
        return []
    proj = _project_dir(cwd, config_dir)
    main = proj / f"{session_id}.jsonl"
    subs = sorted((proj / str(session_id) / "subagents").glob("*.jsonl"))
    return ([main] if main.is_file() else []) + subs


def models_and_refusals(paths: list[Path]) -> tuple[dict, dict, int]:
    """Per-request models and efforts of every transcript, and how many responses the
    provider's safety filter stopped (`stop_reason: refusal`)."""
    models: dict[str, int] = {}
    efforts: dict[str, int] = {}
    refusals = 0
    for path in paths:
        seen = set()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            if rec.get("type") != "assistant" or not msg:
                continue
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            if msg.get("model"):
                models[msg["model"]] = models.get(msg["model"], 0) + 1
            effort = rec.get("effort") or (msg.get("effort") if isinstance(msg, dict) else None)
            if effort:
                efforts[str(effort)] = efforts.get(str(effort), 0) + 1
            if msg.get("stop_reason") == "refusal":
                refusals += 1
    return models, efforts, refusals


def tester_models(cwd: Path, since: float) -> dict:
    """The models the subagents written under `cwd` since `since` (epoch) ran on."""
    proj = _project_dir(cwd)
    paths = [p for p in sorted(proj.glob("*/subagents/*.jsonl")) if p.stat().st_mtime >= since] \
        if proj.is_dir() else []
    return models_and_refusals(paths)[0]


def arm_env(qa_home: Path | None = None) -> dict:
    env = dict(os.environ, **MODEL_PINS)
    env["PATH"] = f"{PLUGIN / '.venv' / 'bin'}:{env.get('PATH', '')}"
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    if qa_home is not None:
        env["VERDICT_HOME"] = str(qa_home)
    return env


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def watch(cmd, cwd: Path, env: dict, log: Path, timeout_s: int, stop_on=()) -> dict:
    """Run `cmd` in its own process group, its output to `log`. Stops it — and says why — on
    a line in `stop_on` (verdict-run's second paid attempt), on the timeout, or when the
    tester's transcript shows a model other than the one being measured."""
    started, wall_start = time.monotonic(), time.time()
    checked_model = False
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT,
                                text=True, start_new_session=True)
        stopped = None
        while proc.poll() is None:
            time.sleep(10)
            elapsed = time.monotonic() - started
            text = log.read_text(encoding="utf-8", errors="replace")
            if any(s in text for s in stop_on):
                stopped = "second attempt stopped"
            elif elapsed > timeout_s + 120:
                stopped = "timeout"
            elif not checked_model and elapsed > WRONG_MODEL_CHECK_S:
                models = tester_models(cwd, wall_start)
                if models:
                    checked_model = True
                    if any(m != MODEL_ID for m in models):
                        stopped = f"wrong model: {models}"
            if stopped:
                _kill(proc)
                proc.wait(timeout=60)
                break
    return {"exit": proc.returncode, "wall_s": round(time.monotonic() - started),
            "stopped": stopped, "output": log.read_text(encoding="utf-8", errors="replace")}


def verdict_of_plain(text: str) -> str | None:
    m = _VERDICT_LINE.search(str(text or ""))
    return m.group(1).lower() if m else None


def blocks(arm: str, verdict) -> bool | None:
    """Whether the gate stopped the change: Verdict's `fail`, the control's `do not ship`."""
    if verdict is None:
        return None
    return verdict == "fail" if arm == "verdict" else verdict == "do not ship"


def run_arm(inst: dict, info: dict, arm: str, work: Path | None = None) -> dict:
    work = work or WORK
    checkout, qa_root = Path(info["checkout"]), Path(info["qa_root"])
    out_dir = work / "runs" / inst["id"] / arm
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    row = {"id": inst["id"], "kind": inst["kind"], "repo": inst["repo"], "arm": arm,
           "model": MODEL_ID, "started": now_utc(), "validation": info.get("validation")}
    if arm == "verdict":
        packet = out_dir / "packet.md"
        packet.write_text(packet_text(inst, checkout, qa_root), encoding="utf-8")
        cmd = [str(PLUGIN / ".venv" / "bin" / "verdict-run"), info["name"], "--repo",
               str(checkout), "--plugin-root", str(PLUGIN), "--prompt-file", str(packet),
               "--model", MODEL, "--timeout-s", str(TIMEOUT_S[arm]),
               "--max-budget-usd", str(BUDGET_USD[arm]), "--", "--output-format", "json"]
        ran = watch(cmd, checkout, arm_env(qa_root.parent), out_dir / "run.log",
                    TIMEOUT_S[arm], stop_on=("retrying once",))
        res = sb.result_line(ran["output"])
        scored = sb.score_instance({"gold_hunks": info["gold_hunks"]}, qa_root,
                                   sb.checkout_source(checkout))
        gate = sh([str(PLUGIN / ".venv" / "bin" / "verdict-gate"), info["name"],
                   "--require-harness", "--min-run-number", "1"],
                  env=arm_env(qa_root.parent)).returncode
        if qa_root.is_dir():
            shutil.copytree(qa_root, out_dir / "qa-root", dirs_exist_ok=True)
        row.update(verdict=scored.get("verdict"), gate_exit=gate,
                   prompt_sha256=scored.get("prompt_sha256"))
    else:
        for name in _VERDICT_PROVISION:        # the control never sees Verdict's agent
            target = checkout / ".claude" / name
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        scratch = QA_HOME / f"{info['name']}-scratch"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir(parents=True)
        prompt = plain_prompt(inst, checkout, scratch)
        (out_dir / "prompt.md").write_text(prompt, encoding="utf-8")
        env, notes = sb.plain_env(arm_env(), None, checkout)
        cmd = sb.plain_argv(prompt, MODEL) + ["--max-budget-usd", str(BUDGET_USD[arm])]
        ran = watch(cmd, checkout, env, out_dir / "run.log", TIMEOUT_S[arm])
        res = sb.result_line(ran["output"])
        answer_text = str(res.get("result") or "")
        (out_dir / "answer.md").write_text(answer_text, encoding="utf-8")
        items = sb.parse_answer(answer_text)
        findings = sb.plain_findings(items or [])
        scored = sb.score_findings(info["gold_hunks"], findings, sb.checkout_source(checkout))
        shutil.rmtree(scratch, ignore_errors=True)
        row.update(verdict=verdict_of_plain(answer_text), answer_parsed=items is not None,
                   env_notes=notes)
    paths = transcripts_of(checkout, res.get("session_id"))
    models, efforts, refusals = models_and_refusals(paths)
    usage = sb.transcript_usage(checkout, res.get("session_id"))
    row.update(
        any_hit=scored.get("any_hit"), headline_hit=scored.get("headline_hit"),
        findings=scored.get("findings"), per_finding=scored.get("per_finding"),
        blocks=blocks(arm, row.get("verdict")), runner_exit=ran["exit"], stopped=ran["stopped"],
        wall_s=ran["wall_s"], cost_usd=res.get("total_cost_usd"), usage=usage, models=models,
        efforts=efforts, refusals=refusals, session_id=res.get("session_id"),
        dirty_after=porcelain(checkout), finished=now_utc())
    return row


# ── the ledger ────────────────────────────────────────────────────────────────

def results_path(arm: str, work: Path | None = None) -> Path:
    return (work or WORK) / f"results-{arm}.jsonl"


def done_ids(arm: str, work: Path | None = None) -> set[str]:
    path = results_path(arm, work)
    if not path.is_file():
        return set()
    return {json.loads(ln)["id"] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}


def append_result(row: dict, work: Path | None = None) -> None:
    path = results_path(row["arm"], work)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def load_results(arm: str, work: Path | None = None) -> list[dict]:
    path = results_path(arm, work)
    if not path.is_file():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _at_least(level, floor: str) -> bool:
    return sb.LEVELS.index(level or "none") >= sb.LEVELS.index(floor)


def render_table(kind: str | None, work: Path | None = None) -> str:
    """Per arm: located (any finding, headline), the gate's call, refusals, bill — and per
    instance both arms side by side, so a miss shows what each said instead."""
    arms = {arm: [r for r in load_results(arm, work) if not kind or r["kind"] == kind] for arm in ARMS}
    both = sorted(set(r["id"] for r in arms["verdict"]) & set(r["id"] for r in arms["plain"]))
    lines = [f"Instances scored in both arms: {len(both)}" + (f" ({kind})" if kind else ""), "",
             "| | Verdict | plain Claude Code |", "|---|---|---|"]

    def rate(rows, pred):
        n = len(rows)
        return f"{sum(1 for r in rows if pred(r))}/{n}" if n else "—"

    sel = {arm: [r for r in arms[arm] if r["id"] in both] for arm in ARMS}
    for label, pred in (
            ("located, any finding, function or better", lambda r: _at_least(r.get("any_hit"), "function")),
            ("located, any finding, file or better", lambda r: _at_least(r.get("any_hit"), "file")),
            ("located, headline, function or better", lambda r: _at_least(r.get("headline_hit"), "function")),
            ("gate blocked the change", lambda r: r.get("blocks") is True),
            ("blocked AND located (function+)", lambda r: r.get("blocks") is True
             and _at_least(r.get("any_hit"), "function")),
            ("stopped by the safety filter (≥ 1 refusal)", lambda r: (r.get("refusals") or 0) > 0),
            ("run did not finish", lambda r: bool(r.get("stopped")))):
        lines.append(f"| {label} | {rate(sel['verdict'], pred)} | {rate(sel['plain'], pred)} |")
    for label, key in (("median cost (CLI)", "cost_usd"), ("median wall (s)", "wall_s")):
        vals = {arm: sorted(r[key] for r in sel[arm] if isinstance(r.get(key), (int, float)))
                for arm in ARMS}
        med = {arm: (v[len(v) // 2] if v else None) for arm, v in vals.items()}
        fmt = (lambda x: f"${x:.2f}") if key == "cost_usd" else (lambda x: f"{x}")
        lines.append(f"| {label} | {fmt(med['verdict']) if med['verdict'] is not None else '—'} | "
                     f"{fmt(med['plain']) if med['plain'] is not None else '—'} |")
    lines += ["", "| Instance | kind | Verdict: verdict · any · headline | plain: verdict · any · headline |",
              "|---|---|---|---|"]
    by = {arm: {r["id"]: r for r in sel[arm]} for arm in ARMS}
    for iid in both:
        v, p = by["verdict"][iid], by["plain"][iid]
        lines.append(f"| {iid} | {v['kind']} | {v.get('verdict')} · {v.get('any_hit')} · "
                     f"{v.get('headline_hit')} | {p.get('verdict')} · {p.get('any_hit')} · "
                     f"{p.get('headline_hit')} |")
    return "\n".join(lines)


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_prepare(args) -> int:
    info = prepare(instance(args.id))
    print(json.dumps({k: v for k, v in info.items() if k != "gold_hunks"}, indent=2))
    return 0


def one(inst: dict, arms=ARMS, work: Path | None = None) -> list[dict]:
    """Both arms on one fresh preparation: the control first, on a checkout no `.claude/`
    has touched, then Verdict on the same tree."""
    try:
        info = prepare(inst, work)
    except Exception as exc:  # an instance that cannot be prepared is recorded, not retried
        row = {"id": inst["id"], "kind": inst["kind"], "repo": inst["repo"], "arm": "prepare",
               "error": str(exc)[:2000], "finished": now_utc()}
        (work or WORK).joinpath("prepare-errors.jsonl").open("a", encoding="utf-8").write(
            json.dumps(row) + "\n")
        print(f"  {inst['id']}: not prepared — {str(exc)[:300]}", file=sys.stderr)
        return []
    rows = []
    for arm in ("plain", "verdict"):
        if arm not in arms:
            continue
        restore(Path(info["checkout"]))
        row = run_arm(inst, info, arm, work)
        append_result(row, work)
        rows.append(row)
        print(f"  {inst['id']} [{arm}] verdict={row.get('verdict')} any={row.get('any_hit')} "
              f"head={row.get('headline_hit')} refusals={row.get('refusals')} "
              f"stopped={row.get('stopped')} cost={row.get('cost_usd')}", file=sys.stderr)
    return rows


def cmd_run(args) -> int:
    one(instance(args.id), arms=(args.arm,) if args.arm else ARMS)
    return 0


def in_lane(inst: dict, lane: str | None) -> bool:
    """`--lane I/N`: instances split by repository, so two lanes never share a checkout
    path (the checkout is named for the project, and one project may hold three)."""
    if not lane:
        return True
    i, n = (int(x) for x in lane.split("/"))
    digest = int(hashlib.sha256(inst["repo"].encode("utf-8")).hexdigest(), 16)
    return digest % n == i


def cmd_batch(args) -> int:
    todo = [i for i in load_instances() if (not args.kind or i["kind"] == args.kind)
            and in_lane(i, args.lane)]
    count = 0
    for inst in todo:
        arms = tuple(a for a in ARMS if inst["id"] not in done_ids(a))
        if not arms:
            continue
        if args.limit and count >= args.limit:
            break
        count += 1
        print(f"{now_utc()} {inst['id']} ({inst['kind']}): {', '.join(arms)}", file=sys.stderr)
        one(inst, arms=arms)
    print(f"{now_utc()} batch done ({count} instances)", file=sys.stderr)
    return 0


def cmd_table(args) -> int:
    print(render_table(args.kind))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("id")
    p = sub.add_parser("run")
    p.add_argument("id")
    p.add_argument("--arm", choices=ARMS, default=None)
    p = sub.add_parser("batch")
    p.add_argument("--kind", choices=("money", "security"), default=None)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--lane", default=None, metavar="I/N",
                   help="run only lane I of N; lanes split by repository")
    p = sub.add_parser("table")
    p.add_argument("--kind", choices=("money", "security"), default=None)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"prepare": cmd_prepare, "run": cmd_run, "batch": cmd_batch,
            "table": cmd_table}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
