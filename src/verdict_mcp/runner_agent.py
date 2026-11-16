"""Which agent judges and how: the prompt, the agent's name and effort, its flags, and the
bill and budget lines a run prints.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import json
from pathlib import Path


DEFAULT_PROMPT = (
    "Use the verdict agent to run today's QA pass on this repository — a delta run "
    "against the stored baseline, or a baseline if none exists. Run the agent to "
    "completion IN THIS SESSION: do not spawn it in the background, and do not end "
    "your turn until its state file and report are written — there is no 'later' in "
    "a headless run. Verdict reports and specifies; it does not fix. Relay the agent's "
    "handoff verbatim and add nothing of your own: no summary, no offer to write fixes "
    "— an offer to fix under Verdict's name is the one sentence its position cannot "
    "afford.")


# The prompt when the session IS the tester (`--agent verdict`): there is no outer
# session left to relay, delegate or offer anything.
AGENT_PROMPT = (
    "Run today's QA pass on this repository — a delta run against the stored baseline, or "
    "a baseline if none exists. This is a run: start with verdict-facts and end with "
    "verdict-finalize, in this session and in the foreground; an answer without state is "
    "not accepted, and there is no 'later' in a headless run.")


# The tester is the session itself, not a subagent the session may or may not spawn. On
# 2026-10-06 four asked money gates ran from a packet that never asked for the agent: a
# generic session at effort `medium`, without Verdict's prompt, and two of the four ended
# their turn with no state. `--agent` makes the provisioned agent file the main thread —
# its prompt, its tools, and the scope guards that know it by name — and `--effort` pins
# the effort its frontmatter pins.
AGENT_NAME = "verdict"


AGENT_EFFORT_DEFAULT = "xhigh"


def agent_effort(repo) -> str:
    """The effort the provisioned agent file pins (`effort:` in its frontmatter)."""
    try:
        text = (Path(repo) / ".claude" / "agents" / f"{AGENT_NAME}.md").read_text(encoding="utf-8")
    except OSError:
        return AGENT_EFFORT_DEFAULT
    head = text.split("\n---", 1)[0] if text.startswith("---") else ""
    for line in head.splitlines():
        if line.strip().startswith("effort:"):
            value = line.split(":", 1)[1].strip().strip("'\"")
            return value or AGENT_EFFORT_DEFAULT
    return AGENT_EFFORT_DEFAULT


def agent_flags(repo, passthrough) -> list:
    """`--agent verdict --effort <pinned>`, when the agent file is there to load. Without
    it (`--no-provision` on a repository that has none) the session is told in words, as
    before. An operator's own `--agent` or `--effort` after `--` is theirs to keep."""
    if not (Path(repo) / ".claude" / "agents" / f"{AGENT_NAME}.md").is_file():
        return []
    def given(flag):
        return any(p == flag or p.startswith(flag + "=") for p in passthrough)

    flags = []
    if not given("--agent"):
        flags += ["--agent", AGENT_NAME]
    if not given("--effort"):
        flags += ["--effort", agent_effort(repo)]
    return flags


# Opus 5.5 list rates, $/MTok: what an escalation run's bill line prices its tokens at.
OPUS_RATES = {"input_tokens": 4.0, "output_tokens": 20.0, "cache_read_input_tokens": 0.20,
              "cache_creation_input_tokens": 5.0}


def budget_line(cap, calls) -> str:
    """What a capped asked run's tester is told about its budget (0.93.0). A session stopped at its
    dollar cap writes no state, so the tester paces itself and keeps room to finalize; the
    2026-10-19 runs that were told so all finalized under the cap."""
    if cap is None:
        return ""
    aim = f"Aim for about {calls} tool calls. " if calls else ""
    return f"{aim}The run stops at ${cap:g}: keep enough of it to finalize."


def tester_prompt(prompt, told, tester, packet, budget="") -> str:
    """The words the session is launched with: the operator's, else the agent's or the
    delegating prompt, then an escalation run's packet or a capped run's budget line."""
    text = prompt if told else (AGENT_PROMPT if tester else DEFAULT_PROMPT)
    if packet:
        return f"{text}\n\n{packet}"
    # The budget joins on the same line: a `.cmd` shim on Windows (an npm-installed `claude`)
    # ends an argument at its first newline, and every flag after the prompt would be lost.
    return f"{text} {budget}" if budget else text


def print_bill(args, qa_root, before=0, capped=False) -> None:
    """A capped asked run (--lite, --escalate, --max-budget-usd) closes with what it cost; every
    run's bill is in usage.jsonl as before."""
    bill = bill_line(qa_root, before) if (args.escalate or capped) else None
    if bill:
        print(f"verdict-run: {'escalation run' if args.escalate else 'run'} bill — {bill}")


def bill_line(qa_root, before=0) -> str | None:
    """The bill of every run this invocation wrote (run_number above `before`), summed from
    usage.jsonl and priced when the model is Opus 5.5: a session that finalized twice spent twice."""
    try:
        rows = [json.loads(line) for line in
                (Path(qa_root) / "usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return None
    usage: dict = {}
    for row in rows:
        if isinstance(row.get("run_number"), int) and row["run_number"] > before:
            for key, value in (row.get("usage") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    usage[key] = usage.get(key, 0) + value
                elif key == "model":
                    usage[key] = value
    if not usage.get("requests"):
        return None
    line = (f"{usage['requests']} request(s), {usage.get('output_tokens', 0):,} output and "
            f"{usage.get('cache_read_input_tokens', 0):,} cache-read token(s)")
    if str(usage.get("model") or "").startswith("claude-opus-5-5"):
        dollars = sum(usage.get(k, 0) * rate for k, rate in OPUS_RATES.items()) / 1e6
        line += f", about ${dollars:.2f} at list price"
    return line
