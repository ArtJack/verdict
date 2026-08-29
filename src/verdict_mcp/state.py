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


_SOURCE_EXTS = (
    "py|ts|tsx|js|jsx|mjs|cjs|go|rs|rb|java|kt|php|cs|swift|sql|sh|"
    "yml|yaml|json|toml|md|css|html"
)
_CITED_PATH = re.compile(rf"([A-Za-z0-9_./-]+\.(?:{_SOURCE_EXTS}))\b")
# Defect *weight*, not defect count: ten typos are not a Critical. Exposed
# alongside the raw count because the two rank differently and both are true.
SEVERITY_WEIGHT = {"Blocker": 8.0, "Critical": 5.0, "Major": 2.0, "Minor": 1.0, "Trivial": 0.5}


def cited_path(finding: dict) -> str | None:
    """The first source path cited in a finding's evidence, if any."""
    for item in finding.get("evidence", []) or []:
        m = _CITED_PATH.search(str(item))
        if m:
            return m.group(1)
    return None


def _canonicalize(paths: set[str]) -> dict[str, str]:
    """Merge paths that are suffixes of one another onto the longest form.

    The same module gets cited at different depths across runs
    (`marketplaces/x.py` in one, `core/src/pkg/marketplaces/x.py` in another).
    Left unmerged, one hotspot reads as two lukewarm ones.
    """
    longest = sorted(paths, key=len, reverse=True)
    mapping = {}
    for p in paths:
        mapping[p] = next((q for q in longest if q != p and q.endswith("/" + p)), p)
    return mapping


def hotspots(state: dict, limit: int = 10) -> dict:
    """Where this project's defects actually cluster, computed from its own
    findings rather than from prose someone wrote once.

    Returns per-file `findings` (all-time), `open`, and `weight` (severity-
    weighted, all-time), plus `runs_of_history` — a ranking built on one run is
    a snapshot, not a pattern, and the caller is owed that number.
    """
    findings = state.get("findings", []) or []
    raw = {}
    uncited = 0
    for f in findings:
        path = cited_path(f)
        if path is None:
            uncited += 1
            continue
        raw.setdefault(path, []).append(f)

    canon = _canonicalize(set(raw))
    merged: dict[str, dict] = {}
    for path, group in raw.items():
        entry = merged.setdefault(
            canon[path], {"path": canon[path], "findings": 0, "open": 0, "weight": 0.0})
        for f in group:
            entry["findings"] += 1
            entry["open"] += 1 if f.get("status") == "open" else 0
            entry["weight"] += SEVERITY_WEIGHT.get(
                str(f.get("severity") or "").strip().capitalize(), 1.0)

    ranked = sorted(
        merged.values(), key=lambda e: (-e["weight"], -e["findings"], e["path"]))
    for entry in ranked:
        entry["weight"] = round(entry["weight"], 1)
    return {
        "runs_of_history": state.get("run_number"),
        "findings_total": len(findings),
        "findings_without_a_cited_path": uncited,
        "hotspots": ranked[:limit],
    }


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
