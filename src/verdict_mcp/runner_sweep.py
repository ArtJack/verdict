"""The model-free night: the sweep that runs the suite and the hygiene scan with no model,
what blocks it, and the verdict it may write.

Split out of runner.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and runner.py imports back what its callers use.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    from .gate import evaluate, news_line
    from .state import norm_status
    from . import clock
    from .gitenv import git_env
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from gate import evaluate, news_line
    from state import norm_status
    from gitenv import git_env


# ── the model-free night ──────────────────────────────────────────────────
#
# "I don't change code every day" is the objection every low-churn project
# raises against a nightly, and --skip-unchanged answered the exact-sha half of
# it. The other half: HEAD moved, but by a commit that touched nothing any
# finding cites. The harness can tell — it hashes every cited line (0.83.0),
# runs the gates, diffs the test-id set, and knows the quarantine dates — so
# the runner asks it, and when every condition holds it finalizes a sweep: the
# previous verdict carried by id (the 0.84.0 verb), signed by no model, a run
# number advanced so the gate's freshness reads true. Any condition failing
# prints why and runs the model. The judgment is synthetic and says so in every
# field a reader would look at.


#: The harness child's first act: put the runner's own source root on ITS path, and only there.
_BOOT = ("import sys; sys.path.insert(0, sys.argv.pop(1)); "
         "from verdict_mcp.harness import main; sys.exit(main())")


def _harness(sub: str, *args: str) -> subprocess.CompletedProcess:
    # The child runs the code this runner is, installed or not. Measured on the Sales nightly:
    # `python3 src/verdict_mcp/runner.py`, started by an interpreter that never installed the
    # package, could not `-m verdict_mcp.harness`, and every sweep from 2026-09-17 ended
    # "No module named 'verdict_mcp'" — exit 5, nothing measured, for two nights.
    #
    # 0.90.0 fixed that with PYTHONPATH, and every grandchild inherited it: from an installed
    # verdict the root is the whole site-packages of Verdict's own environment, and the
    # project's test command imported Verdict's packages ahead of its own. Measured the same
    # day on the pinned nightly's lab-down drill: Sales' pytest exited 2 with 925 of ~3,450
    # tests collected, the gate read as failed and the sweep was refused. The path goes into
    # the child's sys.path and nowhere else; the environment is inherited untouched.
    src = str(Path(__file__).resolve().parent.parent)
    return subprocess.run([sys.executable, "-c", _BOOT, src, sub, *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def _changed_files(repo, sha_range: str):
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", sha_range],
                          capture_output=True, text=True, env=git_env())
    if proc.returncode != 0:
        return None
    return sorted({ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()})


def sweep_blockers(facts: dict, previous: dict, changed, today) -> list[str]:
    """Every reason this run cannot be swept — empty means it can. Each
    condition is a measurement the harness already made; none is a guess."""
    why = []
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    if drift.get("status") != "measured":
        why.append("evidence drift not measured"
                   + (f" ({drift['reason']})" if drift.get("reason") else ""))
    else:
        summ = drift.get("summary") or {}
        moved = list(summ.get("drifted_findings") or []) + list(summ.get("drifted_accepted") or [])
        if moved or summ.get("drifted_intact"):
            why.append("cited code moved or changed: "
                       + ", ".join(moved[:5] or ["a verified-intact item"]))
    if changed is None:
        why.append("no commit range to compare")
    else:
        cited = set()
        for f in previous.get("findings") or []:
            # A hygiene finding is re-measured by the sweep's own scan: a file only it
            # cites has nothing a model must read.
            if not isinstance(f, dict) or f.get("source") == "hygiene" \
                    or norm_status(f.get("status")) in ("resolved", "withdrawn"):
                continue
            cited |= {str(a.get("path")).replace("\\", "/") for a in (f.get("anchors") or [])
                      if isinstance(a, dict) and a.get("path")}
        for group in previous.get("verified_intact_anchors") or []:
            cited |= {str(a.get("path")).replace("\\", "/") for a in (group or [])
                      if isinstance(a, dict) and a.get("path")}
        hit = sorted(set(changed) & cited)
        if hit:
            why.append("changed files a finding cites: " + ", ".join(hit[:5]))
    gates = facts.get("gates") or {}
    if not gates:
        why.append("no gate ran")
    for name, g in gates.items():
        if g.get("result") == "unavailable":
            why.append(f"gate {name} could not start (exit {g.get('exit_code')})")
        elif g.get("result") != "pass":
            why.append(f"gate {name} failed")
        if "counts_unparsed" in g:
            why.append(f"gate {name}: counts unparsed")
        if g.get("executed_nothing"):
            why.append(f"gate {name}: {g['executed_nothing']}")
    if gates and not any(g.get("counts") for g in gates.values()):
        why.append("no gate produced test counts")
    ids = facts.get("test_ids") if isinstance(facts.get("test_ids"), dict) else {}
    if ids.get("status") != "measured":
        why.append("the test-id set was not measured")
    elif ids.get("added_count") or ids.get("removed_count"):
        why.append(f"the test-id set changed (+{ids.get('added_count')}/-{ids.get('removed_count')})")
    for q in previous.get("flaky_quarantine") or []:
        until = str((q or {}).get("quarantined_until") or "")
        if not until or until <= today.isoformat():
            why.append(f"quarantine due: {(q or {}).get('test_id')}")
    if facts.get("previous_run_incomplete"):
        why.append("the previous run never finished")
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") == "measured" and cov.get("changed_lines") \
            and not cov.get("changed_lines_executed"):
        why.append("the diff has changed lines no test executed")
    return why


def uncapped_verdict(previous: dict):
    """The verdict a sweep carries: the tester's own, from before finalize capped it
    over a Critical the hygiene scan filed. The cap belongs to the Critical, not to
    the verdict — finalize applies it again while the Critical is open, and a sweep
    that carried the capped verdict would keep `pass with risks` long after the key
    was gone. Read only when the record says the verdict it holds is that cap."""
    capped = (previous.get("hygiene") or {}).get("verdict_capped") \
        if isinstance(previous.get("hygiene"), dict) else None
    if isinstance(capped, dict) and capped.get("to") == previous.get("verdict") and capped.get("from"):
        return capped["from"]
    return previous.get("verdict")


def sweep_judgment(facts: dict, previous: dict, changed: list, commits,
                   notes: list | None = None) -> dict:
    """The synthetic judgment of a sweep: the previous verdict, every open
    finding carried by id, and a not_tested that says what a sweep does not do.

    `verified_intact` is carried, not emptied. It used to be written `[]`, so a
    sweep silently dropped the list of invariants the NEXT sweep is supposed to
    guard — the one thing the first external user said he was paying for, deleted
    by the cheapest run in the system (P-32). `notes` carries anything the caller
    measured and the sweep itself cannot know, such as a gateway that was down.
    """
    # A hygiene finding is not carried by id: the sweep's own scan re-measures it, and
    # naming it would only record it as ignored (state.hygiene.ignored_judgment_ids).
    open_ids = [str(f["id"]) for f in previous.get("findings") or []
                if isinstance(f, dict) and f.get("id") and norm_status(f.get("status")) == "open"
                and f.get("source") != "hygiene"]
    sha_range = (facts.get("last_run") or {}).get("sha_range")
    n = f"{commits} commit{'' if commits == 1 else 's'}" if commits is not None else "commits"
    m = f"{len(changed)} file{'' if len(changed) == 1 else 's'}"
    return {
        "topic": "sweep",
        "verdict": uncapped_verdict(previous),
        "isolation_check": {"result": "n/a", "method": "model-free sweep: no agent ran; "
                            "verdict-facts read the checkout and wrote only inside the QA root"},
        "full_sweep": False,
        "release_blockers": list(previous.get("release_blockers") or []),
        "findings": [], "still_open": open_ids, "resolved": [], "questions": [],
        "not_tested": [f"everything a judgment covers — this run measured only: HEAD moved {n} "
                       f"({m} changed, none cited by a finding), every gate green, the collected "
                       "test-id set unchanged, no quarantine due, no cited line moved",
                       "nothing outside the checkout was read — no database, no MCP tools, no "
                       "production numbers — so a standing blocker that quotes one was NOT "
                       "re-read"] + [str(x) for x in (notes or [])],
        "verified_intact": list(previous.get("verified_intact") or []),
        "next_run_focus": list(previous.get("next_run_focus") or []),
        "flaky_quarantine": list(previous.get("flaky_quarantine") or []),
        "prose": {"scope": f"Model-free sweep over `{sha_range}`: {n}, {m} changed, none cited by "
                           "an open or accepted finding or a verified-intact item.",
                  "notes": "No agent ran. The previous verdict is carried because nothing it "
                           "rested on moved; the next model run judges the change on its merits."},
    }


def swept_verdict(qa_root, previous: dict) -> str:
    """What the sweep wrote, said as such. It carries the tester's verdict
    (`uncapped_verdict`), and a Critical the hygiene scan files, or still sees, caps a
    `pass` at `pass with risks`: the line said "'pass' carried" over a state that held
    the cap."""
    carried = uncapped_verdict(previous)
    try:
        state = json.loads((Path(qa_root) / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    written = state.get("verdict") if isinstance(state, dict) else None
    if written is None or written == carried:
        return f"verdict {carried!r} carried"
    capped = ((state.get("hygiene") or {}).get("verdict_capped") or {}).get("by") or []
    return (f"verdict {written!r} written, not the carried {carried!r}"
            + (f" — capped by {', '.join(map(str, capped))}, filed by the hygiene scan"
               if capped else ""))


def sweep(repo, qa_root, project, fail_on, require_harness, before, notes=None) -> int | None:
    """Try the model-free sweep → the gate's exit code, or None to run the model."""
    try:
        previous = json.loads((Path(qa_root) / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("verdict-run: no sweep — no previous state to carry; running the model",
              file=sys.stderr)
        return None
    facts_proc = _harness("facts", "--repo", str(repo), "--qa-root", str(qa_root))
    if facts_proc.returncode != 0:
        print("verdict-run: no sweep — verdict-facts failed: "
              + (facts_proc.stderr or "").strip().splitlines()[-1:][0] if facts_proc.stderr
              else "verdict-run: no sweep — verdict-facts failed", file=sys.stderr)
        return None
    try:
        facts = json.loads((Path(qa_root) / "facts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("verdict-run: no sweep — facts.json unreadable; running the model", file=sys.stderr)
        return None
    sha_range = (facts.get("last_run") or {}).get("sha_range")
    changed = _changed_files(repo, sha_range) if sha_range else None
    why = sweep_blockers(facts, previous, changed, clock.today())
    if why:
        print("verdict-run: no sweep — " + "; ".join(why) + " — running the model", file=sys.stderr)
        return None
    count = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", sha_range],
                           capture_output=True, text=True, env=git_env())
    commits = int(count.stdout.strip()) if count.returncode == 0 and count.stdout.strip().isdigit() else None
    judgment = sweep_judgment(facts, previous, changed or [], commits, notes)
    jpath = Path(qa_root) / "judgment.json"
    jpath.write_text(json.dumps(judgment, indent=2) + "\n", encoding="utf-8")
    fin = _harness("finalize", "--qa-root", str(qa_root), "--judgment", str(jpath), "--sweep")
    if fin.returncode != 0:
        print("verdict-run: no sweep — finalize refused the sweep; running the model:\n"
              + (fin.stderr or "").strip()[-600:], file=sys.stderr)
        return None
    counts = " · ".join(f"{name} {g.get('summary') or g.get('result')}"
                        for name, g in (facts.get("gates") or {}).items())
    print(f"verdict-run: swept — run {before + 1}: HEAD moved "
          f"{commits if commits is not None else '?'} commit(s), {len(changed or [])} file(s) "
          f"changed, none cited by a finding; gates green ({counts}); test-id set unchanged; "
          f"no quarantine due; no cited line moved — {swept_verdict(qa_root, previous)}, "
          "no model call", file=sys.stderr)
    result = evaluate(project, fail_on, None, before + 1, require_harness=require_harness)
    print(f"verdict-run: verdict {result.get('verdict')!r} → exit {result['exit_code']} "
          f"({result['reason']})")
    if news := news_line(result):
        print(f"verdict-run: {news}")
    if result.get("report"):
        print(f"verdict-run: report {result['report']}")
    return result["exit_code"]
