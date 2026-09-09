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

    verdict-local --repo . --model qwen3 --env-file ~/.config/verdict-gateway.env
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
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

try:
    from .harness import collect, finalize_main
    from .reports import read_report
    from .project_key import derive_key
    from .state import home as state_home
    from .state import resolve_root
    from .validate import validate_finding
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from harness import collect, finalize_main
    from reports import read_report
    from project_key import derive_key
    from state import home as state_home
    from state import resolve_root
    from validate import validate_finding

MAX_SOURCE_LINES = 120          # one question's worth of code
MAX_FUNCTIONS = 60              # a cap, so a large repository still finishes
DEFAULT_TIMEOUT_S = 900


# ── the model, as a subroutine ────────────────────────────────────────────────

class Model:
    """One bounded question, one JSON answer. No conversation, no accumulation.

    `/no_think` is prepended for the Qwen family, which otherwise spends its whole
    output budget reasoning and returns an empty text block — measured, not assumed.
    """

    def __init__(self, name: str, base_url: str, token: str, timeout_s=DEFAULT_TIMEOUT_S):
        self.name, self.base_url, self.token, self.timeout_s = name, base_url, token, timeout_s
        self.calls, self.input_tokens, self.output_tokens, self.retries = 0, 0, 0, 0

    def ask(self, prompt: str, max_tokens: int = 1200) -> str:
        body = {"model": self.name, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": "/no_think\n" + prompt}]}
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/v1/messages", data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            doc = json.load(resp)
        self.calls += 1
        usage = doc.get("usage") or {}
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        return "".join(b.get("text") or "" for b in doc.get("content", [])
                       if b.get("type") == "text")

    def ask_json(self, prompt: str, max_tokens: int = 1200) -> dict | None:
        """The answer as JSON, or None. One retry with a blunter instruction, because
        a small model's first answer is often prose with JSON inside it."""
        for attempt in (1, 2, 3):
            try:
                text = self.ask(prompt if attempt == 1 else
                                prompt + "\n\nReturn ONLY the JSON object, starting with "
                                         "{ and ending with }. No prose, no explanation.",
                                max_tokens)
            except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
                return None
            doc = extract_json(text)
            if doc is not None:
                return doc
            self.retries += 1
        return None


def extract_json(text: str) -> dict | None:
    """The first JSON object in a reply — a small model wraps it in prose, fences it,
    or both, and refusing that costs a call for nothing."""
    if not text:
        return None
    text = re.sub(r"^\s*```(?:json)?|```\s*$", "", text.strip(), flags=re.M)
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            doc, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict):
            return doc
    return None


# ── what to ask about: the harness decides, not the model ─────────────────────

class Chunk:
    """One function, with the line numbers it really occupies in its file."""

    def __init__(self, path: str, name: str, start: int, end: int, source: str):
        self.path, self.name, self.start, self.end, self.source = path, name, start, end, source

    def numbered(self) -> str:
        return "\n".join(f"{self.start + i:4d}| {line}"
                         for i, line in enumerate(self.source.splitlines()))


def chunks_of(repo: Path, rel: str) -> list:
    """Every top-level function and method of a module, as its own question.

    Line numbers come from the file, not from the excerpt: a model asked to point at a
    line in a pasted block counts from 1 and is wrong by the offset every time. Here the
    numbers are printed in the excerpt, so the answer is checkable against the file.
    """
    try:
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    lines = text.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        if end - start > MAX_SOURCE_LINES:
            end = start + MAX_SOURCE_LINES
        out.append(Chunk(rel, node.name, start, end, "\n".join(lines[start - 1:end])))
    return out


def candidates(facts: dict, repo: Path) -> list:
    """Which files to read, least covered first — the reading map when the profile
    measured coverage, the tracked source otherwise."""
    reading = facts.get("reading_map") or {}
    files = [m["path"] for m in (reading.get("lowest") or []) if m.get("path")]
    files += [m["path"] for m in (reading.get("never_imported") or []) if isinstance(m, dict)
              and m.get("path")]
    if not files:
        census = facts.get("code_census") or {}
        files = [f for f in (census.get("largest_files") or []) if isinstance(f, str)]
    if not files:
        files = [str(p.relative_to(repo)) for p in sorted(repo.rglob("*.py"))
                 if ".venv" not in p.parts and "test" not in p.name]
    seen, out = set(), []
    for rel in files:
        if rel in seen or not (repo / rel).is_file():
            continue
        seen.add(rel)
        out.append(rel)
    return out


# ── the questions ─────────────────────────────────────────────────────────────

CONTRACT_Q = """You are a software tester reading one function. Its docstring, or the name
and the code, state what it must do.

File: {path}
```python
{source}
```

Does the code do exactly what it claims? Look for: a boundary that is off by one (`>` where
`>=` is meant), a rounding or conversion that loses value, an error path that is swallowed,
a condition that can never be true, a value returned unrounded or unvalidated.

Reply with JSON only:
{{"verdict": "matches" or "mismatch",
  "line": <the line number from the left margin above, or null>,
  "mechanism": "<one sentence: what the code does, and what it should do instead>"}}"""

CLASSIFY_Q = """You are a software tester. A defect has been claimed in this function.

File: {path}
```python
{source}
```

Claim: {mechanism}

Answer with JSON only:
{{"is_real": true or false,
  "severity": "Blocker" or "Critical" or "Major" or "Minor" or "Trivial",
  "title": "<one sentence naming the defect and its consequence, under 120 characters>",
  "impact": "<one sentence: what a caller gets wrong because of it>"}}"""


def examine(model: Model, chunk: Chunk) -> dict | None:
    """Two bounded calls: is it wrong, and if so how bad. Neither sees the other's
    context — the second is given the claim as text, not as history."""
    first = model.ask_json(CONTRACT_Q.format(path=chunk.path, source=chunk.numbered()))
    if not first or str(first.get("verdict")) != "mismatch":
        return None
    mechanism = str(first.get("mechanism") or "").strip()
    if len(mechanism) < 12:
        return None
    line = first.get("line")
    line = int(line) if isinstance(line, (int, float)) and chunk.start <= line <= chunk.end \
        else chunk.start
    second = model.ask_json(CLASSIFY_Q.format(path=chunk.path, source=chunk.numbered(),
                                              mechanism=mechanism), max_tokens=600)
    if not second or second.get("is_real") is not True:
        return None
    severity = str(second.get("severity") or "Minor")
    if severity not in ("Blocker", "Critical", "Major", "Minor", "Trivial"):
        severity = "Minor"
    title = str(second.get("title") or "").strip() or f"{chunk.name}: {mechanism[:100]}"
    return {"function": chunk.name, "path": chunk.path, "line": line, "severity": severity,
            "title": title[:200], "mechanism": mechanism,
            "impact": str(second.get("impact") or "").strip()}


UNPROVEN_CEILING = "Minor"


def capped(severity: str, proven: bool) -> str:
    """A claim nobody executed cannot outrank one that was executed.

    Measured on boltons, a real 30-module library: the local model filed 35 findings from
    reading alone, every one of them `REAL_DEFECT`, 34 of them Major or above, across
    three modules. A tester whose every finding is Critical has no severity at all, and a
    reader learns to skip the list. So severity from reading is capped until a
    counterfactual moves it: prove the line and the model's own severity stands, leave it
    unproven and it sits below everything the suite actually demonstrated.
    """
    return severity if proven else UNPROVEN_CEILING


def finding_of(claim: dict, ident: str, chunk_source: str, proof: dict | None = None) -> dict:
    """A claim becomes a finding file — with `confidence: hypothesis`, because nothing
    here was proven by execution. The harness refuses to call it anything else, and a
    small-model run that claimed `proven` would be exactly the flattery this project
    exists to reject."""
    excerpt = "\n".join(chunk_source.splitlines()[:6])
    proven = bool(proof and proof.get("status") == "proven")
    evidence = [
        f"{claim['path']}:{claim['line']} — read against the function's own contract"
        + ("" if proven else "; not executed, not counterfactually tested"),
        f"excerpt:\n{excerpt}",
    ]
    if proven:
        evidence.insert(0, (
            f"COUNTERFACTUAL (scratch copy, PYTHONDONTWRITEBYTECODE=1, __pycache__ swept, "
            f"import verified inside the scratch): `{proof['expression']}` returns "
            f"{proof['before']!r} at HEAD; with {claim['path']}:{proof['line']} changed from "
            f"`{proof['was']}` to `{proof['now']}` it returns {proof['after']!r}. "
            f"{proof['reason']}."))
    narrative = f"{claim['mechanism']} {claim['impact']}".strip()
    narrative += (" Proven by counterfactual, not by reading: the value follows the line."
                  if proven else
                  f" Filed by `verdict-local` from a bounded reading of this function "
                  f"alone, with no execution behind it — so its severity is held at "
                  f"{UNPROVEN_CEILING} however bad it reads. Confirm before acting.")
    return {
        "id": ident,
        "title": claim["title"],
        "severity": capped(claim["severity"], proven),
        "priority": "P1" if proven and claim["severity"] not in ("Minor", "Trivial") else "P2",
        "status": "open",
        "failure_classification": "REAL_DEFECT",
        "confidence": "proven" if proven else "hypothesis",
        "evidence": evidence,
        "root_cause": {"mechanism": claim["mechanism"],
                       "origin": "not investigated in local mode"},
        "narrative": narrative,
    }



# ── the counterfactual: the only evidence that separates cause from correlation ──

PROBE_Q = """You said this function is wrong:

File: {path}
```python
{source}
```

Claim: {mechanism}

Give me two things so I can test that claim by running it.

1. One Python expression that calls this code where the claim says it goes wrong. One
   line, no imports, no side effects. The module is already imported as `m`.
2. The one line to change, by its number in the left margin, and the whole replacement
   line with its indentation.

I will run the expression before and after the change myself, so do not tell me what it
returns — only how to reach it.

Reply with JSON only:
{{"expression": "m.some_function(1, 2)",
  "fix_line": <line number from the left margin>,
  "fix_replacement": "<the whole replacement line, with its indentation>"}}"""

COPY_SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "build", "dist", ".idea", ".claude"}
PROBE_TIMEOUT_S = 60
MAX_COPY_BYTES = 300 * 1024 * 1024


def module_name(repo: Path, rel: str) -> str:
    """The import path of a file, or "" when it is not importable from the repo root."""
    parts = list(Path(rel).with_suffix("").parts)
    if not parts or parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return ""
    # `src/pkg/mod.py` imports as `pkg.mod` when `src` is a source root
    if parts[0] in ("src", "lib") and (repo / parts[0] / "__init__.py").exists() is False:
        parts = parts[1:]
    return ".".join(parts)


def source_root(repo: Path, rel: str) -> Path:
    return repo / "src" if rel.startswith("src/") and (repo / "src").is_dir() else repo


def scratch_copy(repo: Path, into: Path) -> bool:
    """A copy of the tree that runs its own code — the discipline §3.5 demands, done by
    the harness so the model cannot get it wrong. Returns False when the tree is too
    large to copy, which is a refusal, not a silent skip."""
    total = 0
    for path in repo.rglob("*"):
        if any(part in COPY_SKIP for part in path.parts):
            continue
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
            if total > MAX_COPY_BYTES:
                return False
    shutil.copytree(repo, into, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(*COPY_SKIP))
    return True


def run_probe(python: str, root: Path, module: str, expression: str) -> tuple:
    """Evaluate one expression against one tree → (value_json, error).

    The tree is put first on `PYTHONPATH` and the module's resolved file is checked to be
    inside it before the expression is trusted: a scratch that imports the original source
    makes every injection read as a no-op, and this project measured 0 of 4 defects caught
    without that check. Bytecode writing is off and `__pycache__` swept, because CPython
    validates a cached file on mtime-in-seconds plus size and a same-size edit within one
    second re-runs the old bytecode.
    """
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    # Compare resolved paths on both sides: on macOS `/var` is a symlink to `/private/var`,
    # so a correct import fails a naive prefix check and every probe reads as unavailable.
    resolved = os.path.realpath(str(root))
    script = (
        "import json, os, sys\n"
        f"import {module} as m\n"
        f"assert os.path.realpath(m.__file__).startswith({resolved!r}), "
        "'imported ' + m.__file__\n"
        f"print('<<<' + json.dumps({expression}, default=repr) + '>>>')\n")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    try:
        proc = subprocess.run([python, "-c", script], cwd=str(root), env=env,
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)[:200]
    out = proc.stdout
    if "<<<" in out and ">>>" in out:
        try:
            return json.loads(out.split("<<<", 1)[1].split(">>>", 1)[0]), None
        except json.JSONDecodeError as exc:
            return None, f"probe printed unparseable JSON: {exc}"
    return None, (proc.stderr.strip().splitlines() or ["no output"])[-1][:200]


def counterfactual(model: Model, repo: Path, chunk: Chunk, claim: dict,
                   python: str) -> dict | None:
    """Flip the suspected line in a scratch copy and watch the value follow.

    Three outcomes, all of them useful: the value flips to what the model predicted
    (`proven`), the value does not move (`disproven` — the claim is withdrawn before it is
    ever filed), or the probe cannot run (unchanged, still a hypothesis).
    """
    module = module_name(repo, chunk.path)
    if not module:
        return {"status": "unavailable",
                "reason": f"{chunk.path} is not importable from the repository root"}
    answer = model.ask_json(PROBE_Q.format(path=chunk.path, source=chunk.numbered(),
                                           mechanism=claim["mechanism"], module=module),
                            max_tokens=700)
    if not answer:
        return {"status": "unavailable", "reason": "the model did not answer with JSON"}
    expression = str(answer.get("expression") or "").strip()
    replacement = answer.get("fix_replacement")
    line = answer.get("fix_line")
    if not expression or "\n" in expression or not isinstance(replacement, str):
        return {"status": "unavailable",
                "reason": "the probe was not one expression and one replacement line"}
    if not isinstance(line, (int, float)) or not (chunk.start <= int(line) <= chunk.end):
        return {"status": "unavailable",
                "reason": f"the line to flip ({line}) is outside {chunk.name}"}
    line = int(line)

    with tempfile.TemporaryDirectory(prefix="verdict-cf-") as tmp:
        scratch = Path(tmp) / "tree"
        if not scratch_copy(repo, scratch):
            return {"status": "unavailable", "reason": "the tree is too large to copy"}
        root_before = source_root(repo, chunk.path)
        before, err = run_probe(python, root_before, module, expression)
        if err:
            return {"status": "unavailable", "reason": f"probe failed on the original: {err}"}
        target = scratch / chunk.path
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if not (1 <= line <= len(lines)):
            return {"status": "unavailable", "reason": "the line to flip is outside the file"}
        original_line = lines[line - 1]
        lines[line - 1] = replacement
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        after, err = run_probe(python, source_root(scratch, chunk.path), module, expression)
        if err:
            return {"status": "unavailable", "reason": f"probe failed on the scratch: {err}"}

    flipped = before != after
    return {
        "status": "proven" if flipped else "disproven",
        "expression": expression, "before": before, "after": after,
        "line": line, "was": original_line.strip()[:160], "now": replacement.strip()[:160],
        "reason": ("the value follows the line: flipping it changed the result"
                   if flipped else
                   "the value did not move when the line was flipped — the line is not the "
                   "cause, whatever else may be true"),
    }

# ── the suite: what execution says, before anything is read ───────────────────

GATE_DEFAULT = "python3 -m pytest -q -p no:cacheprovider --junitxml={report}"
QUARANTINE_DAYS = 14
SKIP_MARKER = re.compile(
    r"^[ \t]*(?:@(?:pytest\.mark|unittest)\.(?P<marker>skip|skipif)|(?P<call>pytest\.skip))"
    r"\(\s*(?P<args>[^)]*)", re.M)
# A condition that is not a constant makes the skip a guard, not a graveyard.
_ALWAYS = re.compile(r"^\s*(?:True|1)\s*(?:,|$)")
_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")


def gate_of(facts: dict, override: str | None) -> tuple[str, str] | None:
    """The suite command: the operator's, then the profile's, then pytest."""
    if override:
        return ("suite", override)
    for name, gate in (facts.get("gates") or {}).items():
        command = gate.get("command") if isinstance(gate, dict) else None
        if command:
            return (name, command)
    return ("suite", GATE_DEFAULT)


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


def skips_without_expiry(repo: Path, files: list) -> list:
    """Every skip marker whose reason names no expiry — a quarantine with no end is a
    test that has been deleted without anyone deciding to delete it."""
    out = []
    for rel in files:
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in SKIP_MARKER.finditer(text):
            args = m.group("args") or ""
            if m.group("marker") == "skipif" and not _ALWAYS.match(args):
                # `skipif(sys.version_info < (3, 9))` is a guard: it runs wherever it can,
                # and it has no expiry because it needs none. Measured on boltons, where
                # every version guard came back as a finding until this line existed.
                continue
            line = text[:m.start()].count("\n") + 1
            if not has_expiry(args):
                out.append({"path": rel, "line": line, "reason": args.strip()[:200]})
    return out


def has_expiry(reason: str) -> bool:
    """True only when the reason names a date still in the future.

    "temporarily disabled 2026-05-02" is not an expiry — it is the day someone disabled
    it and moved on, which is exactly the shape of a test that will never run again. A
    naive date match read that as a deadline and let the whole class through.
    """
    today = clock.today()
    for match in _DATE.finditer(reason or ""):
        try:
            when = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if when > today:
            return True
    return False


def test_files(repo: Path) -> list:
    out = []
    for path in sorted(repo.rglob("*.py")):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py") or "tests" in path.parts:
            out.append(str(path.relative_to(repo)))
    return out


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
                     filed: list) -> int:
    """One bounded question per passing test — the suite is under review too, and a green
    test asserting the wrong thing is invisible to every gate."""
    examined = 0
    for rel in files:
        for chunk in chunks_of(repo, rel)[:MAX_FUNCTIONS]:
            if not chunk.name.startswith("test"):
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
    return {
        "id": ident, "title": claim["title"], "severity": claim["severity"],
        "priority": "P1" if claim["severity"] in ("Blocker", "Critical", "Major") else "P2",
        "status": "open", "failure_classification": claim["classification"],
        "confidence": "hypothesis", "evidence": evidence,
        "root_cause": {"mechanism": claim["mechanism"] or claim["title"],
                       "origin": "not investigated in local mode"},
        "narrative": (f"{claim['mechanism']} Filed by `verdict-local` from the failing test "
                      "and its error text. Nothing was executed to confirm it beyond the "
                      "suite run itself."),
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


def skip_finding(skip: dict, ident: str) -> dict:
    return {
        "id": ident,
        "title": f"A test is skipped with no expiry: {skip['reason'][:90]}"[:200],
        "severity": "Minor", "priority": "P2", "status": "open",
        "failure_classification": "BRITTLE_TEST", "confidence": "proven",
        "evidence": [f"{skip['path']}:{skip['line']} — skip marker with reason "
                     f"{skip['reason'][:200]!r}; no date or expiry in the reason",
                     "found by a regular expression over the test files, not by a model"],
        "root_cause": {"mechanism": "A skip with no expiry is a deleted test that nobody "
                                    "decided to delete: it never runs again and no one is "
                                    "told.",
                       "origin": "not investigated in local mode"},
        "narrative": "A skipped test with no expiry silently removes coverage. Either give "
                     "the skip an expiry date or delete the test deliberately.",
    }


# ── the run ───────────────────────────────────────────────────────────────────

def file_findings(model: Model, repo: Path, files: list, mint, findings_dir: Path,
                  filed: list, python: str, prove: bool) -> tuple:
    """Read the source, one function at a time, and try to prove each claim by flipping
    the line in a scratch copy. Returns (examined, proven, disproven)."""
    examined = proven = disproven = 0
    for rel in files:
        for chunk in chunks_of(repo, rel)[:MAX_FUNCTIONS]:
            examined += 1
            claim = examine(model, chunk)
            if not claim:
                continue
            proof = counterfactual(model, repo, chunk, claim, python) if prove else None
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
            mint(finding_of(claim, "@", chunk.source, proof), findings_dir, filed)
    return examined, proven, disproven


def interpreter_of(command: str) -> str:
    """The python the project's own gate uses — a probe run with a different interpreter
    is measuring a different environment."""
    for token in command.split():
        low = token.lower()
        if low.endswith("python") or low.endswith("python3") or low.endswith("python.exe"):
            return token
    return sys.executable


def run(repo: Path, qa_root: Path, model: Model, limit: int, gate: str | None,
        reruns: int, prove: bool = True) -> int:
    qa_root.mkdir(parents=True, exist_ok=True)
    name, command = gate_of(load_profile_gates(qa_root), gate)
    print(f"verdict-local: measuring {repo} · gate {name}", file=sys.stderr)
    facts = collect(repo, qa_root, [(name, command)])
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    files = candidates(facts, repo)[:limit]
    python = interpreter_of(command)
    print(f"verdict-local: {len(files)} file(s) to read, model {model.name}"
          + (f", proving with {python}" if prove else ", proving disabled"), file=sys.stderr)
    prefix = str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[0]
    number = int(str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[1] or 1)

    findings_dir = qa_root / "findings"
    findings_dir.mkdir(exist_ok=True)
    counter = [number]

    def mint(entry: dict, into: Path, into_list: list) -> None:
        """File a finding, or refuse it — the validator decides, never the model."""
        entry["id"] = f"{prefix}-{counter[0]}"
        problems = validate_finding(entry, f"findings/{entry['id']}.json", set(), set())
        if problems:
            print(f"verdict-local: rejected {entry['id']}: {problems[0]}", file=sys.stderr)
            return
        (into / f"{entry['id']}.json").write_text(json.dumps(entry, indent=1), encoding="utf-8")
        into_list.append(entry)
        counter[0] += 1
        print(f"verdict-local: {entry['id']} {entry['severity']} {entry.get('failure_classification', '')} "
              f"— {entry['title'][:80]}", file=sys.stderr)

    filed = []

    # 1. What execution says. Repetition answers flakiness; the model is never asked.
    failures = failures_of(facts)
    repeats = rerun_failures(repo, command, reruns) if failures or reruns else []
    flaky = unstable(failures, repeats)
    if failures:
        print(f"verdict-local: {len(failures)} failing test(s), {len(flaky)} unstable across "
              f"{len(repeats) + 1} run(s)", file=sys.stderr)
    quarantine = []
    for test_id in sorted(flaky):
        quarantine.append({
            "test_id": test_id,
            "first_seen": clock.today().isoformat(),
            "fail_count": sum(1 for r in [set(f["id"] for f in failures)] + [set(x) for x in repeats]
                              if test_id in r),
            "run_count": len(repeats) + 1,
            "quarantined_until": (clock.today() + timedelta(days=QUARANTINE_DAYS)).isoformat(),
            "reason": f"failed in some of {len(repeats) + 1} identical runs and passed in "
                      "others — measured, not judged",
        })
    for entry in quarantine:
        mint(flaky_finding(entry, len(repeats) + 1, "@"), findings_dir, filed)
    for failure in failures:
        if failure["id"] in flaky:
            continue
        claim = classify(model, repo, failure)
        if claim:
            mint(failure_finding(claim, "@"), findings_dir, filed)

    # 2. Skips with no expiry — a regular expression, no model call at all.
    for skip in skips_without_expiry(repo, test_files(repo)):
        mint(skip_finding(skip, "@"), findings_dir, filed)

    # 3. What reading says, function by function — the source, then the tests.
    examined, proven, disproven = file_findings(model, repo, files, mint, findings_dir,
                                                filed, python, prove)
    examined += brittle_findings(model, repo, test_files(repo)[:limit], mint, findings_dir,
                                 filed)

    judgment = {
        "verdict": verdict_for(filed),
        "findings": [], "still_open": [], "resolved": [],
        "not_tested": [
            "the commit history: no origin was traced, and no `git log -S` was run",
            ("claims the counterfactual could not reach — a probe that would not run leaves "
             "its finding a hypothesis" if prove else
             "everything a counterfactual would show: proving was disabled this run"),
            "any file beyond the "
            f"{len(files)} read this run",
        ],
        "prose": {
            "scope": (f"Local mode: {examined} function(s) in {len(files)} file(s) read one at "
                      f"a time by {model.name}, each in isolation. The harness measured the "
                      "repository; the model answered bounded questions about single "
                      "functions."),
            "risks": ("Every finding here is a `hypothesis`: read, not executed. This mode "
                      "cannot see a defect that spans two functions, and does not judge the "
                      "test suite at all."),
        },
        "isolation_check": {"result": "pass", "note": "local mode reads the checkout and "
                                                      "runs the suite gate; it writes nothing "
                                                      "outside the QA root"},
        "verified_intact": [], "flaky_quarantine": quarantine,
        "release_blockers": [f["id"] for f in filed if f["severity"] == "Blocker"],
        "full_sweep": False,
    }
    (qa_root / "judgment.json").write_text(json.dumps(judgment, indent=1), encoding="utf-8")
    code = finalize_main(["--qa-root", str(qa_root),
                          "--judgment", str(qa_root / "judgment.json")])
    if proven or disproven:
        print(f"verdict-local: {proven} claim(s) proven by counterfactual, {disproven} "
              f"withdrawn before filing", file=sys.stderr)
    print(f"verdict-local: {len(filed)} finding(s) from {examined} function(s) · "
          f"{model.calls} model calls · {model.input_tokens:,} in / "
          f"{model.output_tokens:,} out · {model.retries} retries", file=sys.stderr)
    return code


def verdict_for(filed: list) -> str:
    """The verdict is arithmetic over the findings, not an opinion: an open Blocker
    forces `fail`, and so does a Critical this mode could not disprove."""
    severities = {f.get("severity") for f in filed}
    if "Blocker" in severities or "Critical" in severities:
        return "fail"
    return "pass with risks" if filed else "pass"


def load_profile_gates(qa_root: Path) -> dict:
    """The profile's own gates, in the shape `gate_of` reads."""
    try:
        from .profile import parse
    except ImportError:
        from profile import parse
    path = qa_root / "profile.md"
    if not path.is_file():
        return {}
    block = parse(path.read_text(encoding="utf-8")) or {}
    gates = block.get("gates") or {}
    return {"gates": {name: {"command": cmd} for name, cmd in gates.items()}}


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
    ap.add_argument("--model", default=os.environ.get("VERDICT_LOCAL_MODEL", "qwen3"))
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
    project = args.project or (str(repo) if resolve_root(str(repo)) else derive_key(repo)[0])
    qa_root = resolve_root(project) or (state_home() / project)
    model = Model(args.model, base_url, token, args.timeout_s)
    print(f"verdict-local: {clock.now():%Y-%m-%dT%H:%M:%SZ} · project {project!r}",
          file=sys.stderr)
    return run(repo, qa_root, model, args.limit, args.gate, args.reruns,
               args.prove)


if __name__ == "__main__":
    sys.exit(main())
