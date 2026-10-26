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
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
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
# A repro a model wrote rather than a tester (`verdict-backfill`, 0.92.0) runs only inside a
# sandbox with no network and no writes outside its fresh checkout, wherever it runs: the
# backfill, finalize's replay, the nightly's in-run replay, `verdict-replay`. A project with
# `probes: off` turned the local model's calls into its own code off because those functions
# reach live accounts and money; with no network they reach neither. Where no sandbox exists,
# such a repro is not run at all.
MODEL_WRITTEN = "backfill"
SANDBOX_PROFILE = ('(version 1)(allow default)(deny network*)(deny file-write* (subpath "/"))'
                   '(allow file-write* (subpath "{writable}") (literal "/dev/null") '
                   '(literal "/dev/stdout") (literal "/dev/stderr") (literal "/dev/tty"))')


BACKFILL_FILE = "backfill.jsonl"
STILL_BROKEN = "still broken"
LOOKS_FIXED = "looks fixed"


def load_backfill(qa_root) -> dict:
    """The latest `verdict-backfill` row per finding id, from `<qa_root>/backfill.jsonl`."""
    out: dict = {}
    try:
        text = (Path(qa_root) / BACKFILL_FILE).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id"):
            out[str(row["id"])] = row
    return out


def adopt_backfill(findings, rows: dict) -> list:
    """Attach a still-broken row's repro to its open finding when that finding has none → the ids
    adopted. Finalize calls it; from then on every run replays the repro, in the sandbox."""
    adopted = []
    for f in findings or []:
        row = rows.get(str(f.get("id")))
        if (not row or f.get("repro") or not is_open(f)
                or not str(row.get("verdict") or "").startswith(STILL_BROKEN)
                or not model_written(row.get("repro"))):
            continue
        f["repro"] = dict(row["repro"])
        adopted.append(str(f.get("id")))
    return adopted


def model_written(repro) -> bool:
    """The repro was drafted by a model and kept because it reproduced, not written by a tester."""
    return isinstance(repro, dict) and str(repro.get("origin") or "").startswith(MODEL_WRITTEN)


def sandbox_prefix(writable: Path) -> list | None:
    """The argv prefix that runs a command with no network and writes only under `writable`,
    or None where this machine has no such sandbox (macOS's sandbox-exec is the one used)."""
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        return None
    return ["sandbox-exec", "-p", SANDBOX_PROFILE.format(writable=str(Path(writable).resolve()))]


def repro_of(finding: dict) -> dict | None:
    """The structured repro block, or None when the finding has none worth running."""
    r = finding.get("repro")
    if isinstance(r, dict) and isinstance(r.get("command"), str) and r["command"].strip():
        return r
    return None


def wants_replay(finding: dict) -> bool:
    """An open Major-or-worse finding: the ones a repro is asked of (`repro_rule`), and named
    when they carry none."""
    return is_open(finding) and str(finding.get("severity") or "") in SEVERITIES_ASKED


def replayable(finding: dict) -> bool:
    """An open finding that carries a repro, whatever its severity (0.93.0): a Minor with a
    command that shows its defect is evidence too. Measured 2026-10-19: a capped asked run filed
    a third of what it found at Minor, and no repro of those ever ran."""
    return is_open(finding) and repro_of(finding) is not None


def major_first(findings) -> list:
    """Major-or-worse first, the rest after, each group in its own order: a cap or a budget that
    cuts the list cuts Minors first."""
    findings = list(findings or [])
    return [f for f in findings if wants_replay(f)] + [f for f in findings if not wants_replay(f)]


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


def _fresh_checkout(repo: Path, ref: str = "HEAD") -> tuple[Path | None, str, str]:
    """(worktree path, the commit's sha, problem). A detached worktree at `ref`: the same
    tree the run saw, in a place the run's scratch never touched."""
    base = Path(tempfile.mkdtemp(prefix="verdict-replay-")).resolve()   # git reports resolved paths
    scratch = base / "tree"
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", f"{ref}^{{commit}}"],
                          capture_output=True, text=True)
    if head.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        return None, "", (f"not a git repository: {repo}" if ref == "HEAD"
                          else f"commit {ref[:12]} is not in this repository")
    proc = subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(scratch),
                           head.stdout.strip()], capture_output=True, text=True)
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


# What the harness runs without a person: an interpreter on a script in the QA root or the
# fresh tree, a `-c` string, or pytest — argv, never a shell. `verdict-facts` and
# `verdict-finalize` run a command the tester wrote, outside the Bash guard that watches the
# tester's own commands, so a pipeline, a redirection or an arbitrary program is not theirs
# to run; `verdict-replay`, typed by a person who can read it first (`--show`), runs anything.
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_INTERPRETER = re.compile(r"^(?:python(?:\d+(?:\.\d+)?)?|pypy\d*(?:\.\d+)?|pytest)$")
_MODULES = ("pytest", "unittest", "doctest")
_REFUSED_ENV = ("LD_", "DYLD_")
_SHELL_OPERATORS = (";", "&", "|", "<", ">", "`", "$(", "\n")


def _outside_quotes(command: str) -> str:
    """The command with every quoted span blanked — what a shell would read as operators."""
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(command):
                out.append("  ")
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(" ")
        elif c in "'\"":
            quote = c
            out.append(" ")
        elif c == "\\" and os.name != "nt" and i + 1 < len(command):
            out.append("  ")
            i += 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _split(command: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(command)
    words = shlex.split(command, posix=False)          # a Windows path's backslashes stay
    return [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "'\"" else w for w in words]


def unattended_argv(command: str, scratch: Path, qa_root: Path, cwd: Path):
    """(argv, env, problem): the command as argv when its shape is one the harness runs
    unattended, else (None, {}, why)."""
    bare = _outside_quotes(command)
    for op in _SHELL_OPERATORS:
        if op in bare:
            shown = "a newline" if op == "\n" else f"`{op}`"
            return None, {}, f"the command uses {shown}, a shell operator"
    try:
        words = _split(command)
    except ValueError as exc:
        return None, {}, f"the command cannot be split into words ({exc})"
    env: dict = {}
    if len(words) > 1 and Path(words[0]).name == "env" and not words[1].startswith("-"):
        # `env A=1 python x.py` says what `A=1 python x.py` says; a tester writes it that way often
        # (2026-10-18: a proven Major's repro went unreplayed over the word). `env -i` is not that.
        words = words[1:]
    while words and _ENV_ASSIGN.match(words[0]):
        name, _, value = words.pop(0).partition("=")
        if name.startswith(_REFUSED_ENV):
            return None, {}, f"the command sets {name}"
        env[name] = value
    if not words:
        return None, {}, "the command names no program"
    prog = Path(words[0]).name.lower()
    prog = prog[:-4] if prog.endswith(".exe") else prog
    if not _INTERPRETER.match(prog):
        return None, {}, f"`{Path(words[0]).name}` is not python or pytest"
    if prog == "pytest":
        return words, env, ""
    i = 1
    while i < len(words) and words[i].startswith("-") and words[i] not in ("-c", "-m"):
        i += 2 if words[i] in ("-W", "-X") else 1
    if i >= len(words):
        return None, {}, "python with no script, `-c` or `-m` reads its program from stdin"
    if words[i] == "-c":
        return words, env, ""
    if words[i] == "-m":
        module = words[i + 1] if i + 1 < len(words) else ""
        if module not in _MODULES:
            return None, {}, f"`-m {module}` is not one of {', '.join(_MODULES)}"
        return words, env, ""
    script = Path(words[i])
    script = (script if script.is_absolute() else Path(cwd) / script).resolve()
    roots = [Path(qa_root).resolve(), Path(scratch).resolve()]
    if not any(script == r or r in script.parents for r in roots):
        return None, {}, f"the script {words[i]} is outside the QA root and the fresh checkout"
    return words, env, ""


def replay_one(finding: dict, repo: Path, scratch: Path, qa_root: Path, timeout: int,
               unattended: bool = False, sandbox=sandbox_prefix) -> dict:
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
    row = {"id": str(finding.get("id")), "command": command, "cwd": str(cwd),
           "expect": r.get("expect") if isinstance(r.get("expect"), dict) else {"exit": 0}}
    argv, own_env = command, {}
    wrap = None
    if model_written(r):
        # Unattended shape and the sandbox, whoever asked: a model chose this code.
        unattended = True
        wrap = sandbox(scratch.parent) if sandbox else None
        if not wrap:
            row.update(result="could not run", exit=None, output_tail="",
                       checks=["a model-written repro runs only inside a sandbox with no network "
                               "and no writes outside its checkout, and this machine has none"])
            return row
    if unattended:
        argv, own_env, refusal = unattended_argv(command, scratch, qa_root, cwd)
        if argv is None:
            row.update(result="could not run", exit=None, output_tail="",
                       checks=[f"not run unattended: {refusal}. The harness runs an interpreter "
                               "on a script in the QA root or the fresh tree, a `-c` string, or "
                               "pytest; `verdict-replay` runs any command when a person asks"])
            return row
    env = dict(os.environ)
    own_path = own_env.pop("PYTHONPATH", "")
    env.update(own_env)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_guard_dir(scratch.parent)), str(scratch / "src"), str(scratch)]
        + ([own_path] if own_path else [])
        + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    env[ORIGINAL_ENV] = os.pathsep.join(dict.fromkeys([str(repo.resolve()), str(repo)]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    if wrap:
        # A scrubbed environment as well: nothing the caller's shell holds (a token, a password,
        # a gateway key) is there for a script a model wrote to read or print, and `~` is the
        # checkout's own scratch, not the owner's home.
        tmp = scratch.parent / "tmp"
        tmp.mkdir(exist_ok=True)
        keep = ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE",
                ORIGINAL_ENV, *own_env)
        env = {k: v for k, v in env.items() if k in keep}
        env.update(TMPDIR=str(tmp), HOME=str(tmp))
        argv = [*wrap, *argv]
    try:
        proc = subprocess.run(argv, shell=not unattended, cwd=str(cwd), env=env,
                              capture_output=True, text=True, errors="replace", timeout=timeout)
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


MEASURE_MAX_FINDINGS = 12
MEASURE_TIMEOUT_S = 180
MEASURE_BUDGET_S = 600


def measure_findings(repo: Path, findings, previous_sha: str | None, qa_root: Path,
                     measured_at: str, timeout: int = MEASURE_TIMEOUT_S,
                     cap: int = MEASURE_MAX_FINDINGS, source: str = "facts",
                     refs: tuple = ("HEAD", "previous"),
                     budget: int = MEASURE_BUDGET_S) -> tuple[dict, list[str]]:
    """Run each open finding's `repro` (Major+ first, 0.93.0) on a fresh worktree at HEAD and,
    when the record names one, at the previous commit → ({finding id: record}, notes).

    The `verification_test` shape, applied to the command a finding carries: a
    reproduction at the previous commit and none at HEAD is a fix the harness watched;
    a reproduction at HEAD is a defect still there, whatever a judgment says. Every row
    also goes to `replays.jsonl`, so the gate shows the latest reading per finding.
    """
    notes: list[str] = []
    todo = major_first(f for f in findings or [] if replayable(f))
    if not todo:
        return {}, notes
    if len(todo) > cap:
        notes.append(f"replay capped at {cap} of {len(todo)} open findings with a repro (Major+ first)")
        todo = todo[:cap]
    want_previous = "previous" in refs and bool(previous_sha)
    records: dict = {str(f.get("id")): {"command": repro_of(f)["command"],
                                         "previous_sha": previous_sha if want_previous else None,
                                         "at_head": "unavailable",
                                         "at_previous": "unavailable" if want_previous else None}
                     for f in todo}
    rows, started, over_budget = [], time.monotonic(), set()
    # The previous commit first, HEAD last: the gate reads the latest row per finding.
    for ref, key in ((previous_sha, "at_previous"), ("HEAD", "at_head")):
        if key == "at_previous" and not want_previous:
            continue
        scratch, sha, problem = _fresh_checkout(repo, ref)
        if scratch is None:
            notes.append(f"replay at {'HEAD' if ref == 'HEAD' else ref[:7]}: {problem}")
            continue
        try:
            for f in todo:
                if time.monotonic() - started > budget:
                    over_budget.add(str(f.get("id")))
                    continue
                row = replay_one(f, repo, scratch, qa_root, timeout, unattended=True)
                row.update(at=measured_at, checkout=sha, scratch=str(scratch), source=source,
                           ref="HEAD" if ref == "HEAD" else "previous")
                rows.append(row)
                rec = records[str(f.get("id"))]
                rec[key] = row["result"]
                rec[f"checks_{'head' if key == 'at_head' else 'previous'}"] = row["checks"]
                if row.get("isolated") is False:
                    rec["isolated"] = False
        finally:
            _remove_checkout(repo, scratch)
    if rows:
        with (Path(qa_root) / REPLAYS_FILE).open("a", encoding="utf-8") as handle:
            for row in rows:      # the previous commit's row first: the gate reads the last
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    if over_budget:
        notes.append(f"replay stopped at its {budget}s budget: {len(over_budget)} finding(s) "
                     f"not measured at every commit ({', '.join(sorted(over_budget)[:5])})")
    heads = [r["at_head"] for r in records.values()]
    notes.append(f"replay: {len(records)} open finding(s) measured at HEAD"
                 + (f" and {previous_sha[:7]}" if want_previous else "")
                 + f" — {heads.count('reproduced')} reproduced, "
                 f"{heads.count('not reproduced')} not reproduced, "
                 f"{heads.count('could not run')} could not run")
    return records, notes


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
    ap.add_argument("ids", nargs="*", help="finding ids to replay (default: every open finding "
                                           "with a structured repro, Major+ first)")
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
                if (str(f.get("id")) in wanted if wanted else (wants_replay(f) or replayable(f)))]
    skipped = [str(f.get("id")) for f in findings if repro_of(f) is None]
    todo = major_first(f for f in findings if repro_of(f) is not None)
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
