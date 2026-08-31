"""Shared path predicate for Verdict's scope guards.

A path is inside QA scope when it is the repository's own `.qa/` root (team
mode) or lives under the solo state root — `$VERDICT_HOME`, defaulting to
`~/.claude/verdict` — matching the agent's §0 and the MCP server's project
resolution.
"""

import os


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
