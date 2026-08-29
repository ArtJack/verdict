"""Read-only MCP server over Verdict QA state.

Exposes the state the Verdict agent maintains (state.json, reports/,
profile.md) to any MCP client — an orchestrator gating a merge, Cursor/Codex
sessions, a CI step commenting a PR. Every tool is read-only: the server never
writes, and the write path stays exclusively with the agent.

Project resolution lives in `verdict_mcp.state` (shared with the
`verdict-gate` CLI): a bare key resolves in $VERDICT_HOME (default
~/.claude/verdict), a path resolves its `.qa/` (team mode). Unknown projects
return {"error": ...} with the known project list rather than raising —
friendlier for agent consumers.
"""

import re
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .state import (
    DELTA_VALUES,
    home,
    hotspots,
    known_projects,
    load_state,
    order_findings,
    parse_date,
)

mcp = FastMCP("verdict")
_RO = ToolAnnotations(readOnlyHint=True)

_REPORT_CAP = 512 * 1024


@mcp.tool(annotations=_RO)
def list_projects() -> dict:
    """List every project with a Verdict baseline in the solo state root."""
    out = []
    for key in known_projects():
        state, err = load_state(key)
        if err:
            out.append({"project": key, "error": err["error"]})
            continue
        out.append(
            {
                "project": key,
                "verdict": state.get("verdict"),
                "run_number": state.get("run_number"),
                "run_type": state.get("run_type"),
                "last_run_utc": (state.get("last_run") or {}).get("timestamp_utc"),
            }
        )
    return {"state_root": str(home()), "projects": out}


@mcp.tool(annotations=_RO)
def get_verdict(project: str) -> dict:
    """The last recorded verdict, release blockers, and report path for a project."""
    state, err = load_state(project)
    if err:
        return err
    last = state.get("last_run") or {}
    return {
        "project": state.get("project", project),
        "verdict": state.get("verdict"),
        "release_blockers": state.get("release_blockers", []),
        "run_number": state.get("run_number"),
        "run_type": state.get("run_type"),
        "last_run_utc": last.get("timestamp_utc"),
        "git_sha": last.get("git_sha"),
        "sha_range": last.get("sha_range"),
        "report": last.get("report"),
        "not_tested": state.get("not_tested", []),
    }


@mcp.tool(annotations=_RO)
def get_findings(project: str, status: str = "open") -> dict:
    """Findings for a project. status: 'open' (default), 'all', or one of
    NEW / STILL_OPEN / RESOLVED / REGRESSED. REGRESSED sort first, then by
    severity, then by age (oldest first shown last run's pressure)."""
    state, err = load_state(project)
    if err:
        return err
    findings = state.get("findings", [])
    if status == "all":
        selected = findings
    elif status == "open":
        selected = [f for f in findings if f.get("status") == "open"]
    elif status in DELTA_VALUES:
        selected = [f for f in findings if f.get("delta") == status]
    else:
        return {
            "error": f"unknown status {status!r}",
            "allowed": ["open", "all", *sorted(DELTA_VALUES)],
        }
    ordered = order_findings(selected)
    return {"project": state.get("project", project), "status": status, "count": len(ordered), "findings": ordered}


@mcp.tool(annotations=_RO)
def get_quarantine(project: str) -> dict:
    """The flaky-test quarantine ledger, with an expired flag per entry."""
    state, err = load_state(project)
    if err:
        return err
    today = date.today()
    entries = []
    for q in state.get("flaky_quarantine", []):
        until = parse_date(q.get("quarantined_until", ""))
        entries.append({**q, "expired": bool(until and until < today)})
    return {"project": state.get("project", project), "count": len(entries), "quarantine": entries}


@mcp.tool(annotations=_RO)
def get_history(project: str) -> dict:
    """Run history parsed from the project's reports/INDEX.md, oldest first."""
    state, err = load_state(project)
    if err:
        return err
    index = Path(state["_qa_root"]) / "reports" / "INDEX.md"
    if not index.is_file():
        return {"project": state.get("project", project), "runs": [], "note": "no INDEX.md yet"}
    rows, header = [], None
    for line in index.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        row = dict(zip(header, cells))
        link = re.search(r"\[.*?\]\((.*?)\)", cells[-1]) if cells else None
        if link:
            row["report_path"] = link.group(1)
        rows.append(row)
    return {"project": state.get("project", project), "runs": rows, "count": len(rows)}


@mcp.tool(annotations=_RO)
def get_report(project: str, report: str | None = None) -> dict:
    """Content of a QA report. Default: the last run's report; pass `report`
    (a path relative to the QA root, as returned by get_verdict/get_history)
    for an earlier one. Reports over 512KB are truncated with a flag."""
    state, err = load_state(project)
    if err:
        return err
    root = Path(state["_qa_root"]).resolve()
    rel = str(report or (state.get("last_run") or {}).get("report") or "")
    if not rel:
        return {"error": f"no report recorded for {project!r}"}
    raw = Path(rel)
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    if not candidate.is_relative_to(root):
        return {"error": "report path escapes the QA root", "report": rel}
    if candidate.suffix != ".md":
        return {"error": "only .md reports are served", "report": rel}
    if not candidate.is_file():
        return {"error": f"report not found: {rel}"}
    content = candidate.read_text(encoding="utf-8")
    truncated = len(content) > _REPORT_CAP
    if truncated:
        content = content[:_REPORT_CAP]
    return {
        "project": state.get("project", project),
        # POSIX-style relative path on every platform — this value round-trips
        # as the `report` argument and into links.
        "path": candidate.relative_to(root).as_posix(),
        "content": content,
        "truncated": truncated,
    }


@mcp.tool(annotations=_RO)
def get_profile(project: str) -> dict:
    """The project's QA profile — isolation rules, risk areas, real test
    commands — plus the lessons ledger (judgment corrections) when one exists."""
    state, err = load_state(project)
    if err:
        return err
    root = Path(state["_qa_root"])
    path = root / "profile.md"
    if not path.is_file():
        return {
            "error": f"no profile.md for {project!r}",
            "hint": "run /qa-baseline to create one",
        }
    out = {"project": state.get("project", project),
           "content": path.read_text(encoding="utf-8")}
    lessons = root / "lessons.md"
    if lessons.is_file():
        out["lessons"] = lessons.read_text(encoding="utf-8")
    return out


@mcp.tool(annotations=_RO)
def get_trends(project: str) -> dict:
    """Run-over-run trajectory: per-run test counts and verdicts parsed from
    the INDEX, plus the current pressure picture — open findings by severity,
    age distribution, quarantine size. Direction is the signal; cells the
    INDEX writes as prose come back raw with parsed numbers where possible."""
    state, err = load_state(project)
    if err:
        return err
    runs = []
    index = Path(state["_qa_root"]) / "reports" / "INDEX.md"
    if index.is_file():
        history = get_history(project)
        for row in history.get("runs", []):
            tests_cell = next((v for k, v in row.items() if "tests" in k.lower()), "")
            nums = re.findall(r"\d+", str(tests_cell))
            runs.append({
                "date": next((v for k, v in row.items() if k.lower() == "date"), None),
                "run_type": next((v for k, v in row.items() if "run type" in k.lower()), None),
                "verdict": next((v for k, v in row.items() if k.lower() == "verdict"), None),
                "tests_cell": tests_cell,
                "tests_passed": int(nums[0]) if nums else None,
            })
    hot = hotspots(state)
    open_findings = [f for f in state.get("findings", []) if f.get("status") == "open"]
    by_sev: dict = {}
    for f in open_findings:
        sev = str(f.get("severity") or "unknown").strip().capitalize()
        by_sev[sev] = by_sev.get(sev, 0) + 1
    ages = sorted(int(f.get("age_days") or 0) for f in open_findings)
    return {
        "project": state.get("project", project),
        "runs": runs,
        "current": {
            "run_number": state.get("run_number"),
            "verdict": state.get("verdict"),
            "open_findings": len(open_findings),
            "open_by_severity": by_sev,
            "age_days": {
                "oldest": ages[-1] if ages else None,
                "median": ages[len(ages) // 2] if ages else None,
            },
            "quarantine_size": len(state.get("flaky_quarantine", [])),
            "duration_s": (state.get("tests") or {}).get("duration_s"),
        },
        # Where defects actually cluster, computed from this project's own
        # findings. `runs_of_history` is part of the answer: a ranking built on
        # one run is a snapshot, not a pattern.
        "hotspots": hot,
    }


@mcp.tool(annotations=_RO)
def get_state(project: str) -> dict:
    """The full raw state.json for a project (escape hatch; schema in docs/state-schema.md)."""
    state, err = load_state(project)
    return err if err else state


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
