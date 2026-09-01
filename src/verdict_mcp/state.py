"""Read-only loading of Verdict QA state. Stdlib only.

The MCP server and the `verdict-gate` CLI both build on this module. Keeping
`mcp` (and every other third-party import) out of here is what lets the GitHub
Action's gate mode run `gate.py` as a bare script with zero installs.

Project resolution, mirroring the agent's §0:
  - a bare key (e.g. "pricer") resolves to  $VERDICT_HOME/<key>/   (solo mode);
    VERDICT_HOME defaults to ~/.claude/verdict
  - a path (e.g. "/repo" or "~/work/app") resolves to <path>/.qa/  (team mode),
    or to the path itself if it directly contains state.json.
"""

import hashlib
import json
import os
import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

SEVERITY_RANK = {"Blocker": 0, "Critical": 1, "Major": 2, "Minor": 3, "Trivial": 4}
DELTA_VALUES = {"NEW", "STILL_OPEN", "RESOLVED", "REGRESSED"}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:[\\/]")
# How far back to look for a rewritten commit's content before calling it
# diverged. Bounded so the session banner never pays for a deep history.
_DRIFT_SEARCH = 500


def home() -> Path:
    return Path(os.environ.get("VERDICT_HOME", str(Path.home() / ".claude" / "verdict")))


def known_projects() -> list[str]:
    root = home()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "state.json").is_file())


def norm_status(value) -> str:
    """Normalize a finding's status for comparison.

    A live baseline wrote `"OPEN"`, and every `status == "open"` test in this
    codebase silently disagreed with it: the gate reported zero open findings
    for a project holding seven, one of them Critical. Case is not a contract
    violation worth failing a run over — it is a comparison bug, and it belongs
    fixed in one place rather than guarded at ten call sites.
    """
    return str(value or "").strip().lower()


def is_open(finding: dict) -> bool:
    """Open unless explicitly closed. The enum lives in `validate`, which
    refuses to write anything outside it; here the job is to fail safe on a
    state that got written anyway, because reading it the other way let a
    mistyped `"closed"` hide an open Critical from the gate."""
    return norm_status(finding.get("status")) not in ("resolved", "withdrawn")


def sev_rank(value) -> int:
    """Rank severity case-insensitively; unknown or missing values sort last."""
    return SEVERITY_RANK.get(str(value or "").strip().capitalize(), 99)


def is_path_like(project: str) -> bool:
    """True when the argument addresses a filesystem path rather than a solo key."""
    return (
        "/" in project
        or "\\" in project
        or project.startswith("~")
        or project == "."
        or bool(_DRIVE_PREFIX.match(project))
    )


def resolve_root(project: str) -> Path | None:
    """Return the QA root for a project key or a filesystem path, else None."""
    if is_path_like(project):
        p = Path(project).expanduser().resolve()
        if (p / ".qa" / "state.json").is_file():
            return p / ".qa"
        if (p / "state.json").is_file():
            return p
        return None
    for key in (project, project.lower()):
        solo = home() / key
        if (solo / "state.json").is_file():
            return solo
    return None


def load_state(project: str) -> tuple[dict | None, dict | None]:
    """Return (state, error). Exactly one is non-None."""
    root = resolve_root(project)
    if root is None:
        return None, {
            "error": f"no Verdict state found for {project!r}",
            "known_projects": known_projects(),
            "hint": "pass a project key from known_projects, or a repo path whose .qa/ holds state.json",
        }
    try:
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"error": f"state.json unreadable for {project!r}: {exc}"}
    state["_qa_root"] = str(root)
    return state, None


def parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def parse_timestamp(value: str) -> datetime | None:
    """Parse a state timestamp into an aware UTC datetime."""
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


_SOURCE_EXTS = (
    "py|ts|tsx|js|jsx|mjs|cjs|go|rs|rb|java|kt|php|cs|swift|sql|sh|"
    "yml|yaml|json|toml|md|css|html"
)
_CITED_PATH = re.compile(rf"([A-Za-z0-9_./-]+\.(?:{_SOURCE_EXTS}))\b")
# Defect *weight*, not defect count: ten typos are not a Critical. Exposed
# alongside the raw count because the two rank differently and both are true.
SEVERITY_WEIGHT = {"Blocker": 8.0, "Critical": 5.0, "Major": 2.0, "Minor": 1.0, "Trivial": 0.5}


def cited_path(finding: dict) -> str | None:
    """The first source path cited in a finding's evidence, if any."""
    for item in finding.get("evidence", []) or []:
        m = _CITED_PATH.search(str(item))
        if m:
            return m.group(1)
    return None


def _canonicalize(paths: set[str]) -> dict[str, str]:
    """Merge paths that are suffixes of one another onto the longest form.

    The same module gets cited at different depths across runs
    (`marketplaces/x.py` in one, `core/src/pkg/marketplaces/x.py` in another).
    Left unmerged, one hotspot reads as two lukewarm ones.
    """
    longest = sorted(paths, key=len, reverse=True)
    mapping = {}
    for p in paths:
        mapping[p] = next((q for q in longest if q != p and q.endswith("/" + p)), p)
    return mapping


def hotspots(state: dict, limit: int = 10) -> dict:
    """Where this project's defects actually cluster, computed from its own
    findings rather than from prose someone wrote once.

    Returns per-file `findings` (all-time), `open`, and `weight` (severity-
    weighted, all-time), plus `runs_of_history` — a ranking built on one run is
    a snapshot, not a pattern, and the caller is owed that number.
    """
    findings = state.get("findings", []) or []
    raw = {}
    uncited = 0
    for f in findings:
        path = cited_path(f)
        if path is None:
            uncited += 1
            continue
        raw.setdefault(path, []).append(f)

    canon = _canonicalize(set(raw))
    merged: dict[str, dict] = {}
    for path, group in raw.items():
        entry = merged.setdefault(
            canon[path], {"path": canon[path], "findings": 0, "open": 0, "weight": 0.0})
        for f in group:
            entry["findings"] += 1
            entry["open"] += 1 if is_open(f) else 0
            entry["weight"] += SEVERITY_WEIGHT.get(
                str(f.get("severity") or "").strip().capitalize(), 1.0)

    ranked = sorted(
        merged.values(), key=lambda e: (-e["weight"], -e["findings"], e["path"]))
    for entry in ranked:
        entry["weight"] = round(entry["weight"], 1)
    return {
        "runs_of_history": state.get("run_number"),
        "findings_total": len(findings),
        "findings_without_a_cited_path": uncited,
        "hotspots": ranked[:limit],
    }


CONFIDENCE_LEVELS = ("proven", "probable", "hypothesis", "unstated")
CALIBRATION_MIN_SAMPLE = 30
OUTCOMES_FILE = "outcomes.json"
RUNS_FILE = "runs.jsonl"


def finding_key(finding: dict) -> str:
    """Stable identity for ledger purposes: the run-to-run `hash` when there is
    one, else the human id, else the title."""
    for field in ("hash", "id", "title"):
        value = finding.get(field)
        if value:
            return str(value)
    return ""


def outcome_row(finding: dict, decided_on: str | None = None) -> dict:
    """The part of a finding worth keeping forever — a hundred bytes, not a
    finding. Evidence, prose, and root-cause chains stay in the report."""
    root = finding.get("root_cause") or {}
    row = {
        "hash": finding.get("hash"),
        "id": finding.get("id"),
        "severity": finding.get("severity"),
        "confidence": finding.get("confidence"),
        "proof_method": (root.get("proof") or {}).get("method"),
        "outcome": finding.get("outcome") or "unknown",
        "outcome_reason": finding.get("outcome_reason"),
        "first_seen": finding.get("first_seen"),
    }
    if row["outcome"] in ("confirmed", "refuted") and decided_on:
        row["decided_on"] = decided_on
    return {k: v for k, v in row.items() if v is not None}


def load_outcomes(qa_root) -> dict:
    """The permanent outcome ledger, keyed by finding identity. Missing or
    corrupt reads as empty — a lost ledger must never fail a run."""
    try:
        data = json.loads((Path(qa_root) / OUTCOMES_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    rows = data.get("findings") if isinstance(data, dict) else data
    if not isinstance(rows, dict):
        return {}
    return {k: v for k, v in rows.items() if isinstance(v, dict)}


def merge_outcomes(ledger: dict, findings: list, decided_on: str | None = None) -> dict:
    """Fold this run's findings into the ledger — the only reason calibration
    can exist at all.

    `state.json` keeps open findings and the current run's resolutions; a
    finding resolved two runs ago is gone from it. Without somewhere permanent
    to put decided outcomes, every settled finding would leave the sample as
    soon as it stopped being news, and the denominator would never grow past
    one run's worth. Upsert by identity, so re-running a finalize rewrites the
    same rows instead of counting them twice; a decided outcome is never
    overwritten by a later `unknown`, because losing the current findings list
    is not evidence that nothing was ever settled.
    """
    out = {str(k): dict(v) for k, v in (ledger or {}).items()}
    for f in findings or []:
        key = finding_key(f)
        if not key:
            continue
        row = outcome_row(f, decided_on)
        prior = out.get(key)
        if prior:
            if (prior.get("outcome") in ("confirmed", "refuted")
                    and row.get("outcome") not in ("confirmed", "refuted")):
                row = {**prior, **{k: v for k, v in row.items()
                                   if k not in ("outcome", "outcome_reason", "decided_on")}}
            else:
                row = {**prior, **row}
        out[key] = row
    return out


def calibration(state: dict, min_sample: int = CALIBRATION_MIN_SAMPLE,
                ledger: dict | None = None) -> dict:
    """Did the confidence this tester claimed predict what happened?

    Outcomes come from what the findings *did*, never from asking the model:
    a finding that was fixed and verified, or that regressed, was real; a
    finding the tester withdrew was not. Everything else is `unknown` and is
    excluded from the denominator — a still-open finding is genuinely
    ambiguous (not real, or real and nobody's priority yet), and counting it
    either way would make the number out of an assumption.

    Rates appear only once a bucket has `min_sample` decided outcomes.
    Below that the counts stand alone: "2 of 3" is a fact, "67%" is decoration.
    """
    if ledger is None and state.get("_qa_root"):
        ledger = load_outcomes(state["_qa_root"])
    rows = {str(k): v for k, v in (ledger or {}).items()}
    # The current run wins over its own ledger row: a withdrawal filed today
    # outranks the confirmation inferred yesterday.
    for f in state.get("findings", []) or []:
        key = finding_key(f)
        if key:
            rows[key] = f
    findings = list(rows.values())
    by_confidence: dict[str, dict] = {}
    by_method: dict[str, dict] = {}

    def bucket(store, key):
        return store.setdefault(
            key, {"confirmed": 0, "refuted": 0, "unknown": 0})

    for f in findings:
        outcome = f.get("outcome") or "unknown"
        if outcome not in ("confirmed", "refuted"):
            outcome = "unknown"
        conf = str(f.get("confidence") or "unstated").lower()
        if conf not in CONFIDENCE_LEVELS:
            conf = "unstated"
        bucket(by_confidence, conf)[outcome] += 1
        method = ((f.get("root_cause") or {}).get("proof") or {}).get("method")
        if method:
            bucket(by_method, str(method).lower())[outcome] += 1

    def finish(store):
        for key, counts in store.items():
            decided = counts["confirmed"] + counts["refuted"]
            counts["decided"] = decided
            if decided >= min_sample:
                counts["precision"] = round(counts["confirmed"] / decided, 3)
                counts["reading"] = f"{counts['confirmed']} of {decided} held up"
            else:
                counts["precision"] = None
                counts["reading"] = (
                    f"{counts['confirmed']} of {decided} decided so far — "
                    f"too few for a rate (needs {min_sample})")
        return store

    decided_total = sum(c["confirmed"] + c["refuted"] for c in by_confidence.values())
    return {
        "min_sample": min_sample,
        "findings_tracked": len(findings),
        "decided_outcomes": decided_total,
        "undecided_outcomes": len(findings) - decided_total,
        "by_confidence": finish(by_confidence),
        "by_proof_method": finish(by_method),
        "caveats": [
            "`confirmed` means fix-verified or regressed; it therefore tracks which "
            "findings held up under a check, not correctness in the abstract",
            "still-open findings are undecided on purpose and are excluded from every "
            "rate rather than guessed at",
            "a finding resolved without re-injection stays undecided: absence is not proof",
        ],
    }


RENDERED_BY_FINALIZE = "rendered from `state.json` by `verdict-finalize`"
# The two traces that survive a `git checkout`. `facts.json` and `judgment.json`
# are per-run scratch — a team-mode `.qa/` gitignores them, so a CI job looking
# at a fresh checkout finds neither, however honestly the run was measured.
# They are also the weaker evidence: `facts.json` existing proves the measuring
# step ran, not that `finalize` consumed it, whereas `calibration` is written
# only by `merge` and the report footer only by the renderer. So the durable
# pair is what a gate requires; the other two corroborate and are reported.
# Keys the chain does not sign. "chain" is the signature itself. The rest are
# volatile telemetry added after signing shipped: including them would make
# `_chain_signal`'s re-derivation of an *old* signed state produce a new-shape
# row and fail its own binding check — every pre-upgrade state would read as
# tampered. Tampering with a duration is not worth guarding against; tampering
# with a verdict is, and that stays signed.
_CHAIN_EXCLUDED = ("chain", "gate_durations")


def chain_link(prev: str, row: dict) -> str:
    """This run's link in the run-history chain: sha256(prev + canonical row).

    The point is that the value depends on the row's *content*. `report_rendered`
    checks for a fixed footer string and `state_computed` checks that a key holds
    a dict — both are satisfiable by copying what is already visible in the
    committed `.qa/` artifacts, which is how `--require-harness` was shown to be
    defeated by imitation rather than forgery. A link copied forward from the
    previous run does not verify against the new row, so imitation stops working.

    Honest about what this is not: nothing here makes fabrication impossible. A
    model that reimplements the chain correctly can still write a state by hand
    — at which point it has done most of the work the harness would have done.
    What changes is that the cheap attack, copy the strings, now fails loudly.
    """
    body = {k: v for k, v in row.items() if k not in _CHAIN_EXCLUDED}
    payload = (prev or "") + json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_chain(rows: list) -> dict:
    """Recompute the run-history chain → {"status", "first_bad"}.

    status is one of:
      intact    — every chained row verifies against its predecessor
      unchained — no row carries a link yet (a project from before this existed)
      broken    — a link does not verify, or a row after the first chained one
                  dropped its link. Dropping is a break on purpose: without that
                  ratchet, a fabricator could simply omit what it cannot compute.
    """
    start = next((i for i, r in enumerate(rows)
                  if isinstance(r, dict) and r.get("chain")), None)
    if start is None:
        return {"status": "unchained", "first_bad": None}
    prev = ""
    for row in rows[start:]:
        if not isinstance(row, dict) or not row.get("chain"):
            return {"status": "broken", "first_bad": (row or {}).get("run_number")}
        if row["chain"] != chain_link(prev, row):
            return {"status": "broken", "first_bad": row.get("run_number")}
        prev = row["chain"]
    return {"status": "intact", "first_bad": None}


DURABLE_SIGNALS = ("state_computed", "report_rendered", "chain_intact")


def missing_durable(signals: dict) -> list:
    """The durable traces absent from `signals` — what a gate refuses over."""
    return [name for name in DURABLE_SIGNALS if not signals.get(name)]


def harness_signals(state: dict, qa_root=None) -> dict:
    """Was this state produced by measure → judge → finalize, or written by hand?

    Four independent traces, because each alone is weak. `facts.json` says the
    measuring step ran — and its `measured_at` must match this run's timestamp,
    or the file is left over from an earlier run. `calibration` is written only
    by `merge`. The report footer is emitted only by the renderer.

    One definition, shared by the gate, the eval scorer and the MCP surface.
    Three separate hand-written copies of the *hook* list is what let the eval
    and the nightly drift away from production without anyone noticing.
    """
    root = Path(qa_root or state.get("_qa_root") or ".")
    facts = None
    try:
        facts = json.loads((root / "facts.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    stamp = (state.get("last_run") or {}).get("timestamp_utc")
    report_raw = ""
    rel = str((state.get("last_run") or {}).get("report") or "")
    if rel:
        path = Path(rel) if Path(rel).is_absolute() else root / rel
        try:
            report_raw = path.read_text(encoding="utf-8")
        except OSError:
            report_raw = ""
    return {
        "facts_measured": bool(facts) and facts.get("measured_at") == stamp,
        "judgment_written": (root / "judgment.json").is_file(),
        "state_computed": isinstance(state.get("calibration"), dict),
        "report_rendered": RENDERED_BY_FINALIZE in report_raw,
        # Survives a checkout because runs.jsonl is committed, and unlike the two
        # above it cannot be satisfied by copying: the link is a function of the
        # row it signs. A state whose own link disagrees with the history is not
        # trusted even when the history verifies on its own.
        "chain_intact": _chain_signal(state, root),
    }


def _chain_signal(state: dict, root) -> bool:
    rows, _ = load_runs(root)
    result = verify_chain(rows)
    if result["status"] == "broken":
        return False
    recorded = (state.get("last_run") or {}).get("chain")
    if result["status"] == "unchained":
        # A project from before the chain existed. Claiming a link the history
        # does not carry is worse than carrying none, so it is refused.
        return not recorded
    last = rows[-1] if rows else {}
    if not recorded or recorded != last.get("chain"):
        return False
    # Once a project is chained, the run this state describes must be in it.
    if state.get("run_number") != last.get("run_number"):
        return False
    # And the state must still be the state that was signed. The link signs the
    # history row, and the row is *derived* from the state — so re-deriving it
    # and checking it reproduces the same link binds the two together. Without
    # this, laundering the verdict and emptying the findings in state.json alone
    # left an intact chain behind it, which is the hole the chain was added for.
    earlier = [r for r in rows[:-1] if r.get("chain")]
    prev = str(earlier[-1]["chain"]) if earlier else ""
    # The signed row may carry a correction generation, which is stamped at
    # write time from the ledger and is not derivable from the state — so it is
    # read back off the row being verified. Tampering with it is not an escape:
    # the revision travels inside the signed body, so a bumped value breaks the
    # link it rode in on before this comparison is ever reached.
    return chain_link(prev, history_row(state, _row_revision(last))) == recorded


def history_row(state: dict, revision: int = 0) -> dict:
    """One machine-native line of run history, derived from the state.

    The run-over-run time series used to live only in INDEX.md, and consumers
    parsed the markdown table with heuristic column matching. That worked until
    production wrote prose into the cells — run types like "delta (merge gate
    re-gate: … @ 5b9518d1)" — and every reader had to un-parse a rendering.
    Markdown is a render target; for history it had become the database. This
    row is the database; the INDEX stays for humans.

    `revision` is the correction generation for this run number, and it is the
    difference between a ledger a reader can trust and one it can only guess
    at. The file is append-only, so a corrected re-finalize cannot edit what it
    corrects — it can only be written after it. Left unmarked, telling the
    authoritative row from the one it supersedes means trusting file order and
    nothing else; stamped, the answer is in the record.
    """
    last = state.get("last_run") or {}
    findings = state.get("findings", []) or []
    by_sev: dict = {}
    for f in findings:
        if is_open(f):
            sev = str(f.get("severity") or "unknown").strip().capitalize()
            by_sev[sev] = by_sev.get(sev, 0) + 1
    by_delta: dict = {}
    for f in findings:
        d = f.get("delta") or "?"
        by_delta[d] = by_delta.get(d, 0) + 1
    row = {
        "run_number": state.get("run_number"),
        "run_type": state.get("run_type"),
        "verdict": state.get("verdict"),
        "timestamp_utc": last.get("timestamp_utc"),
        "git_sha": last.get("git_sha"),
        "sha_range": last.get("sha_range"),
        "git_branch": last.get("git_branch"),
        "tests": state.get("tests"),
        "findings": {
            "tracked": len(findings),
            "open": sum(by_sev.values()),
            "open_by_severity": by_sev,
            "delta": by_delta,
        },
        "quarantine": len(state.get("flaky_quarantine", []) or []),
        "report": last.get("report"),
    }
    durations = {name: g["duration_s"] for name, g in (state.get("gates") or {}).items()
                 if isinstance(g, dict) and isinstance(g.get("duration_s"), (int, float))}
    if durations:
        # Telemetry for the duration-regression fact: a gate that jumps from 3s
        # to 65s usually means a test started calling a live service. Excluded
        # from the chain body (see _CHAIN_EXCLUDED).
        row["gate_durations"] = durations
    for optional in ("run_label",):
        if state.get(optional) is not None:
            row[optional] = state[optional]
    if last.get("model"):
        row["model"] = last["model"]
    if revision:
        # Generation zero stays absent, so a first write is byte-for-byte what
        # it has always been and no existing row has to be reinterpreted.
        row["revision"] = revision
    return {k: v for k, v in row.items() if v is not None}


def _row_revision(row: dict) -> int:
    """A history row's correction generation. Absent, malformed, or boolean
    reads as 0: every row written before revisions existed is generation zero,
    and a garbled value must never outrank a real one."""
    value = row.get("revision")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value if value > 0 else 0


def next_revision(qa_root, run_number) -> int:
    """The generation to stamp on the next row for `run_number`.

    Zero when the ledger has no row for that run yet — the ordinary case. When
    rows already exist the next generation is one past the highest, so a
    correction outranks what it corrects without touching it. That happens more
    easily than it looks: `validate` refuses a second finalize at the same run
    number, so the way to retry a bad run is to restore `state.json` from
    `state.json.prev` and re-run — which rolls back every file except this one,
    because append-only is the point. The stale row stays; this says which row
    won.
    """
    if isinstance(run_number, bool) or not isinstance(run_number, int):
        return 0
    path = Path(qa_root) / RUNS_FILE
    if not path.is_file():
        return 0
    highest = -1
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("run_number") == run_number:
            highest = max(highest, _row_revision(row))
    return highest + 1 if highest >= 0 else 0


def load_runs(qa_root) -> tuple[list[dict], int]:
    """Read `<qa-root>/runs.jsonl` → (rows, skipped_lines).

    Tolerant by design: a torn trailing line from a crash mid-append is skipped
    and counted, never fatal. Duplicate run_numbers resolve by `revision`: the
    highest generation wins, because a correction is written after the row it
    corrects and says so. Equal generations fall back to the last write, which
    is what every row written before revisions existed relies on.
    """
    path = Path(qa_root) / RUNS_FILE
    if not path.is_file():
        return [], 0
    rows: dict = {}
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(row, dict) and isinstance(row.get("run_number"), int):
            prior = rows.get(row["run_number"])
            if prior is None or _row_revision(row) >= _row_revision(prior):
                rows[row["run_number"]] = row
        else:
            skipped += 1
    return [rows[n] for n in sorted(rows)], skipped


def order_findings(findings: list[dict]) -> list[dict]:
    """REGRESSED first, then severity, then oldest-first pressure."""
    return sorted(
        findings,
        key=lambda f: (
            0 if f.get("delta") == "REGRESSED" else 1,
            sev_rank(f.get("severity")),
            -(f.get("age_days") or 0),
        ),
    )


def code_drift(repo, sha, timeout: float = 3.0) -> dict:
    """How far the code has moved since this state was written.

    A verdict goes stale in two ways and only one of them is a duration. The
    repo's own state proved the point: written four hours earlier, it named
    three open Major findings that had all been fixed and merged in the six
    commits since. Nothing was corrupt — only a run resolves findings — but
    every consumer read it as current, because the only staleness signal in
    the product was a seven-day clock and the state was not old. It was
    *behind*. Measured here once so the session banner, the status command and
    anything else that reports a stored verdict can say the same thing.

    Returns {"status", "commits", "head"} where status is:
      current  — HEAD is the commit that was tested
      behind   — HEAD is `commits` commits ahead of the tested commit
      diverged — the tested commit is not in HEAD's history
      unknown  — no git, no recorded sha, or the commit is not in this repo

    Never raises and never blocks: an unreadable repository is `unknown`, not
    an alarm. A false "you are behind" would train people to ignore the line.
    """
    out = {"status": "unknown", "commits": None, "head": None}
    if not sha or not isinstance(sha, str) or not repo:
        return out

    def git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo), *args],
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None

    head = git("rev-parse", "--verify", "HEAD^{commit}")
    if head is None or head.returncode != 0:
        return out
    out["head"] = head.stdout.strip()

    # Resolve the recorded sha in *this* repository. A commit that is absent
    # (shallow clone, a different repo, a rewritten branch) is unknown, not
    # diverged: we cannot see far enough to make either claim.
    rec = git("rev-parse", "--verify", f"{sha.strip()}^{{commit}}")
    if rec is None or rec.returncode != 0:
        return out
    recorded = rec.stdout.strip()

    if recorded == out["head"]:
        out["status"] = "current"
        out["commits"] = 0
        return out

    anc = git("merge-base", "--is-ancestor", recorded, out["head"])
    if anc is None or anc.returncode not in (0, 1):
        return out  # 0 = ancestor, 1 = not; anything else is an error, not an answer

    if anc.returncode == 0:
        count = git("rev-list", "--count", f"{recorded}..{out['head']}")
        if count is None or count.returncode != 0:
            return out
        try:
            out["commits"] = int(count.stdout.strip())
        except ValueError:
            return out
        out["status"] = "behind"
        return out

    # Not an ancestor — but ancestry is not content. A squash merge replaces the
    # branch with a new commit carrying the identical tree, so every squash-merged
    # state would otherwise report "this verdict describes different code" about
    # code that is byte-identical. Ask what the commit *contained*, not where it
    # sat: walk back for a commit whose tree matches, and the distance to it is
    # the honest answer. Only when no such commit exists is the code really
    # different.
    rec_tree = git("rev-parse", f"{recorded}^{{tree}}")
    if rec_tree is None or rec_tree.returncode != 0:
        return out
    wanted = rec_tree.stdout.strip()

    walk = git("rev-list", f"--max-count={_DRIFT_SEARCH}", "--format=%T", out["head"])
    if walk is None or walk.returncode != 0:
        return out
    # `rev-list --format` emits "commit <sha>" then the format line, per commit.
    trees = [ln for ln in walk.stdout.splitlines() if not ln.startswith("commit ")]
    for distance, tree in enumerate(trees):
        if tree.strip() == wanted:
            out["status"] = "current" if distance == 0 else "behind"
            out["commits"] = distance
            return out

    out["status"] = "diverged"
    return out


# Written both ways in the wild: `**Repo-Path:** \`/path\`` in the profiles the
# agent generates, and a bare `Repo-Path: /path` in hand-written ones. Measured
# across the live roots rather than assumed — the bold form was the majority and
# the first pattern here matched none of them.
_REPO_PATH = re.compile(r"^\*{0,2}Repo-Path:\*{0,2}\s*`?([^`\n]+?)`?\s*$", re.M)


def repo_for_root(root) -> Path | None:
    """The repository a QA root describes, or None if it cannot be determined.

    Team mode is structural — the root *is* `<repo>/.qa`. Solo mode keeps the
    state outside the repo, so the link is the `Repo-Path:` header the profile
    records. Returns None rather than guessing: every caller of this treats an
    unknown repository as "cannot measure", never as "nothing changed".

    Caveat worth knowing before gating on the result: `Repo-Path` records the
    *main* worktree, by design — that is what makes the project key stable
    across worktrees. A run executed in a linked worktree therefore records a
    sha the main worktree's HEAD may never have seen, and the distance measured
    here is between two different checkouts. Callers that gate on drift should
    be opt-in for exactly that reason.
    """
    if not root:
        return None
    root = Path(root)
    if root.name == ".qa" and (root.parent / ".git").exists():
        return root.parent
    profile = root / "profile.md"
    try:
        m = _REPO_PATH.search(profile.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not m:
        return None
    candidate = Path(m.group(1).strip()).expanduser()
    return candidate if (candidate / ".git").exists() else None
