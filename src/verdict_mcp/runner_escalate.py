"""Escalating a local run to a paid one: the packet it hands over, the preflight checks, and
starting the escalation.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

try:
    from . import escalate
    from .runner_local import PREMEASURED_ENV, clear_marker, local_endpoint
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import escalate
    from runner_local import PREMEASURED_ENV, clear_marker, local_endpoint


def escalation_packet(repo, qa_root, args, budget_usd, local_main=None) -> tuple:
    """The breadth pass and the tester's packet → (packet text or None, exit code).

    `verdict-local` reads in a scratch copy of the QA root, on the facts verdict-run has just
    measured, so the real record is written once, by the tester. The copy is removed whatever
    happens; the packet and its summary are kept beside the record."""
    if local_main is None:
        try:
            from .small import main as local_main
        except ImportError:  # bare-script execution
            from small import main as local_main
    scratch = escalate.scratch_copy(qa_root)
    try:
        argv = escalate.local_argv(repo, scratch, qa_root, args.local_model, args.local_limit,
                                   args.sha_range, args.local_env_file)
        code = local_main(argv)
        if code != 0:
            print(f"verdict-run: the breadth pass exited {code} — no packet, so no escalation run "
                  "was started; run without --escalate for a full asked run", file=sys.stderr)
            return None, 5
        facts = json.loads((Path(qa_root) / "facts.json").read_text(encoding="utf-8"))
        text, summary = escalate.compose(scratch, facts, budget_usd,
                                         args.calls or escalate.CALLS_DEFAULT)
        escalate.record(qa_root, text, summary)
        print(f"verdict-run: escalation — {summary['leads']} item(s) for the tester from "
              f"{summary['local_model']} ({summary['functions_read']} function(s) read, "
              f"{summary['proven_local']} proven by counterfactual, {summary['survivor_functions']} "
              f"census survivor function(s)); packet {escalate.PACKET_FILE}", file=sys.stderr)
        return text, 0
    except (OSError, json.JSONDecodeError) as exc:
        print(f"verdict-run: the breadth pass left no readable facts ({type(exc).__name__}) — no "
              "escalation run was started", file=sys.stderr)
        return None, 5
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def start_escalation(repo, qa_root, args, env, base_url, token, cap) -> tuple:
    """The checks and the breadth pass before an escalation run's tester → (packet, exit code
    or None to go on). Every refusal here starts nothing, and never a full run in its place.
    Without --escalate there is nothing to do: ("", None)."""
    if not args.escalate:
        return "", None
    if not env.get(PREMEASURED_ENV):
        print("verdict-run: --escalate reads on the facts measured before the tester starts, "
              "and that measurement failed — no escalation run was started, and no full run "
              "in its place", file=sys.stderr)
        return "", 2
    try:
        from .small import gateway_alive
    except ImportError:  # bare-script execution
        from small import gateway_alive
    alive, detail = gateway_alive(base_url, token)
    print(f"verdict-run: local engine — {detail}", file=sys.stderr)
    if not alive:
        clear_marker(qa_root)
        print("verdict-run: the local gateway is down, so there is no breadth pass — no "
              "escalation run was started, and no full run in its place", file=sys.stderr)
        return "", 5
    packet, code = escalation_packet(repo, qa_root, args, cap)
    if packet is None:
        clear_marker(qa_root)
        return "", code
    return packet, None


def asked_preflight(args, ap) -> None:
    """`--lite`, `--escalate` and `--calls` shape an asked run, a model run; a local or
    model-free night has no tester to tell. One cheap mode at a time."""
    if args.lite and args.escalate:
        ap.error("--lite and --escalate are two cheap asked runs: pick one")
    if (args.lite or args.calls is not None) and args.on_drift != "model":
        ap.error("--lite and --calls shape an asked run's tester; --on-drift local/none runs none")
    if args.calls is not None and args.calls < 1:
        ap.error("--calls takes a positive number")


def escalate_preflight(args, ap) -> tuple:
    """(base_url, token, exit code or None) for `--escalate`, before anything runs; without
    the flag, (None, None, None)."""
    if not args.escalate:
        return None, None, None
    if args.on_drift != "model" or args.no_premeasure:
        ap.error("--escalate is an asked run: it measures first and launches the tester, so it "
                 "takes neither --on-drift local/none nor --no-premeasure")
    base_url, token = local_endpoint(args.local_env_file, dict(os.environ))
    if not base_url or not token:
        print("verdict-run: --escalate needs the local gateway — ANTHROPIC_BASE_URL and "
              "ANTHROPIC_AUTH_TOKEN in --local-env-file or in the environment. Refusing before "
              "anything runs: an escalation run with no breadth pass would be a full asked run "
              "nobody asked for.", file=sys.stderr)
        return None, None, 2
    return base_url, token, None
