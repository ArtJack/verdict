"""Read-only MCP server over Verdict QA state.

Exposes the state the Verdict agent maintains (state.json, reports/INDEX.md)
to any MCP client — an orchestrator gating a merge, Cursor/Codex sessions, a
CI step commenting a PR. Every tool is read-only: the server never writes,
and the write path stays exclusively with the agent.

Project resolution, mirroring the agent's own rules:
  - a bare key (e.g. "pricer") resolves to  $VERDICT_HOME/<key>/   (solo mode);
    VERDICT_HOME defaults to ~/.claude/verdict
  - a path (e.g. "/repo" or "~/work/app") resolves to <path>/.qa/  (team mode),
    or to the path itself if it directly contains state.json.

Unknown projects return {"error": ...} with the known project list rather
than raising — friendlier for agent consumers.
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("verdict")
_RO = ToolAnnotations(readOnlyHint=True)

_SEVERITY_RANK = {"Blocker": 0, "Critical": 1, "Major": 2, "Minor": 3, "Trivial": 4}
_DELTA_VALUES = {"NEW", "STILL_OPEN", "RESOLVED", "REGRESSED"}


def _home() -> Path:
    return Path(os.environ.get("VERDICT_HOME", str(Path.home() / ".claude" / "verdict")))


def _known_projects() -> list[str]:
    home = _home()
    if not home.is_dir():
        return []
    return sorted(p.name for p in home.iterdir() if (p / "state.json").is_file())


def resolve_root(project: str) -> Path | None:
    """Return the QA root for a project key or a filesystem path, else None."""
    if os.sep in project or project.startswith("~") or project == ".":
        p = Path(project).expanduser().resolve()
        if (p / ".qa" / "state.json").is_file():
            return p / ".qa"
        if (p / "state.json").is_file():
            return p
        return None
    solo = _home() / project
    if (solo / "state.json").is_file():
        return solo
    return None


def _load_state(project: str) -> tuple[dict | None, dict | None]:
    """Return (state, error). Exactly one is non-None."""
    root = resolve_root(project)
    if root is None:
        return None, {
            "error": f"no Verdict state found for {project!r}",
            "known_projects": _known_projects(),
            "hint": "pass a project key from known_projects, or a repo path whose .qa/ holds state.json",
        }
    try:
        state = json.loads((root / "state.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"error": f"state.json unreadable for {project!r}: {exc}"}
    state["_qa_root"] = str(root)
    return state, None


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


@mcp.tool(annotations=_RO)
def list_projects() -> dict:
    """List every project with a Verdict baseline in the solo state root."""
    out = []
    for key in _known_projects():
        state, err = _load_state(key)
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
    return {"state_root": str(_home()), "projects": out}


@mcp.tool(annotations=_RO)
def get_verdict(project: str) -> dict:
    """The last recorded verdict, release blockers, and report path for a project."""
    state, err = _load_state(project)
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
    state, err = _load_state(project)
    if err:
        return err
    findings = state.get("findings", [])
    if status == "all":
        selected = findings
    elif status == "open":
        selected = [f for f in findings if f.get("status") == "open"]
    elif status in _DELTA_VALUES:
        selected = [f for f in findings if f.get("delta") == status]
    else:
        return {
            "error": f"unknown status {status!r}",
            "allowed": ["open", "all", *sorted(_DELTA_VALUES)],
        }
    ordered = sorted(
        selected,
        key=lambda f: (
            0 if f.get("delta") == "REGRESSED" else 1,
            _SEVERITY_RANK.get(f.get("severity"), 99),
            -(f.get("age_days") or 0),
        ),
    )
    return {"project": state.get("project", project), "status": status, "count": len(ordered), "findings": ordered}


@mcp.tool(annotations=_RO)
def get_quarantine(project: str) -> dict:
    """The flaky-test quarantine ledger, with an expired flag per entry."""
    state, err = _load_state(project)
    if err:
        return err
    today = date.today()
    entries = []
    for q in state.get("flaky_quarantine", []):
        until = _parse_date(q.get("quarantined_until", ""))
        entries.append({**q, "expired": bool(until and until < today)})
    return {"project": state.get("project", project), "count": len(entries), "quarantine": entries}


@mcp.tool(annotations=_RO)
def get_history(project: str) -> dict:
    """Run history parsed from the project's reports/INDEX.md, oldest first."""
    state, err = _load_state(project)
    if err:
        return err
    index = Path(state["_qa_root"]) / "reports" / "INDEX.md"
    if not index.is_file():
        return {"project": state.get("project", project), "runs": [], "note": "no INDEX.md yet"}
    rows, header = [], None
    for line in index.read_text().splitlines():
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
def get_state(project: str) -> dict:
    """The full raw state.json for a project (escape hatch; schema in docs/state-schema.md)."""
    state, err = _load_state(project)
    return err if err else state


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
