#!/usr/bin/env python3
"""verdict-local — a QA run driven by the harness, with a small model as a subroutine.

The agent shape cannot shrink to a 7B model, and no amount of prompt tuning will make
it. Measured on this project's own runs: 38 model turns each re-reading ~53k tokens of
context, of which ~19k is fixed preamble (the 13k contract plus the measured facts)
before the investigation starts. A model with a 40k window has nothing left to think
with, and one served at 4k cannot even receive the system prompt.

So this mode inverts the control. Python does everything deterministic — measure the
gates, read coverage, list the source, slice it into functions, run a test, apply a
counterfactual in a scratch copy, validate the JSON, assemble the state — and the model
answers one bounded question at a time, with a few hundred tokens of context and a
schema it must fill. Nothing accumulates: each call is independent, so the context never
grows and a weak model is never asked to hold a plan in its head.

Measured 2026-09-08, `qwen3:8b` on a local Ollama behind a LiteLLM gateway: asked whether
each function in a module implements its own docstring, with 340 tokens of input, it
found two of the fixture's seeded defects — the `>` that should be `>=`, and `round()`
where the spec says half-up — in 30 seconds. That is the whole thesis: the judgment is
within reach of a small model; the 38-turn agent loop is not.

What is *not* claimed: this mode is not the agent. It has no exploratory charter, no
archaeology, no adversarial reading of the suite. It answers a fixed set of questions
well enough to file findings a person can act on, and it says so in the report.

Three shapes, all of them local:

    verdict-local --repo . --env-file ~/.config/gw.env            a first baseline
    verdict-local --repo . --delta --env-file ~/.config/gw.env    tonight's delta
    verdict-local --repo . --base main --qa-root /tmp/pr.qa ...   a branch, a PR

The delta is the one that took a release to get right. A cheap engine's real hazard
is not a wrong finding — a hypothesis held at Minor is cheap to check — it is the
*silence* of the findings it never mentions: `merge()` reads an unmentioned finding
as resolved, so a run that carried nothing forward closed a backlog it had never
looked at. So every prior open finding leaves a delta in one of exactly three
places: resolved by a measured fail→pass on a test somebody chose, carried by id
because its cited code is where it was, or re-filed under its own id because that
code changed and nothing here read the change. The invariant is asserted before
anything is finalized, and the verdict is monotone: this engine can make a verdict
worse or leave it alone, never better.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

try:
    from .anchors import line_sha, refs_in
    from .harness import (RETRY_WINDOW_HOURS, _git, _parse_marker_time, _run_test, collect,
                          finalize_main, finding_hash, is_test_file, split_hygiene)
    from .filed import FINDINGS_DIR, archive_findings
    from .profile import assertion_gaps_from, risk_paths_from, sandbox_from
    from .profile import ProfileError, gates_from, hygiene_filing_from
    from .profile import load as load_profile
    from . import sandbox
    from .reports import read_report
    from .project_key import derive_key
    from .state import home as state_home
    from .state import norm_status, resolve_root, root_refusal
    from .validate import known_tests, validate_finding
    from . import clock, languages
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import languages
    from anchors import line_sha, refs_in
    from harness import (RETRY_WINDOW_HOURS, _git, _parse_marker_time, _run_test, collect,
                         finalize_main, finding_hash, is_test_file, split_hygiene)
    from filed import FINDINGS_DIR, archive_findings
    from profile import assertion_gaps_from, risk_paths_from, sandbox_from
    from profile import ProfileError, gates_from, hygiene_filing_from
    from profile import load as load_profile
    import sandbox
    from reports import read_report
    from project_key import derive_key
    from state import home as state_home
    from state import norm_status, resolve_root, root_refusal
    from validate import known_tests, validate_finding
try:  # split out of this file by the structure pass; still importable here
    from .local_model import (DEFAULT_NUM_CTX, DEFAULT_TIMEOUT_S, Model, gateway_alive,
                              extract_json as extract_json)
except ImportError:  # executed as a bare script
    from local_model import (DEFAULT_NUM_CTX, DEFAULT_TIMEOUT_S, Model, gateway_alive,
                             extract_json as extract_json)
try:  # split out of this file by the structure pass; still importable here
    from .local_chunks import (Chunk as Chunk, chunks_of, gap_functions, gap_hint,
                               MAX_SOURCE_LINES as MAX_SOURCE_LINES)
except ImportError:  # executed as a bare script
    from local_chunks import (Chunk as Chunk, chunks_of, gap_functions, gap_hint,
                              MAX_SOURCE_LINES as MAX_SOURCE_LINES)
try:  # split out of this file by the structure pass; still importable here
    from .local_candidates import (added_lines, candidates, changed_files, changed_lines_in,
                                   changed_lines_of, chunks_in_range, delta_candidates, python_in,
                                   readable_in)
except ImportError:  # executed as a bare script
    from local_candidates import (added_lines, candidates, changed_files, changed_lines_in,
                                  changed_lines_of, chunks_in_range, delta_candidates, python_in,
                                  readable_in)
try:  # split out of this file by the structure pass; still importable here
    from .local_questions import (FAILURE_CEILING, UNPROVEN_CEILING, capped_failure, examine,
                                  finding_of, CLASSIFY_Q as CLASSIFY_Q, CONTRACT_Q as CONTRACT_Q,
                                  capped as capped, classify_question as classify_question,
                                  contract_question as contract_question)
except ImportError:  # executed as a bare script
    from local_questions import (FAILURE_CEILING, UNPROVEN_CEILING, capped_failure, examine,
                                 finding_of, CLASSIFY_Q as CLASSIFY_Q, CONTRACT_Q as CONTRACT_Q,
                                 capped as capped, classify_question as classify_question,
                                 contract_question as contract_question)
try:  # split out of this file by the structure pass; still importable here
    from .local_probes import (counterfactual, PROBE_Q as PROBE_Q, import_roots as import_roots,
                               module_name as module_name, probe_root as probe_root,
                               run_probe as run_probe, safe_probe as safe_probe,
                               safe_replacement as safe_replacement, scratch_copy as scratch_copy,
                               source_root as source_root)
except ImportError:  # executed as a bare script
    from local_probes import (counterfactual, PROBE_Q as PROBE_Q, import_roots as import_roots,
                              module_name as module_name, probe_root as probe_root,
                              run_probe as run_probe, safe_probe as safe_probe,
                              safe_replacement as safe_replacement, scratch_copy as scratch_copy,
                              source_root as source_root)
try:  # split out of this file by the structure pass; still importable here
    from .local_skips import (group_skips, skip_finding, skip_scan_files, skips_without_expiry,
                              test_files, collected_test_files as collected_test_files,
                              has_expiry as has_expiry)
except ImportError:  # executed as a bare script
    from local_skips import (group_skips, skip_finding, skip_scan_files, skips_without_expiry,
                             test_files, collected_test_files as collected_test_files,
                             has_expiry as has_expiry)
MAX_FUNCTIONS = 60              # a cap, so a large repository still finishes
# What a gate run may spend. A PR gate that takes an hour is a gate nobody
# waits for, so the caps are the product decision: six files, twenty-four
# functions, six counterfactuals, two minutes per call and fifteen minutes of
# model time in total. Estimated on the author's GTX 1070 at roughly sixteen
# minutes for a PR-sized diff.
GATE_MAX_FILES = 6
GATE_MAX_FUNCTIONS = 24
GATE_MAX_PROBES = 6
GATE_CALL_TIMEOUT_S = 120
GATE_MODEL_BUDGET_S = 900
# A night on a project with state. Measured on Sales (2026-09-18): with no model-time budget
# a day's range of 744 unexercised changed lines kept the engine asking for 4 h 10 min — 190
# questions, 60 functions read, 259 skipped at the function cap — and a nightly that runs into
# the working day is a nightly nobody keeps. An hour, 24 functions, 12 proofs: the
# ranking puts the riskiest changed functions first, and what is left is counted, not hidden.
NIGHT_MAX_FUNCTIONS = 24
NIGHT_MAX_PROBES = 12
NIGHT_MODEL_BUDGET_S = 3600
# Five identical runs is what releases a quarantine. Arithmetic, not judgment:
# the model is never asked whether a test has stopped being flaky.
REQUARANTINE_RUNS = 5
REQUARANTINE_TIMEOUT_S = 300
# The name this engine signs its runs with, in `last_run.engine`, the run marker
# and the report's Judge line. A state that does not say who judged it reads the
# same whether an Opus session or an 8B model on the desk wrote it.
ENGINE = "verdict-local"

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
            # The suite again: target code, in the box (`sandbox.py`).
            sandbox.run(rendered, cwd=repo, shell=True, writable=[repo, scratch],
                        extra_env={"PYTHONDONTWRITEBYTECODE": "1"}, timeout=1800)
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


# ── every prior finding is mentioned ──────────────────────────────────────────
#
# This is the safety-critical half of a local delta, and the reason 0.88.0's
# local mode was only ever safe over a fresh project. It wrote `still_open: []`,
# and `merge()`'s silence rule reads an unmentioned finding as resolved unless
# five or more AND over half the backlog went quiet at once. A key with four
# open findings therefore lost all four to a run that never looked at them, and
# a key with sixty lost the ten whose code had drifted. Silence is not a verdict
# and this engine is never allowed to speak it: every prior open finding leaves
# here in exactly one of three places, and the invariant below is asserted
# before anything is finalized.

_CARRY_FIELDS = ("id", "title", "severity", "priority", "failure_classification",
                 "root_cause")


def drift_of(facts: dict, fid: str) -> tuple:
    """(worst drift, the refs that moved) for one finding, from `evidence_drift`."""
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    rec = (drift.get("findings") or {}).get(str(fid))
    if not isinstance(rec, dict):
        return "", []
    moved = [str(r.get("ref")) for r in rec.get("refs") or []
             if isinstance(r, dict) and r.get("status") in ("changed", "missing")]
    return str(rec.get("drift") or ""), moved


def measured_resolution(facts: dict, fid: str) -> dict | None:
    """The one record that closes a finding with no model in the room: its cited
    test failed at the previous commit and passes at HEAD, on a test somebody
    chose — `explicit`, or collected for the first time this run.

    A test that merely passes at HEAD proves nothing: it may never have
    demonstrated the defect at all. `harness._chosen` draws the same line for the
    agent, and this engine gets no weaker rule because it is cheaper.
    """
    rec = (facts.get("verification") or {}).get(str(fid))
    if not isinstance(rec, dict):
        return None
    if rec.get("at_previous") != "fail" or rec.get("at_head") != "pass":
        return None
    if rec.get("selected_by") not in ("explicit", "added_this_run"):
        return None
    return rec


def partition_prior(previous: dict | None, facts: dict) -> tuple:
    """Every prior open finding, sorted into the only three honest outcomes.

    A. a measured fix — the ONLY path to `resolved`;
    B. the cited code is where it was — carried by id, unread;
    C. the cited code changed or vanished — re-filed under its own id with the
       drift as a fresh evidence line, because `still_open` over changed code is
       refused by the harness (rightly: the evidence no longer says what the
       finding says) and silence would resolve it.

    → (resolved ids, still-open ids, [(prior finding, drift, moved refs)])
    """
    resolved, still_open, refile = [], [], []
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if norm_status(f.get("status")) != "open" or f.get("source") == "hygiene":
            # accepted, resolved and withdrawn are the harness's to carry — and so is a
            # hygiene finding, which the scan re-measures every run
            continue
        fid = str(f["id"])
        drift, moved = drift_of(facts, fid)
        if measured_resolution(facts, fid):
            resolved.append(fid)
        elif drift in ("changed", "missing"):
            refile.append((f, drift, moved))
        else:
            still_open.append(fid)
    return resolved, still_open, refile


_REFILE_NARRATIVE = (
    "Carried by re-filing rather than by the words 'still open'. That is not this finding "
    "confirmed — it is the same claim standing over code nobody has read since, and the line "
    "added to its evidence says which measurement moved. A model run should read it before "
    "anyone acts on the severity above.")


def refiled_finding(prior: dict, note: str, collected, narrative=_REFILE_NARRATIVE) -> dict:
    """A prior finding, re-filed under its own id, with one measured line added.

    Everything the tester wrote is copied verbatim; the one thing added is `note`,
    which says in measured terms what changed and that nothing read it this run.
    No `confidence` — the claim was made once and `merge` freezes it — and
    `verification_test` survives only while the collector still knows that id.
    """
    entry = {k: json.loads(json.dumps(prior[k])) for k in _CARRY_FIELDS if k in prior}
    entry["status"] = "open"
    entry["evidence"] = [str(e) for e in (prior.get("evidence") or [])] + [note]
    test = prior.get("verification_test")
    if isinstance(test, str) and (collected is None
                                  or test.strip().replace("\\", "/") in collected):
        entry["verification_test"] = test
    entry["narrative"] = narrative
    return entry


def drift_note(drift: str, moved: list) -> str:
    where = ", ".join(moved[:5]) or "the cited lines"
    return (f"re-filed unread: the code this finding cites {drift} since the evidence above "
            f"was written ({where}) — measured by verdict-facts' anchors; no model read the "
            "new code this run")


def carry_invariant(prior_open: list, resolved: list, still_open: list, filed_ids) -> list:
    """Every prior open id must leave this run in one of the three places, or the
    run does not finalize. Asserted rather than trusted: the failure it guards is
    silent by construction — a finding that nobody mentions becomes RESOLVED in a
    state file nobody re-reads."""
    accounted = set(resolved) | set(still_open) | set(filed_ids)
    missing = [fid for fid in prior_open if fid not in accounted]
    return missing


# ── the quarantine, re-measured ───────────────────────────────────────────────

def requarantine(repo: Path, entries, test_one_cmd: str | None, today,
                 runs: int = REQUARANTINE_RUNS) -> tuple:
    """Re-run every DUE quarantine entry `runs` times → (kept, released, notes).

    An expiry is a date somebody wrote down, not a measurement, and releasing a
    test because the date passed is how a flaky test walks back into the set that
    blocks releases. Five identical runs answer the question exactly, and the
    model is never asked: repetition is arithmetic. An entry with no expiry due
    is carried verbatim, and a project with no `test_one_cmd` gets its entries
    kept, a parked question, and a line in `not_tested` — never a release.
    """
    kept, released, notes = [], [], []
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("test_id"):
            continue
        until = str(entry.get("quarantined_until") or "")
        if until and until > today.isoformat():
            kept.append(entry)
            continue
        if not test_one_cmd:
            kept.append(entry)
            notes.append(f"{entry['test_id']} is due for release from quarantine and was NOT "
                         "re-measured: the profile declares no `test_one_cmd`, so nothing here "
                         "can run one test. The quarantine is kept rather than expired")
            continue
        outcomes = [_run_test(test_one_cmd, str(entry["test_id"]), repo, repo,
                              REQUARANTINE_TIMEOUT_S)["result"] for _ in range(runs)]
        passed = sum(1 for r in outcomes if r == "pass")
        if passed == runs:
            released.append({**entry, "runs_measured": runs})
            notes.append(f"{entry['test_id']} passed {runs} of {runs} identical runs — released "
                         "from quarantine by measurement; it blocks releases again")
        else:
            kept.append({**entry,
                         "first_seen": entry.get("first_seen") or today.isoformat(),
                         "fail_count": runs - passed, "run_count": runs,
                         "quarantined_until": (today + timedelta(days=QUARANTINE_DAYS)).isoformat(),
                         "reason": f"re-measured {today.isoformat()}: {passed} of {runs} identical "
                                   "runs passed — still not deterministic, so the expiry moves"})
            notes.append(f"{entry['test_id']} passed only {passed} of {runs} identical runs — "
                         "quarantine extended by measurement")
    return kept, released, notes


def flaky_findings_by_test(previous: dict | None, test_ids) -> dict:
    """`{test id: finding id}` for the open FLAKY findings a previous run left.

    Matched on the test id appearing in the finding's own words, which is how
    this engine and the agent both write them. There is no structured link
    between a quarantine entry and its finding, and inventing one now would not
    read the findings people already have.
    """
    wanted = {str(t) for t in test_ids if t}
    out: dict = {}
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or norm_status(f.get("status")) != "open":
            continue
        if f.get("failure_classification") != "FLAKY":
            continue
        blob = " ".join([str(f.get("title") or "")] + [str(e) for e in (f.get("evidence") or [])])
        for test_id in wanted:
            if test_id in blob:
                out.setdefault(test_id, str(f.get("id")))
    return out


def failure_on_record(previous: dict | None, test_id: str) -> dict | None:
    """The open or accepted finding this engine filed for this failing test, or None.

    Matched on the exact sentence `failure_finding` writes — `<id> fails at HEAD` — and
    nothing looser: a finding that merely mentions a test may be about something else in
    it, and treating it as this failure would hide a new one. A resolved finding is not
    matched here; a failure that returns goes through the identity rule like any other."""
    sentence = f"{test_id} fails at HEAD"
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if norm_status(f.get("status")) not in ("open", "accepted"):
            continue
        if any(str(e).startswith(sentence) for e in f.get("evidence") or []):
            return f
    return None


def released_ids(previous: dict | None, released: list) -> list:
    """The FLAKY findings whose quarantine this run released — they are re-filed
    with the measurement, not left standing on a claim that is no longer true."""
    tests = [r.get("test_id") for r in released if isinstance(r, dict)]
    return sorted(set(flaky_findings_by_test(previous, tests).values()))


def merge_quarantine(carried: list, fresh: list) -> list:
    """The carried entries plus this run's, one per test id.

    A test already under an expiry that goes unstable again would otherwise be in
    the list twice — once with last run's counts and once with this run's — and a
    reader would have no way to tell which expiry governs. This run's measurement
    wins, because it is the newer one.
    """
    by_test = {}
    for entry in list(carried) + list(fresh):
        if isinstance(entry, dict) and entry.get("test_id"):
            by_test[str(entry["test_id"])] = entry
    return [by_test[k] for k in sorted(by_test)]


# ── the verdict, which may never improve on its own ───────────────────────────

def gate_failed(facts: dict) -> bool:
    """Did any gate this run come back red? A suite with failing tests is the plainest
    thing a QA run can know, and it outranks everything this engine reads.

    Measured 2026-09-17, and the reason this function exists: on the seeded delta fixture
    the local tier carried all five prior findings honestly, filed the new defect — and
    reported `pass with risks` over a suite with three failing tests, because the verdict
    was computed from finding severities alone and an unproven reading is held at Minor.
    A strong model classifies a failure (stale expectation, brittle test, flaky) and may
    still ship; this engine cannot be trusted to make that call from a few hundred tokens
    of context, so a red gate is a `fail` and a person or a real model decides otherwise.
    """
    for gate in (facts.get("gates") or {}).values():
        if isinstance(gate, dict) and str(gate.get("result")) == "fail":
            return True
    return False


def counts_measured(facts: dict) -> bool:
    """Did any gate this run produce test counts? Nothing else establishes that a
    test executed at all, and a verdict over that is `blocked`, not `pass`."""
    if facts.get("no_gates"):
        return False
    gates = facts.get("gates") or {}
    return bool(gates) and any(isinstance(g, dict) and g.get("counts") for g in gates.values())


def unexercised_diff(facts: dict) -> int:
    """How many changed lines no test executed — 0 when coverage was not measured."""
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") != "measured":
        return 0
    changed = int(cov.get("changed_lines") or 0)
    return changed - int(cov.get("changed_lines_executed") or 0) if changed else 0


def local_verdict(previous_verdict, filed: list, carried: list, measured: bool,
                  cold_lines: int = 0, ceiling: str | None = None,
                  gates_failed: bool = False) -> str:
    """The verdict of a local run — arithmetic, and monotone downwards.

    The rule that matters is the one this engine cannot be trusted without: a run
    that read six functions with an 8B model may never improve the standing
    verdict. Two verdicts are sticky, and for different reasons.

    A `fail` stays `fail` because something with judgment found a defect and
    nothing here has the standing to say it is gone. A `blocked` stays `blocked`
    because a previous run could not test at all — an environment, a tool, a
    requirement nobody answered — and this engine cannot tell whether what
    blocked it has cleared. Letting `blocked` improve was the worse of the two:
    the gate turns exit 3 into exit 0 on the word of a run that read six
    functions, which is precisely the false green this tier exists to make
    impossible.
    """
    if not measured:
        return "blocked"
    if gates_failed:
        # Red suite, red verdict. Not "pass with risks over three failing tests".
        return "fail"
    severities = [str(f.get("severity")) for f in list(filed) + list(carried)]
    if "Blocker" in severities:
        return "fail"
    if previous_verdict is None:
        # A baseline has nothing to carry and nothing to protect, so this
        # engine's own arithmetic stands — capped by what it could not read.
        standing = verdict_for(filed)
        return "pass with risks" if standing == "pass" and (cold_lines or ceiling) else standing
    if previous_verdict in ("fail", "blocked"):
        return str(previous_verdict)
    if "Critical" in severities or filed or cold_lines or ceiling:
        return "pass with risks"
    return str(previous_verdict or "pass")


CARRIED_BLOCKED = ("the previous run was blocked and this engine cannot tell whether what "
                   "blocked it has cleared — the verdict is carried, not re-judged")


# ── what a model would still have to answer ───────────────────────────────────

def needs_claude(facts: dict, filed: list, refiled: list, touched: list,
                 parked: int, over_limit: bool, non_python: bool) -> dict:
    """The measured reasons a real model run is still owed, for a gate's summary.

    Not advice and not a score: each entry is something the harness counted, so
    "this gate is green and here is what it did not ask" is checkable rather than
    reassuring.
    """
    out: dict = {}
    cold = unexercised_diff(facts)
    if cold:
        out["unexercised_changed_lines"] = cold
    if touched:
        out["touches_open_finding"] = sorted(touched)[:20]
    unproven = sorted({str(f.get("id")) for f in filed
                       if f.get("confidence") != "proven"
                       and str(f.get("severity")) in ("Blocker", "Critical", "Major")})
    if unproven:
        out["unprovable_high_severity"] = unproven[:20]
    if refiled:
        out["drift_unsettled"] = sorted(str(f.get("id")) for f in refiled)[:20]
    if non_python:
        # The key keeps its name (state-schema.md documents it); since every language is read
        # it means "nothing in the range this engine reads".
        out["non_python_diff"] = ("no source this engine reads in the range: only configuration, "
                                  "data, styles, documentation, tests or generated files — it read "
                                  "no code at all")
    if parked:
        out["questions_parked"] = parked
    if over_limit:
        out["diff_over_limit"] = ("the range is larger than the caps this engine runs under; "
                                  "part of it was never read")
    return out


LEADS_FILE = "leads.json"
NO_CODE_READ = ("No code was read this run: the range changed no source this engine reads, "
                "only configuration, data, styles, documentation, tests or generated files. A "
                "green gate here means the suite did not fail; it is not a QA pass.")
# Why a reading of any other language stays unproven: a counterfactual flips a line and re-runs
# an expression in a Python interpreter, and there is no such seam for them here.
NO_PROBE = "no counterfactual: this engine executes Python only, and this code is {language}"
# The ceiling for a range whose code in another language was read. Read is not run: the verdict
# over code no question could ever prove stays below `pass`, as it did when that code was not read
# at all.
READ_NOT_RUN = ("Code in the range in a language other than Python was read, one function or "
                "excerpt at a time, and none of it was executed: this engine runs counterfactuals "
                "in Python only, so every reading there is unproven, and a green gate is not a QA "
                "pass of that code.")
# A focus list that only ever grows is a focus list nobody reads, which is the
# same as not having one.
FOCUS_LINES = 20
LEADS_IN_FOCUS = 5
LEADS_IN_REPORT = 25


def _unique(items) -> list:
    """The list with its order kept and its repeats dropped."""
    seen, out = set(), []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        out.append(item)
    return out


# ── the run ───────────────────────────────────────────────────────────────────

class Budget:
    """How much model this run may spend, and what it skipped when it stopped.

    A gate nobody waits for is a gate nobody runs, so the caps are part of the
    product: a bounded number of functions, a bounded number of counterfactuals,
    and a wall-clock ceiling on the model's part. What matters for honesty is the
    other half — when a cap bites, the run says how many candidates it never looked
    at, because a truncated read reported as a complete one is the exact shape of a
    false green.

    The ceiling's clock starts at the first question, not when the budget is built:
    the suite and coverage run in between, and they are measurement, not model time.
    Started at construction, it counted them — on Verdict's own repository they took
    853 of a release gate's 900 s, and the gate read no function and reported "the
    900s model budget ran out" (2026-10-15).
    """

    def __init__(self, functions: int = MAX_FUNCTIONS, probes=None, seconds=None):
        self.functions, self.probes, self.seconds = functions, probes, seconds
        self.used_functions, self.used_probes, self.skipped = 0, 0, 0
        self.stopped = None
        self._started = None

    def elapsed_s(self) -> float:
        return 0.0 if self._started is None else time.monotonic() - self._started

    def take_function(self) -> bool:
        if self._started is None:
            self._started = time.monotonic()
        if not self.stopped:
            # `>=`: a budget of 0 s is spent at once. With `>`, Windows' 15.6 ms monotonic
            # clock reads 0.0 right after construction and a spent budget reads as unspent.
            if self.seconds is not None and self.elapsed_s() >= self.seconds:
                self.stopped = "the %ds model budget ran out" % int(self.seconds)
            elif self.used_functions >= self.functions:
                self.stopped = f"the cap of {self.functions} function(s) was reached"
        if self.stopped:
            self.skipped += 1
            return False
        self.used_functions += 1
        return True

    def take_probe(self) -> bool:
        """A counterfactual is the expensive question — a scratch copy and two
        subprocesses — so it has a cap of its own. Running out of probes leaves the
        claim a hypothesis, which is the honest outcome anyway."""
        if self.probes is None:
            return True
        if self.used_probes >= self.probes:
            return False
        self.used_probes += 1
        return True


# ── a finding that already exists ─────────────────────────────────────────────

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Names too common to say which function a finding meant. A finding that mentions
# `run` has not named the function `run`.
_TOO_COMMON = frozenset({"main", "init", "__init__", "run", "get", "set", "call", "test",
                         "setup", "teardown", "update", "process", "handle", "__call__",
                         "__repr__", "__str__", "__eq__", "__hash__"})


class PriorIndex:
    """Which earlier finding a claim about this function already is.

    Measured on the seeded delta (2026-09-18): the rounding defect the previous run had
    resolved came back, the engine read `round_cents`, described the bug correctly — and
    filed it as a NEW finding, because it minted its own id and never looked at the state
    it was carrying. A regression is the most important thing a nightly can say, and it
    was reported as news. The same blindness filed a second finding for a defect that was
    already open, which on a project with a backlog is a new duplicate every night.

    Two ways to know, strongest first. **The finding's anchors** (0.83.0 hashes every
    line a finding cites): if a line this function holds now has the same hash, it is the
    same code. **The function's name**, when the finding names it — in its title, its
    evidence or its root cause — and cites no other file: an old finding written before
    anchors, or one whose line has been edited. The name is a weaker signal, so a name
    that says nothing (`run`, `main`) never matches, and every match says which signal
    it rested on. Withdrawn findings are the tester's own errors and never match.
    """

    def __init__(self, previous):
        self.entries = []
        for f in (previous or {}).get("findings") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            status = norm_status(f.get("status"))
            if status not in ("open", "accepted", "resolved"):
                continue
            anchors = [a for a in f.get("anchors") or [] if isinstance(a, dict)]
            text = " ".join([str(f.get("title") or "")]
                            + [str(e) for e in f.get("evidence") or []]
                            + [json.dumps(f.get("root_cause") or {})])
            paths = {str(a["path"]) for a in anchors if a.get("path")}
            paths |= {str(path) for path, _line in refs_in([text])}
            shas = {(str(a.get("path")), str(a.get("line_sha")))
                    for a in anchors if a.get("path") and a.get("line_sha")}
            self.entries.append({"finding": f, "status": status, "paths": paths,
                                 "shas": shas, "words": set(_IDENT.findall(text))})

    def match(self, repo: Path, chunk) -> tuple:
        """→ (prior finding, its status, how it was recognised) or (None, None, None)."""
        try:
            lines = (repo / chunk.path).read_bytes().splitlines()[chunk.start - 1:chunk.end]
        except OSError:
            lines = []
        here = {(chunk.path, line_sha(line)) for line in lines if line.strip()}
        for e in self.entries:
            hit = here & e["shas"]
            if hit:
                return e["finding"], e["status"], (
                    f"a line it cited when it was filed is in `{chunk.name}` again, "
                    f"unchanged (line hash {sorted(hit)[0][1]})")
        name = chunk.name
        if len(name) < 4 or name in _TOO_COMMON:
            return None, None, None
        for e in self.entries:
            if name in e["words"] and (not e["paths"] or chunk.path in e["paths"]):
                return e["finding"], e["status"], (
                    f"it names `{name}`, the function this claim is about — matched by "
                    "name, not by line, so read it before trusting the link")
        return None, None, None


def regressed_finding(prior: dict, claim_entry: dict, how: str) -> dict:
    """A resolved finding, back: its own id, so the harness calls it REGRESSED.

    The title is the original's — the id names that finding — and this run's reading
    goes into the evidence beside the reason the two were linked. Severity stays what
    this engine can justify (held at Minor unless a counterfactual proved it): being the
    same bug is measured, how bad it is now is not. No `confidence`: the claim was made
    once, when the finding was first filed, and `merge` keeps that one.
    """
    entry = dict(claim_entry)
    entry.pop("confidence", None)
    entry["id"] = prior["id"]
    entry["title"] = str(prior.get("title") or claim_entry.get("title"))
    entry["evidence"] = [
        f"REGRESSED — {prior['id']} was resolved, and this run found it again: {how}.",
        f"this run's reading: {claim_entry.get('title')}",
    ] + list(claim_entry.get("evidence") or [])
    return entry


def focus_names(facts: dict) -> set:
    """The function and class names the profile's risk-focus section names (0.92.0)."""
    return {str(n) for n in ((facts.get("risk_focus") or {}).get("names") or [])}


def ordered_chunks(repo: Path, rel: str, lines, gaps: dict | None, focus=()) -> list:
    """The functions to ask about: the ones holding an assertion-gap survivor first, then the
    ones the profile's risk focus names, then the rest in file order."""
    chunks = chunks_in_range(repo, rel, lines)
    named = (gaps or {}).get(rel) or {}
    if not named and not focus:
        return chunks
    return sorted(chunks, key=lambda c: (c.name not in named, c.name.rsplit(".", 1)[-1] not in focus))


def file_findings(model: Model, repo: Path, targets: list, mint, findings_dir: Path,
                  filed: list, python: str, prove: bool, budget: Budget,
                  prior_index: PriorIndex | None = None, already_open: list | None = None,
                  leads: list | None = None, probes: list | None = None,
                  gaps: dict | None = None, asked: set | None = None, focus=()) -> tuple:
    """Read the source, one function at a time, and try to prove each claim by flipping
    the line in a scratch copy. Returns (examined, proven, disproven).

    `targets` is `(path, the changed lines or None)`: a run over a range asks only
    about the functions the range touched, because a function nobody edited is a
    question this engine already asked on some earlier night.

    `probes`, when given, collects one row per counterfactual attempted — the
    expression, where it ran, the status and the reason — so `facts.json` says what
    was executed this run, refusals included (audit 2026-10-02, O-S-1 (5)).
    """
    examined = proven = disproven = 0
    for rel, lines in targets:
        named = (gaps or {}).get(rel) or {}
        for chunk in ordered_chunks(repo, rel, lines, gaps, focus):
            if not budget.take_function():
                continue
            examined += 1
            if asked is not None:
                asked.add((rel, chunk.name))
            claim = examine(model, chunk, gap_hint(named[chunk.name]) if chunk.name in named else None)
            if not claim:
                continue
            # A counterfactual runs Python; for any other language none is attempted and none
            # of the probe budget is spent.
            unprovable = (NO_PROBE.format(language=languages.name_of(chunk.lang))
                          if chunk.lang != "python" else None)
            proof = (counterfactual(model, repo, chunk, claim, python)
                     if prove and not unprovable and budget.take_probe() else None)
            if proof is not None and probes is not None:
                probes.append({"path": chunk.path, "function": chunk.name,
                               "line": claim["line"], "expression": proof.get("expression", ""),
                               "scratch": proof.get("scratch"), "status": proof["status"],
                               "reason": proof.get("reason", "")})
            if proof and proof.get("status") == "unavailable":
                print(f"verdict-local: not proven, {chunk.path}:{claim['line']} — "
                      f"{proof['reason']}", file=sys.stderr)
            if proof and proof.get("status") == "disproven":
                # Withdrawn before it was ever filed. The cheapest false positive is the
                # one the harness catches for the reader.
                disproven += 1
                print(f"verdict-local: withdrew a claim in {chunk.path}:{claim['line']} — "
                      f"{proof['reason']}", file=sys.stderr)
                continue
            if proof and proof.get("status") == "proven":
                proven += 1
            entry = finding_of(claim, "@", chunk.source, proof)
            prior, status, how = (prior_index.match(repo, chunk) if prior_index
                                  else (None, None, None))
            if prior is None and leads is not None and entry.get("confidence") != "proven":
                # A project with state is a backlog somebody has to read. Measured on Sales:
                # 27 unproven Minor readings in one night, on top of 69 open findings. What a
                # small model read and could not prove is a lead for the next run that can
                # judge it — listed in the report, not added to the record.
                leads.append({"path": chunk.path, "line": claim["line"], "function": chunk.name,
                              "title": claim["title"], "severity": claim["severity"],
                              "why": (proof or {}).get("reason") or unprovable or
                              ("no counterfactual was attempted" if not prove
                               else "the proof budget was spent")})
            elif prior is None:
                mint(entry, findings_dir, filed)
            elif any(str(f.get("id")) == str(prior["id"]) for f in filed):
                continue            # this run already filed that finding once
            elif status == "resolved" and entry.get("confidence") != "proven":
                # A resolved finding is re-anchored when it is resolved, so its anchors often
                # cite the fix: a line match says the fix is still there as often as it says
                # the defect is back. Measured on ifta-agent (2026-10-15): the fixed function's
                # own signature matched, and a proven Critical was re-filed as REGRESSED on a
                # small model's unproven — and wrong — reading of the fixed code. Reopening a
                # closed finding takes what filing a new one takes: a proof. Without one it is
                # a lead for a run that can judge it.
                print(f"verdict-local: not re-opened — `{chunk.name}` may be {prior['id']} "
                      f"again ({how}), but the reading is unproven", file=sys.stderr)
                if leads is not None:
                    leads.append({"path": chunk.path, "line": claim["line"],
                                  "function": chunk.name, "title": claim["title"],
                                  "severity": claim["severity"],
                                  "why": f"may be {prior['id']} (resolved) again — {how}; "
                                         "unproven, so the resolved finding was not re-opened"})
            elif status == "resolved":
                print(f"verdict-local: {prior['id']} is back — {how}", file=sys.stderr)
                mint(regressed_finding(prior, entry, how), findings_dir, filed, keep_id=True)
            else:
                # Open or accepted already: it is carried by id, re-filed if its code
                # moved, or the maintainer's. A second finding for it is a duplicate
                # the backlog grows by every night.
                if already_open is not None:
                    already_open.append((str(prior["id"]), chunk.name, how))
                print(f"verdict-local: not filed again — `{chunk.name}` is {prior['id']} "
                      f"({status}): {how}", file=sys.stderr)
    return examined, proven, disproven


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
            # `uv run` syncs the project first, and a sync builds it: the build backend is the
            # project's code, so the question goes in the box like every other run of it.
            proc = sandbox.run(
                [runner, "run", "python", "-c", "import sys; print(sys.executable)"],
                cwd=str(repo) if repo else None, writable=[repo] if repo else [],
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
    # The project's code runs in the box the profile sets (`sandbox.py`), here as in facts.
    sandbox.configure(sandbox.policy_from(sandbox_from(config, profile_notes), qa_root, profile_notes))
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
    facts["sandbox"] = sandbox.current().as_fact()
    facts.setdefault("last_run", {})["engine"] = ENGINE
    return facts


def run(repo: Path, qa_root: Path, model: Model, limit: int, gate: str | None,
        reruns: int, prove: bool = True, delta: bool = False,
        sha_range: str | None = None, reference_state=None,
        budget: Budget | None = None, reuse_facts: bool = False) -> int:
    refusal = root_refusal(qa_root, "verdict-local", repo)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    qa_root.mkdir(parents=True, exist_ok=True)
    budget = budget or Budget()
    try:
        config, profile_notes = load_profile(qa_root)
    except ProfileError as exc:
        print(f"verdict-local: {exc}", file=sys.stderr)
        return 2
    gates = [("suite", gate)] if gate else (gates_from(config) or [("suite", GATE_DEFAULT)])
    name, command = gates[0]
    # Read whatever is there, always — never `if delta`. A caller that forgot the
    # flag over a root that already holds a record would otherwise get the 0.88.0
    # behaviour back: no prior finding mentioned, and the merge resolving the lot.
    # The flag says what the operator expected, and a mismatch is worth a line.
    previous = read_json(qa_root / "state.json")
    if delta and not previous:
        print(f"verdict-local: --delta was asked for, but {qa_root} holds no state — this "
              "run is a baseline, with nothing to carry", file=sys.stderr)
    reference = read_reference(reference_state) if reference_state else None

    # Whether a counterfactual may run at all, decided before anything is measured and
    # said in `not_tested` either way: the profile's `probes: off`, `--no-prove`,
    # `--max-probes 0`, or a gate that runs no Python interpreter (audit 2026-10-02,
    # O-S-1 (4) and O-D-11). The old code fell back to Verdict's own interpreter.
    python = interpreter_of(command, repo)
    disabled = None
    if probes_off(config, profile_notes):
        disabled = "probes disabled by profile (`probes: off` in profile.md)"
    elif not prove:
        disabled = "probes disabled by flag (`--no-prove`)"
    elif budget.probes == 0:
        disabled = "probes disabled by flag (`--max-probes 0`)"
    elif python is None:
        disabled = f"proving disabled: no Python interpreter in the gate (`{command}`)"
    prove = disabled is None

    exposed = plaintext_env_files(repo)
    if exposed:
        print(f"verdict-local: not running the gates — plaintext {', '.join(exposed)} at the "
              f"checkout root: a test run could reach live services with real keys. Remove "
              "it from the checkout under test and run again. Nothing was measured or written.",
              file=sys.stderr)
        return 5
    print(f"verdict-local: measuring {repo} · gate {name}", file=sys.stderr)
    facts = measure(repo, qa_root, gates, config, sha_range, profile_notes,
                    reuse=reuse_facts)
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    measured_range = (facts.get("last_run") or {}).get("sha_range")
    ranged = bool(measured_range)
    changed = changed_files(repo, measured_range)
    if ranged:
        cold_by_file = changed_lines_of(facts)
        # A range with nothing in it — the commit the last run measured — has nothing to
        # read. Handing it an empty list fell through to the reading map: the second Sales
        # shadow night re-ranked the whole repository's least-covered files and reported
        # its empty range as too large for the caps.
        sizes = added_lines(repo, measured_range) if any(languages.readable(p) for p in changed) else None
        ranked = delta_candidates(facts, repo, changed, sizes) if changed else []
        # Coverage names the changed lines no test ran, for Python. For every other language
        # the diff itself names the changed lines: one question per function they sit in, never
        # the whole file.
        braced = [rel for rel in ranked[:limit] if languages.language_of(rel) not in (None, "python")]
        diff_lines = changed_lines_in(repo, measured_range, braced)
        targets = [(rel, diff_lines.get(rel) if rel in braced else cold_by_file.get(rel))
                   for rel in ranked[:limit]]
    else:
        ranked = candidates(facts, repo)
        targets = [(rel, None) for rel in ranked[:limit]]
    files = [rel for rel, _ in targets]
    over_limit = len(ranked) > limit
    non_python = bool(ranged and changed and not readable_in(changed))

    print(f"verdict-local: {len(files)} file(s) to read, model {model.name}"
          + (f", proving with {python}" if prove else f", {disabled}"), file=sys.stderr)
    prefix = str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[0]
    number = int(str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[1] or 1)

    findings_dir = qa_root / FINDINGS_DIR
    findings_dir.mkdir(exist_ok=True)
    counter = [number]
    collected = known_tests(qa_root)
    prior_ids = {str(f.get("id")) for f in (previous or {}).get("findings") or []
                 if isinstance(f, dict) and f.get("id")}
    prior_by_hash = {finding_hash(f): f for f in (previous or {}).get("findings") or []
                     if isinstance(f, dict) and f.get("id")}
    on_record: list = []

    def mint(entry: dict, into: Path, into_list: list, keep_id: bool = False) -> None:
        """File a finding, or refuse it — the validator decides, never the model."""
        # One identity, one finding. The harness recognises a finding by its cited path and
        # its title, and refuses a run that files the same identity twice — a refusal that
        # costs the whole night. Anything this run already filed under the same identity is
        # the same finding: its evidence is added there, and no second file is written.
        prior = None if keep_id else prior_by_hash.get(finding_hash(entry))
        twin = next((f for f in into_list if finding_hash(f) == finding_hash(entry)), None)
        if twin is None and prior is not None:
            twin = next((f for f in into_list if str(f.get("id")) == str(prior["id"])), None)
        if twin is not None:
            twin["evidence"] = list(twin.get("evidence") or []) + [
                e for e in entry.get("evidence") or [] if e not in (twin.get("evidence") or [])]
            (into / f"{twin['id']}.json").write_text(json.dumps(twin, indent=1),
                                                     encoding="utf-8")
            print(f"verdict-local: {twin['id']} again — the same identity, folded into it",
                  file=sys.stderr)
            return
        # The same across nights: an identity the record already holds is that finding.
        # Open, it is carried by id, and filing it again puts one identity under two ids —
        # found by replaying the first Sales shadow night, whose skip markers would all have
        # come back on the second, so finalize would have refused every night after the
        # first. Accepted or withdrawn, it is a person's decision that a regular expression
        # does not overturn. Resolved, it came back: under its own id, so it is REGRESSED.
        status = norm_status((prior or {}).get("status"))
        if prior is not None and status != "resolved":
            on_record.append((str(prior["id"]), status))
            print(f"verdict-local: not filed again — {prior['id']} ({status}) is this finding "
                  "already", file=sys.stderr)
            return
        if prior is not None:
            print(f"verdict-local: {prior['id']} is back — the identity it was resolved under",
                  file=sys.stderr)
            entry = regressed_finding(prior, entry,
                                      "the same file and title it was resolved under")
            keep_id = True
        if not keep_id:
            entry["id"] = f"{prefix}-{counter[0]}"
        problems = validate_finding(entry, f"{FINDINGS_DIR}/{entry['id']}.json",
                                    prior_ids, collected)
        if problems:
            print(f"verdict-local: rejected {entry['id']}: {problems[0]}", file=sys.stderr)
            return
        (into / f"{entry['id']}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
        into_list.append(entry)
        if not keep_id:
            counter[0] += 1
        print(f"verdict-local: {entry['id']} {entry['severity']} {entry.get('failure_classification', '')} "
              f"— {entry['title'][:80]}", file=sys.stderr)

    filed = []
    today = clock.today()

    # 1. What execution says. Repetition answers flakiness; the model is never asked.
    failures = failures_of(facts)
    repeats = rerun_failures(repo, command, reruns) if failures or reruns else []
    flaky = unstable(failures, repeats)
    if failures:
        print(f"verdict-local: {len(failures)} failing test(s), {len(flaky)} unstable across "
              f"{len(repeats) + 1} run(s)", file=sys.stderr)
    fresh_quarantine = []
    for test_id in sorted(flaky):
        fresh_quarantine.append({
            "test_id": test_id,
            "first_seen": today.isoformat(),
            "fail_count": sum(1 for r in [set(f["id"] for f in failures)] + [set(x) for x in repeats]
                              if test_id in r),
            "run_count": len(repeats) + 1,
            "quarantined_until": (today + timedelta(days=QUARANTINE_DAYS)).isoformat(),
            "reason": f"failed in some of {len(repeats) + 1} identical runs and passed in "
                      "others — measured, not judged",
        })
    # A test that already has an open FLAKY finding is being carried by id below;
    # filing a second one for the same instability would put two ids on one defect.
    already_flaky = flaky_findings_by_test(previous, sorted(flaky))
    for entry in fresh_quarantine:
        if entry["test_id"] in already_flaky:
            print(f"verdict-local: {entry['test_id']} is already "
                  f"{already_flaky[entry['test_id']]}; the quarantine is re-measured and the "
                  "finding carried, not filed again", file=sys.stderr)
            continue
        mint(flaky_finding(entry, len(repeats) + 1, "@"), findings_dir, filed)
    for failure in failures:
        if failure["id"] in flaky:
            continue
        # A failing test this engine already filed is that finding, still open: carried by
        # id, not classified again. The model words its title differently from night to
        # night, so the identity rule alone would file a new duplicate every night the test
        # stays red — at about ninety seconds of the night's model budget each.
        cited = failure_on_record(previous, failure["id"])
        if cited is not None:
            status = norm_status(cited.get("status"))
            on_record.append((str(cited["id"]), status))
            print(f"verdict-local: not classified again — {failure['id']} is {cited['id']} "
                  f"({status})", file=sys.stderr)
            continue
        claim = classify(model, repo, failure)
        if claim:
            mint(failure_finding(claim, "@"), findings_dir, filed)

    # 2. Skips with no expiry — a regular expression, no model call at all.
    for skip in group_skips(skips_without_expiry(repo, skip_scan_files(repo, qa_root))):
        mint((focus_finding if skip.get("kind") == "focus" else skip_finding)(skip, "@"),
             findings_dir, filed)

    # 3. What reading says, function by function — the source, then the tests.
    already_open: list = []
    leads: list | None = [] if previous else None      # a project with a record to protect
    probe_ledger: list = []                            # every counterfactual, refusals too
    asked_functions: set = set()
    examined, proven, disproven = file_findings(model, repo, targets, mint, findings_dir,
                                                filed, python, prove, budget,
                                                prior_index=PriorIndex(previous),
                                                already_open=already_open, leads=leads,
                                                probes=probe_ledger, gaps=gap_functions(facts),
                                                asked=asked_functions, focus=focus_names(facts))
    # Beside `last_run`, not inside its `local` block: that block is copied into a
    # `usage.jsonl` row every run, and the ledger is a record, not a bill.
    facts["probes"] = probe_ledger
    suite_files = ([p for p in python_in(changed) if is_test_file(p)] if ranged
                   else skip_scan_files(repo, qa_root)[:limit])
    examined += brittle_findings(model, repo, suite_files, mint, findings_dir, filed, budget,
                                 leads=leads)

    # 4. The quarantine, re-measured rather than expired by the calendar.
    carried_quarantine, released, quarantine_notes = requarantine(
        repo, (previous or {}).get("flaky_quarantine") or [], config.get("test_one_cmd"), today)
    quarantine_out = merge_quarantine(carried_quarantine, fresh_quarantine)

    # 5. Every prior open finding is mentioned — A, B or C, and nothing else.
    prior_open = [str(f.get("id")) for f in (previous or {}).get("findings") or []
                  if isinstance(f, dict) and f.get("id") and norm_status(f.get("status")) == "open"
                  and f.get("source") != "hygiene"]
    resolved_ids, still_open_ids, to_refile = partition_prior(previous, facts)
    by_id = {str(f.get("id")): f for f in (previous or {}).get("findings") or []
             if isinstance(f, dict) and f.get("id")}
    for fid in released_ids(previous, released):
        # A released quarantine changes what its FLAKY finding says about itself,
        # so the finding is re-filed with the measurement rather than carried by
        # words that are no longer true.
        if fid in still_open_ids:
            still_open_ids.remove(fid)
            to_refile.append((by_id[fid], "released", []))

    asked_questions, refiled = [], []
    for prior, drift, moved in to_refile:
        fid = str(prior.get("id"))
        note = (f"quarantine released {today.isoformat()}: the test passed "
                f"{REQUARANTINE_RUNS} of {REQUARANTINE_RUNS} identical runs and blocks "
                "releases again. The finding stays open — nothing explained why it was ever "
                "unstable" if drift == "released" else drift_note(drift, moved))
        before = len(filed)
        mint(refiled_finding(prior, note, collected), findings_dir, filed, keep_id=True)
        if len(filed) > before:
            refiled.append(filed[-1])
            asked_questions.append({
                "question": f"{fid} was re-filed unread by {ENGINE}: {note[:150]}. Is it still "
                            "real over the new code?",
                "finding": fid,
                "context": "no model read the changed code this run; the severity above is "
                           "the one the finding was filed with"})
        else:
            # Refused by the validator. Silence resolves it, so it goes back into
            # the carried set — the conservative direction, always.
            still_open_ids.append(fid)

    missing = carry_invariant(prior_open, resolved_ids, still_open_ids,
                              {str(f.get("id")) for f in filed})
    if missing:
        print(f"verdict-local: refusing to finalize — {len(missing)} prior open finding(s) "
              f"would go unmentioned ({', '.join(missing[:5])}), and the merge reads silence "
              "as resolution. No state was written; the run marker is left in place.",
              file=sys.stderr)
        return 1

    if (model.answered + model.unanswered) and not model.answered:
        print(f"verdict-local: refusing to finalize — {model.unanswered} question(s) were "
              f"asked and none was answered ({model.errors} transport error(s)). A judgment "
              "assembled from no answers is a run that measured the suite and called it QA. "
              "No judgment, no state; the run marker is left in place.", file=sys.stderr)
        return 5

    measured = counts_measured(facts)
    cold_lines = unexercised_diff(facts)
    carried_records = [by_id[f] for f in still_open_ids if f in by_id]
    # A prior state with no verdict in it is unknown, not clean — and `None` here
    # means "baseline", which would hand this run the freedom a baseline has.
    prior_verdict = (previous.get("verdict") or "blocked") if previous else None
    braced_read = examined > 0 and any(languages.language_of(rel) not in (None, "python")
                                       for rel in files)
    verdict = local_verdict(prior_verdict, filed, carried_records, measured, cold_lines,
                            ceiling=(NO_CODE_READ if non_python
                                     else READ_NOT_RUN if braced_read else None),
                            gates_failed=gate_failed(facts))

    touched = touches_findings(reference, changed) if reference else []
    owed = needs_claude(facts, filed, refiled, touched, len(asked_questions),
                        over_limit and ranged, non_python)

    blockers = _unique([b for b in (previous or {}).get("release_blockers") or []
                        if not any(str(b).startswith(fid) for fid in resolved_ids)]
                       + [f["id"] for f in filed if f.get("severity") == "Blocker"])
    # Deduplicated, and this run's lines first: a nightly that appends its own
    # focus to the previous run's forever ends up with a list nobody reads, which
    # is the same as having none.
    focus = _unique(
        [f"{f['id']}: read the changed code under this finding — {ENGINE} re-filed it "
         "without reading it" for f in refiled]
        + [f"needs a model run — {key}: {value}" for key, value in sorted(owed.items())]
        + [f"lead, unproven: {x['path']}:{x['line']} `{x['function']}` — {x['title'][:120]}"
           for x in (leads or [])[:LEADS_IN_FOCUS]]
        + [str(x) for x in (previous or {}).get("next_run_focus") or []])[:FOCUS_LINES]

    for note in quarantine_notes:
        print(f"verdict-local: {note}", file=sys.stderr)
        if "NOT re-measured" in note:
            asked_questions.append({
                "question": f"A quarantine is due and could not be re-measured: {note[:170]}",
                "context": "declare `test_one_cmd` in the profile so the harness can run one "
                           "test, or release the quarantine deliberately"})

    unread = [(path, name) for path, names in gap_functions(facts).items() for name in names
              if (path, name) not in asked_functions]
    not_tested = not_tested_lines(model, files, examined, prior_open, still_open_ids,
                                  refiled, prove, budget, quarantine_notes, non_python,
                                  disabled=disabled, unread_survivors=unread)
    if braced_read:
        not_tested.append(READ_NOT_RUN)
    if ranged and (kinds := languages.unread_summary(changed)):
        # Named by kind, so a range that changed styles and copy beside its code says what of it
        # no question looked at: a stylesheet is not program source, and nothing here reads one.
        not_tested.append(f"changed in the range and read by no question here, because none of "
                          f"it is program source: {kinds}")
    if leads:
        not_tested.append(
            f"{len(leads)} reading(s) this engine could not prove were listed as leads in the "
            "report, not filed — a lead is a question for a run that can judge it, not a finding")
    if already_open:
        # Said, not swallowed: a claim that was not filed is still something this run read.
        ids = ", ".join(sorted({fid for fid, _name, _how in already_open}))
        not_tested.append(
            f"{len(already_open)} claim(s) about function(s) that already carry an open finding "
            f"({ids}) were not filed again — whether each is that finding or a second defect "
            "in the same function was not settled")
    if on_record:
        ids = ", ".join(sorted({f"{fid} ({status})" for fid, status in on_record}))
        not_tested.append(
            f"{len(on_record)} finding(s) this run found again are already on the record "
            f"({ids}) and were not filed again — the same identity, or a failing test this "
            "engine already filed; each stays as the record has it")
    carried_blocked = prior_verdict == "blocked" and verdict == "blocked"
    if carried_blocked:
        not_tested.append(CARRIED_BLOCKED)

    judgment = {
        "topic": "local-delta" if previous else "local",
        "verdict": verdict,
        "findings": [], "still_open": still_open_ids, "resolved": resolved_ids,
        "questions": asked_questions,
        "not_tested": not_tested,
        "prose": {
            "scope": (f"{ENGINE}: {examined} function(s) in {len(files)} file(s) read one at a "
                      f"time by {model.name}, each in isolation"
                      + (f", over the range `{measured_range}`" if ranged else "")
                      + ". The harness measured the repository; the model answered bounded "
                        "questions about single functions."),
            "risks": ("Every finding read here is a `hypothesis` unless a counterfactual "
                      "proved it. This mode cannot see a defect that spans two functions, and "
                      "it reads the suite only where the range touched it."
                      + (" " + NO_CODE_READ if non_python else "")
                      + (" " + READ_NOT_RUN if braced_read else "")),
            "notes": ("No Claude tokens were spent on this run. The verdict cannot improve on "
                      "its own: a previous `fail` stays `fail`, and a previous `blocked` "
                      "stays `blocked`, until something with judgment looks at it."
                      + (" " + CARRIED_BLOCKED[0].upper() + CARRIED_BLOCKED[1:] + "."
                         if carried_blocked else "")
                      + leads_text(leads)),
        },
        "isolation_check": {"result": "pass",
                            "method": ("measured before the gates: no plaintext .env file at "
                                       "the checkout root. The profile's own isolation steps "
                                       "were not executed: this engine runs the profile's gates "
                                       "and reads code, and writes nothing outside the QA root")},
        "verified_intact": list((previous or {}).get("verified_intact") or []),
        "flaky_quarantine": quarantine_out,
        "release_blockers": blockers,
        "next_run_focus": focus,
        "full_sweep": False,
    }
    (qa_root / "judgment.json").write_text(json.dumps(judgment, indent=1), encoding="utf-8")

    # No gateway in it: this block becomes the state's `last_run.local`, which a team
    # commits. The address goes to finalize below, and from there to the bill only.
    facts["last_run"]["local"] = {
        "model": model.name,
        "calls": model.calls, "tokens": model.input_tokens + model.output_tokens,
        "input_tokens": model.input_tokens, "output_tokens": model.output_tokens,
        "answered": model.answered, "unanswered": model.unanswered,
        "retries": model.retries, "errors": model.errors, "num_ctx": model.num_ctx,
        "functions_read": examined, "functions_skipped": budget.skipped,
        "seconds": round(budget.elapsed_s(), 1),
    }
    if owed:
        facts["needs_claude"] = owed
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    # The report's leads as data, for the run that judges them next: `verdict-run --escalate`
    # hands them to the tester with the census survivors and this engine's own filings.
    (qa_root / LEADS_FILE).write_text(json.dumps({"engine": ENGINE, "model": model.name,
                                                  "leads": leads or []}, indent=1),
                                      encoding="utf-8")

    code = finalize_main(["--qa-root", str(qa_root),
                          "--judgment", str(qa_root / "judgment.json")],
                         gateway=model.base_url)
    if proven or disproven:
        print(f"verdict-local: {proven} claim(s) proven by counterfactual, {disproven} "
              f"withdrawn before filing", file=sys.stderr)
    print_summary(model, files, examined, filed, refiled, resolved_ids, still_open_ids,
                  written_verdict(qa_root, verdict) if code == 0 else verdict, owed, budget,
                  engine_verdict=verdict)
    return code


def written_verdict(qa_root: Path, fallback: str) -> str:
    """The verdict the state holds. This engine's own arithmetic cannot see a Critical
    the hygiene scan files at finalize, which caps a `pass` at `pass with risks`."""
    try:
        state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return str(state.get("verdict") or fallback) if isinstance(state, dict) else fallback


def leads_text(leads) -> str:
    """The report's list of what was read and not proven — for a person, or for the next
    run that can judge it. Capped, and it says so when it is."""
    if not leads:
        return ""
    shown = leads[:LEADS_IN_REPORT]
    lines = [f"\n\n**Leads — read by a small model, not proven, not filed ({len(leads)}).** "
             "Each is a question for a run that can judge it; none is on the record."]
    for x in shown:
        lines.append(f"- `{x['path']}:{x['line']}` `{x['function']}` — {x['title']} "
                     f"(read as {x['severity']}; {x['why']})")
    if len(leads) > len(shown):
        lines.append(f"- … and {len(leads) - len(shown)} more, not listed")
    return "\n".join(lines)


def not_tested_lines(model: Model, files: list, examined: int, prior_open: list,
                     still_open: list, refiled: list, prove: bool, budget: Budget,
                     quarantine_notes: list, non_python: bool,
                     disabled: str | None = None, unread_survivors: list | None = None) -> list:
    """What a night like this one does not do, counted rather than described.

    The temptation with a cheap engine is to let its report read like the
    expensive one's. This list is what stops that: every line is a number the run
    measured, so a local `pass` is visibly a different sentence from an agent's.
    `disabled` is why no counterfactual ran, when none did — the profile's switch, a
    flag, or a gate with no Python interpreter — named rather than summarised.
    """
    out = [
        f"no agent ran: {model.answered + model.unanswered} bounded question(s) went to "
        f"{model.name} — no exploratory charter, no archaeology, no adversarial reading of "
        "the suite",
        "the commit history: no origin was traced, and no `git log -S` was run",
        f"{len(still_open)} of {len(prior_open)} prior open finding(s) were carried unread, "
        f"and {len(refiled)} re-filed because the code they cite changed and no model looked "
        "at the change",
        f"{len(files)} file(s) and {examined} function(s) were read; nothing else in the "
        "repository was",
        ("claims the counterfactual could not reach — a probe that would not run leaves its "
         f"finding a hypothesis, and an unproven severity is held at {UNPROVEN_CEILING} for a "
         f"reading and at {FAILURE_CEILING} for a failing test the model classified"
         if prove else
         f"everything a counterfactual would show: {disabled or 'proving was disabled this run'}"
         ", so every finding from reading is a hypothesis, and a failing test the model "
         f"classified is held at {FAILURE_CEILING}"),
        "nothing outside the checkout was read — no database, no MCP tools, no production "
        "numbers — so a standing blocker that quotes one was NOT re-read",
        f"{model.unanswered} question(s) the model did not answer"
        + (f", {model.errors} of which the gateway never received" if model.errors else ""),
    ]
    if budget.stopped:
        out.append(f"{budget.skipped} candidate function(s) were never asked about: "
                   f"{budget.stopped}")
    out.extend(f"{path}::{name} — an assertion-gap survivor this run did not read"
               for path, name in (unread_survivors or []))
    if non_python:
        out.append(NO_CODE_READ)
    out.extend(quarantine_notes)
    return out


def print_summary(model: Model, files: list, examined: int, filed: list, refiled: list,
                  resolved: list, still_open: list, verdict: str, owed: dict,
                  budget: Budget, engine_verdict: str | None = None) -> None:
    """At most fifteen lines, ending on the number this whole release is about.
    `verdict` is the one the state holds; `engine_verdict`, this engine's own, is
    named when finalize capped it."""
    lines = [
        f"verdict-local: verdict {verdict!r}"
        + (f" (this engine's {engine_verdict!r}, capped at finalize by a Critical the "
           "hygiene scan filed)" if engine_verdict and engine_verdict != verdict else ""),
        f"  read       {examined} function(s) in {len(files)} file(s)"
        + (f", {budget.skipped} skipped — {budget.stopped}" if budget.stopped else ""),
        f"  filed      {len(filed)} finding(s), {len(refiled)} of them re-filed unread",
        f"  carried    {len(still_open)} by id · resolved {len(resolved)} by measurement",
        f"  model      {model.name} · {model.calls} call(s) · "
        f"{model.input_tokens + model.output_tokens:,} token(s) · "
        f"{model.unanswered} unanswered · {model.errors} transport error(s)",
    ]
    for key, value in sorted(owed.items()):
        lines.append(f"  needs a model run: {key} — {value}")
    print("\n".join(lines[:14] + ["  Claude tokens: 0"]), file=sys.stderr)


def verdict_for(filed: list) -> str:
    """The verdict is arithmetic over the findings, not an opinion: an open Blocker
    forces `fail`, and so does a Critical this mode could not disprove."""
    severities = {f.get("severity") for f in filed}
    if "Blocker" in severities or "Critical" in severities:
        return "fail"
    return "pass with risks" if filed else "pass"


def resolve_range(repo: Path, explicit, base) -> str | None:
    """`BASE..HEAD` from `--range`, or from `--base` through the merge base.

    A branch is judged against where it left the trunk, not against the trunk's
    tip: `main..HEAD` after somebody else merges reads their commits as this
    branch's change. `git merge-base` asks the question that was meant.
    """
    if explicit:
        return str(explicit)
    if not base:
        return None
    merge_base = _git(["merge-base", str(base), "HEAD"], repo)
    if not merge_base:
        print(f"verdict-local: --base {base} has no merge base with HEAD in {repo}",
              file=sys.stderr)
        return None
    return f"{merge_base}..HEAD"


def read_env_file(path: Path) -> dict:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="verdict-local", description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", default=None)
    ap.add_argument("--repo", default=None)
    # `chat`, not the alias the first nights used: DECISIONS.md 2026-09-25 measured that one
    # thinking through its whole budget and answering 1 question in 9, so a run that omitted
    # `--model` spent the night to exit 5 (audit 2026-10-02, O-D-5).
    ap.add_argument("--model", default=os.environ.get("VERDICT_LOCAL_MODEL", "chat"),
                    help="the model name sent to the gateway (default: $VERDICT_LOCAL_MODEL, "
                         "else `chat`). An alias that thinks through its whole budget "
                         "answers nothing, and the run exits 5 after the suite has run")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="KEY=VALUE file with ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN")
    ap.add_argument("--limit", type=int, default=8, metavar="N",
                    help="read at most N files, least covered first (default 8)")
    ap.add_argument("--gate", default=None, metavar="CMD",
                    help="the suite command; `{report}` is rendered to a JUnit path. "
                         "Default: the profile's gate, else pytest")
    ap.add_argument("--no-prove", dest="prove", action="store_false",
                    help="do not flip claimed lines in a scratch copy to test them; every "
                         "finding then stays a hypothesis")
    ap.add_argument("--reruns", type=int, default=2, metavar="N",
                    help="run the suite N more times to find tests that are not stable "
                         "(default 2); flakiness is measured, never asked of the model")
    ap.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--num-ctx", type=int, metavar="TOKENS",
                    default=int(os.environ.get("VERDICT_LOCAL_NUM_CTX") or DEFAULT_NUM_CTX),
                    help="the context window each question asks the server for (default "
                         f"{DEFAULT_NUM_CTX}); 0 leaves the server's own default, which on "
                         "Ollama is 4,096 and cuts long questions from the front")
    ap.add_argument("--delta", action="store_true",
                    help="a delta against the stored baseline: every prior open finding is "
                         "resolved by measurement, carried by id, or re-filed with the drift "
                         "that moved it — never left silent. Implied by a QA root that "
                         "already holds a state")
    ap.add_argument("--qa-root", default=None, metavar="DIR",
                    help="the QA root to write. REQUIRED with --range/--base: a linked "
                         "worktree resolves the MAIN worktree's project key, so a branch run "
                         "without this would write the project's own state")
    ap.add_argument("--range", dest="sha_range", default=None, metavar="BASE..HEAD",
                    help="judge this commit range instead of the one since the last run")
    ap.add_argument("--base", default=None, metavar="REF",
                    help="judge the range since the merge base with REF")
    ap.add_argument("--reuse-facts", action="store_true",
                    help="use facts.json when it was measured for this same HEAD within "
                         f"{REUSE_MAX_AGE_MIN:.0f} minutes (verdict-run's sweep attempt) "
                         "instead of running the gates again")
    ap.add_argument("--reference-state", type=Path, default=None, metavar="PATH",
                    help="the project's real state.json, read-only, to say which of its open "
                         "findings this range touches")
    ap.add_argument("--max-functions", type=int, default=None, metavar="N",
                    help=f"ask about at most N functions (default {MAX_FUNCTIONS}; "
                         f"{GATE_MAX_FUNCTIONS} when a range is named)")
    ap.add_argument("--max-probes", type=int, default=None, metavar="N",
                    help="apply at most N counterfactuals; the rest stay hypotheses")
    ap.add_argument("--max-model-s", type=int, default=None, metavar="S",
                    help="stop asking after S seconds and report what went unread")
    args = ap.parse_args(argv)

    env = dict(os.environ)
    if args.env_file:
        if not args.env_file.is_file():
            print(f"verdict-local: --env-file {args.env_file} does not exist", file=sys.stderr)
            return 2
        env.update(read_env_file(args.env_file))
    base_url, token = env.get("ANTHROPIC_BASE_URL"), env.get("ANTHROPIC_AUTH_TOKEN")
    if not base_url or not token:
        print("verdict-local: ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are required — "
              "point them at a gateway that speaks the Anthropic messages API "
              "(LiteLLM in front of Ollama, for example)", file=sys.stderr)
        return 2

    repo = Path(args.repo).expanduser().resolve() if args.repo else Path.cwd()
    if (args.sha_range or args.base) and not args.qa_root:
        # P-31, and the reason this is required rather than defaulted: in a linked
        # worktree `derive_key` returns the MAIN worktree's key, so a branch run
        # would resolve — and overwrite — the project's own state root with a
        # judgment about a branch nobody has merged.
        print("verdict-local: --range/--base needs --qa-root. A branch run resolves the MAIN "
              "worktree's project key, so without it this would write the project's own "
              "state from a branch. Point it at a throwaway directory holding a copy of the "
              "key's profile.md.", file=sys.stderr)
        return 2
    sha_range = resolve_range(repo, args.sha_range, args.base)
    if args.base and not sha_range:
        return 2
    if args.qa_root:
        qa_root = Path(args.qa_root).expanduser().resolve()
        project = args.project or str(qa_root)
    else:
        project = args.project or (str(repo) if resolve_root(str(repo)) else derive_key(repo)[0])
        qa_root = resolve_root(project) or (state_home() / project)

    ranged = bool(sha_range)
    model = Model(args.model, base_url, token,
                  GATE_CALL_TIMEOUT_S if ranged and args.timeout_s == DEFAULT_TIMEOUT_S
                  else args.timeout_s, num_ctx=args.num_ctx)
    alive, detail = gateway_alive(base_url, token)
    if not alive:
        # Asked before the suite, not after. A dead gateway found at the first
        # question has already cost a whole suite run and left a marker claiming a
        # run in progress; found here, nothing is written at all and the night is
        # recorded as one where no model was available.
        print(f"verdict-local: the gateway is not answering — {detail}. Nothing was measured "
              "and no state was written: a run with no model is not a QA pass.",
              file=sys.stderr)
        return 5
    os.environ["VERDICT_MODEL"] = f"local:{model.name}"
    # Three shapes, three budgets: a gate over a range, a night over a project that already
    # has a record, and a first pass over a fresh one (unbounded in time, as before).
    night = not ranged and (qa_root / "state.json").is_file()
    budget = Budget(
        functions=(args.max_functions if args.max_functions is not None
                   else GATE_MAX_FUNCTIONS if ranged
                   else NIGHT_MAX_FUNCTIONS if night else MAX_FUNCTIONS),
        probes=(args.max_probes if args.max_probes is not None
                else GATE_MAX_PROBES if ranged
                else NIGHT_MAX_PROBES if night else None),
        seconds=(args.max_model_s if args.max_model_s is not None
                 else GATE_MODEL_BUDGET_S if ranged
                 else NIGHT_MODEL_BUDGET_S if night else None))
    # A named range is a gate somebody is waiting for, so it takes the caps
    # unless the operator overrode them: six files, and no repeat runs of the
    # whole suite — three green suites prove nothing about a diff.
    limit = GATE_MAX_FILES if ranged and args.limit == 8 else args.limit
    reruns = 0 if ranged and args.reruns == 2 else args.reruns
    print(f"verdict-local: {clock.now():%Y-%m-%dT%H:%M:%SZ} · project {project!r} · {detail}",
          file=sys.stderr)
    return run(repo, qa_root, model, limit, args.gate, reruns, args.prove,
               delta=args.delta or (qa_root / "state.json").is_file(),
               sha_range=sha_range, reference_state=args.reference_state, budget=budget,
               reuse_facts=args.reuse_facts)


if __name__ == "__main__":
    sys.exit(main())
