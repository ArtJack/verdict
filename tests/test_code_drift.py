"""A stored verdict ages by commits, not only by hours.

This file exists because of a measured failure on this repository. Its own
`.qa/state.json`, four hours old, named three open Major findings — all three
fixed and merged in the six commits since. Nothing was corrupt; only a run
resolves findings. But every consumer read the state as current, because the
only staleness signal in the product was a seven-day clock and the state was
not old. It was behind. These tests hold the distinction.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
from state import code_drift  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "report_open_findings.py"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """A scratch repo with three commits on main and a diverged branch."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    shas = []
    for i in range(3):
        (r / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"c{i}")
        shas.append(git(r, "rev-parse", "HEAD"))
    return r, shas


def test_head_is_current(repo):
    r, shas = repo
    d = code_drift(r, shas[-1])
    assert d["status"] == "current" and d["commits"] == 0


def test_counts_commits_behind(repo):
    r, shas = repo
    assert code_drift(r, shas[0])["commits"] == 2
    assert code_drift(r, shas[0])["status"] == "behind"
    assert code_drift(r, shas[1])["commits"] == 1


def squash_merge(r, branch):
    """What every PR in this repo does: same tree, new commit, broken ancestry."""
    git(r, "checkout", "-q", "main")
    subprocess.run(["git", "-C", str(r), "merge", "-q", "--squash", branch],
                   capture_output=True, text=True)
    git(r, "commit", "-qm", f"squashed {branch} (#1)")
    return git(r, "rev-parse", "HEAD")


def test_squash_merged_state_is_current_not_diverged(repo):
    """The defect this file failed to catch the first time.

    Every PR in this repository is squash-merged and `.qa/state.json` is
    committed, so the sha a state records stops being an ancestor of main the
    moment its own PR lands. Reporting that as "different code" would fire on
    main immediately, about code that is byte-identical.
    """
    r, _ = repo
    git(r, "checkout", "-q", "-b", "feat")
    (r / "work.txt").write_text("w", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "work")
    feat = git(r, "rev-parse", "HEAD")
    squash_merge(r, "feat")

    assert subprocess.run(["git", "-C", str(r), "merge-base", "--is-ancestor", feat, "HEAD"],
                          capture_output=True).returncode == 1, "precondition: ancestry is broken"
    assert not git(r, "diff", "--stat", feat, "HEAD"), "precondition: content is identical"

    d = code_drift(r, feat)
    assert d["status"] == "current", f"squash merge misread as {d['status']}"
    assert d["commits"] == 0


def test_squash_merged_then_moved_on_reports_the_real_distance(repo):
    r, _ = repo
    git(r, "checkout", "-q", "-b", "feat")
    (r / "work.txt").write_text("w", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "work")
    feat = git(r, "rev-parse", "HEAD")
    squash_merge(r, "feat")
    for i in range(2):
        (r / f"after{i}.txt").write_text("x", encoding="utf-8")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"after{i}")

    d = code_drift(r, feat)
    assert d["status"] == "behind" and d["commits"] == 2, d


def test_diverged_branch_is_not_reported_as_behind(repo):
    """The dangerous case: a verdict measured on code this branch never had."""
    r, shas = repo
    git(r, "checkout", "-q", "-b", "side", shas[0])
    (r / "side.txt").write_text("x", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "side")
    (r / "different.txt").write_text("content main never had", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "divergent content")
    d = code_drift(r, shas[-1])          # main's tip: unreachable AND different
    assert d["status"] == "diverged"
    assert d["commits"] is None, "a diverged verdict has no meaningful distance"


def test_unknown_never_raises_and_never_cries_wolf(repo, tmp_path):
    """A false 'you are behind' trains people to ignore the line."""
    r, _ = repo
    for bad in (None, "", 12345, "not-a-sha"):
        assert code_drift(r, bad)["status"] == "unknown", bad
    assert code_drift(tmp_path / "no-such-dir", "HEAD")["status"] == "unknown"
    assert code_drift(tmp_path, "HEAD")["status"] == "unknown"   # exists, not a repo
    # A well-formed id this complete clone lacks is the one case that is *not*
    # a limit of observation — it is reported as `absent` (VERDICT-F-18). It
    # still never raises, and garbage above still never alarms.
    assert code_drift(r, "deadbeef" * 5)["status"] == "absent"


def run_banner(cwd, qa_home):
    env = {k: v for k, v in os.environ.items() if k != "VERDICT_HOME"}
    env["VERDICT_HOME"] = str(qa_home)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd)}),
                          capture_output=True, text=True, env=env).stdout


def seed_state(qa_home, key, sha, stamp=None):
    root = qa_home / key
    root.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({
        "schema_version": "1.3", "project": key, "run_number": 2, "run_type": "delta",
        "verdict": "pass with risks",
        "last_run": {"timestamp_utc": stamp or datetime.now(timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"), "git_sha": sha},
        "findings": [{"id": "X-F-1", "severity": "Major", "status": "open",
                      "title": "a finding that may already be fixed", "age_days": 1}],
    }), encoding="utf-8")
    return root


def test_banner_warns_when_the_code_moved_on(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[0])
    out = run_banner(r, tmp_path / "qa")
    assert "Measured 2 commits ago" in out, out
    assert out.index("Measured 2 commits ago") < out.index("open finding"), \
        "the qualification must precede what it qualifies"


def test_banner_is_quiet_when_current(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[-1])
    out = run_banner(r, tmp_path / "qa")
    assert "Measured" not in out and "different code" not in out, out
    assert "open finding" in out, "the rest of the banner still renders"


def test_banner_singular_commit(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[1])
    assert "Measured 1 commit ago" in run_banner(r, tmp_path / "qa")


def test_banner_warns_on_divergence(repo, tmp_path):
    r, shas = repo
    git(r, "checkout", "-q", "-b", "side", shas[0])
    seed_state(tmp_path / "qa", r.name, shas[-1])
    assert "not in this branch's history" in run_banner(r, tmp_path / "qa")


def test_future_timestamp_is_named_not_rendered_as_negative_days(repo, tmp_path):
    """A state that misreports when it was written is a state to distrust."""
    ahead = (datetime.now(timezone.utc) + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[-1], stamp=ahead)
    out = run_banner(r, tmp_path / "qa")
    assert "in the future" in out, out
    assert "-" not in out.splitlines()[0], f"negative day count leaked: {out.splitlines()[0]}"


def test_intermediate_commit_of_a_squashed_branch_is_diverged(repo):
    """Not a gap in the squash fix — the tested content really is gone.

    The fix covers a squash that preserved the tested tree. When a branch gains
    further commits before squashing, the tree that was measured exists nowhere
    in the resulting history, so the verdict describes code this branch does not
    have. `diverged` is the honest answer, and at the gate it means exit 5.
    """
    r, _ = repo
    git(r, "checkout", "-q", "-b", "feat")
    (r / "first.txt").write_text("1", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "first")
    measured = git(r, "rev-parse", "HEAD")     # a QA run happens here
    (r / "second.txt").write_text("2", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "second")          # then the branch moves on
    squash_merge(r, "feat")

    assert code_drift(r, measured)["status"] == "diverged"


# --- absent is an observation; unknown is a limit of observation ------------
#
# VERDICT-F-18, filed by Verdict on itself from a fresh clone: the run-3 base
# commit was a squash-merged branch head that no longer existed anywhere, the
# clone was complete, and `unknown` swallowed it — so a 2-day-old verdict was
# shown with no hint its base commit was unlocatable. A shallow clone that
# cannot see far enough is a different fact and stays `unknown`.

def test_a_complete_clone_missing_the_commit_is_absent_not_unknown(repo):
    r, _ = repo
    d = code_drift(r, "0" * 40)
    assert d["status"] == "absent", d
    assert d["head"], "HEAD was resolvable; only the recorded commit was not"


def test_a_shallow_clone_that_cannot_see_the_commit_stays_unknown(repo, tmp_path):
    r, shas = repo
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", r.as_uri(), str(shallow)],
                   check=True, capture_output=True)
    assert git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    assert code_drift(shallow, shas[0])["status"] == "unknown"


def test_banner_names_a_commit_the_repository_does_not_contain(repo, tmp_path):
    r, _ = repo
    seed_state(tmp_path / "qa", r.name, "0" * 40)
    out = run_banner(r, tmp_path / "qa")
    assert "does not contain" in out and "never had" in out, out
