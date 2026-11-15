"""The hygiene census's rows in a run: split out of facts.json into their side file at
facts time, then read back at finalize as evidence and as the previous run's rows.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .hygiene import TIER2_KINDS, Evidence, absent_from_tree, hygiene_reading
    from .harness_common import HYGIENE_ITEMS_FILE, _atomic_write
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene import TIER2_KINDS, Evidence, absent_from_tree, hygiene_reading
    from harness_common import HYGIENE_ITEMS_FILE, _atomic_write


# What the scan vouches for, file by file: finalize's evidence, never the tester's
# reading, so it travels in the side file with the rows.
_VOUCHED = ("scanned_paths", "parse_failed_paths", "rls_judged")


def split_hygiene(facts: dict, qa_root: Path) -> None:
    """Move the tier-2 rows out of facts.json, into `<qa_root>/hygiene-items.json`.

    The tester reads facts.json whole on every run, and junk is never a finding:
    on Sales the hygiene block was 1,301 lines of it, 1,070 of them tier-2 rows
    there for no decision the tester makes. What stays is what reading needs — the
    status, the scope, exact counts of every tier, the tier-1 items and the leads
    — and the name of the file the ledger reads the rest from (`tier2_items`). What
    the scan vouches for goes with the rows, for finalize alone (`hygiene_evidence`):
    every path it scanned, the Python files the parser refused, and whether every
    migration was read — and, for a reader, the uncapped list of paths it could not
    read (`unread_paths`). A block with no items (the scan was unavailable) moves nothing and names
    no file; a block already split is left as it is, so a second call cannot empty
    the file. A side file that cannot be written costs the run nothing: tier 2 and
    the lists stay inline, where the readers find them, and `tier2_note` says why."""
    block = facts.get("hygiene")
    if not isinstance(block, dict) or not isinstance(block.get("items"), list) \
            or "tier2_file" in block:
        return
    rows, kept = [], []
    for it in block["items"]:
        (rows if isinstance(it, dict) and it.get("tier") == 2 else kept).append(it)
    # Bound to this facts run: a side file another run left is no side file at all.
    side = {"schema": 1, "git_sha": (facts.get("last_run") or {}).get("git_sha"),
            "measured_at": facts.get("measured_at"), "items": rows,
            "unread_paths": block.get("unread_paths", []),
            **{key: block[key] for key in _VOUCHED if key in block}}
    try:
        _atomic_write(Path(qa_root) / HYGIENE_ITEMS_FILE, json.dumps(side, indent=1) + "\n")
    except OSError as exc:
        block["tier2_note"] = (f"{HYGIENE_ITEMS_FILE} could not be written "
                               f"({exc.strerror or type(exc).__name__}): tier 2 stays in items")
        return
    block.pop("tier2_note", None)
    block.pop("unread_paths", None)
    for key in _VOUCHED:
        block.pop(key, None)
    block["items"] = kept
    block["tier2_file"] = HYGIENE_ITEMS_FILE
    block["tier2_count"] = len(rows)
    block["reading"] = hygiene_reading(HYGIENE_ITEMS_FILE)


def tier2_items(facts_hygiene: dict, qa_root: Path, bind=None) -> list | None:
    """This run's tier-2 rows, the way the ledger reads them: from the file
    `split_hygiene` names, or from the block itself when it names none — a facts
    file written before the split, one reused by --reuse-if-fresh, or one whose side
    file could not be written, all hold tier 2 inline, and reading that as empty
    would tell a ledger every row had resolved. None when the named file is
    missing, unreadable or holds no list of rows: this run's rows are unknown, which
    is not the same as none, and the ledger resolves nothing on it. A row that is
    not a well-formed tier-2 item is passed over. Whatever the QA root holds, the
    ledger gets rows or None, never an error. `bind` is the facts run the file must
    be (`_side_doc`)."""
    if not isinstance(facts_hygiene, dict):
        return []
    if "tier2_file" not in facts_hygiene:
        rows = facts_hygiene.get("items")
        return [it for it in rows if _tier2_row(it)] if isinstance(rows, list) else []
    side = _hygiene_side(facts_hygiene, qa_root, bind)
    rows = side.get("items") if side else None
    if not isinstance(rows, list):
        return None
    return [it for it in rows if _tier2_row(it)]


def hygiene_evidence(facts_hygiene: dict, qa_root: Path, repo=None, sha=None,
                     bind=None) -> Evidence:
    """What this run's scan vouches for, for the lifecycle: the paths it scanned, the
    Python files the parser refused and whether every migration was read — from the
    side file, or inline from a block never split — and, for a file it did not read,
    whether the tree at `sha` still holds it. A side file that cannot be read, or
    that another facts run wrote (`bind`), vouches for nothing, so nothing resolves by
    it (a deleted file still does)."""
    side = _hygiene_side(facts_hygiene, qa_root, bind)
    block = facts_hygiene if isinstance(facts_hygiene, dict) else {}

    def vouched(key):
        return side[key] if side and key in side else block.get(key)

    scanned, parse_failed = vouched("scanned_paths"), vouched("parse_failed_paths")
    return Evidence(scanned=scanned if isinstance(scanned, list) else (),
                    parse_failed=parse_failed if isinstance(parse_failed, list) else (),
                    rls_judged=vouched("rls_judged") is True,
                    absent=(lambda paths: absent_from_tree(repo, sha, paths)) if repo else None)


def hygiene_previous(block, qa_root: Path, run_number):
    """The previous run's ledger block with its rows read back from the file they went
    to (`write_state`), for `hygiene.ledger` to compare this run's against. A block
    that still holds its rows — one merged in this process, or one whose file could
    not be written — is returned as it is. The file must be the one that previous
    state's own run wrote: a state restored from state.json.prev, or a run killed
    between the two writes, leaves a file from another run, and comparing against it
    would resolve rows the state never had. When the rows cannot be read the block is
    returned without them, and the ledger carries nothing forward and says so."""
    if not isinstance(block, dict) or isinstance(block.get("rows"), list):
        return block
    doc = _side_doc(qa_root, block.get("rows_file"))
    if (doc is None or type(doc.get("run_number")) is not int or doc["run_number"] != run_number
            or not isinstance(doc.get("rows"), list)):
        return block
    return dict(block, rows=doc["rows"])


def _hygiene_side(facts_hygiene: dict, qa_root: Path, bind=None):
    """The side file a split block names, loaded — or None (`_side_doc`)."""
    return _side_doc(qa_root, facts_hygiene.get("tier2_file") if isinstance(facts_hygiene, dict)
                     else None, bind)


def _side_doc(qa_root: Path, name, bind=None):
    """A hygiene file in the QA root, loaded — or None: no file named, a name reaching
    out of the QA root, a file missing, unreadable or nested past what the parser
    holds (RecursionError, at about 1,000 levels on 3.9), a schema that is not the
    integer 1 (`true == 1` in Python, and is no schema), or — given `bind`, the facts
    run's {git_sha, measured_at} — a file another facts run wrote."""
    if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name:
        return None
    try:
        doc = json.loads((Path(qa_root) / name).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(doc, dict) or type(doc.get("schema")) is not int or doc["schema"] != 1:
        return None
    if bind is not None and any(doc.get(k) != bind.get(k) for k in ("git_sha", "measured_at")):
        return None
    return doc


def _tier2_row(it) -> bool:
    """A tier-2 row in the shape the scan writes one: a junk kind, a str path, an int
    line (a bool is not one), and str fingerprint, excerpt and why."""
    return (isinstance(it, dict) and type(it.get("tier")) is int and it["tier"] == 2
            and it.get("kind") in TIER2_KINDS and isinstance(it.get("path"), str)
            and type(it.get("line")) is int
            and all(isinstance(it.get(field), str) for field in ("fingerprint", "excerpt", "why")))
