"""What a team-mode run leaves in `.qa/` is either the record or ignored.

`findings.prev/` (0.84.0) and `usage.jsonl` (0.89.0) were written into every team-mode root
and listed in no `.gitignore`, so each run left them untracked — and `usage.jsonl` names the
machine that ran it, down to the local tier's gateway address, one `git add .qa` from a
public repository (found 2026-10-15, after run 16 of this one). This drives two runs through
the harness in a team root holding this repository's own `.qa/.gitignore`, and requires every
file they leave to be a name the record keeps or one git ignores: a file the harness starts
writing tomorrow fails here until somebody decides which it is.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from verdict_mcp.harness import facts_main, finalize_main

REPO = Path(__file__).resolve().parent.parent
# The record — what a team commits. The maintainer's ledgers and the issue ledger are in it
# although these two runs write none of them.
RECORD = {".gitignore", "profile.md", "state.json", "runs.jsonl", "outcomes.json", "reports",
          "findings", "test-ids.txt", "hygiene-items.json", "hygiene-ledger.json",
          "questions.json", "accepted.json", "answers.json", "issues.json", "lessons.md"}
# What a run passes through, and the bill. The coverage names are listed only for roots that
# ran 0.53–0.57; the harness writes those files to a temporary directory now.
SCRATCH = {"facts.json", "judgment.json", "state.json.prev", "run-in-progress.json",
           "findings.prev", "usage.jsonl", "coverage.rc", "coverage.db", "coverage.json"}
JUDGMENT = {"verdict": "pass with risks", "isolation_check": {"result": "pass", "method": "none"},
            "release_blockers": [], "not_tested": ["everything"]}


def _git(repo, *args) -> str:
    # Hermetic: a developer's global excludes file (`*.json`, say) must not decide what a
    # team root ignores.
    empty = repo.parent / "no-excludes"
    empty.touch()
    return subprocess.run(["git", "-c", f"core.excludesFile={empty.as_posix()}", *args],
                          cwd=str(repo), check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout


def _team_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("a = 1\n", encoding="utf-8")
    # One quoted word: `cmd /c` strips the outer pair when a line carries more.
    (repo / "gate.py").write_text("print('1 passed in 0.01s')\n", encoding="utf-8")
    qa = repo / ".qa"
    qa.mkdir()
    shutil.copyfile(REPO / ".qa" / ".gitignore", qa / ".gitignore")
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: \"{sys.executable}\" gate.py\n---\n\n"
        "# QA profile — scratch\n\nProject-Key: scratch\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "x@y")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo, qa


def _run(repo, qa, judgment, finding=None):
    """One run, facts to finalize → the id of the finding it filed as a file, if any."""
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    fid = None
    if finding:
        fid = json.loads((qa / "facts.json").read_text(encoding="utf-8"))["next_finding_id"]
        (qa / "findings").mkdir(exist_ok=True)
        (qa / "findings" / f"{fid}.json").write_text(
            json.dumps({"id": fid, **finding}), encoding="utf-8")
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return fid


def _entries(listing: str) -> set:
    """`.qa/findings/F-1.json` → `findings`: the name directly under the root."""
    return {line.split("/")[1] for line in listing.splitlines() if line.startswith(".qa/")}


def test_two_team_runs_leave_only_the_record_and_what_git_ignores(tmp_path):
    repo, qa = _team_repo(tmp_path)
    fid = _run(repo, qa, JUDGMENT, finding={
        "title": "a is one", "severity": "Major", "priority": "P1", "status": "open",
        "failure_classification": "REAL_DEFECT", "confidence": "proven",
        "evidence": ["src/app.py:1 — a = 1"]})
    # The second run moves the first one's finding files aside and appends a second bill.
    _run(repo, qa, dict(JUDGMENT, findings=[], still_open=[fid]))
    assert (qa / "findings.prev" / f"{fid}.json").is_file()
    assert len((qa / "usage.jsonl").read_text(encoding="utf-8").splitlines()) == 2

    kept = _entries(_git(repo, "ls-files", "--cached", "--others", "--exclude-standard", ".qa"))
    ignored = _entries(_git(repo, "ls-files", "--others", "--ignored", "--exclude-standard",
                            "--directory", ".qa"))
    assert kept <= RECORD, f"a run wrote {sorted(kept - RECORD)} into the team root, and " \
                           "neither the record nor .qa/.gitignore names it"
    assert ignored <= SCRATCH, f".qa/.gitignore hides {sorted(ignored - SCRATCH)}"
    assert {"findings.prev", "usage.jsonl"} <= ignored
    assert {"state.json", "runs.jsonl", "outcomes.json", "reports"} <= kept, \
        "the record itself must reach git"


def test_the_docs_a_team_reads_name_what_the_root_ignores():
    """The README tells a team what to ignore, and `/verdict:baseline team` writes the file.
    Both must list what this repository's own root ignores, or a team's first commit of
    `.qa/` publishes what this one keeps out."""
    ours = {line.strip().rstrip("/") for line in
            (REPO / ".qa" / ".gitignore").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")}
    current = ours - {"coverage.rc", "coverage.db", "coverage.json"}
    assert current == SCRATCH - {"coverage.rc", "coverage.db", "coverage.json"}
    for doc in ("README.md", "commands/baseline.md"):
        text = (REPO / doc).read_text(encoding="utf-8")
        missing = sorted(n for n in current if f"`{n}`" not in text and f"`{n}/`" not in text)
        assert not missing, f"{doc} does not name {missing}"
