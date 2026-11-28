"""What the `directory` branch keeps, now that most of the plugin needs a Verified organization.

From 0.93.1 (2026-10-30) the Claude directory refused every Verdict version. Command hooks,
and every file that is not Markdown, text, JSON, YAML or an image, are accepted only from a
Verified organization; two credential rules and a package-manager rule apply to everyone.
Verdict asks to be Verified, which keeps its hooks and its Python. Until then, and after,
the branch ships less: nothing the plugin never runs or reads
(`.github/directory_branch.py`, EXCLUDED and NOT_RUN).

Two promises hold the trimmed branch:

* every module that a hook, the agent, a command or a skill can reach is still on it, found
  by walking the imports from everything they name, so the plugin never meets a missing
  file. The walk is checked by running the trimmed tree itself;
* what 0.95.0's review flagged, and the plugin does not need, stays off.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("directory_branch", REPO / ".github" / "directory_branch.py")
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

PROMPTS = [*sorted((REPO / "agents").glob("*.md")), *sorted((REPO / "commands").glob("*.md")),
           *sorted((REPO / "skills").glob("*/SKILL.md"))]
HOOK_RUNS = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+\.py)")
NAMED_MODULE = re.compile(r"src/verdict_mcp/([a-z_]+)\.py")
NAMED_CLI = re.compile(r"\bverdict-[a-z]+\b")
SCRIPT = re.compile(r'^(verdict-[a-z]+)\s*=\s*"verdict_mcp\.([a-z_]+):', re.M)


def tracked():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout: the branch is built from tracked files")
    return [p for p in out.decode("utf-8").split("\0") if p]


def modules():
    """Every module the plugin could load, by the name an import uses: src/verdict_mcp/
    and the hooks' own helpers."""
    found = {p.stem: p for p in (REPO / "src" / "verdict_mcp").glob("*.py")}
    found.update({p.stem: p for p in (REPO / "hooks").glob("*.py")})
    return found


def entry_points():
    """What the plugin runs by name: the hooks' commands, the modules and the commands
    (`verdict-facts` …) the agent, the commands and the skills tell Claude to run."""
    scripts = dict(SCRIPT.findall((REPO / "pyproject.toml").read_text(encoding="utf-8")))
    hooks = (REPO / "hooks" / "hooks.json").read_text(encoding="utf-8")
    start = {Path(p).stem for p in HOOK_RUNS.findall(hooks)}
    for prompt in PROMPTS:
        text = prompt.read_text(encoding="utf-8")
        start.update(NAMED_MODULE.findall(text))
        start.update(scripts[c] for c in NAMED_CLI.findall(text) if c in scripts)
    return start


def imported(path: Path):
    """Every name an import in `path` could load: `import clock`, `from .state import x`,
    `from state import x` (a module run as a script), `from verdict_mcp import harness`."""
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            yield from (a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if base:
                yield base
            yield from (f"{base}.{a.name}" if base else a.name for a in node.names)


def reached():
    known = modules()
    seen, todo = set(), sorted(entry_points())
    while todo:
        name = todo.pop()
        if name in seen or name not in known:
            continue
        seen.add(name)
        for dotted in imported(known[name]):
            parts = [p for p in dotted.split(".") if p]
            if parts[:1] == ["verdict_mcp"]:
                parts = parts[1:]
            todo.extend(parts[:1])
    return seen


def test_every_module_the_plugin_can_reach_is_on_the_branch():
    shipped = {p for p in tracked() if db.shipped(p)}
    known = modules()
    reach = reached()
    assert {"harness", "gate", "validate", "state", "hygiene_patterns", "enforce_bash_scope"} <= reach, (
        "the walk stopped finding what the plugin runs, so this test would pass on anything")
    missing = sorted(m for m in reach if known[m].relative_to(REPO).as_posix() not in shipped)
    assert missing == [], "the directory would get a plugin that imports files it lacks: " + ", ".join(missing)


def test_what_the_review_flagged_and_the_plugin_never_reads_stays_off():
    paths = set(tracked())
    flagged = ("src/verdict_mcp/runner_env.py", "docs/nightly.md",                # credential findings
               "AGENTS.md", "pyproject.toml", "docs/demo.svg", "scripts/check_structure.py")
    for path in flagged:
        assert path in paths and not db.shipped(path), path
    # Off for any repository layout: names the directory reads as an agent's own rules
    # or a package manager's configuration, and SVG.
    named = {"agents.md", "claude.md", "claude.local.md", "pyproject.toml", "setup.py", "setup.cfg",
             "requirements.txt", "package.json", "package-lock.json", "pipfile", "poetry.lock", "uv.lock"}
    shipped_named = sorted(p for p in paths if db.shipped(p)
                           and (p.rsplit("/", 1)[-1].lower() in named or p.lower().endswith(".svg")))
    assert shipped_named == []


def test_the_readme_names_no_key_variable():
    """0.95.0's review counted the README among the files that use a credential from the
    user's machine. It named the gateway's variables and an env file; the guide that needs
    them, docs/nightly.md, stays on GitHub."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert re.findall(r"ANTHROPIC_[A-Z_]+|--env-file", text) == []


def test_the_trimmed_tree_runs(tmp_path):
    """The plugin, as the directory gets it, started the way Claude Code starts it."""
    root = tmp_path / "plugin"
    for rel in (p for p in tracked() if db.shipped(p)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    env = dict(os.environ, VERDICT_HOME=str(tmp_path / "home"), CLAUDE_PLUGIN_ROOT=str(root))
    env.pop("VERDICT_STRICT", None)

    def run(*args, stdin=""):
        done = subprocess.run([sys.executable, *map(str, args)], input=stdin, capture_output=True,
                              encoding="utf-8", env=env, cwd=str(tmp_path))
        assert done.returncode == 0, f"{args}: exit {done.returncode}\n{done.stderr[-800:]}"

    for hook in json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"].values():
        for group in hook:
            for h in group["hooks"]:
                script = HOOK_RUNS.search(h["command"]).group(1)
                run(root / script, stdin="{}")
    src = root / "src" / "verdict_mcp"
    run(src / "harness.py", "facts", "--help")
    run(src / "harness.py", "finalize", "--help")
    for module in ("gate", "validate", "questions", "accept", "replay"):
        run(src / f"{module}.py", "--help")
