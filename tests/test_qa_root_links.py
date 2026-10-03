"""The harness writes real files inside the real QA root, and nothing through a link.

0.90.3's report-path rule read the path's spelling. The release's own Opus gate
(2026-10-03) walked around it in a scratch checkout, each case exit 0:

  S1  `.qa/reports` a symlink to the repository; the judgment names `reports/README.md`
      — the report landed on the project's README;
  S2  `reports/x.md` itself a symlink to the README — the same;
  S3  `.qa/reports` a symlink to `src/` — the generated report and INDEX.md landed there;
  S4  `.qa/facts.json` a symlink to `src/app.py` — `verdict-facts` wrote the facts over
      the code under test;
  S5  the judgment names `reports/INDEX.md` — the run index was replaced by a report.

A second hard link to a file is the same thing without a symlink to look for, and
`--qa-root src` is the same thing with no link at all. Every writer of a QA root —
facts, finalize, the local tier, the maintainer's three commands — refuses a root that
holds such a link or that sits among the code. The hooks' half (the Bash guard refuses to
build such a root; the Stop hook does not write through one) is tests/test_hooks_links.py,
which runs on the hooks' own interpreter floor.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

from verdict_mcp import accept, harness, issues, questions, small
from verdict_mcp.harness import facts_main, finalize_main
from verdict_mcp.state import misplaced_root, planted_links, root_refusal
from verdict_mcp.validate import report_outside_reports

from test_local_gate import branch_repo, throwaway_root  # noqa: E402

links = pytest.mark.skipif(os.name == "nt", reason="symlinks need a privilege on Windows")
JUDGMENT = {"verdict": "pass with risks", "findings": [],
            "isolation_check": {"result": "pass", "method": "none"},
            "release_blockers": [], "not_tested": ["everything"]}


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def _make(tmp_path, plant=None):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("# victim README\n", encoding="utf-8")
    (repo / "src" / "app.py").write_text("a = 1\n", encoding="utf-8")
    qa = repo / ".qa"
    qa.mkdir()
    # One quoted word: `cmd /c` strips the outer pair when a line carries more.
    (repo / "gate.py").write_text("print('1 passed in 0.01s')\n", encoding="utf-8")
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: \"{sys.executable}\" gate.py\n---\n\n"
        "# QA profile — scratch\n\nProject-Key: scratch\n", encoding="utf-8")
    if plant:
        plant(repo, qa)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "x@y")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo, qa


def _facts(repo, qa, *extra):
    return facts_main(["--repo", str(repo), "--qa-root", str(qa), *extra])


def _finalize(qa, judgment):
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    return finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")])


class _NoModel:
    name = "none"

    def __getattr__(self, attr):
        raise AssertionError(f"the model was reached ({attr}) on a root the run refused")


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "home"))


@links
def test_s1_a_reports_directory_that_is_a_link_to_the_repository(tmp_path, capsys):
    repo, qa = _make(tmp_path, lambda r, q: os.symlink("..", q / "reports"))
    assert _facts(repo, qa) == 2
    assert "reports → .." in capsys.readouterr().err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# victim README\n"


@links
def test_s2_a_report_file_that_is_a_link_to_the_readme(tmp_path, capsys):
    def plant(repo, qa):
        (qa / "reports").mkdir()
        os.symlink("../../README.md", qa / "reports" / "x.md")
    repo, qa = _make(tmp_path, plant)
    assert _facts(repo, qa) == 2 and "reports/x.md" in capsys.readouterr().err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# victim README\n"


@links
def test_finalize_refuses_a_link_planted_after_the_facts(tmp_path, capsys):
    """`verdict-facts` saw a clean root; the link arrives before `verdict-finalize`.
    The run index is appended by name — through the link, onto the README."""
    repo, qa = _make(tmp_path)
    assert _facts(repo, qa) == 0
    (qa / "reports").mkdir(exist_ok=True)
    os.symlink("../../README.md", qa / "reports" / "INDEX.md")
    capsys.readouterr()
    assert _finalize(qa, JUDGMENT) == 1
    assert "holds a link" in capsys.readouterr().err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# victim README\n"
    assert not (qa / "state.json").exists(), "a refused finalize writes no state"


@links
@pytest.mark.parametrize("plant, judgment, lands", [
    # `reports` becomes a link to src/ and the harness names the report itself
    (lambda repo, qa: os.symlink("../src", qa / "reports"), {}, "src"),
    # the judgment names a report that is a dangling link to a file that is not there yet
    (lambda repo, qa: ((qa / "reports").mkdir(exist_ok=True),
                       os.symlink("../../NEW.md", qa / "reports" / "x.md")),
     {"report": "reports/x.md"}, "."),
])
def test_the_report_write_checks_the_name_it_opens(plant, judgment, lands, tmp_path,
                                                   monkeypatch, capsys):
    """The check at the top reads the root as it stood. This is the root changing
    between that check and the write — simulated by taking the first check away."""
    repo, qa = _make(tmp_path)
    assert _facts(repo, qa) == 0
    if (qa / "reports").is_dir() and not any((qa / "reports").iterdir()):
        (qa / "reports").rmdir()
    plant(repo, qa)
    before = sorted(os.listdir(repo / lands))
    monkeypatch.setattr(harness, "root_refusal", lambda *a, **k: None)
    capsys.readouterr()
    assert _finalize(qa, {**JUDGMENT, **judgment}) == 1
    assert "does not resolve to a plain file" in capsys.readouterr().err
    assert sorted(os.listdir(repo / lands)) == before, "the report was written through the link"


@links
def test_s3_a_reports_directory_that_points_into_the_source_tree(tmp_path):
    repo, qa = _make(tmp_path, lambda r, q: os.symlink("../src", q / "reports"))
    assert _facts(repo, qa) == 2
    assert sorted(os.listdir(repo / "src")) == ["app.py"]


@links
def test_s4_a_facts_file_that_is_a_link_to_the_code_under_test(tmp_path):
    repo, qa = _make(tmp_path, lambda r, q: os.symlink("../src/app.py", q / "facts.json"))
    assert _facts(repo, qa) == 2
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "a = 1\n"
    assert not (qa / "run-in-progress.json").exists(), "nothing is written before the check"


def test_s5_the_run_index_is_never_a_report(tmp_path, capsys):
    assert report_outside_reports("reports/INDEX.md")
    assert report_outside_reports("reports/index.md")
    repo, qa = _make(tmp_path)
    assert _facts(repo, qa) == 0 and _finalize(qa, JUDGMENT) == 0
    index = (qa / "reports" / "INDEX.md").read_text(encoding="utf-8")
    assert _facts(repo, qa) == 0
    assert _finalize(qa, {**JUDGMENT, "report": "reports/INDEX.md"}) == 1
    assert "run index" in capsys.readouterr().err
    assert (qa / "reports" / "INDEX.md").read_text(encoding="utf-8") == index


def test_a_second_name_for_a_file_is_a_link_too(tmp_path):
    repo, qa = _make(tmp_path)
    os.link(repo / "src" / "app.py", qa / "facts.json")
    found = planted_links(qa)
    assert found and found[0].startswith("facts.json (one of 2 names")
    assert _facts(repo, qa) == 2
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "a = 1\n"


@pytest.mark.skipif(os.name != "nt", reason="a junction is a Windows directory link")
def test_a_junction_is_a_link_on_windows(tmp_path):
    """The unprivileged way to link a directory there, and `is_symlink()` is False for it."""
    repo, qa = _make(tmp_path)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(qa / "reports"), str(repo / "src")],
                          capture_output=True, text=True)
    assert made.returncode == 0, made.stderr or made.stdout
    assert any(line.startswith("reports") for line in planted_links(qa)), planted_links(qa)
    assert _facts(repo, qa) == 2
    assert sorted(os.listdir(repo / "src")) == ["app.py"]


@links
def test_links_a_tester_parked_deeper_in_the_root_are_not_the_harnesss_business(tmp_path):
    """Two of the author's own solo roots carry a virtualenv and a pytest tmp tree."""
    repo, qa = _make(tmp_path)
    (qa / ".venv-qa" / "bin").mkdir(parents=True)
    os.symlink(sys.executable, qa / ".venv-qa" / "bin" / "python")
    (qa / "scratch" / "tmp").mkdir(parents=True)
    os.symlink("pytest-3", qa / "scratch" / "tmp" / "pytest-current")
    assert planted_links(qa) == [] and root_refusal(qa, "x") is None
    assert _facts(repo, qa) == 0 and _finalize(qa, JUDGMENT) == 0


def test_out_is_not_a_way_into_the_checkout(tmp_path, capsys):
    repo, qa = _make(tmp_path)
    assert _facts(repo, qa, "--out", str(repo / "README.md")) == 2
    assert "refusing --out" in capsys.readouterr().err
    assert (repo / "README.md").read_text(encoding="utf-8") == "# victim README\n"
    if os.name != "nt":
        (tmp_path / "elsewhere").mkdir()
        os.symlink(repo / "src" / "app.py", tmp_path / "elsewhere" / "alias.json")
        assert _facts(repo, qa, "--out", str(tmp_path / "elsewhere" / "alias.json")) == 2
        assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "a = 1\n"
    assert _facts(repo, qa, "--out", str(qa / "facts-copy.json")) == 0
    assert _facts(repo, qa, "--out", str(tmp_path / "elsewhere" / "facts.json")) == 0
    assert (tmp_path / "elsewhere" / "facts.json").is_file()


# ── and the root itself: `--qa-root` is the caller's word ────────────────────────────

def _src(repo):
    return sorted(p.name for p in (repo / "src").iterdir())


def test_a_root_among_the_code_is_refused_before_anything_is_created(tmp_path, capsys):
    """No link at all: `verdict-facts --qa-root src` wrote the facts, the marker and
    the test ids into `src/`, and `verdict-finalize --qa-root src` a state, a report
    and the run index — both commands the tester has to be able to run."""
    repo, qa = _make(tmp_path)
    assert facts_main(["--repo", str(repo), "--qa-root", str(repo / "src")]) == 2
    assert "outside its .qa/" in capsys.readouterr().err
    assert _src(repo) == ["app.py"]
    assert facts_main(["--repo", str(repo), "--qa-root", str(repo / "src" / "qa")]) == 2
    assert not (repo / "src" / "qa").exists(), "the root was created before it was refused"
    # finalize, pointed there with real facts and a judgment kept somewhere else
    assert _facts(repo, qa) == 0
    (tmp_path / "j.json").write_text(json.dumps(JUDGMENT), encoding="utf-8")
    capsys.readouterr()
    assert finalize_main(["--qa-root", str(repo / "src"), "--facts", str(qa / "facts.json"),
                          "--judgment", str(tmp_path / "j.json")]) == 1
    assert "outside its .qa/" in capsys.readouterr().err
    assert _src(repo) == ["app.py"]


def test_naming_the_code_a_solo_home_does_not_make_it_one(tmp_path, monkeypatch, capsys):
    """The solo home is an environment variable, and the tester types the command:
    `VERDICT_HOME=. verdict-facts --qa-root src`."""
    repo, qa = _make(tmp_path)
    monkeypatch.setenv("VERDICT_HOME", str(repo))
    assert facts_main(["--repo", str(repo), "--qa-root", str(repo / "src")]) == 2
    assert "inside the repository under test" in capsys.readouterr().err
    assert _src(repo) == ["app.py"]
    # finalize learns the repository from the facts
    monkeypatch.delenv("VERDICT_HOME")
    assert _facts(repo, qa) == 0
    monkeypatch.setenv("VERDICT_HOME", str(repo))
    (tmp_path / "j.json").write_text(json.dumps(JUDGMENT), encoding="utf-8")
    capsys.readouterr()
    assert finalize_main(["--qa-root", str(repo / "src"), "--facts", str(qa / "facts.json"),
                          "--judgment", str(tmp_path / "j.json")]) == 1
    assert "inside the repository under test" in capsys.readouterr().err
    assert _src(repo) == ["app.py"]
    # and the project's own .qa/ is still its root, whatever the variable says
    assert _finalize(qa, JUDGMENT) == 0


@links
def test_a_qa_directory_that_is_a_link_into_the_code(tmp_path, capsys):
    repo, qa = _make(tmp_path)
    shutil.rmtree(qa)
    os.symlink("src", repo / ".qa")
    assert facts_main(["--repo", str(repo)]) == 2            # the default team root
    assert "outside its .qa/" in capsys.readouterr().err
    assert _src(repo) == ["app.py"]


@links
def test_a_qa_link_that_leaves_the_checkout_is_the_callers_business(tmp_path):
    repo, qa = _make(tmp_path)
    outside = tmp_path / "state"
    shutil.move(str(qa), str(outside))
    os.symlink(outside, repo / ".qa")
    assert facts_main(["--repo", str(repo)]) == 0
    assert (outside / "facts.json").is_file()


def test_the_three_places_a_root_may_be(tmp_path, monkeypatch):
    repo, qa = _make(tmp_path)
    assert misplaced_root(qa) is None                         # the .qa at the top of a checkout
    assert misplaced_root(qa / "branch-run") is None          # … and below it
    assert misplaced_root(tmp_path / "elsewhere" / "qa") is None   # outside any checkout, not yet made
    monkeypatch.setenv("VERDICT_HOME", str(repo / "home"))
    assert misplaced_root(repo / "home" / "key") is None      # a solo home, wherever it is kept
    assert misplaced_root(repo / "src")
    assert misplaced_root(repo / "src" / ".qa"), "a `.qa` deeper in the tree is code"
    assert misplaced_root(repo), "the checkout itself"
    # a linked worktree is a checkout of its own: `.git` is a file there
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /somewhere/.git/worktrees/wt\n", encoding="utf-8")
    assert misplaced_root(worktree / ".qa") is None
    assert misplaced_root(worktree / "qa")


def test_the_local_tier_refuses_a_root_among_the_code(tmp_path, capsys):
    repo, sha_range = branch_repo(tmp_path)
    assert small.run(repo, repo / "pr.qa", _NoModel(), limit=4, gate=None, reruns=0,
                     prove=False, sha_range=sha_range) == 2
    assert "outside its .qa/" in capsys.readouterr().err
    assert not (repo / "pr.qa").exists()


CITE = "DECISIONS.md 2026-10-03 — the constant is the documented value"
WHY = "the README names one as the value; changing it would break every caller that reads it"
ASK = "Is one the documented value of `a`, or is the README's example the mistake here?"


@pytest.fixture()
def finalized(tmp_path):
    """A team-mode root one run old: one open finding, one question waiting."""
    repo, qa = _make(tmp_path)
    assert _facts(repo, qa) == 0
    fid = json.loads((qa / "facts.json").read_text(encoding="utf-8"))["next_finding_id"]
    finding = {"id": fid, "title": "a is one", "severity": "Major", "priority": "P1",
               "status": "open", "failure_classification": "REAL_DEFECT",
               "confidence": "proven", "evidence": ["src/app.py:1 — a = 1"]}
    assert _finalize(qa, {**JUDGMENT, "findings": [finding], "questions": [
        {"question": ASK, "finding": fid, "context": "src/app.py:1"}]}) == 0
    qid = next(iter(json.loads((qa / "questions.json").read_text(encoding="utf-8"))["questions"]))
    return repo, qa, fid, qid


def _pens(repo, fid, qid, gh):
    """Each of the maintainer's three writers, as the maintainer would run it."""
    return [
        ("accepted.json.tmp", lambda: accept.main(
            [str(repo), fid, "--cite", CITE, "--reason", WHY, "--by", "Art"])),
        ("answers.json.tmp", lambda: questions.main(
            [str(repo), qid, "--answer", "One is the documented value; the README is wrong.",
             "--by", "Art"])),
        ("issues.json.tmp", lambda: issues.main(
            [str(repo), "--create", "--gh-cmd", str(gh)])),
    ]


def _gh(tmp_path):
    called = tmp_path / "gh-was-called"
    gh = tmp_path / "gh"
    gh.write_text(f"#!/bin/sh\ntouch '{called}'\necho https://github.com/o/r/issues/1\n",
                  encoding="utf-8")
    gh.chmod(0o755)
    return gh, called


@links
@pytest.mark.parametrize("which", [0, 1, 2], ids=["verdict-accept", "verdict-answer",
                                                  "verdict-issues --create"])
def test_the_maintainers_writers_refuse_a_linked_root(which, finalized, tmp_path, capsys):
    """All three write `<ledger>.tmp` and rename it — by name, in the root."""
    repo, qa, fid, qid = finalized
    gh, called = _gh(tmp_path)
    name, write = _pens(repo, fid, qid, gh)[which]
    os.symlink("../src/app.py", qa / name)
    capsys.readouterr()
    assert write() == 2
    assert name in capsys.readouterr().err
    assert (repo / "src" / "app.py").read_text(encoding="utf-8") == "a = 1\n"
    assert not called.exists(), "an issue was filed from a root its ledger cannot be written in"


@pytest.mark.skipif(os.name == "nt", reason="the gh stub is a shell script")
def test_the_same_three_write_a_clean_root_and_reading_never_refuses(finalized, tmp_path):
    """The other half of the claim: the refusal is about the link, not the command."""
    repo, qa, fid, qid = finalized
    gh, called = _gh(tmp_path)
    # issues first: an accepted risk is not an issue to open
    for name, write in reversed(_pens(repo, fid, qid, gh)):
        assert write() == 0, name
        assert (qa / name[:-len(".tmp")]).is_file()
    assert called.exists()
    os.symlink("../src/app.py", qa / "stray")
    assert accept.main([str(repo), "--list"]) == 0
    assert questions.main([str(repo), "--list"]) == 0
    assert issues.main([str(repo)]) == 0, "the dry run reads"


@links
def test_the_local_tier_refuses_a_linked_root_before_it_measures(tmp_path, capsys):
    """`verdict-local` writes `facts.json` itself — S4 again, by the engine that runs
    unattended every night."""
    repo, sha_range = branch_repo(tmp_path)
    qa = throwaway_root(tmp_path)
    before = (repo / "mod.py").read_text(encoding="utf-8")
    os.symlink(repo / "mod.py", qa / "facts.json")
    assert small.run(repo, qa, _NoModel(), limit=4, gate=None, reruns=0, prove=False,
                     sha_range=sha_range) == 2
    assert "verdict-local: refusing" in capsys.readouterr().err
    assert (repo / "mod.py").read_text(encoding="utf-8") == before
