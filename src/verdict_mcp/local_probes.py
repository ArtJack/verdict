"""The counterfactual: a probe the model proposes, checked for safety, run in a scratch
copy of the project. The only evidence that separates cause from correlation.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import ast
import configparser
import fnmatch
import io
import json
import keyword
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unicodedata
from pathlib import Path

try:
    from .hygiene import _scrub as scrub_secrets
    from .local_model import Model
    from .local_chunks import Chunk
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene import _scrub as scrub_secrets
    from local_model import Model
    from local_chunks import Chunk


# ── the counterfactual: the only evidence that separates cause from correlation ──


PROBE_Q = """You said this function is wrong:

File: {path}
```python
{source}
```

Claim: {mechanism}

Give me two things so I can test that claim by running it.

1. One Python expression that calls this code where the claim says it goes wrong. One
   line, no imports, no side effects. The module is already imported as `m`.
2. The one line to change, by its number in the left margin, and the whole replacement
   line with its indentation.

I will run the expression before and after the change myself, so do not tell me what it
returns — only how to reach it.

Reply with JSON only, and put a real call to `{function}` in the expression:
{{"expression": "<a one-line call on m that reaches the claim, e.g. m.{function}(...)>",
  "fix_line": <line number from the left margin>,
  "fix_replacement": "<the whole replacement line, with its indentation>"}}"""


COPY_SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox", ".mypy_cache",
             ".pytest_cache", ".ruff_cache", "build", "dist", ".idea", ".claude"}


# What never reaches the scratch copy, by name pattern. Audit 2026-10-02, O-S-1: the copy
# carried every `.env` in the tree, and the module under probe imports its config on
# import — so the "after" run read the project's live credentials in a directory the
# model's expression could reach. A project whose module is called `secrets.py` loses
# that import in the scratch and the probe says so; that is the safe direction.
SECRET_SKIP = (".env", ".env.*", "*.env", ".envrc", "*.pem", "*.key", "id_rsa*", ".ssh",
               ".netrc", ".npmrc", ".pypirc", ".gnupg", ".aws", ".git-credentials",
               "credentials", "credentials.*", "credentials*.json", "*.p12", "*.pfx",
               "secrets.*")


# The child's environment is built from this list, never from the parent's environment.
# Measured 2026-10-02 (`probe_small2.py`): `env=dict(os.environ, …)` handed the probe the
# gateway token the nightly exports — `env_has_token=True` in both runs — and whatever
# else launchd's environment holds. `LC_*` is kept with these; `PYTHONPATH` is the
# scratch roots only; `SYSTEMROOT`/`TEMP`/`TMP` are what a Windows CRT needs to start.
PROBE_ENV_KEEP = ("PATH", "HOME", "LANG", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP",
                  "USERPROFILE", "HOMEDRIVE", "HOMEPATH")   # the last three: Windows' HOME


PROBE_TIMEOUT_S = 60


MAX_COPY_BYTES = 300 * 1024 * 1024


def probe_env(roots) -> dict:
    """The environment a probe runs under: the allowlist above, bytecode writing off,
    and an import path made of the scratch roots and nothing else."""
    env = {k: v for k, v in os.environ.items()
           if k.upper() in PROBE_ENV_KEEP or k.upper().startswith("LC_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(str(r) for r in roots)
    return env


def _not_literal(node) -> str | None:
    """None when `ast.literal_eval` accepts the node — a number, negative too, a string,
    bytes, None, True, False, or a tuple, list, set or dict of those — else what it is."""
    try:
        ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return ast.unparse(node)[:60]
    return None


def safe_probe(expression: str, function: str | None = None) -> tuple:
    """The expression as a syntax tree, read before anything runs → (the call rendered
    back from the tree, None) or (None, "probe_unsafe: <which rule>").

    Measured 2026-10-02 (audit O-S-1): the only checks on the model's expression were
    one line, names the function, fix line inside the chunk — and
    `m.f(open(...).write(os.getcwd()) or 1)` passed all three and ran in the checkout.
    What is accepted now is exactly one call on `m` to the function under probe, every
    positional argument and keyword value a literal. No other call, no name, no attribute
    chain, no subscript, no lambda, no comprehension, no f-string, no starred or `**`
    argument, no dunder. A method call needs `m.Holder().beta()`, a nested call, and is
    refused with the rest: the price of a probe that cannot be told from `m.run_share(...)`.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except (SyntaxError, ValueError) as exc:
        detail = str(exc).splitlines()[0][:80] if str(exc) else "empty"
        return None, f"probe_unsafe: not one Python expression ({detail})"
    call = tree.body
    if not isinstance(call, ast.Call):
        return None, f"probe_unsafe: not a call ({type(call).__name__})"
    func = call.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "m"):
        return None, f"probe_unsafe: calls {ast.unparse(func)[:60]}, not a function of m"
    if func.attr.startswith("__"):
        return None, f"probe_unsafe: a dunder attribute (m.{func.attr})"
    if function is not None and func.attr != function:
        return None, f"probe_unsafe: does not call {function} (m.{func.attr})"
    for i, node in enumerate(call.args, 1):
        if isinstance(node, ast.Starred):
            return None, f"probe_unsafe: argument {i} is starred"
        why = _not_literal(node)
        if why:
            return None, f"probe_unsafe: argument {i} is not a literal ({why})"
    for kw in call.keywords:
        if kw.arg is None:
            return None, "probe_unsafe: `**` unpacking"
        why = _not_literal(kw.value)
        if why:
            return None, f"probe_unsafe: keyword {kw.arg} is not a literal ({why})"
    return ast.unparse(call), None


# The few builtins a one-line boundary or arithmetic fix reaches for. Nothing here
# opens, imports, evaluates or reflects.
FIX_BUILTINS = frozenset({
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "float", "frozenset", "int",
    "isinstance", "len", "list", "max", "min", "pow", "range", "reversed", "round", "set",
    "sorted", "str", "sum", "tuple", "zip", "self", "cls"})


def _names(source: str) -> set:
    """Every identifier in a piece of source, read lexically — partial code tokenizes."""
    out = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.NAME:
                # The form Python runs: it normalises identifiers to NFKC before
                # executing them, so the check must compare the same form it will (F-4).
                out.add(unicodedata.normalize("NFKC", tok.string))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        pass
    return out


def safe_replacement(replacement: str, function_source: str) -> str | None:
    """Why the model's replacement line may not be written into the scratch, or None.

    The expression is read as a syntax tree; the line that replaces the suspected one is
    code as well, and it runs — in the scratch, under the allowlisted environment, but with
    the operator's privileges: `import os; os.system(...)` reads `~/.ssh` from a scratch as
    easily as from a checkout, and an environment without the token does not stop a line
    that opens the file the token lives in. So a fix may use only what the function already
    uses: every name in it is a keyword, a name that appears in the function's own source,
    or one of a few builtins a boundary fix reaches for. No `import`, no name the function
    never mentioned, no dunder attribute it did not already have, no f-string (its fields
    are code a lexical read cannot see before 3.12), one physical line. Conservative on
    purpose: a refused fix leaves the claim a hypothesis, which is what it was.
    """
    if "\n" in replacement or "\r" in replacement:
        return "fix_unsafe: more than one line"
    known = _names(function_source)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(replacement.strip() + "\n").readline))
    except (tokenize.TokenError, SyntaxError, IndentationError) as exc:
        return f"fix_invalid: {str(exc)[:80]}"
    after_dot = False
    for tok in tokens:
        kind = tokenize.tok_name.get(tok.type, "")
        if kind == "FSTRING_START" or (tok.type == tokenize.STRING
                                       and re.match(r"(?i)[rbu]*f", tok.string)):
            return "fix_unsafe: an f-string — its fields are code this check cannot read"
        if tok.type == tokenize.NAME:
            # NFKC, as `_names` above and as the interpreter: a fullwidth or
            # mathematical spelling of `__globals__` or `eval` tokenises as itself but
            # runs as the ASCII name, so the raw spelling must not be what is judged (F-4).
            name = unicodedata.normalize("NFKC", tok.string)
            if name in ("import", "from"):
                return f"fix_unsafe: `{name}` in a one-line fix"
            if after_dot:
                if name.startswith("__") and name not in known:
                    return f"fix_unsafe: reaches the dunder `{name}`"
            elif not (keyword.iskeyword(name) or name in known or name in FIX_BUILTINS):
                return f"fix_unsafe: introduces `{name}`, a name the function never uses"
        after_dot = tok.type == tokenize.OP and tok.string == "."
    return None


def module_name(repo: Path, rel: str) -> str:
    """The import path of a file, or "" when it is not importable from the repo root."""
    parts = list(Path(rel).with_suffix("").parts)
    if not parts or parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return ""
    # `src/pkg/mod.py` imports as `pkg.mod` when `src` is a source root
    if parts[0] in ("src", "lib") and (repo / parts[0] / "__init__.py").exists() is False:
        parts = parts[1:]
    return ".".join(parts)


def source_root(repo: Path, rel: str) -> Path:
    return repo / "src" if rel.startswith("src/") and (repo / "src").is_dir() else repo


def import_roots(repo: Path) -> list:
    """The directories the project's own test runner puts on the import path — pytest's
    `pythonpath`, from pytest.ini, tox.ini, setup.cfg or pyproject.toml — relative to the
    repository, existing ones only, in the order declared."""
    found: list = []
    for name, section in (("pytest.ini", "pytest"), ("tox.ini", "pytest"),
                          ("setup.cfg", "tool:pytest")):
        cfg = repo / name
        if not cfg.is_file():
            continue
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(cfg, encoding="utf-8")
            if parser.has_option(section, "pythonpath"):
                found += parser.get(section, "pythonpath").split()
        except (configparser.Error, OSError, UnicodeDecodeError):
            continue
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib              # Python 3.11+; the ini files above still count on 3.9
            doc = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:               # noqa: BLE001 — a config we cannot read adds nothing
            doc = {}
        value = (((doc.get("tool") or {}).get("pytest") or {}).get("ini_options") or {}) \
            .get("pythonpath")
        found += value.split() if isinstance(value, str) else \
            [str(v) for v in value] if isinstance(value, list) else []
    out: list = []
    for entry in found:
        entry = entry.strip().rstrip("/")
        if entry and entry != "." and (repo / entry).is_dir() and entry not in out:
            out.append(entry)
    return out


def probe_root(repo: Path, rel: str) -> tuple:
    """(import root, module name) a counterfactual imports a file through.

    Measured on Sales (2026-09-18): `core/src/sales_core/cli.py` was imported as
    `core.src.sales_core.cli` from the repository root, so the package's own imports of
    `sales_core.*` fell through to an editable install of another worktree — one without
    the module the day's commits had added — and every one of the night's probes failed
    before it could prove anything. The root is the project's own: the deepest `pythonpath`
    its test runner declares that contains the file; else, for a file inside a package, the
    first directory above the package chain; else the repository, as before.
    """
    path = Path(rel)
    declared = [Path(r) for r in import_roots(repo)
                if path.parts[:len(Path(r).parts)] == Path(r).parts]
    if declared:
        base = max(declared, key=lambda r: len(r.parts))
    elif path.name == "__init__.py" or (repo / path.parent / "__init__.py").is_file():
        base = path.parent
        while base.parts and (base == path.parent and path.name == "__init__.py"
                              or (repo / base / "__init__.py").is_file()):
            base = base.parent
    else:
        return source_root(repo, rel), module_name(repo, rel)
    parts = list(path.relative_to(base).with_suffix("").parts) if base.parts \
        else list(path.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return (repo / base if base.parts else repo), ".".join(parts)


def scratch_copy(repo: Path, into: Path) -> bool:
    """A copy of the tree that runs its own code — the discipline §3.5 demands, done by
    the harness so the model cannot get it wrong. Returns False when the tree is too
    large to copy, which is a refusal, not a silent skip."""
    total = 0
    for path in repo.rglob("*"):
        if any(part in COPY_SKIP or any(fnmatch.fnmatch(part, pat) for pat in SECRET_SKIP)
               for part in path.relative_to(repo).parts):
            continue
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                pass
            if total > MAX_COPY_BYTES:
                return False
    # `symlinks=True`: copy a link as a link, never the bytes it points at. The default
    # followed it, so a link to `~/.aws/credentials` materialised the secret in the scratch
    # (gate F-1, 2026-10-03). Then drop any link that resolves OUTSIDE the tree — a link in
    # is scratch's own file; a link out is a door to the real filesystem, which the probe
    # runs with no OS sandbox to stop. A dangling link is removed too: it names a path, and
    # the path may fill in later.
    shutil.copytree(repo, into, dirs_exist_ok=True, symlinks=True,
                    ignore=shutil.ignore_patterns(*COPY_SKIP, *SECRET_SKIP))
    into_real = into.resolve()
    for link in into.rglob("*"):
        if not link.is_symlink():
            continue
        target = link.resolve()
        if target == into_real or into_real in target.parents:
            continue            # a link that stays inside the copy
        link.unlink()
    return True


def run_probe(python: str, root: Path, module: str, expression: str,
              extra_paths=()) -> tuple:
    """Evaluate one expression against one tree → (value_json, error).

    The tree is put first on `PYTHONPATH` and the module's resolved file is checked to be
    inside it before the expression is trusted: a scratch that imports the original source
    makes every injection read as a no-op, and this project measured 0 of 4 defects caught
    without that check. Bytecode writing is off and `__pycache__` swept, because CPython
    validates a cached file on mtime-in-seconds plus size and a same-size edit within one
    second re-runs the old bytecode.

    This is the only path to a child process, so it reads the expression as a syntax tree
    itself (`safe_probe`, any function of `m`) and refuses before anything starts: a
    caller that skipped the check cannot run arbitrary code. The environment is the
    allowlist in `probe_env`, never the parent's (audit 2026-10-02, O-S-1).
    """
    call, why = safe_probe(expression)
    if why:
        return None, why
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    # Compare resolved paths on both sides: on macOS `/var` is a symlink to `/private/var`,
    # so a correct import fails a naive prefix check and every probe reads as unavailable.
    resolved = os.path.realpath(str(root))
    script = (
        "import json, os, sys\n"
        f"import {module} as m\n"
        f"assert os.path.realpath(m.__file__).startswith({resolved!r}), "
        "'imported ' + m.__file__\n"
        f"print('<<<' + json.dumps({call}, default=repr) + '>>>')\n")
    env = probe_env([root, *extra_paths])
    try:
        proc = subprocess.run([python, "-c", script], cwd=str(root), env=env,
                              capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)[:200]
    out = proc.stdout
    if "<<<" in out and ">>>" in out:
        try:
            return json.loads(out.split("<<<", 1)[1].split(">>>", 1)[0]), None
        except json.JSONDecodeError as exc:
            return None, f"probe printed unparseable JSON: {exc}"
    return None, (proc.stderr.strip().splitlines() or ["no output"])[-1][:200]


def counterfactual(model: Model, repo: Path, chunk: Chunk, claim: dict,
                   python: str) -> dict | None:
    """Flip the suspected line in a scratch copy and watch the value follow.

    Three outcomes, all of them useful: the value flips to what the model predicted
    (`proven`), the value does not move (`disproven` — the claim is withdrawn before it is
    ever filed), or the probe cannot run (unchanged, still a hypothesis).

    Nothing here runs in the checkout. Measured 2026-10-02 (audit O-S-1, `probe_small2.py`):
    the "before" run executed the model's expression with `cwd=<repo>` and the real tree on
    `PYTHONPATH`, and the marker it wrote read `<the checkout> env_has_token=True`. Now the
    tree is copied once, the original is probed in the copy, the copy's file is patched, and
    the patched copy is probed — and the expression is a syntax tree the harness has read
    (`safe_probe`) before the copy is even made. Every outcome is a record: the expression
    (scrubbed, so a key the model copied out of a docstring never lands in a file), the
    scratch it ran in or None, the status and the reason.
    """
    def refused(reason: str, expression: str = "", scratch: str | None = None) -> dict:
        return {"status": "unavailable", "reason": scrub_secrets(reason)[:300],
                "expression": scrub_secrets(expression)[:200], "scratch": scratch}

    root_rel, module = probe_root(repo, chunk.path)
    if not module:
        return refused(f"{chunk.path} is not importable from the repository root")
    answer = model.ask_json(PROBE_Q.format(path=chunk.path, source=chunk.numbered(),
                                           mechanism=claim["mechanism"], module=module,
                                           function=chunk.name), max_tokens=700)
    if not answer:
        return refused("the model did not answer with JSON")
    expression = str(answer.get("expression") or "").strip()
    replacement = answer.get("fix_replacement")
    line = answer.get("fix_line")
    if not expression or "\n" in expression or not isinstance(replacement, str):
        return refused("the probe was not one expression and one replacement line", expression)
    if chunk.name not in expression:
        # A small model copies the schema's example instead of writing a call: measured on
        # boltons, where every probe came back as `m.some_function(1, 2)` and failed on an
        # attribute that does not exist. The expression must reach the function it is about.
        return refused(f"the probe does not call {chunk.name}: {expression[:80]}", expression)
    if not isinstance(line, (int, float)) or not (chunk.start <= int(line) <= chunk.end):
        return refused(f"the line to flip ({line}) is outside {chunk.name}", expression)
    line = int(line)
    call, why = safe_probe(expression, chunk.name)
    if why:
        return refused(why, expression)
    # The replacement line is code too, and it runs: the same wall, before the copy.
    unsafe_fix = safe_replacement(replacement, chunk.source)
    if unsafe_fix:
        return refused(unsafe_fix, call)

    with tempfile.TemporaryDirectory(prefix="verdict-cf-") as tmp:
        scratch = Path(tmp) / "tree"
        where = str(scratch)
        if not scratch_copy(repo, scratch):
            return refused("the tree is too large to copy", call)
        scratch_root = scratch / root_rel.relative_to(repo) if root_rel != repo else scratch
        others = [scratch / r for r in import_roots(repo)]
        before, err = run_probe(python, scratch_root, module, call, others)
        if err:
            return refused(f"probe failed on the original: {err}", call, where)
        target = scratch / chunk.path
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if not (1 <= line <= len(lines)):
            return refused("the line to flip is outside the file", call, where)
        original_line = lines[line - 1]
        lines[line - 1] = replacement
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        after, err = run_probe(python, scratch_root, module, call, others)
        if err:
            return refused(f"probe failed on the scratch: {err}", call, where)

    flipped = before != after
    return {
        "status": "proven" if flipped else "disproven",
        "expression": scrub_secrets(call)[:200], "scratch": where,
        "before": before, "after": after,
        "line": line, "was": original_line.strip()[:160], "now": replacement.strip()[:160],
        "reason": ("the value follows the line: flipping it changed the result"
                   if flipped else
                   "the value did not move when the line was flipped — the line is not the "
                   "cause, whatever else may be true"),
    }
