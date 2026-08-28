"""Reference implementation of docs/project-key.md — the project-key spec.

The agent's §0 carries the same rule as a shell recipe; this module is the
programmatic form used by `verdict-gate` to resolve a checkout to its solo
key. If the two ever disagree, docs/project-key.md wins. Stdlib only.
"""

import re
import subprocess
from pathlib import Path

_UNSAFE = re.compile(r"[^a-z0-9._-]")


def sanitize(name: str) -> str:
    name = name.lower()
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return _UNSAFE.sub("-", name) or "-"


def derive_key(cwd: str | Path = ".") -> tuple[str, str]:
    """Return (key, source): the project key for a checkout.

    source is "git" (main-worktree basename — the normal case, immune to git
    worktrees) or "directory" (fallback outside any repository).
    """
    path = Path(cwd).resolve()
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        proc = None
    if proc and proc.returncode == 0 and proc.stdout.startswith("worktree "):
        main = proc.stdout.splitlines()[0][len("worktree "):].strip()
        if main:
            return sanitize(Path(main).name), "git"
    return sanitize(path.name), "directory"
