"""The project's environment: the interpreter its runner uses, whether probes are off,
plaintext env files, facts a run can reuse, and the measurement step.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from .anchors import refs_in
    from .harness import RETRY_WINDOW_HOURS, _git, _parse_marker_time, collect, split_hygiene
    from .filed import archive_findings
    from .profile import assertion_gaps_from, risk_paths_from, hygiene_filing_from
    from .state import norm_status
    from . import clock
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from anchors import refs_in
    from harness import RETRY_WINDOW_HOURS, _git, _parse_marker_time, collect, split_hygiene
    from filed import archive_findings
    from profile import assertion_gaps_from, risk_paths_from, hygiene_filing_from
    from state import norm_status


# The name this engine signs its runs with, in `last_run.engine`, the run marker
# and the report's Judge line. A state that does not say who judged it reads the
# same whether an Opus session or an 8B model on the desk wrote it.
ENGINE = "verdict-local"


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


_PYTHON_NAME = re.compile(r"^(?:python|pypy)[0-9.]*w?(?:\.exe)?$")


_PY_TOOLS = frozenset({"pytest", "py.test", "coverage", "pytest.exe", "coverage.exe"})


_RUNNERS = frozenset({"uv", "poetry", "pipenv", "pdm", "hatch", "rye"})


_RUNNER_PYTHON: dict = {}           # (runner, repo) → what `<runner> run python` is, or None


RUNNER_TIMEOUT_S = 30


def interpreter_of(command: str, repo=None) -> str | None:
    """The python the project's own gate runs — or None when the gate runs none.

    A probe run with a different interpreter is measuring a different environment.
    Measured 2026-10-02 (audit O-D-11): only a token ending in `python` was recognised, so
    `uv run pytest`, `.venv/bin/pytest` and `npm test` all fell back to Verdict's own
    interpreter, every probe died on the first third-party import, and the run reported
    "probe failed on the original" as the model's failure to prove. Now `<dir>/bin/pytest`
    is `<dir>/bin/python`; `uv run …` (poetry, pipenv, pdm, hatch and rye the same) is asked
    once what it runs; a bare `pytest` or `python` is looked up on PATH; and a gate with no
    Python in it — `npm test`, `go test`, `cargo test` — is None, so the caller says proving
    is off instead of importing the project with the wrong interpreter.
    """
    tokens = _gate_tokens(command)
    for i, token in enumerate(tokens):
        if _ENV_ASSIGN.match(token):
            continue
        head, _, name = token.replace("\\", "/").rpartition("/")
        low = name.lower()
        if _PYTHON_NAME.match(low):
            return token if head else shutil.which(token)
        if low in _PY_TOOLS:
            found = token if head else shutil.which(token)
            return _python_beside(found) if found else None
        if low in _RUNNERS and tokens[i + 1:i + 2] == ["run"]:
            return runner_python(token, repo)
    return None


def _gate_tokens(command: str, windows: bool | None = None) -> list:
    """A gate command as words, a quoted path kept whole on either platform.

    On Windows this was `command.split()`: `"C:\\Program Files\\Python312\\python.exe" -m
    pytest` came apart at the space, no token ended in `python`, and the lookup fell
    through to whatever `pytest` was on PATH — Verdict's own, again (found by the first
    Windows CI run of 0.90.3). shlex's non-POSIX mode keeps a path's backslashes; it also
    keeps the quotes on a token, which come off here.
    """
    windows = (os.name == "nt") if windows is None else windows
    try:
        if not windows:
            return shlex.split(command)
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.split(command, posix=False)]
    except ValueError:
        return command.split()


def _python_beside(tool: str) -> str:
    """`<dir>/bin/pytest` → `<dir>/bin/python`; `Scripts/pytest.exe` → `Scripts/python.exe`."""
    head, _, name = tool.replace("\\", "/").rpartition("/")
    python = "python.exe" if name.lower().endswith(".exe") else "python"
    return f"{head}/{python}" if head else python


def runner_python(runner: str, repo) -> str | None:
    """What `<runner> run python` actually is, asked once per repository and remembered:
    the project's interpreter, not Verdict's, and it does not change within a run. A
    runner that cannot answer — not installed, no project, thirty seconds gone — is None,
    said on stderr, and the caller records that proving is off."""
    key = (runner, str(repo) if repo else "")
    if key not in _RUNNER_PYTHON:
        found, why = None, None
        try:
            proc = subprocess.run(
                [runner, "run", "python", "-c", "import sys; print(sys.executable)"],
                cwd=str(repo) if repo else None, capture_output=True, text=True,
                timeout=RUNNER_TIMEOUT_S)
            if proc.returncode == 0 and proc.stdout.strip():
                found = proc.stdout.strip().splitlines()[-1].strip()
            else:
                why = (proc.stderr.strip().splitlines() or [f"exit {proc.returncode}"])[-1][:160]
        except (OSError, subprocess.SubprocessError) as exc:
            why = str(exc)[:160]
        if not found:
            print(f"verdict-local: `{runner} run python` could not name the gate's interpreter "
                  f"({why}) — proving is disabled", file=sys.stderr)
        _RUNNER_PYTHON[key] = found
    return _RUNNER_PYTHON[key]


_PROBES_OFF = ("off", "false", "no")


def probes_off(config: dict, notes: list | None = None) -> bool:
    """The profile's `probes:` setting — `off`, `false` or `no` in any case switches the
    counterfactual off for the project, which is what a project whose public functions
    talk to live accounts sets (audit 2026-10-02, O-S-1 (4): Sales' share runners were
    among the modules the nightly asked the model to probe). Read the way `hygiene:` is:
    a value it cannot read leaves probes on and adds a note, because a typo must never
    pass for a setting that took."""
    value = config.get("probes")
    if isinstance(value, str):
        value = value.strip()
    if not value:
        return False
    if isinstance(value, str) and value.lower() in _PROBES_OFF:
        return True
    if isinstance(value, str) and value.lower() in ("on", "true", "yes"):
        return False
    if notes is not None:
        notes.append(f"probes: '{value}' is not understood — probes stay on")
    return False


def read_reference(path) -> dict | None:
    """Another root's `state.json`, opened to be READ.

    A branch run judges a throwaway QA root, which is what keeps it from writing
    over the project's real record — but it still wants to know which open
    findings the range touches, and that lives in the real state. So the file is
    read, once, here, and nothing downstream is ever handed the path: a function
    that cannot see a filename cannot open it for writing.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"verdict-local: --reference-state could not be read ({exc}); this range's "
              "relation to the project's open findings is unknown", file=sys.stderr)
        return None
    return doc if isinstance(doc, dict) else None


def touches_findings(reference: dict | None, changed) -> list:
    """Which open findings of the reference state cite a file this range touched."""
    paths = {str(c).replace("\\", "/") for c in changed or []}
    hit = []
    for f in (reference or {}).get("findings") or []:
        if not isinstance(f, dict) or norm_status(f.get("status")) != "open":
            continue
        cited = {str(a.get("path")).replace("\\", "/") for a in f.get("anchors") or []
                 if isinstance(a, dict) and a.get("path")}
        for ref, _line in refs_in([str(t) for t in (f.get("evidence") or [])]):
            cited.add(str(ref).replace("\\", "/"))
        if cited & paths:
            hit.append(str(f.get("id")))
    return hit


def read_json(path) -> dict | None:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


# The one isolation fact this engine can measure for any project before it runs a gate: a
# plaintext `.env` at the checkout root. With one there, a test run may reach live services
# with real keys — ifta-agent's profile makes it "every stateful task is blocked". Until
# 2026-10-15 every local report said "Isolation check: pass" from a literal in this file.
_ENV_NOT_SECRET = (".example", ".sample", ".template", ".dist", ".tmpl", ".sops", ".enc",
                   ".age", ".gpg")


def plaintext_env_files(repo: Path) -> list:
    """`.env*` files at the checkout root that are neither examples nor encrypted."""
    try:
        names = sorted(p.name for p in repo.iterdir() if p.name.startswith(".env") and p.is_file())
    except OSError:
        return []
    return [n for n in names
            if "example" not in n.lower() and not n.lower().endswith(_ENV_NOT_SECRET)]


# How old a facts.json may be and still describe "this run". verdict-run's sweep attempt
# measures minutes before this engine starts; the window is facts_main's own
# `--reuse-max-age-min` default.
REUSE_MAX_AGE_MIN = 90.0


def reusable_facts(repo: Path, qa_root: Path) -> dict | None:
    """facts.json, when it was measured for this same HEAD within the reuse window — else None.

    verdict-run tries the model-free sweep first, and the sweep's `verdict-facts` has
    already run the gates, the coverage suite and the fix re-runs, written the id
    ledger and staked the run marker for this commit. Measuring again cost a Sales
    night a second full suite and a second coverage suite (about ten minutes, measured
    2026-10-15), and it read the ledger the first measurement had just rewritten: 36
    tests added on ifta-agent were reported as "+0 / −0", and the tests collected for
    the first time — the one selection that lets a fix's own new regression test
    resolve a finding by measurement — came back empty every drift night.
    """
    facts = read_json(qa_root / "facts.json")
    if not isinstance(facts, dict):
        return None
    if (facts.get("last_run") or {}).get("git_sha") != _git(["rev-parse", "HEAD"], repo):
        return None
    measured = _parse_marker_time(facts.get("measured_at"))
    if measured is None:
        return None
    age_min = (clock.now() - measured).total_seconds() / 60
    if age_min < 0 or age_min > REUSE_MAX_AGE_MIN:
        return None
    return facts


def measure(repo: Path, qa_root: Path, gates: list, config: dict, sha_range,
            profile_notes: list, reuse: bool = False) -> dict:
    """The deterministic half, with the whole profile behind it.

    0.88.0 called `collect` with the gate command and nothing else, so
    `test_one_cmd`, `test_ids_cmd` and `coverage_suite_cmd` never reached it: no
    fix could be verified, no id ledger was written, and diff coverage was
    permanently unavailable. Each of those is a measurement this engine's safety
    rules rest on — a resolution needs a verified fix, a carried citation needs
    the id ledger it is checked against, and the reading order needs the changed
    lines nothing executed. The housekeeping `facts_main` does comes with them:
    the run marker before the gates, last run's finding files moved aside, and
    the collected ids written down. So does the profile's `hygiene:` setting,
    which 0.91.0 read in `facts_main` alone: `hygiene: off` filed nothing there
    and everything here, on the engine that runs every night. And the junk rows
    leave the facts for their own file, as they do there, before `run` writes
    facts.json for the first time.
    """
    filing = hygiene_filing_from(config, profile_notes)
    marker_path = qa_root / "run-in-progress.json"
    reused = reusable_facts(repo, qa_root) if reuse else None
    if reused is not None:
        # The measurement is this run's own, taken by the sweep attempt a moment ago:
        # its marker, its archived findings, its ledger and its hygiene split all
        # stand. Only the engine's name is this one's to add.
        marker_path.write_text(json.dumps({
            "started_utc": clock.stamp(), "repo": str(repo),
            "git_sha": (reused.get("last_run") or {}).get("git_sha"),
            "engine": ENGINE}, indent=2) + "\n", encoding="utf-8")
        if profile_notes:
            reused["profile_notes"] = list(dict.fromkeys(
                list(reused.get("profile_notes") or []) + list(profile_notes)))
        reused["reused"] = {"measured_at": reused.get("measured_at"),
                            "why": "measured for this same HEAD by verdict-run's sweep "
                                   "attempt; the gates, coverage and fix re-runs were not "
                                   "run a second time, and the test-id delta is that "
                                   "measurement's"}
        reused.setdefault("last_run", {})["engine"] = ENGINE
        return reused
    abandoned = read_json(marker_path)
    head = _git(["rev-parse", "HEAD"], repo)
    started = _parse_marker_time((abandoned or {}).get("started_utc")) if abandoned else None
    retry = bool(abandoned) and abandoned.get("git_sha") == head and started is not None \
        and (clock.now() - started).total_seconds() / 3600 <= RETRY_WINDOW_HOURS
    marker_path.write_text(json.dumps({
        "started_utc": clock.stamp(), "repo": str(repo), "git_sha": head,
        "engine": ENGINE}, indent=2) + "\n", encoding="utf-8")
    archived = archive_findings(qa_root, keep=retry)
    # The assertion-gap census, as verdict-facts runs it (0.91.1): without it this engine's
    # reading order and hints had nothing to steer by — measured 2026-10-17, a local run whose
    # profile said `assertion_gaps: on` carried no census at all.
    gaps_on, gaps_budget = assertion_gaps_from(config, profile_notes)
    facts = collect(repo, qa_root, gates, config.get("test_ids_cmd"), abandoned=abandoned,
                    test_one_cmd=config.get("test_one_cmd"),
                    coverage_suite_cmd=config.get("coverage_suite_cmd"), sha_range=sha_range,
                    hygiene_filing=filing,
                    assertion_gaps=({"test_one_cmd": config.get("test_one_cmd"), "budget_s": gaps_budget,
                                     "globs": risk_paths_from(config, [])} if gaps_on else None))
    facts.pop("_added_test_ids", None)
    ids = facts.pop("_test_ids", None)
    if ids is not None:
        (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    split_hygiene(facts, qa_root)
    if archived:
        facts["findings_archived"] = archived
    if profile_notes:
        facts["profile_notes"] = profile_notes
    facts.setdefault("last_run", {})["engine"] = ENGINE
    return facts
