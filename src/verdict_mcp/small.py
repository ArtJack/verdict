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
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

try:
    from .anchors import refs_in
    from .harness import (RETRY_WINDOW_HOURS, _git, _parse_marker_time, _run_test, collect,
                          finalize_main, is_test_file)
    from .filed import FINDINGS_DIR, archive_findings
    from .profile import ProfileError, gates_from
    from .profile import load as load_profile
    from .reports import read_report
    from .project_key import derive_key
    from .state import home as state_home
    from .state import norm_status, resolve_root
    from .validate import known_tests, validate_finding
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from anchors import refs_in
    from harness import (RETRY_WINDOW_HOURS, _git, _parse_marker_time, _run_test, collect,
                         finalize_main, is_test_file)
    from filed import FINDINGS_DIR, archive_findings
    from profile import ProfileError, gates_from
    from profile import load as load_profile
    from reports import read_report
    from project_key import derive_key
    from state import home as state_home
    from state import norm_status, resolve_root
    from validate import known_tests, validate_finding

MAX_SOURCE_LINES = 120          # one question's worth of code
MAX_FUNCTIONS = 60              # a cap, so a large repository still finishes
DEFAULT_TIMEOUT_S = 900
# The window each question asks for. Ollama serves every model at 4,096 tokens unless told
# otherwise, and past that it keeps only the END of the prompt: the instructions go first,
# `/no_think` with them, and the model thinks through its whole budget and answers nothing
# or invents something. Measured 2026-09-17 through the author's gateway, one ~6k-token
# prompt with a code word on its first line: at the default it arrived as 2,050 tokens and
# the model answered "0126"; asked with `num_ctx: 8192` it arrived whole (5,943 tokens), the
# answer was right, and it came back in 49 seconds instead of 137. Sent on the request, so it
# needs no change on anyone's server; `--num-ctx 0` leaves the server's default alone.
DEFAULT_NUM_CTX = 8192
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
# Five identical runs is what releases a quarantine. Arithmetic, not judgment:
# the model is never asked whether a test has stopped being flaky.
REQUARANTINE_RUNS = 5
REQUARANTINE_TIMEOUT_S = 300
LIVELINESS_PATH = "/health/liveliness"
# The name this engine signs its runs with, in `last_run.engine`, the run marker
# and the report's Judge line. A state that does not say who judged it reads the
# same whether an Opus session or an 8B model on the desk wrote it.
ENGINE = "verdict-local"


# ── the model, as a subroutine ────────────────────────────────────────────────

class Model:
    """One bounded question, one JSON answer. No conversation, no accumulation.

    `/no_think` is prepended for the Qwen family, which otherwise spends its whole
    output budget reasoning and returns an empty text block — measured, not assumed.
    """

    def __init__(self, name: str, base_url: str, token: str, timeout_s=DEFAULT_TIMEOUT_S,
                 num_ctx: int = DEFAULT_NUM_CTX):
        self.name, self.base_url, self.token, self.timeout_s = name, base_url, token, timeout_s
        self.num_ctx = int(num_ctx or 0)
        self.calls, self.input_tokens, self.output_tokens, self.retries = 0, 0, 0, 0
        # A transport failure and an unparseable reply are different facts, and
        # `retries` counted only the second. A night where the gateway died
        # halfway through therefore reported "0 retries" beside a judgment built
        # from half the questions — which reads as a clean run. Counted apart,
        # and both land in `last_run.local`.
        self.errors, self.answered, self.unanswered = 0, 0, 0

    def ask(self, prompt: str, max_tokens: int = 1200) -> str:
        body = {"model": self.name, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": "/no_think\n" + prompt}]}
        if self.num_ctx:
            body["num_ctx"] = self.num_ctx
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/v1/messages", data=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                doc = json.load(resp)
        except urllib.error.HTTPError as exc:
            # A gateway in front of something that is not Ollama may refuse a parameter it
            # does not know. That is a fact about the server, not a failed question: ask
            # again without the window, once, and say what that costs.
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:       # noqa: BLE001 — the body is a courtesy, not evidence
                pass
            if self.num_ctx and exc.code in (400, 422) and "num_ctx" in detail:
                print(f"verdict-local: the gateway refused num_ctx ({exc.code}); asking without "
                      "it — a server that keeps its default window will cut long questions "
                      "from the front", file=sys.stderr)
                self.num_ctx = 0
                return self.ask(prompt, max_tokens)
            raise
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
                self.errors += 1
                self.unanswered += 1
                return None
            doc = extract_json(text)
            if doc is not None:
                self.answered += 1
                return doc
            self.retries += 1
        self.unanswered += 1
        return None


def gateway_alive(base_url: str, token: str | None = None, timeout_s: float = 10.0) -> tuple:
    """Is anything listening → (alive, what the endpoint said).

    Asked BEFORE the suite runs, never after. A gateway discovered dead at the
    first question has already cost a full suite run and left a run marker
    behind announcing a run in progress; asked first it costs one HTTP round
    trip, and the night is recorded honestly as one where no model was
    available rather than as one that judged nothing and said `pass`.
    """
    url = base_url.rstrip("/") + LIVELINESS_PATH
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode() or 0)
    except urllib.error.HTTPError as exc:
        # An HTTP error is still an answer: something is listening. 401 means a
        # credential problem, not a dead endpoint, and calling that "unreachable"
        # sends the operator to the wrong half of the system.
        return 200 <= int(exc.code) < 300, f"{url} answered {exc.code}"
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return False, f"{url} is unreachable: {str(exc)[:160]}"
    return 200 <= code < 300, f"{url} answered {code}"


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


def changed_files(repo: Path, sha_range: str | None) -> list:
    """The files a range touched, as git names them — or [] when there is no range."""
    if not sha_range:
        return []
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", sha_range],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return sorted({ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()})


def changed_lines_of(facts: dict) -> dict:
    """`{path: set(line)}` for the changed lines no test executed, from measured
    coverage. The best free ranking there is: a changed line the suite never ran
    is the code most likely to be wrong and least likely to be caught."""
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") != "measured":
        return {}
    out: dict = {}
    for path, entry in (cov.get("per_file") or {}).items():
        if not isinstance(entry, dict):
            continue
        lines = set()
        for span in entry.get("unexercised_ranges") or []:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                lines |= set(range(int(span[0]), int(span[1]) + 1))
            elif isinstance(span, int):
                lines.add(span)
        if lines:
            out[str(path).replace("\\", "/")] = lines
    return out


def drifted_paths(facts: dict) -> list:
    """Files under a finding whose cited code moved or changed since the evidence
    was written — the second-best free ranking, because the harness already knows
    the reader was about to be misled there."""
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    if drift.get("status") != "measured":
        return []
    out = []
    for rec in (drift.get("findings") or {}).values():
        if not isinstance(rec, dict):
            continue
        for ref in rec.get("refs") or []:
            if isinstance(ref, dict) and ref.get("status") in ("changed", "moved", "missing"):
                path = str(ref.get("ref") or "").rsplit(":", 1)[0]
                if path:
                    out.append(path.replace("\\", "/"))
    return out


def delta_candidates(facts: dict, repo: Path, changed: list) -> list:
    """What to read when the run is a delta: the change, ranked by what nothing ran.

    Coverage rank is the right question for a baseline and the wrong one for a
    delta — the least-covered module in the repository is the same module it was
    last night, and re-reading it spends the night re-deriving yesterday's
    findings. A delta reads the diff: the changed files whose changed lines no
    test executed first, then the files a drifted finding cites, then the rest of
    the diff.

    The reading map is the fallback for a run with NO range at all, and only
    then. A range that contains no Python must come back empty: falling through
    to the whole repository would let a TypeScript-only diff be reported as a
    Python audit of files the change never touched.
    """
    if not changed:
        return candidates(facts, repo)
    cold = changed_lines_of(facts)
    drifted = drifted_paths(facts)
    ranked, seen = [], set()
    for group in ([p for p in changed if p in cold],
                  [p for p in changed if p in drifted],
                  list(changed)):
        for rel in group:
            if rel in seen or not rel.endswith(".py"):
                continue
            if not (repo / rel).is_file():
                continue
            seen.add(rel)
            ranked.append(rel)
    return ranked


def python_in(paths) -> list:
    """The `.py` files of a set of paths. A diff with none of them is a diff this
    engine cannot read at all, and that is a fact the run has to state rather than
    a reason to report a clean pass."""
    return [p for p in paths if str(p).endswith(".py")]


def chunks_in_range(repo: Path, rel: str, lines: set | None) -> list:
    """The functions of a file that intersect the changed lines — the whole file
    when the range is not known at line granularity."""
    chunks = chunks_of(repo, rel)
    if not lines:
        return chunks
    return [c for c in chunks if any(c.start <= n <= c.end for n in lines)] or chunks


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

Reply with JSON only, and put a real call to `{function}` in the expression:
{{"expression": "<a one-line call on m that reaches the claim, e.g. m.{function}(...)>",
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
                                           mechanism=claim["mechanism"], module=module,
                                           function=chunk.name), max_tokens=700)
    if not answer:
        return {"status": "unavailable", "reason": "the model did not answer with JSON"}
    expression = str(answer.get("expression") or "").strip()
    replacement = answer.get("fix_replacement")
    line = answer.get("fix_line")
    if not expression or "\n" in expression or not isinstance(replacement, str):
        return {"status": "unavailable",
                "reason": "the probe was not one expression and one replacement line"}
    if chunk.name not in expression:
        # A small model copies the schema's example instead of writing a call: measured on
        # boltons, where every probe came back as `m.some_function(1, 2)` and failed on an
        # attribute that does not exist. The expression must reach the function it is about.
        return {"status": "unavailable",
                "reason": f"the probe does not call {chunk.name}: {expression[:80]}"}
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
                     filed: list, budget) -> int:
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
        if norm_status(f.get("status")) != "open":
            continue        # accepted, resolved and withdrawn are the harness's to carry
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
        out["non_python_diff"] = ("no parseable Python in the range — this engine read no "
                                  "code at all")
    if parked:
        out["questions_parked"] = parked
    if over_limit:
        out["diff_over_limit"] = ("the range is larger than the caps this engine runs under; "
                                  "part of it was never read")
    return out


NO_CODE_READ = ("No code was read this run: the range contains no parseable Python, and this "
                "engine reads Python only. A green gate here means the suite did not fail; it "
                "is not a QA pass.")
# A focus list that only ever grows is a focus list nobody reads, which is the
# same as not having one.
FOCUS_LINES = 20


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
    and a wall-clock ceiling. What matters for honesty is the other half — when a
    cap bites, the run says how many candidates it never looked at, because a
    truncated read reported as a complete one is the exact shape of a false green.
    """

    def __init__(self, functions: int = MAX_FUNCTIONS, probes=None, seconds=None):
        self.functions, self.probes, self.seconds = functions, probes, seconds
        self.used_functions, self.used_probes, self.skipped = 0, 0, 0
        self.stopped = None
        self._started = time.monotonic()

    def elapsed_s(self) -> float:
        return time.monotonic() - self._started

    def take_function(self) -> bool:
        if not self.stopped:
            if self.seconds is not None and self.elapsed_s() > self.seconds:
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


def file_findings(model: Model, repo: Path, targets: list, mint, findings_dir: Path,
                  filed: list, python: str, prove: bool, budget: Budget) -> tuple:
    """Read the source, one function at a time, and try to prove each claim by flipping
    the line in a scratch copy. Returns (examined, proven, disproven).

    `targets` is `(path, the changed lines or None)`: a run over a range asks only
    about the functions the range touched, because a function nobody edited is a
    question this engine already asked on some earlier night.
    """
    examined = proven = disproven = 0
    for rel, lines in targets:
        for chunk in chunks_in_range(repo, rel, lines):
            if not budget.take_function():
                continue
            examined += 1
            claim = examine(model, chunk)
            if not claim:
                continue
            proof = (counterfactual(model, repo, chunk, claim, python)
                     if prove and budget.take_probe() else None)
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


def measure(repo: Path, qa_root: Path, gates: list, config: dict, sha_range,
            profile_notes: list) -> dict:
    """The deterministic half, with the whole profile behind it.

    0.88.0 called `collect` with the gate command and nothing else, so
    `test_one_cmd`, `test_ids_cmd` and `coverage_suite_cmd` never reached it: no
    fix could be verified, no id ledger was written, and diff coverage was
    permanently unavailable. Each of those is a measurement this engine's safety
    rules rest on — a resolution needs a verified fix, a carried citation needs
    the id ledger it is checked against, and the reading order needs the changed
    lines nothing executed. The housekeeping `facts_main` does comes with them:
    the run marker before the gates, last run's finding files moved aside, and
    the collected ids written down.
    """
    marker_path = qa_root / "run-in-progress.json"
    abandoned = read_json(marker_path)
    head = _git(["rev-parse", "HEAD"], repo)
    started = _parse_marker_time((abandoned or {}).get("started_utc")) if abandoned else None
    retry = bool(abandoned) and abandoned.get("git_sha") == head and started is not None \
        and (clock.now() - started).total_seconds() / 3600 <= RETRY_WINDOW_HOURS
    marker_path.write_text(json.dumps({
        "started_utc": clock.stamp(), "repo": str(repo), "git_sha": head,
        "engine": ENGINE}, indent=2) + "\n", encoding="utf-8")
    archived = archive_findings(qa_root, keep=retry)
    facts = collect(repo, qa_root, gates, config.get("test_ids_cmd"), abandoned=abandoned,
                    test_one_cmd=config.get("test_one_cmd"),
                    coverage_suite_cmd=config.get("coverage_suite_cmd"), sha_range=sha_range)
    facts.pop("_added_test_ids", None)
    ids = facts.pop("_test_ids", None)
    if ids is not None:
        (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    if archived:
        facts["findings_archived"] = archived
    if profile_notes:
        facts["profile_notes"] = profile_notes
    facts.setdefault("last_run", {})["engine"] = ENGINE
    return facts


def run(repo: Path, qa_root: Path, model: Model, limit: int, gate: str | None,
        reruns: int, prove: bool = True, delta: bool = False,
        sha_range: str | None = None, reference_state=None,
        budget: Budget | None = None) -> int:
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

    print(f"verdict-local: measuring {repo} · gate {name}", file=sys.stderr)
    facts = measure(repo, qa_root, gates, config, sha_range, profile_notes)
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    measured_range = (facts.get("last_run") or {}).get("sha_range")
    ranged = bool(measured_range)
    changed = changed_files(repo, measured_range)
    if ranged:
        cold_by_file = changed_lines_of(facts)
        ranked = delta_candidates(facts, repo, changed)
        targets = [(rel, cold_by_file.get(rel)) for rel in ranked[:limit]]
    else:
        ranked = candidates(facts, repo)
        targets = [(rel, None) for rel in ranked[:limit]]
    files = [rel for rel, _ in targets]
    over_limit = len(ranked) > limit
    non_python = bool(ranged and changed and not python_in(changed))

    python = interpreter_of(command)
    print(f"verdict-local: {len(files)} file(s) to read, model {model.name}"
          + (f", proving with {python}" if prove else ", proving disabled"), file=sys.stderr)
    prefix = str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[0]
    number = int(str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[1] or 1)

    findings_dir = qa_root / FINDINGS_DIR
    findings_dir.mkdir(exist_ok=True)
    counter = [number]
    collected = known_tests(qa_root)
    prior_ids = {str(f.get("id")) for f in (previous or {}).get("findings") or []
                 if isinstance(f, dict) and f.get("id")}

    def mint(entry: dict, into: Path, into_list: list, keep_id: bool = False) -> None:
        """File a finding, or refuse it — the validator decides, never the model."""
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
        claim = classify(model, repo, failure)
        if claim:
            mint(failure_finding(claim, "@"), findings_dir, filed)

    # 2. Skips with no expiry — a regular expression, no model call at all.
    for skip in skips_without_expiry(repo, test_files(repo)):
        mint(skip_finding(skip, "@"), findings_dir, filed)

    # 3. What reading says, function by function — the source, then the tests.
    examined, proven, disproven = file_findings(model, repo, targets, mint, findings_dir,
                                                filed, python, prove, budget)
    suite_files = ([p for p in python_in(changed) if is_test_file(p)] if ranged
                   else test_files(repo)[:limit])
    examined += brittle_findings(model, repo, suite_files, mint, findings_dir, filed, budget)

    # 4. The quarantine, re-measured rather than expired by the calendar.
    carried_quarantine, released, quarantine_notes = requarantine(
        repo, (previous or {}).get("flaky_quarantine") or [], config.get("test_one_cmd"), today)
    quarantine_out = merge_quarantine(carried_quarantine, fresh_quarantine)

    # 5. Every prior open finding is mentioned — A, B or C, and nothing else.
    prior_open = [str(f.get("id")) for f in (previous or {}).get("findings") or []
                  if isinstance(f, dict) and f.get("id") and norm_status(f.get("status")) == "open"]
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
    verdict = local_verdict(prior_verdict, filed, carried_records, measured, cold_lines,
                            ceiling=NO_CODE_READ if non_python else None,
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
        + [str(x) for x in (previous or {}).get("next_run_focus") or []])[:FOCUS_LINES]

    for note in quarantine_notes:
        print(f"verdict-local: {note}", file=sys.stderr)
        if "NOT re-measured" in note:
            asked_questions.append({
                "question": f"A quarantine is due and could not be re-measured: {note[:170]}",
                "context": "declare `test_one_cmd` in the profile so the harness can run one "
                           "test, or release the quarantine deliberately"})

    not_tested = not_tested_lines(model, files, examined, prior_open, still_open_ids,
                                  refiled, prove, budget, quarantine_notes, non_python)
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
                      + (" " + NO_CODE_READ if non_python else "")),
            "notes": ("No Claude tokens were spent on this run. The verdict cannot improve on "
                      "its own: a previous `fail` stays `fail`, and a previous `blocked` "
                      "stays `blocked`, until something with judgment looks at it."
                      + (" " + CARRIED_BLOCKED[0].upper() + CARRIED_BLOCKED[1:] + "."
                         if carried_blocked else "")),
        },
        "isolation_check": {"result": "pass", "note": "local mode reads the checkout and "
                                                      "runs the suite gate; it writes nothing "
                                                      "outside the QA root"},
        "verified_intact": list((previous or {}).get("verified_intact") or []),
        "flaky_quarantine": quarantine_out,
        "release_blockers": blockers,
        "next_run_focus": focus,
        "full_sweep": False,
    }
    (qa_root / "judgment.json").write_text(json.dumps(judgment, indent=1), encoding="utf-8")

    facts["last_run"]["local"] = {
        "model": model.name,
        "host": urllib.parse.urlparse(model.base_url).hostname or model.base_url,
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

    code = finalize_main(["--qa-root", str(qa_root),
                          "--judgment", str(qa_root / "judgment.json")])
    if proven or disproven:
        print(f"verdict-local: {proven} claim(s) proven by counterfactual, {disproven} "
              f"withdrawn before filing", file=sys.stderr)
    print_summary(model, files, examined, filed, refiled, resolved_ids, still_open_ids,
                  verdict, owed, budget)
    return code


def not_tested_lines(model: Model, files: list, examined: int, prior_open: list,
                     still_open: list, refiled: list, prove: bool, budget: Budget,
                     quarantine_notes: list, non_python: bool) -> list:
    """What a night like this one does not do, counted rather than described.

    The temptation with a cheap engine is to let its report read like the
    expensive one's. This list is what stops that: every line is a number the run
    measured, so a local `pass` is visibly a different sentence from an agent's.
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
         f"finding a hypothesis, and an unproven severity is held at {UNPROVEN_CEILING}"
         if prove else
         "everything a counterfactual would show: proving was disabled this run, so every "
         "finding from reading is a hypothesis"),
        "nothing outside the checkout was read — no database, no MCP tools, no production "
        "numbers — so a standing blocker that quotes one was NOT re-read",
        f"{model.unanswered} question(s) the model did not answer"
        + (f", {model.errors} of which the gateway never received" if model.errors else ""),
    ]
    if budget.stopped:
        out.append(f"{budget.skipped} candidate function(s) were never asked about: "
                   f"{budget.stopped}")
    if non_python:
        out.append(NO_CODE_READ)
    out.extend(quarantine_notes)
    return out


def print_summary(model: Model, files: list, examined: int, filed: list, refiled: list,
                  resolved: list, still_open: list, verdict: str, owed: dict,
                  budget: Budget) -> None:
    """At most fifteen lines, ending on the number this whole release is about."""
    lines = [
        f"verdict-local: verdict {verdict!r}",
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
    budget = Budget(
        functions=(args.max_functions if args.max_functions is not None
                   else (GATE_MAX_FUNCTIONS if ranged else MAX_FUNCTIONS)),
        probes=(args.max_probes if args.max_probes is not None
                else (GATE_MAX_PROBES if ranged else None)),
        seconds=(args.max_model_s if args.max_model_s is not None
                 else (GATE_MODEL_BUDGET_S if ranged else None)))
    # A named range is a gate somebody is waiting for, so it takes the caps
    # unless the operator overrode them: six files, and no repeat runs of the
    # whole suite — three green suites prove nothing about a diff.
    limit = GATE_MAX_FILES if ranged and args.limit == 8 else args.limit
    reruns = 0 if ranged and args.reruns == 2 else args.reruns
    print(f"verdict-local: {clock.now():%Y-%m-%dT%H:%M:%SZ} · project {project!r} · {detail}",
          file=sys.stderr)
    return run(repo, qa_root, model, limit, args.gate, reruns, args.prove,
               delta=args.delta or (qa_root / "state.json").is_file(),
               sha_range=sha_range, reference_state=args.reference_state, budget=budget)


if __name__ == "__main__":
    sys.exit(main())
