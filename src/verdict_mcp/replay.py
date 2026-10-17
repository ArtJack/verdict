"""verdict-replay — run a finding's repro again on a fresh checkout, outside the run.

A run's probes live in the QA root's scratch and import the checkout the run was in; a
report built on them says "it reproduced for the tester". The pass that made the Phase 3
reports credible (2026-10-16/17, six projects) was done by hand every time: a fresh clone,
the finding's script, the expected value. This is that pass as a command.

For each open finding with a structured `repro` block — `{"command": …, "cwd": "repo" |
"qa_root", "expect": {"exit": N, "stdout_contains": …, "stderr_contains": …}}` — the
repository is checked out again as a detached git worktree at HEAD, the command runs there
with `PYTHONPATH` pointing at the fresh tree first (an editable install's `.pth` names the
original checkout, and would quietly test it), bytecode writing and lazy git fetches off,
and the result is compared with `expect`. Any spelling of the original checkout's path in
the command is rewritten to the fresh tree, for the same reason.

Results go to `<qa-root>/replays.jsonl`, beside the state and outside the signed row — a
replay is evidence about a finding, not a run — and `verdict-gate` shows the latest one per
open finding. The command runs in a shell with the caller's rights: `--show` prints every
command without running one. Exit 0: every replayed finding reproduced; 1: one did not; 2: nothing could be
replayed (no repo, no repro blocks, or a command that could not start).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from . import clock
    from .state import is_open, load_state, repo_for_root
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from state import is_open, load_state, repo_for_root

REPLAYS_FILE = "replays.jsonl"
ORIGINAL_ENV = "VERDICT_REPLAY_ORIGINAL"
# Runs at interpreter start, after site-packages' `.pth` files and before the command: an
# editable install of the original checkout — a `.pth` line naming it, or meson-python's
# meta-path finder carrying its build directory — would import the original quietly. On
# 2026-10-17 numpy-financial's replay said "reproduced" with every import from the tester's
# own tree, PYTHONPATH notwithstanding. Entries under the interpreter's own prefix stay: the
# checkout's `.venv` is where the dependencies live.
GUARD = """# written by verdict-replay: the fresh tree is what runs
import os as _os, sys as _sys

def disarm(path, meta_path, originals, prefixes):
    \"\"\"(sys.path, sys.meta_path) without what points into the original checkout.\"\"\"
    def norm(p):
        return _os.path.normcase(_os.path.normpath(p))

    roots = [norm(o) for o in originals if o]
    keep = [norm(p) for p in prefixes if p]

    def original(value):
        if not isinstance(value, str) or not value:
            return False
        v = norm(value)
        return (any(v == r or v.startswith(r + _os.sep) for r in roots)
                and not any(v == k or v.startswith(k + _os.sep) for k in keep))

    def strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, (list, tuple, set, frozenset)):
            for item in obj:
                yield from strings(item)
        elif isinstance(obj, dict):
            for item in list(obj.keys()) + list(obj.values()):
                yield from strings(item)

    path = [p for p in path if not original(p)]
    finders = []
    for f in meta_path:
        attrs = getattr(f, "__dict__", None) or {}
        if any(original(v) for v in strings(list(attrs.values()))):
            continue
        finders.append(f)
    return path, finders

_originals = [o for o in _os.environ.get(%r, "").split(_os.pathsep) if o]
if _originals:
    _sys.path[:], _sys.meta_path[:] = disarm(
        list(_sys.path), list(_sys.meta_path), _originals,
        [_sys.prefix, _sys.exec_prefix, _sys.base_prefix, _sys.base_exec_prefix])
    for _k in [k for k in _sys.path_importer_cache if isinstance(k, str)]:
        _n = _os.path.normcase(_os.path.normpath(_k))
        if any(_n == _os.path.normcase(_os.path.normpath(o)) or
               _n.startswith(_os.path.normcase(_os.path.normpath(o)) + _os.sep) for o in _originals):
            del _sys.path_importer_cache[_k]
""" % ORIGINAL_ENV
TRACEBACK = "Traceback (most recent call last)"
IMPORT_ERRORS = ("ImportError:", "ModuleNotFoundError:")


def _import_failure(err: str) -> str:
    """The last line of a traceback that is an import failure, else ''. On a fresh tree a
    compiled package has no built extension: numpy-financial's `_cfinancial` (2026-10-17)."""
    lines = [line for line in err.splitlines() if line.strip()]
    if TRACEBACK in err and lines and lines[-1].startswith(IMPORT_ERRORS):
        return lines[-1][:160]
    return ""
CANNOT_START = (126, 127, 9009)
NOT_RECOGNIZED = "is not recognized as an internal or external command"   # cmd.exe, exit 1
SEVERITIES_ASKED = ("Blocker", "Critical", "Major")
TAIL = 1200


def repro_of(finding: dict) -> dict | None:
    """The structured repro block, or None when the finding has none worth running."""
    r = finding.get("repro")
    if isinstance(r, dict) and isinstance(r.get("command"), str) and r["command"].strip():
        return r
    return None


def wants_replay(finding: dict) -> bool:
    return is_open(finding) and str(finding.get("severity") or "") in SEVERITIES_ASKED


def without_repro(findings) -> list[str]:
    """Ids of the open, proven Major+ findings that carry no structured repro — the ones
    `verdict-replay` cannot check, whose evidence stays prose."""
    return [str(f.get("id")) for f in findings or []
            if wants_replay(f) and f.get("confidence") == "proven" and repro_of(f) is None]


def _cwd_for(raw, scratch: Path, qa_root: Path) -> tuple[Path | None, str]:
    """`repo` (default), `qa_root`, or a relative path inside the fresh checkout."""
    name = str(raw or "repo")
    if name == "repo":
        return scratch, ""
    if name == "qa_root":
        return qa_root, ""
    candidate = (scratch / name).resolve()
    if os.path.isabs(name) or candidate != scratch.resolve() and scratch.resolve() not in candidate.parents:
        return None, f"cwd {name!r} is outside the fresh checkout"
    if not candidate.is_dir():
        return None, f"cwd {name!r} is not a directory in the checkout"
    return candidate, ""


def _fresh_checkout(repo: Path) -> tuple[Path | None, str, str]:
    """(worktree path, HEAD sha, problem). A detached worktree at HEAD: the same tree the
    run saw, in a place the run's scratch never touched."""
    base = Path(tempfile.mkdtemp(prefix="verdict-replay-")).resolve()   # git reports resolved paths
    scratch = base / "tree"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True)
    if head.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        return None, "", f"not a git repository: {repo}"
    proc = subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(scratch),
                           "HEAD"], capture_output=True, text=True)
    if proc.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        return None, head.stdout.strip(), f"git worktree add failed: {proc.stderr.strip()[:200]}"
    return scratch, head.stdout.strip(), ""


def _remove_checkout(repo: Path, scratch: Path | None) -> None:
    """Remove the fresh worktree; a removal that failed is said, with the way to finish it —
    a locked file on Windows leaves the directory, and git then carries a stale entry."""
    if scratch is None:
        return
    proc = subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(scratch)],
                          capture_output=True, text=True)
    if scratch.parent.name.startswith("verdict-replay-"):   # only the directory this module made
        shutil.rmtree(scratch.parent, ignore_errors=True)
    if proc.returncode != 0 or scratch.exists():
        print(f"verdict-replay: the fresh worktree at {scratch} was not fully removed"
              f"{': ' + proc.stderr.strip().splitlines()[-1][:120] if proc.stderr.strip() else ''} — "
              f"remove the directory and run `git -C {repo} worktree prune`", file=sys.stderr)


def _guard_dir(base: Path) -> Path:
    site = base / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(GUARD, encoding="utf-8")
    return site


def _names_original(text: str, repo: Path) -> bool:
    """The output cites a path into the original checkout — an import, a traceback frame —
    other than its hidden directories (`.venv`, `.git`, `.qa`) and a venv by any usual name."""
    plain = text.replace("\\", "/")
    for root in {str(repo.resolve()), str(repo)}:
        if re.search(re.escape(root.replace("\\", "/")) + r"/(?!\.|venv/|env/|node_modules/)", plain):
            return True
    return False


def _verdict(expect: dict, returncode: int, out: str, err: str) -> tuple[str, list[str]]:
    """What the result says against `expect`. With no expectation at all, exit 0 is the bar."""
    checks = []
    if not isinstance(expect, dict) or not expect:
        expect = {"exit": 0}
    ok = True
    if "exit" in expect:
        want = expect["exit"]
        hit = returncode == want
        ok &= hit
        checks.append(f"exit {returncode}{'' if hit else f' (expected {want})'}")
    for key, text in (("stdout_contains", out), ("stderr_contains", err)):
        if key in expect:
            hit = str(expect[key]) in text
            ok &= hit
            checks.append(f"{key} {'found' if hit else 'MISSING'}: {str(expect[key])[:60]!r}")
    return ("reproduced" if ok else "not reproduced"), checks


def _either_sep(root: str) -> str:
    """A regex for `root` spelled with either separator — Windows commands name the checkout
    both ways."""
    return r"[\\/]".join(re.escape(part) for part in re.split(r"[\\/]", root))   # a leading '/' is a part


def _rewrite_paths(command: str, repo: Path, scratch: Path) -> str:
    """A path into the original checkout would quietly test the original — rewritten to the
    fresh tree when the fresh tree has it. What the tree lacks stays where it is: the
    interpreter in the checkout's own `.venv` is untracked, and the fresh tree has no venv."""
    def swap(m):
        rest = m.group(2)
        target = scratch / rest.lstrip("/\\") if rest else scratch
        if target.exists():
            return str(scratch) + rest
        return m.group(0)
    for root in {str(repo.resolve()), str(repo)}:
        command = re.sub(rf"({_either_sep(root)})((?:[\\/][^\s'\"]*)?)", swap, command)
    return command


def replay_one(finding: dict, repo: Path, scratch: Path, qa_root: Path, timeout: int) -> dict:
    r = repro_of(finding)
    if r is None:
        return {"id": str(finding.get("id")), "command": "", "cwd": "", "expect": {},
                "result": "could not run", "exit": None, "output_tail": "",
                "checks": ["no structured repro (`repro.command`) on the finding"]}
    command = _rewrite_paths(str(r["command"]), repo, scratch)
    command = command.replace("{repo}", str(scratch)).replace("{qa_root}", str(qa_root))
    cwd, problem = _cwd_for(r.get("cwd"), scratch, qa_root)
    if cwd is None:
        return {"id": str(finding.get("id")), "command": command, "cwd": str(r.get("cwd")),
                "expect": r.get("expect") if isinstance(r.get("expect"), dict) else {"exit": 0},
                "result": "could not run", "exit": None, "checks": [problem], "output_tail": ""}
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_guard_dir(scratch.parent)), str(scratch / "src"), str(scratch)]
        + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env[ORIGINAL_ENV] = os.pathsep.join(dict.fromkeys([str(repo.resolve()), str(repo)]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    row = {"id": str(finding.get("id")), "command": command, "cwd": str(cwd),
           "expect": r.get("expect") if isinstance(r.get("expect"), dict) else {"exit": 0}}
    try:
        proc = subprocess.run(command, shell=True, cwd=str(cwd), env=env, capture_output=True,
                              text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        row.update(result="could not run", exit=None, checks=[f"timed out after {timeout}s"],
                   output_tail="")
        return row
    except OSError as exc:
        row.update(result="could not run", exit=None, checks=[str(exc)[:200]], output_tail="")
        return row
    if proc.returncode in CANNOT_START or NOT_RECOGNIZED in proc.stderr:
        row.update(result="could not run", exit=proc.returncode,
                   checks=[f"the command could not start (exit {proc.returncode})"],
                   output_tail=(proc.stdout + proc.stderr)[-TAIL:])
        return row
    result, checks = _verdict(row["expect"], proc.returncode, proc.stdout, proc.stderr)
    if result == "reproduced" and TRACEBACK in proc.stderr and "stderr_contains" not in row["expect"]:
        # An exit code alone cannot tell the defect from a crash on the way to it.
        result = "could not run"
        checks.append("crashed with a traceback, and `expect` names no stderr text — an exit "
                      "code alone cannot tell a crash from the defect")
    if result == "not reproduced" and (failure := _import_failure(proc.stderr)):
        # The command never reached the defect: the fresh tree could not be imported.
        result = "could not run"
        checks.append(f"the fresh tree could not be imported ({failure}) — a package with "
                      "compiled extensions needs its build step in `repro.command`")
    isolated = not _names_original(proc.stdout + proc.stderr, repo)
    if not isolated:
        checks.append("the output names the original checkout: the fresh tree may not be what ran")
    row.update(result=result, exit=proc.returncode, checks=checks, isolated=isolated,
               output_tail=(proc.stdout + proc.stderr)[-TAIL:])
    return row


def load_replays(qa_root) -> dict:
    """The latest replay per finding id, from `replays.jsonl`; {} when there is none."""
    latest: dict = {}
    try:
        lines = (Path(qa_root) / REPLAYS_FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return latest
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("id"):
            latest[str(row["id"])] = row
    return latest


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # the Windows cp1252 trap, every CLI
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="verdict-replay", description=__doc__.split("\n\n")[0])
    ap.add_argument("project", help="project key or a repo path whose .qa/ holds state.json")
    ap.add_argument("ids", nargs="*", help="finding ids to replay (default: every open Major+ "
                                           "finding with a structured repro)")
    ap.add_argument("--show", action="store_true",
                    help="print each finding's repro command and expectation; run nothing")
    ap.add_argument("--keep", action="store_true", help="keep the fresh worktree afterwards")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per command (default 600)")
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-replay: {err['error']}", file=sys.stderr)
        return 2
    qa_root = Path(state["_qa_root"])
    repo = repo_for_root(qa_root)
    if repo is None:
        print("verdict-replay: the QA root names no repository (team mode needs <repo>/.qa; "
              "solo mode needs Repo-Path in profile.md)", file=sys.stderr)
        return 2
    wanted = {i for i in args.ids}
    findings = [f for f in state.get("findings") or []
                if (str(f.get("id")) in wanted if wanted else wants_replay(f))]
    skipped = [str(f.get("id")) for f in findings if repro_of(f) is None]
    todo = [f for f in findings if repro_of(f) is not None]
    for fid in skipped:
        print(f"verdict-replay: {fid} has no structured repro (`repro.command`) — nothing to "
              "replay; the run's evidence is prose", file=sys.stderr)
    if not todo:
        print("verdict-replay: nothing to replay", file=sys.stderr)
        return 2
    if args.show:
        # The command runs with the caller's rights, in a shell: read it before running it.
        for f in todo:
            r = repro_of(f)
            print(f"{f.get('id')}  cwd={r.get('cwd') or 'repo'}  expect={json.dumps(r.get('expect') or {'exit': 0})}\n"
                  f"    {r['command']}")
        return 0
    scratch, head, problem = _fresh_checkout(repo)
    if scratch is None:
        print(f"verdict-replay: {problem}", file=sys.stderr)
        return 2
    print(f"verdict-replay: fresh checkout of {repo} at {head[:7]} → {scratch}", file=sys.stderr)
    rows = []
    try:
        for f in todo:
            print(f"verdict-replay: running {f.get('id')}: {repro_of(f)['command']}", file=sys.stderr)
            row = replay_one(f, repo, scratch, qa_root, args.timeout)
            row.update(at=clock.stamp(), run_number=state.get("run_number"), checkout=head,
                       scratch=str(scratch))
            rows.append(row)
            mark = {"reproduced": "✓", "not reproduced": "✗", "could not run": "?"}[row["result"]]
            print(f"verdict-replay: {mark} {row['id']} {row['result']}"
                  + (" (NOT isolated)" if row.get("isolated") is False else "")
                  + " — " + "; ".join(row["checks"]), file=sys.stderr)
    finally:
        if not args.keep:
            _remove_checkout(repo, scratch)
    with (qa_root / REPLAYS_FILE).open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    results = [r["result"] for r in rows]
    leaky = [r["id"] for r in rows if r.get("isolated") is False]
    print(f"verdict-replay: {results.count('reproduced')} reproduced · "
          f"{results.count('not reproduced')} not reproduced · "
          f"{results.count('could not run')} could not run · {len(skipped)} without a repro"
          + (f" · {len(leaky)} not isolated ({', '.join(leaky)})" if leaky else "")
          + f" → {qa_root / REPLAYS_FILE}", file=sys.stderr)
    if results.count("reproduced") == len(results):
        return 0
    return 1 if "not reproduced" in results else 2


if __name__ == "__main__":
    sys.exit(main())
