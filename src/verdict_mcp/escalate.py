"""Escalation runs: breadth at zero Claude tokens, judgment from a short list.

An asked Opus run spends most of its bill re-reading its own context. One baseline on a
stranger's repository (2026-10-17) took 63 requests, 6.9M cache-read tokens and 85k output
tokens for $3.90, about four times a plain Claude session asked the same question. Most of what it
paid for was breadth: which functions to read, which lines the suite runs without checking.
The harness and the local tier already measure that for about a cent.

`verdict-run --escalate` runs `verdict-local` first, in a scratch copy of the QA root, and
hands the tester only what it passed on: the claims it proved by counterfactual, the
census's survivors, its unproven readings and the reasons a model run is owed. The tester
proves or drops each one. The real QA root gets two things from this module: the packet the
tester was given (`escalation.md`) and a summary under `last_run.escalation` in facts.json,
which finalize carries into the state, the bill and the not-tested list.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

LEADS_FILE = "leads.json"
PACKET_FILE = "escalation.md"
BUDGET_DEFAULT_USD = 2.5
# Caps for the breadth pass: the local gate's, which the 2026-10-14 measurements sized.
LOCAL_CAPS = ("--max-functions", "24", "--max-probes", "6", "--max-model-s", "600")
MAX_ITEMS = 25
MAX_SURVIVOR_FUNCTIONS = 12
SURVIVOR_LINES = 2
MAX_READ_FIRST = 6
SEVERITY_ORDER = {"Blocker": 0, "Critical": 1, "Major": 2, "Minor": 3, "Trivial": 4}
# Not copied into the scratch root: earlier runs' reports and probe scripts are history, and
# the breadth pass needs only the record and the facts.
SKIP_COPY = ("reports", "scratch", "findings.prev")


def scratch_copy(qa_root: Path) -> Path:
    """A private copy of the QA root for the breadth pass → its path. The local tier never
    writes the real root during an escalation run. Links are copied as links, so a planted
    one is refused in the copy exactly as it would be in the root."""
    dest = Path(tempfile.mkdtemp(prefix="verdict-escalation-"))
    if Path(qa_root).is_dir():
        shutil.copytree(qa_root, dest, symlinks=True, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(*SKIP_COPY))
    return dest


def local_argv(repo: Path, scratch: Path, qa_root: Path, model: str, limit: int,
               sha_range: str | None, env_file: Path | None) -> list:
    """verdict-local's arguments for the breadth pass: the facts verdict-run just measured,
    the local gate's caps, no flaky re-runs, and the real state read-only as the reference."""
    argv = ["--repo", str(repo), "--qa-root", str(scratch), "--reuse-facts",
            "--model", model, "--limit", str(limit), "--reruns", "0", *LOCAL_CAPS]
    if (Path(scratch) / "state.json").is_file():
        argv.append("--delta")
    if sha_range:
        argv += ["--range", sha_range]
    if (Path(qa_root) / "state.json").is_file():
        argv += ["--reference-state", str(Path(qa_root) / "state.json")]
    if env_file:
        argv += ["--env-file", str(env_file)]
    return argv


def _read(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _where(finding: dict) -> str:
    for a in finding.get("anchors") or []:
        if isinstance(a, dict) and (a.get("ref") or a.get("path")):
            return str(a.get("ref") or a.get("path"))
    first = str((finding.get("evidence") or [""])[0])
    return first.split(" ", 1)[0] if first else "?"


def _one_line(text, width=200) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[:width - 1] + "…"


def code_findings(scratch: Path) -> tuple:
    """The breadth pass's own filings about code → (proven, unproven), most severe first.
    Only what it filed in this pass (`NEW`) and only defects in code: skipped tests, flaky
    ones and failing gates are measured again by the tester's own harness."""
    state = _read(Path(scratch) / "state.json") or {}
    proven, unproven = [], []
    for f in state.get("findings") or []:
        if not isinstance(f, dict) or f.get("delta") != "NEW":
            continue
        if str(f.get("failure_classification") or "") != "REAL_DEFECT":
            continue
        (proven if f.get("confidence") == "proven" else unproven).append(f)

    def rank(f):
        return SEVERITY_ORDER.get(str(f.get("severity")), 9)

    return sorted(proven, key=rank), sorted(unproven, key=rank)


def survivors(facts: dict) -> list:
    """Census survivors grouped by function → [(path, function, [survivor, ...])]."""
    gaps = (facts or {}).get("assertion_gaps")
    if not isinstance(gaps, dict):
        return []
    grouped: dict = {}
    for s in gaps.get("survived") or []:
        if isinstance(s, dict) and s.get("path") and s.get("function"):
            grouped.setdefault((s["path"], s["function"]), []).append(s)
    return [(path, fn, items) for (path, fn), items in grouped.items()]


def compose(scratch: Path, facts: dict, budget_usd: float) -> tuple:
    """The packet the tester is handed, and the summary recorded beside the run → (text, summary).

    Order is priority: a claim the local tier proved by counterfactual, then every census
    survivor (finalize holds the tester to account for each under `repro_rule`), then the head
    of the harness's risk-ranked reading map that no survivor already covers, then the small
    model's unproven readings, its unfiled leads and the reasons a model run is owed. The
    first measurement (2026-10-18) put the reading map last, and the item a known defect sat
    behind was cut by the cap."""
    scratch = Path(scratch)
    scratch_facts = _read(scratch / "facts.json") or {}
    local = (scratch_facts.get("last_run") or {}).get("local") or {}
    proven, unproven = code_findings(scratch)
    leads = (_read(scratch / LEADS_FILE) or {}).get("leads") or []
    grouped = survivors(facts)
    owed = scratch_facts.get("needs_claude") or {}
    listed_functions = {(path, fn) for path, fn, _ in grouped[:MAX_SURVIVOR_FUNCTIONS]}
    reading_map = [i for i in (((facts or {}).get("read_first") or {}).get("items") or [])
                   if isinstance(i, dict) and (i.get("path"), i.get("function")) not in listed_functions]
    reading_map = reading_map[:MAX_READ_FIRST]

    items = [f"- **Proven by counterfactual** · `{_where(f)}` — {_one_line(f.get('title'))} "
             f"(read as {f.get('severity')})" for f in proven]
    for path, fn, found in grouped[:MAX_SURVIVOR_FUNCTIONS]:
        shown = "; ".join(f"line {s.get('line')}: `{_one_line(s.get('before'), 80)}` → "
                          f"`{_one_line(s.get('after'), 80)}`" for s in found[:SURVIVOR_LINES])
        items.append(f"- **Census survivor** · `{path}::{fn}` — its tests run it without checking "
                     f"what it does: they stay green when {shown}")
    items += [f"- **Read first** · `{i.get('path')}::{i.get('function')}` (risk: {i.get('risk')})"
              for i in reading_map]
    items += [f"- **Unproven reading** · `{_where(f)}` — {_one_line(f.get('title'))} "
              f"(read as {f.get('severity')})" for f in unproven]
    items += [f"- **Lead** · `{x.get('path')}:{x.get('line')}` `{x.get('function')}` — "
              f"{_one_line(x.get('title'))} (read as {x.get('severity')}; "
              f"{_one_line(x.get('why'), 100)})" for x in leads]
    items += [f"- **Owed a model run** · {reason}: {_one_line(value, 160)}"
              for reason, value in sorted(owed.items())]
    listed = items[:MAX_ITEMS]
    if len(items) > MAX_ITEMS:
        listed.append(f"- … {len(items) - MAX_ITEMS} more item(s) were not listed; name them in "
                      "not_tested as unread")
    if not items:
        listed.append("- The breadth pass passed nothing on: no claim, no survivor, no reason a "
                      "model run is owed. Confirm the gates, account for the reading map, and stop")
    model = local.get("model") or "the local model"
    functions = local.get("functions_read") or 0
    text = ESCALATION_SECTION.format(model=model, functions=functions, cap=budget_usd,
                                     items="\n".join(listed))
    summary = {
        "leads": min(len(items), MAX_ITEMS), "not_listed": max(0, len(items) - MAX_ITEMS),
        "proven_local": len(proven), "unproven_local": len(unproven),
        "unfiled_leads": len(leads), "survivor_functions": len(grouped), "owed": sorted(owed),
        "local_model": model, "local_calls": local.get("calls"),
        "local_seconds": local.get("seconds"), "functions_read": functions,
        "budget_usd": budget_usd,
        "packet_sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
    }
    return text, summary


ESCALATION_SECTION = """This is an escalation run (`verdict-run --escalate`). The breadth \
pass is done, at zero Claude tokens. The harness measured this commit: gates, coverage and \
the assertion-gap census. Then {model} read {functions} function(s) one at a time. What it \
passed on is listed below, most promising first. Your job is judgment and proof.

1. Work the list in order. For each item, read the cited function and the tests that \
exercise it. File it only if you can show it: `proven` with a `repro` block (command, cwd, \
expect) that fails while the defect is there, or `probable` with the argument. Otherwise drop \
it and say why in not_tested.
2. A census survivor says the function's tests run it without checking what it does. Read the \
whole function and what it computes, not only the line named: a defect, if there is one, can \
be anywhere in it. Then cite it in a finding, or name it in not_tested as \
`path::function — why`.
3. The list was chosen by coverage, the census and a small model, not by the scope your \
instructions name. Cover that scope as well, preferring what the list does not reach, and \
follow each item's evidence into its callers, callees and tests. Say in not_tested what you \
did not read.
4. Aim for about 35 tool calls. The run stops at ${cap:g}.

{items}
"""


def record(qa_root: Path, text: str, summary: dict) -> None:
    """The packet beside the record, and the summary into the facts the tester adopts."""
    root = Path(qa_root)
    (root / PACKET_FILE).write_text(text, encoding="utf-8")
    facts = _read(root / "facts.json")
    if isinstance(facts, dict):
        facts.setdefault("last_run", {})["escalation"] = summary
        (root / "facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")


def not_tested_line(summary: dict) -> str:
    """The line finalize adds to an escalation run's not-tested list, in the harness's voice."""
    return (f"escalation run: the tester was handed {summary.get('leads', 0)} item(s) from a "
            f"breadth pass by {summary.get('local_model') or 'a local model'}, which read "
            f"{summary.get('functions_read') or 0} function(s); Claude read only those items "
            "and what their evidence led to, and no other code")
