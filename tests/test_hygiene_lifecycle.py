"""The hygiene lifecycle: tier 1 as harness-owned findings, tier 2 as a ledger.

Owned by the harness means measured every run and resolved only on evidence —
every file the item lives in was scanned this run, or is gone from the tree —
never by the tester's silence, never re-filed by a judgment."""

from verdict_mcp import hygiene
from verdict_mcp.hygiene import Evidence, is_hygiene, leads_followed, ledger, reconcile


def item(kind, fp, tier=1, path="a.py", line=1, **extra):
    return {"kind": kind, "tier": tier, "path": path, "line": line, "excerpt": "x",
            "why": "w", "fingerprint": fp, **extra}


def facts(*items, filing="on", status="measured"):
    return {"status": status, "filing": filing, "items": list(items),
            "scope": {"files": 1, "capped": False, "file_cap": 5000},
            "counts_by_kind": {}, "leads": [], "leads_total": 0}


def minter():
    n = [100]

    def mint():
        n[0] += 1
        return f"W-F-{n[0]}"
    return mint


def read(*paths, **more):
    """What a run's scan vouches for: these files were read."""
    return Evidence(scanned=paths, **more)


READ = read("a.py", "b.py", "c.py")


def by_fp(findings):
    return {f["hygiene"]["fingerprint"]: f["delta"] for f in findings}


def test_a_new_tier_one_item_is_a_new_finding_owned_by_the_harness():
    out = reconcile(facts(item("secret_in_code", "fp1")), [], minter(), "2026-10-01", 3, "abc12345")
    [f] = out
    assert is_hygiene(f) and f["delta"] == "NEW" and f["severity"] == "Critical"
    assert f["id"] == "W-F-101" and f["confidence"] == "proven" and f["hash"] == "hygiene:fp1"


def test_it_stays_open_under_its_id_and_resolves_when_its_file_is_read_without_it():
    first = reconcile(facts(item("secret_in_code", "fp1")), [], minter(), "2026-10-01", 3, "a")
    again = reconcile(facts(item("secret_in_code", "fp1")), first, minter(), "2026-10-05", 4, "b")
    assert again[0]["id"] == first[0]["id"] and again[0]["delta"] == "STILL_OPEN"
    assert again[0]["age_days"] == 4
    gone = reconcile(facts(), again, minter(), "2026-10-06", 5, "c0ffee99", evidence=READ)
    assert gone[0]["delta"] == "RESOLVED" and "no longer detected at c0ffee99" in gone[0]["carried_forward"]


def test_it_regresses_under_the_same_id():
    first = reconcile(facts(item("secret_in_code", "fp1")), [], minter(), "2026-10-01", 3, "a")
    gone = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=READ)
    back = reconcile(facts(item("secret_in_code", "fp1")), gone, minter(), "2026-10-03", 5, "c")
    assert back[0]["id"] == first[0]["id"] and back[0]["delta"] == "REGRESSED"
    assert back[0]["regressed_at_run"] == 5


def test_filing_off_files_nothing_and_resolves_what_was_open():
    first = reconcile(facts(item("secret_in_code", "fp1")), [], minter(), "2026-10-01", 3, "a")
    off = reconcile(facts(item("secret_in_code", "fp1"), filing="off"), first, minter(), "2026-10-02", 4, "b")
    assert [f["delta"] for f in off] == ["RESOLVED"] and "off in the profile" in off[0]["carried_forward"]


def test_an_unmeasured_scan_carries_open_items_whatever_else_it_knows():
    first = reconcile(facts(item("secret_in_code", "fp1")), [], minter(), "2026-10-01", 3, "a")
    carried = reconcile({"status": "unavailable"}, first, minter(), "2026-10-02", 4, "b", evidence=READ)
    assert [(f["delta"], f["status"]) for f in carried] == [("STILL_OPEN", "open")]
    assert "unavailable" in carried[0]["carried_forward"]


# ── resolved only on evidence ─────────────────────────────────────────────
# An open item this run did not see resolves when every file it lives in was
# scanned — or is gone from the tree the scan read. A file unread, cut by the
# cap or too large carries it, whatever the scan's status says.

def test_an_item_not_seen_resolves_only_where_its_file_was_read():
    first = reconcile(facts(item("secret_in_code", "fp1", path="a.py"), item("secret_in_code", "fp2", path="b.py"),
                            item("secret_in_code", "fp3", path="c.py")), [], minter(), "2026-10-01", 3, "a")
    part = facts(item("secret_in_code", "fp1", path="a.py"), item("secret_in_code", "fp4", path="d.py"),
                 status="partial")
    out = reconcile(part, first, minter(), "2026-10-02", 4, "b", evidence=read("a.py", "b.py", "d.py"))
    assert by_fp(out) == {"fp1": "STILL_OPEN", "fp2": "RESOLVED", "fp3": "STILL_OPEN", "fp4": "NEW"}
    [carried] = [f for f in out if f["hygiene"]["fingerprint"] == "fp3"]
    assert carried["status"] == "open" and "c.py was not read" in carried["carried_forward"]
    assert carried["id"] == first[2]["id"]
    # read at last, and the key is gone from it: now it resolves
    later = reconcile(facts(), out, minter(), "2026-10-03", 5, "c", evidence=read("a.py", "c.py"))
    assert by_fp(later)["fp3"] == "RESOLVED"


def test_a_ledger_row_not_seen_resolves_only_where_its_file_was_read():
    rows = [item("unused_import", "u1", 2, path="a.py"), item("broad_swallow", "s1", 2, path="b.py")]
    one = ledger(facts(), rows, None, "2026-10-01", 1, "a")
    two = ledger(facts(status="partial"), rows[:1], one, "2026-10-02", 2, "b", evidence=read("a.py"))
    [s1] = [r for r in two["rows"] if r["fingerprint"] == "s1"]
    assert (s1["status"], s1["delta"], s1["first_seen"]) == ("open", "STILL_OPEN", "2026-10-01")
    assert "b.py was not read" in s1["carried_forward"]
    assert two["summary"]["resolved"] == 0 and two["summary"]["carried"] == 1
    assert two["summary"]["partial"] is True
    assert two["summary"]["by_kind"]["broad_swallow"] == {"open": 1, "new": 0, "resolved": 0}, \
        "a carried row is an open row"
    three = ledger(facts(), rows[:1], two, "2026-10-03", 3, "c", evidence=read("a.py", "b.py"))
    assert three["summary"]["resolved"] == 1
    assert [r["delta"] for r in three["rows"] if r["fingerprint"] == "s1"] == ["RESOLVED"]


def test_the_ledger_tracks_new_still_open_and_removed_rows():
    one = ledger(facts(), [item("unused_import", "u1", 2), item("broad_swallow", "s1", 2)], None,
                 "2026-10-01", 1, "a")
    assert one["summary"]["first_inventory"] is True and one["summary"]["new"] == 2
    two = ledger(facts(), [item("unused_import", "u1", 2)], one, "2026-10-02", 2, "b", evidence=READ)
    assert two["summary"] == {"open": 1, "new": 0, "resolved": 1, "first_inventory": False, "capped": False,
                              "by_kind": {"broad_swallow": {"open": 0, "new": 0, "resolved": 1},
                                          "unused_import": {"open": 1, "new": 0, "resolved": 0}}}
    kept = [r for r in two["rows"] if r["status"] == "open"][0]
    assert kept["first_seen"] == "2026-10-01" and kept["delta"] == "STILL_OPEN"
    [gone] = [r for r in two["rows"] if r["status"] == "resolved"]
    assert (gone["resolved_on"], gone["resolved_at_run"], gone["resolved_sha"]) == ("2026-10-02", 2, "b")


def test_a_file_gone_from_the_tree_resolves_what_was_in_it():
    # The usual fix for a committed secrets file is deleting it, and a deleted file
    # is never scanned again: its absence from the tree is the evidence. Git is asked
    # only about files the scan did not read, and once per file.
    asked = []

    def absent(paths):
        asked.append(sorted(paths))
        return {"deploy/.env"} & set(paths)
    first = reconcile(facts(item("secret_file_tracked", "k1", path="deploy/.env"),
                            item("secret_in_code", "k2", path="kept.py"),
                            item("secret_in_code", "k3", path="read.py")), [], minter(), "2026-10-01", 3, "a")
    ev = read("read.py", absent=absent)
    out = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=ev)
    assert {f["hygiene"]["path"]: f["delta"] for f in out} == {
        "deploy/.env": "RESOLVED", "kept.py": "STILL_OPEN", "read.py": "RESOLVED"}
    assert asked == [["deploy/.env", "kept.py"]]
    one = ledger(facts(), [item("todo_comment", "t1", 2, path="deploy/.env")], None, "2026-10-01", 1, "a")
    two = ledger(facts(), [], one, "2026-10-02", 2, "b", evidence=ev)
    assert [r["delta"] for r in two["rows"]] == ["RESOLVED"] and len(asked) == 1, "asked once, remembered"


def test_a_file_the_parser_refused_carries_what_only_the_parser_finds():
    # bad.py was scanned — its lines were read — but the parser refused it, so the
    # checks that walk its syntax tree did not run: their silence proves nothing.
    ev = read("bad.py", parse_failed=["bad.py"])
    rows = [item("unused_import", "u1", 2, path="bad.py"), item("broad_swallow", "b1", 2, path="bad.py"),
            item("todo_comment", "t1", 2, path="bad.py"), item("commented_out_code", "c1", 2, path="bad.py"),
            item("oversized_file", "o1", 2, path="bad.py")]
    one = ledger(facts(), rows, None, "2026-10-01", 1, "a")
    two = ledger(facts(), [], one, "2026-10-02", 2, "b", evidence=ev)
    assert {r["fingerprint"]: r["delta"] for r in two["rows"]} == {
        "u1": "STILL_OPEN", "b1": "STILL_OPEN", "t1": "STILL_OPEN", "c1": "STILL_OPEN", "o1": "RESOLVED"}
    assert "did not parse" in [r for r in two["rows"] if r["fingerprint"] == "u1"][0]["carried_forward"]
    first = reconcile(facts(item("debugger_statement", "d1", path="bad.py"),
                            item("secret_in_code", "k1", path="bad.py")), [], minter(), "2026-10-01", 3, "a")
    out = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=ev)
    assert by_fp(out) == {"d1": "STILL_OPEN", "k1": "RESOLVED"}


def test_an_rls_switch_resolves_only_when_every_migration_was_read():
    # A table counts by its final state across every migration; with one unread,
    # the scan files no RLS item at all, and that silence is no fix.
    sql = item("open_database_rules", "r1", path="db/001_orders.sql", line=2)
    rules = item("open_database_rules", "r2", path="firestore.rules", line=4)
    first = reconcile(facts(sql, rules), [], minter(), "2026-10-01", 3, "a")
    scanned = ("db/001_orders.sql", "firestore.rules")
    unjudged = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=read(*scanned))
    assert by_fp(unjudged) == {"r1": "STILL_OPEN", "r2": "RESOLVED"}
    judged = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=read(*scanned, rls_judged=True))
    assert by_fp(judged) == {"r1": "RESOLVED", "r2": "RESOLVED"}


def test_a_client_secret_that_moves_to_another_file_stays_the_same_finding():
    at_a = item("public_env_secret", "p1", path="web/a.ts", variable="NEXT_PUBLIC_X_SECRET",
                sites=["web/a.ts"])
    at_b = item("public_env_secret", "p2", path="web/b.ts", line=7, variable="NEXT_PUBLIC_X_SECRET",
                sites=["web/b.ts"])
    first = reconcile(facts(at_a), [], minter(), "2026-10-01", 3, "a")
    moved = reconcile(facts(at_b), first, minter(), "2026-10-02", 4, "b", evidence=read("web/a.ts", "web/b.ts"))
    [f] = moved
    assert (f["id"], f["delta"], f["hash"]) == (first[0]["id"], "STILL_OPEN", first[0]["hash"])
    assert f["hygiene"]["path"] == "web/b.ts" and f["hygiene"]["fingerprint"] == "p2"
    assert f["hygiene"]["variable"] == "NEXT_PUBLIC_X_SECRET"


def test_a_client_secret_resolves_only_once_every_file_that_read_it_was_scanned():
    pub = item("public_env_secret", "p1", path="web/a.ts", variable="NEXT_PUBLIC_X_SECRET",
               sites=["ci/deploy.yml", "web/a.ts"])
    first = reconcile(facts(pub), [], minter(), "2026-10-01", 3, "a")
    part = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=read("web/a.ts"))
    assert [f["delta"] for f in part] == ["STILL_OPEN"] and "ci/deploy.yml" in part[0]["carried_forward"]
    whole = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=read("web/a.ts", "ci/deploy.yml"))
    assert [f["delta"] for f in whole] == ["RESOLVED"]


def test_a_copied_function_resolves_only_once_every_copy_was_scanned_or_is_gone():
    dup = item("duplicate_function", "f1", 2, path="a.py", sites=["a.py", "b.py", "c.py"])
    one = ledger(facts(), [dup], None, "2026-10-01", 1, "a")
    two = ledger(facts(), [], one, "2026-10-02", 2, "b", evidence=read("a.py", "b.py"))
    assert [r["delta"] for r in two["rows"]] == ["STILL_OPEN"]
    three = ledger(facts(), [], one, "2026-10-02", 2, "b",
                   evidence=read("a.py", "b.py", absent=lambda paths: {"c.py"} & set(paths)))
    assert [r["delta"] for r in three["rows"]] == ["RESOLVED"]


def test_a_side_file_that_could_not_be_read_resolves_no_row_and_says_so():
    one = ledger(facts(), [item("unused_import", "u1", 2)], None, "2026-10-01", 1, "a")
    block = dict(facts(), counts_by_kind={"secret_in_code": 1, "unused_import": 3})
    two = ledger(block, None, one, "2026-10-02", 2, "b", evidence=READ)
    assert [(r["fingerprint"], r["status"], r["delta"]) for r in two["rows"]] == [("u1", "open", "STILL_OPEN")]
    assert two["summary"]["tier2_unread"] is True
    assert (two["summary"]["new"], two["summary"]["resolved"]) == (0, 0)
    assert two["summary"]["by_kind"] == {"unused_import": {"open": 3, "new": 0, "resolved": 0}}, \
        "the counts are the scan's own, which facts.json still holds"


def test_an_unavailable_scan_keeps_the_ledger_rather_than_dropping_it():
    one = ledger(facts(), [item("unused_import", "u1", 2)], None, "2026-10-01", 1, "a")
    two = ledger({"status": "unavailable", "reason": "git could not run"}, None, one, "2026-10-02", 2, "b",
                 evidence=READ)
    assert two["status"] == "unavailable" and two["reason"] == "git could not run"
    assert [(r["fingerprint"], r["delta"]) for r in two["rows"]] == [("u1", "STILL_OPEN")]
    three = ledger(facts(), [item("unused_import", "u1", 2)], two, "2026-10-03", 3, "c", evidence=READ)
    assert three["summary"]["first_inventory"] is False
    assert (three["rows"][0]["delta"], three["rows"][0]["first_seen"]) == ("STILL_OPEN", "2026-10-01")
    assert ledger({}, [], None, "2026-10-01", 1, "a") == {
        "status": "unavailable",
        "reason": "facts.json carries no hygiene scan — measured by a verdict-facts older than 0.91.0"}


def test_past_the_cap_the_rows_with_a_history_are_kept_and_the_counts_stay_exact(monkeypatch):
    monkeypatch.setattr(hygiene, "LEDGER_CAP", 2)
    old = [item("unused_import", "u1", 2), item("unused_import", "u2", 2)]
    one = ledger(facts(), old, None, "2026-10-01", 1, "a")
    fresh = [item("todo_comment", f"t{n}", 2) for n in range(3)]
    two = ledger(facts(), fresh + old, one, "2026-10-02", 2, "b", evidence=READ)
    assert two["summary"]["capped"] is True
    assert (two["summary"]["open"], two["summary"]["new"]) == (5, 3)
    assert sorted(r["fingerprint"] for r in two["rows"]) == ["u1", "u2"]


def test_leads_followed_counts_findings_that_cite_a_leads_line():
    leads = [{"path": "auth.py", "line": 40}, {"path": "web.py", "line": 9}]
    found = [{"id": "W-F-1", "evidence": ["auth.py:42 the swallow"]}]
    assert leads_followed(leads, found) == 1


# ── merge(): the harness files tier 1, and the track record stays the tester's ─

import json  # noqa: E402

from conftest import git, judgment  # noqa: E402

from verdict_mcp.harness import collect, facts_main, finalize_main, merge, split_hygiene  # noqa: E402
from verdict_mcp.validate import validate  # noqa: E402

LIVE = "sk-ant-api03-" + "Qm9vY2FsbDEzW7tVx2Lp8Rz4Kf0HdN5sGj3aYcBwXeTqUiO"   # not a real key


def committed(repo, files: dict, message="change"):
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", message], repo)


def hygiene_findings(state):
    return [f for f in state["findings"] if f.get("source") == "hygiene"]


def test_merge_files_tier_one_carries_it_and_never_resolves_it_by_silence(repo, qa_root):
    committed(repo, {"k.py": f'K = "{LIVE}"\nimport os\n'}, "key")
    facts1 = collect(repo, qa_root, [])
    first = merge(facts1, judgment(), None)
    hyg = hygiene_findings(first)
    assert len(hyg) == 1 and hyg[0]["id"] == "W-F-2" and hyg[0]["delta"] == "NEW"
    assert first["hygiene"]["summary"]["open"] == 1          # the unused import
    assert not [p for p in validate(first, qa_root) if "W-F-2" in p]
    # the tester says nothing about it next run: still open, same id
    silent = judgment(findings=[])
    facts2 = dict(collect(repo, qa_root, []), run_number=2, run_type="delta")
    second = merge(facts2, silent, first)
    again = hygiene_findings(second)
    assert again[0]["id"] == "W-F-2" and again[0]["delta"] == "STILL_OPEN"
    # the key is removed: resolved by measurement
    committed(repo, {"k.py": "import os\n"}, "rotate")
    facts3 = dict(collect(repo, qa_root, []), run_number=3, run_type="delta")
    third = merge(facts3, silent, second)
    gone = hygiene_findings(third)
    assert gone[0]["delta"] == "RESOLVED"


def test_hygiene_findings_stay_out_of_the_testers_track_record(repo, qa_root):
    from verdict_mcp.state import calibration, merge_outcomes
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    state = merge(collect(repo, qa_root, []), judgment(), None)
    tester = [f for f in state["findings"] if f.get("source") != "hygiene"]
    assert hygiene_findings(state), "the scan filed the key"
    with_h = calibration({"findings": state["findings"]}, ledger=merge_outcomes({}, state["findings"], "2026-10-01"))
    without = calibration({"findings": tester}, ledger=merge_outcomes({}, tester, "2026-10-01"))
    assert with_h == without, "a regex's finding is not the tester's prediction"
    kept = merge_outcomes({}, state["findings"], "2026-10-01")
    assert any(r.get("source") == "hygiene" for r in kept.values()), \
        "the id stays in the outcome ledger so it is never minted twice"


def test_a_judgment_copy_of_a_hygiene_finding_is_ignored_not_duplicated(repo, qa_root):
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    first = merge(collect(repo, qa_root, []), judgment(), None)
    copy = [dict(f) for f in hygiene_findings(first)]
    j = judgment()
    j["findings"] += copy
    second = merge(dict(collect(repo, qa_root, []), run_number=2, run_type="delta"), j, first)
    assert len(hygiene_findings(second)) == 1


def test_a_deleted_file_resolves_its_finding_and_an_unread_one_carries_it(repo, qa_root, monkeypatch):
    from verdict_mcp import hygiene
    committed(repo, {"k.py": f'K = "{LIVE}"\n', "deploy/cfg.py": f'TOKEN = "{LIVE}"\n'}, "keys")
    first = merge(collect(repo, qa_root, []), judgment(), None)
    assert sorted(f["hygiene"]["path"] for f in hygiene_findings(first)) == ["deploy/cfg.py", "k.py"]
    committed(repo, {"k.py": None}, "delete the file")
    real = hygiene._scan_file

    def unread(rel, *args, **kwargs):
        if rel == "deploy/cfg.py":
            raise RuntimeError("a detector broke")
        return real(rel, *args, **kwargs)
    monkeypatch.setattr(hygiene, "_scan_file", unread)
    second = merge(dict(collect(repo, qa_root, []), run_number=2, run_type="delta"),
                   judgment(findings=[]), first)
    by_path = {f["hygiene"]["path"]: f for f in hygiene_findings(second)}
    assert by_path["k.py"]["delta"] == "RESOLVED", "gone from the tree the scan read"
    assert (by_path["deploy/cfg.py"]["delta"], by_path["deploy/cfg.py"]["status"]) == ("STILL_OPEN", "open")
    assert "deploy/cfg.py was not read" in by_path["deploy/cfg.py"]["carried_forward"]
    assert not validate(second, qa_root)


def test_the_ledger_is_read_from_the_side_file_and_an_unreadable_one_resolves_nothing(repo, qa_root):
    committed(repo, {"j.py": "import os\n"}, "junk")
    facts1 = collect(repo, qa_root, [])
    split_hygiene(facts1, qa_root)
    first = merge(facts1, judgment(), None, qa_root=qa_root)
    assert [(r["kind"], r["delta"]) for r in first["hygiene"]["rows"]] == [("unused_import", "NEW")]
    committed(repo, {"j.py": "x = 1\n"}, "tidy")
    facts2 = dict(collect(repo, qa_root, []), run_number=2, run_type="delta")
    split_hygiene(facts2, qa_root)
    (qa_root / "hygiene-items.json").write_text("{not json", encoding="utf-8")
    second = merge(facts2, judgment(findings=[]), first, qa_root=qa_root)
    assert second["hygiene"]["summary"]["tier2_unread"] is True
    assert [(r["kind"], r["delta"]) for r in second["hygiene"]["rows"]] == [("unused_import", "STILL_OPEN")]


def test_a_pass_is_capped_over_a_critical_the_scan_filed(repo, qa_root):
    # §10: a `pass` cannot stand over an open Critical. The tester may not have weighed
    # one the scan filed, and the local tier and the sweep weigh nothing — refusing the
    # run would lose every such night, so the harness caps its own and says why.
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    state = merge(collect(repo, qa_root, []), judgment(verdict="pass"), None)
    [key] = hygiene_findings(state)
    assert state["verdict"] == "pass with risks"
    assert state["hygiene"]["verdict_capped"] == {"from": "pass", "to": "pass with risks", "by": [key["id"]]}
    assert not validate(state, qa_root)
    clean = merge(collect(repo, qa_root, []), judgment(verdict="fail"), None)
    assert clean["verdict"] == "fail" and "verdict_capped" not in clean["hygiene"], "only a pass is capped"


def finalize_run(repo, qa, j: dict) -> dict:
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    (qa / "judgment.json").write_text(json.dumps(j), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return json.loads((qa / "state.json").read_text(encoding="utf-8"))


def test_still_open_naming_a_hygiene_finding_carries_nothing_twice(repo, tmp_path):
    # The local tier and the sweep name every open id in `still_open`; the copy that
    # verb expands to carries no `source`, and filed beside the harness's own it would
    # put one id in the state twice.
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    qa = tmp_path / "qa-root"
    (qa / "reports").mkdir(parents=True)
    first = finalize_run(repo, qa, judgment(findings=[], report=""))
    [key] = hygiene_findings(first)
    second = finalize_run(repo, qa, judgment(findings=[], report="", still_open=[key["id"]]))
    assert [f["id"] for f in second["findings"]] == [key["id"]]
    assert hygiene_findings(second)[0]["delta"] == "STILL_OPEN"


def test_the_local_tier_finalizes_a_night_the_scan_files_a_critical_on(tmp_path):
    from test_hygiene import make_repo
    from test_hygiene_facts import root_with
    from test_local_delta import GATE, ScriptedModel
    from verdict_mcp import small
    repo = make_repo(tmp_path, {
        "mod.py": f'KEY = "{LIVE}"\n\n\ndef kept(x):\n    return x + 1\n',
        "test_mod.py": "from mod import kept\n\n\ndef test_kept():\n    assert kept(1) == 2\n"})
    qa = root_with(tmp_path, f"gates:\n  suite: {GATE}\n")
    assert small.run(repo, qa, ScriptedModel(), limit=4, gate=None, reruns=0, prove=False) == 0
    state = json.loads((qa / "state.json").read_text(encoding="utf-8"))
    assert [f["hygiene"]["kind"] for f in hygiene_findings(state)] == ["secret_in_code"]
    assert state["verdict"] == "pass with risks"


# ── exemptions: the drift a sweep reads, and the sweep itself ─────────────
# A hygiene finding is re-measured by the scan on every run, sweeps included. The
# code it cites moving says nothing a model must read, so neither the drift the
# next run is handed nor the free sweep's blockers count it.

def test_a_file_only_hygiene_cites_does_not_block_the_free_sweep():
    from datetime import date

    from verdict_mcp.runner import sweep_blockers
    previous = {"findings": [{"id": "W-F-9", "status": "open", "source": "hygiene",
                              "anchors": [{"path": "web/app.js", "line": 3}]}]}
    facts_ = {"evidence_drift": {"status": "measured", "summary": {}},
              "gates": {"suite": {"result": "pass", "counts": {"passed": 1}}},
              "test_ids": {"status": "measured"}}
    why = sweep_blockers(facts_, previous, ["web/app.js"], date(2026, 10, 1))
    assert not any("cites" in w for w in why)
    tester = {"findings": [dict(previous["findings"][0], source=None)]}
    assert any("cites" in w for w in sweep_blockers(facts_, tester, ["web/app.js"], date(2026, 10, 1))), \
        "the tester's own finding on the same file still blocks it"


def test_evidence_drift_leaves_the_harnesss_own_findings_out(repo, qa_root):
    from verdict_mcp.anchors import anchors_for
    anchors = anchors_for(repo, ["a.py:1 the assignment"])
    cited = {"status": "open", "severity": "Minor", "priority": "P3", "anchors": anchors,
             "evidence": ["a.py:1 the assignment"]}
    previous = {"project": "widget", "run_number": 1, "verdict": "pass with risks",
                "findings": [{**cited, "id": "W-F-1", "title": "the tester's"},
                             {**cited, "id": "W-F-2", "title": "the scan's", "source": "hygiene",
                              "hygiene": {"kind": "debugger_statement", "fingerprint": "d1",
                                          "path": "a.py"}}]}
    (qa_root / "state.json").write_text(json.dumps(previous), encoding="utf-8")
    committed(repo, {"a.py": "x = 2\n"}, "move the cited line")
    drift = collect(repo, qa_root, [])["evidence_drift"]
    assert drift["summary"]["drifted_findings"] == ["W-F-1"]
    assert "W-F-2" not in drift["findings"]


# ── the validator: a judgment never files, nor edits, a hygiene finding ───

def test_a_judgment_may_not_file_a_hygiene_finding():
    from verdict_mcp.validate import validate_judgment
    j = judgment()
    j["findings"][0]["source"] = "hygiene"
    problems = validate_judgment(j)
    assert any("filed by verdict-finalize" in p for p in problems)
    marked = judgment()
    marked["findings"][0]["hygiene"] = {"kind": "secret_in_code", "fingerprint": "fp1"}
    assert any("filed by verdict-finalize" in p for p in validate_judgment(marked))
    assert not validate_judgment(judgment()), "the tester's own finding is untouched"


def test_a_judgment_may_not_file_its_own_finding_under_a_hygiene_id(repo, qa_root):
    # Filed beside the harness's finding it would put one id in the state twice, and
    # the state would be refused in the vocabulary of a structure the tester never wrote.
    from verdict_mcp.validate import validate_judgment
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    previous = merge(collect(repo, qa_root, []), judgment(), None)
    [key] = hygiene_findings(previous)
    j = judgment()
    j["findings"][0]["id"] = key["id"]
    problems = validate_judgment(j, previous)
    assert any(key["id"] in p and "hygiene finding" in p for p in problems), problems
    assert not validate_judgment(judgment(), previous)


# ── an id the outcome ledger holds is never minted again ──────────────────
# A hygiene finding resolves by measurement and leaves the state a run later, far
# more often than the tester's; its id then lives on only in outcomes.json, and the
# next finding must not take it. load_outcomes() hands over the rows themselves.

def test_an_id_only_the_outcome_ledger_holds_is_never_minted_again(repo, qa_root):
    from verdict_mcp.state import load_outcomes
    (qa_root / "outcomes.json").write_text(json.dumps({"schema_version": 1, "findings": {
        "hygiene:0badc0de": {"hash": "hygiene:0badc0de", "id": "W-F-9", "source": "hygiene"}}}),
        encoding="utf-8")
    (qa_root / "state.json").write_text(json.dumps({"project": "widget", "run_number": 1,
                                                    "findings": [{"id": "W-F-1", "status": "open"}]}),
                                        encoding="utf-8")
    assert collect(repo, qa_root, [])["next_finding_id"] == "W-F-10"
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    state = merge(collect(repo, qa_root, []), judgment(), None, ledger=load_outcomes(qa_root))
    assert [f["id"] for f in hygiene_findings(state)] == ["W-F-10"]


# ── an RLS switch is judged on every migration, never on one that went away ─
# While a migration goes unread, no table's final state is known; deleting the one
# that disabled RLS is no evidence about it either — a squash replaces old
# migrations with a baseline that may say anything.

def test_a_deleted_migration_resolves_no_rls_finding_while_rls_is_unjudged():
    rls = item("open_database_rules", "r1", path="supabase/migrations/001_orders.sql", line=2)
    first = reconcile(facts(rls), [], minter(), "2026-10-01", 3, "a")
    gone = Evidence(scanned=[], rls_judged=False, absent=lambda paths: set(paths))
    unjudged = reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=gone)
    assert [(f["delta"], f["status"]) for f in unjudged] == [("STILL_OPEN", "open")]
    assert "row-level-security" in unjudged[0]["carried_forward"]
    judged = Evidence(scanned=[], rls_judged=True, absent=lambda paths: set(paths))
    assert [f["delta"] for f in reconcile(facts(), first, minter(), "2026-10-02", 4, "b", evidence=judged)] \
        == ["RESOLVED"], "with every migration read, a deleted one is gone like any file"


def test_a_squash_onto_a_baseline_too_large_to_read_keeps_the_rls_finding_open(repo, qa_root, monkeypatch):
    from verdict_mcp import hygiene
    committed(repo, {"db/migrations/001_orders.sql": ("create table orders(id int);\n"
                                                      "alter table orders disable row level security;\n")},
              "orders, RLS off")
    first = merge(collect(repo, qa_root, []), judgment(), None)
    [rls] = [f for f in hygiene_findings(first) if f["hygiene"]["kind"] == "open_database_rules"]
    monkeypatch.setattr(hygiene, "MAX_BYTES", 400)
    baseline = ("".join(f"create table t{i}(id int);\n" for i in range(40))
                + "alter table orders enable row level security;\n")
    committed(repo, {"db/migrations/001_orders.sql": None, "db/schema.sql": baseline}, "squash")
    second = merge(dict(collect(repo, qa_root, []), run_number=2, run_type="delta"),
                   judgment(findings=[]), first)
    [again] = [f for f in hygiene_findings(second) if f["id"] == rls["id"]]
    assert (again["delta"], again["status"]) == ("STILL_OPEN", "open")


# ── the validator's refusal invites no copy ───────────────────────────────

def test_the_refusal_says_whose_the_finding_is_and_invites_no_copy(repo, qa_root):
    from verdict_mcp.validate import validate_judgment
    marked = judgment()
    marked["findings"][0]["source"] = "hygiene"
    [said] = [p for p in validate_judgment(marked) if "hygiene" in p]
    assert "W-F-1" in said and "belongs to the harness" in said
    assert "not be copied or re-filed" in said and "your own finding" not in said
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    previous = merge(collect(repo, qa_root, []), judgment(), None)
    [key] = hygiene_findings(previous)
    reused = judgment()
    reused["findings"][0]["id"] = key["id"]
    [said] = [p for p in validate_judgment(reused, previous) if "hygiene" in p]
    assert f"the hygiene finding {key['id']}" in said and "belongs to the harness" in said
    assert "not be copied or re-filed" in said and "mint" not in said


# ── the report: a Hygiene section, the cap said, the scan's findings measured ─
# Rendered from the state's preview, never from the rows: once finalize has moved
# them to hygiene-ledger.json the state holds none, and the report reads the state.

def test_the_report_renders_the_hygiene_section_after_accepted_risks(repo, qa_root):
    from verdict_mcp.harness import render_report
    (repo / "b.py").write_text("import os\n# TODO: x\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "junk"], repo)
    state = merge(collect(repo, qa_root, []), judgment(), None)
    text = render_report(state, None)
    assert "## Hygiene" in text
    section = text.split("## Hygiene", 1)[1]
    assert "first inventory" in section and "| unused import | 1 |" in section
    assert text.index("## Findings") < text.index("## Hygiene") < text.index("## Release blockers")


def preview_row(fp, path, line, kind, excerpt, first_seen, delta):
    return {"fingerprint": fp, "kind": kind, "path": path, "line": line, "excerpt": excerpt,
            "first_seen": first_seen, "delta": delta}


OLD_ROW = preview_row("o1", "old/a.py", 3, "todo_comment", "# TODO: the first one", "2026-09-01", "STILL_OPEN")
NEW_ROW = preview_row("n1", "web/new.py", 7, "unused_import", "import sys", "2026-10-01", "NEW")


def on_disk(**state) -> dict:
    """A state as finalize leaves it on disk: the ledger's counts, its preview and the
    name of the file holding its rows — and no rows."""
    hygiene = {"status": "measured", "measured_at_run": 3,
               "scope": {"files": 40, "capped": False, "file_cap": 5000, "failed": 0},
               "summary": {"open": 2, "new": 1, "resolved": 1, "first_inventory": False, "capped": False,
                           "by_kind": {"todo_comment": {"open": 1, "new": 0, "resolved": 1},
                                       "unused_import": {"open": 1, "new": 1, "resolved": 0}}},
               "preview": {"oldest": [OLD_ROW, NEW_ROW], "new": [NEW_ROW]},
               "rows_file": "hygiene-ledger.json", "leads": {"handed": 4, "followed": 1}}
    return {"project": "widget", "run_number": 3, "run_type": "delta", "verdict": "pass with risks",
            "last_run": {"timestamp_utc": "2026-10-01T00:00:00Z"}, "findings": [],
            "not_tested": ["concurrency"], "hygiene": hygiene, **state}


def hygiene_section(text: str) -> str:
    return text.split("## Hygiene", 1)[1].split("\n## ", 1)[0]


def test_the_section_lists_the_preview_the_state_keeps_not_the_rows_it_moved_out():
    from verdict_mcp.harness import render_report
    accepted = {"id": "W-F-7", "title": "declined", "severity": "Minor", "priority": "P3",
                "status": "accepted", "delta": "ACCEPTED",
                "accepted": {"by": "owner", "on": "2026-09-20", "citation": "DECISIONS.md", "reason": "cosmetic"}}
    text = render_report(on_disk(findings=[accepted]))
    assert text.index("## Accepted risks") < text.index("## Hygiene") < text.index("## Release blockers")
    section = hygiene_section(text)
    assert section.startswith("\n\n2 open · 1 new · 1 removed since the last run · 40 files scanned\n")
    assert "| todo comment | 1 | 0 | 1 |" in section and "| unused import | 1 | 1 | 0 |" in section
    oldest, new = section.split("**Oldest open:**", 1)[1].split("**New this run:**", 1)
    assert "- `old/a.py:3` todo comment — # TODO: the first one (since 2026-09-01)" in oldest
    assert "- `web/new.py:7` unused import — import sys" in new
    assert "Leads handed to the tester: 4; 1 of them cited by a finding within five lines." in section
    for quiet in ("Partial scan", "Carried open", "hygiene-items.json", "Not measured"):
        assert quiet not in section, quiet
    assert "Near-certain exposures" not in section, "none is filed above, so none is pointed to"


def test_a_first_inventory_lists_its_rows_once():
    from verdict_mcp.harness import render_report
    state = on_disk()
    state["hygiene"]["summary"].update(open=1, new=1, resolved=0, first_inventory=True)
    state["hygiene"]["preview"] = {"oldest": [NEW_ROW], "new": [NEW_ROW]}
    section = hygiene_section(render_report(state))
    assert "first inventory: everything is new because nothing was tracked before" in section
    assert section.count("`web/new.py:7`") == 1 and "**New this run:**" not in section


# The flags, each on a block the real ledger() built: a hand-built summary can hold
# counts no run produces, and a renderer checked against one proves nothing.
JUNK = [item("unused_import", "u1", 2, path="a.py"), item("broad_swallow", "s1", 2, path="b.py")]


def first_run():
    return ledger(facts(), JUNK, None, "2026-10-01", 1, "a")


def test_a_partial_scan_says_what_it_could_not_read_and_still_counts_what_it_did():
    from verdict_mcp.harness import render_report
    partial = dict(facts(status="partial"),
                   scope={"files": 1, "capped": False, "file_cap": 5000, "failed": 1, "failed_paths": ["b.py"]})
    block = ledger(partial, JUNK[:1], first_run(), "2026-10-02", 2, "b", evidence=read("a.py"))
    assert block["summary"]["partial"] is True and block["summary"]["carried"] == 1
    section = hygiene_section(render_report(on_disk(hygiene=block)))
    assert section.startswith("\n\n2 open · 0 new · 0 removed since the last run · 1 files scanned\n")
    assert ("- Partial scan: 1 file(s) could not be read, so nothing in them was marked removed: `b.py`"
            in section)
    assert ("- Carried open, not removed: 1 row(s) this run did not see — nothing this run read proves "
            "them gone") in section


def test_new_and_removed_are_not_measured_when_this_runs_rows_could_not_be_read():
    from verdict_mcp.gate import _hygiene_line
    from verdict_mcp.harness import render_report
    from verdict_mcp.state import history_row
    counted = dict(facts(), counts_by_kind={"unused_import": 1, "broad_swallow": 1})
    block = ledger(counted, None, first_run(), "2026-10-02", 2, "b")
    s = block["summary"]
    assert s["tier2_unread"] is True and (s["open"], s["new"], s["resolved"], s["carried"]) == (2, 0, 0, 2)
    state = on_disk(hygiene=block)
    section = hygiene_section(render_report(state))
    assert section.startswith("\n\n2 open · new and removed not measured this run · 1 files scanned\n")
    assert "| broad swallow | 1 | — | — |" in section and "| unused import | 1 | — | — |" in section
    assert ("- This run's junk list could not be read from `hygiene-items.json`: which rows are new or "
            "removed is not known, and the open count is the scan's own") in section
    assert [ln for ln in section.splitlines() if ln.startswith("- Carried open")] == [
        "- Carried open, not removed: 2 row(s) from the last run — this run could not read its junk list, "
        "so none is known to be gone"]
    assert "did not see" not in section
    assert _hygiene_line({"hygiene": s}) == ("2 open (new and removed not measured this run) · "
                                             "broad swallow 1 · unused import 1")
    assert history_row(state)["hygiene"] == {"open": 2, "new": None, "resolved": None}


def test_new_and_removed_are_not_measured_when_last_runs_rows_could_not_be_read():
    from verdict_mcp.gate import _hygiene_line
    from verdict_mcp.harness import render_report
    from verdict_mcp.state import history_row
    block = ledger(facts(), JUNK, {"status": "measured", "rows_file": "hygiene-ledger.json"},
                   "2026-10-03", 3, "c")
    s = block["summary"]
    assert s["prior_unread"] is True and (s["open"], s["new"], s["resolved"]) == (2, 2, 0)
    state = on_disk(hygiene=block)
    text = render_report(state)
    section = hygiene_section(text)
    assert section.startswith("\n\n2 open · new and removed not measured this run · 1 files scanned\n")
    assert "| broad swallow | 1 | — | — |" in section and "**New this run:**" not in section
    assert text.count("last run's hygiene rows could not be read") == 1, "said once, under the scope"
    assert _hygiene_line({"hygiene": s}) == ("2 open (new and removed not measured this run) · "
                                             "broad swallow 1 · unused import 1")
    assert history_row(state)["hygiene"] == {"open": 2, "new": None, "resolved": None}


def test_an_unmeasured_scan_says_so_and_what_it_carried():
    from verdict_mcp.harness import render_report
    state = on_disk()
    state["hygiene"] = {
        "status": "unavailable", "reason": "git cannot show a commit",
        "summary": {"open": 1, "new": 0, "resolved": 0, "first_inventory": False, "capped": False,
                    "by_kind": {"todo_comment": {"open": 1, "new": 0, "resolved": 0}}, "carried": 1},
        "preview": {"oldest": [OLD_ROW], "new": []}, "carried_from_run": 2}
    section = hygiene_section(render_report(state))
    assert "Not measured this run — git cannot show a commit" in section
    assert "- Carried open, not removed: 1 row(s) from the last run" in section
    del state["hygiene"]
    assert "## Hygiene" not in render_report(state), "a state from before the scan says nothing of it"


def test_a_capped_verdict_is_said_under_the_verdict(repo, qa_root):
    from verdict_mcp.harness import render_report
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    state = merge(collect(repo, qa_root, []), judgment(verdict="pass"), None)
    [key] = hygiene_findings(state)
    lines = render_report(state).splitlines()
    under = lines[lines.index("**VERDICT: pass with risks**") + 2]
    assert under.startswith(
        f"_Verdict capped from `pass` to `pass with risks` by the hygiene scan: {key['id']}"), under
    clean = merge(collect(repo, qa_root, []), judgment(verdict="fail"), None)
    assert "Verdict capped" not in render_report(clean)


def test_a_hygiene_finding_is_measured_by_the_scan_not_by_a_test(repo, qa_root):
    from verdict_mcp.harness import render_report
    committed(repo, {"k.py": f'K = "{LIVE}"\n'}, "key")
    state = merge(collect(repo, qa_root, []), judgment(), None)
    [key] = hygiene_findings(state)
    text = render_report(state)
    scans = text.split(f"### {key['id']} ", 1)[1].split("\n#", 1)[0]
    assert "- Measured by the hygiene scan; resolves when the scan stops seeing it" in scans
    assert "Never measured" not in scans
    testers = text.split("### W-F-1 ", 1)[1].split("\n#", 1)[0]
    assert "- Never measured — no `verification_test` declared" in testers, "the tester's own, unchanged"
    assert "Near-certain exposures are filed above as findings" in hygiene_section(text)


# ── the run history: hygiene counts per run, unsigned like gate durations ──

def test_history_rows_carry_unsigned_hygiene_counts():
    from verdict_mcp.state import chain_link, history_row
    state = {"run_number": 2, "verdict": "pass", "findings": [],
             "last_run": {"timestamp_utc": "2026-10-01T00:00:00Z"},
             "hygiene": {"status": "measured", "summary": {"open": 5, "new": 1, "resolved": 2}}}
    row = history_row(state)
    assert row["hygiene"] == {"open": 5, "new": 1, "resolved": 2}
    bare = dict(row)
    del bare["hygiene"]
    assert chain_link("x", row) == chain_link("x", bare), "telemetry stays out of the signed body"
    assert "hygiene" not in history_row({**state, "hygiene": {"status": "unavailable", "reason": "r"}})


def test_a_chain_signed_before_the_counts_still_verifies(repo, tmp_path):
    # A run finalized before this release signed a row with no hygiene counts while its
    # state already held the ledger. Re-derived today, that row carries the counts; were
    # they signed, every such state would read as tampered and fail --require-harness.
    from verdict_mcp.state import harness_signals, load_chain_anchor, load_runs, verify_chain
    committed(repo, {"j.py": "import os\n"}, "junk")
    qa = tmp_path / "qa-root"
    (qa / "reports").mkdir(parents=True)
    state = finalize_run(repo, qa, judgment(findings=[], report=""))
    rows, _ = load_runs(qa)
    assert rows[-1]["hygiene"] == {"open": 1, "new": 1, "resolved": 0}
    signed_before = [{k: v for k, v in r.items() if k != "hygiene"} for r in rows]
    (qa / "runs.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in signed_before),
                                   encoding="utf-8")
    assert verify_chain(load_runs(qa)[0], load_chain_anchor(qa))["status"] == "intact"
    assert harness_signals(state, qa)["chain_intact"] is True
