"""Shared path predicate for Verdict's scope guards.

A path is inside QA scope when it has a `.qa` component (team mode) or lives
under the solo state root — `$VERDICT_HOME`, defaulting to `~/.claude/verdict` —
matching the agent's §0 and the MCP server's project resolution.
"""

import os


def solo_root() -> str:
    root = os.environ.get("VERDICT_HOME") or "~/.claude/verdict"
    return os.path.normpath(os.path.abspath(os.path.expanduser(root)))


def is_allowed_path(path: str) -> bool:
    """True when `path` is inside a QA root. Empty paths are allowed — there
    is nothing to judge, and the permission system still applies."""
    if not path:
        return True
    p = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
    if ".qa" in p.split(os.sep):
        return True
    root = solo_root()
    return p == root or p.startswith(root + os.sep)
