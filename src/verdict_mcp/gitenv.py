"""The environment every git call in the package runs under. Stdlib only.

`git -C <repo>` moves into `<repo>` and then looks for a repository, unless the
environment has already named one: GIT_DIR names the repository, GIT_INDEX_FILE
its index, GIT_OBJECT_DIRECTORY its object store, GIT_WORK_TREE its working
tree, and git obeys each of them wherever `-C` points. Every git call here
passed the caller's environment through, so a run read whatever repository the
environment named. Measured on 0.90.2 with GIT_DIR set to repository A and every
reader asked about repository B: `derive_key(B)` answered A's key (a run on B
would have read and written A's state); the census, the harness and the runner
read A's HEAD; `code_drift` called B's own HEAD "absent"; the scratch checkout
for fix verification failed; and an acceptance or answer signed without `--by`
took A's `user.name`. A review of the 0.91.0 hygiene scan found it first, where a
scan of B returned A's content.

Where the variables come from, measured on git 2.50: every pre-commit hook
carries GIT_INDEX_FILE, a hook run by a git that was itself given `--git-dir` or
GIT_DIR carries GIT_DIR as well, a post-receive hook in a bare repository carries
GIT_DIR=., and anyone may export them.

`git_env()` is `os.environ` without the seven variables below. Everything else
(PATH, HOME, the author's identity, GIT_CONFIG_*) passes through as before.
"""

# Lazy annotations, so this module imports on the 3.9 `python3` the hooks run
# under: they reach it through `project_key` and `state` (VERDICT-F-55).
from __future__ import annotations

import os

#: The variables that name a repository, or a part of one, whatever `-C` says:
#: the repository, its working tree, the common directory a linked worktree
#: shares, its index, its object store, the stores borrowed beside it, and the
#: namespace its refs are read under.
REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def git_env() -> dict:
    """The caller's environment without REPO_VARS: what every git call gets as `env=`.

    Read at call time, not import time, so a variable set after import is seen;
    and a new dict each time, so nothing a caller does to it reaches `os.environ`.
    """
    return {k: v for k, v in os.environ.items() if k not in REPO_VARS}
