"""The CI surfaces a stranger copies: the Action's run mode, the eval job, the README snippet.

Three findings of the 2026-10-02 audit, each a text fact about a workflow file:
the Action's run mode copied in the agent file and never registered a hook, so
`VERDICT_STRICT=1` armed nothing under `--dangerously-skip-permissions`
(D-D-11); the weekly eval piped through `tee` without `pipefail` and reported
success with no API key, never producing a score (D-D-2); the README's
`uses: ArtJack/verdict@v0` named a ref that did not exist (D-D-1).
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
EVAL = (ROOT / ".github" / "workflows" / "eval.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_the_actions_run_mode_loads_the_whole_plugin_and_runs_the_tester_directly():
    assert '--plugin-dir "${{ github.action_path }}"' in ACTION
    assert "--agent verdict" in ACTION
    assert "--strict-mcp-config" in ACTION
    assert "sed -e" not in ACTION, "the agent file is no longer copied in by hand"
    assert "VERDICT_MIN_RUN_NUMBER" in ACTION, "a crashed pass must not re-serve the committed state"


def test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with():
    """`hooks.json` says `python3`; on a stock Mac that is 3.9. The matrix ran 3.10 and
    3.13, and the floor was an AST shape check (D-D-26)."""
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci[ci.index("hooks-floor:"):ci.index("delta-diff-freshness:")]
    assert "--python 3.9" in job and "--no-project" in job
    for name in ("test_hooks.py", "test_hooks_0903.py", "test_hooks_pens.py",
                 "test_hooks_links.py", "test_stop_hook.py", "test_validate_hook_scope.py"):
        assert name in job, f"{name} is not run on the floor"


def test_the_eval_job_cannot_report_green_without_a_key():
    step = EVAL[EVAL.index("- name: Run the eval"):]
    assert "shell: bash" in step.split("run: |")[0], "pipefail comes with shell: bash"
    assert "ANTHROPIC_API_KEY is not set" in step


def test_the_readme_ci_snippet_names_a_ref_the_release_maintains():
    m = re.search(r"uses: ArtJack/verdict@(v\d+)", README)
    assert m, "the README shows a `uses:` line"
    version = re.search(r'^version = "(\d+)\.', (ROOT / "pyproject.toml").read_text(encoding="utf-8"),
                        re.M).group(1)
    assert m.group(1) == f"v{version}", "the snippet names the current major version"
    assert 'git push -f origin "$major"' in RELEASE, "release.yml moves the major tag"


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))


def _run_scripts(text):
    """Each `run:` script in a workflow file: the key's own line and everything indented under it."""
    lines, scripts = text.splitlines(), []
    for i, line in enumerate(lines):
        m = re.match(r"( *)(- )?run:(.*)", line)
        if not m:
            continue
        indent = len(m.group(1)) + len(m.group(2) or "")
        body = [m.group(3)]
        for following in lines[i + 1:]:
            if following.strip() and len(following) - len(following.lstrip()) <= indent:
                break
            body.append(following)
        scripts.append("\n".join(body))
    return scripts


def test_every_action_is_pinned_to_a_commit():
    """A tag or a branch can move after it was read. `release.yml`'s publish step holds the
    project's PyPI identity, and the same reasoning already pinned `mcp-publisher` to a
    checksum (VERDICT-F-73). Dependabot moves the pins, in a pull request someone reads."""
    for path in [*WORKFLOWS, ROOT / "action.yml"]:
        for ref in re.findall(r"^\s*(?:- )?uses:\s*(\S+)", path.read_text(encoding="utf-8"), re.M):
            if not ref.startswith("./"):
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), f"{path.name}: {ref}"


def test_no_workflow_grants_write_at_the_top():
    """Write access goes to the one job that needs it. A workflow with no `permissions:` block
    takes whatever the repository's default happens to be."""
    for path in WORKFLOWS:
        top = re.search(r"^permissions:\n((?:  .*\n)+)", path.read_text(encoding="utf-8"), re.M)
        assert top, f"{path.name} has no top-level permissions"
        assert "write" not in top.group(1), f"{path.name} grants write to every job"


def test_no_run_script_interpolates_what_a_caller_typed():
    """`${{ inputs.x }}` in a `run:` is pasted into the script before the shell starts, so a
    value with a quote in it is code. It reaches the script through `env:` instead."""
    for path in [*WORKFLOWS, ROOT / "action.yml"]:
        for script in _run_scripts(path.read_text(encoding="utf-8")):
            assert not re.search(r"\$\{\{[^}]*(github\.event|inputs\.)", script), \
                f"{path.name}: {script[:80]}"


# ── what the suite may evaluate before a test starts ──────────────────────

# Absent from the `os` module on Windows. Touching one of these where it is
# evaluated at import time raises AttributeError, which is a collection error:
# the whole module fails, not one test.
_UNIX_ONLY = frozenset({
    "geteuid", "getuid", "getegid", "getgid", "getgroups", "getlogin",
    "fork", "forkpty", "uname", "setuid", "seteuid", "setgid", "chown",
    "getpgid", "getsid", "nice", "getpriority", "setpriority",
})


def _import_time_expressions(tree):
    """Every expression the interpreter evaluates while importing the module.

    A decorator runs when its `def` is reached, and a module-level statement when
    the line is reached. A function body does not.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield from node.decorator_list
        else:
            yield node


def _unguarded_unix_only(expr):
    """Unix-only `os.<name>` calls in `expr` that nothing in `expr` guards."""
    names = {n.attr for n in ast.walk(expr)
             if isinstance(n, ast.Attribute) and n.attr in _UNIX_ONLY
             and isinstance(n.value, ast.Name) and n.value.id == "os"}
    if not names:
        return set()
    flat = ast.unparse(expr).replace(" ", "")
    guarded = "hasattr(os," in flat or "os.name" in flat or "sys.platform" in flat
    return set() if guarded else names


def test_nothing_the_suite_evaluates_at_import_is_absent_on_windows():
    """`ci.yml` runs the suite on `windows-latest`, and a `skipif` condition is evaluated
    when the decorator is reached, not when the test runs. So

        @pytest.mark.skipif(os.geteuid() == 0, reason="root reads unreadable files")

    is not a skip on Windows — it is an AttributeError that fails the module's whole
    collection. It shipped in `tests/test_census.py` on 2026-11-04 and took both Windows
    jobs of PR #180 down in 28 seconds, while every gate on the author's mac was green:
    the species `docs/silent-failures.md` files as "code that only runs on the interpreter
    you tested with". Guard the call — `hasattr(os, "geteuid") and os.geteuid() == 0`, as
    `tests/test_stop_hook.py` does, or an `os.name` test — or move it inside the body.
    """
    assert "windows-latest" in CI, "the premise of this test is gone; re-read it"
    offenders = {}
    for path in sorted([*(ROOT / "tests").glob("*.py"),
                        *(ROOT / "src" / "verdict_mcp").glob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for expr in _import_time_expressions(tree):
            for name in _unguarded_unix_only(expr):
                offenders.setdefault(path.name, set()).add(f"os.{name}")
    assert not offenders, f"evaluated at import and missing on Windows: {offenders}"
