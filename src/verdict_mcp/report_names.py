"""Where a run's report goes: its file name, its topic, whether an existing report
belongs to this run, and re-reporting a run with its narratives kept.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from .hygiene import is_hygiene
    from .filed import FINDINGS_DIR
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene import is_hygiene
    from filed import FINDINGS_DIR


_REPORT_RUN = re.compile(r"·\s*run\s+(\d+)\b")


def _report_belongs_to(path: Path, run_number) -> bool:
    """True when the report on disk is this run's own — its header names the
    run number — so a retry reuses the file an earlier attempt at the same run
    left. A refusal takes its report back now (finalize_main); a finalize killed
    after rendering still leaves one, as every refusal used to."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:200]
    except OSError:
        return False
    m = _REPORT_RUN.search(head)
    return bool(m) and m.group(1) == str(run_number)


_TOPIC_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_topic(topic, fallback: str) -> str:
    """A report topic is a filename fragment, never a path.

    `judgment.topic` went into `reports/<date>-<topic>.md` as written, so a
    topic of `../../x` named a file outside `reports/` and the `mkdir` below
    built the way there (audit 2026-10-02, H-D-1). One character class, runs
    of anything else collapsed to one dash, nothing left that a path could
    use."""
    text = _TOPIC_SAFE.sub("-", str(topic or ""))
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return text or fallback


def _report_name(qa_root: Path, stamp: str, topic: str, run_number) -> str:
    """`reports/<date>-<topic>.md`, unless an earlier run already wrote that
    file. A second delta on the same day used to overwrite the first one's
    report — the artifact of record, gone without a word — found by the
    acceptance run for 0.83.0 on its own history (boltons run 3 over run 2).
    Another run's file is left alone and this one gets `-run<n>` appended; a
    file this run itself wrote is reused."""
    base = f"reports/{stamp}-{_safe_topic(topic, 'run')}"
    for rel in (f"{base}.md", f"{base}-run{run_number}.md"):
        path = qa_root / rel
        if not path.exists() or _report_belongs_to(path, run_number):
            return rel
    n = 2
    while (qa_root / f"{base}-run{run_number}-{n}.md").exists():
        n += 1
    return f"{base}-run{run_number}-{n}.md"


# What a re-report by id carries from the previous state: the finding as its
# author last wrote it. Never the computed fields, never a fix claim — a
# resolution by id is "gone, not verified" unless the harness measures it.
_RE_REPORT_FIELDS = ("id", "title", "severity", "priority", "failure_classification",
                     "confidence", "evidence", "verification_test", "root_cause")


def _lift_narratives(judgment: dict) -> None:
    """A finding file's `narrative` becomes `prose.findings[id]` — the place
    the renderer has always read per-finding prose from."""
    for f in judgment.get("findings") or []:
        if not isinstance(f, dict) or "narrative" not in f:
            continue
        text = f.pop("narrative")
        if isinstance(text, str) and text.strip():
            prose = judgment.get("prose")
            if not isinstance(prose, dict):
                prose = judgment["prose"] = {}
            if not isinstance(prose.get("findings"), dict):
                prose["findings"] = {}
            prose["findings"].setdefault(str(f.get("id")), text)


def _re_report(judgment: dict, previous: dict | None, facts: dict) -> list[str]:
    """Expand `still_open` and `resolved` into findings copied from the
    previous state → problems.

    The verb is cheap on purpose — run 14 re-typed eighteen findings to say
    "still there" — and the harness keeps it honest: an id whose cited code
    changed or vanished since the evidence was written (`evidence_drift`, T-1)
    is refused, because the evidence no longer says what the finding says.

    A hygiene finding named by either verb expands to nothing: the scan re-measures
    it every run (reconcile), and the tester's word neither keeps it open nor
    closes it. The local tier and the sweep name every open id in `still_open`,
    and the copy — which carries no `source` — would stand beside the harness's
    own finding under the same id."""
    prev_by_id = {str(f.get("id")): f for f in ((previous or {}).get("findings") or [])
                  if isinstance(f, dict) and f.get("id")}
    drift = ((facts.get("evidence_drift") or {}).get("findings") or {}) \
        if isinstance(facts.get("evidence_drift"), dict) else {}
    bad = []
    for verb, status in (("still_open", "open"), ("resolved", "resolved")):
        for fid in judgment.get(verb) or []:
            prior = prev_by_id.get(str(fid))
            if prior is None:
                continue            # validate_judgment has already refused it
            if is_hygiene(prior):
                continue            # the harness's own: re-measured, never carried by word
            d = drift.get(str(fid)) if verb == "still_open" else None
            if isinstance(d, dict) and d.get("drift") in ("changed", "missing"):
                refs = ", ".join(f"{r.get('ref')} ({r.get('status')})" for r in d.get("refs") or []
                                 if r.get("status") in ("changed", "missing"))
                bad.append(f"still_open names {fid}, but the code it cites {d['drift']} since "
                           f"the evidence was written ({refs}) — write "
                           f"{FINDINGS_DIR}/{fid}.json with fresh evidence, or resolve it")
                continue
            entry = {k: prior[k] for k in _RE_REPORT_FIELDS if k in prior}
            entry["status"] = status
            entry["re_reported"] = verb
            judgment["findings"].append(entry)
    return bad
