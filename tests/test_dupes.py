"""`verdict-dupes` (0.90.12): the tracker search a report should never skip.

Two of the nine 2026-10-16/17 stranger findings were already fixed by open PRs (fava #2381,
numpy-financial #158), found by hand. The command derives single-word queries from a finding,
asks `gh search issues --include-prs`, ranks what comes back, and the gate names the lead.
"""

import json
from pathlib import Path

from verdict_mcp import dupes
from verdict_mcp.gate import _fmt_comment, _fmt_text, evaluate

FAVA = {"id": "FAVA-F-1", "severity": "Major", "priority": "P1", "status": "open", "confidence": "proven",
        "first_seen": "2026-10-16", "age_days": 1, "delta": "NEW",
        "title": "Adding an entry rewrites digit-only string metadata as a number: `ref: \"00123\"` is written as `ref: 123`",
        "evidence": ["src/fava/serialisation.py:240 — `_DECIMAL_RE = re.compile(r\"-?\\d+\")`; "
                     "`if isinstance(o, str) and _DECIMAL_RE.fullmatch(o)`",
                     "frontend/src/entries/metadata.ts:42 — `string_to_meta_value` sends a plain string"]}

TRACKER = {
    "metadata": [{"number": 2381, "title": "serialisation: preserve numeric string metadata", "state": "open",
                  "isPullRequest": True, "url": "https://github.com/beancount/fava/pull/2381", "updatedAt": "2026-10-15T10:00:00Z"},
                 {"number": 2370, "title": "Filtering entries by metadata keys", "state": "open",
                  "isPullRequest": False, "url": "https://github.com/beancount/fava/issues/2370", "updatedAt": "2026-10-01T00:00:00Z"}],
    "rewrites": [],
    "serialisation": [{"number": 2381, "title": "serialisation: preserve numeric string metadata", "state": "open",
                       "isPullRequest": True, "url": "https://github.com/beancount/fava/pull/2381", "updatedAt": "2026-10-15T10:00:00Z"},
                      {"number": 2359, "title": "fix deserialisation of int lineno metadata", "state": "closed",
                       "isPullRequest": True, "url": "https://github.com/beancount/fava/pull/2359", "updatedAt": "2026-09-01T00:00:00Z"}],
}


def _root(tmp_path, findings, profile="Repo-Path: /nowhere\nRepo-Remote: https://github.com/beancount/fava.git\n"):
    root = tmp_path / "fava"
    root.mkdir(parents=True)
    (root / "profile.md").write_text(profile, encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "schema_version": 3, "project": "FAVA", "run_number": 1, "verdict": "pass with risks",
        "last_run": {"timestamp_utc": "2026-10-17T08:00:00Z", "git_sha": "x", "sha_range": "a..b"},
        "release_blockers": [], "not_tested": [], "findings": findings}), encoding="utf-8")
    return root


def _fake_search(calls):
    def search(remote, term):
        calls.append((remote, term))
        return TRACKER.get(term, []), ""
    return search


def _rows(root):
    return [json.loads(l) for l in (root / "related.jsonl").read_text(encoding="utf-8").splitlines()]


# ── terms ─────────────────────────────────────────────────────────────────

def test_terms_are_single_words_code_names_first_then_title_words_then_evidence():
    terms = dupes.terms_of(FAVA)
    assert terms[:1] == ["00123"] or terms[0] not in ("", None)
    assert "metadata" in terms and "rewrites" in terms
    assert "_DECIMAL_RE" in terms or "fullmatch" in terms, terms
    assert len(terms) <= dupes.MAX_TERMS
    assert all(" " not in t for t in terms)
    assert "digit-only" not in terms and "digit" not in terms, "hyphens split; short parts dropped"


def test_terms_skip_the_language_and_the_stopwords():
    f = {"title": "`return None` when the value is wrong — `self.save()` ignores `update_fields`",
         "evidence": ["src/payments/models.py:40 — `def save(self, *args)`"]}
    terms = dupes.terms_of(f)
    assert "return" not in terms and "None" not in terms and "self" not in terms and "save" not in [t.lower() for t in terms] or "update_fields" in terms
    assert "update_fields" in terms
    assert "models" in terms, terms


def test_remote_comes_from_the_profile_then_the_checkout(tmp_path):
    assert dupes.remote_of("Repo-Remote: https://github.com/numpy/numpy-financial.git\n", None) == "numpy/numpy-financial"
    assert dupes.remote_of("**Repo-Remote:** `git@github.com:beancount/fava.git`\n", None) == "beancount/fava"
    assert dupes.remote_of("Repo-Remote: https://github.com/django-oscar/django-oscar/\n", None) == "django-oscar/django-oscar"
    assert dupes.remote_of("", None) is None
    import subprocess
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/a/b.git"], check=True)
    assert dupes.remote_of("", repo) == "a/b"


# ── ranking ───────────────────────────────────────────────────────────────

def test_an_item_two_terms_returned_outranks_one_and_title_overlap_breaks_ties():
    ranked = dupes.rank(TRACKER, FAVA["title"])
    assert [i["number"] for i in ranked][:1] == [2381]
    assert ranked[0]["hits"] == ["metadata", "serialisation"] and ranked[0]["kind"] == "pr"
    assert ranked[0]["state"] == "open" and ranked[0]["score"] > ranked[1]["score"]
    # 2370 ("metadata keys") and 2359 ("int lineno metadata") each came from one term; the one
    # sharing more title words with the finding comes first
    rest = {i["number"]: i for i in ranked[1:]}
    assert set(rest) == {2370, 2359}
    assert dupes.rank({}, "x") == []


def test_a_shared_number_in_the_titles_outranks_generic_hits_and_evidence_terms_weigh_half():
    """numpy-financial F-13 (2026-10-17): four generic terms — `rate`, `inputs`, `begin`, `diff`,
    the last two from the evidence — put "pmt() function too slow" first, and the open PR that
    fixes the finding, "restrict rate results to values above -100%", fell out of the five."""
    title = "`rate` returns -1.0 or a rate below -100% for inputs that have no valid rate, instead of NaN"
    hits = {"rate": [{"number": 36, "title": "pmt() function too slow"},
                     {"number": 158, "title": "BUG: restrict rate results to values above -100%", "isPullRequest": True, "state": "OPEN"}],
            "inputs": [{"number": 36, "title": "pmt() function too slow"}],
            "begin": [{"number": 36, "title": "pmt() function too slow"}],
            "diff": [{"number": 36, "title": "pmt() function too slow"}]}
    weights = {"rate": 1.0, "inputs": 1.0, "begin": 0.5, "diff": 0.5}
    ranked = dupes.rank(hits, title, weights=weights)
    assert [i["number"] for i in ranked] == [158, 36]
    assert ranked[0]["symptoms"] == ["-100%"] and ranked[0]["score"] == 3.5 and ranked[1]["score"] == 3.0
    assert dupes._symptoms(title) == {"-1.0", "-100%", "nan"}
    assert dupes._symptoms("version 3.2.1 and 0") == {"3.2.1"}, "single digits and dotted versions: one token"
    w = dupes.term_weights(FAVA)
    assert w["metadata"] == 1.0 and all(v == 0.5 for k, v in w.items() if k in ("_DECIMAL_RE", "fullmatch", "serialisation"))


# ── the command ───────────────────────────────────────────────────────────

def test_the_command_searches_each_term_once_and_writes_the_ledger(tmp_path, capsys):
    root = _root(tmp_path, [FAVA])
    calls, sleeps = [], []
    rc = dupes.main([str(root)], _search=_fake_search(calls), _sleep=sleeps.append)
    assert rc == 0, capsys.readouterr().err
    assert len(calls) == len(dupes.terms_of(FAVA)) and all(r == "beancount/fava" for r, _ in calls)
    assert len(sleeps) == len(calls) - 1 and all(s == dupes.PAUSE_S for s in sleeps), "paced; the first is free"
    (row,) = _rows(root)
    assert row["id"] == "FAVA-F-1" and row["remote"] == "beancount/fava" and row["run_number"] == 1
    assert row["queries"] == [t for _, t in calls]
    assert row["items"][0]["number"] == 2381 and row["items"][0]["url"].endswith("/pull/2381")
    assert len(row["items"]) <= dupes.KEEP
    err = capsys.readouterr().err
    assert "FAVA-F-1 — #2381 open PR “serialisation: preserve numeric string metadata”" in err
    assert "1 of 1 finding(s) searched in beancount/fava · 1 with related items · 1 with an open PR" in err


def test_a_failed_search_stops_and_is_recorded_not_counted_as_searched(tmp_path, capsys):
    root = _root(tmp_path, [FAVA, dict(FAVA, id="FAVA-F-2", title="another thing about `metadata`")])
    def search(remote, term):
        return [], "GraphQL: API rate limit exceeded"
    rc = dupes.main([str(root)], _search=search, _sleep=lambda s: None)
    assert rc == 2
    rows = _rows(root)
    assert rows[0]["queries"] == [] and rows[0]["problem"] == "GraphQL: API rate limit exceeded"
    assert len(rows) == 1, "after a dead first search the rest is not attempted"
    assert "search stopped: GraphQL: API rate limit exceeded" in capsys.readouterr().err


def test_show_prints_terms_and_searches_nothing_and_minor_findings_are_not_searched(tmp_path, capsys):
    minor = dict(FAVA, id="FAVA-F-3", severity="Minor", priority="P3")
    root = _root(tmp_path, [FAVA, minor])
    calls = []
    assert dupes.main([str(root), "--show"], _search=_fake_search(calls)) == 0
    out = capsys.readouterr().out
    assert out.startswith("FAVA-F-1  ") and "metadata" in out and "FAVA-F-3" not in out
    assert calls == [] and not (root / "related.jsonl").exists()
    assert dupes.main([str(root), "FAVA-F-3"], _search=_fake_search(calls), _sleep=lambda s: None) == 0
    assert [r["id"] for r in _rows(root)] == ["FAVA-F-3"], "a named id is searched whatever its severity"


def test_no_remote_and_no_findings_are_exit_2(tmp_path, capsys):
    root = _root(tmp_path, [FAVA], profile="Repo-Path: /nowhere\n")
    assert dupes.main([str(root)], _search=_fake_search([])) == 2
    assert "no GitHub remote" in capsys.readouterr().err
    assert dupes.main([str(root), "--remote", "beancount/fava"], _search=_fake_search([]), _sleep=lambda s: None) == 0
    empty = _root(tmp_path / "e", [dict(FAVA, status="resolved")])
    assert dupes.main([str(empty)], _search=_fake_search([])) == 2


def test_without_gh_the_real_search_is_refused_plainly(tmp_path, capsys, monkeypatch):
    root = _root(tmp_path, [FAVA])
    monkeypatch.setattr(dupes.shutil, "which", lambda name: None)
    assert dupes.main([str(root)]) == 2
    assert "`gh` is not installed" in capsys.readouterr().err


# ── the gate reads the ledger ─────────────────────────────────────────────

def test_the_gate_names_each_searched_findings_lead_and_warns_on_an_open_pr(tmp_path):
    unsearched = dict(FAVA, id="FAVA-F-2", title="a second thing")
    root = _root(tmp_path, [FAVA, unsearched,
                            dict(FAVA, id="FAVA-F-4", title="nothing in the tracker", evidence=["x.py:1 — `quux`"])])
    dupes.main([str(root), "FAVA-F-1", "FAVA-F-4"], _search=_fake_search([]), _sleep=lambda s: None)
    r = evaluate(str(root), fail_on="fail", max_age_hours=None, min_run_number=None)
    assert r["tracker"] == {"searched": ["FAVA-F-1", "FAVA-F-4"], "leads": {"FAVA-F-1": "#2381 open PR"},
                            "open_prs": ["FAVA-F-1"]}
    by_id = {f["id"]: f for f in r["findings_open"]}
    assert by_id["FAVA-F-1"]["related"][0] == {"number": 2381, "title": "serialisation: preserve numeric string metadata",
                                               "state": "open", "kind": "pr",
                                               "url": "https://github.com/beancount/fava/pull/2381"}
    assert "related" not in by_id["FAVA-F-2"], "never searched"
    assert by_id["FAVA-F-4"]["related"] == [], "searched, nothing related"
    text = _fmt_text(r, 10)
    assert ("tracker: FAVA-F-1 ↔ #2381 open PR · FAVA-F-4: nothing related — 1 led by an OPEN PR: "
            "read it before reporting") in text
    assert "FAVA-F-1 Major/P1 Adding an entry rewrites" in text and "· tracker #2381 open PR" in text
    comment = _fmt_comment(r, 10)
    assert "**Tracker:** FAVA-F-1 ↔ #2381 open PR" in comment and "· tracker #2381 open PR |" in comment


def test_a_record_nobody_searched_shows_nothing(tmp_path):
    root = _root(tmp_path, [FAVA])
    r = evaluate(str(root), fail_on="fail", max_age_hours=None, min_run_number=None)
    assert "tracker" not in r and "related" not in r["findings_open"][0]
    assert "tracker" not in _fmt_text(r, 10) and "Tracker" not in _fmt_comment(r, 10)
    assert dupes.load_related(tmp_path / "missing") == {}
