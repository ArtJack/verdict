"""What a run cost and who judged it: the usage file, the bill measured from the session,
and the gateway host, which never reaches a committed file.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
from pathlib import Path

try:
    from .usage import ENTRYPOINT_ENV, SESSION_ENV, run_usage, FIELDS as USAGE_FIELDS
    from .harness_common import _read_json
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from usage import ENTRYPOINT_ENV, SESSION_ENV, run_usage, FIELDS as USAGE_FIELDS
    from harness_common import _read_json


USAGE_FILE = "usage.jsonl"


def _judged_locally(facts: dict) -> bool:
    """Whether `verdict-local` judged this run — a model behind a gateway, not a Claude
    session. The engine signs `last_run.engine` before it finalizes and exports
    `VERDICT_MODEL=local:<alias>`; either is enough."""
    engine = str(((facts or {}).get("last_run") or {}).get("engine") or "")
    return engine == "verdict-local" or str(os.environ.get("VERDICT_MODEL") or "").startswith("local:")


def _measure_bill(qa_root: Path, facts: dict) -> dict | None:
    """What this run has spent, read from the session's own transcript → a record, or
    None when it cannot be known. Read before the state is composed, because the one
    thing in it that belongs in the state is *which model answered*: a run spawned as
    a subagent inherits its session's model, no operator exported `VERDICT_MODEL`, and
    for three weeks the author's own history recorded no model on most rows while the
    most expensive one on the account did the work."""
    # A local run's judge is not a Claude session. The session that launched it — an
    # orchestrator's desktop session, an eval — is somebody else's bill, and its models are
    # not the tester's: found 2026-10-14, when the suite was run from a desktop session that
    # had answered on two models, the one-model rule read that session's transcript and
    # blocked the finalize tests. A local gate launched from such a session would have been
    # blocked the same way. The engine's own calls and tokens are in `last_run.local`.
    if _judged_locally(facts):
        return None
    marker = _read_json(qa_root / "run-in-progress.json") or {}
    session = marker.get("session_id") or os.environ.get(SESSION_ENV)
    if not session:
        return None
    return run_usage(session, since=marker.get("started_utc"),
                     fingerprint=facts.get("measured_at"))


def _gateway_host(value) -> str | None:
    """The hostname in a gateway's base URL → or None. Never the URL itself.

    The local tier wrote `urlparse(base_url).hostname or base_url`, so a URL that parses
    to no hostname — one written without a scheme — went in whole, with whatever userinfo,
    path or query it carried. A bare hostname is read as one: that is what a facts.json
    written by 0.90.10 or earlier holds in `last_run.local.host`."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return None
    try:
        return urllib.parse.urlsplit(text if "//" in text else "//" + text).hostname or None
    except ValueError:
        return None


def _record_bill(qa_root: Path, state: dict, bill: dict | None,
                 gateway_host: str | None = None) -> None:
    """One line per run in `usage.jsonl`, beside the state and outside the signed row.

    Outside, because a bill is telemetry: signing it would make every state written
    before this file existed re-derive to a different row, the reason `gate_durations`
    is kept out of the chain body. A run with no readable transcript still gets its
    line — `usage: null` and why — so an absent bill is not mistaken for a free run.
    `gateway_host` is the host a local run called, which the state no longer carries
    (`finalize_main`): the bill is the paying machine's own telemetry, not the record a
    team commits, so it may name it.
    Never raises, and never changes the exit code: the state is already on disk."""
    try:
        last = state.get("last_run") or {}
        row = {"run_number": state.get("run_number"), "run_type": state.get("run_type"),
               "timestamp_utc": last.get("timestamp_utc"), "model": last.get("model")}
        if os.environ.get(ENTRYPOINT_ENV):
            row["entrypoint"] = os.environ[ENTRYPOINT_ENV]
        if os.environ.get("CLAUDE_EFFORT"):
            row["effort"] = os.environ["CLAUDE_EFFORT"]
        if isinstance(last.get("escalation"), dict):
            esc = last["escalation"]
            row["escalation"] = {k: esc.get(k) for k in ("leads", "local_model", "local_calls",
                                                          "functions_read", "budget_usd")}
        if state.get("run_type") == "sweep":
            row["usage"] = {"requests": 0, **{k: 0 for k in USAGE_FIELDS}}
            row["note"] = "model-free sweep: no model was called"
        elif last.get("engine"):
            # A second engine answered, so the Claude bill is a measured zero
            # rather than an unknown — and the engine's own counters go in the
            # same row, because "this night cost nothing" is only credible
            # beside the number of calls it took to cost nothing.
            row["engine"] = last["engine"]
            row["usage"] = {"requests": 0, **{k: 0 for k in USAGE_FIELDS}}
            row["local"] = {**(last.get("local") or {}),
                            **({"host": gateway_host} if gateway_host else {})}
            row["note"] = (f"judged by {last['engine']}: no Claude request was made; the "
                           "`local` object carries that engine's own calls and tokens")
        elif bill:
            row["usage"] = bill
            row["note"] = ("measured up to verdict-finalize; the closing handoff that "
                           "follows is not in it")
        else:
            row["usage"] = None
            row["note"] = ("no transcript could be read for this run — outside Claude Code, "
                           "another machine, or a cleaned home. Unknown, not zero")
        with (qa_root / USAGE_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as exc:        # noqa: BLE001 — see the docstring
        print(f"verdict-finalize: the run's bill was not recorded ({exc}); the state is "
              "written and valid", file=sys.stderr)
