"""The suite, before anything is read: failures and reruns, unstable tests, brittle tests,
and failures classified with or without the model.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .reports import read_report
    from .local_model import Model
    from .local_chunks import chunks_of
    from .local_questions import capped_failure
    from .local_skips import test_files
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from reports import read_report
    from local_model import Model
    from local_chunks import chunks_of
    from local_questions import capped_failure
    from local_skips import test_files


# ── the suite: what execution says, before anything is read ───────────────────


GATE_DEFAULT = "python3 -m pytest -q -p no:cacheprovider --junitxml={report}"


QUARANTINE_DAYS = 14


def failures_of(facts: dict) -> list:
    """Per-test failures from the gate's report file — id, kind and message.

    Read from JUnit XML rather than from the summary line, because a classification
    needs the assertion text, and a dialect guess does not carry it.
    """
    out = []
    for gate in (facts.get("gates") or {}).values():
        report = gate.get("report") if isinstance(gate, dict) else None
        for f in (report or {}).get("failures") or []:
            if isinstance(f, dict) and f.get("id"):
                out.append({"id": str(f["id"]), "kind": str(f.get("kind") or "failure"),
                            "message": str(f.get("message") or "")[:600]})
    return out


def rerun_failures(repo: Path, command: str, times: int) -> list:
    """Run the suite again and return each run's failing set.

    Flakiness is a property of repetition, and repetition is arithmetic — no model is
    asked whether a test is flaky, because running it twice answers that exactly.
    """
    sets = []
    for _ in range(max(0, times)):
        with tempfile.TemporaryDirectory(prefix="verdict-local-") as scratch:
            path = Path(scratch) / "report.xml"
            rendered = command.replace("{report}", str(path))
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            subprocess.run(rendered, cwd=repo, env=env, shell=True, capture_output=True,
                           text=True, timeout=1800)
            sets.append(ids_in_report(path))
    return sets


def ids_in_report(path: Path) -> set:
    """The failing ids in a report the gate wrote, in the harness's own id shape.

    Parsing it here a second time was the bug: a rerun's ids did not match the ids in
    `facts`, every set difference was total, and all three failures were reported as
    unstable. One parser, one shape.
    """
    summary, _ = read_report(path)
    return {f["id"] for f in (summary.get("failures") or []) if f.get("id")}


def unstable(first: list, repeats: list) -> set:
    """Ids that failed in some runs and not others — flaky by measurement."""
    runs = [set(f["id"] for f in first)] + [set(r) for r in repeats]
    if len(runs) < 2:
        return set()
    union, common = set().union(*runs), set.intersection(*runs)
    return {i for i in union - common}


BRITTLE_Q = """You are a software tester reading one test that currently passes.

File: {path}
```python
{source}
```

Is this test brittle — does it assert something incidental that would break on a harmless
change? Look for: an exact error message compared with `==`, a hard-coded timestamp or
path, an assertion on formatting or ordering that is not part of the contract, a mock
asserting its own return value, an assertion that cannot fail.

A test that asserts the behaviour it is named for is NOT brittle. Say so.

Reply with JSON only:
{{"brittle": true or false,
  "line": <the line number from the left margin above, or null>,
  "why": "<one sentence: what it asserts that it should not>"}}"""


def brittle_findings(model: Model, repo: Path, files: list, mint, findings_dir: Path,
                     filed: list, budget, leads: list | None = None) -> int:
    """One bounded question per passing test — the suite is under review too, and a green
    test asserting the wrong thing is invisible to every gate.

    It shares the run's budget with the source reading, and comes after it: when
    the cap bites, what goes unread is the suite, not the change.
    """
    examined = 0
    for rel in files:
        for chunk in chunks_of(repo, rel):
            if not chunk.name.startswith("test"):
                continue
            if not budget.take_function():
                continue
            examined += 1
            answer = model.ask_json(BRITTLE_Q.format(path=rel, source=chunk.numbered()),
                                    max_tokens=600)
            if not answer or answer.get("brittle") is not True:
                continue
            why = str(answer.get("why") or "").strip()
            if len(why) < 12:
                continue
            line = answer.get("line")
            line = int(line) if isinstance(line, (int, float)) and chunk.start <= line <= chunk.end \
                else chunk.start
            if leads is not None:
                # A green test a small model thinks is brittle is an opinion about a
                # test that passes — nothing executed disagrees with it.
                leads.append({"path": rel, "line": line, "function": chunk.name,
                              "title": f"{chunk.name} may assert something incidental: {why}"[:200],
                              "severity": "Minor", "why": "an opinion about a passing test"})
                continue
            mint({
                "id": "@", "title": f"{chunk.name} asserts something incidental: {why}"[:200],
                "severity": "Minor", "priority": "P2", "status": "open",
                "failure_classification": "BRITTLE_TEST", "confidence": "hypothesis",
                "evidence": [f"{rel}:{line} — {why}",
                             "read by a small model; the test passes today, so nothing "
                             "executed disagrees with it"],
                "root_cause": {"mechanism": why, "origin": "not investigated in local mode"},
                "narrative": f"{why} A test like this fails on a change that harms nobody, "
                             "and passing it is not evidence the behaviour is right.",
            }, findings_dir, filed)
    return examined


CLASSIFY_FAILURE_Q = """You are a software tester classifying one failing test.

Failing test: {id}
Error:
{message}

The test:
```python
{test_source}
```
{context}
Classify the failure. Use exactly one of:
- REAL_DEFECT: the code is wrong.
- STALE_EXPECTATION: the code changed on purpose and the test was not updated. Only if the
  documentation or changelog excerpt above authorises the change.
- BRITTLE_TEST: the code is right; the test asserts something too exact or incidental.
- ENVIRONMENT: nothing is wrong with the code or the test — a file, dependency or service
  the test needs is absent.

Reply with JSON only:
{{"classification": "REAL_DEFECT" or "STALE_EXPECTATION" or "BRITTLE_TEST" or "ENVIRONMENT",
  "severity": "Blocker" or "Critical" or "Major" or "Minor" or "Trivial",
  "title": "<one sentence naming the problem and its consequence, under 120 characters>",
  "mechanism": "<one sentence: why the test fails>"}}"""


def source_of_test(repo: Path, test_id: str) -> tuple:
    """(file, source) for a failing test id, by name — the id's own path when it has
    one, otherwise the first test file that defines that function."""
    name = test_id.rsplit("::", 1)[-1].split("[")[0]
    for rel in test_files(repo):
        for chunk in chunks_of(repo, rel):
            if chunk.name == name:
                return rel, chunk.numbered()
    return "", ""


def changelog_excerpt(repo: Path, words: list) -> str:
    """The lines of a CHANGELOG that mention what the failing test is about.

    A STALE_EXPECTATION is the classification most likely to excuse a regression, so the
    contract demands a citation for it. Local mode hands the model the candidate lines
    and keeps them as the evidence if the answer uses them.
    """
    for name in ("CHANGELOG.md", "CHANGELOG", "CHANGES.md", "HISTORY.rst"):
        path = repo / name
        if not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        hits = [f"{name}:{i + 1} — {line.strip()}" for i, line in enumerate(lines)
                if line.strip() and any(w.lower() in line.lower() for w in words if len(w) > 3)]
        if hits:
            return "\n".join(hits[:6])
    return ""


ENVIRONMENT_ERRORS = ("FileNotFoundError", "ModuleNotFoundError", "ImportError",
                      "ConnectionError", "ConnectionRefused", "PermissionError",
                      "OSError: [Errno", "No such file or directory",
                      "could not connect", "Address already in use")


def deterministic_kind(message: str) -> str | None:
    """The classification the error text already states.

    A `FileNotFoundError` is an environment failure by definition, and asking a model to
    agree is a call spent to learn nothing — and, when the reply is not JSON twice, a
    finding lost. Measured: the small model's answers parse about half the time, so the
    cheap deterministic path is also the reliable one.
    """
    for needle in ENVIRONMENT_ERRORS:
        if needle.lower() in (message or "").lower():
            return "ENVIRONMENT"
    return None


def words_of(*texts) -> list:
    """Identifier-aware words: `test_net_proceeds_hundred` is four words, and the
    changelog entry that authorises a change says "fee", not the test's name."""
    out = []
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z_]{2,}", text or ""):
            out.append(token)
            out.extend(part for part in token.split("_") if len(part) > 3)
    seen, unique = set(), []
    for word in out:
        low = word.lower()
        if low not in seen:
            seen.add(low)
            unique.append(word)
    return unique


def classify(model: Model, repo: Path, failure: dict) -> dict | None:
    rel, test_source = source_of_test(repo, failure["id"])
    settled = deterministic_kind(failure["message"])
    if settled:
        first = failure["message"].strip().splitlines()[0][:120]
        return {"id": failure["id"], "path": rel or failure["id"].split("::")[0],
                "classification": settled, "severity": "Major",
                "title": f"{failure['id']} cannot run here: {first}"[:200],
                "mechanism": f"The failure is {first} — the test needs something the "
                             "environment does not provide, so it says nothing about the "
                             "code.",
                "message": failure["message"], "excerpt": "",
                "settled_by": "the error class, not a model"}
    # The test's own source carries the words that matter — its comment naming the rule,
    # the function it calls. The id and the assertion alone never found the entry.
    words = words_of(test_source, failure["id"], failure["message"])
    excerpt = changelog_excerpt(repo, words[:24])
    context = (f"\nChangelog lines that mention it:\n{excerpt}\n" if excerpt else "\n")
    answer = model.ask_json(CLASSIFY_FAILURE_Q.format(
        id=failure["id"], message=failure["message"], test_source=test_source or "(not found)",
        context=context), max_tokens=800)
    if not answer:
        return None
    kind = str(answer.get("classification") or "")
    if kind not in ("REAL_DEFECT", "STALE_EXPECTATION", "BRITTLE_TEST", "ENVIRONMENT"):
        return None
    severity = str(answer.get("severity") or "Major")
    if severity not in ("Blocker", "Critical", "Major", "Minor", "Trivial"):
        severity = "Major"
    return {"id": failure["id"], "path": rel or failure["id"].split("::")[0],
            "classification": kind, "severity": severity,
            "title": str(answer.get("title") or "").strip()[:200] or f"{failure['id']} fails",
            "mechanism": str(answer.get("mechanism") or "").strip(),
            "message": failure["message"], "excerpt": excerpt}


def failure_finding(claim: dict, ident: str) -> dict:
    """A classified failure becomes a finding. `STALE_EXPECTATION` carries the changelog
    lines it rests on, because that is the classification the contract will not accept
    without a citation."""
    evidence = [f"{claim['id']} fails at HEAD: {claim['message'][:300]}"]
    if claim["excerpt"]:
        evidence.append("intent citation — " + claim["excerpt"].replace("\n", " · ")[:400])
    evidence.append(f"classified by {claim.get('settled_by', 'a small model')} from the "
                    "failure text and the test source; no counterfactual was applied")
    severity = capped_failure(claim["severity"])
    held = (f" The model said {claim['severity']}; unproven, it is held at {severity}."
            if severity != claim["severity"] else "")
    return {
        "id": ident, "title": claim["title"], "severity": severity,
        "priority": "P1" if severity in ("Blocker", "Critical", "Major") else "P2",
        "status": "open", "failure_classification": claim["classification"],
        "confidence": "hypothesis", "evidence": evidence,
        "root_cause": {"mechanism": claim["mechanism"] or claim["title"],
                       "origin": "not investigated in local mode"},
        "narrative": (f"{claim['mechanism']} Filed by `verdict-local` from the failing test "
                      "and its error text. Nothing was executed to confirm it beyond the "
                      f"suite run itself.{held}"),
    }


def flaky_finding(entry: dict, runs: int, ident: str) -> dict:
    """A test measured unstable is a finding as well as a quarantine — the quarantine
    stops it blocking a release, the finding is what somebody has to fix."""
    return {
        "id": ident,
        "title": f"{entry['test_id']} is not deterministic: it failed in some of {runs} "
                 f"identical runs and passed in others"[:200],
        "severity": "Major", "priority": "P2", "status": "open",
        "failure_classification": "FLAKY", "confidence": "proven",
        "evidence": [f"{entry['test_id']} — outcome differed across {runs} runs of the same "
                     "command on the same commit, with no change in between",
                     f"quarantined until {entry['quarantined_until']} by measurement, not by "
                     "judgement"],
        "root_cause": {"mechanism": "The test's outcome depends on something that varies "
                                    "between runs — a clock, a random value, an ordering, or "
                                    "state left by another test.",
                       "origin": "not investigated in local mode"},
        "narrative": "Measured by repetition: the same command on the same commit produced "
                     "different results. A test that cannot decide is not evidence either way.",
    }


def focus_finding(mark: dict, ident: str) -> dict:
    """A committed `it.only`, `fit` or `fdescribe`: the suite runs that test and silently drops
    every other one in its file (in Mocha's case, in the whole run), and stays green."""
    lines = mark.get("lines") or [mark["line"]]
    return {
        "id": ident,
        "title": f"A focused test switches off the rest of its suite: {mark['reason'][:80]}"[:200],
        "severity": "Minor", "priority": "P2", "status": "open",
        "failure_classification": "BRITTLE_TEST", "confidence": "proven",
        "evidence": [f"{mark['path']}:{line} — focus marker (`.only`, `fit`, `fdescribe` or "
                     f"`only: true`) on {mark['reason'][:200]!r}" for line in lines]
                    + ["found by a regular expression over the test files, not by a model"],
        "root_cause": {"mechanism": "A focus marker left in committed code makes the runner "
                                    "execute only the focused tests; every other test in its "
                                    "scope is skipped without a failure.",
                       "origin": "not investigated in local mode"},
        "narrative": "A focused test narrows the suite to itself while the run stays green. "
                     "Remove the focus marker.",
    }
