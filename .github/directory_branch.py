#!/usr/bin/env python3
"""Write a release's plugin to the `directory` branch: every file but the tests.

The Claude directory scans every file on the branch its listing tracks. It
tracked `main`, so it read `tests/test_hygiene.py`, the suite of Verdict's own
secret scan, which has to hold secret-shaped values to test anything. Every
version after 0.90.2 failed "Secret in a shipped file" on it, whatever shape the
fake keys took: split into `+` chains, then stored reversed (2026-10-03). A plugin
needs none of that to run.

So each release also lands here as one commit: the release's tree minus what
only develops or measures Verdict (EXCLUDED), on top of the branch's previous
commit. The listing tracks this branch instead, set on the plugin's Settings tab
under "Tracked branch or tag". The directory allows that change without a new
submission, because the repository and the plugin folder, which can't change,
stay what they were (claude.com/docs/plugins/submit, "Change the tracked branch
or tag").

Usage:
    python3 .github/directory_branch.py v0.90.7          # move the local branch
    python3 .github/directory_branch.py v0.90.7 --push   # build on origin's tip, fast-forward it
    python3 .github/directory_branch.py "$GITHUB_SHA" --label "$GITHUB_REF_NAME" --push

Plumbing only: the working tree, the index and every other ref are left alone.
The push is never forced, so a branch that moved underneath refuses instead of
losing a commit. Prints the new commit, or that the release is already there.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "directory"

# What a plugin never runs or reads: the suite (the secret scan's tests carry the
# shapes it detects), the eval harness and its seeded fixtures, Verdict's own QA
# record, CI, this repository's own Claude settings, and the changelog archive.
EXCLUDED = ("tests/", "eval/", ".qa/", ".github/", ".claude/", "docs/changelog/",
            # Since 2026-10-30 the directory takes these only from a Verified
            # organization, and the plugin reads none of them: contributor rules, the
            # package build, a maintainer's script, the README's animation.
            "AGENTS.md", "pyproject.toml", "scripts/", "docs/demo.svg",
            # What runs Verdict outside Claude Code: the nightly's guide (it names the
            # gateway's key variables: one of 0.95.0's credential findings), the GitHub
            # Action, the MCP registry's manifest and PyPI's front page.
            "docs/nightly.md", "action.yml", "server.json", "README-pypi.md")

# Modules no hook, agent, command or skill reaches: `verdict-run` and its local tier,
# the browser check, and what only they import. They ship through PyPI.
# `runner_env.py`, which hands the gateway's key to a headless run, was another of
# 0.95.0's credential findings. tests/test_directory_contents.py walks the imports
# from everything the plugin runs or names and fails if one of these is reached.
NOT_RUN = {"backfill", "braces", "check", "ends", "reach", "readers", "regions", "small",
           "testmarks"}
NOT_RUN_FAMILIES = ("browser", "local_", "runner")


def _not_run(path: str) -> bool:
    folder, _, name = path.rpartition("/")
    if folder != "src/verdict_mcp" or not name.endswith(".py"):
        return False
    return name[:-3] in NOT_RUN or name.startswith(NOT_RUN_FAMILIES)


def shipped(path: str) -> bool:
    """Whether a tracked path (posix, from the repository root) goes to the directory."""
    return not path.startswith(EXCLUDED) and not _not_run(path)


def _git(repo, *args: str, env: dict | None = None, data: bytes | None = None) -> bytes:
    done = subprocess.run(["git", "-C", str(repo), *args], input=data, env=env,
                          capture_output=True)
    if done.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def _text(repo, *args: str, **kw) -> str:
    return _git(repo, *args, **kw).decode("utf-8").strip()


def _local_tip(repo, branch: str) -> str | None:
    try:
        return _text(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}^{{commit}}")
    except RuntimeError:
        return None


def _remote_tip(repo, remote: str, branch: str) -> str | None:
    """The branch's commit on the remote, fetched now; None only when the remote
    answers that it has no such branch. An unreachable remote raises, so a network
    failure can never start the branch over."""
    if not _text(repo, "ls-remote", "--heads", remote, f"refs/heads/{branch}"):
        return None
    _git(repo, "fetch", "--quiet", "--no-tags", remote,
         f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    return _text(repo, "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}^{{commit}}")


def plugin_tree(repo, commit: str) -> str:
    """The tree of `commit` without EXCLUDED, written to the object store."""
    kept = []
    for entry in filter(None, _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0")):
        meta, path = entry.split(b"\t", 1)
        kind = meta.split(b" ")[1].decode()
        name = path.decode("utf-8", "surrogateescape")
        if kind != "blob":
            raise RuntimeError(f"{name} is a {kind}: the directory takes regular files only")
        if shipped(name):
            kept.append(entry)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        _git(repo, "update-index", "-z", "--index-info", env=env, data=b"\0".join(kept) + b"\0")
        return _text(repo, "write-tree", env=env)


def build(repo, ref: str, *, label: str | None = None, branch: str = BRANCH,
          remote: str | None = None) -> str | None:
    """Commit `ref`'s plugin onto `branch` and return the commit, or None when the
    branch already holds exactly that tree. With `remote`, the parent is the
    remote's tip, fetched now, and the commit is pushed there without force."""
    commit = _text(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    tree = plugin_tree(repo, commit)
    parent = _remote_tip(repo, remote, branch) if remote else _local_tip(repo, branch)
    if parent and _text(repo, "rev-parse", f"{parent}^{{tree}}") == tree:
        return None
    manifest = json.loads(_git(repo, "show", f"{commit}:.claude-plugin/plugin.json"))
    message = (f"directory: {manifest['name']} {manifest['version']} from {label or ref} · {commit[:7]}\n\n"
               f"The plugin as the Claude directory reads it: the tree of {commit}\n"
               f"without {', '.join(EXCLUDED)},\n"
               f"and without the modules no hook, agent, command or skill runs.\n"
               f"Written by .github/directory_branch.py.\n")
    new = _text(repo, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", message)
    if remote:
        _git(repo, "push", "--quiet", remote, f"{new}:refs/heads/{branch}")
    else:
        _git(repo, "update-ref", f"refs/heads/{branch}", new, parent or "")
    return new


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ref", help="the release to write: a tag, or a commit with --label")
    ap.add_argument("--label", help="what the commit message calls the release (default: REF)")
    ap.add_argument("--branch", default=BRANCH)
    ap.add_argument("--push", action="store_true",
                    help="build on the remote's tip and fast-forward the remote's branch")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    try:
        new = build(args.repo, args.ref, label=args.label, branch=args.branch,
                    remote=args.remote if args.push else None)
    except RuntimeError as exc:
        print(f"directory_branch: {exc}", file=sys.stderr)
        return 1
    print(f"{args.branch}: {new}" if new else
          f"{args.branch}: already holds {args.label or args.ref}'s plugin; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
