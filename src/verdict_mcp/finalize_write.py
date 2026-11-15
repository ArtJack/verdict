"""Writing the run's record: state.json, the index row, the hygiene ledger rows, and the
check that every artifact a run must leave is there.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .hygiene import is_hygiene
    from .state import (OUTCOMES_FILE, is_open, load_chain_anchor, load_outcomes, merge_outcomes,
                        RUNS_FILE, chain_link, history_row, load_runs, next_revision)
    from .validate import validate
    from .harness_common import HYGIENE_LEDGER_FILE, _atomic_write, _read_json
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene import is_hygiene
    from state import (OUTCOMES_FILE, is_open, load_chain_anchor, load_outcomes, merge_outcomes,
                       RUNS_FILE, chain_link, history_row, load_runs, next_revision)
    from validate import validate
    from harness_common import HYGIENE_LEDGER_FILE, _atomic_write, _read_json


def index_row(state: dict) -> str:
    t = state.get("tests") or {}
    counts = f"{t.get('passed', 'n/a')} / {t.get('skipped', 'n/a')} / {t.get('failed', 'n/a')}"
    sev = {}
    for f in state.get("findings", []):
        if is_open(f):
            sev[f.get("severity")] = sev.get(f.get("severity"), 0) + 1
    bcmm = "/".join(str(sev.get(s, 0)) for s in ("Blocker", "Critical", "Major", "Minor"))
    report = str((state.get("last_run") or {}).get("report") or "")
    name = Path(report).name
    # Measured, not composed. The Date cell came from the local clock while every
    # other stamp in the run is UTC, so a row written after 17:00 on a UTC-7 host
    # carried yesterday's date permanently — run 4 of this repository reads
    # 09-01 against a state stamped 09-02T04:44Z. And the Δ-tests cell was the
    # literal "n/a" whatever the set-diff had measured (VERDICT-F-24).
    stamp = str((state.get("last_run") or {}).get("timestamp_utc") or "")
    day = stamp[:10] if len(stamp) >= 10 else "n/a"
    ids = state.get("test_ids") or {}
    if ids.get("status") == "measured":
        delta = (f"+{ids.get('added_count', len(ids.get('added', [])))}/"
                 f"−{ids.get('removed_count', len(ids.get('removed', [])))}")
    else:
        delta = "n/a"
    return (f"| {day} | {state['project']} | {state['run_type']} "
            f"| {state['verdict']} | {counts} | {delta} | {bcmm} | [{name}]({report}) |")


INDEX_HEADER = ("| Date | Project | Run type | Verdict | Tests (pass/skip/fail) | Δ tests "
                "| Findings (B/C/M/m) | Report |\n|---|---|---|---|---|---|---|---|")


def write_state(qa_root: Path, state: dict) -> list[str]:
    """Validate, then write: state.json.prev, state.json, and the INDEX row.

    Validation happens here because the PostToolUse hook matches Write/Edit and
    would never see a file a shell command wrote. An invalid state is not
    written at all — prevention beats notification.
    """
    # The ledger `merge` folded travels on the state under a private key —
    # taken off before anything serialises it, because reusing that result is
    # what keeps the persisted ledger and the state's own calibration block
    # describing the same run, and a leading underscore is not a licence to
    # write internals into the artifact.
    ledger = state.pop("_ledger", None)
    problems = validate(state, qa_root, _read_json(qa_root / "state.json"))
    if problems:
        return problems
    if ledger is None:
        decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] or None
        ledger = merge_outcomes(load_outcomes(qa_root), state.get("findings", []), decided_on)

    # Atomic replace, not a bare write. A crash between truncate and flush
    # leaves the file the whole system pivots on half-written, and §6 already
    # carries a rule for recovering from a corrupt state — cheaper to make it
    # near-impossible than to handle it well.
    _atomic_write(qa_root / "state.json.prev",
                  (qa_root / "state.json").read_text(encoding="utf-8")) \
        if (qa_root / "state.json").is_file() else None
    # The chain link is computed before the state is written, because the state
    # records it: a state that names a link the history does not carry is how a
    # copied literal used to pass. history_row() does not read last_run.chain,
    # so stamping it here cannot change the row the link signs.
    prior, _ = load_runs(qa_root)
    # The correction generation is stamped before the link is computed, because
    # the link signs it: a correction is a new row with new content, and signing
    # it identically to the row it supersedes would make the two rows
    # indistinguishable to the chain.
    row = history_row(state, next_revision(qa_root, state.get("run_number")))
    earlier = [r for r in prior
               if isinstance(r.get("run_number"), int)
               and r["run_number"] < (state.get("run_number") or 0)]
    prev = str(earlier[-1].get("chain") or "") if earlier else ""
    row["chain"] = chain_link(prev, row)
    state.setdefault("last_run", {})["chain"] = row["chain"]

    _write_hygiene_rows(qa_root, state)
    _atomic_write(qa_root / "state.json", json.dumps(state, indent=2) + "\n")
    # The chain's ratchet lives here rather than in the history it guards: a
    # signal a fabricator can shed by deleting one file is not a signal
    # (VERDICT-F-21). Shedding it now means destroying the permanent track
    # record too, which the next report says out loud.
    anchor = load_chain_anchor(qa_root)
    _atomic_write(qa_root / OUTCOMES_FILE,
                  json.dumps({"schema_version": 1, "project": state.get("project"),
                              "chain": {"since_run": anchor.get("since_run")
                                        or state.get("run_number"),
                                        "last_link": row["chain"]},
                              "findings": ledger}, indent=2, sort_keys=True) + "\n")

    # One machine-native line per run. Appended, not rewritten: the file is
    # history, and the tolerant reader (state.load_runs) skips a torn trailing
    # line rather than dying on it.
    with (qa_root / RUNS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

    reports = qa_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    index = reports / "INDEX.md"
    if index.is_file():
        body = index.read_text(encoding="utf-8").rstrip("\n")
    else:
        body = f"# QA run index — {state['project']}\n\n{INDEX_HEADER}"
    _atomic_write(index, body + "\n" + index_row(state) + "\n")
    return []


def _ignored_hygiene_ids(judgment: dict, previous: dict | None) -> list[str]:
    """The hygiene findings a judgment named, which merge passed over: an id of the
    previous state's in `still_open` or `resolved`, or a finding marked as one."""
    theirs = {str(f.get("id")) for f in ((previous or {}).get("findings") or [])
              if is_hygiene(f) and f.get("id")}
    named = {str(x) for verb in ("still_open", "resolved")
             for x in (judgment.get(verb) if isinstance(judgment.get(verb), list) else [])
             if str(x) in theirs}
    copies = {str(f.get("id")) for f in (judgment.get("findings") or [])
              if is_hygiene(f) and f.get("id")}
    return sorted(named | copies)


def _write_hygiene_rows(qa_root: Path, state: dict) -> None:
    """Move the junk ledger's rows out of the state into `hygiene-ledger.json`, with
    the run that wrote them — the state keeps the counts and the preview, and the
    tester, who reads state.json first on every run, no longer reads 119 rows of junk
    (Sales). Called once the state is accepted, so a refused run leaves last run's
    rows in place. A file that cannot be written costs the run nothing: the rows stay
    in the state, where the next run reads them, and `rows_note` says why."""
    block = state.get("hygiene")
    if not isinstance(block, dict) or not isinstance(block.get("rows"), list):
        return
    doc = {"schema": 1, "run_number": state.get("run_number"), "rows": block["rows"]}
    try:
        _atomic_write(Path(qa_root) / HYGIENE_LEDGER_FILE, json.dumps(doc, indent=1) + "\n")
    except OSError as exc:
        block["rows_note"] = (f"{HYGIENE_LEDGER_FILE} could not be written "
                              f"({exc.strerror or type(exc).__name__}): the rows stay here")
        return
    block.pop("rows_note", None)
    del block["rows"]
    block["rows_file"] = HYGIENE_LEDGER_FILE


def check_artifacts(qa_root: Path, state: dict) -> list[str]:
    """Re-read what finalize just wrote and make the four artifacts agree.

    Run 4 of this repository found two harness defects — a state re-keyed to
    the directory name, an INDEX row dated from the local clock — not by
    reading source but by reading its own artifacts back and comparing them:
    the state, the INDEX row, the runs.jsonl row and the report describe one
    run and must agree, and where they disagree the harness composed a value
    instead of measuring it. That was the agent's discipline; this is the
    harness's. Every check reads from disk, not from the objects in memory,
    because "what did we mean to write" is the question the lesson warns
    against.
    """
    problems: list[str] = []
    root = Path(qa_root)
    run = state.get("run_number")
    last = state.get("last_run") or {}

    on_disk = _read_json(root / "state.json") or {}
    if on_disk.get("run_number") != run or on_disk.get("verdict") != state.get("verdict"):
        problems.append(f"state.json on disk (run {on_disk.get('run_number')}, verdict "
                        f"{on_disk.get('verdict')!r}) is not the state just written "
                        f"(run {run}, verdict {state.get('verdict')!r})")

    rows, _ = load_runs(root)
    row = rows[-1] if rows else {}
    if row.get("run_number") != run:
        problems.append(f"runs.jsonl ends at run {row.get('run_number')}, the state says {run}")
    else:
        if row.get("chain") != last.get("chain"):
            problems.append("runs.jsonl's last link is not the one last_run.chain records")
        if row.get("verdict") != state.get("verdict"):
            problems.append(f"runs.jsonl records verdict {row.get('verdict')!r}, the state "
                            f"says {state.get('verdict')!r}")

    index = root / "reports" / "INDEX.md"
    lines = [ln for ln in index.read_text(encoding="utf-8").splitlines()
             if ln.startswith("| ") and not ln.startswith("| Date")] if index.is_file() else []
    cells = [c.strip() for c in lines[-1].strip().strip("|").split("|")] if lines else []
    stamp = str(last.get("timestamp_utc") or "")[:10]
    if not cells:
        problems.append("INDEX.md has no run row")
    else:
        if cells[0] != stamp:
            problems.append(f"INDEX row is dated {cells[0]}, the state was measured {stamp}")
        if len(cells) > 1 and cells[1] != str(state.get("project")):
            problems.append(f"INDEX row names project {cells[1]!r}, the state says "
                            f"{state.get('project')!r}")
        if len(cells) > 3 and cells[3] != str(state.get("verdict")):
            problems.append(f"INDEX row records verdict {cells[3]!r}, the state says "
                            f"{state.get('verdict')!r}")

    report = str(last.get("report") or "")
    if not report or not (root / report).is_file():
        problems.append(f"the report the state names ({report or 'none'}) is not on disk")
    elif cells and Path(report).name not in lines[-1]:
        problems.append(f"INDEX row does not link the report the state names ({Path(report).name})")
    return problems
