"""A finding that already exists, and filing the new ones: the index of prior findings,
regressions, the order chunks are asked in, and the findings filed from the answers.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    from .anchors import line_sha, refs_in
    from .state import norm_status
    from . import languages
    from .local_model import Model
    from .local_chunks import gap_hint
    from .local_candidates import chunks_in_range
    from .local_questions import examine, finding_of
    from .local_probes import counterfactual
    from .local_leads import NO_PROBE
    from .local_budget import Budget
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import languages
    from anchors import line_sha, refs_in
    from state import norm_status
    from local_model import Model
    from local_chunks import gap_hint
    from local_candidates import chunks_in_range
    from local_questions import examine, finding_of
    from local_probes import counterfactual
    from local_leads import NO_PROBE
    from local_budget import Budget


# ── a finding that already exists ─────────────────────────────────────────────


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


# Names too common to say which function a finding meant. A finding that mentions
# `run` has not named the function `run`.
_TOO_COMMON = frozenset({"main", "init", "__init__", "run", "get", "set", "call", "test",
                         "setup", "teardown", "update", "process", "handle", "__call__",
                         "__repr__", "__str__", "__eq__", "__hash__"})


class PriorIndex:
    """Which earlier finding a claim about this function already is.

    Measured on the seeded delta (2026-09-18): the rounding defect the previous run had
    resolved came back, the engine read `round_cents`, described the bug correctly — and
    filed it as a NEW finding, because it minted its own id and never looked at the state
    it was carrying. A regression is the most important thing a nightly can say, and it
    was reported as news. The same blindness filed a second finding for a defect that was
    already open, which on a project with a backlog is a new duplicate every night.

    Two ways to know, strongest first. **The finding's anchors** (0.83.0 hashes every
    line a finding cites): if a line this function holds now has the same hash, it is the
    same code. **The function's name**, when the finding names it — in its title, its
    evidence or its root cause — and cites no other file: an old finding written before
    anchors, or one whose line has been edited. The name is a weaker signal, so a name
    that says nothing (`run`, `main`) never matches, and every match says which signal
    it rested on. Withdrawn findings are the tester's own errors and never match.
    """

    def __init__(self, previous):
        self.entries = []
        for f in (previous or {}).get("findings") or []:
            if not isinstance(f, dict) or not f.get("id"):
                continue
            status = norm_status(f.get("status"))
            if status not in ("open", "accepted", "resolved"):
                continue
            anchors = [a for a in f.get("anchors") or [] if isinstance(a, dict)]
            text = " ".join([str(f.get("title") or "")]
                            + [str(e) for e in f.get("evidence") or []]
                            + [json.dumps(f.get("root_cause") or {})])
            paths = {str(a["path"]) for a in anchors if a.get("path")}
            paths |= {str(path) for path, _line in refs_in([text])}
            shas = {(str(a.get("path")), str(a.get("line_sha")))
                    for a in anchors if a.get("path") and a.get("line_sha")}
            self.entries.append({"finding": f, "status": status, "paths": paths,
                                 "shas": shas, "words": set(_IDENT.findall(text))})

    def match(self, repo: Path, chunk) -> tuple:
        """→ (prior finding, its status, how it was recognised) or (None, None, None)."""
        try:
            lines = (repo / chunk.path).read_bytes().splitlines()[chunk.start - 1:chunk.end]
        except OSError:
            lines = []
        here = {(chunk.path, line_sha(line)) for line in lines if line.strip()}
        for e in self.entries:
            hit = here & e["shas"]
            if hit:
                return e["finding"], e["status"], (
                    f"a line it cited when it was filed is in `{chunk.name}` again, "
                    f"unchanged (line hash {sorted(hit)[0][1]})")
        name = chunk.name
        if len(name) < 4 or name in _TOO_COMMON:
            return None, None, None
        for e in self.entries:
            if name in e["words"] and (not e["paths"] or chunk.path in e["paths"]):
                return e["finding"], e["status"], (
                    f"it names `{name}`, the function this claim is about — matched by "
                    "name, not by line, so read it before trusting the link")
        return None, None, None


def regressed_finding(prior: dict, claim_entry: dict, how: str) -> dict:
    """A resolved finding, back: its own id, so the harness calls it REGRESSED.

    The title is the original's — the id names that finding — and this run's reading
    goes into the evidence beside the reason the two were linked. Severity stays what
    this engine can justify (held at Minor unless a counterfactual proved it): being the
    same bug is measured, how bad it is now is not. No `confidence`: the claim was made
    once, when the finding was first filed, and `merge` keeps that one.
    """
    entry = dict(claim_entry)
    entry.pop("confidence", None)
    entry["id"] = prior["id"]
    entry["title"] = str(prior.get("title") or claim_entry.get("title"))
    entry["evidence"] = [
        f"REGRESSED — {prior['id']} was resolved, and this run found it again: {how}.",
        f"this run's reading: {claim_entry.get('title')}",
    ] + list(claim_entry.get("evidence") or [])
    return entry


def focus_names(facts: dict) -> set:
    """The function and class names the profile's risk-focus section names (0.92.0)."""
    return {str(n) for n in ((facts.get("risk_focus") or {}).get("names") or [])}


def ordered_chunks(repo: Path, rel: str, lines, gaps: dict | None, focus=()) -> list:
    """The functions to ask about: the ones holding an assertion-gap survivor first, then the
    ones the profile's risk focus names, then the rest in file order."""
    chunks = chunks_in_range(repo, rel, lines)
    named = (gaps or {}).get(rel) or {}
    if not named and not focus:
        return chunks
    return sorted(chunks, key=lambda c: (c.name not in named, c.name.rsplit(".", 1)[-1] not in focus))


def file_findings(model: Model, repo: Path, targets: list, mint, findings_dir: Path,
                  filed: list, python: str, prove: bool, budget: Budget,
                  prior_index: PriorIndex | None = None, already_open: list | None = None,
                  leads: list | None = None, probes: list | None = None,
                  gaps: dict | None = None, asked: set | None = None, focus=(),
                  refute=None, set_aside: list | None = None) -> tuple:
    """Read the source, one function at a time, and try to prove each claim by flipping
    the line in a scratch copy. Returns (examined, proven, disproven).

    `refute(claim, chunk)`, when given, returns why a fact of this run already answers a
    claim, or None; an answered claim goes to `set_aside` with that reason and is neither
    filed nor listed as a lead (local_refuted.py).

    `targets` is `(path, the changed lines or None)`: a run over a range asks only
    about the functions the range touched, because a function nobody edited is a
    question this engine already asked on some earlier night.

    `probes`, when given, collects one row per counterfactual attempted — the
    expression, where it ran, the status and the reason — so `facts.json` says what
    was executed this run, refusals included (audit 2026-10-02, O-S-1 (5)).
    """
    examined = proven = disproven = 0
    for rel, lines in targets:
        named = (gaps or {}).get(rel) or {}
        for chunk in ordered_chunks(repo, rel, lines, gaps, focus):
            if not budget.take_function():
                continue
            examined += 1
            if asked is not None:
                asked.add((rel, chunk.name))
            claim = examine(model, chunk, gap_hint(named[chunk.name]) if chunk.name in named else None)
            if not claim:
                continue
            aside = refute(claim, chunk) if refute else None
            if aside is not None:
                if set_aside is not None:
                    set_aside.append(aside)
                print(f"verdict-local: set aside {chunk.path}:{claim['line']} — {aside['why']}",
                      file=sys.stderr)
                continue
            # A counterfactual runs Python; for any other language none is attempted and none
            # of the probe budget is spent.
            unprovable = (NO_PROBE.format(language=languages.name_of(chunk.lang))
                          if chunk.lang != "python" else None)
            proof = (counterfactual(model, repo, chunk, claim, python)
                     if prove and not unprovable and budget.take_probe() else None)
            if proof is not None and probes is not None:
                probes.append({"path": chunk.path, "function": chunk.name,
                               "line": claim["line"], "expression": proof.get("expression", ""),
                               "scratch": proof.get("scratch"), "status": proof["status"],
                               "reason": proof.get("reason", "")})
            if proof and proof.get("status") == "unavailable":
                print(f"verdict-local: not proven, {chunk.path}:{claim['line']} — "
                      f"{proof['reason']}", file=sys.stderr)
            if proof and proof.get("status") == "disproven":
                # Withdrawn before it was ever filed. The cheapest false positive is the
                # one the harness catches for the reader.
                disproven += 1
                print(f"verdict-local: withdrew a claim in {chunk.path}:{claim['line']} — "
                      f"{proof['reason']}", file=sys.stderr)
                continue
            if proof and proof.get("status") == "proven":
                proven += 1
            entry = finding_of(claim, "@", chunk.source, proof)
            prior, status, how = (prior_index.match(repo, chunk) if prior_index
                                  else (None, None, None))
            if prior is None and leads is not None and entry.get("confidence") != "proven":
                # A project with state is a backlog somebody has to read. Measured on Sales:
                # 27 unproven Minor readings in one night, on top of 69 open findings. What a
                # small model read and could not prove is a lead for the next run that can
                # judge it — listed in the report, not added to the record.
                leads.append({"path": chunk.path, "line": claim["line"], "function": chunk.name,
                              "title": claim["title"], "severity": claim["severity"],
                              "why": (proof or {}).get("reason") or unprovable or
                              ("no counterfactual was attempted" if not prove
                               else "the proof budget was spent")})
            elif prior is None:
                mint(entry, findings_dir, filed)
            elif any(str(f.get("id")) == str(prior["id"]) for f in filed):
                continue            # this run already filed that finding once
            elif status == "resolved" and entry.get("confidence") != "proven":
                # A resolved finding is re-anchored when it is resolved, so its anchors often
                # cite the fix: a line match says the fix is still there as often as it says
                # the defect is back. Measured on ifta-agent (2026-10-15): the fixed function's
                # own signature matched, and a proven Critical was re-filed as REGRESSED on a
                # small model's unproven — and wrong — reading of the fixed code. Reopening a
                # closed finding takes what filing a new one takes: a proof. Without one it is
                # a lead for a run that can judge it.
                print(f"verdict-local: not re-opened — `{chunk.name}` may be {prior['id']} "
                      f"again ({how}), but the reading is unproven", file=sys.stderr)
                if leads is not None:
                    leads.append({"path": chunk.path, "line": claim["line"],
                                  "function": chunk.name, "title": claim["title"],
                                  "severity": claim["severity"],
                                  "why": f"may be {prior['id']} (resolved) again — {how}; "
                                         "unproven, so the resolved finding was not re-opened"})
            elif status == "resolved":
                print(f"verdict-local: {prior['id']} is back — {how}", file=sys.stderr)
                mint(regressed_finding(prior, entry, how), findings_dir, filed, keep_id=True)
            else:
                # Open or accepted already: it is carried by id, re-filed if its code
                # moved, or the maintainer's. A second finding for it is a duplicate
                # the backlog grows by every night.
                if already_open is not None:
                    already_open.append((str(prior["id"]), chunk.name, how))
                print(f"verdict-local: not filed again — `{chunk.name}` is {prior['id']} "
                      f"({status}): {how}", file=sys.stderr)
    return examined, proven, disproven
