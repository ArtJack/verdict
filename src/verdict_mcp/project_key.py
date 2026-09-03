"""Reference implementation of docs/project-key.md — the project-key spec.

The agent's §0 carries the same rule as a shell recipe; this module is the
programmatic form used by `verdict-gate` to resolve a checkout to its solo
key. If the two ever disagree, docs/project-key.md wins. Stdlib only.
"""

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

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
