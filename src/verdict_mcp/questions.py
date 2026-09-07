#!/usr/bin/env python3
"""verdict-answer — the maintainer's second pen, and the questions it answers.

A run ends with things only a person can decide: is `;` still a query
separator, is single-file vendoring a supported contract, should the gate run
an installed wheel. They used to live in the closing handoff and in prose, so
the next run asked them again — one was carried for seven runs, boltons parked
four in its profile where no reader would find them.

Two files, one pen each. `questions.json` is written by `verdict-finalize` and
nobody else: every question a judgment asks, with an id minted once
(`<PROJECT>-Q-<n>`), the run that asked it, and its status. `answers.json` is
written by `verdict-answer` and nobody else — the scope guards refuse it to
the tester, as they refuse `accepted.json` — and finalize folds each answer
into the question it answers. The next `verdict-facts` lists what is parked
and what was answered since the last run, so a decision is read, not re-asked;
the report renders "Needs human decision" from the ledger; the session-start
banner and `verdict-gate` say how many are waiting.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

try:
    from . import clock
    from .state import load_state
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from state import load_state

QUESTIONS_FILE = "questions.json"
ANSWERS_FILE = "answers.json"
MIN_TEXT = 12
_QID = re.compile(r"^(?P<prefix>.+)-Q-(?P<n>\d+)$")
_WS = re.compile(r"\s+")


# ── the tester's ledger (finalize's pen) ────────────────────────────────────

def load_questions(qa_root) -> dict:
    """The whole ledger; missing or corrupt reads as empty."""
    try:
        data = json.loads((Path(qa_root) / QUESTIONS_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {"schema_version": 1, "questions": {}}
    if not isinstance(data, dict) or not isinstance(data.get("questions"), dict):
        return {"schema_version": 1, "questions": {}}
    data["questions"] = {str(k): v for k, v in data["questions"].items() if isinstance(v, dict)}
    return data


def load_answers(qa_root) -> dict:
    """The maintainer's answers keyed by question id; missing or corrupt reads
    as empty — a lost file answers nothing, it does not fail a run."""
    try:
        data = json.loads((Path(qa_root) / ANSWERS_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    rows = data.get("answers") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {str(k): v for k, v in rows.items() if isinstance(v, dict)}


def normalize(text) -> str:
    return _WS.sub(" ", str(text or "")).strip().strip(".?!").lower()


_FID = re.compile(r"^(?P<prefix>.+)-F-\d+$")


def id_prefix(findings, project: str) -> str:
    """The prefix this project's finding ids use (`PRICER` in `PRICER-F-3`),
    so a question reads `PRICER-Q-1` beside them; the key, upper-cased, on a
    project that has no findings yet."""
    prefixes: dict = {}
    for f in findings or []:
        m = _FID.match(str((f or {}).get("id") or "")) if isinstance(f, dict) else None
        if m:
            prefixes[m["prefix"]] = prefixes.get(m["prefix"], 0) + 1
    return max(prefixes, key=prefixes.get) if prefixes else str(project).upper()


def next_qid(prefix: str, ledger: dict) -> str:
    top = 0
    for qid in ledger.get("questions") or {}:
        m = _QID.match(str(qid))
        if m:
            top = max(top, int(m["n"]))
    return f"{prefix}-Q-{top + 1}"


def _age(asked_on, today: date):
    try:
        return (today - date.fromisoformat(str(asked_on)[:10])).days
    except (TypeError, ValueError):
        return None


def _write(qa_root, ledger: dict) -> None:
    path = Path(qa_root) / QUESTIONS_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _fold_answers(ledger: dict, answers: dict) -> None:
    for qid, a in answers.items():
        q = ledger["questions"].get(qid)
        if not q:
            continue
        q["status"] = "dismissed" if a.get("dismissed") else "answered"
        for k in ("answer", "reason", "by", "on"):
            if a.get(k) is not None:
                q[k] = a[k]


def view(ledger: dict, today: date) -> dict:
    """What a reader needs: the parked questions with their age, and the
    answers no run has acknowledged yet."""
    parked, fresh = [], []
    for qid, q in ledger.get("questions", {}).items():
        row = {"id": qid, "question": q.get("question"), "finding": q.get("finding"),
               "asked_on": q.get("asked_on"), "asked_at_run": q.get("asked_at_run")}
        if q.get("context"):
            row["context"] = q["context"]
        if q.get("status", "parked") == "parked":
            age = _age(q.get("asked_on"), today)
            if age is not None:
                row["age_days"] = age
            parked.append(row)
        elif q.get("acknowledged_at_run") is None:
            fresh.append({**row, "status": q.get("status"), "answer": q.get("answer"),
                          "reason": q.get("reason"), "by": q.get("by"), "on": q.get("on")})
    return {"parked": parked, "answered_since_last_run": fresh}


def facts_view(qa_root, today: date) -> dict | None:
    """For `verdict-facts`: the ledger with the answers folded in, read-only —
    None when the project has never asked a question."""
    ledger = load_questions(qa_root)
    if not ledger["questions"]:
        return None
    _fold_answers(ledger, load_answers(qa_root))
    out = view(ledger, today)
    out["ledger"] = str(Path(qa_root) / QUESTIONS_FILE)
    return out


def fold(qa_root, prefix: str, asked, run_number, today: date) -> tuple[dict, list[str]]:
    """finalize's step: mint this run's questions, fold the answers, acknowledge
    them, write the ledger → (view for the state, notes). `prefix` is the
    project's finding-id prefix (see `id_prefix`)."""
    ledger = load_questions(qa_root)
    notes = []
    _fold_answers(ledger, load_answers(qa_root))
    existing = {normalize(q.get("question")): qid for qid, q in ledger["questions"].items()}
    for item in asked or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("question") or "").strip()
        key = normalize(text)
        if not key:
            continue
        if key in existing:
            notes.append(f"question already on the ledger as {existing[key]} — not re-asked")
            continue
        qid = next_qid(prefix, ledger)
        entry = {"question": text, "status": "parked", "asked_on": today.isoformat(),
                 "asked_at_run": run_number}
        for k in ("context", "finding", "options"):
            if item.get(k):
                entry[k] = item[k]
        ledger["questions"][qid] = entry
        existing[key] = qid
    out = view(ledger, today)
    for row in out["answered_since_last_run"]:
        ledger["questions"][row["id"]]["acknowledged_at_run"] = run_number
    if ledger["questions"]:
        _write(qa_root, ledger)
    return out, notes


# ── the maintainer's pen ────────────────────────────────────────────────────

def _who() -> str:
    try:
        out = subprocess.run(["git", "config", "user.name"], capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("USER") or os.environ.get("USERNAME") or "maintainer"


def read_answers_file(root: Path) -> dict:
    """The whole file — this command edits it, so a corrupt one is an error,
    not the empty dict the readers use."""
    path = Path(root) / ANSWERS_FILE
    if not path.is_file():
        return {"schema_version": 1, "answers": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise ValueError(f"{path} is not an answers ledger")
    return data


def write_answers_file(root: Path, data: dict) -> None:
    path = Path(root) / ANSWERS_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def answer(root: Path, qid: str, text: str, by: str, today: str,
           dismiss: bool = False) -> tuple[int, str]:
    ledger = load_questions(root)
    q = ledger["questions"].get(qid)
    if q is None:
        return 2, (f"no question {qid!r} in {Path(root) / QUESTIONS_FILE} — "
                   "`verdict-answer <project> --list` shows the parked ones")
    if len((text or "").strip()) < MIN_TEXT:
        flag = "--reason" if dismiss else "--answer"
        return 2, (f"{flag} needs a real {flag[2:]}, not {text!r} — a decision "
                   "the next run cannot read is not a decision")
    data = read_answers_file(root)
    prior = data["answers"].get(qid)
    if prior:
        return 2, (f"{qid} was already {'dismissed' if prior.get('dismissed') else 'answered'} "
                   f"on {prior.get('on')} by {prior.get('by')}; edit {ANSWERS_FILE} by hand "
                   "to change the record — it is yours")
    entry = {"by": by, "on": today}
    if dismiss:
        entry["dismissed"] = True
        entry["reason"] = text.strip()
    else:
        entry["answer"] = text.strip()
    data["answers"][qid] = entry
    write_answers_file(root, data)
    verb = "dismissed" if dismiss else "answered"
    return 0, (f"{verb} {qid} — by {by} on {today}\n"
               f"  question: {q.get('question')}\n"
               f"  ledger: {Path(root) / ANSWERS_FILE}\n"
               "  effect: the next run reads the decision instead of asking again")


def listing(root: Path, today: date) -> str:
    ledger = load_questions(root)
    if not ledger["questions"]:
        return f"no questions on the ledger ({Path(root) / QUESTIONS_FILE})"
    _fold_answers(ledger, load_answers(root))
    lines = []
    for qid, q in ledger["questions"].items():
        status = q.get("status", "parked")
        age = _age(q.get("asked_on"), today)
        head = f"{qid:14} {status:10} asked run {q.get('asked_at_run')}"
        head += f", {age}d ago" if age is not None else ""
        if q.get("finding"):
            head += f" · about {q['finding']}"
        lines.append(head)
        lines.append(f"{'':14} {q.get('question')}")
        if status != "parked":
            lines.append(f"{'':14} → {q.get('answer') or q.get('reason')} "
                         f"({q.get('by')}, {q.get('on')})")
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # the Windows cp1252 trap, every CLI
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        prog="verdict-answer",
        description="Answer a question the tester parked — the maintainer's pen; "
                    "the next run reads the decision instead of asking again.")
    ap.add_argument("project", help="solo project key, or a repository path (team mode)")
    ap.add_argument("question", nargs="?", help="the question id, e.g. PRICER-Q-2")
    ap.add_argument("--answer", default="", metavar="TEXT", help="the decision, in a sentence or two")
    ap.add_argument("--dismiss", action="store_true",
                    help="close the question without deciding; needs --reason")
    ap.add_argument("--reason", default="", metavar="TEXT", help="why it is dismissed")
    ap.add_argument("--by", default=None, metavar="NAME",
                    help="who decides (default: git config user.name)")
    ap.add_argument("--list", action="store_true", help="print the ledger and stop")
    ap.add_argument("--today", default=None, help=argparse.SUPPRESS)   # test seam
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-answer: {err['error']}", file=sys.stderr)
        return 4
    root = Path(state["_qa_root"])
    today = args.today or clock.today().isoformat()
    try:
        if args.list:
            print(listing(root, date.fromisoformat(today)))
            return 0
        if not args.question:
            print("verdict-answer: a question id is required (or --list)", file=sys.stderr)
            return 2
        if args.dismiss and args.answer:
            print("verdict-answer: --dismiss takes --reason, not --answer", file=sys.stderr)
            return 2
        code, msg = answer(root, args.question, args.reason if args.dismiss else args.answer,
                           args.by or _who(), today, dismiss=args.dismiss)
    except ValueError as exc:
        print(f"verdict-answer: {exc}", file=sys.stderr)
        return 2
    print(("verdict-answer: " if code else "") + msg, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
