"""The CI surfaces a stranger copies: the Action's run mode, the eval job, the README snippet.

Three findings of the 2026-10-02 audit, each a text fact about a workflow file:
the Action's run mode copied in the agent file and never registered a hook, so
`VERDICT_STRICT=1` armed nothing under `--dangerously-skip-permissions`
(D-D-11); the weekly eval piped through `tee` without `pipefail` and reported
success with no API key, never producing a score (D-D-2); the README's
`uses: ArtJack/verdict@v0` named a ref that did not exist (D-D-1).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTION = (ROOT / "action.yml").read_text(encoding="utf-8")
EVAL = (ROOT / ".github" / "workflows" / "eval.yml").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


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
                 "test_stop_hook.py", "test_validate_hook_scope.py"):
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
