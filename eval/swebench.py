#!/usr/bin/env python3
"""The external key: SWE-bench Verified instances as an answer key nobody here wrote.

Every other key in eval/ was written by the same hands that wrote the prompt, so a
tester that passes them has been tuned against them. SWE-bench Verified is 500 real
defects, each fixed by its own maintainers, each with a test that fails before the
fix and passes after it. This harness turns one instance into one Verdict run:

  1. the repository at the instance's base commit — the fixed commit's parent — with
     every later commit, branch and tag physically absent (`git log` ends there);
  2. the maintainers' environment from SWE-bench's own specs (interpreter, pins);
  3. the environment proven before the tester arrives: the withheld tests fail at
     base and pass with the gold patch, applied in the checkout and reverted;
  4. the issue text, verbatim, as the shipped `/verdict:bug` charter — run headless
     through `verdict-run` against the plugin in the cache (the newest installed
     version by default; never a checkout that is being edited);
  5. the findings scored against the gold patch's location, deterministically: does
     a `path:line` the finding cites fall in a file the fix touched (`file`), inside
     one of its hunks (`hunk`), or in the same function (`function`)? The tester's
     headline finding is scored apart from "any finding".

The withheld tests never enter the checkout the tester sees, and `hints_text` is
never shown. Mechanism is prose and is not machine-scored: a miss is published with
what the finding said instead, so a reader can judge the near-misses themselves.

The instance set is a rule, not a hand-pick: every Verified instance whose repository
has fewer than twenty instances in the set — the five smallest repositories.

Usage:
  python3 eval/swebench.py select                 # the set → eval/swebench/instances.json
  python3 eval/swebench.py run <instance_id>      # prepare, validate, run, score: one instance
  python3 eval/swebench.py batch [--limit N]      # every pending instance, in order, resumable
  python3 eval/swebench.py table                  # eval/swebench/results.jsonl → markdown

Model runs cost real tokens; this is never a CI job.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
REPO = EVAL_DIR.parent
OUT_DIR = EVAL_DIR / "swebench"
INSTANCES = OUT_DIR / "instances.json"
RESULTS = OUT_DIR / "results.jsonl"
SPECS = OUT_DIR / "specs.json"

sys.path.insert(0, str(REPO / "src"))
from verdict_mcp.anchors import refs_in  # noqa: E402
from verdict_mcp.project_key import derive_key  # noqa: E402
from verdict_mcp.runner import limit_kind, plugin_root, seconds_until_reset  # noqa: E402

DATASET = "princeton-nlp/SWE-bench_Verified"
ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=princeton-nlp%2FSWE-bench_Verified"
            "&config=default&split=test&offset={offset}&length=100")
SMALL_REPO_MAX = 20           # a repository with fewer instances than this is "small"
CACHE = Path(os.environ.get("VERDICT_SWEBENCH_CACHE") or Path.home() / ".cache" / "verdict-swebench")

# Where the package and the tests live, per repository — coverage needs the package,
# the gates need the test target. The first existing tests entry wins (requests kept
# its suite in one root-level file until 2.20).
LAYOUT = {
    "pallets/flask": {"package": "src/flask", "tests": ["tests"]},
    "psf/requests": {"package": "requests", "tests": ["tests", "test_requests.py"]},
    "mwaskom/seaborn": {"package": "seaborn", "tests": ["tests"]},
    "pytest-dev/pytest": {"package": "src/_pytest", "tests": ["testing"]},
    "pylint-dev/pylint": {"package": "pylint", "tests": ["tests"]},
}
# The projects' own test requirements, on top of SWE-bench's pins: the file the
# project's tox/CI installs, taken when the checkout has it. SWE-bench's images
# install these through the repo's own metadata; a bare venv does not. (requests'
# own `requirements.txt` pins a 2015 pytest that cannot run on 3.9, so its plugins
# are named below instead.)
TEST_REQUIREMENTS = {
    "pallets/flask": ["requirements/tests.txt"],
    "psf/requests": ["requirements-dev.txt"],
    "mwaskom/seaborn": [],
    "pytest-dev/pytest": [],
    "pylint-dev/pylint": ["requirements_test.txt", "requirements_test_min.txt"],
}
# What the suite imports and no requirements file carries — resolved fresh.
EXTRA_PACKAGES = {
    "psf/requests": ["pytest-httpbin", "pytest-mock"],
}
# The same, resolved AS OF the instance's date (`uv --exclude-newer`): pytest's own
# suite asserts on pygments' colouring and on `pkg_resources`, which setuptools has
# since removed — the tooling its CI installed that week is the tooling that matches.
DATED_EXTRAS = {
    "pytest-dev/pytest": ["setuptools", "pygments", "hypothesis", "xmlschema", "mock", "requests"],
}
# SWE-bench's pins post-date the instances by a year or more, and around the withheld
# test they break the suite the maintainers had green: seaborn 0.12 under pandas 2.0
# is 646 red at base, flask 2.3-dev under Werkzeug 2.3.7 raises deprecations as
# errors, requests 2.26's dev requirements no longer import under markupsafe 2.1.
# So the environment is resolved AS OF the instance's date (`uv --exclude-newer`):
# what `pip install -e .[dev]` gave the maintainer the week the issue was filed —
# for every instance filed since DATED_FROM, when period test tooling still runs on
# the interpreter SWE-bench names. Older instances (requests 1.x–2.9, pytest 4–5:
# a 2015 pytest cannot run on 3.9) keep SWE-bench's pins with test tooling resolved
# fresh. The two repositories named here are dated whatever their date.
DATED_FROM = "2020-01-01"
DATED_ENV = {"mwaskom/seaborn", "pallets/flask"}
# Installed fresh before the editable build (`--no-build-isolation`): every backend
# the five repositories declare, plus what their setup.py files import.
BUILD_BACKENDS = ["setuptools", "wheel", "setuptools_scm", "flit_core", "hatchling"]
# Batch order: cheapest suites first, so a stopped batch has the most rows.
REPO_ORDER = ["pallets/flask", "psf/requests", "pytest-dev/pytest", "mwaskom/seaborn",
              "pylint-dev/pylint"]
SEVERITY_RANK = {"Blocker": 5, "Critical": 4, "Major": 3, "Minor": 2, "Trivial": 1}
LEVELS = ("none", "file", "hunk", "function")
HUNK_SLACK = 15               # lines either side of a gold hunk that still count as the hunk

HEADLESS = (
    "Use the verdict agent to process the bug report below against this repository. Run the "
    "agent to completion IN THIS SESSION: do not spawn it in the background, and do not end "
    "your turn until its state file and report are written — there is no 'later' in a "
    "headless run. Verdict reports and specifies; it does not fix. Relay the agent's handoff "
    "verbatim and add nothing of your own.")
CHARTER_TAIL = (
    "The checkout is the exact commit the report was filed against; nothing after it exists "
    "here, and the QA profile in the QA root names the project's suite. The finding must "
    "locate the defect — the file and line where the cause lives, cited as `path:line` in its "
    "evidence — and state the mechanism. No fix is wanted and none exists to verify.")


def sh(cmd, cwd=None, env=None, timeout=None, check=False):
    proc = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, capture_output=True,
                          text=True, errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))} → rc {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout).strip()[-800:]}")
    return proc


def git(args, cwd):
    return sh(["git", *args], cwd=cwd, check=True).stdout.strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── the dataset ───────────────────────────────────────────────────────────────

def dataset_rows() -> list[dict]:
    """All 500 Verified rows, fetched once through the datasets-server API and cached."""
    cached = CACHE / "verified.json"
    if cached.is_file():
        return json.loads(cached.read_text(encoding="utf-8"))
    rows = []
    for offset in range(0, 500, 100):
        with urllib.request.urlopen(ROWS_URL.format(offset=offset), timeout=120) as resp:
            rows += [r["row"] for r in json.load(resp)["rows"]]
    if len(rows) != 500:
        raise SystemExit(f"swebench: expected 500 Verified rows, got {len(rows)}")
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def row_for(instance_id: str) -> dict:
    for r in dataset_rows():
        if r["instance_id"] == instance_id:
            return r
    raise SystemExit(f"swebench: no Verified instance {instance_id!r}")


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


def gold_of(patch: str) -> dict[str, list[list[int]]]:
    """The fix's location on the base side: file → [start, end] line ranges of its hunks.
    A pure insertion (`-N,0`) is anchored at the line it follows."""
    out: dict[str, list[list[int]]] = {}
    for block in re.split(r"(?m)^diff --git ", patch)[1:]:
        head, _, rest = block.partition("\n")
        m = re.match(r"a/(\S+) b/(\S+)", head)
        if not m:
            continue
        ranges = []
        for h in _HUNK.finditer(rest):
            start, count = int(h.group(1)), int(h.group(2) or 1)
            ranges.append([start, start] if count == 0 else [start, start + count - 1])
        out[m.group(2)] = ranges
    return out


def select_instances(rows: list[dict]) -> list[dict]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["repo"]] = counts.get(r["repo"], 0) + 1
    small = {repo for repo, n in counts.items() if n < SMALL_REPO_MAX}
    chosen = [r for r in rows if r["repo"] in small]

    def order(r):
        num = int(r["instance_id"].rsplit("-", 1)[1])
        pos = REPO_ORDER.index(r["repo"]) if r["repo"] in REPO_ORDER else len(REPO_ORDER)
        return (pos, num)

    out = []
    for r in sorted(chosen, key=order):
        gold = gold_of(r["patch"])
        out.append({
            "instance_id": r["instance_id"], "repo": r["repo"], "version": r["version"],
            "difficulty": r["difficulty"], "base_commit": r["base_commit"],
            "created_at": r["created_at"],
            "gold_files": sorted(gold), "gold_hunks": gold,
            "fail_to_pass": json.loads(r["FAIL_TO_PASS"]),
            "problem_statement_chars": len(r["problem_statement"]),
        })
    return out


def cmd_select(args) -> int:
    rows = dataset_rows()
    chosen = select_instances(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    doc = {
        "_rule": (f"every {DATASET} instance whose repository has fewer than {SMALL_REPO_MAX} "
                  "instances in the set — the five smallest repositories, nothing chosen by hand"),
        "selected_at": now_utc(), "count": len(chosen), "instances": chosen,
    }
    INSTANCES.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    by_repo: dict[str, int] = {}
    for c in chosen:
        by_repo[c["repo"]] = by_repo.get(c["repo"], 0) + 1
    print(f"{len(chosen)} instances → {INSTANCES.relative_to(REPO)}")
    for repo, n in sorted(by_repo.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {repo}")
    return 0


def instances() -> list[dict]:
    if not INSTANCES.is_file():
        raise SystemExit("swebench: run `select` first")
    return json.loads(INSTANCES.read_text(encoding="utf-8"))["instances"]


# ── the environment ───────────────────────────────────────────────────────────

def spec_for(repo: str, version: str) -> dict:
    specs = json.loads(SPECS.read_text(encoding="utf-8"))["repos"]
    try:
        return specs[repo][version]
    except KeyError:
        raise SystemExit(f"swebench: no environment spec for {repo} {version}")


def workdir(instance_id: str) -> Path:
    return CACHE / "work" / instance_id


def mirror_of(repo: str) -> Path:
    path = CACHE / "mirrors" / (repo.replace("/", "__") + ".git")
    if not path.is_dir():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"  mirroring {repo}", file=sys.stderr)
        sh(["git", "clone", "-q", "--mirror", f"https://github.com/{repo}.git", str(path)],
           check=True)
    return path


def checkout_base(repo: str, base: str, dest: Path) -> None:
    """A checkout whose history ENDS at the base commit. Later commits, branches
    and tags are not merely unlisted: the reflogs are expired before the repack,
    the alternates link to the mirror is cut, so the objects are not there."""
    mirror = mirror_of(repo)
    if sh(["git", "cat-file", "-e", f"{base}^{{commit}}"], cwd=mirror).returncode != 0:
        sh(["git", "fetch", "-q", "--all"], cwd=mirror, check=True)
    sh(["git", "clone", "-q", "--shared", "--no-checkout", str(mirror), str(dest)], check=True)
    git(["checkout", "-q", "-b", "base", base], dest)
    git(["remote", "remove", "origin"], dest)        # takes refs/remotes/origin/* with it
    for ref in git(["for-each-ref", "--format=%(refname)"], dest).splitlines():
        if not ref or ref == "refs/heads/base":
            continue
        # A tag on an ancestor is history, and setuptools_scm reads the version
        # from it; a tag on anything else is the future.
        if ref.startswith("refs/tags/") and sh(
                ["git", "merge-base", "--is-ancestor", ref, "base"], cwd=dest).returncode == 0:
            continue
        git(["update-ref", "-d", ref], dest)
    git(["reflog", "expire", "--expire=now", "--all"], dest)
    git(["repack", "-a", "-d", "-q"], dest)
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    if alternates.exists():
        alternates.unlink()
    git(["prune"], dest)
    git(["fsck", "--no-progress", "--connectivity-only"], dest)


def uv_python(version: str) -> str:
    proc = sh(["uv", "python", "find", version])
    if proc.returncode != 0:
        sh(["uv", "python", "install", version], check=True)
        proc = sh(["uv", "python", "find", version], check=True)
    return proc.stdout.strip()


def is_dated(inst: dict, as_of: str) -> bool:
    return inst["repo"] in DATED_ENV or as_of >= DATED_FROM


def base_date(checkout: Path) -> str:
    """The base commit's date — the week the code under test was written. Not the
    issue's `created_at`: SWE-bench dates an instance by the issue, and an issue can
    sit open for a year before the commit that fixes it (requests-5414: filed
    2020-04, fixed on a 2021-09 tree whose dependencies did not exist in 2020)."""
    return git(["show", "-s", "--format=%cI", "HEAD"], checkout)[:10]


def build_env(inst: dict, spec: dict, checkout: Path, venv: Path, as_of: str,
              force_pins: bool = False) -> list[str]:
    """The maintainers' environment: SWE-bench's interpreter, packages as of the
    instance's date (or SWE-bench's pins — see DATED_FROM, or `force_pins` when
    the dated environment failed validation), the project editable, pytest and
    coverage for the gates, the project's own test requirements."""
    notes = []
    for step in spec.get("pre_install", []):
        # the one pre_install among these repositories is a GNU `sed -i` on setup.cfg
        m = re.match(r"sed -i 's/(.*)/(.*)/' (\S+)$", step)
        if not m:
            raise RuntimeError(f"unhandled pre_install step: {step}")
        target = checkout / m.group(3)
        target.write_text(target.read_text(encoding="utf-8").replace(m.group(1), m.group(2)),
                          encoding="utf-8")
        notes.append(f"pre_install: {step}")
    py = uv_python(spec["python"])
    sh(["uv", "venv", "-q", "--python", py, str(venv)], check=True)
    vpy = str(venv / "bin" / "python")
    dated = is_dated(inst, as_of) and not force_pins
    date_flag = ["--exclude-newer", as_of] if dated else []
    pkgs = [] if dated else list(spec.get("pip_packages", []))
    has_pytest = any(re.match(r"pytest(==|>=|$)", p) for p in pkgs)
    if not has_pytest and inst["repo"] != "pytest-dev/pytest":   # the project IS pytest there
        pkgs.append("pytest")
    pkgs.append("coverage")
    sh(["uv", "pip", "install", "-q", "--python", vpy, *date_flag, *pkgs], check=True)
    notes.append(f"environment resolved as of {as_of}" if dated
                 else f"SWE-bench pins: {len(spec.get('pip_packages', []))}")
    install = spec["install"]
    # Editable for every project, whatever the spec's `pip install .` says: the
    # counterfactual doctrine in the prompt is written for the editable `.pth` trap,
    # and a suite that imports an installed copy would make a scratch edit a no-op
    # — and would make the gold patch a no-op too, which is what the validation
    # step catches. The spec's extras (`.[dev]`) are kept. The build backends are
    # today's, outside the date: a 2020 setuptools has no editable hook, and the
    # date is about what the code ran against, not what packaged it.
    sh(["uv", "pip", "install", "-q", "--python", vpy, *BUILD_BACKENDS], check=True)
    m = re.search(r"\.\[[^\]]+\]", install)
    target = m.group(0) if m else "."
    proc = sh(["uv", "pip", "install", "-q", "--python", vpy, *date_flag,
               "--no-build-isolation", "-e", target], cwd=checkout)
    if proc.returncode != 0:
        raise RuntimeError(f"editable install failed: {proc.stderr.strip()[-600:]}")
    notes.append(f"install: {install} (run as editable)")
    for rel in TEST_REQUIREMENTS.get(inst["repo"], []):
        req = checkout / rel
        if req.is_file():
            proc = sh(["uv", "pip", "install", "-q", "--python", vpy, *date_flag, "-r", str(req)],
                      cwd=checkout)
            notes.append(f"test requirements: {rel}" + ("" if proc.returncode == 0
                                                       else " (failed, continuing)"))
            break
    extra = EXTRA_PACKAGES.get(inst["repo"], [])
    if extra:
        proc = sh(["uv", "pip", "install", "-q", "--python", vpy, *extra], cwd=checkout)
        notes.append("extra packages: " + ", ".join(extra)
                     + ("" if proc.returncode == 0 else " (failed, continuing)"))
    dated_extra = DATED_EXTRAS.get(inst["repo"], [])
    if dated_extra:
        # `--reinstall`, not `--upgrade`: a satisfied requirement is never re-resolved,
        # and the build backend installed fresh above (setuptools 82, no
        # `pkg_resources`) would otherwise stand in for the 2020 one the suite needs.
        proc = sh(["uv", "pip", "install", "-q", "--python", vpy, "--reinstall",
                   "--exclude-newer", as_of, *dated_extra], cwd=checkout)
        notes.append(f"extra packages as of {as_of}: " + ", ".join(dated_extra)
                     + ("" if proc.returncode == 0 else " (failed, continuing)"))
    return notes


_OUTCOME = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS) (\S.*?)(?: - .*)?$")


def outcomes_from(output: str) -> dict[str, str]:
    """Per-test outcomes from a `-rA` run's short summary — SWE-bench's own way of
    reading a run. Test ids are not passed on the command line: a parametrized id
    with a space in it (`test_get_annotation_annassign[a: str = None-Optional[str]]`)
    is split by pytest 6 before it is matched, and reads as "not found"."""
    out: dict[str, str] = {}
    for line in output.splitlines():
        m = _OUTCOME.match(line.strip())
        if m:
            out[m.group(2).strip()] = m.group(1)
    return out


def test_files_of(test_patch: str) -> list[str]:
    return sorted(gold_of(test_patch))


def status_of(outcomes: dict[str, str], test_id: str) -> str:
    """The outcome of one withheld test. SWE-bench's own log parser cut ids at
    whitespace (`…test_get_annotation_annassign[a:` for `[a: str = None-Optional[str]]`),
    so a listed id that names no outcome is read as a prefix: PASSED when every
    outcome it prefixes passed, the worst of them otherwise, `absent` when none."""
    if test_id in outcomes:
        return outcomes[test_id]
    matches = [v for k, v in outcomes.items() if k.startswith(test_id)]
    if not matches:
        return "absent"
    return "PASSED" if all(v == "PASSED" for v in matches) else \
        next(v for v in matches if v != "PASSED")


def temproot(checkout: Path) -> Path:
    """A private pytest temp root per instance. The default `pytest-of-<user>` is
    shared by every suite on the machine, and pytest's own suite leaves read-only
    `garbage-*` directories there (`test_cache_failure_warns`) that the next
    session's cleanup warns about — a warning pytest's config turns into a setup
    ERROR on unrelated tests."""
    root = checkout.parent / "scratch" / "pytest-tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_test_files(vpy: str, checkout: Path, files: list[str]) -> tuple[dict[str, str], str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTEST_DEBUG_TEMPROOT=str(temproot(checkout)))
    proc = sh([vpy, "-m", "pytest", "-rA", "-p", "no:cacheprovider", "-p", "no:randomly",
               *files], cwd=checkout, env=env, timeout=1800)
    output = proc.stdout + proc.stderr
    return outcomes_from(output), output


def validate_env(row: dict, checkout: Path, vpy: str) -> tuple[bool, str]:
    """The withheld tests fail at base and pass with the gold patch — proven in
    the checkout, then reverted, before the tester arrives. Read the way SWE-bench
    reads its own runs: the test files from the test patch, `-rA`, per-test
    outcomes; a withheld test that is absent or erroring at base counts as failing."""
    ids = json.loads(row["FAIL_TO_PASS"])
    files = test_files_of(row["test_patch"])
    test_patch = checkout / ".swebench-test.patch"
    gold_patch = checkout / ".swebench-gold.patch"
    test_patch.write_text(row["test_patch"], encoding="utf-8")
    gold_patch.write_text(row["patch"], encoding="utf-8")
    try:
        proc = sh(["git", "apply", "--whitespace=nowarn", str(test_patch)], cwd=checkout)
        if proc.returncode != 0:
            return False, f"test patch does not apply: {proc.stderr.strip()[-300:]}"
        before, _ = run_test_files(vpy, checkout, files)
        failing_at_base = [i for i in ids if status_of(before, i) != "PASSED"]
        if not failing_at_base:
            return False, f"all {len(ids)} withheld test(s) already pass at base"
        proc = sh(["git", "apply", "--whitespace=nowarn", str(gold_patch)], cwd=checkout)
        if proc.returncode != 0:
            return False, f"gold patch does not apply: {proc.stderr.strip()[-300:]}"
        after, output = run_test_files(vpy, checkout, files)
        failing = [i for i in ids if status_of(after, i) != "PASSED"]
        if failing:
            detail = "; ".join(f"{i} → {status_of(after, i)}" for i in failing[:3])
            tail = " | ".join(output.strip().splitlines()[-2:])
            return False, (f"{len(failing)} of {len(ids)} withheld test(s) do not pass with the "
                           f"gold patch: {detail} | {tail}")
        # Every withheld test passes with the fix; the defect is observable when at
        # least one fails without it. Tests SWE-bench lists that already pass here
        # are named, not fatal — their base run failed for its own reasons.
        note = "" if len(failing_at_base) == len(ids) else \
            f" ({len(ids) - len(failing_at_base)} already passed at base)"
        return True, (f"{len(failing_at_base)} of {len(ids)} withheld test(s) fail at base, "
                      f"all pass with the fix{note}")
    finally:
        test_patch.unlink(missing_ok=True)
        gold_patch.unlink(missing_ok=True)
        sh(["git", "checkout", "-q", "--", "."], cwd=checkout)
        sh(["git", "clean", "-fdq"], cwd=checkout)
        for cache in checkout.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)


def tests_target(repo: str, checkout: Path) -> str:
    for candidate in LAYOUT[repo]["tests"]:
        if (checkout / candidate).exists():
            return candidate
    raise RuntimeError(f"no test target found for {repo} among {LAYOUT[repo]['tests']}")


def write_profile(qa_root: Path, key: str, inst: dict, checkout: Path, vpy: str,
                  scratch: Path) -> None:
    repo = inst["repo"]
    package = LAYOUT[repo]["package"]
    target = tests_target(repo, checkout)
    base = (f"PYTHONDONTWRITEBYTECODE=1 PYTEST_DEBUG_TEMPROOT={temproot(checkout)} "
            f"{vpy} -m pytest -q -p no:cacheprovider")
    network = ""
    if repo == "psf/requests":
        network = ("- Parts of the suite talk to a public httpbin (`httpbin.org`) or a local "
                   "`pytest-httpbin` server. That traffic is the project's own test design; a "
                   "failure there is `ENVIRONMENT` until proven otherwise.\n")
    text = f"""---
gates:
  suite: {base} --junitxml={{report}} {target}
test_ids_cmd: {base} --collect-only {target}
test_one_cmd: {base} "{{id}}"
coverage_suite_cmd: PYTHONDONTWRITEBYTECODE=1 PYTEST_DEBUG_TEMPROOT={temproot(checkout)} COVERAGE_FILE={scratch}/.coverage {vpy} -m coverage run --source={package} -m pytest -q -p no:cacheprovider {target}
---

# QA Profile — {key}

Project-Key: {key}
Repo-Path: {checkout}
Repo-Remote: https://github.com/{repo}.git
Security-Pass: disabled
Schema-Version: 1

## What this project is

`{repo}` at version {inst['version']}, checked out at the exact commit a bug report was
filed against. It is a **library**; it moves no money and holds no user data. The blast
radius is downstream: a wrong behaviour in a public API ships to every dependant.

## History

This checkout's history ends at HEAD. There are no later commits, branches or tags —
the report is being processed at the moment it was filed, not with hindsight.

## Isolation rules

- A QA-owned virtualenv is pre-built at `{vpy}` with the project installed editable,
  `pytest` and `coverage`. Do **not** install anything, anywhere, and do not run
  `pip`; if the venv is missing, report `blocked`.
- Every pytest invocation carries `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`
  (else `.pytest_cache/` and `__pycache__/` appear in the checkout), and
  `PYTEST_DEBUG_TEMPROOT={temproot(checkout)}` so its temp directories stay private to
  this run. Coverage runs with `COVERAGE_FILE` outside the checkout, as the gate above does.
- Counterfactuals go in a scratch copy of the tree with the copy's source first on
  `PYTHONPATH` — the editable install's `.pth` names this checkout absolutely.
- Isolation check each run: `git status --porcelain` before and after the gates.
  Anything but a clean tree (modulo a pre-existing `?? .claude/`) is an unintended
  write — report it, do not revert it.
{network}
## Real commands

- The suite gate above is the project's own pytest suite (`{target}`), one interpreter
  (Python {spec_python(inst)}), local machine. CI ran a matrix; this run covers one cell.
- No lint, type or coverage gate is enforced here; coverage is a QA-side measurement.
"""
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "profile.md").write_text(text, encoding="utf-8")


def spec_python(inst: dict) -> str:
    return spec_for(inst["repo"], inst["version"])["python"]


def build_prompt(root: Path, row: dict) -> str:
    """The shipped `/verdict:bug` command, headless, with the issue as its argument."""
    text = (root / "commands" / "bug.md").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    body = (parts[2] if len(parts) == 3 else text).strip()
    body = body.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
    body = body.replace("`$ARGUMENTS`", "the bug report below").replace("$ARGUMENTS", "the bug report below")
    report = row["problem_statement"].strip()
    return (f"{HEADLESS}\n\n{body}\n\n{CHARTER_TAIL}\n\n"
            f"## Bug report (verbatim, from the project's issue tracker)\n\n{report}\n")


def prepare(inst: dict, row: dict, keep_existing: bool) -> dict:
    work = workdir(inst["instance_id"])
    # The checkout carries the instance's name: the project key, the QA root and
    # the finding ids all derive from the directory's basename (§0).
    checkout, venv, qa_home = work / inst["instance_id"], work / "venv", work / "qa-home"
    if work.exists() and not keep_existing:
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    (work / "logs").mkdir(exist_ok=True)
    info = {"work": str(work), "checkout": str(checkout), "venv": str(venv),
            "qa_home": str(qa_home), "env_notes": []}
    if not checkout.is_dir():
        print(f"  checkout at {inst['base_commit'][:12]}", file=sys.stderr)
        checkout_base(inst["repo"], inst["base_commit"], checkout)
    spec = spec_for(inst["repo"], inst["version"])
    vpy = str(venv / "bin" / "python")
    as_of = base_date(checkout)
    info["base_date"] = as_of
    fresh = not Path(vpy).exists()
    dated_failed = None
    if fresh:
        print(f"  environment: python {spec['python']}, {len(spec.get('pip_packages', []))} pins, "
              f"base commit dated {as_of}", file=sys.stderr)
        try:
            info["env_notes"] = build_env(inst, spec, checkout, venv, as_of)
        except RuntimeError as exc:
            # A project whose metadata pins a dependency released AFTER its base
            # commit (pylint's astroid dev pins) cannot resolve as of its date at all.
            if not is_dated(inst, as_of):
                raise
            dated_failed = f"dated environment did not build: {str(exc)[-300:]}"
    if dated_failed is None and fresh and is_dated(inst, as_of):
        ok, why = validate_env(row, checkout, vpy)
        if not ok:
            dated_failed = f"dated environment failed validation: {why}"
    if dated_failed is not None:
        # SWE-bench's own pins are the other legitimate environment — tried before
        # the instance is given up, and named in the notes either way.
        print(f"  {dated_failed} — rebuilding with SWE-bench's pins", file=sys.stderr)
        shutil.rmtree(venv, ignore_errors=True)
        info["env_notes"] = [dated_failed] + build_env(inst, spec, checkout, venv, as_of,
                                                        force_pins=True)
    ok, why = validate_env(row, checkout, vpy)
    info["env_valid"], info["env_check"] = ok, why
    print(f"  environment check: {why}", file=sys.stderr)
    key, _ = derive_key(checkout)
    info["key"] = key
    qa_root = qa_home / key
    if qa_root.exists():
        shutil.rmtree(qa_root)
    write_profile(qa_root, key, inst, checkout, vpy, work / "scratch")
    (work / "scratch").mkdir(exist_ok=True)
    return info


# ── the run ───────────────────────────────────────────────────────────────────

def transcript_usage(cwd: Path, session_id, config_dir=None) -> dict | None:
    """The whole session's token bill from Claude Code's own transcript — the main
    session and every subagent — summed per request id. The CLI's result line
    reports the last turn only; the tester's work happens in the subagent."""
    if not session_id:
        return None
    key = re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))
    # `CLAUDE_CONFIG_DIR` moves the transcripts with the account that paid.
    named = (config_dir or os.environ.get("CLAUDE_CONFIG_DIR"))
    base = (Path(named).expanduser() if named else Path.home() / ".claude") / "projects" / key
    files = [base / f"{session_id}.jsonl"]
    files += sorted((base / session_id / "subagents").glob("*.jsonl")) \
        if (base / session_id / "subagents").is_dir() else []
    by_req: dict[str, dict] = {}
    seen = 0
    for f in files:
        if not f.is_file():
            continue
        seen += 1
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "assistant":
                continue
            usage = (d.get("message") or {}).get("usage")
            rid = d.get("requestId") or d.get("uuid")
            if isinstance(usage, dict) and rid:
                by_req[rid] = usage
    if not by_req:
        return None
    totals = {k: 0 for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                             "cache_read_input_tokens")}
    for usage in by_req.values():
        for k in totals:
            totals[k] += int(usage.get(k) or 0)
    return {"requests": len(by_req), "files": seen, **totals}


def seed_config(config_dir: Path, project: Path) -> None:
    """Mark the checkout trusted inside a named config directory."""
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


def result_line(output: str) -> dict:
    """The `--output-format json` result the CLI printed, out of the runner's relay."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and doc.get("type") == "result":
            return doc
    return {}


def read_env_file(path: Path) -> dict:
    """`KEY=VALUE` lines from a file the operator owns — how a second account's
    `CLAUDE_CONFIG_DIR`, or a gateway's base URL and key, reach a batch without
    passing through a command line."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def run_instance(inst: dict, row: dict, info: dict, root: Path, model: str,
                 timeout_s: int, attempt: int, extra_env: dict | None = None) -> dict:
    work = Path(info["work"])
    prompt_file = work / "prompt.md"
    prompt_file.write_text(build_prompt(root, row), encoding="utf-8")
    log = work / "logs" / f"run{attempt}.log"
    env = dict(os.environ, VERDICT_HOME=info["qa_home"], **(extra_env or {}))
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    config_dir = env.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        # A config directory the CLI has never seen has accepted neither the
        # trust dialog nor bypass-permissions mode, and `verdict-run` passes
        # `--dangerously-skip-permissions`: the session would exit 0 having
        # done nothing, which reads as a lost run rather than a setup error.
        seed_config(Path(config_dir), Path(info["checkout"]))
    cmd = [sys.executable, str(root / "src" / "verdict_mcp" / "runner.py"), info["key"],
           "--repo", info["checkout"], "--plugin-root", str(root),
           "--prompt-file", str(prompt_file), "--model", model, "--timeout-s", str(timeout_s),
           "--", "--output-format", "json"]
    started = time.monotonic()
    proc = subprocess.run(cmd, cwd=info["checkout"], env=env, capture_output=True, text=True,
                          errors="replace", timeout=timeout_s * 2 + 11000)
    wall = time.monotonic() - started
    output = proc.stdout + "\n--- stderr ---\n" + proc.stderr
    log.write_text(output, encoding="utf-8")
    res = result_line(output)
    usage = res.get("usage") or {}
    return {
        "runner_exit": proc.returncode, "wall_s": round(wall), "log": str(log),
        "cost_usd": res.get("total_cost_usd"), "duration_api_ms": res.get("duration_api_ms"),
        "num_turns": res.get("num_turns"), "session_id": res.get("session_id"),
        "tokens": {k: usage.get(k) for k in ("input_tokens", "output_tokens",
                                             "cache_creation_input_tokens",
                                             "cache_read_input_tokens")} if usage else None,
        "session_limited": limit_kind(output) == "session",
        "limit": limit_kind(output),
        "output": output,
    }


# ── the score ─────────────────────────────────────────────────────────────────

def _spans(source: str):
    """(start, end, qualname) for every function and class, innermost resolvable."""
    tree = ast.parse(source)
    spans = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                spans.append((child.lineno, getattr(child, "end_lineno", child.lineno), name))
                walk(child, name + ".")
            else:
                walk(child, prefix)
    walk(tree, "")
    return spans


def enclosing(spans, line: int):
    best = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or end - start < best[1] - best[0]):
            best = (start, end, name)
    return best[2] if best else None


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _same_file(cited: str, gold: str) -> bool:
    """Exact, or one a directory-qualified suffix of the other (`_pytest/pathlib.py`
    for `src/_pytest/pathlib.py`). A bare filename matches nothing: every package
    has a `utils.py`."""
    cited, gold = _norm(cited), _norm(gold)
    if cited == gold:
        return True
    shorter = min(cited, gold, key=len)
    return "/" in shorter and (gold.endswith("/" + cited) or cited.endswith("/" + gold))


def cited_refs(finding: dict) -> list[tuple[str, int]]:
    """Every `path:line` the finding cites: the anchors finalize took from its
    evidence and class sites, plus references in the prose fields it does not anchor."""
    refs = []
    for a in finding.get("anchors") or []:
        if isinstance(a, dict) and a.get("path") and a.get("line"):
            refs.append((str(a["path"]), int(a["line"])))
    rc = finding.get("root_cause") if isinstance(finding.get("root_cause"), dict) else {}
    prose = [str(finding.get("title") or ""), str(rc.get("mechanism") or ""),
             str(rc.get("origin") or "")]
    for path, line in refs_in(prose):
        refs.append((path, int(line)))
    seen, out = set(), []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def checkout_source(checkout: Path):
    """`source_of` for a live checkout: the file's text at base, or None."""
    def source_of(path: str):
        p = checkout / path
        return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
    return source_of


def mirror_source(repo: str, base: str):
    """`source_of` for a re-score after the checkout is gone: the file at the base
    commit, read from the repository mirror."""
    mirror = mirror_of(repo)

    def source_of(path: str):
        proc = sh(["git", "show", f"{base}:{path}"], cwd=mirror)
        return proc.stdout if proc.returncode == 0 else None
    return source_of


def level_of(refs, gold: dict, source_of=None) -> tuple[str, list[str]]:
    """The best location match over a finding's references, and the matched refs.
    `source_of(path)` returns the file's text at base for the function grade."""
    best, matched = "none", []
    spans_cache: dict[str, list] = {}
    for path, line in refs:
        for gpath, hunks in gold.items():
            if not _same_file(path, gpath):
                continue
            level = "file"
            if any(s - HUNK_SLACK <= line <= e + HUNK_SLACK for s, e in hunks):
                level = "hunk"
            if source_of is not None:
                if gpath not in spans_cache:
                    text = source_of(gpath)
                    try:
                        spans_cache[gpath] = _spans(text) if text is not None else []
                    except SyntaxError:
                        spans_cache[gpath] = []
                spans = spans_cache[gpath]
                mine = enclosing(spans, line)
                if mine is not None:
                    theirs = {enclosing(spans, ln) for s, e in hunks for ln in range(s, e + 1)}
                    if mine in theirs:
                        level = "function"
            if LEVELS.index(level) > LEVELS.index(best):
                best = level
            if level != "none":
                matched.append(f"{path}:{line} → {level}")
    return best, matched


def headline_of(findings: list[dict]) -> dict | None:
    if not findings:
        return None
    return max(findings, key=lambda f: (SEVERITY_RANK.get(str(f.get("severity")), 0),
                                        -findings.index(f)))


def score_instance(inst: dict, qa_root: Path, source_of=None) -> dict:
    out = {"verdict": None, "findings": 0, "any_hit": "none", "headline_hit": "none",
           "headline": None, "per_finding": [], "harness": None, "run_number": None,
           "report": None, "prompt_sha256": None, "state": "missing"}
    state_file = qa_root / "state.json"
    if not state_file.is_file():
        return out
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out["state"] = f"unreadable: {exc}"
        return out
    out["state"] = "read"
    out["verdict"] = state.get("verdict")
    out["run_number"] = state.get("run_number")
    last = state.get("last_run") or {}
    out["report"] = last.get("report")
    who = last.get("harness") if isinstance(last.get("harness"), dict) else {}
    out["harness"] = {"version": who.get("version"),
                      "provisioned_prompt_sha256": who.get("provisioned_prompt_sha256")}
    out["prompt_sha256"] = who.get("provisioned_prompt_sha256") or who.get("prompt_sha256")
    findings = [f for f in state.get("findings") or [] if isinstance(f, dict)
                and str(f.get("status") or "open") == "open"]
    out["findings"] = len(findings)
    gold = inst["gold_hunks"]
    head = headline_of(findings)
    for f in findings:
        level, matched = level_of(cited_refs(f), gold, source_of)
        row = {"id": f.get("id"), "severity": f.get("severity"), "confidence": f.get("confidence"),
               "classification": f.get("failure_classification"), "hit": level,
               "matched": matched, "title": str(f.get("title") or "")[:160],
               "cited": sorted({p for p, _ in cited_refs(f)})}
        out["per_finding"].append(row)
        if LEVELS.index(level) > LEVELS.index(out["any_hit"]):
            out["any_hit"] = level
        if head is not None and f is head:
            out["headline_hit"] = level
            out["headline"] = row["id"]
    return out


# ── one instance, end to end ──────────────────────────────────────────────────

def done_ids() -> set[str]:
    if not RESULTS.is_file():
        return set()
    ids = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                ids.add(json.loads(line)["instance_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return ids


def append_result(row: dict) -> None:
    """Append; a retried instance keeps its earlier rows too, and `load_results`
    reads the latest — the ledger is a history, the table is the present."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def archive(inst: dict, info: dict) -> Path:
    dest = CACHE / "runs" / inst["instance_id"]
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    qa_root = Path(info["qa_home"]) / info["key"]
    if qa_root.is_dir():
        shutil.copytree(qa_root, dest / "qa")
    logs = Path(info["work"]) / "logs"
    if logs.is_dir():
        shutil.copytree(logs, dest / "logs")
    prompt = Path(info["work"]) / "prompt.md"
    if prompt.is_file():
        shutil.copyfile(prompt, dest / "prompt.md")
    return dest


def one(inst: dict, args, root: Path) -> dict:
    iid = inst["instance_id"]
    print(f"== {iid} ({inst['repo']} {inst['version']}, {inst['difficulty']})", file=sys.stderr)
    row = row_for(iid)
    result = {"instance_id": iid, "repo": inst["repo"], "version": inst["version"],
              "difficulty": inst["difficulty"], "gold_files": inst["gold_files"],
              "model": args.model, "plugin_root": str(root), "plugin_version": plugin_version(root),
              "started_at": now_utc(), "status": "pending"}
    try:
        info = prepare(inst, row, keep_existing=args.reuse)
    except Exception as exc:                        # noqa: BLE001 — published, not hidden
        result.update(status="prepare_failed", note=str(exc)[-600:])
        return result
    result["env"] = {"valid": info["env_valid"], "check": info["env_check"],
                     "notes": info["env_notes"], "base_date": info.get("base_date")}
    if not info["env_valid"]:
        result.update(status="env_invalid", note=info["env_check"])
        cleanup(info, args.keep)
        return result

    attempt, run = 0, None
    while attempt < 3:
        attempt += 1
        run = run_instance(inst, row, info, root, args.model, args.timeout_s, attempt,
                           extra_env=getattr(args, "_env", None))
        qa_root = Path(info["qa_home"]) / info["key"]
        if (qa_root / "state.json").is_file() or not run["session_limited"]:
            break

        wait = seconds_until_reset(run["output"]) or 3600
        print(f"  session limit and no state — waiting {wait}s (attempt {attempt})",
              file=sys.stderr)
        time.sleep(wait)
    output = run.pop("output", "")
    run["transcript"] = transcript_usage(Path(info["checkout"]), run.get("session_id"),
                                         (args._env or {}).get("CLAUDE_CONFIG_DIR"))
    result["run"] = run
    result["attempts"] = attempt
    qa_root = Path(info["qa_home"]) / info["key"]
    score = score_instance(inst, qa_root, checkout_source(Path(info["checkout"])))
    result["score"] = score
    if score["state"] != "read":
        result["status"] = "no_state"
        result["note"] = (score["state"] if score["state"] != "missing"
                          else "the run wrote no state" + (" (session limit)" if run["session_limited"]
                                                          else ""))
    elif score["verdict"] == "blocked":
        result["status"] = "blocked"
    else:
        result["status"] = "scored"
    result["archive"] = str(archive(inst, info))
    result["finished_at"] = now_utc()
    m = re.search(r"verdict-run: verdict .*", output)
    if m:
        result["runner_line"] = m.group(0)[:200]
    cleanup(info, args.keep)
    return result


def plugin_version(root: Path) -> str | None:
    manifest = root / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        return None


def cleanup(info: dict, keep: bool) -> None:
    if keep:
        print(f"  workdir kept: {info['work']}", file=sys.stderr)
        return
    for sub in ("checkout", "venv", "scratch"):
        shutil.rmtree(Path(info["work"]) / sub, ignore_errors=True)


def resolve_root(explicit) -> Path:
    """The plugin under test: an explicit root, else the newest version in the
    plugin cache — the SHIPPED plugin, never the checkout this script sits in,
    which may be mid-edit while a run is alive."""
    if explicit:
        root = plugin_root(explicit)
        if root is None:
            raise SystemExit(f"swebench: {explicit!r} has no agents/verdict.md + hooks/hooks.json")
        return root
    cache = Path.home() / ".claude" / "plugins" / "cache" / "verdict" / "verdict"
    versions = [p for p in cache.iterdir()
                if (p / "agents" / "verdict.md").is_file()] if cache.is_dir() else []
    if not versions:
        raise SystemExit("swebench: no installed plugin in the cache — pass --plugin-root")
    return max(versions, key=lambda p: [int(x) if x.isdigit() else -1 for x in p.name.split(".")])


def cmd_prepare(args) -> int:
    """Checkout, environment, validation and profile — no model run. The
    environment step of a pilot, and the way to inspect a checkout by hand."""
    pool = {i["instance_id"]: i for i in instances()}
    if args.instance not in pool:
        raise SystemExit(f"swebench: {args.instance!r} is not in the selected set")
    inst = pool[args.instance]
    info = prepare(inst, row_for(args.instance), keep_existing=args.reuse)
    print(json.dumps(info, indent=2))
    return 0 if info["env_valid"] else 1


def cmd_run(args) -> int:
    root = resolve_root(args.plugin_root)
    print(f"plugin root: {root} ({plugin_version(root) or 'unversioned'})", file=sys.stderr)
    pool = {i["instance_id"]: i for i in instances()}
    if args.instance not in pool:
        raise SystemExit(f"swebench: {args.instance!r} is not in the selected set")
    result = one(pool[args.instance], args, root)
    if not args.dry:
        append_result(result)
    print(json.dumps({k: v for k, v in result.items() if k != "score"} | {
        "score": {k: v for k, v in (result.get("score") or {}).items() if k != "per_finding"}},
        indent=2))
    return 0


def rewrite_result(row: dict) -> None:
    """Replace the instance's row in the ledger (the rescore path)."""
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    out = [r for r in rows if r.get("instance_id") != row["instance_id"]] + [row]
    RESULTS.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in out),
                       encoding="utf-8")


def cmd_rescore(args) -> int:
    """Re-grade archived runs with the current scorer — no model, no checkout:
    the base files come from the mirror. What `rescore-0840.py` was for the
    fixture keys, as a subcommand."""
    pool = {i["instance_id"]: i for i in instances()}
    rows = {r["instance_id"]: r for r in load_results()}
    targets = args.instances or sorted(rows)
    for iid in targets:
        row, inst = rows.get(iid), pool.get(iid)
        if row is None or inst is None:
            print(f"  {iid}: no result row or not in the set — skipped", file=sys.stderr)
            continue
        qa = Path(row.get("archive") or CACHE / "runs" / iid) / "qa"
        if not qa.is_dir():
            print(f"  {iid}: no archived QA root — skipped", file=sys.stderr)
            continue
        before = (row.get("score") or {}).get("any_hit"), (row.get("score") or {}).get("headline_hit")
        row["score"] = score_instance(inst, qa, mirror_source(inst["repo"], inst["base_commit"]))
        run = row.get("run") or {}
        if run.get("session_id"):
            checkout = Path(CACHE / "work" / iid / iid)
            usage = transcript_usage(checkout, run["session_id"])
            if usage:
                run["transcript"] = usage
        row["rescored_at"] = now_utc()
        rewrite_result(row)
        after = row["score"]["any_hit"], row["score"]["headline_hit"]
        print(f"  {iid}: {before} → {after}", file=sys.stderr)
    return 0


def cmd_batch(args) -> int:
    root = resolve_root(args.plugin_root)
    print(f"plugin root: {root} ({plugin_version(root) or 'unversioned'})", file=sys.stderr)
    done = done_ids() if not args.redo else set()
    if args.retry:
        # Rows whose status names an environment or a lost run, not a verdict —
        # the instance goes again once the harness has been fixed.
        retry = {r["instance_id"] for r in load_results() if r.get("status") in args.retry}
        done -= retry
    todo = [i for i in instances() if i["instance_id"] not in done]
    if args.only:
        todo = [i for i in todo if i["repo"] in args.only or i["instance_id"] in args.only]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(todo)} instance(s) to run, {len(done)} already in results", file=sys.stderr)
    stop = CACHE / "STOP"
    for n, inst in enumerate(todo, 1):
        if stop.exists():
            print("STOP file present — stopping before the next instance", file=sys.stderr)
            break
        print(f"[{n}/{len(todo)}]", file=sys.stderr)
        result = one(inst, args, root)
        append_result(result)
        if (result.get("run") or {}).get("limit") == "weekly":
            # The allowance is gone for days. Every remaining instance would fail
            # the same way and be written into the ledger as a run that never ran.
            print("weekly limit reached — stopping the batch; resume with the same "
                  "command once it resets", file=sys.stderr)
            break
        s = result.get("score") or {}
        print(f"  → {result['status']}: any {s.get('any_hit')}, headline {s.get('headline_hit')}, "
              f"{s.get('findings')} finding(s), {(result.get('run') or {}).get('wall_s')}s",
              file=sys.stderr)
    return 0


# ── the table ─────────────────────────────────────────────────────────────────

def load_results() -> list[dict]:
    rows = []
    if RESULTS.is_file():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["instance_id"]] = r          # a redo replaces the earlier row
    return list(latest.values())


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}" + (f" ({100 * n // d}%)" if d else "")


def _at_least(row: dict, key: str, level: str) -> bool:
    return LEVELS.index(row["score"][key]) >= LEVELS.index(level)


def render_table(rows: list[dict]) -> str:
    scored = [r for r in rows if r.get("status") == "scored"]
    ran = [r for r in rows if r.get("status") in ("scored", "blocked", "no_state")]
    lines = []
    lines.append(f"Instances attempted: {len(rows)} · ran: {len(ran)} · scored: {len(scored)}")
    for level in ("function", "hunk", "file"):
        lines.append(f"- located at `{level}` or better — any finding: "
                     f"{_pct(sum(_at_least(r, 'any_hit', level) for r in scored), len(scored))}; "
                     f"headline finding: "
                     f"{_pct(sum(_at_least(r, 'headline_hit', level) for r in scored), len(scored))}")
    walls = [r["run"]["wall_s"] for r in ran if r.get("run") and r["run"].get("wall_s")]
    costs = [r["run"]["cost_usd"] for r in ran if r.get("run") and r["run"].get("cost_usd")]
    if walls:
        lines.append(f"- wall time per run: median {sorted(walls)[len(walls) // 2] // 60} min, "
                     f"max {max(walls) // 60} min; total {sum(walls) // 3600}h{(sum(walls) % 3600) // 60:02d}")
    if costs:
        lines.append(f"- cost per run (CLI-reported): median ${sorted(costs)[len(costs) // 2]:.2f}, "
                     f"total ${sum(costs):.2f}")
    outs = [r["run"]["transcript"]["output_tokens"] for r in ran
            if (r.get("run") or {}).get("transcript")]
    if outs:
        lines.append(f"- output tokens per run (whole session, from the transcript): median "
                     f"{sorted(outs)[len(outs) // 2] // 1000}k, total {sum(outs) // 1000}k")
    lines.append("")
    lines.append("| Instance | Difficulty | Status | Findings | Any | Headline | Wall | Output tok | Cost |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: (REPO_ORDER.index(r["repo"]) if r["repo"] in REPO_ORDER
                                         else 99, r["instance_id"])):
        s, run = r.get("score") or {}, r.get("run") or {}
        wall = f"{run['wall_s'] // 60} min" if run.get("wall_s") else "—"
        cost = f"${run['cost_usd']:.2f}" if run.get("cost_usd") else "—"
        tok = f"{run['transcript']['output_tokens'] // 1000}k" if run.get("transcript") else "—"
        lines.append(f"| {r['instance_id']} | {r['difficulty']} | {r['status']} | "
                     f"{s.get('findings', '—')} | {s.get('any_hit', '—')} | "
                     f"{s.get('headline_hit', '—')} | {wall} | {tok} | {cost} |")
    by_diff: dict[str, list] = {}
    for r in scored:
        by_diff.setdefault(r["difficulty"], []).append(r)
    if by_diff:
        lines.append("")
        lines.append("| Difficulty | Scored | Any ≥ hunk | Headline ≥ hunk |")
        lines.append("|---|---|---|---|")
        for diff, group in sorted(by_diff.items()):
            anyh = sum(_at_least(r, "any_hit", "hunk") for r in group)
            headh = sum(_at_least(r, "headline_hit", "hunk") for r in group)
            lines.append(f"| {diff} | {len(group)} | {_pct(anyh, len(group))} | "
                         f"{_pct(headh, len(group))} |")
    misses = [r for r in scored if r["score"]["headline_hit"] == "none"]
    if misses:
        lines.append("")
        lines.append("Misses — what the headline finding said instead (mechanism is not "
                     "machine-scored; judge the near-misses yourself):")
        for r in misses:
            s = r["score"]
            head = next((f for f in s.get("per_finding", []) if f["id"] == s.get("headline")),
                        None)
            if head is None:
                lines.append(f"- {r['instance_id']}: no finding filed; gold "
                             f"{', '.join(r.get('gold_files', []))}")
                continue
            lines.append(f"- {r['instance_id']} ({s['any_hit']} at best): {head['severity']} "
                         f"\"{head['title']}\" — cited {', '.join(head['cited']) or 'nothing'}; "
                         f"gold {', '.join(r.get('gold_files', []))}")
    unrun = [r for r in rows if r.get("status") not in ("scored",)]
    if unrun:
        lines.append("")
        lines.append("Not scored:")
        for r in unrun:
            lines.append(f"- {r['instance_id']}: {r['status']} — {str(r.get('note') or '')[:160]}")
    return "\n".join(lines) + "\n"


def cmd_table(args) -> int:
    rows = load_results()
    if not rows:
        print("no results yet")
        return 0
    print(render_table(rows))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("select", help="write the instance set")
    pp = sub.add_parser("prepare", help="checkout + environment + validation, no model run")
    pp.add_argument("instance")
    pp.add_argument("--reuse", action="store_true", help="reuse an existing workdir")
    for name in ("run", "batch"):
        p = sub.add_parser(name)
        if name == "run":
            p.add_argument("instance")
        else:
            p.add_argument("--limit", type=int, default=0)
            p.add_argument("--only", nargs="*", default=None, help="repositories or instance ids")
            p.add_argument("--redo", action="store_true", help="ignore existing results")
            p.add_argument("--retry", nargs="*", default=None, metavar="STATUS",
                           help="re-run instances whose latest row has one of these statuses "
                                "(env_invalid, prepare_failed, no_state, blocked)")
        p.add_argument("--model", default="opus")
        p.add_argument("--env-file", type=Path, default=None, metavar="PATH",
                       help="KEY=VALUE file loaded into each run's environment: "
                            "CLAUDE_CONFIG_DIR to spend a second account's allowance, or "
                            "ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN for a gateway")
        p.add_argument("--timeout-s", type=int, default=2700)
        p.add_argument("--plugin-root", default=None)
        p.add_argument("--keep", action="store_true", help="keep the checkout and venv")
        p.add_argument("--reuse", action="store_true", help="reuse an existing workdir")
        p.add_argument("--dry", action="store_true", help="do not append to results.jsonl")
    sub.add_parser("table", help="render results.jsonl as markdown")
    rs = sub.add_parser("rescore", help="re-grade archived runs with the current scorer")
    rs.add_argument("instances", nargs="*")
    args = ap.parse_args(argv)
    args._env = {}
    if getattr(args, "env_file", None):
        if not args.env_file.is_file():
            ap.error(f"--env-file {args.env_file} does not exist")
        args._env = read_env_file(args.env_file)
        where = args._env.get("ANTHROPIC_BASE_URL") or args._env.get("CLAUDE_CONFIG_DIR")
        print(f"swebench: environment from {args.env_file} ({where})", file=sys.stderr)
    if args.cmd == "select":
        return cmd_select(args)
    if args.cmd == "prepare":
        return cmd_prepare(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "batch":
        return cmd_batch(args)
    if args.cmd == "rescore":
        return cmd_rescore(args)
    return cmd_table(args)


if __name__ == "__main__":
    sys.exit(main())
