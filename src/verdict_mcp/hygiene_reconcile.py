"""The ledger finalize keeps: reconciling this run's rows with the filed findings, what carries
and what resolves, and the ledger's rows and summary.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

try:
    from .hygiene_const import LEDGER_CAP, PREVIEW_ROWS, SEVERITY, TIER2_KINDS, TITLE
    from .hygiene_evidence import Evidence, _ID_NUMBER, _identity, _paths, is_hygiene
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import LEDGER_CAP, PREVIEW_ROWS, SEVERITY, TIER2_KINDS, TITLE
    from hygiene_evidence import Evidence, _ID_NUMBER, _identity, _paths, is_hygiene


def _filed_first(f) -> tuple:
    """Which of two findings with one identity came first: first seen, then the
    lower id number."""
    m = _ID_NUMBER.search(str(f.get("id") or ""))
    return (str(f.get("first_seen") or "9999"), int(m.group(1)) if m else 1 << 62, str(f.get("id")))


def _open(f) -> bool:
    return str(f.get("status") or "open").strip().lower() not in ("resolved", "withdrawn")


def _age(first_seen: str, today: str) -> int:
    try:
        return (date.fromisoformat(today) - date.fromisoformat(str(first_seen))).days
    except ValueError:
        return 0


def _tier1_row(it) -> bool:
    """A tier-1 item in the shape the scan writes one."""
    return (isinstance(it, dict) and type(it.get("tier")) is int and it["tier"] == 1
            and it.get("kind") in SEVERITY and isinstance(it.get("path"), str)
            and type(it.get("line")) is int
            and all(isinstance(it.get(field), str) for field in ("fingerprint", "excerpt")))


def reconcile(facts_hygiene, prior_findings, mint, today: str, run_number, sha: str,
              evidence=None, earlier=None) -> list:
    """Tier-1 items → findings with a lifecycle, owned by the harness. One seen again
    keeps its id — REGRESSED if it had been resolved; a prior one not seen resolves
    only on `evidence` (Evidence) and is otherwise carried open. `mint` gives a NEW
    finding its id.

    `earlier` holds the hygiene findings the outcome ledger remembers and the state no
    longer holds — resolved two or more runs ago, or before `hygiene: off`, or lost to
    a restored state.json.prev — as {id, hash, first_seen, hygiene_identity}. One seen
    again is REGRESSED under its old id, so what the maintainer accepted under that id
    still applies. Two open findings with one identity are folded into the one filed
    first; the other resolves as superseded by it."""
    fh = facts_hygiene if isinstance(facts_hygiene, dict) else {}
    ev = evidence if isinstance(evidence, Evidence) else Evidence()
    prior, folded = _priors(prior_findings, earlier)
    superseded = [_resolved(p, f"superseded by {kept['id']}", today, run_number) for p, kept in folded]
    if fh.get("status") not in ("measured", "partial"):
        # Nothing measured this run: carry what was open unchanged rather than resolve
        # by silence — the rule the tester's own findings live under.
        return [_carried(p, "the hygiene scan was unavailable this run", today)
                for p in prior.values() if _open(p)] + superseded
    filing = fh.get("filing", "on") == "on"
    out, seen = [], set()
    for it in (fh.get("items") or []) if filing else []:
        if not _tier1_row(it) or _identity(it) in seen:
            continue
        seen.add(_identity(it))
        out.append(_filed(it, prior.get(_identity(it)), mint, today, run_number))
    unseen = [p for key, p in prior.items() if key not in seen and _open(p)]
    if not filing:
        return out + [_resolved(p, "hygiene filing is off in the profile", today, run_number)
                      for p in unseen] + superseded
    # A key in a file that is now itself a committed secrets file is not gone: the file
    # is the finding, and the line inside it is no longer filed on its own.
    file_level = {e["hygiene"]["path"]: e["id"] for e in out
                  if e["hygiene"]["kind"] == "secret_file_tracked"}
    whys = ev.carries([(p["hygiene"].get("kind"), _paths(p["hygiene"])) for p in unseen])
    for p, why in zip(unseen, whys):
        path = p["hygiene"].get("path")
        if why:
            out.append(_carried(p, why, today))
        elif p["hygiene"].get("kind") == "secret_in_code" and path in file_level:
            out.append(_resolved(p, f"superseded by the file-level finding {file_level[path]}",
                                 today, run_number))
        else:
            out.append(_resolved(p, f"no longer detected at {str(sha)[:8]}", today, run_number))
    return out + superseded


def _priors(prior_findings, earlier) -> tuple:
    """The prior findings by identity, and the open ones folded into another with the
    same identity, as (folded, kept). The state's own come first — an open one over a
    resolved one — then what only the outcome ledger remembers, as resolved."""
    prior: dict = {}
    folded = []
    for f in prior_findings or []:
        if not (is_hygiene(f) and isinstance(f.get("hygiene"), dict)):
            continue
        key = _identity(f["hygiene"])
        held = prior.get(key)
        if held is None or (_open(f) and not _open(held)):
            prior[key] = f
        elif _open(f) and _open(held):
            keep, drop = sorted((held, f), key=_filed_first)
            prior[key] = keep
            folded.append((drop, keep))
    for row in sorted((r for r in earlier or [] if isinstance(r, dict)), key=_filed_first):
        key = row.get("hygiene_identity")
        if isinstance(key, str) and key and row.get("id") and key not in prior:
            prior[key] = {"id": row["id"], "source": "hygiene", "status": "resolved",
                          "hash": row.get("hash"), "first_seen": row.get("first_seen"),
                          "hygiene": {"identity": key}}
    return prior, folded


def _filed(it, p, mint, today: str, run_number) -> dict:
    kind, fp, path, line = it["kind"], it["fingerprint"], it["path"], it["line"]
    sev = SEVERITY[kind]
    first_seen = (p or {}).get("first_seen") or today
    was = str((p or {}).get("status") or "").strip().lower()
    hyg = {"kind": kind, "fingerprint": fp, "path": path, "identity": _identity(it)}
    if isinstance(it.get("variable"), str) and it["variable"]:
        hyg["variable"] = it["variable"]
    if isinstance(it.get("sites"), list):
        hyg["sites"] = [s for s in it["sites"] if isinstance(s, str) and s]
    entry = {
        "id": (p or {}).get("id") or mint(),
        "source": "hygiene",
        "hygiene": hyg,
        "title": f"{TITLE[kind]} — {path}:{line}",
        "severity": sev, "priority": "P1" if sev == "Critical" else "P3",
        "status": "open", "failure_classification": None, "confidence": "proven",
        "evidence": [f"{path}:{line} — {it['excerpt']}",
                     "measured by the hygiene scan in verdict-facts and filed by "
                     "verdict-finalize, not by the tester"],
        # A client-side variable's fingerprint moves with its site; its identity, and
        # the hash the outcome ledger keys on, do not.
        "hash": (p or {}).get("hash") or "hygiene:" + fp,
        "first_seen": first_seen, "age_days": _age(first_seen, today),
        "delta": "NEW" if p is None else ("REGRESSED" if was == "resolved" else "STILL_OPEN"),
    }
    if entry["delta"] == "REGRESSED":
        entry["regressed_at_run"] = run_number
    elif (p or {}).get("regressed_at_run") is not None:
        entry["regressed_at_run"] = p["regressed_at_run"]
    return entry


def _carried(p, why: str, today: str) -> dict:
    return {**{k: v for k, v in p.items() if k != "re_reported"}, "delta": "STILL_OPEN",
            "age_days": _age(p.get("first_seen") or today, today),
            "carried_forward": f"carried open, not resolved: {why}"}


def _resolved(p, reason: str, today: str, run_number) -> dict:
    return {**{k: v for k, v in p.items() if k != "re_reported"},
            "status": "resolved", "delta": "RESOLVED", "carried_forward": reason,
            "resolved_at_run": run_number, "age_days": _age(p.get("first_seen") or today, today)}


def ledger(facts_hygiene, tier2, previous_block, today: str, run_number, sha: str,
           evidence=None) -> dict:
    """Tier-2 items → the junk ledger, keyed by fingerprint, with counts that stay
    exact, and a preview of it (_preview). `tier2` is this run's rows
    (harness.tier2_items): None when the side file holding them could not be read,
    and then no row resolves. A row not seen resolves only on `evidence`, like a
    tier-1 finding, and is otherwise carried.

    `previous_block` holds last run's rows, read back from the file they went to
    (harness.hygiene_previous). One that names that file and holds no rows could not
    be read: nothing is carried forward and nothing resolves — every row this run
    is NEW — and the summary says `prior_unread`."""
    fh = facts_hygiene if isinstance(facts_hygiene, dict) else {}
    ev = evidence if isinstance(evidence, Evidence) else Evidence()
    prev = previous_block if isinstance(previous_block, dict) else {}
    prev_rows = prev.get("rows") if isinstance(prev.get("rows"), list) else None
    prior_unread = prev_rows is None and bool(prev.get("rows_file"))
    first_inventory = prev_rows is None and not prior_unread
    prev_open: dict = {}
    for r in prev_rows or []:
        kept = _prior_row(r)
        if kept is not None:
            prev_open.setdefault(kept["fingerprint"], kept)
    if fh.get("status") not in ("measured", "partial"):
        block = {"status": "unavailable", "reason": fh.get("reason") or (
            "facts.json carries no hygiene scan — measured by a verdict-facts older than 0.91.0")}
        if prev_open or prior_unread:
            # Nothing measured, so nothing is known to be gone: last run's open rows are
            # kept rather than dropped, which would start the next inventory over.
            carried = [_carried_row(r, "the hygiene scan was unavailable this run")
                       for r in prev_open.values()]
            summary = _ledger_summary(_count(carried), [], [], carried, False, False)
            if prior_unread:
                summary["prior_unread"] = True
            block.update(summary=summary, rows=carried, preview=_preview(carried),
                         carried_from_run=prev.get("measured_at_run") or prev.get("carried_from_run"))
        return block
    rows_read = tier2 is not None
    items, seen = [], set()
    for it in tier2 or []:
        if (isinstance(it, dict) and it.get("kind") in TIER2_KINDS
                and isinstance(it.get("fingerprint"), str) and it["fingerprint"] not in seen):
            seen.add(it["fingerprint"])
            items.append(it)
    current = [_ledger_row(it, prev_open.get(it["fingerprint"]), today, run_number) for it in items]
    if rows_read:
        unseen = [r for fp, r in prev_open.items() if fp not in seen]
        whys = ev.carries([(r["kind"], _paths(r)) for r in unseen])
        removed = [{**{k: v for k, v in r.items() if k != "carried_forward"}, "status": "resolved",
                    "delta": "RESOLVED", "resolved_on": today, "resolved_at_run": run_number,
                    "resolved_sha": sha}
                   for r, why in zip(unseen, whys) if why is None]
        carried = [_carried_row(r, why) for r, why in zip(unseen, whys) if why]
        open_by_kind = _count(current + carried)
    else:
        # This run's rows are unknown: none of last run's is resolved, none is new, and
        # the counts are the scan's own, which facts.json still holds.
        removed = []
        carried = [_carried_row(r, "this run's rows could not be read from the side file")
                   for r in prev_open.values()]
        open_by_kind = {k: v for k, v in (fh.get("counts_by_kind") or {}).items()
                        if k in TIER2_KINDS and type(v) is int}
    kept = current + carried
    capped = len(kept) > LEDGER_CAP
    if capped:
        kept = sorted(kept, key=lambda r: r["delta"] == "NEW")[:LEDGER_CAP]
    summary = _ledger_summary(open_by_kind, current, removed, carried, first_inventory, capped)
    if fh.get("status") == "partial":
        summary["partial"] = True
    if not rows_read:
        summary["tier2_unread"] = True
    if prior_unread:
        summary["prior_unread"] = True
    return {"status": "measured", "scope": fh.get("scope"), "measured_at_run": run_number,
            "summary": summary, "rows": kept + removed, "preview": _preview(kept + removed),
            "leads": {"handed": fh.get("leads_total", 0)}}


# What a carried row keeps of last run's: its known fields, whatever else the file held.
_ROW_FIELDS = ("fingerprint", "kind", "path", "line", "excerpt", "status", "delta", "first_seen",
               "first_seen_run", "sites", "carried_forward")
_PREVIEW_FIELDS = ("fingerprint", "kind", "path", "line", "excerpt", "first_seen", "delta")


def _prior_row(r):
    """An open row of last run's ledger, as this run may carry it, or None."""
    if not (isinstance(r, dict) and r.get("status") == "open" and r.get("kind") in TIER2_KINDS
            and isinstance(r.get("fingerprint"), str)):
        return None
    return {k: r[k] for k in _ROW_FIELDS if k in r}


def _preview(rows) -> dict:
    """What the state keeps of the ledger, its rows being in a file of their own: the
    PREVIEW_ROWS open rows first seen longest ago, and the first PREVIEW_ROWS new this
    run in path order — the two lists a reader looks at first."""
    def where(r):
        line = r.get("line")
        return (str(r.get("path") or ""), line if type(line) is int else 0, str(r.get("fingerprint")))

    oldest = sorted((r for r in rows if r.get("status") == "open"),
                    key=lambda r: (str(r.get("first_seen") or ""), *where(r)))
    new = sorted((r for r in rows if r.get("delta") == "NEW"), key=where)
    return {"oldest": [{k: r.get(k) for k in _PREVIEW_FIELDS} for r in oldest[:PREVIEW_ROWS]],
            "new": [{k: r.get(k) for k in _PREVIEW_FIELDS} for r in new[:PREVIEW_ROWS]]}


def _ledger_row(it, p, today: str, run_number) -> dict:
    row = {"fingerprint": it["fingerprint"], "kind": it["kind"], "path": it.get("path"),
           "line": it.get("line"), "excerpt": it.get("excerpt"), "status": "open",
           "delta": "STILL_OPEN" if p else "NEW",
           "first_seen": (p or {}).get("first_seen") or today,
           "first_seen_run": (p or {}).get("first_seen_run") or run_number}
    sites = it.get("sites")
    if isinstance(sites, list) and sites and all(isinstance(s, str) for s in sites):
        row["sites"] = list(sites)
    return row


def _carried_row(r, why: str) -> dict:
    return {**r, "delta": "STILL_OPEN", "carried_forward": why}


def _count(rows) -> dict:
    out: dict = {}
    for r in rows:
        out[r["kind"]] = out.get(r["kind"], 0) + 1
    return out


def _ledger_summary(open_by_kind: dict, current, removed, carried, first_inventory: bool,
                    capped: bool) -> dict:
    kinds = sorted(set(open_by_kind) | {r["kind"] for r in [*current, *removed, *carried]})
    by_kind = {k: {"open": open_by_kind.get(k, 0),
                   "new": sum(1 for r in current if r["kind"] == k and r["delta"] == "NEW"),
                   "resolved": sum(1 for r in removed if r["kind"] == k)} for k in kinds}
    summary = {"open": sum(v["open"] for v in by_kind.values()),
               "new": sum(v["new"] for v in by_kind.values()),
               "resolved": len(removed), "first_inventory": first_inventory, "capped": capped,
               "by_kind": by_kind}
    if carried:
        summary["carried"] = len(carried)
    return summary


_CITE = re.compile(r"([\w./\\-]+\.[A-Za-z0-9_]+):(\d+)")


def leads_followed(leads, findings) -> int:
    """How many leads a finding of the tester's cites within five lines — the running
    precision check on the lead rules."""
    cited = [(m.group(1).replace("\\", "/"), int(m.group(2)))
             for f in findings or [] if isinstance(f, dict) and not is_hygiene(f)
             for e in f.get("evidence") or [] for m in _CITE.finditer(str(e))]
    return sum(1 for lead in leads or []
               if isinstance(lead, dict) and isinstance(lead.get("path"), str)
               and type(lead.get("line")) is int
               and any((p.endswith(lead["path"]) or lead["path"].endswith(p))
                       and abs(n - lead["line"]) <= 5 for p, n in cited))
