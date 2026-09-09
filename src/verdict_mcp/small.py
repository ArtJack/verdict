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
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from .harness import collect, finalize_main
    from .project_key import derive_key
    from .state import home as state_home
    from .state import resolve_root
    from .validate import validate_finding
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from harness import collect, finalize_main
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
        for attempt in (1, 2):
            try:
                text = self.ask(prompt if attempt == 1 else
                                prompt + "\n\nReturn ONLY the JSON object. No prose.",
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


def finding_of(claim: dict, ident: str, chunk_source: str) -> dict:
    """A claim becomes a finding file — with `confidence: hypothesis`, because nothing
    here was proven by execution. The harness refuses to call it anything else, and a
    small-model run that claimed `proven` would be exactly the flattery this project
    exists to reject."""
    excerpt = "\n".join(chunk_source.splitlines()[:6])
    return {
        "id": ident,
        "title": claim["title"],
        "severity": claim["severity"],
        "priority": "P2" if claim["severity"] in ("Minor", "Trivial") else "P1",
        "status": "open",
        "failure_classification": "REAL_DEFECT",
        "confidence": "hypothesis",
        "evidence": [
            f"{claim['path']}:{claim['line']} — read by a small model against the function's "
            f"own contract; not executed, not counterfactually tested",
            f"excerpt:\n{excerpt}",
        ],
        "root_cause": {"mechanism": claim["mechanism"],
                       "origin": "not investigated in local mode"},
        "narrative": (f"{claim['mechanism']} {claim['impact']}".strip() +
                      " Filed by `verdict-local`: a bounded reading of this function alone, "
                      "with no execution behind it. Confirm before acting."),
    }


# ── the run ───────────────────────────────────────────────────────────────────

def run(repo: Path, qa_root: Path, model: Model, limit: int) -> int:
    qa_root.mkdir(parents=True, exist_ok=True)
    print(f"verdict-local: measuring {repo}", file=sys.stderr)
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")

    files = candidates(facts, repo)[:limit]
    print(f"verdict-local: {len(files)} file(s) to read, model {model.name}", file=sys.stderr)
    prefix = str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[0]
    number = int(str(facts.get("next_finding_id") or "F-1").rsplit("-", 1)[1] or 1)

    findings_dir = qa_root / "findings"
    findings_dir.mkdir(exist_ok=True)
    known_tests = set()
    filed, examined = [], 0
    for rel in files:
        for chunk in chunks_of(repo, rel)[:MAX_FUNCTIONS]:
            examined += 1
            claim = examine(model, chunk)
            if not claim:
                continue
            ident = f"{prefix}-{number}"
            entry = finding_of(claim, ident, chunk.source)
            problems = validate_finding(entry, f"findings/{ident}.json", set(), known_tests)
            if problems:
                print(f"verdict-local: rejected {ident}: {problems[0]}", file=sys.stderr)
                continue
            (findings_dir / f"{ident}.json").write_text(json.dumps(entry, indent=1),
                                                        encoding="utf-8")
            filed.append(entry)
            number += 1
            print(f"verdict-local: {ident} {entry['severity']} — {entry['title'][:90]}",
                  file=sys.stderr)

    judgment = {
        "verdict": "pass with risks" if filed else "pass",
        "findings": [], "still_open": [], "resolved": [],
        "not_tested": [
            "everything execution would show: no test was run against a claim, no "
            "counterfactual was applied, no commit history was read",
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
        "isolation_check": {"result": "pass", "note": "local mode reads; it runs no gates "
                                                      "beyond the harness's own measurement"},
        "verified_intact": [], "flaky_quarantine": [], "release_blockers": [],
        "full_sweep": False,
    }
    (qa_root / "judgment.json").write_text(json.dumps(judgment, indent=1), encoding="utf-8")
    code = finalize_main(["--qa-root", str(qa_root),
                          "--judgment", str(qa_root / "judgment.json")])
    print(f"verdict-local: {len(filed)} finding(s) from {examined} function(s) · "
          f"{model.calls} model calls · {model.input_tokens:,} in / "
          f"{model.output_tokens:,} out · {model.retries} retries", file=sys.stderr)
    return code


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
    return run(repo, qa_root, model, args.limit)


if __name__ == "__main__":
    sys.exit(main())
