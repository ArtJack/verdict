#!/usr/bin/env python3
"""Where the tokens went: every Verdict-agent run this machine recorded, by who launched
it, which model signed it, and how long its context grew.

`usage.py` prices one run. This prices the habit. The question it was written to answer
(2026-09-16) was "is the nightly what is eating the subscription?", and the answer was no:
of 231 Verdict-agent runs in five weeks, 213 had been spawned from interactive desktop
sessions and inherited that session's model, and they were 83% of the cache-read tokens.
The scheduled nightly — the thing everybody suspected — was 16%. A cost decision made
without this table would have optimised the wrong sixth.

What it reads is Claude Code's own record, not anything Verdict wrote: a delegated agent's
transcript lives at `<config>/projects/<cwd key>/<session>/subagents/agent-<id>.jsonl` with
an `agent-<id>.meta.json` beside it naming the agent type. A request is written more than
once as a turn streams, so tokens are summed per request id, the way `usage.py` does it.

Two numbers here are not in any bill and matter more than the bill: **requests** per run
and the **largest context** any request carried. A run costs turns times a growing context
— the largest single tool result in a traced run was 6k characters — so a run of 150
requests that ends at 400k tokens of context costs an order of magnitude more than the
median one, and a handful of those are a quarter of the total.

    python3 eval/usage_census.py --since 2026-09-01
    python3 eval/usage_census.py --since 2026-09-17 --json > after.json

Reads only. No model, no network, nothing written.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

try:
    from usage import FIELDS, config_root
except ImportError:  # run from another directory
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from usage import FIELDS, config_root

# The names a Verdict agent has run under: the plugin's, the provisioned project-scope
# copy `verdict-run` writes, and the release-candidate copy the eval rig uses.
AGENT_TYPES = ("verdict", "verdict:verdict", "verdict-rc")
HEADLESS = "sdk-cli"                 # `claude -p`: a nightly, an eval, a batch
TOP = 10


def _stamp(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def read_run(transcript: Path) -> dict | None:
    """One delegated agent's transcript as one row, or None when it holds no request."""
    by_request: dict[str, tuple] = {}
    first = last = entrypoint = None
    try:
        handle = transcript.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    with handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue            # a transcript cut off mid-line is still a transcript
            if not isinstance(record, dict):
                continue
            stamp = record.get("timestamp")
            if stamp:
                first = first or stamp
                last = stamp
            entrypoint = entrypoint or record.get("entrypoint")
            if record.get("type") != "assistant":
                continue
            message = record.get("message") or {}
            usage = message.get("usage")
            request = record.get("requestId") or record.get("uuid")
            if isinstance(usage, dict) and request:
                by_request[request] = (usage, message.get("model"))
    if not by_request:
        return None
    row = {k: 0 for k in FIELDS}
    models: Counter = Counter()
    largest = 0
    for usage, model in by_request.values():
        models[str(model)] += 1
        for k in FIELDS:
            row[k] += int(usage.get(k) or 0)
        # What one request carried in: everything but the output. The last of these is
        # how big the conversation had grown by the time the run ended.
        largest = max(largest, sum(int(usage.get(k) or 0) for k in FIELDS if k != "output_tokens"))
    began, ended = _stamp(first), _stamp(last)
    row.update(
        requests=len(by_request), model=models.most_common(1)[0][0], models=dict(models),
        entrypoint=entrypoint or "unknown", max_context=largest,
        started=first, day=(first or "")[:10],
        minutes=round((ended - began).total_seconds() / 60, 1) if began and ended else None)
    return row


def runs(config_dir=None, agent_types=AGENT_TYPES, since: str | None = None,
         until: str | None = None) -> list[dict]:
    """Every run of the named agent types under this configuration, oldest first."""
    rows = []
    base = config_root(config_dir) / "projects"
    for meta_path in sorted(base.glob("*/*/subagents/*.meta.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict) or meta.get("agentType") not in agent_types:
            continue
        row = read_run(meta_path.with_name(meta_path.name[:-len(".meta.json")] + ".jsonl"))
        if row is None:
            continue
        if (since and row["day"] < since) or (until and row["day"] > until):
            continue
        row.update(agent=meta.get("agentType"), description=str(meta.get("description") or ""),
                   spawn_model=meta.get("model"),      # None = the session's model was inherited
                   project=meta_path.parents[2].name)
        rows.append(row)
    return sorted(rows, key=lambda r: r["started"] or "")


def _total(rows) -> dict:
    out = {k: sum(r[k] for r in rows) for k in FIELDS}
    out.update(runs=len(rows), requests=sum(r["requests"] for r in rows))
    return out


def _grouped(rows, key) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    return {name: _total(members) for name, members in sorted(groups.items())}


def _week(day: str) -> str:
    try:
        year, week, _ = date.fromisoformat(day).isocalendar()
    except ValueError:
        return "unknown"
    return f"{year}-W{week:02d}"


def _quantiles(values) -> dict:
    values = sorted(values)
    if not values:
        return {}
    return {"median": statistics.median(values),
            "p90": values[min(len(values) - 1, int(len(values) * 0.9))], "max": values[-1]}


def summarize(rows: list[dict]) -> dict:
    return {
        "total": _total(rows),
        "by_launch": _grouped(rows, lambda r: "headless" if r["entrypoint"] == HEADLESS
                              else "interactive"),
        "by_model": _grouped(rows, lambda r: r["model"]),
        "by_week": _grouped(rows, lambda r: _week(r["day"])),
        "by_project": _grouped(rows, lambda r: r["project"]),
        "inherited_model": sum(1 for r in rows if not r["spawn_model"]),
        "per_run": {name: _quantiles([r[name] for r in rows])
                    for name in ("requests", "output_tokens", "cache_read_input_tokens",
                                 "max_context")},
        "largest": [{k: r[k] for k in ("day", "project", "model", "requests", "output_tokens",
                                       "cache_read_input_tokens", "max_context", "description")}
                    for r in sorted(rows, key=lambda r: -r["cache_read_input_tokens"])[:TOP]],
    }


def _line(name: str, t: dict) -> str:
    return (f"  {name[:44]:44s} {t['runs']:4d} runs {t['requests']:6d} req  "
            f"{t['output_tokens'] / 1e6:6.2f}M out  {t['cache_read_input_tokens'] / 1e6:8.1f}M read  "
            f"{t['cache_creation_input_tokens'] / 1e6:6.1f}M write")


def render(summary: dict) -> str:
    total = summary["total"]
    if not total["runs"]:
        return "no Verdict-agent runs recorded in that window"
    out = [_line("all runs", total).strip(),
           f"  spawned with no model named (the session's model was inherited): "
           f"{summary['inherited_model']} of {total['runs']}"]
    for title, key in (("who launched it", "by_launch"), ("which model", "by_model"),
                       ("by ISO week", "by_week")):
        out.append(f"\n{title}")
        out += [_line(name, t) for name, t in summary[key].items()]
    out.append("\nby project directory (largest cache-read first)")
    ranked = sorted(summary["by_project"].items(),
                    key=lambda kv: -kv[1]["cache_read_input_tokens"])[:TOP]
    out += [_line(name, t) for name, t in ranked]
    out.append("\none run (median · p90 · max)")
    for name, q in summary["per_run"].items():
        out.append(f"  {name:28s} {q['median']:>12,.0f} {q['p90']:>12,.0f} {q['max']:>12,.0f}")
    out.append(f"\nthe {len(summary['largest'])} largest runs by cache-read")
    for r in summary["largest"]:
        out.append(f"  {r['day']} {r['model'][:18]:18s} {r['requests']:4d} req  "
                   f"{r['cache_read_input_tokens'] / 1e6:5.1f}M read  context to "
                   f"{r['max_context'] / 1e3:4.0f}k  {r['description'][:48]}")
    return "\n".join(out)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--since", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD")
    ap.add_argument("--config-dir", default=None,
                    help="a CLAUDE_CONFIG_DIR other than the default — a second account's "
                         "runs are recorded beside that account")
    ap.add_argument("--agent-type", action="append", default=None, metavar="NAME",
                    help=f"agent types to count (default: {', '.join(AGENT_TYPES)})")
    ap.add_argument("--json", action="store_true", help="the summary as JSON")
    args = ap.parse_args(argv)
    rows = runs(args.config_dir, tuple(args.agent_type or AGENT_TYPES), args.since, args.until)
    summary = summarize(rows)
    print(json.dumps(summary, indent=1) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
