"""A finding's identity: the next free id, the anchors and the hash that let a later run
recognise the same defect, and the fields a finding is introduced with.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

try:
    from .anchors import anchors_for
    from .state import is_open
    from .harness_common import _git
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anchors import anchors_for
    from state import is_open
    from harness_common import _git


_LINE_NUMBERS = re.compile(r"\d+")


_WS = re.compile(r"\s+")


_FID = re.compile(r"^(?:(?P<prefix>.+)-)?F-(?P<n>\d+)$")


_SHA = re.compile(r"(?<![0-9a-zA-Z])[0-9a-f]{7,40}(?![0-9a-zA-Z])")


def next_finding_id(key: str, previous: dict | None, ledger: dict | None) -> str:
    """The id the next NEW finding takes: one past the highest ever minted for
    this project, in the state or in the outcome ledger (a finding resolved
    runs ago is gone from the state, and §6 forbids reusing its number). The
    prefix is the one the project already uses — none, when its ids have none
    (`F-162`) — or the key upper-cased on a first run; zero-padding is kept
    when the project pads (`PRICER-F-003`).

    Measured on the Sales shadow run (2026-09-18): the pattern required a
    prefix, so not one of Sales' 75 ids matched, and the first local night
    minted `SALES-F-1` beside `F-162` — a second numbering in one record.

    `ledger` is the rows `load_outcomes` returns, keyed by hash — or the file's own
    `{"findings": rows}`. Only the second shape was read, and every caller passes
    the first, so an id that lived on only in the ledger could be minted again: the
    fate of every hygiene finding a run after it resolves."""
    ids = [f.get("id") for f in (previous or {}).get("findings") or [] if isinstance(f, dict)]
    rows = ledger if isinstance(ledger, dict) else {}
    if isinstance(rows.get("findings"), dict):
        rows = rows["findings"]
    ids += [row.get("id") for row in rows.values() if isinstance(row, dict)]
    prefixes: dict = {}
    top, width = 0, 0
    for fid in ids:
        m = _FID.match(str(fid or ""))
        if not m:
            continue
        prefixes[m["prefix"] or ""] = prefixes.get(m["prefix"] or "", 0) + 1
        n = int(m["n"])
        if n > top:
            top, width = n, (len(m["n"]) if m["n"].startswith("0") else 0)
    prefix = max(prefixes, key=prefixes.get) if prefixes else str(key).upper()
    head = f"{prefix}-F-" if prefix else "F-"
    return f"{head}{top + 1:0{width}d}" if width else f"{head}{top + 1}"


def _earlier_hygiene(ledger, taken: set) -> list:
    """The hygiene findings the outcome ledger remembers under an identity, for an id
    this run neither holds nor has filed: a key resolved two runs ago, or before
    `hygiene: off`, or in a state since restored from state.json.prev, is gone from
    the state but not from the ledger, and comes back as the same finding."""
    wrapped = isinstance(ledger, dict) and isinstance(ledger.get("findings"), dict)
    rows = ledger["findings"] if wrapped else (ledger if isinstance(ledger, dict) else {})
    return [row for row in rows.values()
            if isinstance(row, dict) and row.get("source") == "hygiene"
            and isinstance(row.get("hygiene_identity"), str) and row.get("id")
            and str(row["id"]) not in taken]


def _anchor_texts(finding: dict) -> list[str]:
    """The strings whose `path:line` references get anchored: the evidence and
    the class's sites — the places the finding says the defect lives."""
    rc = finding.get("root_cause") if isinstance(finding.get("root_cause"), dict) else {}
    cls = rc.get("class") if isinstance(rc.get("class"), dict) else {}
    sites = cls.get("sites") if isinstance(cls.get("sites"), list) else []
    return [str(e) for e in (finding.get("evidence") or [])] + [str(x) for x in sites]


def _anchor(entry: dict, prior: dict | None, repo: Path, run_number) -> None:
    """Anchor the finding's cited lines — fresh when its evidence is new,
    carried when the evidence is the text the anchors were taken from.
    Carrying is what lets drift accumulate: an anchor dates from when the
    evidence was written, so "moved since" means since the tester last looked
    at that code, not since last night."""
    texts = _anchor_texts(entry)
    if prior and prior.get("anchors") and _anchor_texts(prior) == texts:
        entry["anchors"] = prior["anchors"]
        if prior.get("anchored_at_run") is not None:
            entry["anchored_at_run"] = prior["anchored_at_run"]
        return
    entry["anchors"] = anchors_for(repo, texts)
    entry["anchored_at_run"] = run_number


def _suggest_tests(entry: dict, facts: dict) -> None:
    """The tests coverage says executed this finding's cited lines and stayed
    green — computed by the harness, never a claim, and never a guard: a test
    that runs the defect without failing is the assertion to look at, and the
    place a regression test belongs."""
    ex = (facts.get("exercised_by") or {}).get(str(entry.get("id") or ""))
    entry.pop("exercised_by_tests", None)
    if isinstance(ex, dict) and ex.get("tests") and is_open(entry):
        entry["exercised_by_tests"] = list(ex["tests"])


def _introduce(entry: dict, prior: dict | None, repo: Path | None) -> None:
    """`introduced_at`: the date of the commit `root_cause.origin` names,
    resolved by git — the finding's other time axis, so dwell time
    (introduction → detection) is a number the report prints. Carried while
    the origin text is unchanged; absent when the origin names no commit this
    repository has. Never derived from `first_seen`: detection is not
    introduction, and a guessed date on this axis would be the kind of
    plausible number the harness exists to refuse."""
    rc = entry.get("root_cause") if isinstance(entry.get("root_cause"), dict) else {}
    origin = rc.get("origin")
    prc = (prior or {}).get("root_cause") if isinstance((prior or {}).get("root_cause"), dict) else {}
    if prior and prior.get("introduced_at") and origin == prc.get("origin"):
        entry["introduced_at"] = prior["introduced_at"]
        if prior.get("introduced_sha"):
            entry["introduced_sha"] = prior["introduced_sha"]
        return
    if not isinstance(origin, str) or repo is None:
        return
    for m in _SHA.finditer(origin):
        if _git(["cat-file", "-t", m.group(0)], repo) != "commit":
            continue
        when = _git(["show", "-s", "--format=%cI", m.group(0)], repo)
        full = _git(["rev-parse", m.group(0)], repo)
        if when and full:
            entry["introduced_at"] = when[:10]
            entry["introduced_sha"] = full
            return


def finding_hash(finding: dict) -> str:
    """Stable identity: cited path + normalized title, line numbers stripped.

    Deliberately not the id: ids are minted once for humans, hashes recognise
    the same finding across runs while line numbers move underneath it.
    """
    if finding.get("hash"):
        return str(finding["hash"])
    evidence = " ".join(str(e) for e in (finding.get("evidence") or []))
    m = re.search(r"([A-Za-z0-9_./-]+\.[A-Za-z]{1,5})", evidence)
    path = m.group(1) if m else ""
    title = _WS.sub(" ", _LINE_NUMBERS.sub("", str(finding.get("title", "")))).strip().lower()
    return hashlib.sha256(f"{path}|{title}".encode()).hexdigest()[:8]
