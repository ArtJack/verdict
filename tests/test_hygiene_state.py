"""The hygiene block a state carries, and what a run says about it.

The tester reads state.json first on every run, and the junk ledger's rows are for
no decision it makes: on Sales they were 119 rows and 51 KB. So the rows live in
`hygiene-ledger.json`, written beside the state once the state is accepted, and the
state keeps the counts and a preview — the ten oldest open rows and ten new ones.
The next run reads the rows back from that file; when it cannot, it carries nothing
forward and says so, rather than resolving what it never compared.

A hygiene id a judgment names in `still_open` or `resolved` is the scan's to
settle: ignored, and recorded where a reader sees it."""

import json
import subprocess

from conftest import judgment

from verdict_mcp import harness
from verdict_mcp.hygiene import ledger

from test_hygiene import make_repo  # noqa: E402

LIVE = "sk-ant-api03-" + "Qm9vY2FsbDEzW7tVx2Lp8Rz4Kf0HdN5sGj3aYcBwXeTqUiO"   # not a real key
PREVIEW_FIELDS = {"fingerprint", "kind", "path", "line", "excerpt", "first_seen", "delta"}


def commit(repo, files: dict, message="change"):
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "add", "-A"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), "commit",
                    "-qm", message], check=True, capture_output=True)


def run(repo, qa, **judged) -> dict:
    """verdict-facts, then verdict-finalize over a judgment that files nothing."""
    assert harness.facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    (qa / "judgment.json").write_text(json.dumps(judgment(findings=[], report="", **judged)),
                                      encoding="utf-8")
    assert harness.finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return json.loads((qa / "state.json").read_text(encoding="utf-8"))


def ledger_file(qa) -> dict:
    return json.loads((qa / "hygiene-ledger.json").read_text(encoding="utf-8"))


def report(qa, state) -> str:
    return (qa / state["last_run"]["report"]).read_text(encoding="utf-8")


# ── the rows leave the state for their own file ───────────────────────────

def test_the_rows_leave_the_state_and_come_back_from_their_file_next_run(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "import os\n# TODO: one\n"})
    qa = tmp_path / "qa"
    first = run(repo, qa)
    block = first["hygiene"]
    assert "rows" not in block and block["rows_file"] == "hygiene-ledger.json"
    assert {"status", "scope", "summary", "measured_at_run", "leads", "rows_file", "preview"} <= set(block)
    doc = ledger_file(qa)
    assert doc["schema"] == 1 and doc["run_number"] == 1
    assert sorted((r["kind"], r["delta"]) for r in doc["rows"]) == [("todo_comment", "NEW"),
                                                                    ("unused_import", "NEW")]
    commit(repo, {"a.py": "import os\n"}, "the TODO is done")
    second = run(repo, qa)
    rows = {r["kind"]: r for r in ledger_file(qa)["rows"]}
    assert (rows["unused_import"]["delta"], rows["unused_import"]["first_seen_run"]) == ("STILL_OPEN", 1)
    assert rows["todo_comment"]["delta"] == "RESOLVED"
    assert second["hygiene"]["summary"]["resolved"] == 1 and "prior_unread" not in second["hygiene"]["summary"]


def test_at_sales_scale_only_the_preview_stays_in_the_state(tmp_path):
    repo = make_repo(tmp_path, {"junk.py": "".join(f"# TODO: item {n}\n" for n in range(119))})
    qa = tmp_path / "qa"
    state = run(repo, qa)
    block = state["hygiene"]
    assert block["summary"]["open"] == 119 and len(ledger_file(qa)["rows"]) == 119
    assert len(block["preview"]["oldest"]) == 10 and len(block["preview"]["new"]) == 10
    assert all(set(r) == PREVIEW_FIELDS for r in block["preview"]["oldest"] + block["preview"]["new"])
    text = (qa / "state.json").read_text(encoding="utf-8")
    assert "item 118" not in text, "a row past the preview is in the ledger file, not the state"
    assert len(json.dumps(block)) < 8_000


def test_the_preview_shows_the_ten_oldest_open_rows_and_ten_new_ones():
    def row(fp, first_seen, path):
        return {"fingerprint": fp, "kind": "todo_comment", "path": path, "line": 1, "excerpt": "# TODO",
                "status": "open", "delta": "NEW", "first_seen": first_seen, "first_seen_run": 1}

    def item(fp, path):
        return {"kind": "todo_comment", "tier": 2, "path": path, "line": 1, "excerpt": "# TODO", "why": "w",
                "fingerprint": fp}
    # twelve rows from earlier runs, dated out of path order, and thirteen new ones
    dates = ["2026-09-07", "2026-09-03", "2026-09-11", "2026-09-01", "2026-09-09", "2026-09-05",
             "2026-09-12", "2026-09-02", "2026-09-10", "2026-09-04", "2026-09-08", "2026-09-06"]
    old = [row(f"o{n:02d}", day, f"old/{n:02d}.py") for n, day in enumerate(dates)]
    previous = {"status": "measured", "measured_at_run": 4, "rows": old}
    tier2 = [item(r["fingerprint"], r["path"]) for r in old] + [item(f"n{n:02d}", f"new/{n:02d}.py")
                                                              for n in reversed(range(13))]
    block = ledger({"status": "measured"}, tier2, previous, "2026-10-01", 5, "abc")
    oldest, new = block["preview"]["oldest"], block["preview"]["new"]
    assert [r["first_seen"] for r in oldest] == sorted(dates)[:10]
    assert [r["path"] for r in new] == [f"new/{n:02d}.py" for n in range(10)]
    assert {r["delta"] for r in new} == {"NEW"} and {r["delta"] for r in oldest} == {"STILL_OPEN"}
    assert all(set(r) == PREVIEW_FIELDS for r in oldest + new)


# ── a prior ledger that cannot be read is carried nowhere ─────────────────

def test_a_missing_prior_file_carries_nothing_resolves_nothing_and_says_so(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "import os\n# TODO: one\n"})
    qa = tmp_path / "qa"
    run(repo, qa)
    (qa / "hygiene-ledger.json").unlink()
    commit(repo, {"a.py": "import os\n"}, "the TODO is done")
    second = run(repo, qa)
    summary = second["hygiene"]["summary"]
    assert summary["prior_unread"] is True and summary["first_inventory"] is False
    assert (summary["resolved"], summary["new"], summary["open"]) == (0, 1, 1)
    assert [(r["kind"], r["delta"], r["first_seen_run"]) for r in ledger_file(qa)["rows"]] == [
        ("unused_import", "NEW", 2)]
    assert "last run's hygiene rows could not be read" in report(qa, second)


def test_a_rows_file_another_run_wrote_is_not_this_states(tmp_path):
    # Restoring state.json from state.json.prev is how a bad run is retried; the rows
    # file on disk is then a later run's, and comparing against it would resolve rows
    # this state never had.
    repo = make_repo(tmp_path, {"a.py": "import os\n# TODO: one\n"})
    qa = tmp_path / "qa"
    run(repo, qa)
    commit(repo, {"b.py": "import sys\n"}, "more junk")
    run(repo, qa)
    (qa / "state.json").write_text((qa / "state.json.prev").read_text(encoding="utf-8"), encoding="utf-8")
    again = run(repo, qa)
    assert again["run_number"] == 2 and again["hygiene"]["summary"]["prior_unread"] is True


def test_the_ledger_flags_a_named_file_it_was_not_given_rows_from():
    item = {"kind": "todo_comment", "tier": 2, "path": "a.py", "line": 1, "excerpt": "# TODO", "why": "w",
            "fingerprint": "t1"}
    block = ledger({"status": "measured"}, [item], {"status": "measured", "rows_file": "hygiene-ledger.json"},
                   "2026-10-01", 2, "abc")
    assert block["summary"]["prior_unread"] is True
    assert [(r["fingerprint"], r["delta"]) for r in block["rows"]] == [("t1", "NEW")]


def test_a_ledger_file_that_cannot_be_written_keeps_the_rows_in_the_state(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "import os\n"})
    qa = tmp_path / "qa"
    (qa / "hygiene-ledger.json").mkdir(parents=True)
    first = run(repo, qa)
    block = first["hygiene"]
    assert "rows_file" not in block and [r["kind"] for r in block["rows"]] == ["unused_import"]
    assert block["rows_note"].startswith("hygiene-ledger.json could not be written")
    second = run(repo, qa)
    assert [r["delta"] for r in second["hygiene"]["rows"]] == ["STILL_OPEN"], "read back inline"


# ── a hygiene id a judgment names is ignored, where a reader sees it ──────

def test_a_hygiene_id_named_by_either_verb_is_ignored_and_recorded(tmp_path):
    repo = make_repo(tmp_path, {"k.py": f'K = "{LIVE}"\n'})
    qa = tmp_path / "qa"
    first = run(repo, qa)
    [key] = [f["id"] for f in first["findings"] if f.get("source") == "hygiene"]
    carried = run(repo, qa, still_open=[key])
    assert carried["hygiene"]["ignored_judgment_ids"] == [key]
    assert f"{key} — the scan's own" in report(qa, carried)
    resolved = run(repo, qa, resolved=[key])
    assert resolved["hygiene"]["ignored_judgment_ids"] == [key]
    [f] = [f for f in resolved["findings"] if f["id"] == key]
    assert (f["status"], f["delta"]) == ("open", "STILL_OPEN"), "the tester's word resolves nothing"
    quiet = run(repo, qa)
    assert "ignored_judgment_ids" not in quiet["hygiene"]
