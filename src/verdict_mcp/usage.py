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

This module lived in `eval/` until 0.89.0, which meant only the eval could read a
bill: a production run recorded which model signed the verdict when an operator
exported `VERDICT_MODEL`, and never what it cost. A census of the author's own
machine (eval/README, "Where the tokens go") found 214 of 232 runs had been
spawned with no model named and had inherited the most expensive one on the
account — a default nobody chose, invisible because nothing wrote it down.
`run_usage` is what `verdict-finalize` calls to write it down.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens",
          "cache_read_input_tokens")

# What the CLI exports to every tool call it spawns. Measured, not documented: the
# value is the session's transcript id, the same string a hook receives as
# `session_id`. Absent outside Claude Code, and then nothing here is known.
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"
ENTRYPOINT_ENV = "CLAUDE_CODE_ENTRYPOINT"


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


# ── a production run's own bill, read where it is finalized ───────────────────

def _when(text) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def session_transcripts(session_id: str, config_dir=None) -> list[Path]:
    """Every transcript of one session, wherever its project directory is. The key
    of that directory is the *session's* launch directory, which a run inside a
    worktree or a `cd` does not share — so the session id is the handle, not the cwd."""
    if not session_id or not re.fullmatch(r"[A-Za-z0-9_-]+", str(session_id)):
        return []
    base = config_root(config_dir) / "projects"
    if not base.is_dir():
        return []
    return sorted(base.glob(f"*/{session_id}.jsonl")) + \
        sorted(base.glob(f"*/{session_id}/subagents/*.jsonl"))


def _modified(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _the_runs_transcript(files: list[Path], fingerprint: str | None) -> tuple:
    """(path, how it was chosen). A session can hold several agents at once, and only
    one of them is this run: the one whose transcript carries the facts' own
    `measured_at`, because `verdict-facts` printed it there. A delegated agent's file
    is looked at before the main session's, which may quote the handoff. With no
    fingerprint to find — the facts were redirected to a file — the transcript still
    being written is the one running `verdict-finalize`, and the record says which
    rule chose it."""
    newest_first = sorted(files, key=_modified, reverse=True)
    if fingerprint:
        delegated = [p for p in newest_first if p.parent.name == "subagents"]
        for path in delegated + [p for p in newest_first if p not in delegated]:
            try:
                if fingerprint in path.read_text(encoding="utf-8", errors="replace"):
                    return path, "fingerprint"
            except OSError:
                continue
    return (newest_first[0], "latest-transcript") if newest_first else (None, None)


def run_usage(session_id: str | None, *, since: str | None = None,
              fingerprint: str | None = None, config_dir=None) -> dict | None:
    """What this run has spent so far, or None when that cannot be known — outside
    Claude Code, on another machine, under a cleaned home. Never raises: a bill that
    cannot be read must not cost the run its state.

    `since` is the run marker's `started_utc`; requests stamped before it belong to
    whatever the session was doing earlier. What is *not* in the figure is everything
    after `verdict-finalize` returns — the closing handoff — so it reads a turn or
    two under the transcript's final total. `eval/usage_census.py` reads that total."""
    try:
        path, source = _the_runs_transcript(session_transcripts(session_id, config_dir),
                                            fingerprint)
        if path is None:
            return None
        began = _when(since) if since else None
        by_request: dict[str, tuple] = {}
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "assistant":
                    continue
                stamp = _when(record.get("timestamp"))
                if began and stamp and stamp < began:
                    continue
                message = record.get("message") or {}
                usage = message.get("usage")
                request = record.get("requestId") or record.get("uuid")
                if isinstance(usage, dict) and request:
                    by_request[request] = (usage, message.get("model"), stamp)
        if not by_request:
            return None
        out = {k: 0 for k in FIELDS}
        models: Counter = Counter()
        stamps = []
        for usage, model, stamp in by_request.values():
            if model and not str(model).startswith("<"):      # "<synthetic>" is not a model
                models[str(model)] += 1
            if stamp:
                stamps.append(stamp)
            for k in FIELDS:
                out[k] += int(usage.get(k) or 0)
        out.update(requests=len(by_request), models=dict(models),
                   model=models.most_common(1)[0][0] if models else None,
                   source=source, transcript=path.name)
        if stamps:
            out["model_wall_s"] = int((max(stamps) - min(stamps)).total_seconds())
        return out
    except Exception:       # noqa: BLE001 — telemetry never takes a run down with it
        return None
