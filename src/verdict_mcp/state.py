"""Read-only loading of Verdict QA state. Stdlib only.

The MCP server and the `verdict-gate` CLI both build on this module. Keeping
`mcp` (and every other third-party import) out of here is what lets the GitHub
Action's gate mode run `gate.py` as a bare script with zero installs.

Project resolution, mirroring the agent's §0:
  - a bare key (e.g. "pricer") resolves to  $VERDICT_HOME/<key>/   (solo mode);
    VERDICT_HOME defaults to ~/.claude/verdict
  - a path (e.g. "/repo" or "~/work/app") resolves to <path>/.qa/  (team mode),
    or to the path itself if it directly contains state.json.
"""

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

SEVERITY_RANK = {"Blocker": 0, "Critical": 1, "Major": 2, "Minor": 3, "Trivial": 4}
DELTA_VALUES = {"NEW", "STILL_OPEN", "RESOLVED", "REGRESSED"}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[\\/]")


def home() -> Path:
    return Path(os.environ.get("VERDICT_HOME", str(Path.home() / ".claude" / "verdict")))


def known_projects() -> list[str]:
    root = home()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "state.json").is_file())


def sev_rank(value) -> int:
    """Rank severity case-insensitively; unknown or missing values sort last."""
    return SEVERITY_RANK.get(str(value or "").strip().capitalize(), 99)


def is_path_like(project: str) -> bool:
    """True when the argument addresses a filesystem path rather than a solo key."""
    return (
        "/" in project
        or "\\" in project
        or project.startswith("~")
        or project == "."
        or bool(_DRIVE_PREFIX.match(project))
    )


def resolve_root(project: str) -> Path | None:
    """Return the QA root for a project key or a filesystem path, else None."""
    if is_path_like(project):
        p = Path(project).expanduser().resolve()
        if (p / ".qa" / "state.json").is_file():
            return p / ".qa"
        if (p / "state.json").is_file():
            return p
        return None
    for key in (project, project.lower()):
        solo = home() / key
        if (solo / "state.json").is_file():
            return solo
    return None


def load_state(project: str) -> tuple[dict | None, dict | None]:
    """Return (state, error). Exactly one is non-None."""
    root = resolve_root(project)
    if root is None:
        return None, {
            "error": f"no Verdict state found for {project!r}",
            "known_projects": known_projects(),
            "hint": "pass a project key from known_projects, or a repo path whose .qa/ holds state.json",
        }
    try:
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"error": f"state.json unreadable for {project!r}: {exc}"}
    state["_qa_root"] = str(root)
    return state, None


def parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def parse_timestamp(value: str) -> datetime | None:
    """Parse a state timestamp into an aware UTC datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def order_findings(findings: list[dict]) -> list[dict]:
    """REGRESSED first, then severity, then oldest-first pressure."""
    return sorted(
        findings,
        key=lambda f: (
            0 if f.get("delta") == "REGRESSED" else 1,
            sev_rank(f.get("severity")),
            -(f.get("age_days") or 0),
        ),
    )
