#!/usr/bin/env python3
"""The plain arm of the recall benchmark: the same case and budget, no Verdict. Spends Claude tokens.

Every number on the recall benchmark so far measured Verdict against earlier Verdicts. This
arm asks the question the benchmark exists for: does Verdict find and prove more than plain
Claude Code given the same scope, model, effort and dollar cap? For one case it checks out the
case's commit in a fresh worktree outside the home directory (so no instruction file reaches
the session), launches the claude CLI the way `eval/swebench.py`'s control arm does (no user
settings, no MCP servers, no VERDICT_* variable) and without web tools (some known defects are
described in upstream trackers), with a prompt carrying what an escalation run's tester gets
about the case: the brief's scope paragraph, the profile's risk sections, the proof standard,
the ~35-call aim and the dollar cap. The session writes its findings as JSON, with a runnable
repro for each proven one. Every Major-or-worse repro is then replayed through Verdict's own
replay (a fresh checkout, the unattended rules an in-run replay follows), and `state.json`,
`replays.jsonl` and `usage.jsonl` are written in the shapes `eval/recall/score_recall.py`
reads, so both arms are scored by one scorer.

    op-agent run --env-file ~/.config/op-env/verdict-run.env -- \\
        python3 eval/recall/plain_arm.py ~/.claude/verdict-bench/recall-cases.json openfisca-core \\
            --brief packet-openfisca-core.md --profile profile.md --out /tmp/plain/openfisca-core

The session's own figure (`total_cost_usd`) is kept beside the token counts; the scorer prices
the tokens at Opus rates, as it prices the Verdict arm.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE.parent))
from swebench import _project_dir, instruction_files, plain_argv, plain_env  # noqa: E402
from verdict_mcp import backfill, replay  # noqa: E402

BLOCKING = ("Blocker", "Critical", "Major")
SEVERITIES = ("Blocker", "Critical", "Major", "Minor", "Trivial")
CONFIDENCES = ("proven", "probable", "hypothesis")

PROMPT = """You are a skeptical software tester reviewing {key} at commit {sha}, checked out in the current \
directory. Find real defects; do not fix them.

{scope}

The project's own notes on what matters:

{risk}

{proof}

The project's tests run with: `{suite}`. Use `{python}` for Python.

Work only from this checkout: do not search the web or read issue trackers. Do not modify the \
repository's files; put any script you write under `{scratch}`. Do not contact anyone, open issues, or \
push anything. Aim for about {calls} tool calls; the session stops at ${cap:g}.

Write your findings to `{findings}` as soon as you have the first one, and keep the file current as you \
go, so that a stop at the dollar cap leaves them on disk. The file is JSON, `{{"findings": [...]}}`, each \
finding:

    {{"id": "P-1", "title": "<one line>", "severity": "Blocker|Critical|Major|Minor|Trivial",
     "confidence": "proven|probable|hypothesis",
     "anchors": [{{"path": "<path relative to the repository root>", "line": <number>}}],
     "evidence": ["<what you read or ran, and what it showed>"],
     "repro": {{"command": "<one command, run from the repository root, that fails while the defect is there>",
               "cwd": "repo", "expect": {{"exit": 1, "stderr_contains": "<text that shows the defect>"}}}}}}

A proven finding carries its repro: prefer `{python} {scratch}/<name>.py`, a script that asserts what must \
not happen. No shell operators (`;`, `&&`, `|`, `>`) in the command.
"""


def paragraph(text: str, start: str) -> str:
    """The brief's paragraph that begins with `start` ("Scope", "Proof standard"), or ''."""
    for block in re.split(r"\n\s*\n", text or ""):
        if block.strip().startswith(start):
            return " ".join(block.split())
    return ""


def risk_sections(profile_text: str) -> str:
    """Every profile section whose heading names a risk, heading included, as written."""
    out, inside = [], False
    for line in (profile_text or "").splitlines():
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            inside = "risk" in heading.group(1).lower()
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def suite_command(profile_text: str) -> str:
    m = re.search(r"(?m)^\s+suite:\s*(.+?)\s*$", profile_text or "")
    return m.group(1) if m else ""


def interpreter(command: str) -> str:
    m = re.search(r"(\S*/python[0-9.]*)(?=\s|$)", command or "")
    return m.group(1) if m else "python3"


def build_prompt(key: str, sha: str, brief: str, profile_text: str, scratch: Path, findings: Path,
                 calls: int = 35, cap: float = 2.5) -> str:
    scope = re.sub(r'as the profile\'s "[^"]*" section lays out', "as the notes below lay out",
                   paragraph(brief, "Scope"))
    suite = suite_command(profile_text)
    return PROMPT.format(key=key, sha=sha[:12], scope=scope, risk=risk_sections(profile_text),
                         proof=paragraph(brief, "Proof standard"), suite=suite, python=interpreter(suite),
                         scratch=scratch, findings=findings, calls=calls, cap=cap)


def result_of(stdout: str) -> dict:
    """The CLI's `--output-format json` result: the last line that parses as a JSON object."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict):
                return doc
    return {}


def read_findings(path: Path, result_text: str = "") -> list:
    """The session's findings: its file, else a `{"findings": ...}` block in its last message."""
    for text in (path.read_text(encoding="utf-8") if path.is_file() else "", result_text or ""):
        m = re.search(r'\{\s*"findings"\s*:', text)
        if not m:
            continue
        try:
            doc, _ = json.JSONDecoder().raw_decode(text[m.start():])
        except json.JSONDecodeError:
            continue
        if isinstance(doc.get("findings"), list):
            return doc["findings"]
    return []


def normalize(findings: list) -> list:
    """The fields the scorer reads, in the record's shapes; anything else the session wrote is kept."""
    out = []
    for i, f in enumerate(findings or [], 1):
        if not isinstance(f, dict):
            continue
        f = dict(f)
        f["id"] = str(f.get("id") or f"P-{i}")
        f["severity"] = f.get("severity") if f.get("severity") in SEVERITIES else "Minor"
        f["confidence"] = f.get("confidence") if f.get("confidence") in CONFIDENCES else "hypothesis"
        f["status"] = "open"
        f["anchors"] = [a for a in f.get("anchors") or [] if isinstance(a, dict) and a.get("path")]
        f["evidence"] = [str(e) for e in f.get("evidence") or []]
        if not isinstance(f.get("repro"), dict) or not f["repro"].get("command"):
            f.pop("repro", None)
        out.append(f)
    return out


def usage_rows(result: dict) -> list:
    """One `usage.jsonl` row per model the session used, in the record's token names."""
    rows = []
    for model, u in (result.get("modelUsage") or {}).items():
        rows.append({"usage": {"model": model, "input_tokens": u.get("inputTokens", 0),
                               "output_tokens": u.get("outputTokens", 0),
                               "cache_read_input_tokens": u.get("cacheReadInputTokens", 0),
                               "cache_creation_input_tokens": u.get("cacheCreationInputTokens", 0)},
                     "cli_cost_usd": u.get("costUSD")})
    if not rows and isinstance(result.get("usage"), dict):
        u = result["usage"]
        rows.append({"usage": {"model": "claude-opus", **{k: u.get(k, 0) for k in (
            "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}},
            "cli_cost_usd": result.get("total_cost_usd")})
    return rows


# What the plain session must not read: Verdict's records and harness, the benchmark's key, and
# the scratch roots earlier runs of either arm left. A hit does not stop the run; it is reported,
# and a contaminated row is not a control.
FORBIDDEN = (".claude/verdict", "verdict-bench", "verdict-branches", "verdict-ops", "Projects/verdict",
             "verdict-qa-mcp", "verdict_mcp", "escalate-", "after-0.91", "packet-final")


def contamination(cwd: Path, session_id, config_dir=None) -> list:
    """The forbidden markers that appear in the session's tool calls and results, from its
    transcript (main session and subagents); None when no transcript is found."""
    if not session_id:
        return None
    base = _project_dir(cwd, config_dir)
    files = [base / f"{session_id}.jsonl"]
    sub = base / str(session_id) / "subagents"
    files += sorted(sub.glob("*.jsonl")) if sub.is_dir() else []
    seen, hits = False, set()
    for f in files:
        if not f.is_file():
            continue
        seen = True
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            hits.update(m for m in FORBIDDEN if m in line)
    return sorted(hits) if seen else None


def replay_all(findings: list, tree: Path, qa_root: Path, sha: str, timeout: int) -> list:
    """Each Major-or-worse repro, run as an in-run replay runs it: a fresh checkout, unattended."""
    rows = []
    for f in findings:
        if f.get("severity") not in BLOCKING or not f.get("repro"):
            continue
        got = backfill.run_at(tree, qa_root, {"id": f["id"], "repro": f["repro"]}, sha, timeout,
                              replay.sandbox_prefix)
        rows.append({"id": f["id"], "result": got.get("result"), "exit": got.get("exit"),
                     "checks": got.get("checks"), "output_tail": got.get("output_tail")})
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="plain_arm.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("cases", type=Path)
    ap.add_argument("key")
    ap.add_argument("--brief", type=Path, required=True, help="the case's run brief (scope, proof standard)")
    ap.add_argument("--profile", type=Path, required=True, help="the case's profile (risk sections, suite)")
    ap.add_argument("--out", type=Path, required=True, help="a new directory: the plain arm's QA root")
    ap.add_argument("--repos", type=Path, default=Path.home() / "src")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--effort", default="xhigh")
    ap.add_argument("--cap", type=float, default=2.5)
    ap.add_argument("--calls", type=int, default=35)
    ap.add_argument("--timeout", type=int, default=2700)
    ap.add_argument("--replay-timeout", type=int, default=180)
    args = ap.parse_args(argv)

    cases = {c["key"]: c for c in json.loads(args.cases.read_text(encoding="utf-8"))["cases"]}
    case = cases.get(args.key)
    if case is None:
        print(f"plain_arm: no case {args.key!r}", file=sys.stderr)
        return 2
    repo, qa = args.repos / args.key, args.out.resolve()
    tree, scratch = qa / "tree", qa / "scratch"
    if qa.exists() and any(qa.iterdir()):
        print(f"plain_arm: {qa} is not empty", file=sys.stderr)
        return 2
    if "verdict" in str(qa).lower() or str(qa).startswith(str(Path.home())):
        # The session sees its paths, and a checkout under the home directory is handed
        # `~/.claude/CLAUDE.md` whatever `--setting-sources` says (eval/swebench.py).
        print(f"plain_arm: {qa} names Verdict or sits under the home directory", file=sys.stderr)
        return 2
    scratch.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(tree), case["sha"]],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"plain_arm: worktree failed: {proc.stderr.strip()}", file=sys.stderr)
        return 2
    try:
        prompt = build_prompt(args.key, case["sha"], args.brief.read_text(encoding="utf-8"),
                              args.profile.read_text(encoding="utf-8"), scratch, qa / "findings.json",
                              args.calls, args.cap)
        (qa / "prompt.md").write_text(prompt, encoding="utf-8")
        cmd = plain_argv(prompt, args.model) + ["--effort", args.effort, "--max-budget-usd", f"{args.cap:g}",
                                                "--disallowedTools", "WebFetch", "WebSearch"]
        env, notes = plain_env(dict(os.environ), None, tree)
        try:
            run = subprocess.run(cmd, cwd=tree, env=env, capture_output=True, text=True, timeout=args.timeout)
            stdout, code = run.stdout, run.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            code = None
        (qa / "session.log").write_text(stdout, encoding="utf-8")
        result = result_of(stdout)
        findings = normalize(read_findings(qa / "findings.json", str(result.get("result") or "")))
        state = {"verdict": "unknown", "release_blockers": [], "findings": findings,
                 "last_run": {"model": args.model, "engine": "plain", "git_sha": case["sha"]}}
        (qa / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
        (qa / "usage.jsonl").write_text("".join(json.dumps(r) + "\n" for r in usage_rows(result)), encoding="utf-8")
        rows = replay_all(findings, tree, qa, case["sha"], args.replay_timeout)
        (qa / "replays.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        got = instruction_files(tree, result.get("session_id"), env.get("CLAUDE_CONFIG_DIR"))
        dirty = contamination(tree, result.get("session_id"), env.get("CLAUDE_CONFIG_DIR"))
        summary = {"key": args.key, "exit": code, "subtype": result.get("subtype"), "num_turns": result.get("num_turns"),
                   "cli_cost_usd": result.get("total_cost_usd"), "findings": len(findings),
                   "blocking": sum(1 for f in findings if f["severity"] in BLOCKING),
                   "replayed": len(rows), "reproduced": sum(1 for r in rows if r["result"] == "reproduced"),
                   "instruction_files": got, "contamination": dirty, "notes": notes}
        (qa / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        print(json.dumps(summary))
        return 0
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tree)],
                       capture_output=True, text=True)


if __name__ == "__main__":
    sys.exit(main())
