"""A second run on the same day must not overwrite the first one's report.

Found by Verdict on itself: the 0.83.0 acceptance run (boltons run 3, a delta)
shared run 2's date and topic, `verdict-finalize` composed the same filename,
and run 2's report — the artifact of record — was gone. The agent noticed,
corrected the INDEX by hand and filed a lesson; the harness now keeps both.
"""

import json

from conftest import judgment
from verdict_mcp.harness import collect, finalize_main


def _judgment_without_a_report_path(**over):
    j = judgment(**over)
    j.pop("report")          # let finalize compose the filename from the topic
    return j


def _finalize(repo, qa_root, j):
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    jpath = qa_root / "judgment.json"
    jpath.write_text(json.dumps(j), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa_root), "--judgment", str(jpath)]) == 0
    return json.loads((qa_root / "state.json").read_text(encoding="utf-8"))["last_run"]["report"]


def test_a_second_run_on_the_same_day_keeps_the_first_runs_report(repo, qa_root):
    first = _finalize(repo, qa_root, _judgment_without_a_report_path(topic="delta"))
    first_text = (qa_root / first).read_text(encoding="utf-8")
    second = _finalize(repo, qa_root, _judgment_without_a_report_path(topic="delta"))
    assert first.endswith("-delta.md") and second.endswith("-delta-run2.md")
    assert (qa_root / first).read_text(encoding="utf-8") == first_text, "run 1's report survived"
    assert "run 2" in (qa_root / second).read_text(encoding="utf-8")
    third = _finalize(repo, qa_root, _judgment_without_a_report_path(topic="delta"))
    assert third.endswith("-delta-run3.md")


def test_a_retry_of_the_same_run_reuses_its_own_file(repo, qa_root):
    first = _finalize(repo, qa_root, _judgment_without_a_report_path(topic="delta"))
    # the state the second attempt will supersede is restored, as a retry does
    (qa_root / "state.json").unlink()
    again = _finalize(repo, qa_root, _judgment_without_a_report_path(topic="delta"))
    assert again == first and "run 1" in (qa_root / again).read_text(encoding="utf-8")
    written = sorted(p.name for p in (qa_root / "reports").glob("*.md") if p.name != "INDEX.md")
    assert written == sorted(["r.md", first.split("/")[-1]]), "no second file for the same run"
