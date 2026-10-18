"""verdict-backfill: a repro for an old finding, drafted by the local model, kept only if it reproduces.

Findings filed before 0.90.12 carry prose evidence and no `repro` block, so nothing can replay
them: the record cannot tell which of them a later commit fixed. One owner's record held 19
proven Major-or-worse findings like that on 2026-10-17. This command asks the local model,
one finding at a time, for a standalone script whose assertion fails while the defect is
there. Each draft runs on a fresh checkout, inside a sandbox with no network and no writes
outside the checkout, at HEAD and at the commit the finding was anchored on. What it says:

- reproduced at HEAD: the finding is still broken, and the next run attaches the repro to it,
  marked as written by a model, so every later run replays it, in the same sandbox;
- not at HEAD but at the anchored commit: it looks fixed since then. Said, never resolved:
  only a run with judgment closes a finding;
- neither: no working repro, and the draft is discarded.

Each row goes to `<qa_root>/backfill.jsonl`; the script stays under `scratch/backfill/`.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from . import clock
    from .profile import load as load_profile
    from .replay import (BACKFILL_FILE, LOOKS_FIXED, MODEL_WRITTEN, STILL_BROKEN, _fresh_checkout,
                         _remove_checkout, adopt_backfill, load_backfill, replay_one,
                         sandbox_prefix, without_repro)
    from .small import Model, import_roots, interpreter_of, read_env_file
    from .state import load_state, repo_for_root
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from profile import load as load_profile
    from replay import (BACKFILL_FILE, LOOKS_FIXED, MODEL_WRITTEN, STILL_BROKEN, _fresh_checkout,
                        _remove_checkout, adopt_backfill, load_backfill, replay_one,
                        sandbox_prefix, without_repro)
    from small import Model, import_roots, interpreter_of, read_env_file
    from state import load_state, repo_for_root

SCRIPT_DIR = ("scratch", "backfill")
MARK = "DEFECT:"
EXPECT = {"exit": 1, "stderr_contains": f"AssertionError: {MARK}"}
DEFAULT_LIMIT = 10
TIMEOUT_S = 120
AROUND = 30
MAX_CITES = 3
MAX_CODE = 9000
MAX_SCRIPT = 12000
# A cheap first filter; the sandbox is the control. A draft that reaches for any of these is
# not run at all.
FORBIDDEN_IMPORTS = {"subprocess", "socket", "smtplib", "ftplib", "telnetlib", "http.client",
                     "urllib.request", "requests", "httpx", "aiohttp", "paramiko"}
FORBIDDEN_CALLS = {"os.system", "os.popen", "os.remove", "os.unlink", "shutil.rmtree",
                   "os.rmdir", "os.removedirs", "os.execv", "os.execvp", "os.fork"}

PROMPT = """You write one standalone Python script that demonstrates a defect a QA run found in this \
repository. Rules:
- It runs from the repository root. On sys.path: {roots}. Import the project's own code from \
there; do not copy or reimplement it.
- Exactly one `assert` checks the defect: it fails while the defect is present and passes once it \
is fixed, and only its message starts with "{mark}". Any other check (a precondition, a setup \
step) uses a plain assert whose message does not carry that word.
- That assertion states what must not happen, in the finding's own terms (the payment is not \
confirmed, the card is charged once, the total is not doubled), so that any correct fix passes it. \
Do not assert the value one particular fix would produce.
- It never touches the network, a database server, a payment provider or a mail server: replace \
any client that would with unittest.mock. It runs in a sandbox with no network, so a real call fails.
- No subprocess, no sockets, no file writes outside tempfile. At most 80 lines.

Answer with JSON only: {{"script": "<the whole script>", "explains": "<one sentence: what the \
assertion checks>"}}

The finding:
{finding}

The cited code at HEAD:
{code}

How the project's own tests run (a fresh interpreter needs the same setup):
{setup}
"""

REPAIR = """Your script for {fid} did not run: it failed before reaching its assertion. Fix it, keeping \
the same rules, and answer with the same JSON. Use only names the cited files define.

Your script:
{script}

What it printed:
{tail}
"""


def _git_show(repo: Path, ref: str, rel: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{rel}"], capture_output=True,
                          text=True, errors="replace")
    return proc.stdout if proc.returncode == 0 else None


def _tree(repo: Path, ref: str) -> list:
    proc = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", ref],
                          capture_output=True, text=True, errors="replace")
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def resolve_path(repo: Path, ref: str, rel: str, tree=None) -> str | None:
    """A cited path as the tree at `ref` has it: as written, or, for a bare or shortened path
    (`job_health.py:494`), the one file whose path ends with it."""
    if _git_show(repo, ref, rel) is not None:
        return rel
    files = tree if tree is not None else _tree(repo, ref)
    hits = [f for f in files if f.endswith("/" + rel.lstrip("./"))]
    return hits[0] if len(hits) == 1 else None


def citations(finding: dict) -> list:
    """(path, line) pairs the finding cites: its anchors first, then `path:line` in its evidence."""
    out: list = []
    for a in finding.get("anchors") or []:
        if isinstance(a, dict) and a.get("path") and isinstance(a.get("line"), int):
            out.append((str(a["path"]), a["line"]))
    for e in finding.get("evidence") or []:
        for m in re.finditer(r"([\w./-]+\.py):(\d+)", str(e)):
            out.append((m.group(1), int(m.group(2))))
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:MAX_CITES]


OUTLINE_NAMES = 40
REPAIRABLE = ("ImportError", "ModuleNotFoundError", "AttributeError", "NameError", "TypeError")


def module_of(rel: str, roots) -> str:
    """The dotted import path of a repository file, under the project's import roots."""
    path = rel[:-3] if rel.endswith(".py") else rel
    for root in sorted(roots or [], key=len, reverse=True):
        if path.startswith(root.rstrip("/") + "/"):
            path = path[len(root.rstrip("/")) + 1:]
            break
    parts = path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def outline(source: str) -> list:
    """What a module defines at the top level: classes with their methods, functions with their
    arguments. Measured 2026-10-18: drafts shown only an excerpt imported names that do not exist."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(f"def {node.name}({', '.join(a.arg for a in node.args.args)})")
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            out.append(f"class {node.name}: " + ", ".join(methods[:12]))
        elif isinstance(node, ast.Assign) and all(isinstance(t, ast.Name) for t in node.targets):
            out += [t.id for t in node.targets if t.id.isupper() or not t.id.startswith("_")][:2]
    return out[:OUTLINE_NAMES]


def cited_code(repo: Path, finding: dict, ref: str = "HEAD", roots=()) -> str:
    """Numbered excerpts of the cited files at `ref`, capped — what the model reads."""
    return cited(repo, finding, ref, roots)[0]


def reaches(repo, qa_root, python, prefix, script_path, spans, head_ref, timeout, sandbox) -> bool | None:
    """Does the repro run any line of a cited function? True, False, or None when the trace could
    not run. Measured 2026-10-18: of six repros kept for defects with a known fix, half did not stop
    reproducing under the fix; one never reached the guard it claimed to test."""
    tracer = Path(qa_root).joinpath(*SCRIPT_DIR, "_trace.py")
    tracer.parent.mkdir(parents=True, exist_ok=True)
    tracer.write_text(TRACER, encoding="utf-8")
    for rel, lo, hi in spans:
        shadow = {"id": "trace", "repro": {
            "command": f"{prefix}{python} {tracer} {rel} {lo} {hi} {script_path}", "cwd": "repo",
            "expect": {"exit": 0}, "origin": f"{MODEL_WRITTEN} trace"}}
        row = run_at(repo, qa_root, shadow, head_ref, timeout, sandbox)
        m = TRACE_MARK.search(str(row.get("output_tail") or ""))
        if m is None:
            return None
        if int(m.group(1)) > 0:
            return True
    return False


TEST_LINES = 70
# A reasoning model spends part of its output budget thinking: at 3,000 tokens one draft in three
# came back cut off mid-line, its assertion never written (2026-10-18).
DRAFT_TOKENS = 8000


def django_settings(repo: Path) -> str | None:
    """The settings module the project's own test runner uses, when it is a Django project."""
    import configparser
    for name, section in (("pytest.ini", "pytest"), ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        cfg = Path(repo) / name
        if cfg.is_file():
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(cfg, encoding="utf-8")
                if parser.has_option(section, "DJANGO_SETTINGS_MODULE"):
                    return parser.get(section, "DJANGO_SETTINGS_MODULE").strip()
            except (configparser.Error, OSError, UnicodeDecodeError):
                continue
    pyproject = Path(repo) / "pyproject.toml"
    if pyproject.is_file():
        try:
            text = pyproject.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        try:
            import tomllib
        except ImportError:  # Python before 3.11: the one key, read off its line
            m = re.search(r"""(?m)^\s*DJANGO_SETTINGS_MODULE\s*=\s*["']([^"'\n]+)["']""", text)
            return m.group(1).strip() if m else None
        try:
            doc = tomllib.loads(text)
        except Exception:  # noqa: BLE001 — a config we cannot read adds nothing
            return None
        opts = ((doc.get("tool") or {}).get("pytest") or {}).get("ini_options") or {}
        value = opts.get("DJANGO_SETTINGS_MODULE")
        return str(value) if value else None
    return None


def test_excerpt(repo: Path, ref: str, rels, names) -> str:
    """The head of the test file nearest the cited code: one beside it, else one that names what
    it defines. The draft copies its setup: measured 2026-10-18, drafts for a Django project kept
    nothing while they could not see how its tests build their objects."""
    files = [f for f in _tree(repo, ref) if f.endswith(".py")
             and (Path(f).name.startswith("test") or Path(f).name.endswith("_test.py"))]
    beside = [f for f in files for r in rels if Path(f).parent == Path(r).parent]
    chosen = beside[:1]
    if not chosen:
        for f in files:
            text = _git_show(repo, ref, f) or ""
            if any(re.search(rf"\b{re.escape(n)}\b", text) for n in names if len(n) >= 4):
                chosen = [f]
                break
    if not chosen:
        return ""
    head = "\n".join((_git_show(repo, ref, chosen[0]) or "").splitlines()[:TEST_LINES])
    return f"# {chosen[0]} (its first {TEST_LINES} lines)\n{head}"


def setup_hint(repo: Path, ref: str, rels, names) -> str:
    lines = []
    if settings := django_settings(repo):
        lines.append(f"This is a Django project; its tests run with DJANGO_SETTINGS_MODULE={settings}. "
                     f"Before importing its models: os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                     f"'{settings}'), then django.setup(). A model whose table does not exist needs it "
                     "created first (django.db.connection.schema_editor().create_model(Model)), or use "
                     "a model the test settings already install.")
    if excerpt := test_excerpt(repo, ref, rels, names):
        lines.append("How one of the project's own tests sets up:\n" + excerpt)
    return "\n\n".join(lines) or "(no test setup found)"


def cited(repo: Path, finding: dict, ref: str = "HEAD", roots=()) -> tuple:
    """(the excerpts the model reads, the cited modules' import paths, the names they define)."""
    parts, tree, modules, defined, rels, spans = [], None, [], [], [], []
    for cited, line in citations(finding):
        rel = resolve_path(repo, ref, cited, tree)
        if rel is None and tree is None:
            tree = _tree(repo, ref)
            rel = resolve_path(repo, ref, cited, tree)
        text = _git_show(repo, ref, rel) if rel else None
        if text is None:
            continue
        lines = text.splitlines()
        lo, hi = max(1, line - AROUND), min(len(lines), line + AROUND)
        body = "\n".join(f"{n:>5}  {lines[n - 1]}" for n in range(lo, hi + 1))
        names = outline(text)
        modules.append(module_of(rel, roots))
        rels.append(rel)
        spans.append((rel, *span(text, line)))
        defined += [n.split(":")[0].split("(")[0].replace("class ", "").replace("def ", "").strip()
                    for n in names]
        head = f"# {rel} — import it as `{modules[-1]}`"
        if names:
            head += "; it defines: " + "; ".join(names)
        parts.append(f"{head}\n# (lines {lo}-{hi})\n{body}")
    return "\n\n".join(parts)[:MAX_CODE], modules, [d for d in defined if d], rels, spans


TRACER = """import runpy, sys
target, lo, hi, script = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
hits = set()


def local(frame, event, arg):
    if event == "line" and lo <= frame.f_lineno <= hi:
        hits.add(frame.f_lineno)
    return local


def call(frame, event, arg):
    return local if frame.f_code.co_filename.replace("\\\\", "/").endswith(target) else None


sys.argv = [script]
sys.settrace(call)
try:
    runpy.run_path(script, run_name="__main__")
except BaseException:
    pass
finally:
    sys.settrace(None)
    print("VERDICT-TRACE hits=%d" % len(hits))
"""
TRACE_MARK = re.compile(r"VERDICT-TRACE hits=(\d+)")


def span(source: str, line: int) -> tuple:
    """(first, last) line of the innermost function holding `line`, else a few lines around it."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return max(1, line - 3), line + 3
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.lineno <= line <= getattr(node, "end_lineno", node.lineno):
            # The body, not the `def` line: an import executes that, and the tracer would read a
            # script that only imports the module as one that ran the function.
            first = node.body[0].lineno if node.body else node.lineno
            if best is None or first >= best[0]:
                best = (first, getattr(node, "end_lineno", node.lineno))
    return best or (max(1, line - 3), line + 3)


def touches(script: str, modules, names) -> bool:
    """The draft imports a cited module or names something a cited file defines: a script that
    touches none of the cited code cannot be showing the finding's defect."""
    if any(m and re.search(rf"(?<![\w.]){re.escape(m)}(?![\w])", script) for m in modules):
        return True
    return any(re.search(rf"\b{re.escape(n)}\b", script) for n in names if len(n) >= 3)


def finding_text(finding: dict) -> str:
    rc = finding.get("root_cause") if isinstance(finding.get("root_cause"), dict) else {}
    lines = [f"{finding.get('id')} ({finding.get('severity')}): {finding.get('title')}"]
    lines += [f"- evidence: {str(e)[:300]}" for e in (finding.get("evidence") or [])[:6]]
    if rc.get("mechanism"):
        lines.append(f"- mechanism: {str(rc['mechanism'])[:600]}")
    return "\n".join(lines)


def _dotted(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def check_script(script) -> str | None:
    """Why a draft is refused before it runs, or None. It must parse, carry a real `assert`
    with the mark (not a bare `raise`), and reach for none of the forbidden modules or calls."""
    if not isinstance(script, str) or not script.strip():
        return "no script"
    if len(script) > MAX_SCRIPT:
        return f"longer than {MAX_SCRIPT} characters"
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        # Where, so the next draft can mend it: two of nineteen findings ran out of drafts on
        # "invalid syntax" alone (2026-10-18).
        at = f" at line {exc.lineno}" if exc.lineno else ""
        text = (exc.text or "").strip()
        return f"does not parse ({exc.msg}{at}" + (f": `{text[:100]}`)" if text else ")")
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)
               and not isinstance(n.test, ast.Constant)
               and isinstance(n.msg, (ast.Constant, ast.JoinedStr)) and MARK in ast.unparse(n.msg)]
    if not asserts:
        return f"no `assert` whose message carries {MARK!r} over a real condition"
    if len(asserts) > 1:
        # Measured 2026-10-18: a precondition that could not load the configuration carried the
        # mark too, failed in the sandbox, and read as the defect.
        return f"{len(asserts)} assertions carry {MARK!r}; exactly one may, the one that checks the defect"
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None and MARK in ast.unparse(node.exc):
            return "raises the mark itself instead of asserting it"
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                if any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS):
                    return f"imports {name}"
        if isinstance(node, ast.Call) and _dotted(node.func) in FORBIDDEN_CALLS:
            return f"calls {_dotted(node.func)}"
    return None


def anchor_sha(qa_root: Path, finding: dict) -> str | None:
    """The commit the finding was last anchored on, from the run history, or None."""
    run = finding.get("anchored_at_run")
    try:
        lines = (Path(qa_root) / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("run_number") == run and row.get("git_sha"):
            return str(row["git_sha"])
    return None


def verdict_of(head: dict, anchor: dict | None, anchor_ref: str | None) -> str:
    if head.get("result") == "reproduced":
        return f"{STILL_BROKEN}: the repro reproduces at HEAD; the next run attaches it to the finding"
    if anchor and anchor.get("result") == "reproduced" and head.get("result") == "not reproduced":
        return (f"{LOOKS_FIXED} since {str(anchor_ref)[:12]}: the repro reproduces there and not at "
                "HEAD — said, not resolved; a run with judgment closes it")
    return "no working repro: the draft was discarded"


def run_at(repo: Path, qa_root: Path, shadow: dict, ref: str, timeout: int, sandbox) -> dict:
    scratch, sha, problem = _fresh_checkout(repo, ref)
    if scratch is None:
        return {"result": "could not run", "checks": [problem], "sha": sha}
    try:
        row = replay_one(shadow, repo, scratch, qa_root, timeout, unattended=True, sandbox=sandbox)
    finally:
        _remove_checkout(repo, scratch)
    return {"result": row["result"], "checks": row.get("checks", [])[:3], "sha": sha,
            "exit": row.get("exit"), "output_tail": str(row.get("output_tail") or "")[-400:]}


ATTEMPTS = 3
RETRY = """

An earlier draft for this finding did not show the defect. What happened:
{why}
Write a different script."""


def _attempt(model, repo, qa_root, finding, python, timeout, sandbox, head_ref, roots, prompt,
             stamp, targets=((), ()), spans=()) -> dict:
    """One draft: ask, check, run at the record's commit (with one repair round on a crash before
    the assertion), and at the anchored commit when it did not reproduce there."""
    fid = str(finding.get("id"))
    reply = model.ask_json(prompt, max_tokens=DRAFT_TOKENS) or {}
    script = reply.get("script")
    if problem := check_script(script):
        return {"verdict": f"no working repro: the draft {problem}", "why": f"the draft {problem}",
                "draft": str(script or "")[:400]}
    if not touches(script, *targets):
        why = "the draft imports none of the cited modules and names nothing the cited files define"
        return {"verdict": f"no working repro: {why}", "why": why, "draft": str(script)[:400]}
    path = Path(qa_root).joinpath(*SCRIPT_DIR, f"{fid}.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    # The project's own import roots (pytest's `pythonpath`), relative to the fresh checkout.
    prefix = f"PYTHONPATH={os.pathsep.join(roots)} " if roots else ""
    repro = {"command": f"{prefix}{python} {path}", "cwd": "repo", "expect": dict(EXPECT),
             "origin": f"{MODEL_WRITTEN} {stamp[:10]} ({getattr(model, 'name', '?')})"}
    shadow = {"id": fid, "repro": repro}
    out: dict = {}
    head = run_at(repo, qa_root, shadow, head_ref, timeout, sandbox)
    tail = str(head.get("output_tail") or "")
    crashed = (head.get("result") in ("could not run", "not reproduced")
               and any(e in tail for e in REPAIRABLE) and "AssertionError" not in tail)
    if crashed:
        fixed = model.ask_json(REPAIR.format(fid=fid, script=script, tail=tail[-1500:]),
                               max_tokens=DRAFT_TOKENS) or {}
        if not check_script(fixed.get("script")):
            path.write_text(fixed["script"], encoding="utf-8")
            reply, out["repaired"] = fixed, True
            head = run_at(repo, qa_root, shadow, head_ref, timeout, sandbox)
    if head.get("result") == "reproduced" and spans \
            and reaches(repo, qa_root, python, prefix, path, spans, head_ref, timeout, sandbox) is False:
        where = ", ".join(f"{rel} lines {lo}-{hi}" for rel, lo, hi in spans)
        why = (f"the script failed its assertion without running any line of the cited function "
               f"({where}); it must call the code the finding is about")
        return {"verdict": f"no working repro: {why}", "why": why, "draft": str(script)[:400]}
    ref = anchor_sha(qa_root, finding) if head.get("result") != "reproduced" else None
    anchor = run_at(repo, qa_root, shadow, ref, timeout, sandbox) if ref else None
    out.update(repro=repro, explains=str(reply.get("explains") or "")[:300], head=head,
               anchor=anchor, verdict=verdict_of(head, anchor, ref),
               why=(str(head.get("output_tail") or "").strip()[-800:] or head.get("result")))
    return out


def backfill_one(model, repo: Path, qa_root: Path, finding: dict, python: str, timeout: int,
                 sandbox=sandbox_prefix, head_ref: str = "HEAD", attempts: int = ATTEMPTS) -> dict:
    """Draft, check and run one finding's repro, up to `attempts` drafts → its backfill.jsonl row.
    `head_ref` is the commit the record describes (its last tested sha), not whatever the working
    checkout has open: an owner's main checkout often sits on a feature branch. Measured
    2026-10-18 on 19 findings: one draft each kept 1 to 3 repros per trial, a different few each
    time, so a finding gets more than one draft, each told why the last one failed."""
    fid = str(finding.get("id"))
    row = {"id": fid, "at": clock.stamp(), "model": getattr(model, "name", "?")}
    roots = import_roots(repo)
    code, modules, names, rels, spans = cited(repo, finding, head_ref, roots)
    if not code:
        row["verdict"] = "no working repro: the finding cites no Python file that exists at HEAD"
        return row
    shown = ", ".join(f"`{r}/`" for r in roots) + (", and " if roots else "") + "the repository root"
    prompt = PROMPT.format(mark=MARK, roots=shown, finding=finding_text(finding), code=code,
                           setup=setup_hint(repo, head_ref, rels, names)[:4000])
    result, used = {}, 0
    for used in range(1, max(1, attempts) + 1):
        result = _attempt(model, repo, qa_root, finding, python, timeout, sandbox, head_ref, roots,
                          prompt + (RETRY.format(why=result["why"]) if result else ""), row["at"],
                          (modules, names), spans)
        if result["verdict"].startswith((STILL_BROKEN, LOOKS_FIXED)):
            break
    row.update({k: v for k, v in result.items() if k != "why"}, attempts=used)
    if not row["verdict"].startswith((STILL_BROKEN, LOOKS_FIXED)):
        # What the last draft ran into, so a miss can be told from a fix: "the draft was discarded"
        # alone says neither whether the assertion held nor whether the script ever ran.
        row["last_why"] = str(result.get("why") or "")[-400:]
    return row


load_rows = load_backfill
adopt = adopt_backfill


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="verdict-backfill", description=__doc__.split("\n\n")[0])
    ap.add_argument("project", help="project key or a repo path whose .qa/ holds state.json")
    ap.add_argument("ids", nargs="*", help="finding ids (default: every open, proven Major+ "
                                           "finding with no repro)")
    ap.add_argument("--env-file", type=Path, default=None,
                    help="KEY=VALUE file with ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN")
    ap.add_argument("--model", default=None, help="the gateway's model name (default: "
                                                  "$VERDICT_LOCAL_MODEL, else chat)")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"at most N findings (default {DEFAULT_LIMIT})")
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S, help=f"seconds per run (default {TIMEOUT_S})")
    ap.add_argument("--attempts", type=int, default=ATTEMPTS,
                    help=f"drafts per finding until one reproduces (default {ATTEMPTS})")
    args = ap.parse_args(argv)

    env = dict(os.environ)
    if args.env_file:
        env.update(read_env_file(args.env_file))
    base_url, token = env.get("ANTHROPIC_BASE_URL"), env.get("ANTHROPIC_AUTH_TOKEN")
    if not base_url or not token:
        print("verdict-backfill: ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN are required (the "
              "local gateway, in --env-file or the environment)", file=sys.stderr)
        return 2
    state, err = load_state(args.project)
    if err:
        print(f"verdict-backfill: {err['error']}", file=sys.stderr)
        return 2
    qa_root = Path(state["_qa_root"])
    repo = repo_for_root(qa_root)
    if repo is None:
        print("verdict-backfill: the QA root names no repository", file=sys.stderr)
        return 2
    if sandbox_prefix(qa_root) is None:
        print("verdict-backfill: a model-written repro runs only inside a sandbox with no network "
              "and no writes outside its checkout (sandbox-exec, macOS), and this machine has none — "
              "nothing was drafted", file=sys.stderr)
        return 2
    config, _notes = load_profile(qa_root)
    python = interpreter_of(str(config.get("test_one_cmd") or (config.get("gates") or {}).get("suite") or ""), repo)
    if not python:
        print("verdict-backfill: the profile's test command names no Python interpreter — "
              "nothing was drafted", file=sys.stderr)
        return 2
    wanted = set(args.ids)
    todo = [f for f in state.get("findings") or []
            if str(f.get("id")) in set(without_repro(state.get("findings")))
            and (not wanted or str(f.get("id")) in wanted)][:args.limit]
    if not todo:
        print("verdict-backfill: no open, proven Major+ finding without a repro", file=sys.stderr)
        return 0
    head_ref = str((state.get("last_run") or {}).get("git_sha") or "HEAD")
    model = Model(args.model or env.get("VERDICT_LOCAL_MODEL") or "chat", base_url, token)
    print(f"verdict-backfill: {len(todo)} finding(s) at {head_ref[:12]} (the record's last tested "
          f"commit), drafted by {model.name}, each run in the sandbox", file=sys.stderr)
    counts = {STILL_BROKEN: 0, LOOKS_FIXED: 0, "none": 0}
    with (qa_root / BACKFILL_FILE).open("a", encoding="utf-8") as ledger:
        for f in todo:
            row = backfill_one(model, repo, qa_root, f, python, args.timeout, head_ref=head_ref,
                               attempts=args.attempts)
            ledger.write(json.dumps(row, sort_keys=True) + "\n")
            ledger.flush()
            kind = next((k for k in (STILL_BROKEN, LOOKS_FIXED) if row["verdict"].startswith(k)), "none")
            counts[kind] += 1
            print(f"verdict-backfill: {row['id']} — {row['verdict']}", file=sys.stderr)
    print(f"verdict-backfill: {counts[STILL_BROKEN]} still broken (proof attached on the next run) · "
          f"{counts[LOOKS_FIXED]} look fixed (said, not resolved) · {counts['none']} without a working "
          f"repro · {model.calls} call(s) to {model.name}, no Claude tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
