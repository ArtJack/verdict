"""What a run actually spent, read from Claude Code's own transcript.

A model comparison is not a comparison until the bill is on the table beside the
score: a cheaper model that scores the same is only cheaper if it did not spend
three times the tokens getting there. The CLI's `--output-format json` result
line reports the *last turn*; a Verdict run does its work inside a delegated
subagent, so the session's real bill lives in the transcript — the main session
file plus every `subagents/*.jsonl` beside it, summed per request id (the same
request is written more than once as a turn streams).

Claude Code stores a session under `<config>/projects/<cwd with every character
outside [A-Za-z0-9-] replaced by ->/<session-id>.jsonl`, where `<config>` is
`CLAUDE_CONFIG_DIR` when set and `~/.claude` otherwise — so a run that spends a
second account's allowance writes its transcript beside that account, not in the
default place. Each eval run gets its own scratch checkout, so that directory
holds exactly this run's sessions.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens")


def config_root(config_dir=None) -> Path:
    """Where the CLI keeps its state: the directory named here, then
    `CLAUDE_CONFIG_DIR`, then the default."""
    named = config_dir or os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(named).expanduser() if named else Path.home() / ".claude"


def project_dir(cwd, config_dir=None) -> Path:
    key = re.sub(r"[^A-Za-z0-9-]", "-", str(Path(cwd).resolve()))
    return config_root(config_dir) / "projects" / key


def session_files(cwd, session_id=None, config_dir=None) -> list[Path]:
    """The transcript files for a run: one session's, or every session recorded
    for this working directory when no id is known."""
    base = project_dir(cwd, config_dir)
    if not base.is_dir():
        return []
    ids = [session_id] if session_id else [p.stem for p in base.glob("*.jsonl")]
    out = []
    for sid in ids:
        main = base / f"{sid}.jsonl"
        if main.is_file():
            out.append(main)
        subs = base / sid / "subagents"
        if subs.is_dir():
            out += sorted(subs.glob("*.jsonl"))
    return out


def usage_of(cwd, session_id=None, config_dir=None) -> dict | None:
    """`{requests, files, sessions, <token fields>}` for a run, or None when the
    transcript is not there (a different machine, a cleaned home)."""
    files = session_files(cwd, session_id, config_dir)
    if not files:
        return None
    by_req: dict[str, dict] = {}
    for path in files:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "assistant":
                continue
            usage = (record.get("message") or {}).get("usage")
            rid = record.get("requestId") or record.get("uuid")
            if isinstance(usage, dict) and rid:
                by_req[rid] = usage
    if not by_req:
        return None
    totals = {k: 0 for k in FIELDS}
    for usage in by_req.values():
        for k in FIELDS:
            totals[k] += int(usage.get(k) or 0)
    sessions = len({p.stem if p.parent.name != "subagents" else p.parent.parent.name
                    for p in files})
    return {"requests": len(by_req), "files": len(files), "sessions": sessions, **totals}


def add(left: dict | None, right: dict | None) -> dict | None:
    """Sum two usage records — a two-phase fixture run is one bill."""
    if left is None:
        return right
    if right is None:
        return left
    out = dict(left)
    for k in ("requests", "files", "sessions", *FIELDS):
        out[k] = int(left.get(k) or 0) + int(right.get(k) or 0)
    return out


def brief(usage: dict | None) -> str:
    if not usage:
        return "usage unknown"
    return (f"{usage['output_tokens'] // 1000}k out · "
            f"{usage['cache_read_input_tokens'] // 1000}k cache read · "
            f"{usage['requests']} requests")
