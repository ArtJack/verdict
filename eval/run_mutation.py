#!/usr/bin/env python3
"""Recall: of defects nobody authored by hand, how many does Verdict find?

`eval/score.py` measures precision against an answer key — eight defects
someone wrote on purpose, which the prompt has effectively been tuned against.
This measures the other half, and it is the number a tester is actually judged
on: **what did you miss?**

The protocol, per mutant:

  1. `eval/mutate.py` takes a *correct* module and breaks one line. Only
     mutants that survive the test suite AND provably change behaviour are used
     — a mutant the suite kills takes no insight to find, and an equivalent
     mutant is a question with no answer.
  2. The mutant is planted in a fresh scratch repo, one defect and no others.
  3. Verdict runs a baseline QA review, in the same isolation the eval uses.
  4. A finding *catches* the mutant when it cites the module and names the
     function that was broken. On a module whose only defect is the planted
     one, that is a defensible bar — and every finding, matched or not, is
     recorded so a human can audit the call.

Because the base is clean, the run also measures the opposite error for free:
findings about a module that has exactly one defect, which are candidate false
positives. Both numbers are reported. Neither is flattered.

Usage:
    python3 eval/run_mutation.py --model opus [--limit 3] [--mutants M03,M26]

Model runs cost real tokens: one per mutant. This is never a per-PR CI job.
"""

# Lazy annotations: `python3 eval/run_mutation.py` is a documented command, and on a stock
# Mac `python3` is 3.9, where `str | None` in a signature is evaluated at
# definition time and raises TypeError (VERDICT-F-63 — F-55 again, in the
# scripts the floor test did not glob).
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))

from mutate import apply_to, census                      # noqa: E402
from run_eval import git, overlay, provision, run_agent, scratch_dir  # noqa: E402

PROMPT = ("Use the verdict-rc agent to run a QA review of the pricer module in this "
          "repository. Verdict-rc reports and specifies; it does not fix. Return the "
          "agent's full handoff: verdict, findings, and artifact paths.")

# The checkout is named for the project, never for its role here: the name becomes the
# project key, the QA root and the prefix of every finding id, and `pricer_clean`
# announced a module someone had already declared correct.
CHECKOUT_NAME = {"pricer_clean": "pricer"}

# The census's behavioural oracle stays with the maintainer's tools. A `probe.py` that
# fingerprints every public function over an input grid is not a file a small project
# has; it tells a tester it is standing inside a mutation run.
MAINTAINER_ONLY = ("probe.py",)


def enclosing_function(source: str, line: int) -> str | None:
    """The `def` a line belongs to — how a finding is matched to a mutant."""
    for text in reversed(source.splitlines()[:line]):
        m = re.match(r"\s*def\s+(\w+)", text)
        if m:
            return m.group(1)
    return None


def classify(state: dict, module: str, function: str | None, line: int) -> dict:
    """Split the run's findings into the one that caught the mutant, and the rest."""
    stem = Path(module).name
    caught, others = [], []
    for f in state.get("findings", []):
        text = " ".join([str(f.get("title", ""))]
                        + [str(e) for e in (f.get("evidence") or [])]).lower()
        cites_module = stem.lower() in text
        names_function = bool(function) and function.lower() in text
        entry = {"id": f.get("id"), "title": f.get("title"),
                 "severity": f.get("severity"), "confidence": f.get("confidence"),
                 "cites_line": f"{stem}:{line}" in text}
        (caught if cites_module and names_function else others).append(entry)
    return {"caught_by": caught, "other_findings": others}


def stage(mutant, fixture_dir, module, work, base_env) -> tuple:
    """The repository the tester is handed: the base with one line broken, one commit.

    The workdir carries no name of its own — `verdict-mut-M03-` put the eval, the
    protocol and the mutant's own id in every absolute path the tester wrote down.
    """
    name = CHECKOUT_NAME.get(fixture_dir.name, fixture_dir.name)
    checkout, qa_home = work / name, work / "qa-home"
    overlay(fixture_dir, checkout, copy=shutil.copy2, exclude=MAINTAINER_ONLY)
    qa_home.mkdir(parents=True, exist_ok=True)
    source = (fixture_dir / module).read_text(encoding="utf-8")
    (checkout / module).write_text(apply_to(source, mutant), encoding="utf-8")

    git(["init", "-qb", "main"], checkout, base_env)
    provision(checkout, {})
    git(["add", "-A"], checkout, base_env)
    git(["commit", "-qm", "Initial commit"], checkout, base_env)
    return checkout, qa_home, qa_home / name


def run_one(mutant, fixture_dir, module, args, base_env):
    work = scratch_dir()
    result = {"mutant": mutant["id"], "operator": mutant["operator"],
              "line": mutant["line"], "before": mutant["before"],
              "after": mutant["after"], "workdir": str(work)}
    try:
        checkout, qa_home, qa_root = stage(mutant, fixture_dir, module, work, base_env)
        source = (fixture_dir / module).read_text(encoding="utf-8")
        result["function"] = enclosing_function(source, mutant["line"])

        run_agent(PROMPT, checkout, qa_home, args.model, args.timeout_s,
                  base_env, work / "run.log")
        state_path = qa_root / "state.json"
        if not state_path.is_file():
            result["error"] = "the agent wrote no state"
            return result
        state = json.loads(state_path.read_text(encoding="utf-8"))
        result.update(classify(state, module, result["function"], mutant["line"]))
        result["caught"] = bool(result["caught_by"])
        result["verdict"] = state.get("verdict")
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", default="pricer_clean")
    ap.add_argument("--module", default="pricer.py")
    ap.add_argument("--model", default="opus")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--limit", type=int, default=None, help="first N survivors only")
    ap.add_argument("--mutants", default=None, help="comma-separated ids, e.g. M03,M26")
    ap.add_argument("--timeout-s", type=int, default=1800)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if shutil.which("claude") is None:
        print("error: the `claude` CLI is required for model runs", file=sys.stderr)
        return 2

    fixture_dir = EVAL_DIR / "fixtures" / args.fixture
    print("taking the census (no model)…", file=sys.stderr)
    counted = census(fixture_dir, args.module, args.python)
    survivors = [m for m in counted["detail"]
                 if not m["killed_by_suite"] and m["behaviour_changed"]]
    if args.mutants:
        wanted = {s.strip() for s in args.mutants.split(",")}
        survivors = [m for m in survivors if m["id"] in wanted]
    if args.limit:
        survivors = survivors[:args.limit]
    print(f"{counted['mutants']} mutants · {counted['killed_by_suite']} killed by the "
          f"suite · {counted['equivalent']} equivalent · {counted['survivors']} survivors; "
          f"running {len(survivors)}", file=sys.stderr)

    base_env = dict(os.environ)
    runs = [run_one(m, fixture_dir, args.module, args, base_env) for m in survivors]
    scored = [r for r in runs if "error" not in r]
    caught = [r for r in scored if r["caught"]]
    summary = {
        "fixture": args.fixture, "module": args.module, "model": args.model,
        "census": {k: counted[k] for k in
                   ("mutants", "killed_by_suite", "equivalent", "survivors")},
        "run": len(runs), "scored": len(scored), "caught": len(caught),
        "recall": round(len(caught) / len(scored), 3) if scored else None,
        "other_findings_total": sum(len(r.get("other_findings", [])) for r in scored),
        "note": ("recall is over survivors only — mutants the suite already kills are "
                 "excluded, as are equivalent mutants. `other_findings` are findings on a "
                 "module whose only defect is the planted one: candidate false positives, "
                 "listed for a human to judge rather than counted automatically"),
        "runs": runs,
    }
    text = json.dumps(summary, indent=2)
    (args.out.write_text(text + "\n", encoding="utf-8") if args.out else print(text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
