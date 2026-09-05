"""Shared path predicate for Verdict's scope guards.

A path is inside QA scope when it is the repository's own `.qa/` root (team
mode) or lives under the solo state root — `$VERDICT_HOME`, defaulting to
`~/.claude/verdict` — matching the agent's §0 and the MCP server's project
resolution.
"""

import os
import sys


def utf8_stderr() -> None:
    """Make this process's stderr UTF-8, so its reason survives the trip.

    Every guard explains itself in prose containing an em-dash, and on Windows
    stderr defaults to the console codepage: the byte written is cp1252's 0x97,
    the caller decodes UTF-8, and the explanation is replaced by a decode error
    in a reader thread. A guard whose reason cannot be read is a guard that
    blocks without saying why. Wrapped, because a hook that cannot configure a
    stream must still run — fail-open is the rule everywhere else here too.
    """
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def solo_root() -> str:
    root = os.environ.get("VERDICT_HOME") or "~/.claude/verdict"
    return os.path.realpath(os.path.expanduser(root))


def is_allowed_path(path: str) -> bool:
    """True when `path` is inside a QA root. Empty paths are allowed — there
    is nothing to judge, and the permission system still applies.

    Resolved with realpath, not abspath: a symlink planted inside a `.qa/`
    directory must not launder a write to wherever it points (VERDICT-F-1,
    found by Verdict reviewing its own repository)."""
    if not path:
        return True
    p = os.path.realpath(os.path.expanduser(path))
    root = solo_root()
    if p == root or p.startswith(root + os.sep):
        return True
    return _in_team_qa_root(p)


def _in_team_qa_root(p: str) -> bool:
    """True only for `<repo>/.qa/...`, where `<repo>` is a git working tree.

    Any component named `.qa` used to be enough, which let a write to
    `<repo>/src/.qa/x` — a directory sitting inside the code under test —
    pass as QA scope. Team mode means the repository's own committed QA root,
    so the `.qa` must sit directly beside a `.git`. Only the first `.qa`
    component is considered: a nested one deeper in the tree is code, not
    scope.
    """
    parts = p.split(os.sep)
    for i, part in enumerate(parts):
        if part != ".qa":
            continue
        repo = os.sep.join(parts[:i]) or os.sep
        # `.git` is a directory in a normal clone and a file in a linked
        # worktree or submodule; both are real checkouts.
        return os.path.exists(os.path.join(repo, ".git"))
    return False


# Files inside a QA root that only the maintainer may write. The accepted-risk
# ledger is the maintainer's decision about the tester's findings; a tester
# that could write it could accept its own findings' risks and empty its own
# open list. `verdict-accept` writes it from outside any session.
MAINTAINER_FILES = ("accepted.json",)


def is_maintainer_file(path: str) -> bool:
    """True for the maintainer's ledger inside a QA root — the one path in
    scope that the tester is still refused."""
    if not path:
        return False
    p = os.path.realpath(os.path.expanduser(path))
    return os.path.basename(p) in MAINTAINER_FILES and is_allowed_path(p)
