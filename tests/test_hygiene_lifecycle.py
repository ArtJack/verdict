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
