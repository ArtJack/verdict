"""One hygiene finding per identity, for as long as the record lasts.

A resolved finding stays in state.json one run, and its id lives on in the outcome
ledger. So a key that comes back two runs after its fix, after `hygiene: off` for a
while, or after a restored state.json.prev, is the same finding — REGRESSED under
its own id, keeping whatever the maintainer accepted under that id — never a new
one. Two open findings with one identity are folded into one, and a key that turns
into a file-level finding says so rather than calling itself gone."""

import json

from verdict_mcp.hygiene import Evidence, reconcile

from test_hygiene import make_repo, unseen  # noqa: E402
from test_hygiene_state import commit, run  # noqa: E402

STRIPE_LIVE = unseen("dH6cN3bY7tR4mW9xK2pLv8qZ_evil_ks")      # a fake key, stored reversed (see test_hygiene.unseen)


def hygiene(state):
    return [(f["id"], f["status"], f.get("delta")) for f in state["findings"] if f.get("source") == "hygiene"]


def outcome_rows(qa) -> dict:
    return json.loads((qa / "outcomes.json").read_text(encoding="utf-8"))["findings"]


def profile(qa, setting):
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "profile.md").write_text(f"---\nhygiene: {setting}\n---\n# p\n", encoding="utf-8")


# ── a key back after its fix is the same finding, however long it was gone ─

def test_a_key_back_two_runs_after_its_fix_regresses_under_its_own_id(tmp_path):
    repo = make_repo(tmp_path, {"app/config.py": f'KEY = "{STRIPE_LIVE}"\n', "app/main.py": "x = 1\n"})
    qa = tmp_path / "qa"
    s1 = run(repo, qa)
    [(fid, _status, delta)] = hygiene(s1)
    assert delta == "NEW"
    [row] = [r for r in outcome_rows(qa).values() if r.get("id") == fid]
    [f1] = [f for f in s1["findings"] if f["id"] == fid]
    assert row["hygiene_identity"] == "fingerprint:" + f1["hygiene"]["fingerprint"]
    commit(repo, {"app/config.py": "KEY = None\n"}, "rotate")
    assert hygiene(run(repo, qa)) == [(fid, "resolved", "RESOLVED")]
    commit(repo, {"app/main.py": "x = 2\n"}, "unrelated")
    assert hygiene(run(repo, qa)) == [], "a resolution stays one run"
    commit(repo, {"app/config.py": f'KEY = "{STRIPE_LIVE}"\n'}, "the key is back")
    s4 = run(repo, qa)
    assert hygiene(s4) == [(fid, "open", "REGRESSED")]
    [f4] = [f for f in s4["findings"] if f["id"] == fid]
    assert f4["regressed_at_run"] == 4 and f4["first_seen"] == f1["first_seen"]
    assert f4["hash"] == f1["hash"]
    assert len([r for r in outcome_rows(qa).values() if r.get("source") == "hygiene"]) == 1


def test_a_key_still_there_when_filing_comes_back_on_is_the_same_finding(tmp_path):
    repo = make_repo(tmp_path, {"app/config.py": f'KEY = "{STRIPE_LIVE}"\n'})
    qa = tmp_path / "qa"
    [(fid, _status, _delta)] = hygiene(run(repo, qa))
    profile(qa, "off")
    s2 = run(repo, qa)
    assert hygiene(s2) == [(fid, "resolved", "RESOLVED")]
    assert hygiene(run(repo, qa)) == []
    assert hygiene(run(repo, qa)) == [], "off for as long as it likes"
    profile(qa, "on")
    s5 = run(repo, qa)
    assert hygiene(s5) == [(fid, "open", "REGRESSED")]


def test_a_regression_keeps_the_acceptance_recorded_under_its_id(tmp_path):
    repo = make_repo(tmp_path, {"app/config.py": f'KEY = "{STRIPE_LIVE}"\n', "app/main.py": "x = 1\n"})
    qa = tmp_path / "qa"
    [(fid, _status, _delta)] = hygiene(run(repo, qa))
    (qa / "accepted.json").write_text(json.dumps({"accepted": {fid: {
        "by": "owner", "on": "2026-09-27", "citation": "DECISIONS.md 2026-09-27",
        "reason": "a sandbox key"}}}), encoding="utf-8")
    commit(repo, {"app/config.py": "KEY = None\n"}, "rotate")
    run(repo, qa)
    commit(repo, {"app/main.py": "x = 2\n"}, "unrelated")
    run(repo, qa)
    commit(repo, {"app/config.py": f'KEY = "{STRIPE_LIVE}"\n'}, "the key is back")
    s4 = run(repo, qa)
    [f] = [f for f in s4["findings"] if f.get("source") == "hygiene"]
    assert (f["id"], f["status"], f["delta"]) == (fid, "accepted", "ACCEPTED")
    assert f["accepted"]["citation"] == "DECISIONS.md 2026-09-27"


# ── one identity, one open finding ────────────────────────────────────────

def minter():
    n = [100]

    def mint():
        n[0] += 1
        return f"W-F-{n[0]}"
    return mint


def facts(*items):
    return {"status": "measured", "filing": "on", "items": list(items)}


def item(kind, fp, path, **extra):
    return {"kind": kind, "tier": 1, "path": path, "line": 1, "excerpt": "x", "why": "w",
            "fingerprint": fp, **extra}


def secret(fid, fp, path, first_seen):
    return {"id": fid, "source": "hygiene", "status": "open", "severity": "Critical", "priority": "P1",
            "first_seen": first_seen, "hash": "hygiene:" + fp,
            "hygiene": {"kind": "public_env_secret", "fingerprint": fp, "path": path,
                        "variable": "NEXT_PUBLIC_X_SECRET", "sites": [path]}}


def test_two_open_findings_with_one_identity_are_folded_and_neither_vanishes():
    # Two findings for one client variable, from before its identity was the name:
    # the older keeps the variable, the other is resolved as superseded by it.
    priors = [secret("W-F-7", "fpb", "web/b.ts", "2026-09-10"), secret("W-F-3", "fpa", "web/a.ts", "2026-09-01")]
    seen = item("public_env_secret", "fpb", "web/b.ts", variable="NEXT_PUBLIC_X_SECRET", sites=["web/b.ts"])
    out = reconcile(facts(seen), priors, minter(), "2026-10-01", 9, "abc",
                    evidence=Evidence(scanned=["web/a.ts", "web/b.ts"]))
    assert sorted((f["id"], f["delta"]) for f in out) == [("W-F-3", "STILL_OPEN"), ("W-F-7", "RESOLVED")]
    [gone] = [f for f in out if f["id"] == "W-F-7"]
    assert gone["carried_forward"] == "superseded by W-F-3" and gone["status"] == "resolved"
    unmeasured = reconcile({"status": "unavailable"}, priors, minter(), "2026-10-01", 9, "abc")
    assert sorted((f["id"], f["delta"]) for f in unmeasured) == [("W-F-3", "STILL_OPEN"), ("W-F-7", "RESOLVED")]


def test_a_key_that_becomes_a_file_level_finding_says_so():
    first = reconcile(facts(item("secret_in_code", "k1", "keys/deploy.pem")), [], minter(), "2026-10-01", 1, "a")
    second = reconcile(facts(item("secret_file_tracked", "t1", "keys/deploy.pem")), first, minter(),
                       "2026-10-02", 2, "b", evidence=Evidence(scanned=["keys/deploy.pem"]))
    by_kind = {f["hygiene"]["kind"]: f for f in second}
    assert by_kind["secret_file_tracked"]["delta"] == "NEW"
    assert by_kind["secret_in_code"]["delta"] == "RESOLVED"
    assert by_kind["secret_in_code"]["carried_forward"] == (
        f"superseded by the file-level finding {by_kind['secret_file_tracked']['id']}")
