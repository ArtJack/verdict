"""verdict-check — a second look at a finished run, on the local tier: siblings and severity.

The bounded Opus check found something material behind 6 of 9 Sonnet gates; a second pass by
the same tester found nothing new in 3 of 3 (Phase 0, 2026-10-11). What paid was not "look
again" but three narrow questions. The third — which ranked code no finding and no
`not_tested` line covers — finalize answers without a model (`read_first`). This asks the
first, siblings, of a cheap model and keeps every answer as a lead: the code the finding's
cited line uses is searched in the repository (git grep; tests, docs and the finding's own
function excluded; adjacent lines folded), and the model sees the finding and each other
site and says which share the defect. The sites come from the search, never from the model,
so a lead always points at real code.

The second question, severity, was measured on the six October stranger records
(2026-10-17, chat-120b) and dropped: it flagged 13 of 18 findings, every one an upgrade along
the standard's literal "financial error -> Critical" line — a constant, not a calibration.
Siblings on the same records: 12 leads, of which 3 pointed at a new site; most of the noise
was lines of the defect's own function, which the search now excludes.

Answers go to `<qa-root>/reviews/<run>-local-check.md` and one row in `reviews.jsonl`
(`material: yes|no`) — beside the state, never in it. A lead is not a finding: the next run
or a person reads it, and proves it or drops it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from . import clock
    from .readfirst import enclosing
    from .small import Model, extract_json, gateway_alive, read_env_file  # noqa: F401
    from .state import is_open, load_state, repo_for_root
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from readfirst import enclosing
    from small import Model, extract_json, gateway_alive, read_env_file  # noqa: F401
    from state import is_open, load_state, repo_for_root

SEVERE = ("Blocker", "Critical", "Major")
MAX_FINDINGS = 8
MAX_SITES = 10
CONTEXT = 6
DEFAULT_ENV = "~/.config/verdict-gateway.env"

SIBLING_Q = """A proven defect, in {path}:
TITLE: {title}
MECHANISM: {mechanism}

Below are other places in the same repository that use `{token}`. For each, decide whether the
SAME defect applies there — the same construct producing the same wrong behaviour — not merely
the same name. Answer with JSON only:
{{"sites": [{{"id": <number>, "same_defect": true or false, "why": "<one sentence>"}}]}}

{sites}"""


_SPAN = re.compile(r"`([^`]{3,120})`")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_COMMON = {"self", "None", "True", "False", "return", "import", "assert", "print", "lambda"}


def _distinctive(ident: str, span: str) -> bool:
    return (ident not in _COMMON and len(ident) >= 6
            and ("." in ident or "_" in ident or ident + "(" in span))


def tokens_of(finding: dict, repo: Path | None = None, cap: int = 2) -> list[str]:
    """The code a finding is about. First from the cited source lines themselves (its anchors'
    `path:line` in the repository): the identifiers there that the finding's own words also
    name, then the rest. Evidence quotes come last — they hold probe code and proposed fixes
    as often as the defect (measured on the six October records)."""
    text = " ".join([str(finding.get("title") or "")] + [str(e) for e in finding.get("evidence") or []])
    scored: dict = {}
    for a in (finding.get("anchors") or [])[:3]:
        if repo is None or not isinstance(a, dict) or not a.get("path") or not isinstance(a.get("line"), int):
            continue
        try:
            line = (Path(repo) / a["path"]).read_text(encoding="utf-8", errors="replace").splitlines()[a["line"] - 1]
        except (OSError, IndexError):
            continue
        for ident in _IDENT.findall(line.split("#", 1)[0]):
            if _distinctive(ident, line):
                named = ident in text or ident.rsplit(".", 1)[-1] in text
                scored[ident] = max(scored.get(ident, 0), 10 + 5 * named + ("." in ident) + len(ident) / 40)
    for t in [*map(str, finding.get("evidence") or []), str(finding.get("title") or "")]:
        for span in _SPAN.findall(t):
            for ident in _IDENT.findall(span):
                if _distinctive(ident, span):
                    scored.setdefault(ident, ("." in ident) + len(ident) / 40)
    return [t for t, _ in sorted(scored.items(), key=lambda kv: -kv[1])][:cap]


def _excluded(path: str) -> bool:
    p = path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    return (p.startswith(("tests/", "test/", "docs/")) or "/tests/" in p or "/test/" in p
            or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py")


def _function_at(repo: Path, path: str, line: int) -> str:
    return next(iter(enclosing(repo, path, {line})), "(module)")


def sites_of(repo: Path, token: str, own: set, cap: int = MAX_SITES) -> list[dict]:
    """Other places of the repository that use `token` — outside the finding's own functions,
    one per run of adjacent lines — each with a numbered excerpt."""
    proc = subprocess.run(["git", "-C", str(repo), "grep", "-n", "-I", "-F", "-e", token],
                          capture_output=True, text=True, errors="replace")
    own_functions = {(p, _function_at(repo, p, ln)) for p, ln in own}
    out = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        num, _, _ = rest.partition(":")
        if not num.isdigit() or _excluded(path):
            continue
        n = int(num)
        if any(path == p and abs(n - ln) <= 3 for p, ln in own):
            continue
        fn = _function_at(repo, path, n)
        if (path, fn) in own_functions and fn != "(module)":
            continue
        if any(s["path"] == path and s["function"] == fn and abs(s["line"] - n) <= 5 for s in out):
            continue                   # one site per run of adjacent lines in one function
        try:
            lines = (Path(repo) / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        lo, hi = max(1, n - CONTEXT), min(len(lines), n + CONTEXT)
        excerpt = "\n".join(f"{i:5} {lines[i - 1]}" for i in range(lo, hi + 1))
        out.append({"path": path, "line": n, "function": fn, "excerpt": excerpt})
        if len(out) >= cap:
            break
    return out


def _own_lines(finding: dict) -> set:
    own = set()
    for a in finding.get("anchors") or []:
        if isinstance(a, dict) and a.get("path") and isinstance(a.get("line"), int):
            own.add((str(a["path"]).replace("\\", "/"), a["line"]))
    return own


def check_finding(model, repo: Path, finding: dict) -> dict:
    """Both questions for one finding → its leads."""
    lead = {"id": str(finding.get("id")), "title": str(finding.get("title") or "")[:160],
            "severity": finding.get("severity"), "siblings": []}
    mechanism = str(((finding.get("root_cause") or {}).get("mechanism"))
                    or (finding.get("evidence") or [""])[0])[:600]
    anchor = next((a for a in finding.get("anchors") or [] if isinstance(a, dict) and a.get("path")), {})
    for token in tokens_of(finding, repo):
        sites = sites_of(repo, token, _own_lines(finding))
        if not sites:
            continue
        listing = "\n\n".join(f"[{i}] {s['path']}:{s['line']}\n{s['excerpt']}" for i, s in enumerate(sites, 1))
        doc = model.ask_json(SIBLING_Q.format(path=anchor.get("path", "?"), title=lead["title"],
                                              mechanism=mechanism, token=token, sites=listing), max_tokens=900)
        for answer in (doc or {}).get("sites") or []:
            try:
                site = sites[int(answer.get("id")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            if answer.get("same_defect") is True:
                lead["siblings"].append({"path": site["path"], "line": site["line"], "token": token,
                                         "why": str(answer.get("why") or "")[:240]})
        break                     # one token's search per finding: bounded
    return lead


def material(lead: dict) -> bool:
    return bool(lead.get("siblings"))


def render(state: dict, leads: list, model_name: str) -> str:
    out = [f"# Local check — run {state.get('run_number')} of {state.get('project')}", "",
           f"Model: `local:{model_name}`. Leads, not findings: each sibling site comes from a search "
           "of the repository and the model's reading of it. The next run, or a person, proves or "
           "drops them.", ""]
    for lead in leads:
        out.append(f"## {lead['id']} ({lead['severity']}) — {lead['title']}")
        for s in lead["siblings"]:
            out.append(f"- sibling: `{s['path']}:{s['line']}` (`{s['token']}`) — {s['why']}")
        if not lead["siblings"]:
            out.append("- no sibling site")
        out.append("")
    return "\n".join(out)


def main(argv=None, _model=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # the Windows cp1252 trap, every CLI
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="verdict-check", description=__doc__.split("\n\n")[0])
    ap.add_argument("project", help="project key or a repo path whose .qa/ holds state.json")
    ap.add_argument("--env-file", default=DEFAULT_ENV,
                    help="ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN for the gateway (default %(default)s)")
    ap.add_argument("--model", default=os.environ.get("VERDICT_LOCAL_MODEL", "chat-120b"))
    ap.add_argument("--max-findings", type=int, default=MAX_FINDINGS)
    ap.add_argument("--dry-run", action="store_true", help="print what would be asked; call nothing")
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-check: {err['error']}", file=sys.stderr)
        return 2
    qa_root = Path(state["_qa_root"])
    repo = repo_for_root(qa_root)
    if repo is None:
        print("verdict-check: the QA root names no repository", file=sys.stderr)
        return 2
    findings = [f for f in state.get("findings") or [] if is_open(f) and f.get("severity") in SEVERE]
    findings = findings[:args.max_findings]
    if not findings:
        print("verdict-check: no open Major+ finding to check", file=sys.stderr)
        return 2
    if args.dry_run:
        for f in findings:
            toks = tokens_of(f, repo)
            sites = sites_of(repo, toks[0], _own_lines(f)) if toks else []
            print(f"{f.get('id')}: token {toks[0] if toks else '-'} · {len(sites)} site(s) · severity {f.get('severity')}")
        return 0
    model = _model
    if model is None:
        env = dict(os.environ)
        path = Path(os.path.expanduser(args.env_file))
        if path.is_file():
            env.update(read_env_file(path))
        base_url, token = env.get("ANTHROPIC_BASE_URL"), env.get("ANTHROPIC_AUTH_TOKEN")
        if not base_url or not token:
            print("verdict-check: no gateway — ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are needed "
                  f"(from {args.env_file} or the environment)", file=sys.stderr)
            return 2
        alive, detail = gateway_alive(base_url, token)
        if not alive:
            print(f"verdict-check: the gateway did not answer ({detail}) — nothing asked", file=sys.stderr)
            return 2
        model = Model(args.model, base_url, token)
    leads = [check_finding(model, repo, f) for f in findings]
    run = state.get("run_number")
    (qa_root / "reviews").mkdir(exist_ok=True)
    report = qa_root / "reviews" / f"{run}-local-check.md"
    report.write_text(render(state, leads, args.model), encoding="utf-8")
    mat = [lead["id"] for lead in leads if material(lead)]
    row = {"date": clock.stamp()[:10], "run": run, "kind": "local-check", "model": f"local:{args.model}",
           "material": "yes" if mat else "no", "findings_checked": len(leads),
           "siblings": sum(len(lead["siblings"]) for lead in leads),
           "report": str(report.relative_to(qa_root))}
    with (qa_root / "reviews.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    calls = getattr(model, "calls", None)
    print(f"verdict-check: {len(leads)} finding(s) checked · {row['siblings']} sibling lead(s) · "
          f"material: {row['material']}"
          + (f" ({', '.join(mat)})" if mat else "")
          + (f" · {calls} call(s) on local:{args.model}" if calls is not None else "")
          + f" → {report}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
