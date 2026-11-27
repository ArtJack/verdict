"""What finalize asks the scan: whether a finding is hygiene's, whether its file is gone from
the tree, the evidence the scan vouches for, and a finding's identity.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    from .hygiene_git import _git_env
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_git import _git_env


# ── lifecycle: finalize calls these ───────────────────────────────────────
# Tier 1 becomes findings the harness owns, tier 2 the junk ledger. Both follow
# one rule for what this run did not see: it resolves only on evidence — every
# file it lives in was scanned, or is gone from the tree — and is otherwise
# carried open. Silence about a file nobody read is never a fix.


# What a Python file yields only once the parser has read it (_python, and the
# bodies _duplicates compares): where the parser refused the file this run, their
# silence there proves nothing.
_PARSED_KINDS = frozenset(("debugger_statement", "broad_swallow", "unused_import",
                           "commented_out_code", "todo_comment", "duplicate_function"))
_HEX_SHA = re.compile(r"[0-9a-f]{7,64}")


def is_hygiene(finding) -> bool:
    return isinstance(finding, dict) and finding.get("source") == "hygiene"


def absent_from_tree(repo, sha, paths) -> set:
    """Which of `paths` the tree at `sha` does not hold — the evidence a deleted
    file's item resolves on. Read from the tree, never the blobs, and from `repo`, as
    the scan read it: `git cat-file -e <sha>:<path>` looks a path up from the top of
    the work tree, and calls a blob a partial clone never fetched missing, and either
    would resolve what is in a file that is still there. When git cannot list the
    tree, nothing is known to be gone."""
    want = {p for p in paths or () if isinstance(p, str) and p}
    if not want:
        return set()
    rev = str(sha) if sha and _HEX_SHA.fullmatch(str(sha)) else "HEAD"
    try:
        proc = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", "--name-only", rev],
                              capture_output=True, env=_git_env())
    except OSError:
        return set()
    if proc.returncode != 0:
        return set()
    return want - {p.decode("utf-8", "replace") for p in proc.stdout.split(b"\0") if p}


class Evidence:
    """What a run's scan vouches for, file by file: the positive evidence an open
    item it did not see needs before it resolves.

    Such an item resolves when every file it lives in (`_paths`) was scanned — all
    its checks ran over it — or is gone from the tree the scan read. Two exceptions
    to "scanned": a Python file the parser refused says nothing about the kinds only
    the parser finds, and no RLS switch in SQL is judged unless every migration was
    read. Anything else carries the item open: a file unread, cut by the cap or too
    large to read, a side file that could not be read (then nothing is scanned), a
    scan that was unavailable. `absent(paths)` answers which of them are gone from
    the tree; it is asked only about files the scan did not read, once per file."""

    def __init__(self, scanned=(), parse_failed=(), rls_judged=False, absent=None):
        self.scanned = frozenset(p for p in scanned or () if isinstance(p, str))
        self.parse_failed = frozenset(p for p in parse_failed or () if isinstance(p, str))
        self.rls_judged = rls_judged is True
        self._absent = absent
        self._gone: dict = {}

    def absent(self, paths) -> set:
        """Which of `paths` are gone from the tree, each asked about once."""
        ask = sorted({p for p in paths if p not in self._gone})
        if ask:
            try:
                gone = set(self._absent(ask)) if self._absent else set()
            except Exception:
                gone = set()        # a tree nobody could read says nothing is gone
            self._gone.update((p, p in gone) for p in ask)
        return {p for p in paths if self._gone.get(p)}

    def carries(self, items) -> list:
        """For each open item this run did not see, as (kind, paths): None when the
        evidence resolves it, else why it stays open."""
        whys = [self._excepted(kind, paths) for kind, paths in items]
        ask = {p for (_kind, paths), why in zip(items, whys) if why is None
               for p in paths if p not in self.scanned}
        gone = self.absent(ask)
        out = []
        for (_kind, paths), why in zip(items, whys):
            if why is None:
                unread = [p for p in paths if p not in self.scanned and p not in gone]
                if unread:
                    why = f"{unread[0]} was not read by this run's scan"
                elif not paths:
                    why = "no file is recorded for it"
            out.append(why)
        return out

    def _excepted(self, kind, paths):
        """Why this run's evidence proves nothing about `kind` in `paths`, or None. An
        RLS switch in SQL waits for every migration to be read, whether its own file
        was scanned or has gone: deleting the migration that disabled RLS is no
        evidence about the table — a squash puts a baseline in its place that may say
        anything. Past that, a file the parser refused says nothing of the kinds only
        the parser finds."""
        sql = [p for p in paths if p.lower().endswith(".sql")]
        if kind == "open_database_rules" and sql and not self.rls_judged:
            return ("a migration went unread this run, so no table's final row-level-security "
                    "state is known — and a deleted migration is no evidence about one")
        for p in paths:
            if p in self.scanned and kind in _PARSED_KINDS and p in self.parse_failed:
                return f"{p} did not parse this run, so the checks that read its syntax tree did not run"
        return None


def _paths(record) -> list:
    """Every file an item lives in: each copy of a copied function, each file that
    reads a client-side variable, and the one it was filed at."""
    if not isinstance(record, dict):
        return []
    sites = record.get("sites")
    paths = [p for p in sites if isinstance(p, str) and p] if isinstance(sites, list) else []
    if isinstance(record.get("path"), str) and record["path"] and record["path"] not in paths:
        paths.append(record["path"])
    return paths


def identity_of(record) -> str:
    """What makes two items one across runs, as the outcome ledger keeps it
    (`hygiene_identity`): `fingerprint:<fp>` — except for a secret in a client-side
    variable, `public_env_secret:<VARIABLE>`, wherever it is read: a site that moves
    is the same finding. A record that already names its identity keeps it."""
    if isinstance(record.get("identity"), str) and record["identity"]:
        return record["identity"]
    if record.get("kind") == "public_env_secret" and record.get("variable"):
        return "public_env_secret:" + str(record["variable"])
    return "fingerprint:" + str(record.get("fingerprint"))


_identity = identity_of
_ID_NUMBER = re.compile(r"(\d+)$")
